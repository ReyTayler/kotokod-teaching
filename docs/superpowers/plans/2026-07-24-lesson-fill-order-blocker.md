# Блокер отметки урока при незакрытых предыдущих занятиях — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Преподаватель не может отметить урок группы, пока у неё есть незакрытые занятия, которые должны были состояться раньше отмечаемого.

**Architecture:** Один чистый запрос-счётчик в `apps/scheduling/repository.py` (владелец `planned_lessons`) + гард в `apps/teacher_spa/services.py::submit_lesson` до любых записей. Ядро `apps/lessons/services.py::record_lesson` НЕ трогаем — именно поэтому admin SPA остаётся escape hatch. Фронт не меняется: отказ приходит в существующем контракте `{'success': False, 'error': ...}` и показывается в `LessonForm` через `submitError`.

**Tech Stack:** Django 5 ORM (managed=False модели), DRF, pytest + pytest-django, PostgreSQL.

**Спека:** `docs/superpowers/specs/2026-07-24-lesson-fill-order-blocker-design.md`

## Правила этого репозитория (обязательно к прочтению перед стартом)

- **Не коммитить и не пушить без явной просьбы владельца** (`CLAUDE.md`). Шаги «Коммит» ниже выполнять ТОЛЬКО если он попросил; иначе оставлять изменения в рабочем дереве и переходить к следующей задаче. Рабочее дерево содержит чужой WIP — `git add -A` запрещён, только точечный `git add <файл>`.
- **Не запускать `npm run build`** и не трогать `frontend/*-dist/` — эта задача фронта не касается вообще.
- **Не запускать `recreate_test_db.*`** — тестовые БД общие для всех worktree.
- **Прогон тестов — целиком** (`pytest -q` из `journal_django/`): приложения по-разному настраивают `django_db_setup` (часть работает с общей `journal_test`, часть — со свежей `test_journal_test`), поэтому частичный прогон даёт ложную картину. Точечный запуск одного теста допустим ТОЛЬКО внутри TDD-цикла; итоговая проверка — полный прогон.
- Команды запускать из `c:\Users\ilyap\TestKOTOKOD\journal_django` интерпретатором `.venv\Scripts\python.exe` (venv лежит внутри `journal_django/`).

## File Structure

| Файл | Что делает | Действие |
|---|---|---|
| `journal_django/apps/scheduling/repository.py` | доступ к `planned_lessons`; сюда добавляется `count_unfilled_before` | Modify (~после `unfilled_planned_lessons`, строка ~173) |
| `journal_django/apps/teacher_spa/services.py` | `submit_lesson` — резолв + вызов ядра; сюда добавляется гард и константа текста | Modify (константа — шапка модуля; гард — после резолва `ids`, строка ~159) |
| `journal_django/apps/scheduling/tests/test_unfilled_before.py` | юнит-тесты счётчика | Create |
| `journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py` | e2e-тесты блокера в `TestSubmitLesson` | Modify (конец класса, перед `test_transaction_rollback_on_payroll_failure`) |
| `journal_django/apps/lessons/tests/test_lessons_api.py` | регресс-гард: admin-путь НЕ блокируется | Modify (конец файла) |

---

### Task 1: Счётчик долгов `count_unfilled_before`

**Files:**
- Create: `journal_django/apps/scheduling/tests/test_unfilled_before.py`
- Modify: `journal_django/apps/scheduling/repository.py`

Фикстура `group_with_group` уже есть в `journal_django/apps/scheduling/tests/conftest.py`: она отдаёт `(gid, tid)` и создаёт 4 pending-строки плана на 07/14/21/28 июля 2026, время 18:00, `seq`/`lesson_number` = 1..4.

«Сейчас» подменяем monkeypatch'ем `apps.scheduling.repository.msk_now` — иначе тесты зависят от реального времени запуска и будут мигать.

- [ ] **Step 1: Написать падающие тесты**

Создать `journal_django/apps/scheduling/tests/test_unfilled_before.py`:

```python
"""
count_unfilled_before — счётчик незакрытых занятий группы, которые должны были
состояться РАНЬШЕ отмечаемого урока (блокер отметки в teacher SPA).

Фикстура group_with_group: 4 pending-строки на 07/14/21/28 июля 2026, 18:00.
«Сейчас» подменяется monkeypatch'ем msk_now — без этого тесты зависят от
реального времени запуска.
"""
from __future__ import annotations

import datetime

import pytest
from django.db import connection

from apps.core.utils.dates import MSK
from apps.scheduling import repository

pytestmark = pytest.mark.django_db


def _freeze(monkeypatch, moment: datetime.datetime) -> None:
    monkeypatch.setattr(repository, 'msk_now', lambda: moment.replace(tzinfo=MSK))


def test_no_plan_returns_zero(monkeypatch, group_with_group):
    """Группа без плановых строк на дату — долгов нет."""
    gid, _ = group_with_group
    _freeze(monkeypatch, datetime.datetime(2026, 7, 7, 20, 0))
    with connection.cursor() as cur:
        cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [gid])
    assert repository.count_unfilled_before(gid, '2026-07-07') == 0


def test_single_happened_lesson_is_not_a_debt(monkeypatch, group_with_group):
    """Единственное наступившее занятие — это и есть отмечаемое, не долг."""
    gid, _ = group_with_group
    _freeze(monkeypatch, datetime.datetime(2026, 7, 7, 20, 0))
    assert repository.count_unfilled_before(gid, '2026-07-07') == 0


def test_two_unfilled_lessons_give_one_debt(monkeypatch, group_with_group):
    """07.07 не отмечено, отмечают 14.07 → один долг."""
    gid, _ = group_with_group
    _freeze(monkeypatch, datetime.datetime(2026, 7, 14, 20, 0))
    assert repository.count_unfilled_before(gid, '2026-07-14') == 1


def test_three_unfilled_lessons_give_two_debts(monkeypatch, group_with_group):
    """07.07 и 14.07 не отмечены, отмечают 21.07 → два долга."""
    gid, _ = group_with_group
    _freeze(monkeypatch, datetime.datetime(2026, 7, 21, 20, 0))
    assert repository.count_unfilled_before(gid, '2026-07-21') == 2


def test_future_rows_are_ignored(monkeypatch, group_with_group):
    """Строки позже отмечаемой даты в счёт не идут."""
    gid, _ = group_with_group
    _freeze(monkeypatch, datetime.datetime(2026, 7, 28, 20, 0))
    assert repository.count_unfilled_before(gid, '2026-07-07') == 0


def test_lesson_later_today_is_not_a_debt(monkeypatch, group_with_group):
    """Занятие того же дня, время которого ещё НЕ наступило, долгом не считается."""
    gid, tid = group_with_group
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
            'scheduled_time, teacher_id, status, created_at, updated_at) '
            "VALUES (%s, 5, 5, '2026-07-07', '20:00', %s, 'pending', NOW(), NOW())",
            [gid, tid],
        )
    # 19:00: строка 18:00 наступила (её и отмечают), строка 20:00 — ещё нет.
    _freeze(monkeypatch, datetime.datetime(2026, 7, 7, 19, 0))
    assert repository.count_unfilled_before(gid, '2026-07-07') == 0


def test_earlier_lesson_same_day_is_a_debt(monkeypatch, group_with_group):
    """Мультислот: утреннее занятие не отмечено, отмечают вечернее → долг."""
    gid, tid = group_with_group
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
            'scheduled_time, teacher_id, status, created_at, updated_at) '
            "VALUES (%s, 5, 5, '2026-07-07', '10:00', %s, 'pending', NOW(), NOW())",
            [gid, tid],
        )
    _freeze(monkeypatch, datetime.datetime(2026, 7, 7, 20, 0))
    assert repository.count_unfilled_before(gid, '2026-07-07') == 1


def test_done_and_cancelled_rows_are_not_debts(monkeypatch, group_with_group):
    """status done/cancelled долгом не считается."""
    gid, _ = group_with_group
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE planned_lessons SET status = 'done' "
            "WHERE group_id = %s AND scheduled_date = '2026-07-07'",
            [gid],
        )
        cur.execute(
            "UPDATE planned_lessons SET status = 'cancelled' "
            "WHERE group_id = %s AND scheduled_date = '2026-07-14'",
            [gid],
        )
    _freeze(monkeypatch, datetime.datetime(2026, 7, 21, 20, 0))
    assert repository.count_unfilled_before(gid, '2026-07-21') == 0


def test_row_with_linked_fact_is_not_a_debt(monkeypatch, group_with_group):
    """Строка со status='pending', но с привязанным фактом — не долг: урок за неё
    уже записан, статус просто не переставлен."""
    gid, tid = group_with_group
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, '
            'lesson_duration_minutes, lesson_type, submitted_at, submitted_by_token) '
            "VALUES (%s, %s, '2026-07-07', 1, 60, 'regular', NOW(), 'test-unfilled') "
            'RETURNING id',
            [gid, tid],
        )
        fact_id = cur.fetchone()[0]
        cur.execute(
            'UPDATE planned_lessons SET fact_lesson_id = %s '
            "WHERE group_id = %s AND scheduled_date = '2026-07-07'",
            [fact_id, gid],
        )
    _freeze(monkeypatch, datetime.datetime(2026, 7, 14, 20, 0))
    assert repository.count_unfilled_before(gid, '2026-07-14') == 0


def test_non_course_rows_are_ignored(monkeypatch, group_with_group):
    """Строка без seq (маркер отмены/разовое занятие) долгом не считается."""
    gid, tid = group_with_group
    with connection.cursor() as cur:
        cur.execute(
            'DELETE FROM planned_lessons WHERE group_id = %s AND '
            "scheduled_date IN ('2026-07-14','2026-07-21','2026-07-28')",
            [gid],
        )
        cur.execute(
            'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
            'scheduled_time, teacher_id, status, created_at, updated_at) '
            "VALUES (%s, NULL, NULL, '2026-07-01', '18:00', %s, 'pending', NOW(), NOW())",
            [gid, tid],
        )
    _freeze(monkeypatch, datetime.datetime(2026, 7, 7, 20, 0))
    assert repository.count_unfilled_before(gid, '2026-07-07') == 0


def test_other_group_rows_are_ignored(monkeypatch, group_with_group, sched_setup):
    """Долги считаются в пределах группы: чужие строки не влияют."""
    gid, _ = group_with_group
    other_gid = sched_setup['group_a']
    _freeze(monkeypatch, datetime.datetime(2026, 7, 7, 20, 0))
    assert repository.count_unfilled_before(other_gid, '2026-07-07') == 0
```

- [ ] **Step 2: Убедиться, что тесты падают**

Выполнить из `journal_django/`:

```
.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_unfilled_before.py -q
```

Ожидается: все тесты падают с `AttributeError: module 'apps.scheduling.repository' has no attribute 'count_unfilled_before'`.

- [ ] **Step 3: Реализовать счётчик**

В `journal_django/apps/scheduling/repository.py` добавить импорт `MSK` в существующую строку импорта дат:

```python
from apps.core.utils.dates import MSK, msk_now, msk_today
```

и вставить функцию сразу после `unfilled_planned_lessons` (перед `groups_without_plan`):

```python
def count_unfilled_before(group_id: int, lesson_date) -> int:
    """
    Сколько незакрытых курсовых занятий группы должны были состояться РАНЬШЕ того,
    которое отмечается на дату lesson_date. 0 → отметку можно записывать.

    Отмечаемым считается САМОЕ ПОЗДНЕЕ наступившее незакрытое занятие с датой
    <= lesson_date: именно его привяжет к факту `link_facts` (матчинг по
    lesson_number идёт по возрастанию seq). Оно из счёта исключается — долг это
    всё, что осталось РАНЬШЕ него.

    «Наступило» = datetime(scheduled_date, scheduled_time, МСК) <= сейчас, как в
    `services._planned_status` (overdue считается на чтении). Занятие сегодня
    позже по времени долгом не считается — оно ещё впереди. scheduled_time NULL
    трактуется как 00:00.

    Учитываются только курсовые строки (seq не NULL): маркеры отмены и разовые
    занятия к последовательности курса не относятся. Один запрос; сортировка в
    Python — строк на группу десятки.
    """
    rows = (
        PlannedLesson.objects
        .filter(
            group_id=group_id,
            seq__isnull=False,
            status=PENDING,
            fact_lesson__isnull=True,
            scheduled_date__lte=lesson_date,
        )
        .values_list('scheduled_date', 'scheduled_time')
    )
    now = msk_now()
    midnight = datetime.time(0, 0)
    happened = [
        (d, t or midnight)
        for d, t in rows
        if now >= datetime.datetime.combine(d, t or midnight, tzinfo=MSK)
    ]
    return max(0, len(happened) - 1)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

```
.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_unfilled_before.py -q
```

Ожидается: 11 passed.

- [ ] **Step 5: Коммит (только по явной просьбе владельца)**

```bash
git add journal_django/apps/scheduling/repository.py journal_django/apps/scheduling/tests/test_unfilled_before.py
git commit -m "feat(scheduling): count_unfilled_before — счётчик незакрытых занятий группы"
```

---

### Task 2: Гард в `submit_lesson`

**Files:**
- Modify: `journal_django/apps/teacher_spa/services.py`
- Test: `journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py`

Тесты кладутся в конец класса `TestSubmitLesson` (перед `test_transaction_rollback_on_payroll_failure`, строка ~642). Паттерн вставки/очистки плановых строк копируется из соседнего `test_submit_lesson_links_fact_to_planned_lesson`. Хелперы `_cleanup_lesson` / `_get_lesson_id` уже есть в модуле.

Дата урока в этих тестах — `2026-06-10` (она в прошлом, как в остальных тестах класса), долг ставится на `2026-06-03`.

- [ ] **Step 1: Написать падающие тесты**

Добавить в класс `TestSubmitLesson`:

```python
    def test_blocked_when_earlier_lesson_unfilled(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Незакрытое занятие прошлой недели → отказ, урок не создаётся."""
        teacher_id, _ = teacher_fixture
        token = f'acct:{account_fixture}'
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-03', '10:00', %s, 'pending', NOW(), NOW()), "
                "       (%s, 2, 2, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW())",
                [group_fixture, teacher_id, group_fixture, teacher_id],
            )
        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body['success'] is False
            assert body['error'] == (
                'Есть не отмеченные занятия. Обратитесь к менеджеру или '
                'администратору за правкой расписания.'
            )
            assert _get_lesson_id(group_fixture, token) is None
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group_fixture])

    def test_not_blocked_when_earlier_lesson_cancelled(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Отменённое занятие долгом не считается — урок записывается."""
        teacher_id, _ = teacher_fixture
        token = f'acct:{account_fixture}'
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-03', '10:00', %s, 'cancelled', NOW(), NOW()), "
                "       (%s, 2, 2, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW())",
                [group_fixture, teacher_id, group_fixture, teacher_id],
            )
        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.json()['success'] is True
            lesson_id = _get_lesson_id(group_fixture, token)
            assert lesson_id is not None
            _cleanup_lesson(lesson_id)
            with connection.cursor() as cur:
                cur.execute(
                    'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                    [membership_fixture],
                )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group_fixture])

    def test_not_blocked_when_earlier_lesson_done(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Проведённое занятие долгом не считается — урок записывается."""
        teacher_id, _ = teacher_fixture
        token = f'acct:{account_fixture}'
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-03', '10:00', %s, 'done', NOW(), NOW()), "
                "       (%s, 2, 2, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW())",
                [group_fixture, teacher_id, group_fixture, teacher_id],
            )
        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.json()['success'] is True
            lesson_id = _get_lesson_id(group_fixture, token)
            assert lesson_id is not None
            _cleanup_lesson(lesson_id)
            with connection.cursor() as cur:
                cur.execute(
                    'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                    [membership_fixture],
                )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group_fixture])

    def test_not_blocked_by_non_course_row(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Строка без seq (маркер/разовое занятие) блокером не является."""
        teacher_id, _ = teacher_fixture
        token = f'acct:{account_fixture}'
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, NULL, NULL, '2026-06-03', '10:00', %s, 'pending', NOW(), NOW()), "
                "       (%s, 1, 1, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW())",
                [group_fixture, teacher_id, group_fixture, teacher_id],
            )
        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.json()['success'] is True
            lesson_id = _get_lesson_id(group_fixture, token)
            assert lesson_id is not None
            _cleanup_lesson(lesson_id)
            with connection.cursor() as cur:
                cur.execute(
                    'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                    [membership_fixture],
                )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group_fixture])

    def test_not_blocked_by_later_unfilled_lesson(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Незакрытое занятие ПОЗЖЕ отмечаемой даты не мешает ретро-отметке."""
        teacher_id, _ = teacher_fixture
        token = f'acct:{account_fixture}'
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW()), "
                "       (%s, 2, 2, '2026-06-17', '10:00', %s, 'pending', NOW(), NOW())",
                [group_fixture, teacher_id, group_fixture, teacher_id],
            )
        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.json()['success'] is True
            lesson_id = _get_lesson_id(group_fixture, token)
            assert lesson_id is not None
            _cleanup_lesson(lesson_id)
            with connection.cursor() as cur:
                cur.execute(
                    'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                    [membership_fixture],
                )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group_fixture])
```

- [ ] **Step 2: Убедиться, что первый тест падает, остальные проходят**

```
.venv\Scripts\python.exe -m pytest "apps/teacher_spa/tests/test_teacher_spa_api.py::TestSubmitLesson" -q
```

Ожидается: `test_blocked_when_earlier_lesson_unfilled` FAILED (`assert True is False` — урок записался, гарда ещё нет), остальные новые тесты PASSED.

- [ ] **Step 3: Реализовать гард**

В `journal_django/apps/teacher_spa/services.py` добавить импорт после `from apps.lessons.services import record_lesson`:

```python
from apps.scheduling import repository as scheduling_repository
```

и константу после блока импортов (перед `def get_current_teacher`):

```python
# Отказ при незакрытых предыдущих занятиях группы. Закрыть дыру задним числом
# может админ/менеджер через admin SPA — там гарда нет намеренно (escape hatch).
UNFILLED_LESSONS_BLOCKED = (
    'Есть не отмеченные занятия. Обратитесь к менеджеру или '
    'администратору за правкой расписания.'
)
```

В `submit_lesson` вставить гард сразу после вычисления `original_teacher_id` (строка ~159), ДО расчёта номера урока:

```python
    # Блокер порядка заполнения: пока у группы есть незакрытые занятия, которые
    # должны были состояться раньше отмечаемого, писать урок нельзя. Иначе факт
    # съедает чужую плановую строку (link_facts матчит по номеру, а номер берётся
    # из прогресса учеников) — план и факт разъезжаются, а день, который
    # преподаватель только что отметил, остаётся «Надо заполнить».
    if scheduling_repository.count_unfilled_before(ids['group_id'], date) > 0:
        return {'success': False, 'error': UNFILLED_LESSONS_BLOCKED}
```

- [ ] **Step 4: Убедиться, что весь класс зелёный**

```
.venv\Scripts\python.exe -m pytest "apps/teacher_spa/tests/test_teacher_spa_api.py::TestSubmitLesson" -q
```

Ожидается: все тесты класса PASSED. Особое внимание к трём старым тестам, которые создают плановые строки (`test_submit_lesson_links_fact_to_planned_lesson`, `test_substitution_derived_from_assigned_planned_lesson`, `test_reschedule_derived_from_moved_planned_lesson`) — у них ровно одна наступившая незакрытая строка, то есть долгов ноль, и они обязаны остаться зелёными. Если какой-то из них покраснел — это баг в счётчике, а не в тесте.

- [ ] **Step 5: Коммит (только по явной просьбе владельца)**

```bash
git add journal_django/apps/teacher_spa/services.py journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py
git commit -m "feat(teacher-spa): блокер отметки урока при незакрытых предыдущих занятиях"
```

---

### Task 3: Замена блокируется, admin — нет

**Files:**
- Test: `journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py`
- Test: `journal_django/apps/lessons/tests/test_lessons_api.py`

Две границы правила из спеки, каждая — отдельный регресс-гард. Код при этом не меняется: обе поведенческие ветки уже следуют из Task 2 (замена идёт тем же путём `submit_lesson`; admin идёт мимо него, через `create_lesson_full`). Тесты фиксируют это намеренно, чтобы позже никто не «унифицировал» гард в ядро.

Паттерн подмены копируется из `test_substitution_derived_from_assigned_planned_lesson` (строка ~448): группа принадлежит другому преподавателю, а отправителю назначено плановое занятие на эту дату.

- [ ] **Step 1: Тест «замена тоже блокируется»**

Добавить в класс `TestSubmitLesson`, взяв за основу существующий `test_substitution_derived_from_assigned_planned_lesson` — прочитать его целиком и повторить его схему фикстур (создание второго преподавателя-владельца группы и назначение планового занятия отправителю), добавив к ней ещё одну незакрытую строку неделей раньше:

```python
    def test_substitute_teacher_is_blocked_too(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Подменяющий преподаватель блокируется так же: долг группы важнее того,
        кто именно отмечает. Закрыть чужой долг он не вправе — текст отправляет
        его к менеджеру."""
        teacher_id, _ = teacher_fixture
        token = f'acct:{account_fixture}'
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO teachers (name, active) VALUES ('__spa_owner__', true) RETURNING id",
            )
            owner_id = cur.fetchone()[0]
            cur.execute(
                'UPDATE groups SET teacher_id = %s WHERE id = %s',
                [owner_id, group_fixture],
            )
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-03', '10:00', %s, 'pending', NOW(), NOW()), "
                "       (%s, 2, 2, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW())",
                [group_fixture, owner_id, group_fixture, teacher_id],
            )
        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body['success'] is False
            assert body['error'] == (
                'Есть не отмеченные занятия. Обратитесь к менеджеру или '
                'администратору за правкой расписания.'
            )
            assert _get_lesson_id(group_fixture, token) is None
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group_fixture])
                cur.execute(
                    'UPDATE groups SET teacher_id = %s WHERE id = %s',
                    [teacher_id, group_fixture],
                )
                cur.execute('DELETE FROM teachers WHERE id = %s', [owner_id])
```

- [ ] **Step 2: Запустить тест замены**

```
.venv\Scripts\python.exe -m pytest "apps/teacher_spa/tests/test_teacher_spa_api.py::TestSubmitLesson::test_substitute_teacher_is_blocked_too" -q
```

Ожидается: PASSED. Если тест падает с `success is True`, сверить схему фикстур с `test_substitution_derived_from_assigned_planned_lesson`: право отметить чужую группу даёт только плановая строка на эту дату с `teacher_id` отправителя.

- [ ] **Step 3: Тест «admin-путь не блокируется»**

Добавить в конец `journal_django/apps/lessons/tests/test_lessons_api.py`. Фикстуры, клиент (`_client('admin')`), `BASE_URL` и уборщик `_delete_lesson` в этом модуле уже есть — тест построен по образцу `test_post_creates_lesson` (строка 160). `connection` в модуле импортирован.

```python
def test_post_not_blocked_by_unfilled_plan(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture,
):
    """Admin SPA — escape hatch: ручное создание урока НЕ блокируется незакрытыми
    занятиями группы, иначе разблокировать группу будет некому. Гард живёт в
    teacher_spa.submit_lesson, а не в ядре record_lesson — этот тест страхует от
    переноса гарда в ядро."""
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
            'scheduled_time, teacher_id, status, created_at, updated_at) '
            "VALUES (%s, 1, 1, '2026-03-14', '10:00', %s, 'pending', NOW(), NOW())",
            [group_fixture, teacher_id_fixture],
        )
    payload = {
        'lesson_date': '2026-03-21',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    }
    try:
        resp = _client('admin').post(BASE_URL, payload, format='json')
        assert resp.status_code == 201
        _delete_lesson(resp.json()['id'])
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group_fixture])
```

- [ ] **Step 4: Запустить admin-тест**

```
.venv\Scripts\python.exe -m pytest apps/lessons/tests/test_lessons_api.py -q
```

Ожидается: все тесты файла PASSED, включая новый.

- [ ] **Step 5: Коммит (только по явной просьбе владельца)**

```bash
git add journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py journal_django/apps/lessons/tests/test_lessons_api.py
git commit -m "test: границы блокера — замена блокируется, admin остаётся escape hatch"
```

---

### Task 4: Полный прогон и проверка на живой БД

**Files:** изменений нет — только верификация.

- [ ] **Step 1: Полный прогон тестов**

```
.venv\Scripts\python.exe -m pytest -q
```

Ожидается: 0 failed. Частичный прогон не считается проверкой — приложения по-разному настраивают `django_db_setup`.

- [ ] **Step 2: Проверить счётчик на реальных данных dev-БД**

```
set PYTHONIOENCODING=utf-8 && set DJANGO_SETTINGS_MODULE=config.settings.development && .venv\Scripts\python.exe -c "import django; django.setup(); from apps.scheduling.repository import count_unfilled_before; from apps.core.utils.dates import msk_today; print([(g, count_unfilled_before(g, msk_today())) for g in (16, 105, 110)])"
```

Ожидается: числа, а не исключение. Для групп с длинным незаполненным хвостом (16, 105) счётчик заведомо > 0 — это и есть ожидаемое поведение блокера до ручной расчистки хвоста.

- [ ] **Step 3: Отчитаться владельцу**

Сообщить: что реализовано, результат полного прогона (числом), какие группы блокируются на текущих данных, и напомнить, что изменения не закоммичены (если явной просьбы коммитить не было).

---

## Замечания для исполнителя

- **Не переносить гард в `record_lesson`.** Это выглядит как «унификация», но ломает escape hatch: админ не сможет закрыть дыру, и группа останется заблокированной навсегда. Task 3 Step 3 специально это страхует.
- **Не добавлять порогов и окон.** Владелец сознательно отказался от амнистии исторического хвоста (542 незакрытые строки в dev-БД) — он разгребает его вручную.
- **Фронт не трогать.** Отказ показывается существующим механизмом `submitError` в `LessonForm`; правок в `frontend/teacher-src` эта задача не содержит, сборка фронта не запускается.
- Новых моделей, URL и миграций нет → `apps/changelog/registry.py` и `labels.py` не трогаются.
