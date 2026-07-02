"""
Serializers for students.

StudentReadSerializer  — полный вывод ученика.
StudentWriteSerializer — ввод для POST (createStudentSchema).
StudentUpdateSerializer — ввод для PATCH (updateStudentSchema, все поля optional).

Правила валидации — точный порт Zod-схем из shared/schemas.js:
  createStudentSchema / updateStudentSchema.
"""
from __future__ import annotations

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
    phone = serializers.CharField(allow_null=True, allow_blank=True)
    school_grade = serializers.IntegerField(allow_null=True)
    platform_id = serializers.CharField(allow_null=True, allow_blank=True)
    parent_name = serializers.CharField(allow_null=True, allow_blank=True)
    first_purchase_date = DateStringField(allow_null=True)
    age = serializers.IntegerField(allow_null=True)
    pm = serializers.CharField(allow_null=True, allow_blank=True)
    enrollment_status = serializers.CharField()
    frozen_until_month = serializers.IntegerField(allow_null=True)
    created_at = serializers.DateTimeField()


class StudentWriteSerializer(serializers.Serializer):
    """
    Ввод для POST /api/admin/students (createStudentSchema).

    Обязательные поля: full_name.
    Бизнес-правило: frozen ↔ frozen_until_month != null.
    """

    full_name = serializers.CharField(min_length=1)
    birth_date = DateStringField(allow_null=True, required=False)
    phone = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    school_grade = serializers.IntegerField(min_value=1, max_value=11, allow_null=True, required=False)
    platform_id = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    parent_name = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    first_purchase_date = DateStringField(allow_null=True, required=False)
    age = serializers.IntegerField(min_value=0, max_value=120, allow_null=True, required=False)
    pm = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    enrollment_status = serializers.ChoiceField(choices=ENROLLMENT_STATUS_CHOICES, required=False)
    frozen_until_month = serializers.IntegerField(min_value=1, max_value=12, allow_null=True, required=False)

    def validate_full_name(self, value: str) -> str:
        return value.strip()

    def validate(self, data: dict) -> dict:
        """
        Бизнес-правило из createStudentSchema.refine():
          (enrollment_status === 'frozen') ↔ (frozen_until_month != null)
        Если enrollment_status не передан — пропускаем.
        """
        status = data.get('enrollment_status')
        if status is None:
            return data
        frozen_month = data.get('frozen_until_month')
        is_frozen = status == 'frozen'
        has_month = frozen_month is not None
        if is_frozen != has_month:
            raise serializers.ValidationError(
                'frozen status requires frozen_until_month'
            )
        return data


class StudentUpdateSerializer(serializers.Serializer):
    """
    Ввод для PATCH /api/admin/students/:id (updateStudentSchema).

    Все поля необязательны (partial по Zod .partial()).
    Бизнес-правило frozen/frozen_until_month на update НЕ проверяем — как в JS.
    """

    full_name = serializers.CharField(min_length=1, required=False)
    birth_date = DateStringField(allow_null=True, required=False)
    phone = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    school_grade = serializers.IntegerField(min_value=1, max_value=11, allow_null=True, required=False)
    platform_id = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    parent_name = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    first_purchase_date = DateStringField(allow_null=True, required=False)
    age = serializers.IntegerField(min_value=0, max_value=120, allow_null=True, required=False)
    pm = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    enrollment_status = serializers.ChoiceField(choices=ENROLLMENT_STATUS_CHOICES, required=False)
    frozen_until_month = serializers.IntegerField(min_value=1, max_value=12, allow_null=True, required=False)

    def validate_full_name(self, value: str) -> str:
        return value.strip()
