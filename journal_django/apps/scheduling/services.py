"""
Бизнес-логика планирования: сборка календаря плановых занятий за окно.

View → Service (здесь) → occurrences (чистый генератор) + repository (ORM).
Единый источник расписания — group_schedule_slots (не regex по имени группы).
"""
from __future__ import annotations

import datetime

from apps.core.utils.dates import msk_now
from apps.scheduling import repository
from apps.scheduling.occurrences import (
    Occurrence, build_occurrences,
    CANCELLED, DONE, MOVED, OVERDUE, PENDING,
)

_LABELS = {
    DONE: 'Заполнено',
    OVERDUE: 'Надо заполнить',
    PENDING: 'Пока урока не было',
    CANCELLED: 'Отменён',
}


def _iso(d: datetime.date | None) -> str | None:
    return d.isoformat() if d else None


def _hhmm(t: datetime.time | None) -> str | None:
    return t.strftime('%H:%M') if t else None


def _ddmm(d: datetime.date) -> str:
    return f'{d.day:02d}.{d.month:02d}'


def _report_day(d: datetime.date) -> int:
    """Кодировка дня недели Вс=0 (как report.day / JS getDay) из реальной даты."""
    return (d.weekday() + 1) % 7


def _label(o: Occurrence) -> str:
    if o.status == MOVED and o.moved_to:
        return f'Перенесён на {_ddmm(o.moved_to)}'
    return _LABELS.get(o.status, '')


def _occurrence_dict(g: dict, o: Occurrence, students: list[dict], teacher_names: dict) -> dict:
    is_half = g['lesson_duration_minutes'] == 45
    teacher = (
        teacher_names.get(o.teacher_override_id)
        if o.teacher_override_id else g['teacher_name']
    )
    return {
        'group': g['name'],
        'groupDisplay': g['name'],
        'teacher': teacher,
        'teacherOverride': teacher_names.get(o.teacher_override_id) if o.teacher_override_id else None,
        'direction': g['direction_name'],
        'color': g['direction_color'],
        'isGroup': not g['is_individual'],
        'date': _iso(o.date),
        'time': _hhmm(o.time),
        'day': _report_day(o.date),
        'seq': o.seq if o.seq >= 0 else None,
        'lessonNumber': float(o.lesson_number) if o.lesson_number is not None else None,
        'isHalf': is_half,
        'isExtra': o.is_extra,
        'status': o.status,
        'label': _label(o),
        'movedFrom': _iso(o.moved_from),
        'movedTo': _iso(o.moved_to),
        'students': students,
    }


def build_calendar(
    window_from: datetime.date,
    window_to: datetime.date,
    teacher_id: int | None = None,
) -> dict:
    """
    Плановые занятия всех активных групп (опц. одного преподавателя) за окно.

    Возвращает {occurrences, unscheduled, window}. unscheduled — группы, которые
    нельзя запланировать (нет старта/слотов) с причиной (data-quality сигнал
    вместо тихого попадания в noTime, как раньше в regex-пути).
    """
    groups = repository.active_groups(teacher_id)
    ids = [g['id'] for g in groups]

    slots = repository.slots_by_group(ids)
    exceptions = repository.exceptions_by_group(ids)
    facts = repository.fact_dates_by_group(ids, window_from, window_to)
    students = repository.student_names_by_group(ids)
    tnames = repository.teacher_names()
    now = msk_now()

    occurrences: list[dict] = []
    unscheduled: list[dict] = []

    for g in groups:
        gid = g['id']
        g_slots = slots.get(gid, [])
        if g['group_start_date'] is None:
            unscheduled.append({'group': g['name'], 'reason': 'no_start_date'})
            continue
        if not g_slots:
            unscheduled.append({'group': g['name'], 'reason': 'no_slots'})
            continue

        occs = build_occurrences(
            start_date=g['group_start_date'],
            duration_minutes=g['lesson_duration_minutes'],
            total_lessons=g['total_lessons'],
            slots=g_slots,
            exceptions=exceptions.get(gid, []),
            fact_dates=facts.get(gid, set()),
            window_from=window_from,
            window_to=window_to,
            now_msk=now,
        )
        g_students = [{'name': n} for n in students.get(gid, [])]
        for o in occs:
            occurrences.append(_occurrence_dict(g, o, g_students, tnames))

    occurrences.sort(key=lambda x: (x['date'], x['time'] or ''))
    return {
        'occurrences': occurrences,
        'unscheduled': unscheduled,
        'window': {'from': window_from.isoformat(), 'to': window_to.isoformat()},
    }
