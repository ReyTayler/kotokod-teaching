"""
Авто-прогрессия стадий по ОБЩЕЙ истории посещений ученика (подписочная модель):
  - 4 отдельные is_auto-стадии «Не было урока», «Урок 1..3» (миграция 0003,
    переименована миграцией 0009);
  - engine.sync_lesson_stage двигает сделку по мере посещаемости (lesson_attendance);
  - цикл отработан → «Ждём продление» (+due_at); баланс ≤ 0 → «Ждём оплату»;
  - ручной перевод в decision-стадию «замораживает» авто-прогресс.
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.renewals import engine, repository
from apps.renewals.models import RenewalDeal, RenewalPipeline, RenewalStage


def _make_group_with_membership(direction_id: int, teacher_id: int, student_id: int,
                                name: str = '__lp_test_group__') -> int:
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, active, created_at) "
            "VALUES (%s, %s, %s, false, true, now()) RETURNING id",
            [name, direction_id, teacher_id])
        group_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s, %s, 0, true)", [group_id, student_id])
    return group_id


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
    assert [s.key for s in stages] == ['no_lesson_yet', 'lesson_1', 'lesson_2', 'lesson_3']
    assert [s.label for s in stages] == ['Не было урока', 'Урок 1', 'Урок 2', 'Урок 3']
    assert not RenewalStage.objects.filter(pipeline=pipe, key='lesson_progress').exists()


@pytest.mark.django_db
def test_ensure_deal_starts_on_no_lesson_yet(make_student):
    sid = make_student()
    deal = engine.ensure_deal(sid, cycle_no=1)
    assert deal.stage.key == 'no_lesson_yet'


@pytest.mark.django_db
def test_sync_lesson_stage_advances_with_attendance(make_student, make_direction,
                                                    make_teacher, make_payment,
                                                    make_attendance):
    sid, did, tid = make_student(), make_direction(), make_teacher()
    make_payment(sid, did, lessons=8)  # баланс > 0 — иначе уедет в «Ждём оплату»
    gid = _make_group_with_membership(did, tid, sid)
    try:
        deal = engine.ensure_deal(sid, cycle_no=1)
        assert deal.stage.key == 'no_lesson_yet'

        make_attendance(sid, gid, tid, count=1)
        engine.sync_lesson_stage(sid)
        deal.refresh_from_db()
        assert deal.stage.key == 'lesson_1'

        make_attendance(sid, gid, tid, count=2, start='2026-06-10')
        engine.sync_lesson_stage(sid)
        deal.refresh_from_db()
        assert deal.stage.key == 'lesson_3'
    finally:
        _cleanup_group(gid, sid)


@pytest.mark.django_db
def test_sync_lesson_stage_does_not_override_manual_decision(make_student, make_direction,
                                                             make_teacher, make_payment,
                                                             make_attendance):
    """Ручные (не is_auto) стадии движок не трогает — «Думает» остаётся."""
    sid, did, tid = make_student(), make_direction(), make_teacher()
    make_payment(sid, did, lessons=8)
    gid = _make_group_with_membership(did, tid, sid)
    try:
        deal = engine.ensure_deal(sid, cycle_no=1)
        thinking = RenewalStage.objects.get(pipeline=deal.pipeline, key='thinking')
        repository.move_deal(deal.id, thinking.id, None, author_id=None)

        make_attendance(sid, gid, tid, count=3)
        engine.sync_lesson_stage(sid)

        deal.refresh_from_db()
        assert deal.stage.key == 'thinking'
    finally:
        _cleanup_group(gid, sid)


@pytest.mark.django_db
def test_cycle_complete_moves_to_awaiting_renewal(make_student, make_direction,
                                                  make_teacher, make_payment,
                                                  make_attendance):
    """4 суммарных урока отработаны → «Ждём продление» + зафиксирован due_at."""
    sid, did, tid = make_student(), make_direction(), make_teacher()
    make_payment(sid, did, lessons=8)
    gid = _make_group_with_membership(did, tid, sid)
    try:
        make_attendance(sid, gid, tid, count=4)
        deal = engine.ensure_deal(sid, cycle_no=1)
        engine.sync_lesson_stage(sid)
        deal.refresh_from_db()
        assert deal.stage.key == 'awaiting_renewal'
        assert deal.due_at is not None
        assert deal.stage.key != 'no_lesson_yet'  # фикс зацикливания attended % 4
    finally:
        _cleanup_group(gid, sid)


@pytest.mark.django_db
def test_balance_zero_mid_cycle_moves_to_awaiting_payment(make_student, make_direction,
                                                          make_teacher, make_attendance):
    """Цикл не отработан (2 из 4), оплат нет (баланс ≤ 0) → «Ждём оплату»."""
    sid, did, tid = make_student(), make_direction(), make_teacher()
    gid = _make_group_with_membership(did, tid, sid)
    try:
        make_attendance(sid, gid, tid, count=2)
        deal = engine.ensure_deal(sid, cycle_no=1)
        engine.sync_lesson_stage(sid)
        deal.refresh_from_db()
        assert deal.stage.key == 'awaiting_payment'
        assert deal.due_at is None
    finally:
        _cleanup_group(gid, sid)


@pytest.mark.django_db
def test_awaiting_renewal_wins_over_awaiting_payment(make_student, make_direction,
                                                     make_teacher, make_attendance):
    """Цикл отработан И баланс ≤ 0 → приоритет у «Ждём продление» (долг — бейджем)."""
    sid, did, tid = make_student(), make_direction(), make_teacher()
    gid = _make_group_with_membership(did, tid, sid)
    try:
        make_attendance(sid, gid, tid, count=4)
        deal = engine.ensure_deal(sid, cycle_no=1)
        engine.sync_lesson_stage(sid)
        deal.refresh_from_db()
        assert deal.stage.key == 'awaiting_renewal'
    finally:
        _cleanup_group(gid, sid)


@pytest.mark.django_db
def test_cross_direction_attendance_counts_into_one_history(make_student, make_direction,
                                                            make_teacher, make_payment,
                                                            make_attendance):
    """
    Подписочная модель: посещения РАЗНЫХ направлений складываются в общую
    историю ученика — 2 + 2 урока в двух группах = цикл отработан.
    """
    sid, tid = make_student(), make_teacher()
    did1, did2 = make_direction('__renew_dir_a__'), make_direction('__renew_dir_b__')
    make_payment(sid, did1, lessons=8)
    gid1 = _make_group_with_membership(did1, tid, sid, name='__lp_group_a__')
    gid2 = _make_group_with_membership(did2, tid, sid, name='__lp_group_b__')
    try:
        make_attendance(sid, gid1, tid, count=2, start='2026-06-01')
        make_attendance(sid, gid2, tid, count=2, start='2026-06-10')
        deal = engine.ensure_deal(sid, cycle_no=1)
        engine.sync_lesson_stage(sid)
        deal.refresh_from_db()
        assert deal.stage.key == 'awaiting_renewal'  # 4 суммарных урока
    finally:
        _cleanup_group(gid1, sid)
        _cleanup_group(gid2, sid)


@pytest.mark.django_db
def test_prepaid_cycle2_deal_stays_on_no_lesson_yet(make_student, make_direction,
                                                     make_teacher, make_payment,
                                                     make_attendance):
    """Сделка цикла 2 при attended=2 (ещё идёт цикл 1) стоит на «Не было урока»
    — это и есть П-7: предоплаченный цикл ещё не начался, а не «отработан 1 урок»."""
    sid, did, tid = make_student(), make_direction(), make_teacher()
    make_payment(sid, did, lessons=8)
    gid = _make_group_with_membership(did, tid, sid)
    try:
        make_attendance(sid, gid, tid, count=2)
        engine.ensure_deal(sid, cycle_no=2)
        engine.sync_lesson_stage(sid)
        deal = RenewalDeal.objects.get(student_id=sid, cycle_no=2)
        assert deal.stage.key == 'no_lesson_yet'
    finally:
        _cleanup_group(gid, sid)
