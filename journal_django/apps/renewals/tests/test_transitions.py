import pytest
from apps.renewals import transitions
from apps.renewals.transitions import InvalidTransition


def test_terminal_stages_are_frozen():
    assert transitions.is_allowed(from_kind='won', to_kind='decision') is False
    assert transitions.is_allowed(from_kind='lost', to_kind='progress') is False


def test_assert_raises():
    with pytest.raises(InvalidTransition):
        transitions.assert_allowed(from_kind='won', to_kind='decision')


def test_cannot_manually_move_onto_progress_stage():
    """Прогресс-стадии («Не было урока»/«Урок N») двигает только движок —
    вручную выставить сделку на конкретный урок цикла нельзя ни с decision,
    ни с другой progress-стадии, независимо от cycle_completed."""
    assert transitions.is_allowed(from_kind='decision', to_kind='progress', cycle_completed=True) is False
    assert transitions.is_allowed(from_kind='decision', to_kind='progress', cycle_completed=False) is False
    assert transitions.is_allowed(from_kind='progress', to_kind='progress', cycle_completed=False) is False
    with pytest.raises(InvalidTransition):
        transitions.assert_allowed(from_kind='decision', to_kind='progress')


def test_auto_decision_stage_reachable_anytime():
    """«Ждём оплату»/«Ждём продление» (kind='decision', is_auto=True) —
    не «ручная» стадия: вручную встать на неё можно в любой момент, даже
    если цикл ещё не завершён (например, «Ждём оплату» до 4-го урока)."""
    assert transitions.is_allowed(
        from_kind='progress', to_kind='decision', to_is_auto=True, cycle_completed=False) is True
    assert transitions.is_allowed(
        from_kind='decision', to_kind='decision', to_is_auto=True, cycle_completed=False) is True


def test_cycle_not_completed_blocks_manual_decision_and_won():
    """Пока цикл не завершён — на РУЧНУЮ decision-стадию («Думает» и т.п.,
    is_auto=False) и в «Продлён» нельзя, независимо от того, откуда уходим
    (progress-стадия или «Ждём оплату» с ещё не отработанными 4 уроками).
    «Ушёл» разрешён всегда (решение пользователя 2026-07-17)."""
    for from_kind in ('progress', 'decision'):
        assert transitions.is_allowed(
            from_kind=from_kind, to_kind='lost', cycle_completed=False) is True
        assert transitions.is_allowed(
            from_kind=from_kind, to_kind='won', cycle_completed=False) is False
        assert transitions.is_allowed(
            from_kind=from_kind, to_kind='decision', to_is_auto=False, cycle_completed=False) is False
    with pytest.raises(InvalidTransition):
        transitions.assert_allowed(from_kind='decision', to_kind='won', cycle_completed=False)


def test_cycle_completed_normal_rules_apply():
    """Как только цикл завершён — обычные правила: ручная decision-стадия,
    won, lost — все разрешены."""
    assert transitions.is_allowed(
        from_kind='decision', to_kind='decision', to_is_auto=False, cycle_completed=True) is True
    assert transitions.is_allowed(from_kind='decision', to_kind='won', cycle_completed=True) is True
    assert transitions.is_allowed(from_kind='decision', to_kind='lost', cycle_completed=True) is True
