"""
Models for tokens — managed=False, поверх существующей БД.

Таблица:
  tokens — токены для teacher SPA (soft-delete через active)

Схема из db/migrations/001_initial_schema.sql.
PK — token (text), не serial id.
"""
from __future__ import annotations

from django.db import models


class Token(models.Model):
    """
    Токен доступа для teacher SPA.

    Соответствует таблице `tokens`.
    PK — строковый token формата XXX-XXX-XXX.
    """

    token = models.TextField(primary_key=True)
    # FK → teachers(id). NO ACTION в БД → DO_NOTHING в ORM (managed=False).
    teacher = models.ForeignKey(
        'teachers.Teacher',
        on_delete=models.DO_NOTHING,
        db_column='teacher_id',
        related_name='tokens',
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = True
        db_table = 'tokens'
