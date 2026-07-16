"""
ExtraLessonsService — оркестрация назначения/отмены/фиксации/удаления
доп.урока. Транзакции — здесь (как apps.lessons.services.record_lesson);
repository — чистые ORM-операции.
"""
from __future__ import annotations

import datetime
from typing import Optional

from django.db import transaction

from apps.audit.services import log_event
from apps.extra_lessons import repository
from apps.extra_lessons.exceptions import (
    DuplicateAssignment, MissedLessonNotFound, NotTeachersAssignment,
)
from apps.extra_lessons.models import DONE, SCHEDULED
from apps.lessons import repository as lessons_repository
from apps.lessons.models import Lesson
from apps.payroll.calculator import calculate_extra_lesson_payment, calculate_penalty
from apps.payroll.models import Payroll
from apps.students.models import Student

# insert_payroll (apps.lessons.repository) принимает ровно этот набор полей —
# переиспользуем его вместо повторной ORM-вставки Payroll здесь (единственное
# отличие доп.урока — ОТКУДА берутся payment/penalty, см. record() ниже).


def _actor(request):
    return getattr(getattr(request, 'user', None), 'email', None)


def _to_date(value: str) -> datetime.date:
    return datetime.date.fromisoformat(value)


def _to_time(value: str) -> datetime.time:
    parts = [int(x) for x in value.split(':')]
    return datetime.time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)


def create_assignment(data: dict, request) -> dict:
    """
    Создаёт назначение доп.урока. Валидация:
      - missed_lesson_id обязан существовать (иначе MissedLessonNotFound)
      - ни у одного из student_ids не должно быть уже активного назначения
        за этот же пропуск (иначе DuplicateAssignment)
    """
    missed_lesson_id = data['missed_lesson_id']
    if not Lesson.objects.filter(id=missed_lesson_id).exists():
        raise MissedLessonNotFound(f'Урок #{missed_lesson_id} не найден.')

    student_ids = data['student_ids']
    duplicates = [
        sid for sid in student_ids
        if repository.has_active_assignment(missed_lesson_id, sid)
    ]
    if duplicates:
        names = list(
            Student.objects.filter(id__in=duplicates).values_list('full_name', flat=True)
        )
        raise DuplicateAssignment(names)

    assignment_id = repository.create_assignment(
        missed_lesson_id=missed_lesson_id,
        teacher_id=data['teacher_id'],
        student_ids=student_ids,
        scheduled_date=_to_date(data['scheduled_date']),
        scheduled_time=_to_time(data['scheduled_time']),
        duration_minutes=data['duration_minutes'],
    )
    log_event(
        'extra_lesson_create',
        actor_email=_actor(request),
        target_id=assignment_id,
        meta={'missed_lesson_id': missed_lesson_id, 'student_ids': student_ids},
        request=request,
    )
    return repository.get_assignment_full(assignment_id)


def cancel_assignment(assignment_id: int, request) -> Optional[dict]:
    """None → назначения нет (404). ValueError → уже done/cancelled (view → 409)."""
    if repository.get_assignment_full(assignment_id) is None:
        return None
    repository.cancel_assignment(assignment_id)
    log_event(
        'extra_lesson_cancel', actor_email=_actor(request),
        target_id=assignment_id, meta={}, request=request,
    )
    return repository.get_assignment_full(assignment_id)


def get_assignment_for_teacher(assignment_id: int, teacher_id: int) -> Optional[dict]:
    """None → не найдено ИЛИ принадлежит другому преподавателю (единый 404 —
    не раскрываем чужим существование назначения)."""
    full = repository.get_assignment_full(assignment_id)
    if full is None or full['teacher_id'] != teacher_id:
        return None
    return full


def record(
    assignment_id: int,
    *,
    teacher_id: int,
    attendance: list[dict],
    record_url: Optional[str],
    submitted_by_token: str,
    submit_date: str,
    request,
) -> Optional[dict]:
    """
    Фиксация проведения доп.урока. Атомарно:
      1. Lesson(lesson_type='extra') — group/lesson_number унаследованы от
         пропущенного урока, teacher/duration — от назначения.
      2. LessonAttendance для участников ЭТОГО доп.урока (кто реально пришёл).
      3. Payroll — payment=200×present (calculate_extra_lesson_payment),
         penalty — та же формула просрочки, что у обычных уроков.
      4. Для присутствовавших — apply_makeup_attendance на ИСХОДНОМ уроке.
      5. ExtraLessonAssignment → status=done, fact_lesson=новый Lesson.

    None → назначения нет (view → 404). NotTeachersAssignment → чужое
    назначение (view → 403). ValueError → уже done/cancelled (view → 409).
    """
    full = repository.get_assignment_full(assignment_id)
    if full is None:
        return None
    if full['teacher_id'] != teacher_id:
        raise NotTeachersAssignment('Это назначение принадлежит другому преподавателю.')
    # Быстрая проверка без блокировки — не гейтит запись, только 404/403.
    # Авторитетная проверка статуса — под select_for_update() ниже, в atomic().
    if full['status'] != SCHEDULED:
        raise ValueError('Доп.урок уже проведён или отменён.')

    # Дефенс-в-глубину: считаем присутствовавших только среди РЕАЛЬНЫХ
    # участников назначения — сериализатор (задача позже) даёт настоящую
    # 400-валидацию для внешнего вызывающего, здесь же просто отбрасываем
    # записи посторонних student_id молча.
    participant_ids = set(repository.participant_student_ids(assignment_id))
    attendance = [a for a in attendance if a['student_id'] in participant_ids]

    present_count = sum(1 for a in attendance if a['present'])
    payment = calculate_extra_lesson_payment(present_count)
    penalty = calculate_penalty(
        full['scheduled_date'].isoformat(), submit_date, present_count,
    )

    with transaction.atomic():
        # Авторитетная проверка статуса под блокировкой строки — гонка двух
        # параллельных record() иначе создала бы два Lesson-факта/Payroll
        # (см. lock_assignment_for_record).
        locked = repository.lock_assignment_for_record(assignment_id)
        if locked is None:
            return None
        if locked['teacher_id'] != teacher_id:
            raise NotTeachersAssignment('Это назначение принадлежит другому преподавателю.')
        if locked['status'] != SCHEDULED:
            raise ValueError('Доп.урок уже проведён или отменён.')

        lesson_id = lessons_repository.insert_lesson({
            'lesson_date': locked['scheduled_date'].isoformat(),
            'teacher_id': teacher_id,
            'group_id': locked['missed_lesson_group_id'],
            'original_teacher_id': None,
            # lesson_number наследуется от пропущенного урока — доп.урок
            # компенсирует именно ЭТУ позицию курса, показываем это в списке
            # уроков (lesson_type='extra' отличает его от исходного).
            'lesson_number': Lesson.objects.get(id=locked['missed_lesson_id']).lesson_number,
            'lesson_duration_minutes': locked['duration_minutes'],
            'lesson_type': 'extra',
            'record_url': record_url,
            'submitted_by_token': submitted_by_token,
        })
        lessons_repository.insert_attendance(lesson_id, attendance)
        lessons_repository.insert_payroll({
            'lesson_id': lesson_id,
            'teacher_id': teacher_id,
            'total_students': len(attendance),
            'present_count': present_count,
            'payment': payment,
            'penalty': penalty,
        })
        for a in attendance:
            if a['present']:
                lessons_repository.apply_makeup_attendance(locked['missed_lesson_id'], a['student_id'])
        repository.mark_done(assignment_id, fact_lesson_id=lesson_id)

    log_event(
        'extra_lesson_record', actor_email=_actor(request),
        target_id=assignment_id,
        meta={'lesson_id': lesson_id, 'payment': payment, 'penalty': penalty},
        request=request,
    )
    return {'lesson_id': lesson_id, 'payment': payment, 'penalty': penalty}


def delete_fact(assignment_id: int, request) -> bool:
    """
    Откатывает проведённый доп.урок: возвращает исходному уроку прежнюю
    посещаемость/lessons_done, удаляет Payroll+Lesson доп.урока, возвращает
    назначение в status=scheduled. ValueError → назначение не в статусе done
    (view → 409). False → назначения нет (view → 404).
    """
    full = repository.get_assignment_full(assignment_id)
    if full is None:
        return False
    if full['status'] != DONE:
        raise ValueError('Удалить факт можно только у проведённого доп.урока.')

    fact_lesson_id = full['fact_lesson_id']
    with transaction.atomic():
        present_ids = list(
            Lesson.objects.get(id=fact_lesson_id).attendance
            .filter(present=True).values_list('student_id', flat=True)
        )
        for sid in present_ids:
            lessons_repository.revert_makeup_attendance(full['missed_lesson_id'], sid)
        Payroll.objects.filter(lesson_id=fact_lesson_id).delete()
        Lesson.objects.filter(id=fact_lesson_id).delete()
        repository.reset_to_scheduled(assignment_id)

    log_event(
        'extra_lesson_delete', actor_email=_actor(request),
        target_id=assignment_id, meta={'fact_lesson_id': fact_lesson_id}, request=request,
    )
    return True


def list_assignments(
    page: int = 1, page_size: int = 50, sort_by: str = 'scheduled_date',
    sort_dir: str = 'desc', filters: Optional[dict] = None,
) -> dict:
    return repository.list_assignments(
        page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir, filters=filters,
    )
