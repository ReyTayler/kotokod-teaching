# Раздел «Заполнить» (вкладка Дашборда) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить в admin SPA новую вкладку Дашборда «Заполнить» — сводный, пагинируемый список ВСЕХ просроченных незаполненных плановых уроков групп и доп.уроков (отработок) по всем преподавателям, с фильтром по преподавателю и переходом к заполнению.

**Architecture:** Зеркалим паттерн «Реестра куратора» (`apps/dashboard`): тонкая `APIView` + `StandardPagination`, логика в отдельном сервисе, чтение — батч-запросами репозиториев без N+1. Бэкенд читает overdue-строки двух источников (`PlannedLesson` из `apps/scheduling`, `AbsenceResolution` из `apps/extra_lessons`), сервис `apps/dashboard/fill_service.py` мёржит их в единый список, фильтрует по точному порогу overdue (время урока в МСК уже прошло — как `_planned_status`), сортирует «старые сверху». Фронт — ленивый чанк-вкладка `FillTab` поверх общих `DataTable`/`Combobox`.

**Tech Stack:** Django + DRF (managed-модели PostgreSQL), React 19 + TanStack Query v5 + React Router v7, Vite.

---

## Контекст и предыстория (прочитать перед стартом)

- **Дизайн-решения этой фичи** (закреплены с пользователем 2026-07-20):
  1. Показываем **только overdue** — плановый урок, момент которого в МСК уже строго прошёл, а факт не внесён. Будущие `pending` НЕ показываем.
  2. Скоуп — **план + доп.уроки** (отработки пропусков), все преподаватели сразу.
  3. UI — **плоская таблица + фильтр по преподавателю** (как `AdminCalendarPage`), внутри Дашборда третьей вкладкой рядом с «Финансы»/«Реестр».
  4. Клик по строке планового урока → вкладка группы, где урок **заполняется**. У группы нет вкладки «План»; фактическое заполнение — во вкладке **«Уроки»** (`?tab=lessons`: `LessonGrid` → клик по квадрату → `LessonEditor`). Значит `planned` → `/admin/groups/:groupId?tab=lessons`; `extra` → `/admin/extra-lessons`.

- **Прежняя спека** `docs/superpowers/specs/2026-07-17-lesson-attendance-guard-and-unfilled-dashboard-design.md` (Часть 2) проектировала этот же виджет, но **не была реализована** и расходится с решениями выше (там: только план, без фильтра, окно 30 дней, вкладка «Уроки» как цель — цель совпадает). Настоящий план её заменяет и расширяет. Часть 1 той спеки (блокировка урока без учеников) — **вне охвата**, не трогаем.

- **Почему список в память, а не UNION в БД:** источники гетерогенны (две разные таблицы/модели), а `StandardPagination` штатно пагинирует и обычный Python-список (см. прежнюю спеку и `RegistryStudentsView`-контракт). DB-`WHERE` (активная группа + статус + fact NULL + `scheduled_date <= today`) уже сужает выборку до реального «бэклога незаполненных», а не всех уроков — это не нарушение правила «не читать всё». Мёрж двух списков в Python проще и надёжнее `QuerySet.union()` с выравниванием колонок.

- **Ключевые факты кодовой базы:**
  - Статус планового урока вычисляется на чтении (`apps/scheduling/services.py::_planned_status`): overdue = `status != done/cancelled` И `fact_lesson_id IS NULL` И `datetime(scheduled_date, scheduled_time, МСК) <= now`.
  - Хранимый `PlannedLesson.status` для незаполненного = `'pending'` (`apps/scheduling/occurrences.PENDING`); `done`/`cancelled` — отдельные хранимые значения. Перенос (`moved_from_date`) статус не меняет — перенесённая строка остаётся `pending` и подлежит заполнению.
  - Доп.урок overdue: `AbsenceResolution.status == 'makeup_scheduled'` (`apps/extra_lessons/models.MAKEUP_SCHEDULED`), `fact_lesson_id IS NULL`, время прошло. `pending`-резолюции имеют `scheduled_date IS NULL` и не попадают; `makeup_done` имеет проставленный `fact_lesson`.
  - `apps/scheduling/repository.py::teacher_names()` уже существует (id→имя, батч) — переиспользуем.
  - `StandardPagination` (`apps/core/pagination.py`): query-параметры `page`/`page_size` (default 50, max 500), конверт `{rows, total, page, page_size}`.
  - Тест-БД — managed-схема `journal_test`; фикстуры проекта — raw-SQL insert + явный cleanup (см. `apps/scheduling/tests/conftest.py`, `apps/extra_lessons/tests/conftest.py`). Гоняем дефолтным `pytest`.

- **Инварианты проекта, которые НЕЛЬЗЯ нарушить:**
  - RBAC: каждая новая вьюха задаёт `permission_classes`. Здесь — `IsManagerOrAdmin` (как весь дашборд и доп.уроки).
  - Фронт: только `components/form/*` (`Combobox`), никаких native-элементов; цвета/отступы — токены `styles/tokens.css`; `placeholderData: keepPreviousData` во всех server-paginated хуках.
  - НЕ запускать `npm run build` (dist-артефакты не коммитить). Фронт проверяется вручную в dev (nginx :8080 → runserver).

---

## Структура файлов

**Бэкенд (создать):**
- `journal_django/apps/dashboard/fill_service.py` — мёрж + overdue-фильтр + форма ответа.
- `journal_django/apps/dashboard/fill_views.py` — `UnfilledLessonsView` (RBAC, валидация `teacher_id`, пагинация).
- `journal_django/apps/dashboard/tests/test_fill_api.py` — API + сервис-тесты.

**Бэкенд (изменить):**
- `journal_django/apps/scheduling/repository.py` — новая `unfilled_planned_lessons(today, teacher_id)`.
- `journal_django/apps/extra_lessons/repository.py` — новая `unfilled_extra_lessons(today, teacher_id)`.
- `journal_django/apps/dashboard/urls.py` — маршрут `/unfilled-lessons`.
- `journal_django/apps/scheduling/tests/test_build_calendar.py` — кейс `unfilled_planned_lessons`.
- `journal_django/apps/extra_lessons/tests/test_extra_lessons_repository.py` — кейс `unfilled_extra_lessons`.

**Фронтенд (создать):**
- `journal_django/frontend/admin-src/src/hooks/useUnfilledLessons.ts` — server-paginated хук.
- `journal_django/frontend/admin-src/src/pages/dashboard/fill/FillTable.tsx` — колонки + `onRowClick`-навигация.
- `journal_django/frontend/admin-src/src/pages/dashboard/fill/FillTab.tsx` — фильтр-`Combobox` + таблица + пустое состояние.

**Фронтенд (изменить):**
- `journal_django/frontend/admin-src/src/lib/shared-types.ts` — тип `UnfilledLesson`.
- `journal_django/frontend/admin-src/src/pages/dashboard/DashboardPage.tsx` — третья вкладка `fill`.

---

## Task 1: Репозиторий scheduling — `unfilled_planned_lessons`

**Files:**
- Modify: `journal_django/apps/scheduling/repository.py`
- Test: `journal_django/apps/scheduling/tests/test_build_calendar.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `journal_django/apps/scheduling/tests/test_build_calendar.py` (использует фикстуру `sched_setup` из `conftest.py`; создаёт плановые строки прямым SQL и проверяет выборку):

```python
import datetime
from django.db import connection
from apps.scheduling import repository


def _insert_planned(group_id, teacher_id, date_str, time_str, status='pending', fact_lesson_id=None):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO planned_lessons "
            "(group_id, seq, lesson_number, scheduled_date, scheduled_time, teacher_id, "
            " status, fact_lesson_id, created_at, updated_at) "
            "VALUES (%s, 1, 1, %s, %s, %s, %s, %s, NOW(), NOW()) RETURNING id",
            [group_id, date_str, time_str, teacher_id, status, fact_lesson_id],
        )
        return cur.fetchone()[0]


def test_unfilled_planned_lessons_filters_and_scope(sched_setup):
    s = sched_setup
    # overdue-кандидат (прошлое, pending, без факта) у преподавателя A
    _insert_planned(s['group_a'], s['teacher_a'], '2026-06-02', '10:00')
    # done — исключается хранимым статусом
    _insert_planned(s['group_a'], s['teacher_a'], '2026-06-03', '10:00', status='done')
    # cancelled — исключается
    _insert_planned(s['group_a'], s['teacher_a'], '2026-06-04', '10:00', status='cancelled')
    # у преподавателя B (своя группа) — не попадёт при фильтре по A
    _insert_planned(s['group_b'], s['teacher_b'], '2026-06-05', '12:00')

    today = datetime.date(2026, 7, 1)

    all_rows = repository.unfilled_planned_lessons(today)
    dates = {(r['group_pk'], r['scheduled_date'].isoformat()) for r in all_rows}
    assert (s['group_a'], '2026-06-02') in dates       # pending попал
    assert (s['group_b'], '2026-06-05') in dates       # оба преподавателя (school-wide)
    assert all(r['scheduled_date'].isoformat() not in ('2026-06-03', '2026-06-04')
               for r in all_rows if r['group_pk'] == s['group_a'])  # done/cancelled нет

    a_rows = repository.unfilled_planned_lessons(today, teacher_id=s['teacher_a'])
    a_groups = {r['group_pk'] for r in a_rows}
    assert s['group_a'] in a_groups and s['group_b'] not in a_groups  # фильтр по преподавателю


def test_unfilled_planned_lessons_excludes_future_and_filled(sched_setup):
    s = sched_setup
    # будущее относительно today — DB отдаёт (<= today), сервис отсечёт по времени;
    # здесь проверяем сам DB-фильтр: дата > today не выбирается вовсе.
    _insert_planned(s['group_a'], s['teacher_a'], '2026-08-01', '10:00')
    today = datetime.date(2026, 7, 1)
    rows = repository.unfilled_planned_lessons(today)
    assert all(r['scheduled_date'] <= today for r in rows)
```

- [ ] **Step 2: Прогнать — упадёт**

Run: `cd journal_django && python -m pytest apps/scheduling/tests/test_build_calendar.py::test_unfilled_planned_lessons_filters_and_scope -v`
Expected: FAIL — `AttributeError: module 'apps.scheduling.repository' has no attribute 'unfilled_planned_lessons'`.

- [ ] **Step 3: Реализовать функцию**

Добавить в `journal_django/apps/scheduling/repository.py` (рядом с `planned_lessons_in_window`; `PENDING`, `F`, `Q`, `PlannedLesson` уже импортированы в модуле):

```python
def unfilled_planned_lessons(
    today: datetime.date, teacher_id: int | None = None,
) -> list[dict]:
    """
    Незаполненные плановые занятия ВСЕХ активных групп по школе (или одного
    преподавателя) с датой <= today — источник вкладки «Заполнить».

    Overdue-порог по времени (момент урока в МСК уже прошёл) досчитывает вызывающий
    (fill_service), как и `_planned_status`/`build_calendar` — здесь только грубый
    DB-срез по дате. `status=PENDING` + `fact_lesson__isnull` исключают done/
    cancelled/уже-связанные с фактом строки. Скоуп преподавателя — по эффективному
    исполнителю (замена ИЛИ штатный препод занятия), как в `planned_lessons_in_window`.

    Возвращает «сырые» словари (date/time — объекты) для fill_service.
    """
    qs = PlannedLesson.objects.filter(
        group__active=True,
        status=PENDING,
        fact_lesson__isnull=True,
        scheduled_date__lte=today,
    )
    if teacher_id is not None:
        qs = qs.filter(
            Q(substitute_teacher_id=teacher_id)
            | Q(substitute_teacher_id__isnull=True, teacher_id=teacher_id)
        )
    return list(
        qs.order_by('scheduled_date', 'scheduled_time').values(
            'id', 'scheduled_date', 'scheduled_time', 'lesson_number',
            'teacher_id', 'substitute_teacher_id',
            group_pk=F('group_id'),
            group_name=F('group__name'),
            direction_name=F('group__direction__name'),
            direction_color=F('group__direction__color'),
        )
    )
```

- [ ] **Step 4: Прогнать — пройдёт**

Run: `cd journal_django && python -m pytest apps/scheduling/tests/test_build_calendar.py -k unfilled_planned -v`
Expected: PASS (оба теста).

- [ ] **Step 5: Коммит**

```bash
git add journal_django/apps/scheduling/repository.py journal_django/apps/scheduling/tests/test_build_calendar.py
git commit -m "feat(scheduling): unfilled_planned_lessons — school-wide overdue plan query"
```

---

## Task 2: Репозиторий extra_lessons — `unfilled_extra_lessons`

**Files:**
- Modify: `journal_django/apps/extra_lessons/repository.py`
- Test: `journal_django/apps/extra_lessons/tests/test_extra_lessons_repository.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `journal_django/apps/extra_lessons/tests/test_extra_lessons_repository.py` (переиспользует фикстуры `conftest.py`: `missed_lesson_fixture`, `student_fixture`, `teacher_fixture`, `group_fixture`). Создаёт резолюции прямым SQL:

```python
import datetime
from django.db import connection
from apps.extra_lessons import repository


def _insert_resolution(missed_lesson_id, student_id, teacher_id, status,
                       date_str, time_str, fact_lesson_id=None):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO absence_resolutions "
            "(missed_lesson_id, student_id, assigned_teacher_id, scheduled_date, "
            " scheduled_time, duration_minutes, status, fact_lesson_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, 60, %s, %s, NOW()) RETURNING id",
            [missed_lesson_id, student_id, teacher_id, date_str, time_str, status, fact_lesson_id],
        )
        rid = cur.fetchone()[0]
    return rid


def test_unfilled_extra_lessons_scope_and_status(
    missed_lesson_fixture, student_fixture, teacher_fixture, group_fixture, other_teacher_fixture,
):
    # makeup_scheduled в прошлом → кандидат
    rid = _insert_resolution(missed_lesson_fixture, student_fixture, teacher_fixture,
                             'makeup_scheduled', '2026-06-10', '15:00')
    today = datetime.date(2026, 7, 1)
    try:
        rows = repository.unfilled_extra_lessons(today)
        ids = {r['id'] for r in rows}
        assert rid in ids
        row = next(r for r in rows if r['id'] == rid)
        assert row['group_id'] == group_fixture
        assert row['assigned_teacher_id'] == teacher_fixture
        assert row['group_name'] == '__el_test_group__'

        # фильтр по чужому преподавателю — резолюции нет
        assert rid not in {r['id'] for r in repository.unfilled_extra_lessons(today, other_teacher_fixture)}
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM absence_resolutions WHERE id = %s', [rid])


def test_unfilled_extra_lessons_excludes_pending_and_done(
    missed_lesson_fixture, student_fixture, teacher_fixture,
):
    # makeup_done (с фактом) — исключается; pending имеет scheduled_date NULL → не создаём
    done = _insert_resolution(missed_lesson_fixture, student_fixture, teacher_fixture,
                              'makeup_done', '2026-06-11', '15:00', fact_lesson_id=missed_lesson_fixture)
    today = datetime.date(2026, 7, 1)
    try:
        assert done not in {r['id'] for r in repository.unfilled_extra_lessons(today)}
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM absence_resolutions WHERE id = %s', [done])
```

- [ ] **Step 2: Прогнать — упадёт**

Run: `cd journal_django && python -m pytest apps/extra_lessons/tests/test_extra_lessons_repository.py -k unfilled_extra -v`
Expected: FAIL — `AttributeError: ... has no attribute 'unfilled_extra_lessons'`.

- [ ] **Step 3: Реализовать функцию**

Добавить в `journal_django/apps/extra_lessons/repository.py` (рядом с `assignments_in_window`). Убедиться, что вверху модуля импортированы `AbsenceResolution` и `MAKEUP_SCHEDULED` — если `MAKEUP_SCHEDULED` не импортирован, добавить в существующий импорт `from apps.extra_lessons.models import ...`:

```python
def unfilled_extra_lessons(today, teacher_id=None) -> list[dict]:
    """Незаполненные доп.уроки (отработки) по школе с датой <= today — источник
    вкладки «Заполнить». makeup_scheduled без факта; pending имеет scheduled_date
    NULL и не попадает, makeup_done имеет проставленный fact_lesson. Overdue-порог
    по времени досчитывает вызывающий (fill_service). group_id/group_name — группа
    пропущенного урока (для перехода). Опц. скоуп по назначенному преподавателю."""
    qs = AbsenceResolution.objects.filter(
        status=MAKEUP_SCHEDULED,
        fact_lesson__isnull=True,
        scheduled_date__lte=today,
    )
    if teacher_id is not None:
        qs = qs.filter(assigned_teacher_id=teacher_id)
    return list(
        qs.order_by('scheduled_date', 'scheduled_time').values(
            'id', 'scheduled_date', 'scheduled_time', 'assigned_teacher_id',
            group_id=F('missed_lesson__group_id'),
            group_name=F('missed_lesson__group__name'),
        )
    )
```

- [ ] **Step 4: Прогнать — пройдёт**

Run: `cd journal_django && python -m pytest apps/extra_lessons/tests/test_extra_lessons_repository.py -k unfilled_extra -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add journal_django/apps/extra_lessons/repository.py journal_django/apps/extra_lessons/tests/test_extra_lessons_repository.py
git commit -m "feat(extra-lessons): unfilled_extra_lessons — school-wide overdue makeup query"
```

---

## Task 3: Сервис `fill_service.unfilled_lessons` (мёрж + overdue-порог + сортировка)

**Files:**
- Create: `journal_django/apps/dashboard/fill_service.py`
- Test: `journal_django/apps/dashboard/tests/test_fill_api.py` (создаём файл, часть 1 — сервис)

- [ ] **Step 1: Написать падающий тест**

Создать `journal_django/apps/dashboard/tests/test_fill_api.py` с raw-SQL хелпером и сервис-тестами (инжектируем `now`, чтобы порог overdue был детерминирован):

```python
"""Тесты вкладки «Заполнить»: сервис мёржа + API (RBAC, пагинация, фильтр)."""
from __future__ import annotations

import datetime

import pytest
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import connection
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.utils.dates import MSK
from apps.dashboard import fill_service


@pytest.fixture
def fill_setup(db):
    """Преподаватель + активная группа + плановые строки под разные кейсы."""
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name, active) VALUES ('__fill_T__', true) RETURNING id")
        teacher = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO directions (name,is_individual,total_lessons,color,active) "
            "VALUES ('__fill_dir__',false,8,'#4F59F9',true) RETURNING id")
        direction = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
            "lesson_duration_minutes,group_start_date,active) "
            "VALUES ('__fill_G__',%s,%s,false,60,'2026-06-01',true) RETURNING id",
            [direction, teacher])
        group = cur.fetchone()[0]
        # A: overdue (прошлое, pending, без факта)
        cur.execute(
            "INSERT INTO planned_lessons (group_id,seq,lesson_number,scheduled_date,"
            "scheduled_time,teacher_id,status,created_at,updated_at) "
            "VALUES (%s,1,1,'2026-06-02','10:00',%s,'pending',NOW(),NOW())", [group, teacher])
        # B: сегодня, но время ещё НЕ наступило относительно инжектированного now
        cur.execute(
            "INSERT INTO planned_lessons (group_id,seq,lesson_number,scheduled_date,"
            "scheduled_time,teacher_id,status,created_at,updated_at) "
            "VALUES (%s,2,2,'2026-07-01','23:00',%s,'pending',NOW(),NOW())", [group, teacher])
    data = {'teacher': teacher, 'direction': direction, 'group': group}
    yield data
    with connection.cursor() as cur:
        cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group])
        cur.execute('DELETE FROM groups WHERE id = %s', [group])
        cur.execute('DELETE FROM directions WHERE id = %s', [direction])
        cur.execute('DELETE FROM teachers WHERE id = %s', [teacher])


def test_unfilled_lessons_includes_overdue_excludes_future(fill_setup):
    # now = 2026-07-01 12:00 МСК: строка A (02.06) прошла, строка B (01.07 23:00) — нет
    now = datetime.datetime(2026, 7, 1, 12, 0, tzinfo=MSK)
    rows = fill_service.unfilled_lessons(now=now)
    ours = [r for r in rows if r['group_id'] == fill_setup['group']]
    assert len(ours) == 1
    assert ours[0]['date'] == '2026-06-02'
    assert ours[0]['kind'] == 'planned'
    assert ours[0]['time'] == '10:00'
    assert ours[0]['teacher_name'] == '__fill_T__'
    assert ours[0]['lesson_number'] == 1.0


def test_unfilled_lessons_teacher_filter(fill_setup):
    now = datetime.datetime(2026, 7, 1, 12, 0, tzinfo=MSK)
    other = fill_service.unfilled_lessons(teacher_id=fill_setup['teacher'] + 100000, now=now)
    assert all(r['group_id'] != fill_setup['group'] for r in other)


def test_unfilled_lessons_sorted_old_first(fill_setup):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO planned_lessons (group_id,seq,lesson_number,scheduled_date,"
            "scheduled_time,teacher_id,status,created_at,updated_at) "
            "VALUES (%s,3,3,'2026-05-01','09:00',%s,'pending',NOW(),NOW())",
            [fill_setup['group'], fill_setup['teacher']])
    now = datetime.datetime(2026, 7, 1, 12, 0, tzinfo=MSK)
    ours = [r for r in fill_service.unfilled_lessons(now=now)
            if r['group_id'] == fill_setup['group']]
    assert [r['date'] for r in ours] == ['2026-05-01', '2026-06-02']  # старые сверху
```

- [ ] **Step 2: Прогнать — упадёт**

Run: `cd journal_django && python -m pytest apps/dashboard/tests/test_fill_api.py -k "unfilled_lessons" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.dashboard.fill_service'`.

- [ ] **Step 3: Реализовать сервис**

Создать `journal_django/apps/dashboard/fill_service.py`:

```python
"""
Сервис вкладки «Заполнить» — сводка просроченных незаполненных занятий по школе.

Мёржит два источника (плановые уроки `apps.scheduling` + доп.уроки-отработки
`apps.extra_lessons`), отсекает по точному порогу overdue (момент занятия в МСК
уже наступил — та же логика, что `scheduling.services._planned_status`), сортирует
«старые сверху». Пагинацию делает вьюха (StandardPagination поверх списка).
"""
from __future__ import annotations

import datetime

from apps.core.utils.dates import MSK, msk_now
from apps.extra_lessons import repository as extra_repo
from apps.scheduling import repository as scheduling_repo


def _passed(d: datetime.date, t: datetime.time | None, now: datetime.datetime) -> bool:
    """Момент занятия (МСК) уже наступил — overdue-порог, как в _planned_status."""
    occ_dt = datetime.datetime.combine(d, t or datetime.time(0, 0), tzinfo=MSK)
    return now >= occ_dt


def _fmt_time(t: datetime.time | None) -> str | None:
    return t.strftime('%H:%M') if t else None


def unfilled_lessons(
    teacher_id: int | None = None, now: datetime.datetime | None = None,
) -> list[dict]:
    """Плоский список overdue незаполненных уроков (план + доп.уроки), старые сверху.
    now инжектируется в тестах; в проде — msk_now()."""
    now = now or msk_now()
    today = now.date()
    tnames = scheduling_repo.teacher_names()
    out: list[dict] = []

    for r in scheduling_repo.unfilled_planned_lessons(today, teacher_id):
        if not _passed(r['scheduled_date'], r['scheduled_time'], now):
            continue
        effective = r['substitute_teacher_id'] or r['teacher_id']
        out.append({
            'kind': 'planned',
            'id': r['id'],
            'group_id': r['group_pk'],
            'group_name': r['group_name'],
            'teacher_name': tnames.get(effective),
            'direction_name': r['direction_name'],
            'direction_color': r['direction_color'],
            'lesson_number': float(r['lesson_number']) if r['lesson_number'] is not None else None,
            'date': r['scheduled_date'].isoformat(),
            'time': _fmt_time(r['scheduled_time']),
        })

    for r in extra_repo.unfilled_extra_lessons(today, teacher_id):
        if not _passed(r['scheduled_date'], r['scheduled_time'], now):
            continue
        out.append({
            'kind': 'extra',
            'id': r['id'],
            'group_id': r['group_id'],
            'group_name': r['group_name'],
            'teacher_name': tnames.get(r['assigned_teacher_id']),
            'direction_name': None,
            'direction_color': None,
            'lesson_number': None,
            'date': r['scheduled_date'].isoformat(),
            'time': _fmt_time(r['scheduled_time']),
        })

    out.sort(key=lambda x: (x['date'], x['time'] or ''))
    return out
```

Примечание: проверить, что `apps/core/utils/dates.py` экспортирует `MSK` и `msk_now` (используются в `scheduling/services.py`). Если имя таймзоны иное — использовать то же, что импортирует `scheduling/services.py`.

- [ ] **Step 4: Прогнать — пройдёт**

Run: `cd journal_django && python -m pytest apps/dashboard/tests/test_fill_api.py -k "unfilled_lessons" -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Коммит**

```bash
git add journal_django/apps/dashboard/fill_service.py journal_django/apps/dashboard/tests/test_fill_api.py
git commit -m "feat(dashboard): fill_service.unfilled_lessons — merge overdue plan + makeups"
```

---

## Task 4: Вьюха + маршрут `/api/admin/dashboard/unfilled-lessons`

**Files:**
- Create: `journal_django/apps/dashboard/fill_views.py`
- Modify: `journal_django/apps/dashboard/urls.py`
- Test: `journal_django/apps/dashboard/tests/test_fill_api.py` (дополняем — часть 2, API)

- [ ] **Step 1: Написать падающий тест**

Дописать в `journal_django/apps/dashboard/tests/test_fill_api.py`:

```python
def _jwt_client(role: str) -> APIClient:
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO accounts (email,password,role,is_active,is_staff,is_superuser,"
            "first_name,last_name,token_version,date_joined) "
            "VALUES (%s,%s,%s,true,false,false,'','',0,NOW()) RETURNING id",
            [f'__fill_{role}__@t.local', make_password('x'), role])
        account_id = cur.fetchone()[0]
    from apps.accounts.models import Account
    user = Account.objects.get(pk=account_id)
    refresh = RefreshToken.for_user(user)
    refresh['token_version'] = user.token_version
    client = APIClient()
    client.cookies[settings.SIMPLE_JWT.get('AUTH_COOKIE', 'access')] = str(refresh.access_token)
    client._fill_account_id = account_id  # для cleanup
    return client


def _cleanup_account(client):
    with connection.cursor() as cur:
        cur.execute('DELETE FROM accounts WHERE id = %s', [client._fill_account_id])


URL = '/api/admin/dashboard/unfilled-lessons'


def test_fill_api_envelope_and_rbac(fill_setup):
    manager = _jwt_client('manager')
    teacher = _jwt_client('teacher')
    try:
        # teacher — 403 (IsManagerOrAdmin)
        assert teacher.get(URL).status_code == 403
        # manager — 200, конверт {rows,total,page,page_size}
        resp = manager.get(URL)
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {'rows', 'total', 'page', 'page_size'}
        our = [r for r in body['rows'] if r['group_id'] == fill_setup['group']]
        # строка A (02.06) overdue относительно реального now (тест в будущем от 2026)
        assert any(r['date'] == '2026-06-02' and r['kind'] == 'planned' for r in our)
    finally:
        _cleanup_account(manager)
        _cleanup_account(teacher)


def test_fill_api_teacher_filter_param(fill_setup):
    manager = _jwt_client('manager')
    try:
        resp = manager.get(URL, {'teacher_id': fill_setup['teacher'] + 100000})
        assert resp.status_code == 200
        assert all(r['group_id'] != fill_setup['group'] for r in resp.json()['rows'])
        # кривой teacher_id → 400
        assert manager.get(URL, {'teacher_id': 'abc'}).status_code == 400
    finally:
        _cleanup_account(manager)
```

Примечание: строка A с датой `2026-06-02` гарантированно overdue при реальном `msk_now()` (текущая дата проекта — 2026-07-20 и позже). Строка B (`2026-07-01 23:00`) тоже станет overdue со временем — тест на неё не опирается.

- [ ] **Step 2: Прогнать — упадёт**

Run: `cd journal_django && python -m pytest apps/dashboard/tests/test_fill_api.py -k "fill_api" -v`
Expected: FAIL — 404 (маршрута ещё нет).

- [ ] **Step 3: Реализовать вьюху и маршрут**

Создать `journal_django/apps/dashboard/fill_views.py`:

```python
"""
Тонкая APIView вкладки «Заполнить» дашборда.

  GET /api/admin/dashboard/unfilled-lessons?teacher_id=&page=&page_size=
      → пагинированный {rows,total,page,page_size} просроченных незаполненных
        плановых + доп.уроков по школе (опц. один преподаватель).

Права: manager/admin (IsManagerOrAdmin) — как весь дашборд. Логика — в
fill_service; здесь только валидация teacher_id и пагинация готового списка
(StandardPagination штатно работает и с Python-списком).
"""
from __future__ import annotations

from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import StandardPagination
from apps.core.permissions import IsManagerOrAdmin
from apps.dashboard import fill_service

_MAX_INT4 = 2147483647


class UnfilledLessonsView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        raw = request.query_params.get('teacher_id')
        teacher_id = None
        if raw:
            # isdecimal (не isdigit): '²' пройдёт isdigit, но упадёт в int() → 500.
            if not raw.isdecimal() or int(raw) > _MAX_INT4:
                raise ValidationError('teacher_id должен быть целым числом.')
            teacher_id = int(raw)
        rows = fill_service.unfilled_lessons(teacher_id)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(page)
```

Изменить `journal_django/apps/dashboard/urls.py` — добавить импорт и маршрут:

```python
from apps.dashboard.fill_views import UnfilledLessonsView
```

и в `urlpatterns` (после `'/monthly'`):

```python
    path('/unfilled-lessons', UnfilledLessonsView.as_view(), name='dashboard-unfilled-lessons'),
```

- [ ] **Step 4: Прогнать — пройдёт**

Run: `cd journal_django && python -m pytest apps/dashboard/tests/test_fill_api.py -v`
Expected: PASS (все тесты файла).

- [ ] **Step 5: Коммит**

```bash
git add journal_django/apps/dashboard/fill_views.py journal_django/apps/dashboard/urls.py journal_django/apps/dashboard/tests/test_fill_api.py
git commit -m "feat(dashboard): GET /api/admin/dashboard/unfilled-lessons endpoint"
```

---

## Task 5: Фронт — тип `UnfilledLesson` + хук `useUnfilledLessons`

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/shared-types.ts`
- Create: `journal_django/frontend/admin-src/src/hooks/useUnfilledLessons.ts`

- [ ] **Step 1: Добавить тип**

В `journal_django/frontend/admin-src/src/lib/shared-types.ts` рядом с `export interface Paginated<T>` добавить:

```ts
export interface UnfilledLesson {
  kind: 'planned' | 'extra';
  id: number;
  group_id: number;
  group_name: string;
  teacher_name: string | null;
  direction_name: string | null;
  direction_color: string | null;
  lesson_number: number | null;
  date: string;        // 'YYYY-MM-DD'
  time: string | null; // 'HH:MM'
}
```

- [ ] **Step 2: Создать хук**

Создать `journal_django/frontend/admin-src/src/hooks/useUnfilledLessons.ts` (по образцу `useRegistry.ts::useRegistryStudents`):

```ts
import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Paginated, UnfilledLesson } from '../lib/shared-types';

export interface UnfilledLessonsParams {
  page: number;
  page_size: number;
  teacher_id: number | null;
}

function buildQuery(p: UnfilledLessonsParams): string {
  const qs = new URLSearchParams();
  qs.set('page', String(p.page));
  qs.set('page_size', String(p.page_size));
  if (p.teacher_id != null) qs.set('teacher_id', String(p.teacher_id));
  return qs.toString();
}

/**
 * GET /api/admin/dashboard/unfilled-lessons — серверно-пагинированный список
 * просроченных незаполненных уроков (план + доп.уроки) по школе, опц. фильтр
 * по преподавателю. placeholderData: keepPreviousData — правило проекта.
 */
export function useUnfilledLessons(params: UnfilledLessonsParams) {
  return useQuery({
    queryKey: ['unfilled-lessons', params],
    queryFn: () =>
      api<Paginated<UnfilledLesson>>('GET', `/api/admin/dashboard/unfilled-lessons?${buildQuery(params)}`),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}
```

Примечание: убедиться, что `api` импортируется так же, как в `useRegistry.ts` (там `import { api } from '../lib/api'`), и что `Paginated` действительно экспортируется из `shared-types.ts` (проверено: `useRegistry` берёт `Paginated` из `../lib/types`, который ре-экспортирует из `shared-types`; если сборка ругается — импортировать `Paginated` из `../lib/types`).

- [ ] **Step 3: Проверить типы**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: без ошибок в новых файлах. (Если `npx tsc` не сконфигурирован — `npm run typecheck`, если есть в `package.json`.)

- [ ] **Step 4: Коммит**

```bash
git add journal_django/frontend/admin-src/src/lib/shared-types.ts journal_django/frontend/admin-src/src/hooks/useUnfilledLessons.ts
git commit -m "feat(admin-ui): UnfilledLesson type + useUnfilledLessons hook"
```

---

## Task 6: Фронт — таблица `FillTable`

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/dashboard/fill/FillTable.tsx`

- [ ] **Step 1: Создать компонент**

Создать `journal_django/frontend/admin-src/src/pages/dashboard/fill/FillTable.tsx` (по образцу `registry/RegistryTable.tsx`; клик по строке ведёт к заполнению — план в «Уроки» группы, доп.урок в раздел «Доп.уроки»):

```tsx
import { useNavigate } from 'react-router-dom';
import { DataTable, type Column, type ServerPaginationState, type ServerPaginationCallbacks } from '../../../components/table/DataTable';
import { fmtDate } from '../../../lib/format';
import type { UnfilledLesson } from '../../../lib/shared-types';

interface Props {
  rows: UnfilledLesson[];
  serverPagination: ServerPaginationState & ServerPaginationCallbacks;
  isLoading: boolean;
}

export function FillTable({ rows, serverPagination, isLoading }: Props) {
  const navigate = useNavigate();

  const columns: Column<UnfilledLesson>[] = [
    {
      key: 'date',
      label: 'Дата',
      cell: (r) => (
        <span>
          {fmtDate(r.date)}{r.time ? `, ${r.time}` : ''}
        </span>
      ),
    },
    {
      key: 'group_name',
      label: 'Группа',
      cell: (r) => (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <span
            aria-hidden
            style={{
              width: 8, height: 8, borderRadius: '50%',
              background: r.direction_color || 'var(--text3)', flex: '0 0 auto',
            }}
          />
          {r.group_name}
        </span>
      ),
    },
    {
      key: 'teacher_name',
      label: 'Преподаватель',
      cell: (r) => r.teacher_name || '—',
    },
    {
      key: 'direction_name',
      label: 'Направление',
      cell: (r) => r.direction_name || '—',
    },
    {
      key: 'lesson_number',
      label: '№',
      cell: (r) => (r.lesson_number != null ? String(r.lesson_number) : '—'),
    },
    {
      key: 'kind',
      label: 'Тип',
      cell: (r) =>
        r.kind === 'extra'
          ? <span className="nav-badge" title="Доп.урок (отработка)">Доп.</span>
          : <span style={{ color: 'var(--text3)' }}>Урок</span>,
    },
  ];

  const goFill = (r: UnfilledLesson) => {
    if (r.kind === 'extra') navigate('/admin/extra-lessons');
    else navigate(`/admin/groups/${r.group_id}?tab=lessons`);
  };

  return (
    <DataTable<UnfilledLesson>
      data={rows}
      columns={columns}
      title="Незаполненные уроки"
      onRowClick={goFill}
      serverPagination={serverPagination}
      isLoading={isLoading}
    />
  );
}
```

Примечание: проверить, что `fmtDate` экспортируется из `lib/format` (используется в `RegistryTable.tsx`). Класс `nav-badge` уже определён (см. `Sidebar.tsx` `ExtraLessonsBadge`).

- [ ] **Step 2: Проверить типы**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: без ошибок.

- [ ] **Step 3: Коммит**

```bash
git add journal_django/frontend/admin-src/src/pages/dashboard/fill/FillTable.tsx
git commit -m "feat(admin-ui): FillTable — unfilled-lessons table with fill navigation"
```

---

## Task 7: Фронт — вкладка `FillTab` (фильтр по преподавателю + таблица + пустое состояние)

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/dashboard/fill/FillTab.tsx`

- [ ] **Step 1: Создать компонент**

Создать `journal_django/frontend/admin-src/src/pages/dashboard/fill/FillTab.tsx` (фильтр — `Combobox` как в `AdminCalendarPage`, состояние page/teacher в URL через `useListSearchParams` как в `RegistryTab`):

```tsx
import { useMemo } from 'react';
import { useListSearchParams } from '../../../hooks/useListSearchParams';
import { useTeachers } from '../../../hooks/useTeachers';
import { useUnfilledLessons } from '../../../hooks/useUnfilledLessons';
import { FillTable } from './FillTable';
import { Field } from '../../../components/form/Field';
import { Combobox } from '../../../components/form/Combobox';

export default function FillTab() {
  const s = useListSearchParams({ sortBy: 'date', sortDir: 'asc', pageSize: 30 });
  const { page, pageSize, sortBy, sortDir, filters, setPage, setPageSize, getExtra, setExtra } = s;

  const teachers = useTeachers(true); // включая архивных — у них тоже бывают старые долги
  const rawTeacher = getExtra('teacher');
  const teacherId = rawTeacher && /^\d+$/.test(rawTeacher) ? Number(rawTeacher) : null;

  const teacherOptions = useMemo(
    () => (teachers.data || []).slice().sort((a, b) => a.name.localeCompare(b.name))
      .map((t) => ({ value: String(t.id), label: t.name })),
    [teachers.data],
  );

  const q = useUnfilledLessons({ page, page_size: pageSize, teacher_id: teacherId });
  const total = q.data?.total ?? 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
      <div style={{ maxWidth: 320 }}>
        <Field label="Преподаватель">
          <Combobox
            value={teacherId != null ? String(teacherId) : ''}
            onChange={(v) => { setExtra('teacher', v || null); setPage(1); }}
            options={teacherOptions}
            placeholder="Все преподаватели"
          />
        </Field>
      </div>

      {total === 0 && !q.isFetching ? (
        <div className="cal-empty">Все уроки заполнены 🎉</div>
      ) : (
        <FillTable
          rows={q.data?.rows || []}
          isLoading={q.isFetching}
          serverPagination={{
            page,
            pageSize,
            total,
            sortBy,
            sortDir,
            filters,
            onPageChange: setPage,
            onPageSizeChange: setPageSize,
            onSortChange: () => {},   // колонки не sortable — сортировка фиксирована на бэке
            onFiltersChange: () => {}, // фильтр по преподавателю — отдельным Combobox выше
          }}
        />
      )}
    </div>
  );
}
```

Примечание: проверить фактические сигнатуры `useListSearchParams` (возвращает `getExtra`/`setExtra`/`setPage` — как в `RegistryTab.tsx`) и `useTeachers` (принимает bool includeArchived — как в `AdminCalendarPage.tsx`). Класс `cal-empty` уже используется в `AdminCalendarPage`. `Combobox`/`Field` — из `components/form/`.

- [ ] **Step 2: Проверить типы**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: без ошибок.

- [ ] **Step 3: Коммит**

```bash
git add journal_django/frontend/admin-src/src/pages/dashboard/fill/FillTab.tsx
git commit -m "feat(admin-ui): FillTab — teacher filter + unfilled-lessons table"
```

---

## Task 8: Фронт — подключить вкладку в `DashboardPage`

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/dashboard/DashboardPage.tsx`

- [ ] **Step 1: Добавить третью вкладку**

Изменить `journal_django/frontend/admin-src/src/pages/dashboard/DashboardPage.tsx`:

1. Рядом с `RegistryTab` добавить ленивый импорт:
```tsx
const FillTab = lazy(() => import('./fill/FillTab'));
```

2. Расширить тип и парсинг таба:
```tsx
type Tab = 'finance' | 'registry' | 'fill';
```
```tsx
  const rawTab = sp.get('tab');
  const tab: Tab = rawTab === 'registry' ? 'registry' : rawTab === 'fill' ? 'fill' : 'finance';
```

3. В `setTab` логика удаления параметра для дефолта уже есть (`t === 'finance'` → delete); ветки `registry`/`fill` пишут `next.set('tab', t)` — существующий `else` это покрывает, менять не нужно.

4. Добавить третью кнопку-таб после кнопки «Реестр»:
```tsx
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'fill'}
          className={`dash-tab${tab === 'fill' ? ' dash-tab--active' : ''}`}
          onClick={() => setTab('fill')}
        >
          Заполнить
        </button>
```

5. Заменить финальный тернар рендера вкладок на явные ветки:
```tsx
      {tab === 'finance' && <FinanceView />}
      {tab === 'registry' && (
        <Suspense fallback={<PageLoading />}>
          <RegistryTab />
        </Suspense>
      )}
      {tab === 'fill' && (
        <Suspense fallback={<PageLoading />}>
          <FillTab />
        </Suspense>
      )}
```

- [ ] **Step 2: Проверить типы**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: без ошибок.

- [ ] **Step 3: Коммит**

```bash
git add journal_django/frontend/admin-src/src/pages/dashboard/DashboardPage.tsx
git commit -m "feat(admin-ui): add 'Заполнить' tab to dashboard"
```

---

## Task 9: Финальная проверка (бэкенд-тесты + ручной прогон в браузере)

**Files:** нет правок кода (только запуск/проверка; фиксы — точечные, если что-то всплывёт).

- [ ] **Step 1: Полный прогон бэкенд-тестов затронутых приложений**

Run: `cd journal_django && python -m pytest apps/dashboard apps/scheduling apps/extra_lessons -q`
Expected: все зелёные, новых падений нет.

- [ ] **Step 2: Убедиться, что фронт НЕ собирался (dist не тронут)**

Run: `git status --porcelain journal_django/frontend/admin-dist`
Expected: пусто (никаких изменений в `admin-dist/` — правило проекта: `npm run build` не запускаем, dist-артефакты не коммитим).

- [ ] **Step 3: Ручная проверка в браузере (dev)**

Запустить dev-стенд (nginx :8080 → runserver, Vite dev по проектной инструкции). Проверить под ролью manager/admin:
1. Дашборд → появилась третья вкладка «Заполнить»; `?tab=fill` в URL при переключении.
2. Таблица показывает просроченные незаполненные уроки, старые сверху; для доп.уроков — бейдж «Доп.».
3. Фильтр «Преподаватель» сужает список; при выборе — `teacher` в URL, страница сбрасывается на 1.
4. Клик по строке планового урока → `/admin/groups/:id?tab=lessons` (вкладка «Уроки», где урок заполняется). Клик по доп.уроку → `/admin/extra-lessons`.
5. Пагинация переключает страницы, фокус/скролл не скачут (`keepPreviousData`).
6. Под ролью teacher SPA admin недоступна (эндпоинт отдаёт 403 — уже покрыто тестом).

- [ ] **Step 4: Обновить память проекта**

Дописать в `MEMORY.md` пункт о реализованной вкладке «Заполнить» (эндпоинт `/api/admin/dashboard/unfilled-lessons`, источники: overdue `planned_lessons` + `absence_resolutions`, замена непроведённой спеки 2026-07-17 Часть 2). Отметить статус: реализовано, закоммичено, НЕ запушено/не задеплоено (если так).

- [ ] **Step 5: Финальный статус**

Сообщить пользователю: что сделано, результат прогона тестов (числа), что фронт проверен вручную, что осталось (пуш/деплой — только по явной просьбе).

---

## Self-Review (выполнено при написании плана)

- **Покрытие решений:** overdue-only (Task 1/2 DB-срез + Task 3 порог по времени) ✓; план+доп.уроки (Task 1+2, мёрж Task 3) ✓; плоская таблица + фильтр по преподавателю (Task 6/7) ✓; клик → заполнение (Task 6: план→`?tab=lessons`, доп→`/admin/extra-lessons`) ✓; вкладка Дашборда (Task 8) ✓; RBAC IsManagerOrAdmin (Task 4) ✓; серверная пагинация + keepPreviousData (Task 4/5/7) ✓.
- **Заглушки:** нет — весь код и команды приведены полностью.
- **Согласованность имён/типов:** `unfilled_planned_lessons(today, teacher_id)` → отдаёт `id/group_pk/group_name/direction_name/direction_color/lesson_number/teacher_id/substitute_teacher_id/scheduled_date/scheduled_time`; `unfilled_extra_lessons(today, teacher_id)` → `id/group_id/group_name/assigned_teacher_id/scheduled_date/scheduled_time`; `fill_service.unfilled_lessons(teacher_id, now)` мёржит их в единую форму `UnfilledLesson` (kind/id/group_id/group_name/teacher_name/direction_name/direction_color/lesson_number/date/time), совпадающую с TS-типом (Task 5) и колонками таблицы (Task 6). Эндпоинт-путь `/api/admin/dashboard/unfilled-lessons` одинаков в Task 4 и Task 5.
- **Проверки перед реализацией (отметить исполнителю):** фактические сигнатуры `useListSearchParams`, `useTeachers`, экспорт `Paginated` из `shared-types`, `MSK`/`msk_now` в `apps/core/utils/dates` — все помечены примечаниями «убедиться, что…» в соответствующих задачах.
