"""
PayrollService — тонкий слой между views и repository. Никакого SQL здесь.
"""
from __future__ import annotations

from typing import Optional

from apps.payroll import repository


def list_payroll(
    page: int = 1,
    page_size: int = 50,
    sort_by: str = 'lesson_date',
    sort_dir: str = 'desc',
    filters: Optional[dict] = None,
) -> dict:
    return repository.list_payroll(
        page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir, filters=filters,
    )


def payroll_summary(
    teacher_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    return repository.payroll_summary(teacher_id=teacher_id, date_from=date_from, date_to=date_to)


def update_payroll(payroll_id: int, fields: dict) -> Optional[dict]:
    return repository.update_payroll(payroll_id, fields)
