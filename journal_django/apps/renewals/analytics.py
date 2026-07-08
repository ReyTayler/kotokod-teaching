"""Аналитика продлений: воронка по стадиям + сводные KPI."""
from __future__ import annotations

from django.db import connection


def funnel(group_by: str | None = None) -> dict:
    """
    Распределение открытых сделок по стадиям + renewal rate за 30 дней
    (won / (won + lost) среди закрытых).
    """
    with connection.cursor() as cur:
        cur.execute("""
            SELECT st.key, st.label, st.kind, COUNT(*) AS cnt,
                   COALESCE(SUM(d.expected_amount),0) AS sum_amt
            FROM renewal_deal d JOIN renewal_stage st ON st.id = d.stage_id
            WHERE d.outcome_at IS NULL
            GROUP BY st.key, st.label, st.kind, st.sort_order
            ORDER BY st.sort_order
        """)
        cols = [c[0] for c in cur.description]
        stages = [dict(zip(cols, r)) for r in cur.fetchall()]

        cur.execute("""
            SELECT st.kind, COUNT(*) FROM renewal_deal d
            JOIN renewal_stage st ON st.id = d.stage_id
            WHERE d.outcome_at IS NOT NULL AND d.outcome_at >= now() - interval '30 days'
            GROUP BY st.kind
        """)
        closed = {r[0]: r[1] for r in cur.fetchall()}
    won, lost = closed.get('won', 0), closed.get('lost', 0)
    rate = round(won / (won + lost) * 100, 1) if (won + lost) else None
    return {'stages': stages, 'renewal_rate_30d': rate, 'won_30d': won, 'lost_30d': lost}
