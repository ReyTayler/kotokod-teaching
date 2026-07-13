"""Безопасный доступ к "рваным" строкам Google Sheets + JS-подобный parseInt/parseFloat.

Google Sheets API отдаёт строки без хвостовых пустых ячеек ("рваные" строки) —
обращение по индексу может выйти за границу. cell() безопасно достаёт значение
как строку. parse_int/parse_float берут ведущее целое/десятичное число из строки
(без экспоненциальной записи), а не требуют строгого совпадения — исходные
Node-скрипты полагались именно на это поведение (JS parseInt/parseFloat) при
разборе таблиц.
"""
from __future__ import annotations

import re

_LEADING_INT_RE = re.compile(r'^\s*(-?\d+)')
_LEADING_FLOAT_RE = re.compile(r'^\s*(-?\d+(?:\.\d+)?)')


def cell(row: list, idx: int) -> str:
    """row[idx] как строка, '' если индекс вне диапазона или значение отсутствует."""
    if idx >= len(row):
        return ''
    value = row[idx]
    if value is None:
        return ''
    return str(value).strip()


def parse_int(raw) -> int | None:
    """Как JS `parseInt(raw, 10)` — ведущие цифры строки, иначе None (аналог NaN)."""
    if raw is None:
        return None
    m = _LEADING_INT_RE.match(str(raw))
    return int(m.group(1)) if m else None


def parse_float(raw) -> float | None:
    """Как JS `parseFloat(raw)` — ведущее число, иначе None (аналог NaN)."""
    if raw is None:
        return None
    m = _LEADING_FLOAT_RE.match(str(raw))
    return float(m.group(1)) if m else None
