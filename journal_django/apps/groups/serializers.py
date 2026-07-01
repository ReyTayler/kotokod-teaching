"""
Serializers for groups.

GroupScheduleSlotSerializer  — вложенное представление слота расписания.
GroupReadSerializer          — полный вывод группы со слотами.
GroupWriteSerializer         — ввод для POST (createGroupSchema).
GroupUpdateSerializer        — ввод для PATCH (updateGroupSchema, все поля необязательны).

Правила валидации — точный порт Zod-схем из shared/schemas.js:
  createGroupSchema / updateGroupSchema.
"""
from __future__ import annotations

import re

from rest_framework import serializers

from apps.core.fields import DateStringField

# ---- константы из Zod-схем ----
VALID_LESSON_DURATIONS = (45, 60, 90)
VALID_SLOT_TIME_RE = re.compile(r'^\d{2}:\d{2}(:\d{2})?$')


class GroupScheduleSlotSerializer(serializers.Serializer):
    """
    Слот расписания (day_of_week, start_time).

    Используется как вложенный список в GroupReadSerializer и как вход
    в write-сериализаторах.

    day_of_week: 0–6 (0=понедельник), соответствует Zod dayOfWeek.
    start_time:  HH:MM или HH:MM:SS, соответствует Zod timeStr.
    """

    day_of_week = serializers.IntegerField(min_value=0, max_value=6)
    start_time = serializers.CharField()

    def validate_start_time(self, value: str) -> str:
        if not VALID_SLOT_TIME_RE.match(value):
            raise serializers.ValidationError(
                'start_time must match HH:MM or HH:MM:SS format.'
            )
        return value


class GroupReadSerializer(serializers.Serializer):
    """
    Вывод группы со всеми полями + вложенные слоты расписания.

    Используется только для to_representation — direction_name, teacher_name
    добавляются raw-SQL запросом.
    """

    id = serializers.IntegerField()
    name = serializers.CharField()
    direction_id = serializers.IntegerField()
    teacher_id = serializers.IntegerField()
    is_individual = serializers.BooleanField()
    lesson_duration_minutes = serializers.IntegerField()
    lessons_per_week = serializers.IntegerField()
    group_start_date = DateStringField(allow_null=True)
    vk_chat = serializers.CharField(allow_null=True, allow_blank=True)
    active = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    # Поля из JOIN — присутствуют только в списке (listGroups)
    direction_name = serializers.CharField(allow_null=True, required=False)
    direction_color = serializers.CharField(allow_null=True, required=False)
    teacher_name = serializers.CharField(allow_null=True, required=False)
    # Вложенные слоты
    slots = GroupScheduleSlotSerializer(many=True)


class GroupWriteSerializer(serializers.Serializer):
    """
    Вход для POST /api/admin/groups (createGroupSchema).

    Обязательные поля:
      name, direction_id, teacher_id, is_individual,
      lesson_duration_minutes, lessons_per_week.
    """

    name = serializers.CharField(min_length=1)
    direction_id = serializers.IntegerField(min_value=1)
    teacher_id = serializers.IntegerField(min_value=1)
    is_individual = serializers.BooleanField()
    lesson_duration_minutes = serializers.ChoiceField(choices=VALID_LESSON_DURATIONS)
    lessons_per_week = serializers.IntegerField(min_value=1, max_value=7)
    group_start_date = DateStringField(allow_null=True, required=False)
    vk_chat = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    slots = GroupScheduleSlotSerializer(many=True, required=False)

    def validate_name(self, value: str) -> str:
        return value.strip()


class GroupUpdateSerializer(serializers.Serializer):
    """
    Вход для PATCH /api/admin/groups/:id (updateGroupSchema).

    Все поля необязательны (partial по Zod .partial()).
    Дополнительно: active (boolean) — для ручной активации/деактивации.
    """

    name = serializers.CharField(min_length=1, required=False)
    direction_id = serializers.IntegerField(min_value=1, required=False)
    teacher_id = serializers.IntegerField(min_value=1, required=False)
    is_individual = serializers.BooleanField(required=False)
    lesson_duration_minutes = serializers.ChoiceField(
        choices=VALID_LESSON_DURATIONS, required=False
    )
    lessons_per_week = serializers.IntegerField(min_value=1, max_value=7, required=False)
    group_start_date = DateStringField(allow_null=True, required=False)
    vk_chat = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    slots = GroupScheduleSlotSerializer(many=True, required=False)
    active = serializers.BooleanField(required=False)

    def validate_name(self, value: str) -> str:
        return value.strip()
