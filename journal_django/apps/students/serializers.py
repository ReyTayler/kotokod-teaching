"""
Serializers for students.

StudentReadSerializer  — полный вывод ученика.
StudentWriteSerializer — ввод для POST (createStudentSchema).
StudentUpdateSerializer — ввод для PATCH (updateStudentSchema, все поля optional).

Правила валидации — точный порт Zod-схем из shared/schemas.js:
  createStudentSchema / updateStudentSchema.
"""
from __future__ import annotations

from datetime import date

from rest_framework import serializers

from apps.core.fields import DateStringField

# Допустимые значения enrollment_status (из shared/schemas.js enrollmentStatus)
ENROLLMENT_STATUS_CHOICES = ('enrolled', 'not_enrolled', 'frozen', 'declined')


class StudentReadSerializer(serializers.Serializer):
    """
    Полный вывод ученика.

    Используется для to_representation — поля совпадают с таблицей students.
    """

    id = serializers.IntegerField()
    full_name = serializers.CharField()
    birth_date = DateStringField(allow_null=True)
    platform_id = serializers.CharField(allow_null=True, allow_blank=True)
    bitrix24_link = serializers.CharField(allow_null=True, allow_blank=True)
    parent1_name = serializers.CharField(allow_null=True, allow_blank=True)
    parent1_phone = serializers.CharField(allow_null=True, allow_blank=True)
    parent1_email = serializers.CharField(allow_null=True, allow_blank=True)
    parent2_name = serializers.CharField(allow_null=True, allow_blank=True)
    parent2_phone = serializers.CharField(allow_null=True, allow_blank=True)
    parent2_email = serializers.CharField(allow_null=True, allow_blank=True)
    first_purchase_date = DateStringField(allow_null=True)
    age = serializers.IntegerField(allow_null=True)
    pm = serializers.CharField(allow_null=True, allow_blank=True)
    enrollment_status = serializers.CharField()
    frozen_from = DateStringField(allow_null=True)
    frozen_until = DateStringField(allow_null=True)
    created_at = serializers.DateTimeField()


class StudentWriteSerializer(serializers.Serializer):
    """
    Ввод для POST /api/admin/students (createStudentSchema).

    Обязательные поля: full_name.
    Бизнес-правило: frozen ↔ обе даты frozen_from/frozen_until заданы.
    """

    full_name = serializers.CharField(min_length=1)
    birth_date = DateStringField(allow_null=True, required=False)
    platform_id = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    bitrix24_link = serializers.URLField(allow_null=True, allow_blank=True, required=False)
    parent1_name = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    parent1_phone = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    parent1_email = serializers.EmailField(allow_null=True, allow_blank=True, required=False)
    parent2_name = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    parent2_phone = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    parent2_email = serializers.EmailField(allow_null=True, allow_blank=True, required=False)
    first_purchase_date = DateStringField(allow_null=True, required=False)
    age = serializers.IntegerField(min_value=0, max_value=120, allow_null=True, required=False)
    pm = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    enrollment_status = serializers.ChoiceField(choices=ENROLLMENT_STATUS_CHOICES, required=False)
    frozen_from = DateStringField(allow_null=True, required=False)
    frozen_until = DateStringField(allow_null=True, required=False)

    def validate_full_name(self, value: str) -> str:
        return value.strip()

    def validate(self, data: dict) -> dict:
        """frozen ⟺ обе даты заданы. Пропускаем, если статус не передан."""
        status = data.get('enrollment_status')
        if status is None:
            return data
        has_dates = data.get('frozen_from') is not None and data.get('frozen_until') is not None
        if (status == 'frozen') != has_dates:
            raise serializers.ValidationError(
                'frozen status requires frozen_from and frozen_until')
        return data


class StudentUpdateSerializer(serializers.Serializer):
    """
    Ввод для PATCH /api/admin/students/:id (updateStudentSchema).

    Все поля необязательны (partial по Zod .partial()).
    Бизнес-правило frozen/frozen_from/frozen_until на update НЕ проверяем — как в JS.
    """

    full_name = serializers.CharField(min_length=1, required=False)
    birth_date = DateStringField(allow_null=True, required=False)
    platform_id = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    bitrix24_link = serializers.URLField(allow_null=True, allow_blank=True, required=False)
    parent1_name = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    parent1_phone = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    parent1_email = serializers.EmailField(allow_null=True, allow_blank=True, required=False)
    parent2_name = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    parent2_phone = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    parent2_email = serializers.EmailField(allow_null=True, allow_blank=True, required=False)
    first_purchase_date = DateStringField(allow_null=True, required=False)
    age = serializers.IntegerField(min_value=0, max_value=120, allow_null=True, required=False)
    pm = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    enrollment_status = serializers.ChoiceField(choices=ENROLLMENT_STATUS_CHOICES, required=False)
    frozen_from = DateStringField(allow_null=True, required=False)
    frozen_until = DateStringField(allow_null=True, required=False)

    def validate_full_name(self, value: str) -> str:
        return value.strip()


class StudentCommentSerializer(serializers.Serializer):
    """Read-only элемент списка комментариев (GET .../comments)."""

    id = serializers.IntegerField()
    body = serializers.CharField()
    created_at = serializers.DateTimeField()
    author_id = serializers.IntegerField(allow_null=True)
    author_name = serializers.SerializerMethodField()

    def get_author_name(self, obj) -> str | None:
        return obj.author.full_name if obj.author_id and obj.author else None


class StudentCommentWriteSerializer(serializers.Serializer):
    """Ввод для POST .../comments."""

    body = serializers.CharField(max_length=5000, allow_blank=False)

    def validate_body(self, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError('body must not be blank')
        return stripped


class StudentStatusSerializer(serializers.Serializer):
    """Ввод POST /students/:id/status. frozen ⟺ обе даты; membership_ids опц."""
    status = serializers.ChoiceField(choices=ENROLLMENT_STATUS_CHOICES)
    frozen_from = DateStringField(required=False, allow_null=True)
    frozen_until = DateStringField(required=False, allow_null=True)
    membership_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True)

    def validate(self, data: dict) -> dict:
        if data['status'] == 'frozen':
            if not data.get('frozen_from') or not data.get('frozen_until'):
                raise serializers.ValidationError(
                    'frozen requires frozen_from and frozen_until')
            if date.fromisoformat(data['frozen_from']) > date.fromisoformat(data['frozen_until']):
                raise serializers.ValidationError('frozen_from must be <= frozen_until')
        else:
            if data.get('frozen_from') or data.get('frozen_until'):
                raise serializers.ValidationError(
                    'frozen_from/frozen_until only allowed for frozen status')
        return data


class StudentResumeSerializer(serializers.Serializer):
    """Ввод POST /students/:id/resume."""
    actual_resume_date = DateStringField()
