"""
Сериализаторы-валидаторы admin-операций плана (planned_lessons).

Строгая валидация входа каждой мутации (шаг 4). Стиль зеркалит
apps/groups/serializers.py (ScheduleChangeSerializer):
даты — DateStringField ('YYYY-MM-DD'), время — HH:MM(:SS), day_of_week 0..6 (Вс=0).

Лишние поля не принимаются молча — StrictSerializer.validate отклоняет неизвестные
ключи (чтобы опечатка в имени поля не проходила тихо мимо валидации).
"""
from __future__ import annotations

import re

from rest_framework import serializers

from apps.core.fields import DateStringField

# Время слота/занятия: HH:MM или HH:MM:SS (как VALID_SLOT_TIME_RE в groups).
_TIME_RE = re.compile(r'^\d{2}:\d{2}(:\d{2})?$')


def _validate_time(value):
    """Проверить формат HH:MM(:SS); None/'' пропускаем (optional-поля)."""
    if value in (None, ''):
        return value
    if not _TIME_RE.match(value):
        raise serializers.ValidationError('Время должно быть в формате HH:MM или HH:MM:SS.')
    return value


class StrictSerializer(serializers.Serializer):
    """Базовый сериализатор, отклоняющий неизвестные поля (не «глотать» опечатки)."""

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {k: 'Неизвестное поле.' for k in sorted(unknown)}
            )
        return attrs


class PlanRescheduleSerializer(StrictSerializer):
    """POST /plan/<lid>/reschedule — разовый перенос (+опц. время/преподаватель)."""

    new_date = DateStringField()
    new_time = serializers.CharField(required=False, allow_null=True)
    new_teacher_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_new_time(self, value):
        return _validate_time(value)


class PlanPermanentChangeSerializer(StrictSerializer):
    """POST /plan/permanent-change — перенос навсегда (с позиции from_seq).

    effective_from НЕ принимается от клиента: граница нового слота выводится на
    сервере из новой даты строки seq=from_seq (см. repository.permanent_change),
    чтобы версионирование слота и сдвиг хвоста не разъезжались. Лишний
    effective_from в теле → 400 (StrictSerializer отклоняет неизвестные поля)."""

    from_seq = serializers.IntegerField(min_value=1)
    new_day_of_week = serializers.IntegerField(min_value=0, max_value=6)
    new_time = serializers.CharField(required=False, allow_null=True)
    new_teacher_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_new_time(self, value):
        return _validate_time(value)


class PlanChangeTeacherSerializer(StrictSerializer):
    """POST /plan/<lid>/change-teacher — разовая смена преподавателя одной строки."""

    new_teacher_id = serializers.IntegerField(min_value=1)


class PlanChangeTeacherPermanentSerializer(StrictSerializer):
    """POST /plan/change-teacher-permanent — смена преподавателя хвоста (seq>=from_seq)."""

    from_seq = serializers.IntegerField(min_value=1)
    new_teacher_id = serializers.IntegerField(min_value=1)


class PlanExtraSerializer(StrictSerializer):
    """POST /plan/extra — доп. занятие вне курса (seq=NULL)."""

    date = DateStringField()
    time = serializers.CharField()
    teacher_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_time(self, value):
        if not value or not _TIME_RE.match(value):
            raise serializers.ValidationError('Время должно быть в формате HH:MM или HH:MM:SS.')
        return value
