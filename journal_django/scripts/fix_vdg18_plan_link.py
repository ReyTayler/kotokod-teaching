"""
Разовая коррекция ВДГ18 (group_id=85): занятия 27 июня не было.

Что делает (в одной транзакции, с pghistory-контекстом — попадёт в журнал
изменений и будет откатываемо):
  1. Факт 21983 (урок 26 июня, №25) отвязывается от позиции seq 26 (27.06, Сб)
     и привязывается к позиции seq 25 (26.06, Пт) → она становится «проведено».
  2. Освободившаяся субботняя позиция уезжает в конец курса (следующий слот
     после последнего планового занятия) — длина курса остаётся 36 занятий.
  3. Хвост курса перенумеровывается штатной _renumber_persist: номера позиций
     снова совпадают с номерами фактов (03.07 → №26, 10.07 → №27 и т.д.).

APPLY=1 — записать; иначе dry-run с откатом транзакции.
"""
import datetime
import os
from decimal import Decimal

import pghistory
from django.db import transaction

from apps.core.utils.dates import msk_now
from apps.groups.models import GroupScheduleSlot
from apps.scheduling import repository as sched_repo
from apps.scheduling.models import PlannedLesson
from apps.scheduling.occurrences import DONE, PENDING

GROUP = 85
FACT = 21983
P_TARGET = 152506   # seq 25, 26.06 Пт — сейчас pending без факта
P_EXTRA = 152507    # seq 26, 27.06 Сб — сейчас держит факт 21983
APPLY = os.environ.get('APPLY') == '1'


def show(title):
    print(f'\n--- {title} ---')
    rows = (PlannedLesson.objects
            .filter(group_id=GROUP, seq__isnull=False, seq__gte=24)
            .order_by('scheduled_date'))
    for p in rows:
        print(f'  id={p.id} seq={p.seq:<3} №{p.lesson_number:<5} {p.scheduled_date} '
              f'{p.scheduled_date:%a} {p.status:<8} факт={p.fact_lesson_id}')


now = msk_now()
with transaction.atomic():
    show('БЫЛО')

    p_target = PlannedLesson.objects.select_for_update().get(id=P_TARGET)
    p_extra = PlannedLesson.objects.select_for_update().get(id=P_EXTRA)

    # Гарды: работаем только с ожидаемым состоянием.
    assert p_target.group_id == GROUP and p_extra.group_id == GROUP, 'чужая группа'
    assert p_target.fact_lesson_id is None, f'{P_TARGET} уже привязан'
    assert p_target.status == PENDING, f'{P_TARGET} статус {p_target.status}'
    assert p_extra.fact_lesson_id == FACT, f'{P_EXTRA} держит {p_extra.fact_lesson_id}'
    assert p_extra.status == DONE, f'{P_EXTRA} статус {p_extra.status}'

    slots = list(GroupScheduleSlot.objects.filter(group_id=GROUP))
    assert len(slots) == 1, f'ожидался 1 слот, найдено {len(slots)}'
    slot = slots[0]

    with pghistory.context(
        operation='manual.fix_plan_link',
        url=f'manual/fix-plan-link/group/{GROUP}',
        method='SCRIPT',
        note='ВДГ18: занятия 27.06 не было — факт 21983 перевешен на позицию 25',
    ):
        # 1. Перевесить факт (unique на fact_lesson — сначала освободить).
        p_extra.fact_lesson_id = None
        p_extra.status = PENDING
        p_extra.updated_at = now
        p_extra.save(update_fields=['fact_lesson', 'status', 'updated_at'])

        p_target.fact_lesson_id = FACT
        p_target.status = DONE
        p_target.updated_at = now
        p_target.save(update_fields=['fact_lesson', 'status', 'updated_at'])

        # 2. Субботнюю позицию — в конец курса, на следующую дату слота.
        occupied = set(
            PlannedLesson.objects.filter(group_id=GROUP)
            .exclude(id=P_EXTRA)
            .values_list('scheduled_date', flat=True)
        )
        last_date = max(occupied)
        new_date = last_date + datetime.timedelta(days=7)
        while new_date in occupied:
            new_date += datetime.timedelta(days=7)
        # Слот проекта: Вс=0 (как JS getDay); Python weekday(): Пн=0 → пересчёт.
        assert (new_date.weekday() + 1) % 7 == slot.day_of_week, (
            f'{new_date} не попадает в слот дня {slot.day_of_week}')
        print(f'\n  субботняя позиция {P_EXTRA}: {p_extra.scheduled_date} → {new_date}')
        p_extra.scheduled_date = new_date
        p_extra.scheduled_time = slot.start_time
        p_extra.updated_at = now
        p_extra.save(update_fields=['scheduled_date', 'scheduled_time', 'updated_at'])

        # 3. Перенумеровать хвост курса после позиции 25 — штатной функцией.
        tail = list(
            PlannedLesson.objects
            .filter(group_id=GROUP, seq__isnull=False,
                    scheduled_date__gt=p_target.scheduled_date)
            .order_by('scheduled_date', 'scheduled_time')
        )
        print(f'  перенумеровываю хвост: {len(tail)} строк, seq 26..{25 + len(tail)}')
        # start_number — номер ПОСЛЕДНЕГО занятия перед хвостом: renumber_by_date
        # присваивает первому start_number + step (см. planner.py:323).
        sched_repo._renumber_persist(
            tail, start_seq=26, start_number=p_target.lesson_number,
            step=Decimal('1'), now=now,
        )

    show('СТАЛО')

    # Итоговая сверка: номер факта == номер позиции у всех привязанных строк.
    bad = [
        (p.id, p.lesson_number, p.fact_lesson.lesson_number)
        for p in PlannedLesson.objects.filter(
            group_id=GROUP, seq__isnull=False, fact_lesson__isnull=False
        ).select_related('fact_lesson')
        if p.lesson_number != p.fact_lesson.lesson_number
    ]
    print(f'\n  расхождений номер позиции vs номер факта: {len(bad)} {bad if bad else ""}')
    total = PlannedLesson.objects.filter(group_id=GROUP, seq__isnull=False).count()
    done = PlannedLesson.objects.filter(group_id=GROUP, seq__isnull=False, status=DONE).count()
    print(f'  длина курса: {total} позиций, проведено: {done}')

    if not APPLY:
        transaction.set_rollback(True)
        print('\n  DRY-RUN — транзакция откачена, в базе ничего не изменилось.')
    else:
        print('\n  ЗАПИСАНО.')
