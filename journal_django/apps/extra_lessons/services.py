"""
ExtraLessonsService — оркестрация назначения/отмены/фиксации/удаления
доп.урока (пер-ученик AbsenceResolution). Транзакции — здесь (как
apps.lessons.services.record_lesson); repository — чистые ORM-операции.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Optional

from django.db import IntegrityError, transaction

from apps.audit.services import log_event
from apps.extra_lessons import repository
from apps.extra_lessons.exceptions import (
    DuplicateAssignment, MissedLessonNotFound, NotTeachersAssignment, StudentNotAbsent,
)
from apps.extra_lessons.models import BURNED, MAKEUP_DONE, MAKEUP_SCHEDULED, PENDING
from apps.groups.models import Group
from apps.lessons import repository as lessons_repository
from apps.lessons.models import Lesson
from apps.payroll.calculator import calculate_extra_lesson_payment, calculate_penalty
from apps.payroll.models import Payroll
from apps.students.models import Student
from apps.teachers.models import Teacher

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


def _step(duration_minutes) -> Decimal:
    """half-lesson инвариант: 45 мин → 0.5 урока, иначе 1 (как apps.lessons)."""
    return Decimal('0.5') if duration_minutes == 45 else Decimal('1')


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
                # Edge: pending-строки нет (пропуск до релиза). FOR UPDATE по нулю
                # строк не лочит → две параллельные вставки конфликтуют по полному
                # UNIQUE; переводим IntegrityError в чистый DuplicateAssignment (409),
                # а не 500.
                try:
                    rid = repository.create_scheduled_direct(
                        missed_lesson_id=missed_lesson_id, student_id=sid,
                        assigned_teacher_id=data['teacher_id'], scheduled_date=scheduled_date,
                        scheduled_time=scheduled_time, duration_minutes=duration_minutes)
                except IntegrityError:
                    raise DuplicateAssignment([str(sid)])
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
      1. Lesson(lesson_type='extra') — group/lesson_number/длительность унаследованы
         от ПРОПУЩЕННОГО урока (длительность = вес потребления исходного занятия),
         teacher — от резолюции.
      2. LessonAttendance ученика этой резолюции (present, как отметил учитель).
      3. Payroll — payment=200×present (calculate_extra_lesson_payment),
         penalty — та же формула просрочки, что у обычных уроков.
      4. Если present — инкремент group_memberships.lessons_done в группе
         пропуска на вес исходного урока. Потребление баланса идёт от САМОГО факта
         доп.урока (present=true), а ИСХОДНЫЙ пропуск остаётся present=false.
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

        missed_lesson = Lesson.objects.get(id=locked['missed_lesson_id'])
        lesson_id = lessons_repository.insert_lesson({
            'lesson_date': locked['scheduled_date'].isoformat(),
            'teacher_id': teacher_id,
            'group_id': locked['missed_lesson_group_id'],
            'original_teacher_id': None,
            # lesson_number наследуется от пропущенного урока — доп.урок
            # компенсирует именно ЭТУ позицию курса, показываем это в списке
            # уроков (lesson_type='extra' отличает его от исходного).
            'lesson_number': missed_lesson.lesson_number,
            # Длительность = длительность ИСХОДНОГО пропущенного урока (не
            # duration_minutes резолюции): вес потребления факта доп.урока обязан
            # совпасть с весом компенсируемого занятия (half-lesson: 45→0.5).
            'lesson_duration_minutes': missed_lesson.lesson_duration_minutes,
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
            # Потребление идёт от самого факта доп.урока (present=true, длительность
            # исходного урока). Исходный пропуск остаётся present=false навсегда —
            # ретроактивная отметка исходного занятия больше не делается. Двигаем
            # lessons_done группы пропуска на вес исходного урока (как record_lesson).
            step = _step(missed_lesson.lesson_duration_minutes)
            lessons_repository.increment_lessons_done(
                locked['missed_lesson_group_id'], [locked['student_id']], step,
            )
            # Доп.урок двигает авто-стадию «Продлений» (как обычный урок в
            # record_lesson) — раньше это делал apply_makeup_attendance через
            # on_commit; теперь делаем явно, т.к. потребление ушло на extra-факт.
            direction_id = Group.objects.filter(
                id=locked['missed_lesson_group_id']).values_list('direction_id', flat=True).first()
            transaction.on_commit(
                lambda: lessons_repository.sync_renewal_stage(locked['student_id'], direction_id))
        repository.mark_makeup_done(resolution_id, fact_lesson_id=lesson_id)

    log_event(
        'extra_lesson_record', actor_email=_actor(request),
        target_id=resolution_id,
        meta={'lesson_id': lesson_id, 'payment': payment, 'penalty': penalty},
        request=request,
    )
    return {'lesson_id': lesson_id, 'payment': payment, 'penalty': penalty}


def _burn_payment_teacher_id(missed_lesson) -> int:
    """Флет-надбавку за сгорание получает преподаватель пропущенного урока. Если
    он уволен (Teacher.active=False) — надбавка уходит ТЕКУЩЕМУ преподавателю
    группы (Group.teacher_id): уволенному платить нельзя. Если и текущий не
    найден — остаётся исходный (не допускаем NULL teacher_id в Payroll)."""
    active = Teacher.objects.filter(
        id=missed_lesson.teacher_id).values_list('active', flat=True).first()
    if active:
        return missed_lesson.teacher_id
    current = Group.objects.filter(
        id=missed_lesson.group_id).values_list('teacher_id', flat=True).first()
    return current or missed_lesson.teacher_id


def burn(resolution_id: int, *, request, burn_date: str) -> Optional[dict]:
    """
    «Сжечь» пропуск: pending → burned. Симметрично проведённому доп.уроку —
    создаёт отдельную запись-урок Lesson(lesson_type='burned') present=true для
    ученика, дата=burn_date (сегодня), длительность=ИСХОДНОГО урока (вес
    потребления, half-lesson 45→0.5), teacher=преподаватель пропущенного урока
    (уволенному — текущему преп. группы, см. _burn_payment_teacher_id). Флет
    payment=200 (calculate_extra_lesson_payment), penalty=0 (админское действие,
    submit_date==lesson_date). Урок списывается с баланса штатно (present=true на
    burned-факте в свою дату); ИСХОДНЫЙ пропуск остаётся present=false.

    None → резолюции нет (view → 404). ValueError → не в статусе pending
    (view → 409). UnpaidAttendanceBlocked → у ученика balance<=0 (view → 400):
    сжигать нечего.
    """
    full = repository.get_resolution_full(resolution_id)
    if full is None:
        return None
    if full['status'] != PENDING:
        raise ValueError('Сжечь можно только нерешённый (pending) пропуск.')

    # Нельзя сжечь урок ученику без оплаченного остатка (нечего сжигать).
    lessons_repository.assert_students_paid([full['student_id']])

    payment = calculate_extra_lesson_payment(1)
    penalty = 0  # админское действие: submit_date == lesson_date

    with transaction.atomic():
        # Авторитетная проверка статуса под блокировкой строки — гонка двух
        # параллельных burn() иначе создала бы два burned-факта + Payroll.
        locked = repository.lock_for_record(resolution_id)
        if locked is None:
            return None
        if locked['status'] != PENDING:
            raise ValueError('Сжечь можно только нерешённый (pending) пропуск.')

        missed_lesson = Lesson.objects.get(id=locked['missed_lesson_id'])
        payment_teacher_id = _burn_payment_teacher_id(missed_lesson)
        lesson_id = lessons_repository.insert_lesson({
            'lesson_date': burn_date,
            'teacher_id': payment_teacher_id,
            'group_id': locked['missed_lesson_group_id'],
            'original_teacher_id': None,
            'lesson_number': missed_lesson.lesson_number,
            # Вес списания = вес пропущенного занятия (half-lesson 45→0.5).
            'lesson_duration_minutes': missed_lesson.lesson_duration_minutes,
            'lesson_type': 'burned',
            'record_url': None,
            # Уникализирует lessons_natural_key (date,group,number,token): два
            # ученика, сожжённые за один пропуск в один день, иначе схлопнулись бы.
            'submitted_by_token': f'burn:{resolution_id}',
        })
        lessons_repository.insert_attendance(
            lesson_id, [{'student_id': locked['student_id'], 'present': True}],
        )
        lessons_repository.insert_payroll({
            'lesson_id': lesson_id,
            'teacher_id': payment_teacher_id,
            'total_students': 1,
            'present_count': 1,
            'payment': payment,
            'penalty': penalty,
        })
        step = _step(missed_lesson.lesson_duration_minutes)
        lessons_repository.increment_lessons_done(
            locked['missed_lesson_group_id'], [locked['student_id']], step,
        )
        # Сгорание двигает авто-стадию «Продлений» (как обычный урок/доп.урок) —
        # потребление ушло на burned-факт.
        direction_id = Group.objects.filter(
            id=locked['missed_lesson_group_id']).values_list('direction_id', flat=True).first()
        transaction.on_commit(
            lambda: lessons_repository.sync_renewal_stage(locked['student_id'], direction_id))
        repository.mark_burned(resolution_id, fact_lesson_id=lesson_id)

    log_event(
        'extra_lesson_burn', actor_email=_actor(request),
        target_id=resolution_id,
        meta={'lesson_id': lesson_id, 'payment': payment},
        request=request,
    )
    return {'lesson_id': lesson_id, 'payment': payment}


def delete_fact(resolution_id: int, request) -> bool:
    """
    Откатывает проведённый доп.урок ИЛИ сгорание (makeup_done / burned): списывает
    lessons_done обратно на вес факта (extra/burned несут длительность исходного
    урока → _step корректен для обоих), удаляет Payroll+Lesson факта, возвращает
    резолюцию в status=pending. Исходный пропуск и так остался present=false —
    трогать его не нужно. ValueError → резолюция не в откатываемом статусе
    (view → 409). False → резолюции нет (view → 404).
    """
    full = repository.get_resolution_full(resolution_id)
    if full is None:
        return False
    if full['status'] not in (MAKEUP_DONE, BURNED):
        raise ValueError('Удалить факт можно только у проведённого доп.урока или сгорания.')

    with transaction.atomic():
        # Авторитетная проверка статуса под блокировкой строки — гонка двух
        # параллельных delete_fact() иначе оба прошли бы неблокирующую проверку
        # выше и оба попытались бы удалить один и тот же fact_lesson (см.
        # lock_for_delete).
        locked = repository.lock_for_delete(resolution_id)
        if locked is None:
            return False
        if locked['status'] not in (MAKEUP_DONE, BURNED):
            raise ValueError('Удалить факт можно только у проведённого доп.урока или сгорания.')

        fact_lesson_id = locked['fact_lesson_id']
        fact = Lesson.objects.get(id=fact_lesson_id)
        present_ids = list(
            fact.attendance.filter(present=True).values_list('student_id', flat=True)
        )
        # Списываем lessons_done обратно на вес факта доп.урока (он несёт
        # длительность исходного урока, поэтому _step корректен). Симметрично
        # инкременту в record(); исходный пропуск present=false не трогаем.
        if present_ids:
            step = _step(fact.lesson_duration_minutes)
            lessons_repository.decrement_lessons_done(fact.group_id, present_ids, step)
            # Откат доп.урока тоже двигает авто-стадию «Продлений» назад
            # (раньше — revert_makeup_attendance через on_commit).
            direction_id = Group.objects.filter(
                id=fact.group_id).values_list('direction_id', flat=True).first()
            for sid in present_ids:
                transaction.on_commit(
                    lambda sid=sid: lessons_repository.sync_renewal_stage(sid, direction_id))
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
