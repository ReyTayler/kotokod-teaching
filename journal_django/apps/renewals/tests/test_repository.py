"""Тесты repository.board() и repository.list_deals()."""
import pytest

from apps.renewals import engine, repository


@pytest.mark.django_db
def test_board_groups_open_deals(make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, cycle_no=1)
    board = repository.board()
    progress_col = next(c for c in board['columns'] if c['kind'] == 'progress')
    assert progress_col['count'] >= 1
    assert any(card['student_name'] == '__renew_test_student__' for card in progress_col['cards'])


@pytest.mark.django_db
def test_list_paginates(make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, cycle_no=1)
    res = repository.list_deals(page=1, page_size=10, sort_by='cycle_no', sort_dir='asc', filters={})
    assert res['total'] >= 1
    assert res['page'] == 1


@pytest.mark.django_db
def test_column_cards_offset(make_student):
    """«Показать ещё»: offset поверх COLUMN_LIMIT, та же сортировка, что и в board()."""
    deal_ids = []
    for i in range(3):
        sid = make_student(f'__renew_test_student_{i}__')
        deal = engine.ensure_deal(sid, cycle_no=1)
        deal_ids.append(deal.id)

    from apps.renewals.models import RenewalDeal
    stage_id = RenewalDeal.objects.get(id=deal_ids[0]).stage_id

    flt = {'student': '__renew_test_student_'}
    all_cards = repository.column_cards(stage_id, offset=0, filters=flt)['cards']
    ids_in_order = [c['id'] for c in all_cards if c['id'] in deal_ids]
    assert len(ids_in_order) == 3

    offset_cards = repository.column_cards(stage_id, offset=1, filters=flt)['cards']
    ids_from_offset = [c['id'] for c in offset_cards if c['id'] in deal_ids]
    assert ids_from_offset == ids_in_order[1:]
