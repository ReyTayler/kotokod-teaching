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
    subscriptions_count = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=6, min_value=Decimal('0'))
    paid_at = DateStringField()
    note = serializers.CharField(max_length=500, allow_null=True, required=False, default=None)
