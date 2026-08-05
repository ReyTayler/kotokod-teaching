# Инвариант «плановая дата = фактическая» + проверка здоровья планов — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** курсовая позиция плана, за которой закреплён проведённый урок, всегда стоит на дате этого урока; плюс read-only проверка в разделе «Синхро», показывающая группы, где план разъехался с занятиями.

**Architecture:** слой 0 — общий помощник `sync_position_date` в `apps/scheduling/repository.py`, вызываемый из четырёх точек, где меняется связка «позиция ↔ факт» или дата факта. Слой 1 — новый read-only модуль `apps/scheduling/health.py` с семью проверками, обёрнутый по существующему образцу `apps/sync/backfills/*` → Celery-задача → строка в `ACTIONS` → карточка на странице «Синхро».

**Tech Stack:** Python 3 / Django + DRF, PostgreSQL, Celery, pytest; фронт — React 19 + TanStack Query v5 (`journal_django/frontend/admin-src`).

**Спека:** `docs/superpowers/specs/2026-08-05-plan-health-design.md`.

**Как гонять тесты:** из `journal_django/`. Точечно — `pytest <path>::<test> -v`. Перед коммитом крупного куска и в самом конце — **полный** `pytest -q`, не по приложениям: часть приложений no-op'ит `django_db_setup`, часть пересоздаёт тестовую базу, прогон по частям даёт ложный результат.

---

## Структура файлов

| Файл | Ответственность | Задача |
|---|---|---|
| `apps/scheduling/repository.py` | +`sync_position_date`; правки `attach_fact`, `link_facts`, `relink_fact` | 1–4 |
| `apps/lessons/services.py` | вызов помощника при правке даты урока | 5 |
| `apps/scheduling/health.py` | **создать** — семь проверок, только чтение | 6–7 |
| `apps/sync/backfills/check_plan_health.py` | **создать** — обёртка `run()` | 8 |
| `apps/sync/tasks.py` | Celery-задача | 8 |
| `apps/sync/views.py` | строка в `ACTIONS` | 8 |
| `frontend/admin-src/src/lib/sync.ts` | тип действия, флаг `readOnly`, группа `checks` | 9 |
| `frontend/admin-src/src/pages/sync/SyncActionCard.tsx` | не рендерить чекбокс при `readOnly` | 9 |
| `frontend/admin-src/src/pages/sync/SyncPage.tsx` | секция «Проверки» | 9 |
| `apps/scheduling/tests/test_sync_position_date.py` | **создать** — тесты слоя 0 | 1–5 |
| `apps/scheduling/tests/test_plan_health.py` | **создать** — тесты проверок | 6–7 |
| `apps/sync/tests/test_check_plan_health.py` | **создать** — обёртка + RBAC | 8 |

---

## Task 1: Помощник `sync_position_date`

**Files:**
- Modify: `journal_django/apps/scheduling/repository.py` (добавить функцию после `attach_fact`, ~строка 745)
- Test: `journal_django/apps/scheduling/tests/test_sync_position_date.py`

- [ ] **Step 1: Написать падающий тест**

Создать `journal_django/apps/scheduling/tests/test_sync_position_date.py`:

```python
"""
Тесты инварианта «плановая дата курсовой позиции = дата её факта».
Спека: docs/superpowers/specs/2026-08-05-plan-health-design.md §2-3.
"""
from __future__ import annotations

import datetime

import pytest
from django.db import connection

from apps.scheduling.models import PlannedLesson
from apps.scheduling.repository import sync_position_date

pytestmark = pytest.mark.django_db


def _lesson(group_id: int, teacher_id: int, date: str, number, lesson_type='regular') -> int:
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, '
            'lesson_duration_minutes, lesson_type, submitted_at, submitted_by_token) '
            "VALUES (%s,%s,%s,%s,60,%s,NOW(),'__sync_pos_test__') RETURNING id",
            [group_id, teacher_id, date, number, lesson_type])
        return cur.fetchone()[0]


def test_moves_position_to_fact_date(group_with_group):
    """Позиция стоит на 07.07, факт проведён 09.07 → позиция переезжает на 09.07."""
    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-07-09', 1)
    pos = PlannedLesson.objects.get(group_id=gid, seq=1)
    pos.fact_lesson_id = lesson_id
    pos.status = 'done'
    pos.save(update_fields=['fact_lesson', 'status'])

    assert sync_position_date(lesson_id) is True

    pos.refresh_from_db()
    assert pos.scheduled_date == datetime.date(2026, 7, 9)
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `pytest apps/scheduling/tests/test_sync_position_date.py::test_moves_position_to_fact_date -v`
Expected: FAIL — `ImportError: cannot import name 'sync_position_date'`

- [ ] **Step 3: Реализовать помощник**

В `journal_django/apps/scheduling/repository.py` сразу после `attach_fact` вставить:

```python
def sync_position_date(lesson_id: int) -> bool:
    """
    Привести плановую дату курсовой позиции к дате её факта.

    Инвариант (спека 2026-08-05 §2): позиция, за которой закреплён проведённый
    урок, стоит на дате этого урока. Иначе «проведённое» занятие висит в
    календаре не в свой день, а операции планирования (permanent_change,
    cancel) кладут хвост поверх него — так сломались ПИ337, ПИ314, РИ283.

    Разовый перенос (moved_from_date) гасится: он описывал плановое движение
    занятия, а новая дата приходит от факта и к тому переносу отношения не
    имеет. Время позиции не трогаем — у факта времени нет.

    Не-курсовые занятия (доп.урок, сгорание) позиций не занимают → no-op.
    Идемпотентна: даты уже совпадают → ничего не пишет, возвращает False.
    True — позиция сдвинута.
    """
    lesson = (
        Lesson.objects.filter(id=lesson_id)
        .values('lesson_date', 'lesson_type')
        .first()
    )
    if lesson is None or lesson['lesson_type'] not in COURSE_LESSON_TYPES:
        return False

    with transaction.atomic():
        position = (
            PlannedLesson.objects.select_for_update()
            .filter(fact_lesson_id=lesson_id, seq__isnull=False)
            .first()
        )
        if position is None or position.scheduled_date == lesson['lesson_date']:
            return False
        position.scheduled_date = lesson['lesson_date']
        position.moved_from_date = None
        position.updated_at = msk_now()
        position.save(update_fields=[
            'scheduled_date', 'moved_from_date', 'updated_at',
        ])
        return True
```

Импорты `Lesson`, `COURSE_LESSON_TYPES`, `transaction`, `msk_now`, `PlannedLesson` в файле уже есть — добавлять ничего не нужно.

- [ ] **Step 4: Запустить тест, убедиться что проходит**

Run: `pytest apps/scheduling/tests/test_sync_position_date.py::test_moves_position_to_fact_date -v`
Expected: PASS

- [ ] **Step 5: Дописать тесты краевых случаев**

Добавить в тот же файл:

```python
def test_idempotent_when_dates_already_match(group_with_group):
    """Даты совпадают → ничего не пишем, False."""
    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-07-07', 1)
    pos = PlannedLesson.objects.get(group_id=gid, seq=1)
    pos.fact_lesson_id = lesson_id
    pos.status = 'done'
    pos.save(update_fields=['fact_lesson', 'status'])

    assert sync_position_date(lesson_id) is False


def test_clears_moved_from_date(group_with_group):
    """Метка разового переноса гасится (спека §3.2)."""
    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-07-09', 1)
    pos = PlannedLesson.objects.get(group_id=gid, seq=1)
    pos.fact_lesson_id = lesson_id
    pos.status = 'done'
    pos.moved_from_date = datetime.date(2026, 7, 1)
    pos.save(update_fields=['fact_lesson', 'status', 'moved_from_date'])

    sync_position_date(lesson_id)

    pos.refresh_from_db()
    assert pos.moved_from_date is None


def test_ignores_system_lesson(group_with_group):
    """Доп.урок позиции курса не занимает → no-op, без исключения."""
    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-07-09', 1, lesson_type='extra')
    assert sync_position_date(lesson_id) is False


def test_missing_lesson_is_noop(group_with_group):
    """Несуществующий урок не роняет вызов."""
    assert sync_position_date(999_999_999) is False


def test_fact_without_position_is_noop(group_with_group):
    """Факт есть, позиции за ним не закреплено → no-op."""
    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-07-09', 1)
    assert sync_position_date(lesson_id) is False


def test_allows_landing_on_occupied_date(group_with_group):
    """Дата факта совпала с датой другой позиции — разрешено (спека §3.2):
    два реальных занятия в один день бывают."""
    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-07-14', 1)
    pos = PlannedLesson.objects.get(group_id=gid, seq=1)   # стоит на 07.07
    pos.fact_lesson_id = lesson_id
    pos.status = 'done'
    pos.save(update_fields=['fact_lesson', 'status'])

    assert sync_position_date(lesson_id) is True

    pos.refresh_from_db()
    assert pos.scheduled_date == datetime.date(2026, 7, 14)
    # Позиция seq=2 как стояла на 14.07, так и стоит — коллизия допустима.
    assert PlannedLesson.objects.filter(
        group_id=gid, scheduled_date='2026-07-14').count() == 2
```

- [ ] **Step 6: Прогнать файл целиком**

Run: `pytest apps/scheduling/tests/test_sync_position_date.py -v`
Expected: 7 passed

- [ ] **Step 7: Коммит**

```bash
git add journal_django/apps/scheduling/repository.py journal_django/apps/scheduling/tests/test_sync_position_date.py
git commit -m "feat(scheduling): помощник sync_position_date — плановая дата следует за фактической"
```

---

## Task 2: `attach_fact` держит инвариант при записи урока

**Files:**
- Modify: `journal_django/apps/scheduling/repository.py:733-744`
- Test: `journal_django/apps/scheduling/tests/test_sync_position_date.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `test_sync_position_date.py`:

```python
def test_attach_fact_sets_position_date(group_with_group):
    """Запись урока задним числом ставит позицию на дату урока (спека §3.2):
    именно так разъехались позиции 20-23 в ПИ337."""
    from apps.scheduling.repository import attach_fact

    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-06-30', 1)   # позиция стоит на 07.07
    pos = PlannedLesson.objects.get(group_id=gid, seq=1)

    attach_fact(pos.id, lesson_id)

    pos.refresh_from_db()
    assert pos.status == 'done'
    assert pos.fact_lesson_id == lesson_id
    assert pos.scheduled_date == datetime.date(2026, 6, 30)
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `pytest apps/scheduling/tests/test_sync_position_date.py::test_attach_fact_sets_position_date -v`
Expected: FAIL — `assert datetime.date(2026, 7, 7) == datetime.date(2026, 6, 30)`

- [ ] **Step 3: Реализовать**

Заменить тело `attach_fact` в `journal_django/apps/scheduling/repository.py`:

```python
def attach_fact(planned_lesson_id: int, lesson_id: int) -> None:
    """
    Закрепить факт за позицией курса: fact_lesson_id + status='done' + плановая
    дата позиции = дата урока (инвариант спеки 2026-08-05 §2).

    Вызывается из record_lesson внутри той же транзакции, СРАЗУ после вставки
    урока и только по позиции, уже залоченной lock_course_position. Заменяет для
    этого факта «угадывающий» link_facts: позиция названа явно, номер урока взят
    из неё, поэтому сопоставлять по номеру нечего.

    Дата урока читается отдельным запросом: record_lesson её знает, но передавать
    через сигнатуру — лишняя связность, а запрос по первичному ключу тривиален.
    """
    fields = {
        'fact_lesson_id': lesson_id,
        'status': DONE,
        'updated_at': msk_now(),
    }
    lesson_date = (
        Lesson.objects.filter(id=lesson_id)
        .values_list('lesson_date', flat=True)
        .first()
    )
    if lesson_date is not None:
        # moved_from_date гасим по той же причине, что в sync_position_date:
        # метка описывала плановое движение, дата приходит от факта.
        fields['scheduled_date'] = lesson_date
        fields['moved_from_date'] = None

    PlannedLesson.objects.filter(id=planned_lesson_id).update(**fields)
```

- [ ] **Step 4: Запустить**

Run: `pytest apps/scheduling/tests/test_sync_position_date.py -v`
Expected: 8 passed

- [ ] **Step 5: Прогнать соседей — запись урока трогает много чего**

Run: `pytest apps/lessons apps/scheduling apps/teacher_spa -q`
Expected: без падений. Если падает тест, ожидавший «позиция осталась на плановой дате» — это ожидаемая смена поведения: поправить ожидание теста и в его докстринге сослаться на спеку.

- [ ] **Step 6: Коммит**

```bash
git add journal_django/apps/scheduling/repository.py journal_django/apps/scheduling/tests/test_sync_position_date.py
git commit -m "feat(scheduling): attach_fact ставит позицию на дату урока"
```

---

## Task 3: `link_facts` держит инвариант при пакетной привязке

**Files:**
- Modify: `journal_django/apps/scheduling/repository.py:435-530`
- Test: `journal_django/apps/scheduling/tests/test_sync_position_date.py`

- [ ] **Step 1: Написать падающий тест**

```python
def test_link_facts_sets_position_dates(group_with_group):
    """Пакетная привязка тоже ставит плановую дату позиции по факту."""
    from apps.scheduling.repository import link_facts

    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-06-30', 1)   # позиция seq=1 стоит на 07.07

    assert link_facts(gid) == 1

    pos = PlannedLesson.objects.get(group_id=gid, seq=1)
    assert pos.status == 'done'
    assert pos.fact_lesson_id == lesson_id
    assert pos.scheduled_date == datetime.date(2026, 6, 30)
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `pytest apps/scheduling/tests/test_sync_position_date.py::test_link_facts_sets_position_dates -v`
Expected: FAIL — дата осталась 2026-07-07

- [ ] **Step 3: Реализовать**

В `link_facts` три правки.

Первая — докстринг, абзац про дату заменить на:

```python
    """
    Слинковать плановые строки группы с проведёнными уроками (факт) и проставить
    status='done'. Плановая дата позиции ставится равной дате факта — инвариант
    спеки 2026-08-05 §2 (прежде дата НЕ перезаписывалась, из-за чего проведённые
    занятия оставались в календаре не в свой день; так сломались ПИ337/ПИ314/РИ283).
```

Вторая — в проходе 1 (матчинг по `lesson_number`) после `p.status = DONE` добавить:

```python
            p.scheduled_date = chosen['lesson_date']
            p.moved_from_date = None
```

Третья — в проходе 2 (матчинг по дате) после `p.status = DONE` добавить те же две строки (там даты и так равны, но код единообразен), и расширить `bulk_update`:

```python
        if to_update:
            PlannedLesson.objects.bulk_update(
                to_update,
                ['fact_lesson', 'status', 'scheduled_date', 'moved_from_date',
                 'updated_at'],
            )
```

- [ ] **Step 4: Запустить**

Run: `pytest apps/scheduling/tests/test_sync_position_date.py -v`
Expected: 9 passed

- [ ] **Step 5: Коммит**

```bash
git add journal_django/apps/scheduling/repository.py journal_django/apps/scheduling/tests/test_sync_position_date.py
git commit -m "feat(scheduling): link_facts ставит плановые даты по фактам"
```

---

## Task 4: `relink_fact` держит инвариант при смене номера

**Files:**
- Modify: `journal_django/apps/scheduling/repository.py:533-595`
- Test: `journal_django/apps/scheduling/tests/test_sync_position_date.py`

- [ ] **Step 1: Написать падающий тест**

```python
def test_relink_fact_sets_position_date(group_with_group):
    """Смена номера урока переносит факт на позицию своего номера — и та
    встаёт на дату факта."""
    from apps.scheduling.repository import relink_fact

    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-06-30', 1)
    first = PlannedLesson.objects.get(group_id=gid, seq=1)
    first.fact_lesson_id = lesson_id
    first.status = 'done'
    first.save(update_fields=['fact_lesson', 'status'])

    with connection.cursor() as cur:
        cur.execute('UPDATE lessons SET lesson_number=2 WHERE id=%s', [lesson_id])

    assert relink_fact(lesson_id) is True

    first.refresh_from_db()
    assert first.fact_lesson_id is None
    assert first.status == 'pending'

    second = PlannedLesson.objects.get(group_id=gid, seq=2)
    assert second.fact_lesson_id == lesson_id
    assert second.scheduled_date == datetime.date(2026, 6, 30)
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `pytest apps/scheduling/tests/test_sync_position_date.py::test_relink_fact_sets_position_date -v`
Expected: FAIL — у второй позиции дата осталась 2026-07-14

- [ ] **Step 3: Реализовать**

В `relink_fact` расширить набор читаемых полей урока:

```python
    lesson = (
        Lesson.objects.filter(id=lesson_id)
        .values('id', 'group_id', 'lesson_number', 'lesson_type', 'lesson_date')
        .first()
    )
```

и в блоке записи целевой позиции добавить дату:

```python
        target.fact_lesson_id = lesson_id
        target.status = DONE
        target.scheduled_date = lesson['lesson_date']
        target.moved_from_date = None
        target.updated_at = now
        target.save(update_fields=[
            'fact_lesson', 'status', 'scheduled_date', 'moved_from_date',
            'updated_at',
        ])
        return True
```

- [ ] **Step 4: Запустить**

Run: `pytest apps/scheduling/tests/test_sync_position_date.py -v`
Expected: 10 passed

- [ ] **Step 5: Коммит**

```bash
git add journal_django/apps/scheduling/repository.py journal_django/apps/scheduling/tests/test_sync_position_date.py
git commit -m "feat(scheduling): relink_fact ставит позицию на дату факта"
```

---

## Task 5: Правка даты урока двигает позицию

**Files:**
- Modify: `journal_django/apps/lessons/services.py:343-364`
- Test: `journal_django/apps/scheduling/tests/test_sync_position_date.py`

- [ ] **Step 1: Написать падающий тест**

```python
def test_update_lesson_date_moves_position(group_with_group):
    """Правка даты урока двигает плановую строку — прямая причина поломки ПИ337."""
    from apps.lessons.services import update_lesson
    from apps.scheduling.repository import attach_fact

    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-07-07', 1)
    pos = PlannedLesson.objects.get(group_id=gid, seq=1)
    attach_fact(pos.id, lesson_id)

    update_lesson(lesson_id, {'lesson_date': datetime.date(2026, 7, 2)})

    pos.refresh_from_db()
    assert pos.scheduled_date == datetime.date(2026, 7, 2)


def test_update_lesson_without_date_leaves_position(group_with_group):
    """Правка без смены даты позицию не трогает."""
    from apps.lessons.services import update_lesson
    from apps.scheduling.repository import attach_fact

    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-07-07', 1)
    pos = PlannedLesson.objects.get(group_id=gid, seq=1)
    attach_fact(pos.id, lesson_id)

    update_lesson(lesson_id, {'record_url': 'https://example.test/rec'})

    pos.refresh_from_db()
    assert pos.scheduled_date == datetime.date(2026, 7, 7)
```

- [ ] **Step 2: Запустить, убедиться что первый падает**

Run: `pytest apps/scheduling/tests/test_sync_position_date.py::test_update_lesson_date_moves_position -v`
Expected: FAIL — дата позиции осталась 2026-07-07

- [ ] **Step 3: Реализовать**

В `journal_django/apps/lessons/services.py` расширить существующий импорт (строки 29–32) — было:

```python
from apps.scheduling.repository import (
    attach_fact, find_course_position_by_date_and_number, link_facts,
    lock_course_position, relink_fact,
)
```

стало:

```python
from apps.scheduling.repository import (
    attach_fact, find_course_position_by_date_and_number, link_facts,
    lock_course_position, relink_fact, sync_position_date,
)
```

Затем в `update_lesson` вставить вызов перед пересчётом ключа отправки:

```python
    # Плановая дата проведённого занятия следует за фактической (инвариант спеки
    # 2026-08-05 §2). Прежде дата НЕ синхронизировалась, и правка дат уроков
    # оставляла плановые строки на старых датах: занятие висело в календаре не в
    # свой день, а «перенос навсегда» клал хвост курса поверх него (ПИ337).
    if fields.get('lesson_date') is not None:
        sync_position_date(lesson_id)

    # Ключ отправки выведен из даты и позиции — при их правке он обязан
    # пересчитаться, иначе появляются два скрытых дефекта:
    #   • правка даты: старая дата остаётся заблокированной навсегда, а на новую
    #     спокойно ляжет второй урок;
    #   • правка номера: факт уезжает на другую позицию (relink_fact), а ключ
    #     остаётся указывать на прежнюю — та выглядит свободной, но запись на неё
    #     упирается в уникальный индекс, то есть ЛОЖНЫЙ 409 и незаполнимая позиция.
    if fields.get('lesson_date') is not None or fields.get('lesson_number') is not None:
        _refresh_submission_key(lesson_id)
```

Важно: `sync_position_date` вызывается **после** `relink_fact`/`link_facts` (они выше по телу функции) и **до** `_refresh_submission_key` — ключ считается от актуальной позиции.

- [ ] **Step 4: Запустить**

Run: `pytest apps/scheduling/tests/test_sync_position_date.py -v`
Expected: 12 passed

- [ ] **Step 5: Прогнать полный набор — слой 0 закончен**

Run: `pytest -q`
Expected: без падений. Упавшие тесты, ожидающие расхождения плановой и фактической даты, — ожидаемая смена доктрины: поправить ожидание и сослаться в докстринге теста на спеку.

- [ ] **Step 6: Коммит**

```bash
git add journal_django/apps/lessons/services.py journal_django/apps/scheduling/tests/test_sync_position_date.py
git commit -m "feat(lessons): правка даты урока двигает плановую строку"
```

---

## Task 6: Проверки здоровья — сводка по всем группам

**Files:**
- Create: `journal_django/apps/scheduling/health.py`
- Test: `journal_django/apps/scheduling/tests/test_plan_health.py`

- [ ] **Step 1: Написать падающий тест**

Создать `journal_django/apps/scheduling/tests/test_plan_health.py`:

```python
"""
Тесты проверок здоровья планов. Спека:
docs/superpowers/specs/2026-08-05-plan-health-design.md §4.
"""
from __future__ import annotations

import datetime

import pytest
from django.db import connection

from apps.scheduling import health
from apps.scheduling.models import PlannedLesson

pytestmark = pytest.mark.django_db


def _lesson(group_id: int, teacher_id: int, date: str, number, lesson_type='regular') -> int:
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, '
            'lesson_duration_minutes, lesson_type, submitted_at, submitted_by_token) '
            "VALUES (%s,%s,%s,%s,60,%s,NOW(),'__health_test__') RETURNING id",
            [group_id, teacher_id, date, number, lesson_type])
        return cur.fetchone()[0]


def _counts_for(group_id: int) -> dict:
    report = health.check_all()
    for row in report['groups']:
        if row['group_id'] == group_id:
            return row['counts']
    return {}


def test_healthy_group_not_reported(group_with_group):
    """Здоровая группа в отчёт не попадает."""
    gid, _tid = group_with_group
    assert _counts_for(gid) == {}


def test_detects_collision(group_with_group):
    """Две курсовые позиции на одну дату и время."""
    gid, _tid = group_with_group
    PlannedLesson.objects.filter(group_id=gid, seq=2).update(
        scheduled_date='2026-07-07')   # seq=1 уже там, время у всех 18:00
    assert _counts_for(gid).get('collision') == 1
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `pytest apps/scheduling/tests/test_plan_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.scheduling.health'`

- [ ] **Step 3: Создать модуль**

Создать `journal_django/apps/scheduling/health.py`:

```python
"""
Проверки здоровья планов занятий — ТОЛЬКО ЧТЕНИЕ, ничего не меняют.

Ловят рассогласования между planned_lessons и lessons, которые ломают календарь
и операции планирования. Разбор случаев и обоснование набора проверок —
docs/superpowers/specs/2026-08-05-plan-health-design.md §4.

check_all() считает сводку по всем активным группам ОДНИМ запросом: на проде 134
активные группы, цикл по группам недопустим (CLAUDE.md, раздел про
производительность). check_group() — те же проверки по одной группе, но с
конкретными строками для интерфейса.

Длина курса берётся как COALESCE(groups.lessons_total, directions.total_lessons) —
ручная длина группы перекрывает длину направления, см. apps.groups.course_length.
"""
from __future__ import annotations

from django.db import connection

from apps.lessons.models import COURSE_LESSON_TYPES

# Ключи проверок в порядке убывания серьёзности. Русские подписи — на фронте.
CHECKS = (
    'fact_without_position',
    'beyond_course',
    'number_mismatch',
    'date_mismatch',
    'done_in_future',
    'collision',
    'duplicate_dates',
)

_SUMMARY_SQL = """
WITH course_len AS (
  SELECT g.id AS gid, g.name,
         COALESCE(g.lessons_total, d.total_lessons) AS total
  FROM groups g LEFT JOIN directions d ON d.id = g.direction_id
  WHERE g.active
),
c_collision AS (
  SELECT group_id gid, count(*) n FROM (
    SELECT group_id, scheduled_date, scheduled_time FROM planned_lessons
    WHERE seq IS NOT NULL AND status <> 'cancelled'
    GROUP BY 1,2,3 HAVING count(*) > 1) x GROUP BY 1),
c_done_future AS (
  SELECT group_id gid, count(*) n FROM planned_lessons
  WHERE status = 'done' AND scheduled_date > CURRENT_DATE GROUP BY 1),
c_date AS (
  SELECT p.group_id gid, count(*) n FROM planned_lessons p
  JOIN lessons l ON l.id = p.fact_lesson_id
  WHERE p.scheduled_date <> l.lesson_date GROUP BY 1),
c_number AS (
  SELECT p.group_id gid, count(*) n FROM planned_lessons p
  JOIN lessons l ON l.id = p.fact_lesson_id
  WHERE p.lesson_number <> l.lesson_number GROUP BY 1),
c_orphan AS (
  SELECT l.group_id gid, count(*) n FROM lessons l
  WHERE l.lesson_type IN %(types)s
    AND NOT EXISTS (SELECT 1 FROM planned_lessons p WHERE p.fact_lesson_id = l.id)
  GROUP BY 1),
c_beyond AS (
  SELECT p.group_id gid, count(*) n FROM planned_lessons p
  JOIN course_len cl ON cl.gid = p.group_id
  WHERE p.seq IS NOT NULL AND cl.total IS NOT NULL AND p.lesson_number > cl.total
  GROUP BY 1),
c_dupdate AS (
  SELECT group_id gid, count(*) n FROM (
    SELECT group_id, lesson_date FROM lessons
    WHERE lesson_type IN %(types)s
    GROUP BY 1,2 HAVING count(*) > 1) y GROUP BY 1)
SELECT cl.gid, cl.name,
       COALESCE(c_orphan.n, 0), COALESCE(c_beyond.n, 0),
       COALESCE(c_number.n, 0), COALESCE(c_date.n, 0),
       COALESCE(c_done_future.n, 0), COALESCE(c_collision.n, 0),
       COALESCE(c_dupdate.n, 0)
FROM course_len cl
LEFT JOIN c_collision   ON c_collision.gid = cl.gid
LEFT JOIN c_done_future ON c_done_future.gid = cl.gid
LEFT JOIN c_date        ON c_date.gid = cl.gid
LEFT JOIN c_number      ON c_number.gid = cl.gid
LEFT JOIN c_orphan      ON c_orphan.gid = cl.gid
LEFT JOIN c_beyond      ON c_beyond.gid = cl.gid
LEFT JOIN c_dupdate     ON c_dupdate.gid = cl.gid
"""


def check_all() -> dict:
    """
    Сводка по всем активным группам.

    {'entity': 'plan-health', 'checked': <групп проверено>,
     'groups': [{'group_id', 'name', 'counts': {<ключ>: <нарушений>}}, ...]}

    В groups попадают только группы, где хотя бы одна проверка ненулевая;
    порядок — по суммарному числу нарушений убыв., затем по имени.
    """
    with connection.cursor() as cur:
        cur.execute(_SUMMARY_SQL, {'types': tuple(COURSE_LESSON_TYPES)})
        rows = cur.fetchall()

    groups = []
    for gid, name, *values in rows:
        counts = {key: n for key, n in zip(CHECKS, values) if n}
        if counts:
            groups.append({'group_id': gid, 'name': name, 'counts': counts})

    groups.sort(key=lambda r: (-sum(r['counts'].values()), r['name']))
    return {'entity': 'plan-health', 'checked': len(rows), 'groups': groups}
```

- [ ] **Step 4: Запустить**

Run: `pytest apps/scheduling/tests/test_plan_health.py -v`
Expected: 2 passed

- [ ] **Step 5: Дописать тесты на остальные пять проверок**

```python
def test_detects_done_in_future(group_with_group):
    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2099-01-01', 1)
    PlannedLesson.objects.filter(group_id=gid, seq=1).update(
        status='done', fact_lesson_id=lesson_id, scheduled_date='2099-01-01')
    assert _counts_for(gid).get('done_in_future') == 1


def test_detects_date_mismatch(group_with_group):
    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-06-30', 1)
    PlannedLesson.objects.filter(group_id=gid, seq=1).update(
        status='done', fact_lesson_id=lesson_id)   # позиция осталась на 07.07
    assert _counts_for(gid).get('date_mismatch') == 1


def test_detects_number_mismatch(group_with_group):
    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-07-07', 3)
    PlannedLesson.objects.filter(group_id=gid, seq=1).update(
        status='done', fact_lesson_id=lesson_id)   # у позиции номер 1, у урока 3
    assert _counts_for(gid).get('number_mismatch') == 1


def test_detects_fact_without_position(group_with_group):
    gid, tid = group_with_group
    _lesson(gid, tid, '2026-07-07', 1)             # ни к одной позиции не привязан
    assert _counts_for(gid).get('fact_without_position') == 1


def test_detects_beyond_course(group_with_group):
    """Длина курса фикстуры — 4 урока; позиция с номером 9 сверх него."""
    gid, tid = group_with_group
    now = datetime.datetime(2026, 7, 1, 12, 0)
    PlannedLesson.objects.create(
        group_id=gid, seq=9, lesson_number=9, scheduled_date='2026-09-01',
        scheduled_time=datetime.time(18, 0), teacher_id=tid, status='pending',
        created_at=now, updated_at=now)
    assert _counts_for(gid).get('beyond_course') == 1


def test_detects_duplicate_dates(group_with_group):
    gid, tid = group_with_group
    _lesson(gid, tid, '2026-07-07', 1)
    _lesson(gid, tid, '2026-07-07', 2)
    assert _counts_for(gid).get('duplicate_dates') == 1


def test_check_all_does_not_loop_over_groups(group_with_group, django_assert_num_queries):
    """Один запрос на всю сводку — цикл по группам недопустим (134 группы на проде)."""
    with django_assert_num_queries(1):
        health.check_all()
```

- [ ] **Step 6: Запустить файл**

Run: `pytest apps/scheduling/tests/test_plan_health.py -v`
Expected: 9 passed

- [ ] **Step 7: Коммит**

```bash
git add journal_django/apps/scheduling/health.py journal_django/apps/scheduling/tests/test_plan_health.py
git commit -m "feat(scheduling): проверки здоровья планов — сводка по всем группам"
```

---

## Task 7: Проверки по одной группе с деталями строк

**Files:**
- Modify: `journal_django/apps/scheduling/health.py`
- Test: `journal_django/apps/scheduling/tests/test_plan_health.py`

- [ ] **Step 1: Написать падающий тест**

```python
def test_check_group_returns_rows(group_with_group):
    """По одной группе отдаём конкретные строки, а не счётчики."""
    gid, tid = group_with_group
    lesson_id = _lesson(gid, tid, '2026-06-30', 1)
    PlannedLesson.objects.filter(group_id=gid, seq=1).update(
        status='done', fact_lesson_id=lesson_id)

    report = health.check_group(gid)

    assert report['group_id'] == gid
    rows = report['findings']['date_mismatch']
    assert len(rows) == 1
    assert rows[0]['seq'] == 1
    assert rows[0]['scheduled_date'] == datetime.date(2026, 7, 7)
    assert rows[0]['fact_date'] == datetime.date(2026, 6, 30)


def test_check_group_missing_group(group_with_group):
    assert health.check_group(999_999_999) is None
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `pytest apps/scheduling/tests/test_plan_health.py::test_check_group_returns_rows -v`
Expected: FAIL — `AttributeError: module 'apps.scheduling.health' has no attribute 'check_group'`

- [ ] **Step 3: Реализовать**

Дописать в `journal_django/apps/scheduling/health.py`:

```python
_GROUP_SQL = {
    'collision': """
        SELECT p.id, p.seq, p.lesson_number, p.scheduled_date, NULL::date
        FROM planned_lessons p
        JOIN (SELECT scheduled_date, scheduled_time FROM planned_lessons
              WHERE group_id = %(gid)s AND seq IS NOT NULL AND status <> 'cancelled'
              GROUP BY 1,2 HAVING count(*) > 1) dup
          ON dup.scheduled_date = p.scheduled_date AND dup.scheduled_time = p.scheduled_time
        WHERE p.group_id = %(gid)s AND p.seq IS NOT NULL AND p.status <> 'cancelled'
        ORDER BY p.scheduled_date, p.seq""",
    'done_in_future': """
        SELECT p.id, p.seq, p.lesson_number, p.scheduled_date, l.lesson_date
        FROM planned_lessons p LEFT JOIN lessons l ON l.id = p.fact_lesson_id
        WHERE p.group_id = %(gid)s AND p.status = 'done'
          AND p.scheduled_date > CURRENT_DATE ORDER BY p.seq""",
    'date_mismatch': """
        SELECT p.id, p.seq, p.lesson_number, p.scheduled_date, l.lesson_date
        FROM planned_lessons p JOIN lessons l ON l.id = p.fact_lesson_id
        WHERE p.group_id = %(gid)s AND p.scheduled_date <> l.lesson_date
        ORDER BY p.seq""",
    'number_mismatch': """
        SELECT p.id, p.seq, p.lesson_number, p.scheduled_date, l.lesson_date
        FROM planned_lessons p JOIN lessons l ON l.id = p.fact_lesson_id
        WHERE p.group_id = %(gid)s AND p.lesson_number <> l.lesson_number
        ORDER BY p.seq""",
    'fact_without_position': """
        SELECT l.id, NULL::int, l.lesson_number, NULL::date, l.lesson_date
        FROM lessons l
        WHERE l.group_id = %(gid)s AND l.lesson_type IN %(types)s
          AND NOT EXISTS (SELECT 1 FROM planned_lessons p WHERE p.fact_lesson_id = l.id)
        ORDER BY l.lesson_number""",
    'beyond_course': """
        SELECT p.id, p.seq, p.lesson_number, p.scheduled_date, NULL::date
        FROM planned_lessons p
        JOIN groups g ON g.id = p.group_id
        LEFT JOIN directions d ON d.id = g.direction_id
        WHERE p.group_id = %(gid)s AND p.seq IS NOT NULL
          AND COALESCE(g.lessons_total, d.total_lessons) IS NOT NULL
          AND p.lesson_number > COALESCE(g.lessons_total, d.total_lessons)
        ORDER BY p.lesson_number""",
    'duplicate_dates': """
        SELECT l.id, NULL::int, l.lesson_number, NULL::date, l.lesson_date
        FROM lessons l
        JOIN (SELECT lesson_date FROM lessons
              WHERE group_id = %(gid)s AND lesson_type IN %(types)s
              GROUP BY 1 HAVING count(*) > 1) dup ON dup.lesson_date = l.lesson_date
        WHERE l.group_id = %(gid)s AND l.lesson_type IN %(types)s
        ORDER BY l.lesson_date, l.id""",
}


def check_group(group_id: int) -> dict | None:
    """
    Те же проверки по одной группе, но с конкретными строками для интерфейса.

    {'group_id', 'name', 'findings': {<ключ проверки>: [{'id', 'seq',
     'lesson_number', 'scheduled_date', 'fact_date'}, ...]}}

    ВНИМАНИЕ по полю id: у проверок, работающих от плана, это id плановой строки;
    у fact_without_position и duplicate_dates — id ЗАНЯТИЯ (позиции у них нет,
    поэтому seq и scheduled_date приходят пустыми). Интерфейс обязан различать
    эти два случая по ключу проверки, а не гадать по содержимому.

    В findings попадают только сработавшие проверки. Группы нет → None.
    Группа маленькая (десятки строк), поэтому здесь запрос на проверку — это
    дешевле и читаемее одного гигантского UNION.
    """
    with connection.cursor() as cur:
        cur.execute('SELECT name FROM groups WHERE id = %s', [group_id])
        row = cur.fetchone()
        if row is None:
            return None
        name = row[0]

        params = {'gid': group_id, 'types': tuple(COURSE_LESSON_TYPES)}
        findings = {}
        for key in CHECKS:
            cur.execute(_GROUP_SQL[key], params)
            rows = [
                {'id': r[0], 'seq': r[1], 'lesson_number': r[2],
                 'scheduled_date': r[3], 'fact_date': r[4]}
                for r in cur.fetchall()
            ]
            if rows:
                findings[key] = rows

    return {'group_id': group_id, 'name': name, 'findings': findings}
```

- [ ] **Step 4: Запустить**

Run: `pytest apps/scheduling/tests/test_plan_health.py -v`
Expected: 11 passed

- [ ] **Step 5: Коммит**

```bash
git add journal_django/apps/scheduling/health.py journal_django/apps/scheduling/tests/test_plan_health.py
git commit -m "feat(scheduling): проверки здоровья по одной группе с деталями строк"
```

---

## Task 8: Действие «Проверка планов групп» в «Синхро»

**Files:**
- Create: `journal_django/apps/sync/backfills/check_plan_health.py`
- Modify: `journal_django/apps/sync/tasks.py`, `journal_django/apps/sync/views.py:16-30`
- Test: `journal_django/apps/sync/tests/test_check_plan_health.py`

- [ ] **Step 1: Написать падающий тест**

Создать `journal_django/apps/sync/tests/test_check_plan_health.py`:

```python
# journal_django/apps/sync/tests/test_check_plan_health.py
"""Проверка планов в «Синхро»: обёртка + RBAC. Read-only действие."""
import pytest

from apps.sync.backfills import check_plan_health

pytestmark = pytest.mark.django_db


def test_run_returns_plan_health_report():
    result = check_plan_health.run()
    assert result['entity'] == 'plan-health'
    assert 'checked' in result
    assert isinstance(result['groups'], list)


def test_run_accepts_dry_run_flag():
    """dry_run для read-only действия бессмыслен, но сигнатура общая с
    остальными backfill-модулями (apps/sync/views.py передаёт его всегда)."""
    assert check_plan_health.run(dry_run=True)['entity'] == 'plan-health'


def test_endpoint_requires_superadmin(admin_client):
    resp = admin_client.post('/api/admin/sync/check-plan-health/run', {}, format='json')
    assert resp.status_code == 403


def test_endpoint_runs_for_superadmin(superadmin_client):
    resp = superadmin_client.post('/api/admin/sync/check-plan-health/run', {}, format='json')
    assert resp.status_code == 202
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `pytest apps/sync/tests/test_check_plan_health.py -v`
Expected: FAIL — `ImportError: cannot import name 'check_plan_health'`

- [ ] **Step 3: Создать обёртку**

Создать `journal_django/apps/sync/backfills/check_plan_health.py`:

```python
# journal_django/apps/sync/backfills/check_plan_health.py
"""Проверка здоровья планов занятий по всем активным группам.

ТОЛЬКО ЧТЕНИЕ — в отличие от остальных модулей apps/sync/backfills, ничего не
пишет. Логика проверок живёт в apps.scheduling.health (доменное знание о плане),
здесь только обёртка под общий контракт run(dry_run) → dict, которого ждёт
apps/sync/views.py. Параметр dry_run принимается и игнорируется: менять нечего.

Спека: docs/superpowers/specs/2026-08-05-plan-health-design.md §4.
"""
from __future__ import annotations

from apps.scheduling import health


def run(dry_run: bool = False) -> dict:
    return health.check_all()
```

- [ ] **Step 4: Добавить Celery-задачу**

В `journal_django/apps/sync/tasks.py` дописать `check_plan_health` в импорт из `apps.sync.backfills` (список в алфавитном порядке) и добавить задачу:

```python
@shared_task(name='apps.sync.tasks.check_plan_health_task', time_limit=120)
def check_plan_health_task(dry_run: bool = False) -> dict:
    return check_plan_health.run(dry_run=dry_run)
```

- [ ] **Step 5: Зарегистрировать действие**

В `journal_django/apps/sync/views.py` в словарь `ACTIONS` добавить строку последней:

```python
    'check-plan-health': tasks.check_plan_health_task,
```

- [ ] **Step 6: Запустить**

Run: `pytest apps/sync/tests/test_check_plan_health.py -v`
Expected: 4 passed

- [ ] **Step 7: Коммит**

```bash
git add journal_django/apps/sync/backfills/check_plan_health.py journal_django/apps/sync/tasks.py journal_django/apps/sync/views.py journal_django/apps/sync/tests/test_check_plan_health.py
git commit -m "feat(sync): действие «Проверка планов групп» — read-only диагностика"
```

---

## Task 9: Карточка «Проверки» на странице «Синхро»

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/sync.ts`
- Modify: `journal_django/frontend/admin-src/src/pages/sync/SyncActionCard.tsx:7-28`
- Modify: `journal_django/frontend/admin-src/src/pages/sync/SyncPage.tsx`

Тестов на фронте в проекте нет — проверка через `tsc` и сборку.

- [ ] **Step 1: Расширить описание действий**

В `journal_django/frontend/admin-src/src/lib/sync.ts`:

```ts
export type SyncAction =
  | 'teachers' | 'groups' | 'students' | 'lessons' | 'payments' | 'payroll'
  | 'rebuild-payroll' | 'rebuild-counters' | 'rebuild-planned-lessons'
  | 'rebuild-absence-resolutions' | 'rebuild-renewals' | 'rebuild-renewal-dates'
  | 'check-plan-health'
  | 'run-all';

export interface SyncActionDef {
  action: SyncAction;
  label: string;
  group: 'run-all' | 'sheets' | 'rebuild' | 'checks';
  /** Действие только читает: чекбокс «только предпросмотр» не показываем. */
  readOnly?: boolean;
}
```

и добавить в конец массива `SYNC_ACTIONS`:

```ts
  {
    action: 'check-plan-health',
    label: 'Планы групп — проверка (ничего не меняет: покажет, где план разъехался с занятиями)',
    group: 'checks',
    readOnly: true,
  },
```

- [ ] **Step 2: Научить карточку режиму «только чтение»**

В `journal_django/frontend/admin-src/src/pages/sync/SyncActionCard.tsx` заменить блок строки действия:

```tsx
      <div className="sync-card__row">
        <span className="sync-card__label">{def.label}</span>
        {!def.readOnly && (
          <Checkbox
            label="только предпросмотр"
            checked={dryRun}
            onChange={(e) => setDryRun(e.target.checked)}
            disabled={busy}
          />
        )}
        <button type="button" className="btn-add" disabled={busy} onClick={() => run(def.readOnly ? false : dryRun)}>
          Запустить
        </button>
      </div>
```

- [ ] **Step 3: Добавить секцию на страницу**

В `journal_django/frontend/admin-src/src/pages/sync/SyncPage.tsx`:

```tsx
export default function SyncPage() {
  const runAll = SYNC_ACTIONS.filter((a) => a.group === 'run-all');
  const sheets = SYNC_ACTIONS.filter((a) => a.group === 'sheets');
  const rebuild = SYNC_ACTIONS.filter((a) => a.group === 'rebuild');
  const checks = SYNC_ACTIONS.filter((a) => a.group === 'checks');

  return (
    <section className="page sync-page">
      <PageHeader title="Синхро" />

      {runAll.map((def) => <SyncActionCard key={def.action} def={def} />)}

      <div className="sync-page__group-title">Проверки (только чтение)</div>
      {checks.map((def) => <SyncActionCard key={def.action} def={def} />)}

      <div className="sync-page__group-title">Из Google Sheets</div>
      {sheets.map((def) => <SyncActionCard key={def.action} def={def} />)}

      <div className="sync-page__group-title">Пересчёт из БД (Sheets не трогают)</div>
      {rebuild.map((def) => <SyncActionCard key={def.action} def={def} />)}
    </section>
  );
}
```

- [ ] **Step 4: Проверить типы и собрать**

```bash
cd journal_django/frontend/admin-src
npx tsc --noEmit
npm run build
```
Expected: обе команды без ошибок.

- [ ] **Step 5: Коммит**

```bash
git add journal_django/frontend/admin-src/src journal_django/frontend/admin-dist
git commit -m "feat(admin): раздел «Проверки» в «Синхро» — проверка планов групп"
```

⚠️ Перед коммитом проверить `git status`: пересборка меняет много файлов в `admin-dist`, посторонних правок в индексе быть не должно.

---

## Task 10: Финальная проверка

- [ ] **Step 1: Полный прогон тестов**

Run (из `journal_django/`): `pytest -q`
Expected: без падений. Гонять именно полный набор — прогон по приложениям даёт ложный результат.

- [ ] **Step 2: Живая проверка проверок на дев-базе**

```bash
cd journal_django
python manage.py shell -c "from apps.scheduling import health; import json; r = health.check_all(); print(json.dumps({'checked': r['checked'], 'groups': r['groups'][:5]}, ensure_ascii=False, indent=2, default=str))"
```
Expected: печатается число проверенных групп и до пяти проблемных с ключами проверок.

- [ ] **Step 3: Проверить в браузере**

Открыть `/admin/sync` под суперадмином, нажать «Запустить» в секции «Проверки». Ожидается: чекбокса «только предпросмотр» у этой карточки нет, результат приходит JSON'ом со списком групп.

- [ ] **Step 4: Обновить документацию**

В `docs/lesson-scheduling.md` добавить абзац: плановая дата проведённой позиции равна дате занятия (инвариант, поддерживается `sync_position_date`), и в разделе «Синхро» есть read-only проверка планов. Сослаться на спеку.

- [ ] **Step 5: Коммит**

```bash
git add docs/lesson-scheduling.md
git commit -m "docs: инвариант плановой даты и проверка планов групп"
```

---

## Что НЕ входит в этот план

Из спеки, раздел 5 — решения приняты, реализация отложена:

- **Слой 2** — кнопка починки `POST /api/admin/groups/<pk>/plan/resync` на вкладке «Расписание» + правило `plan.resync` в `apps/changelog/labels.py`.
- **Слой 3** — сокрытие кнопки при `fact_without_position` / `duplicate_dates`.
- **Операция «закрыть пропуск в нумерации»** (случай МГ59).
- **Ретроспективная починка существующих расхождений.** На момент написания это 80 позиций в 10 группах; лечится вручную через `manage.py resync_plan_facts --group N --apply`. Слой 0 их не двигает — он держит инвариант только для новых правок и записей.
