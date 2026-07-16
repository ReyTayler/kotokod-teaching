"""
Golden-тесты compute_fifo — дословный порт services/fifo.test.js на Decimal.

Каждый кейс сверяет Decimal-в-Decimal до копейки. Плюс граничные случаи из
брифа 02: half-lesson, перерасход, NULL-партий нет, переход месяца, частичное гашение.

compute_fifo — чистая функция, БД не нужна (нет pytest.mark.django_db).
"""
from __future__ import annotations

from decimal import Decimal

from apps.finances.fifo import compute_fifo

MS = '2026-06-01'
ME = '2026-07-01'


def _lessons(n, date):
    return [{'units': 1, 'date': date} for _ in range(n)]


def _D(x):
    return Decimal(str(x))


# ---------------------------------------------------------------------------
# Golden из fifo.test.js
# ---------------------------------------------------------------------------

def test_two_lots_across_month_boundary():
    lots = [
        {'lessons': 4, 'price_per_lesson': _D(500)},
        {'lessons': 4, 'price_per_lesson': _D(450)},
    ]
    cons = _lessons(3, '2026-05-10') + _lessons(4, '2026-06-10')
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_total'] == _D('3350.00')
    assert r['worked_off_month'] == _D('1850.00')
    assert r['remaining_value'] == _D('450.00')
    assert r['over_consumed_lessons'] == _D('0.00')


def test_invariant_total_paid_equals_worked_plus_remaining():
    lots = [
        {'lessons': 4, 'price_per_lesson': _D(500)},
        {'lessons': 4, 'price_per_lesson': _D(450)},
    ]
    cons = _lessons(5, '2026-06-10')
    r = compute_fifo(lots, cons, MS, ME)
    total_paid = _D(4 * 500 + 4 * 450)
    assert r['worked_off_total'] + r['remaining_value'] == total_paid


def test_half_lesson_partial():
    lots = [{'lessons': 4, 'price_per_lesson': _D(500)}]
    cons = [{'units': 0.5, 'date': '2026-06-10'}]
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_month'] == _D('250.00')
    assert r['remaining_value'] == _D('1750.00')


def test_over_consumed_no_price():
    lots = [{'lessons': 4, 'price_per_lesson': _D(500)}]
    cons = _lessons(6, '2026-06-10')
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_total'] == _D('2000.00')
    assert r['over_consumed_lessons'] == _D('2.00')
    assert r['remaining_value'] == _D('0.00')


def test_no_lots_all_over_consumed():
    r = compute_fifo([], _lessons(2, '2026-06-10'), MS, ME)
    assert r['worked_off_total'] == _D('0.00')
    assert r['over_consumed_lessons'] == _D('2.00')
    assert r['remaining_value'] == _D('0.00')


def test_no_consumption_all_remaining():
    lots = [{'lessons': 4, 'price_per_lesson': _D(500)}]
    r = compute_fifo(lots, [], MS, ME)
    assert r['worked_off_total'] == _D('0.00')
    assert r['remaining_value'] == _D('2000.00')


def test_worked_off_by_month():
    lots = [
        {'lessons': 4, 'price_per_lesson': _D(500)},
        {'lessons': 4, 'price_per_lesson': _D(450)},
    ]
    cons = _lessons(3, '2026-05-10') + _lessons(4, '2026-06-10')
    r = compute_fifo(lots, cons, '2026-06-01', '2026-07-01')
    assert r['worked_off_by_month']['2026-05'] == _D('1500.00')
    assert r['worked_off_by_month']['2026-06'] == _D('1850.00')


# ---------------------------------------------------------------------------
# Доп. граничные случаи (бриф 02)
# ---------------------------------------------------------------------------

def test_dec_to_jan_month_boundary():
    # Переход декабрь→январь: month_end эксклюзивный = '2026-01-01'.
    lots = [{'lessons': 4, 'price_per_lesson': _D(500)}]
    cons = _lessons(2, '2025-12-31') + _lessons(2, '2026-01-01')
    r = compute_fifo(lots, cons, '2025-12-01', '2026-01-01')
    # Только декабрьские уроки попадают в worked_off_month.
    assert r['worked_off_month'] == _D('1000.00')
    assert r['worked_off_total'] == _D('2000.00')
    assert r['worked_off_by_month']['2025-12'] == _D('1000.00')
    assert r['worked_off_by_month']['2026-01'] == _D('1000.00')


def test_fractional_price_per_lesson_kopeck_precision():
    # total_amount=6290 на 12 уроков → 524.1666... за урок. 12 уроков списано →
    # ровно 6290.00 (Decimal-точность, без накопленной float-ошибки).
    price = _D(6290) / _D(12)
    lots = [{'lessons': 12, 'price_per_lesson': price}]
    cons = _lessons(12, '2026-06-10')
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_total'] == _D('6290.00')
    assert r['remaining_value'] == _D('0.00')


def test_partial_lot_consumption():
    # Частичное гашение партии: 2 из 4 уроков.
    lots = [{'lessons': 4, 'price_per_lesson': _D(500)}]
    cons = _lessons(2, '2026-06-10')
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_total'] == _D('1000.00')
    assert r['remaining_value'] == _D('1000.00')


def test_worked_off_by_direction():
    lots = [
        {'lessons': 4, 'price_per_lesson': _D(500)},
        {'lessons': 4, 'price_per_lesson': _D(450)},
    ]
    cons = [
        {'units': 1, 'date': '2026-06-10', 'direction_id': 1},
        {'units': 1, 'date': '2026-06-11', 'direction_id': 1},
        {'units': 1, 'date': '2026-06-12', 'direction_id': 2},
    ]
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_direction'][1] == _D('1000.00')
    assert r['worked_off_by_direction'][2] == _D('500.00')


def test_worked_off_by_direction_absent_key_is_ignored():
    # Golden-кейсы выше не передают direction_id — не должно падать, просто {}.
    lots = [{'lessons': 4, 'price_per_lesson': _D(500)}]
    cons = _lessons(2, '2026-06-10')
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_direction'] == {}


def test_worked_off_unit_prices_month_single_lot():
    lots = [{'lessons': 4, 'price_per_lesson': _D(500)}]
    cons = _lessons(2, '2026-06-10')
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_unit_prices_month'] == [_D('500.00')]


def test_worked_off_unit_prices_month_two_lots_crossed_within_month():
    # Партия A (500) на 3 урока заканчивается внутри месяца, продолжение — партия B (450).
    lots = [
        {'lessons': 3, 'price_per_lesson': _D(500)},
        {'lessons': 4, 'price_per_lesson': _D(450)},
    ]
    cons = _lessons(5, '2026-06-10')
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_unit_prices_month'] == [_D('500.00'), _D('450.00')]


def test_worked_off_unit_prices_month_excludes_outside_month():
    lots = [{'lessons': 4, 'price_per_lesson': _D(500)}]
    cons = _lessons(2, '2026-05-10')  # ДО месяца [MS, ME)
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_unit_prices_month'] == []


def test_worked_off_unit_prices_month_excludes_refund_and_over_consumption():
    lots = [{'lessons': 2, 'price_per_lesson': _D(500)}]
    cons = _lessons(4, '2026-06-10') + [  # 2 реальных + 2 сверх лимита (без партии)
        {'units': 1, 'date': '2026-06-15', 'refund': True},
    ]
    r = compute_fifo(lots, cons, MS, ME)
    # Только цена реально списанной партии; ни возврат, ни перерасход не добавляют цену.
    assert r['worked_off_unit_prices_month'] == [_D('500.00')]


def test_refund_consumption_zeroes_remaining_without_revenue():
    from decimal import Decimal
    from apps.finances.fifo import compute_fifo
    lots = [{'lessons': 4, 'price_per_lesson': Decimal('1000')}]
    cons = [
        {'units': Decimal('1'), 'date': '2026-01-05', 'direction_id': None},
        {'units': Decimal('3'), 'date': '2026-01-31', 'direction_id': None, 'refund': True},
    ]
    r = compute_fifo(lots, cons, '2026-01-01', '2026-02-01')
    assert r['remaining_value'] == Decimal('0.00')      # хвост погашен возвратом
    assert r['worked_off_total'] == Decimal('1000.00')  # только 1 реальный урок
