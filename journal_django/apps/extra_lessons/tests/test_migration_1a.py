"""Переливка групповых назначений в пер-ученик резолюции (1:1, общий fact_lesson через FK)."""
from __future__ import annotations
import pytest
from django.db import connection
from apps.extra_lessons._migration_helpers import migrate_assignments_to_resolutions

pytestmark = pytest.mark.django_db


def test_group_assignment_becomes_per_student(teacher_fixture, missed_lesson_fixture, student_fixture):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO students (full_name, enrollment_status) VALUES ('__mig_s2__','enrolled') RETURNING id")
        sid2 = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO extra_lesson_assignments (teacher_id, missed_lesson_id, scheduled_date, "
            "scheduled_time, duration_minutes, status, fact_lesson_id, created_at) "
            "VALUES (%s,%s,'2026-04-05','15:00',45,'done',%s, now()) RETURNING id",
            [teacher_fixture, missed_lesson_fixture, missed_lesson_fixture])
        aid = cur.fetchone()[0]
        for sid in (student_fixture, sid2):
            cur.execute("INSERT INTO extra_lesson_participants (assignment_id, student_id) VALUES (%s,%s)", [aid, sid])
    try:
        migrate_assignments_to_resolutions(connection)
        with connection.cursor() as cur:
            cur.execute("SELECT student_id, status, fact_lesson_id, assigned_teacher_id "
                        "FROM absence_resolutions WHERE missed_lesson_id = %s ORDER BY student_id", [missed_lesson_fixture])
            rows = cur.fetchall()
        assert {r[0] for r in rows} == {student_fixture, sid2}
        assert all(r[1] == 'done' and r[2] == missed_lesson_fixture and r[3] == teacher_fixture for r in rows)
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id = %s', [missed_lesson_fixture])
            cur.execute('DELETE FROM extra_lesson_participants WHERE assignment_id = %s', [aid])
            cur.execute('DELETE FROM extra_lesson_assignments WHERE id = %s', [aid])
            cur.execute('DELETE FROM students WHERE id = %s', [sid2])
