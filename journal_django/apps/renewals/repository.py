"""Repository renewals: чтение агрегатов из memberships/finances + операции над сделками."""
from __future__ import annotations

from django.db import connection

from apps.renewals import cycle


def active_cycles() -> list[dict]:
    """
    Для каждого активного (ученик × направление) — сколько уроков отработано,
    чтобы движок мог гарантировать сделку текущего цикла.
    """
    sql = """
        SELECT m.student_id,
               g.direction_id,
               COALESCE(SUM(m.lessons_done), 0) AS attended
        FROM group_memberships m
        JOIN groups g ON g.id = m.group_id
        WHERE m.active = true AND g.direction_id IS NOT NULL
        GROUP BY m.student_id, g.direction_id
    """
    with connection.cursor() as cur:
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        r['cycle_no'] = cycle.cycle_no_from_attended(r['attended'])
    return rows
