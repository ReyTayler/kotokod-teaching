"""
Разбитая на 4 стадии авто-прогрессия «Урок 1..4»:
  - миграция 0003 сидит 4 отдельные is_auto-стадии вместо одной lesson_progress;
  - ensure_deal стартует новую сделку на первой (Урок 1);
  - engine.sync_lesson_stage двигает сделку по мере посещаемости;
  - ручной перевод в decision/won/lost стадию «замораживает» авто-прогресс.
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.renewals import engine, repository
from apps.renewals.models import RenewalDeal, RenewalPipeline, RenewalStage


def _make_group_with_membership(direction_id: int, teacher_id: int, student_id: int,
                                 lessons_done: float = 0) -> int:
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, active, created_at) "
            "VALUES ('__lp_test_group__', %s, %s, false, true, now()) RETURNING id",
            [direction_id, teacher_id])
        group_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s, %s, %s, true)", [group_id, student_id, lessons_done])
    return group_id


def _set_lessons_done(group_id: int, student_id: int, value: float) -> None:
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE group_memberships SET lessons_done = %s WHERE group_id = %s AND student_id = %s",
            [value, group_id, student_id])


def _cleanup_group(group_id: int, student_id: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM renewal_activity WHERE deal_id IN '
                    '(SELECT id FROM renewal_deal WHERE student_id = %s)', [student_id])
        cur.execute('DELETE FROM renewal_deal WHERE student_id = %s', [student_id])
        cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [group_id])
        cur.execute('DELETE FROM groups WHERE id = %s', [group_id])


@pytest.mark.django_db
def test_default_pipeline_has_four_lesson_stages():
    pipe = RenewalPipeline.objects.get(is_default=True)
    stages = list(RenewalStage.objects.filter(
        pipeline=pipe, kind='progress', is_auto=True).order_by('sort_order'))
    assert [s.key for s in stages] == ['lesson_1', 'lesson_2', 'lesson_3', 'lesson_4']
    assert [s.label for s in stages] == ['Урок 1', 'Урок 2', 'Урок 3', 'Урок 4']
    assert not RenewalStage.objects.filter(pipeline=pipe, key='lesson_progress').exists()


@pytest.mark.django_db
def test_ensure_deal_starts_on_lesson_1(make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    assert deal.stage.key == 'lesson_1'


@pytest.mark.django_db
def test_sync_lesson_stage_advances_with_attendance(make_student, make_direction, make_teacher):
    sid, did, tid = make_student(), make_direction(), make_teacher()
    gid = _make_group_with_membership(did, tid, sid, lessons_done=0)
    try:
        deal = engine.ensure_deal(sid, did, cycle_no=1)
        assert deal.stage.key == 'lesson_1'

        _set_lessons_done(gid, sid, 1)
        engine.sync_lesson_stage(sid, did)
        deal.refresh_from_db()
        assert deal.stage.key == 'lesson_2'

        _set_lessons_done(gid, sid, 3)
        engine.sync_lesson_stage(sid, did)
        deal.refresh_from_db()
        assert deal.stage.key == 'lesson_4'
    finally:
        _cleanup_group(gid, sid)


@pytest.mark.django_db
def test_sync_lesson_stage_does_not_override_manual_decision(make_student, make_direction, make_teacher):
    sid, did, tid = make_student(), make_direction(), make_teacher()
    gid = _make_group_with_membership(did, tid, sid, lessons_done=0)
    try:
        deal = engine.ensure_deal(sid, did, cycle_no=1)
        awaiting = RenewalStage.objects.get(pipeline=deal.pipeline, key='awaiting_payment')
        repository.move_deal(deal.id, awaiting.id, None, author_id=None)

        _set_lessons_done(gid, sid, 3)
        engine.sync_lesson_stage(sid, did)

        deal.refresh_from_db()
        assert deal.stage.key == 'awaiting_payment'
    finally:
        _cleanup_group(gid, sid)


@pytest.mark.django_db
def test_rebuild_command_self_heals_lesson_stage(make_student, make_direction, make_teacher):
    sid, did, tid = make_student(), make_direction(), make_teacher()
    gid = _make_group_with_membership(did, tid, sid, lessons_done=2)
    try:
        from django.core.management import call_command
        call_command('rebuild_renewal_deals')
        deal = RenewalDeal.objects.get(student_id=sid, direction_id=did, cycle_no=1)
        assert deal.stage.key == 'lesson_3'
    finally:
        _cleanup_group(gid, sid)
