from apps.sync.backfills.dates import parse_lesson_date, parse_start_date


def test_parse_start_date_valid():
    assert parse_start_date('13.07.2026') == '2026-07-13'


def test_parse_start_date_two_digit_year():
    assert parse_start_date('13.07.26') == '2026-07-13'


def test_parse_start_date_invalid_returns_none():
    assert parse_start_date('не дата') is None
    assert parse_start_date('') is None
    assert parse_start_date(None) is None


def test_parse_start_date_rejects_trailing_junk():
    # parse_start_date заякорен с обеих сторон (^...$) — в отличие от parse_lesson_date
    assert parse_start_date('13.07.2026 доп.текст') is None


def test_parse_lesson_date_valid():
    assert parse_lesson_date('13.07.2026') == '2026-07-13'


def test_parse_lesson_date_allows_trailing_junk():
    # parse_lesson_date заякорен только слева — хвост после даты игнорируется
    assert parse_lesson_date('13.07.2026 доп.текст') == '2026-07-13'


def test_parse_lesson_date_invalid_returns_none():
    assert parse_lesson_date('не дата') is None
    assert parse_lesson_date(None) is None
