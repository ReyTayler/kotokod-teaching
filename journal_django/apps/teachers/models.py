"""
Models for teachers — managed=False, поверх существующей БД.

Таблица:
  teachers — преподаватели (soft-delete через active)

Схема из db/migrations/001_initial_schema.sql + 003_admin_soft_delete.sql.
"""
from __future__ import annotations

import pghistory
from django.db import models


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class Teacher(models.Model):
    """
    Преподаватель.

    Соответствует таблице `teachers`.
    """

    id = models.AutoField(primary_key=True)
    name = models.TextField(unique=True)
    email = models.TextField(null=True, blank=True)
    phone = models.TextField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = True
        db_table = 'teachers'
        indexes = [
            models.Index(
                fields=['active'], name='teachers_active_idx',
                condition=models.Q(active=True),
            ),
        ]
