"""
Тесты импортёра истории направлений (apps/groups/importers/direction_history.py).

normalize_course_name / classify_and_aggregate — чистые функции, без БД.
parse_sheet — читает синтетический .xlsx (без сети/реального файла школы).
import_to_db — интеграционные тесты, реальная БД (managed=False, journal_test).
"""
from __future__ import annotations

import pytest

from apps.groups.importers.direction_history import normalize_course_name


@pytest.mark.parametrize('raw,expected', [
    ('Питон', 'Python'),
    ('Питон 52 урока', 'Python'),
    ('Питон Старый (16 ур)', 'Python'),
    ('Питон Старый (32 урока)', 'Python'),
    ('Python', 'Python'),
    ('Python ИНДИВ', 'Python'),
    ('Роблокс', 'Roblox Группа'),
    ('Роблокс Старый (16 ур)', 'Roblox Группа'),
    ('Роблокс Особые Условия', 'Roblox Группа'),
    ('Roblox ИНДИВ', 'Roblox Группа'),
    ('Скретч', 'Scratch'),
    ('Скретч Старый (16 ур)', 'Scratch'),
    ('Майнкрафт', 'Minecraft'),
    ('Блендер', 'Blender'),
    ('Веб-дизайн', 'Веб-дизайн'),
    ('Веб-дизайн ИНДИВ', 'Веб-дизайн'),
    ('Веб-дизайн Особые Условия', 'Веб-дизайн'),
    ('Веб-разработка', 'Web-разработка'),
])
def test_normalize_course_name_maps_to_canonical_direction(raw, expected):
    assert normalize_course_name(raw) == expected


def test_normalize_course_name_unrecognized_returns_none():
    assert normalize_course_name('Плавание') is None
    assert normalize_course_name('') is None
    assert normalize_course_name(None) is None
