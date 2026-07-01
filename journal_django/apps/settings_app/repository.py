"""
SettingsRepository — единственное место с SQL для раздела settings_app.

SQL перенесён дословно из services/repo/settings.js.

Ключ настроек — username = str(account_id) из сессии.
Хранится как JSONB (произвольный объект).

Особенность: username в таблице — text PK. После перехода на RBAC
ключом стал account_id (строкой), а не имя пользователя.
"""
from __future__ import annotations

import json

from django.utils import timezone

from .models import AdminUserSettings


# ---------------------------------------------------------------------------
# Repository functions (ORM-порт логики services/repo/settings.js)
# ---------------------------------------------------------------------------

def _as_dict(val) -> dict:
    """JSONField обычно возвращает dict; подстраховка на случай строки jsonb."""
    if isinstance(val, str):
        return json.loads(val)
    return val if val else {}


def get_admin_settings(username: str) -> dict:
    """
    Возвращает настройки аккаунта или пустой dict.

    ORM-эквивалент: SELECT settings FROM admin_user_settings WHERE username = %s
    """
    val = (
        AdminUserSettings.objects
        .filter(username=username)
        .values_list('settings', flat=True)
        .first()
    )
    if val is None:
        return {}
    return _as_dict(val)


def upsert_admin_settings(username: str, settings_data: dict) -> dict:
    """
    Сохраняет настройки (INSERT ... ON CONFLICT (username) DO UPDATE).

    ORM-эквивалент через update_or_create() (паттерн 4.9). updated_at
    обновляется так же, как `now()` в исходном SQL.
    """
    obj, _ = AdminUserSettings.objects.update_or_create(
        username=username,
        defaults={'settings': settings_data or {}, 'updated_at': timezone.now()},
    )
    return _as_dict(obj.settings)
