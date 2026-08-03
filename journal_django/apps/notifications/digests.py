"""
Сборка и рассылка дайджестов.

Оба дайджеста — только в личку (спека, п. 2.5). Данные собираются ОДНИМ запросом
на всю школу и группируются в памяти: сто преподавателей — это два запроса,
а не двести. VPS 2 CPU / 2 ГБ, запрос на преподавателя здесь недопустим.
"""
from __future__ import annotations

import datetime
import logging

from django.db.models import F

from apps.core.utils.dates import msk_now
from apps.dashboard import fill_service
from apps.extra_lessons import repository as extra_repo
from apps.groups.models import Group
from apps.notifications import messages, services
from apps.notifications.constants import CHANNEL_DM, KIND_FILL_DIGEST, KIND_MORNING_DIGEST
from apps.notifications.models import TelegramRecipient
from apps.scheduling import repository as scheduling_repo
from apps.scheduling.occurrences import CANCELLED, MOVED

logger = logging.getLogger(__name__)


def _active_recipients() -> dict[int, tuple[int, str]]:
    """teacher_id → (chat_id, ФИО). Только активные привязки."""
    rows = (TelegramRecipient.objects
            .filter(is_active=True)
            .values_list('teacher_id', 'telegram_user__chat_id', 'teacher__name'))
    return {teacher_id: (chat_id, name) for teacher_id, chat_id, name in rows}


def _collect_day(day: datetime.date) -> dict[int, list[dict]]:
    """
    Занятия дня по всей школе, сгруппированные по эффективному преподавателю.

    Плановые занятия: planned_lessons_in_window уже фильтрует активные группы и
    учитывает замену — занятие попадает в день заменяющего, а не основного.
    Отменённые и перенесённые строки исключаются.
    """
    result: dict[int, list[dict]] = {}

    for row in scheduling_repo.planned_lessons_in_window(day, day, teacher_id=None):
        if row['status'] in (CANCELLED, MOVED):
            continue
        substitute_id = row['substitute_teacher_id']
        effective = substitute_id or row['teacher_id']
        if effective is None:
            continue
        result.setdefault(effective, []).append({
            'time': row['scheduled_time'].strftime('%H:%M') if row['scheduled_time'] else '—',
            'group': row['group_name'],
            'direction': row['direction_name'],
            'seq': row['seq'],
            'is_substitute': substitute_id is not None,
            'is_extra': False,
        })

    extra_rows = extra_repo.scheduled_on(day)
    if extra_rows:
        group_ids = {r['group_pk'] for r in extra_rows if r['group_pk']}
        groups = {
            g['id']: g for g in Group.objects
            .filter(id__in=group_ids)
            .values('id', 'name', direction_name=F('direction__name'))
        }
        for row in extra_rows:
            teacher_id = row['assigned_teacher_id']
            if teacher_id is None:
                continue
            group = groups.get(row['group_pk']) or {}
            result.setdefault(teacher_id, []).append({
                'time': row['scheduled_time'].strftime('%H:%M') if row['scheduled_time'] else '—',
                'group': group.get('name', '—'),
                'direction': group.get('direction_name', '—'),
                'seq': None,
                'is_substitute': False,
                'is_extra': True,
            })

    for items in result.values():
        items.sort(key=lambda i: i['time'])
    return result


def send_morning_digest(day: datetime.date | None = None) -> int:
    """Разослать утренний список занятий. Возвращает число поставленных сообщений."""
    day = day or msk_now().date()
    recipients = _active_recipients()
    if not recipients:
        return 0

    queued = 0
    for teacher_id, items in _collect_day(day).items():
        if not items:
            continue
        target = recipients.get(teacher_id)
        if target is None:
            continue
        chat_id, teacher_name = target
        text = messages.morning_digest(teacher_name=teacher_name, day=day, items=items)
        created = services.enqueue(
            kind=KIND_MORNING_DIGEST, channel=CHANNEL_DM, chat_id=chat_id, text=text,
            dedup_key=f'morning:{teacher_id}:{day.isoformat()}',
            recipient_teacher_id=teacher_id,
        )
        queued += int(created)
    return queued


def send_fill_digest(day: datetime.date | None = None) -> int:
    """
    Разослать список незаполненных отчётов.

    Логика «что считается незаполненным» НЕ переписывается: берём тот же расчёт,
    что питает вкладку «Заполнить» дашборда, иначе через полгода два места разъедутся.

    Номер урока — ПОРЯДКОВЫЙ (seq), не `lesson_number` (внутренний вес для денег,
    на 45-минутных курсах lesson_number = seq * 0.5). unfilled_lessons() теперь
    отдаёт готовый `seq` для плановых строк (см. apps.dashboard.fill_service и
    apps.scheduling.repository.unfilled_planned_lessons) — округление lesson_number
    сюда больше не годится и не используется.
    """
    day = day or msk_now().date()
    recipients = _active_recipients()
    if not recipients:
        return 0

    by_teacher: dict[int, list[dict]] = {}
    for row in fill_service.unfilled_lessons(sort_dir='asc'):
        teacher_id = row.get('teacher_id')
        if teacher_id is None:
            continue
        by_teacher.setdefault(teacher_id, []).append({
            'date': datetime.date.fromisoformat(row['date']),
            'time': row['time'] or '—',
            'group': row['group_name'],
            'direction': row['direction_name'],
            'seq': row.get('seq'),
        })

    queued = 0
    for teacher_id, items in by_teacher.items():
        target = recipients.get(teacher_id)
        if target is None:
            continue
        chat_id, _name = target
        text = messages.fill_digest(items=items)
        created = services.enqueue(
            kind=KIND_FILL_DIGEST, channel=CHANNEL_DM, chat_id=chat_id, text=text,
            dedup_key=f'fill:{teacher_id}:{day.isoformat()}',
            recipient_teacher_id=teacher_id,
        )
        queued += int(created)
    return queued
