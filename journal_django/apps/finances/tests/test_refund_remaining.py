"""Тесты student_fifo_remaining — неотработанный остаток ученика."""
from __future__ import annotations

import pytest
from decimal import Decimal
from django.db import connection

from apps.finances.repository import student_fifo_remaining

pytestmark = pytest.mark.django_db


def _add_payment(sid, did, lessons, total, graph_cleanup, kind='purchase', subs=1):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, "
            "lessons_count, kind, unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'2026-01-01','t') RETURNING id",
            [sid, did, subs, lessons, kind, 0, total])
        pid = cur.fetchone()[0]
    graph_cleanup['payments'].append(pid)
    return pid


def test_remaining_no_attendance(student_fixture, direction_fixture, graph_cleanup):
    _add_payment(student_fixture, direction_fixture, 4, 4000, graph_cleanup)
    r = student_fifo_remaining(student_fixture)
    assert r['remaining_lessons'] == 4
    assert r['remaining_value'] == Decimal('4000.00')


def test_remaining_zero_when_no_payments(student_fixture):
    r = student_fifo_remaining(student_fixture)
    assert r['remaining_lessons'] == 0
    assert r['remaining_value'] == Decimal('0.00')
