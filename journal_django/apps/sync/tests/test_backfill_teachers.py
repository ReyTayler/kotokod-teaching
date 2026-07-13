# journal_django/apps/sync/tests/test_backfill_teachers.py
import pytest
from django.db import connection

from apps.sync.backfills import teachers


def test_extract_teachers_from_student_rows():
    student_rows = [
        ['Иванов', '', '', '', '', '', '', '', '', '', '', 'Петрова', 'Группа A'],
        ['Сидоров', '', '', '', '', '', '', '', '', '', '', 'Петрова', 'Группа A'],
        ['Козлов', '', '', '', '', '', '', '', '', '', '', 'Смирнова', 'Группа B'],
    ]
    result = teachers.extract_teachers(student_rows, [])
    assert set(result) == {'Петрова', 'Смирнова'}


def test_extract_teachers_skips_uchenika_net():
    student_rows = [
        ['Х', '', '', '', '', '', '', '', '', '', '', 'УЧЕНИКА НЕТ', 'Группа A'],
    ]
    assert teachers.extract_teachers(student_rows, []) == []


def test_extract_teachers_includes_token_sheet():
    token_rows = [
        ['header'] * 6,
        ['', '', '', '', 'TOKEN1', 'Кузнецова'],
    ]
    result = teachers.extract_teachers([], token_rows)
    assert result == ['Кузнецова']


@pytest.mark.django_db
def test_run_inserts_new_teachers(monkeypatch):
    monkeypatch.setattr(
        teachers.sheets_client, 'read_students_range',
        lambda *a: [['S', '', '', '', '', '', '', '', '', '', '', '__test_sync_teacher__', 'Группа X']],
    )
    monkeypatch.setattr(teachers.sheets_client, 'read_journal_range', lambda *a: [['h'] * 6])

    try:
        result = teachers.run(dry_run=False)
        assert result['read'] == 1
        assert result['inserted'] == 1
        with connection.cursor() as cur:
            cur.execute("SELECT id FROM teachers WHERE name = %s", ['__test_sync_teacher__'])
            assert cur.fetchone() is not None
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM teachers WHERE name = %s", ['__test_sync_teacher__'])


@pytest.mark.django_db
def test_run_dry_run_does_not_write(monkeypatch):
    monkeypatch.setattr(
        teachers.sheets_client, 'read_students_range',
        lambda *a: [['S', '', '', '', '', '', '', '', '', '', '', '__test_sync_teacher_dry__', 'Группа X']],
    )
    monkeypatch.setattr(teachers.sheets_client, 'read_journal_range', lambda *a: [['h'] * 6])

    result = teachers.run(dry_run=True)
    assert result['read'] == 1
    assert result['dry_run'] is True

    with connection.cursor() as cur:
        cur.execute("SELECT id FROM teachers WHERE name = %s", ['__test_sync_teacher_dry__'])
        assert cur.fetchone() is None
