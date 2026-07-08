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


def move_deal(deal_id: int, to_stage_id: int, reason_code: str | None,
              author_id: int | None) -> dict | None:
    """Переместить сделку в стадию, записать активность, синхронизировать outcome/enrollment."""
    from django.db import transaction
    from django.utils import timezone
    from apps.renewals.models import RenewalActivity, RenewalDeal, RenewalStage
    from apps.renewals.transitions import assert_allowed, InvalidTransition

    with transaction.atomic():
        deal = RenewalDeal.objects.select_for_update().filter(id=deal_id).first()
        if deal is None:
            return None
        to_stage = RenewalStage.objects.filter(id=to_stage_id, pipeline=deal.pipeline).first()
        if to_stage is None:
            raise InvalidTransition('Стадия не принадлежит воронке сделки')
        from_stage = deal.stage
        assert_allowed(from_kind=from_stage.kind, to_kind=to_stage.kind)

        deal.stage = to_stage
        deal.stage_entered_at = timezone.now()
        if reason_code is not None:
            deal.reason_code = reason_code
        deal.outcome_at = timezone.now() if to_stage.kind in ('won', 'lost') else None
        deal.save(update_fields=['stage', 'stage_entered_at', 'reason_code',
                                 'outcome_at', 'updated_at'])
        RenewalActivity.objects.create(
            deal=deal, kind='stage_change', from_stage=from_stage, to_stage=to_stage,
            author_id=author_id, body=reason_code or '')
        # win-стадия по кнопке (без оплаты) тоже респавнит цикл
        if to_stage.kind == 'won':
            from apps.renewals import engine
            engine.ensure_deal(deal.student_id, deal.direction_id, deal.cycle_no + 1,
                               assignee_id=deal.assignee_id)
    return deal_computed(deal_id)


COLUMN_LIMIT = 50  # карточек на колонку по умолчанию (остальное — «Показать ещё»)


def board(filters: dict | None = None) -> dict:
    """
    Доска: открытые сделки, сгруппированные по стадиям дефолтной воронки.
    Возвращает колонки в порядке sort_order с count/sum_potential и первыми N карточками.
    """
    filters = filters or {}
    from apps.renewals.models import RenewalPipeline, RenewalStage
    pipeline = RenewalPipeline.objects.get(is_default=True)
    stages = list(RenewalStage.objects.filter(pipeline=pipeline).order_by('sort_order'))

    where = ['d.outcome_at IS NULL']
    params: list = []
    if filters.get('assignee_id'):
        where.append('d.assignee_id = %s'); params.append(int(filters['assignee_id']))
    if filters.get('direction_id'):
        where.append('d.direction_id = %s'); params.append(int(filters['direction_id']))
    if filters.get('overdue') == 'true':
        where.append("d.next_touch_at IS NOT NULL AND d.next_touch_at < now()::date")
    where_sql = ' AND '.join(where)

    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT d.stage_id, COUNT(*) AS cnt, COALESCE(SUM(d.expected_amount),0) AS sum_amt
            FROM renewal_deal d WHERE {where_sql} GROUP BY d.stage_id
        """, params)
        agg = {r[0]: {'count': r[1], 'sum_potential': float(r[2])} for r in cur.fetchall()}

    columns = []
    for st in stages:
        stat = agg.get(st.id, {'count': 0, 'sum_potential': 0.0})
        cards = _deals_in_stage(st.id, where_sql, params, COLUMN_LIMIT)
        columns.append({
            'stage_id': st.id, 'key': st.key, 'label': st.label, 'kind': st.kind,
            'color': st.color, 'count': stat['count'],
            'sum_potential': stat['sum_potential'], 'cards': cards,
        })
    return {'columns': columns}


def _deals_in_stage(stage_id: int, where_sql: str, base_params: list, limit: int) -> list[dict]:
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT d.id, s.full_name AS student_name, dir.name AS direction_name,
                   dir.color AS direction_color, d.cycle_no, d.expected_amount,
                   d.next_touch_at, a.full_name AS assignee_name,
                   EXTRACT(DAY FROM now() - d.stage_entered_at)::int AS days_in_stage
            FROM renewal_deal d
            JOIN students s ON s.id = d.student_id
            JOIN directions dir ON dir.id = d.direction_id
            LEFT JOIN accounts a ON a.id = d.assignee_id
            WHERE {where_sql} AND d.stage_id = %s
            ORDER BY d.next_touch_at NULLS LAST, d.stage_entered_at
            LIMIT %s
        """, base_params + [stage_id, limit])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def list_deals(page: int, page_size: int, sort_by: str, sort_dir: str, filters: dict) -> dict:
    """Списочный вид: server-pagination. sort_dir валидируется вызывающим (view)."""
    where = ['1=1']
    params: list = []
    if not filters.get('include_closed'):
        where.append('d.outcome_at IS NULL')
    if filters.get('assignee_id'):
        where.append('d.assignee_id = %s'); params.append(int(filters['assignee_id']))
    if filters.get('direction_id'):
        where.append('d.direction_id = %s'); params.append(int(filters['direction_id']))
    if filters.get('stage_id'):
        where.append('d.stage_id = %s'); params.append(int(filters['stage_id']))
    where_sql = ' AND '.join(where)

    sort_col = {
        'next_touch_at': 'd.next_touch_at', 'stage_entered_at': 'd.stage_entered_at',
        'cycle_no': 'd.cycle_no', 'student_name': 's.full_name',
    }.get(sort_by, 'd.stage_entered_at')
    direction = 'DESC' if sort_dir == 'desc' else 'ASC'

    with connection.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM renewal_deal d WHERE {where_sql}", params)
        total = cur.fetchone()[0]
        cur.execute(f"""
            SELECT d.id, s.full_name AS student_name, dir.name AS direction_name,
                   dir.color AS direction_color, d.cycle_no, st.label AS stage_label,
                   st.kind AS stage_kind, d.next_touch_at, a.full_name AS assignee_name,
                   EXTRACT(DAY FROM now() - d.stage_entered_at)::int AS days_in_stage
            FROM renewal_deal d
            JOIN students s ON s.id = d.student_id
            JOIN directions dir ON dir.id = d.direction_id
            JOIN renewal_stage st ON st.id = d.stage_id
            LEFT JOIN accounts a ON a.id = d.assignee_id
            WHERE {where_sql}
            ORDER BY {sort_col} {direction} NULLS LAST, d.id
            LIMIT %s OFFSET %s
        """, params + [page_size, (page - 1) * page_size])
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {'rows': rows, 'total': total, 'page': page, 'page_size': page_size}
