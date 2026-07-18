"""Чистая переливка старых групповых назначений в пер-ученик AbsenceResolution."""
from __future__ import annotations


def migrate_assignments_to_resolutions(connection) -> None:
    with connection.cursor() as cur:
        cur.execute("""
            INSERT INTO absence_resolutions
                (missed_lesson_id, student_id, assigned_teacher_id, scheduled_date,
                 scheduled_time, duration_minutes, status, fact_lesson_id, created_at)
            SELECT a.missed_lesson_id, p.student_id, a.teacher_id, a.scheduled_date,
                   a.scheduled_time, a.duration_minutes, a.status, a.fact_lesson_id, a.created_at
            FROM extra_lesson_assignments a
            JOIN extra_lesson_participants p ON p.assignment_id = a.id
            ON CONFLICT (missed_lesson_id, student_id) DO NOTHING
        """)
