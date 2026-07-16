"""
E2E тесты для /api/admin/extra-lessons (admin) и /api/extra-lessons (teacher).

Паттерн — как apps/lessons/tests/test_lessons_api.py: root conftest.py даёт
admin_client/manager_client/teacher_client/superadmin_client/anon_client (JWT
access-cookie для СВЕЖЕГО, случайного аккаунта на каждый вызов фикстуры).

Для teacher-скоуп тестов (владелец назначения vs чужой) нужен teacher-аккаунт,
привязанный к КОНКРЕТНОМУ teacher_id (не случайному) — по аналогии с
apps/teacher_spa/tests/conftest.py::account_fixture. Локальный хелпер
_teacher_client_for(teacher_id) создаёт такой аккаунт через api_client_for
(root conftest.py) + apps.accounts.models.Account.
"""
from __future__ import annotations

import pytest
from django.contrib.auth.hashers import make_password
from django.db import connection

pytestmark = pytest.mark.django_db

ADMIN_URL = '/api/admin/extra-lessons'
TEACHER_URL = '/api/extra-lessons'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _teacher_account_for(teacher_id: int, email: str) -> int:
    """Создаёт account с role='teacher', привязанный к КОНКРЕТНОМУ teacher_id."""
    pw = make_password('testpass_sentinel')
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO accounts
                (email, password, role, teacher_id, is_active, is_staff, is_superuser,
                 first_name, last_name, token_version, date_joined)
            VALUES (%s, %s, 'teacher', %s, true, false, false, '', '', 0, NOW())
            RETURNING id
            """,
            [email, pw, teacher_id],
        )
        return cur.fetchone()[0]


def _delete_account(account_id: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM security_audit_log WHERE account_id = %s OR target_id = %s', [account_id, account_id])
        cur.execute('DELETE FROM accounts WHERE id = %s', [account_id])


@pytest.fixture
def teacher_client_for(api_client_for, teacher_fixture, other_teacher_fixture):
    """teacher_client_for(teacher_id) → APIClient JWT для аккаунта, привязанного
    к ЭТОМУ teacher_id (в отличие от root teacher_client — случайный teacher).

    Явно зависит от teacher_fixture/other_teacher_fixture (даже если тест
    использует только один из них) — иначе нет гарантии, что наш account
    (FK teacher_id, ON DELETE NO ACTION в БД) будет удалён РАНЬШЕ, чем сам
    teacher-фикстура снесёт свою строку teachers, и DELETE FROM teachers
    упадёт по внешнему ключу. Явная fixture-зависимость гарантирует нужный
    порядок teardown (pytest: зависимость переживает зависящую фикстуру).
    """
    from apps.accounts.models import Account

    created_ids: list[int] = []

    def _make(teacher_id: int, email: str):
        acc_id = _teacher_account_for(teacher_id, email)
        created_ids.append(acc_id)
        account = Account.objects.get(pk=acc_id)
        return api_client_for(account)

    yield _make
    for acc_id in created_ids:
        _delete_account(acc_id)


def _create_payload(missed_lesson_id, teacher_id, student_id, date='2026-04-05'):
    return {
        'missed_lesson_id': missed_lesson_id,
        'teacher_id': teacher_id,
        'student_ids': [student_id],
        'scheduled_date': date,
        'scheduled_time': '15:00',
        'duration_minutes': 45,
    }


# ---------------------------------------------------------------------------
# Admin: create — RBAC
# ---------------------------------------------------------------------------

def test_manager_can_create_assignment(
    manager_client, teacher_fixture, missed_lesson_fixture, student_fixture,
):
    resp = manager_client.post(
        ADMIN_URL,
        _create_payload(missed_lesson_fixture, teacher_fixture, student_fixture),
        format='json',
    )
    assert resp.status_code == 201
    assert resp.data['status'] == 'scheduled'


def test_admin_can_create_assignment(
    admin_client, teacher_fixture, missed_lesson_fixture, student_fixture,
):
    resp = admin_client.post(
        ADMIN_URL,
        _create_payload(missed_lesson_fixture, teacher_fixture, student_fixture),
        format='json',
    )
    assert resp.status_code == 201


def test_teacher_cannot_create_assignment(
    teacher_client, teacher_fixture, missed_lesson_fixture, student_fixture,
):
    resp = teacher_client.post(
        ADMIN_URL,
        _create_payload(missed_lesson_fixture, teacher_fixture, student_fixture),
        format='json',
    )
    assert resp.status_code == 403


def test_unauthenticated_gets_401(
    anon_client, teacher_fixture, missed_lesson_fixture, student_fixture,
):
    resp = anon_client.post(
        ADMIN_URL,
        _create_payload(missed_lesson_fixture, teacher_fixture, student_fixture),
        format='json',
    )
    assert resp.status_code == 401


def test_create_missing_missed_lesson_400(
    admin_client, teacher_fixture, student_fixture,
):
    resp = admin_client.post(
        ADMIN_URL,
        _create_payload(999_999_999, teacher_fixture, student_fixture),
        format='json',
    )
    assert resp.status_code == 400


def test_create_invalid_body_400(admin_client):
    resp = admin_client.post(ADMIN_URL, {'missed_lesson_id': 'not-an-int'}, format='json')
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Admin: list / detail
# ---------------------------------------------------------------------------

def test_list_contract(admin_client):
    resp = admin_client.get(ADMIN_URL)
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {'rows', 'total', 'page', 'page_size'}


def test_get_detail_200(admin_client, teacher_fixture, missed_lesson_fixture, student_fixture):
    created = admin_client.post(
        ADMIN_URL,
        _create_payload(missed_lesson_fixture, teacher_fixture, student_fixture),
        format='json',
    ).data
    resp = admin_client.get(f'{ADMIN_URL}/{created["id"]}')
    assert resp.status_code == 200
    assert resp.data['id'] == created['id']


def test_get_detail_404(admin_client):
    resp = admin_client.get(f'{ADMIN_URL}/999999999')
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Admin: cancel
# ---------------------------------------------------------------------------

def test_cancel_happy_path(admin_client, teacher_fixture, missed_lesson_fixture, student_fixture):
    created = admin_client.post(
        ADMIN_URL,
        _create_payload(missed_lesson_fixture, teacher_fixture, student_fixture),
        format='json',
    ).data
    resp = admin_client.post(f'{ADMIN_URL}/{created["id"]}/cancel')
    assert resp.status_code == 200
    assert resp.data['status'] == 'cancelled'


def test_cancel_404(admin_client):
    resp = admin_client.post(f'{ADMIN_URL}/999999999/cancel')
    assert resp.status_code == 404


def test_cancel_conflict_when_already_cancelled(
    admin_client, teacher_fixture, missed_lesson_fixture, student_fixture,
):
    created = admin_client.post(
        ADMIN_URL,
        _create_payload(missed_lesson_fixture, teacher_fixture, student_fixture),
        format='json',
    ).data
    admin_client.post(f'{ADMIN_URL}/{created["id"]}/cancel')
    resp = admin_client.post(f'{ADMIN_URL}/{created["id"]}/cancel')
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Admin: delete (fact) — 404 / 409 (not done yet)
# ---------------------------------------------------------------------------

def test_delete_404(admin_client):
    resp = admin_client.delete(f'{ADMIN_URL}/999999999')
    assert resp.status_code == 404


def test_delete_conflict_when_not_done(
    admin_client, teacher_fixture, missed_lesson_fixture, student_fixture,
):
    created = admin_client.post(
        ADMIN_URL,
        _create_payload(missed_lesson_fixture, teacher_fixture, student_fixture),
        format='json',
    ).data
    resp = admin_client.delete(f'{ADMIN_URL}/{created["id"]}')
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Teacher: detail scope — own (200) vs. another teacher's (404, not 403)
# ---------------------------------------------------------------------------

def test_teacher_can_get_own_assignment(
    admin_client, teacher_client_for, teacher_fixture, missed_lesson_fixture, student_fixture,
):
    created = admin_client.post(
        ADMIN_URL,
        _create_payload(missed_lesson_fixture, teacher_fixture, student_fixture),
        format='json',
    ).data
    owner_client = teacher_client_for(teacher_fixture, '__el_owner__@test.local')
    resp = owner_client.get(f'{TEACHER_URL}/{created["id"]}')
    assert resp.status_code == 200
    assert resp.data['id'] == created['id']


def test_teacher_gets_404_for_another_teachers_assignment(
    admin_client, teacher_client_for, teacher_fixture, other_teacher_fixture,
    missed_lesson_fixture, student_fixture,
):
    created = admin_client.post(
        ADMIN_URL,
        _create_payload(missed_lesson_fixture, teacher_fixture, student_fixture),
        format='json',
    ).data
    stranger_client = teacher_client_for(other_teacher_fixture, '__el_stranger__@test.local')
    resp = stranger_client.get(f'{TEACHER_URL}/{created["id"]}')
    # Единый 404 — не раскрываем чужим существование назначения (не 403).
    assert resp.status_code == 404


def test_teacher_detail_404_for_nonexistent(teacher_client):
    resp = teacher_client.get(f'{TEACHER_URL}/999999999')
    assert resp.status_code == 404


def test_manager_cannot_use_teacher_endpoint(manager_client):
    resp = manager_client.get(f'{TEACHER_URL}/1')
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Teacher: record
# ---------------------------------------------------------------------------

def test_teacher_can_record_own_assignment(
    admin_client, teacher_client_for, teacher_fixture, missed_lesson_fixture, student_fixture,
):
    created = admin_client.post(
        ADMIN_URL,
        _create_payload(missed_lesson_fixture, teacher_fixture, student_fixture),
        format='json',
    ).data
    owner_client = teacher_client_for(teacher_fixture, '__el_owner2__@test.local')
    try:
        resp = owner_client.post(
            f'{TEACHER_URL}/{created["id"]}/record',
            {
                'attendance': [{'student_id': student_fixture, 'present': True}],
                'record_url': None,
            },
            format='json',
        )
        assert resp.status_code == 200
        assert 'lesson_id' in resp.data
        assert 'payment' in resp.data
        assert 'penalty' in resp.data
    finally:
        with connection.cursor() as cur:
            cur.execute(
                'SELECT fact_lesson_id FROM extra_lesson_assignments WHERE id = %s',
                [created['id']],
            )
            row = cur.fetchone()
            fact_lesson_id = row[0] if row else None
        if fact_lesson_id:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [fact_lesson_id])
                cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [fact_lesson_id])
                cur.execute('DELETE FROM lessons WHERE id = %s', [fact_lesson_id])


def test_teacher_cannot_record_another_teachers_assignment(
    admin_client, teacher_client_for, teacher_fixture, other_teacher_fixture,
    missed_lesson_fixture, student_fixture,
):
    created = admin_client.post(
        ADMIN_URL,
        _create_payload(missed_lesson_fixture, teacher_fixture, student_fixture),
        format='json',
    ).data
    stranger_client = teacher_client_for(other_teacher_fixture, '__el_stranger2__@test.local')
    resp = stranger_client.post(
        f'{TEACHER_URL}/{created["id"]}/record',
        {'attendance': [{'student_id': student_fixture, 'present': True}], 'record_url': None},
        format='json',
    )
    assert resp.status_code == 403


def test_record_404_for_nonexistent(teacher_client, student_fixture):
    resp = teacher_client.post(
        f'{TEACHER_URL}/999999999/record',
        {'attendance': [{'student_id': student_fixture, 'present': True}], 'record_url': None},
        format='json',
    )
    assert resp.status_code == 404


def test_record_conflict_when_already_done(
    admin_client, teacher_client_for, teacher_fixture, missed_lesson_fixture, student_fixture,
):
    created = admin_client.post(
        ADMIN_URL,
        _create_payload(missed_lesson_fixture, teacher_fixture, student_fixture),
        format='json',
    ).data
    owner_client = teacher_client_for(teacher_fixture, '__el_owner3__@test.local')
    body = {'attendance': [{'student_id': student_fixture, 'present': True}], 'record_url': None}
    first = owner_client.post(f'{TEACHER_URL}/{created["id"]}/record', body, format='json')
    assert first.status_code == 200
    try:
        second = owner_client.post(f'{TEACHER_URL}/{created["id"]}/record', body, format='json')
        assert second.status_code == 409
    finally:
        fact_lesson_id = first.data['lesson_id']
        with connection.cursor() as cur:
            cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [fact_lesson_id])
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [fact_lesson_id])
            cur.execute('DELETE FROM lessons WHERE id = %s', [fact_lesson_id])


def test_record_invalid_body_400(teacher_client):
    resp = teacher_client.post(f'{TEACHER_URL}/1/record', {}, format='json')
    assert resp.status_code == 400
