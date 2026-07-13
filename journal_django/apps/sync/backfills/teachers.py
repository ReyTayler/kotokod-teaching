# journal_django/apps/sync/backfills/teachers.py
"""Backfill преподавателей из Google Sheets. Порт scripts/backfill-teachers.js."""
from __future__ import annotations

from django.db import connection

from apps.sync import sheets_client
from apps.sync.backfills.rows import cell


def extract_teachers(student_rows: list[list], token_rows: list[list]) -> list[str]:
    names: set[str] = set()

    for row in student_rows:
        teacher = cell(row, 11)
        group = cell(row, 12)
        if not teacher or not group:
            continue
        if 'УЧЕНИКА НЕТ' in teacher or 'УЧЕНИКА НЕТ' in group:
            continue
        names.add(teacher)

    for row in token_rows[1:]:
        teacher = cell(row, 5)
        if teacher:
            names.add(teacher)

    return list(names)


def run(dry_run: bool = False) -> dict:
    result = {'entity': 'teachers', 'read': 0, 'inserted': 0, 'skipped': 0, 'dry_run': dry_run}

    student_rows = sheets_client.read_students_range('Список всех детей', 'A3:S')
    token_rows = sheets_client.read_journal_range('Токены', 'A:F')

    names = extract_teachers(student_rows, token_rows)
    result['read'] = len(names)

    if dry_run:
        return result

    with connection.cursor() as cur:
        for name in names:
            cur.execute(
                """
                INSERT INTO teachers (name) VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                RETURNING id
                """,
                [name],
            )
            if cur.fetchone() is None:
                result['skipped'] += 1
            else:
                result['inserted'] += 1

    return result
