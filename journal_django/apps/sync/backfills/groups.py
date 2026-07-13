# journal_django/apps/sync/backfills/groups.py
"""Backfill групп из Google Sheets. Порт scripts/backfill-groups.js."""
from __future__ import annotations

from django.db import connection

from apps.sync import sheets_client
from apps.sync.backfills.dates import parse_start_date
from apps.sync.backfills.rows import cell
from apps.sync.lib.parse_time import parse_lesson_duration, parse_time_slots


def extract_groups(rows: list[list]) -> list[dict]:
    seen: dict[str, dict] = {}
    for row in rows:
        teacher = cell(row, 11)
        group = cell(row, 12)
        vk = cell(row, 15)
        direction = cell(row, 18)
        start_date = parse_start_date(cell(row, 13))

        if not teacher or not group or not direction:
            continue
        if any('УЧЕНИКА НЕТ' in v for v in (teacher, group, direction)):
            continue

        if group not in seen:
            is_individual = 'ИНДИВ' in direction
            slots = parse_time_slots(group)
            seen[group] = {
                'name': group,
                'direction_name': direction,
                'teacher_name': teacher,
                'is_individual': is_individual,
                'lesson_duration_minutes': parse_lesson_duration(group),
                'lessons_per_week': len(slots) or 1,
                'vk_chat': vk,
                'group_start_date': start_date,
                'slots': slots,
            }
        else:
            g = seen[group]
            if not g['group_start_date'] and start_date:
                g['group_start_date'] = start_date

    return list(seen.values())


def run(dry_run: bool = False) -> dict:
    result = {
        'entity': 'groups', 'read': 0, 'inserted': 0, 'updated': 0,
        'skipped': 0, 'slots_replaced': 0, 'dry_run': dry_run,
    }

    rows = sheets_client.read_students_range('Список всех детей', 'A3:T')
    groups_data = extract_groups(rows)
    result['read'] = len(groups_data)

    if dry_run:
        return result

    with connection.cursor() as cur:
        for g in groups_data:
            cur.execute(
                """
                WITH d AS (SELECT id FROM directions WHERE name = %(direction_name)s),
                     te AS (SELECT id FROM teachers WHERE name = %(teacher_name)s)
                INSERT INTO groups (name, direction_id, teacher_id, is_individual,
                                    lesson_duration_minutes, lessons_per_week, vk_chat, group_start_date)
                SELECT %(name)s, d.id, te.id, %(is_individual)s, %(duration)s, %(per_week)s,
                       NULLIF(%(vk_chat)s, ''), %(start_date)s
                FROM d, te
                ON CONFLICT (name) DO UPDATE SET
                   direction_id            = EXCLUDED.direction_id,
                   teacher_id              = EXCLUDED.teacher_id,
                   is_individual           = EXCLUDED.is_individual,
                   lesson_duration_minutes = EXCLUDED.lesson_duration_minutes,
                   lessons_per_week        = EXCLUDED.lessons_per_week,
                   vk_chat                 = EXCLUDED.vk_chat,
                   group_start_date        = EXCLUDED.group_start_date
                WHERE
                   groups.direction_id            IS DISTINCT FROM EXCLUDED.direction_id
                OR groups.teacher_id              IS DISTINCT FROM EXCLUDED.teacher_id
                OR groups.is_individual           IS DISTINCT FROM EXCLUDED.is_individual
                OR groups.lesson_duration_minutes IS DISTINCT FROM EXCLUDED.lesson_duration_minutes
                OR groups.lessons_per_week        IS DISTINCT FROM EXCLUDED.lessons_per_week
                OR (groups.vk_chat IS DISTINCT FROM NULLIF(EXCLUDED.vk_chat, ''))
                OR groups.group_start_date        IS DISTINCT FROM EXCLUDED.group_start_date
                RETURNING id, (xmax = 0) AS inserted
                """,
                {
                    'direction_name': g['direction_name'], 'teacher_name': g['teacher_name'],
                    'name': g['name'], 'is_individual': g['is_individual'],
                    'duration': g['lesson_duration_minutes'], 'per_week': g['lessons_per_week'],
                    'vk_chat': g['vk_chat'], 'start_date': g['group_start_date'],
                },
            )
            row = cur.fetchone()

            if row is None:
                cur.execute('SELECT id FROM groups WHERE name = %s', [g['name']])
                found = cur.fetchone()
                if found is None:
                    result['skipped'] += 1
                    continue
                group_id = found[0]
                result['skipped'] += 1
            else:
                group_id, inserted = row
                if inserted:
                    result['inserted'] += 1
                else:
                    result['updated'] += 1

            cur.execute('DELETE FROM group_schedule_slots WHERE group_id = %s', [group_id])
            for slot in g['slots']:
                cur.execute(
                    'INSERT INTO group_schedule_slots (group_id, day_of_week, start_time) VALUES (%s, %s, %s)',
                    [group_id, slot['day_of_week'], slot['start_time']],
                )
                result['slots_replaced'] += 1

    return result
