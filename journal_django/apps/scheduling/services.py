"""
Бизнес-логика планирования: сборка календаря плановых занятий за окно.

View → Service (здесь) → occurrences (чистый генератор) + repository (ORM).
Единый источник расписания — group_schedule_slots (не regex по имени группы).
"""
from __future__ import annotations

import datetime

from apps.audit.services import log_event
from apps.core.utils.dates import msk_now
from apps.scheduling import repository
from apps.scheduling.occurrences import (
    Occurrence, build_occurrences,
    CANCELLED, DONE, MOVED, OVERDUE, PENDING,
)

_LABELS = {
    DONE: 'Заполнено',
    OVERDUE: 'Надо заполнить',
    PENDING: 'Пока урока не было',
    CANCELLED: 'Отменён',
}


def _iso(d: datetime.date | None) -> str | None:
    return d.isoformat() if d else None


def _hhmm(t: datetime.time | None) -> str | None:
    return t.strftime('%H:%M') if t else None


def _ddmm(d: datetime.date) -> str:
    return f'{d.day:02d}.{d.month:02d}'


def _report_day(d: datetime.date) -> int:
    """Кодировка дня недели Вс=0 (как report.day / JS getDay) из реальной даты."""
    return (d.weekday() + 1) % 7


def _label(o: Occurrence) -> str:
    if o.status == MOVED and o.moved_to:
        return f'Перенесён на {_ddmm(o.moved_to)}'
    return _LABELS.get(o.status, '')


def _occurrence_dict(g: dict, o: Occurrence, students: list[dict], teacher_names: dict) -> dict:
    is_half = g['lesson_duration_minutes'] == 45
    teacher = (
        teacher_names.get(o.teacher_override_id)
        if o.teacher_override_id else g['teacher_name']
    )
    return {
        'group': g['name'],
        'groupDisplay': g['name'],
        'teacher': teacher,
        'teacherOverride': teacher_names.get(o.teacher_override_id) if o.teacher_override_id else None,
        'direction': g['direction_name'],
        'color': g['direction_color'],
        'isGroup': not g['is_individual'],
        'date': _iso(o.date),
        'time': _hhmm(o.time),
        'day': _report_day(o.date),
        'seq': o.seq if o.seq >= 0 else None,
        'lessonNumber': float(o.lesson_number) if o.lesson_number is not None else None,
        'isHalf': is_half,
        'isExtra': o.is_extra,
        'status': o.status,
        'label': _label(o),
        'movedFrom': _iso(o.moved_from),
        'movedTo': _iso(o.moved_to),
        'students': students,
    }


def build_calendar(
    window_from: datetime.date,
    window_to: datetime.date,
    teacher_id: int | None = None,
) -> dict:
    """
    Плановые занятия всех активных групп (опц. одного преподавателя) за окно.

    Возвращает {occurrences, unscheduled, window}. unscheduled — группы, которые
    нельзя запланировать (нет старта/слотов) с причиной (data-quality сигнал
    вместо тихого попадания в noTime, как раньше в regex-пути).
    """
    groups = repository.active_groups(teacher_id)
    ids = [g['id'] for g in groups]

    slots = repository.slots_by_group(ids)
    exceptions = repository.exceptions_by_group(ids)
    facts = repository.fact_dates_by_group(ids, window_from, window_to)
    students = repository.student_names_by_group(ids)
    tnames = repository.teacher_names()
    now = msk_now()

    occurrences: list[dict] = []
    unscheduled: list[dict] = []

    for g in groups:
        gid = g['id']
        g_slots = slots.get(gid, [])
        if g['group_start_date'] is None:
            unscheduled.append({'group': g['name'], 'reason': 'no_start_date'})
            continue
        if not g_slots:
            unscheduled.append({'group': g['name'], 'reason': 'no_slots'})
            continue

        occs = build_occurrences(
            start_date=g['group_start_date'],
            duration_minutes=g['lesson_duration_minutes'],
            total_lessons=g['total_lessons'],
            slots=g_slots,
            exceptions=exceptions.get(gid, []),
            fact_dates=facts.get(gid, set()),
            window_from=window_from,
            window_to=window_to,
            now_msk=now,
        )
        g_students = [{'name': n} for n in students.get(gid, [])]
        for o in occs:
            occurrences.append(_occurrence_dict(g, o, g_students, tnames))

    occurrences.sort(key=lambda x: (x['date'], x['time'] or ''))
    return {
        'occurrences': occurrences,
        'unscheduled': unscheduled,
        'window': {'from': window_from.isoformat(), 'to': window_to.isoformat()},
    }


# ---------------------------------------------------------------------------
# Admin-план: оркестрация операций над planned_lessons + аудит (шаг 4).
#
# Тонкие функции: валидация — в сериализаторах (view), ORM/логика дат — в
# repository/planner. Здесь — конвертация строк во date/time-объекты, вызов
# repository и log_event на КАЖДУЮ мутацию. RBAC/CSRF — на уровне view.
# meta не содержит PII/секретов (только id/seq/даты/время).
# ---------------------------------------------------------------------------

def _to_date(value) -> datetime.date | None:
    """'YYYY-MM-DD' → date. None/'' → None. (DateStringField отдаёт валидную строку.)"""
    if not value:
        return None
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(value)


def _to_time(value) -> datetime.time | None:
    """'HH:MM' / 'HH:MM:SS' → time. None/'' → None. (Формат уже проверен сериализатором.)"""
    if not value:
        return None
    if isinstance(value, datetime.time):
        return value
    parts = [int(x) for x in value.split(':')]
    return datetime.time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)


def _actor(request):
    return getattr(getattr(request, 'user', None), 'email', None)


def get_plan(group_id: int) -> list[dict] | None:
    """Плановые строки группы (или None, если группы нет)."""
    return repository.get_plan(group_id)


def generate_plan(group_id: int, request) -> list[dict] | None:
    """Идемпотентная генерация плана + аудит. None → группы нет."""
    result = repository.generate_for_group(group_id)
    if result is None:
        return None
    log_event(
        'plan_generate',
        actor_email=_actor(request),
        target_id=group_id,
        meta={'written': result['written'], 'reason': result['reason']},
        request=request,
    )
    return result['plan']


def reschedule(group_id: int, lesson_id: int, data: dict, request) -> dict | None:
    """Разовый перенос + аудит. None → строки нет; ValueError → перенос 'done'."""
    new_teacher_id = data.get('new_teacher_id')
    row = repository.reschedule_lesson(
        group_id,
        lesson_id,
        _to_date(data['new_date']),
        _to_time(data.get('new_time')),
        new_teacher_id,
    )
    if row is None:
        return None
    log_event(
        'plan_reschedule',
        actor_email=_actor(request),
        target_id=group_id,
        meta={
            'lesson_id': lesson_id,
            'new_date': data['new_date'],
            'new_time': data.get('new_time'),
            'new_teacher_id': new_teacher_id,
        },
        request=request,
    )
    return row


def permanent_change(group_id: int, data: dict, request) -> list[dict] | None:
    """Перенос навсегда + аудит. None → группы нет; ValueError → мульти-слот /
    нет времени слота / нет курсовых строк с позиции (view → 400).

    effective_from выводится на сервере в repository.permanent_change (не из тела)."""
    plan = repository.permanent_change(
        group_id,
        from_seq=data['from_seq'],
        new_day_of_week=data['new_day_of_week'],
        new_time=_to_time(data.get('new_time')),
        new_teacher_id=data.get('new_teacher_id'),
    )
    if plan is None:
        return None
    log_event(
        'plan_permanent_change',
        actor_email=_actor(request),
        target_id=group_id,
        meta={
            'from_seq': data['from_seq'],
            'new_day_of_week': data['new_day_of_week'],
            'new_time': data.get('new_time'),
            'new_teacher_id': data.get('new_teacher_id'),
        },
        request=request,
    )
    return plan


def cancel(group_id: int, lesson_id: int, request) -> list[dict] | None:
    """Отмена со сдвигом хвоста + аудит. from_date выводится из даты занятия lid.

    None → строки нет (404). ValueError → якорь не курсовой/активный (view → 400):
    отмена определена только для курсовых строк в статусе pending/overdue; для
    extra (seq IS NULL) и уже cancelled/moved сдвиг хвоста бессмыслен."""
    anchor = repository.get_plan_lesson(group_id, lesson_id)
    if anchor is None:
        return None
    if anchor['seq'] is None:
        raise ValueError('Отмена доступна только для курсового занятия (не доп. занятия).')
    if anchor['status'] in (CANCELLED, MOVED, DONE):
        raise ValueError(
            'Отмена доступна только для активного занятия '
            '(не отменённого/перенесённого/проведённого).'
        )
    from_date = anchor['scheduled_date']
    plan = repository.cancel_lesson(group_id, from_date)
    log_event(
        'plan_cancel',
        actor_email=_actor(request),
        target_id=group_id,
        meta={'lesson_id': lesson_id, 'from_date': from_date.isoformat()},
        request=request,
    )
    return plan


def add_extra(group_id: int, data: dict, request) -> dict | None:
    """Доп. занятие вне курса + аудит. None → группы нет."""
    teacher_id = data.get('teacher_id')
    row = repository.add_extra(
        group_id,
        date=_to_date(data['date']),
        time=_to_time(data['time']),
        teacher_id=teacher_id,
    )
    if row is None:
        return None
    log_event(
        'plan_extra',
        actor_email=_actor(request),
        target_id=group_id,
        meta={'date': data['date'], 'time': data['time'], 'teacher_id': teacher_id},
        request=request,
    )
    return row
