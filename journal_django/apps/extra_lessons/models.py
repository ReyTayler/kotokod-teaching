"""
Models for extra_lessons — доп.уроки, назначаемые отдельным ученикам группы,
пропустившим конкретный основной (уже проведённый) урок.

ExtraLessonAssignment — «оболочка» по аналогии с scheduling.PlannedLesson:
scheduled (назначено) → done (проведено, fact_lesson заполнен) | cancelled.
Группа доп.урока отдельно не хранится — это всегда группа missed_lesson
(участники объединены вокруг одного пропущенного урока, см.
docs/superpowers/specs/2026-07-15-extra-lessons-design.md).
"""
from __future__ import annotations

import pghistory
from django.db import models

SCHEDULED = 'scheduled'
DONE = 'done'
CANCELLED = 'cancelled'
STATUS_CHOICES = [SCHEDULED, DONE, CANCELLED]

# Совпадает с VALID_LESSON_DURATIONS admin-формы обычных уроков + 30 мин
# (доп.урок может быть короче группового занятия).
VALID_DURATIONS = (30, 45, 60, 90)


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class ExtraLessonAssignment(models.Model):
    """Назначение доп.урока — компенсация пропуска ОДНОГО основного урока."""

    id = models.AutoField(primary_key=True)
    teacher = models.ForeignKey(
        'teachers.Teacher',
        on_delete=models.PROTECT,
        related_name='extra_lesson_assignments',
    )
    # Пропущенный основной урок (факт) — ОДИН на всё назначение. Обязан быть
    # уже проведённым (валидация — apps.extra_lessons.services.create_assignment).
    missed_lesson = models.ForeignKey(
        'lessons.Lesson',
        on_delete=models.PROTECT,
        related_name='extra_lesson_assignments',
    )
    students = models.ManyToManyField(
        'students.Student',
        through='ExtraLessonParticipant',
        related_name='extra_lesson_assignments',
    )
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField()
    duration_minutes = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=16, default=SCHEDULED)
    # Факт проведения доп.урока (lessons.Lesson lesson_type='extra'). Заполняется
    # при записи (record), возвращается в NULL при откате (delete_fact).
    fact_lesson = models.OneToOneField(
        'lessons.Lesson',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='extra_lesson_assignment',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'extra_lesson_assignments'
        indexes = [
            models.Index(fields=['teacher', 'scheduled_date'], name='ela_teacher_date_idx'),
            models.Index(fields=['missed_lesson'], name='ela_missed_lesson_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                name='extra_lesson_assignments_status_check',
                condition=models.Q(status__in=STATUS_CHOICES),
            ),
            models.CheckConstraint(
                name='extra_lesson_assignments_duration_check',
                condition=models.Q(duration_minutes__in=VALID_DURATIONS),
            ),
        ]


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class ExtraLessonParticipant(models.Model):
    """Участник доп.урока (through-модель ExtraLessonAssignment ↔ Student)."""

    id = models.AutoField(primary_key=True)
    assignment = models.ForeignKey(
        ExtraLessonAssignment,
        on_delete=models.CASCADE,
        related_name='participants',
    )
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.PROTECT,
        related_name='extra_lesson_participations',
    )

    class Meta:
        managed = True
        db_table = 'extra_lesson_participants'
        constraints = [
            models.UniqueConstraint(
                fields=['assignment', 'student'],
                name='extra_lesson_participants_assignment_student_key',
            ),
        ]
