# journal_django/apps/sync/tests/test_backfill_payments.py
import pytest
from django.db import connection

from apps.sync.backfills import payments


def test_norm_name():
    assert payments.norm_name('  Пётр  Иванов ') == 'петр иванов'
    assert payments.norm_name('Алёна') == 'алена'


def test_parse_date_valid():
    assert payments.parse_date('13.07.2026') == '2026-07-13'


def test_parse_date_invalid():
    assert payments.parse_date('2026-07-13') is None
    assert payments.parse_date('') is None


def test_parse_amount_valid():
    assert payments.parse_amount('1 500,50') == 1500.5


def test_parse_amount_zero_or_negative_is_none():
    assert payments.parse_amount('0') is None
    assert payments.parse_amount('-100') is None
    assert payments.parse_amount('abc') is None


@pytest.mark.django_db
def test_run_inserts_payment_for_archived_direction(monkeypatch):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO students (full_name) VALUES ('__test_sync_pay_student__') RETURNING id")
        student_id = cur.fetchone()[0]

    rows = [['__test_sync_pay_student__', 'заметка', '5000', '13.07.2026', 'Архив']]
    monkeypatch.setattr(payments.sheets_client, 'read_journal_range', lambda *a: rows)

    try:
        result = payments.run(dry_run=False)
        assert result['inserted'] == 1
        assert result['archived'] == 1
        with connection.cursor() as cur:
            cur.execute(
                "SELECT total_amount, direction_id FROM payments WHERE student_id = %s AND created_by = 'backfill-script'",
                [student_id],
            )
            row = cur.fetchone()
            assert row is not None
            assert row[1] is None
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM payments WHERE student_id = %s", [student_id])
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])


@pytest.mark.django_db
def test_run_skips_unknown_student(monkeypatch):
    rows = [['__nonexistent_student__', '', '5000', '13.07.2026', 'Архив']]
    monkeypatch.setattr(payments.sheets_client, 'read_journal_range', lambda *a: rows)

    result = payments.run(dry_run=False)
    assert result['inserted'] == 0
    assert result['skipped'] == 1
    assert 'не найден' in result['skipped_details'][0]['reason']


@pytest.mark.django_db
def test_run_append_mode_skips_duplicates(monkeypatch):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO students (full_name) VALUES ('__test_sync_pay_dup__') RETURNING id")
        student_id = cur.fetchone()[0]

    rows = [['__test_sync_pay_dup__', '', '5000', '13.07.2026', 'Архив']]
    monkeypatch.setattr(payments.sheets_client, 'read_journal_range', lambda *a: rows)

    try:
        first = payments.run(dry_run=False)
        second = payments.run(dry_run=False)
        assert first['inserted'] == 1
        assert second['inserted'] == 0
        assert second['duplicate_skipped'] == 1
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM payments WHERE student_id = %s", [student_id])
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])
