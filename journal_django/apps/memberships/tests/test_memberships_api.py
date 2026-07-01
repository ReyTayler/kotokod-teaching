"""
E2E тесты для /api/admin/memberships.

Используют DRF APIClient с реальной БД (managed=False, продовая).
Все созданные строки удаляются в teardown (прямой DELETE через connection).

Cookie:
  Генерируются через _make_cookie() из conftest.py — идентично Node.js sign().
  ADMIN_COOKIE_SECRET переопределяется через pytest-django фикстуру settings.

Тестируемые кейсы:
  - без cookie → 401
  - cookie role=teacher → 403
  - cookie role=admin → 200 (список)
  - cookie role=manager → 200 (список)
  - GET список — массив (не dict с rows/total/page/page_size)
  - GET фильтры: group_id, student_id, include_inactive=1
  - POST → 201, UPSERT (повторный POST → 201 с реактивацией)
  - PATCH → 200/404
  - DELETE → 204/404
"""
from __future__ import annotations

import pytest
from django.db import connection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = '/api/admin/memberships'


def _get_valid_group_id() -> int:
    with connection.cursor() as cur:
        cur.execute('SELECT id FROM groups WHERE active = true LIMIT 1')
        row = cur.fetchone()
    if not row:
        pytest.skip('No active groups in DB')
    return row[0]


def _get_valid_student_id() -> int:
    with connection.cursor() as cur:
        cur.execute('SELECT id FROM students LIMIT 1')
        row = cur.fetchone()
    if not row:
        pytest.skip('No students in DB')
    return row[0]


def _cleanup_pair(group_id: int, student_id: int) -> None:
    """Удалить все строки для пары (group_id, student_id)."""
    with connection.cursor() as cur:
        cur.execute(
            'DELETE FROM group_memberships WHERE group_id = %s AND student_id = %s',
            [group_id, student_id],
        )


def _cleanup_by_id(membership_id: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])


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
def test_admin_cookie_returns_200(admin_client):
    resp = admin_client.get(BASE_URL)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_manager_cookie_returns_200(manager_client):
    resp = manager_client.get(BASE_URL)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/admin/memberships — list
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_list_returns_array(admin_client):
    """Ответ — массив, не dict {rows, total, page, page_size}."""
    resp = admin_client.get(BASE_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.django_db
def test_list_not_paginated(admin_client):
    """Ответ не содержит ключей пагинатора."""
    resp = admin_client.get(BASE_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert not isinstance(data, dict)


@pytest.mark.django_db
def test_list_default_only_active(admin_client):
    """По умолчанию include_inactive не передан — только active=true."""
    resp = admin_client.get(BASE_URL)
    assert resp.status_code == 200
    for row in resp.json():
        assert row['active'] is True


@pytest.mark.django_db
def test_list_include_inactive(admin_client):
    """include_inactive=1 возвращает все записи."""
    resp_active = admin_client.get(BASE_URL)
    resp_all = admin_client.get(BASE_URL + '?include_inactive=1')
    assert resp_all.status_code == 200
    assert len(resp_all.json()) >= len(resp_active.json())


@pytest.mark.django_db
def test_list_filter_by_group_id(admin_client):
    group_id = _get_valid_group_id()
    resp = admin_client.get(BASE_URL + f'?group_id={group_id}&include_inactive=1')
    assert resp.status_code == 200
    for row in resp.json():
        assert row['group_id'] == group_id


@pytest.mark.django_db
def test_list_filter_by_student_id(admin_client):
    student_id = _get_valid_student_id()
    resp = admin_client.get(BASE_URL + f'?student_id={student_id}&include_inactive=1')
    assert resp.status_code == 200
    for row in resp.json():
        assert row['student_id'] == student_id


@pytest.mark.django_db
def test_list_rows_have_group_name(admin_client):
    resp = admin_client.get(BASE_URL)
    assert resp.status_code == 200
    rows = resp.json()
    if rows:
        assert 'group_name' in rows[0]


@pytest.mark.django_db
def test_list_rows_have_student_name(admin_client):
    resp = admin_client.get(BASE_URL)
    assert resp.status_code == 200
    rows = resp.json()
    if rows:
        assert 'student_name' in rows[0]


@pytest.mark.django_db
def test_list_filter_nonexistent_group_empty(admin_client):
    resp = admin_client.get(BASE_URL + '?group_id=999999999')
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /api/admin/memberships — create / upsert
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_post_returns_201(admin_client):
    group_id = _get_valid_group_id()
    student_id = _get_valid_student_id()
    _cleanup_pair(group_id, student_id)
    try:
        resp = admin_client.post(
            BASE_URL,
            {'group_id': group_id, 'student_id': student_id},
            format='json',
        )
        assert resp.status_code == 201
    finally:
        _cleanup_pair(group_id, student_id)


@pytest.mark.django_db
def test_post_creates_membership(admin_client):
    group_id = _get_valid_group_id()
    student_id = _get_valid_student_id()
    _cleanup_pair(group_id, student_id)
    try:
        resp = admin_client.post(
            BASE_URL,
            {'group_id': group_id, 'student_id': student_id},
            format='json',
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data['group_id'] == group_id
        assert data['student_id'] == student_id
        assert data['active'] is True
    finally:
        _cleanup_pair(group_id, student_id)


@pytest.mark.django_db
def test_post_with_start_date(admin_client):
    group_id = _get_valid_group_id()
    student_id = _get_valid_student_id()
    _cleanup_pair(group_id, student_id)
    try:
        resp = admin_client.post(
            BASE_URL,
            {'group_id': group_id, 'student_id': student_id, 'start_date': '2025-09-01'},
            format='json',
        )
        assert resp.status_code == 201
        assert resp.json()['start_date'] == '2025-09-01'
    finally:
        _cleanup_pair(group_id, student_id)


@pytest.mark.django_db
def test_post_upsert_reactivation(admin_client):
    """
    UPSERT: повторный POST той же пары после удаления → 201 с active=true.

    Не должен возвращать 409 и не должен создавать дубль.
    """
    group_id = _get_valid_group_id()
    student_id = _get_valid_student_id()
    _cleanup_pair(group_id, student_id)
    try:
        # Создаём
        resp1 = admin_client.post(
            BASE_URL,
            {'group_id': group_id, 'student_id': student_id},
            format='json',
        )
        assert resp1.status_code == 201
        membership_id = resp1.json()['id']

        # Деактивируем напрямую
        with connection.cursor() as cur:
            cur.execute(
                'UPDATE group_memberships SET active = false WHERE id = %s',
                [membership_id],
            )

        # Повторный POST → реактивация
        resp2 = admin_client.post(
            BASE_URL,
            {'group_id': group_id, 'student_id': student_id},
            format='json',
        )
        assert resp2.status_code == 201
        data2 = resp2.json()
        assert data2['id'] == membership_id  # тот же id
        assert data2['active'] is True
    finally:
        _cleanup_pair(group_id, student_id)


@pytest.mark.django_db
def test_post_missing_group_id_returns_400(admin_client):
    student_id = _get_valid_student_id()
    resp = admin_client.post(BASE_URL, {'student_id': student_id}, format='json')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_post_missing_student_id_returns_400(admin_client):
    group_id = _get_valid_group_id()
    resp = admin_client.post(BASE_URL, {'group_id': group_id}, format='json')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_post_invalid_group_id_zero_returns_400(admin_client):
    student_id = _get_valid_student_id()
    resp = admin_client.post(
        BASE_URL,
        {'group_id': 0, 'student_id': student_id},
        format='json',
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PATCH /api/admin/memberships/:id — update
# ---------------------------------------------------------------------------

@pytest.fixture
def existing_membership():
    """Создаёт membership и удаляет после теста."""
    group_id = _get_valid_group_id()
    student_id = _get_valid_student_id()
    _cleanup_pair(group_id, student_id)
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO group_memberships (group_id, student_id, lessons_done, remaining, active)
            VALUES (%s, %s, 0, 0, true)
            ON CONFLICT (group_id, student_id) DO UPDATE SET active = true
            RETURNING *
            """,
            [group_id, student_id],
        )
        columns = [col[0] for col in cur.description]
        row = dict(zip(columns, cur.fetchone()))
    yield row
    _cleanup_pair(group_id, student_id)


@pytest.mark.django_db
def test_patch_returns_200(admin_client, existing_membership):
    resp = admin_client.patch(
        f"{BASE_URL}/{existing_membership['id']}",
        {'active': False},
        format='json',
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_patch_updates_active(admin_client, existing_membership):
    resp = admin_client.patch(
        f"{BASE_URL}/{existing_membership['id']}",
        {'active': False},
        format='json',
    )
    assert resp.status_code == 200
    assert resp.json()['active'] is False


@pytest.mark.django_db
def test_patch_updates_start_date(admin_client, existing_membership):
    resp = admin_client.patch(
        f"{BASE_URL}/{existing_membership['id']}",
        {'start_date': '2025-06-01'},
        format='json',
    )
    assert resp.status_code == 200
    assert resp.json()['start_date'] == '2025-06-01'


@pytest.mark.django_db
def test_patch_nonexistent_returns_404(admin_client):
    resp = admin_client.patch(
        f'{BASE_URL}/999999999',
        {'active': False},
        format='json',
    )
    assert resp.status_code == 404
    assert resp.json() == {'error': 'Not found'}


# ---------------------------------------------------------------------------
# DELETE /api/admin/memberships/:id — soft delete
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_delete_returns_204(admin_client):
    group_id = _get_valid_group_id()
    student_id = _get_valid_student_id()
    _cleanup_pair(group_id, student_id)
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO group_memberships (group_id, student_id, lessons_done, remaining, active)
            VALUES (%s, %s, 0, 0, true)
            ON CONFLICT (group_id, student_id) DO UPDATE SET active = true
            RETURNING id
            """,
            [group_id, student_id],
        )
        membership_id = cur.fetchone()[0]
    try:
        resp = admin_client.delete(f'{BASE_URL}/{membership_id}')
        assert resp.status_code == 204
    finally:
        _cleanup_pair(group_id, student_id)


@pytest.mark.django_db
def test_delete_sets_active_false(admin_client):
    group_id = _get_valid_group_id()
    student_id = _get_valid_student_id()
    _cleanup_pair(group_id, student_id)
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO group_memberships (group_id, student_id, lessons_done, remaining, active)
            VALUES (%s, %s, 0, 0, true)
            ON CONFLICT (group_id, student_id) DO UPDATE SET active = true
            RETURNING id
            """,
            [group_id, student_id],
        )
        membership_id = cur.fetchone()[0]
    try:
        admin_client.delete(f'{BASE_URL}/{membership_id}')
        # Проверяем через БД
        with connection.cursor() as cur:
            cur.execute(
                'SELECT active FROM group_memberships WHERE id = %s',
                [membership_id],
            )
            active = cur.fetchone()[0]
        assert active is False
    finally:
        _cleanup_pair(group_id, student_id)


@pytest.mark.django_db
def test_delete_nonexistent_returns_404(admin_client):
    resp = admin_client.delete(f'{BASE_URL}/999999999')
    assert resp.status_code == 404
    assert resp.json() == {'error': 'Not found'}
