"""Фикстуры renewals: создаём реальные строки в journal_test, чистим в teardown."""
from __future__ import annotations

import pytest
from django.db import connection


@pytest.fixture
def make_student(db):
    ids = []

    def _make(full_name='__renew_test_student__'):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO students (full_name, enrollment_status, created_at) "
                "VALUES (%s, 'enrolled', now()) RETURNING id", [full_name])
            sid = cur.fetchone()[0]
        ids.append(sid)
        return sid

    yield _make
    # renewal_activity → renewal_deal FK создан Django как DEFERRABLE INITIALLY
    # DEFERRED, из-за чего ON DELETE CASCADE откладывается и валит FK на teardown.
    # Поэтому чистим activity явно перед сделками.
    with connection.cursor() as cur:
        for sid in ids:
            cur.execute(
                'DELETE FROM renewal_activity WHERE deal_id IN '
                '(SELECT id FROM renewal_deal WHERE student_id = %s)', [sid])
            cur.execute('DELETE FROM renewal_deal WHERE student_id = %s', [sid])
            cur.execute('DELETE FROM students WHERE id = %s', [sid])


@pytest.fixture
def make_direction(db):
    ids = []

    def _make(name='__renew_test_dir__', price='4000.00'):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO directions (name, is_individual, active, subscription_price) "
                "VALUES (%s, false, true, %s) RETURNING id", [name, price])
            did = cur.fetchone()[0]
        ids.append(did)
        return did

    yield _make
    with connection.cursor() as cur:
        for did in ids:
            cur.execute(
                'DELETE FROM renewal_activity WHERE deal_id IN '
                '(SELECT id FROM renewal_deal WHERE direction_id = %s)', [did])
            cur.execute('DELETE FROM renewal_deal WHERE direction_id = %s', [did])
            cur.execute('DELETE FROM directions WHERE id = %s', [did])


@pytest.fixture
def make_teacher(db):
    """Преподаватель для групп (groups.teacher_id — NOT NULL FK)."""
    ids = []

    def _make(name='__renew_test_teacher__'):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO teachers (name, created_at) VALUES (%s, now()) RETURNING id",
                [name])
            tid = cur.fetchone()[0]
        ids.append(tid)
        return tid

    yield _make
    with connection.cursor() as cur:
        for tid in ids:
            cur.execute('DELETE FROM teachers WHERE id = %s', [tid])
