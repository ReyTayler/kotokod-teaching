"""Тесты repository.board() и repository.list_deals()."""
import pytest

from apps.renewals import engine, repository


@pytest.mark.django_db
def test_board_groups_open_deals(make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    board = repository.board()
    progress_col = next(c for c in board['columns'] if c['kind'] == 'progress')
    assert progress_col['count'] >= 1
    assert any(card['student_name'] == '__renew_test_student__' for card in progress_col['cards'])


@pytest.mark.django_db
def test_list_paginates(make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    res = repository.list_deals(page=1, page_size=10, sort_by='cycle_no', sort_dir='asc', filters={})
    assert res['total'] >= 1
    assert res['page'] == 1
