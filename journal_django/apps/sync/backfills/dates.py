"""Разбор дат из Google Sheets. Порт parseStartDate/parseLessonDate
(scripts/backfill-students.js, scripts/backfill-lessons.js).

Google Sheets API отдаёт ячейки как обычные JSON-строки (дефолтный render
mode FORMATTED_VALUE) — ветка "value instanceof Date" в оригинальных
JS-скриптах была защитной на случай другого рендера и на практике никогда не
срабатывала с sheets.spreadsheets.values.get() без valueRenderOption. В этом
порту она не нужна — работаем только со строками.

parse_start_date заякорен с обеих сторон (вся строка обязана быть датой) —
для дат рождения/старта абонемента. parse_lesson_date заякорен только слева
(хвост после даты игнорируется) — для дат в журнале уроков, где в ячейке
иногда встречается день недели после даты.
"""
from __future__ import annotations

import re

_DATE_ANCHORED_RE = re.compile(r'^(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})$')
_DATE_PREFIX_RE = re.compile(r'^(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})')


def _to_iso(dd: str, mm: str, yyyy: str) -> str:
    dd = dd.zfill(2)
    mm = mm.zfill(2)
    if len(yyyy) == 2:
        yyyy = '20' + yyyy
    return f'{yyyy}-{mm}-{dd}'


def parse_start_date(value) -> str | None:
    """ДД.ММ.ГГГГ (вся строка) → YYYY-MM-DD, иначе None."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = _DATE_ANCHORED_RE.match(s)
    if not m:
        return None
    return _to_iso(*m.groups())


def parse_lesson_date(value) -> str | None:
    """ДД.ММ.ГГГГ в начале строки (хвост игнорируется) → YYYY-MM-DD, иначе None."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = _DATE_PREFIX_RE.match(s)
    if not m:
        return None
    return _to_iso(*m.groups())
