"""API-тесты записи renewals: move (валидация переходов), patch, comment, activity."""
import pytest

from apps.renewals import engine
from apps.renewals.models import RenewalStage

BASE = '/api/admin/renewals'


def _stage_id(key):
    return RenewalStage.objects.get(key=key, pipeline__is_default=True).id


@pytest.mark.django_db
def test_move_to_decision(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('awaiting_payment')}, format='json')
    assert resp.status_code == 200
    assert resp.json()['stage_key'] == 'awaiting_payment'


@pytest.mark.django_db
def test_move_from_terminal_409(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    admin_client.post(f'{BASE}/{deal.id}/move', {'to_stage_id': _stage_id('churned')}, format='json')
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('thinking')}, format='json')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_move_to_stage_outside_pipeline_409(admin_client, make_student, make_direction):
    """to_stage_id, которого нет в воронке сделки → InvalidTransition → 409, не 500."""
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': 999999999}, format='json')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_patch_next_touch(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    resp = admin_client.patch(f'{BASE}/{deal.id}',
                              {'next_touch_at': '2026-07-15'}, format='json')
    assert resp.status_code == 200
    assert resp.json()['next_touch_at'] == '2026-07-15'


@pytest.mark.django_db
def test_comment_then_activity(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    admin_client.post(f'{BASE}/{deal.id}/comment', {'body': 'позвонил, думает'}, format='json')
    acts = admin_client.get(f'{BASE}/{deal.id}/activity').json()
    assert any(a['kind'] == 'comment' and a['body'] == 'позвонил, думает' for a in acts)
