# journal_django/apps/sync/tests/test_backfill_students.py
import pytest
from django.db import connection

from apps.sync.backfills import students


def _row(name, teacher='', group='', done='', enroll=''):
    row = [''] * 20
    row[0] = name
    row[2] = '10'
    row[9] = 'PM1'
    row[11] = teacher
    row[12] = group
    row[13] = '01.09.2025'
    row[14] = '5'
    row[16] = done
    row[19] = enroll
    return row


def test_extract_students_basic():
    rows = [_row('Иванов Иван', teacher='Петрова', group='Группа A', done='3.5')]
    result = students.extract_students_and_memberships(rows)
    assert len(result['students']) == 1
    assert result['students'][0]['full_name'] == 'Иванов Иван'
    assert result['students'][0]['age'] == 10
    assert len(result['memberships']) == 1
    assert result['memberships'][0]['lessons_done'] == 3.5


def test_extract_students_skips_uchenika_net_name():
    rows = [_row('УЧЕНИКА НЕТ')]
    result = students.extract_students_and_memberships(rows)
    assert result['students'] == []


def test_extract_students_no_membership_without_teacher():
    rows = [_row('Одиночка', teacher='', group='')]
    result = students.extract_students_and_memberships(rows)
    assert len(result['students']) == 1
    assert result['memberships'] == []
    assert result['students'][0]['enrollment_status'] == 'not_enrolled'


def test_map_enrollment_yes():
    assert students.map_enrollment_from_sheets('Да', True) == {
        'enrollment_status': 'enrolled', 'frozen_from': None, 'frozen_until': None,
    }


def test_map_enrollment_frozen_with_month():
    # Лист держит только месяц окончания заморозки → инференс дат (месяц=январь).
    result = students.map_enrollment_from_sheets('нет январь', True)
    assert result['enrollment_status'] == 'frozen'
    assert result['frozen_until'] is not None
    assert result['frozen_until'].month == 1
    assert result['frozen_from'] is not None
    # Инвариант frozen_from <= frozen_until (CHECK на модели).
    assert result['frozen_from'] <= result['frozen_until']


def test_map_enrollment_declined():
    result = students.map_enrollment_from_sheets('отказ от занятий', True)
    assert result['enrollment_status'] == 'declined'


@pytest.mark.django_db
def test_run_inserts_student_and_membership(monkeypatch):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_s__') RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM directions LIMIT 1")
        direction_row = cur.fetchone()
        direction_id = direction_row[0] if direction_row is not None else None
        created_direction = False
        if direction_id is None:
            cur.execute(
                "INSERT INTO directions (name, is_individual) VALUES ('__test_sync_direction_s__', false) RETURNING id"
            )
            direction_id = cur.fetchone()[0]
            created_direction = True
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes, lessons_per_week) "
            "VALUES ('__test_sync_group_s__', %s, %s, false, 90, 1) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]

    rows = [_row('__test_sync_student__', teacher='__test_sync_teacher_s__', group='__test_sync_group_s__', done='2')]
    monkeypatch.setattr(students.sheets_client, 'read_students_range', lambda *a: rows)

    try:
        result = students.run(dry_run=False)
        assert result['students_inserted'] == 1
        assert result['memberships_inserted'] == 1
        with connection.cursor() as cur:
            cur.execute("SELECT id FROM students WHERE full_name = %s", ['__test_sync_student__'])
            assert cur.fetchone() is not None
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM group_memberships WHERE group_id = %s", [group_id])
            cur.execute("DELETE FROM students WHERE full_name = '__test_sync_student__'")
            cur.execute("DELETE FROM groups WHERE id = %s", [group_id])
            cur.execute("DELETE FROM teachers WHERE name = '__test_sync_teacher_s__'")
            if created_direction:
                cur.execute("DELETE FROM directions WHERE id = %s", [direction_id])
