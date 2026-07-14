# journal_django/apps/sync/backfills/lessons.py
"""Backfill занятий и посещаемости из Google Sheets. Порт scripts/backfill-lessons.js."""
from __future__ import annotations

from django.db import connection

from apps.sync import sheets_client
from apps.sync.backfills.dates import parse_lesson_date
from apps.sync.backfills.rows import cell, parse_float


def _lesson_type_from_label(label: str) -> str:
    if label == 'Замена':
        return 'substitution'
    if label == 'Перенос':
        return 'reschedule'
    return 'regular'


def extract_lessons(rows: list[list]) -> dict:
    lessons_map: dict[str, dict] = {}
    attendance: list[dict] = []

    for row in rows:
        if not row:
            continue
        date = parse_lesson_date(cell(row, 0))
        teacher = cell(row, 1)
        group = cell(row, 2)
        lesson_num = parse_float(cell(row, 3))
        student = cell(row, 4)
        status = cell(row, 5)
        token = cell(row, 7)
        record = cell(row, 8)
        type_label = cell(row, 9)
        original = cell(row, 10)

        if not date or not teacher or not group or lesson_num is None or not student or not token:
            continue

        key = f'{date}|{group}|{lesson_num}|{token}'
        if key not in lessons_map:
            lessons_map[key] = {
                'lesson_date': date,
                'teacher_name': teacher,
                'group_name': group,
                'lesson_number': lesson_num,
                'submitted_by_token': token,
                'record_url': record or None,
                'lesson_type': _lesson_type_from_label(type_label),
                'original_teacher_name': original or None,
            }

        attendance.append({
            'lesson_key': key,
            'student_name': student,
            'present': status == 'Был',
        })

    return {'lessons': list(lessons_map.values()), 'attendance': attendance}


def run(dry_run: bool = False) -> dict:
    result = {
        'entity': 'lessons+attendance',
        'lessons_read': 0, 'lessons_inserted': 0, 'lessons_skipped': 0,
        'attendance_read': 0, 'attendance_inserted': 0, 'attendance_skipped': 0,
        'dry_run': dry_run,
    }

    group_rows = sheets_client.read_journal_range('Журнал группы', 'A2:K')
    indiv_rows = sheets_client.read_journal_range('Журнал индивы', 'A2:K')
    extracted = extract_lessons(group_rows + indiv_rows)
    lessons_data = extracted['lessons']
    attendance = extracted['attendance']
    result['lessons_read'] = len(lessons_data)
    result['attendance_read'] = len(attendance)

    if dry_run:
        return result

    lesson_id_by_key: dict[str, int] = {}

    with connection.cursor() as cur:
        for l in lessons_data:
            cur.execute(
                """
                WITH g AS (SELECT id, lesson_duration_minutes FROM groups WHERE name = %(group_name)s),
                     te AS (SELECT id FROM teachers WHERE name = %(teacher_name)s),
                     ot AS (SELECT id FROM teachers WHERE name = %(original)s)
                INSERT INTO lessons
                    (lesson_date, teacher_id, group_id, lesson_number,
                     lesson_duration_minutes, lesson_type, record_url,
                     submitted_by_token, original_teacher_id, submitted_at)
                SELECT %(lesson_date)s, te.id, g.id, %(lesson_number)s, g.lesson_duration_minutes,
                       %(lesson_type)s, %(record_url)s, %(token)s,
                       (SELECT id FROM ot), (%(lesson_date)s::date)::timestamptz
                FROM g, te
                ON CONFLICT (lesson_date, group_id, lesson_number, submitted_by_token) DO NOTHING
                RETURNING id
                """,
                {
                    'group_name': l['group_name'], 'teacher_name': l['teacher_name'],
                    'original': l['original_teacher_name'], 'lesson_date': l['lesson_date'],
                    'lesson_number': l['lesson_number'], 'lesson_type': l['lesson_type'],
                    'record_url': l['record_url'], 'token': l['submitted_by_token'],
                },
            )
            row = cur.fetchone()
            key = f"{l['lesson_date']}|{l['group_name']}|{l['lesson_number']}|{l['submitted_by_token']}"

            if row is None:
                cur.execute(
                    """
                    SELECT l.id FROM lessons l
                    JOIN groups g ON g.id = l.group_id
                    WHERE l.lesson_date = %s AND g.name = %s AND l.lesson_number = %s AND l.submitted_by_token = %s
                    """,
                    [l['lesson_date'], l['group_name'], l['lesson_number'], l['submitted_by_token']],
                )
                found = cur.fetchone()
                result['lessons_skipped'] += 1
                if found is None:
                    continue
                lesson_id_by_key[key] = found[0]
            else:
                lesson_id_by_key[key] = row[0]
                result['lessons_inserted'] += 1

        for a in attendance:
            lesson_id = lesson_id_by_key.get(a['lesson_key'])
            if lesson_id is None:
                result['attendance_skipped'] += 1
                continue
            cur.execute(
                """
                WITH s AS (SELECT id FROM students WHERE full_name = %s)
                INSERT INTO lesson_attendance (lesson_id, student_id, present)
                SELECT %s, s.id, %s FROM s
                ON CONFLICT (lesson_id, student_id) DO NOTHING
                """,
                [a['student_name'], lesson_id, a['present']],
            )
            if cur.rowcount > 0:
                result['attendance_inserted'] += 1
            else:
                result['attendance_skipped'] += 1

    return result
