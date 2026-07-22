# journal_django/apps/sync/backfills/students.py
"""Backfill учеников и абонементов из Google Sheets. Порт scripts/backfill-students.js."""
from __future__ import annotations

from django.db import connection

from apps.core.utils.dates import msk_now
from apps.students.migrations._frozen_backfill_util import (
    clamp_frozen_from,
    infer_frozen_until,
)
from apps.sync import sheets_client
from apps.sync.backfills.dates import parse_start_date
from apps.sync.backfills.rows import cell, parse_float, parse_int

MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
          'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']


def map_enrollment_from_sheets(raw, has_membership: bool) -> dict:
    """Статус зачисления из ячейки листа → {enrollment_status, frozen_from, frozen_until}.

    В листе хранится только месяц окончания заморозки (год/дату начала лист не
    держит). Конвертируем тем же инференсом, что и миграция 0010: frozen_until —
    1-е число ближайшего наступления месяца, frozen_from — best-effort = сегодня
    по МСК, склампленный до frozen_until (инвариант frozen_from <= frozen_until).
    """
    s = str(raw or '').strip().lower()
    fallback_status = 'enrolled' if has_membership else 'not_enrolled'
    fallback = {'enrollment_status': fallback_status, 'frozen_from': None, 'frozen_until': None}

    if not s:
        return fallback
    if s == 'да':
        return {'enrollment_status': 'enrolled', 'frozen_from': None, 'frozen_until': None}
    if s == 'нет':
        return {'enrollment_status': 'not_enrolled', 'frozen_from': None, 'frozen_until': None}
    if 'отказ' in s:
        return {'enrollment_status': 'declined', 'frozen_from': None, 'frozen_until': None}

    rest = s[3:].strip() if s.startswith('нет') else s
    for idx, month in enumerate(MONTHS):
        if rest.startswith(month):
            today = msk_now().date()
            until = infer_frozen_until(idx + 1, today)
            return {
                'enrollment_status': 'frozen',
                'frozen_from': clamp_frozen_from(today, until),
                'frozen_until': until,
            }
    return fallback


def extract_students_and_memberships(rows: list[list]) -> dict:
    students_map: dict[str, dict] = {}
    memberships: list[dict] = []

    for row in rows:
        name = cell(row, 0)
        if not name or 'УЧЕНИКА НЕТ' in name:
            continue

        teacher = cell(row, 11)
        group = cell(row, 12)
        teacher_ok = bool(teacher) and 'УЧЕНИКА НЕТ' not in teacher
        group_ok = bool(group) and 'УЧЕНИКА НЕТ' not in group
        has_membership = teacher_ok and group_ok

        if name not in students_map:
            enroll = map_enrollment_from_sheets(cell(row, 19) or None, has_membership)
            students_map[name] = {
                'full_name': name,
                'age': parse_int(cell(row, 2)),
                'birth_date': parse_start_date(cell(row, 7)),
                'parent1_phone': cell(row, 6) or None,
                'platform_id': cell(row, 4) or None,
                'parent1_name': cell(row, 5) or None,
                'first_purchase_date': parse_start_date(cell(row, 8)),
                'enrollment_status': enroll['enrollment_status'],
                'frozen_from': enroll['frozen_from'],
                'frozen_until': enroll['frozen_until'],
            }

        if has_membership:
            done = round((parse_float(cell(row, 16)) or 0) * 10) / 10
            memberships.append({
                'student_name': name,
                'group_name': group,
                'lessons_done': done,
                'start_date': parse_start_date(cell(row, 13)),
                'sheet_row': parse_int(cell(row, 14)),
            })

    return {'students': list(students_map.values()), 'memberships': memberships}


def run(dry_run: bool = False) -> dict:
    result = {
        'entity': 'students+memberships',
        'students_read': 0, 'students_inserted': 0, 'students_updated': 0, 'students_skipped': 0,
        'memberships_read': 0, 'memberships_inserted': 0, 'memberships_updated': 0, 'memberships_skipped': 0,
        'dry_run': dry_run,
    }

    rows = sheets_client.read_students_range('Список всех детей', 'A3:T')
    extracted = extract_students_and_memberships(rows)
    students_data = extracted['students']
    memberships = extracted['memberships']
    result['students_read'] = len(students_data)
    result['memberships_read'] = len(memberships)

    if dry_run:
        return result

    with connection.cursor() as cur:
        for s in students_data:
            cur.execute(
                """
                INSERT INTO students
                    (full_name, age, birth_date, parent1_phone, platform_id,
                     parent1_name, first_purchase_date, enrollment_status,
                     frozen_from, frozen_until)
                VALUES (%(full_name)s, %(age)s, %(birth_date)s, %(phone)s,
                        %(platform)s, %(parent)s, %(first_purchase)s, %(status)s,
                        %(frozen_from)s, %(frozen_until)s)
                ON CONFLICT (full_name) DO UPDATE SET
                    age                 = EXCLUDED.age,
                    birth_date          = EXCLUDED.birth_date,
                    parent1_phone       = EXCLUDED.parent1_phone,
                    platform_id         = EXCLUDED.platform_id,
                    parent1_name        = EXCLUDED.parent1_name,
                    first_purchase_date = EXCLUDED.first_purchase_date,
                    enrollment_status   = EXCLUDED.enrollment_status,
                    frozen_from         = EXCLUDED.frozen_from,
                    frozen_until        = EXCLUDED.frozen_until
                WHERE students.age IS DISTINCT FROM EXCLUDED.age
                   OR students.birth_date          IS DISTINCT FROM EXCLUDED.birth_date
                   OR students.parent1_phone       IS DISTINCT FROM EXCLUDED.parent1_phone
                   OR students.platform_id         IS DISTINCT FROM EXCLUDED.platform_id
                   OR students.parent1_name        IS DISTINCT FROM EXCLUDED.parent1_name
                   OR students.first_purchase_date IS DISTINCT FROM EXCLUDED.first_purchase_date
                   OR students.enrollment_status   IS DISTINCT FROM EXCLUDED.enrollment_status
                   OR students.frozen_from         IS DISTINCT FROM EXCLUDED.frozen_from
                   OR students.frozen_until        IS DISTINCT FROM EXCLUDED.frozen_until
                RETURNING (xmax = 0) AS inserted
                """,
                {
                    'full_name': s['full_name'], 'age': s['age'],
                    'birth_date': s['birth_date'], 'phone': s['parent1_phone'],
                    'platform': s['platform_id'], 'parent': s['parent1_name'],
                    'first_purchase': s['first_purchase_date'], 'status': s['enrollment_status'],
                    'frozen_from': s['frozen_from'], 'frozen_until': s['frozen_until'],
                },
            )
            row = cur.fetchone()
            if row is None:
                result['students_skipped'] += 1
            elif row[0]:
                result['students_inserted'] += 1
            else:
                result['students_updated'] += 1

        for m in memberships:
            cur.execute(
                """
                WITH g AS (SELECT id FROM groups   WHERE name = %(group_name)s),
                     s AS (SELECT id FROM students WHERE full_name = %(student_name)s)
                INSERT INTO group_memberships
                    (group_id, student_id, lessons_done, start_date, sheet_row, active)
                SELECT g.id, s.id, %(lessons_done)s, %(start_date)s, %(sheet_row)s, true FROM g, s
                ON CONFLICT (group_id, student_id) DO UPDATE SET
                    lessons_done = EXCLUDED.lessons_done,
                    start_date   = EXCLUDED.start_date,
                    sheet_row    = EXCLUDED.sheet_row
                WHERE group_memberships.lessons_done IS DISTINCT FROM EXCLUDED.lessons_done
                   OR group_memberships.start_date   IS DISTINCT FROM EXCLUDED.start_date
                   OR group_memberships.sheet_row    IS DISTINCT FROM EXCLUDED.sheet_row
                RETURNING (xmax = 0) AS inserted
                """,
                {
                    'group_name': m['group_name'], 'student_name': m['student_name'],
                    'lessons_done': m['lessons_done'], 'start_date': m['start_date'],
                    'sheet_row': m['sheet_row'],
                },
            )
            row = cur.fetchone()
            if row is None:
                result['memberships_skipped'] += 1
            elif row[0]:
                result['memberships_inserted'] += 1
            else:
                result['memberships_updated'] += 1

    return result
