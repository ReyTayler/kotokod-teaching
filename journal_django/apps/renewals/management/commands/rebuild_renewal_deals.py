"""Пересборка сделок продления — самозаживление на случай пропущенных сигналов."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.renewals import engine, repository


class Command(BaseCommand):
    help = 'Гарантирует сделку текущего цикла для каждого активного (ученик×направление).'

    def handle(self, *args, **options):
        processed = 0
        for row in repository.active_cycles():
            engine.ensure_deal(row['student_id'], row['direction_id'], row['cycle_no'])
            processed += 1
        self.stdout.write(self.style.SUCCESS(f'renewals: обработано {processed} циклов'))
