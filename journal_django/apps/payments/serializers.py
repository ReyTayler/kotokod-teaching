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
    # direction_id/lessons_count — обязательны для purchase/extra, но у доплаты
    # (kind='surcharge') их нет: направление берётся у родителя, уроков не добавляет.
    # required=False на уровне поля + явная проверка в validate() ниже.
    direction_id = serializers.IntegerField(min_value=1, required=False)
    lessons_count = serializers.IntegerField(min_value=1, required=False)
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'))
    paid_at = DateStringField()
    note = serializers.CharField(max_length=500, allow_null=True, required=False, default=None)
    # kind='extra' — доплата сверх курса (мимо лимита).
    # kind='surcharge' — доплата к уже купленному абонементу (деньги без уроков).
    # По умолчанию 'purchase'.
    kind = serializers.ChoiceField(choices=['purchase', 'extra', 'surcharge'], required=False, default='purchase')
    parent_payment_id = serializers.IntegerField(min_value=1, required=False)
    subscription_index = serializers.IntegerField(min_value=1, required=False)

    def validate_lessons_count(self, value):
        # Одна оплата: либо целые блоки (кратно 4), либо предоплата 1|2|3.
        if value % 4 == 0 or value in (1, 2, 3):
            return value
        raise serializers.ValidationError('lessons_count: кратно 4 (блоки) или 1–3 (предоплата)')

    def validate(self, attrs):
        if attrs.get('kind') == 'surcharge':
            missing = [f for f in ('parent_payment_id', 'subscription_index')
                       if attrs.get(f) is None]
            if missing:
                raise serializers.ValidationError(
                    {f: 'Обязательно для доплаты' for f in missing})
            attrs.pop('lessons_count', None)
            return attrs
        for field in ('direction_id', 'lessons_count'):
            if attrs.get(field) is None:
                raise serializers.ValidationError({field: 'Обязательное поле'})
        return attrs
