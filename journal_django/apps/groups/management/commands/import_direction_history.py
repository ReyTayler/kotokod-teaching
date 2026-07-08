"""
python manage.py import_direction_history <путь_к_xlsx> [--dry-run]

Импортирует историю направлений учеников из листа «Переходимость по курсам»
внешней таблицы в архивные группы/уроки/посещения/членства.

См. docs/superpowers/specs/2026-07-08-direction-history-import-design.md

Гонять на dev-БД (journal), не на journal_test.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.groups.importers.direction_history import (
    classify_and_aggregate, import_to_db, parse_sheet,
)


class Command(BaseCommand):
    help = 'Импорт истории направлений учеников из внешней таблицы «Переходимость по курсам».'

    def add_arguments(self, parser):
        parser.add_argument('xlsx_path', type=str, help='Путь к .xlsx файлу')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Не писать в БД: только показать, что было бы сделано.',
        )

    def handle(self, *args, **opts):
        path = opts['xlsx_path']
        dry = opts['dry_run']

        try:
            rows = parse_sheet(path)
        except FileNotFoundError as e:
            raise CommandError(f'Файл не найден: {e}')
        except KeyError as e:
            raise CommandError(f'Лист не найден в файле: {e}')

        aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)
        report = import_to_db(aggregated, dry_run=dry)

        self._print_report(rows, skipped, unrecognized, unmatched, report)

    def _print_report(self, rows, skipped, unrecognized, unmatched, report):
        mode = 'DRY-RUN (запись отключена)' if report.dry_run else 'запись в БД'
        self.stdout.write(self.style.MIGRATE_HEADING(f'Импорт истории направлений — {mode}'))
        self.stdout.write(f'  Учеников в листе:                  {len(rows)}')
        self.stdout.write(f'  Пар ученик×направление к импорту:  {report.total_pairs}')
        label = 'Импортировано (было бы)' if report.dry_run else 'Импортировано'
        self.stdout.write(f'  {label}: {report.imported_pairs} (уроков: {report.lessons_written})')
        self.stdout.write(f'  Уже импортировано ранее:            {report.already_imported}')
        self.stdout.write(f'  Пропущено (текущее направление):    {len(skipped)}')
        self.stdout.write(f'  Нераспознанный статус:              {len(unrecognized)}')
        self.stdout.write(f'  Нераспознанное название курса:      {len(unmatched)}')

        if unrecognized:
            self.stdout.write(self.style.WARNING('  Нераспознанные статусы:'))
            for r in unrecognized:
                self.stdout.write(f'    - {r.full_name} / {r.course_raw}: «{r.status}»')

        if unmatched:
            self.stdout.write(self.style.WARNING('  Нераспознанные курсы:'))
            for r in unmatched:
                self.stdout.write(f'    - {r.full_name}: «{r.course_raw}»')

        if report.unmatched_students:
            self.stdout.write(self.style.WARNING('  Не найденные ученики:'))
            for name in report.unmatched_students:
                self.stdout.write(f'    - {name}')

        if report.unmatched_directions_in_db:
            self.stdout.write(self.style.WARNING('  Направления не найдены в БД:'))
            for name in report.unmatched_directions_in_db:
                self.stdout.write(f'    - {name}')

        if report.idempotency_anomalies:
            self.stdout.write(self.style.ERROR('  Аномалии идемпотентности (нужна ручная проверка):'))
            for a in report.idempotency_anomalies:
                self.stdout.write(f'    - {a}')

        if report.failed_pairs:
            self.stdout.write(self.style.ERROR('  Ошибки при записи (нужна ручная проверка):'))
            for f in report.failed_pairs:
                self.stdout.write(f'    - {f}')

        self.stdout.write(self.style.SUCCESS('Готово.'))
