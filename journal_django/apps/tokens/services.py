"""
TokensService — тонкий слой между views и repository.

Никакого SQL здесь — всё через repository.
"""
from __future__ import annotations

from typing import Optional

from apps.tokens import repository


def generate_random_token() -> str:
    """Генерирует случайный токен XXX-XXX-XXX."""
    return repository.generate_random_token()


def list_tokens(include_inactive: bool = False) -> list[dict]:
    """Делегирует список токенов в repository."""
    return repository.list_tokens(include_inactive=include_inactive)


def create_token(data: dict) -> dict:
    """Создаёт токен. 409 при UniqueViolation поднимает view."""
    return repository.create_token(data)


def update_token(token: str, data: dict) -> Optional[dict]:
    """Обновляет токен. Возвращает None если не найден."""
    return repository.update_token(token, data)


def revoke_token(token: str) -> bool:
    """Отзывает токен (active=false). Возвращает False если не найден."""
    return repository.revoke_token(token)
