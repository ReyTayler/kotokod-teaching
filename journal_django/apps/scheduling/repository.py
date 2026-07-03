"""
Доступ к данным для планирования занятий — батч-запросы (без N+1).

Единственное место ORM-доступа раздела scheduling. Все чтения — по спискам
group_id одним запросом, группировка в Python. Даты/время приходят как
date/time объекты (managed-модели), генератор работает с ними напрямую.
"""
from __future__ import annotations

import datetime
from collections import defaultdict

from django.db import transaction
from django.db.models import F

from apps.core.utils.dates import msk_now
from apps.groups.models import GroupScheduleSlot, LessonScheduleException
from apps.groups.models import Group
from apps.lessons.models import Lesson
from apps.memberships.models import GroupMembership
from apps.teachers.models import Teacher
from apps.scheduling.models import PlannedLesson
from apps.scheduling.occurrences import DONE, ScheduleException, Slot
from apps.scheduling.planner import PlannedRow


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


# ---------------------------------------------------------------------------
# ЗАПИСЬ плана (materialize-on-write). Батч, без N+1; идемпотентно.
# ---------------------------------------------------------------------------

# Поля курсовой строки, которые несёт PlannedRow и которые бэкфилл/генерация
# может обновлять у ещё непроведённых строк (даты/время/препод/статус/номер).
_PLAN_UPDATE_FIELDS = (
    'lesson_number', 'scheduled_date', 'scheduled_time', 'teacher', 'status',
    'updated_at',
)


def persist_plan(group_id: int, rows: list[PlannedRow]) -> int:
    """
    Идемпотентно записать/обновить курсовые строки плана группы в planned_lessons.

    Ключ идемпотентности — UniqueConstraint(group, seq): одна строка на позицию
    курса. Строки со status='done' (проведённые) НЕ перезаписываются. Строки, чьи
    значения не изменились, пропускаются (повторный прогон → 0 изменений).

    Работает только с курсовыми строками (seq задан) — ровно то, что отдаёт
    planner.generate(); extra/маркеры (seq=NULL) сюда не попадают.

    created_at/updated_at заполняются msk_now() (см. миграцию 0001: DB-default
    now() — на случай raw-INSERT; при ORM-вставке значение задаём явно, т.к.
    Django включает колонку в INSERT).

    Возвращает число фактически изменённых строк (созданных + обновлённых).
    """
    if not rows:
        return 0

    now = msk_now()
    with transaction.atomic():
        existing = {
            p.seq: p
            for p in PlannedLesson.objects.filter(
                group_id=group_id, seq__isnull=False,
            )
        }

        to_create: list[PlannedLesson] = []
        to_update: list[PlannedLesson] = []

        for r in rows:
            if r.seq is None:
                # generate() курсовые строки всегда с seq; extra — вне бэкфилла.
                continue
            ex = existing.get(r.seq)
            if ex is None:
                to_create.append(PlannedLesson(
                    group_id=group_id,
                    seq=r.seq,
                    lesson_number=r.lesson_number,
                    scheduled_date=r.scheduled_date,
                    scheduled_time=r.scheduled_time,
                    teacher_id=r.teacher_id,
                    status=r.status,
                    created_at=now,
                    updated_at=now,
                ))
                continue
            if ex.status == DONE:
                # Проведённые не трогаем.
                continue
            # Обновляем только при реальном изменении — иначе повтор идемпотентен.
            if (
                ex.lesson_number == r.lesson_number
                and ex.scheduled_date == r.scheduled_date
                and ex.scheduled_time == r.scheduled_time
                and ex.teacher_id == r.teacher_id
                and ex.status == r.status
            ):
                continue
            ex.lesson_number = r.lesson_number
            ex.scheduled_date = r.scheduled_date
            ex.scheduled_time = r.scheduled_time
            ex.teacher_id = r.teacher_id
            ex.status = r.status
            ex.updated_at = now
            to_update.append(ex)

        if to_create:
            PlannedLesson.objects.bulk_create(to_create)
        if to_update:
            PlannedLesson.objects.bulk_update(to_update, list(_PLAN_UPDATE_FIELDS))

    return len(to_create) + len(to_update)


def link_facts(group_id: int) -> int:
    """
    Слинковать плановые строки группы с проведёнными уроками (факт) и проставить
    status='done'.

    Для каждой ещё непривязанной строки (fact_lesson IS NULL) ищем факт той же
    группы с совпадающей scheduled_date == Lesson.lesson_date. При неоднозначности
    (несколько уроков в одну дату) — уточняем по lesson_number. Один факт ↔ одна
    плановая строка (fact_lesson unique): уже привязанные факты исключаются, а
    выбранный кандидат снимается из пула в рамках прогона.

    Батч (без N+1): три запроса на группу. Идемпотентно — повторный прогон линкует
    0 (все совпадения уже привязаны).

    Возвращает число новых линковок.
    """
    now = msk_now()
    with transaction.atomic():
        already_linked = set(
            PlannedLesson.objects
            .filter(group_id=group_id, fact_lesson_id__isnull=False)
            .values_list('fact_lesson_id', flat=True)
        )

        by_date: dict[datetime.date, list[dict]] = defaultdict(list)
        for f in Lesson.objects.filter(group_id=group_id).values(
            'id', 'lesson_date', 'lesson_number',
        ):
            if f['id'] in already_linked:
                continue
            by_date[f['lesson_date']].append(f)

        if not by_date:
            return 0

        rows = list(
            PlannedLesson.objects
            .filter(group_id=group_id, fact_lesson_id__isnull=True)
            .order_by('seq')
        )

        to_update: list[PlannedLesson] = []
        for p in rows:
            cands = by_date.get(p.scheduled_date)
            if not cands:
                continue
            chosen = None
            if p.lesson_number is not None:
                for f in cands:
                    if f['lesson_number'] == p.lesson_number:
                        chosen = f
                        break
            if chosen is None:
                chosen = cands[0]
            cands.remove(chosen)
            p.fact_lesson_id = chosen['id']
            p.status = DONE
            p.updated_at = now
            to_update.append(p)

        if to_update:
            PlannedLesson.objects.bulk_update(
                to_update, ['fact_lesson', 'status', 'updated_at'],
            )

    return len(to_update)
