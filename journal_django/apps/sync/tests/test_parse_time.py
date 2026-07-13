# journal_django/apps/sync/tests/test_parse_time.py
from apps.sync.lib.parse_time import parse_lesson_duration, parse_time_slots


def test_parse_time_slots_full_day_name():
    assert parse_time_slots('Группа Понедельник 18:00') == [{'day_of_week': 1, 'start_time': '18:00:00'}]


def test_parse_time_slots_short_day_name():
    assert parse_time_slots('Группа Пн 18:00') == [{'day_of_week': 1, 'start_time': '18:00:00'}]


def test_parse_time_slots_multiple_days():
    result = parse_time_slots('Группа Пн 18:00 Ср 19:30')
    assert result == [
        {'day_of_week': 1, 'start_time': '18:00:00'},
        {'day_of_week': 3, 'start_time': '19:30:00'},
    ]


def test_parse_time_slots_dot_separator():
    assert parse_time_slots('Группа Вт 18.00') == [{'day_of_week': 2, 'start_time': '18:00:00'}]


def test_parse_time_slots_single_digit_hour_padded():
    assert parse_time_slots('Группа Сб 9:00') == [{'day_of_week': 6, 'start_time': '09:00:00'}]


def test_parse_time_slots_empty_or_no_match():
    assert parse_time_slots('') == []
    assert parse_time_slots(None) == []
    assert parse_time_slots('Группа без расписания') == []


def test_parse_lesson_duration_default_90():
    assert parse_lesson_duration('Группа Пн 18:00') == 90


def test_parse_lesson_duration_45_minutes():
    assert parse_lesson_duration('Группа Пн 18:00 45 минут') == 45
    assert parse_lesson_duration(None) == 90
