"""Валидатор переходов между стадиями по их виду (kind)."""
from __future__ import annotations


class InvalidTransition(Exception):
    """Недопустимый переход стадии."""


_TERMINAL = {'won', 'lost'}


def is_allowed(*, from_kind: str, to_kind: str) -> bool:
    if from_kind in _TERMINAL:
        return False
    return to_kind in {'progress', 'decision', 'won', 'lost'}


def assert_allowed(*, from_kind: str, to_kind: str) -> None:
    if not is_allowed(from_kind=from_kind, to_kind=to_kind):
        raise InvalidTransition(f'Переход {from_kind} → {to_kind} запрещён')
