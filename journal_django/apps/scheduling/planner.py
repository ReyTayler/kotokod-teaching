"""
Чистые функции планировщика материализованных плановых занятий — БЕЗ доступа к БД.

Операции над списком плановых строк (PlannedRow): генерация плана из старта/слотов,
разовый перенос, перенос навсегда (сдвиг хвоста на новый день недели), отмена со
сдвигом хвоста +1 неделю, доп. занятие. Запись результата в БД — в repository.py
(шаг 4); здесь только детерминированная логика над датами, тестируемая в изоляции.

Инвариант всех операций: строки со статусом DONE (проведённые) НЕ трогаются.
`seq`/`lesson_number` (порядок контента) стабильны — двигаются только даты
(и опц. преподаватель). Конвенция day_of_week — Вс=0. Даты — datetime.date/time
без TZ. См. docs/lesson-scheduling.md.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Optional

from apps.scheduling.occurrences import (
    PENDING, DONE,
    Slot, _offset_from_monday, _step_for, _walk,
)


@dataclass
class PlannedRow:
    """Материализованная плановая строка (значения, релевантные для логики дат).

    Отражает поля модели PlannedLesson, участвующие в операциях планировщика.
    Запись/чтение ORM — в repository.py; planner оперирует только значениями.
    """
    seq: Optional[int]
    lesson_number: Optional[Decimal]
    scheduled_date: datetime.date
    scheduled_time: datetime.time
    teacher_id: Optional[int] = None
    status: str = PENDING
    moved_from_date: Optional[datetime.date] = None
    moved_to_date: Optional[datetime.date] = None
    is_extra: bool = False


# Активные (непроведённые) статусы, которые операции могут двигать.
_MUTABLE = frozenset({'pending', 'overdue'})


def _far_future(start: datetime.date, total_lessons: int, step: Decimal) -> datetime.date:
    """Верхняя граница генерации для _walk (в неделях, с запасом).

    Число сессий до достижения total = total_lessons / step (полуурок step=0.5 →
    вдвое больше сессий). При >=1 слоте в неделю столько же недель максимум.
    Раньше граница считалась как total_lessons+2 (ошибочно — 1 сессия/неделю),
    из-за чего полуурочные курсы обрезались вдвое."""
    weeks = int(Decimal(total_lessons) / step) + 2
    return start + datetime.timedelta(weeks=weeks)


def generate(
    *,
    start_date: datetime.date,
    slots: list[Slot],
    total_lessons: Optional[int],
    duration_minutes: int,
    default_teacher_id: Optional[int],
) -> list[PlannedRow]:
    """Развернуть план курса: N курсовых строк (seq 1..N) еженедельно на день/время
    слота. Переиспользует чистый генератор occurrences._walk. total_lessons
    обязателен: если None (или нет слотов) — группа «unscheduled», вернуть []."""
    if total_lessons is None or not slots:
        return []
    step = _step_for(duration_minutes)
    occ = _walk(start_date, slots, step, total_lessons, _far_future(start_date, total_lessons, step))
    return [
        PlannedRow(
            seq=o.seq,
            lesson_number=o.lesson_number,
            scheduled_date=o.date,
            scheduled_time=o.time,
            teacher_id=default_teacher_id,
            status=PENDING,
        )
        for o in occ
    ]


def reschedule(
    row: PlannedRow,
    *,
    new_date: datetime.date,
    new_time: Optional[datetime.time] = None,
    new_teacher_id: Optional[int] = None,
) -> PlannedRow:
    """Разовый перенос одной строки: новые дата/время (+опц. преподаватель),
    прежняя дата фиксируется в moved_from_date. seq/lesson_number сохраняются.
    Проведённое (DONE) переносить нельзя."""
    if row.status == DONE:
        raise ValueError('Нельзя перенести проведённое занятие (status=done).')
    return replace(
        row,
        scheduled_date=new_date,
        scheduled_time=new_time if new_time is not None else row.scheduled_time,
        teacher_id=new_teacher_id if new_teacher_id is not None else row.teacher_id,
        moved_from_date=row.scheduled_date,
    )


def _shift_to_weekday(d: datetime.date, new_dow_sun0: int) -> datetime.date:
    """Дата того же недельного окна (Пн..Вс), но на новый день недели (Вс=0)."""
    monday = d - datetime.timedelta(days=d.weekday())
    return monday + datetime.timedelta(days=_offset_from_monday(new_dow_sun0))


def permanent_change(
    rows: list[PlannedRow],
    *,
    from_seq: int,
    new_day_of_week: int,
    new_time: Optional[datetime.time] = None,
    new_teacher_id: Optional[int] = None,
) -> list[PlannedRow]:
    """Перенос навсегда: пересчитать дату всех курсовых строк seq>=from_seq со
    статусом pending/overdue на новый день недели, сохраняя недельную каденцию;
    опц. проставить преподавателя. Проведённые и голова (seq<from_seq) не трогаются.
    Версионирование слота (закрыть старый/открыть новый) — эффект repository."""
    out: list[PlannedRow] = []
    for r in rows:
        if r.seq is not None and r.seq >= from_seq and r.status in _MUTABLE:
            out.append(replace(
                r,
                scheduled_date=_shift_to_weekday(r.scheduled_date, new_day_of_week),
                scheduled_time=new_time if new_time is not None else r.scheduled_time,
                teacher_id=new_teacher_id if new_teacher_id is not None else r.teacher_id,
            ))
        else:
            out.append(replace(r))
    return out


def cancel(rows: list[PlannedRow], *, from_date: datetime.date) -> list[PlannedRow]:
    """Отмена со сдвигом: все непроведённые строки с scheduled_date>=from_date
    сдвигаются на +7 дней (день недели/время сохраняются — курс продлевается на
    неделю, уроки не списываются). Проведённые (DONE) не трогаются."""
    out: list[PlannedRow] = []
    for r in rows:
        if r.scheduled_date >= from_date and r.status != DONE:
            out.append(replace(r, scheduled_date=r.scheduled_date + datetime.timedelta(days=7)))
        else:
            out.append(replace(r))
    return out


def extra(
    *,
    date: datetime.date,
    time: datetime.time,
    teacher_id: Optional[int],
) -> PlannedRow:
    """Доп. занятие вне курса: seq/lesson_number = None, is_extra=True."""
    return PlannedRow(
        seq=None,
        lesson_number=None,
        scheduled_date=date,
        scheduled_time=time,
        teacher_id=teacher_id,
        status=PENDING,
        is_extra=True,
    )
