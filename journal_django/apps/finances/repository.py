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
from typing import Iterable, Optional

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


def _makeup_completion_dates(
    student_ids: Optional[Iterable[int]] = None,
) -> dict[tuple[int, int], datetime.date]:
    """
    (missed_lesson_id, student_id) → дата ФАКТИЧЕСКОГО проведения доп.урока,
    которым скомпенсирован этот пропуск (apps.extra_lessons, status='makeup_done').

    Используется, чтобы «отработанные» деньги относились к месяцу, в котором
    доп.урок реально проведён, а не к месяцу исходного пропущенного занятия —
    иначе компенсация, проведённая в другом месяце, задним числом уезжала бы
    в месяц пропуска в помесячных финансовых отчётах (решение пользователя
    2026-07-16). Единицы (half-lesson) по-прежнему считаются от ИСХОДНОГО
    урока (_attended_units_case) — меняется только дата для месячной разбивки.
    """
    from apps.extra_lessons.models import AbsenceResolution

    qs = AbsenceResolution.objects.filter(status='makeup_done')
    if student_ids is not None:
        qs = qs.filter(student_id__in=list(student_ids))
    rows = qs.values(
        'student_id',
        'missed_lesson_id',
        completion_date=F('fact_lesson__lesson_date'),
    )
    return {
        (r['missed_lesson_id'], r['student_id']): r['completion_date']
        for r in rows if r['completion_date'] is not None
    }


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
    иначе деление на 0 / Infinity ломает суммы. Партии не фильтруются по
    direction_id — легаси-оплаты (direction_id NULL, subscriptions_count
    проставлен миграцией 0004 apps/payments) пулятся наравне с обычными,
    как и в balance_for_student (2026-07-09: убран лишний фильтр
    direction_id__isnull=False, оставшийся от дизайна до редизайна общего
    пула 2026-07-08 — иначе дашборд «Долги» считал устаревшие остатки).
    Строки kind='refund' не образуют партий — становятся синтетическими
    consumption-записями (флаг refund), готовыми для compute_fifo.
    """
    lots_rows = (
        Payment.objects
        .order_by('student_id', 'paid_at', 'id')
        .values('student_id', 'total_amount', 'lessons_count', 'kind', 'paid_at')
    )

    cons_rows = (
        LessonAttendance.objects
        .filter(present=True)
        # доп.уроки (lesson_type='extra') не учитываются в потреблении баланса —
        # компенсируемый урок уже учтён через ретроактивную отметку исходного
        # занятия (apply_makeup_attendance); иначе один пропуск списался бы дважды.
        .exclude(lesson__lesson_type='extra')
        .annotate(units=_attended_units_case())
        .order_by('student_id', 'lesson__lesson_date', 'lesson_id')
        .values(
            'student_id', 'units', 'lesson_id', 'burned_at',
            direction_id=F('lesson__group__direction_id'),
            lesson_date=F('lesson__lesson_date'),
        )
    )
    makeup_dates = _makeup_completion_dates()

    lots_by_key: dict[str, list] = {}
    purchased_by_key: dict[str, int] = {}
    refund_cons: dict[str, list] = {}   # синтетические списания-возвраты
    for r in lots_rows:
        key = str(r['student_id'])
        raw = r['lessons_count']
        if r['kind'] == 'refund':
            # возврат: гасит остаток (units = |lessons_count|, точный Decimal), без выручки
            refund_cons.setdefault(key, []).append({
                'units': -to_decimal(raw) if raw is not None else Decimal('0'),
                'date': _date_str(r['paid_at']),
                'direction_id': None,
                'refund': True,
            })
            continue
        lessons = int(raw) if raw is not None else 0  # покупки всегда целые
        if not (lessons > 0):  # guard: NULL/0
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
        # Приоритет даты для месячной атрибуции денег:
        # 1) makeup_dates — компенсированный пропуск: дата ДОП.урока;
        # 2) burned_at — ретроактивная ручная отметка (update_attendance_cell):
        #    дата самой правки, не дата исходного урока (см. update_attendance_cell);
        # 3) lesson_date — обычная посещаемость, проставленная при подаче урока.
        date = makeup_dates.get(
            (r['lesson_id'], r['student_id']), r['burned_at'] or r['lesson_date'],
        )
        cons_by_key.setdefault(key, []).append({
            'units': units,
            'date': _date_str(date),
            'direction_id': r['direction_id'],
        })
        consumed_by_key[key] = consumed_by_key.get(key, Decimal('0')) + units

    # Возвраты — синтетические списания всего остатка на дату возврата: мержим в
    # consumption'ы и пересортируем по дате (возврат после посещений того же дня).
    for key, refs in refund_cons.items():
        cons_by_key.setdefault(key, []).extend(refs)
    for key, lst in cons_by_key.items():
        lst.sort(key=lambda c: (c['date'], 1 if c.get('refund') else 0))

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

def balances_for_students(student_ids: Iterable[int]) -> dict[int, int | float]:
    """
    Общий баланс (purchased − attended) сразу для набора учеников — без N+1.

    Используется там, где строк много за один раз (teacher_spa.read_all_students
    тянет всю школу разом на 2 CPU/2 ГБ VPS). Каждый переданный student_id
    гарантированно есть в результате (0, если нет ни оплат, ни посещений).

    purchased = SUM(lessons_count) (включает отрицательные строки возврата → net).
    """
    ids = list(student_ids)
    if not ids:
        return {}

    balances: dict[int, Decimal] = {sid: Decimal('0') for sid in ids}

    purchased = (
        Payment.objects.filter(student_id__in=ids)
        .values('student_id')
        .annotate(s=Coalesce(Sum('lessons_count', output_field=_DEC), _ZERO))
    )
    for r in purchased:
        balances[r['student_id']] += r['s']

    attended = (
        LessonAttendance.objects.filter(student_id__in=ids, present=True)
        # доп.уроки (lesson_type='extra') не учитываются в потреблении баланса —
        # компенсируемый урок уже учтён через ретроактивную отметку исходного
        # занятия (apply_makeup_attendance); иначе один пропуск списался бы дважды.
        .exclude(lesson__lesson_type='extra')
        .values('student_id')
        .annotate(s=Coalesce(Sum(_attended_units_case()), _ZERO))
    )
    for r in attended:
        balances[r['student_id']] -= r['s']

    return {sid: _js_number(v) for sid, v in balances.items()}


def attended_units_total(student_id: int) -> Decimal:
    """
    Суммарно «отработано» уроков учеником за всю историю (present=true), в тех же
    единицах (half-lesson 45мин=0.5) и с тем же исключением lesson_type='extra',
    что и потребление баланса (fifo_inputs/balances_for_students): компенсируемый
    пропуск уже учтён через ретроактивную отметку исходного урока, а сам extra —
    нет, иначе один пропуск считался бы дважды.

    ЕДИНЫЙ источник правды «отработано» — вызывается и балансом finances, и движком
    продлений (apps.renewals.engine._attended_total), чтобы «отработано» в отчёте и
    прогресс сделки в «Продлениях» никогда не разошлись (до этого продления считали
    present=true БЕЗ исключения extra → доп.урок задваивал прогресс).
    """
    row = (
        LessonAttendance.objects
        .filter(student_id=student_id, present=True)
        .exclude(lesson__lesson_type='extra')
        .aggregate(s=Coalesce(Sum(_attended_units_case()), _ZERO))
    )
    return row['s']


def balance_for_student(student_id: int) -> int | float:
    """
    Общий баланс ученика (единый пул по всем направлениям): purchased − attended.
    half-lesson: 45→0.5. Делегирует в balances_for_students — одна формула на двоих.
    """
    return balances_for_students([student_id])[student_id]


def student_fifo_remaining(student_id: int) -> dict:
    """
    Неотработанный остаток ученика: сколько уроков и денег ещё не списано.
    remaining_lessons = баланс (purchased − attended, half-lesson учтён).
    remaining_value   = FIFO remaining_value по партиям-покупкам ученика.

    Строки kind='refund' (см. apps/payments/repository.py::refund_student) не
    образуют партий — как в fifo_inputs(), они становятся синтетическими
    consumption-записями (флаг refund), которые гасят остаток партий без
    учёта в worked_off_*. Иначе повторный вызов после возврата продолжал бы
    показывать остаток, который уже был возвращён (см. Task 4.2).
    """
    from apps.finances.fifo import compute_fifo

    remaining_lessons = balance_for_student(student_id)

    payment_rows = (
        Payment.objects.filter(student_id=student_id)
        .order_by('paid_at', 'id')
        .values('total_amount', 'lessons_count', 'kind', 'paid_at')
    )
    lots = []
    refund_cons = []
    for r in payment_rows:
        if r['kind'] == 'refund':
            raw = r['lessons_count']
            refund_cons.append({
                'units': -to_decimal(raw) if raw is not None else Decimal('0'),
                'date': _date_str(r['paid_at']),
                'direction_id': None,
                'refund': True,
            })
            continue
        lessons = int(r['lessons_count']) if r['lessons_count'] is not None else 0
        if lessons > 0:
            lots.append({
                'lessons': lessons,
                'price_per_lesson': to_decimal(r['total_amount']) / Decimal(lessons),
            })

    cons_rows = (
        LessonAttendance.objects.filter(student_id=student_id, present=True)
        # доп.уроки (lesson_type='extra') не учитываются в потреблении баланса —
        # компенсируемый урок уже учтён через ретроактивную отметку исходного
        # занятия (apply_makeup_attendance); иначе один пропуск списался бы дважды.
        .exclude(lesson__lesson_type='extra')
        .annotate(units=_attended_units_case())
        .order_by('lesson__lesson_date', 'lesson_id')
        .values('units', 'lesson_id', 'burned_at', lesson_date=F('lesson__lesson_date'))
    )
    makeup_dates = _makeup_completion_dates(student_ids=[student_id])
    cons = [
        {
            'units': to_decimal(r['units']),
            # Приоритет даты — см. fifo_inputs(): makeup_dates > burned_at > lesson_date.
            'date': _date_str(makeup_dates.get(
                (r['lesson_id'], student_id), r['burned_at'] or r['lesson_date'],
            )),
            'direction_id': None,
        }
        for r in cons_rows
    ]
    cons.extend(refund_cons)
    cons.sort(key=lambda c: (c['date'], 1 if c.get('refund') else 0))

    fifo = compute_fifo(lots, cons, '0001-01-01', '9999-12-31')
    return {
        'remaining_lessons': remaining_lessons,
        'remaining_value': fifo['remaining_value'],
    }


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
        # доп.уроки (lesson_type='extra') не учитываются в потреблении баланса —
        # компенсируемый урок уже учтён через ретроактивную отметку исходного
        # занятия (apply_makeup_attendance); иначе один пропуск списался бы дважды.
        .exclude(lesson__lesson_type='extra')
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
