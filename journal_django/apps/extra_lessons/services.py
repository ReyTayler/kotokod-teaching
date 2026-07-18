"""
ExtraLessonsService — оркестрация назначения/отмены/фиксации/удаления
доп.урока (пер-ученик AbsenceResolution). Транзакции — здесь (как
apps.lessons.services.record_lesson); repository — чистые ORM-операции.
"""
from __future__ import annotations

import datetime
from typing import Optional

from django.db import transaction

from apps.audit.services import log_event
from apps.extra_lessons import repository
from apps.extra_lessons.exceptions import (
    DuplicateAssignment, MissedLessonNotFound, NotTeachersAssignment, StudentNotAbsent,
)
from apps.extra_lessons.models import MAKEUP_DONE, MAKEUP_SCHEDULED, PENDING
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
    """Назначить доп.урок по multi-select. Для каждого ученика: найти его
    pending-резолюцию (авто-создана при записи урока) и перевести в
    makeup_scheduled; если pending нет (пропуск до релиза) — создать сразу
    makeup_scheduled. Валидации:
      - missed_lesson_id обязан существовать (иначе MissedLessonNotFound)
      - каждый student_id обязан быть реально отмечен present=false на
        missed_lesson_id (иначе StudentNotAbsent) — доп.урок компенсирует
        только настоящий пропуск, не присутствовавшего/постороннего ученика
      - ни у одного из student_ids не должно быть уже активной резолюции
        (makeup_scheduled/makeup_done) за этот же пропуск (иначе
        DuplicateAssignment)
      - ни у одного из student_ids не должно быть balance <= 0 (иначе
        UnpaidAttendanceBlocked, apps.lessons.exceptions) — доп.урок не должен
        компенсировать пропуск ученику, у которого на МОМЕНТ назначения уже
        нет оплаченных уроков (если баланс к моменту назначения уже исчерпан
        другими посещениями, компенсация задним числом создала бы
        неоплаченный урок).

    Возвращает {'created': N, 'resolution_ids': [...]}.
    """
    missed_lesson_id = data['missed_lesson_id']
    if not Lesson.objects.filter(id=missed_lesson_id).exists():
        raise MissedLessonNotFound(f'Урок #{missed_lesson_id} не найден.')

    student_ids = data['student_ids']

    not_absent = repository.students_not_absent(missed_lesson_id, student_ids)
    if not_absent:
        names = list(
            Student.objects.filter(id__in=not_absent).values_list('full_name', flat=True)
        )
        raise StudentNotAbsent(names)

    duplicates = [
        sid for sid in student_ids
        if repository.has_active_resolution(missed_lesson_id, sid)
    ]
    if duplicates:
        names = list(
            Student.objects.filter(id__in=duplicates).values_list('full_name', flat=True)
        )
        raise DuplicateAssignment(names)

    lessons_repository.assert_students_paid(student_ids)

    scheduled_date = _to_date(data['scheduled_date'])
    scheduled_time = _to_time(data['scheduled_time'])
    duration_minutes = data['duration_minutes']
    resolution_ids = []
    with transaction.atomic():
        for sid in student_ids:
            locked = repository.lock_for_assign(missed_lesson_id, sid)
            if locked is None:
                rid = repository.create_scheduled_direct(
                    missed_lesson_id=missed_lesson_id, student_id=sid,
                    assigned_teacher_id=data['teacher_id'], scheduled_date=scheduled_date,
                    scheduled_time=scheduled_time, duration_minutes=duration_minutes)
            elif locked['status'] != PENDING:
                # Гонка: между has_active_resolution и локом статус ушёл.
                raise DuplicateAssignment([str(sid)])
            else:
                repository.assign_pending(
                    locked['id'], assigned_teacher_id=data['teacher_id'],
                    scheduled_date=scheduled_date, scheduled_time=scheduled_time,
                    duration_minutes=duration_minutes)
                rid = locked['id']
            resolution_ids.append(rid)
    log_event(
        'extra_lesson_assign',
        actor_email=_actor(request),
        target_id=resolution_ids[0],
        meta={
            'missed_lesson_id': missed_lesson_id,
            'student_ids': student_ids,
            'resolution_ids': resolution_ids,
        },
        request=request,
    )
    return {'created': len(resolution_ids), 'resolution_ids': resolution_ids}


def cancel_assignment(resolution_id: int, request) -> Optional[dict]:
    """Отмена назначенного доп.урока: makeup_scheduled → pending (пропуск снова
    ждёт решения). None → нет резолюции (404). ValueError → не makeup_scheduled
    (view → 409)."""
    full = repository.get_resolution_full(resolution_id)
    if full is None:
        return None
    if full['status'] != MAKEUP_SCHEDULED:
        raise ValueError('Отменить можно только назначенный (ещё не проведённый) доп.урок.')
    repository.back_to_pending(resolution_id)
    log_event(
        'extra_lesson_cancel', actor_email=_actor(request),
        target_id=resolution_id, meta={}, request=request,
    )
    return repository.get_resolution_full(resolution_id)


def get_assignment_for_teacher(resolution_id: int, teacher_id: int) -> Optional[dict]:
    """None → не найдено ИЛИ принадлежит другому преподавателю (единый 404 —
    не раскрываем чужим существование резолюции)."""
    full = repository.get_resolution_full(resolution_id)
    if full is None or full['assigned_teacher_id'] != teacher_id:
        return None
    return full


def record(
    resolution_id: int,
    *,
    teacher_id: int,
    present: bool,
    record_url: Optional[str],
    submitted_by_token: str,
    submit_date: str,
    request,
) -> Optional[dict]:
    """
    Фиксация проведения доп.урока для ОДНОЙ резолюции (один ученик). Атомарно:
      1. Lesson(lesson_type='extra') — group/lesson_number унаследованы от
         пропущенного урока, teacher/duration — от резолюции.
      2. LessonAttendance ученика этой резолюции (present, как отметил учитель).
      3. Payroll — payment=200×present (calculate_extra_lesson_payment),
         penalty — та же формула просрочки, что у обычных уроков.
      4. Если present — apply_makeup_attendance на ИСХОДНОМ уроке.
      5. AbsenceResolution → status=makeup_done, fact_lesson=новый Lesson.

    None → резолюции нет (view → 404). NotTeachersAssignment → чужая резолюция
    (view → 403). ValueError → не в статусе makeup_scheduled (view → 409).
    UnpaidAttendanceBlocked (apps.lessons.exceptions) → у present-ученика
    balance <= 0 НА МОМЕНТ проведения (view → 400) — проверяется заново здесь,
    а не только при create_assignment, потому что между назначением и
    фактическим проведением баланс мог измениться (ученик израсходовал остаток
    другими уроками, оплата аннулирована и т.п.).
    """
    full = repository.get_resolution_full(resolution_id)
    if full is None:
        return None
    if full['assigned_teacher_id'] != teacher_id:
        raise NotTeachersAssignment('Это назначение принадлежит другому преподавателю.')
    # Быстрая проверка без блокировки — не гейтит запись, только 404/403.
    # Авторитетная проверка статуса — под select_for_update() ниже, в atomic().
    if full['status'] != MAKEUP_SCHEDULED:
        raise ValueError('Доп.урок можно провести только из статуса «назначен».')

    if present:
        lessons_repository.assert_students_paid([full['student_id']])

    present_count = 1 if present else 0
    payment = calculate_extra_lesson_payment(present_count)
    penalty = calculate_penalty(
        full['scheduled_date'].isoformat(), submit_date, present_count,
    )

    with transaction.atomic():
        # Авторитетная проверка статуса под блокировкой строки — гонка двух
        # параллельных record() иначе создала бы два Lesson-факта/Payroll
        # (см. lock_for_record).
        locked = repository.lock_for_record(resolution_id)
        if locked is None:
            return None
        if locked['assigned_teacher_id'] != teacher_id:
            raise NotTeachersAssignment('Это назначение принадлежит другому преподавателю.')
        if locked['status'] != MAKEUP_SCHEDULED:
            raise ValueError('Доп.урок можно провести только из статуса «назначен».')

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
        lessons_repository.insert_attendance(
            lesson_id, [{'student_id': locked['student_id'], 'present': present}],
        )
        lessons_repository.insert_payroll({
            'lesson_id': lesson_id,
            'teacher_id': teacher_id,
            'total_students': 1,
            'present_count': present_count,
            'payment': payment,
            'penalty': penalty,
        })
        if present:
            lessons_repository.apply_makeup_attendance(
                locked['missed_lesson_id'], locked['student_id'],
            )
        repository.mark_makeup_done(resolution_id, fact_lesson_id=lesson_id)

    log_event(
        'extra_lesson_record', actor_email=_actor(request),
        target_id=resolution_id,
        meta={'lesson_id': lesson_id, 'payment': payment, 'penalty': penalty},
        request=request,
    )
    return {'lesson_id': lesson_id, 'payment': payment, 'penalty': penalty}


def delete_fact(resolution_id: int, request) -> bool:
    """
    Откатывает проведённый доп.урок: возвращает исходному уроку прежнюю
    посещаемость/lessons_done, удаляет Payroll+Lesson доп.урока, возвращает
    резолюцию в status=pending. ValueError → резолюция не в статусе makeup_done
    (view → 409). False → резолюции нет (view → 404).
    """
    full = repository.get_resolution_full(resolution_id)
    if full is None:
        return False
    if full['status'] != MAKEUP_DONE:
        raise ValueError('Удалить факт можно только у проведённого доп.урока.')

    with transaction.atomic():
        # Авторитетная проверка статуса под блокировкой строки — гонка двух
        # параллельных delete_fact() иначе оба прошли бы неблокирующую проверку
        # выше и оба попытались бы удалить один и тот же fact_lesson (см.
        # lock_for_delete).
        locked = repository.lock_for_delete(resolution_id)
        if locked is None:
            return False
        if locked['status'] != MAKEUP_DONE:
            raise ValueError('Удалить факт можно только у проведённого доп.урока.')

        fact_lesson_id = locked['fact_lesson_id']
        present_ids = list(
            Lesson.objects.get(id=fact_lesson_id).attendance
            .filter(present=True).values_list('student_id', flat=True)
        )
        for sid in present_ids:
            lessons_repository.revert_makeup_attendance(locked['missed_lesson_id'], sid)
        Payroll.objects.filter(lesson_id=fact_lesson_id).delete()
        Lesson.objects.filter(id=fact_lesson_id).delete()
        repository.back_to_pending(resolution_id)

    log_event(
        'extra_lesson_delete', actor_email=_actor(request),
        target_id=resolution_id, meta={'fact_lesson_id': fact_lesson_id}, request=request,
    )
    return True


def autocreate_pending_for_lesson(missed_lesson_id, absent_student_ids) -> int:
    """Вызывается из record_lesson (та же транзакция) для обычных уроков.
    Создаёт pending по отсутствовавшим. Идемпотентно."""
    return repository.autocreate_pending(missed_lesson_id, absent_student_ids)


def cleanup_on_student_leave(student_id) -> int:
    """Уход/архивация ученика: удалить его pending + makeup_scheduled резолюции.
    makeup_done не трогаем. Вызывается из apps.students.services.change_student_status."""
    return repository.delete_open_for_student(student_id)


def list_assignments(
    page: int = 1, page_size: int = 50, sort_by: str = 'scheduled_date',
    sort_dir: str = 'desc', filters: Optional[dict] = None,
) -> dict:
    return repository.list_resolutions(
        page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir, filters=filters,
    )
