"""Repository renewals: чтение агрегатов из memberships/finances + операции над сделками."""
from __future__ import annotations

from django.db import connection

from apps.renewals import cycle


def _directions_agg(student_col: str) -> str:
    """json-массив активных направлений ученика [{name, color}] для SELECT."""
    return f"""
    COALESCE((
        SELECT json_agg(json_build_object('name', x.name, 'color', x.color)
                        ORDER BY x.name)
        FROM (SELECT DISTINCT dd.name, dd.color
              FROM group_memberships mm
              JOIN groups gg ON gg.id = mm.group_id
              JOIN directions dd ON dd.id = gg.direction_id
              WHERE mm.student_id = {student_col} AND mm.active = true) x
    ), '[]'::json)
"""


DIRECTIONS_AGG_SQL = _directions_agg('d.student_id')


def students_without_deal() -> list[dict]:
    """
    Сводка «Ученики без сделок»: активный membership есть, открытой сделки нет.
    Для каждого — направления, суммарно посещено, расчётный цикл и флаг долга.
    Из неё менеджер вручную создаёт сделку (POST /api/admin/renewals).
    """
    from apps.finances.repository import balances_for_students

    sql = f"""
        SELECT s.id AS student_id, s.full_name AS student_name,
               {_directions_agg('s.id')} AS directions,
               COALESCE((
                   SELECT SUM(CASE WHEN l.lesson_duration_minutes = 45
                                   THEN 0.5 ELSE 1 END)
                   FROM lesson_attendance la
                   JOIN lessons l ON l.id = la.lesson_id
                   WHERE la.student_id = s.id AND la.present = true
               ), 0) AS attended
        FROM students s
        WHERE EXISTS (SELECT 1 FROM group_memberships m
                      WHERE m.student_id = s.id AND m.active = true)
          AND NOT EXISTS (SELECT 1 FROM renewal_deal d
                          WHERE d.student_id = s.id AND d.outcome_at IS NULL)
        ORDER BY s.full_name
    """
    with connection.cursor() as cur:
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    balances = balances_for_students([r['student_id'] for r in rows])
    for r in rows:
        r['attended'] = float(r['attended'])
        r['cycle_no'] = cycle.cycle_no_from_attended(r['attended'])
        r['debt'] = float(balances.get(r['student_id'], 0)) < 0
    return rows


def deal_computed(deal_id: int) -> dict | None:
    """
    Сделка + вычисляемые поля: имя ученика, активные направления (справочно),
    прогресс n/4 от общей истории, balance, days_in_stage. Баланс — apps.finances.
    """
    from apps.finances.repository import balance_for_student

    sql = f"""
        SELECT d.id, d.student_id, d.cycle_no, d.stage_id,
               d.assignee_id, d.next_touch_at, d.reason_code,
               d.due_at, d.stage_entered_at, d.outcome_at, d.created_at,
               s.full_name AS student_name,
               {DIRECTIONS_AGG_SQL} AS directions,
               st.key AS stage_key, st.label AS stage_label, st.kind AS stage_kind,
               st.color AS stage_color,
               a.full_name AS assignee_name,
               EXTRACT(DAY FROM now() - d.stage_entered_at)::int AS days_in_stage,
               COALESCE((
                   SELECT SUM(CASE WHEN l.lesson_duration_minutes = 45
                                   THEN 0.5 ELSE 1 END)
                   FROM lesson_attendance la
                   JOIN lessons l ON l.id = la.lesson_id
                   WHERE la.student_id = d.student_id AND la.present = true), 0) AS attended
        FROM renewal_deal d
        JOIN students s   ON s.id = d.student_id
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
    # Прогресс от номера цикла сделки (не attended % 4): у сделки цикла N свои
    # уроки (N−1)×4+1 .. N×4, иначе после 4-го урока прогресс «заворачивался».
    into = attended - (data['cycle_no'] - 1) * cycle.LESSONS_PER_CYCLE
    # 1..4, где 1 = «Не было урока цикла» (into<=0), 2..4 = «Урок 1..3» отработаны
    # (into=1..3). Текст на фронте (RenewalDrawer) разворачивает это в -1 при выводе.
    data['lesson_in_cycle'] = min(max(int(into), 0), cycle.LESSONS_PER_CYCLE - 1) + 1
    data['cycle_completed'] = into >= cycle.LESSONS_PER_CYCLE
    data['balance'] = balance_for_student(data['student_id'])
    data['debt'] = float(data['balance']) < 0
    return data


def move_deal(deal_id: int, to_stage_id: int, reason_code: str | None,
              author_id: int | None) -> dict | None:
    """Переместить сделку в стадию, записать активность, синхронизировать outcome/enrollment."""
    from django.db import transaction
    from django.utils import timezone
    from apps.renewals import engine
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
        assert_allowed(from_kind=from_stage.kind, to_kind=to_stage.kind,
                       from_is_auto=from_stage.is_auto, to_is_auto=to_stage.is_auto,
                       cycle_completed=engine.cycle_completed(deal))

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
        # Менеджер вручную подтвердил продление — единственный путь закрытия
        # сделки как «Продлён» (оплата больше не закрывает сделку сама, см.
        # signals.py). Спавним следующий цикл, перешагивая занятые закрытые
        # номера (переоткрытия/возвраты могли оставить «дыру»).
        if to_stage.kind == 'won':
            next_cycle = engine.next_open_cycle_no(deal.student_id, deal.cycle_no + 1)
            engine.ensure_deal(deal.student_id, next_cycle)
    return deal_computed(deal_id)


def patch_deal(deal_id: int, data: dict) -> dict | None:
    from django.utils import timezone
    from apps.renewals.models import RenewalDeal
    fields = {}
    for k in ('assignee_id', 'next_touch_at', 'reason_code'):
        if k in data:
            fields[k] = data[k]
    if not fields:
        return deal_computed(deal_id)
    # .update() не триггерит auto_now — обновляем updated_at вручную (как в move_deal).
    fields['updated_at'] = timezone.now()
    updated = RenewalDeal.objects.filter(id=deal_id).update(**fields)
    return deal_computed(deal_id) if updated else None


def add_comment(deal_id: int, body: str, author_id: int | None) -> dict | None:
    from apps.renewals.models import RenewalActivity, RenewalDeal
    if not RenewalDeal.objects.filter(id=deal_id).exists():
        return None
    act = RenewalActivity.objects.create(
        deal_id=deal_id, kind='comment', body=body, author_id=author_id)
    return {'id': act.id, 'created_at': act.created_at}


def list_activity(deal_id: int) -> list[dict]:
    with connection.cursor() as cur:
        cur.execute("""
            SELECT ra.id, ra.kind, ra.body, ra.created_at,
                   fs.label AS from_label, ts.label AS to_label,
                   a.full_name AS author_name, ra.payment_id
            FROM renewal_activity ra
            LEFT JOIN renewal_stage fs ON fs.id = ra.from_stage_id
            LEFT JOIN renewal_stage ts ON ts.id = ra.to_stage_id
            LEFT JOIN accounts a ON a.id = ra.author_id
            WHERE ra.deal_id = %s ORDER BY ra.created_at DESC
        """, [deal_id])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


COLUMN_LIMIT = 50  # карточек на колонку по умолчанию (остальное — «Показать ещё»)


def _board_where(filters: dict) -> tuple[str, list]:
    """Общий WHERE для board()/column_cards() — открытые сделки + опциональные фильтры."""
    where = ['d.outcome_at IS NULL']
    params: list = []
    if filters.get('assignee_id'):
        where.append('d.assignee_id = %s'); params.append(int(filters['assignee_id']))
    if filters.get('direction_id'):
        # Направление — атрибут ученика (активные membership), не сделки.
        where.append("""EXISTS (
            SELECT 1 FROM group_memberships fm
            JOIN groups fg ON fg.id = fm.group_id
            WHERE fm.student_id = d.student_id AND fm.active = true
              AND fg.direction_id = %s)""")
        params.append(int(filters['direction_id']))
    if filters.get('overdue') == 'true':
        where.append("d.next_touch_at IS NOT NULL AND d.next_touch_at < now()::date")
    if filters.get('student'):
        # Поиск по имени ученика (per-column search в канбане). ILIKE — регистр
        # и раскладку не различаем; % экранировать не нужно (параметризованный %s).
        where.append('s.full_name ILIKE %s'); params.append(f"%{filters['student']}%")
    return ' AND '.join(where), params


def board(filters: dict | None = None) -> dict:
    """
    Доска: открытые сделки, сгруппированные по стадиям дефолтной воронки.
    Возвращает колонки в порядке sort_order с count и первыми N карточками.
    Остальные — через column_cards() («Показать ещё»).
    """
    filters = filters or {}
    from apps.renewals.models import RenewalPipeline, RenewalStage
    pipeline = RenewalPipeline.objects.get(is_default=True)
    # Терминальные (won/lost) колонки на доске не показываем: открытых сделок в них
    # не бывает (outcome_at ставится при закрытии), закрытие — через зоны drag'а,
    # архив — списочный вид с фильтром «Показать закрытые».
    stages = list(RenewalStage.objects.filter(pipeline=pipeline)
                  .exclude(kind__in=('won', 'lost')).order_by('sort_order'))

    where_sql, params = _board_where(filters)

    with connection.cursor() as cur:
        # JOIN students — на случай student-фильтра в where_sql (доска его штатно
        # не передаёт, но join 1:1 по FK безвреден и держит _board_where консистентным).
        cur.execute(f"""
            SELECT d.stage_id, COUNT(*) AS cnt
            FROM renewal_deal d
            JOIN students s ON s.id = d.student_id
            WHERE {where_sql} GROUP BY d.stage_id
        """, params)
        counts = {r[0]: r[1] for r in cur.fetchall()}

    columns = []
    for st in stages:
        cards = _deals_in_stage(st.id, where_sql, params, COLUMN_LIMIT, offset=0)
        columns.append({
            'stage_id': st.id, 'key': st.key, 'label': st.label, 'kind': st.kind,
            'color': st.color, 'count': counts.get(st.id, 0), 'cards': cards,
        })
    return {'columns': columns}


def _deals_in_stage(stage_id: int, where_sql: str, base_params: list,
                     limit: int, offset: int) -> list[dict]:
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT d.id, d.student_id, s.full_name AS student_name,
                   {DIRECTIONS_AGG_SQL} AS directions,
                   d.cycle_no,
                   d.next_touch_at, d.due_at, a.full_name AS assignee_name,
                   EXTRACT(DAY FROM now() - d.stage_entered_at)::int AS days_in_stage,
                   COALESCE((
                       SELECT SUM(CASE WHEN l.lesson_duration_minutes = 45
                                       THEN 0.5 ELSE 1 END)
                       FROM lesson_attendance la
                       JOIN lessons l ON l.id = la.lesson_id
                       WHERE la.student_id = d.student_id AND la.present = true), 0) AS attended
            FROM renewal_deal d
            JOIN students s ON s.id = d.student_id
            LEFT JOIN accounts a ON a.id = d.assignee_id
            WHERE {where_sql} AND d.stage_id = %s
            ORDER BY d.next_touch_at NULLS LAST, d.stage_entered_at
            LIMIT %s OFFSET %s
        """, base_params + [stage_id, limit, offset])
        cols = [c[0] for c in cur.description]
        cards = [dict(zip(cols, r)) for r in cur.fetchall()]
    # cycle_completed нужен фронту, чтобы во время drag'а скрыть зону
    # «Продлён» для сделок с незавершённым циклом (move всё равно ответит
    # 409, но так карточку туда даже не пытаются бросить, см. move_deal).
    for c in cards:
        attended = float(c.pop('attended') or 0)
        into = attended - (c['cycle_no'] - 1) * cycle.LESSONS_PER_CYCLE
        c['cycle_completed'] = into >= cycle.LESSONS_PER_CYCLE
    return _annotate_debt(cards)


def _annotate_debt(cards: list[dict]) -> list[dict]:
    """Бейдж долга (balance < 0) — батчем через apps.finances, без N+1."""
    from apps.finances.repository import balances_for_students
    ids = list({c['student_id'] for c in cards})
    if not ids:
        return cards
    balances = balances_for_students(ids)
    for c in cards:
        c['debt'] = float(balances.get(c['student_id'], 0)) < 0
    return cards


def column_cards(stage_id: int, offset: int, filters: dict | None = None) -> dict:
    """
    Карточки одной колонки канбана: count (с учётом фильтров) + страница карточек
    от offset. Та же выборка/сортировка, что и в board(). Используется для
    «Показать ещё» и для поиска по имени ученика внутри колонки (filter[student]).
    count нужен, чтобы фронт знал, есть ли ещё совпадения (кнопка «Показать ещё»).
    """
    where_sql, params = _board_where(filters or {})
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT COUNT(*) FROM renewal_deal d
            JOIN students s ON s.id = d.student_id
            WHERE {where_sql} AND d.stage_id = %s
        """, params + [stage_id])
        count = cur.fetchone()[0]
    cards = _deals_in_stage(stage_id, where_sql, params, COLUMN_LIMIT, offset)
    return {'count': count, 'cards': cards}


def list_stages() -> list[dict]:
    from apps.renewals.models import RenewalPipeline, RenewalStage
    pipe = RenewalPipeline.objects.get(is_default=True)
    return list(RenewalStage.objects.filter(pipeline=pipe).order_by('sort_order')
                .values('id', 'key', 'label', 'color', 'kind', 'is_auto', 'sort_order'))


def create_stage(data: dict) -> dict:
    from apps.renewals.models import RenewalPipeline, RenewalStage
    from django.db.models import Max
    pipe = RenewalPipeline.objects.get(is_default=True)
    next_order = (RenewalStage.objects.filter(pipeline=pipe)
                  .aggregate(m=Max('sort_order'))['m'] or 0) + 1
    base_key = data.get('key') or _slugify_key(data['label'])
    key = _unique_stage_key(pipe, base_key)
    st = RenewalStage.objects.create(
        pipeline=pipe, key=key, label=data['label'], color=data.get('color'),
        kind=data['kind'], sort_order=next_order, is_auto=False)
    return _stage_dict(st)


def update_stage(stage_id: int, data: dict) -> dict | None:
    from apps.renewals.models import RenewalStage
    st = RenewalStage.objects.filter(id=stage_id).first()
    if st is None:
        return None
    for k in ('label', 'color', 'kind'):
        if k in data:
            setattr(st, k, data[k])
    st.save()
    return _stage_dict(st)


def delete_stage(stage_id: int) -> str:
    """Нельзя удалить стадию с ЛЮБЫМИ сделками (открытыми ИЛИ закрытыми — FK
    RESTRICT физически не даст) или единственную won/lost/progress."""
    from django.db.models.deletion import RestrictedError
    from apps.renewals.models import RenewalDeal, RenewalStage
    st = RenewalStage.objects.filter(id=stage_id).first()
    if st is None:
        return 'not_found'
    # закрытые сделки навсегда привязаны к won/lost-стадии (RESTRICT) — их наличие
    # тоже блокирует удаление, иначе st.delete() падает RestrictedError → 500.
    if RenewalDeal.objects.filter(stage_id=stage_id).exists():
        return 'has_open_deals'
    if st.is_auto or (RenewalStage.objects.filter(
            pipeline=st.pipeline, kind=st.kind).count() == 1 and st.kind in ('won', 'lost', 'progress')):
        return 'protected'
    try:
        st.delete()
    except RestrictedError:
        # гонка: сделка привязалась к стадии между проверкой и удалением.
        return 'has_open_deals'
    return 'ok'


def reorder_stages(order: list[int]) -> list[dict]:
    from apps.renewals.models import RenewalStage
    from django.db import transaction
    with transaction.atomic():
        for i, sid in enumerate(order):
            RenewalStage.objects.filter(id=sid).update(sort_order=i)
    return list_stages()


def _slugify_key(label: str) -> str:
    import re
    base = re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_') or 'stage'
    return base


def _unique_stage_key(pipeline, base_key: str) -> str:
    """
    Гарантирует уникальность key в рамках воронки (UNIQUE(pipeline, key)).
    _slugify_key схлопывает кириллицу (и вообще не-ASCII) в один и тот же
    fallback ('stage'), поэтому без этой проверки вторая такая стадия падает
    IntegrityError вместо понятной ошибки.
    """
    from apps.renewals.models import RenewalStage
    key = base_key
    suffix = 2
    while RenewalStage.objects.filter(pipeline=pipeline, key=key).exists():
        key = f'{base_key}_{suffix}'
        suffix += 1
    return key


def _stage_dict(st) -> dict:
    return {'id': st.id, 'key': st.key, 'label': st.label, 'color': st.color,
            'kind': st.kind, 'is_auto': st.is_auto, 'sort_order': st.sort_order}


def list_deals(page: int, page_size: int, sort_by: str, sort_dir: str, filters: dict) -> dict:
    """Списочный вид: server-pagination. sort_dir валидируется вызывающим (view)."""
    where = ['1=1']
    params: list = []
    if not filters.get('include_closed'):
        where.append('d.outcome_at IS NULL')
    if filters.get('assignee_id'):
        where.append('d.assignee_id = %s'); params.append(int(filters['assignee_id']))
    if filters.get('direction_id'):
        where.append("""EXISTS (
            SELECT 1 FROM group_memberships fm
            JOIN groups fg ON fg.id = fm.group_id
            WHERE fm.student_id = d.student_id AND fm.active = true
              AND fg.direction_id = %s)""")
        params.append(int(filters['direction_id']))
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
            SELECT d.id, s.full_name AS student_name,
                   {DIRECTIONS_AGG_SQL} AS directions,
                   d.cycle_no, st.label AS stage_label,
                   st.kind AS stage_kind, st.color AS stage_color,
                   d.next_touch_at, d.due_at, a.full_name AS assignee_name,
                   EXTRACT(DAY FROM now() - d.stage_entered_at)::int AS days_in_stage
            FROM renewal_deal d
            JOIN students s ON s.id = d.student_id
            JOIN renewal_stage st ON st.id = d.stage_id
            LEFT JOIN accounts a ON a.id = d.assignee_id
            WHERE {where_sql}
            ORDER BY {sort_col} {direction} NULLS LAST, d.id
            LIMIT %s OFFSET %s
        """, params + [page_size, (page - 1) * page_size])
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {'rows': rows, 'total': total, 'page': page, 'page_size': page_size}
