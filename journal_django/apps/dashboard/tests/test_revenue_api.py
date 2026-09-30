"""
GET /api/admin/dashboard/revenue — Revenue / Orders + разбивка по дням и месяцам
(спека docs/superpowers/specs/2026-09-18-revenue-dashboard-design.md).

Тест-БД общая и засеяна боевыми оплатами, поэтому свои оплаты кладём в 2099 год —
там гарантированно пусто, суммы сверяются точно.
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.dashboard import services as svc

pytestmark = pytest.mark.django_db

URL = '/api/admin/dashboard/revenue'


@pytest.fixture(scope='session')
def django_db_setup():
    pass


@pytest.fixture
def student_id():
    with connection.cursor() as cur:
        cur.execute("INSERT INTO students (full_name) VALUES ('__revenue_student__') RETURNING id")
        return cur.fetchone()[0]


def _pay(student_id, paid_at, amount, kind='purchase'):
    lessons = -4 if kind == 'refund' else 4
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, kind, subscriptions_count, lessons_count, "
            "unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s,%s,1,%s,%s,%s,%s,'test')",
            [student_id, kind, lessons, abs(amount), amount, paid_at],
        )


# ---------------------------------------------------------------------------
# Доступ и валидация
# ---------------------------------------------------------------------------

def test_requires_auth(anon_client):
    assert anon_client.get(URL).status_code == 401


def test_teacher_forbidden(teacher_client):
    assert teacher_client.get(URL).status_code == 403


@pytest.mark.parametrize('params', [{'from': '2026-13-01'}, {'to': '2026-02-30'}])
def test_invalid_date(manager_client, params):
    resp = manager_client.get(URL, params)
    assert resp.status_code == 400
    assert resp.json() == {'error': 'invalid_date'}


def test_invalid_range(manager_client):
    resp = manager_client.get(URL, {'from': '2099-02-01', 'to': '2099-01-01'})
    assert resp.status_code == 400
    assert resp.json() == {'error': 'invalid_range'}


# ---------------------------------------------------------------------------
# Расчёт
# ---------------------------------------------------------------------------

def test_totals_daily_and_monthly(admin_client, student_id):
    _pay(student_id, '2099-01-30', 10000)
    _pay(student_id, '2099-01-30', 5000.50)
    _pay(student_id, '2099-02-01', 8000)
    _pay(student_id, '2099-02-02', -3000, kind='refund')
    _pay(student_id, '2099-02-05', 99999)            # за границей периода

    resp = admin_client.get(URL, {'from': '2099-01-30', 'to': '2099-02-02'})
    assert resp.status_code == 200
    body = resp.json()

    assert body['from'] == '2099-01-30' and body['to'] == '2099-02-02'
    # Возврат вычитается из суммы, но заказом не считается.
    assert body['revenue'] == 20000.5
    assert body['orders'] == 3
    assert body['aov'] == 6666.83                           # 20000.50 / 3, до копеек
    assert body['daily'] == [
        {'date': '2099-01-30', 'revenue': 15000.5, 'orders': 2, 'aov': 7500.25},
        # пустой день: сумма и заказы — ноль, средний чек — нет значения
        {'date': '2099-01-31', 'revenue': 0, 'orders': 0, 'aov': None},
        {'date': '2099-02-01', 'revenue': 8000, 'orders': 1, 'aov': 8000},
        # только возврат: заказов нет → AOV не считается
        {'date': '2099-02-02', 'revenue': -3000, 'orders': 0, 'aov': None},
    ]
    assert body['monthly'] == [
        {'month': '2099-01', 'revenue': 15000.5, 'orders': 2, 'aov': 7500.25},
        # AOV = Revenue / Orders: возврат уменьшает средний чек месяца
        {'month': '2099-02', 'revenue': 5000, 'orders': 1, 'aov': 5000},
    ]


def test_aov_null_without_orders(manager_client):
    body = manager_client.get(URL, {'from': '2099-06-01', 'to': '2099-06-02'}).json()
    assert body['orders'] == 0 and body['aov'] is None


def test_bounds_are_inclusive(manager_client, student_id):
    _pay(student_id, '2099-03-01', 100)
    _pay(student_id, '2099-03-10', 200)
    body = manager_client.get(URL, {'from': '2099-03-01', 'to': '2099-03-10'}).json()
    assert body['revenue'] == 300 and body['orders'] == 2
    assert len(body['daily']) == 10


def test_default_period_is_last_three_months(manager_client):
    body = manager_client.get(URL).json()
    assert (body['from'], body['to']) == svc.default_period()
    assert body['daily'][0]['date'] == body['from']
    assert body['daily'][-1]['date'] == body['to']


# ---------------------------------------------------------------------------
# default_period — зажим дня в короткий месяц и переход года
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('today, expected', [
    ('2026-09-18', ('2026-06-18', '2026-09-18')),
    ('2026-05-31', ('2026-02-28', '2026-05-31')),
    ('2028-05-31', ('2028-02-29', '2028-05-31')),
    ('2026-02-15', ('2025-11-15', '2026-02-15')),
])
def test_default_period(today, expected):
    assert svc.default_period(today) == expected
