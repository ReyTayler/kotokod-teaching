"""
Тесты единого дома баланса (apps/finances/balance.py + repository).

С 2026-07-08 баланс общий пул на ученика (не per-direction) —
apps/finances/repository.py::balance_for_student. paid_by_direction /
attended_by_direction — информационные разбивки, НЕ баланс.
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.finances import balance, repository

pytestmark = pytest.mark.django_db


def _add_payment(created, student_id, direction_id, subs, total, paid_at='2026-06-01'):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, unit_price, "
            "total_amount, paid_at, created_by) VALUES (%s,%s,%s,%s,%s,%s,'test') RETURNING id",
            [student_id, direction_id, subs, total, total, paid_at],
        )
        pid = cur.fetchone()[0]
    created['payments'].append(pid)
    return pid


def _add_lesson_attendance(created, group_id, teacher_id, student_id, date, duration=60):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s,%s,%s,1,%s,'regular','test') RETURNING id",
            [group_id, teacher_id, date, duration],
        )
        lid = cur.fetchone()[0]
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s,%s,true)',
            [lid, student_id],
        )
    created['lessons'].append(lid)
    return lid


def test_total_balance_is_int_when_whole(student_fixture, direction_fixture, graph_cleanup):
    # 1 подписка ×4 = 4 куплено, 0 посещений → total_balance 4 (int).
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000)
    result = balance.get_student_balance(student_fixture)
    assert result['total_balance'] == 4
    assert isinstance(result['total_balance'], int)


def test_total_balance_is_float_with_half_lesson(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000)
    # 45-мин урок → attended 0.5 → total_balance 3.5 (float)
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-06-10', duration=45
    )
    result = balance.get_student_balance(student_fixture)
    assert result['total_balance'] == 3.5
    assert isinstance(result['total_balance'], float)


def test_balance_for_student_matches(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000)
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-06-10', duration=60
    )
    bal = repository.balance_for_student(student_fixture)
    assert bal == 3
    assert isinstance(bal, int)


def test_balance_pools_across_directions(
    teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    """
    Ключевой сценарий редизайна: оплата за направление A, но урок отработан в
    ДРУГОМ направлении B — списывается из общего пула, а не остаётся зависшей.
    """
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO directions (name, sheet_name, is_individual, active) "
            "VALUES ('__fin_dir_b__', '__fin_sheet_b__', false, true) RETURNING id"
        )
        direction_b = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active) "
            "VALUES ('__fin_group_b__', %s, %s, false, 60, true) RETURNING id",
            [direction_b, teacher_id_fixture],
        )
        group_b = cur.fetchone()[0]
    try:
        # Оплата на направление A (direction_fixture) — 4 урока.
        _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000)
        # Урок отработан на направлении B (group_b).
        lid = _add_lesson_attendance(
            graph_cleanup, group_b, teacher_id_fixture, student_fixture, '2026-06-10', duration=60
        )
        result = balance.get_student_balance(student_fixture)
        # 4 куплено на A, 1 отработан на B → общий баланс 3 (списался из общего пула).
        assert result['total_balance'] == 3
        paid_a = next(d for d in result['paid_by_direction'] if d['direction_id'] == direction_fixture)
        assert paid_a['total_paid_amount'] == 2000
        attended_b = next(d for d in result['attended_by_direction'] if d['direction_id'] == direction_b)
        assert attended_b['attended_lessons'] == 1
    finally:
        # ВАЖНО: удалить lesson_attendance/lessons для group_b ДО удаления group/direction
        # (graph_cleanup teardown идёт позже; FK lessons→groups иначе падает).
        with connection.cursor() as cur:
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lid])
            cur.execute('DELETE FROM lessons WHERE id = %s', [lid])
            if lid in graph_cleanup['lessons']:
                graph_cleanup['lessons'].remove(lid)
            cur.execute('DELETE FROM groups WHERE id = %s', [group_b])
            cur.execute('DELETE FROM directions WHERE id = %s', [direction_b])


def test_balance_empty_student(student_fixture, graph_cleanup):
    result = balance.get_student_balance(student_fixture)
    assert result['paid_by_direction'] == []
    assert result['attended_by_direction'] == []
    assert result['total_balance'] == 0
    assert result['payments'] == []
