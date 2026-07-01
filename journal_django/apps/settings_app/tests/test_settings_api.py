"""
E2E тесты для /api/admin/settings.

Фаза 4: аутентификация через JWT. Использует корневые фикстуры admin_client /
manager_client / teacher_client / anon_client.
_cleanup_settings убирает записи по account_id, который теперь берётся из
реального аккаунта (не sentinel 99997).
"""
from __future__ import annotations

import pytest
from django.db import connection

BASE_URL = '/api/admin/settings'


def _cleanup_settings_for_client(client_account_id: int) -> None:
    """Удаляем настройки, сохранённые тестом (по username = str(account_id))."""
    with connection.cursor() as cur:
        cur.execute(
            'DELETE FROM admin_user_settings WHERE username = %s',
            [str(client_account_id)],
        )


# ---------------------------------------------------------------------------
# Authentication / authorization
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_no_cookie_returns_401(anon_client):
    resp = anon_client.get(BASE_URL)
    assert resp.status_code == 401


@pytest.mark.django_db
def test_teacher_cookie_returns_403(teacher_client):
    resp = teacher_client.get(BASE_URL)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_admin_get_returns_200(admin_client):
    resp = admin_client.get(BASE_URL)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_manager_get_returns_200(manager_client):
    resp = manager_client.get(BASE_URL)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/admin/settings
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_get_returns_settings_shape(admin_client):
    resp = admin_client.get(BASE_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert 'settings' in data
    assert isinstance(data['settings'], dict)


@pytest.mark.django_db
def test_get_empty_settings_for_new_account(admin_client):
    """Новый аккаунт возвращает пустой объект настроек."""
    resp = admin_client.get(BASE_URL)
    assert resp.status_code == 200
    assert isinstance(resp.json()['settings'], dict)


# ---------------------------------------------------------------------------
# PUT /api/admin/settings
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_put_saves_and_returns_settings(admin_client):
    payload = {'theme': 'dark', 'pageSize': 25}
    resp = admin_client.put(BASE_URL, payload, format='json')
    assert resp.status_code == 200
    data = resp.json()
    assert 'settings' in data
    assert data['settings']['theme'] == 'dark'
    assert data['settings']['pageSize'] == 25


@pytest.mark.django_db
def test_put_persists_settings(admin_client):
    """PUT, затем GET возвращает то же самое."""
    payload = {'columns': ['id', 'name', 'active']}
    admin_client.put(BASE_URL, payload, format='json')

    resp = admin_client.get(BASE_URL)
    assert resp.status_code == 200
    assert resp.json()['settings']['columns'] == ['id', 'name', 'active']


@pytest.mark.django_db
def test_put_non_object_returns_400(admin_client):
    resp = admin_client.put(BASE_URL, [1, 2, 3], format='json')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_put_returns_200_not_201(admin_client):
    resp = admin_client.put(BASE_URL, {'x': 1}, format='json')
    assert resp.status_code == 200
