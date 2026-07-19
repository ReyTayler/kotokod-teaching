"""
Бизнес-логика планирования: сборка календаря плановых занятий за окно.

View → Service (здесь) → occurrences (чистый генератор) + repository (ORM).
Единый источник расписания — group_schedule_slots (не regex по имени группы).
"""
from __future__ import annotations

import datetime

from apps.audit.services import log_event
from apps.core.utils.dates import MSK, msk_now
from apps.extra_lessons import repository as extra_lessons_repository
from apps.extra_lessons.models import MAKEUP_DONE as EXTRA_DONE
from apps.scheduling import repository
from apps.scheduling.occurrences import CANCELLED, DONE, OVERDUE, PENDING

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


def _report_day(d: datetime.date) -> int:
    """Кодировка дня недели Вс=0 (как report.day / JS getDay) из реальной даты."""
    return (d.weekday() + 1) % 7


def _planned_status(r: dict, now_msk: datetime.datetime) -> str:
    """
    Статус планового занятия НА ЧТЕНИИ из строки planned_lessons.

      done      — status=='done' или есть fact_lesson (связь план→факт);
      cancelled — как хранится (маркер отмены);
      иначе     — overdue, если datetime(дата, время, МСК) уже наступил, иначе pending.

    (Бэкфилл оставил прошлые незаполненные строки как pending → overdue считаем здесь,
    на чтении, по времени занятия в МСК. Перенос показывается через moved_from_date —
    отдельного статуса 'moved' нет.)
    """
    if r['status'] == DONE or r['fact_lesson_id'] is not None:
        return DONE
    if r['status'] == CANCELLED:
        return CANCELLED
    occ_dt = datetime.datetime.combine(
        r['scheduled_date'], r['scheduled_time'] or datetime.time(0, 0), tzinfo=MSK,
    )
    return OVERDUE if now_msk >= occ_dt else PENDING


def _planned_label(status: str) -> str:
    return _LABELS.get(status, '')


def _planned_occurrence_dict(
    r: dict, students: list[dict], tnames: dict, now_msk: datetime.datetime,
) -> dict:
    """Строка planned_lessons → dict календаря (контракт ответа /api/calendar).

    teacher = имя препода занятия (planned_lesson.teacher), иначе имя учителя группы;
    teacherOverride = имя, если препод занятия ≠ учитель группы (как прежде).
    Перенос показывается через movedFrom (moved_from_date); movedTo не используется.
    """
    is_half = r['lesson_duration_minutes'] == 45
    status = _planned_status(r, now_msk)
    sub_id = r.get('substitute_teacher_id')
    content_teacher_id = r['teacher_id']
    group_teacher_id = r['group_teacher_id']
    effective_id = sub_id or content_teacher_id
    is_override = (sub_id is not None) or (
        content_teacher_id is not None and content_teacher_id != group_teacher_id
    )
    teacher = tnames.get(effective_id) if effective_id else tnames.get(group_teacher_id)
    ln = r['lesson_number']
    return {
        'group': r['group_name'],
        'groupId': r['group_pk'],
        'groupDisplay': r['group_name'],
        'teacher': teacher,
        'teacherOverride': tnames.get(effective_id) if is_override else None,
        'direction': r['direction_name'],
        'color': r['direction_color'],
        'isGroup': not r['is_individual'],
        'durationMinutes': r['lesson_duration_minutes'],
        'vkChat': r['group_vk_chat'] or None,
        'date': _iso(r['scheduled_date']),
        'time': _hhmm(r['scheduled_time']),
        'day': _report_day(r['scheduled_date']),
        'seq': r['seq'],
        'lessonNumber': float(ln) if ln is not None else None,
        'isHalf': is_half,
        'isExtra': r['seq'] is None,
        'status': status,
        'label': _planned_label(status),
        'movedFrom': _iso(r['moved_from_date']),
        'movedTo': None,
        'students': students,
    }


def _extra_lesson_status(status_value: str, scheduled_date, scheduled_time, now_msk) -> str:
    """
    Статус карточки доп.урока → тот же алфавит OccStatus, что и у planned_lessons.

    status_value — значение AbsenceResolution.status (свой словарь
    pending/makeup_scheduled/makeup_done из apps.extra_lessons.models), сравниваем
    с его константой EXTRA_DONE (=makeup_done), а не с DONE (тот — OccStatus для
    ВЫХОДА этой функции, из apps.scheduling.occurrences; строки совпадают случайно,
    это разные словари). Резолюции в статусе pending имеют scheduled_date=NULL и в
    окно календаря не попадают, поэтому сюда доходят только makeup_scheduled/done.
    """
    if status_value == EXTRA_DONE:
        return DONE
    occ_dt = datetime.datetime.combine(scheduled_date, scheduled_time, tzinfo=MSK)
    return OVERDUE if now_msk >= occ_dt else PENDING


def _extra_lesson_occurrence_dict(r: dict, now_msk: datetime.datetime) -> dict:
    """Строка extra_lessons.assignments_in_window → dict календаря (occurrence-
    форма). extraLessonId — дискриминатор для фронта (WeekGrid красит красным,
    OccurrenceMenu подставляет «Провести доп.урок» вместо «Отметить урок»)."""
    status = _extra_lesson_status(r['status'], r['scheduled_date'], r['scheduled_time'], now_msk)
    label = f"Доп.урок · {r['missed_lesson_group_name']}"
    return {
        'group': label,
        'groupId': None,
        'groupDisplay': label,
        'teacher': r['teacher_name'],
        'teacherOverride': None,
        'direction': None,
        'color': None,
        # У planned occurrence isGroup — свойство группы (not is_individual);
        # здесь, за неимением группового контекста в самой карточке доп.урока,
        # это счётчик участников ЭТОГО назначения — осознанное отличие:
        # фронт всё равно узнаёт карточку доп.урока по extraLessonId (красный
        # цвет, своё меню), isGroup для неё чисто косметический сигнал.
        'isGroup': len(r['student_names']) > 1,
        'durationMinutes': r['duration_minutes'],
        'vkChat': None,
        'date': _iso(r['scheduled_date']),
        'time': _hhmm(r['scheduled_time']),
        'day': _report_day(r['scheduled_date']),
        'seq': None,
        'lessonNumber': None,
        'isHalf': False,
        'isExtra': False,
        'extraLessonId': r['id'],
        'status': status,
        'label': _planned_label(status),
        'movedFrom': None,
        'movedTo': None,
        'students': [{'name': n} for n in r['student_names']],
    }


def build_calendar(
    window_from: datetime.date,
    window_to: datetime.date,
    teacher_id: int | None = None,
) -> dict:
    """
    Плановые занятия преподавателя за окно — чтение materialize-on-write
    planned_lessons (заменило прежний compute-on-read из слотов + исключений).

    Скоуп — по `planned_lesson.teacher_id` (препод конкретного занятия): смена
    преподавателя занятия автоматически перекидывает урок между календарями.
    Статусы вычисляются на чтении (_planned_status). unscheduled — активные группы
    ЭТОГО преподавателя (по group.teacher_id) без единой плановой строки, с причиной.

    Возвращает {occurrences, unscheduled, window} — контракт сохранён 1:1.
    """
    if teacher_id is None:
        # Календарь всегда скоупится по преподавателю (view передаёт teacher_id).
        # Без препода планового скоупа нет — возвращаем пустой конверт.
        return {
            'occurrences': [],
            'unscheduled': [],
            'window': {'from': window_from.isoformat(), 'to': window_to.isoformat()},
        }

    rows = repository.planned_lessons_in_window(window_from, window_to, teacher_id)
    group_ids = sorted({r['group_pk'] for r in rows})
    students = repository.student_names_by_group(group_ids)
    tnames = repository.teacher_names()
    now = msk_now()

    occurrences: list[dict] = []
    for r in rows:
        g_students = [{'name': n} for n in students.get(r['group_pk'], [])]
        occurrences.append(_planned_occurrence_dict(r, g_students, tnames, now))

    for r in extra_lessons_repository.assignments_in_window(teacher_id, window_from, window_to):
        occurrences.append(_extra_lesson_occurrence_dict(r, now))

    occurrences.sort(key=lambda x: (x['date'], x['time'] or ''))
    return {
        'occurrences': occurrences,
        'unscheduled': repository.groups_without_plan(teacher_id),
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


def autogenerate_plan_on_setup(
    group_id: int, *, source: str, actor_email: str | None = None,
) -> None:
    """Автогенерация плана при первичной настройке группы (Механизм 1).

    Срабатывает ТОЛЬКО первый раз: guard plan_exists(active_only=True) — непустой
    план ИЛИ неактивная/отсутствующая группа → тихий выход. Пока нет старта/слота/
    total — generate_for_group вернёт reason (written=0), план останется пустым,
    следующая правка попробует снова. Идемпотентно (generate_for_group create_only).

    Гонку двух почти одновременных триггеров (старт и слот) глушим на IntegrityError
    (UniqueConstraint(group, seq)): план уже создан конкурентом → выходим. Аудит
    plan_auto_generate пишем только при реальной записи (written>0); source — точка
    вызова (group_create/group_update/schedule_change), actor_email опционален
    (автоматическое действие). Вызывается синхронно из groups.services после того,
    как repository закоммитил группу/слоты (ATOMIC_REQUESTS=False)."""
    from django.db import IntegrityError

    if repository.plan_exists(group_id, active_only=True):
        return
    try:
        result = repository.generate_for_group(group_id)
    except IntegrityError:
        return
    if result is None:
        return
    if result['written'] > 0:
        log_event(
            'plan_auto_generate',
            actor_email=actor_email,
            target_id=group_id,
            meta={
                'written': result['written'],
                'reason': result['reason'],
                'source': source,
            },
        )


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


def change_teacher(group_id: int, lesson_id: int, data: dict, request) -> dict | None:
    """Разовая смена преподавателя одной строки + аудит. None → строки нет (404);
    ValueError → строка проведена (view → 409). Дату/время не трогает."""
    new_teacher_id = data['new_teacher_id']
    row = repository.change_teacher(group_id, lesson_id, new_teacher_id)
    if row is None:
        return None
    log_event(
        'plan_change_teacher',
        actor_email=_actor(request),
        target_id=group_id,
        meta={'lesson_id': lesson_id, 'new_teacher_id': new_teacher_id},
        request=request,
    )
    return row


def change_teacher_permanent(group_id: int, data: dict, request) -> list[dict] | None:
    """Смена преподавателя навсегда (хвост seq>=from_seq) + аудит. None → группы нет
    (404); ValueError → нет курсовых строк с позиции (view → 400)."""
    plan = repository.change_teacher_permanent(
        group_id,
        from_seq=data['from_seq'],
        new_teacher_id=data['new_teacher_id'],
    )
    if plan is None:
        return None
    log_event(
        'plan_change_teacher_permanent',
        actor_email=_actor(request),
        target_id=group_id,
        meta={'from_seq': data['from_seq'], 'new_teacher_id': data['new_teacher_id']},
        request=request,
    )
    return plan


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
    if anchor['status'] in (CANCELLED, DONE):
        raise ValueError(
            'Отмена доступна только для активного занятия '
            '(не отменённого/проведённого).'
        )
    from_date = anchor['scheduled_date']
    plan = repository.cancel_lesson(
        group_id, from_date,
        marker_time=anchor['scheduled_time'],
        marker_teacher_id=anchor['teacher_id'],
    )
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
