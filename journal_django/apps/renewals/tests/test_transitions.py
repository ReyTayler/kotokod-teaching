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
