"""
Serializers for teacher_spa.

Порт submitLessonSchema из shared/schemas.js (lines 263-274).

VALID_LESSON_TYPES = ('regular', 'substitution', 'reschedule') — из lessonType enum.
date-поле — DateStringField (YYYY-MM-DD, без timezone drift).
"""
from __future__ import annotations

from rest_framework import serializers

from apps.core.fields import DateStringField
from apps.directions.models import Direction
from apps.payroll.models import Payroll

VALID_LESSON_TYPES = ('regular', 'substitution', 'reschedule')


class StudentAttendanceSerializer(serializers.Serializer):
    """Элемент списка студентов в submitLesson: {name: str, present: bool}."""

    name = serializers.CharField()
    present = serializers.BooleanField()


class SubmitLessonSerializer(serializers.Serializer):
    """
    Порт submitLessonSchema из shared/schemas.js.

    Обязательные: group, date, students.
    Необязательные: recordUrl, isSubstitution, originalTeacher, lessonType.
    """

    # Zod: z.string().optional() / lessonType.optional() — null НЕ принимается (Express 400).
    # Пустую строку z.string() принимает → allow_blank=True. z.string() не триммит →
    # trim_whitespace=False.
    group = serializers.CharField()
    date = DateStringField()
    recordUrl = serializers.CharField(
        allow_blank=True, required=False, trim_whitespace=False
    )
    students = StudentAttendanceSerializer(many=True)
    isSubstitution = serializers.BooleanField(required=False, default=False)
    originalTeacher = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=False
    )
    lessonType = serializers.ChoiceField(choices=VALID_LESSON_TYPES, required=False)


class MyLessonSerializer(serializers.Serializer):
    """
    Read-only элемент истории «Мои уроки» (GET /api/lessons).

    Payroll (1:1) может отсутствовать у исторических записей → все производные
    от него поля отдаются как None. Decimal-поля рендерятся строкой с масштабом
    (DateSafeJSONRenderer) — фронт приводит Number().
    """

    id = serializers.IntegerField()
    date = serializers.DateField(source='lesson_date')
    group = serializers.CharField(source='group.name')
    lessonNumber = serializers.DecimalField(
        source='lesson_number', max_digits=5, decimal_places=1
    )
    lessonType = serializers.CharField(source='lesson_type')
    isSubstitution = serializers.SerializerMethodField()
    originalTeacher = serializers.SerializerMethodField()
    recordUrl = serializers.CharField(source='record_url', allow_null=True)
    submittedAt = serializers.DateTimeField(source='submitted_at')
    direction = serializers.SerializerMethodField()
    directionColor = serializers.SerializerMethodField()
    presentCount = serializers.SerializerMethodField()
    totalCount = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()
    penalty = serializers.SerializerMethodField()

    def _payroll(self, obj):
        try:
            return obj.payroll
        except Payroll.DoesNotExist:
            return None

    def _direction(self, obj):
        try:
            return obj.group.direction
        except Direction.DoesNotExist:
            return None

    def get_direction(self, obj):
        d = self._direction(obj)
        return d.name if d else None

    def get_directionColor(self, obj):
        d = self._direction(obj)
        return d.color if d else None

    def get_isSubstitution(self, obj) -> bool:
        return obj.lesson_type == 'substitution'

    def get_originalTeacher(self, obj):
        return obj.original_teacher.name if obj.original_teacher_id else None

    def get_presentCount(self, obj):
        pr = self._payroll(obj)
        return pr.present_count if pr else None

    def get_totalCount(self, obj):
        pr = self._payroll(obj)
        return pr.total_students if pr else None

    def get_payment(self, obj):
        pr = self._payroll(obj)
        return str(pr.payment) if pr else None

    def get_penalty(self, obj):
        pr = self._payroll(obj)
        return str(pr.penalty) if pr else None
