"""
LessonsRepository — единственное место доступа к данным раздела lessons.

ORM-порт services/repo/lessons.js (раздел 09).

Критичные инварианты (00-conventions, 01-lessons):
  • half-lesson: lesson_duration_minutes == 45 → шаг 0.5 урока, иначе 1.
  • create_lesson_full / delete_lesson_full / update_attendance_cell корректируют
    group_memberships.lessons_done на дельту шага в ТОЙ ЖЕ транзакции.
  • Пагинация (list_lessons) — sort_by по whitelist с тихим fallback (как Express,
    без 400), вторичная сортировка l.id DESC.
  • Контракт ответа пагинатора: { rows, total, page, page_size }.
  • numeric/date — сырые Decimal/date, приводит DateSafeJSONRenderer.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from django.db import transaction
from django.db.models import F, Value, DecimalField
from django.db.models.functions import Greatest, Now

from apps.core.utils.orm import dictrow, dictrows
from apps.groups.models import Group
from apps.students.models import Student

from .models import Lesson, LessonAttendance
from apps.payroll.models import Payroll
from apps.payroll.calculator import calculate_payment
from apps.memberships.models import GroupMembership
from apps.scheduling.repository import unlink_fact
from apps.finances.repository import balances_for_students
from .exceptions import UnpaidAttendanceBlocked


def _sync_renewal_stage(student_id: int, direction_id: int | None) -> None:
    """Пост-коммит-хук: подвинуть авто-стадию «Урок N» раздела «Продления»."""
    from apps.renewals import engine
    engine.sync_lesson_stage_safe(student_id, direction_id)


def sync_renewal_stage(student_id: int, direction_id: int | None) -> None:
    """Публичная обёртка над _sync_renewal_stage для внешних вызывающих
    (apps.extra_lessons.services.record/delete_fact) — доп.урок тоже двигает
    авто-стадию «Продлений», как обычный урок в record_lesson."""
    _sync_renewal_stage(student_id, direction_id)


# ---------------------------------------------------------------------------
# Конфигурация пагинации
# ---------------------------------------------------------------------------

# Поля строки урока (l.* / RETURNING *), в порядке схемы.
_LESSON_FIELDS = (
    'id', 'group_id', 'teacher_id', 'original_teacher_id', 'lesson_date',
    'lesson_number', 'lesson_duration_minutes', 'lesson_type', 'record_url',
    'submitted_at', 'submitted_by_token',
)

# Whitelist sort_by → ORM-поле. l.id DESC — вторичная сортировка.
_SORTABLE: dict[str, str] = {
    'lesson_date':   'lesson_date',
    'lesson_number': 'lesson_number',
    'group_name':    'group__name',
    'teacher_name':  'teacher__name',
    'lesson_type':   'lesson_type',
}

_DEFAULT_SORT_BY = 'lesson_date'
_DEFAULT_SORT_DIR = 'desc'

_ZERO = Value(Decimal('0'), output_field=DecimalField(max_digits=6, decimal_places=1))


def _step(duration_minutes) -> Decimal:
    """half-lesson инвариант: 45 мин → 0.5 урока, иначе 1."""
    return Decimal('0.5') if duration_minutes == 45 else Decimal('1')


def assert_students_paid(present_student_ids: list[int]) -> None:
    """
    Бросает UnpaidAttendanceBlocked, если у кого-то из перечисленных учеников
    остаток оплаченных уроков <= 0. Баланс считается СЕРВЕРОМ (батч, тот же
    расчёт, что read_all_students в teacher_spa) — не принимает клиентский вход.
    No-op для пустого списка. Общая проверка для create/attendance-toggle путей
    (apps.lessons.services.record_lesson, apps.lessons.repository.update_attendance_cell).
    """
    if not present_student_ids:
        return
    balances = balances_for_students(present_student_ids)
    blocked_ids = [sid for sid in present_student_ids if balances.get(sid, 0) <= 0]
    if not blocked_ids:
        return
    names = list(
        Student.objects.filter(id__in=blocked_ids)
        .values_list('full_name', flat=True)
    )
    raise UnpaidAttendanceBlocked(names)


def insert_lesson(fields: dict) -> int:
    """INSERT урока. Возвращает id. submitted_at — DB DEFAULT now() через Now()."""
    obj = Lesson.objects.create(
        lesson_date=fields['lesson_date'],
        teacher_id=fields['teacher_id'],
        group_id=fields['group_id'],
        original_teacher_id=fields.get('original_teacher_id'),
        lesson_number=fields['lesson_number'],
        lesson_duration_minutes=fields['lesson_duration_minutes'],
        lesson_type=fields.get('lesson_type') or 'regular',
        record_url=fields.get('record_url') or None,
        submitted_by_token=fields.get('submitted_by_token') or 'admin-imported',
        submitted_at=Now(),
    )
    return obj.pk


def insert_attendance(lesson_id: int, attendance: list[dict]) -> None:
    """
    Вставка посещаемости только для существующих студентов (= JOIN students),
    ON CONFLICT (lesson_id, student_id) DO NOTHING. No-op если список пуст.
    """
    if not attendance:
        return
    sids = [a['student_id'] for a in attendance]
    valid = set(Student.objects.filter(id__in=sids).values_list('id', flat=True))
    LessonAttendance.objects.bulk_create(
        [
            LessonAttendance(
                lesson_id=lesson_id,
                student_id=a['student_id'],
                present=bool(a['present']),
            )
            for a in attendance if a['student_id'] in valid
        ],
        ignore_conflicts=True,
    )


def increment_lessons_done(group_id: int, student_ids: list[int], step: Decimal) -> None:
    """UPDATE group_memberships SET lessons_done += step WHERE (group_id, student_id) IN ids."""
    if not student_ids:
        return
    GroupMembership.objects.filter(
        group_id=group_id, student_id__in=student_ids,
    ).update(lessons_done=F('lessons_done') + step)


def decrement_lessons_done(group_id: int, student_ids: list[int], step: Decimal) -> None:
    """UPDATE group_memberships SET lessons_done = GREATEST(lessons_done - step, 0)
    WHERE (group_id, student_id) IN ids. Обратная к increment_lessons_done —
    откат потребления при удалении факта (apps.extra_lessons.services.delete_fact);
    тот же GREATEST(...,0)-паттерн, что в delete_lesson_full."""
    if not student_ids:
        return
    GroupMembership.objects.filter(
        group_id=group_id, student_id__in=student_ids,
    ).update(lessons_done=Greatest(F('lessons_done') - step, _ZERO))


def insert_payroll(fields: dict) -> None:
    """INSERT записи payroll. Вызывается всегда (сервер сам считает payment/penalty)."""
    Payroll.objects.create(
        lesson_id=fields['lesson_id'],
        teacher_id=fields['teacher_id'],
        total_students=fields['total_students'],
        present_count=fields['present_count'],
        payment=fields['payment'],
        penalty=fields['penalty'],
    )


def _apply_filters(qs, filters: dict[str, Any]):
    """
    Фильтры (дословно из LESSONS_PAGINATION.filters): group_id, teacher_id,
    lesson_date_from (>=), lesson_date_to (<=), group_name/teacher_name (LIKE),
    lesson_type (exact). Пустые значения игнорируются.
    """
    group_id = filters.get('group_id')
    if group_id not in (None, ''):
        qs = qs.filter(group_id=int(group_id))

    teacher_id = filters.get('teacher_id')
    if teacher_id not in (None, ''):
        qs = qs.filter(teacher_id=int(teacher_id))

    date_from = filters.get('lesson_date_from')
    if date_from not in (None, ''):
        qs = qs.filter(lesson_date__gte=date_from)

    date_to = filters.get('lesson_date_to')
    if date_to not in (None, ''):
        qs = qs.filter(lesson_date__lte=date_to)

    group_name = filters.get('group_name')
    if group_name not in (None, ''):
        qs = qs.filter(group__name__icontains=str(group_name))

    teacher_name = filters.get('teacher_name')
    if teacher_name not in (None, ''):
        qs = qs.filter(teacher__name__icontains=str(teacher_name))

    lesson_type = filters.get('lesson_type')
    if lesson_type not in (None, ''):
        qs = qs.filter(lesson_type=lesson_type)

    return qs


# ---------------------------------------------------------------------------
# Repository functions
# ---------------------------------------------------------------------------

def list_lessons(
    page: int = 1,
    page_size: int = 50,
    sort_by: str = _DEFAULT_SORT_BY,
    sort_dir: str = _DEFAULT_SORT_DIR,
    filters: Optional[dict] = None,
) -> dict:
    """
    Пагинированный список уроков с joined-полями и payroll (LEFT).

    Контракт ответа: { rows, total, page, page_size }.
    """
    if filters is None:
        filters = {}

    sort_field = _SORTABLE.get(sort_by) or _SORTABLE[_DEFAULT_SORT_BY]
    order_prefix = '' if sort_dir == 'asc' else '-'

    qs = _apply_filters(Lesson.objects.all(), filters)

    total = qs.count()  # payroll 1:1 → LEFT JOIN не множит строки

    offset = max(0, (page - 1) * page_size)
    ordered = qs.order_by(f'{order_prefix}{sort_field}', '-id')
    rows = dictrows(
        ordered[offset:offset + page_size].values(
            *_LESSON_FIELDS,
            group_name=F('group__name'),
            teacher_name=F('teacher__name'),
            original_teacher_name=F('original_teacher__name'),   # LEFT (nullable FK)
            payroll_id=F('payroll__id'),                         # LEFT (reverse 1:1)
            total_students=F('payroll__total_students'),
            present_count=F('payroll__present_count'),
            payment=F('payroll__payment'),
            penalty=F('payroll__penalty'),
        )
    )

    return {
        'rows': rows,
        'total': total,
        'page': page,
        'page_size': page_size,
    }


def get_lesson_full(lesson_id: int) -> Optional[dict]:
    """Полный урок: meta + attendance[] + payroll (порт getLessonFull, 3 запроса)."""
    lesson = dictrow(
        Lesson.objects.filter(id=lesson_id).values(
            *_LESSON_FIELDS,
            group_name=F('group__name'),
            teacher_name=F('teacher__name'),
            original_teacher_name=F('original_teacher__name'),
        )
    )
    if lesson is None:
        return None

    lesson['attendance'] = dictrows(
        LessonAttendance.objects
        .filter(lesson_id=lesson_id)
        .order_by('student__full_name')
        .values('student_id', 'present', 'burned_at', student_name=F('student__full_name'))
    )

    lesson['payroll'] = dictrow(
        Payroll.objects.filter(lesson_id=lesson_id).values(
            'id', 'total_students', 'present_count', 'payment', 'penalty',
            'burn_surcharge_amount', 'burn_surcharge_at',
        )
    )

    return lesson


def update_lesson(lesson_id: int, fields: dict) -> Optional[dict]:
    """
    Обновляет meta урока (PATCH через COALESCE, дословно из lessons.js).

    original_teacher_id nullable — различаем «не передано» и «явный null» по
    наличию ключа (CASE WHEN has_original): ключ есть → перезаписываем (вкл. null).
    """
    obj = Lesson.objects.filter(id=lesson_id).first()
    if obj is None:
        return None

    if fields.get('lesson_date') is not None:
        obj.lesson_date = fields['lesson_date']
    if fields.get('teacher_id') is not None:
        obj.teacher_id = fields['teacher_id']
    if fields.get('lesson_number') is not None:
        obj.lesson_number = fields['lesson_number']
    if fields.get('lesson_type') is not None:
        obj.lesson_type = fields['lesson_type']
    if fields.get('record_url'):                  # NULLIF: пустая строка → не трогаем
        obj.record_url = fields['record_url']
    if 'original_teacher_id' in fields:           # has_original → set даже null
        obj.original_teacher_id = fields['original_teacher_id']

    obj.save()
    return dictrow(Lesson.objects.filter(id=lesson_id).values(*_LESSON_FIELDS))


def delete_lesson_full(lesson_id: int) -> bool:
    """
    Удаляет урок (CASCADE attendance + явный DELETE payroll),
    предварительно откатывая lessons_done у присутствовавших (GREATEST(x-step, 0)).
    """
    with transaction.atomic():
        ctx = (
            Lesson.objects
            .filter(id=lesson_id)
            .values('group_id', 'lesson_duration_minutes')
            .first()
        )
        if ctx is not None:
            step = _step(ctx['lesson_duration_minutes'])
            sids = list(
                LessonAttendance.objects
                .filter(lesson_id=lesson_id, present=True)
                .values_list('student_id', flat=True)
            )
            if sids:
                GroupMembership.objects.filter(
                    group_id=ctx['group_id'], student_id__in=sids,
                ).update(lessons_done=Greatest(F('lessons_done') - step, _ZERO))

                direction_id = Group.objects.filter(
                    id=ctx['group_id']).values_list('direction_id', flat=True).first()
                for sid in sids:
                    transaction.on_commit(
                        lambda sid=sid: _sync_renewal_stage(sid, direction_id))

        unlink_fact(lesson_id)
        Payroll.objects.filter(lesson_id=lesson_id).delete()
        _count, details = Lesson.objects.filter(id=lesson_id).delete()

    return details.get('lessons.Lesson', 0) > 0


def update_attendance_cell(lesson_id: int, student_id: int, present: bool) -> bool:
    """
    Toggle present одной ячейки (UPSERT) + корректировка lessons_done дельтой +
    пересчёт Payroll.present_count/payment (не penalty — она про своевременность
    исходной записи урока, не должна меняться от последующей правки посещаемости).

    Бросает UnpaidAttendanceBlocked, если переключают В present:true ученика
    без оплаченных уроков (assert_students_paid) — ДО любых изменений, но
    ПОСЛЕ проверки существования урока (несуществующий lesson_id → False,
    как и раньше, а не блокировка по балансу).

    True→True (no-op) сохраняет прежнее значение. НЕ создаёт «сгораний» —
    ретроактивная отметка пропуска задним числом теперь идёт через раздел
    «Доп.уроки» (burned-Lesson, apps.extra_lessons.services.burn), а не флипом
    ячейки исходного урока.
    """
    with transaction.atomic():
        ctx = (
            Lesson.objects
            .filter(id=lesson_id)
            .values('group_id', 'lesson_duration_minutes')
            .first()
        )
        if ctx is None:
            return False

        if present:
            assert_students_paid([student_id])

        prev = (
            LessonAttendance.objects
            .filter(lesson_id=lesson_id, student_id=student_id)
            .values('present')
            .first()
        )
        prev_present = prev['present'] if prev is not None else None

        step = _step(ctx['lesson_duration_minutes'])
        nxt = bool(present)

        LessonAttendance.objects.bulk_create(
            [LessonAttendance(lesson_id=lesson_id, student_id=student_id, present=nxt)],
            update_conflicts=True,
            unique_fields=['lesson', 'student'],
            update_fields=['present'],
        )

        delta = Decimal('0')
        if prev_present is None and nxt:
            delta = step
        elif prev_present is False and nxt:
            delta = step
        elif prev_present is True and not nxt:
            delta = -step

        if delta != 0:
            GroupMembership.objects.filter(
                group_id=ctx['group_id'], student_id=student_id,
            ).update(lessons_done=Greatest(F('lessons_done') + delta, _ZERO))

            direction_id = Group.objects.filter(
                id=ctx['group_id']).values_list('direction_id', flat=True).first()
            transaction.on_commit(
                lambda: _sync_renewal_stage(student_id, direction_id))

        # Пересчёт Payroll из фактических attendance-строк. select_for_update() —
        # тот же паттерн read-then-recompute-then-write, что в проекте (apps/payments,
        # apps/renewals/engine, apps/memberships) — без него два параллельных PATCH
        # на разных учеников ОДНОГО урока посчитали бы COUNT до коммита друг друга,
        # и последний commit тихо затёр бы вклад первого (lost update).
        payroll = Payroll.objects.select_for_update().filter(lesson_id=lesson_id).first()
        if payroll is not None:
            total_students = LessonAttendance.objects.filter(lesson_id=lesson_id).count()
            present_total = LessonAttendance.objects.filter(
                lesson_id=lesson_id, present=True,
            ).count()
            is_half = ctx['lesson_duration_minutes'] == 45
            payroll.total_students = total_students
            payroll.present_count = present_total
            payroll.payment = calculate_payment(total_students, present_total, is_half)
            payroll.save(update_fields=['total_students', 'present_count', 'payment'])

        return True
