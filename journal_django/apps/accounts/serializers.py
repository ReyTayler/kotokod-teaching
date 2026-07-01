"""
Serializers for accounts. Порт createAccountSchema/updateAccountSchema (shared/schemas.js).

createAccountSchema:
  email (trim+lowercase+email), role ∈ {teacher,manager,admin},
  teacher_id (positive int, nullable, optional),
  + refine: (role == 'teacher') == (teacher_id is not None).
updateAccountSchema: email/role/active — все optional, без refine.

⚠️ Вывода-сериализатора нет: views возвращают сырые dict из repository БЕЗ
секретов (password_hash, twofa_secret вырезаются в services).
"""
from __future__ import annotations

from rest_framework import serializers

ROLES = ('teacher', 'manager', 'admin')


class AccountCreateSerializer(serializers.Serializer):
    """Вход POST /api/admin/accounts."""

    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=ROLES)
    teacher_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)

    def validate_email(self, value: str) -> str:
        # Zod emailStr = trim().toLowerCase().email() — EmailField уже триммит.
        return value.strip().lower()

    def validate(self, attrs: dict) -> dict:
        # refine: teacher ⟺ teacher_id задан (и только teacher).
        # Принятое расхождение (status-equivalent): при провале этого refine Express
        # отдаёт details:{} (Zod .refine() пишет в formErrors, а validate.js шлёт только
        # fieldErrors), а DRF — details:{non_field_errors:[...]}. Статус 400 совпадает,
        # SPA ветвится по статусу. Полную байт-идентичность details всё равно недостижимо
        # из-за разных текстов сообщений Zod vs DRF (то же касается field-ошибок).
        is_teacher = attrs.get('role') == 'teacher'
        has_teacher = attrs.get('teacher_id') is not None
        if is_teacher != has_teacher:
            raise serializers.ValidationError(
                'teacher role requires teacher_id (and only teacher)'
            )
        return attrs


class AccountUpdateSerializer(serializers.Serializer):
    """Вход PATCH /api/admin/accounts/:id (все поля optional, без refine)."""

    email = serializers.EmailField(required=False)
    role = serializers.ChoiceField(choices=ROLES, required=False)
    active = serializers.BooleanField(required=False)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()
