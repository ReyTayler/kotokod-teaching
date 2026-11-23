"""API-тесты для /api/admin/teachers/:id/comments."""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth.hashers import make_password
from django.db import connection

from conftest import make_auth_client

BASE_URL = '/api/admin/teachers'


def _create_teacher() -> int:
    name = f'__test_api_comment_teacher__{uuid.uuid4().hex[:8]}'
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO teachers (name, created_at) VALUES (%s, NOW()) RETURNING id',
            [name],
        )
        return cur.fetchone()[0]


def _cleanup_teacher(teacher_id: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM teacher_comment WHERE teacher_id = %s', [teacher_id])
        cur.execute('DELETE FROM teachers WHERE id = %s', [teacher_id])


def _add_comment(teacher_id: int, body: str = 'x') -> int:
    from apps.teachers.models import TeacherComment
    return TeacherComment.objects.create(teacher_id=teacher_id, body=body).id


def _comment_count(teacher_id: int) -> int:
    with connection.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM teacher_comment WHERE teacher_id = %s', [teacher_id])
        return cur.fetchone()[0]


def _create_named_admin_client(full_name: str):
    from apps.accounts.models import Account
    email = f'__test_named_admin__{uuid.uuid4().hex[:8]}@test.local'
    pw = make_password('testpass_sentinel')
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO accounts "
            "(email, password, role, is_active, is_staff, is_superuser, "
            "first_name, last_name, full_name, token_version, date_joined) "
            "VALUES (%s, %s, 'admin', true, false, false, '', '', %s, 0, NOW()) RETURNING id",
            [email, pw, full_name],
        )
        acc_id = cur.fetchone()[0]
    account = Account.objects.get(pk=acc_id)
    return make_auth_client(account), acc_id


def _cleanup_account(acc_id: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM accounts WHERE id = %s', [acc_id])


@pytest.fixture
def teacher_id():
    tid = _create_teacher()
    yield tid
    _cleanup_teacher(tid)


# ---------------------------------------------------------------------------
# Доступ
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_anon_list_returns_401(anon_client, teacher_id):
    assert anon_client.get(f'{BASE_URL}/{teacher_id}/comments').status_code == 401


@pytest.mark.django_db
def test_anon_create_returns_401(anon_client, teacher_id):
    resp = anon_client.post(f'{BASE_URL}/{teacher_id}/comments', {'body': 'x'}, format='json')
    assert resp.status_code == 401
    assert _comment_count(teacher_id) == 0


@pytest.mark.django_db
def test_anon_delete_returns_401(anon_client, teacher_id):
    comment_id = _add_comment(teacher_id)
    resp = anon_client.delete(f'{BASE_URL}/{teacher_id}/comments/{comment_id}')
    assert resp.status_code == 401
    assert _comment_count(teacher_id) == 1


@pytest.mark.django_db
def test_teacher_cannot_list(teacher_client, teacher_id):
    _add_comment(teacher_id, 'Служебная заметка')
    resp = teacher_client.get(f'{BASE_URL}/{teacher_id}/comments')
    assert resp.status_code == 403
    assert 'Служебная заметка' not in resp.content.decode()


@pytest.mark.django_db
def test_teacher_cannot_create(teacher_client, teacher_id):
    resp = teacher_client.post(f'{BASE_URL}/{teacher_id}/comments', {'body': 'x'}, format='json')
    assert resp.status_code == 403
    assert _comment_count(teacher_id) == 0


@pytest.mark.django_db
def test_teacher_cannot_delete(teacher_client, teacher_id):
    comment_id = _add_comment(teacher_id)
    resp = teacher_client.delete(f'{BASE_URL}/{teacher_id}/comments/{comment_id}')
    assert resp.status_code == 403
    assert _comment_count(teacher_id) == 1


@pytest.mark.django_db
def test_manager_can_create_and_list(manager_client, teacher_id):
    resp = manager_client.post(
        f'{BASE_URL}/{teacher_id}/comments',
        {'body': '  Просил не ставить уроки по пятницам  '},
        format='json',
    )
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {'id', 'body', 'created_at', 'author_id', 'author_name'}
    assert body['body'] == 'Просил не ставить уроки по пятницам'
    assert body['author_id'] is not None

    resp = manager_client.get(f'{BASE_URL}/{teacher_id}/comments')
    assert resp.status_code == 200
    data = resp.json()
    assert set(data) == {'rows', 'total', 'page', 'page_size'}
    assert data['total'] == 1
    assert data['rows'][0]['id'] == body['id']
    assert data['rows'][0]['body'] == 'Просил не ставить уроки по пятницам'


@pytest.mark.django_db
def test_manager_cannot_delete(manager_client, teacher_id):
    comment_id = _add_comment(teacher_id)
    resp = manager_client.delete(f'{BASE_URL}/{teacher_id}/comments/{comment_id}')
    assert resp.status_code == 403
    assert _comment_count(teacher_id) == 1


@pytest.mark.django_db
def test_admin_can_delete(admin_client, teacher_id):
    comment_id = _add_comment(teacher_id)
    resp = admin_client.delete(f'{BASE_URL}/{teacher_id}/comments/{comment_id}')
    assert resp.status_code == 204
    assert _comment_count(teacher_id) == 0
    resp = admin_client.delete(f'{BASE_URL}/{teacher_id}/comments/{comment_id}')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_superadmin_can_create_and_delete(superadmin_client, teacher_id):
    resp = superadmin_client.post(
        f'{BASE_URL}/{teacher_id}/comments', {'body': 'x'}, format='json')
    assert resp.status_code == 201
    resp = superadmin_client.delete(f'{BASE_URL}/{teacher_id}/comments/{resp.json()["id"]}')
    assert resp.status_code == 204
    assert _comment_count(teacher_id) == 0


# ---------------------------------------------------------------------------
# 404
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_unknown_teacher_list_returns_404(admin_client):
    assert admin_client.get(f'{BASE_URL}/999999999/comments').status_code == 404


@pytest.mark.django_db
def test_unknown_teacher_create_returns_404(admin_client):
    resp = admin_client.post(f'{BASE_URL}/999999999/comments', {'body': 'x'}, format='json')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_delete_unknown_comment_returns_404(admin_client, teacher_id):
    resp = admin_client.delete(f'{BASE_URL}/{teacher_id}/comments/999999999')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_delete_other_teachers_comment_returns_404(admin_client, teacher_id):
    """id чужого комментария под своим преподавателем — 404, комментарий цел."""
    other_id = _create_teacher()
    try:
        comment_id = _add_comment(other_id)
        resp = admin_client.delete(f'{BASE_URL}/{teacher_id}/comments/{comment_id}')
        assert resp.status_code == 404
        assert _comment_count(other_id) == 1
    finally:
        _cleanup_teacher(other_id)


# ---------------------------------------------------------------------------
# Валидация
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_blank_body_returns_400(admin_client, teacher_id):
    resp = admin_client.post(f'{BASE_URL}/{teacher_id}/comments', {'body': '  '}, format='json')
    assert resp.status_code == 400
    assert _comment_count(teacher_id) == 0


@pytest.mark.django_db
def test_create_missing_body_returns_400(admin_client, teacher_id):
    resp = admin_client.post(f'{BASE_URL}/{teacher_id}/comments', {}, format='json')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_create_too_long_body_returns_400(admin_client, teacher_id):
    resp = admin_client.post(
        f'{BASE_URL}/{teacher_id}/comments', {'body': 'x' * 5001}, format='json')
    assert resp.status_code == 400
    assert _comment_count(teacher_id) == 0


# ---------------------------------------------------------------------------
# Автор, порядок, пагинация, изоляция
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_author_name_reflects_creator(teacher_id):
    """author_name — Account.full_name автора, author_id — id его учётки."""
    client, acc_id = _create_named_admin_client('Иван Иванов')
    try:
        resp = client.post(f'{BASE_URL}/{teacher_id}/comments', {'body': 'Комментарий'}, format='json')
        assert resp.status_code == 201
        assert resp.json()['author_id'] == acc_id
        assert resp.json()['author_name'] == 'Иван Иванов'
        row = client.get(f'{BASE_URL}/{teacher_id}/comments').json()['rows'][0]
        assert row['author_name'] == 'Иван Иванов'
        assert row['author_id'] == acc_id
    finally:
        _cleanup_teacher(teacher_id)
        _cleanup_account(acc_id)


@pytest.mark.django_db
def test_author_id_from_body_is_ignored(teacher_id):
    """Автора нельзя подставить из тела запроса — он всегда request.user."""
    client, acc_id = _create_named_admin_client('Пётр Петров')
    try:
        resp = client.post(
            f'{BASE_URL}/{teacher_id}/comments',
            {'body': 'x', 'author_id': acc_id + 100000},
            format='json',
        )
        assert resp.status_code == 201
        assert resp.json()['author_id'] == acc_id
    finally:
        _cleanup_teacher(teacher_id)
        _cleanup_account(acc_id)


@pytest.mark.django_db
def test_list_newest_first(admin_client, teacher_id):
    ids = [_add_comment(teacher_id, f'c{i}') for i in range(3)]
    rows = admin_client.get(f'{BASE_URL}/{teacher_id}/comments').json()['rows']
    assert [r['id'] for r in rows] == list(reversed(ids))


@pytest.mark.django_db
def test_list_pagination(admin_client, teacher_id):
    ids = [_add_comment(teacher_id, f'c{i}') for i in range(5)]
    newest_first = list(reversed(ids))

    page1 = admin_client.get(f'{BASE_URL}/{teacher_id}/comments?page=1&page_size=2').json()
    page2 = admin_client.get(f'{BASE_URL}/{teacher_id}/comments?page=2&page_size=2').json()
    page3 = admin_client.get(f'{BASE_URL}/{teacher_id}/comments?page=3&page_size=2').json()
    assert page1['total'] == 5
    assert page1['page'] == 1
    assert page1['page_size'] == 2
    assert [r['id'] for r in page1['rows']] == newest_first[:2]
    assert [r['id'] for r in page2['rows']] == newest_first[2:4]
    assert [r['id'] for r in page3['rows']] == newest_first[4:]


@pytest.mark.django_db
def test_list_isolated_by_teacher(admin_client, teacher_id):
    other_id = _create_teacher()
    try:
        _add_comment(other_id, 'чужой')
        own = _add_comment(teacher_id, 'свой')
        data = admin_client.get(f'{BASE_URL}/{teacher_id}/comments').json()
        assert data['total'] == 1
        assert data['rows'][0]['id'] == own
    finally:
        _cleanup_teacher(other_id)


@pytest.mark.django_db
def test_list_single_query_for_authors(teacher_id,django_assert_max_num_queries):
    """Имена авторов — через JOIN, а не запрос на строку (N+1)."""
    from apps.teachers.models import TeacherComment
    client, acc_id = _create_named_admin_client('Автор')
    try:
        for i in range(5):
            TeacherComment.objects.create(teacher_id=teacher_id, body=f'c{i}', author_id=acc_id)
        # Фиксированный потолок: аутентификация + проверка преподавателя + COUNT + SELECT.
        # Не зависит от числа строк — с N+1 было бы 5+ запросов сверху.
        with django_assert_max_num_queries(6):
            resp = client.get(f'{BASE_URL}/{teacher_id}/comments')
        assert resp.status_code == 200
        assert all(r['author_name'] == 'Автор' for r in resp.json()['rows'])
    finally:
        _cleanup_teacher(teacher_id)
        _cleanup_account(acc_id)
