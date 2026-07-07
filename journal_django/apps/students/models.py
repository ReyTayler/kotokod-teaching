"""
Models for students — managed=False, поверх существующей БД.

Таблица students из db/migrations/001_initial_schema.sql.
DATE-поля (birth_date, first_purchase_date) хранятся как CharField(max_length=10)
для защиты от timezone drift — та же стратегия что в services/db.js setTypeParser(1082, v=>v).
"""
from __future__ import annotations

import pghistory
from django.db import models


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class Student(models.Model):
    """
    Ученик.

    Соответствует таблице `students`.
    """

    id = models.AutoField(primary_key=True)
    full_name = models.TextField(unique=True)
    birth_date = models.DateField(null=True, blank=True)
    phone = models.TextField(null=True, blank=True)
    school_grade = models.IntegerField(null=True, blank=True)
    platform_id = models.TextField(null=True, blank=True)
    parent_name = models.TextField(null=True, blank=True)
    first_purchase_date = models.DateField(null=True, blank=True)
    age = models.IntegerField(null=True, blank=True)
    pm = models.TextField(null=True, blank=True)
    enrollment_status = models.TextField(default='enrolled')
    frozen_until_month = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = True
        db_table = 'students'
        constraints = [
            models.CheckConstraint(
                name='students_school_grade_check',
                condition=models.Q(school_grade__gte=1) & models.Q(school_grade__lte=11),
            ),
            models.CheckConstraint(
                name='students_enrollment_status_check',
                condition=models.Q(enrollment_status__in=[
                    'enrolled', 'not_enrolled', 'frozen', 'declined']),
            ),
            models.CheckConstraint(
                name='students_frozen_until_month_check',
                condition=models.Q(frozen_until_month__gte=1) & models.Q(frozen_until_month__lte=12),
            ),
            models.CheckConstraint(
                name='students_check',
                condition=(
                    (models.Q(enrollment_status='frozen') & models.Q(frozen_until_month__isnull=False))
                    | (~models.Q(enrollment_status='frozen') & models.Q(frozen_until_month__isnull=True))
                ),
            ),
        ]
