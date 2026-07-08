"""Services renewals — тонкий слой между views и repository/engine."""
from __future__ import annotations

from apps.renewals import repository


def board(filters: dict | None = None) -> dict:
    return repository.board(filters)


def list_deals(**kwargs) -> dict:
    return repository.list_deals(**kwargs)


def get_deal(deal_id: int) -> dict | None:
    return repository.deal_computed(deal_id)
