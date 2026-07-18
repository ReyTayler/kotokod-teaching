"""
Models for extra_lessons — доп.уроки/резолюции пропусков, привязанные к
конкретному ученику, пропустившему основной (уже проведённый) урок.

AbsenceResolution — пер-ученик (1:1) «пропуск, требующий решения»: одна строка
на (пропущенный урок × ученик), scheduled (назначено) → done (проведено,
fact_lesson заполнен) | cancelled. Группа доп.урока отдельно не хранится — это
всегда группа missed_lesson. См.
docs/superpowers/specs/2026-07-18-unify-absences-makeup-burn-design.md.
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


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class AbsenceResolution(models.Model):
    """
    Пер-ученик (1:1) «пропуск, требующий решения» — заменила групповую пару
    ExtraLessonAssignment+ExtraLessonParticipant. Одна строка на (пропущенный
    урок × ученик). Статусы в Фазе 1a прежние (scheduled/done/cancelled). См.
    docs/superpowers/specs/2026-07-18-unify-absences-makeup-burn-design.md.
    """
    id = models.AutoField(primary_key=True)
    missed_lesson = models.ForeignKey('lessons.Lesson', on_delete=models.CASCADE,
                                      related_name='absence_resolutions')
    student = models.ForeignKey('students.Student', on_delete=models.PROTECT,
                                related_name='absence_resolutions')
    assigned_teacher = models.ForeignKey('teachers.Teacher', on_delete=models.PROTECT,
                                         null=True, blank=True, related_name='absence_resolutions')
    scheduled_date = models.DateField(null=True, blank=True)
    scheduled_time = models.TimeField(null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, default=SCHEDULED)
    fact_lesson = models.ForeignKey('lessons.Lesson', on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='absence_resolution_facts')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'absence_resolutions'
        indexes = [
            models.Index(fields=['status'], name='ar_status_idx'),
            models.Index(fields=['missed_lesson'], name='ar_missed_lesson_idx'),
            models.Index(fields=['assigned_teacher', 'scheduled_date'], name='ar_teacher_date_idx'),
            models.Index(fields=['student'], name='ar_student_idx'),
        ]
        constraints = [
            # Частичный уникальный: не более ОДНОЙ активной (не отменённой)
            # резолюции на (пропуск × ученик) — совпадает с guard'ом
            # repository.has_active_resolution (тот тоже исключает cancelled).
            # После отмены можно назначить заново (cancelled-строки не считаются),
            # как было в групповой модели.
            models.UniqueConstraint(fields=['missed_lesson', 'student'],
                                    condition=~models.Q(status=CANCELLED),
                                    name='absence_resolutions_missed_student_key'),
            models.CheckConstraint(name='absence_resolutions_status_check',
                                   condition=models.Q(status__in=STATUS_CHOICES)),
        ]
