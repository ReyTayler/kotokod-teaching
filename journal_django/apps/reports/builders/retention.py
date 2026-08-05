"""
Построитель «Отчёта по переходимости» — как дети переходят из цикла в цикл,
в разрезе преподавателей и направлений.

Параметров нет: отчёт общий, по всей истории. Период не выбирается сознательно —
интерес здесь в ТРЕНДЕ, а тренд обязан включать и те месяцы, когда уходы ещё не
отмечали (см. «Как читать» ниже). Свернув всё в одно число за выбранный период,
мы бы это скрыли.

Структура книги:
  1. «Свод — преподаватели»   строка = преподаватель, итог за всю историю;
  2. «Свод — направления»     то же, строка = направление;
  3. «Помесячно — преподаватели»  длинный формат под сводные таблицы Excel;
  4. «Помесячно — направления»    то же;
  5. «Детализация»            строка = сделка, чтобы разложить любую цифру.

ТРИ ВЕЩИ, БЕЗ КОТОРЫХ ЦИФРЫ ЧИТАЮТСЯ НЕВЕРНО (продублированы в шапке листов):

1. Сумма строк БОЛЬШЕ школьного итога. `renewal_deal` привязана к ученику и
   циклу — направления или группы в ней нет вовсе. Ученика связываем с
   преподавателями и направлениями через его группы, поэтому занимающийся у
   двоих попадает в обе строки. Колонку нельзя складывать.

2. Уходы отмечают не с начала времён. В журнале стадия «Ушёл» массово
   появилась только весной 2026 — до этого ушедших просто не переводили, и
   сделка оставалась висеть в «Ждём продление». Поэтому ранние месяцы покажут
   100 % у всех: это артефакт учёта, а не удержание. Отсюда же колонка
   «застряло» — она честнее доли.

3. Служебная запись «Архив (импорт истории)» (`teachers.is_service`) идёт
   отдельной строкой и НЕ входит в итог: на ней висит ~80 % всех сделок школы,
   и в общем зачёте она забивает всех живых преподавателей.
"""
from __future__ import annotations

import io
from collections import defaultdict

from django.db import connection

# Сделка считается ЗАСТРЯВШЕЙ, если она открыта и её опорная дата старше этого
# порога. 30 дней — цикл продления укладывается в месяц: всё, что висит дольше,
# уже не «в работе», а забыто. Порог влияет только на отчёт, не на домен.
STUCK_AFTER_DAYS = 30

_NOTE_LINES = [
    'Сумма строк больше школьного итога: сделка привязана к ученику, а не к направлению, '
    'поэтому ученик, занимающийся у нескольких преподавателей, учитывается в каждой строке. '
    'Колонку складывать нельзя.',
    'Уходы («Ушёл») массово отмечают только с весны 2026 — в более ранних месяцах доля '
    'будет 100 % у всех, и это артефакт учёта, а не удержание. Смотрите колонку «Застряло».',
    'Строка «Архив (импорт истории)» — служебная запись, куда сложили доисторические данные. '
    'В итог она не входит.',
]


def _fetch_deals() -> list[dict]:
    """Все сделки продления с исходом и опорной датой.

    `outcome_month` — месяц закрытия по МСК. `outcome_at` — timestamptz, поэтому
    конвертируем явно: без AT TIME ZONE события ночью 00:00–02:59 по Москве
    уезжают в предыдущий месяц (та же поправка, что в apps.renewals.analytics).
    """
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT d.id,
                   d.student_id,
                   s.full_name                                            AS student_name,
                   d.cycle_no,
                   st.kind                                                AS kind,
                   st.label                                               AS stage_label,
                   to_char(d.outcome_at AT TIME ZONE 'Europe/Moscow', 'YYYY-MM') AS outcome_month,
                   (d.outcome_at AT TIME ZONE 'Europe/Moscow')::date      AS outcome_date,
                   (d.outcome_at IS NULL
                    AND COALESCE(d.due_at, d.stage_entered_at::date)
                        < current_date - INTERVAL '{STUCK_AFTER_DAYS} days') AS is_stuck,
                   COALESCE(d.due_at, d.stage_entered_at::date)           AS reference_date
              FROM renewal_deal d
              JOIN renewal_stage st ON st.id = d.stage_id
              JOIN students s       ON s.id = d.student_id
             ORDER BY s.full_name, d.cycle_no
        """)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _student_links() -> tuple[dict[int, list[dict]], dict[int, list[dict]]]:
    """
    student_id → преподаватели и student_id → направления, через ЛЮБЫЕ членства.

    Членство неактивное и группа архивная считаются: ушедший ученик — часть
    истории переходимости, и выкинув его, мы показали бы только выживших.
    """
    with connection.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT m.student_id,
                            t.id AS teacher_id, t.name AS teacher_name, t.is_service,
                            dir.id AS direction_id, dir.name AS direction_name
              FROM group_memberships m
              JOIN groups g      ON g.id = m.group_id
              JOIN teachers t    ON t.id = g.teacher_id
              JOIN directions dir ON dir.id = g.direction_id
        """)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    teachers: dict[int, dict[int, dict]] = defaultdict(dict)
    directions: dict[int, dict[int, dict]] = defaultdict(dict)
    for r in rows:
        teachers[r['student_id']][r['teacher_id']] = {
            'id': r['teacher_id'], 'name': r['teacher_name'], 'is_service': r['is_service'],
        }
        directions[r['student_id']][r['direction_id']] = {
            'id': r['direction_id'], 'name': r['direction_name'], 'is_service': False,
        }
    return (
        {sid: list(v.values()) for sid, v in teachers.items()},
        {sid: list(v.values()) for sid, v in directions.items()},
    )


def _blank() -> dict:
    return {
        'students': set(), 'won': 0, 'lost': 0, 'open': 0, 'stuck': 0,
        'by_month': defaultdict(lambda: {'won': 0, 'lost': 0}),
    }


def _aggregate(deals: list[dict], links: dict[int, list[dict]]) -> list[dict]:
    """Свернуть сделки по измерению (преподаватель или направление)."""
    acc: dict[int, dict] = {}
    names: dict[int, dict] = {}

    for deal in deals:
        for entity in links.get(deal['student_id'], ()):
            bucket = acc.setdefault(entity['id'], _blank())
            names[entity['id']] = entity
            bucket['students'].add(deal['student_id'])

            if deal['kind'] == 'won':
                bucket['won'] += 1
            elif deal['kind'] == 'lost':
                bucket['lost'] += 1
            else:
                bucket['open'] += 1
                if deal['is_stuck']:
                    bucket['stuck'] += 1

            month = deal['outcome_month']
            if month and deal['kind'] in ('won', 'lost'):
                bucket['by_month'][month][deal['kind']] += 1

    out = []
    for entity_id, bucket in acc.items():
        closed = bucket['won'] + bucket['lost']
        out.append({
            'id': entity_id,
            'name': names[entity_id]['name'],
            'is_service': names[entity_id]['is_service'],
            'students': len(bucket['students']),
            'closed': closed,
            'won': bucket['won'],
            'lost': bucket['lost'],
            # None, а не 0: «закрытых сделок нет» и «все ушли» — разные вещи.
            'pct': round(bucket['won'] * 100 / closed) if closed else None,
            'stuck': bucket['stuck'],
            'open': bucket['open'],
            'by_month': dict(bucket['by_month']),
        })
    # Служебные записи — в конец, живые — по убыванию объёма.
    out.sort(key=lambda r: (r['is_service'], -r['closed'], r['name']))
    return out


def collect() -> dict:
    """Все данные отчёта. Отдельно от рендера — чтобы тестировать без openpyxl."""
    deals = _fetch_deals()
    by_teacher_links, by_direction_links = _student_links()
    return {
        'deals': deals,
        'teachers': _aggregate(deals, by_teacher_links),
        'directions': _aggregate(deals, by_direction_links),
        'links_teachers': by_teacher_links,
        'links_directions': by_direction_links,
    }


# ---------------------------------------------------------------------------
# Рендер
# ---------------------------------------------------------------------------

_SUMMARY_COLUMNS = [
    ('Название', 'name', 34),
    ('Учеников', 'students', 11),
    ('Закрыто циклов', 'closed', 16),
    ('Продлились', 'won', 13),
    ('Ушли', 'lost', 9),
    ('Доля продлений', 'pct', 16),
    ('Застряло', 'stuck', 11),
    ('В работе', 'open', 11),
]


def _write_notes(ws, ncols: int, title: str) -> int:
    """Заголовок + пояснения. Возвращает номер строки, с которой идёт таблица."""
    from openpyxl.styles import Alignment, Font

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    cell = ws.cell(row=1, column=1, value=title)
    cell.font = Font(bold=True, size=14)

    row = 2
    for note in _NOTE_LINES:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
        c = ws.cell(row=row, column=1, value=note)
        c.font = Font(size=9, italic=True, color='808080')
        c.alignment = Alignment(wrap_text=True, vertical='top')
        ws.row_dimensions[row].height = 26
        row += 1
    return row + 1


def _style_header(ws, row: int, ncols: int) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    fill = PatternFill('solid', fgColor='4F59F9')
    font = Font(bold=True, color='FFFFFF')
    for ci in range(1, ncols + 1):
        cell = ws.cell(row=row, column=ci)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(wrap_text=True, vertical='center')


def _write_summary(ws, title: str, rows: list[dict]) -> None:
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    ncols = len(_SUMMARY_COLUMNS)
    header_row = _write_notes(ws, ncols, title)

    for ci, (label, _key, width) in enumerate(_SUMMARY_COLUMNS, start=1):
        ws.cell(row=header_row, column=ci, value=label)
        ws.column_dimensions[get_column_letter(ci)].width = width
    _style_header(ws, header_row, ncols)

    ri = header_row
    for row in rows:
        ri += 1
        for ci, (_label, key, _w) in enumerate(_SUMMARY_COLUMNS, start=1):
            value = row[key]
            if key == 'name' and row['is_service']:
                value = f'{value} — служебная, не в итоге'
            if key == 'pct':
                # Доля пишется числом 0..1 с процентным форматом: так Excel
                # умеет её усреднять и строить по ней графики, а строка «94 %»
                # осталась бы текстом.
                cell = ws.cell(row=ri, column=ci, value=None if value is None else value / 100)
                cell.number_format = '0 %'
                continue
            cell = ws.cell(row=ri, column=ci, value=value)
            if key == 'name' and row['is_service']:
                cell.font = Font(italic=True, color='808080')

    ws.freeze_panes = ws.cell(row=header_row + 1, column=2)


_MONTHLY_COLUMNS = [
    ('Название', 'name', 34),
    ('Месяц', 'month', 12),
    ('Продлились', 'won', 13),
    ('Ушли', 'lost', 9),
    ('Доля продлений', 'pct', 16),
]


def _write_monthly(ws, title: str, rows: list[dict]) -> int:
    """Длинный формат (строка = сущность × месяц) — под сводные таблицы Excel."""
    from openpyxl.utils import get_column_letter

    ncols = len(_MONTHLY_COLUMNS)
    header_row = _write_notes(ws, ncols, title)

    for ci, (label, _key, width) in enumerate(_MONTHLY_COLUMNS, start=1):
        ws.cell(row=header_row, column=ci, value=label)
        ws.column_dimensions[get_column_letter(ci)].width = width
    _style_header(ws, header_row, ncols)

    ri = header_row
    written = 0
    for row in rows:
        for month in sorted(row['by_month']):
            counts = row['by_month'][month]
            closed = counts['won'] + counts['lost']
            ri += 1
            written += 1
            ws.cell(row=ri, column=1, value=row['name'])
            ws.cell(row=ri, column=2, value=month)
            ws.cell(row=ri, column=3, value=counts['won'])
            ws.cell(row=ri, column=4, value=counts['lost'])
            cell = ws.cell(row=ri, column=5,
                           value=None if not closed else counts['won'] / closed)
            cell.number_format = '0 %'

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    return written


_DETAIL_COLUMNS = [
    ('Ученик', 34),
    ('Цикл', 8),
    ('Стадия', 22),
    ('Исход', 14),
    ('Дата исхода', 14),
    ('Опорная дата', 14),
    ('Застряла', 11),
    ('Преподаватели', 40),
    ('Направления', 40),
]

_KIND_LABELS = {'won': 'Продлился', 'lost': 'Ушёл'}


def _write_detail(ws, deals: list[dict], links_t: dict, links_d: dict) -> None:
    from openpyxl.utils import get_column_letter

    ncols = len(_DETAIL_COLUMNS)
    header_row = _write_notes(ws, ncols, 'Детализация: строка = сделка продления')

    for ci, (label, width) in enumerate(_DETAIL_COLUMNS, start=1):
        ws.cell(row=header_row, column=ci, value=label)
        ws.column_dimensions[get_column_letter(ci)].width = width
    _style_header(ws, header_row, ncols)

    ri = header_row
    for deal in deals:
        ri += 1
        teachers = ', '.join(sorted(e['name'] for e in links_t.get(deal['student_id'], ())))
        directions = ', '.join(sorted(e['name'] for e in links_d.get(deal['student_id'], ())))
        ws.cell(row=ri, column=1, value=deal['student_name'])
        ws.cell(row=ri, column=2, value=deal['cycle_no'])
        ws.cell(row=ri, column=3, value=deal['stage_label'])
        ws.cell(row=ri, column=4, value=_KIND_LABELS.get(deal['kind'], 'В работе'))
        ws.cell(row=ri, column=5, value=deal['outcome_date'])
        ws.cell(row=ri, column=6, value=deal['reference_date'])
        ws.cell(row=ri, column=7, value='да' if deal['is_stuck'] else '')
        ws.cell(row=ri, column=8, value=teachers or '— нет групп —')
        ws.cell(row=ri, column=9, value=directions or '— нет групп —')

    ws.freeze_panes = ws.cell(row=header_row + 1, column=2)


def render_workbook(data: dict) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()

    ws = wb.active
    ws.title = 'Свод — преподаватели'
    _write_summary(ws, 'Переходимость по преподавателям (вся история)', data['teachers'])

    _write_summary(
        wb.create_sheet('Свод — направления'),
        'Переходимость по направлениям (вся история)', data['directions'],
    )
    _write_monthly(
        wb.create_sheet('Помесячно — преподаватели'),
        'Переходимость по месяцам: преподаватели', data['teachers'],
    )
    _write_monthly(
        wb.create_sheet('Помесячно — направления'),
        'Переходимость по месяцам: направления', data['directions'],
    )
    _write_detail(
        wb.create_sheet('Детализация'),
        data['deals'], data['links_teachers'], data['links_directions'],
    )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build() -> tuple[bytes, int, str]:
    """(xlsx-байты, число сделок, имя файла). Параметров нет — отчёт общий."""
    from apps.core.utils.dates import msk_now

    data = collect()
    content = render_workbook(data)
    filename = f'retention_{msk_now():%Y-%m-%d}.xlsx'
    return content, len(data['deals']), filename
