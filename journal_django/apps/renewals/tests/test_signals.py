import pytest
from django.db.models.functions import Now

from apps.payments.models import Payment
from apps.renewals import engine
from apps.renewals.models import RenewalDeal


@pytest.mark.django_db
def test_payment_orm_create_closes_deal(make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    # created_at не имеет model-default (как в проде create_payment) → задаём явно.
    pay = Payment.objects.create(
        student_id=sid, direction_id=did, subscriptions_count=1,
        unit_price=4000, total_amount=4000, paid_at='2026-07-08', created_at=Now())
    try:
        assert RenewalDeal.objects.filter(
            student_id=sid, direction_id=did, outcome_at__isnull=False).count() == 1
        assert RenewalDeal.objects.filter(
            student_id=sid, direction_id=did, cycle_no=2, outcome_at__isnull=True).exists()
    finally:
        RenewalDeal.objects.filter(student_id=sid).delete()
        pay.delete()
