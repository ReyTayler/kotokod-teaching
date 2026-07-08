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


def _build_test_workbook(path):
    """Синтетический .xlsx, повторяющий структуру реального листа «Переходимость по курсам»:
    строка 1 — групповые заголовки «Переход N», строка 2 — заголовки колонок,
    строка 3+ — данные. Хвостовая пустая строка должна отфильтровываться."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Переходимость по курсам'

    ws.append([None, None, None, 'Переход 1', None, None, None, 'Переход 2', None, None, None])
    ws.append([
        'ФИ РЕБ', 'Сколько отзанимался', None,
        'Курс', 'прошёл ур', 'месяцев', 'Статус перехода',
        'Курс', 'прошёл ур', 'месяцев', 'Статус перехода',
    ])
    ws.append([
        'Иванов Пётр', 45, None,
        'Питон', 32, 8, 'Закончил и перешёл',
        'Роблокс', 13, 3.25, 'Продолжает учиться',
    ])
    ws.append([
        'Сидорова Анна', 20, None,
        'Скретч', 20, 5, 'Заморозка Сентябрь',
        None, None, 0, None,
    ])
    # Хвостовая «пустая» строка — как в реальном файле (шаблон без ученика).
    ws.append([None, 0, 0.0, None, None, 0, None, None, None, 0, None])

    wb.save(path)


def test_parse_sheet_reads_students_and_filters_empty_rows(tmp_path):
    from apps.groups.importers.direction_history import parse_sheet

    path = tmp_path / 'test.xlsx'
    _build_test_workbook(path)

    rows = parse_sheet(str(path))

    assert len(rows) == 2

    ivanov = rows[0]
    assert ivanov.full_name == 'Иванов Пётр'
    assert len(ivanov.transitions) == 2
    assert ivanov.transitions[0].course_raw == 'Питон'
    assert ivanov.transitions[0].lessons == 32
    assert ivanov.transitions[0].status == 'Закончил и перешёл'
    assert ivanov.transitions[1].course_raw == 'Роблокс'
    assert ivanov.transitions[1].lessons == 13
    assert ivanov.transitions[1].status == 'Продолжает учиться'

    sidorova = rows[1]
    assert sidorova.full_name == 'Сидорова Анна'
    # Второй слот пуст (course=None) -> не попадает в transitions.
    assert len(sidorova.transitions) == 1
    assert sidorova.transitions[0].course_raw == 'Скретч'
    assert sidorova.transitions[0].lessons == 20
    assert sidorova.transitions[0].status == 'Заморозка Сентябрь'


def test_parse_sheet_strips_whitespace_from_full_name(tmp_path):
    import openpyxl
    from apps.groups.importers.direction_history import parse_sheet

    path = tmp_path / 'test2.xlsx'
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Переходимость по курсам'
    ws.append([None, None, None, 'Переход 1', None, None, None])
    ws.append(['ФИ РЕБ', 'Сколько отзанимался', None, 'Курс', 'прошёл ур', 'месяцев', 'Статус перехода'])
    ws.append(['  Петров Иван  ', 10, None, 'Питон', 10, 2.5, 'Отказ'])
    wb.save(path)

    rows = parse_sheet(str(path))
    assert rows[0].full_name == 'Петров Иван'


def _row(full_name, *slots):
    """slots: list of (course_raw, lessons, status) tuples."""
    from apps.groups.importers.direction_history import StudentRow, TransitionSlot
    return StudentRow(
        full_name=full_name,
        transitions=[TransitionSlot(course_raw=c, lessons=n, status=s) for c, n, s in slots],
    )


def test_classify_and_aggregate_sums_repeated_direction():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [
        _row(
            'Столярова Анастасия',
            ('Питон', 20, 'Закончил и перешёл'),
            ('Веб-разработка', 15, 'Продолжает учиться'),
            ('Питон', 10, 'Ожидание перехода'),  # повторный заход на то же направление
        ),
    ]

    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated[('Столярова Анастасия', 'Python')] == 30
    assert ('Столярова Анастасия', 'Web-разработка') not in aggregated
    assert len(skipped) == 1
    assert skipped[0].course_raw == 'Веб-разработка'
    assert unrecognized == []
    assert unmatched == []


def test_classify_and_aggregate_skips_current_status():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [_row('Иванов Пётр', ('Питон', 32, 'Продолжает учиться'))]
    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated == {}
    assert len(skipped) == 1
    assert skipped[0].full_name == 'Иванов Пётр'
    assert skipped[0].status == 'Продолжает учиться'


def test_classify_and_aggregate_skips_frozen_status_variants():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [_row('Иванов Пётр', ('Питон', 32, 'Заморозка Сентябрь'))]
    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated == {}
    assert len(skipped) == 1


def test_classify_and_aggregate_reports_unrecognized_status():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [_row('Кокорин Владимир', ('Веб-дизайн', 12, 'Что с ним'))]
    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated == {}
    assert skipped == []
    assert len(unrecognized) == 1
    assert unrecognized[0].full_name == 'Кокорин Владимир'
    assert unrecognized[0].status == 'Что с ним'


def test_classify_and_aggregate_reports_unmatched_course_name():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [_row('Петров Иван', ('Плавание', 8, 'Закончил и перешёл'))]
    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated == {}
    assert len(unmatched) == 1
    assert unmatched[0].full_name == 'Петров Иван'
    assert unmatched[0].course_raw == 'Плавание'
