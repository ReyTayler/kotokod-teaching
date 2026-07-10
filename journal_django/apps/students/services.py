"""
StudentsService — тонкий слой между views и repository.

Принцип: никакого SQL здесь — всё через repository.
"""
from __future__ import annotations

from typing import Optional

from apps.payments import services as payments_services
from apps.students import repository


def list_students(
    page: int = 1,
    page_size: int = 50,
    sort_by: str = 'full_name',
    sort_dir: str = 'asc',
    filters: Optional[dict] = None,
) -> dict:
    """Делегирует список учеников в repository."""
    return repository.list_students(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        filters=filters,
    )


def get_student(student_id: int) -> Optional[dict]:
    """Возвращает ученика или None."""
    return repository.get_student(student_id)


def create_student(data: dict) -> dict:
    """Создаёт ученика."""
    return repository.create_student(data)


def update_student(student_id: int, data: dict) -> Optional[dict]:
    """Обновляет ученика. Возвращает None если не найден."""
    return repository.update_student(student_id, data)


def soft_delete_student(student_id: int) -> bool:
    """Мягкое удаление (enrollment_status='not_enrolled'). Возвращает False если не найден."""
    return repository.soft_delete_student(student_id)


def student_stats(student_id: int) -> dict:
    """Сводка посещаемости ученика."""
    return repository.student_stats(student_id)


def get_student_balance(student_id: int) -> dict:
    """Баланс ученика по направлениям (постоянный дом — apps/payments/)."""
    return payments_services.get_student_balance(student_id)


def add_comment(student_id: int, body: str, author_id: Optional[int]):
    """Создаёт комментарий к ученику."""
    return repository.add_comment(student_id, body, author_id)


def delete_comment(student_id: int, comment_id: int) -> bool:
    """Удаляет комментарий. False если не найден."""
    return repository.delete_comment(student_id, comment_id)
