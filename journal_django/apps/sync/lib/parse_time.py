# journal_django/apps/sync/lib/parse_time.py
"""Разбор дня недели/времени и длительности урока из названия группы.
Порт scripts/lib/parse-time.js (parseTimeSlots/parseLessonDuration).
"""
from __future__ import annotations

import re

_DAY_MAP = {
    'воскресенье': 0, 'вс': 0,
    'понедельник': 1, 'пн': 1,
    'вторник': 2, 'вт': 2,
    'среда': 3, 'ср': 3,
    'четверг': 4, 'чт': 4,
    'пятница': 5, 'пт': 5,
    'суббота': 6, 'сб': 6,
}

_DAY_PATTERN = '(воскресенье|понедельник|вторник|среда|четверг|пятница|суббота|вс|пн|вт|ср|чт|пт|сб)'
_TIME_SLOT_RE = re.compile(rf'{_DAY_PATTERN}[^0-9]*?(\d{{1,2}})[:.\-](\d{{2}})', re.IGNORECASE)
_DURATION_45_RE = re.compile(r'\b45\s*минут', re.IGNORECASE)


def parse_time_slots(group_name) -> list[dict]:
    """Извлекает все пары (день недели, время начала) из названия группы."""
    if not group_name:
        return []
    slots = []
    for m in _TIME_SLOT_RE.finditer(str(group_name)):
        day = _DAY_MAP.get(m.group(1).lower())
        if day is None:
            continue
        hh = m.group(2).zfill(2)
        mm = m.group(3)
        slots.append({'day_of_week': day, 'start_time': f'{hh}:{mm}:00'})
    return slots


def parse_lesson_duration(group_name) -> int:
    """45, если в названии группы встречается "45 минут", иначе 90 (стандартная длительность)."""
    return 45 if _DURATION_45_RE.search(str(group_name or '')) else 90
