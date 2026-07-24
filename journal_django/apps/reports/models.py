"""
Раздел «Отчёты» — БЕЗ персистентных моделей.

Сформированные отчёты НЕ хранятся на платформе: задача генерации уходит в Celery,
готовый xlsx переносится эфемерно через celery result backend (Redis в проде /
in-memory локально) и стримится клиенту сразу по готовности. В нашу БД ничего не
пишется — поэтому здесь только перечисление типов отчётов, без models.Model.
"""
from __future__ import annotations

from django.db import models


class ReportType(models.TextChoices):
    RENEWALS_MONTH = 'renewals_month', 'Отчёт по продлениям (за месяц)'
    ACCOUNTING_MONTH = 'accounting_month', 'Бухгалтерский отчёт (за месяц)'
