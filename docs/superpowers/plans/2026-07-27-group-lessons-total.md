# Ручная длина курса группы (`groups.lessons_total`) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** дать менеджеру задать в форме группы, сколько уроков эта группа должна отходить, вместо жёсткой привязки к `direction.total_lessons`.

**Architecture:** новое необязательное поле `groups.lessons_total`. Единственная функция «эффективная длина курса» (`COALESCE(group.lessons_total, direction.total_lessons)`) подставляется в четыре места, где длина курса нужна для **плана и сетки**. Лимит продаж и прогресс ученика по направлению не трогаются. Правка числа подгоняет план в той же транзакции: хвост дописывается или удаляется, проведённое защищено.

**Tech Stack:** Django 5 + DRF, PostgreSQL, pytest, React 19 + TanStack Query (admin SPA).

**Спека:** `docs/superpowers/specs/2026-07-27-group-lessons-total-design.md`

---

## Правила этого репозитория (обязательно к соблюдению)

- **Коммитить и пушить ТОЛЬКО по явной просьбе пользователя** (CLAUDE.md). Шаги «Commit» в этом плане означают: показать `git status` + `git diff --stat`, дождаться решения. Субагентам git запрещён.
- Рабочий каталог всех команд — `journal_django/`. Интерпретатор — `.venv/Scripts/python.exe`.
- Тест-БД `journal_test` **общая** для всех worktree; `scripts/recreate_test_db.ps1` рушит seed-данные — не запускать.
- Native form-элементы в admin SPA запрещены: только компоненты из `components/form/`.
- Единица измерения длины курса везде — **уроки**, не занятия. У 45-минутной группы шаг 0.5, поэтому 2 урока = 4 занятия.
- `npm run build` не запускать — dist коммитит пользователь отдельно.

## Файловая структура

| Файл | Ответственность |
|---|---|
| `apps/groups/models.py` | поле `lessons_total` + CHECK |
| `apps/groups/migrations/0006_*.py` | миграция (создаётся `makemigrations`) |
| `apps/groups/course_length.py` (новый) | единственный источник «эффективной длины курса» |
| `apps/groups/repository.py` | `_GROUP_FIELDS`, `create_group`, `update_group`, `get_group_progress` |
| `apps/groups/services.py` | оркестрация: правка числа → подгонка плана |
| `apps/groups/serializers.py` | приём/выдача поля |
| `apps/groups/views.py` | 409 при попытке урезать проведённое |
| `apps/scheduling/exceptions.py` (новый) | `PlanHasRecordedLessons` |
| `apps/scheduling/repository.py` | эффективная длина в генерации/пересборке/списке групп + `resize_plan` |
| `apps/scheduling/services.py` | тонкая обёртка `resize_plan` |
| `apps/changelog/summary.py` | подпись поля в журнале изменений |
| `frontend/admin-src/src/lib/shared-types.ts` | тип `Group.lessons_total` |
| `frontend/admin-src/src/hooks/useGroups.ts` | `GroupPayload.lessons_total` |
| `frontend/admin-src/src/pages/groups/GroupFormModal.tsx` | поле ввода |
| `frontend/admin-src/src/pages/groups/GroupDetailPage.tsx` | отображение |
| `apps/groups/tests/test_group_lessons_total.py` (новый) | тесты модели, API, подгонки плана |
| `apps/scheduling/tests/test_plan_lessons_total.py` (новый) | тесты генерации и `resize_plan` |

---

## Task 1: Поле `lessons_total` в модели и миграция

**Files:**
- Modify: `journal_django/apps/groups/models.py:56` (после `vk_chat`)
- Create: `journal_django/apps/groups/migrations/0006_group_lessons_total.py` (генерируется)
- Test: `journal_django/apps/groups/tests/test_group_lessons_total.py`

- [ ] **Step 1: Написать падающий тест**

Создать `apps/groups/tests/test_group_lessons_total.py`:

```python
"""
Тесты ручной длины курса группы (groups.lessons_total).

См. docs/superpowers/specs/2026-07-27-group-lessons-total-design.md.
Схема journal_test общая — данные создаём и удаляем сами (managed-таблицы,
django_db_setup в conftest — no-op).
"""
from __future__ import annotations

import pytest
from django.db import connection, IntegrityError, transaction


@pytest.fixture
def dir_and_teacher(db):
    """Направление (курс 8 уроков) + преподаватель. Возвращает (direction_id, teacher_id)."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO directions (name, total_lessons, color, active) "
            "VALUES ('__lt_dir__', 8, '#4F59F9', true) RETURNING id"
        )
        direction_id = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name, active) VALUES ('__lt_tch__', true) RETURNING id")
        teacher_id = cur.fetchone()[0]
    yield direction_id, teacher_id
    with connection.cursor() as cur:
        cur.execute("DELETE FROM groups WHERE direction_id = %s", [direction_id])
        cur.execute("DELETE FROM directions WHERE id = %s", [direction_id])
        cur.execute("DELETE FROM teachers WHERE id = %s", [teacher_id])


@pytest.mark.django_db
def test_lessons_total_defaults_to_null(dir_and_teacher):
    """Новая группа без явного числа наследует длину курса от направления."""
    from apps.groups.models import Group
    direction_id, teacher_id = dir_and_teacher
    g = Group.objects.create(
        name='__lt_default__', direction_id=direction_id, teacher_id=teacher_id,
        is_individual=True, lesson_duration_minutes=90, lessons_per_week=1,
        created_at='2026-07-27T00:00:00+03:00',
    )
    assert g.lessons_total is None


@pytest.mark.django_db
def test_lessons_total_stores_value(dir_and_teacher):
    """Заданное число сохраняется как есть."""
    from apps.groups.models import Group
    direction_id, teacher_id = dir_and_teacher
    g = Group.objects.create(
        name='__lt_value__', direction_id=direction_id, teacher_id=teacher_id,
        is_individual=True, lesson_duration_minutes=90, lessons_per_week=1,
        lessons_total=2, created_at='2026-07-27T00:00:00+03:00',
    )
    g.refresh_from_db()
    assert g.lessons_total == 2


@pytest.mark.django_db
def test_lessons_total_rejects_zero(dir_and_teacher):
    """Ноль уроков бессмыслен — запрещён CHECK-констрейнтом в БД."""
    from apps.groups.models import Group
    direction_id, teacher_id = dir_and_teacher
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Group.objects.create(
                name='__lt_zero__', direction_id=direction_id, teacher_id=teacher_id,
                is_individual=True, lesson_duration_minutes=90, lessons_per_week=1,
                lessons_total=0, created_at='2026-07-27T00:00:00+03:00',
            )
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv/Scripts/python.exe -m pytest apps/groups/tests/test_group_lessons_total.py -q`
Expected: FAIL — `TypeError: Group() got unexpected keyword arguments: 'lessons_total'`

- [ ] **Step 3: Добавить поле в модель**

В `apps/groups/models.py` после строки `vk_chat = models.TextField(null=True, blank=True)` вставить:

```python
    # Длина курса ИМЕННО ЭТОЙ группы в уроках. NULL — «как в направлении»
    # (directions.total_lessons), это дефолт и поведение всех старых групп.
    # Задаётся вручную в форме группы, когда группа должна отходить только часть
    # курса (ученик начал не с первого урока — прошёл остальное в другой группе).
    # Единица — УРОКИ, не занятия: у 45-мин группы шаг 0.5, поэтому 2 урока = 4
    # занятия. Читать только через apps.groups.course_length — длина группы НЕ
    # применяется к лимиту продаж (apps.payments) и к прогрессу ученика по
    # направлению (apps.students). См.
    # docs/superpowers/specs/2026-07-27-group-lessons-total-design.md.
    lessons_total = models.IntegerField(null=True, blank=True)
```

В `class Meta.constraints` того же класса добавить:

```python
            models.CheckConstraint(
                name='groups_lessons_total_check',
                condition=models.Q(lessons_total__isnull=True) | models.Q(lessons_total__gt=0),
            ),
```

- [ ] **Step 4: Сгенерировать миграцию**

Run: `.venv/Scripts/python.exe manage.py makemigrations groups`
Expected: создан `apps/groups/migrations/0006_group_lessons_total.py`; внутри — `AddField` для `group` И для `groupevent` (pghistory-модель), `AddConstraint`, плюс пересозданные триггеры pghistory.

Проверить глазами, что `AddField` для `groupevent` присутствует: `grep -c "groupevent" apps/groups/migrations/0006_*.py` — должно быть ≥ 1. Если триггеры не перегенерировались, выполнить `.venv/Scripts/python.exe manage.py makemigrations` ещё раз и добавить полученный файл.

- [ ] **Step 5: Применить миграцию к обеим базам**

Run: `.venv/Scripts/python.exe manage.py migrate groups`
Expected: `Applying groups.0006_... OK` (dev-БД `journal`)

Run: `.venv/Scripts/python.exe manage.py migrate groups --settings=config.settings.test`
Expected: `Applying groups.0006_... OK` (тест-БД `journal_test` — она общая и живёт отдельно от dev)

- [ ] **Step 6: Прогнать тест**

Run: `.venv/Scripts/python.exe -m pytest apps/groups/tests/test_group_lessons_total.py -q`
Expected: 3 passed

- [ ] **Step 7: Показать изменения пользователю**

Run: `git status --short && git diff --stat`
Коммит — только если пользователь попросит.

---

## Task 2: Эффективная длина курса в планировании

**Files:**
- Create: `journal_django/apps/groups/course_length.py`
- Modify: `journal_django/apps/scheduling/repository.py:43`, `:1143`, `:1287`
- Test: `journal_django/apps/scheduling/tests/test_plan_lessons_total.py`

- [ ] **Step 1: Написать падающий тест**

Создать `apps/scheduling/tests/test_plan_lessons_total.py`:

```python
"""
План группы с ручной длиной курса (groups.lessons_total).

Направление курса — 8 уроков; группа с lessons_total=2 должна планировать
2 занятия, а не 8. Половинный формат (45 мин) — 2 урока = 4 занятия.
"""
from __future__ import annotations

import datetime

import pytest
from django.db import connection

from apps.scheduling.models import PlannedLesson


def _make_group(cur, direction_id, teacher_id, *, name, duration, lessons_total):
    cur.execute(
        "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
        "lesson_duration_minutes, lessons_per_week, group_start_date, active, "
        "lesson_number_offset, lessons_total) "
        "VALUES (%s, %s, %s, true, %s, 1, DATE '2026-08-03', true, 0, %s) RETURNING id",
        [name, direction_id, teacher_id, duration, lessons_total],
    )
    group_id = cur.fetchone()[0]
    # Пн 10:00 (конвенция Вс=0 → понедельник = 1)
    cur.execute(
        "INSERT INTO group_schedule_slots (group_id, day_of_week, start_time, effective_from) "
        "VALUES (%s, 1, TIME '10:00', DATE '2000-01-01')",
        [group_id],
    )
    return group_id


@pytest.fixture
def plan_setup(db):
    """Направление (8 уроков) + преподаватель. Чистит за собой всё созданное."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO directions (name, total_lessons, color, active) "
            "VALUES ('__plt_dir__', 8, '#4F59F9', true) RETURNING id"
        )
        direction_id = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name, active) VALUES ('__plt_tch__', true) RETURNING id")
        teacher_id = cur.fetchone()[0]
    yield direction_id, teacher_id
    with connection.cursor() as cur:
        cur.execute(
            "DELETE FROM planned_lessons WHERE group_id IN "
            "(SELECT id FROM groups WHERE direction_id = %s)", [direction_id])
        cur.execute(
            "DELETE FROM group_schedule_slots WHERE group_id IN "
            "(SELECT id FROM groups WHERE direction_id = %s)", [direction_id])
        cur.execute("DELETE FROM groups WHERE direction_id = %s", [direction_id])
        cur.execute("DELETE FROM directions WHERE id = %s", [direction_id])
        cur.execute("DELETE FROM teachers WHERE id = %s", [teacher_id])


@pytest.mark.django_db
def test_generate_uses_group_lessons_total(plan_setup):
    """lessons_total=2 при курсе направления 8 → в плане 2 занятия."""
    from apps.scheduling.repository import generate_for_group
    direction_id, teacher_id = plan_setup
    with connection.cursor() as cur:
        group_id = _make_group(cur, direction_id, teacher_id,
                               name='__plt_short__', duration=90, lessons_total=2)

    generate_for_group(group_id)

    rows = list(PlannedLesson.objects.filter(group_id=group_id, seq__isnull=False)
                .order_by('seq').values_list('seq', 'lesson_number', 'scheduled_date'))
    assert [r[0] for r in rows] == [1, 2]
    assert [float(r[1]) for r in rows] == [1.0, 2.0]
    assert rows[0][2] == datetime.date(2026, 8, 3)


@pytest.mark.django_db
def test_generate_half_lesson_group(plan_setup):
    """45 мин: 2 урока = 4 занятия с номерами 0.5 … 2.0."""
    from apps.scheduling.repository import generate_for_group
    direction_id, teacher_id = plan_setup
    with connection.cursor() as cur:
        group_id = _make_group(cur, direction_id, teacher_id,
                               name='__plt_half__', duration=45, lessons_total=2)

    generate_for_group(group_id)

    numbers = [float(n) for n in PlannedLesson.objects
               .filter(group_id=group_id, seq__isnull=False)
               .order_by('seq').values_list('lesson_number', flat=True)]
    assert numbers == [0.5, 1.0, 1.5, 2.0]


@pytest.mark.django_db
def test_generate_falls_back_to_direction(plan_setup):
    """Пустое поле — длина курса берётся из направления (регресс)."""
    from apps.scheduling.repository import generate_for_group
    direction_id, teacher_id = plan_setup
    with connection.cursor() as cur:
        group_id = _make_group(cur, direction_id, teacher_id,
                               name='__plt_full__', duration=90, lessons_total=None)

    generate_for_group(group_id)

    assert PlannedLesson.objects.filter(group_id=group_id, seq__isnull=False).count() == 8
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv/Scripts/python.exe -m pytest apps/scheduling/tests/test_plan_lessons_total.py -q`
Expected: FAIL — первые два теста дают 8 занятий вместо 2 и 4 (длина берётся из направления)

- [ ] **Step 3: Создать модуль эффективной длины**

Создать `apps/groups/course_length.py`:

```python
"""
Эффективная длина курса группы — единственный источник числа уроков для ПЛАНА
и СЕТКИ.

`groups.lessons_total` (ручное число в форме группы) перекрывает
`directions.total_lessons`. Пусто → длина курса направления, как было раньше.

НЕ применять к лимиту продаж (apps.payments.repository.create_payment) и к
прогрессу ученика по направлению (apps.students.repository.student_stats,
apps.dashboard.registry_service): там курс измеряется программой направления,
иначе ученику короткой группы нельзя будет продать больше уроков, чем она
длится. См. docs/superpowers/specs/2026-07-27-group-lessons-total-design.md,
раздел 4.

Единица измерения — УРОКИ курса, не календарные занятия: у 45-минутной группы
шаг 0.5 (apps.scheduling.occurrences._step_for), поэтому 2 урока = 4 занятия.
"""
from __future__ import annotations

from django.db.models import F
from django.db.models.functions import Coalesce


def effective_total_lessons_expr():
    """ORM-выражение для `.values()`/`.annotate()` на queryset модели Group."""
    return Coalesce(F('lessons_total'), F('direction__total_lessons'))
```

- [ ] **Step 4: Подставить выражение в scheduling**

В `apps/scheduling/repository.py` добавить импорт рядом с остальными импортами приложений:

```python
from apps.groups.course_length import effective_total_lessons_expr
```

Заменить четыре вхождения `total_lessons=F('direction__total_lessons')` на `total_lessons=effective_total_lessons_expr()`:
- в `active_groups` (около строки 43),
- в `permanent_change` (около строки 837) — «изменить расписание» разворачивает хвост курса тем же `planner.generate`; без правки группа-остаток при смене расписания получила бы хвост на весь курс направления,
- в `generate_for_group` (около строки 1143),
- в `rebuild_from_facts` (около строки 1287).

Проверить, что не осталось других: `grep -n "direction__total_lessons" apps/scheduling/repository.py` — вывод должен быть пустым.

- [ ] **Step 5: Прогнать тесты**

Run: `.venv/Scripts/python.exe -m pytest apps/scheduling/tests/test_plan_lessons_total.py -q`
Expected: 3 passed

Run: `.venv/Scripts/python.exe -m pytest apps/scheduling -q`
Expected: все тесты scheduling проходят (регресс планировщика)

- [ ] **Step 6: Показать изменения пользователю**

Run: `git status --short && git diff --stat`

---

## Task 3: Эффективная длина в сетке прогресса

**Files:**
- Modify: `journal_django/apps/groups/repository.py:450`
- Test: `journal_django/apps/groups/tests/test_group_lessons_total.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `apps/groups/tests/test_group_lessons_total.py`:

```python
@pytest.mark.django_db
def test_progress_grid_uses_group_lessons_total(dir_and_teacher):
    """Сетка «Прогресс» рисует клетки по длине группы, а не направления."""
    from apps.groups.repository import get_group_progress
    from apps.groups.models import Group
    direction_id, teacher_id = dir_and_teacher
    g = Group.objects.create(
        name='__lt_grid__', direction_id=direction_id, teacher_id=teacher_id,
        is_individual=True, lesson_duration_minutes=90, lessons_per_week=1,
        lessons_total=2, created_at='2026-07-27T00:00:00+03:00',
    )

    progress = get_group_progress(g.id)

    # Направление — 8 уроков, группа — 2: клеток должно быть 2.
    assert progress['total_slots'] == 2
    assert len(progress['slots']) == 2


@pytest.mark.django_db
def test_progress_grid_half_lesson(dir_and_teacher):
    """45 мин: 2 урока группы = 4 клетки сетки."""
    from apps.groups.repository import get_group_progress
    from apps.groups.models import Group
    direction_id, teacher_id = dir_and_teacher
    g = Group.objects.create(
        name='__lt_grid_half__', direction_id=direction_id, teacher_id=teacher_id,
        is_individual=True, lesson_duration_minutes=45, lessons_per_week=1,
        lessons_total=2, created_at='2026-07-27T00:00:00+03:00',
    )

    progress = get_group_progress(g.id)

    assert progress['total_slots'] == 4
    assert len(progress['slots']) == 4
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv/Scripts/python.exe -m pytest apps/groups/tests/test_group_lessons_total.py -q -k grid`
Expected: FAIL — 8 клеток вместо 2 (и 16 вместо 4)

- [ ] **Step 3: Подставить выражение**

В `apps/groups/repository.py` добавить импорт:

```python
from apps.groups.course_length import effective_total_lessons_expr
```

В `get_group_progress` заменить

```python
        .values('id', 'lesson_duration_minutes', total_lessons=F('direction__total_lessons'))
```

на

```python
        .values('id', 'lesson_duration_minutes',
                total_lessons=effective_total_lessons_expr())
```

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/Scripts/python.exe -m pytest apps/groups -q`
Expected: все тесты groups проходят, включая новые

- [ ] **Step 5: Показать изменения пользователю**

Run: `git status --short && git diff --stat`

---

## Task 4: Подгонка плана при изменении числа (`resize_plan`)

**Files:**
- Create: `journal_django/apps/scheduling/exceptions.py`
- Modify: `journal_django/apps/scheduling/repository.py` (новая функция в конце файла), `journal_django/apps/scheduling/services.py`
- Test: `journal_django/apps/scheduling/tests/test_plan_lessons_total.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `apps/scheduling/tests/test_plan_lessons_total.py`:

```python
@pytest.mark.django_db
def test_resize_plan_shrinks_tail(plan_setup):
    """Уменьшили длину — лишние непроведённые занятия удалены с конца."""
    from apps.scheduling.repository import generate_for_group, resize_plan
    direction_id, teacher_id = plan_setup
    with connection.cursor() as cur:
        group_id = _make_group(cur, direction_id, teacher_id,
                               name='__plt_shrink__', duration=90, lessons_total=None)
    generate_for_group(group_id)
    assert PlannedLesson.objects.filter(group_id=group_id, seq__isnull=False).count() == 8

    with connection.cursor() as cur:
        cur.execute("UPDATE groups SET lessons_total = 3 WHERE id = %s", [group_id])
    resize_plan(group_id)

    seqs = list(PlannedLesson.objects.filter(group_id=group_id, seq__isnull=False)
                .order_by('seq').values_list('seq', flat=True))
    assert seqs == [1, 2, 3]


@pytest.mark.django_db
def test_resize_plan_extends_tail(plan_setup):
    """Увеличили длину — недостающие занятия дописаны после последней даты."""
    from apps.scheduling.repository import generate_for_group, resize_plan
    direction_id, teacher_id = plan_setup
    with connection.cursor() as cur:
        group_id = _make_group(cur, direction_id, teacher_id,
                               name='__plt_extend__', duration=90, lessons_total=2)
    generate_for_group(group_id)
    assert PlannedLesson.objects.filter(group_id=group_id, seq__isnull=False).count() == 2

    with connection.cursor() as cur:
        cur.execute("UPDATE groups SET lessons_total = 4 WHERE id = %s", [group_id])
    resize_plan(group_id)

    rows = list(PlannedLesson.objects.filter(group_id=group_id, seq__isnull=False)
                .order_by('seq').values_list('seq', 'lesson_number', 'scheduled_date'))
    assert [r[0] for r in rows] == [1, 2, 3, 4]
    assert [float(r[1]) for r in rows] == [1.0, 2.0, 3.0, 4.0]
    # Слот — понедельник, старт 03.08 → 3-е и 4-е занятия на следующих понедельниках.
    assert rows[2][2] == datetime.date(2026, 8, 17)
    assert rows[3][2] == datetime.date(2026, 8, 24)


@pytest.mark.django_db
def test_resize_plan_refuses_to_cut_recorded(plan_setup):
    """Нельзя урезать план короче уже проведённых занятий."""
    from apps.scheduling.exceptions import PlanHasRecordedLessons
    from apps.scheduling.repository import generate_for_group, resize_plan
    direction_id, teacher_id = plan_setup
    with connection.cursor() as cur:
        group_id = _make_group(cur, direction_id, teacher_id,
                               name='__plt_recorded__', duration=90, lessons_total=None)
    generate_for_group(group_id)
    # Первые три занятия «проведены».
    PlannedLesson.objects.filter(group_id=group_id, seq__in=[1, 2, 3]).update(status='done')

    with connection.cursor() as cur:
        cur.execute("UPDATE groups SET lessons_total = 2 WHERE id = %s", [group_id])
    with pytest.raises(PlanHasRecordedLessons):
        resize_plan(group_id)

    # План не пострадал.
    assert PlannedLesson.objects.filter(group_id=group_id, seq__isnull=False).count() == 8
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python.exe -m pytest apps/scheduling/tests/test_plan_lessons_total.py -q -k resize`
Expected: FAIL — `ImportError: cannot import name 'resize_plan'`

- [ ] **Step 3: Создать исключение**

Создать `apps/scheduling/exceptions.py`:

```python
"""
Доменные исключения планировщика.

Не зависят от DRF/HTTP — бросаются в repository, маппятся в HTTP-ответ во view.
"""
from __future__ import annotations


class PlanHasRecordedLessons(Exception):
    """
    Попытка задать группе длину курса короче, чем в ней уже проведено занятий.

    Урезать план можно только по непроведённым (pending/overdue) строкам:
    удаление проведённого (done) или перенесённого (moved) занятия — потеря
    фактических данных. View отдаёт 409 Conflict.
    """

    def __init__(self, recorded_lessons: int) -> None:
        self.recorded_lessons = recorded_lessons
        super().__init__(
            f'В группе уже проведено занятий: {recorded_lessons}. '
            f'Задать меньшее число уроков нельзя.'
        )
```

- [ ] **Step 4: Реализовать `resize_plan`**

В конец `apps/scheduling/repository.py` добавить:

```python
def resize_plan(group_id: int) -> int:
    """
    Подогнать план группы под её текущую длину курса (после правки lessons_total).

    Хвост за границей новой длины удаляется — но ТОЛЬКО pending/overdue строки;
    done/moved защищены (PlanHasRecordedLessons). Недостающие позиции дописываются
    от даты последнего планового занятия по текущим открытым слотам, тем же
    примитивом planner.generate, что строит план с нуля, — поэтому seq/номера
    продолжаются непрерывно. Маркеры отмен (seq IS NULL) не трогаются.

    Единицы: длина курса — в УРОКАХ, план — в занятиях. Число занятий =
    уроки / шаг (45 мин → шаг 0.5 → вдвое больше занятий), поэтому граница
    считается через step, а не по числу уроков напрямую.

    Возвращает число изменённых строк (удалённых + созданных). No-op, если длина
    курса не задана нигде, нет открытых слотов или дописывать некуда.
    """
    g = (
        Group.objects
        .filter(id=group_id)
        .values(
            'id', 'lesson_duration_minutes', 'teacher_id', 'group_start_date',
            total_lessons=effective_total_lessons_expr(),
        )
        .first()
    )
    if g is None or g['total_lessons'] is None:
        return 0

    step = _step_for(g['lesson_duration_minutes'])
    target_count = int(Decimal(g['total_lessons']) / step)
    now = msk_now()
    changed = 0

    with transaction.atomic():
        rows = list(
            PlannedLesson.objects
            .select_for_update()
            .filter(group_id=group_id, seq__isnull=False)
            .order_by('seq')
        )
        extra = [p for p in rows if p.seq > target_count]
        blocked = [p for p in extra if p.status not in _MUTABLE_STATUSES]
        if blocked:
            recorded = len([p for p in rows if p.status not in _MUTABLE_STATUSES])
            raise PlanHasRecordedLessons(recorded)

        if extra:
            PlannedLesson.objects.filter(id__in=[p.id for p in extra]).delete()
            changed += len(extra)

        kept = [p for p in rows if p.seq <= target_count]
        if len(kept) >= target_count:
            return changed

        open_slots = [
            s for s in slots_by_group([group_id]).get(group_id, [])
            if s.effective_to is None
        ]
        if not open_slots:
            return changed  # некуда разворачивать хвост — план останется коротким

        if kept:
            last = kept[-1]
            start_seq = last.seq + 1
            start_number = last.lesson_number
            start_date = last.scheduled_date + datetime.timedelta(days=1)
        elif g['group_start_date'] is not None:
            start_seq = 1
            start_number = Decimal('0')
            start_date = g['group_start_date']
        else:
            return changed

        new_rows = planner.generate(
            start_date=start_date,
            slots=open_slots,
            total_lessons=g['total_lessons'],
            duration_minutes=g['lesson_duration_minutes'],
            default_teacher_id=g['teacher_id'],
            start_seq=start_seq,
            start_number=start_number,
        )
        if new_rows:
            PlannedLesson.objects.bulk_create([
                PlannedLesson(
                    group_id=group_id,
                    seq=r.seq,
                    lesson_number=r.lesson_number,
                    scheduled_date=r.scheduled_date,
                    scheduled_time=r.scheduled_time,
                    teacher_id=r.teacher_id,
                    status=r.status,
                    created_at=now,
                    updated_at=now,
                )
                for r in new_rows
            ])
            changed += len(new_rows)

    return changed
```

Добавить импорт исключения в начало `apps/scheduling/repository.py`:

```python
from apps.scheduling.exceptions import PlanHasRecordedLessons
```

Проверить, что `datetime`, `Decimal`, `transaction`, `planner`, `_step_for`, `msk_now`, `_MUTABLE_STATUSES`, `slots_by_group` уже импортированы в этом модуле (все они там используются выше) — новых импортов, кроме исключения и `effective_total_lessons_expr` из Task 2, не требуется.

- [ ] **Step 5: Прогнать тесты**

Run: `.venv/Scripts/python.exe -m pytest apps/scheduling/tests/test_plan_lessons_total.py -q`
Expected: 6 passed

- [ ] **Step 6: Добавить обёртку в services**

В `apps/scheduling/services.py` рядом с `generate_plan` добавить:

```python
def resize_plan(group_id: int) -> int:
    """Подогнать план под текущую длину курса группы. См. repository.resize_plan."""
    return repository.resize_plan(group_id)
```

- [ ] **Step 7: Прогнать весь scheduling**

Run: `.venv/Scripts/python.exe -m pytest apps/scheduling -q`
Expected: все тесты проходят

- [ ] **Step 8: Показать изменения пользователю**

Run: `git status --short && git diff --stat`

---

## Task 5: API — приём, выдача и вызов подгонки плана

**Files:**
- Modify: `journal_django/apps/groups/serializers.py` (три сериализатора), `journal_django/apps/groups/repository.py` (`_GROUP_FIELDS:43`, `create_group:223`, `update_group:276`), `journal_django/apps/groups/services.py` (`update_group:175`), `journal_django/apps/groups/views.py:149`
- Test: `journal_django/apps/groups/tests/test_group_lessons_total.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `apps/groups/tests/test_group_lessons_total.py`:

```python
@pytest.mark.django_db
def test_api_create_group_with_lessons_total(admin_client, dir_and_teacher):
    """POST принимает число уроков и возвращает его в ответе."""
    direction_id, teacher_id = dir_and_teacher
    resp = admin_client.post('/api/admin/groups', {
        'name': '__lt_api_create__',
        'direction_id': direction_id,
        'teacher_id': teacher_id,
        'is_individual': True,
        'lesson_duration_minutes': 90,
        'lessons_per_week': 1,
        'lessons_total': 2,
        'slots': [],
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert resp.json()['lessons_total'] == 2


@pytest.mark.django_db
def test_api_patch_lessons_total_and_reset(admin_client, dir_and_teacher):
    """PATCH задаёт число и умеет сбросить его обратно в «как в направлении»."""
    from apps.groups.models import Group
    direction_id, teacher_id = dir_and_teacher
    g = Group.objects.create(
        name='__lt_api_patch__', direction_id=direction_id, teacher_id=teacher_id,
        is_individual=True, lesson_duration_minutes=90, lessons_per_week=1,
        created_at='2026-07-27T00:00:00+03:00',
    )

    resp = admin_client.patch(f'/api/admin/groups/{g.id}', {'lessons_total': 3}, format='json')
    assert resp.status_code == 200, resp.content
    assert resp.json()['lessons_total'] == 3

    resp = admin_client.patch(f'/api/admin/groups/{g.id}', {'lessons_total': None}, format='json')
    assert resp.status_code == 200, resp.content
    assert resp.json()['lessons_total'] is None


@pytest.mark.django_db
def test_api_rejects_zero_lessons_total(admin_client, dir_and_teacher):
    """Ноль уроков отклоняется валидацией, а не падает на CHECK."""
    from apps.groups.models import Group
    direction_id, teacher_id = dir_and_teacher
    g = Group.objects.create(
        name='__lt_api_zero__', direction_id=direction_id, teacher_id=teacher_id,
        is_individual=True, lesson_duration_minutes=90, lessons_per_week=1,
        created_at='2026-07-27T00:00:00+03:00',
    )

    resp = admin_client.patch(f'/api/admin/groups/{g.id}', {'lessons_total': 0}, format='json')

    assert resp.status_code == 400


@pytest.mark.django_db
def test_api_patch_shrinks_plan(admin_client, dir_and_teacher):
    """Правка числа через API подгоняет план (не только сохраняет поле)."""
    from apps.groups.models import Group
    from apps.scheduling.models import PlannedLesson
    from apps.scheduling.repository import generate_for_group
    direction_id, teacher_id = dir_and_teacher
    g = Group.objects.create(
        name='__lt_api_plan__', direction_id=direction_id, teacher_id=teacher_id,
        is_individual=True, lesson_duration_minutes=90, lessons_per_week=1,
        group_start_date=datetime.date(2026, 8, 3),
        created_at='2026-07-27T00:00:00+03:00',
    )
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO group_schedule_slots (group_id, day_of_week, start_time, effective_from) "
            "VALUES (%s, 1, TIME '10:00', DATE '2000-01-01')", [g.id])
    generate_for_group(g.id)
    assert PlannedLesson.objects.filter(group_id=g.id, seq__isnull=False).count() == 8

    resp = admin_client.patch(f'/api/admin/groups/{g.id}', {'lessons_total': 3}, format='json')

    assert resp.status_code == 200, resp.content
    assert PlannedLesson.objects.filter(group_id=g.id, seq__isnull=False).count() == 3


@pytest.mark.django_db
def test_api_patch_conflict_on_recorded(admin_client, dir_and_teacher):
    """Урезать план короче проведённых занятий — 409, поле не сохраняется."""
    from apps.groups.models import Group
    from apps.scheduling.models import PlannedLesson
    from apps.scheduling.repository import generate_for_group
    direction_id, teacher_id = dir_and_teacher
    g = Group.objects.create(
        name='__lt_api_conflict__', direction_id=direction_id, teacher_id=teacher_id,
        is_individual=True, lesson_duration_minutes=90, lessons_per_week=1,
        group_start_date=datetime.date(2026, 8, 3),
        created_at='2026-07-27T00:00:00+03:00',
    )
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO group_schedule_slots (group_id, day_of_week, start_time, effective_from) "
            "VALUES (%s, 1, TIME '10:00', DATE '2000-01-01')", [g.id])
    generate_for_group(g.id)
    PlannedLesson.objects.filter(group_id=g.id, seq__in=[1, 2, 3]).update(status='done')

    resp = admin_client.patch(f'/api/admin/groups/{g.id}', {'lessons_total': 2}, format='json')

    assert resp.status_code == 409, resp.content
    g.refresh_from_db()
    assert g.lessons_total is None  # откат транзакции: поле не сохранилось
    assert PlannedLesson.objects.filter(group_id=g.id, seq__isnull=False).count() == 8
```

В начало файла тестов добавить `import datetime`, а фикстуре `dir_and_teacher` в блоке очистки — удаление плана и слотов перед удалением групп:

```python
        cur.execute("DELETE FROM planned_lessons WHERE group_id IN "
                    "(SELECT id FROM groups WHERE direction_id = %s)", [direction_id])
        cur.execute("DELETE FROM group_schedule_slots WHERE group_id IN "
                    "(SELECT id FROM groups WHERE direction_id = %s)", [direction_id])
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python.exe -m pytest apps/groups/tests/test_group_lessons_total.py -q -k api`
Expected: FAIL — в ответе нет ключа `lessons_total`

- [ ] **Step 3: Сериализаторы**

В `apps/groups/serializers.py`:

`GroupReadSerializer` — после `lesson_number_offset` добавить:

```python
    # Ручная длина курса группы в уроках; null — «как в направлении».
    lessons_total = serializers.IntegerField(allow_null=True, required=False)
```

`GroupWriteSerializer` — после `lessons_per_week` добавить:

```python
    lessons_total = serializers.IntegerField(min_value=1, allow_null=True, required=False)
```

`GroupUpdateSerializer` — после `lessons_per_week` добавить ту же строку:

```python
    lessons_total = serializers.IntegerField(min_value=1, allow_null=True, required=False)
```

- [ ] **Step 4: Repository**

В `apps/groups/repository.py`:

`_GROUP_FIELDS` — добавить `'lessons_total'` в конец кортежа.

`create_group` — в `Group.objects.create(...)` после `vk_chat=...` добавить:

```python
            lessons_total=data.get('lessons_total'),
```

`update_group` — после блока `vk_chat` добавить (проверка по наличию ключа, а не по истинности: `None` — легальное значение «как в направлении», `0` отсекает сериализатор):

```python
        # Ручная длина курса: ключ присутствует → пишем как есть, включая None
        # («вернуться к длине направления»). Подгонку плана делает services.
        if 'lessons_total' in data:
            obj.lessons_total = data['lessons_total']
```

- [ ] **Step 5: Services — подгонка плана в одной транзакции с правкой**

В `apps/groups/services.py` заменить `update_group` на:

```python
def update_group(group_id: int, data: dict) -> Optional[dict]:
    """Обновляет группу. Возвращает None если не найдена.

    Если сменилась ручная длина курса (lessons_total) — план подгоняется под неё
    в ТОЙ ЖЕ транзакции: 409 (PlanHasRecordedLessons) откатывает и запись поля,
    иначе в БД осталось бы число, которому план не соответствует.
    """
    from django.db import transaction
    from apps.groups.models import Group
    from apps.scheduling import services as scheduling_services

    before = (
        Group.objects.filter(id=group_id)
        .values_list('lessons_total', flat=True)
        .first()
    )
    with transaction.atomic():
        group = repository.update_group(group_id, data)
        if group is None:
            return None
        if 'lessons_total' in data and data['lessons_total'] != before:
            scheduling_services.resize_plan(group_id)

    _autogenerate_plan(group_id, 'group_update')
    return group
```

- [ ] **Step 6: View — 409**

В `apps/groups/views.py` в методе `patch` расширить обработку исключений рядом с `ImmutableGroupFormat`:

```python
        except PlanHasRecordedLessons as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
```

и добавить импорт:

```python
from apps.scheduling.exceptions import PlanHasRecordedLessons
```

- [ ] **Step 7: Прогнать тесты**

Run: `.venv/Scripts/python.exe -m pytest apps/groups -q`
Expected: все тесты groups проходят

- [ ] **Step 8: Показать изменения пользователю**

Run: `git status --short && git diff --stat`

---

## Task 6: Подпись поля в журнале изменений

**Files:**
- Modify: `journal_django/apps/changelog/summary.py:210`
- Test: `journal_django/apps/groups/tests/test_group_lessons_total.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `apps/groups/tests/test_group_lessons_total.py`:

```python
def test_changelog_label_for_lessons_total():
    """Поле подписано по-русски — иначе в журнале изменений будет сырое имя колонки."""
    from apps.changelog.summary import FIELD_RU
    assert FIELD_RU['lessons_total'] == 'уроков в группе'
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv/Scripts/python.exe -m pytest apps/groups/tests/test_group_lessons_total.py -q -k changelog`
Expected: FAIL — `KeyError: 'lessons_total'`

- [ ] **Step 3: Добавить подпись**

В `apps/changelog/summary.py` в словарь `FIELD_RU` (около строки 181) рядом со строкой `'total_lessons': 'всего занятий', ...` добавить:

```python
    'lessons_total': 'уроков в группе',
```

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/Scripts/python.exe -m pytest apps/groups/tests/test_group_lessons_total.py apps/changelog -q`
Expected: все проходят

- [ ] **Step 5: Показать изменения пользователю**

Run: `git status --short && git diff --stat`

---

## Task 7: Интерфейс — ввод и отображение

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/shared-types.ts:53`, `hooks/useGroups.ts:14`, `pages/groups/GroupFormModal.tsx`, `pages/groups/GroupDetailPage.tsx:92`

- [ ] **Step 1: Тип и payload**

В `lib/shared-types.ts` в тип `Group` после `lesson_number_offset?: number;` добавить:

```ts
  // Ручная длина курса группы в уроках; null/undefined — «как в направлении».
  // Единица — уроки, не занятия: у 45-мин группы 2 урока = 4 занятия.
  lessons_total?: number | null;
```

В `hooks/useGroups.ts` в `GroupPayload` после `lessons_per_week: number;` добавить:

```ts
  lessons_total?: number | null;
```

- [ ] **Step 2: Поле в форме группы**

В `pages/groups/GroupFormModal.tsx`:

добавить импорт:

```tsx
import { NumberInput } from '../../components/form/NumberInput';
```

добавить состояние рядом с остальными:

```tsx
  // Пустая строка = «как в направлении» (на бэк уйдёт null).
  const [lessonsTotal, setLessonsTotal] = useState<string>(
    initial?.lessons_total != null ? String(initial.lessons_total) : '',
  );
```

добавить производные значения после `directionOptions`:

```tsx
  const selectedDirection = directions.find((d) => d.id === Number(directionId));
  const directionLessons = selectedDirection?.total_lessons ?? null;
  // Половинный формат: один урок курса = два занятия по 45 минут.
  const sessionsHint = lessonsTotal && duration === 45
    ? `${lessonsTotal} ур. = ${Number(lessonsTotal) * 2} занятий по 45 мин`
    : null;
```

в `onSubmit` в теле create добавить после `lessons_per_week: 1,`:

```tsx
          lessons_total: lessonsTotal ? Number(lessonsTotal) : null,
```

в теле update добавить после `vk_chat: vkChat || null,`:

```tsx
          lessons_total: lessonsTotal ? Number(lessonsTotal) : null,
```

в разметку, в секцию «Параметры» после поля «Длительность», добавить:

```tsx
        <Field label="Уроков в группе">
          <NumberInput
            min={1}
            step={1}
            value={lessonsTotal}
            onChange={(e) => setLessonsTotal(e.target.value)}
            placeholder={directionLessons ? `как в направлении (${directionLessons})` : 'как в направлении'}
          />
          <span className="field-hint">
            {sessionsHint
              || 'Сколько уроков курса пройдёт эта группа. Пусто — весь курс направления.'}
          </span>
        </Field>
```

- [ ] **Step 3: Отображение на карточке группы**

В `pages/groups/GroupDetailPage.tsx` в массив `fields` после строки `{ key: 'lessons_per_week', label: 'Уроков в неделю' },` добавить:

```tsx
    { key: 'lessons_total', label: 'Уроков в группе',
      cell: (r) => r.lessons_total != null
        ? `${r.lessons_total} (задано вручную)`
        : 'как в направлении' },
```

- [ ] **Step 4: Проверить типы**

Run: `cd frontend/admin-src && npm run typecheck`
Expected: без ошибок (`tsc --noEmit`)

- [ ] **Step 5: Показать изменения пользователю**

Run: `git status --short && git diff --stat`

`npm run build` НЕ запускать — пересборку `dist` пользователь делает отдельно.

---

## Task 8: Полная верификация

**Files:** нет изменений — только прогон

- [ ] **Step 1: Полный backend-прогон**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 0 failed. Гонять целиком, не по частям: часть приложений использует общую `journal_test`, часть — свежую `test_journal_test`, и раздельный запуск маскирует расхождения схемы.

Этот прогон и есть регресс по разделу 4 спеки: тесты `apps/payments` (лимит продаж) и `apps/students` (прогресс по направлению) должны остаться зелёными без правок — если какой-то из них потребовал изменения, длина группы утекла туда, где ей не место.

- [ ] **Step 2: Проверить, что длина группы не утекла в деньги и прогресс**

Run: `grep -rn "effective_total_lessons_expr" apps/ --include=*.py`
Expected: только `apps/groups/course_length.py`, `apps/groups/repository.py`, `apps/scheduling/repository.py`. Если выражение появилось в `apps/payments`, `apps/students` или `apps/dashboard` — это нарушение раздела 4 спеки, откатить.

- [ ] **Step 3: Ручная проверка в браузере**

1. Создать группу с направлением на 36 уроков, указать «Уроков в группе» = 2, задать расписание → в плане ровно 2 занятия, в сетке 2 клетки.
2. Поменять число на 4 → в плане 4 занятия, две новые даты после последней.
3. Отметить занятие, затем попробовать поставить число меньше проведённого → 409 с понятным текстом, число в форме не сохранилось.
4. Очистить поле → план вернулся к длине направления.
5. Открыть журнал изменений группы → правка подписана «уроков в группе».

- [ ] **Step 4: Привести ПГ300 в порядок**

В группе ПГ300 задать «Уроков в группе» = остаток курса, снять 34 пометки «неоплачиваемый пропуск» на вкладке «Прогресс» (они лягут на новые клетки 1 и 2 и вычеркнут ученика), убедиться, что план сгенерирован на реальные даты.

- [ ] **Step 5: Показать итог пользователю**

Run: `git status --short && git diff --stat`
Коммит — по явной просьбе пользователя.
