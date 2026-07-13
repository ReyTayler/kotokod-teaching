from apps.sync.backfills.rows import cell, parse_float, parse_int


def test_cell_returns_empty_for_missing_index():
    assert cell(['a', 'b'], 5) == ''


def test_cell_returns_empty_for_falsy_value():
    assert cell(['a', '', None], 1) == ''
    assert cell(['a', '', None], 2) == ''


def test_cell_strips_and_stringifies():
    assert cell(['  Иванов  '], 0) == 'Иванов'


def test_parse_int_leading_digits():
    assert parse_int('12abc') == 12
    assert parse_int('  42') == 42


def test_parse_int_none_on_no_digits():
    assert parse_int('abc') is None
    assert parse_int('') is None
    assert parse_int(None) is None


def test_parse_float_leading_number():
    assert parse_float('3.5abc') == 3.5
    assert parse_float('10') == 10.0


def test_parse_float_none_on_invalid():
    assert parse_float('abc') is None
    assert parse_float('') is None


def test_cell_preserves_numeric_zero():
    assert cell([0, 'b'], 0) == '0'


def test_parse_int_preserves_zero():
    assert parse_int(0) == 0
    assert parse_int('0') == 0


def test_parse_float_preserves_zero():
    assert parse_float(0) == 0.0


def test_parse_int_truncates_float_string():
    assert parse_int('10.9') == 10


def test_parse_int_negative():
    assert parse_int('-5') == -5


def test_parse_float_negative():
    assert parse_float('-2.5') == -2.5
