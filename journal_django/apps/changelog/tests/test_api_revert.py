"""POST /api/admin/changelog/<uuid>/revert — только admin/superadmin, аудит в security_audit_log."""
from __future__ import annotations

import pghistory
import pytest

from apps.audit.models import SecurityAuditLog

pytestmark = pytest.mark.django_db


def _last_op_id(client):
    return client.get('/api/admin/changelog?page_size=1').json()['rows'][0]['id']


def _create_direction(client):
    # Запись направлений — только superadmin (ReadStaffWriteSuperAdmin), поэтому
    # генератор события в этих тестах — superadmin_client; сам revert
    # проверяется отдельным клиентом (admin/manager/teacher/superadmin).
    resp = client.post('/api/admin/directions', {
        'name': '__chg_api_rev__', 'sheet_name': 'chg', 'is_individual': False,
    }, format='json')
    assert resp.status_code in (200, 201)


def test_revert_endpoint_success(admin_client, superadmin_client):
    """Admin откатывает операцию, сгенерированную superadmin'ом — разрешено."""
    _create_direction(superadmin_client)
    op_id = _last_op_id(admin_client)
    resp = admin_client.post(f'/api/admin/changelog/{op_id}/revert')
    assert resp.status_code == 200, resp.content
    assert resp.json()['reverted_events'] == 1
    # аудит-событие безопасности записано
    assert SecurityAuditLog.objects.filter(event='changelog_revert').exists()


def test_revert_endpoint_superadmin_allowed(superadmin_client):
    """Superadmin откатывает собственную операцию — разрешено."""
    _create_direction(superadmin_client)
    op_id = _last_op_id(superadmin_client)
    resp = superadmin_client.post(f'/api/admin/changelog/{op_id}/revert')
    assert resp.status_code == 200, resp.content


def test_revert_endpoint_conflict_409(admin_client, superadmin_client):
    from apps.directions.models import Direction
    _create_direction(superadmin_client)
    op_id = _last_op_id(admin_client)
    # Позднее изменение — свой контекст (в проде это другой запрос)
    with pghistory.context(url='/t2', method='PATCH'):
        Direction.objects.filter(name='__chg_api_rev__').update(name='__chg_api_rev2__')
    resp = admin_client.post(f'/api/admin/changelog/{op_id}/revert')
    assert resp.status_code == 409
    assert resp.json()['details']['conflicts']


def test_revert_endpoint_rbac(admin_client, manager_client, teacher_client, superadmin_client):
    """Manager/teacher — 403; admin — разрешено (не 403)."""
    _create_direction(superadmin_client)
    op_id = _last_op_id(admin_client)
    assert manager_client.post(f'/api/admin/changelog/{op_id}/revert').status_code == 403
    assert teacher_client.post(f'/api/admin/changelog/{op_id}/revert').status_code == 403
    resp = admin_client.post(f'/api/admin/changelog/{op_id}/revert')
    assert resp.status_code != 403


def test_revert_endpoint_double_revert_400(superadmin_client):
    """Повторный откат той же операции через API → 400."""
    _create_direction(superadmin_client)
    op_id = _last_op_id(superadmin_client)
    assert superadmin_client.post(f'/api/admin/changelog/{op_id}/revert').status_code == 200
    resp = superadmin_client.post(f'/api/admin/changelog/{op_id}/revert')
    assert resp.status_code == 400
    assert resp.json()['error']


def test_revert_endpoint_revert_of_revert_400(superadmin_client):
    """Откат самой revert-операции через API → 400."""
    _create_direction(superadmin_client)
    op_id = _last_op_id(superadmin_client)
    assert superadmin_client.post(f'/api/admin/changelog/{op_id}/revert').status_code == 200
    # revert-операция теперь на вершине ленты
    revert_op_id = next(
        r['id'] for r in superadmin_client.get('/api/admin/changelog?page_size=5').json()['rows']
        if r['operation'] == 'changelog.revert'
    )
    resp = superadmin_client.post(f'/api/admin/changelog/{revert_op_id}/revert')
    assert resp.status_code == 400
    assert resp.json()['error']


def test_revert_endpoint_404(admin_client):
    resp = admin_client.post(
        '/api/admin/changelog/00000000-0000-0000-0000-000000000000/revert')
    assert resp.status_code == 404
