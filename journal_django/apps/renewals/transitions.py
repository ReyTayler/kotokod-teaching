"""Валидатор переходов между стадиями по их виду (kind) и признаку is_auto."""
from __future__ import annotations


class InvalidTransition(Exception):
    """Недопустимый переход стадии."""


_TERMINAL = {'won', 'lost'}


def is_allowed(*, from_kind: str, to_kind: str,
               to_is_auto: bool = False, cycle_completed: bool = True) -> bool:
    """
    to_is_auto — целевая стадия управляется движком (progress-стадии,
    «Ждём оплату», «Ждём продление»), а не выставляется руками менеджера.
    cycle_completed — отработаны ли все 4 урока ТЕКУЩЕГО цикла сделки
    (apps.renewals.engine.cycle_completed), а не факт нахождения на
    конкретной стадии: «Ждём оплату» (is_auto, kind='decision') тоже
    бывает ДО завершения цикла — деньги могут кончиться раньше 4-го урока.

    Решения пользователя (2026-07-17):
    - на progress-стадию («Не было урока»/«Урок 1–3») вручную поставить
      сделку нельзя никогда — двигает только движок по событиям;
    - на другие авто-стадии («Ждём оплату», «Ждём продление») вручную
      встать можно в любой момент — это не «ручная» стадия, а лишь
      досрочное ручное выставление того, что движок и сам бы поставил;
    - пока цикл не завершён, на РУЧНУЮ decision-стадию («Думает»,
      «Заморожен», «Игнорит» и любые кастомные) и тем более в «Продлён» —
      нельзя. «Ушёл» разрешён в любой момент, независимо ни от чего.
    """
    if from_kind in _TERMINAL:
        return False
    if to_kind == 'progress':
        return False
    if to_kind == 'decision' and to_is_auto:
        return True
    if not cycle_completed:
        return to_kind == 'lost'
    return to_kind in {'decision', 'won', 'lost'}


def assert_allowed(*, from_kind: str, to_kind: str,
                   to_is_auto: bool = False, cycle_completed: bool = True) -> None:
    if not is_allowed(from_kind=from_kind, to_kind=to_kind,
                      to_is_auto=to_is_auto, cycle_completed=cycle_completed):
        raise InvalidTransition(f'Переход {from_kind} → {to_kind} запрещён')
