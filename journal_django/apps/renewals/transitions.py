"""Валидатор переходов между стадиями по их виду (kind) и признаку is_auto."""
from __future__ import annotations


class InvalidTransition(Exception):
    """Недопустимый переход стадии."""


_TERMINAL = {'won', 'lost'}


def is_allowed(*, from_kind: str, to_kind: str,
               from_is_auto: bool = False, to_is_auto: bool = False,
               cycle_completed: bool = True) -> bool:
    """
    Авто-стадии (is_auto) двигает ТОЛЬКО движок по событиям. Руками:
    - на авто-стадию встать нельзя (to_is_auto) — прогресс, «Ждём оплату»,
      «Ждём продление», «Заморожен»;
    - с авто-стадии уйти нельзя (from_is_auto) — даже в «Ушёл»; отказ
      оформляется сменой статуса ученика (engine.decline_deal).
    Ручные decision-стадии («Думает», «Игнорит», кастомные) двигаются как раньше:
    в другую ручную decision / «Продлён» — при завершённом цикле; «Ушёл» — всегда.

    Решение пользователя 2026-07-17 (ужесточает прежнее decision+is_auto→True).
    """
    if from_kind in _TERMINAL:
        return False
    if from_is_auto:
        return False
    if to_is_auto:
        return False
    if to_kind == 'progress':
        return False
    if not cycle_completed:
        return to_kind == 'lost'
    return to_kind in {'decision', 'won', 'lost'}


def assert_allowed(*, from_kind: str, to_kind: str,
                   from_is_auto: bool = False, to_is_auto: bool = False,
                   cycle_completed: bool = True) -> None:
    if not is_allowed(from_kind=from_kind, to_kind=to_kind,
                      from_is_auto=from_is_auto, to_is_auto=to_is_auto,
                      cycle_completed=cycle_completed):
        raise InvalidTransition(f'Переход {from_kind} → {to_kind} запрещён')
