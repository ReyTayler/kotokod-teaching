"""
PaymentsRepository — единственное место доступа к данным раздела payments.

ORM-порт services/repo/payments.js (раздел 09).

Критичный паритет:
  • unit_price / total_amount — сырые Decimal → renderer выдаёт строки (как Express).
  • purchased/attended/balance/total_paid/new_balance — числа (int|float) через
    _js_number() (живёт в apps/finances).
  • Транзакция + FOR UPDATE в create_payment (select_for_update).
  • payments immutable: только create/delete, никакого UPDATE.
  • unit_price округляется до копеек ДО умножения (round_kopecks).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import F, Sum, Value
from django.db.models.functions import Coalesce, Now

from apps.core.utils.decimal import round_kopecks
from apps.core.utils.orm import dictrow, dictrows

from .models import Payment


# Поля строки оплаты (p.* / RETURNING *), в порядке схемы.
_PAYMENT_FIELDS = (
    'id', 'student_id', 'direction_id', 'subscriptions_count', 'lessons_count', 'kind', 'unit_price',
    'total_amount', 'paid_at', 'note', 'created_at', 'created_by',
)

# _js_number и расчёт баланса живут в едином доме apps/finances.
# Переэкспортируем для обратной совместимости (delete_payment, тесты).
from apps.finances.repository import _js_number  # noqa: E402,F401


def _normalize_lessons_count(row: dict) -> dict:
    """
    lessons_count теперь DecimalField (Task 4.0: дробные возвраты, -3.5 и т.п.),
    но в JSON-ответе должен остаться JS Number (int для целых покупок), как раньше
    при IntegerField — иначе DateSafeJSONRenderer превратит его в строку '2.0',
    как unit_price/total_amount, что ломает контракт API.
    """
    if row.get('lessons_count') is not None:
        row['lessons_count'] = _js_number(row['lessons_count'])
    return row


# ---------------------------------------------------------------------------
# Repository functions (ORM-порт services/repo/payments.js)
# ---------------------------------------------------------------------------

def create_payment(data: dict) -> dict:
    """
    Создаёт оплату внутри транзакции с SELECT FOR UPDATE.

    Возвращает {'payment': row} или {'error': ...} — НЕ кидает исключение.
    Порядок (инвариант): лок direction → подсчёт already под локом → проверка cap → INSERT.
    """
    from apps.directions.models import Direction

    student_id = data['student_id']
    direction_id = data['direction_id']
    lessons_count = data['lessons_count']
    total_amount = data['total_amount']
    paid_at = data['paid_at']
    note = data.get('note')
    created_by = data.get('created_by')

    with transaction.atomic():
        dir_row = (
            Direction.objects.select_for_update()
            .filter(id=direction_id)
            .values('id', 'total_lessons')
            .first()
        )
        if dir_row is None:
            return {'error': 'direction_not_found'}
        if not dir_row['total_lessons'] or dir_row['total_lessons'] <= 0:
            return {'error': 'no_capacity'}

        # cap в уроках: считаем только покупки этого направления
        already = (
            Payment.objects
            .filter(student_id=student_id, direction_id=direction_id, kind='purchase')
            .aggregate(s=Coalesce(Sum('lessons_count'), Value(Decimal('0'))))['s']
        )
        if already + lessons_count > dir_row['total_lessons']:
            return {
                'error': 'cap_exceeded',
                'already': _js_number(already),
                'cap_subscriptions': int(dir_row['total_lessons'] // 4),
            }

        total = round_kopecks(total_amount)
        unit_price = round_kopecks(total / Decimal(lessons_count))
        subs = lessons_count // 4 if lessons_count % 4 == 0 else None

        obj = Payment.objects.create(
            student_id=student_id,
            direction_id=direction_id,
            subscriptions_count=subs,
            lessons_count=lessons_count,
            kind='purchase',
            unit_price=unit_price,
            total_amount=total,
            paid_at=paid_at,
            note=note or None,
            created_by=created_by or None,
            created_at=Now(),
        )
        row = _normalize_lessons_count(dictrow(Payment.objects.filter(pk=obj.pk).values()))

    return {'payment': row}


def list_payments(
    student_id: Optional[int] = None,
    direction_id: Optional[int] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
) -> list[dict]:
    """
    Список оплат с опциональными фильтрами.

    JOIN students (inner) + LEFT JOIN directions (nullable). ORDER paid_at DESC, id DESC.
    """
    qs = Payment.objects.all()
    if student_id is not None:
        qs = qs.filter(student_id=student_id)
    if direction_id is not None:
        qs = qs.filter(direction_id=direction_id)
    if from_ is not None:
        qs = qs.filter(paid_at__gte=from_)
    if to is not None:
        qs = qs.filter(paid_at__lte=to)

    rows = dictrows(
        qs.order_by('-paid_at', '-id').values(
            *_PAYMENT_FIELDS,
            student_name=F('student__full_name'),
            direction_name=F('direction__name'),
        )
    )
    return [_normalize_lessons_count(r) for r in rows]


def get_payment(payment_id: int) -> Optional[dict]:
    """Возвращает одну оплату или None."""
    row = dictrow(Payment.objects.filter(id=payment_id).values())
    return _normalize_lessons_count(row) if row is not None else None


def delete_payment(payment_id: int) -> dict:
    """
    Хард-удаляет оплату и пересчитывает общий баланс ученика (единый пул).

    Возвращает {'deleted': False} или {'deleted': True, student_id, direction_id, new_balance}.
    """
    row = (
        Payment.objects.filter(id=payment_id)
        .values('student_id', 'direction_id')
        .first()
    )
    if row is None:
        return {'deleted': False}

    Payment.objects.filter(id=payment_id).delete()

    student_id = row['student_id']
    direction_id = row['direction_id']
    balance = _balance_for_student(student_id)
    return {
        'deleted': True,
        'student_id': student_id,
        'direction_id': direction_id,
        'new_balance': balance,
    }


def _balance_for_student(student_id: int) -> int | float:
    """Общий баланс ученика (единый пул). Делегирует в единый дом apps/finances."""
    from apps.finances.repository import balance_for_student
    return balance_for_student(student_id)


def get_student_balance(student_id: int) -> dict:
    """Баланс ученика по всем направлениям. Делегирует в apps/finances."""
    from apps.finances.balance import get_student_balance as _impl
    return _impl(student_id)


def get_direction_payments_count(direction_id: int) -> int:
    """Количество оплат для направления."""
    return Payment.objects.filter(direction_id=direction_id).count()


def refund_student(student_id: int, created_by: str | None = None) -> dict:
    """
    Оформляет возврат неотработанного остатка ученика (единый пул).

    Возвращает {'error': 'student_not_found'|'nothing_to_refund'} или
    {'refund': row, 'new_balance': <=0, 'refunded_amount': Decimal}.
    Строка возврата: kind='refund', lessons_count/total_amount отрицательные,
    direction_id=NULL (пул-возврат). Иммутабельна как все payments.
    """
    from apps.finances.repository import student_fifo_remaining, balance_for_student
    from apps.students.models import Student

    with transaction.atomic():
        if not Student.objects.select_for_update().filter(id=student_id).exists():
            return {'error': 'student_not_found'}

        rem = student_fifo_remaining(student_id)
        remaining_lessons = rem['remaining_lessons']
        remaining_value = rem['remaining_value']
        if remaining_lessons <= 0 or remaining_value <= 0:
            return {'error': 'nothing_to_refund'}

        obj = Payment.objects.create(
            student_id=student_id,
            direction_id=None,
            subscriptions_count=None,
            lessons_count=-Decimal(str(remaining_lessons)),
            kind='refund',
            unit_price=Decimal('0'),
            total_amount=-remaining_value,
            paid_at=Now(),
            note=f'Возврат {remaining_lessons} уроков на сумму {remaining_value} ₽',
            created_by=created_by or None,
            created_at=Now(),
        )
        row = _normalize_lessons_count(dictrow(Payment.objects.filter(pk=obj.pk).values()))
        new_balance = balance_for_student(student_id)

    return {'refund': row, 'new_balance': new_balance, 'refunded_amount': remaining_value}
