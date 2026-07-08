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


def deal_computed(deal_id: int) -> dict | None:
    """
    Сделка + вычисляемые поля: имя ученика, направление/цвет, прогресс n/4,
    remaining, balance, days_in_stage. Баланс — через apps.finances.
    """
    from apps.finances.repository import balance_for_direction

    sql = """
        SELECT d.id, d.student_id, d.direction_id, d.cycle_no, d.stage_id,
               d.assignee_id, d.expected_amount, d.next_touch_at, d.reason_code,
               d.stage_entered_at, d.outcome_at, d.created_at,
               s.full_name AS student_name,
               dir.name AS direction_name, dir.color AS direction_color,
               st.key AS stage_key, st.label AS stage_label, st.kind AS stage_kind,
               st.color AS stage_color,
               a.full_name AS assignee_name,
               EXTRACT(DAY FROM now() - d.stage_entered_at)::int AS days_in_stage,
               COALESCE((
                   SELECT SUM(m.lessons_done) FROM group_memberships m
                   JOIN groups g ON g.id = m.group_id
                   WHERE m.student_id = d.student_id AND g.direction_id = d.direction_id
                     AND m.active = true), 0) AS attended
        FROM renewal_deal d
        JOIN students s   ON s.id = d.student_id
        JOIN directions dir ON dir.id = d.direction_id
        JOIN renewal_stage st ON st.id = d.stage_id
        LEFT JOIN accounts a ON a.id = d.assignee_id
        WHERE d.id = %s
    """
    with connection.cursor() as cur:
        cur.execute(sql, [deal_id])
        row = cur.fetchone()
        if row is None:
            return None
        cols = [c[0] for c in cur.description]
        data = dict(zip(cols, row))
    attended = float(data.pop('attended') or 0)
    data['lesson_in_cycle'] = int(attended % cycle.LESSONS_PER_CYCLE) + 1  # 1..4
    data['balance'] = balance_for_direction(data['student_id'], data['direction_id'])
    return data
