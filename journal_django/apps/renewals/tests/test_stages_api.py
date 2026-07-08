"""API стадий воронки: read — staff (manager/admin/superadmin), write — только superadmin."""
import pytest

BASE = '/api/admin/renewals/stages'


@pytest.mark.django_db
def test_manager_reads_stages(manager_client):
    assert manager_client.get(BASE).status_code == 200


@pytest.mark.django_db
def test_manager_cannot_create(manager_client):
    resp = manager_client.post(BASE, {'label': 'X', 'kind': 'decision'}, format='json')
    assert resp.status_code == 403


@pytest.mark.django_db
def test_super_creates_and_deletes(superadmin_client):
    resp = superadmin_client.post(BASE, {'label': 'Перезвонить позже', 'kind': 'decision',
                                         'color': '#AABBCC'}, format='json')
    assert resp.status_code == 201
    sid = resp.json()['id']
    assert superadmin_client.delete(f'{BASE}/{sid}').status_code == 204


@pytest.mark.django_db
def test_cannot_delete_protected_auto_stage(superadmin_client):
    """Единственную auto-стадию lesson_progress удалить нельзя → 409."""
    stages = superadmin_client.get(BASE).json()
    auto = next(s for s in stages if s['key'] == 'lesson_progress')
    resp = superadmin_client.delete(f"{BASE}/{auto['id']}")
    assert resp.status_code == 409
    assert resp.json()['error'] == 'protected'


@pytest.mark.django_db
def test_super_reorders_stages(superadmin_client):
    """Reorder меняет sort_order: GET отражает новый порядок."""
    stages = superadmin_client.get(BASE).json()
    order = [s['id'] for s in stages]
    reversed_order = list(reversed(order))
    resp = superadmin_client.post(f'{BASE}/reorder', {'order': reversed_order}, format='json')
    assert resp.status_code == 200
    after = [s['id'] for s in resp.json()]
    assert after == reversed_order
    # GET подтверждает персистентность
    again = [s['id'] for s in superadmin_client.get(BASE).json()]
    assert again == reversed_order


@pytest.mark.django_db
def test_manager_cannot_reorder(manager_client):
    resp = manager_client.post(f'{BASE}/reorder', {'order': [1, 2]}, format='json')
    assert resp.status_code == 403
