"""
ExtraLessonsRepository — единственное место ORM-доступа раздела extra_lessons.

Батч-запросы без N+1 (assignments_in_window собирает все имена одним
IN-запросом на список назначений — используется календарём, Task 10).
"""
from __future__ import annotations

import datetime
from typing import Optional

from django.db import transaction
from django.db.models import F

from apps.extra_lessons.models import (
    CANCELLED, DONE, SCHEDULED,
    ExtraLessonAssignment, ExtraLessonParticipant,
)


def create_assignment(
    *,
    missed_lesson_id: int,
    teacher_id: int,
    student_ids: list[int],
    scheduled_date: datetime.date,
    scheduled_time: datetime.time,
    duration_minutes: int,
) -> int:
    """Создаёт назначение (status=scheduled) + участников. Возвращает id."""
    with transaction.atomic():
        obj = ExtraLessonAssignment.objects.create(
            missed_lesson_id=missed_lesson_id,
            teacher_id=teacher_id,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            duration_minutes=duration_minutes,
            status=SCHEDULED,
        )
        ExtraLessonParticipant.objects.bulk_create([
            ExtraLessonParticipant(assignment_id=obj.id, student_id=sid)
            for sid in student_ids
        ])
    return obj.id


def get_assignment_full(assignment_id: int) -> Optional[dict]:
    """Назначение + участники (id+имя) + метаданные пропущенного урока/учителя."""
    row = (
        ExtraLessonAssignment.objects
        .filter(id=assignment_id)
        .values(
            'id', 'teacher_id', 'missed_lesson_id', 'scheduled_date', 'scheduled_time',
            'duration_minutes', 'status', 'fact_lesson_id',
            teacher_name=F('teacher__name'),
            missed_lesson_group_id=F('missed_lesson__group_id'),
            missed_lesson_group_name=F('missed_lesson__group__name'),
            missed_lesson_date=F('missed_lesson__lesson_date'),
        )
        .first()
    )
    if row is None:
        return None
    row['participants'] = list(
        ExtraLessonParticipant.objects
        .filter(assignment_id=assignment_id)
        .order_by('student__full_name')
        .values('student_id', student_name=F('student__full_name'))
    )
    return row


def participant_student_ids(assignment_id: int) -> list[int]:
    return list(
        ExtraLessonParticipant.objects
        .filter(assignment_id=assignment_id)
        .values_list('student_id', flat=True)
    )


def has_active_assignment(missed_lesson_id: int, student_id: int) -> bool:
    """Есть ли уже НЕотменённое назначение доп.урока за этот пропуск у этого
    студента — не даём задвоить компенсацию одного пропуска."""
    return (
        ExtraLessonParticipant.objects
        .filter(
            student_id=student_id,
            assignment__missed_lesson_id=missed_lesson_id,
        )
        .exclude(assignment__status=CANCELLED)
        .exists()
    )


def cancel_assignment(assignment_id: int) -> None:
    """status → cancelled. ValueError, если не 'scheduled' (404 обрабатывает
    вызывающий сервис отдельно — до этого вызова)."""
    with transaction.atomic():
        obj = ExtraLessonAssignment.objects.select_for_update().filter(id=assignment_id).first()
        if obj is None:
            return
        if obj.status != SCHEDULED:
            raise ValueError('Отменить можно только ещё не проведённый доп.урок.')
        obj.status = CANCELLED
        obj.save(update_fields=['status'])


def mark_done(assignment_id: int, *, fact_lesson_id: int) -> None:
    ExtraLessonAssignment.objects.filter(id=assignment_id).update(
        status=DONE, fact_lesson_id=fact_lesson_id,
    )


def reset_to_scheduled(assignment_id: int) -> None:
    """Откат mark_done (удаление факта доп.урока) — см. services.delete_fact."""
    ExtraLessonAssignment.objects.filter(id=assignment_id).update(
        status=SCHEDULED, fact_lesson_id=None,
    )


def list_assignments(
    page: int = 1,
    page_size: int = 50,
    sort_by: str = 'scheduled_date',
    sort_dir: str = 'desc',
    filters: Optional[dict] = None,
) -> dict:
    """Пагинированный список назначений. Контракт: {rows, total, page, page_size}."""
    if filters is None:
        filters = {}
    sortable = {
        'scheduled_date': 'scheduled_date',
        'status': 'status',
        'teacher_name': 'teacher__name',
    }
    sort_field = sortable.get(sort_by) or sortable['scheduled_date']
    order_prefix = '' if sort_dir == 'asc' else '-'

    qs = ExtraLessonAssignment.objects.all()
    status_filter = filters.get('status')
    if status_filter not in (None, ''):
        qs = qs.filter(status=status_filter)
    teacher_id = filters.get('teacher_id')
    if teacher_id not in (None, ''):
        qs = qs.filter(teacher_id=int(teacher_id))

    total = qs.count()
    offset = max(0, (page - 1) * page_size)
    ordered = qs.order_by(f'{order_prefix}{sort_field}', '-id')
    rows = list(
        ordered[offset:offset + page_size].values(
            'id', 'teacher_id', 'missed_lesson_id', 'scheduled_date', 'scheduled_time',
            'duration_minutes', 'status', 'fact_lesson_id',
            teacher_name=F('teacher__name'),
            missed_lesson_group_name=F('missed_lesson__group__name'),
            missed_lesson_date=F('missed_lesson__lesson_date'),
        )
    )
    if rows:
        ids = [r['id'] for r in rows]
        names_by_assignment: dict[int, list[dict]] = {}
        for aid, sid, name in (
            ExtraLessonParticipant.objects
            .filter(assignment_id__in=ids)
            .order_by('student__full_name')
            .values_list('assignment_id', 'student_id', 'student__full_name')
        ):
            names_by_assignment.setdefault(aid, []).append(
                {'student_id': sid, 'student_name': name}
            )
        for r in rows:
            r['participants'] = names_by_assignment.get(r['id'], [])

    return {'rows': rows, 'total': total, 'page': page, 'page_size': page_size}


def assignments_in_window(
    teacher_id: int, window_from: datetime.date, window_to: datetime.date,
) -> list[dict]:
    """Назначения ОДНОГО преподавателя за окно — источник календаря (Task 10)."""
    rows = list(
        ExtraLessonAssignment.objects
        .filter(
            teacher_id=teacher_id,
            scheduled_date__gte=window_from,
            scheduled_date__lte=window_to,
        )
        .values(
            'id', 'scheduled_date', 'scheduled_time', 'duration_minutes', 'status',
            teacher_name=F('teacher__name'),
            missed_lesson_group_name=F('missed_lesson__group__name'),
        )
    )
    if not rows:
        return []
    ids = [r['id'] for r in rows]
    names_by_assignment: dict[int, list[str]] = {}
    for aid, name in (
        ExtraLessonParticipant.objects
        .filter(assignment_id__in=ids)
        .order_by('student__full_name')
        .values_list('assignment_id', 'student__full_name')
    ):
        names_by_assignment.setdefault(aid, []).append(name)
    for r in rows:
        r['student_names'] = names_by_assignment.get(r['id'], [])
    return rows
