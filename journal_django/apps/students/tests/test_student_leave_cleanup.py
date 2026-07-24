"""Уход ученика (declined) удаляет его pending-резолюции пропусков в
снимаемых группах, сохраняет makeup_done (факт + деньги), а при наличии
makeup_scheduled («Назначен») — блокирует смену статуса (MembershipHasScheduledMakeups),
пока назначенный доп.урок не разобран."""
from __future__ import annotations

import pytest
from django.db import connection

from apps.extra_lessons.exceptions import MembershipHasScheduledMakeups
from apps.memberships.models import GroupMembership
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


def test_leaving_deletes_pending_keeps_done(group_student):
    """Уход без назначенных доп.уроков: pending удалён, makeup_done сохранён."""
    sid = group_student['student']
    gid = group_student['group']
    tid = group_student['teacher']
    lessons = []
    with connection.cursor() as cur:
        for i, st in enumerate(('pending', 'makeup_done'), start=1):
            lid = _make_lesson(gid, tid, f'2026-05-{i:02d}', i, f'__leave_tok_{i}__')
            lessons.append(lid)
            fact = 'NULL' if st != 'makeup_done' else str(lid)
            cur.execute(
                "INSERT INTO absence_resolutions (missed_lesson_id, student_id, status, "
                f"fact_lesson_id, created_at) VALUES (%s, %s, %s, {fact}, now())",
                [lid, sid, st])
    try:
        assert _statuses(sid) == ['makeup_done', 'pending']

        services.change_student_status(sid, 'declined', actor=None)

        # pending удалён; makeup_done сохранён.
        assert _statuses(sid) == ['makeup_done']
    finally:
        with connection.cursor() as cur:
            # ON DELETE CASCADE (missed_lesson) снесёт резолюции при удалении уроков.
            cur.execute('DELETE FROM lessons WHERE id = ANY(%s)', [lessons])


def test_leaving_blocked_by_scheduled_makeup(group_student):
    """Назначенный доп.урок в снимаемой группе блокирует уход: смена статуса
    откатывается целиком (членство остаётся активным, резолюции не тронуты)."""
    sid = group_student['student']
    gid = group_student['group']
    tid = group_student['teacher']
    mid = group_student['membership']
    lessons = []
    with connection.cursor() as cur:
        for i, st in enumerate(('pending', 'makeup_scheduled', 'makeup_done'), start=1):
            lid = _make_lesson(gid, tid, f'2026-05-{i:02d}', i, f'__leave_blk_tok_{i}__')
            lessons.append(lid)
            fact = 'NULL' if st != 'makeup_done' else str(lid)
            cur.execute(
                "INSERT INTO absence_resolutions (missed_lesson_id, student_id, status, "
                f"fact_lesson_id, created_at) VALUES (%s, %s, %s, {fact}, now())",
                [lid, sid, st])
    try:
        with pytest.raises(MembershipHasScheduledMakeups):
            services.change_student_status(sid, 'declined', actor=None)

        # Полный откат: резолюции не тронуты, членство активно.
        assert _statuses(sid) == ['makeup_done', 'makeup_scheduled', 'pending']
        assert GroupMembership.objects.get(id=mid).active is True
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM lessons WHERE id = ANY(%s)', [lessons])
