"""
Serializers for teacher_spa.

Порт submitLessonSchema из shared/schemas.js (lines 263-274).

VALID_LESSON_TYPES = ('regular', 'substitution', 'reschedule') — из lessonType enum.
date-поле — DateStringField (YYYY-MM-DD, без timezone drift).
"""
from __future__ import annotations

from rest_framework import serializers

from apps.core.fields import DateStringField

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
