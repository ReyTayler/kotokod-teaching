# journal_django/apps/sync/tests/test_rebuild_absence_resolutions.py
import pytest
from django.db import connection

from apps.sync.backfills import rebuild_absence_resolutions


def _setup():
    """Активная группа + активный член (enrolled) + обычный урок, где ученик
    present=false и БЕЗ резолюции. Возвращает ids для ассертов/очистки."""
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__ar_t__') RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM directions LIMIT 1")
        row = cur.fetchone()
        created_dir = False
        if row is None:
            cur.execute("INSERT INTO directions (name) VALUES ('__ar_d__') RETURNING id")
            row = cur.fetchone(); created_dir = True
        direction_id = row[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, active, lesson_number_offset) "
            "VALUES ('__ar_g__', %s, %s, false, 60, 1, true, 0) RETURNING id",
            [direction_id, teacher_id])
        group_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status) "
            "VALUES ('__ar_s__', 'enrolled') RETURNING id")
        student_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s, %s, 0, true) RETURNING id", [group_id, student_id])
        membership_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lessons (lesson_date, teacher_id, group_id, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token, submitted_at) "
            "VALUES ('2026-05-01', %s, %s, 1, 60, 'regular', 'AR_TOK', now()) RETURNING id",
            [teacher_id, group_id])
        lesson_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s, %s, false)",
            [lesson_id, student_id])
    return dict(teacher_id=teacher_id, direction_id=direction_id, created_dir=created_dir,
                group_id=group_id, student_id=student_id, membership_id=membership_id,
                lesson_id=lesson_id)


def _teardown(ctx):
    with connection.cursor() as cur:
        cur.execute("DELETE FROM absence_resolutions WHERE missed_lesson_id = %s", [ctx['lesson_id']])
        cur.execute("DELETE FROM lesson_attendance WHERE lesson_id = %s", [ctx['lesson_id']])
        cur.execute("DELETE FROM lessons WHERE id = %s", [ctx['lesson_id']])
        cur.execute("DELETE FROM group_memberships WHERE id = %s", [ctx['membership_id']])
        cur.execute("DELETE FROM students WHERE id = %s", [ctx['student_id']])
        cur.execute("DELETE FROM groups WHERE id = %s", [ctx['group_id']])
        cur.execute("DELETE FROM teachers WHERE id = %s", [ctx['teacher_id']])
        if ctx['created_dir']:
            cur.execute("DELETE FROM directions WHERE id = %s", [ctx['direction_id']])


def _resolution(lesson_id, student_id):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT status FROM absence_resolutions WHERE missed_lesson_id=%s AND student_id=%s",
            [lesson_id, student_id])
        row = cur.fetchone()
    return row[0] if row else None


@pytest.mark.django_db
def test_creates_pending_for_active_member_miss():
    ctx = _setup()
    try:
        res = rebuild_absence_resolutions.run(dry_run=False)
        assert res['created'] >= 1
        assert _resolution(ctx['lesson_id'], ctx['student_id']) == 'pending'
        # Идемпотентность: повторный прогон — этот пропуск уже не кандидат.
        res2 = rebuild_absence_resolutions.run(dry_run=False)
        assert res2['created'] == 0
        with connection.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM absence_resolutions WHERE missed_lesson_id=%s AND student_id=%s",
                [ctx['lesson_id'], ctx['student_id']])
            assert cur.fetchone()[0] == 1
    finally:
        _teardown(ctx)


@pytest.mark.django_db
def test_dry_run_counts_without_writing():
    ctx = _setup()
    try:
        res = rebuild_absence_resolutions.run(dry_run=True)
        assert res['candidates'] >= 1
        assert res['created'] == 0
        assert _resolution(ctx['lesson_id'], ctx['student_id']) is None  # ничего не записано
    finally:
        _teardown(ctx)


@pytest.mark.django_db
def test_skips_left_student_and_inactive_membership():
    ctx = _setup()
    try:
        # Ученик ушёл → в кандидаты не попадает (очередь ушедших не поднимаем).
        with connection.cursor() as cur:
            cur.execute("UPDATE students SET enrollment_status='declined' WHERE id=%s", [ctx['student_id']])
        res = rebuild_absence_resolutions.run(dry_run=False)
        assert _resolution(ctx['lesson_id'], ctx['student_id']) is None
        # Вернём enrolled, но членство неактивно → тоже пропуск.
        with connection.cursor() as cur:
            cur.execute("UPDATE students SET enrollment_status='enrolled' WHERE id=%s", [ctx['student_id']])
            cur.execute("UPDATE group_memberships SET active=false WHERE id=%s", [ctx['membership_id']])
        rebuild_absence_resolutions.run(dry_run=False)
        assert _resolution(ctx['lesson_id'], ctx['student_id']) is None
        assert res['created'] == 0
    finally:
        _teardown(ctx)


@pytest.mark.django_db
def test_skips_unpaid_skip_miss():
    """Неоплачиваемый пропуск (present=false + unpaid_skip=true) — прощённый исход,
    доп.урока НЕ требует: бэкфилл его не берёт (как и record_lesson)."""
    ctx = _setup()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE lesson_attendance SET unpaid_skip=true "
                "WHERE lesson_id=%s AND student_id=%s", [ctx['lesson_id'], ctx['student_id']])
        res = rebuild_absence_resolutions.run(dry_run=False)
        assert res['created'] == 0
        assert _resolution(ctx['lesson_id'], ctx['student_id']) is None
    finally:
        _teardown(ctx)


@pytest.mark.django_db
def test_skips_when_resolution_already_exists():
    ctx = _setup()
    try:
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO absence_resolutions (missed_lesson_id, student_id, status, created_at) "
                "VALUES (%s, %s, 'burned', now())", [ctx['lesson_id'], ctx['student_id']])
        res = rebuild_absence_resolutions.run(dry_run=False)
        assert res['created'] == 0
        # Существующая burned-резолюция не перезаписана в pending.
        assert _resolution(ctx['lesson_id'], ctx['student_id']) == 'burned'
    finally:
        _teardown(ctx)
