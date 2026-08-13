"""
Догнать картинки, застрявшие в состоянии pending.

Нужна в двух случаях: Celery не работал в момент загрузки (локальная разработка
без Redis) и задача упала. Запускается вручную или из cron.

    python manage.py knowledge_optimize_pending
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.knowledge import repository
from apps.knowledge.tasks import optimize_image


class Command(BaseCommand):
    help = 'Построить WebP-варианты для картинок в состоянии pending.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        image_ids = repository.pending_image_ids(limit=options['limit'])
        if not image_ids:
            self.stdout.write('Нечего обрабатывать.')
            return
        for image_id in image_ids:
            # Синхронный вызов задачи: команда для того и нужна, чтобы обойтись
            # без брокера.
            result = optimize_image(image_id)
            self.stdout.write(f'{image_id}: {result}')
        self.stdout.write(self.style.SUCCESS(f'Обработано: {len(image_ids)}'))
