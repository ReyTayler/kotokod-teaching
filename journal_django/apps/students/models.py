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
    platform_id = models.TextField(null=True, blank=True)
    bitrix24_link = models.TextField(null=True, blank=True)
    parent1_name = models.TextField(null=True, blank=True)
    parent1_phone = models.TextField(null=True, blank=True)
    parent1_email = models.TextField(null=True, blank=True)
    parent2_name = models.TextField(null=True, blank=True)
    parent2_phone = models.TextField(null=True, blank=True)
    parent2_email = models.TextField(null=True, blank=True)
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


class StudentComment(models.Model):
    """
    Комментарий менеджера/админа к ученику. Append-only: без UpdateEvent, без
    API редактирования. Не трекается pghistory — сам факт (author+created_at)
    уже виден в UI, отдельный changelog-след избыточен (осознанное отступление
    от общего правила CLAUDE.md, см. docs/superpowers/specs/2026-07-10-student-comments-design.md).
    """

    id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE,
        db_column='student_id', related_name='comments',
    )
    body = models.TextField()
    author = models.ForeignKey(
        'accounts.Account', on_delete=models.SET_NULL, null=True, blank=True,
        db_column='author_id', related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'student_comment'
        indexes = [
            models.Index(fields=['student', '-created_at'], name='student_comment_student_idx'),
        ]
