"""
DashboardService — порт services/repo/dashboard.js (getDashboard, getMonthlyFinance).

FIFO через единый apps/finances (fifo_inputs + compute_fifo) — не дублируем.
Денежные значения отдаются как JSON-числа (js_number: целое→int, дробное→float),
ровно как Express (Number + JSON.stringify), а не строкой. Округление до 2 знаков —
js_round2 (Math.round(x*100)/100), не round_kopecks.

ИЗВЕСТНОЕ РАСХОЖДЕНИЕ (решение пользователя): worked_off в getMonthlyFinance и
worked_off_month/deferred_total в getDashboard суммируют точные Decimal из FIFO,
тогда как Express копит во float — отсюда ≤1 копейка разницы в нескольких
ИСТОРИЧЕСКИХ ячейках. См. apps/finances/fifo.py и память project_fifo_decimal_decision.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Optional

from apps.core.utils.dates import msk_month_range_triple
from apps.core.utils.decimal import js_number, js_round2, to_decimal
from apps.dashboard import repository
from apps.finances.fifo import compute_fifo
from apps.finances.repository import fifo_inputs

_ZERO = Decimal('0')


def _add_day(d: str) -> str:
    """d + 1 день (UTC), 'YYYY-MM-DD'. Порт dashboard.js _addDay (для эксклюзивного to)."""
    return (datetime.date.fromisoformat(d) + datetime.timedelta(days=1)).strftime('%Y-%m-%d')


def get_dashboard(from_: Optional[str] = None, to: Optional[str] = None) -> dict:
    """
    Сводка: revenue_month, worked_off_month, carryover, deferred_total, top-долги.

    Порт dashboard.js getDashboard. Период [period_start, period_end):
    с from/to — заданный диапазон (to эксклюзивно через _add_day), иначе текущий МСК-месяц.
    """
    month, month_start, month_end = msk_month_range_triple()
    has_range = bool(from_ or to)
    period_start = (from_ or '0001-01-01') if has_range else month_start
    period_end = (_add_day(to) if to else '9999-12-31') if has_range else month_end

    revenue_month = js_round2(repository.revenue_for_period(period_start, period_end))

    inp = fifo_inputs()
    lots_by_key = inp['lots_by_key']
    cons_by_key = inp['cons_by_key']
    purchased_by_key = inp['purchased_by_key']
    consumed_by_key = inp['consumed_by_key']

    worked_off_month = _ZERO
    deferred_total = _ZERO
    debt_keys: list[dict] = []
    for key in inp['keys']:
        fifo = compute_fifo(
            lots_by_key.get(key, []), cons_by_key.get(key, []), period_start, period_end
        )
        worked_off_month += fifo['worked_off_month']
        deferred_total += fifo['remaining_value']
        balance = to_decimal(purchased_by_key.get(key, 0)) - to_decimal(consumed_by_key.get(key, 0))
        if balance < 0:
            sid, did = (int(x) for x in key.split(':'))
            debt_keys.append({
                'student_id': sid,
                'direction_id': did,
                'balance': js_round2(balance),
            })

    worked_off_month = js_round2(worked_off_month)
    deferred_total = js_round2(deferred_total)
    carryover_month = js_round2(revenue_month - worked_off_month)

    # Стабильная сортировка по возрастанию баланса (insertion order — тай-брейк, как в JS).
    debt_keys.sort(key=lambda d: d['balance'])
    debts_total = len(debt_keys)
    top_debts = debt_keys[:8]

    student_ids = list(dict.fromkeys(d['student_id'] for d in top_debts))
    direction_ids = list(dict.fromkeys(d['direction_id'] for d in top_debts))
    s_map = repository.students_names(student_ids)
    d_map = repository.directions_info(direction_ids)

    debts = [{
        'student_id': d['student_id'],
        'student_name': s_map.get(d['student_id'], '—'),
        'direction_id': d['direction_id'],
        'direction_name': d_map[d['direction_id']]['name'] if d['direction_id'] in d_map else '—',
        'direction_color': d_map[d['direction_id']]['color'] if d['direction_id'] in d_map else None,
        'balance': js_number(d['balance']),
    } for d in top_debts]

    return {
        'month': month,
        'from': from_ or None,
        'to': to or None,
        'revenue_month': js_number(revenue_month),
        'worked_off_month': js_number(worked_off_month),
        'carryover_month': js_number(carryover_month),
        'deferred_total': js_number(deferred_total),
        'debts': debts,
        'debts_total': debts_total,
    }


def get_monthly_finance(years: Optional[list[int]] = None) -> dict:
    """
    Year-over-year помесячно: revenue (по paid_at) + worked_off (FIFO по месяцу урока).

    Порт dashboard.js getMonthlyFinance. years — список запрошенных лет (или None → текущий).
    """
    cur_year = int(msk_month_range_triple()[0][:4])

    raw_years = years if years is not None else [cur_year]
    req_years = sorted({
        y for y in (int(x) for x in raw_years) if 1970 <= y <= 9999
    })[-6:]
    if not req_years:
        req_years = [cur_year]

    available_years = [yy for yy in repository.distinct_source_years() if 2015 <= yy <= cur_year + 1]
    for y in req_years:
        if y not in available_years:
            available_years.append(y)
    available_years.sort()

    min_y, max_y = req_years[0], req_years[-1]
    rev_by_ym = repository.revenue_by_year_month(min_y, max_y)

    inp = fifo_inputs()
    lots_by_key = inp['lots_by_key']
    cons_by_key = inp['cons_by_key']
    worked_by_ym: dict[str, Decimal] = {}
    for key in inp['keys']:
        fifo = compute_fifo(
            lots_by_key.get(key, []), cons_by_key.get(key, []), '0001-01-01', '9999-12-31'
        )
        for ym, val in fifo['worked_off_by_month'].items():
            worked_by_ym[ym] = worked_by_ym.get(ym, _ZERO) + val

    by_year: dict[int, list] = {}
    for y in req_years:
        arr = []
        for m in range(1, 13):
            ym = f'{y}-{m:02d}'
            rev = rev_by_ym.get(ym)
            worked = worked_by_ym.get(ym)
            arr.append({
                'month': m,
                'revenue': js_number(js_round2(rev if rev is not None else _ZERO)),
                'worked_off': js_number(js_round2(worked if worked is not None else _ZERO)),
            })
        by_year[y] = arr

    return {'years': req_years, 'available_years': available_years, 'byYear': by_year}
