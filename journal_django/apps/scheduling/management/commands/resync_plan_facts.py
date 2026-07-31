"""
Снять сдвиг нумерации между планом курса и фактами в одной группе.

Зачем. При первичном заполнении плана позиции раскладывались по датам занятий, а
номера в самих уроках шли своим порядком. Если в середине оказывалась «лишняя»
позиция (день не по расписанию, дубль номера), все последующие факты садились на
позицию с номером на единицу больше. Преподаватель видит в календаре номер, не
совпадающий с номером в журнале урока, а освободившаяся позиция висит
непроведённой (ПИ316, №26 — типичный случай).

Что делает: приводит привязки к инварианту «номер факта = номер позиции».
  • каждый факт вешается на позицию со своим номером;
  • плановая дата позиции becomes датой факта (позиция описывает прошедшее занятие);
  • позиции, которым факта не досталось, освобождаются и остаются в плане впереди.

Чего НЕ делает: не создаёт и не удаляет ни уроки, ни позиции, не меняет номера в
самих уроках. Если фактам не находится позиции с их номером — команда отказывается
работать целиком, чтобы не чинить наполовину.

Изменения идут под pghistory-контекстом — попадают в журнал изменений и
откатываются оттуда.

    python manage.py resync_plan_facts --group 87            # разбор, без записи
    python manage.py resync_plan_facts --group 87 --apply    # записать
"""
from __future__ import annotations

import pghistory
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from apps.core.utils.dates import msk_now
from apps.groups.models import Group
from apps.lessons.models import COURSE_LESSON_TYPES, Lesson
from apps.scheduling.models import PlannedLesson
from apps.scheduling.occurrences import DONE, PENDING


class Command(BaseCommand):
    help = 'Приводит привязки план↔факт группы к правилу «номер факта = номер позиции».'

    def add_arguments(self, parser):
        parser.add_argument('--group', type=int, required=True, metavar='ID',
                            help='ID группы.')
        parser.add_argument('--apply', action='store_true',
                            help='Записать. Без флага — только показать, что изменится.')

    def handle(self, *args, **options):
        group_id = options['group']
        apply_changes = options['apply']

        group = Group.objects.filter(id=group_id).first()
        if group is None:
            raise CommandError(f'Группы {group_id} нет.')

        facts = list(
            Lesson.objects.filter(group_id=group_id, lesson_type__in=COURSE_LESSON_TYPES)
            .order_by('lesson_number', 'lesson_date', 'id')
            .values('id', 'lesson_date', 'lesson_number')
        )
        positions = list(
            PlannedLesson.objects.filter(group_id=group_id, seq__isnull=False)
            .order_by('seq')
        )

        by_number = {p.lesson_number: p for p in positions}
        if len(by_number) != len(positions):
            raise CommandError('В плане есть позиции с одинаковым номером — сначала это.')

        # Факт без позиции своего номера чинить нечем: отказываемся целиком.
        orphans = [f for f in facts if f['lesson_number'] not in by_number]
        if orphans:
            self.stdout.write(self.style.ERROR(
                'Для этих занятий нет позиции с таким номером — разберитесь вручную:'))
            for f in orphans:
                self.stdout.write(f"  урок {f['id']} №{f['lesson_number']} {f['lesson_date']}")
            raise CommandError('Ничего не изменено.')

        wanted = {}      # position_id -> (fact_id, fact_date)
        for f in facts:
            wanted[by_number[f['lesson_number']].id] = (f['id'], f['lesson_date'])

        changes = []
        for p in positions:
            target = wanted.get(p.id)
            new_fact = target[0] if target else None
            new_date = target[1] if target else p.scheduled_date
            if p.fact_lesson_id != new_fact or p.scheduled_date != new_date:
                changes.append((p, new_fact, new_date))

        self.stdout.write(f'\nГруппа {group.name} (id={group_id}): '
                          f'позиций {len(positions)}, занятий {len(facts)}')
        if not changes:
            self.stdout.write(self.style.SUCCESS('Всё уже согласовано — менять нечего.'))
            return

        self.stdout.write(f'\nИзменится позиций: {len(changes)}\n')
        self.stdout.write('  позиция  №     было: факт / дата         станет: факт / дата')
        for p, new_fact, new_date in changes:
            self.stdout.write(
                f'  {p.id:<8} {str(p.lesson_number):<5} '
                f'{str(p.fact_lesson_id):<8} {p.scheduled_date}  ->  '
                f'{str(new_fact):<8} {new_date}'
            )

        freed = [p for p, f, _ in changes if f is None]
        if freed:
            self.stdout.write('\nОсвобождаются (станут ближайшими занятиями):')
            for p in freed:
                self.stdout.write(f'  №{p.lesson_number} на {p.scheduled_date}')

        with transaction.atomic():
            with pghistory.context(
                operation='manual.resync_plan_facts',
                url=f'manual/resync-plan-facts/group/{group_id}',
                method='COMMAND',
                note=f'{group.name}: снят сдвиг нумерации плана относительно занятий',
            ):
                now = msk_now()
                # Сначала снять все привязки, которые меняются: fact_lesson уникален,
                # иначе первая же перестановка упрётся в ограничение.
                for p, _new_fact, _new_date in changes:
                    if p.fact_lesson_id is not None:
                        PlannedLesson.objects.filter(id=p.id).update(
                            fact_lesson=None, status=PENDING, updated_at=now)
                for p, new_fact, new_date in changes:
                    PlannedLesson.objects.filter(id=p.id).update(
                        fact_lesson_id=new_fact,
                        status=DONE if new_fact else PENDING,
                        scheduled_date=new_date,
                        updated_at=now,
                    )

            mismatch = (
                PlannedLesson.objects
                .filter(group_id=group_id, seq__isnull=False, fact_lesson__isnull=False)
                .exclude(lesson_number=F('fact_lesson__lesson_number'))
                .count()
            )
            linked = PlannedLesson.objects.filter(
                group_id=group_id, fact_lesson__isnull=False).count()
            self.stdout.write(f'\nПривязано занятий: {linked} из {len(facts)}')
            self.stdout.write(f'Расхождений «номер позиции ≠ номер занятия»: {mismatch}')
            if mismatch or linked != len(facts):
                raise CommandError('Проверка после записи не сошлась — откат.')

            if not apply_changes:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING(
                    '\nПробный прогон — в базе ничего не изменилось. '
                    'Повторите с --apply, чтобы записать.'))
                return

        self.stdout.write(self.style.SUCCESS('\nЗаписано.'))
