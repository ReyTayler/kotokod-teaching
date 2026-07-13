"""Сериализаторы renewals. Read — из dict repository; write — валидация входа."""
from __future__ import annotations

from rest_framework import serializers


class DealCreateSerializer(serializers.Serializer):
    """Ручное создание сделки ученику (из сводки «Ученики без сделок»)."""
    student_id = serializers.IntegerField()


class MoveSerializer(serializers.Serializer):
    to_stage_id = serializers.IntegerField()
    reason_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class DealPatchSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField(required=False, allow_null=True)
    next_touch_at = serializers.DateField(required=False, allow_null=True)
    reason_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class CommentSerializer(serializers.Serializer):
    body = serializers.CharField()


class StageWriteSerializer(serializers.Serializer):
    label = serializers.CharField()
    color = serializers.RegexField(r'^#[0-9a-fA-F]{6}$', required=False, allow_null=True)
    kind = serializers.ChoiceField(choices=['progress', 'decision', 'won', 'lost'])
    key = serializers.RegexField(r'^[a-z0-9_]+$', required=False)


class StageReorderSerializer(serializers.Serializer):
    order = serializers.ListField(child=serializers.IntegerField())  # stage_id в новом порядке
