"""
Models for lessons — managed=False, поверх существующей БД.

Таблицы:
  lessons            — урок (операционная запись посещаемости)
  lesson_attendance  — посещение (PK = lesson_id + student_id)

Схема из db/migrations/001_initial_schema.sql.
date-поля (lesson_date) хранятся как CharField(max_length=10) — защита от timezone
drift (та же стратегия, что services/db.js setTypeParser(1082, v => v)).
numeric-поля (lesson_number) — DecimalField, рендерер выдаёт строку с сохранением масштаба.
"""
from __future__ import annotations

from django.db import models


class Lesson(models.Model):
    """
    Урок. Соответствует таблице `lessons`.
    """

    id = models.AutoField(primary_key=True)
    # FK → groups(id) / teachers(id). NO ACTION в БД → DO_NOTHING (managed=False).
    group = models.ForeignKey(
        'groups.Group',
        on_delete=models.DO_NOTHING,
        db_column='group_id',
        related_name='lessons',
    )
    teacher = models.ForeignKey(
        'teachers.Teacher',
        on_delete=models.DO_NOTHING,
        db_column='teacher_id',
        related_name='lessons',
    )
    # FK → teachers(id), nullable (замена/подмена преподавателя).
    original_teacher = models.ForeignKey(
        'teachers.Teacher',
        on_delete=models.DO_NOTHING,
        db_column='original_teacher_id',
        related_name='lessons_as_original',
        null=True,
        blank=True,
    )
    lesson_date = models.DateField()
    # numeric(5,1) — поддержка half-lesson (0.5)
    lesson_number = models.DecimalField(max_digits=5, decimal_places=1)
    lesson_duration_minutes = models.IntegerField()
    lesson_type = models.TextField()
    record_url = models.TextField(null=True, blank=True)
    submitted_at = models.DateTimeField()
    submitted_by_token = models.TextField()

    class Meta:
        managed = True
        db_table = 'lessons'
        indexes = [
            models.Index(fields=['group', 'lesson_date'], name='lessons_group_date_idx'),
            models.Index(fields=['teacher', 'lesson_date'], name='lessons_teacher_date_idx'),
            models.Index(fields=['-lesson_date', '-id'], name='lessons_date_desc_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['lesson_date', 'group', 'lesson_number', 'submitted_by_token'],
                name='lessons_natural_key',
            ),
        ]


class LessonAttendance(models.Model):
    """
    Посещение урока. Соответствует таблице `lesson_attendance`.

    Реальный PK — составной (lesson_id, student_id). Django не выражает составной
    PK напрямую; lesson помечен primary_key для удовлетворения ORM. Раздел работает
    через raw SQL — ORM-модель только для документации/inspectdb-паритета.
    """

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        db_column='lesson_id',
        related_name='attendance',
        primary_key=True,
    )
    # FK → students(id). NO ACTION в БД → DO_NOTHING (managed=False).
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.DO_NOTHING,
        db_column='student_id',
        related_name='attendance',
    )
    present = models.BooleanField()

    class Meta:
        managed = True
        db_table = 'lesson_attendance'
        unique_together = (('lesson', 'student'),)
        indexes = [
            models.Index(fields=['student'], name='lesson_attendance_student_idx'),
        ]
