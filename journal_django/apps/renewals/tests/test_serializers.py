"""Тесты сериализаторов renewals + smoke на repository.deal_computed."""
import pytest

from apps.renewals import engine, repository
from apps.renewals.serializers import DealPatchSerializer, MoveSerializer


def test_move_requires_stage():
    assert MoveSerializer(data={}).is_valid() is False
    assert MoveSerializer(data={'to_stage_id': 5}).is_valid() is True


def test_patch_all_optional():
    assert DealPatchSerializer(data={}).is_valid() is True


@pytest.mark.django_db
def test_deal_computed_shape(make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    data = repository.deal_computed(deal.id)
    assert data is not None
    for key in ('student_name', 'direction_name', 'stage_key', 'lesson_in_cycle', 'balance'):
        assert key in data
    assert data['student_name'] == '__renew_test_student__'
    assert data['lesson_in_cycle'] == 1


@pytest.mark.django_db
def test_deal_computed_missing_returns_none():
    assert repository.deal_computed(999999999) is None
