"""
Сериализаторы-валидаторы extra_lessons. StrictSerializer — тот же паттерн,
что apps/scheduling/serializers.py (отклонять неизвестные поля).
"""
from __future__ import annotations

import re

from rest_framework import serializers

from apps.core.fields import DateStringField
from apps.extra_lessons.models import VALID_DURATIONS

_TIME_RE = re.compile(r'^\d{2}:\d{2}(:\d{2})?$')


class StrictSerializer(serializers.Serializer):
    """Базовый сериализатор, отклоняющий неизвестные поля."""

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {k: 'Неизвестное поле.' for k in sorted(unknown)}
            )
        return attrs


class ExtraLessonCreateSerializer(StrictSerializer):
    """POST /api/admin/extra-lessons — назначить доп.урок."""

    missed_lesson_id = serializers.IntegerField(min_value=1)
    teacher_id = serializers.IntegerField(min_value=1)
    student_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False,
    )
    scheduled_date = DateStringField()
    scheduled_time = serializers.CharField()
    duration_minutes = serializers.ChoiceField(choices=VALID_DURATIONS)

    def validate_scheduled_time(self, value):
        if not value or not _TIME_RE.match(value):
            raise serializers.ValidationError('Время должно быть в формате HH:MM или HH:MM:SS.')
        return value

    def validate_student_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError('Ученики не должны повторяться.')
        return value


class ExtraLessonAttendanceItemSerializer(serializers.Serializer):
    student_id = serializers.IntegerField(min_value=1)
    present = serializers.BooleanField()


class ExtraLessonRecordSerializer(StrictSerializer):
    """POST /api/extra-lessons/:id/record — фиксация проведения (teacher)."""

    record_url = serializers.CharField(
        allow_null=True, allow_blank=True, required=False, trim_whitespace=False,
    )
    attendance = ExtraLessonAttendanceItemSerializer(many=True, allow_empty=False)
