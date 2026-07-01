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

from typing import Optional

from django.db import transaction
from django.db.models import F, Sum, Value
from django.db.models.functions import Coalesce, Now

from apps.core.utils.decimal import round_kopecks
from apps.core.utils.orm import dictrow, dictrows

from .models import Payment


# Поля строки оплаты (p.* / RETURNING *), в порядке схемы.
_PAYMENT_FIELDS = (
    'id', 'student_id', 'direction_id', 'subscriptions_count', 'unit_price',
    'total_amount', 'paid_at', 'note', 'created_at', 'created_by',
)

# _js_number и расчёт баланса живут в едином доме apps/finances.
# Переэкспортируем для обратной совместимости (delete_payment, тесты).
from apps.finances.repository import _js_number  # noqa: E402,F401


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
    subscriptions_count = data['subscriptions_count']
    unit_price = data['unit_price']
    paid_at = data['paid_at']
    note = data.get('note')
    created_by = data.get('created_by')

    with transaction.atomic():
        # 1. Лок direction'а, читаем total_lessons.
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

        # 2. Под локом считаем уже-куплено и сверяем с cap.
        already = (
            Payment.objects
            .filter(student_id=student_id, direction_id=direction_id)
            .aggregate(s=Coalesce(Sum('subscriptions_count'), Value(0)))['s']
        )
        cap_subs = int(dir_row['total_lessons'] // 4)
        if already + subscriptions_count > cap_subs:
            return {
                'error': 'cap_exceeded',
                'already': already,
                'cap_subscriptions': cap_subs,
            }

        # 3. INSERT — unit_price округляем до копеек ДО умножения.
        price = round_kopecks(unit_price)
        total = price * subscriptions_count  # Decimal * int — точно

        obj = Payment.objects.create(
            student_id=student_id,
            direction_id=direction_id,
            subscriptions_count=subscriptions_count,
            unit_price=price,
            total_amount=total,
            paid_at=paid_at,
            note=note or None,
            created_by=created_by or None,
            created_at=Now(),
        )
        row = dictrow(Payment.objects.filter(pk=obj.pk).values())

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

    return dictrows(
        qs.order_by('-paid_at', '-id').values(
            *_PAYMENT_FIELDS,
            student_name=F('student__full_name'),
            direction_name=F('direction__name'),
        )
    )


def get_payment(payment_id: int) -> Optional[dict]:
    """Возвращает одну оплату или None."""
    return dictrow(Payment.objects.filter(id=payment_id).values())


def delete_payment(payment_id: int) -> dict:
    """
    Хард-удаляет оплату и пересчитывает баланс по направлению.

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
    balance = _balance_for_direction(student_id, direction_id)
    return {
        'deleted': True,
        'student_id': student_id,
        'direction_id': direction_id,
        'new_balance': balance,
    }


def _balance_for_direction(student_id: int, direction_id: int) -> int | float:
    """Баланс по одному направлению. Делегирует в единый дом apps/finances."""
    from apps.finances.repository import balance_for_direction
    return balance_for_direction(student_id, direction_id)


def get_student_balance(student_id: int) -> dict:
    """Баланс ученика по всем направлениям. Делегирует в apps/finances."""
    from apps.finances.balance import get_student_balance as _impl
    return _impl(student_id)


def get_direction_payments_count(direction_id: int) -> int:
    """Количество оплат для направления."""
    return Payment.objects.filter(direction_id=direction_id).count()
