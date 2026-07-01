"""
Integration-тесты finances.repository.fifo_inputs + end-to-end compute_fifo
на реальном графе данных.

Покрытие:
  - lots/consumptions строятся по ключу student:direction;
  - guard subscriptions_count NULL/0 — партия пропускается;
  - lesson_date приходит строкой 'YYYY-MM-DD';
  - end-to-end compute_fifo на построенных входах сходится до копейки.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection

from apps.finances import repository
from apps.finances.fifo import compute_fifo

pytestmark = pytest.mark.django_db


def _add_payment(created, student_id, direction_id, subs, unit_price, total, paid_at):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, unit_price, "
            "total_amount, paid_at, created_by) VALUES (%s,%s,%s,%s,%s,%s,'test') RETURNING id",
            [student_id, direction_id, subs, unit_price, total, paid_at],
        )
        pid = cur.fetchone()[0]
    created['payments'].append(pid)
    return pid


def _add_legacy_payment(created, student_id, paid_at):
    """Легаси-оплата: direction_id=NULL, subs=NULL (валидно по CHECK). Должна быть
    исключена FIFO-запросом (WHERE direction_id IS NOT NULL)."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, unit_price, "
            "total_amount, paid_at, created_by) VALUES (%s,NULL,NULL,0,0,%s,'test') RETURNING id",
            [student_id, paid_at],
        )
        pid = cur.fetchone()[0]
    created['payments'].append(pid)
    return pid


_LESSON_SEQ = [0]


def _add_lesson_with_attendance(created, group_id, teacher_id, student_id, date, duration=60):
    # Уникальный lesson_number — таблица lessons имеет natural-key
    # (lesson_date, group_id, lesson_number, submitted_by_token).
    _LESSON_SEQ[0] += 1
    number = _LESSON_SEQ[0]
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s,%s,%s,%s,%s,'regular','test') RETURNING id",
            [group_id, teacher_id, date, number, duration],
        )
        lid = cur.fetchone()[0]
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s,%s,true)',
            [lid, student_id],
        )
    created['lessons'].append(lid)
    return lid


def test_fifo_inputs_builds_lots_and_consumptions(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    # Две партии разной цены: 1 подписка ×4=4 урока по 500; 1×4=4 по 450.
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000, 2000, '2026-05-01')
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 1800, 1800, '2026-05-15')
    # Легаси-оплата (direction=NULL) — должна быть исключена WHERE direction_id IS NOT NULL.
    _add_legacy_payment(graph_cleanup, student_fixture, '2026-05-20')
    # 3 посещения в мае, 4 в июне.
    for _ in range(3):
        _add_lesson_with_attendance(
            graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-05-10'
        )
    for _ in range(4):
        _add_lesson_with_attendance(
            graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-06-10'
        )

    inputs = repository.fifo_inputs()
    key = f'{student_fixture}:{direction_fixture}'

    assert key in inputs['keys']
    lots = inputs['lots_by_key'][key]
    # Легаси direction=NULL исключена WHERE → ровно 2 партии.
    assert len(lots) == 2
    assert lots[0]['lessons'] == 4
    assert lots[0]['price_per_lesson'] == Decimal('500')
    assert lots[1]['price_per_lesson'] == Decimal('450')
    assert inputs['purchased_by_key'][key] == 8

    cons = inputs['cons_by_key'][key]
    assert len(cons) == 7
    # lesson_date — строка, units — Decimal
    assert isinstance(cons[0]['date'], str)
    assert cons[0]['date'] == '2026-05-10'
    assert inputs['consumed_by_key'][key] == Decimal('7')

    # End-to-end: совпадает с golden из fifo.test.js (3 по 500 в мае + 1×500+3×450 в июне).
    r = compute_fifo(lots, cons, '2026-06-01', '2026-07-01')
    assert r['worked_off_total'] == Decimal('3350.00')
    assert r['worked_off_month'] == Decimal('1850.00')
    assert r['remaining_value'] == Decimal('450.00')


def test_fifo_inputs_half_lesson_units(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000, 2000, '2026-06-01')
    # 45-мин урок → units = 0.5
    _add_lesson_with_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-06-10', duration=45
    )
    inputs = repository.fifo_inputs()
    key = f'{student_fixture}:{direction_fixture}'
    assert inputs['cons_by_key'][key][0]['units'] == Decimal('0.5')
    assert inputs['consumed_by_key'][key] == Decimal('0.5')
