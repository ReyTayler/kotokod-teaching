"""
Юнит-тесты чистого генератора occurrences (без БД).

Опорные даты: 2026-06-01 — понедельник. day_of_week в конвенции Вс=0
(Пн=1, Вт=2, Ср=3, Чт=4, Пт=5, Сб=6, Вс=0).
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from apps.core.utils.dates import MSK
from apps.scheduling.occurrences import (
    Occurrence, ScheduleException, Slot, build_occurrences,
    CANCELLED, DONE, MOVED, OVERDUE, PENDING,
)

D = datetime.date
T = datetime.time
MON, TUE, WED = 1, 2, 3          # Вс=0 конвенция
SUN = 0
FAR = datetime.datetime(2000, 1, 1, tzinfo=MSK)   # «сейчас» в прошлом → всё pending


def _slot(dow, hh, eff_from=D(2000, 1, 1), eff_to=None):
    return Slot(day_of_week=dow, start_time=T(hh, 0), effective_from=eff_from, effective_to=eff_to)


def _build(**kw):
    base = dict(
        start_date=D(2026, 6, 1),
        duration_minutes=90,
        total_lessons=4,
        slots=[_slot(MON, 10)],
        exceptions=[],
        fact_dates=set(),
        window_from=D(2026, 6, 1),
        window_to=D(2026, 6, 30),
        now_msk=FAR,
    )
    base.update(kw)
    return build_occurrences(**base)


def test_basic_weekly_recurrence():
    occ = _build()
    assert [o.date for o in occ] == [D(2026, 6, 1), D(2026, 6, 8), D(2026, 6, 15), D(2026, 6, 22)]
    assert [o.lesson_number for o in occ] == [Decimal('1'), Decimal('2'), Decimal('3'), Decimal('4')]
    assert all(o.time == T(10, 0) for o in occ)


def test_half_lesson_step():
    occ = _build(duration_minutes=45, total_lessons=2)
    # 2 занятия курса × шаг 0.5 → 4 сессии, номера 0.5..2.0
    assert [o.lesson_number for o in occ] == [Decimal('0.5'), Decimal('1.0'), Decimal('1.5'), Decimal('2.0')]
    assert len(occ) == 4


def test_multiple_slots_per_week_ordered_by_date():
    occ = _build(slots=[_slot(MON, 10), _slot(WED, 14)], total_lessons=4)
    assert [o.date for o in occ] == [D(2026, 6, 1), D(2026, 6, 3), D(2026, 6, 8), D(2026, 6, 10)]
    assert [o.lesson_number for o in occ] == [Decimal('1'), Decimal('2'), Decimal('3'), Decimal('4')]


def test_course_length_terminates():
    occ = _build(total_lessons=2)
    assert len(occ) == 2


def test_open_ended_course_fills_window():
    occ = _build(total_lessons=None, window_from=D(2026, 6, 1), window_to=D(2026, 6, 22))
    assert [o.date for o in occ] == [D(2026, 6, 1), D(2026, 6, 8), D(2026, 6, 15), D(2026, 6, 22)]


def test_window_filters_but_preserves_numbering():
    # длинный курс, узкое окно — номера должны быть «глобальными» от старта
    occ = _build(total_lessons=10, window_from=D(2026, 6, 15), window_to=D(2026, 6, 22))
    assert [o.date for o in occ] == [D(2026, 6, 15), D(2026, 6, 22)]
    assert [o.lesson_number for o in occ] == [Decimal('3'), Decimal('4')]


def test_start_midweek_skips_earlier_slot():
    # старт в среду 2026-06-03, слот — понедельник → первый Пн будет 06-08
    occ = _build(start_date=D(2026, 6, 3), slots=[_slot(MON, 10)], total_lessons=2)
    assert [o.date for o in occ] == [D(2026, 6, 8), D(2026, 6, 15)]


def test_sunday_convention():
    # слот Вс=0 → занятие в воскресенье (2026-06-07 — воскресенье)
    occ = _build(start_date=D(2026, 6, 1), slots=[_slot(SUN, 12)], total_lessons=1)
    assert occ[0].date == D(2026, 6, 7)
    assert occ[0].date.weekday() == 6  # Python Sunday=6


def test_permanent_time_change_continuous_numbering():
    slots = [
        _slot(MON, 10, eff_from=D(2026, 6, 1), eff_to=D(2026, 6, 14)),   # первые 2 понедельника
        _slot(WED, 14, eff_from=D(2026, 6, 15)),                          # далее среды
    ]
    occ = _build(slots=slots, total_lessons=4)
    assert [o.date for o in occ] == [D(2026, 6, 1), D(2026, 6, 8), D(2026, 6, 17), D(2026, 6, 24)]
    assert [o.lesson_number for o in occ] == [Decimal('1'), Decimal('2'), Decimal('3'), Decimal('4')]
    assert occ[2].time == T(14, 0)


def test_reschedule_marks_moved_and_inserts_new():
    ex = ScheduleException(kind='reschedule', original_date=D(2026, 6, 8),
                           new_date=D(2026, 6, 10), new_start_time=T(15, 0))
    occ = _build(exceptions=[ex])
    by_date = {o.date: o for o in occ}
    assert by_date[D(2026, 6, 8)].status == MOVED
    assert by_date[D(2026, 6, 8)].moved_to == D(2026, 6, 10)
    moved = by_date[D(2026, 6, 10)]
    assert moved.moved_from == D(2026, 6, 8)
    assert moved.lesson_number == Decimal('2')      # наследует номер исходной occurrence
    assert moved.time == T(15, 0)


def test_reschedule_into_window_from_outside():
    # исходная дата ВНЕ окна, новая — В окне: перенесённое занятие всё равно видно
    ex = ScheduleException(kind='reschedule', original_date=D(2026, 5, 25),
                           new_date=D(2026, 6, 3), new_start_time=T(11, 0))
    occ = _build(start_date=D(2026, 5, 25), total_lessons=6,
                 window_from=D(2026, 6, 1), window_to=D(2026, 6, 10), exceptions=[ex])
    dates = [o.date for o in occ]
    assert D(2026, 6, 3) in dates
    moved = next(o for o in occ if o.date == D(2026, 6, 3))
    assert moved.moved_from == D(2026, 5, 25)


def test_cancel_marks_cancelled():
    ex = ScheduleException(kind='cancel', original_date=D(2026, 6, 15))
    occ = _build(exceptions=[ex])
    assert next(o for o in occ if o.date == D(2026, 6, 15)).status == CANCELLED


def test_extra_lesson_has_no_number():
    ex = ScheduleException(kind='extra', new_date=D(2026, 6, 5), new_start_time=T(16, 0))
    occ = _build(exceptions=[ex])
    extra = next(o for o in occ if o.date == D(2026, 6, 5))
    assert extra.is_extra is True
    assert extra.lesson_number is None
    assert extra.seq == -1


def test_status_done_overdue_pending():
    now = datetime.datetime(2026, 6, 16, 12, 0, tzinfo=MSK)
    occ = _build(fact_dates={D(2026, 6, 1)}, now_msk=now)
    st = {o.date: o.status for o in occ}
    assert st[D(2026, 6, 1)] == DONE       # есть факт
    assert st[D(2026, 6, 8)] == OVERDUE    # прошло, факта нет
    assert st[D(2026, 6, 15)] == OVERDUE   # 15-е < 16-е
    assert st[D(2026, 6, 22)] == PENDING   # будущее


def test_unscheduled_when_no_start_or_no_slots():
    assert _build(start_date=None) == []
    assert _build(slots=[]) == []
