"""
Юнит-тесты чистых функций планировщика planner.py (без БД).

Операции над материализованными плановыми строками (PlannedRow): генерация плана,
разовый перенос, перенос навсегда, отмена со сдвигом, доп. занятие.

Опорные даты: 2026-06-01 — понедельник. day_of_week в конвенции Вс=0
(Пн=1, Вт=2, Ср=3, Чт=4, Пт=5, Сб=6, Вс=0).
"""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from apps.scheduling.occurrences import DONE, PENDING, Slot
from apps.scheduling.planner import (
    PlannedRow, cancel, extra, generate, permanent_change, reschedule,
)

D = datetime.date
T = datetime.time
MON, TUE, WED, THU, FRI, SAT, SUN = 1, 2, 3, 4, 5, 6, 0


def _slot(dow, hh, eff_from=D(2000, 1, 1), eff_to=None):
    return Slot(day_of_week=dow, start_time=T(hh, 0), effective_from=eff_from, effective_to=eff_to)


# --------------------------------------------------------------------------- #
# generate
# --------------------------------------------------------------------------- #

def test_generate_weekly_produces_n_rows():
    rows = generate(
        start_date=D(2026, 6, 1), slots=[_slot(MON, 10)],
        total_lessons=4, duration_minutes=90, default_teacher_id=7,
    )
    assert [r.seq for r in rows] == [1, 2, 3, 4]
    assert [r.scheduled_date for r in rows] == [D(2026, 6, 1), D(2026, 6, 8), D(2026, 6, 15), D(2026, 6, 22)]
    assert [r.lesson_number for r in rows] == [Decimal('1'), Decimal('2'), Decimal('3'), Decimal('4')]
    assert all(r.scheduled_time == T(10, 0) for r in rows)
    assert all(r.teacher_id == 7 for r in rows)
    assert all(r.status == PENDING for r in rows)


def test_generate_half_lesson_step():
    rows = generate(
        start_date=D(2026, 6, 1), slots=[_slot(MON, 10)],
        total_lessons=2, duration_minutes=45, default_teacher_id=1,
    )
    # 2 урока курса × шаг 0.5 → 4 сессии, номера 0.5..2.0
    assert len(rows) == 4
    assert [r.lesson_number for r in rows] == [Decimal('0.5'), Decimal('1.0'), Decimal('1.5'), Decimal('2.0')]


def test_generate_sunday_slot_maps_to_correct_date():
    rows = generate(
        start_date=D(2026, 6, 1), slots=[_slot(SUN, 12)],
        total_lessons=2, duration_minutes=90, default_teacher_id=1,
    )
    # Первое воскресенье на/после старта = 2026-06-07, затем 06-14.
    assert [r.scheduled_date for r in rows] == [D(2026, 6, 7), D(2026, 6, 14)]
    assert all(r.scheduled_time == T(12, 0) for r in rows)


def test_generate_multiple_slots_ordered_by_date():
    rows = generate(
        start_date=D(2026, 6, 1), slots=[_slot(MON, 10), _slot(WED, 14)],
        total_lessons=4, duration_minutes=90, default_teacher_id=1,
    )
    assert [r.scheduled_date for r in rows] == [D(2026, 6, 1), D(2026, 6, 3), D(2026, 6, 8), D(2026, 6, 10)]
    assert [r.seq for r in rows] == [1, 2, 3, 4]


def test_generate_no_total_returns_empty():
    rows = generate(
        start_date=D(2026, 6, 1), slots=[_slot(MON, 10)],
        total_lessons=None, duration_minutes=90, default_teacher_id=1,
    )
    assert rows == []


def test_generate_no_slots_returns_empty():
    rows = generate(
        start_date=D(2026, 6, 1), slots=[],
        total_lessons=4, duration_minutes=90, default_teacher_id=1,
    )
    assert rows == []


def test_generate_is_idempotent_by_value():
    kw = dict(start_date=D(2026, 6, 1), slots=[_slot(MON, 10)],
              total_lessons=4, duration_minutes=90, default_teacher_id=7)
    assert generate(**kw) == generate(**kw)


def test_generate_versioned_slots_continuous_numbering():
    """Версионные слоты (закрытый + открытый) → _walk выбирает активный на дату,
    номера сквозные. Покрывает переход effective_from/effective_to в генераторе."""
    slots = [
        _slot(MON, 10, eff_from=D(2026, 6, 1), eff_to=D(2026, 6, 14)),   # первые 2 понедельника
        _slot(WED, 14, eff_from=D(2026, 6, 15)),                          # далее среды
    ]
    rows = generate(
        start_date=D(2026, 6, 1), slots=slots,
        total_lessons=4, duration_minutes=90, default_teacher_id=1,
    )
    assert [r.scheduled_date for r in rows] == [D(2026, 6, 1), D(2026, 6, 8), D(2026, 6, 17), D(2026, 6, 24)]
    assert [r.lesson_number for r in rows] == [Decimal('1'), Decimal('2'), Decimal('3'), Decimal('4')]
    assert rows[2].scheduled_time == T(14, 0)


# --------------------------------------------------------------------------- #
# reschedule
# --------------------------------------------------------------------------- #

def _row(seq=2, ln='2', date=D(2026, 6, 8), time=T(10, 0), teacher=7, status=PENDING):
    return PlannedRow(
        seq=seq, lesson_number=Decimal(ln), scheduled_date=date,
        scheduled_time=time, teacher_id=teacher, status=status,
    )


def test_reschedule_moves_single_row_and_sets_moved_from():
    out = reschedule(_row(), new_date=D(2026, 6, 10), new_time=T(12, 0))
    assert out.scheduled_date == D(2026, 6, 10)
    assert out.scheduled_time == T(12, 0)
    assert out.moved_from_date == D(2026, 6, 8)
    assert out.seq == 2
    assert out.lesson_number == Decimal('2')


def test_reschedule_keeps_time_when_new_time_none():
    out = reschedule(_row(time=T(10, 0)), new_date=D(2026, 6, 10), new_time=None)
    assert out.scheduled_time == T(10, 0)


def test_reschedule_optional_teacher_override():
    out = reschedule(_row(teacher=7), new_date=D(2026, 6, 10), new_teacher_id=9)
    assert out.teacher_id == 9
    keep = reschedule(_row(teacher=7), new_date=D(2026, 6, 10))
    assert keep.teacher_id == 7


def test_reschedule_done_raises():
    with pytest.raises(ValueError):
        reschedule(_row(status=DONE), new_date=D(2026, 6, 10))


# --------------------------------------------------------------------------- #
# permanent_change
# --------------------------------------------------------------------------- #

def _plan_mon():
    return generate(
        start_date=D(2026, 6, 1), slots=[_slot(MON, 10)],
        total_lessons=4, duration_minutes=90, default_teacher_id=7,
    )


def test_permanent_change_recomputes_tail_to_new_weekday():
    rows = permanent_change(_plan_mon(), from_seq=2, new_day_of_week=WED, new_time=T(14, 0))
    by_seq = {r.seq: r for r in rows}
    assert by_seq[1].scheduled_date == D(2026, 6, 1)   # голова не тронута
    assert by_seq[1].scheduled_time == T(10, 0)
    # Каждая строка сдвигается на среду СВОЕЙ недели, недельная каденция сохранена.
    assert by_seq[2].scheduled_date == D(2026, 6, 10)  # среда недели 06-08
    assert by_seq[3].scheduled_date == D(2026, 6, 17)  # среда недели 06-15
    assert by_seq[4].scheduled_date == D(2026, 6, 24)  # среда недели 06-22
    assert all(by_seq[s].scheduled_time == T(14, 0) for s in (2, 3, 4))


def test_permanent_change_does_not_touch_done():
    rows = _plan_mon()
    rows[1].status = DONE  # seq=2 проведён
    out = permanent_change(rows, from_seq=2, new_day_of_week=WED)
    by_seq = {r.seq: r for r in out}
    assert by_seq[2].scheduled_date == D(2026, 6, 8)   # done остался на понедельнике
    assert by_seq[3].scheduled_date == D(2026, 6, 17)  # pending переехал на среду своей недели
    assert by_seq[4].scheduled_date == D(2026, 6, 24)


def test_permanent_change_sets_teacher_on_tail_only():
    out = permanent_change(_plan_mon(), from_seq=3, new_day_of_week=MON, new_teacher_id=9)
    by_seq = {r.seq: r for r in out}
    assert by_seq[1].teacher_id == 7
    assert by_seq[2].teacher_id == 7
    assert by_seq[3].teacher_id == 9
    assert by_seq[4].teacher_id == 9


# --------------------------------------------------------------------------- #
# cancel
# --------------------------------------------------------------------------- #

def test_cancel_shifts_tail_plus_seven_days():
    out = cancel(_plan_mon(), from_date=D(2026, 6, 8))
    by_seq = {r.seq: r for r in out}
    assert by_seq[1].scheduled_date == D(2026, 6, 1)    # до from_date — не тронут
    assert by_seq[2].scheduled_date == D(2026, 6, 15)   # +7
    assert by_seq[3].scheduled_date == D(2026, 6, 22)
    assert by_seq[4].scheduled_date == D(2026, 6, 29)


def test_cancel_ignores_done():
    rows = _plan_mon()
    rows[1].status = DONE  # seq=2 на 06-08 проведён
    out = cancel(rows, from_date=D(2026, 6, 8))
    by_seq = {r.seq: r for r in out}
    assert by_seq[2].scheduled_date == D(2026, 6, 8)    # done не сдвинут
    assert by_seq[3].scheduled_date == D(2026, 6, 22)   # pending +7
    assert by_seq[4].scheduled_date == D(2026, 6, 29)


def test_cancel_preserves_weekday_and_time():
    out = cancel(_plan_mon(), from_date=D(2026, 6, 8))
    moved = next(r for r in out if r.seq == 2)
    assert moved.scheduled_date.weekday() == D(2026, 6, 8).weekday()  # тот же день недели
    assert moved.scheduled_time == T(10, 0)


# --------------------------------------------------------------------------- #
# extra
# --------------------------------------------------------------------------- #

def test_extra_row_is_non_course():
    r = extra(date=D(2026, 6, 20), time=T(15, 0), teacher_id=3)
    assert r.seq is None
    assert r.lesson_number is None
    assert r.is_extra is True
    assert r.scheduled_date == D(2026, 6, 20)
    assert r.scheduled_time == T(15, 0)
    assert r.teacher_id == 3
    assert r.status == PENDING
