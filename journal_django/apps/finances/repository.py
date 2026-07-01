"""
FinancesRepository — единственное место доступа к данным вычислительного слоя финансов.

ORM-порт (раздел 09):
  • fifo_inputs()            ← _fifoInputs() (dashboard.js)
  • balance_for_direction()  ← _balance_for_direction (payments.js)
  • student_balance_rows()   ← getStudentBalance WITH-запрос (payments.js)
  • total_paid_amount()      ← getStudentBalance итоговая сумма (payments.js)

CTE getStudentBalance переразбит на отдельные агрегирующие запросы + сборка по
direction_id в Python (паттерн 4.8) — баланс выводится, не хранится.

Числа баланса (purchased/attended/balance) отдаются через _js_number (int/float,
как Number(x) в JS). Сырые поля оплат (unit_price/total_amount) — Decimal, в строку
их приводит DateSafeJSONRenderer. fifo.py (чистый Python) не трогаем.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.db.models import Case, DecimalField, F, Sum, Value, When
from django.db.models.functions import Coalesce

from apps.core.utils.decimal import to_decimal

from apps.directions.models import Direction
from apps.lessons.models import LessonAttendance
from apps.payments.models import Payment


_DEC = DecimalField(max_digits=20, decimal_places=2)
_ZERO = Value(Decimal('0'), output_field=_DEC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _js_number(d) -> int | float:
    """JS Number(x): целое → int, дробное → float. Decimal('8.0')→8, Decimal('7.5')→7.5."""
    f = float(d)
    return int(f) if f == int(f) else f


def _date_str(value) -> str:
    """lesson_date (date) → 'YYYY-MM-DD' (Node отдаёт строку через type-parser)."""
    if isinstance(value, datetime.date):
        return value.strftime('%Y-%m-%d')
    return str(value)[:10]


def _attended_units_case():
    """half-lesson: SUM(CASE WHEN duration=45 THEN 0.5 ELSE 1) как Decimal-выражение."""
    return Case(
        When(lesson__lesson_duration_minutes=45, then=Value(Decimal('0.5'))),
        default=Value(Decimal('1')),
        output_field=_DEC,
    )


# ---------------------------------------------------------------------------
# FIFO-входы (порт _fifoInputs из dashboard.js)
# ---------------------------------------------------------------------------

def fifo_inputs() -> dict:
    """
    Загружает FIFO-входы по ключу 'student_id:direction_id'.

    Возвращает lots_by_key / purchased_by_key / cons_by_key / consumed_by_key / keys.
    Guard: оплаты с subscriptions_count NULL/0 (lessons ≤ 0) пропускаются —
    иначе деление на 0 / Infinity ломает суммы.
    """
    lots_rows = (
        Payment.objects
        .filter(direction_id__isnull=False)
        .order_by('student_id', 'direction_id', 'paid_at', 'id')
        .values('student_id', 'direction_id', 'total_amount', 'subscriptions_count')
    )

    cons_rows = (
        LessonAttendance.objects
        .filter(present=True)
        .annotate(units=_attended_units_case())
        .order_by('student_id', 'lesson__group__direction_id', 'lesson__lesson_date', 'lesson_id')
        .values(
            'student_id', 'units',
            direction_id=F('lesson__group__direction_id'),
            lesson_date=F('lesson__lesson_date'),
        )
    )

    lots_by_key: dict[str, list] = {}
    purchased_by_key: dict[str, int] = {}
    for r in lots_rows:
        key = f"{r['student_id']}:{r['direction_id']}"
        subs = r['subscriptions_count']
        lessons = int(subs) * 4 if subs is not None else 0
        if not (lessons > 0):  # guard: NULL/0 subscriptions_count
            continue
        lots_by_key.setdefault(key, []).append({
            'lessons': lessons,
            'price_per_lesson': to_decimal(r['total_amount']) / Decimal(lessons),
        })
        purchased_by_key[key] = purchased_by_key.get(key, 0) + lessons

    cons_by_key: dict[str, list] = {}
    consumed_by_key: dict[str, Decimal] = {}
    for r in cons_rows:
        key = f"{r['student_id']}:{r['direction_id']}"
        units = to_decimal(r['units'])
        cons_by_key.setdefault(key, []).append({
            'units': units,
            'date': _date_str(r['lesson_date']),
        })
        consumed_by_key[key] = consumed_by_key.get(key, Decimal('0')) + units

    # keys в порядке вставки: сначала ключи партий (порядок строк lots), затем
    # ключи посещений, которых ещё не было. Порядок важен для тай-брейка дашборда.
    keys = list(lots_by_key.keys())
    for k in cons_by_key:
        if k not in lots_by_key:
            keys.append(k)
    return {
        'lots_by_key': lots_by_key,
        'purchased_by_key': purchased_by_key,
        'cons_by_key': cons_by_key,
        'consumed_by_key': consumed_by_key,
        'keys': keys,
    }


# ---------------------------------------------------------------------------
# Баланс (порт из payments.js — единый дом)
# ---------------------------------------------------------------------------

def balance_for_direction(student_id: int, direction_id: int) -> int | float:
    """
    Баланс по одному направлению: purchased − attended. half-lesson: 45→0.5.
    Возврат _js_number (int|float). (CTE → два агрегата + вычитание, паттерн 4.8.)
    """
    purchased = Payment.objects.filter(
        student_id=student_id, direction_id=direction_id,
    ).aggregate(s=Coalesce(Sum(F('subscriptions_count') * 4, output_field=_DEC), _ZERO))['s']

    attended = LessonAttendance.objects.filter(
        student_id=student_id, present=True, lesson__group__direction_id=direction_id,
    ).aggregate(s=Coalesce(Sum(_attended_units_case()), _ZERO))['s']

    return _js_number(purchased - attended)


def student_balance_rows(student_id: int) -> list[dict]:
    """
    Per-direction строки баланса (paid/attended), только направления с оплатами
    или посещениями. ORDER BY d.name. Возвращает сырые числа — _js_number делает balance.py.
    """
    paid = {
        r['direction_id']: r
        for r in (
            Payment.objects
            .filter(student_id=student_id)
            .exclude(direction_id__isnull=True)        # легаси (direction_id NULL) не джойнятся
            .values('direction_id')
            .annotate(
                purchased=Sum(F('subscriptions_count') * 4, output_field=_DEC),
                total_paid=Sum('total_amount'),
            )
        )
    }

    attended = {
        r['did']: r['attended']
        for r in (
            LessonAttendance.objects
            .filter(student_id=student_id, present=True)
            .values(did=F('lesson__group__direction_id'))
            .annotate(attended=Sum(_attended_units_case()))
        )
    }

    dir_ids = set(paid) | set(attended)
    rows: list[dict] = []
    for d in Direction.objects.filter(id__in=dir_ids).order_by('name').values('id', 'name', 'color'):
        did = d['id']
        purchased = paid.get(did, {}).get('purchased') or Decimal('0')
        total_paid = paid.get(did, {}).get('total_paid') or Decimal('0')
        att = attended.get(did) or Decimal('0')
        rows.append({
            'direction_id': did,
            'direction_name': d['name'],
            'direction_color': d['color'],
            'purchased_lessons': purchased,
            'attended_lessons': att,
            'balance': purchased - att,
            'total_paid_amount': total_paid,
        })
    return rows


def total_paid_amount(student_id: int) -> int | float:
    """Итоговая сумма всех оплат ученика. SUM(total_amount)."""
    total = Payment.objects.filter(student_id=student_id).aggregate(
        s=Coalesce(Sum('total_amount'), _ZERO),
    )['s']
    return _js_number(total)
