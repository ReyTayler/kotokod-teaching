"""Движковые переходы сделки при заморозке/отказе/выходе — в обход валидатора
(как reopen_deal). freeze_deal → 'frozen'; decline_deal → терминальный 'lost';
resume_from_freeze → расчётная авто-стадия по attended/balance."""
import pytest

from apps.renewals import engine
from apps.renewals.models import RenewalDeal, RenewalStage


def _stage_key(deal_id):
    return RenewalDeal.objects.get(id=deal_id).stage.key


@pytest.mark.django_db
def test_freeze_deal_moves_open_deal_to_frozen(make_student, make_direction):
    sid = make_student()
    deal = engine.ensure_deal(sid, cycle_no=1)
    engine.freeze_deal(sid)
    assert _stage_key(deal.id) == 'frozen'
    assert RenewalDeal.objects.get(id=deal.id).outcome_at is None


@pytest.mark.django_db
def test_freeze_deal_noop_without_open_deal(make_student):
    sid = make_student()
    engine.freeze_deal(sid)  # не падает без сделки


@pytest.mark.django_db
def test_decline_deal_closes_as_lost(make_student, make_direction):
    sid = make_student()
    deal = engine.ensure_deal(sid, cycle_no=1)
    engine.decline_deal(sid)
    row = RenewalDeal.objects.get(id=deal.id)
    assert row.stage.kind == 'lost'
    assert row.outcome_at is not None


@pytest.mark.django_db
def test_resume_from_freeze_returns_to_auto_stage(make_student, make_direction):
    sid = make_student()
    deal = engine.ensure_deal(sid, cycle_no=1)
    engine.freeze_deal(sid)
    assert _stage_key(deal.id) == 'frozen'
    engine.resume_from_freeze(sid)
    # attended=0, balance<=0 → 'no_lesson_yet' (первая прогресс-стадия) либо
    # 'awaiting_payment' если баланс<=0. Главное — ушли с 'frozen'.
    assert _stage_key(deal.id) != 'frozen'


@pytest.mark.django_db
def test_resume_noop_if_not_frozen(make_student, make_direction):
    sid = make_student()
    deal = engine.ensure_deal(sid, cycle_no=1)
    before = _stage_key(deal.id)
    engine.resume_from_freeze(sid)  # сделка не на 'frozen' → no-op
    assert _stage_key(deal.id) == before


@pytest.mark.django_db
def test_sync_lesson_stage_does_not_wake_frozen_deal(make_student, make_direction):
    """Regression: frozen стал is_auto=True (Task 5) для блокировки ручных
    переходов, но это не должно означать, что обычный sync_lesson_stage
    (срабатывает на каждую запись урока/оплаты) может сам разморозить
    сделку — выйти из frozen может только явный resume_from_freeze."""
    sid = make_student()
    deal = engine.ensure_deal(sid, cycle_no=1)
    engine.freeze_deal(sid)
    assert _stage_key(deal.id) == 'frozen'
    engine.sync_lesson_stage(sid)
    assert _stage_key(deal.id) == 'frozen'
