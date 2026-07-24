"""Сериализаторы параметров отчётов раздела «Отчёты»."""
from __future__ import annotations

from rest_framework import serializers

from apps.core.utils.dates import msk_now


class RenewalsReportParamsSerializer(serializers.Serializer):
    """Параметры «Отчёта по продлениям»: год и месяц."""
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    month = serializers.IntegerField(min_value=1, max_value=12)

    def validate(self, attrs: dict) -> dict:
        # Месяц не может быть в будущем — отчёта по нему ещё нет. Дата — по МСК,
        # не по системным часам процесса (date.today() читает часовой пояс ОС,
        # который необязательно московский).
        today = msk_now().date()
        if (attrs['year'], attrs['month']) > (today.year, today.month):
            raise serializers.ValidationError({'month': 'Месяц ещё не наступил.'})
        return attrs


class AccountingReportParamsSerializer(serializers.Serializer):
    """Параметры «Бухгалтерского отчёта»: месяц строкой YYYY-MM (формат
    apps.finances.reports.collect_monthly_report)."""
    month = serializers.RegexField(
        r'^\d{4}-(0[1-9]|1[0-2])$', error_messages={'invalid': 'Ожидается месяц в формате YYYY-MM.'})

    def validate_month(self, value: str) -> str:
        y, m = (int(x) for x in value.split('-'))
        today = msk_now().date()
        if (y, m) > (today.year, today.month):
            raise serializers.ValidationError('Месяц ещё не наступил.')
        return value
