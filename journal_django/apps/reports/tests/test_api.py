"""API-тесты раздела «Отчёты»: RBAC + run→status→download через celery result
backend (в eager-режиме .delay() исполняется синхронно). Ничего не хранится в БД."""
from __future__ import annotations

import io

import pytest

pytestmark = pytest.mark.django_db

BASE = '/api/admin/reports'
RUN = f'{BASE}/renewals_month/run'


def test_run_returns_task_id(manager_client):
    resp = manager_client.post(RUN, {'year': 2026, 'month': 5}, format='json')
    assert resp.status_code == 202
    assert resp.json()['task_id']


def test_run_then_status_success(manager_client):
    task_id = manager_client.post(RUN, {'year': 2026, 'month': 5}, format='json').json()['task_id']
    st = manager_client.get(f'{BASE}/status/{task_id}')
    assert st.status_code == 200
    body = st.json()
    assert body['state'] == 'SUCCESS'
    assert body['filename'] == 'renewals_2026-05.xlsx'
    # байты в статусе НЕ отдаём
    assert 'content_b64' not in body


def test_run_then_download_xlsx(manager_client):
    task_id = manager_client.post(RUN, {'year': 2026, 'month': 5}, format='json').json()['task_id']
    resp = manager_client.get(f'{BASE}/download/{task_id}')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp['Content-Type']
    assert 'attachment' in resp['Content-Disposition']
    from openpyxl import load_workbook
    assert load_workbook(io.BytesIO(resp.getvalue())).active.cell(row=2, column=1).value == 'ФИО ученика'


def test_download_unknown_task_not_ready(manager_client):
    # неизвестный task_id → PENDING → «ещё не готов» (400)
    resp = manager_client.get(f'{BASE}/download/00000000-0000-0000-0000-000000000000')
    assert resp.status_code == 400


def test_run_rejects_bad_month(manager_client):
    assert manager_client.post(RUN, {'year': 2026, 'month': 13}, format='json').status_code == 400


def test_run_rejects_future_month(manager_client):
    assert manager_client.post(RUN, {'year': 2999, 'month': 12}, format='json').status_code == 400


def test_run_unknown_report_type_404(manager_client):
    assert manager_client.post(f'{BASE}/no_such/run', {'year': 2026, 'month': 5},
                               format='json').status_code == 404


def test_teacher_forbidden(teacher_client):
    assert teacher_client.post(RUN, {'year': 2026, 'month': 5}, format='json').status_code == 403
    assert teacher_client.get(f'{BASE}/status/x').status_code == 403


def test_anon_unauthorized(anon_client):
    assert anon_client.post(RUN, {'year': 2026, 'month': 5}, format='json').status_code in (401, 403)


def test_admin_allowed(admin_client):
    assert admin_client.post(RUN, {'year': 2026, 'month': 5}, format='json').status_code == 202
