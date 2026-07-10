"""
PaymentsService — тонкий слой между views и repository.

Никакого SQL здесь — всё через repository.
"""
from __future__ import annotations

from typing import Optional

from apps.payments import repository


def list_payments(
    student_id: Optional[int] = None,
    direction_id: Optional[int] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
) -> list[dict]:
    return repository.list_payments(
        student_id=student_id,
        direction_id=direction_id,
        from_=from_,
        to=to,
    )


def get_payment(payment_id: int) -> Optional[dict]:
    return repository.get_payment(payment_id)


def create_payment(data: dict) -> dict:
    """Возвращает {'payment': row} или {'error': ...}."""
    return repository.create_payment(data)


def delete_payment(payment_id: int) -> dict:
    """Возвращает {'deleted': False} или {'deleted': True, ..., 'new_balance': ...}."""
    return repository.delete_payment(payment_id)


def get_student_balance(student_id: int) -> dict:
    return repository.get_student_balance(student_id)


def refund_student(student_id: int, created_by: Optional[str] = None) -> dict:
    return repository.refund_student(student_id, created_by=created_by)
