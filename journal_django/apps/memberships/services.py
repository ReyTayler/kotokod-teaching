"""
MembershipsService — тонкий слой бизнес-логики между views и repository.

Принцип: никакого SQL здесь — всё через repository.
"""
from __future__ import annotations

from typing import Optional

from apps.memberships import repository


def list_memberships(
    group_id: Optional[int] = None,
    student_id: Optional[int] = None,
    include_inactive: bool = False,
) -> list[dict]:
    """Делегирует список membership в repository."""
    return repository.list_memberships(
        group_id=group_id,
        student_id=student_id,
        include_inactive=include_inactive,
    )


def add_membership(data: dict) -> dict:
    """Создаёт или реактивирует membership (UPSERT)."""
    return repository.add_membership(data)


def update_membership(membership_id: int, data: dict) -> Optional[dict]:
    """Обновляет membership. Возвращает None если не найден."""
    return repository.update_membership(membership_id, data)


def remove_membership(membership_id: int) -> bool:
    """Мягкое удаление (active=false). Возвращает False если не найден."""
    return repository.remove_membership(membership_id)
