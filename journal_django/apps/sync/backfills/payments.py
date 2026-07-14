# journal_django/apps/sync/backfills/payments.py
"""Backfill оплат из Google Sheets — только режим --append (безопасный).

Порт scripts/backfill-payments.js в режиме --append. Режим --reset (удаление
старых backfill-записей и полная перезаливка) сознательно НЕ выставлен в
Celery-задачу/API — слишком рискован для кнопки в браузере (см. спеку).
Доступен только как ручная операция через Django shell/management command,
если понадобится.
"""
from __future__ import annotations

import re

from django.db import connection

from apps.sync import sheets_client
from apps.sync.backfills.rows import cell

SHEET_NAME = 'Свод оплат'
RANGE = 'A2:E'

_DATE_RE = re.compile(r'^(\d{2})\.(\d{2})\.(\d{4})$')


def norm_name(s) -> str:
    return ' '.join(str(s or '').lower().replace('ё', 'е').split())


def parse_date(raw) -> str | None:
    m = _DATE_RE.match(str(raw or '').strip())
    if not m:
        return None
    d, mo, y = m.groups()
    return f'{y}-{mo}-{d}'


def parse_amount(raw) -> float | None:
    s = str(raw or '').replace(' ', '').replace(',', '.')
    try:
        n = float(s)
    except ValueError:
        return None
    return n if n > 0 else None


def run(dry_run: bool = False) -> dict:
    result = {
        'name': 'payments', 'dry_run': dry_run,
        'rows_read': 0, 'inserted': 0, 'duplicate_skipped': 0, 'skipped': 0,
        'archived': 0, 'non_standard': 0, 'skipped_details': [],
    }

    rows = sheets_client.read_journal_range(SHEET_NAME, RANGE)
    result['rows_read'] = len(rows)

    with connection.cursor() as cur:
        cur.execute('SELECT id, full_name FROM students')
        student_idx: dict[str, list[int]] = {}
        for sid, full_name in cur.fetchall():
            student_idx.setdefault(norm_name(full_name), []).append(sid)

        cur.execute('SELECT id, name, subscription_price FROM directions')
        dir_idx = {norm_name(name): (did, price) for did, name, price in cur.fetchall()}

        # created_by не годится маркером дедупликации: миграция 0006 переписала
        # created_by='backfill-script' на 'Павлов Илья' для ВСЕХ уже существующих
        # строк — сверяем содержимое платежа (студент/направление/сумма/дата),
        # а не автора.
        existing_keys = set()
        cur.execute(
            "SELECT student_id, direction_id, total_amount, paid_at FROM payments"
        )
        for student_id, direction_id, total_amount, paid_at in cur.fetchall():
            existing_keys.add(f"{student_id}|{direction_id or 'null'}|{total_amount}|{paid_at}")

        for i, row in enumerate(rows):
            row_num = i + 2
            raw_name = cell(row, 0)
            raw_note = cell(row, 1)
            raw_amount = cell(row, 2)
            raw_date = cell(row, 3)
            raw_dir = cell(row, 4)

            if not raw_name and not raw_amount and not raw_date and not raw_dir:
                continue

            st_key = norm_name(raw_name)
            st_matches = student_idx.get(st_key, [])
            if len(st_matches) == 0:
                result['skipped_details'].append({'row': row_num, 'reason': f"ученик '{raw_name}' не найден"})
                result['skipped'] += 1
                continue
            if len(st_matches) > 1:
                result['skipped_details'].append(
                    {'row': row_num, 'reason': f"ученик '{raw_name}' — несколько матчей: {st_matches}"})
                result['skipped'] += 1
                continue
            student_id = st_matches[0]

            amount = parse_amount(raw_amount)
            if amount is None:
                result['skipped_details'].append({'row': row_num, 'reason': f"невалидная сумма '{raw_amount}'"})
                result['skipped'] += 1
                continue

            paid_at = parse_date(raw_date)
            if not paid_at:
                result['skipped_details'].append({'row': row_num, 'reason': f"невалидная дата '{raw_date}'"})
                result['skipped'] += 1
                continue

            dir_key = norm_name(raw_dir)
            direction_id = None
            subscriptions_count = None
            unit_price = amount

            if dir_key in ('архив', ''):
                subscriptions_count = 1
                result['archived'] += 1
            else:
                dir_row = dir_idx.get(dir_key)
                if dir_row is None:
                    result['skipped_details'].append({'row': row_num, 'reason': f"направление '{raw_dir}' не найдено"})
                    result['skipped'] += 1
                    continue
                direction_id, price = dir_row
                price = float(price) if price is not None else None
                if price and price > 0 and round(amount * 100) % round(price * 100) == 0:
                    subscriptions_count = round(round(amount * 100) / round(price * 100))
                    unit_price = price
                else:
                    subscriptions_count = 1
                    unit_price = amount
                    result['non_standard'] += 1

            price_final = round(float(unit_price), 2)
            total_final = (
                f'{price_final * subscriptions_count:.2f}'
                if subscriptions_count is not None
                else f'{price_final:.2f}'
            )
            lessons_count = subscriptions_count * 4 if subscriptions_count is not None else None

            key = f"{student_id}|{direction_id or 'null'}|{total_final}|{paid_at}"
            if key in existing_keys:
                result['duplicate_skipped'] += 1
                continue

            if dry_run:
                result['inserted'] += 1
                continue

            cur.execute(
                """
                INSERT INTO payments
                    (student_id, direction_id, subscriptions_count, lessons_count, unit_price, total_amount, paid_at, note, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'backfill-script')
                """,
                [student_id, direction_id, subscriptions_count, lessons_count, price_final, total_final, paid_at,
                 raw_note.strip() or None],
            )
            result['inserted'] += 1
            existing_keys.add(key)

    return result
