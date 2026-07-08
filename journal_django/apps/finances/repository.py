"""
FinancesRepository — единственное место доступа к данным вычислительного слоя финансов.

ORM-порт (раздел 09):
  • fifo_inputs()                ← _fifoInputs() (dashboard.js)
  • balance_for_student()        ← общий пул (2026-07-08 редизайн)
  • paid_by_direction_rows()     ← информ. разбивка «оплачено по направлениям» (2026-07-08)
  • attended_by_direction_rows() ← информ. разбивка «отработано по направлениям» (2026-07-08)
  • total_paid_amount()          ← getStudentBalance итоговая сумма (payments.js)

Баланс выводится, не хранится: balance_for_student — единый пул (все купленные
минус все отработанные уроки, без разбивки по направлению). Разбивки
paid_by_direction_rows / attended_by_direction_rows — только информационные.

Число баланса отдаётся через _js_number (int/float, как Number(x) в JS). Сырые
поля оплат (unit_price/total_amount) — Decimal, в строку их приводит
DateSafeJSONRenderer. fifo.py (чистый Python) не трогаем.
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
    Загружает FIFO-входы по ключу student_id (общий пул на ученика).

    С 2026-07-08 payments.direction_id и направление урока — раздельные измерения:
    оплата с тегом направления A может быть погашена уроком в направлении B (см.
    docs/superpowers/specs/2026-07-08-student-balance-pooling-design.md). Партии
    (lots) сортируются по paid_at глобально по ученику; посещения (consumptions) —
    по lesson_date глобально. direction_id урока сохраняется в каждой
    consumption-записи только для атрибуции worked_off_by_direction в отчётах.

    Возвращает lots_by_key / purchased_by_key / cons_by_key / consumed_by_key / keys.
    Guard: оплаты с subscriptions_count NULL/0 (lessons ≤ 0) пропускаются —
    иначе деление на 0 / Infinity ломает суммы.
    """
    lots_rows = (
        Payment.objects
        .filter(direction_id__isnull=False)
        .order_by('student_id', 'paid_at', 'id')
        .values('student_id', 'total_amount', 'subscriptions_count')
    )

    cons_rows = (
        LessonAttendance.objects
        .filter(present=True)
        .annotate(units=_attended_units_case())
        .order_by('student_id', 'lesson__lesson_date', 'lesson_id')
        .values(
            'student_id', 'units',
            direction_id=F('lesson__group__direction_id'),
            lesson_date=F('lesson__lesson_date'),
        )
    )

    lots_by_key: dict[str, list] = {}
    purchased_by_key: dict[str, int] = {}
    for r in lots_rows:
        key = str(r['student_id'])
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
        key = str(r['student_id'])
        units = to_decimal(r['units'])
        cons_by_key.setdefault(key, []).append({
            'units': units,
            'date': _date_str(r['lesson_date']),
            'direction_id': r['direction_id'],
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

def balance_for_student(student_id: int) -> int | float:
    """
    Общий баланс ученика (единый пул по всем направлениям): purchased − attended.
    half-lesson: 45→0.5. Возврат _js_number (int|float).
    """
    purchased = Payment.objects.filter(
        student_id=student_id,
    ).aggregate(s=Coalesce(Sum(F('subscriptions_count') * 4, output_field=_DEC), _ZERO))['s']

    attended = LessonAttendance.objects.filter(
        student_id=student_id, present=True,
    ).aggregate(s=Coalesce(Sum(_attended_units_case()), _ZERO))['s']

    return _js_number(purchased - attended)


def paid_by_direction_rows(student_id: int) -> list[dict]:
    """
    Оплачено по направлениям (по тегу оплаты payments.direction_id) — ТОЛЬКО
    информационная разбивка, не баланс (баланс общий — см. balance_for_student).
    """
    paid = (
        Payment.objects
        .filter(student_id=student_id)
        .exclude(direction_id__isnull=True)  # легаси (direction_id NULL) не джойнятся
        .values('direction_id')
        .annotate(total_paid=Sum('total_amount'))
    )
    totals = {r['direction_id']: r['total_paid'] for r in paid}
    if not totals:
        return []

    rows: list[dict] = []
    for d in Direction.objects.filter(id__in=totals).order_by('name').values('id', 'name', 'color'):
        rows.append({
            'direction_id': d['id'],
            'direction_name': d['name'],
            'direction_color': d['color'],
            'total_paid_amount': totals[d['id']],
        })
    return rows


def attended_by_direction_rows(student_id: int) -> list[dict]:
    """
    Отработано по направлениям (по направлению УРОКА, не оплаты) — ТОЛЬКО
    информационная разбивка, не баланс.
    """
    attended = (
        LessonAttendance.objects
        .filter(student_id=student_id, present=True)
        .values(did=F('lesson__group__direction_id'))
        .annotate(attended=Sum(_attended_units_case()))
    )
    totals = {r['did']: r['attended'] for r in attended if r['did'] is not None}
    if not totals:
        return []

    rows: list[dict] = []
    for d in Direction.objects.filter(id__in=totals).order_by('name').values('id', 'name', 'color'):
        rows.append({
            'direction_id': d['id'],
            'direction_name': d['name'],
            'direction_color': d['color'],
            'attended_lessons': totals[d['id']],
        })
    return rows


def total_paid_amount(student_id: int) -> int | float:
    """Итоговая сумма всех оплат ученика. SUM(total_amount)."""
    total = Payment.objects.filter(student_id=student_id).aggregate(
        s=Coalesce(Sum('total_amount'), _ZERO),
    )['s']
    return _js_number(total)
