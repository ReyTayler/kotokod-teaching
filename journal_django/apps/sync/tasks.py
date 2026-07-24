# journal_django/apps/sync/tasks.py
"""Celery-задачи apps.sync — обёртки над backfills/*.py.

Очередь 'default' (не 'interactive') — не конкурируют с OTP-письмами входа за
приоритет. time_limit с запасом под реальный объём данных из Google Sheets;
run_all-задача самая долгая (5 шагов подряд).
"""
from __future__ import annotations

from celery import shared_task

from apps.sync.backfills import (
    groups, lessons, payments, payroll, rebuild_absence_resolutions,
    rebuild_counters, rebuild_payroll, rebuild_planned_lessons, rebuild_renewal_dates,
    rebuild_renewals, run_all, students, teachers,
)


@shared_task(name='apps.sync.tasks.backfill_teachers_task', time_limit=120)
def backfill_teachers_task(dry_run: bool = False) -> dict:
    return teachers.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.backfill_groups_task', time_limit=120)
def backfill_groups_task(dry_run: bool = False) -> dict:
    return groups.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.backfill_students_task', time_limit=180)
def backfill_students_task(dry_run: bool = False) -> dict:
    return students.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.backfill_lessons_task', time_limit=300)
def backfill_lessons_task(dry_run: bool = False) -> dict:
    return lessons.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.backfill_payments_task', time_limit=180)
def backfill_payments_task(dry_run: bool = False) -> dict:
    return payments.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.backfill_payroll_task', time_limit=180)
def backfill_payroll_task(dry_run: bool = False) -> dict:
    return payroll.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.rebuild_payroll_task', time_limit=180)
def rebuild_payroll_task(dry_run: bool = False) -> dict:
    return rebuild_payroll.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.rebuild_counters_task', time_limit=180)
def rebuild_counters_task(dry_run: bool = False) -> dict:
    return rebuild_counters.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.rebuild_planned_lessons_task', time_limit=300)
def rebuild_planned_lessons_task(dry_run: bool = False) -> dict:
    return rebuild_planned_lessons.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.rebuild_absence_resolutions_task', time_limit=300)
def rebuild_absence_resolutions_task(dry_run: bool = False) -> dict:
    return rebuild_absence_resolutions.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.rebuild_renewals_task', time_limit=300)
def rebuild_renewals_task(dry_run: bool = False) -> dict:
    return rebuild_renewals.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.rebuild_renewal_dates_task', time_limit=300)
def rebuild_renewal_dates_task(dry_run: bool = False) -> dict:
    return rebuild_renewal_dates.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.run_all_task', time_limit=600)
def run_all_task(dry_run: bool = False) -> dict:
    return run_all.run(dry_run=dry_run)
