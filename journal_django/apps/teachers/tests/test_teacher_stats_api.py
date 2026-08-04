"""
E2E тесты для GET /api/admin/teachers/<id>/stats.

RBAC: read-only, доступ у manager/admin/superadmin; teacher и аноним — мимо.
"""
from __future__ import annotations

import pytest

BASE_URL = '/api/admin/teachers'


def _url(teacher_id: int, month: str | None = None) -> str:
    suffix = f'?month={month}' if month else ''
    return f'{BASE_URL}/{teacher_id}/stats{suffix}'


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_anonymous_returns_401(anon_client, stats_teacher):
    assert anon_client.get(_url(stats_teacher)).status_code == 401


@pytest.mark.django_db
def test_teacher_role_returns_403(teacher_client, stats_teacher):
    assert teacher_client.get(_url(stats_teacher)).status_code == 403


@pytest.mark.django_db
def test_manager_returns_200(manager_client, stats_teacher):
    assert manager_client.get(_url(stats_teacher)).status_code == 200


@pytest.mark.django_db
def test_admin_returns_200(admin_client, stats_teacher):
    assert admin_client.get(_url(stats_teacher)).status_code == 200


# ---------------------------------------------------------------------------
# Контракт
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_response_shape(admin_client, stats_teacher, make_group, make_lesson):
    group = make_group('__api_stats_group__')
    make_lesson(group, '2026-07-06')

    body = admin_client.get(_url(stats_teacher, '2026-07')).json()

    assert body['month'] == '2026-07'
    assert body['total'] == {'sessions': 1, 'minutes': 90, 'substitutions': 0}
    assert body['last_lesson_date'] == '2026-07-06'
    assert len(body['monthly']) == 12
    assert len(body['by_direction']) == 1
    assert len(body['by_duration']) == 1
    assert any(r['group_id'] == group for r in body['group_progress'])


@pytest.mark.django_db
def test_group_progress_lessons_done_wire_format(admin_client, stats_teacher,
                                                  make_group, make_lesson):
    """
    lessons_done на проводе — строка '2.0', НЕ число 2: DateSafeJSONRenderer
    сериализует Decimal через str(), а Cast в group_progress фиксирует scale
    numeric(6,1). Без Cast для двух целых занятий это была бы строка '2'.
    """
    group = make_group('__api_stats_scale__', duration=90)
    make_lesson(group, '2026-07-06', duration=90)
    make_lesson(group, '2026-07-13', duration=90)

    body = admin_client.get(_url(stats_teacher, '2026-07')).json()

    row = next(r for r in body['group_progress'] if r['group_id'] == group)
    assert row['lessons_done'] == '2.0'


@pytest.mark.django_db
def test_month_defaults_to_current(admin_client, stats_teacher):
    from apps.core.utils.dates import msk_now

    body = admin_client.get(_url(stats_teacher)).json()

    assert body['month'] == msk_now().strftime('%Y-%m')


@pytest.mark.django_db
@pytest.mark.parametrize('bad', [
    '2026-13', '2026', 'июль', '2026-7', '2026-00',
    # Крайние годы: на них month_bounds считает date(10000,1,1) / date(0,...)
    # и падает ValueError — 400 обязан отсечь их до этого, а не отдать 500.
    '9999-12', '0001-01',
])
def test_invalid_month_returns_400(admin_client, stats_teacher, bad):
    resp = admin_client.get(_url(stats_teacher, bad))

    assert resp.status_code == 400
    assert 'error' in resp.json()


@pytest.mark.django_db
def test_unknown_teacher_returns_404(admin_client):
    resp = admin_client.get(_url(999999999))

    assert resp.status_code == 404
    assert resp.json() == {'error': 'Not found'}


@pytest.mark.django_db
def test_archived_teacher_still_returns_stats(admin_client, stats_teacher, make_group,
                                              make_lesson):
    """Архивный преподаватель — не 404: его карточку открывают, чтобы посмотреть,
    сколько он отработал до архивации."""
    from django.db import connection
    group = make_group('__api_stats_arch__')
    make_lesson(group, '2026-07-06')
    with connection.cursor() as cur:
        cur.execute('UPDATE teachers SET active = false WHERE id = %s', [stats_teacher])

    resp = admin_client.get(_url(stats_teacher, '2026-07'))

    assert resp.status_code == 200
    assert resp.json()['total']['sessions'] == 1
