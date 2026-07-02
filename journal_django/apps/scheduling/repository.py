"""
Доступ к данным для планирования занятий — батч-запросы (без N+1).

Единственное место ORM-доступа раздела scheduling. Все чтения — по спискам
group_id одним запросом, группировка в Python. Даты/время приходят как
date/time объекты (managed-модели), генератор работает с ними напрямую.
"""
from __future__ import annotations

import datetime

from django.db.models import F

from apps.groups.models import GroupScheduleSlot, LessonScheduleException
from apps.groups.models import Group
from apps.lessons.models import Lesson
from apps.memberships.models import GroupMembership
from apps.teachers.models import Teacher
from apps.scheduling.occurrences import ScheduleException, Slot


def active_groups(teacher_id: int | None = None) -> list[dict]:
    """Активные группы (+ преподаватель/направление/длина курса). Опц. скоуп по учителю."""
    qs = Group.objects.filter(active=True)
    if teacher_id is not None:
        qs = qs.filter(teacher_id=teacher_id)
    return list(
        qs.values(
            'id', 'name', 'is_individual', 'lesson_duration_minutes', 'group_start_date',
            teacher_pk=F('teacher_id'),
            teacher_name=F('teacher__name'),
            direction_name=F('direction__name'),
            direction_color=F('direction__color'),
            total_lessons=F('direction__total_lessons'),
        )
    )


def slots_by_group(group_ids: list[int]) -> dict[int, list[Slot]]:
    result: dict[int, list[Slot]] = {}
    if not group_ids:
        return result
    rows = GroupScheduleSlot.objects.filter(group_id__in=group_ids).values(
        'group_id', 'day_of_week', 'start_time', 'effective_from', 'effective_to',
    )
    for r in rows:
        result.setdefault(r['group_id'], []).append(Slot(
            day_of_week=r['day_of_week'],
            start_time=r['start_time'],
            effective_from=r['effective_from'],
            effective_to=r['effective_to'],
        ))
    return result


def exceptions_by_group(group_ids: list[int]) -> dict[int, list[ScheduleException]]:
    result: dict[int, list[ScheduleException]] = {}
    if not group_ids:
        return result
    rows = LessonScheduleException.objects.filter(group_id__in=group_ids).values(
        'group_id', 'kind', 'original_date', 'original_time',
        'new_date', 'new_start_time', 'new_teacher_id',
    )
    for r in rows:
        result.setdefault(r['group_id'], []).append(ScheduleException(
            kind=r['kind'],
            original_date=r['original_date'],
            original_time=r['original_time'],
            new_date=r['new_date'],
            new_start_time=r['new_start_time'],
            new_teacher_id=r['new_teacher_id'],
        ))
    return result


def fact_dates_by_group(
    group_ids: list[int], window_from: datetime.date, window_to: datetime.date,
) -> dict[int, set]:
    """Даты проведённых уроков (факт) в окне — для статуса 'done'."""
    result: dict[int, set] = {}
    if not group_ids:
        return result
    rows = (
        Lesson.objects
        .filter(group_id__in=group_ids, lesson_date__gte=window_from, lesson_date__lte=window_to)
        .values('group_id', 'lesson_date')
    )
    for r in rows:
        result.setdefault(r['group_id'], set()).add(r['lesson_date'])
    return result


def student_names_by_group(group_ids: list[int]) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    if not group_ids:
        return result
    rows = (
        GroupMembership.objects
        .filter(group_id__in=group_ids, active=True)
        .order_by('student__full_name')
        .values('group_id', name=F('student__full_name'))
    )
    for r in rows:
        result.setdefault(r['group_id'], []).append(r['name'])
    return result


def teacher_names() -> dict[int, str]:
    """id → имя преподавателя (для teacher_override в переносах)."""
    return dict(Teacher.objects.values_list('id', 'name'))
