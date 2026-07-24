# Unified Schedule Relay — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить «слепой +7» при отмене занятия на единый непрерывный пересчёт хвоста по слотам (без дыр, идемпотентно) и сделать разовую замену преподавателя свойством даты, которое не «уезжает» при сдвиге расписания.

**Architecture:** Один примитив раскладки `relay_from_date(tail, resume_date, slots, skip_dates)` раскладывает курсовой хвост подряд по слотам, пропуская уже занятые даты (маркеры отмен, `done`-уроки, доп.занятия). `cancel` перестаёт делать `+7`: ставит маркер и зовёт relay. Разовая замена преподавателя переезжает из колонки `teacher_id` (преподаватель контента) в новую колонку `substitute_teacher_id` (замена на дату), которая обнуляется при смене даты строки.

**Tech Stack:** Django 5 + DRF, PostgreSQL, pghistory, pytest. Бэкенд в `journal_django/`. Тесты — `pytest` из `journal_django/` (тестовая БД `journal_test`, см. `config/settings/test.py`).

**Инварианты проекта (не нарушать):**
- Чистые функции планировщика (`planner.py`, `occurrences.py`) — БЕЗ доступа к БД.
- `PlannedLesson` под `@pghistory.track` → любое новое поле требует `makemigrations` (создаст AddField и для event-таблицы).
- Даты — чистый `datetime.date`/`time` без TZ; «сейчас» — `msk_now()`.
- Батч-запросы, без N+1. Все write — в `transaction.atomic`.
- RBAC/CSRF на вьюхах не трогаем (эндпоинты уже защищены `IsManagerOrAdmin`).
- `UniqueConstraint(group, seq)` — одна строка на позицию курса; коллизии по ДАТЕ допустимы (две строки на одну дату — это нормально, напр. done + сдвинутая).

---

## File Structure

| Файл | Ответственность | Изменения |
|---|---|---|
| `apps/scheduling/occurrences.py` | Чистый генератор `_walk` | +параметр `skip_dates` |
| `apps/scheduling/planner.py` | Чистые операции над `PlannedRow` | `relay_from_date` +`skip_dates`; удалить `cancel` |
| `apps/scheduling/models.py` | Модель `PlannedLesson` | +поле `substitute_teacher` |
| `apps/scheduling/repository.py` | ORM + оркестрация | `cancel_lesson` через relay; чтение/скоуп по эффективному преподавателю; хелпер `_relay_tail` |
| `apps/scheduling/services.py` | Сборка календаря + read-side статусов | эффективный преподаватель в occurrence-dict |
| `apps/scheduling/tests/test_occurrences_skip.py` | НОВЫЙ — unit skip_dates | создать |
| `apps/scheduling/tests/test_planner_relay.py` | unit relay | +тесты skip_dates |
| `apps/scheduling/tests/test_planner.py` | unit планировщика | удалить блок `cancel` |
| `apps/scheduling/tests/test_plan_api.py` | integration план-API | обновить ожидания cancel; +тесты замены |
| `apps/scheduling/migrations/000X_*.py` | Схема | сгенерировать `makemigrations` |
| `docs/lesson-scheduling.md` | Документация механизма | обновить раздел «Отмена» и «Замена» |

---

## Phase 1 — Примитив пересчёта со «скипами» (чистые функции)

### Task 1: `skip_dates` в генераторе `_walk`

**Files:**
- Modify: `journal_django/apps/scheduling/occurrences.py:69-106`
- Test: `journal_django/apps/scheduling/tests/test_occurrences_skip.py` (создать)

- [ ] **Step 1: Написать падающий тест**

Create `journal_django/apps/scheduling/tests/test_occurrences_skip.py`:

```python
"""Unit: _walk пропускает даты из skip_dates, не расходуя на них номер урока.

Опорные даты: 2026-06-01 — понедельник. day_of_week Вс=0 (Пн=1..Сб=6, Вс=0)."""
from __future__ import annotations

import datetime
from decimal import Decimal

from apps.scheduling.occurrences import Slot, _walk

D = datetime.date
T = datetime.time
MON = 1


def _slot(dow, hh):
    return Slot(day_of_week=dow, start_time=T(hh, 0), effective_from=D(2000, 1, 1))


def test_walk_skips_dates_without_consuming_number():
    # Недельный понедельник, курс из 3 уроков, пропускаем 2-й понедельник (06-08).
    occ = _walk(
        D(2026, 6, 1), [_slot(MON, 10)], Decimal('1'), 3, D(2026, 8, 1),
        skip_dates=frozenset({D(2026, 6, 8)}),
    )
    # 06-08 пропущен → уроки встают на 06-01, 06-15, 06-22 (номера 1,2,3 непрерывны).
    assert [o.date for o in occ] == [D(2026, 6, 1), D(2026, 6, 15), D(2026, 6, 22)]
    assert [o.seq for o in occ] == [1, 2, 3]
    assert [o.lesson_number for o in occ] == [Decimal('1'), Decimal('2'), Decimal('3')]


def test_walk_no_skip_dates_is_unchanged():
    occ = _walk(D(2026, 6, 1), [_slot(MON, 10)], Decimal('1'), 2, D(2026, 8, 1))
    assert [o.date for o in occ] == [D(2026, 6, 1), D(2026, 6, 8)]
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd journal_django && python -m pytest apps/scheduling/tests/test_occurrences_skip.py -v`
Expected: FAIL — `_walk() got an unexpected keyword argument 'skip_dates'`.

- [ ] **Step 3: Реализовать skip_dates в `_walk`**

В `journal_django/apps/scheduling/occurrences.py` заменить сигнатуру и тело `_walk`:

```python
def _walk(
    start: datetime.date,
    slots: list[Slot],
    step: Decimal,
    total: Optional[int],
    generate_until: datetime.date,
    skip_dates: frozenset[datetime.date] = frozenset(),
) -> list[Occurrence]:
    """
    Перебор курса по неделям от даты старта. На каждой неделе берём слоты,
    активные на конкретную дату, упорядоченные по (дата, время), инкрементим
    seq/lesson_number. Останавливаемся, когда номер превысил длину курса
    (total) ИЛИ прошли generate_until (для открытых курсов total=None).

    Даты из skip_dates ПРОПУСКАЮТСЯ как позиции размещения (номер урока на них
    НЕ расходуется) — так пересчёт хвоста обходит уже занятые даты (маркеры
    отмен, проведённые уроки, доп.занятия), оставаясь непрерывным.
    """
    occ: list[Occurrence] = []
    num = Decimal('0')
    seq = 0
    monday = start - datetime.timedelta(days=start.weekday())  # Пн недели старта
    weeks = 0
    while weeks < _CAP_WEEKS:
        week_cands: list[tuple[datetime.date, datetime.time]] = []
        for s in slots:
            d = monday + datetime.timedelta(days=_offset_from_monday(s.day_of_week))
            if d < start:
                continue
            if s.active_on(d):
                week_cands.append((d, s.start_time))
        week_cands.sort()
        for d, t in week_cands:
            if d in skip_dates:
                continue  # занятая дата — не размещаем и не тратим номер
            num += step
            if total is not None and num > total:
                return occ  # курс завершён
            seq += 1
            occ.append(Occurrence(date=d, time=t, seq=seq, lesson_number=num))
        if monday > generate_until:
            break
        monday += datetime.timedelta(days=7)
        weeks += 1
    return occ
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `cd journal_django && python -m pytest apps/scheduling/tests/test_occurrences_skip.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Регресс генератора не сломан**

Run: `cd journal_django && python -m pytest apps/scheduling/tests/test_planner.py -v -k generate`
Expected: PASS (все generate-тесты зелёные — skip_dates по умолчанию пуст).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/scheduling/occurrences.py journal_django/apps/scheduling/tests/test_occurrences_skip.py
git commit -m "feat(scheduling): skip_dates in _walk generator (skip occupied dates)"
```

---

### Task 2: `skip_dates` в `relay_from_date`

**Files:**
- Modify: `journal_django/apps/scheduling/planner.py:287-320`
- Test: `journal_django/apps/scheduling/tests/test_planner_relay.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `journal_django/apps/scheduling/tests/test_planner_relay.py`:

```python
def test_relay_skips_occupied_dates_contiguously():
    """Пересчёт хвоста обходит занятые даты (skip_dates) без дыр: две подряд
    занятые даты → хвост встаёт на следующие свободные слот-даты."""
    slots = [Slot(day_of_week=1, start_time=datetime.time(10, 0),   # понедельник
                  effective_from=datetime.date(2000, 1, 1))]
    tail = [_row(3, datetime.date(2026, 6, 15)),
            _row(5, datetime.date(2026, 6, 29))]
    # resume с 06-15; заняты 06-15 (маркер отмены) и 06-22 (done-урок).
    out = relay_from_date(
        tail, resume_date=datetime.date(2026, 6, 15), slots=slots,
        duration_minutes=90,
        skip_dates=frozenset({datetime.date(2026, 6, 15), datetime.date(2026, 6, 22)}),
    )
    assert [r.scheduled_date for r in out] == [
        datetime.date(2026, 6, 29), datetime.date(2026, 7, 6)]
    assert [r.seq for r in out] == [3, 5]


def test_relay_without_skip_dates_unchanged():
    slots = [Slot(day_of_week=3, start_time=datetime.time(10, 0),
                  effective_from=datetime.date(2000, 1, 1))]
    tail = [_row(5, datetime.date(2026, 7, 1)), _row(6, datetime.date(2026, 7, 8))]
    out = relay_from_date(tail, resume_date=datetime.date(2026, 8, 5),
                          slots=slots, duration_minutes=90)
    assert [r.scheduled_date for r in out] == [
        datetime.date(2026, 8, 5), datetime.date(2026, 8, 12)]
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd journal_django && python -m pytest apps/scheduling/tests/test_planner_relay.py -v -k skip`
Expected: FAIL — `relay_from_date() got an unexpected keyword argument 'skip_dates'`.

- [ ] **Step 3: Добавить `skip_dates` в `relay_from_date`**

В `journal_django/apps/scheduling/planner.py` заменить функцию `relay_from_date` целиком:

```python
def relay_from_date(
    tail: list[PlannedRow],
    *,
    resume_date: datetime.date,
    slots: list[Slot],
    duration_minutes: int,
    skip_dates: frozenset[datetime.date] = frozenset(),
) -> list[PlannedRow]:
    """Переложить хвост курсовых строк (ordered by seq) на новые даты, разворачивая
    слот от resume_date включительно. i-я строка → i-е СВОБОДНОЕ слот-занятие.
    seq/lesson_number сохраняются; moved_from_date обнуляется (разовые переносы
    схлопываются); исходный status сохраняется (НЕ принудительно PENDING —
    вызывающий обязан передавать только pending/overdue строки, DONE тут не
    фильтруются, см. инвариант модуля).

    skip_dates — уже занятые даты (маркеры отмен, проведённые уроки, доп.занятия):
    _walk их пропускает, номер на них не тратится → раскладка остаётся непрерывной
    и не наезжает на существующие пины. Горизонт генерации расширяем на число
    скипов, чтобы всем строкам хватило свободных слотов.

    total для _walk считается ТОЧНО как len(ordered)*step (Decimal, без округления) —
    _walk останавливается строго при num > total, так что выдаёт РОВНО N occurrences
    независимо от полу-урочного шага (0.5). Пустой хвост / нет слотов → без сдвига."""
    if not tail or not slots:
        return [replace(r) for r in tail]
    ordered = sorted(tail, key=lambda r: (r.seq if r.seq is not None else 0))
    step = _step_for(duration_minutes)
    total = Decimal(len(ordered)) * step
    horizon_weeks = len(ordered) + len(skip_dates) + 2
    generate_until = resume_date + datetime.timedelta(weeks=horizon_weeks)
    occ = _walk(resume_date, slots, step, total, generate_until, skip_dates=skip_dates)
    out: list[PlannedRow] = []
    for r, o in zip(ordered, occ):
        out.append(replace(
            r,
            scheduled_date=o.date,
            scheduled_time=o.time,
            moved_from_date=None,
        ))
    return out
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd journal_django && python -m pytest apps/scheduling/tests/test_planner_relay.py -v`
Expected: PASS (все, включая старые relay-тесты — старый вызов без skip_dates работает).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/scheduling/planner.py journal_django/apps/scheduling/tests/test_planner_relay.py
git commit -m "feat(scheduling): skip_dates in relay_from_date (contiguous relay around pins)"
```

---

## Phase 2 — Колонка `substitute_teacher_id` (замена — свойство даты)

### Task 3: Поле `substitute_teacher` в модели + миграция

**Files:**
- Modify: `journal_django/apps/scheduling/models.py:60-68`
- Create: `journal_django/apps/scheduling/migrations/000X_planned_lesson_substitute_teacher.py` (через makemigrations)

- [ ] **Step 1: Добавить поле в модель**

В `journal_django/apps/scheduling/models.py` сразу после определения поля `teacher` (после строки 68, до `status = ...`) добавить:

```python
    # Разовая замена преподавателя НА ЭТУ ДАТУ (не путать с teacher — преподавателем
    # контента). Свойство конкретной календарной даты: при смене scheduled_date
    # строки (перекладка/отмена) обнуляется (замена «не едет» с контентом).
    # Эффективный преподаватель занятия = substitute_teacher или teacher.
    substitute_teacher = models.ForeignKey(
        'teachers.Teacher',
        on_delete=models.DO_NOTHING,
        db_column='substitute_teacher_id',
        related_name='substitute_planned_lessons',
        null=True,
        blank=True,
    )
```

- [ ] **Step 2: Сгенерировать миграцию**

Run: `cd journal_django && python manage.py makemigrations scheduling`
Expected: создан файл миграции с `AddField` для `plannedlesson.substitute_teacher` И для event-модели (pghistory). Открыть файл, убедиться, что есть две `AddField` (основная таблица + `plannedlessonevent`), новых `RunSQL`-триггеров руками не правим.

- [ ] **Step 3: Применить миграцию к тестовой и dev БД**

Run: `cd journal_django && python manage.py migrate scheduling`
Expected: `Applying scheduling.000X_... OK`.

- [ ] **Step 4: Проверка регистра changelog (модель уже покрыта)**

Run: `cd journal_django && python -m pytest apps/changelog/tests/test_registry.py -v`
Expected: PASS — модель `PlannedLesson` уже в реестре; добавление поля реестр не ломает.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/scheduling/models.py journal_django/apps/scheduling/migrations/
git commit -m "feat(scheduling): add substitute_teacher column to planned_lessons"
```

---

## Phase 3 — `cancel` через relay + очистка замены при переезде

### Task 4: `_relay_tail` хелпер + `cancel_lesson` без «+7»

**Files:**
- Modify: `journal_django/apps/scheduling/repository.py:804-847` (`cancel_lesson`)
- Modify: `journal_django/apps/scheduling/repository.py` (добавить `_relay_tail`, импорты)
- Test: `journal_django/apps/scheduling/tests/test_plan_api.py` (обновить `TestCancel`)

- [ ] **Step 1: Обновить integration-тест отмены под непрерывную раскладку**

В `journal_django/apps/scheduling/tests/test_plan_api.py` заменить метод `test_shifts_tail_preserves_done` в классе `TestCancel` на:

```python
    def test_shifts_tail_relays_around_done_pin(self, manager_client, plan_group):
        """Отмена пересчитывает хвост непрерывно, ОБХОДЯ проведённый (done) урок:
        done — неподвижный пин, курсовая строка на его дату не наезжает, а встаёт
        на следующий свободный слот. Голова до from_date не двигается."""
        gid = plan_group['group_id']
        plan = _generate(manager_client, gid).json()
        by_seq = _by_seq(plan)
        anchor = by_seq[3]         # 2026-06-15
        done_row = by_seq[4]       # 2026-06-22 — done, неподвижный пин
        with connection.cursor() as cur:
            cur.execute("UPDATE planned_lessons SET status='done' WHERE id=%s", [done_row['id']])

        resp = manager_client.post(f'/api/admin/groups/{gid}/plan/{anchor["id"]}/cancel', {}, format='json')
        assert resp.status_code == 200
        after = _by_seq(resp.json())
        assert after[1]['scheduled_date'] == '2026-06-01'   # < from_date — не тронут
        assert after[2]['scheduled_date'] == '2026-06-08'   # < from_date — не тронут
        assert after[4]['scheduled_date'] == '2026-06-22'   # done — не тронут
        assert after[4]['status'] == 'done'
        # seq3 обходит занятые 06-15 (маркер) и 06-22 (done) → 06-29; seq5 → 07-06.
        assert after[3]['scheduled_date'] == '2026-06-29'
        assert after[5]['scheduled_date'] == '2026-07-06'

    def test_double_cancel_is_contiguous_no_gap(self, manager_client, plan_group):
        """Две отмены (сначала поздняя, затем ранняя) дают непрерывное расписание
        без пустых недель. Итоговый хвост сдвинут на 2 недели, но без дыр."""
        gid = plan_group['group_id']
        plan = _generate(manager_client, gid).json()
        by_seq = _by_seq(plan)
        # Курс: seq1..5 по понедельникам 06-01,06-08,06-15,06-22,06-29.
        manager_client.post(f'/api/admin/groups/{gid}/plan/{by_seq[3]["id"]}/cancel', {}, format='json')
        after = manager_client.post(
            f'/api/admin/groups/{gid}/plan/{by_seq[1]["id"]}/cancel', {}, format='json',
        ).json()
        course = sorted(
            [r for r in after if r['seq'] is not None and r['status'] != 'done'],
            key=lambda r: r['seq'],
        )
        dates = [r['scheduled_date'] for r in course]
        # Непрерывность: каждая следующая курсовая дата ровно на неделю позже.
        for i in range(1, len(dates)):
            d0 = datetime.date.fromisoformat(dates[i - 1])
            d1 = datetime.date.fromisoformat(dates[i])
            assert (d1 - d0).days == 7, f'разрыв между {dates[i-1]} и {dates[i]}'
        # Два маркера отмены присутствуют.
        markers = [r for r in after if r['status'] == 'cancelled']
        assert len(markers) == 2
```

Убедиться, что в начале файла есть `import datetime` и `from django.db import connection` (если нет — добавить к существующим импортам).

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && python -m pytest "apps/scheduling/tests/test_plan_api.py::TestCancel" -v`
Expected: FAIL — старая логика `+7` ставит seq3 на 06-22 (наезд на done) и оставляет дыру.

- [ ] **Step 3: Добавить хелпер `_relay_tail` и переписать `cancel_lesson`**

В `journal_django/apps/scheduling/repository.py` в блок импортов добавить (рядом со строкой 24):

```python
from apps.scheduling.occurrences import CANCELLED, DONE, MOVED, OVERDUE, PENDING, Slot, _step_for  # noqa: F401  (существующая строка)
```

(строка уже импортирует нужное; `datetime` уже импортирован.)

Добавить новый хелпер перед `cancel_lesson` (около строки 804):

```python
def _relay_tail(
    group_id: int,
    *,
    from_date: datetime.date,
    now: datetime.datetime,
) -> None:
    """Непрерывно переложить курсовой хвост группы (pending/overdue, seq задан,
    scheduled_date >= from_date) по текущему открытому слоту от from_date,
    ОБХОДЯ уже занятые даты (проведённые уроки, маркеры отмен, доп.занятия и
    любые прочие строки вне хвоста). Замена преподавателя (substitute_teacher)
    обнуляется у строк, чья дата изменилась (замена — свойство даты, не едет).

    Вызывается ВНУТРИ уже открытой транзакции. Нет открытого слота или пустой
    хвост → ничего не двигаем (нельзя развернуть каденцию)."""
    tail = list(
        PlannedLesson.objects
        .select_for_update()
        .filter(group_id=group_id, seq__isnull=False,
                status__in=_MUTABLE_STATUSES, scheduled_date__gte=from_date)
        .order_by('seq')
    )
    if not tail:
        return
    tail_ids = {p.id for p in tail}

    g = (Group.objects.filter(id=group_id).values('lesson_duration_minutes').first())
    if g is None:
        return
    open_slots = [s for s in slots_by_group([group_id]).get(group_id, [])
                  if s.effective_to is None]
    if not open_slots:
        return

    # Занятые даты = даты ВСЕХ строк группы, не входящих в перекладываемый хвост
    # (done/маркеры/extra/голова). На них курсовую строку не ставим.
    skip_dates = frozenset(
        PlannedLesson.objects
        .filter(group_id=group_id)
        .exclude(id__in=tail_ids)
        .values_list('scheduled_date', flat=True)
    )

    by_seq = {p.seq: p for p in tail}
    relaid = planner.relay_from_date(
        [_row_from_model(p) for p in tail],
        resume_date=from_date,
        slots=open_slots,
        duration_minutes=g['lesson_duration_minutes'],
        skip_dates=skip_dates,
    )
    to_update = []
    for cr in relaid:
        p = by_seq[cr.seq]
        date_changed = p.scheduled_date != cr.scheduled_date
        p.scheduled_date = cr.scheduled_date
        p.scheduled_time = cr.scheduled_time
        p.moved_from_date = None
        if date_changed:
            p.substitute_teacher_id = None  # замена не едет с контентом
        p.updated_at = now
        to_update.append(p)
    PlannedLesson.objects.bulk_update(
        to_update,
        ['scheduled_date', 'scheduled_time', 'moved_from_date',
         'substitute_teacher', 'updated_at'],
    )
```

Заменить тело `cancel_lesson` (строки ~822-847) на:

```python
    now = msk_now()
    with transaction.atomic():
        # Маркер отмены на исходной дате (seq=NULL): календарь показывает
        # зачёркнутое занятие. Несёт время/преподавателя отменённого занятия.
        PlannedLesson.objects.create(
            group_id=group_id, seq=None, lesson_number=None,
            scheduled_date=from_date, scheduled_time=marker_time,
            teacher_id=marker_teacher_id, status=CANCELLED,
            created_at=now, updated_at=now,
        )
        # Непрерывный пересчёт хвоста от from_date, обходя занятые даты (в т.ч.
        # только что вставленный маркер). Заменяет прежний слепой сдвиг +7.
        _relay_tail(group_id, from_date=from_date, now=now)

    return get_plan(group_id)
```

Обновить docstring `cancel_lesson` (строки 811-820): заменить «сдвигаются на +7 дней» на «непрерывно перекладываются по слоту от from_date, обходя занятые даты (relay); курс продлевается ровно на число отменённых занятий, без дыр».

- [ ] **Step 4: Запустить `TestCancel` — убедиться, что проходит**

Run: `cd journal_django && python -m pytest "apps/scheduling/tests/test_plan_api.py::TestCancel" -v`
Expected: PASS (включая `test_cancel_creates_cancelled_marker`, `test_second_cancel_does_not_move_prior_marker_or_extra`, `test_cancel_extra_row_rejected`, новые contiguous-тесты).

- [ ] **Step 5: Полный регресс раздела scheduling**

Run: `cd journal_django && python -m pytest apps/scheduling -v`
Expected: PASS. Если падает `test_freeze_scheduling.py` — заморозка использует `relay_from_date` со старой сигнатурой (skip_dates по умолчанию пуст, обратная совместимость сохранена), падать не должна.

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/scheduling/repository.py journal_django/apps/scheduling/tests/test_plan_api.py
git commit -m "feat(scheduling): cancel relays tail contiguously (no +7, no gaps, skips pins)"
```

---

### Task 5: Удалить мёртвую `planner.cancel` и её тесты

**Files:**
- Modify: `journal_django/apps/scheduling/planner.py:253-266` (удалить `cancel`)
- Modify: `journal_django/apps/scheduling/tests/test_planner.py` (удалить блок cancel)

- [ ] **Step 1: Убедиться, что `planner.cancel` больше нигде не используется**

Run: `cd journal_django && grep -rn "planner.cancel\|import cancel\|[^_]cancel(" apps/scheduling --include=*.py | grep -v test_plan_api | grep -v cancel_lesson | grep -v cancel_future | grep -v cancellations`
Expected: совпадения только в `planner.py` (определение) и `test_planner.py` (импорт/тесты). Если есть иное использование — остановиться и разобраться.

- [ ] **Step 2: Удалить функцию `cancel` из `planner.py`**

Удалить функцию `cancel` целиком (строки 253-266, docstring + тело). Из docstring модуля (строка 4-8) убрать упоминание «отмена со сдвигом хвоста +1 неделю» → «отмена реализована пересчётом хвоста в repository».

- [ ] **Step 3: Удалить cancel-тесты из `test_planner.py`**

В `journal_django/apps/scheduling/tests/test_planner.py`:
- Убрать `cancel` из импорта (строки 18-21).
- Удалить весь блок `# cancel` (строки 269-323: тесты `test_cancel_shifts_tail_plus_seven_days`, `test_cancel_ignores_done`, `test_cancel_preserves_weekday_and_time`, `test_cancel_does_not_move_extra_or_markers`, `test_cancel_shifts_overdue_course_rows`).

- [ ] **Step 4: Запустить unit-тесты планировщика**

Run: `cd journal_django && python -m pytest apps/scheduling/tests/test_planner.py -v`
Expected: PASS (без cancel-тестов, остальное зелёное).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/scheduling/planner.py journal_django/apps/scheduling/tests/test_planner.py
git commit -m "refactor(scheduling): remove dead planner.cancel (relay replaces +7)"
```

---

## Phase 4 — Замена преподавателя как свойство даты

### Task 6: `change_teacher` пишет `substitute_teacher_id`

**Files:**
- Modify: `journal_django/apps/scheduling/planner.py:197-203` (`change_teacher`)
- Modify: `journal_django/apps/scheduling/repository.py:614-638` (`change_teacher`)
- Modify: `journal_django/apps/scheduling/planner.py:27-45` (`PlannedRow` +поле)
- Modify: `journal_django/apps/scheduling/repository.py:508-519` (`_row_from_model`)
- Test: `journal_django/apps/scheduling/tests/test_plan_api.py` (класс замены)

- [ ] **Step 1: Написать падающий integration-тест**

В `journal_django/apps/scheduling/tests/test_plan_api.py` добавить новый класс (после `TestCancel`):

```python
class TestSubstituteTeacher:
    def test_change_teacher_sets_substitute_not_content(self, manager_client, plan_group):
        """Разовая замена пишется в substitute_teacher, teacher (контент) не тронут."""
        gid = plan_group['group_id']
        plan = _generate(manager_client, gid).json()
        target = _by_seq(plan)[3]
        sub = plan_group['teacher_b']
        resp = manager_client.post(
            f'/api/admin/groups/{gid}/plan/{target["id"]}/change-teacher',
            {'new_teacher_id': sub}, format='json',
        )
        assert resp.status_code == 200
        with connection.cursor() as cur:
            cur.execute(
                "SELECT teacher_id, substitute_teacher_id FROM planned_lessons WHERE id=%s",
                [target['id']],
            )
            content_id, substitute_id = cur.fetchone()
        assert substitute_id == sub          # замена в новой колонке
        assert content_id != sub             # контент-преподаватель не тронут

    def test_substitute_dropped_when_cancel_moves_row(self, manager_client, plan_group):
        """Баг №1: замена НЕ едет с контентом. Ставим замену на урок, отменяем его —
        сдвинутая строка теряет замену (замена осталась на отменённой дате)."""
        gid = plan_group['group_id']
        plan = _generate(manager_client, gid).json()
        by_seq = _by_seq(plan)
        target = by_seq[3]
        sub = plan_group['teacher_b']
        manager_client.post(
            f'/api/admin/groups/{gid}/plan/{target["id"]}/change-teacher',
            {'new_teacher_id': sub}, format='json',
        )
        manager_client.post(
            f'/api/admin/groups/{gid}/plan/{target["id"]}/cancel', {}, format='json',
        )
        with connection.cursor() as cur:
            cur.execute(
                "SELECT substitute_teacher_id FROM planned_lessons WHERE id=%s",
                [target['id']],
            )
            (substitute_id,) = cur.fetchone()
        assert substitute_id is None   # замена сброшена при переезде строки
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && python -m pytest "apps/scheduling/tests/test_plan_api.py::TestSubstituteTeacher" -v`
Expected: FAIL — `change_teacher` пока пишет `teacher_id`; колонка `substitute_teacher_id` не заполняется.

- [ ] **Step 3: Добавить поле в `PlannedRow` и `change_teacher` (planner)**

В `journal_django/apps/scheduling/planner.py` в датакласс `PlannedRow` (после `teacher_id`, строка 38) добавить:

```python
    substitute_teacher_id: Optional[int] = None
```

Заменить функцию `change_teacher` (строки 197-203) на:

```python
def change_teacher(row: PlannedRow, *, new_teacher_id: int) -> PlannedRow:
    """Разовая замена преподавателя на дату этой строки: пишет substitute_teacher_id
    (НЕ teacher_id — тот остаётся преподавателем контента). Дата/время/moved_from не
    трогаются; при последующем переезде строки замена обнуляется (свойство даты).
    Проведённое (DONE) менять нельзя."""
    if row.status == DONE:
        raise ValueError('Нельзя сменить преподавателя проведённого занятия (status=done).')
    return replace(row, substitute_teacher_id=new_teacher_id)
```

- [ ] **Step 4: Прокинуть поле в `_row_from_model` (repository)**

В `journal_django/apps/scheduling/repository.py` в `_row_from_model` (строки 508-519) добавить в конструктор `PlannedRow`:

```python
        substitute_teacher_id=p.substitute_teacher_id,
```

- [ ] **Step 5: Обновить `repository.change_teacher`**

В `journal_django/apps/scheduling/repository.py` заменить тело `change_teacher` (строки 623-638) на:

```python
    now = msk_now()
    with transaction.atomic():
        p = (
            PlannedLesson.objects
            .select_for_update()
            .filter(group_id=group_id, id=lesson_id)
            .first()
        )
        if p is None:
            return None
        updated = planner.change_teacher(_row_from_model(p), new_teacher_id=new_teacher_id)
        p.substitute_teacher_id = updated.substitute_teacher_id
        p.updated_at = now
        p.save(update_fields=['substitute_teacher', 'updated_at'])

    return _plan_row_dict_obj(p, teacher_names())
```

Обновить docstring `change_teacher` (строки 618-622): «меняет ТОЛЬКО teacher_id» → «пишет substitute_teacher (замена на дату); teacher (контент) и дату не трогает».

- [ ] **Step 6: Запустить тест замены — убедиться, что проходит**

Run: `cd journal_django && python -m pytest "apps/scheduling/tests/test_plan_api.py::TestSubstituteTeacher" -v`
Expected: PASS (2 passed). `test_substitute_dropped_when_cancel_moves_row` проходит благодаря очистке `substitute_teacher_id` в `_relay_tail` (Task 4).

- [ ] **Step 7: Проверить, что старый conflict-тест замены (done→409) ещё зелёный**

Run: `cd journal_django && python -m pytest "apps/scheduling/tests/test_plan_api.py" -v -k change_teacher`
Expected: PASS (`test_change_teacher_done_conflict` и др.).

- [ ] **Step 8: Commit**

```bash
git add journal_django/apps/scheduling/planner.py journal_django/apps/scheduling/repository.py journal_django/apps/scheduling/tests/test_plan_api.py
git commit -m "feat(scheduling): one-off teacher change writes date-bound substitute_teacher"
```

---

### Task 7: Read-side — эффективный преподаватель в календаре и плане

**Files:**
- Modify: `journal_django/apps/scheduling/repository.py:106-127` (`planned_lessons_in_window`)
- Modify: `journal_django/apps/scheduling/services.py:65-104` (`_planned_occurrence_dict`)
- Modify: `journal_django/apps/scheduling/repository.py:471-505` (`_plan_row_dict` / `_plan_row_dict_obj`)
- Modify: `journal_django/apps/scheduling/repository.py:542-554` (`get_plan` values)
- Test: `journal_django/apps/scheduling/tests/test_build_calendar.py`

- [ ] **Step 1: Написать падающий тест календаря**

В `journal_django/apps/scheduling/tests/test_build_calendar.py` убедиться, что вверху есть `from django.db import connection` (если нет — добавить), и добавить тест. Фикстура `sched_setup` (см. `apps/scheduling/tests/conftest.py`): группа A (teacher_a, слот Пн 10:00, total 8 → уроки по понедельникам 06-01..07-20), teacher_b с именем `__sched_B__`:

```python
@pytest.mark.django_db
def test_substitute_shows_in_substitute_calendar_on_its_date(sched_setup):
    """Занятие с заменой попадает в календарь ПОДМЕНЯЮЩЕГО (B) на свою дату, а не
    преподавателя контента (A); occurrence несёт teacherOverride = имя B."""
    s = sched_setup
    repository.generate_for_group(s['group_a'])
    target_date = D(2026, 6, 15)   # понедельник — курсовая строка группы A
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE planned_lessons SET substitute_teacher_id=%s "
            "WHERE group_id=%s AND scheduled_date=%s AND seq IS NOT NULL",
            [s['teacher_b'], s['group_a'], target_date],
        )

    # Календарь ПОДМЕНЯЮЩЕГО (B) на эту дату — строка есть, эффективный препод = B.
    cal_b = services.build_calendar(target_date, target_date, teacher_id=s['teacher_b'])
    b_rows = [o for o in cal_b['occurrences'] if o['groupId'] == s['group_a']]
    assert len(b_rows) == 1
    assert b_rows[0]['teacher'] == '__sched_B__'
    assert b_rows[0]['teacherOverride'] == '__sched_B__'

    # Календарь преподавателя КОНТЕНТА (A) на эту дату — строки с заменой нет.
    cal_a = services.build_calendar(target_date, target_date, teacher_id=s['teacher_a'])
    a_rows = [o for o in cal_a['occurrences']
              if o['groupId'] == s['group_a'] and o['date'] == '2026-06-15']
    assert a_rows == []
```

Убедиться, что вверху файла есть `import pytest` (есть) и `from apps.scheduling import repository, services` (есть).

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && python -m pytest apps/scheduling/tests/test_build_calendar.py -v -k substitute`
Expected: FAIL — скоуп идёт по `teacher_id`, строка с заменой не попадает в календарь B (или попадает в календарь A).

- [ ] **Step 3: Скоуп окна по эффективному преподавателю**

В `journal_django/apps/scheduling/repository.py` в начало файла к импортам добавить:

```python
from django.db.models import F, Min, Q
```

(строка 14 сейчас `from django.db.models import F, Min` — заменить на строку с `Q`.)

Заменить `.filter(...)` в `planned_lessons_in_window` (строки 108-113) на:

```python
        .filter(
            Q(substitute_teacher_id=teacher_id)
            | Q(substitute_teacher_id__isnull=True, teacher_id=teacher_id),
            group__active=True,
            scheduled_date__gte=window_from,
            scheduled_date__lte=window_to,
        )
```

И добавить `substitute_teacher_id` в `.values(...)` (строка 115):

```python
            'id', 'seq', 'lesson_number', 'scheduled_date', 'scheduled_time',
            'teacher_id', 'substitute_teacher_id', 'status', 'fact_lesson_id',
            'moved_from_date',
```

- [ ] **Step 4: Эффективный преподаватель в occurrence-dict**

В `journal_django/apps/scheduling/services.py` в `_planned_occurrence_dict` заменить блок вычисления преподавателя (строки 76-79) на:

```python
    sub_id = r.get('substitute_teacher_id')
    content_teacher_id = r['teacher_id']
    group_teacher_id = r['group_teacher_id']
    effective_id = sub_id or content_teacher_id
    is_override = (sub_id is not None) or (
        content_teacher_id is not None and content_teacher_id != group_teacher_id
    )
    teacher = tnames.get(effective_id) if effective_id else tnames.get(group_teacher_id)
```

И в возвращаемом dict (строка 86) заменить:

```python
        'teacherOverride': tnames.get(effective_id) if is_override else None,
```

- [ ] **Step 5: Эффективный преподаватель в плане (admin «Обзор плана»)**

В `journal_django/apps/scheduling/repository.py` в `get_plan` (строки 546-551) добавить `substitute_teacher_id` в `.values(...)`:

```python
            'id', 'seq', 'lesson_number', 'scheduled_date', 'scheduled_time',
            'teacher_id', 'substitute_teacher_id', 'status', 'fact_lesson_id',
            'moved_from_date',
```

В `_plan_row_dict` (строки 471-490) заменить вычисление преподавателя так, чтобы `teacher_id`/`teacher_name` показывали эффективного преподавателя (сохраняя контракт фронта — отдельного поля замены фронт не ждёт):

```python
def _plan_row_dict(r: dict, tnames: dict[int, str]) -> dict:
    """Сериализуемая плановая строка из .values()-словаря. is_extra = seq IS NULL.
    teacher_id/teacher_name — ЭФФЕКТИВНЫЙ преподаватель (замена на дату, если есть,
    иначе преподаватель контента) — чтобы admin-план показывал того, кто реально ведёт."""
    ln = r['lesson_number']
    effective_teacher_id = r.get('substitute_teacher_id') or r['teacher_id']
    return {
        'id': r['id'],
        'seq': r['seq'],
        'lesson_number': float(ln) if ln is not None else None,
        'scheduled_date': _iso(r['scheduled_date']),
        'scheduled_time': _hhmm(r['scheduled_time']),
        'teacher_id': effective_teacher_id,
        'teacher_name': tnames.get(effective_teacher_id),
        'status': r['status'],
        'fact_lesson_id': r['fact_lesson_id'],
        'fact_date': _iso(r.get('fact_date')),
        'record_url': r.get('record_url'),
        'moved_from_date': _iso(r['moved_from_date']),
        'is_extra': r['seq'] is None,
    }
```

В `_plan_row_dict_obj` (строки 493-505) добавить `substitute_teacher_id` в передаваемый dict:

```python
        'teacher_id': p.teacher_id,
        'substitute_teacher_id': p.substitute_teacher_id,
```

- [ ] **Step 6: Запустить тест календаря — убедиться, что проходит**

Run: `cd journal_django && python -m pytest apps/scheduling/tests/test_build_calendar.py -v`
Expected: PASS.

- [ ] **Step 7: Полный регресс scheduling + teacher_spa + dashboard**

Run: `cd journal_django && python -m pytest apps/scheduling apps/teacher_spa apps/dashboard -v`
Expected: PASS (occurrence-контракт `teacher`/`teacherOverride` не изменился по форме).

- [ ] **Step 8: Commit**

```bash
git add journal_django/apps/scheduling/repository.py journal_django/apps/scheduling/services.py journal_django/apps/scheduling/tests/test_build_calendar.py
git commit -m "feat(scheduling): calendar & plan read effective teacher (substitute on its date)"
```

---

## Phase 5 — Консолидация: заморозка через тот же примитив + документация

### Task 8: Заморозка обходит занятые даты (единый примитив)

**Files:**
- Modify: `journal_django/apps/scheduling/repository.py:1090-1160` (`freeze_individual_group`)
- Modify: `journal_django/apps/scheduling/repository.py:1038-1087` (`preview_freeze`)
- Test: `journal_django/apps/scheduling/tests/test_freeze_scheduling.py`

- [ ] **Step 1: Написать тест — заморозка не наезжает на done-пин**

В `journal_django/apps/scheduling/tests/test_freeze_scheduling.py` добавить тест. Фикстура `indiv_group`: слот среда 10:00, seq1..4 по средам 07-01..07-22, extra на 07-10. Добавляем done-пин на будущую среду 08-12 (куда иначе встал бы хвост):

```python
@pytest.mark.django_db
def test_freeze_relay_skips_occupied_slot_dates(indiv_group):
    """Перекладка хвоста при заморозке обходит занятую слот-дату (done-урок на
    будущей среде), оставаясь непрерывной — единый примитив relay со skip_dates."""
    gid = indiv_group['group']
    now = datetime.datetime(2026, 7, 1, 12, 0)
    # Проведённый урок (пин) на будущую среду 2026-08-12, куда иначе встал бы хвост.
    PlannedLesson.objects.create(
        group_id=gid, seq=5, lesson_number=5,
        scheduled_date=datetime.date(2026, 8, 12), scheduled_time=datetime.time(10, 0),
        teacher_id=indiv_group['teacher'], status=DONE, created_at=now, updated_at=now)

    relaid = sched_repo.freeze_individual_group(
        gid, frozen_from=datetime.date(2026, 7, 8),
        resume_date=datetime.date(2026, 8, 5))
    assert relaid == 3

    rows = {r.seq: r for r in PlannedLesson.objects.filter(
        group_id=gid, seq__isnull=False, status=PENDING).order_by('seq')}
    dates = [rows[s].scheduled_date for s in (2, 3, 4)]
    # Ни одна переложенная строка не встала на занятую 2026-08-12 (done),
    # каденция непрерывна по свободным средам (08-12 обойдена).
    assert dates == [datetime.date(2026, 8, 5),
                     datetime.date(2026, 8, 19),
                     datetime.date(2026, 8, 26)]
```

- [ ] **Step 2: Запустить — убедиться, что падает (или зафиксировать текущее)**

Run: `cd journal_django && python -m pytest apps/scheduling/tests/test_freeze_scheduling.py -v -k skip`
Expected: FAIL — текущая заморозка не передаёт skip_dates, хвост может наехать на занятую дату.

- [ ] **Step 3: Передать skip_dates в перекладку заморозки**

В `journal_django/apps/scheduling/repository.py` в `freeze_individual_group`, в блоке (б) перед вызовом `planner.relay_from_date` (около строки 1143) собрать занятые даты и передать их:

```python
        by_seq = {p.seq: p for p in tail}
        tail_ids = {p.id for p in tail}
        skip_dates = frozenset(
            PlannedLesson.objects
            .filter(group_id=group_id)
            .exclude(id__in=tail_ids)
            .values_list('scheduled_date', flat=True)
        )
        relaid = planner.relay_from_date(
            [_row_from_model(p) for p in tail],
            resume_date=resume_date,
            slots=open_slots,
            duration_minutes=g['lesson_duration_minutes'],
            skip_dates=skip_dates,
        )
```

В цикле записи (около строки 1150-1157) добавить очистку замены при смене даты (единообразно с `_relay_tail`):

```python
        to_update = []
        for cr in relaid:
            p = by_seq[cr.seq]
            date_changed = p.scheduled_date != cr.scheduled_date
            p.scheduled_date = cr.scheduled_date
            p.scheduled_time = cr.scheduled_time
            p.moved_from_date = None
            if date_changed:
                p.substitute_teacher_id = None
            p.updated_at = now
            to_update.append(p)
        PlannedLesson.objects.bulk_update(
            to_update,
            ['scheduled_date', 'scheduled_time', 'moved_from_date',
             'substitute_teacher', 'updated_at'])
        return len(to_update)
```

В `preview_freeze` (строки 1075-1080) — тот же `skip_dates` в предпросмотрном вызове `relay_from_date`, чтобы предпросмотр совпадал с фактической перекладкой:

```python
            tail_ids = {p.id for p in tail}
            skip_dates = frozenset(
                PlannedLesson.objects
                .filter(group_id=group_id)
                .exclude(id__in=tail_ids)
                .values_list('scheduled_date', flat=True)
            )
            relaid = planner.relay_from_date(
                [_row_from_model(p) for p in tail],
                resume_date=frozen_until,
                slots=open_slots,
                duration_minutes=g['lesson_duration_minutes'],
                skip_dates=skip_dates,
            )
```

- [ ] **Step 4: Запустить тесты заморозки — убедиться, что зелёные**

Run: `cd journal_django && python -m pytest apps/scheduling/tests/test_freeze_scheduling.py apps/scheduling/tests/test_preview_freeze.py apps/students/tests/test_status_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/scheduling/repository.py journal_django/apps/scheduling/tests/test_freeze_scheduling.py
git commit -m "refactor(scheduling): freeze relay uses shared skip_dates primitive"
```

---

### Task 9: Документация механизма

**Files:**
- Modify: `journal_django/docs/lesson-scheduling.md` (или `docs/lesson-scheduling.md` — найти существующий)

- [ ] **Step 1: Найти документ**

Run: `cd journal_django && find . -name lesson-scheduling.md -not -path '*/.venv/*' 2>/dev/null; find .. -name lesson-scheduling.md -not -path '*/.venv/*' -not -path '*/node_modules/*' 2>/dev/null`
Expected: путь к файлу.

- [ ] **Step 2: Обновить разделы «Отмена» и «Замена преподавателя»**

Внести в документ:
- **Отмена** больше не «сдвиг +7»: ставит маркер на дату и **непрерывно перекладывает** курсовой хвост от даты отмены по открытому слоту, обходя занятые даты (done/маркеры/extra). Несколько отмен → курс продлевается ровно на число отмен, без пустых недель, независимо от порядка.
- **Замена преподавателя (разовая)** хранится в `planned_lessons.substitute_teacher_id` — это свойство КАЛЕНДАРНОЙ ДАТЫ, а не позиции курса. При любой смене `scheduled_date` строки (отмена/заморозка/перекладка) замена обнуляется. Эффективный преподаватель = `substitute_teacher_id ?? teacher_id`; календарь и план показывают эффективного.
- **Единый примитив** `relay_from_date(..., skip_dates=...)`: и отмена, и заморозка перекладывают хвост одним способом.

- [ ] **Step 3: Commit**

```bash
git add -A -- '*lesson-scheduling.md'
git commit -m "docs(scheduling): unified relay cancel + date-bound substitute teacher"
```

---

## Финальная проверка

- [ ] **Полный прогон backend-тестов**

Run: `cd journal_django && python -m pytest -q`
Expected: все тесты зелёные (в т.ч. changelog registry, freeze, plan-api, calendar).

- [ ] **Ручная проверка сценариев багов (через verify-скилл или API)**

1. Замена преподавателя на урок → отмена этого урока → сдвинутая строка БЕЗ замены, замена осталась на отменённой (зачёркнутой) дате. **Баг №1 закрыт.**
2. Отмена урока → хвост +1 неделя без дыр. Затем отмена более раннего урока → хвост суммарно +2 недели, **расписание непрерывно (никаких пустых недель)**. **Баг №2 закрыт.**

---

## Заметки по объёму / что НЕ входит (YAGNI)

- **Разовый перенос одного урока** (`reschedule` на произвольную дату) — остаётся пином, `relay_from_date` его не двигает (он не в хвосте >= from_date по семантике отмены; при заморозке его дата попадает в окно — тогда он перекладывается, что корректно). Семантику `reschedule.new_teacher_id` (пишет `teacher_id`) в этом плане НЕ меняем.
- **Мультислотовые группы в «переносе навсегда»** — существующий guard оставлен как есть.
- **Фронтенд не меняется**: контракт occurrence (`teacher`, `teacherOverride`) и плана (`teacher_id`, `teacher_name`) сохранён по форме — меняется только источник значения (эффективный преподаватель).
- **Прошлое (done/факты)** движок не трогает — работает только с pending/overdue хвостом.
