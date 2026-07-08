"""Services renewals — тонкий слой между views и repository/engine."""
from __future__ import annotations

from apps.renewals import repository


def board(filters: dict | None = None) -> dict:
    return repository.board(filters)


def list_deals(**kwargs) -> dict:
    return repository.list_deals(**kwargs)


def get_deal(deal_id: int) -> dict | None:
    return repository.deal_computed(deal_id)


def move_deal(deal_id, to_stage_id, reason_code, author_id):
    return repository.move_deal(deal_id, to_stage_id, reason_code, author_id)


def patch_deal(deal_id, data):
    return repository.patch_deal(deal_id, data)


def add_comment(deal_id, body, author_id):
    return repository.add_comment(deal_id, body, author_id)


def list_activity(deal_id):
    return repository.list_activity(deal_id)
