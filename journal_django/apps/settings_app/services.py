"""
SettingsService — тонкий слой между views и repository.

Никакого SQL здесь — всё через repository.
"""
from __future__ import annotations

from apps.settings_app import repository


def get_settings(account_id: int) -> dict:
    """Возвращает настройки аккаунта (или {} если нет)."""
    return repository.get_admin_settings(str(account_id))


def upsert_settings(account_id: int, settings_data: dict) -> dict:
    """Сохраняет настройки (INSERT ON CONFLICT UPDATE)."""
    return repository.upsert_admin_settings(str(account_id), settings_data)
