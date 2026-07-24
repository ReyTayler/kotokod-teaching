"""Валидатор переходов между стадиями по их виду (kind), признаку is_auto и ключу."""
from __future__ import annotations


class InvalidTransition(Exception):
    """Недопустимый переход стадии."""


_TERMINAL = {'won', 'lost'}

# «Ждём продление» — единственная авто-стадия, с которой менеджер уходит РУКАМИ
# (подтверждение/отклонение продления). Прочие авто-стадии двигает только движок.
AWAITING_RENEWAL_KEY = 'awaiting_renewal'


def is_allowed(*, from_kind: str, to_kind: str,
               from_is_auto: bool = False, to_is_auto: bool = False,
               from_key: str | None = None,
               cycle_completed: bool = True, balance: float = 1) -> bool:
    """
    Авто-стадии (is_auto) двигает движок по событиям. Руками:
    - на авто-стадию встать нельзя (to_is_auto) — прогресс, «Ждём оплату»,
      «Ждём продление», «Заморожен»;
    - с авто-стадии уйти нельзя (from_is_auto) — КРОМЕ «Ждём продление»
      (from_key == AWAITING_RENEWAL_KEY): это точка ручного решения о продлении.
    С «Ждём продление» (kind='decision') работают обычные ворота decision-стадий:
    в другую ручную decision / «Продлён» — при завершённом цикле; «Ушёл» — всегда.
    В «Продлён» — дополнительно только при положительном балансе (> 0 уроков):
    без него продление не подкреплено оплатой на следующий цикл.

    Решение пользователя 2026-07-19 (послабляет прежний тотальный from_is_auto→False
    от 2026-07-17: без выхода со стадии «Ждём продление» сделку нельзя было закрыть
    как «Продлён»).
    """
    if from_kind in _TERMINAL:
        return False
    if from_is_auto and from_key != AWAITING_RENEWAL_KEY:
        return False
    if to_is_auto:
        return False
    if to_kind == 'progress':
        return False
    if not cycle_completed:
        return to_kind == 'lost'
    if to_kind == 'won' and balance <= 0:
        return False
    return to_kind in {'decision', 'won', 'lost'}


def assert_allowed(*, from_kind: str, to_kind: str,
                   from_is_auto: bool = False, to_is_auto: bool = False,
                   from_key: str | None = None,
                   cycle_completed: bool = True, balance: float = 1) -> None:
    if not is_allowed(from_kind=from_kind, to_kind=to_kind,
                      from_is_auto=from_is_auto, to_is_auto=to_is_auto,
                      from_key=from_key, cycle_completed=cycle_completed,
                      balance=balance):
        if to_kind == 'won' and balance <= 0:
            raise InvalidTransition(
                'Нельзя отметить как «Продлён»: на балансе ученика должно быть больше 0 уроков')
        raise InvalidTransition(f'Переход {from_kind} → {to_kind} запрещён')
