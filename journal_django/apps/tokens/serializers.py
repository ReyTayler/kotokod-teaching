"""
Serializers for tokens.

TokenReadSerializer   — вывод токена (включая teacher_name из JOIN).
TokenWriteSerializer  — ввод для POST (createTokenSchema).
TokenUpdateSerializer — ввод для PATCH (updateTokenSchema).

Правила валидации — точный порт Zod-схем из shared/schemas.js:
  createTokenSchema:
    token: z.string().regex(/^[A-Z2-9]{3}-[A-Z2-9]{3}-[A-Z2-9]{3}$/)
    teacher_id: id (positive int)
  updateTokenSchema:
    teacher_id: id.optional()
    active: z.boolean().optional()

PK — token (text), не serial id.
"""
from __future__ import annotations

import re

from rest_framework import serializers

_TOKEN_RE = re.compile(r'^[A-Z2-9]{3}-[A-Z2-9]{3}-[A-Z2-9]{3}$')


class TokenReadSerializer(serializers.Serializer):
    """Вывод токена со всеми полями + teacher_name из JOIN."""

    token = serializers.CharField()
    teacher_id = serializers.IntegerField()
    active = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    # Из JOIN teachers
    teacher_name = serializers.CharField(allow_null=True, required=False)


class TokenWriteSerializer(serializers.Serializer):
    """
    Вход для POST /api/admin/tokens (createTokenSchema).

    token: XXX-XXX-XXX (алфавит [A-Z2-9], без 0/O/1/I)
    teacher_id: positive int
    """

    token = serializers.CharField()
    teacher_id = serializers.IntegerField(min_value=1)

    def validate_token(self, value: str) -> str:
        if not _TOKEN_RE.match(value):
            raise serializers.ValidationError(
                'Token must match XXX-XXX-XXX format (uppercase letters A-Z except O, digits 2-9).'
            )
        return value


class TokenUpdateSerializer(serializers.Serializer):
    """
    Вход для PATCH /api/admin/tokens/:token (updateTokenSchema).

    Все поля необязательны.
    """

    teacher_id = serializers.IntegerField(min_value=1, required=False)
    active = serializers.BooleanField(required=False)
