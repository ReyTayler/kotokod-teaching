"""
Celery-задачи dashboard (Фаза 3, спека 2026-07-11).

Пока одна — прогрев кэша СВОДКИ «Реестра куратора». Модуль импортируется
Celery-автодискавером ТОЛЬКО когда воркер/beat запущены (прод). Локально, где
пакет celery не установлен, модуль не грузится.

Вся логика — в registry_service.refresh_summary (тестируется без Celery);
задача лишь делегирует.
"""
from __future__ import annotations

from celery import shared_task

from apps.dashboard import registry_service


@shared_task(name='apps.dashboard.tasks.refresh_registry_summary')
def refresh_registry_summary() -> str:
    """Пересчитать сводку реестра и положить в кэш. Возвращает generated_at."""
    return registry_service.refresh_summary()
