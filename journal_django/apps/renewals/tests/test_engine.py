import pytest
from apps.renewals import engine
from apps.renewals.models import RenewalDeal, RenewalStage


@pytest.mark.django_db
def test_ensure_deal_is_idempotent(make_student, make_direction):
    sid, did = make_student(), make_direction()
    d1 = engine.ensure_deal(sid, did, cycle_no=1)
    d2 = engine.ensure_deal(sid, did, cycle_no=1)
    assert d1.id == d2.id
    assert RenewalDeal.objects.filter(student_id=sid, direction_id=did).count() == 1
    assert d1.stage.kind == 'progress'
    assert d1.outcome_at is None


@pytest.mark.django_db
def test_close_won_and_respawn(make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    engine.close_deal_won(sid, did)
    open_deals = RenewalDeal.objects.filter(student_id=sid, direction_id=did, outcome_at__isnull=True)
    closed = RenewalDeal.objects.filter(student_id=sid, direction_id=did, outcome_at__isnull=False)
    assert closed.count() == 1
    assert closed.first().stage.kind == 'won'
    assert open_deals.count() == 1
    assert open_deals.first().cycle_no == 2
