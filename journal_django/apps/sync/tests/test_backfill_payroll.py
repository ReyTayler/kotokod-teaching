# journal_django/apps/sync/tests/test_backfill_payroll.py
import pytest
from django.db import connection

from apps.sync.backfills import payroll


def _row(date='13.07.2026', group='Группа A', num='1', total='2', present='2', payment='400', token='TOK1', penalty=''):
    row = [''] * 10
    row[0] = date
    row[2] = group
    row[3] = num
    row[4] = total
    row[5] = present
    row[6] = payment
    row[8] = token
    row[9] = penalty
    return row


def test_extract_payroll_basic():
    result = payroll.extract_payroll([_row()])
    assert len(result) == 1
    assert result[0]['lesson_date'] == '2026-07-13'
    assert result[0]['payment'] == 400.0
    assert result[0]['penalty'] == 0.0


def test_extract_payroll_with_penalty():
    result = payroll.extract_payroll([_row(penalty='40')])
    assert result[0]['penalty'] == 40.0


def test_extract_payroll_skips_row_without_token():
    result = payroll.extract_payroll([_row(token='')])
    assert result == []


def test_extract_payroll_skips_non_numeric_total():
    result = payroll.extract_payroll([_row(total='n/a')])
    assert result == []


@pytest.mark.django_db
def test_run_inserts_payroll_row(monkeypatch):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_p__') RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM directions LIMIT 1")
        direction_row = cur.fetchone()
        created_direction = False
        if direction_row is None:
            cur.execute(
                "INSERT INTO directions (name) VALUES ('__test_sync_direction_p__') RETURNING id"
            )
            direction_row = cur.fetchone()
            created_direction = True
        direction_id = direction_row[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes, "
            "lessons_per_week, lesson_number_offset) "
            "VALUES ('__test_sync_group_p__', %s, %s, false, 90, 1, 0) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lessons (lesson_date, teacher_id, group_id, lesson_number, lesson_duration_minutes, "
            "lesson_type, submitted_by_token, submitted_at) "
            "VALUES ('2026-07-13', %s, %s, 1, 90, 'regular', 'TOK1', now()) RETURNING id",
            [teacher_id, group_id],
        )
        lesson_id = cur.fetchone()[0]

    rows = [_row(group='__test_sync_group_p__')]
    monkeypatch.setattr(payroll.sheets_client, 'read_journal_range', lambda *a: rows)

    try:
        result = payroll.run(dry_run=False)
        assert result['inserted'] == 1
        with connection.cursor() as cur:
            cur.execute("SELECT payment FROM payroll WHERE lesson_id = %s", [lesson_id])
            assert cur.fetchone()[0] == 400
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM payroll WHERE lesson_id = %s", [lesson_id])
            cur.execute("DELETE FROM lessons WHERE id = %s", [lesson_id])
            cur.execute("DELETE FROM groups WHERE id = %s", [group_id])
            cur.execute("DELETE FROM teachers WHERE id = %s", [teacher_id])
            if created_direction:
                cur.execute("DELETE FROM directions WHERE id = %s", [direction_id])
