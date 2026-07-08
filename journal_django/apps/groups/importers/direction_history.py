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


@dataclass
class TransitionSlot:
    course_raw: str
    lessons: int
    status: str


@dataclass
class StudentRow:
    full_name: str
    transitions: list[TransitionSlot]


# 0-indexed колонка «Курс» для каждого слота «Переход N» (лессонс/месяцев/статус —
# следующие 3 колонки подряд). До 6 слотов в реальном файле, но парсер не ограничивает
# их число жёстко — читает все группы по 4 колонки начиная с индекса 3.
_SLOT_START_COLUMNS = [3, 7, 11, 15, 19, 23]


def parse_sheet(path: str) -> list[StudentRow]:
    """
    Читает лист SHEET_NAME файла path. Строки 1-2 (1-indexed) — заголовки
    (групповые + колоночные), данные — с 3-й строки. Строка без ФИ (col A) —
    пропускается (хвостовые пустые шаблонные строки в реальном файле).
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb[SHEET_NAME]

        rows: list[StudentRow] = []
        for row in ws.iter_rows(min_row=3, values_only=True):
            full_name_raw = row[0] if len(row) > 0 else None
            if full_name_raw is None or str(full_name_raw).strip() == '':
                continue

            transitions: list[TransitionSlot] = []
            for start in _SLOT_START_COLUMNS:
                course = row[start] if start < len(row) else None
                lessons_raw = row[start + 1] if start + 1 < len(row) else None
                status_raw = row[start + 3] if start + 3 < len(row) else None
                if course is None or lessons_raw is None:
                    continue
                try:
                    lessons = int(round(float(lessons_raw)))
                except (TypeError, ValueError):
                    continue
                if lessons <= 0:
                    continue
                transitions.append(TransitionSlot(
                    course_raw=str(course), lessons=lessons, status=str(status_raw or ''),
                ))

            if transitions:
                rows.append(StudentRow(full_name=str(full_name_raw).strip(), transitions=transitions))

        return rows
    finally:
        wb.close()
