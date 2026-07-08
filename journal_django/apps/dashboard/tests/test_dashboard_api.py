"""
E2E тесты для /api/admin/dashboard (DRF APIClient, реальная БД managed=False).

Дашборд агрегирует всю базу — точные суммы сверяет e2e-diff с Express (golden).
Здесь: auth, валидация (invalid_date/invalid_year), форма ответа и ТИПЫ (числа, не строки).
"""
from __future__ import annotations

import pytest
from django.contrib.auth.hashers import make_password
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

BASE = '/api/admin/dashboard'

_ROLE_EMAILS = {
    'admin': '__dash_admin__@example.com',
    'manager': '__dash_manager__@example.com',
    'teacher': '__dash_teacher__@example.com',
}
_CREATED_IDS: list[int] = []


@pytest.fixture(scope='session')
def django_db_setup():
    pass


def _get_or_create_account(role: str) -> 'Account':
    email = _ROLE_EMAILS[role]
    try:
        return Account.objects.get(email=email)
    except Account.DoesNotExist:
        from django.db import connection as _conn
        with _conn.cursor() as cur:
            # role='teacher' требует teacher_id (CHECK accounts_teacher_role_check).
            teacher_id = None
            if role == 'teacher':
                cur.execute("INSERT INTO teachers (name) VALUES ('__dash_teacher__') RETURNING id")
                teacher_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO accounts (email, password, role, teacher_id, is_active, is_staff, is_superuser, first_name, last_name, date_joined, token_version) "
                "VALUES (%s, %s, %s, %s, true, false, false, '', '', NOW(), 0) RETURNING id",
                [email, make_password('testpass123'), role, teacher_id],
            )
            acc_id = cur.fetchone()[0]
            _CREATED_IDS.append(acc_id)
        return Account.objects.get(pk=acc_id)


def _client(role: str | None) -> APIClient:
    c = APIClient()
    if role is not None:
        account = _get_or_create_account(role)
        refresh = RefreshToken.for_user(account)
        refresh['token_version'] = account.token_version
        c.cookies['access'] = str(refresh.access_token)
    return c


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_requires_auth():
    assert _client(None).get(BASE).status_code == 401


def test_teacher_forbidden():
    assert _client('teacher').get(BASE).status_code == 403


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('role', ['manager', 'admin'])
def test_dashboard_shape_and_types(role):
    resp = _client(role).get(BASE)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        'month', 'from', 'to', 'revenue_month', 'worked_off_month',
        'carryover_month', 'deferred_total', 'debts', 'debts_total',
    }
    # Денежные значения — JSON-числа, не строки (как Express Number()).
    for k in ('revenue_month', 'worked_off_month', 'carryover_month', 'deferred_total'):
        assert isinstance(body[k], (int, float)), f'{k} must be number, got {type(body[k])}'
    assert isinstance(body['debts'], list)
    assert isinstance(body['debts_total'], int)
    # top-долги ≤ 8, balance — число, отсортированы по возрастанию.
    assert len(body['debts']) <= 8
    balances = [d['balance'] for d in body['debts']]
    for b in balances:
        assert isinstance(b, (int, float))
    assert balances == sorted(balances)
    # Долг — общий пул по ученику (2026-07-08), без разбивки по направлению.
    for d in body['debts']:
        assert set(d.keys()) == {'student_id', 'student_name', 'balance'}


def test_dashboard_invalid_date():
    resp = _client('manager').get(BASE, {'from': '2026-13-99'})
    assert resp.status_code == 400
    assert resp.json() == {'error': 'invalid_date'}


def test_dashboard_invalid_date_impossible_day():
    resp = _client('manager').get(BASE, {'to': '2026-02-30'})
    assert resp.status_code == 400


def test_dashboard_valid_range_echoes_params():
    resp = _client('manager').get(BASE, {'from': '2026-01-01', 'to': '2026-12-31'})
    assert resp.status_code == 200
    body = resp.json()
    assert body['from'] == '2026-01-01'
    assert body['to'] == '2026-12-31'


# ---------------------------------------------------------------------------
# Monthly
# ---------------------------------------------------------------------------

def test_monthly_shape():
    resp = _client('manager').get(f'{BASE}/monthly', {'year': '2026'})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {'years', 'available_years', 'byYear'}
    assert body['years'] == [2026]
    assert '2026' in body['byYear']         # JSON-ключ года — строка
    months = body['byYear']['2026']
    assert len(months) == 12
    assert months[0]['month'] == 1
    for cell in months:
        assert isinstance(cell['revenue'], (int, float))
        assert isinstance(cell['worked_off'], (int, float))


def test_monthly_years_list():
    resp = _client('manager').get(f'{BASE}/monthly', {'years': '2025,2026'})
    assert resp.status_code == 200
    body = resp.json()
    assert body['years'] == [2025, 2026]
    assert set(body['byYear'].keys()) == {'2025', '2026'}


def test_monthly_invalid_year():
    resp = _client('manager').get(f'{BASE}/monthly', {'year': 'abcd'})
    assert resp.status_code == 400
    assert resp.json() == {'error': 'invalid_year'}


def test_monthly_invalid_years_list():
    resp = _client('manager').get(f'{BASE}/monthly', {'years': '2025,xx'})
    assert resp.status_code == 400
    assert resp.json() == {'error': 'invalid_year'}


def test_monthly_empty_years_is_invalid():
    # ?years= (пусто) → split → [] → invalid_year (как Express).
    resp = _client('manager').get(f'{BASE}/monthly', {'years': ''})
    assert resp.status_code == 400


def test_monthly_no_params_defaults_current_year():
    resp = _client('manager').get(f'{BASE}/monthly')
    assert resp.status_code == 200
    assert len(resp.json()['years']) == 1
