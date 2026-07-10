"""
Serializers for payments.

PaymentCreateSerializer — порт paymentCreateSchema (shared/schemas.js:239-246):
  student_id / direction_id — int >= 1
  subscriptions_count       — int >= 1
  unit_price                — DecimalField(min_value=0)
  paid_at                   — DateStringField
  note                      — str max 500, nullable, optional
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.core.fields import DateStringField


class PaymentCreateSerializer(serializers.Serializer):
    student_id = serializers.IntegerField(min_value=1)
    direction_id = serializers.IntegerField(min_value=1)
    lessons_count = serializers.IntegerField(min_value=1)
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'))
    paid_at = DateStringField()
    note = serializers.CharField(max_length=500, allow_null=True, required=False, default=None)

    def validate_lessons_count(self, value):
        # Одна оплата: либо целые блоки (кратно 4), либо предоплата 1|2|3.
        if value % 4 == 0 or value in (1, 2, 3):
            return value
        raise serializers.ValidationError('lessons_count: кратно 4 (блоки) или 1–3 (предоплата)')
