"""API-тесты чтения renewals: RBAC + форма ответов board/list."""
import pytest

from apps.renewals import engine

BASE = '/api/admin/renewals'


@pytest.mark.django_db
def test_no_cookie_401(anon_client):
    assert anon_client.get(BASE).status_code == 401


@pytest.mark.django_db
def test_teacher_403(teacher_client):
    assert teacher_client.get(BASE).status_code == 403


@pytest.mark.django_db
def test_manager_board_200(manager_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    resp = manager_client.get(f'{BASE}?view=board')
    assert resp.status_code == 200
    assert 'columns' in resp.json()


@pytest.mark.django_db
def test_manager_list_shape(manager_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    resp = manager_client.get(f'{BASE}?view=list&page=1&page_size=10')
    body = resp.json()
    assert set(body) >= {'rows', 'total', 'page', 'page_size'}


@pytest.mark.django_db
def test_invalid_sort_400(manager_client):
    assert manager_client.get(f'{BASE}?view=list&sort_by=hax').status_code == 400


@pytest.mark.django_db
def test_non_numeric_page_400(manager_client):
    """Нечисловой page не должен ронять 500 — валидируем на входе → 400."""
    assert manager_client.get(f'{BASE}?view=list&page=abc').status_code == 400


@pytest.mark.django_db
def test_non_numeric_filter_400(manager_client):
    """Нечисловой числовой фильтр (уходит в SQL как int) → 400, не 500."""
    assert manager_client.get(
        f'{BASE}?view=board&filter[direction_id]=abc').status_code == 400
