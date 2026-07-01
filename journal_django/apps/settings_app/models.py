"""
Models for settings_app — managed=False, поверх существующей БД.

Таблица:
  admin_user_settings — per-account JSON настройки (видимость колонок и т.п.)

Схема из db/migrations/006_admin_user_settings.sql.
Ключ — username TEXT (account_id строкой, как в Express routes/admin/settings.js).
"""
from __future__ import annotations

from django.db import models

from apps.core.db_fields import TolerantJSONField


class AdminUserSettings(models.Model):
    """
    Per-admin клиентские настройки.

    Соответствует таблице `admin_user_settings`.
    PK — username (text), не serial.
    """

    username = models.TextField(primary_key=True)
    settings = TolerantJSONField(default=dict)
    updated_at = models.DateTimeField()

    class Meta:
        managed = True
        db_table = 'admin_user_settings'
