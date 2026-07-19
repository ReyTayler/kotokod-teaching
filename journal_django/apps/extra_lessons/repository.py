"""ExtraLessonsRepository — единственное место ORM-доступа раздела (пер-ученик AbsenceResolution)."""
from __future__ import annotations

from typing import Optional

from django.db.models import F

from apps.extra_lessons.models import (
    BURNED, MAKEUP_DONE, MAKEUP_SCHEDULED, PENDING, AbsenceResolution,
)
from apps.lessons.models import LessonAttendance


def autocreate_pending(missed_lesson_id, student_ids) -> int:
    """Идемпотентно создать pending-резолюции по списку отсутствовавших.
    bulk_create(ignore_conflicts=True) → INSERT ... ON CONFLICT DO NOTHING по
    UNIQUE(missed_lesson, student). Возвращает len(student_ids) (верхняя оценка;
    тесты проверяют факт создания выборкой). Пустой список — no-op (return 0).

    Через ORM, а не raw executemany: последний несовместим с инъекцией
    pghistory-контекста под HTTP-запросом (не все аргументы форматируются)."""
    if not student_ids:
        return 0
    AbsenceResolution.objects.bulk_create(
        [AbsenceResolution(missed_lesson_id=missed_lesson_id, student_id=sid, status=PENDING)
         for sid in student_ids],
        ignore_conflicts=True,
    )
    return len(student_ids)


def _full_values(qs):
    return qs.values(
        'id', 'missed_lesson_id', 'student_id', 'assigned_teacher_id', 'scheduled_date',
        'scheduled_time', 'duration_minutes', 'status', 'fact_lesson_id',
        student_name=F('student__full_name'),
        teacher_name=F('assigned_teacher__name'),
        missed_lesson_group_id=F('missed_lesson__group_id'),
        missed_lesson_group_name=F('missed_lesson__group__name'),
        missed_lesson_date=F('missed_lesson__lesson_date'),
        missed_lesson_number=F('missed_lesson__lesson_number'))


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


def lock_for_assign(missed_lesson_id, student_id) -> Optional[dict]:
    """SELECT ... FOR UPDATE резолюции перед переводом в makeup_scheduled.
    None → строки нет (сервис создаст напрямую create_scheduled_direct)."""
    return (AbsenceResolution.objects.select_for_update()
            .filter(missed_lesson_id=missed_lesson_id, student_id=student_id)
            .values('id', 'status').first())


def students_not_absent(missed_lesson_id, student_ids) -> list[int]:
    absent = set(LessonAttendance.objects.filter(
        lesson_id=missed_lesson_id, student_id__in=student_ids, present=False
    ).values_list('student_id', flat=True))
    return [sid for sid in student_ids if sid not in absent]


def assign_pending(resolution_id, *, assigned_teacher_id, scheduled_date, scheduled_time,
                   duration_minutes) -> None:
    """pending → makeup_scheduled с параметрами доп.урока."""
    AbsenceResolution.objects.filter(id=resolution_id).update(
        status=MAKEUP_SCHEDULED, assigned_teacher_id=assigned_teacher_id,
        scheduled_date=scheduled_date, scheduled_time=scheduled_time,
        duration_minutes=duration_minutes)


def create_scheduled_direct(*, missed_lesson_id, student_id, assigned_teacher_id,
                            scheduled_date, scheduled_time, duration_minutes) -> int:
    """Edge: pending-строки нет (пропуск до релиза) → создать сразу makeup_scheduled."""
    obj = AbsenceResolution.objects.create(
        missed_lesson_id=missed_lesson_id, student_id=student_id,
        assigned_teacher_id=assigned_teacher_id, status=MAKEUP_SCHEDULED,
        scheduled_date=scheduled_date, scheduled_time=scheduled_time,
        duration_minutes=duration_minutes)
    return obj.id


def back_to_pending(resolution_id) -> None:
    """Отмена назначения / откат факта → pending. Сбрасывает параметры и факт."""
    AbsenceResolution.objects.filter(id=resolution_id).update(
        status=PENDING, assigned_teacher_id=None, scheduled_date=None,
        scheduled_time=None, duration_minutes=None, fact_lesson_id=None)


def mark_makeup_done(resolution_id, *, fact_lesson_id) -> None:
    AbsenceResolution.objects.filter(id=resolution_id).update(
        status=MAKEUP_DONE, fact_lesson_id=fact_lesson_id)


def mark_burned(resolution_id, *, fact_lesson_id) -> None:
    """pending → burned с привязкой к созданному burned-факту (Lesson)."""
    AbsenceResolution.objects.filter(id=resolution_id).update(
        status=BURNED, fact_lesson_id=fact_lesson_id)


def pending_count() -> int:
    """Число необработанных пропусков (status=pending) — для бейджа в сайдбаре."""
    return AbsenceResolution.objects.filter(status=PENDING).count()


def has_active_resolution(missed_lesson_id, student_id) -> bool:
    """Уже назначено / проведено / сожжено? (pending НЕ считается — его как раз
    разрешают). Guard от повторного назначения или сжигания уже закрытого пропуска."""
    return (AbsenceResolution.objects
            .filter(missed_lesson_id=missed_lesson_id, student_id=student_id,
                    status__in=[MAKEUP_SCHEDULED, MAKEUP_DONE, BURNED]).exists())


def delete_open_for_student(student_id) -> int:
    """Уход ученика: удалить его pending + makeup_scheduled (нет факта/денег).
    makeup_done не трогаем. Возвращает число удалённых."""
    qs = AbsenceResolution.objects.filter(
        student_id=student_id, status__in=[PENDING, MAKEUP_SCHEDULED])
    n = qs.count()
    qs.delete()
    return n


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
