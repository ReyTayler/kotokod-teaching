# journal_django/apps/sync/tests/test_rebuild_payroll.py
import pytest
from django.db import connection

from apps.sync.backfills import rebuild_payroll


@pytest.mark.django_db
def test_run_computes_payment_from_attendance():
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_rp__') RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM directions LIMIT 1")
        direction_row = cur.fetchone()
        created_direction = False
        if direction_row is None:
            cur.execute(
                "INSERT INTO directions (name, is_individual) VALUES ('__test_sync_direction_rp__', false) RETURNING id"
            )
            direction_row = cur.fetchone()
            created_direction = True
        direction_id = direction_row[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes, lessons_per_week) "
            "VALUES ('__test_sync_group_rp__', %s, %s, false, 90, 1) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name) VALUES ('__test_sync_student_rp__') RETURNING id")
        student_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lessons (lesson_date, teacher_id, group_id, lesson_number, lesson_duration_minutes, "
            "lesson_type, submitted_by_token, submitted_at) "
            "VALUES ('2026-07-13', %s, %s, 1, 90, 'regular', 'TOKRP', "
            "'2026-07-13T12:00:00+03:00'::timestamptz) RETURNING id",
            [teacher_id, group_id],
        )
        lesson_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s, %s, true)",
            [lesson_id, student_id],
        )

    try:
        result = rebuild_payroll.run(dry_run=False)
        assert result['inserted'] >= 1
        with connection.cursor() as cur:
            cur.execute("SELECT payment, penalty FROM payroll WHERE lesson_id = %s", [lesson_id])
            payment, penalty = cur.fetchone()
            assert payment == 500  # total=1, present=1 → smallGroup rate (total<=2, все пришли)
            assert penalty == 0    # submitted_at date == lesson_date
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM payroll WHERE lesson_id = %s", [lesson_id])
            cur.execute("DELETE FROM lesson_attendance WHERE lesson_id = %s", [lesson_id])
            cur.execute("DELETE FROM lessons WHERE id = %s", [lesson_id])
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])
            cur.execute("DELETE FROM groups WHERE id = %s", [group_id])
            cur.execute("DELETE FROM teachers WHERE id = %s", [teacher_id])
            if created_direction:
                cur.execute("DELETE FROM directions WHERE id = %s", [direction_id])


@pytest.mark.django_db
def test_run_dry_run_does_not_write():
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_rpd__') RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM directions LIMIT 1")
        direction_row = cur.fetchone()
        created_direction = False
        if direction_row is None:
            cur.execute(
                "INSERT INTO directions (name, is_individual) VALUES ('__test_sync_direction_rpd__', false) RETURNING id"
            )
            direction_row = cur.fetchone()
            created_direction = True
        direction_id = direction_row[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes, lessons_per_week) "
            "VALUES ('__test_sync_group_rpd__', %s, %s, false, 90, 1) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name) VALUES ('__test_sync_student_rpd__') RETURNING id")
        student_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lessons (lesson_date, teacher_id, group_id, lesson_number, lesson_duration_minutes, "
            "lesson_type, submitted_by_token, submitted_at) "
            "VALUES ('2026-07-13', %s, %s, 1, 90, 'regular', 'TOKRPD', now()) RETURNING id",
            [teacher_id, group_id],
        )
        lesson_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s, %s, true)",
            [lesson_id, student_id],
        )

    try:
        rebuild_payroll.run(dry_run=True)
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM payroll WHERE lesson_id = %s", [lesson_id])
            assert cur.fetchone() is None
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM lesson_attendance WHERE lesson_id = %s", [lesson_id])
            cur.execute("DELETE FROM lessons WHERE id = %s", [lesson_id])
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])
            cur.execute("DELETE FROM groups WHERE id = %s", [group_id])
            cur.execute("DELETE FROM teachers WHERE id = %s", [teacher_id])
            if created_direction:
                cur.execute("DELETE FROM directions WHERE id = %s", [direction_id])
