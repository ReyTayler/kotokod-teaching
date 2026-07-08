"""Проверяем, что модели renewals объявлены и корректно связаны."""
from __future__ import annotations

from apps.renewals.models import RenewalActivity, RenewalDeal, RenewalPipeline, RenewalStage


def test_tables_named_as_expected():
    assert RenewalPipeline._meta.db_table == 'renewal_pipeline'
    assert RenewalStage._meta.db_table == 'renewal_stage'
    assert RenewalDeal._meta.db_table == 'renewal_deal'
    assert RenewalActivity._meta.db_table == 'renewal_activity'


def test_deal_has_cycle_unique_constraint():
    names = {c.name for c in RenewalDeal._meta.constraints}
    assert 'renewal_deal_cycle_uq' in names


def test_stage_kinds():
    assert set(RenewalStage.Kind.values) == {'progress', 'decision', 'won', 'lost'}
