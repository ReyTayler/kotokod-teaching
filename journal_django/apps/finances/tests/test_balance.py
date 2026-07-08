"""
Тесты единого дома баланса (apps/finances/balance.py + repository).

Дублируют контракт типов (int/float) из payments-тестов, но через finances —
доказывают, что консолидация не изменила поведение.
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


def test_balance_is_int_when_whole(
    student_fixture, direction_fixture, graph_cleanup
):
    # 1 подписка ×4 = 4 куплено, 0 посещений → balance 4 (int).
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000)
    result = balance.get_student_balance(student_fixture)
    d = next(d for d in result['per_direction'] if d['direction_id'] == direction_fixture)
    assert d['balance'] == 4
    assert isinstance(d['balance'], int)


def test_balance_is_float_with_half_lesson(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000)
    # 45-мин урок → attended 0.5 → balance 3.5 (float)
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-06-10', duration=45
    )
    d = next(
        d for d in balance.get_student_balance(student_fixture)['per_direction']
        if d['direction_id'] == direction_fixture
    )
    assert d['balance'] == 3.5
    assert isinstance(d['balance'], float)


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


def test_balance_empty_student(student_fixture, graph_cleanup):
    result = balance.get_student_balance(student_fixture)
    assert result['per_direction'] == []
    assert result['total_balance'] == 0
    assert result['payments'] == []
