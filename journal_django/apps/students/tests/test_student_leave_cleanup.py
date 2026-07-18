"""Уход ученика (declined/not_enrolled) удаляет его pending+makeup_scheduled
резолюции пропусков, но сохраняет makeup_done (факт + деньги)."""
from __future__ import annotations

import pytest
from django.db import connection

from apps.students import services
from apps.students.tests.test_status_service import group_student  # noqa: F401 (fixture)

pytestmark = pytest.mark.django_db


def _make_lesson(group_id, teacher_id, date, number, token):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_at, submitted_by_token) "
            "VALUES (%s, %s, %s, %s, 90, 'regular', now(), %s) RETURNING id",
            [group_id, teacher_id, date, number, token])
        return cur.fetchone()[0]


def _statuses(student_id):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT status FROM absence_resolutions WHERE student_id=%s ORDER BY status",
            [student_id])
        return [r[0] for r in cur.fetchall()]


def test_leaving_deletes_open_keeps_done(group_student):
    sid = group_student['student']
    gid = group_student['group']
    tid = group_student['teacher']
    lessons = []
    with connection.cursor() as cur:
        for i, st in enumerate(('pending', 'makeup_scheduled', 'makeup_done'), start=1):
            lid = _make_lesson(gid, tid, f'2026-05-{i:02d}', i, f'__leave_tok_{i}__')
            lessons.append(lid)
            fact = 'NULL' if st != 'makeup_done' else str(lid)
            cur.execute(
                "INSERT INTO absence_resolutions (missed_lesson_id, student_id, status, "
                f"fact_lesson_id, created_at) VALUES (%s, %s, %s, {fact}, now())",
                [lid, sid, st])
    try:
        assert _statuses(sid) == ['makeup_done', 'makeup_scheduled', 'pending']

        services.change_student_status(sid, 'declined', actor=None)

        # pending + makeup_scheduled удалены; makeup_done сохранён.
        assert _statuses(sid) == ['makeup_done']
    finally:
        with connection.cursor() as cur:
            # ON DELETE CASCADE (missed_lesson) снесёт резолюции при удалении уроков.
            cur.execute('DELETE FROM lessons WHERE id = ANY(%s)', [lessons])
