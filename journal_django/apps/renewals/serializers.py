"""Сериализаторы renewals. Read — из dict repository; write — валидация входа."""
from __future__ import annotations

from rest_framework import serializers


class MoveSerializer(serializers.Serializer):
    to_stage_id = serializers.IntegerField()
    reason_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class DealPatchSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField(required=False, allow_null=True)
    next_touch_at = serializers.DateField(required=False, allow_null=True)
    reason_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    expected_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True)


class CommentSerializer(serializers.Serializer):
    body = serializers.CharField()
