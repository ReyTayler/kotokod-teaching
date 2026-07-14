# journal_django/apps/sync/backfills/payroll.py
"""Backfill зарплаты из Google Sheets. Порт scripts/backfill-payroll.js."""
from __future__ import annotations

from django.db import connection

from apps.sync import sheets_client
from apps.sync.backfills.dates import parse_lesson_date
from apps.sync.backfills.rows import cell, parse_float, parse_int


def extract_payroll(rows: list[list]) -> list[dict]:
    out = []
    for row in rows:
        if not row:
            continue
        date = parse_lesson_date(cell(row, 0))
        group = cell(row, 2)
        lesson_num = parse_float(cell(row, 3))
        total = parse_int(cell(row, 4))
        present = parse_int(cell(row, 5))
        payment = parse_float(cell(row, 6))
        token = cell(row, 8)
        penalty_raw = cell(row, 9)

        if not date or not group or lesson_num is None or not token:
            continue
        if total is None or present is None or payment is None:
            continue

        out.append({
            'lesson_date': date,
            'group_name': group,
            'lesson_number': lesson_num,
            'submitted_by_token': token,
            'total_students': total,
            'present_count': present,
            'payment': payment,
            'penalty': parse_float(penalty_raw) or 0.0,
        })
    return out


def run(dry_run: bool = False) -> dict:
    result = {
        'entity': 'payroll', 'read': 0, 'inserted': 0, 'updated': 0,
        'skipped': 0, 'no_lesson': 0, 'dry_run': dry_run,
    }

    rows = sheets_client.read_journal_range('Зарплата', 'A2:L')
    payroll_data = extract_payroll(rows)
    result['read'] = len(payroll_data)

    if dry_run:
        return result

    with connection.cursor() as cur:
        for p in payroll_data:
            cur.execute(
                """
                WITH l AS (
                    SELECT l.id, l.teacher_id FROM lessons l
                    JOIN groups g ON g.id = l.group_id
                    WHERE l.lesson_date = %(lesson_date)s AND g.name = %(group_name)s
                      AND l.lesson_number = %(lesson_number)s AND l.submitted_by_token = %(token)s
                )
                INSERT INTO payroll (lesson_id, teacher_id, total_students, present_count, payment, penalty)
                SELECT l.id, l.teacher_id, %(total)s, %(present)s, %(payment)s, %(penalty)s FROM l
                ON CONFLICT (lesson_id) DO UPDATE SET
                    total_students = EXCLUDED.total_students,
                    present_count  = EXCLUDED.present_count,
                    payment        = EXCLUDED.payment,
                    penalty        = EXCLUDED.penalty
                WHERE payroll.total_students IS DISTINCT FROM EXCLUDED.total_students
                   OR payroll.present_count  IS DISTINCT FROM EXCLUDED.present_count
                   OR payroll.payment        IS DISTINCT FROM EXCLUDED.payment
                   OR payroll.penalty        IS DISTINCT FROM EXCLUDED.penalty
                RETURNING (xmax = 0) AS inserted
                """,
                {
                    'lesson_date': p['lesson_date'], 'group_name': p['group_name'],
                    'lesson_number': p['lesson_number'], 'token': p['submitted_by_token'],
                    'total': p['total_students'], 'present': p['present_count'],
                    'payment': p['payment'], 'penalty': p['penalty'],
                },
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    """
                    SELECT 1 FROM lessons l JOIN groups g ON g.id = l.group_id
                    WHERE l.lesson_date = %s AND g.name = %s AND l.lesson_number = %s AND l.submitted_by_token = %s
                    """,
                    [p['lesson_date'], p['group_name'], p['lesson_number'], p['submitted_by_token']],
                )
                if cur.fetchone() is None:
                    result['no_lesson'] += 1
                else:
                    result['skipped'] += 1
            elif row[0]:
                result['inserted'] += 1
            else:
                result['updated'] += 1

    return result
