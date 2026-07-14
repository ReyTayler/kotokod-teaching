# journal_django/apps/sync/tests/test_views.py
import pytest


@pytest.mark.django_db
def test_run_requires_superadmin(admin_client):
    """admin (не superadmin) не должен пройти — см. apps.core.permissions.IsSuperAdmin."""
    resp = admin_client.post('/api/admin/sync/teachers/run', {'dry_run': True}, format='json')
    assert resp.status_code == 403


@pytest.mark.django_db
def test_run_rejects_anonymous(anon_client):
    resp = anon_client.post('/api/admin/sync/teachers/run', {'dry_run': True}, format='json')
    assert resp.status_code == 401


@pytest.mark.django_db
def test_run_unknown_action_404(superadmin_client):
    resp = superadmin_client.post('/api/admin/sync/does-not-exist/run', {'dry_run': True}, format='json')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_run_and_status_happy_path(superadmin_client, monkeypatch):
    """CELERY_TASK_ALWAYS_EAGER=True в тестах (нет REDIS_URL) — .delay() выполняется
    синхронно; CELERY_TASK_STORE_EAGER_RESULT=True (Task 1) кладёт результат в backend,
    поэтому последующий GET .../status/<task_id> его находит."""
    monkeypatch.setattr(
        'apps.sync.backfills.teachers.run',
        lambda dry_run=False: {'entity': 'teachers', 'read': 3, 'inserted': 3, 'dry_run': dry_run},
    )

    run_resp = superadmin_client.post('/api/admin/sync/teachers/run', {'dry_run': True}, format='json')
    assert run_resp.status_code == 202
    task_id = run_resp.data['task_id']
    assert task_id

    status_resp = superadmin_client.get(f'/api/admin/sync/status/{task_id}')
    assert status_resp.status_code == 200
    assert status_resp.data['state'] == 'SUCCESS'
    assert status_resp.data['result'] == {'entity': 'teachers', 'read': 3, 'inserted': 3, 'dry_run': True}
    assert status_resp.data['error'] is None


@pytest.mark.django_db
def test_status_reports_failure(superadmin_client, monkeypatch):
    def boom(dry_run=False):
        raise RuntimeError('лист не найден')

    monkeypatch.setattr('apps.sync.backfills.teachers.run', boom)

    run_resp = superadmin_client.post('/api/admin/sync/teachers/run', {'dry_run': False}, format='json')
    task_id = run_resp.data['task_id']

    status_resp = superadmin_client.get(f'/api/admin/sync/status/{task_id}')
    assert status_resp.data['state'] == 'FAILURE'
    assert 'лист не найден' in status_resp.data['error']
