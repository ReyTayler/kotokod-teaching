"""
Бэкфилл материализованных плановых занятий (planned_lessons).

  python manage.py backfill_planned_lessons [--dry-run]

Для всех активных групп с заданными group_start_date И direction.total_lessons:
разворачивает план курса из старта/слотов (planner.generate — единый источник
логики дат), идемпотентно пишет его в planned_lessons (persist_plan), затем
линкует прошлые строки с фактами уроков (link_facts, status='done').

Группы без старта/total_lessons/слотов пропускаются и попадают в отчёт
«unscheduled» с причиной — это data-quality сигнал, а не тихое выпадение.

ИДЕМПОТЕНТНО: повторный прогон не плодит дублей и не перезаписывает проведённые
(status='done'); при неизменных данных — 0 записанных / 0 слинкованных.

--dry-run: ничего не пишет, только показывает, сколько групп и строк было бы
обработано. Гонять на dev-БД (journal), не на journal_test.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.scheduling import planner, repository


class Command(BaseCommand):
    help = 'Бэкфилл planned_lessons для активных групп + линковка с фактами уроков.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Не писать в БД: только показать план обработки.',
        )
        parser.add_argument(
            '--reset', action='store_true',
            help='Полностью пересобрать план: удалить существующие planned_lessons '
                 'группы перед генерацией (РАЗРУШИТЕЛЬНО — сбрасывает ручные операции). '
                 'Нужен для чистого пересбора после исправления логики генерации/линковки.',
        )

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        reset = opts['reset']

        groups = repository.active_groups()
        ids = [g['id'] for g in groups]
        slots_map = repository.slots_by_group(ids)

        processed = 0
        rows_written = 0
        rows_linked = 0
        would_generate = 0
        unscheduled: list[tuple[str, str]] = []

        for g in groups:
            gid = g['id']
            if g['group_start_date'] is None:
                unscheduled.append((g['name'], 'no_start_date'))
                continue
            if g['total_lessons'] is None:
                unscheduled.append((g['name'], 'no_total_lessons'))
                continue
            g_slots = slots_map.get(gid, [])
            if not g_slots:
                unscheduled.append((g['name'], 'no_slots'))
                continue

            rows = planner.generate(
                start_date=g['group_start_date'],
                slots=g_slots,
                total_lessons=g['total_lessons'],
                duration_minutes=g['lesson_duration_minutes'],
                default_teacher_id=g['teacher_pk'],
            )
            if not rows:
                # Старт/слоты/total заданы, но план пуст — сигнализируем.
                unscheduled.append((g['name'], 'empty_plan'))
                continue

            if dry:
                would_generate += len(rows)
                processed += 1
                continue

            with transaction.atomic():
                if reset:
                    repository.reset_plan(gid)
                written = repository.persist_plan(gid, rows)
                linked = repository.link_facts(gid)
            rows_written += written
            rows_linked += linked
            processed += 1

        self._report(
            dry=dry,
            total_groups=len(groups),
            processed=processed,
            unscheduled=unscheduled,
            rows_written=rows_written,
            rows_linked=rows_linked,
            would_generate=would_generate,
        )

    def _report(self, *, dry, total_groups, processed, unscheduled,
                rows_written, rows_linked, would_generate):
        mode = 'DRY-RUN (запись отключена)' if dry else 'запись в БД'
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Бэкфилл planned_lessons — {mode}'
        ))
        self.stdout.write(f'  Активных групп:        {total_groups}')
        self.stdout.write(f'  Обработано:            {processed}')
        self.stdout.write(f'  Пропущено (unscheduled): {len(unscheduled)}')
        if dry:
            self.stdout.write(f'  Строк было бы сгенерировано: {would_generate}')
        else:
            self.stdout.write(f'  Строк создано/обновлено:  {rows_written}')
            self.stdout.write(f'  Слинковано с фактами:     {rows_linked}')

        if unscheduled:
            self.stdout.write(self.style.WARNING('  Пропущенные группы:'))
            for name, reason in unscheduled:
                self.stdout.write(f'    - {name}: {reason}')

        self.stdout.write(self.style.SUCCESS('Готово.'))
