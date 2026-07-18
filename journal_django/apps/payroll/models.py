"""
Model for payroll — managed=False, поверх существующей таблицы `payroll`.

Схема из db/migrations/001_initial_schema.sql:
  payroll(id, lesson_id UNIQUE FK, teacher_id, total_students, present_count,
          payment numeric(10,2), penalty numeric(10,2)).
numeric-поля рендерятся строкой с масштабом ('500.00') — DateSafeJSONRenderer.
"""
from __future__ import annotations

import pghistory
from django.db import models


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class Payroll(models.Model):
    """Запись расчётного листа по уроку (1:1 с lessons)."""

    id = models.AutoField(primary_key=True)
    # FK → lessons(id), UNIQUE в БД → 1:1 (OneToOne). NO ACTION → DO_NOTHING.
    lesson = models.OneToOneField(
        'lessons.Lesson',
        on_delete=models.DO_NOTHING,
        db_column='lesson_id',
        related_name='payroll',
    )
    # FK → teachers(id). NO ACTION в БД → DO_NOTHING (managed=False).
    teacher = models.ForeignKey(
        'teachers.Teacher',
        on_delete=models.DO_NOTHING,
        db_column='teacher_id',
        related_name='payroll_entries',
    )
    total_students = models.IntegerField()
    present_count = models.IntegerField()
    # payment — БАЗОВАЯ оплата за урок, как он был изначально отчитан (present_count
    # без учёта учеников, отмеченных "сгоревшими" задним числом через
    # update_attendance_cell). Надбавка за такие правки — отдельно ниже, чтобы
    # зарплата за май не менялась молча, если правку внесли в июле (симметрично
    # LessonAttendance.burned_at — см. apps.lessons.repository.update_attendance_cell).
    payment = models.DecimalField(max_digits=10, decimal_places=2)
    penalty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Надбавка = calculate_payment(total, present_baseline+burned) - payment.
    # 0/NULL, если по этому уроку не было ни одного "сгорания".
    burn_surcharge_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, db_default=0,
    )
    burn_surcharge_at = models.DateField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = 'payroll'
        indexes = [
            models.Index(fields=['teacher', 'lesson'], name='payroll_teacher_lesson_idx'),
            models.Index(fields=['lesson'], name='payroll_lesson_id_idx'),
        ]
