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
from django.db.models import F, Min

from apps.core.utils.dates import msk_now
from apps.groups.models import GroupScheduleSlot
from apps.groups.models import Group
from apps.lessons.models import Lesson
from apps.memberships.models import GroupMembership
from apps.teachers.models import Teacher
from apps.scheduling import planner
from apps.scheduling.models import PlannedLesson
from apps.scheduling.occurrences import CANCELLED, DONE, MOVED, OVERDUE, PENDING, Slot, _step_for
from apps.scheduling.planner import Fact, PlannedRow


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
# ЧТЕНИЕ planned_lessons для календаря (шаг 5 — read-on-materialized).
# Скоуп по planned_lesson.teacher_id (преподаватель КОНКРЕТНОГО занятия), не по
# учителю группы: смена препода занятия перекидывает урок между календарями.
# ---------------------------------------------------------------------------

def planned_lessons_in_window(
    window_from: datetime.date,
    window_to: datetime.date,
    teacher_id: int,
) -> list[dict]:
    """
    Плановые занятия ОДНОГО преподавателя за окно — источник GET /api/calendar.

    Скоуп — по `planned_lesson.teacher_id` (не по учителю группы): группа занятия
    может принадлежать другому учителю (после смены препода занятия). Только
    активные группы (паритет с прежним compute-путём `active_groups`).

    Батч-джойны, без N+1: один запрос строк с join группы/направления. Имена
    преподавателей и учеников по группам подтягивает вызывающий (services) через
    существующие справочники `teacher_names` / `student_names_by_group`.

    Возвращает «сырые» словари (date/time — объекты) для services._planned_occurrence_dict.
    """
    return list(
        PlannedLesson.objects
        .filter(
            teacher_id=teacher_id,
            group__active=True,
            scheduled_date__gte=window_from,
            scheduled_date__lte=window_to,
        )
        .values(
            'id', 'seq', 'lesson_number', 'scheduled_date', 'scheduled_time',
            'teacher_id', 'status', 'fact_lesson_id',
            'moved_from_date',
            group_pk=F('group_id'),
            group_name=F('group__name'),
            is_individual=F('group__is_individual'),
            lesson_duration_minutes=F('group__lesson_duration_minutes'),
            group_teacher_id=F('group__teacher_id'),
            direction_name=F('group__direction__name'),
            direction_color=F('group__direction__color'),
        )
    )


def groups_without_plan(teacher_id: int) -> list[dict]:
    """
    Активные группы преподавателя (по `group.teacher_id`) без единой строки
    planned_lessons — data-quality сигнал `unscheduled` для календаря.

    Причина: no_start_date / no_total_lessons / no_slots (нельзя сгенерировать) или
    not_generated (можно, но план ещё не материализован). Батч: active_groups +
    один DISTINCT по planned_lessons + slots_by_group.
    """
    groups = active_groups(teacher_id)
    if not groups:
        return []
    ids = [g['id'] for g in groups]
    with_plan = set(
        PlannedLesson.objects
        .filter(group_id__in=ids)
        .values_list('group_id', flat=True)
        .distinct()
    )
    missing = [g for g in groups if g['id'] not in with_plan]
    if not missing:
        return []
    slots = slots_by_group([g['id'] for g in missing])

    out: list[dict] = []
    for g in missing:
        if g['group_start_date'] is None:
            reason = 'no_start_date'
        elif g['total_lessons'] is None:
            reason = 'no_total_lessons'
        elif not slots.get(g['id']):
            reason = 'no_slots'
        else:
            reason = 'not_generated'
        out.append({'group': g['name'], 'reason': reason})
    return out


# ---------------------------------------------------------------------------
# ЧТЕНИЕ planned_lessons для реестра куратора (admin, вся школа).
# Скоуп НЕ по преподавателю — единственное место, где planned_lessons читаются
# по ВСЕМ активным группам разом. Батч, без N+1. Потребитель —
# apps/dashboard/registry_service.py.
# ---------------------------------------------------------------------------

def occurrences_on_date(target: datetime.date) -> list[dict]:
    """
    Плановые занятия ВСЕХ активных групп на конкретную дату (для «Потока дня»).

    Исключены маркеры отмены/переноса (cancelled/moved) — показываем реальные
    занятия дня. Возвращает value-словари (time — объект); имена преподавателей и
    учеников подтягивает вызывающий через teacher_names / student_names_by_group.
    """
    return list(
        PlannedLesson.objects
        .filter(group__active=True, scheduled_date=target)
        .exclude(status__in=(CANCELLED, MOVED))
        .order_by('scheduled_time', 'group_id')
        .values(
            'id', 'scheduled_time', 'status', 'teacher_id',
            group_pk=F('group_id'),
            group_name=F('group__name'),
        )
    )


def next_occurrence_by_group(from_date: datetime.date) -> dict[int, datetime.date]:
    """
    group_id → ближайшая плановая дата (>= from_date) среди pending/overdue строк
    активных групп. Один запрос с Min-агрегацией. Для колонки «Ближайший» (min по
    группам ученика вычисляет вызывающий).
    """
    rows = (
        PlannedLesson.objects
        .filter(
            group__active=True,
            scheduled_date__gte=from_date,
            status__in=(PENDING, OVERDUE),
        )
        .values('group_id')
        .annotate(nx=Min('scheduled_date'))
    )
    return {r['group_id']: r['nx'] for r in rows}


def cancellations_count(period_start, period_end) -> int:
    """
    Число отменённых плановых занятий (маркеры status='cancelled') активных групп
    в полуинтервале [period_start, period_end) — KPI «Отмены» реестра.
    Границы — 'YYYY-MM-DD' строки или date (Django принимает оба для DateField).
    """
    return (
        PlannedLesson.objects
        .filter(
            group__active=True,
            status=CANCELLED,
            scheduled_date__gte=period_start,
            scheduled_date__lt=period_end,
        )
        .count()
    )


# ---------------------------------------------------------------------------
# ЗАПИСЬ плана (materialize-on-write). Батч, без N+1; идемпотентно.
# ---------------------------------------------------------------------------

# Поля курсовой строки, которые несёт PlannedRow и которые бэкфилл/генерация
# может обновлять у ещё непроведённых строк (даты/время/препод/статус/номер).
_PLAN_UPDATE_FIELDS = (
    'lesson_number', 'scheduled_date', 'scheduled_time', 'teacher', 'status',
    'updated_at',
)


def reset_plan(group_id: int) -> int:
    """Удалить весь план группы (для чистой перегенерации, backfill --reset).

    Разрушительно: сбрасывает и ручные операции (переносы/отмены), и линковку с
    фактами. Использовать только при полном пересборе плана. Возвращает число
    удалённых строк."""
    deleted, _ = PlannedLesson.objects.filter(group_id=group_id).delete()
    return deleted


def persist_plan(group_id: int, rows: list[PlannedRow], *, create_only: bool = False) -> int:
    """
    Идемпотентно записать/обновить курсовые строки плана группы в planned_lessons.

    Ключ идемпотентности — UniqueConstraint(group, seq): одна строка на позицию
    курса. Строки со status='done' (проведённые) НЕ перезаписываются. Строки, чьи
    значения не изменились, пропускаются (повторный прогон → 0 изменений).

    create_only=True: существующие строки НЕ обновляются — только досоздаются
    недостающие seq (расширение курса). Используется эндпоинтом generate, чтобы
    повторная генерация не затирала ручные операции (переносы/отмены/смену препода)
    над уже материализованным планом. Полный пересбор — backfill --reset (reset_plan).

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
            if ex is not None and create_only:
                # Существующая строка при create_only не трогается (сохраняем
                # ручные операции); досоздаём только отсутствующие seq.
                continue
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
    status='done'. Плановая дата (scheduled_date) НЕ перезаписывается — она хранит
    дату планового проведения; фактическая дата берётся из fact_lesson.lesson_date
    (см. get_plan → fact_date). Так во «Обзоре» видны обе даты: плановая и факт.

    Порядок матчинга (по надёжности):
      1. по `lesson_number` — позиция урока в курсе, записанная при проведении:
         надёжнее даты (уроки прошлого часто на сдвинутых датах — праздники,
         разовые переносы до этой системы).
      2. по точной дате (fallback) — для фактов без совпадения по номеру
         (напр. lesson_number не записан), но с датой, равной плановой.

    Один факт ↔ одна плановая строка (fact_lesson unique): уже привязанные факты
    исключаются, каждый кандидат используется один раз за прогон. Батч, без N+1.
    Идемпотентно — повторный прогон линкует 0. Возвращает число новых линковок.
    """
    now = msk_now()
    with transaction.atomic():
        already_linked = set(
            PlannedLesson.objects
            .filter(group_id=group_id, fact_lesson_id__isnull=False)
            .values_list('fact_lesson_id', flat=True)
        )

        # Непривязанные факты; по номеру берём самый ранний по дате (детерминизм).
        facts = [
            f for f in Lesson.objects.filter(group_id=group_id)
            .order_by('lesson_date', 'id')
            .values('id', 'lesson_date', 'lesson_number')
            if f['id'] not in already_linked
        ]
        if not facts:
            return 0

        by_number: dict[object, list[dict]] = defaultdict(list)
        by_date: dict[datetime.date, list[dict]] = defaultdict(list)
        for f in facts:
            if f['lesson_number'] is not None:
                by_number[f['lesson_number']].append(f)
            by_date[f['lesson_date']].append(f)

        rows = list(
            PlannedLesson.objects
            .filter(group_id=group_id, fact_lesson_id__isnull=True)
            .order_by('seq')
        )

        used_fact_ids: set = set()
        to_update: list[PlannedLesson] = []

        def _take(cands: list[dict]):
            for f in cands:
                if f['id'] not in used_fact_ids:
                    return f
            return None

        # Проход 1: по lesson_number (плановую дату НЕ трогаем — факт-дата в fact_lesson).
        for p in rows:
            if p.lesson_number is None:
                continue
            chosen = _take(by_number.get(p.lesson_number, []))
            if chosen is None:
                continue
            used_fact_ids.add(chosen['id'])
            p.fact_lesson_id = chosen['id']
            p.status = DONE
            p.updated_at = now
            to_update.append(p)

        linked_row_ids = {id(p) for p in to_update}

        # Проход 2: по точной дате (fallback) для ещё не привязанных строк.
        for p in rows:
            if id(p) in linked_row_ids:
                continue
            chosen = _take(by_date.get(p.scheduled_date, []))
            if chosen is None:
                continue
            used_fact_ids.add(chosen['id'])
            p.fact_lesson_id = chosen['id']
            p.status = DONE
            p.updated_at = now
            to_update.append(p)

        if to_update:
            PlannedLesson.objects.bulk_update(
                to_update, ['fact_lesson', 'status', 'updated_at'],
            )

    return len(to_update)


# ---------------------------------------------------------------------------
# Admin-API операции над planned_lessons (шаг 4). Все write — в transaction.atomic;
# планировщик дат — чистые функции planner.*; версионирование слота при
# «переносе навсегда» переиспользует groups.repository.apply_schedule_change.
# ---------------------------------------------------------------------------

# Статусы, которые операции переноса навсегда пересчитывают (непроведённые).
_MUTABLE_STATUSES = (PENDING, OVERDUE)


def _iso(d: datetime.date | None) -> str | None:
    return d.isoformat() if d else None


def _hhmm(t: datetime.time | None) -> str | None:
    return t.strftime('%H:%M') if t else None


def _plan_row_dict(r: dict, tnames: dict[int, str]) -> dict:
    """Сериализуемая плановая строка из .values()-словаря. is_extra = seq IS NULL."""
    ln = r['lesson_number']
    return {
        'id': r['id'],
        'seq': r['seq'],
        'lesson_number': float(ln) if ln is not None else None,
        'scheduled_date': _iso(r['scheduled_date']),
        'scheduled_time': _hhmm(r['scheduled_time']),
        'teacher_id': r['teacher_id'],
        'teacher_name': tnames.get(r['teacher_id']),
        'status': r['status'],
        'fact_lesson_id': r['fact_lesson_id'],
        # Фактическая дата проведения (из связанного факта) — отдельно от плановой
        # scheduled_date; None если урок ещё не проведён.
        'fact_date': _iso(r.get('fact_date')),
        'record_url': r.get('record_url'),
        'moved_from_date': _iso(r['moved_from_date']),
        'is_extra': r['seq'] is None,
    }


def _plan_row_dict_obj(p: PlannedLesson, tnames: dict[int, str]) -> dict:
    """Сериализуемая плановая строка из ORM-объекта (после save/create)."""
    return _plan_row_dict({
        'id': p.id,
        'seq': p.seq,
        'lesson_number': p.lesson_number,
        'scheduled_date': p.scheduled_date,
        'scheduled_time': p.scheduled_time,
        'teacher_id': p.teacher_id,
        'status': p.status,
        'fact_lesson_id': p.fact_lesson_id,
        'moved_from_date': p.moved_from_date,
    }, tnames)


def _row_from_model(p: PlannedLesson) -> PlannedRow:
    """ORM-объект → PlannedRow (значения для planner)."""
    return PlannedRow(
        seq=p.seq,
        lesson_number=p.lesson_number,
        scheduled_date=p.scheduled_date,
        scheduled_time=p.scheduled_time,
        teacher_id=p.teacher_id,
        status=p.status,
        moved_from_date=p.moved_from_date,
        is_extra=p.seq is None,
    )


def plan_exists(group_id: int, *, active_only: bool = False) -> bool:
    """Есть ли у группы плановые строки (быстрый EXISTS).

    active_only=True: неактивную/отсутствующую группу считаем «план есть» (True),
    чтобы автоген её ПРОПУСКАЛ, не меняя поведение ручного /plan/generate (там
    active-фильтра нет). См. services.autogenerate_plan_on_setup."""
    if active_only and not Group.objects.filter(id=group_id, active=True).exists():
        return True
    return PlannedLesson.objects.filter(group_id=group_id).exists()


def get_plan(group_id: int) -> list[dict] | None:
    """
    Плановые строки группы (сериализуемые), упорядоченные по (дата, время).

    None → группы нет (view → 404). [] → группа есть, плана нет. Батч: два
    запроса (строки + справочник имён преподавателей), без N+1.
    """
    if not Group.objects.filter(id=group_id).exists():
        return None
    rows = (
        PlannedLesson.objects
        .filter(group_id=group_id)
        .order_by('scheduled_date', 'scheduled_time')
        .values(
            'id', 'seq', 'lesson_number', 'scheduled_date', 'scheduled_time',
            'teacher_id', 'status', 'fact_lesson_id', 'moved_from_date',
            fact_date=F('fact_lesson__lesson_date'),
            record_url=F('fact_lesson__record_url'),
        )
    )
    tnames = teacher_names()
    return [_plan_row_dict(r, tnames) for r in rows]


def get_plan_lesson(group_id: int, lesson_id: int) -> dict | None:
    """Одна плановая строка (group_id + id) с датой-объектом. None если нет.

    Возвращает «сырой» словарь (date/time — объекты) для внутренних операций
    (напр. вычисление from_date отмены по id занятия)."""
    return (
        PlannedLesson.objects
        .filter(group_id=group_id, id=lesson_id)
        .values('id', 'seq', 'scheduled_date', 'scheduled_time', 'teacher_id', 'status')
        .first()
    )


def reschedule_lesson(
    group_id: int,
    lesson_id: int,
    new_date: datetime.date,
    new_time: datetime.time | None,
    new_teacher_id: int | None,
) -> dict | None:
    """
    Разовый перенос одной строки (planner.reschedule): новые дата/время (+опц.
    преподаватель), прежняя дата → moved_from_date. seq/lesson_number сохраняются.

    None → строки нет (404). ValueError → перенос проведённого (status='done').
    """
    now = msk_now()
    with transaction.atomic():
        p = (
            PlannedLesson.objects
            .select_for_update()
            .filter(group_id=group_id, id=lesson_id)
            .first()
        )
        if p is None:
            return None
        if p.status == DONE:
            raise ValueError('Нельзя перенести проведённое занятие (status=done).')

        updated = planner.reschedule(
            _row_from_model(p),
            new_date=new_date,
            new_time=new_time,
            new_teacher_id=new_teacher_id,
        )
        p.scheduled_date = updated.scheduled_date
        p.scheduled_time = updated.scheduled_time
        p.teacher_id = updated.teacher_id
        p.moved_from_date = updated.moved_from_date
        p.updated_at = now
        p.save(update_fields=[
            'scheduled_date', 'scheduled_time', 'teacher', 'moved_from_date', 'updated_at',
        ])

    return _plan_row_dict_obj(p, teacher_names())


def change_teacher(
    group_id: int, lesson_id: int, new_teacher_id: int,
) -> dict | None:
    """
    Разовая смена преподавателя одной строки (planner.change_teacher): меняет ТОЛЬКО
    teacher_id, дату/время не трогает и НЕ помечает строку перенесённой.

    None → строки нет (404). ValueError → строка проведена (status='done').
    """
    now = msk_now()
    with transaction.atomic():
        p = (
            PlannedLesson.objects
            .select_for_update()
            .filter(group_id=group_id, id=lesson_id)
            .first()
        )
        if p is None:
            return None
        updated = planner.change_teacher(_row_from_model(p), new_teacher_id=new_teacher_id)
        p.teacher_id = updated.teacher_id
        p.updated_at = now
        p.save(update_fields=['teacher', 'updated_at'])

    return _plan_row_dict_obj(p, teacher_names())


def change_teacher_permanent(
    group_id: int, *, from_seq: int, new_teacher_id: int,
) -> list[dict] | None:
    """
    Смена преподавателя навсегда (planner.change_teacher_tail): проставить teacher_id
    всем курсовым строкам seq>=from_seq в статусе pending/overdue. Даты/дни/слот НЕ
    трогаются (в отличие от permanent_change).

    None → группы нет (404). ValueError → нет курсовых строк с указанной позиции.
    Возвращает новый план (get_plan).
    """
    if not Group.objects.filter(id=group_id).exists():
        return None

    now = msk_now()
    with transaction.atomic():
        tail = list(
            PlannedLesson.objects
            .select_for_update()
            .filter(
                group_id=group_id, seq__isnull=False, seq__gte=from_seq,
                status__in=_MUTABLE_STATUSES,
            )
            .order_by('seq')
        )
        if not tail:
            raise ValueError('Нет курсовых строк для смены преподавателя с указанной позиции (seq).')

        by_seq = {p.seq: p for p in tail}
        changed = planner.change_teacher_tail(
            [_row_from_model(p) for p in tail],
            from_seq=from_seq,
            new_teacher_id=new_teacher_id,
        )
        to_update = []
        for cr in changed:
            p = by_seq[cr.seq]
            p.teacher_id = cr.teacher_id
            p.updated_at = now
            to_update.append(p)
        PlannedLesson.objects.bulk_update(to_update, ['teacher', 'updated_at'])

    return get_plan(group_id)


def permanent_change(
    group_id: int,
    *,
    from_seq: int,
    new_day_of_week: int,
    new_time: datetime.time | None,
    new_teacher_id: int | None,
) -> list[dict] | None:
    """
    Перенос навсегда с позиции from_seq (в одной транзакции):

      (а) пересчитать курсовые строки seq>=from_seq со статусом pending/overdue →
          planner.permanent_change (сдвиг на новый день недели, опц. время/препод);
      (б) версионировать слот — groups.repository.apply_schedule_change (закрыть
          открытые слоты effective_to=дата−1 / вставить новый day/time). Время
          нового слота = new_time или время текущего открытого слота.

    Граница нового слота (effective_from) НЕ принимается от клиента, а выводится
    на сервере из новой даты самой ранней сдвинутой строки (seq=from_seq) — так
    версионирование слота и сдвиг хвоста не могут разъехаться.

    Ограничение (в духе спеки — перенос ЕДИНСТВЕННОГО недельного слота): для групп
    с >1 открытым слотом операция недоступна (иначе _shift_to_weekday сажает
    несколько недельных строк на один день/время → коллизия по дате, которую
    UniqueConstraint(group, seq) не ловит) — поднимаем ValueError ДО любых записей.

    None → группы нет (404). ValueError → мульти-слот / нет времени слота / нет
    курсовых строк с указанной позиции. Возвращает новый план (get_plan).
    """
    # Локальный импорт: избегаем циклической зависимости на уровне модуля
    # (groups.urls → scheduling.views → …). Переиспользуем версионирование слота.
    from apps.groups import repository as groups_repo
    from apps.groups.models import GroupScheduleSlot

    if not Group.objects.filter(id=group_id).exists():
        return None

    now = msk_now()
    with transaction.atomic():
        # (0) Гард мульти-слотовых групп: перенос навсегда рассчитан на один
        # недельный слот. При >1 открытом слоте отказываемся ДО любых изменений.
        open_slots = list(
            GroupScheduleSlot.objects
            .filter(group_id=group_id, effective_to__isnull=True)
            .order_by('day_of_week', 'start_time')
        )
        if len(open_slots) > 1:
            raise ValueError(
                'Перенос навсегда недоступен для групп с несколькими занятиями в неделю.'
            )

        # Время нового слота: явное new_time или время текущего открытого слота.
        if new_time is not None:
            slot_time = new_time
        elif open_slots:
            slot_time = open_slots[0].start_time
        else:
            slot_time = None
        if slot_time is None:
            raise ValueError('Нет времени для нового слота: укажите new_time.')

        # (а) пересчитать хвост курсовых строк.
        tail = list(
            PlannedLesson.objects
            .select_for_update()
            .filter(
                group_id=group_id, seq__isnull=False, seq__gte=from_seq,
                status__in=_MUTABLE_STATUSES,
            )
            .order_by('seq')
        )
        if not tail:
            raise ValueError('Нет курсовых строк для переноса с указанной позиции (seq).')

        by_seq = {p.seq: p for p in tail}
        changed = planner.permanent_change(
            [_row_from_model(p) for p in tail],
            from_seq=from_seq,
            new_day_of_week=new_day_of_week,
            new_time=new_time,
            new_teacher_id=new_teacher_id,
        )

        # (б) версионировать слот. Граница = новая дата самой ранней сдвинутой
        # строки (changed упорядочен по seq → changed[0] соответствует seq=from_seq),
        # которая по построению приходится на new_day_of_week.
        effective_from = changed[0].scheduled_date
        groups_repo.apply_schedule_change(
            group_id,
            effective_from,
            [{'day_of_week': new_day_of_week, 'start_time': slot_time.strftime('%H:%M')}],
        )

        to_update = []
        for cr in changed:
            p = by_seq[cr.seq]
            p.scheduled_date = cr.scheduled_date
            p.scheduled_time = cr.scheduled_time
            p.teacher_id = cr.teacher_id
            p.updated_at = now
            to_update.append(p)
        PlannedLesson.objects.bulk_update(
            to_update, ['scheduled_date', 'scheduled_time', 'teacher', 'updated_at'],
        )

    return get_plan(group_id)


def cancel_lesson(
    group_id: int,
    from_date: datetime.date,
    *,
    marker_time: datetime.time,
    marker_teacher_id: int | None,
) -> list[dict]:
    """
    Отмена со сдвигом: непроведённые строки (status != 'done') с
    scheduled_date >= from_date сдвигаются на +7 дней (день недели/время
    сохраняются — курс продлевается на неделю, уроки не списываются). На исходную
    дату вставляется НЕ-курсовой маркер status='cancelled' (seq=NULL) — календарь
    показывает «отменённое» занятие зачёркнутым. Маркер несёт время/преподавателя
    отменённого занятия (чтобы попасть в нужный столбец/календарь).

    Батч (без N+1): один SELECT + один bulk_update + один INSERT маркера. Абонемент
    не трогаем. Возвращает новый план (get_plan).
    """
    now = msk_now()
    with transaction.atomic():
        # Сдвигаем +7 ТОЛЬКО курсовые pending/overdue строки. Доп. занятия и
        # маркеры отмены (seq=NULL) и проведённые (done) — неподвижные пины.
        tail = list(
            PlannedLesson.objects
            .select_for_update()
            .filter(
                group_id=group_id, scheduled_date__gte=from_date,
                seq__isnull=False, status__in=_MUTABLE_STATUSES,
            )
        )
        if tail:
            for p in tail:
                p.scheduled_date = p.scheduled_date + datetime.timedelta(days=7)
                p.updated_at = now
            PlannedLesson.objects.bulk_update(tail, ['scheduled_date', 'updated_at'])

        PlannedLesson.objects.create(
            group_id=group_id, seq=None, lesson_number=None,
            scheduled_date=from_date, scheduled_time=marker_time,
            teacher_id=marker_teacher_id, status=CANCELLED,
            created_at=now, updated_at=now,
        )

    return get_plan(group_id)


def add_extra(
    group_id: int,
    *,
    date: datetime.date,
    time: datetime.time,
    teacher_id: int | None,
) -> dict | None:
    """
    Доп. занятие вне курса (planner.extra): seq=NULL, lesson_number=NULL, is_extra.
    Не влияет на seq курсовых строк. None → группы нет (404).
    """
    if not Group.objects.filter(id=group_id).exists():
        return None
    now = msk_now()
    with transaction.atomic():
        row = planner.extra(date=date, time=time, teacher_id=teacher_id)
        obj = PlannedLesson.objects.create(
            group_id=group_id,
            seq=row.seq,
            lesson_number=row.lesson_number,
            scheduled_date=row.scheduled_date,
            scheduled_time=row.scheduled_time,
            teacher_id=row.teacher_id,
            status=row.status,
            created_at=now,
            updated_at=now,
        )
    return _plan_row_dict_obj(obj, teacher_names())


def generate_for_group(group_id: int) -> dict | None:
    """
    Идемпотентная генерация плана группы (обёртка над planner.generate +
    persist_plan для эндпоинта generate).

    None → группы нет (404). Иначе {'written': N, 'reason': str|None, 'plan': [...]}:
    reason (no_start_date / no_total_lessons / no_slots) — data-quality сигнал,
    когда план построить нельзя (план остаётся как есть, written=0).
    """
    g = (
        Group.objects
        .filter(id=group_id)
        .values(
            'id', 'lesson_duration_minutes', 'group_start_date', 'teacher_id',
            total_lessons=F('direction__total_lessons'),
        )
        .first()
    )
    if g is None:
        return None

    reason = None
    g_slots: list[Slot] = []
    if g['group_start_date'] is None:
        reason = 'no_start_date'
    elif g['total_lessons'] is None:
        reason = 'no_total_lessons'
    else:
        g_slots = slots_by_group([group_id]).get(group_id, [])
        if not g_slots:
            reason = 'no_slots'

    written = 0
    if reason is None:
        rows = planner.generate(
            start_date=g['group_start_date'],
            slots=g_slots,
            total_lessons=g['total_lessons'],
            duration_minutes=g['lesson_duration_minutes'],
            default_teacher_id=g['teacher_id'],
        )
        # create_only: повторный generate не затирает ручные операции над планом —
        # только досоздаёт недостающие seq (напр. при увеличении длины курса).
        written = persist_plan(group_id, rows, create_only=True)  # атомарен сам по себе

    return {'written': written, 'reason': reason, 'plan': get_plan(group_id)}


# ---------------------------------------------------------------------------
# Rebuild-from-facts (новый дефолт бэкфилла): прошлое = факты (коллапс даты в
# фактическую) + overdue-прошлое (позиции без факта на исторических датах) +
# будущее от текущего момента по актуальному открытому слоту. РАЗРУШИТЕЛЬНО
# (reset_plan): перезаписывает ручные операции будущего — для перелива ожидаемо.
# See docs/lesson-scheduling.md. Композиция чистых функций planner — в них же тесты.
# ---------------------------------------------------------------------------

def facts_by_group(group_ids: list[int]) -> dict[int, list[Fact]]:
    """Проведённые уроки (факты) по группам — планировщику как list[Fact].
    Батч (один запрос), упорядочено по (lesson_date, id) для позиционной линковки."""
    result: dict[int, list[Fact]] = {}
    if not group_ids:
        return result
    rows = (
        Lesson.objects
        .filter(group_id__in=group_ids)
        .order_by('lesson_date', 'id')
        .values('group_id', 'id', 'lesson_date', 'teacher_id')
    )
    for r in rows:
        result.setdefault(r['group_id'], []).append(Fact(
            lesson_date=r['lesson_date'],
            teacher_id=r['teacher_id'],
            fact_lesson_id=r['id'],
        ))
    return result


def _build_rebuild_rows(
    g: dict, slots: list[Slot], facts: list[Fact],
) -> tuple[list[PlannedRow] | None, str | None]:
    """Строки rebuild через planner.generate_from_facts: прошлое=факты, будущее от
    последнего факта по текущему слоту.

    (rows, reason). rows=None при блокирующей причине (нельзя построить план):
    no_start_date / no_total_lessons / no_slots. reason='no_open_slots' — прошлое
    (факты) построено, но будущее не развернуть (нет открытого слота)."""
    if g['group_start_date'] is None:
        return None, 'no_start_date'
    if g['total_lessons'] is None:
        return None, 'no_total_lessons'
    if not slots:
        return None, 'no_slots'
    open_slots = [s for s in slots if s.effective_to is None]
    rows = planner.generate_from_facts(
        facts=facts,
        current_slots=open_slots,
        total_lessons=g['total_lessons'],
        duration_minutes=g['lesson_duration_minutes'],
        default_teacher_id=g['teacher_id'],
        group_start_date=g['group_start_date'],
    )
    return rows, (None if open_slots else 'no_open_slots')


def rebuild_group_plan(
    group_id: int, g: dict, slots: list[Slot], facts: list[Fact],
    *, dry_run: bool = False,
) -> dict:
    """Пересобрать план одной группы (reset + generate_from_facts + bulk_create),
    батч-данные передаёт вызывающий (команда) — без N+1. РАЗРУШИТЕЛЬНО.
    {'written', 'reason'}. Результат today-независим (будущее от последнего факта).

    dry_run=True: ничего не пишет, 'written' = сколько строк было бы записано."""
    rows, reason = _build_rebuild_rows(g, slots, facts)
    if rows is None:
        return {'written': 0, 'reason': reason}
    if dry_run:
        return {'written': len(rows), 'reason': reason}
    now = msk_now()
    with transaction.atomic():
        reset_plan(group_id)
        PlannedLesson.objects.bulk_create([
            PlannedLesson(
                group_id=group_id,
                seq=r.seq,
                lesson_number=r.lesson_number,
                scheduled_date=r.scheduled_date,
                scheduled_time=r.scheduled_time,
                teacher_id=r.teacher_id,
                status=r.status,
                fact_lesson_id=r.fact_lesson_id,
                created_at=now,
                updated_at=now,
            )
            for r in rows
        ])
    return {'written': len(rows), 'reason': reason}


def rebuild_from_facts(group_id: int) -> dict | None:
    """Single-group обёртка rebuild_group_plan (сама читает группу/слоты/факты).

    None → группы нет. Результат today-независим (будущее считается от даты
    последнего факта, не от «сегодня»). Команда бэкфилла использует батч-путь
    (active_groups + slots_by_group + facts_by_group + rebuild_group_plan)."""
    g = (
        Group.objects
        .filter(id=group_id)
        .values(
            'id', 'lesson_duration_minutes', 'group_start_date', 'teacher_id',
            total_lessons=F('direction__total_lessons'),
        )
        .first()
    )
    if g is None:
        return None
    slots = slots_by_group([group_id]).get(group_id, [])
    facts = facts_by_group([group_id]).get(group_id, [])
    return rebuild_group_plan(group_id, g, slots, facts)
