"""
Models for groups — managed=False, поверх существующей БД.

Таблицы:
  groups                — группы занятий (soft-delete через active)
  group_schedule_slots  — расписание (день недели + время начала)

Схема из db/migrations/001_initial_schema.sql + 003_admin_soft_delete.sql.
date-поля хранятся как CharField(max_length=10) — защита от timezone drift
(та же стратегия, что services/db.js setTypeParser(1082, v => v)).
"""
from __future__ import annotations

from django.db import models


class Group(models.Model):
    """
    Группа занятий.

    Соответствует таблице `groups`.
    """

    id = models.AutoField(primary_key=True)
    name = models.TextField(unique=True)
    # FK → directions(id) / teachers(id). NO ACTION в БД → DO_NOTHING (managed=False).
    direction = models.ForeignKey(
        'directions.Direction',
        on_delete=models.DO_NOTHING,
        db_column='direction_id',
        related_name='groups',
    )
    teacher = models.ForeignKey(
        'teachers.Teacher',
        on_delete=models.DO_NOTHING,
        db_column='teacher_id',
        related_name='groups',
    )
    is_individual = models.BooleanField()
    lesson_duration_minutes = models.IntegerField(default=90)
    lessons_per_week = models.IntegerField(default=1)
    group_start_date = models.DateField(null=True, blank=True)
    vk_chat = models.TextField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = True
        db_table = 'groups'
        indexes = [
            models.Index(
                fields=['active'], name='groups_active_idx',
                condition=models.Q(active=True),
            ),
        ]
        constraints = [
            models.CheckConstraint(
                name='groups_lesson_duration_minutes_check',
                condition=models.Q(lesson_duration_minutes__in=[45, 60, 90]),
            ),
            models.CheckConstraint(
                name='groups_lessons_per_week_check',
                condition=models.Q(lessons_per_week__gte=1) & models.Q(lessons_per_week__lte=7),
            ),
        ]


class GroupScheduleSlot(models.Model):
    """
    Слот расписания группы.

    Соответствует таблице `group_schedule_slots`.
    """

    id = models.AutoField(primary_key=True)
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        db_column='group_id',
        related_name='schedule_slots',
    )
    day_of_week = models.IntegerField()
    start_time = models.TimeField()

    class Meta:
        managed = True
        db_table = 'group_schedule_slots'
        indexes = [
            models.Index(fields=['day_of_week', 'start_time'],
                         name='gss_dow_time_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['group', 'day_of_week', 'start_time'],
                name='group_schedule_slots_group_id_day_of_week_start_time_key',
            ),
            models.CheckConstraint(
                name='group_schedule_slots_day_of_week_check',
                condition=models.Q(day_of_week__gte=0) & models.Q(day_of_week__lte=6),
            ),
        ]
