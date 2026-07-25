"""Сериализаторы renewals. Read — из dict repository; write — валидация входа."""
from __future__ import annotations

from rest_framework import serializers


class DealCreateSerializer(serializers.Serializer):
    """Ручное создание сделки ученику (из сводки «Ученики без сделок»)."""
    student_id = serializers.IntegerField()


class MoveSerializer(serializers.Serializer):
    to_stage_id = serializers.IntegerField()
    reason_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    # «До какого месяца заморозка». Обязателен при переходе в стадию 'frozen',
    # на других стадиях игнорируется. День из ввода отбрасывается — храним 1-е число.
    frozen_until_month = serializers.DateField(required=False, allow_null=True)

    def validate(self, data: dict) -> dict:
        from apps.renewals.models import RenewalStage
        from apps.renewals.transitions import FROZEN_KEY

        key = (RenewalStage.objects
               .filter(id=data['to_stage_id']).values_list('key', flat=True).first())
        month = data.get('frozen_until_month')
        if key == FROZEN_KEY:
            if month is None:
                raise serializers.ValidationError(
                    {'frozen_until_month': 'Укажите, до какого месяца заморозка'})
            data['frozen_until_month'] = month.replace(day=1)
        else:
            data['frozen_until_month'] = None
        return data


class DealPatchSerializer(serializers.Serializer):
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
