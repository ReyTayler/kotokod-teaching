"""
GroupsService — тонкий слой бизнес-логики между views и repository.

Принцип: никакого SQL здесь — всё через repository.
Бизнес-правила (409 при дубле имени) обрабатываются во view.
"""
from __future__ import annotations

from typing import Any, Optional

from rest_framework.exceptions import ValidationError

from apps.groups import repository


def list_groups(
    page: int = 1,
    page_size: int = 50,
    sort_by: str = 'name',
    sort_dir: str = 'asc',
    filters: Optional[dict] = None,
) -> dict:
    """Делегирует список групп в repository."""
    return repository.list_groups(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        filters=filters,
    )


def get_group(group_id: int) -> Optional[dict]:
    """Возвращает группу или None."""
    return repository.get_group(group_id)


def create_group(data: dict) -> dict:
    """
    Создаёт группу.

    Поднимает ValidationError(409-style) при нарушении UNIQUE по имени.
    (pgcode 23505 — unique_violation)
    """
    from django.db import IntegrityError
    try:
        return repository.create_group(data)
    except IntegrityError as exc:
        # pg error code 23505 = unique_violation
        if _is_unique_violation(exc):
            raise ValidationError({'error': 'Already exists'}, code='conflict')
        raise


def update_group(group_id: int, data: dict) -> Optional[dict]:
    """Обновляет группу. Возвращает None если не найдена."""
    return repository.update_group(group_id, data)


def soft_delete_group(group_id: int) -> bool:
    """Мягкое удаление (active=false). Возвращает False если не найдена."""
    return repository.soft_delete_group(group_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_unique_violation(exc: Exception) -> bool:
    """Проверить, является ли IntegrityError нарушением уникальности (pgcode 23505)."""
    # psycopg2 кладёт pgcode в .pgcode или в .__cause__.pgcode
    pgcode: Any = getattr(exc, 'pgcode', None)
    if pgcode == '23505':
        return True
    cause = getattr(exc, '__cause__', None)
    if cause and getattr(cause, 'pgcode', None) == '23505':
        return True
    return False
