"""ExtraLessonsRepository — единственное место ORM-доступа раздела (пер-ученик AbsenceResolution)."""
from __future__ import annotations

from typing import Optional

from django.db import transaction
from django.db.models import F

from apps.extra_lessons.models import CANCELLED, DONE, SCHEDULED, AbsenceResolution
from apps.lessons.models import LessonAttendance


def create_resolutions(*, missed_lesson_id, assigned_teacher_id, student_ids,
                       scheduled_date, scheduled_time, duration_minutes) -> list[int]:
    """N независимых резолюций (по одной на ученика), status=scheduled. Возвращает их id."""
    objs = [AbsenceResolution(
        missed_lesson_id=missed_lesson_id, student_id=sid, assigned_teacher_id=assigned_teacher_id,
        scheduled_date=scheduled_date, scheduled_time=scheduled_time,
        duration_minutes=duration_minutes, status=SCHEDULED,
    ) for sid in student_ids]
    AbsenceResolution.objects.bulk_create(objs)
    return [o.id for o in objs]


def _full_values(qs):
    return qs.values(
        'id', 'missed_lesson_id', 'student_id', 'assigned_teacher_id', 'scheduled_date',
        'scheduled_time', 'duration_minutes', 'status', 'fact_lesson_id',
        student_name=F('student__full_name'),
        teacher_name=F('assigned_teacher__name'),
        missed_lesson_group_id=F('missed_lesson__group_id'),
        missed_lesson_group_name=F('missed_lesson__group__name'),
        missed_lesson_date=F('missed_lesson__lesson_date'))


def get_resolution_full(resolution_id) -> Optional[dict]:
    return _full_values(AbsenceResolution.objects.filter(id=resolution_id)).first()


def lock_for_record(resolution_id) -> Optional[dict]:
    """SELECT ... FOR UPDATE внутри atomic() — авторитетная проверка статуса перед записью."""
    return (AbsenceResolution.objects.select_for_update().filter(id=resolution_id)
            .values('id', 'status', 'assigned_teacher_id', 'missed_lesson_id', 'student_id',
                    'scheduled_date', 'duration_minutes',
                    missed_lesson_group_id=F('missed_lesson__group_id')).first())


def lock_for_delete(resolution_id) -> Optional[dict]:
    return (AbsenceResolution.objects.select_for_update().filter(id=resolution_id)
            .values('id', 'status', 'missed_lesson_id', 'student_id', 'fact_lesson_id').first())


def has_active_resolution(missed_lesson_id, student_id) -> bool:
    return (AbsenceResolution.objects.filter(missed_lesson_id=missed_lesson_id, student_id=student_id)
            .exclude(status=CANCELLED).exists())


def students_not_absent(missed_lesson_id, student_ids) -> list[int]:
    absent = set(LessonAttendance.objects.filter(
        lesson_id=missed_lesson_id, student_id__in=student_ids, present=False
    ).values_list('student_id', flat=True))
    return [sid for sid in student_ids if sid not in absent]


def cancel(resolution_id) -> None:
    with transaction.atomic():
        obj = AbsenceResolution.objects.select_for_update().filter(id=resolution_id).first()
        if obj is None:
            return
        if obj.status != SCHEDULED:
            raise ValueError('Отменить можно только ещё не проведённый доп.урок.')
        obj.status = CANCELLED
        obj.save(update_fields=['status'])


def mark_done(resolution_id, *, fact_lesson_id) -> None:
    AbsenceResolution.objects.filter(id=resolution_id).update(status=DONE, fact_lesson_id=fact_lesson_id)


def reset_to_scheduled(resolution_id) -> None:
    AbsenceResolution.objects.filter(id=resolution_id).update(status=SCHEDULED, fact_lesson_id=None)


def list_resolutions(page=1, page_size=50, sort_by='scheduled_date', sort_dir='desc', filters=None) -> dict:
    filters = filters or {}
    sortable = {'scheduled_date': 'scheduled_date', 'status': 'status',
                'teacher_name': 'assigned_teacher__name', 'student_name': 'student__full_name'}
    order = ('' if sort_dir == 'asc' else '-') + sortable.get(sort_by, 'scheduled_date')
    qs = AbsenceResolution.objects.all()
    if filters.get('status'):
        qs = qs.filter(status=filters['status'])
    if filters.get('teacher_id'):
        qs = qs.filter(assigned_teacher_id=int(filters['teacher_id']))
    total = qs.count()
    offset = max(0, (page - 1) * page_size)
    rows = list(_full_values(qs.order_by(order, '-id')[offset:offset + page_size]))
    return {'rows': rows, 'total': total, 'page': page, 'page_size': page_size}


def assignments_in_window(teacher_id, window_from, window_to) -> list[dict]:
    """Резолюции ОДНОГО преподавателя за окно — источник teacher-календаря.
    Каждая резолюция = одна карточка (пер-ученик), поэтому student_names — список
    из одного имени (форму сохраняем для совместимости с scheduling-консьюмером)."""
    rows = list(
        AbsenceResolution.objects
        .filter(assigned_teacher_id=teacher_id,
                scheduled_date__gte=window_from, scheduled_date__lte=window_to)
        .values('id', 'scheduled_date', 'scheduled_time', 'duration_minutes', 'status',
                teacher_name=F('assigned_teacher__name'),
                missed_lesson_group_name=F('missed_lesson__group__name'),
                _student_name=F('student__full_name')))
    for r in rows:
        name = r.pop('_student_name')
        r['student_names'] = [name] if name else []
    return rows
