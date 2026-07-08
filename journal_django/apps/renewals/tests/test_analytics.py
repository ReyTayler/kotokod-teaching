import pytest

from apps.renewals import engine


@pytest.mark.django_db
def test_analytics_shape(manager_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    resp = manager_client.get('/api/admin/renewals/analytics')
    assert resp.status_code == 200
    body = resp.json()
    assert 'stages' in body and 'renewal_rate_30d' in body
    assert 'won_30d' in body and 'lost_30d' in body


@pytest.mark.django_db
def test_analytics_counts_open_deal_in_progress_stage(manager_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    body = manager_client.get('/api/admin/renewals/analytics').json()
    progress = next(s for s in body['stages'] if s['kind'] == 'progress')
    assert progress['cnt'] >= 1


@pytest.mark.django_db
def test_analytics_requires_staff(teacher_client):
    assert teacher_client.get('/api/admin/renewals/analytics').status_code == 403
