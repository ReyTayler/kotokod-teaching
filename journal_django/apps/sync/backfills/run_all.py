# journal_django/apps/sync/backfills/run_all.py
"""Оркестратор: teachers → groups → students → lessons → payroll. Порт scripts/backfill-all.js.

payments сюда намеренно не входит — как и в оригинальном backfill-all.js.
"""
from __future__ import annotations

from apps.sync.backfills import groups, lessons, payroll, students, teachers

STEPS = [
    ('teachers', teachers),
    ('groups', groups),
    ('students', students),
    ('lessons', lessons),
    ('payroll', payroll),
]


def run(dry_run: bool = False) -> dict:
    results = [module.run(dry_run=dry_run) for _, module in STEPS]
    return {'dry_run': dry_run, 'steps': results}
