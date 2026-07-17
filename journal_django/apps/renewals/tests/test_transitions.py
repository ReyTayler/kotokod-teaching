import pytest
from apps.renewals import transitions
from apps.renewals.transitions import InvalidTransition


def test_terminal_stages_are_frozen():
    assert transitions.is_allowed(from_kind='won', to_kind='decision') is False
    assert transitions.is_allowed(from_kind='lost', to_kind='progress') is False


def test_open_to_terminal_allowed():
    assert transitions.is_allowed(from_kind='progress', to_kind='won') is True
    assert transitions.is_allowed(from_kind='decision', to_kind='lost') is True
    assert transitions.is_allowed(from_kind='decision', to_kind='decision') is True


def test_assert_raises():
    with pytest.raises(InvalidTransition):
        transitions.assert_allowed(from_kind='won', to_kind='decision')


def test_cannot_manually_move_onto_progress_stage():
    """Прогресс-стадии («Не было урока»/«Урок N») двигает только движок —
    вручную выставить сделку на конкретный урок цикла нельзя, ни с decision,
    ни с другой progress-стадии."""
    assert transitions.is_allowed(from_kind='decision', to_kind='progress') is False
    assert transitions.is_allowed(from_kind='progress', to_kind='progress') is False
    with pytest.raises(InvalidTransition):
        transitions.assert_allowed(from_kind='decision', to_kind='progress')


def test_can_still_manually_move_off_progress_stage():
    """А вот увести сделку С прогресс-стадии вручную (заморозить, отметить
    ушедшим и т.п.) по-прежнему можно — иначе свежесозданную сделку
    (стартует на «Не было урока») нельзя было бы тронуть руками вовсе."""
    assert transitions.is_allowed(from_kind='progress', to_kind='decision') is True
    assert transitions.is_allowed(from_kind='progress', to_kind='won') is True
    assert transitions.is_allowed(from_kind='progress', to_kind='lost') is True
