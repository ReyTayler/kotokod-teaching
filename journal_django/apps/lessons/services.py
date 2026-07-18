"""
LessonsService — оркестрация записи урока (Lesson+attendance+счётчики+Payroll+
привязка к плановому занятию+синхронизация «Продлений»).

record_lesson — единое ядро (см. docs/superpowers/specs/2026-07-14-unify-lesson-recording-design.md),
используется и этим приложением (create_lesson_full — тонкий адаптер для
admin SPA), и apps.teacher_spa.services.submit_lesson. Транзакция управляется
ЗДЕСЬ (как submit_lesson); repository выполняет ORM-операции, cross-app
вызовы (link_facts/balances_for_students/renewals) — тоже здесь, не в repository.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.db import transaction

from apps.groups.models import Group
from apps.lessons import repository
from apps.lessons.exceptions import LessonHasMakeupResolutions, SystemLessonProtected
from apps.lessons.models import Lesson
from apps.payroll.calculator import calculate_payment, calculate_penalty
from apps.scheduling.repository import link_facts

# Подтипы уроков, которыми владеет apps.extra_lessons (факты доп.урока/сгорания).
# Общий CRUD /api/admin/lessons их не трогает — только откат из раздела «Доп.уроки».
# 'burned' появится в Фазе 2; включён заранее (таких строк ещё нет — безвредно).
_SYSTEM_LESSON_TYPES = ('extra', 'burned')


def _assert_not_system_lesson(lesson_id: int) -> None:
    """Бросает SystemLessonProtected, если урок — системный (extra/burned).
    No-op для несуществующего урока (тип None) — тогда работает обычный путь 404."""
    lesson_type = (
        Lesson.objects.filter(id=lesson_id).values_list('lesson_type', flat=True).first()
    )
    if lesson_type in _SYSTEM_LESSON_TYPES:
        raise SystemLessonProtected(lesson_type)


def _step(duration_minutes) -> Decimal:
    return Decimal('0.5') if duration_minutes == 45 else Decimal('1')


def record_lesson(*,
    lesson_date: str,
    teacher_id: int,
    group_id: int,
    original_teacher_id: Optional[int],
    lesson_number,
    lesson_duration_minutes: int,
    lesson_type: str,
    record_url: Optional[str],
    submitted_by_token: str,
    submit_date: str,
    attendance: list[dict],
) -> dict:
    """
    Единое ядро записи урока. Атомарно создаёт Lesson+LessonAttendance,
    инкрементирует group_memberships.lessons_done, привязывает факт к
    planned_lessons (link_facts), создаёт Payroll (сервер считает
    payment/penalty сам — клиентского payroll не принимает), синхронизирует
    авто-стадию «Продлений» после коммита.

    attendance: [{'student_id': int, 'present': bool}, ...] — student_id уже
    резолвлен вызывающей стороной (teacher_spa резолвит по имени, admin SPA
    передаёт id напрямую).

    submit_date — для calculate_penalty: teacher SPA передаёт «сегодня»
    (штраф за просрочку отчёта), admin SPA передаёт submit_date=lesson_date
    всегда (админ не должен штрафоваться за административную запись задним
    числом — см. design doc).

    Бросает UnpaidAttendanceBlocked (apps.lessons.exceptions), если у кого-то
    из present-учеников остаток оплаченных уроков <= 0 — ДО открытия транзакции,
    ничего не пишется.

    Возвращает {'lesson_id': int, 'payment': int, 'penalty': int}.
    """
    present_student_ids = [a['student_id'] for a in attendance if a['present']]
    repository.assert_students_paid(present_student_ids)

    is_half = lesson_duration_minutes == 45
    step = _step(lesson_duration_minutes)
    total_students = len(attendance)
    present_count = len(present_student_ids)

    payment = calculate_payment(total_students, present_count, is_half)
    penalty = calculate_penalty(lesson_date, submit_date, present_count)

    direction_id = (
        Group.objects.filter(id=group_id).values_list('direction_id', flat=True).first()
        if present_student_ids else None
    )

    with transaction.atomic():
        lesson_id = repository.insert_lesson({
            'lesson_date': lesson_date,
            'teacher_id': teacher_id,
            'group_id': group_id,
            'original_teacher_id': original_teacher_id,
            'lesson_number': lesson_number,
            'lesson_duration_minutes': lesson_duration_minutes,
            'lesson_type': lesson_type,
            'record_url': record_url,
            'submitted_by_token': submitted_by_token,
        })
        # Привязать факт к плановой строке (planned_lessons.fact_lesson_id/status='done'),
        # иначе занятие остаётся «не проведено» в расписании/календаре.
        link_facts(group_id)
        repository.increment_lessons_done(group_id, present_student_ids, step)
        repository.insert_attendance(lesson_id, attendance)
        repository.insert_payroll({
            'lesson_id': lesson_id,
            'teacher_id': teacher_id,
            'total_students': total_students,
            'present_count': present_count,
            'payment': payment,
            'penalty': penalty,
        })

        # Авто-создание «пропусков, требующих решения» — только для обычных уроков
        # (extra/burned сами являются РЕЗУЛЬТАТОМ решения, пропусков не порождают).
        # Ленивый импорт: apps.extra_lessons.repository импортит apps.lessons.models,
        # прямой top-level импорт здесь завёл бы цикл.
        if lesson_type == 'regular':
            absent_student_ids = [a['student_id'] for a in attendance if not a['present']]
            if absent_student_ids:
                from apps.extra_lessons import services as extra_lessons_services
                extra_lessons_services.autocreate_pending_for_lesson(lesson_id, absent_student_ids)

        for sid in present_student_ids:
            transaction.on_commit(lambda sid=sid: repository._sync_renewal_stage(sid, direction_id))

    return {'lesson_id': lesson_id, 'payment': payment, 'penalty': penalty}


def list_lessons(
    page: int = 1,
    page_size: int = 50,
    sort_by: str = 'lesson_date',
    sort_dir: str = 'desc',
    filters: Optional[dict] = None,
) -> dict:
    return repository.list_lessons(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        filters=filters,
    )


def get_lesson_full(lesson_id: int) -> Optional[dict]:
    return repository.get_lesson_full(lesson_id)


def create_lesson_full(data: dict) -> dict:
    """
    Admin SPA — тонкий адаптер над record_lesson. submit_date=lesson_date
    всегда (админ не штрафуется за административную запись задним числом).
    Возвращает {'lesson_id', 'payment', 'penalty'} (view делает повторный
    get_lesson_full для полного ответа, как раньше).
    """
    return record_lesson(
        lesson_date=data['lesson_date'],
        teacher_id=data['teacher_id'],
        group_id=data['group_id'],
        original_teacher_id=data.get('original_teacher_id'),
        lesson_number=data['lesson_number'],
        lesson_duration_minutes=data.get('lesson_duration_minutes') or 90,
        lesson_type=data.get('lesson_type') or 'regular',
        record_url=data.get('record_url') or None,
        submitted_by_token=data.get('submitted_by_token') or 'admin-imported',
        submit_date=data['lesson_date'],
        attendance=data.get('attendance') or [],
    )


def update_lesson(lesson_id: int, fields: dict) -> Optional[dict]:
    _assert_not_system_lesson(lesson_id)
    return repository.update_lesson(lesson_id, fields)


def _assert_no_makeup_done_resolutions(lesson_id: int) -> None:
    """Бросает LessonHasMakeupResolutions, если по пропускам этого урока уже
    проведён доп.урок (makeup_done). Без этого гарда DB-level ON DELETE CASCADE
    (миграция extra_lessons.0007) снёс бы makeup_done-резолюцию каскадом,
    осиротив факт доп.урока + Payroll и не откатив apply_makeup_attendance.
    pending/makeup_scheduled (без факта/денег) удалять каскадом безопасно."""
    from apps.extra_lessons.models import MAKEUP_DONE, AbsenceResolution
    if AbsenceResolution.objects.filter(
        missed_lesson_id=lesson_id, status=MAKEUP_DONE,
    ).exists():
        raise LessonHasMakeupResolutions()


def delete_lesson_full(lesson_id: int) -> bool:
    _assert_not_system_lesson(lesson_id)
    _assert_no_makeup_done_resolutions(lesson_id)
    return repository.delete_lesson_full(lesson_id)


def update_attendance_cell(lesson_id: int, student_id: int, present: bool) -> bool:
    _assert_not_system_lesson(lesson_id)
    return repository.update_attendance_cell(lesson_id, student_id, present)
