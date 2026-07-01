"""
TeachersService — тонкий слой между views и repository.

Никакого SQL здесь — всё через repository.
"""
from __future__ import annotations

from typing import Optional

from apps.teachers import repository


def list_teachers(include_inactive: bool = False) -> list[dict]:
    """Делегирует список преподавателей в repository."""
    return repository.list_teachers(include_inactive=include_inactive)


def get_teacher(teacher_id: int) -> Optional[dict]:
    """Возвращает преподавателя или None."""
    return repository.get_teacher(teacher_id)


def create_teacher(data: dict) -> dict:
    """Создаёт преподавателя. 409 при UniqueViolation поднимает view."""
    return repository.create_teacher(data)


def update_teacher(teacher_id: int, data: dict) -> Optional[dict]:
    """Обновляет преподавателя. Возвращает None если не найден."""
    return repository.update_teacher(teacher_id, data)


def soft_delete_teacher(teacher_id: int) -> bool:
    """Мягкое удаление (active=false). Возвращает False если не найден."""
    return repository.soft_delete_teacher(teacher_id)
