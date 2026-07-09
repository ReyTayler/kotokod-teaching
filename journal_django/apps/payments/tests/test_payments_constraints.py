"""
Тесты CHECK-constraints таблицы payments после снятия payments_direction_count_match
(2026-07-09): subscriptions_count теперь можно задать НЕЗАВИСИМО от direction_id —
легаси-оплаты (direction_id NULL) тоже должны считаться в глобальном балансе.
"""
from __future__ import annotations

import pytest
from django.db import IntegrityError, connection, transaction

from apps.payments.models import Payment


def _make_student():
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status) "
            "VALUES ('__constraint_test_student__', 'enrolled') RETURNING id",
        )
        return cur.fetchone()[0]


@pytest.mark.django_db
class TestPaymentsDirectionCountConstraint:

    def test_subscriptions_count_without_direction_is_allowed(self):
        """Ключевой тест фикса: direction=NULL + subscriptions_count заданный — разрешено."""
        sid = _make_student()
        try:
            p = Payment.objects.create(
                student_id=sid, direction_id=None, subscriptions_count=2,
                unit_price='100.00', total_amount='200.00',
                paid_at='2026-01-01', created_at='2026-01-01T00:00:00Z',
            )
            assert p.id is not None
            assert p.direction_id is None
            assert p.subscriptions_count == 2
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM payments WHERE student_id = %s', [sid])
                cur.execute('DELETE FROM students WHERE id = %s', [sid])

    def test_subscriptions_count_zero_still_rejected(self):
        """payments_subscriptions_count_check по-прежнему работает (constraint не трогали)."""
        sid = _make_student()
        try:
            with pytest.raises(IntegrityError), transaction.atomic():
                Payment.objects.create(
                    student_id=sid, direction_id=None, subscriptions_count=0,
                    unit_price='100.00', total_amount='0.00',
                    paid_at='2026-01-01', created_at='2026-01-01T00:00:00Z',
                )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM students WHERE id = %s', [sid])

    def test_total_amount_mismatch_still_rejected(self):
        """payments_total_match по-прежнему работает (constraint не трогали)."""
        sid = _make_student()
        try:
            with pytest.raises(IntegrityError), transaction.atomic():
                Payment.objects.create(
                    student_id=sid, direction_id=None, subscriptions_count=2,
                    unit_price='100.00', total_amount='999.00',  # должно быть 200.00
                    paid_at='2026-01-01', created_at='2026-01-01T00:00:00Z',
                )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM students WHERE id = %s', [sid])
