"""
Импорт истории направлений учеников из внешней таблицы «Переходимость по курсам».

Парсинг/классификация/агрегация — чистые функции (без БД), легко тестируемые.
import_to_db() — единственная функция с побочными эффектами (пишет в БД).

См. docs/superpowers/specs/2026-07-08-direction-history-import-design.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SHEET_NAME = 'Переходимость по курсам'
ARCHIVE_TEACHER_NAME = 'Архив (импорт истории)'
LEGACY_LESSON_DATE = '2023-01-01'

# Статусы «Переход N», которые означают, что направление ЗАВЕРШЕНО и переносится в архив.
STATUS_ARCHIVE = {
    'Закончил и перешёл',
    'Недоучился и перешёл',
    'Ожидание перехода',
    'Отказ',
}
# Статус «Продолжает учиться» — точное совпадение; «Заморозка*» — по префиксу
# (в таблице встречаются варианты «Заморозка Сентябрь», «Заморозка Июль» и т.п.).
STATUS_SKIP_CURRENT_EXACT = {'Продолжает учиться'}


def is_skip_current(status: str) -> bool:
    """Статус означает «направление ещё текущее» — не архивируем, не считаем ошибкой."""
    return status in STATUS_SKIP_CURRENT_EXACT or status.startswith('Заморозка')


# Порядок важен только визуально — паттерны не пересекаются по смыслу.
_COURSE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'питон|python', re.I), 'Python'),
    (re.compile(r'роблокс|roblox', re.I), 'Roblox Группа'),
    (re.compile(r'скретч|scratch', re.I), 'Scratch'),
    (re.compile(r'майнкрафт|minecraft', re.I), 'Minecraft'),
    (re.compile(r'блендер|blender', re.I), 'Blender'),
    (re.compile(r'веб-дизайн', re.I), 'Веб-дизайн'),
    (re.compile(r'веб-разработка|web-разработка', re.I), 'Web-разработка'),
]


def normalize_course_name(raw: str | None) -> str | None:
    """
    Сырое название курса из таблицы -> каноничное имя направления в системе.

    Всегда возвращает ГРУППОВУЮ версию направления, даже если в исходном названии
    явно написано «ИНДИВ» — приписки (Старый/ИНДИВ/Особые Условия/N уроков)
    игнорируются по решению пользователя (см. спеку, раздел «Нормализация»).
    None, если ни один паттерн не подошёл (нераспознанный курс).
    """
    text = (raw or '').strip()
    if not text:
        return None
    for pattern, canonical in _COURSE_PATTERNS:
        if pattern.search(text):
            return canonical
    return None
