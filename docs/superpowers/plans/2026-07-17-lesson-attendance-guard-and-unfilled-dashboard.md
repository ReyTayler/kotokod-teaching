# Блокировка урока без учеников + виджет «Незаполненные уроки» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Запретить сохранение урока для группы без единого ученика (backend
единое ядро + teacher SPA + admin SPA), и добавить в admin-дашборд новую
вкладку со списком просроченных незаполненных уроков всей школы.

**Architecture:** Backend-правило живёт в одном месте — `apps.lessons.services
.record_lesson` (единое ядро teacher SPA + admin SPA), фронтовые точки входа
дублируют проверку только для мгновенного UX-фидбека. Виджет дашборда — новый
school-wide read в `apps.scheduling` (по образцу уже существующего
`occurrences_on_date`), тонкая вьюха в `apps.dashboard`, новая вкладка admin
SPA переиспользует существующий `DataTable`.

**Tech Stack:** Django 5 + DRF, pytest + `pytest-django` (реальная `journal_test`
БД, `managed=False`), React 19 + TanStack Query v5 (admin SPA), plain
TypeScript + React без стейт-менеджера (teacher SPA).

Спека: `docs/superpowers/specs/2026-07-17-lesson-attendance-guard-and-unfilled-dashboard-design.md`

Все команды `pytest`/`npm` выполняются из каталога `journal_django/` (бэкенд)
и `journal_django/frontend/admin-src/` или `.../teacher-src/` (фронт)
соответственно.

---

## Task 1: Backend — исключение `EmptyAttendanceBlocked` + guard в `record_lesson`

**Files:**
- Modify: `journal_django/apps/lessons/exceptions.py`
- Modify: `journal_django/apps/lessons/services.py:28-108` (`record_lesson`)
- Test: `journal_django/apps/lessons/tests/test_lessons_repository.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `journal_django/apps/lessons/tests/test_lessons_repository.py`
(после существующих `test_create_lesson_*`, рядом с секцией create):

```python
def test_create_lesson_blocked_when_attendance_empty(group_fixture, teacher_id_fixture):
    """attendance=[] (группа без учеников) → EmptyAttendanceBlocked, ничего не создаётся."""
    from apps.lessons.exceptions import EmptyAttendanceBlocked

    with pytest.raises(EmptyAttendanceBlocked):
        services.create_lesson_full({
            'lesson_date': '2026-03-05',
            'group_id': group_fixture,
            'teacher_id': teacher_id_fixture,
            'lesson_number': 1,
            'lesson_duration_minutes': 60,
            'attendance': [],
        })
    with connection.cursor() as cur:
        cur.execute(
            'SELECT COUNT(*) FROM lessons WHERE group_id = %s AND lesson_date = %s',
            [group_fixture, '2026-03-05'],
        )
        assert cur.fetchone()[0] == 0


def test_create_lesson_allowed_when_all_absent(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done,
):
    """attendance непустой, но present=False у единственного ученика — НЕ блокируется
    (легитимный кейс фиксации отсутствия, см. spec «Семантика правила»)."""
    result = services.create_lesson_full({
        'lesson_date': '2026-03-06',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    lesson_id = result['lesson_id']
    try:
        assert lessons_done(group_fixture, student_fixture) == 0
    finally:
        _delete_lesson(lesson_id)
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `pytest apps/lessons/tests/test_lessons_repository.py -k "empty_or_all_absent or attendance_empty or all_absent" -v`
Expected: `test_create_lesson_blocked_when_attendance_empty` FAILS с
`ImportError: cannot import name 'EmptyAttendanceBlocked'` (класса ещё нет);
`test_create_lesson_allowed_when_all_absent` должен пройти уже сейчас (текущее
поведение это разрешает) — если он тоже падает, разобраться перед тем как
продолжать.

- [ ] **Step 3: Добавить исключение**

В `journal_django/apps/lessons/exceptions.py`, после класса
`UnpaidAttendanceBlocked`:

```python


class EmptyAttendanceBlocked(Exception):
    """
    Попытка записать урок для группы без единого ученика (attendance=[]).

    НЕ бросается, если attendance непустой, но все present=False — фиксация
    отсутствия (весь урок прошёл без явившихся учеников) легитимна и не
    блокируется (см. apps.teacher_spa.tests.test_teacher_spa_api::
    test_absent_student_not_incremented).
    """

    def __init__(self) -> None:
        super().__init__('Нельзя записать урок без учеников.')
```

- [ ] **Step 4: Добавить guard в `record_lesson`**

В `journal_django/apps/lessons/services.py`, изменить импорт (строка 19) и
начало функции `record_lesson` (строки 62-64):

```python
from apps.lessons import repository
from apps.lessons.exceptions import EmptyAttendanceBlocked
from apps.payroll.calculator import calculate_payment, calculate_penalty
```

```python
    Бросает EmptyAttendanceBlocked, если attendance пуст (группа без учеников).
    Бросает UnpaidAttendanceBlocked (apps.lessons.exceptions), если у кого-то
    из present-учеников остаток оплаченных уроков <= 0 — ДО открытия транзакции,
    ничего не пишется.

    Возвращает {'lesson_id': int, 'payment': int, 'penalty': int}.
    """
    if not attendance:
        raise EmptyAttendanceBlocked()
    present_student_ids = [a['student_id'] for a in attendance if a['present']]
    repository.assert_students_paid(present_student_ids)
```

(Первая строка докстроки про `EmptyAttendanceBlocked` добавляется перед уже
существующей строкой про `UnpaidAttendanceBlocked`; сам код — `if not
attendance: raise EmptyAttendanceBlocked()` вставляется ПЕРЕД существующей
строкой `present_student_ids = [...]`, остальное без изменений.)

- [ ] **Step 5: Запустить тесты, убедиться что проходят**

Run: `pytest apps/lessons/tests/test_lessons_repository.py -v`
Expected: PASS (весь файл, включая два новых теста и все существующие).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/lessons/exceptions.py journal_django/apps/lessons/services.py journal_django/apps/lessons/tests/test_lessons_repository.py
git commit -m "feat(lessons): block record_lesson when attendance is empty"
```

---

## Task 2: Backend — admin API ловит `EmptyAttendanceBlocked`

**Files:**
- Modify: `journal_django/apps/lessons/views.py:22-37,128-141`
- Test: `journal_django/apps/lessons/tests/test_lessons_api.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `journal_django/apps/lessons/tests/test_lessons_api.py`, после
`test_post_blocked_when_student_has_no_paid_balance`:

```python
def test_post_blocked_when_attendance_empty(group_fixture, teacher_id_fixture):
    """attendance: [] → 400 {'error': ...}, урок не создаётся (EmptyAttendanceBlocked → view)."""
    payload = {
        'lesson_date': '2026-03-29',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [],
    }
    resp = _client('admin').post(BASE_URL, payload, format='json')
    assert resp.status_code == 400
    assert 'error' in resp.json()
    with connection.cursor() as cur:
        cur.execute(
            'SELECT COUNT(*) FROM lessons WHERE group_id = %s AND lesson_date = %s',
            [group_fixture, '2026-03-29'],
        )
        assert cur.fetchone()[0] == 0
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `pytest apps/lessons/tests/test_lessons_api.py -k test_post_blocked_when_attendance_empty -v`
Expected: FAIL — сейчас `attendance: []` создаёт урок (201), а не 400.

- [ ] **Step 3: Поймать исключение во view**

В `journal_django/apps/lessons/views.py`, изменить импорт (строка 32) и
`post` метод `LessonListCreateView` (строки 128-141):

```python
from apps.lessons.exceptions import EmptyAttendanceBlocked, UnpaidAttendanceBlocked
```

```python
    def post(self, request: Request) -> Response:
        serializer = LessonCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = services.create_lesson_full(serializer.validated_data)
        except (UnpaidAttendanceBlocked, EmptyAttendanceBlocked) as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        full = services.get_lesson_full(result['lesson_id'])
        return Response(
            _strip_payroll_for_role(full, request.user.role),
            status=status.HTTP_201_CREATED,
        )
```

- [ ] **Step 4: Запустить тест, убедиться что проходит**

Run: `pytest apps/lessons/tests/test_lessons_api.py -v`
Expected: PASS (весь файл).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/lessons/views.py journal_django/apps/lessons/tests/test_lessons_api.py
git commit -m "feat(lessons): return 400 when admin POST lesson has empty attendance"
```

---

## Task 3: Backend — teacher SPA ловит `EmptyAttendanceBlocked`

**Files:**
- Modify: `journal_django/apps/teacher_spa/services.py:14-17,198-216`
- Test: `journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py`

- [ ] **Step 1: Написать падающий тест**

Добавить метод в класс `TestSubmitLesson` файла
`journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py` (после
`test_absent_allowed_without_paid_balance`). `group_fixture` обязателен здесь:
без него группа `'__spa_test_group__ пн 10:00'` не существует в БД и
`submit_lesson` вернёт `'Группа не найдена'` раньше, чем дойдёт до
`record_lesson` — тест проверял бы не то, что нужно.

```python
    def test_group_without_students_blocked(
        self, teacher_fixture, account_fixture, group_fixture,
    ):
        """Группа существует (group_fixture), но её students в payload = [] →
        success:false, урок не создаётся (EmptyAttendanceBlocked)."""
        resp = self._submit(account_fixture, {
            'group': '__spa_test_group__ пн 10:00',
            'date': '2026-06-10',
            'students': [],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['success'] is False
        assert 'учеников' in body['error']
        assert _get_lesson_id(group_fixture, f'acct:{account_fixture}') is None
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `pytest apps/teacher_spa/tests/test_teacher_spa_api.py -k test_group_without_students_blocked -v`
Expected: FAIL — `students: []` резолвится в `attendance: []` (никого не
резолвить по имени просто нечего), `record_lesson` сейчас создаёт урок с
`total_students=0`, `body['success']` окажется `True`, а не `False`.

- [ ] **Step 3: Поймать исключение в `submit_lesson`**

В `journal_django/apps/teacher_spa/services.py`, изменить импорт (строка 16) и
блок try/except записи (строки 201-216):

```python
from apps.lessons.exceptions import EmptyAttendanceBlocked, UnpaidAttendanceBlocked
```

```python
    try:
        result = record_lesson(
            lesson_date=date,
            teacher_id=lesson_teacher_id,
            group_id=ids['group_id'],
            original_teacher_id=original_teacher_id,
            lesson_number=lesson_num,
            lesson_duration_minutes=ids['lesson_duration_minutes'],
            lesson_type=sub_label,
            record_url=record_url,
            submitted_by_token=f'acct:{account_id}',
            submit_date=format_msk_date(),
            attendance=attendance,
        )
    except (UnpaidAttendanceBlocked, EmptyAttendanceBlocked) as e:
        return {'success': False, 'error': str(e)}
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `pytest apps/teacher_spa/tests/test_teacher_spa_api.py -v`
Expected: PASS (весь файл — включая `test_absent_student_not_incremented` и
`test_absent_allowed_without_paid_balance`, которые должны остаться зелёными
без изменений).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/teacher_spa/services.py journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py
git commit -m "feat(teacher-spa): submitLesson returns success:false for group with no students"
```

---

## Task 4: Frontend teacher SPA — блок кнопки при пустой группе

**Files:**
- Modify: `journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx`

Нет автотестов на фронте (см. spec) — проверка вручную в Task, следующем за
этим (см. Task 5 для аналогичной admin-проверки; для teacher SPA — см. финальный
шаг ниже).

- [ ] **Step 1: Добавить вычисление `noStudents`**

В `LessonForm.tsx`, после строки `const presentCount = ...` (строка 73),
добавить:

```tsx
  const presentCount = groupData.students.reduce((n, s) => n + (present[s.name] ? 1 : 0), 0);
  const noStudents = groupData.students.length === 0;
```

- [ ] **Step 2: Заблокировать кнопку и ранний выход в `handleSubmit`**

Изменить `handleSubmit` (строка 100):

```tsx
  const handleSubmit = () => {
    if (limitExceeded || noStudents || submitLesson.isPending) return;
    setSubmitError(null);
```

Изменить кнопку сохранения (строка 253-260):

```tsx
        <button
          type="button"
          className="btn-save"
          disabled={limitExceeded || noStudents || submitLesson.isPending}
          onClick={handleSubmit}
        >
          {submitLesson.isPending ? 'Сохранение…' : 'Сохранить урок'}
        </button>
```

- [ ] **Step 3: Добавить инлайн-предупреждение**

В JSX, перед блоком `{limitExceeded && limitMessage && (...)}` (строка 197),
добавить:

```tsx
      {noStudents && (
        <div className="lf-error">
          <strong>В группе нет учеников — урок зафиксировать нельзя.</strong>
        </div>
      )}

```

- [ ] **Step 4: Проверить сборку типов**

Run (из `journal_django/frontend/teacher-src/`): `npx tsc --noEmit`
Expected: без новых ошибок (0 errors, либо ровно тот же набор
предсуществующих ошибок, что и до правки — сравнить вывод до/после при
сомнении).

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx
git commit -m "feat(teacher-spa): disable save button when group has no students"
```

---

## Task 5: Frontend admin SPA — блок в `LessonFormModal`

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/lessons/LessonFormModal.tsx`

- [ ] **Step 1: Добавить проверку в `onSubmit`**

В `LessonFormModal.tsx`, изменить `onSubmit` (строки 56-61):

```tsx
  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!groupId || !teacherId) {
      toast('Группа и преподаватель обязательны', 'error');
      return;
    }
    if (members.length === 0) {
      toast('В группе нет учеников — урок зафиксировать нельзя', 'error');
      return;
    }
    const attendance = members.map((m) => ({ student_id: m.student_id, present: isPresent(m.student_id) }));
```

- [ ] **Step 2: Дизейблить кнопку «Создать урок»**

Изменить footer `Dialog` (строки 104-109):

```tsx
      footer={
        <button
          type="submit"
          form="lesson-form"
          className="btn-save"
          disabled={muts.create.isPending || (!!groupId && members.length === 0)}
        >
          Создать урок
        </button>
      }
```

- [ ] **Step 3: Проверить сборку типов**

Run (из `journal_django/frontend/admin-src/`): `npx tsc --noEmit`
Expected: без новых ошибок.

- [ ] **Step 4: Ручная проверка в браузере**

Запустить dev-сервер (см. project skill `/run`, либо `npm run dev` в
`journal_django/frontend/admin-src/` + Django `runserver`). Открыть
`/admin/lessons`, выбрать группу без учеников (или создать тестовую группу без
участников) — убедиться, что кнопка «Создать урок» неактивна, а при попытке
сабмита формы (Enter в текстовом поле) всплывает toast «В группе нет
учеников…» и запрос на `/api/admin/lessons` не уходит (проверить Network tab).

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/lessons/LessonFormModal.tsx
git commit -m "feat(admin): block lesson creation when group has no students"
```

---

## Task 6: Backend — `unfilled_planned_lessons` (school-wide repository read)

**Files:**
- Modify: `journal_django/apps/scheduling/repository.py`
- Test: `journal_django/apps/scheduling/tests/test_unfilled_lessons.py` (new file)

- [ ] **Step 1: Написать падающий тест**

Create `journal_django/apps/scheduling/tests/test_unfilled_lessons.py`:

```python
"""
unfilled_planned_lessons() — school-wide (не per-teacher) чтение просроченных
плановых занятий, источник виджета «Незаполненные уроки» admin-дашборда.
См. docs/superpowers/specs/2026-07-17-lesson-attendance-guard-and-unfilled-dashboard-design.md
"""
from __future__ import annotations

import datetime

import pytest

from apps.scheduling import repository

D = datetime.date


@pytest.mark.django_db
def test_returns_rows_across_teachers(sched_setup):
    """Школьный скоуп: группы ДВУХ разных преподавателей попадают в результат."""
    s = sched_setup
    repository.generate_for_group(s['group_a'])
    repository.generate_for_group(s['group_b'])

    rows = repository.unfilled_planned_lessons(D(2026, 5, 1), D(2026, 12, 31))

    teacher_ids = {r['teacher_id'] for r in rows}
    assert s['teacher_a'] in teacher_ids
    assert s['teacher_b'] in teacher_ids


@pytest.mark.django_db
def test_excludes_done_lessons(sched_setup):
    """status='done' (есть факт) не попадает в выборку (status фильтруется в БД)."""
    s = sched_setup
    repository.generate_for_group(s['group_a'])
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE planned_lessons SET status='done' WHERE group_id = %s",
            [s['group_a']],
        )

    rows = repository.unfilled_planned_lessons(D(2026, 5, 1), D(2026, 12, 31))
    assert all(r['group_pk'] != s['group_a'] for r in rows)


@pytest.mark.django_db
def test_window_bounds_respected(sched_setup):
    """Занятия вне окна (раньше window_from) не попадают в выборку."""
    s = sched_setup
    repository.generate_for_group(s['group_a'])

    rows_out_of_window = repository.unfilled_planned_lessons(D(2027, 1, 1), D(2027, 1, 31))
    assert all(r['group_pk'] != s['group_a'] for r in rows_out_of_window)
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `pytest apps/scheduling/tests/test_unfilled_lessons.py -v`
Expected: FAIL с `AttributeError: module 'apps.scheduling.repository' has no
attribute 'unfilled_planned_lessons'`.

- [ ] **Step 3: Добавить функцию в repository**

В `journal_django/apps/scheduling/repository.py`, добавить после
`cancellations_count` (после строки 230, перед секцией «ЗАПИСЬ плана»):

```python


def unfilled_planned_lessons(window_from: datetime.date, window_to: datetime.date) -> list[dict]:
    """
    Плановые занятия ВСЕХ активных групп в окне со status='pending' (done/
    cancelled/moved уже исключены хранимым статусом) — источник виджета
    «Незаполненные уроки» admin-дашборда (apps.dashboard). Overdue — точный
    порог (время урока < now) проверяет вызывающий (apps.scheduling.services),
    как и occurrences_on_date/build_calendar. Школьный скоуп (не per-teacher) —
    как occurrences_on_date выше.
    """
    return list(
        PlannedLesson.objects
        .filter(
            group__active=True,
            status=PENDING,
            scheduled_date__gte=window_from,
            scheduled_date__lte=window_to,
        )
        .order_by('scheduled_date', 'scheduled_time')
        .values(
            'scheduled_date', 'scheduled_time', 'teacher_id',
            group_pk=F('group_id'),
            group_name=F('group__name'),
            direction_name=F('group__direction__name'),
            direction_color=F('group__direction__color'),
        )
    )
```

- [ ] **Step 4: Запустить тест, убедиться что проходит**

Run: `pytest apps/scheduling/tests/test_unfilled_lessons.py -v`
Expected: PASS (все 3 теста).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/scheduling/repository.py journal_django/apps/scheduling/tests/test_unfilled_lessons.py
git commit -m "feat(scheduling): add school-wide unfilled_planned_lessons query"
```

---

## Task 7: Backend — `build_unfilled_lessons` (overdue-фильтр + сортировка)

**Files:**
- Modify: `journal_django/apps/scheduling/services.py`
- Test: `journal_django/apps/scheduling/tests/test_unfilled_lessons.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `journal_django/apps/scheduling/tests/test_unfilled_lessons.py`:

```python
from unittest.mock import patch

from apps.scheduling import services


@pytest.mark.django_db
def test_build_excludes_future_pending(sched_setup):
    """Плановое занятие с датой в будущем (ещё не наступило) не попадает в overdue-список."""
    s = sched_setup
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
            "scheduled_time, teacher_id, status, created_at, updated_at) "
            "VALUES (%s, 1, 1, '2099-01-01', '10:00', %s, 'pending', NOW(), NOW())",
            [s['group_a'], s['teacher_a']],
        )

    rows = services.build_unfilled_lessons()
    assert all(r['group_id'] != s['group_a'] or r['date'] != '2099-01-01' for r in rows)


@pytest.mark.django_db
def test_build_includes_past_pending_sorted(sched_setup):
    """Прошедшее pending-занятие → попадает в список, отсортировано по (date, time)."""
    s = sched_setup
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
            "scheduled_time, teacher_id, status, created_at, updated_at) "
            "VALUES (%s, 1, 1, '2026-01-10', '10:00', %s, 'pending', NOW(), NOW())",
            [s['group_a'], s['teacher_a']],
        )
        cur.execute(
            "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
            "scheduled_time, teacher_id, status, created_at, updated_at) "
            "VALUES (%s, 2, 2, '2026-01-05', '10:00', %s, 'pending', NOW(), NOW())",
            [s['group_a'], s['teacher_a']],
        )

    rows = services.build_unfilled_lessons(window_days=3650)
    dates = [r['date'] for r in rows if r['group_id'] == s['group_a']]
    assert dates == sorted(dates)
    assert '2026-01-05' in dates
    assert '2026-01-10' in dates
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `pytest apps/scheduling/tests/test_unfilled_lessons.py -k test_build -v`
Expected: FAIL с `AttributeError: module 'apps.scheduling.services' has no
attribute 'build_unfilled_lessons'`.

- [ ] **Step 3: Добавить функцию в services**

В `journal_django/apps/scheduling/services.py`, добавить после `build_calendar`
(после строки 207, перед секцией «Admin-план»):

```python


def build_unfilled_lessons(window_days: int = 30) -> list[dict]:
    """
    Просроченные (надо заполнить) плановые занятия ВСЕЙ школы за скользящее
    окно [сегодня - window_days, сегодня] — источник виджета «Незаполненные
    уроки» admin-дашборда (apps.dashboard.views.UnfilledLessonsView). Статус
    'overdue' вычисляется на чтении (тот же принцип, что _planned_status), но
    скоуп школьный, не per-teacher.
    """
    now = msk_now()
    today = now.date()
    window_from = today - datetime.timedelta(days=window_days)
    rows = repository.unfilled_planned_lessons(window_from, today)
    tnames = repository.teacher_names()

    out: list[dict] = []
    for r in rows:
        occ_dt = datetime.datetime.combine(
            r['scheduled_date'], r['scheduled_time'] or datetime.time(0, 0), tzinfo=MSK,
        )
        if now < occ_dt:
            continue  # ещё не наступил
        out.append({
            'group_id': r['group_pk'],
            'group_name': r['group_name'],
            'teacher_name': tnames.get(r['teacher_id']),
            'direction_name': r['direction_name'],
            'direction_color': r['direction_color'],
            'date': _iso(r['scheduled_date']),
            'time': _hhmm(r['scheduled_time']),
        })
    out.sort(key=lambda x: (x['date'], x['time'] or ''))
    return out
```

(`_iso`/`_hhmm` — уже существующие хелперы в этом файле, строки 26-31; `MSK`/
`msk_now` — уже импортированы в шапке файла, строка 12.)

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `pytest apps/scheduling/tests/test_unfilled_lessons.py -v`
Expected: PASS (все 5 тестов файла).

- [ ] **Step 5: Прогнать весь набор scheduling-тестов (регрессия)**

Run: `pytest apps/scheduling/ -v`
Expected: PASS (ничего не сломано).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/scheduling/services.py journal_django/apps/scheduling/tests/test_unfilled_lessons.py
git commit -m "feat(scheduling): add build_unfilled_lessons for school-wide overdue widget"
```

---

## Task 8: Backend — `GET /api/admin/dashboard/unfilled-lessons`

**Files:**
- Modify: `journal_django/apps/dashboard/views.py`
- Modify: `journal_django/apps/dashboard/urls.py`
- Test: `journal_django/apps/dashboard/tests/test_unfilled_lessons_api.py` (new file)

- [ ] **Step 1: Написать падающий тест**

Create `journal_django/apps/dashboard/tests/test_unfilled_lessons_api.py`:

```python
"""
E2E тесты для /api/admin/dashboard/unfilled-lessons.

Логика overdue-фильтра/сортировки покрыта в apps/scheduling/tests/
test_unfilled_lessons.py — здесь только auth/RBAC и контракт ответа.
"""
from __future__ import annotations

import pytest
from django.contrib.auth.hashers import make_password
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

BASE = '/api/admin/dashboard/unfilled-lessons'

_ROLE_EMAILS = {
    'admin': '__unfilled_admin__@example.com',
    'manager': '__unfilled_manager__@example.com',
    'teacher': '__unfilled_teacher__@example.com',
}


@pytest.fixture(scope='session')
def django_db_setup():
    pass


def _get_or_create_account(role: str) -> 'Account':
    email = _ROLE_EMAILS[role]
    try:
        return Account.objects.get(email=email)
    except Account.DoesNotExist:
        from django.db import connection as _conn
        with _conn.cursor() as cur:
            teacher_id = None
            if role == 'teacher':
                cur.execute("INSERT INTO teachers (name) VALUES ('__unfilled_teacher__') RETURNING id")
                teacher_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO accounts (email, password, role, teacher_id, is_active, is_staff, is_superuser, first_name, last_name, date_joined, token_version) "
                "VALUES (%s, %s, %s, %s, true, false, false, '', '', NOW(), 0) RETURNING id",
                [email, make_password('testpass123'), role, teacher_id],
            )
            acc_id = cur.fetchone()[0]
        return Account.objects.get(pk=acc_id)


def _client(role: str | None) -> APIClient:
    c = APIClient()
    if role is not None:
        account = _get_or_create_account(role)
        refresh = RefreshToken.for_user(account)
        refresh['token_version'] = account.token_version
        c.cookies['access'] = str(refresh.access_token)
    return c


def test_requires_auth():
    assert _client(None).get(BASE).status_code == 401


def test_teacher_forbidden():
    assert _client('teacher').get(BASE).status_code == 403


@pytest.mark.parametrize('role', ['manager', 'admin'])
def test_allowed_roles_envelope(role):
    resp = _client(role).get(BASE)
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {'rows', 'total', 'page', 'page_size'}
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `pytest apps/dashboard/tests/test_unfilled_lessons_api.py -v`
Expected: FAIL — маршрут `/api/admin/dashboard/unfilled-lessons` ещё не
существует (404, не 401/403/200).

- [ ] **Step 3: Добавить вьюху**

В `journal_django/apps/dashboard/views.py`, изменить импорт (строка 22) и
добавить класс в конец файла:

```python
from apps.core.pagination import StandardPagination
from apps.core.permissions import IsManagerOrAdmin
from apps.dashboard import services
from apps.scheduling import services as scheduling_services
```

```python


class UnfilledLessonsView(APIView):
    """
    GET /api/admin/dashboard/unfilled-lessons — просроченные незаполненные
    занятия ВСЕЙ школы за скользящее окно 30 дней, постранично.
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        rows = scheduling_services.build_unfilled_lessons()
        paginator = StandardPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(page)
```

- [ ] **Step 4: Зарегистрировать маршрут**

В `journal_django/apps/dashboard/urls.py`:

```python
from django.urls import path

from apps.dashboard.views import DashboardMonthlyView, DashboardView, UnfilledLessonsView

urlpatterns = [
    path('', DashboardView.as_view(), name='dashboard'),
    path('/monthly', DashboardMonthlyView.as_view(), name='dashboard-monthly'),
    path('/unfilled-lessons', UnfilledLessonsView.as_view(), name='dashboard-unfilled-lessons'),
]
```

- [ ] **Step 5: Запустить тест, убедиться что проходит**

Run: `pytest apps/dashboard/tests/test_unfilled_lessons_api.py -v`
Expected: PASS (все 4 теста).

- [ ] **Step 6: Прогнать весь набор dashboard-тестов (регрессия)**

Run: `pytest apps/dashboard/ -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/dashboard/views.py journal_django/apps/dashboard/urls.py journal_django/apps/dashboard/tests/test_unfilled_lessons_api.py
git commit -m "feat(dashboard): add GET /api/admin/dashboard/unfilled-lessons"
```

---

## Task 9: Frontend admin SPA — тип + хук

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/shared-types.ts`
- Create: `journal_django/frontend/admin-src/src/hooks/useUnfilledLessons.ts`

- [ ] **Step 1: Добавить тип `UnfilledLesson`**

В `journal_django/frontend/admin-src/src/lib/shared-types.ts`, после
интерфейса `Paginated<T>` (после строки 272, перед комментарием «Реестр
куратора»):

```ts

// ===== Незаполненные уроки (вкладка дашборда) =====

export interface UnfilledLesson {
  group_id: number;
  group_name: string;
  teacher_name: string | null;
  direction_name: string | null;
  direction_color: string | null;
  date: string;
  time: string | null;
}
```

- [ ] **Step 2: Создать хук**

Create `journal_django/frontend/admin-src/src/hooks/useUnfilledLessons.ts`:

```ts
import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Paginated, UnfilledLesson } from '../lib/types';

export interface UnfilledLessonsParams {
  page: number;
  page_size: number;
}

function buildQuery(p: UnfilledLessonsParams): string {
  const qs = new URLSearchParams();
  qs.set('page', String(p.page));
  qs.set('page_size', String(p.page_size));
  return qs.toString();
}

// Серверно-пагинированный список просроченных незаполненных уроков (вся школа).
export function useUnfilledLessons(params: UnfilledLessonsParams) {
  return useQuery({
    queryKey: ['dashboard', 'unfilled-lessons', params],
    queryFn: () =>
      api<Paginated<UnfilledLesson>>(
        'GET',
        `/api/admin/dashboard/unfilled-lessons?${buildQuery(params)}`,
      ),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}
```

(`../lib/types` — барrel-файл `journal_django/frontend/admin-src/src/lib/types.ts`,
целиком реэкспортирующий `shared-types.ts` через `export * from
'./shared-types'`; остальные хуки, включая `useRegistry.ts`, импортируют типы
именно оттуда — используем тот же путь для консистентности.)

- [ ] **Step 3: Проверить сборку типов**

Run (из `journal_django/frontend/admin-src/`): `npx tsc --noEmit`
Expected: 0 новых ошибок.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/lib/shared-types.ts journal_django/frontend/admin-src/src/hooks/useUnfilledLessons.ts
git commit -m "feat(admin): add UnfilledLesson type and useUnfilledLessons hook"
```

---

## Task 10: Frontend admin SPA — компонент вкладки `UnfilledLessonsTab`

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/dashboard/unfilled/UnfilledLessonsTab.tsx`

- [ ] **Step 1: Создать компонент**

Create `journal_django/frontend/admin-src/src/pages/dashboard/unfilled/UnfilledLessonsTab.tsx`:

```tsx
import { useNavigate } from 'react-router-dom';
import { useListSearchParams } from '../../../hooks/useListSearchParams';
import { useUnfilledLessons } from '../../../hooks/useUnfilledLessons';
import { DataTable, type Column } from '../../../components/table/DataTable';
import { fmtDate } from '../../../lib/format';
import type { UnfilledLesson } from '../../../lib/types';

const columns: Column<UnfilledLesson>[] = [
  {
    key: 'date',
    label: 'Дата',
    sortable: false,
    cell: (r) => `${fmtDate(r.date)}${r.time ? ' · ' + r.time : ''}`,
  },
  {
    key: 'group_name',
    label: 'Группа',
    sortable: false,
    cell: (r) => (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            display: 'inline-block',
            background: r.direction_color || 'var(--border)',
          }}
        />
        {r.group_name}
      </span>
    ),
  },
  {
    key: 'teacher_name',
    label: 'Преподаватель',
    sortable: false,
    cell: (r) => r.teacher_name || '—',
  },
];

export default function UnfilledLessonsTab() {
  const navigate = useNavigate();
  const { page, pageSize, setPage, setPageSize } = useListSearchParams({
    sortBy: 'date',
    sortDir: 'asc',
    pageSize: 30,
  });
  const { data, isFetching } = useUnfilledLessons({ page, page_size: pageSize });

  return (
    <DataTable
      title="Незаполненные уроки"
      data={data?.rows || []}
      columns={columns}
      isLoading={isFetching}
      onRowClick={(row) => navigate(`/admin/groups/${row.group_id}?tab=lessons`)}
      serverPagination={{
        page,
        pageSize,
        total: data?.total || 0,
        sortBy: 'date',
        sortDir: 'asc',
        filters: {},
        onPageChange: setPage,
        onPageSizeChange: setPageSize,
        onSortChange: () => {},
        onFiltersChange: () => {},
      }}
    />
  );
}
```

- [ ] **Step 2: Проверить сборку типов**

Run (из `journal_django/frontend/admin-src/`): `npx tsc --noEmit`
Expected: 0 новых ошибок. (`fmtDate(s: string | Date | null | undefined):
string` в `lib/format.ts:1` принимает ISO-строку напрямую — `r.date` подходит
без адаптации.)

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/dashboard/unfilled/UnfilledLessonsTab.tsx
git commit -m "feat(admin): add UnfilledLessonsTab component"
```

---

## Task 11: Frontend admin SPA — вкладка в `DashboardPage`

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/dashboard/DashboardPage.tsx`

- [ ] **Step 1: Добавить тип таба, ленивый импорт и кнопку**

Переписать `DashboardPage.tsx` целиком:

```tsx
import { lazy, Suspense } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PageLoading } from '../../components/ui/Skeleton';
import FinanceView from './FinanceView';

// Реестр и «Незаполненные» — отдельные чанки: грузятся только при открытии вкладки.
const RegistryTab = lazy(() => import('./registry/RegistryTab'));
const UnfilledLessonsTab = lazy(() => import('./unfilled/UnfilledLessonsTab'));

type Tab = 'finance' | 'registry' | 'unfilled';

export default function DashboardPage() {
  const [sp, setSp] = useSearchParams();
  const rawTab = sp.get('tab');
  const tab: Tab = rawTab === 'registry' ? 'registry' : rawTab === 'unfilled' ? 'unfilled' : 'finance';

  const setTab = (t: Tab) => {
    const next = new URLSearchParams(sp);
    if (t === 'finance') next.delete('tab');
    else next.set('tab', t);
    setSp(next, { replace: true });
  };

  return (
    <div className="dashboard">
      <header className="dashboard__head">
        <h1 className="dashboard__title">Дашборд</h1>
      </header>

      <nav className="dash-tabs" role="tablist" aria-label="Разделы дашборда">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'finance'}
          className={`dash-tab${tab === 'finance' ? ' dash-tab--active' : ''}`}
          onClick={() => setTab('finance')}
        >
          Финансы
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'registry'}
          className={`dash-tab${tab === 'registry' ? ' dash-tab--active' : ''}`}
          onClick={() => setTab('registry')}
        >
          Реестр
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'unfilled'}
          className={`dash-tab${tab === 'unfilled' ? ' dash-tab--active' : ''}`}
          onClick={() => setTab('unfilled')}
        >
          Незаполненные
        </button>
      </nav>

      {tab === 'finance' && <FinanceView />}
      {tab === 'registry' && (
        <Suspense fallback={<PageLoading />}>
          <RegistryTab />
        </Suspense>
      )}
      {tab === 'unfilled' && (
        <Suspense fallback={<PageLoading />}>
          <UnfilledLessonsTab />
        </Suspense>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Проверить сборку типов**

Run (из `journal_django/frontend/admin-src/`): `npx tsc --noEmit`
Expected: 0 новых ошибок.

- [ ] **Step 3: Ручная проверка в браузере**

Запустить dev-сервер (Django `runserver` + `npm run dev` в `admin-src/`).
Открыть `/admin` (дашборд), убедиться:
- третья вкладка «Незаполненные» отображается и переключается (`?tab=unfilled` в URL);
- список показывает просроченные занятия (создать в дев-БД плановое занятие
  с датой в прошлом без факта, если таких пока нет);
- клик по строке ведёт на `/admin/groups/<id>?tab=lessons`;
- пагинация работает при >30 строк (если данных мало — уменьшить `pageSize`
  временно в хуке для проверки, затем вернуть 30).

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/dashboard/DashboardPage.tsx
git commit -m "feat(admin): add Незаполненные tab to dashboard"
```

---

## Итоговая проверка (после всех задач)

- [ ] **Полный прогон backend-тестов**

Run (из `journal_django/`): `pytest -v`
Expected: PASS, без регрессий во всём наборе (включая `apps/lessons`,
`apps/teacher_spa`, `apps/scheduling`, `apps/dashboard`).

- [ ] **Полная типопроверка обоих фронтов**

Run: `npx tsc --noEmit` в `journal_django/frontend/admin-src/` и
`journal_django/frontend/teacher-src/`.
Expected: 0 ошибок в обоих.
