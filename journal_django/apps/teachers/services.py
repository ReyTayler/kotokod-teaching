"""
TeachersService — тонкий слой между views и repository.

Никакого SQL здесь — всё через repository.
"""
from __future__ import annotations

from typing import Optional

from apps.teachers import repository, stats


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


def get_teacher_stats(teacher_id: int, month: str) -> dict:
    """
    Полный набор чисел карточки преподавателя за месяц.

    Четыре агрегата (месяц, ряд по месяцам, дата последнего занятия, прогресс
    групп) склеиваются здесь, а не на фронте: иначе карточка делала бы четыре
    запроса вместо одного, а VPS у нас 2 CPU.
    """
    breakdown = stats.month_breakdown(teacher_id, month)
    return {
        'month': month,
        'last_lesson_date': stats.last_lesson_date(teacher_id),
        'total': breakdown['total'],
        'by_direction': breakdown['by_direction'],
        'by_duration': breakdown['by_duration'],
        'monthly': stats.monthly_series(teacher_id, month),
        'group_progress': stats.group_progress(teacher_id),
    }
