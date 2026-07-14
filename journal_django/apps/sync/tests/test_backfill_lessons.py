# journal_django/apps/sync/tests/test_backfill_lessons.py
import pytest
from django.db import connection

from apps.sync.backfills import lessons


def _row(date='13.07.2026', teacher='Петрова', group='Группа A', num='1', student='Иванов',
         status='Был', token='TOK1', record='', type_label='', original=''):
    return [date, teacher, group, num, student, status, '', token, record, type_label, original]


def test_extract_lessons_basic():
    rows = [_row()]
    result = lessons.extract_lessons(rows)
    assert len(result['lessons']) == 1
    assert result['lessons'][0]['lesson_date'] == '2026-07-13'
    assert len(result['attendance']) == 1
    assert result['attendance'][0]['present'] is True


def test_extract_lessons_absent_status():
    rows = [_row(status='Не был')]
    result = lessons.extract_lessons(rows)
    assert result['attendance'][0]['present'] is False


def test_extract_lessons_skips_row_without_token():
    rows = [_row(token='')]
    result = lessons.extract_lessons(rows)
    assert result['lessons'] == []


def test_extract_lessons_dedupes_by_key_multiple_students():
    rows = [_row(student='Иванов'), _row(student='Сидоров')]
    result = lessons.extract_lessons(rows)
    assert len(result['lessons']) == 1
    assert len(result['attendance']) == 2


def test_extract_lessons_type_label():
    rows = [_row(type_label='Замена')]
    result = lessons.extract_lessons(rows)
    assert result['lessons'][0]['lesson_type'] == 'substitution'


@pytest.mark.django_db
def test_run_inserts_lesson_and_attendance(monkeypatch):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_l__') RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM directions LIMIT 1")
        direction_row = cur.fetchone()
        created_direction = False
        if direction_row is None:
            cur.execute(
                "INSERT INTO directions (name, is_individual) VALUES ('__test_sync_direction_l__', false) RETURNING id"
            )
            direction_row = cur.fetchone()
            created_direction = True
        direction_id = direction_row[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes, lessons_per_week) "
            "VALUES ('__test_sync_group_l__', %s, %s, false, 90, 1) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name) VALUES ('__test_sync_student_l__') RETURNING id")
        student_id = cur.fetchone()[0]

    rows = [_row(teacher='__test_sync_teacher_l__', group='__test_sync_group_l__', student='__test_sync_student_l__')]
    monkeypatch.setattr(lessons.sheets_client, 'read_journal_range', lambda sheet, rng: rows if sheet == 'Журнал группы' else [])

    try:
        result = lessons.run(dry_run=False)
        assert result['lessons_inserted'] == 1
        assert result['attendance_inserted'] == 1
    finally:
        with connection.cursor() as cur:
            cur.execute(
                "DELETE FROM lesson_attendance WHERE student_id = %s", [student_id])
            cur.execute("DELETE FROM lessons WHERE group_id = %s", [group_id])
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])
            cur.execute("DELETE FROM groups WHERE id = %s", [group_id])
            cur.execute("DELETE FROM teachers WHERE id = %s", [teacher_id])
            if created_direction:
                cur.execute("DELETE FROM directions WHERE id = %s", [direction_id])
