"""Валидатор переходов между стадиями по их виду (kind)."""
from __future__ import annotations


class InvalidTransition(Exception):
    """Недопустимый переход стадии."""


_TERMINAL = {'won', 'lost'}


def is_allowed(*, from_kind: str, to_kind: str) -> bool:
    if from_kind in _TERMINAL:
        return False
    if to_kind == 'progress':
        # Прогресс-стадии («Не было урока», «Урок 1–3») двигает только движок
        # по событиям посещаемости/оплаты — вручную поставить сделку на
        # конкретный урок цикла нельзя (решение пользователя 2026-07-17).
        # Уйти С прогресс-стадии вручную (в decision/won/lost) по-прежнему можно.
        return False
    return to_kind in {'decision', 'won', 'lost'}


def assert_allowed(*, from_kind: str, to_kind: str) -> None:
    if not is_allowed(from_kind=from_kind, to_kind=to_kind):
        raise InvalidTransition(f'Переход {from_kind} → {to_kind} запрещён')
