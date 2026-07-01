"""
E2E тесты для /api/admin/tokens.
"""
from __future__ import annotations

import re

import pytest
from django.db import connection

BASE_URL = '/api/admin/tokens'

_TOKEN_RE = re.compile(r'^[A-Z2-9]{3}-[A-Z2-9]{3}-[A-Z2-9]{3}$')


def _cleanup_token(token: str) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM tokens WHERE token = %s', [token])


def _get_teacher_id() -> int:
    with connection.cursor() as cur:
        cur.execute('SELECT id FROM teachers WHERE active = true LIMIT 1')
        row = cur.fetchone()
    if not row:
        pytest.skip('No active teachers in DB')
    return row[0]


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
def test_admin_returns_200(admin_client):
    resp = admin_client.get(BASE_URL)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_manager_returns_200(manager_client):
    resp = manager_client.get(BASE_URL)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/admin/tokens — list
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_list_returns_list(admin_client):
    resp = admin_client.get(BASE_URL)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.django_db
def test_list_include_inactive(admin_client):
    resp = admin_client.get(BASE_URL + '?include_inactive=1')
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# POST /api/admin/tokens/generate
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_generate_returns_token(admin_client):
    resp = admin_client.post(f'{BASE_URL}/generate', format='json')
    assert resp.status_code == 200
    data = resp.json()
    assert 'token' in data
    assert _TOKEN_RE.match(data['token']), f"Bad token format: {data['token']}"


@pytest.mark.django_db
def test_generate_does_not_save_to_db(admin_client):
    resp = admin_client.post(f'{BASE_URL}/generate', format='json')
    assert resp.status_code == 200
    token_str = resp.json()['token']
    # Убедимся что токена нет в БД
    with connection.cursor() as cur:
        cur.execute('SELECT 1 FROM tokens WHERE token = %s', [token_str])
        row = cur.fetchone()
    assert row is None


# ---------------------------------------------------------------------------
# POST /api/admin/tokens — create
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_returns_201(admin_client):
    teacher_id = _get_teacher_id()
    token_str = 'TST-API-222'
    _cleanup_token(token_str)
    resp = admin_client.post(
        BASE_URL,
        {'token': token_str, 'teacher_id': teacher_id},
        format='json',
    )
    if resp.status_code == 201:
        _cleanup_token(token_str)
    assert resp.status_code == 201


@pytest.mark.django_db
def test_create_invalid_token_format_returns_400(admin_client):
    teacher_id = _get_teacher_id()
    resp = admin_client.post(
        BASE_URL,
        {'token': 'BADTOKEN', 'teacher_id': teacher_id},
        format='json',
    )
    assert resp.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_create_duplicate_token_returns_409(admin_client):
    teacher_id = _get_teacher_id()
    token_str = 'TST-DUP-222'
    _cleanup_token(token_str)
    from apps.tokens import repository
    repository.create_token({'token': token_str, 'teacher_id': teacher_id})
    try:
        resp = admin_client.post(
            BASE_URL,
            {'token': token_str, 'teacher_id': teacher_id},
            format='json',
        )
        assert resp.status_code == 409
    finally:
        _cleanup_token(token_str)


# ---------------------------------------------------------------------------
# PATCH /api/admin/tokens/:token — update
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_patch_returns_200(admin_client):
    teacher_id = _get_teacher_id()
    token_str = 'TST-PTC-222'
    _cleanup_token(token_str)
    from apps.tokens import repository
    repository.create_token({'token': token_str, 'teacher_id': teacher_id})
    try:
        resp = admin_client.patch(
            f'{BASE_URL}/{token_str}',
            {'active': False},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.json()['active'] is False
    finally:
        _cleanup_token(token_str)


@pytest.mark.django_db
def test_patch_nonexistent_returns_404(admin_client):
    resp = admin_client.patch(
        f'{BASE_URL}/ZZZ-ZZZ-999',
        {'active': False},
        format='json',
    )
    assert resp.status_code == 404
    assert resp.json() == {'error': 'Not found'}


# ---------------------------------------------------------------------------
# DELETE /api/admin/tokens/:token — revoke
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_delete_returns_204(admin_client):
    teacher_id = _get_teacher_id()
    token_str = 'TST-DLT-222'
    _cleanup_token(token_str)
    from apps.tokens import repository
    repository.create_token({'token': token_str, 'teacher_id': teacher_id})
    try:
        resp = admin_client.delete(f'{BASE_URL}/{token_str}')
        assert resp.status_code == 204
    finally:
        _cleanup_token(token_str)


@pytest.mark.django_db
def test_delete_nonexistent_returns_404(admin_client):
    resp = admin_client.delete(f'{BASE_URL}/ZZZ-ZZZ-998')
    assert resp.status_code == 404
    assert resp.json() == {'error': 'Not found'}
