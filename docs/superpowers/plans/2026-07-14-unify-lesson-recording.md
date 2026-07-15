# Unify Lesson-Recording Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two independent, incomplete "record a lesson" implementations (teacher SPA's `submit_lesson`, admin's `apps/lessons`) with one shared core (`apps/lessons/services.py::record_lesson`) that both call, so Lesson+attendance+counters+Payroll+`planned_lessons` linkage+renewal-stage sync always happen together, everywhere, with the server always computing payment/penalty.

**Architecture:** `apps/lessons/services.py::record_lesson(...)` becomes the single orchestration point (transaction boundary + cross-app calls: `apps.scheduling.repository.link_facts`, `apps.finances.repository.balances_for_students`, `apps.payroll.calculator`, `apps.renewals.engine`), calling new small ORM-only helpers added to `apps/lessons/repository.py`. `apps/teacher_spa/services.py::submit_lesson` keeps its own teacher-specific resolution (group-by-name, substitution/reschedule derivation, lesson_number calc) but delegates the actual write to `record_lesson`. `apps/lessons/services.py::create_lesson_full` becomes a thin admin-specific adapter over the same `record_lesson`. A new domain exception (`apps.lessons.exceptions.UnpaidAttendanceBlocked`) lets each caller translate a balance-rule violation into its own existing HTTP contract.

**Tech Stack:** Django 5 / DRF (backend), React 19 + TypeScript (admin-src frontend), pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-07-14-unify-lesson-recording-design.md`

---

### Task 1: Move `calculate_payment`/`calculate_penalty` to `apps/payroll/calculator.py`

**Files:**
- Create: `journal_django/apps/payroll/calculator.py`
- Create: `journal_django/apps/payroll/tests/test_calculator.py`
- Modify: `journal_django/apps/teacher_spa/calculator.py` (remove the two functions + `PAY_RATES`)
- Modify: `journal_django/apps/teacher_spa/services.py:21-25` (import from new location)
- Delete: `journal_django/apps/teacher_spa/tests/test_calculator.py`

This is a pure relocation — no behavior change beyond what the user already made
(uncommitted `calculate_penalty` signature: `40 * count_students` instead of flat `40`).
It also fixes the 4 currently-failing tests (old signature) by moving them to the
new location with the new signature.

- [ ] **Step 1: Create `apps/payroll/calculator.py`**

```python
"""
calculator.py — расчёт зарплаты преподавателя за урок (payment) и штрафа за
просрочку отчёта (penalty). Общее для teacher SPA и admin SPA — оба пути
записи урока (apps.teacher_spa.services.submit_lesson,
apps.lessons.services.record_lesson) вызывают эти функции, сервер всегда
считает сам (клиентские payment/penalty не принимаются).

Все функции работают с int (рублями), никаких Decimal — оплата у преподавателя
всегда целая (нет копеек).
"""
from __future__ import annotations

PAY_RATES = {
    'halfLesson': 250,    # за каждого присутствующего в полуурочном занятии
    'smallGroup': 500,    # малая группа (1-2 чел.) — все пришли
    'smallPartial': 300,  # малая группа — пришли не все
    'perStudent': 200,    # большая группа (3+ чел.) — за каждого пришедшего
}


def calculate_payment(total: int, present: int, is_half: bool = False) -> int:
    """
    Правила:
      present == 0            → 0
      isHalf                  → 250 * present
      total <= 2, все пришли  → 500
      total <= 2, часть       → 300
      total > 2               → 200 * present
    """
    if present == 0:
        return 0
    if is_half:
        return PAY_RATES['halfLesson'] * present
    if total <= 2:
        return PAY_RATES['smallGroup'] if present == total else PAY_RATES['smallPartial']
    return PAY_RATES['perStudent'] * present


def calculate_penalty(lesson_date: str, submit_date: str, count_students: int) -> int:
    """
    Штраф за просрочку отчёта: тот же день → 0, иначе → 40₽ на каждого
    присутствовавшего ученика. Оба аргумента в формате 'YYYY-MM-DD'.

    Вызывающая сторона решает, что передать в submit_date: teacher SPA — реальную
    сегодняшнюю дату (штраф за опоздание с отчётом); admin SPA передаёт
    submit_date=lesson_date всегда (админ не должен штрафоваться за
    административную запись задним числом — см. design doc).
    """
    if lesson_date == submit_date:
        return 0
    return 40 * count_students
```

- [ ] **Step 2: Create `apps/payroll/tests/test_calculator.py`** (moved + fixed from
  `apps/teacher_spa/tests/test_calculator.py`, same test bodies, new import path,
  `calculate_penalty` calls updated to the 3-arg signature)

```python
"""
test_calculator.py — юнит-тесты для apps/payroll/calculator.py.

Чисто логические тесты, без БД.
Матрица: half/small/partial/perStudent, present=0, various combos.
Штраф: тот же день → 0, другой → 40 на присутствовавшего.
"""
from __future__ import annotations

import pytest

from apps.payroll.calculator import calculate_payment, calculate_penalty


# ---------------------------------------------------------------------------
# calculate_payment — матрица
# ---------------------------------------------------------------------------

class TestCalculatePayment:
    """Порт матрицы из calculator.js calculatePayment."""

    # present == 0 → всегда 0
    @pytest.mark.parametrize('total,is_half', [
        (1, False), (2, False), (3, False), (1, True), (5, True),
    ])
    def test_present_zero_returns_zero(self, total, is_half):
        assert calculate_payment(total, 0, is_half) == 0

    # isHalf → 250 * present (независимо от total)
    @pytest.mark.parametrize('total,present,expected', [
        (1, 1, 250),
        (2, 2, 500),
        (3, 1, 250),
        (3, 3, 750),
        (5, 2, 500),
    ])
    def test_half_lesson(self, total, present, expected):
        assert calculate_payment(total, present, is_half=True) == expected

    # Малая группа (total <= 2), все пришли → 500
    @pytest.mark.parametrize('total', [1, 2])
    def test_small_group_full(self, total):
        assert calculate_payment(total, total, is_half=False) == 500

    # Малая группа (total == 2), часть пришла → 300
    def test_small_group_partial(self):
        assert calculate_payment(2, 1, is_half=False) == 300

    # Одиночный ученик: total=1, present=1 → 500 (все пришли)
    def test_single_student_present(self):
        assert calculate_payment(1, 1, is_half=False) == 500

    # Большая группа (total > 2) → 200 * present
    @pytest.mark.parametrize('total,present,expected', [
        (3, 1, 200),
        (3, 2, 400),
        (3, 3, 600),
        (5, 0, 0),   # present=0 → 0 (already covered but consistent)
        (5, 4, 800),
        (10, 7, 1400),
    ])
    def test_per_student(self, total, present, expected):
        assert calculate_payment(total, present, is_half=False) == expected

    # Граничный случай: total=3, present=0 → 0
    def test_large_group_present_zero(self):
        assert calculate_payment(3, 0, is_half=False) == 0


# ---------------------------------------------------------------------------
# calculate_penalty
# ---------------------------------------------------------------------------

class TestCalculatePenalty:
    """Штраф: тот же день → 0, другой → 40 на присутствовавшего ученика."""

    def test_same_day_no_penalty(self):
        assert calculate_penalty('2026-06-10', '2026-06-10', 3) == 0

    def test_different_day_penalty_scales_with_present(self):
        assert calculate_penalty('2026-06-09', '2026-06-10', 1) == 40
        assert calculate_penalty('2026-06-09', '2026-06-10', 3) == 120

    def test_future_submit_penalty(self):
        # Урок в будущем, но дата не совпадает → штраф
        assert calculate_penalty('2026-06-11', '2026-06-10', 2) == 80

    def test_penalty_zero_present_no_penalty(self):
        # 0 присутствовавших → штраф 0 (нечего штрафовать)
        assert calculate_penalty('2026-01-01', '2026-06-10', 0) == 0
```

Note the last test (`test_penalty_zero_present_no_penalty`) replaces the old
`test_penalty_amount_is_40` (which asserted a flat 40 regardless of student
count — no longer true under the new `40 * count_students` formula; the
natural corresponding edge case is 0 students → 0 penalty).

- [ ] **Step 3: Run the new test file to verify it's green**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/payroll/tests/test_calculator.py -q`
Expected: 15 passed.

- [ ] **Step 4: Remove the moved functions from `apps/teacher_spa/calculator.py`**

Replace the full file content with:

```python
"""
calculator.py — вспомогательные функции teacher SPA, специфичные для этого
приложения. Расчёт payment/penalty теперь в apps.payroll.calculator (общий для
teacher_spa и apps.lessons — см. apps.lessons.services.record_lesson).
"""
from __future__ import annotations

from apps.core.utils.dates import msk_today


def format_msk_date() -> str:
    """
    Порт formatMskDate() из calculator.js — сегодняшняя дата в МСК как 'YYYY-MM-DD'.

    Переиспользует apps.core.utils.dates.msk_today().
    """
    return msk_today()
```

- [ ] **Step 5: Update the import in `apps/teacher_spa/services.py`**

Replace (lines 17-25):
```python
from apps.accounts.repository import get_by_id_with_teacher
from apps.finances.repository import balances_for_students
from apps.scheduling.repository import link_facts
from apps.teacher_spa import repository
from apps.teacher_spa.calculator import (
    calculate_payment,
    calculate_penalty,
    format_msk_date,
)
```
with:
```python
from apps.accounts.repository import get_by_id_with_teacher
from apps.finances.repository import balances_for_students
from apps.payroll.calculator import calculate_payment, calculate_penalty
from apps.scheduling.repository import link_facts
from apps.teacher_spa import repository
from apps.teacher_spa.calculator import format_msk_date
```

(This is a temporary intermediate state — Task 6 removes `calculate_payment`/
`calculate_penalty` usage from this file entirely once `submit_lesson` delegates
to `record_lesson`. For now, just fix the import path so the file keeps working.)

- [ ] **Step 6: Delete `apps/teacher_spa/tests/test_calculator.py`**

Its content has been fully moved to `apps/payroll/tests/test_calculator.py` (Step 2).

- [ ] **Step 7: Run the full affected suite**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/payroll apps/teacher_spa -q`
Expected: all green, no failures (this finally clears the 4 pre-existing
`TestCalculatePenalty` failures that were sitting in the working tree all session).

- [ ] **Step 8: Commit**

```bash
git add journal_django/apps/payroll/calculator.py journal_django/apps/payroll/tests/test_calculator.py journal_django/apps/teacher_spa/calculator.py journal_django/apps/teacher_spa/services.py
git rm journal_django/apps/teacher_spa/tests/test_calculator.py
git commit -m "refactor(payroll): move calculate_payment/calculate_penalty from teacher_spa"
```

---

### Task 2: `apps/scheduling` — explicit unlink on lesson delete

**Files:**
- Modify: `journal_django/apps/scheduling/repository.py` (add `unlink_fact`, after `link_facts` which ends at line 433)
- Modify: `journal_django/apps/lessons/repository.py:286-319` (`delete_lesson_full`)
- Test: `journal_django/apps/lessons/tests/test_lessons_repository.py`

- [ ] **Step 1: Write the failing test**

Add to `journal_django/apps/lessons/tests/test_lessons_repository.py`, right after
`test_delete_lesson_missing_returns_false` (currently ends at line 206):

```python
def test_delete_lesson_unlinks_planned_lesson(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    """Удаление урока возвращает связанную плановую строку в 'pending' (не
    остаётся зависшей 'done' без факта — см. design doc, аудит delete_lesson_full)."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
            "scheduled_time, teacher_id, status, created_at, updated_at) "
            "VALUES (%s, 1, 1, '2026-03-07', '10:00', %s, 'pending', NOW(), NOW()) "
            "RETURNING id",
            [group_fixture, teacher_id_fixture],
        )
        planned_id = cur.fetchone()[0]

    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-07',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    try:
        from apps.scheduling.repository import link_facts
        link_facts(group_fixture)
        with connection.cursor() as cur:
            cur.execute(
                'SELECT fact_lesson_id, status FROM planned_lessons WHERE id = %s',
                [planned_id],
            )
            fact_lesson_id, status = cur.fetchone()
        assert fact_lesson_id == lesson_id
        assert status == 'done'

        assert repository.delete_lesson_full(lesson_id) is True

        with connection.cursor() as cur:
            cur.execute(
                'SELECT fact_lesson_id, status FROM planned_lessons WHERE id = %s',
                [planned_id],
            )
            fact_lesson_id, status = cur.fetchone()
        assert fact_lesson_id is None
        assert status == 'pending'
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM planned_lessons WHERE id = %s', [planned_id])
```

(Note: `create_lesson_full` here still works exactly as it does today — this
task runs BEFORE Task 5 replaces it, and this test doesn't mark the student
present in a way affected by the balance rule since `membership_fixture`
already has no payment yet at this point in the plan; run this task's tests
alongside Task 1's baseline, not after Task 4/5's fixture changes. If Tasks
are executed strictly in order and Task 4 already ran, `membership_fixture`
will have a real balance by then too — either way this test doesn't depend on
that detail, it only checks the `planned_lessons` row.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_lessons_repository.py -k test_delete_lesson_unlinks_planned_lesson -q`
Expected: FAIL — `status == 'done'` still, `fact_lesson_id` is `None` (nulled by
cascade) but status never got reset.

- [ ] **Step 3: Add `unlink_fact` to `apps/scheduling/repository.py`**

Add this function right after `link_facts` (which ends at line 433, right before
the `# ---...--- Admin-API операции` comment block at line 436):

```python
def unlink_fact(lesson_id: int) -> None:
    """
    Отвязать плановую строку от удаляемого факта: fact_lesson_id=NULL,
    status → PENDING. Вызывается ДО удаления Lesson (внутри той же транзакции,
    из apps.lessons.repository.delete_lesson_full) — без этого шага
    fact_lesson_id зануляется каскадом (FK SET_NULL), но status остаётся
    'done', оставляя плановую строку зависшей «проведённой» без факта.

    Read-side (_planned_status) сам пересчитает overdue/pending по
    scheduled_date/scheduled_time при следующем чтении календаря — здесь
    достаточно вернуть status в PENDING, конкретное overdue/pending не разделяем.
    """
    PlannedLesson.objects.filter(fact_lesson_id=lesson_id).update(
        fact_lesson_id=None, status=PENDING,
    )
```

- [ ] **Step 4: Wire into `delete_lesson_full`**

In `journal_django/apps/lessons/repository.py`, add the import at line 27 (right
after the existing `from apps.memberships.models import GroupMembership`):

```python
from apps.memberships.models import GroupMembership
from apps.scheduling.repository import unlink_fact
```

Then in `delete_lesson_full` (currently lines 286-319), add the call right
before `Payroll.objects.filter(lesson_id=lesson_id).delete()`:

```python
        Payroll.objects.filter(lesson_id=lesson_id).delete()
```
becomes:
```python
        unlink_fact(lesson_id)
        Payroll.objects.filter(lesson_id=lesson_id).delete()
```

- [ ] **Step 5: Run the test again, verify it passes**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_lessons_repository.py -k test_delete_lesson_unlinks_planned_lesson -q`
Expected: PASS.

- [ ] **Step 6: Run the full affected suite**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/scheduling apps/lessons -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/scheduling/repository.py journal_django/apps/lessons/repository.py journal_django/apps/lessons/tests/test_lessons_repository.py
git commit -m "fix(lessons): reset planned_lessons status on lesson delete"
```

---

### Task 3: Balance-check exception + reusable helper

**Files:**
- Create: `journal_django/apps/lessons/exceptions.py`
- Modify: `journal_django/apps/lessons/repository.py` (add `assert_students_paid`)

- [ ] **Step 1: Create `apps/lessons/exceptions.py`**

```python
"""
Доменные исключения раздела lessons.

Не зависят от DRF/HTTP — бросаются в repository/services, маппятся в HTTP-ответ
во view (см. apps/groups/exceptions.py::ImmutableGroupFormat для того же паттерна).
"""
from __future__ import annotations


class UnpaidAttendanceBlocked(Exception):
    """
    Попытка отметить присутствие ученику, у которого не осталось оплаченных
    уроков (remaining <= 0, apps.finances.repository.balances_for_students).

    Действует одинаково для teacher SPA (submitLesson) и admin SPA (создание
    урока, переключение ячейки посещаемости) — единая проверка в
    apps.lessons.repository.assert_students_paid.
    """

    def __init__(self, blocked_names: list[str]) -> None:
        self.blocked_names = blocked_names
        names = ', '.join(blocked_names)
        super().__init__(
            f'У учеников без оплаченных уроков нельзя отметить посещение: {names}.'
        )
```

- [ ] **Step 2: Add `assert_students_paid` to `apps/lessons/repository.py`**

Add the import at the top (near the other cross-app imports, after
`from apps.groups.models import Group`):

```python
from apps.groups.models import Group
from apps.finances.repository import balances_for_students
```

Add the function right after the module-level `_step` helper (currently ends
at line 67, right before `_apply_filters`):

```python
def assert_students_paid(present_student_ids: list[int]) -> None:
    """
    Бросает UnpaidAttendanceBlocked, если у кого-то из перечисленных учеников
    остаток оплаченных уроков <= 0. Баланс считается СЕРВЕРОМ (батч, тот же
    расчёт, что read_all_students в teacher_spa) — не принимает клиентский вход.
    No-op для пустого списка. Общая проверка для create/attendance-toggle путей
    (apps.lessons.services.record_lesson, apps.lessons.repository.update_attendance_cell).
    """
    if not present_student_ids:
        return
    balances = balances_for_students(present_student_ids)
    blocked_ids = [sid for sid in present_student_ids if balances.get(sid, 0) <= 0]
    if not blocked_ids:
        return
    names = list(
        Student.objects.filter(id__in=blocked_ids)
        .values_list('full_name', flat=True)
    )
    raise UnpaidAttendanceBlocked(names)
```

Add the exception import near the top too:
```python
from .exceptions import UnpaidAttendanceBlocked
from .models import Lesson, LessonAttendance
```

- [ ] **Step 3: Verify it imports cleanly (no test yet — exercised by Task 5/7)**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons -q`
Expected: same pass count as before this task (no behavior wired in yet, just
new dead code — confirms no import errors / circular imports).

- [ ] **Step 4: Commit**

```bash
git add journal_django/apps/lessons/exceptions.py journal_django/apps/lessons/repository.py
git commit -m "feat(lessons): add UnpaidAttendanceBlocked + assert_students_paid helper"
```

---

### Task 4: Give `apps/lessons` test fixtures a real paid balance (prerequisite)

Same class of fix as the teacher_spa plan from earlier this session
(`docs/superpowers/plans/2026-07-14-block-unpaid-attendance.md`, Task 1) — do
it now, BEFORE Task 5 wires the balance check into the create/toggle paths,
so the existing test suite doesn't regress for the wrong reason.

**Files:**
- Modify: `journal_django/apps/lessons/tests/conftest.py:80-94` (`membership_fixture`)
- Modify: `journal_django/apps/lessons/tests/test_lessons_repository.py:96-120` (`test_create_lesson_with_payroll`)
- Modify: `journal_django/apps/lessons/tests/test_lessons_api.py:326-355` (`test_payroll_visible_only_to_superadmin`)

- [ ] **Step 1: Give `membership_fixture` a real payment**

Replace `journal_django/apps/lessons/tests/conftest.py:80-94`:

```python
@pytest.fixture
def membership_fixture(group_fixture, student_fixture):
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO group_memberships (group_id, student_id, lessons_done, active)
            VALUES (%s, %s, 0, true)
            RETURNING id
            """,
            [group_fixture, student_fixture],
        )
        membership_id = cur.fetchone()[0]
    yield membership_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])
```

with:

```python
@pytest.fixture
def membership_fixture(group_fixture, student_fixture, direction_fixture):
    """
    С оплатой на 8 уроков (remaining=8) — иначе create_lesson_full/
    update_attendance_cell блокируют present:true (нет оплаченных уроков,
    см. apps.lessons.repository.assert_students_paid).
    """
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO group_memberships (group_id, student_id, lessons_done, active)
            VALUES (%s, %s, 0, true)
            RETURNING id
            """,
            [group_fixture, student_fixture],
        )
        membership_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO payments (student_id, direction_id, subscriptions_count, lessons_count,
                                   unit_price, total_amount, paid_at, created_by)
            VALUES (%s, %s, 2, 8, 1000, 8000, '2026-06-01', 'test')
            RETURNING id
            """,
            [student_fixture, direction_fixture],
        )
        payment_id = cur.fetchone()[0]
    yield membership_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])
        cur.execute('DELETE FROM payments WHERE id = %s', [payment_id])
```

- [ ] **Step 2: Fix `test_create_lesson_with_payroll`** (it sends a client
  `payroll` object with no real `attendance` — incompatible with the upcoming
  "server always computes from attendance" rule; Task 5 removes the `payroll`
  parameter from `create_lesson_full` entirely, so rewrite this test now to
  match what it will look like, using real attendance + the paid fixture)

Replace `journal_django/apps/lessons/tests/test_lessons_repository.py:96-120`:

```python
def test_create_lesson_with_payroll(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture
):
    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-04',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'payroll': {
            'total_students': 5,
            'present_count': 4,
            'payment': 650,
            'penalty': 0,
        },
    })
    try:
        full = repository.get_lesson_full(lesson_id)
        assert full['payroll'] is not None
        assert full['payroll']['total_students'] == 5
        assert full['payroll']['present_count'] == 4
        # numeric → Decimal с масштабом
        assert full['payroll']['payment'] == Decimal('650.00')
    finally:
        _delete_lesson(lesson_id)
```

with:

```python
def test_create_lesson_with_payroll(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture
):
    """Payroll теперь считается сервером из attendance (present=1, total=1 →
    small-group-full formula = 500), клиентский payroll больше не принимается
    (см. Task 5 — этот тест переживёт удаление параметра payroll из create_lesson_full
    только если сам его не передаёт)."""
    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-04',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    try:
        full = repository.get_lesson_full(lesson_id)
        assert full['payroll'] is not None
        assert full['payroll']['total_students'] == 1
        assert full['payroll']['present_count'] == 1
        assert full['payroll']['payment'] == Decimal('500.00')
    finally:
        _delete_lesson(lesson_id)
```

(This test will still call the OLD `create_lesson_full` signature until Task 5
lands — at that point in Task 5 you must revisit this exact test again, because
Task 5 changes `create_lesson_full` to live in `services.py` with a different
call surface. Flagged again in Task 5 Step 6 below — don't lose track of it.)

- [ ] **Step 3: Remove the now-meaningless client `payroll` from the API test**

In `journal_django/apps/lessons/tests/test_lessons_api.py`, in
`test_payroll_visible_only_to_superadmin` (lines 326-355), remove the `payroll`
key from the `payload` dict (lines 336-341):

```python
        'attendance': [{'student_id': student_fixture, 'present': True}],
        'payroll': {
            'total_students': 1,
            'present_count': 1,
            'payment': 500,
            'penalty': 0,
        },
    }
```
becomes:
```python
        'attendance': [{'student_id': student_fixture, 'present': True}],
    }
```

(The test's actual point — payroll visible only to superadmin — is unaffected;
it was never asserting specific payment/penalty VALUES, just visibility.)

- [ ] **Step 4: Run the lessons suite, excluding the two tests that only pass after Task 5**

Two tests were just rewritten to assume "server always computes payroll from
attendance" (Task 5's behavior), which hasn't landed yet — at this point in
the plan, `create_lesson_full` still only creates a Payroll row `if payroll:`
(client-supplied) is truthy, and neither rewritten test sends one anymore.
Both will fail with `payroll is None` until Task 5 lands — expected, that's
the point of writing them now (TDD for Task 5):

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons -q -k "not test_create_lesson_with_payroll and not test_payroll_visible_only_to_superadmin"`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/lessons/tests/conftest.py journal_django/apps/lessons/tests/test_lessons_repository.py journal_django/apps/lessons/tests/test_lessons_api.py
git commit -m "test(lessons): give membership fixture a real paid balance"
```

---

### Task 5: Build `record_lesson` and rewire the admin create path

This is the largest task — it replaces `apps/lessons/repository.py::create_lesson_full`
with a shared core, used by the admin create endpoint. (Teacher SPA is rewired
in Task 6, separately, so this task alone must not break `submit_lesson` — it
still calls the OLD teacher_spa repository functions until Task 6.)

**Files:**
- Modify: `journal_django/apps/lessons/repository.py` (add 4 new functions, delete `create_lesson_full`)
- Modify: `journal_django/apps/lessons/services.py` (add `record_lesson`, rewrite `create_lesson_full`)
- Modify: `journal_django/apps/lessons/serializers.py` (remove `payroll` field + `PayrollPartSerializer`)
- Modify: `journal_django/apps/lessons/views.py` (catch `UnpaidAttendanceBlocked` → 400)
- Test: `journal_django/apps/lessons/tests/test_lessons_repository.py`, `test_lessons_orm_smoke.py`, `test_lessons_api.py`, `test_renewals_stage_sync.py`

- [ ] **Step 1: Add the 4 new repository helpers to `apps/lessons/repository.py`**

Add these right after `_step` (and after `assert_students_paid`, added in Task 3):

```python
def insert_lesson(fields: dict) -> int:
    """INSERT урока. Возвращает id. submitted_at — DB DEFAULT now() через Now()."""
    obj = Lesson.objects.create(
        lesson_date=fields['lesson_date'],
        teacher_id=fields['teacher_id'],
        group_id=fields['group_id'],
        original_teacher_id=fields.get('original_teacher_id'),
        lesson_number=fields['lesson_number'],
        lesson_duration_minutes=fields['lesson_duration_minutes'],
        lesson_type=fields.get('lesson_type') or 'regular',
        record_url=fields.get('record_url') or None,
        submitted_by_token=fields.get('submitted_by_token') or 'admin-imported',
        submitted_at=Now(),
    )
    return obj.pk


def insert_attendance(lesson_id: int, attendance: list[dict]) -> None:
    """
    Вставка посещаемости только для существующих студентов (= JOIN students),
    ON CONFLICT (lesson_id, student_id) DO NOTHING. No-op если список пуст.
    """
    if not attendance:
        return
    sids = [a['student_id'] for a in attendance]
    valid = set(Student.objects.filter(id__in=sids).values_list('id', flat=True))
    LessonAttendance.objects.bulk_create(
        [
            LessonAttendance(
                lesson_id=lesson_id,
                student_id=a['student_id'],
                present=bool(a['present']),
            )
            for a in attendance if a['student_id'] in valid
        ],
        ignore_conflicts=True,
    )


def increment_lessons_done(group_id: int, student_ids: list[int], step: Decimal) -> None:
    """UPDATE group_memberships SET lessons_done += step WHERE (group_id, student_id) IN ids."""
    if not student_ids:
        return
    GroupMembership.objects.filter(
        group_id=group_id, student_id__in=student_ids,
    ).update(lessons_done=F('lessons_done') + step)


def insert_payroll(fields: dict) -> None:
    """INSERT записи payroll. Вызывается всегда (сервер сам считает payment/penalty)."""
    Payroll.objects.create(
        lesson_id=fields['lesson_id'],
        teacher_id=fields['teacher_id'],
        total_students=fields['total_students'],
        present_count=fields['present_count'],
        payment=fields['payment'],
        penalty=fields['penalty'],
    )
```

- [ ] **Step 2: Delete `create_lesson_full` from `apps/lessons/repository.py`**

Remove the entire function (currently lines 186-255, from `def create_lesson_full`
through the `return lesson_id` and its blank lines, right before `def update_lesson`).

- [ ] **Step 3: Rewrite `apps/lessons/services.py`**

Replace the full file content with:

```python
"""
LessonsService — оркестрация записи урока (Lesson+attendance+счётчики+Payroll+
привязка к плановому занятию+синхронизация «Продлений»).

record_lesson — единое ядро (см. docs/superpowers/specs/2026-07-14-unify-lesson-recording-design.md),
используется и этим приложением (create_lesson_full — тонкий адаптер для
admin SPA), и apps.teacher_spa.services.submit_lesson. Транзакция управляется
ЗДЕСЬ (как submit_lesson); repository выполняет ORM-операции, cross-app
вызовы (link_facts/balances_for_students/renewals) — тоже здесь, не в repository.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.db import transaction

from apps.groups.models import Group
from apps.lessons import repository
from apps.payroll.calculator import calculate_payment, calculate_penalty
from apps.scheduling.repository import link_facts


def _step(duration_minutes) -> Decimal:
    return Decimal('0.5') if duration_minutes == 45 else Decimal('1')


def record_lesson(*,
    lesson_date: str,
    teacher_id: int,
    group_id: int,
    original_teacher_id: Optional[int],
    lesson_number,
    lesson_duration_minutes: int,
    lesson_type: str,
    record_url: Optional[str],
    submitted_by_token: str,
    submit_date: str,
    attendance: list[dict],
) -> dict:
    """
    Единое ядро записи урока. Атомарно создаёт Lesson+LessonAttendance,
    инкрементирует group_memberships.lessons_done, привязывает факт к
    planned_lessons (link_facts), создаёт Payroll (сервер считает
    payment/penalty сам — клиентского payroll не принимает), синхронизирует
    авто-стадию «Продлений» после коммита.

    attendance: [{'student_id': int, 'present': bool}, ...] — student_id уже
    резолвлен вызывающей стороной (teacher_spa резолвит по имени, admin SPA
    передаёт id напрямую).

    submit_date — для calculate_penalty: teacher SPA передаёт «сегодня»
    (штраф за просрочку отчёта), admin SPA передаёт submit_date=lesson_date
    всегда (админ не должен штрафоваться за административную запись задним
    числом — см. design doc).

    Бросает UnpaidAttendanceBlocked (apps.lessons.exceptions), если у кого-то
    из present-учеников остаток оплаченных уроков <= 0 — ДО открытия транзакции,
    ничего не пишется.

    Возвращает {'lesson_id': int, 'payment': int, 'penalty': int}.
    """
    present_student_ids = [a['student_id'] for a in attendance if a['present']]
    repository.assert_students_paid(present_student_ids)

    is_half = lesson_duration_minutes == 45
    step = _step(lesson_duration_minutes)
    total_students = len(attendance)
    present_count = len(present_student_ids)

    payment = calculate_payment(total_students, present_count, is_half)
    penalty = calculate_penalty(lesson_date, submit_date, present_count)

    direction_id = (
        Group.objects.filter(id=group_id).values_list('direction_id', flat=True).first()
        if present_student_ids else None
    )

    with transaction.atomic():
        lesson_id = repository.insert_lesson({
            'lesson_date': lesson_date,
            'teacher_id': teacher_id,
            'group_id': group_id,
            'original_teacher_id': original_teacher_id,
            'lesson_number': lesson_number,
            'lesson_duration_minutes': lesson_duration_minutes,
            'lesson_type': lesson_type,
            'record_url': record_url,
            'submitted_by_token': submitted_by_token,
        })
        # Привязать факт к плановой строке (planned_lessons.fact_lesson_id/status='done'),
        # иначе занятие остаётся «не проведено» в расписании/календаре.
        link_facts(group_id)
        repository.increment_lessons_done(group_id, present_student_ids, step)
        repository.insert_attendance(lesson_id, attendance)
        repository.insert_payroll({
            'lesson_id': lesson_id,
            'teacher_id': teacher_id,
            'total_students': total_students,
            'present_count': present_count,
            'payment': payment,
            'penalty': penalty,
        })

        for sid in present_student_ids:
            transaction.on_commit(lambda sid=sid: repository._sync_renewal_stage(sid, direction_id))

    return {'lesson_id': lesson_id, 'payment': payment, 'penalty': penalty}


def list_lessons(
    page: int = 1,
    page_size: int = 50,
    sort_by: str = 'lesson_date',
    sort_dir: str = 'desc',
    filters: Optional[dict] = None,
) -> dict:
    return repository.list_lessons(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        filters=filters,
    )


def get_lesson_full(lesson_id: int) -> Optional[dict]:
    return repository.get_lesson_full(lesson_id)


def create_lesson_full(data: dict) -> dict:
    """
    Admin SPA — тонкий адаптер над record_lesson. submit_date=lesson_date
    всегда (админ не штрафуется за административную запись задним числом).
    Возвращает {'lesson_id', 'payment', 'penalty'} (view делает повторный
    get_lesson_full для полного ответа, как раньше).
    """
    return record_lesson(
        lesson_date=data['lesson_date'],
        teacher_id=data['teacher_id'],
        group_id=data['group_id'],
        original_teacher_id=data.get('original_teacher_id'),
        lesson_number=data['lesson_number'],
        lesson_duration_minutes=data.get('lesson_duration_minutes') or 90,
        lesson_type=data.get('lesson_type') or 'regular',
        record_url=data.get('record_url') or None,
        submitted_by_token=data.get('submitted_by_token') or 'admin-imported',
        submit_date=data['lesson_date'],
        attendance=data.get('attendance') or [],
    )


def update_lesson(lesson_id: int, fields: dict) -> Optional[dict]:
    return repository.update_lesson(lesson_id, fields)


def delete_lesson_full(lesson_id: int) -> bool:
    return repository.delete_lesson_full(lesson_id)


def update_attendance_cell(lesson_id: int, student_id: int, present: bool) -> bool:
    return repository.update_attendance_cell(lesson_id, student_id, present)
```

Note: `record_lesson` calls `repository._sync_renewal_stage` — the existing
helper already defined in `apps/lessons/repository.py` (used by
`delete_lesson_full`/`update_attendance_cell`) — rather than defining its own
copy. This is the real dedup target from the design doc: ONE implementation in
`repository.py`, called both from `repository.py`'s own functions and from
`services.py`. Do NOT add a second `_sync_renewal_stage` def in `services.py`.

- [ ] **Step 4: Remove the `payroll` field from `LessonCreateSerializer`**

In `journal_django/apps/lessons/serializers.py`, delete the `PayrollPartSerializer`
class entirely (lines 35-41) and remove line 66 (`payroll = PayrollPartSerializer(required=False)`)
from `LessonCreateSerializer`.

- [ ] **Step 5: Catch `UnpaidAttendanceBlocked` in the create view**

In `journal_django/apps/lessons/views.py`, add the import:
```python
from apps.lessons.exceptions import UnpaidAttendanceBlocked
```
Then update `LessonListCreateView.post` (currently lines 127-136):
```python
    def post(self, request: Request) -> Response:
        serializer = LessonCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        lesson_id = services.create_lesson_full(serializer.validated_data)
        full = services.get_lesson_full(lesson_id)
        return Response(
            _strip_payroll_for_role(full, request.user.role),
            status=status.HTTP_201_CREATED,
        )
```
becomes:
```python
    def post(self, request: Request) -> Response:
        serializer = LessonCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = services.create_lesson_full(serializer.validated_data)
        except UnpaidAttendanceBlocked as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        full = services.get_lesson_full(result['lesson_id'])
        return Response(
            _strip_payroll_for_role(full, request.user.role),
            status=status.HTTP_201_CREATED,
        )
```

- [ ] **Step 6: Fix `test_create_lesson_with_payroll` for real now**

The Task 4 rewrite already uses `attendance` + `membership_fixture` (paid) and
expects `full['payroll']['payment'] == Decimal('500.00')` — this now passes for
real, since `record_lesson` always creates Payroll computed from attendance.
No further change needed to this test — just re-run it to confirm.

- [ ] **Step 7: Migrate `test_lessons_repository.py` off the deleted `repository.create_lesson_full`**

This function moved to `services.create_lesson_full` (Step 2/3 above) and its
return type changed from `int` (lesson_id) to `dict` (`{'lesson_id', 'payment', 'penalty'}`).
Almost every test in this file calls the old function to set up fixtures for
something else (delete/update/attendance/list) — replace the WHOLE file content:

```python
"""
Integration-тесты слоя lessons (реальная БД, managed=False).

create/attendance-toggle идут через apps.lessons.services (record_lesson —
единое ядро, см. apps.lessons.repository для low-level ORM-хелперов). Остальное
(update_lesson/delete_lesson_full/list_lessons) — repository напрямую, как раньше.

Покрытие:
  - create (через services.create_lesson_full): INSERT урока + attendance +
    payroll (сервер считает сам), инкремент lessons_done, link_facts.
  - half-lesson (45 мин → шаг 0.5) vs обычный (60 мин → шаг 1).
  - get_lesson_full: meta + attendance[] + payroll, None для отсутствующего.
  - update_lesson: COALESCE-семантика, original_teacher_id nullable.
  - delete_lesson_full: откат lessons_done, CASCADE attendance, удаление payroll,
    возврат planned_lessons в pending.
  - update_attendance_cell: дельта lessons_done (false→true→false), UPSERT,
    пересчёт payroll, блокировка без оплаченных уроков.
  - list_lessons: фильтры, сорт, контракт {rows,total,page,page_size}.
  - DATE-инвариант: lesson_date ввод == вывод без сдвига.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection

from apps.lessons import repository, services
from apps.lessons.exceptions import UnpaidAttendanceBlocked

pytestmark = pytest.mark.django_db


def _delete_lesson(lesson_id: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lessons WHERE id = %s', [lesson_id])


# ---------------------------------------------------------------------------
# create (services.create_lesson_full → record_lesson)
# ---------------------------------------------------------------------------

def test_create_lesson_increments_lessons_done_step_1(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-01',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    lesson_id = result['lesson_id']
    try:
        # 60-мин урок → шаг 1
        assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')
        full = repository.get_lesson_full(lesson_id)
        # repo-слой отдаёт psycopg2 date; строку '2026-03-01' даёт renderer (см. API-тест)
        assert full['lesson_date'] == datetime.date(2026, 3, 1)
        assert len(full['attendance']) == 1
        assert full['attendance'][0]['present'] is True
    finally:
        _delete_lesson(lesson_id)


def test_create_lesson_half_lesson_step_05(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-02',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 45,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    try:
        # 45-мин урок → шаг 0.5
        assert lessons_done(group_fixture, student_fixture) == Decimal('0.5')
    finally:
        _delete_lesson(result['lesson_id'])


def test_create_lesson_absent_student_no_increment(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-03',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    try:
        assert lessons_done(group_fixture, student_fixture) == Decimal('0.0')
    finally:
        _delete_lesson(result['lesson_id'])


def test_create_lesson_with_payroll(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture
):
    """Payroll теперь всегда считается сервером из attendance — total=1,
    present=1 → small-group-full formula = 500. Клиентский payroll больше не
    принимается (payroll не передаём вообще)."""
    result = services.create_lesson_full({
        'lesson_date': '2026-03-04',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    lesson_id = result['lesson_id']
    try:
        full = repository.get_lesson_full(lesson_id)
        assert full['payroll'] is not None
        assert full['payroll']['total_students'] == 1
        assert full['payroll']['present_count'] == 1
        assert full['payroll']['payment'] == Decimal('500.00')
    finally:
        _delete_lesson(lesson_id)


def test_create_lesson_blocked_without_paid_balance(
    group_fixture, teacher_id_fixture, student_fixture,
):
    """Ученик без оплаченных уроков (membership без payments) + present:true →
    UnpaidAttendanceBlocked, урок не создаётся вообще."""
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO group_memberships (group_id, student_id, lessons_done, active) '
            'VALUES (%s, %s, 0, true) RETURNING id',
            [group_fixture, student_fixture],
        )
        membership_id = cur.fetchone()[0]
    try:
        with pytest.raises(UnpaidAttendanceBlocked):
            services.create_lesson_full({
                'lesson_date': '2026-03-04',
                'group_id': group_fixture,
                'teacher_id': teacher_id_fixture,
                'lesson_number': 1,
                'lesson_duration_minutes': 60,
                'attendance': [{'student_id': student_fixture, 'present': True}],
            })
        with connection.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM lessons WHERE group_id = %s AND lesson_date = %s',
                [group_fixture, '2026-03-04'],
            )
            assert cur.fetchone()[0] == 0
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])


# ---------------------------------------------------------------------------
# get_lesson_full
# ---------------------------------------------------------------------------

def test_get_lesson_full_missing_returns_none():
    assert repository.get_lesson_full(999_999_999) is None


# ---------------------------------------------------------------------------
# update_lesson
# ---------------------------------------------------------------------------

def test_update_lesson_coalesce(group_fixture, teacher_id_fixture):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-05',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    lesson_id = result['lesson_id']
    try:
        # Передаём только lesson_type — остальное должно сохраниться.
        updated = repository.update_lesson(lesson_id, {'lesson_type': 'substitution'})
        assert updated['lesson_type'] == 'substitution'
        assert updated['lesson_date'] == datetime.date(2026, 3, 5)
    finally:
        _delete_lesson(lesson_id)


def test_update_lesson_original_teacher_explicit_null(group_fixture, teacher_id_fixture):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-06',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'original_teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    lesson_id = result['lesson_id']
    try:
        # Явный null → должен обнулиться.
        updated = repository.update_lesson(lesson_id, {'original_teacher_id': None})
        assert updated['original_teacher_id'] is None

        # Повторно ставим, затем НЕ передаём ключ → должен сохраниться.
        repository.update_lesson(lesson_id, {'original_teacher_id': teacher_id_fixture})
        again = repository.update_lesson(lesson_id, {'lesson_number': 2})
        assert again['original_teacher_id'] == teacher_id_fixture
    finally:
        _delete_lesson(lesson_id)


def test_update_lesson_missing_returns_none():
    assert repository.update_lesson(999_999_999, {'lesson_type': 'regular'}) is None


# ---------------------------------------------------------------------------
# delete_lesson_full
# ---------------------------------------------------------------------------

def test_delete_lesson_rolls_back_lessons_done(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-07',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    lesson_id = result['lesson_id']
    assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')

    ok = repository.delete_lesson_full(lesson_id)
    assert ok is True
    # lessons_done откатился
    assert lessons_done(group_fixture, student_fixture) == Decimal('0.0')
    # attendance удалён по CASCADE
    with connection.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
        assert cur.fetchone()[0] == 0


def test_delete_lesson_unlinks_planned_lesson(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    """Удаление урока возвращает связанную плановую строку в 'pending' (не
    остаётся зависшей 'done' без факта — см. Task 2)."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
            "scheduled_time, teacher_id, status, created_at, updated_at) "
            "VALUES (%s, 1, 1, '2026-03-07', '10:00', %s, 'pending', NOW(), NOW()) "
            "RETURNING id",
            [group_fixture, teacher_id_fixture],
        )
        planned_id = cur.fetchone()[0]

    result = services.create_lesson_full({
        'lesson_date': '2026-03-07',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    lesson_id = result['lesson_id']
    try:
        with connection.cursor() as cur:
            cur.execute(
                'SELECT fact_lesson_id, status FROM planned_lessons WHERE id = %s',
                [planned_id],
            )
            fact_lesson_id, status = cur.fetchone()
        assert fact_lesson_id == lesson_id
        assert status == 'done'

        assert repository.delete_lesson_full(lesson_id) is True

        with connection.cursor() as cur:
            cur.execute(
                'SELECT fact_lesson_id, status FROM planned_lessons WHERE id = %s',
                [planned_id],
            )
            fact_lesson_id, status = cur.fetchone()
        assert fact_lesson_id is None
        assert status == 'pending'
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM planned_lessons WHERE id = %s', [planned_id])


def test_delete_lesson_missing_returns_false():
    assert repository.delete_lesson_full(999_999_999) is False


# ---------------------------------------------------------------------------
# update_attendance_cell
# ---------------------------------------------------------------------------

def test_attendance_toggle_delta(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-08',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    lesson_id = result['lesson_id']
    try:
        # Нет посещения → ставим present=true → +1
        ok = repository.update_attendance_cell(lesson_id, student_fixture, True)
        assert ok is True
        assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')

        # true → false → -1
        repository.update_attendance_cell(lesson_id, student_fixture, False)
        assert lessons_done(group_fixture, student_fixture) == Decimal('0.0')

        # false → true снова → +1
        repository.update_attendance_cell(lesson_id, student_fixture, True)
        assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')
    finally:
        _delete_lesson(lesson_id)


def test_attendance_toggle_missing_lesson_returns_false(student_fixture):
    assert repository.update_attendance_cell(999_999_999, student_fixture, True) is False


def test_attendance_toggle_recomputes_payroll(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    """Переключение ячейки посещаемости пересчитывает present_count/payment
    в Payroll (не penalty — она про своевременность исходной записи)."""
    result = services.create_lesson_full({
        'lesson_date': '2026-03-08',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    lesson_id = result['lesson_id']
    try:
        before = repository.get_lesson_full(lesson_id)
        assert before['payroll']['present_count'] == 0
        assert before['payroll']['payment'] == Decimal('0.00')

        ok = repository.update_attendance_cell(lesson_id, student_fixture, True)
        assert ok is True

        after = repository.get_lesson_full(lesson_id)
        assert after['payroll']['present_count'] == 1
        # total_students=1, present=1 → small-group-full = 500
        assert after['payroll']['payment'] == Decimal('500.00')
    finally:
        _delete_lesson(lesson_id)


def test_attendance_toggle_blocked_when_no_paid_balance(
    group_fixture, teacher_id_fixture, student_fixture,
):
    """Ученик без оплаченных уроков (membership без payments) — переключить в
    present:true нельзя, поднимает UnpaidAttendanceBlocked, ничего не меняется."""
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO group_memberships (group_id, student_id, lessons_done, active) '
            'VALUES (%s, %s, 0, true) RETURNING id',
            [group_fixture, student_fixture],
        )
        membership_id = cur.fetchone()[0]

    result = services.create_lesson_full({
        'lesson_date': '2026-03-08',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    lesson_id = result['lesson_id']
    try:
        with pytest.raises(UnpaidAttendanceBlocked):
            repository.update_attendance_cell(lesson_id, student_fixture, True)
        with connection.cursor() as cur:
            cur.execute(
                'SELECT present FROM lesson_attendance WHERE lesson_id = %s AND student_id = %s',
                [lesson_id, student_fixture],
            )
            assert cur.fetchone()[0] is False
    finally:
        _delete_lesson(lesson_id)
        with connection.cursor() as cur:
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])


# ---------------------------------------------------------------------------
# list_lessons
# ---------------------------------------------------------------------------

def test_list_lessons_envelope_and_filter(group_fixture, teacher_id_fixture):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-09',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    lesson_id = result['lesson_id']
    try:
        list_result = repository.list_lessons(filters={'group_id': group_fixture})
        assert set(list_result.keys()) == {'rows', 'total', 'page', 'page_size'}
        assert list_result['total'] == 1
        assert list_result['rows'][0]['id'] == lesson_id
        assert list_result['rows'][0]['group_name'] == '__les_test_group__'
        assert list_result['rows'][0]['lesson_date'] == datetime.date(2026, 3, 9)
    finally:
        _delete_lesson(lesson_id)


def test_list_lessons_invalid_sort_by_falls_back(group_fixture, teacher_id_fixture):
    # Невалидный sort_by → тихий fallback (как Express paginate), без ошибки.
    result = services.create_lesson_full({
        'lesson_date': '2026-03-10',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    lesson_id = result['lesson_id']
    try:
        list_result = repository.list_lessons(
            sort_by='; DROP TABLE lessons; --',
            filters={'group_id': group_fixture},
        )
        assert list_result['total'] == 1
    finally:
        _delete_lesson(lesson_id)
```

- [ ] **Step 8: Fix `test_lessons_orm_smoke.py`** — these tests use raw
  `Group`/`Teacher`/`Student` ORM creation with NO payment (`_seed()` helper)
  and call the now-deleted `repository.create_lesson_full` directly. Replace
  the whole file content:

```python
"""
Smoke-тесты слоя lessons (раздел 09) — сеют минимальные данные и проверяют
критичные инварианты write-путей, которые в пустой тестовой БД иначе
пропускаются (no data):
  • half-lesson: duration 45 → шаг 0.5; иначе 1;
  • lessons_done корректируется в той же транзакции (create/delete/toggle);
  • get_lesson_full / list_lessons собирают joined-поля и attendance;
  • payroll всегда считается сервером (services.create_lesson_full → record_lesson).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db.models.functions import Now

from apps.directions.models import Direction
from apps.groups.models import Group
from apps.lessons import repository, services
from apps.memberships.models import GroupMembership
from apps.payments.models import Payment
from apps.students.models import Student
from apps.teachers.models import Teacher


def _seed(duration: int = 90):
    d = Direction.objects.create(name=f'ORM-DIR-{duration}', is_individual=False)
    t = Teacher.objects.create(name=f'ORM-T-{duration}', created_at=Now())
    g = Group.objects.create(
        name=f'ORM-G-{duration}', direction_id=d.id, teacher_id=t.id,
        is_individual=False, lesson_duration_minutes=duration, lessons_per_week=1,
        created_at=Now(),
    )
    s1 = Student.objects.create(full_name=f'ORM-S1-{duration}', created_at=Now())
    s2 = Student.objects.create(full_name=f'ORM-S2-{duration}', created_at=Now())
    GroupMembership.objects.create(group_id=g.id, student_id=s1.id, lessons_done=0)
    GroupMembership.objects.create(group_id=g.id, student_id=s2.id, lessons_done=0)
    return d, t, g, s1, s2


def _seed_payment(student_id: int, direction_id: int) -> None:
    """Оплата на 8 уроков — иначе present:true блокируется (assert_students_paid)."""
    Payment.objects.create(
        student_id=student_id, direction_id=direction_id, subscriptions_count=2,
        lessons_count=8, unit_price=1000, total_amount=8000,
        paid_at='2026-01-01', created_by='test',
    )


def _lessons_done(group_id, student_id) -> Decimal:
    return GroupMembership.objects.get(group_id=group_id, student_id=student_id).lessons_done


@pytest.mark.django_db
def test_create_lesson_full_increments_present_full_lesson():
    d, t, g, s1, s2 = _seed(duration=90)
    _seed_payment(s1.id, d.id)
    result = services.create_lesson_full({
        'lesson_date': '2026-01-10', 'teacher_id': t.id, 'group_id': g.id,
        'lesson_number': 1, 'lesson_duration_minutes': 90, 'lesson_type': 'regular',
        'attendance': [
            {'student_id': s1.id, 'present': True},
            {'student_id': s2.id, 'present': False},
        ],
    })
    lid = result['lesson_id']
    assert isinstance(lid, int)
    # present → +1, absent → без изменений
    assert _lessons_done(g.id, s1.id) == Decimal('1.0')
    assert _lessons_done(g.id, s2.id) == Decimal('0.0')

    full = repository.get_lesson_full(lid)
    assert full['group_name'] == g.name
    assert full['teacher_name'] == t.name
    assert len(full['attendance']) == 2
    assert full['payroll']['present_count'] == 1
    # total_students=2, present=1 → малая группа, не все пришли → smallPartial = 300
    assert full['payroll']['payment'] == Decimal('300.00')


@pytest.mark.django_db
def test_create_lesson_full_half_lesson_step():
    d, t, g, s1, s2 = _seed(duration=45)
    _seed_payment(s1.id, d.id)
    services.create_lesson_full({
        'lesson_date': '2026-01-11', 'teacher_id': t.id, 'group_id': g.id,
        'lesson_number': 1, 'lesson_duration_minutes': 45, 'lesson_type': 'regular',
        'attendance': [{'student_id': s1.id, 'present': True}],
    })
    # half-lesson: present → +0.5
    assert _lessons_done(g.id, s1.id) == Decimal('0.5')


@pytest.mark.django_db
def test_delete_lesson_full_rolls_back_lessons_done():
    d, t, g, s1, s2 = _seed(duration=90)
    _seed_payment(s1.id, d.id)
    result = services.create_lesson_full({
        'lesson_date': '2026-01-12', 'teacher_id': t.id, 'group_id': g.id,
        'lesson_number': 1, 'lesson_duration_minutes': 90,
        'attendance': [{'student_id': s1.id, 'present': True}],
    })
    lid = result['lesson_id']
    assert _lessons_done(g.id, s1.id) == Decimal('1.0')
    assert repository.delete_lesson_full(lid) is True
    assert _lessons_done(g.id, s1.id) == Decimal('0.0')
    assert repository.get_lesson_full(lid) is None


@pytest.mark.django_db
def test_update_attendance_cell_toggles_delta():
    d, t, g, s1, s2 = _seed(duration=90)
    _seed_payment(s1.id, d.id)
    result = services.create_lesson_full({
        'lesson_date': '2026-01-13', 'teacher_id': t.id, 'group_id': g.id,
        'lesson_number': 1, 'lesson_duration_minutes': 90,
        'attendance': [{'student_id': s1.id, 'present': False}],
    })
    lid = result['lesson_id']
    assert _lessons_done(g.id, s1.id) == Decimal('0.0')
    # false → true: +1
    assert repository.update_attendance_cell(lid, s1.id, True) is True
    assert _lessons_done(g.id, s1.id) == Decimal('1.0')
    # true → false: -1
    assert repository.update_attendance_cell(lid, s1.id, False) is True
    assert _lessons_done(g.id, s1.id) == Decimal('0.0')
    # GREATEST(...,0): повторный false не уводит в минус
    assert repository.update_attendance_cell(lid, s1.id, False) is True
    assert _lessons_done(g.id, s1.id) == Decimal('0.0')


@pytest.mark.django_db
def test_update_attendance_cell_missing_lesson_returns_false():
    assert repository.update_attendance_cell(999999, 1, True) is False
```

- [ ] **Step 9: Run the full lessons suite**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons -q`
Expected: all green. If `test_renewals_stage_sync.py`'s
`test_sync_ignored_when_no_open_deal` fails (uses `membership_fixture`, already
fixed in Task 4, so should be fine) — investigate if it wasn't already covered;
it should now pass because `membership_fixture` carries a real payment.

- [ ] **Step 10: Run the broader affected suite**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons apps/scheduling apps/payroll apps/renewals apps/groups -q`
Expected: all green.

- [ ] **Step 11: Commit**

```bash
git add journal_django/apps/lessons/repository.py journal_django/apps/lessons/services.py journal_django/apps/lessons/serializers.py journal_django/apps/lessons/views.py journal_django/apps/lessons/tests
git commit -m "feat(lessons): record_lesson shared core, admin create always links plan + computes payroll"
```

---

### Task 6: Rewire teacher SPA to use `record_lesson`

**Files:**
- Modify: `journal_django/apps/teacher_spa/services.py` (rewrite `submit_lesson`'s write step)
- Modify: `journal_django/apps/teacher_spa/repository.py` (delete dead functions)
- Test: `journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py` (should need NO changes — behavior contract unchanged; this step verifies that claim)

- [ ] **Step 1: Rewrite `submit_lesson`**

Replace the full `journal_django/apps/teacher_spa/services.py` content with:

```python
"""
TeacherSpaService — бизнес-логика teacher SPA.

Слой: View → Service (здесь) → Repository (ORM) для резолва входных данных;
запись самого урока делегируется в apps.lessons.services.record_lesson
(единое ядро — см. docs/superpowers/specs/2026-07-14-unify-lesson-recording-design.md).

Порт routes/teacher.js + services/teacher-repo.js.
"""
from __future__ import annotations

import warnings
from typing import Optional

from apps.accounts.repository import get_by_id_with_teacher
from apps.lessons.exceptions import UnpaidAttendanceBlocked
from apps.lessons.services import record_lesson
from apps.teacher_spa import repository
from apps.teacher_spa.calculator import format_msk_date


def get_current_teacher(account_id: int) -> Optional[str]:
    """
    Порт currentTeacher() из routes/teacher.js.

    Возвращает teacher_name или None если аккаунт не привязан к преподавателю.
    """
    acc = get_by_id_with_teacher(account_id)
    return acc['teacher_name'] if acc else None


def get_data(account_id: int) -> dict:
    """
    Порт POST /api/getData из routes/teacher.js.

    Возвращает {'teacher': str, 'data': groupDict} или {'_error': str, '_status': int}.
    """
    teacher = get_current_teacher(account_id)
    if not teacher:  # порт JS if(!teacher): None и пустая строка → не привязан
        return {'_error': 'Аккаунт не привязан к преподавателю', '_status': 403}

    unified = repository.read_all_students()
    teacher_data = unified['data'].get(teacher, {})
    return {'teacher': teacher, 'data': teacher_data}


def get_all_data(account_id: int) -> dict:
    """
    Порт POST /api/getAllData из routes/teacher.js.

    Возвращает {'teacher': str, 'data': все данные} или {'_error': ..., '_status': 403}.
    """
    teacher = get_current_teacher(account_id)
    if not teacher:  # порт JS if(!teacher): None и пустая строка → не привязан
        return {'_error': 'Аккаунт не привязан к преподавателю', '_status': 403}

    unified = repository.read_all_students()
    return {'teacher': teacher, 'data': unified['data']}


def get_group_progress(account_id: int, group_name: str) -> dict:
    """
    Матрица посещаемости группы для страницы группы в teacher SPA.

    Доступ: владелец группы ИЛИ преподаватель, которому назначено хотя бы одно
    НЕотменённое плановое занятие этой группы («Сменить преподавателя» в admin).
    Ответ — тот же контракт, что admin GET /api/admin/groups/:id/progress
    (apps.groups.services.get_group_progress), без дублирования логики.
    """
    from apps.groups import services as groups_services

    acc = get_by_id_with_teacher(account_id)
    teacher_id = acc['teacher_id'] if acc else None
    if not teacher_id:
        return {'_error': 'Аккаунт не привязан к преподавателю', '_status': 403}

    grp = repository.resolve_group_meta(group_name)
    if grp is None:
        return {'_error': 'Группа не найдена', '_status': 404}
    if grp['teacher_id'] != teacher_id and not repository.teacher_has_any_planned_lesson(
        grp['id'], teacher_id,
    ):
        return {'_error': 'Нет доступа к этой группе', '_status': 403}

    data = groups_services.get_group_progress(grp['id'])
    if data is None:
        return {'_error': 'Группа не найдена', '_status': 404}
    return data


def submit_lesson(account_id: int, validated: dict) -> dict:
    """
    Порт POST /api/submitLesson из routes/teacher.js (lines 38-139).

    Резолвит группу/учителя/тип урока/номер урока сам (teacher-специфичная
    логика — замена/перенос выводятся из planned_lessons, half-lesson из
    lesson_duration_minutes). Сама запись (Lesson+attendance+счётчики+Payroll+
    link_facts+балансовая проверка) — apps.lessons.services.record_lesson.

    Возвращает:
      {'success': True, 'payment': int, 'penalty': int, 'lessonNumber': float|int}
      {'success': False, 'error': str}   — ошибки без статуса 4xx (как Express)
      {'_error': str, '_status': 403}    — аккаунт не привязан к преподу
    """
    group = validated['group']
    date = validated['date']
    record_url = validated.get('recordUrl') or None
    students = validated['students']

    # Дата занятия жёстко зафиксирована на фронте (LessonForm не даёт её менять) —
    # это подстраховка от гонки состояний (устаревший кэш календаря) и прямых
    # запросов к API. Сравнение только по дню (строки 'YYYY-MM-DD' сравнимы
    # лексикографически), без учёта времени начала урока.
    if date > format_msk_date():
        return {
            'success': False,
            'error': 'Урок ещё не наступил — отметить его можно только в день занятия или позже.',
        }

    # 1. Auth — препод из сессии
    teacher = get_current_teacher(account_id)
    if not teacher:  # порт JS if(!teacher): None и пустая строка → не привязан
        return {'_error': 'Аккаунт не привязан к преподавателю', '_status': 403}

    # 2. Актуальное состояние (readAllStudents). Группа ищется по имени среди
    #    ВСЕХ преподавателей: своя → обычный урок; чужая допустима только если
    #    занятие назначено этому преподавателю админом (проверка в шаге 3).
    unified = repository.read_all_students()
    own_groups = unified['data'].get(teacher) or {}
    if group in own_groups:
        owner_name = teacher
    else:
        owner_name = next((t for t, gs in unified['data'].items() if group in gs), None)
    if owner_name is None:
        return {'success': False, 'error': 'Группа не найдена'}

    group_data = unified['data'][owner_name][group]

    # 3. Resolve IDs (submitter + группа + продолжительность). Делаем ДО расчётов:
    #    half-lesson теперь определяется СТРУКТУРНО (lesson_duration_minutes == 45),
    #    а не regex '/45\s*минут/' по имени группы (Ф4 — вывод regex из hot-path).
    ids = repository.resolve_ids(teacher, group)
    if not ids or not ids.get('submitter_teacher_id'):
        return {'success': False, 'error': 'Группа/преподаватель не найдены в БД'}

    lesson_teacher_id = ids['submitter_teacher_id']
    # Замена выводится СЕРВЕРОМ, а не флагом клиента: группа принадлежит другому
    # преподавателю. Право отметить чужой урок даёт ТОЛЬКО плановое занятие этой
    # группы на эту дату с teacher_id отправителя — его назначает админ через
    # «Сменить преподавателя» (клиентские isSubstitution/originalTeacher — 400
    # в SubmitLessonSerializer).
    is_substitution = (
        ids['group_owner_id'] is not None and ids['group_owner_id'] != lesson_teacher_id
    )
    if is_substitution and not repository.has_assigned_planned_lesson(
        ids['group_id'], date, lesson_teacher_id,
    ):
        return {'_error': 'Занятие этой группы вам не назначено', '_status': 403}
    original_teacher_id = ids['group_owner_id'] if is_substitution else None

    # 4. lesson_number — done = max(lessonsDone) по студентам группы, или 0 если пусто.
    is_half = ids['lesson_duration_minutes'] == 45
    step = 0.5 if is_half else 1
    group_students = group_data.get('students', [])
    done = max((s.get('lessonsDone') or 0 for s in group_students), default=0)
    # lessonNum = Math.round((done + step) * 10) / 10
    # (done + step) * 10 всегда целое (step кратен 0.5), поэтому round — no-op.
    raw = (done + step) * 10
    lesson_num = round(raw) / 10

    # 5. Mapping student_name → student_id (группа знает имена, admin шлёт id напрямую —
    #    поэтому это остаётся teacher_spa-специфичным шагом, не частью record_lesson).
    stud_rows = repository.resolve_students(ids['group_id'])
    by_name = {r['full_name']: r for r in stud_rows}

    attendance: list[dict] = []
    for s in students:
        meta = by_name.get(s['name'])
        if meta is None:
            warnings.warn(
                f'submitLesson: студент "{s["name"]}" не найден в group_memberships '
                f'для group_id={ids["group_id"]}',
                stacklevel=2,
            )
            continue
        attendance.append({'student_id': meta['student_id'], 'present': bool(s['present'])})

    # 6. subLabel — тип урока. Выводится СЕРВЕРОМ из плана (клиентский lessonType
    #    не принимается): замена — чужая группа (шаг 3); перенос — плановая строка
    #    этой группы/даты/препода перенесена НА эту дату (moved_from_date задан).
    if is_substitution:
        sub_label = 'substitution'
    elif repository.planned_lesson_is_moved(ids['group_id'], date, lesson_teacher_id):
        sub_label = 'reschedule'
    else:
        sub_label = 'regular'

    # 7. Запись — единое ядро (Lesson+attendance+счётчики+Payroll+link_facts+
    #    балансовая проверка+renewal-sync). Баланс — та же проверка, что и в
    #    admin SPA (UnpaidAttendanceBlocked), просто завёрнута в контракт teacher SPA.
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
    except UnpaidAttendanceBlocked as e:
        return {'success': False, 'error': str(e)}

    # lessonNumber: если целое → int, иначе float (JS-совместимость)
    lesson_number_out = int(lesson_num) if lesson_num == int(lesson_num) else lesson_num

    return {
        'success': True,
        'payment': result['payment'],
        'penalty': result['penalty'],
        'lessonNumber': lesson_number_out,
    }
```

- [ ] **Step 2: Delete dead functions from `apps/teacher_spa/repository.py`**

Delete `insert_lesson` (lines 279-295), `increment_counters` (lines 298-305),
`insert_attendance` (lines 308-327), `insert_payroll` (lines 330-339) — all
now unused (superseded by the equivalents added to `apps/lessons/repository.py`
in Task 5). Also remove the now-unused imports at the top: `from decimal import Decimal`
(only used by `increment_counters`), `from django.db.models.functions import Now`
(only used by `insert_lesson`), `Lesson, LessonAttendance` from
`apps.lessons.models` (only used by the deleted functions — double check
`resolve_students`/other remaining functions in this file don't need them
before removing), `Payroll` from `apps.payroll.models`. Keep `GroupMembership`
import if still used elsewhere in the file (check `resolve_students` — it
queries `GroupMembership`, so keep that import).

- [ ] **Step 3: Run the teacher_spa suite — should be UNCHANGED behavior**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa -q`
Expected: same pass count as before this task (all existing `submit_lesson`
tests — including `test_submit_lesson_links_fact_to_planned_lesson`,
`test_present_blocked_when_no_paid_balance`, `test_absent_allowed_without_paid_balance`
from earlier this session — must still pass unchanged, since the external
contract of `submit_lesson` didn't change, only its internals).

- [ ] **Step 4: Run the broader affected suite**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa apps/lessons apps/scheduling apps/payroll apps/renewals apps/groups apps/finances -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/teacher_spa/services.py journal_django/apps/teacher_spa/repository.py
git commit -m "refactor(teacher-spa): delegate lesson writes to apps.lessons.record_lesson"
```

---

### Task 7: `update_attendance_cell` — balance check + payroll recompute

**Files:**
- Modify: `journal_django/apps/lessons/repository.py:322-373` (`update_attendance_cell`)
- Modify: `journal_django/apps/lessons/views.py` (catch `UnpaidAttendanceBlocked` on the attendance-toggle view)
- Test: `journal_django/apps/lessons/tests/test_lessons_repository.py`, `test_lessons_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `journal_django/apps/lessons/tests/test_lessons_repository.py`, right
after `test_attendance_toggle_missing_lesson_returns_false`:

```python
def test_attendance_toggle_recomputes_payroll(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    """Переключение ячейки посещаемости пересчитывает present_count/payment
    в Payroll (не penalty — она про своевременность исходной записи)."""
    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-08',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    try:
        before = repository.get_lesson_full(lesson_id)
        assert before['payroll']['present_count'] == 0
        assert before['payroll']['payment'] == Decimal('0.00')

        ok = repository.update_attendance_cell(lesson_id, student_fixture, True)
        assert ok is True

        after = repository.get_lesson_full(lesson_id)
        assert after['payroll']['present_count'] == 1
        # total_students=1, present=1 → small-group-full = 500
        assert after['payroll']['payment'] == Decimal('500.00')
    finally:
        _delete_lesson(lesson_id)


def test_attendance_toggle_blocked_when_no_paid_balance(
    group_fixture, teacher_id_fixture, student_fixture,
):
    """Ученик без оплаченных уроков (membership без payments) — переключить
    в present:true нельзя, поднимает UnpaidAttendanceBlocked."""
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO group_memberships (group_id, student_id, lessons_done, active) '
            'VALUES (%s, %s, 0, true) RETURNING id',
            [group_fixture, student_fixture],
        )
        membership_id = cur.fetchone()[0]

    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-08',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    try:
        from apps.lessons.exceptions import UnpaidAttendanceBlocked
        with pytest.raises(UnpaidAttendanceBlocked):
            repository.update_attendance_cell(lesson_id, student_fixture, True)
        # Ничего не изменилось
        with connection.cursor() as cur:
            cur.execute(
                'SELECT present FROM lesson_attendance WHERE lesson_id = %s AND student_id = %s',
                [lesson_id, student_fixture],
            )
            assert cur.fetchone()[0] is False
    finally:
        _delete_lesson(lesson_id)
        with connection.cursor() as cur:
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])
```

Add `import pytest` at the top of the file if not already present (it already is,
per the existing `pytestmark = pytest.mark.django_db` line).

- [ ] **Step 2: Run to verify they fail**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_lessons_repository.py -k "test_attendance_toggle_recomputes_payroll or test_attendance_toggle_blocked_when_no_paid_balance" -q`
Expected: `test_attendance_toggle_recomputes_payroll` FAILS (`payment` stays 0,
never recomputed). `test_attendance_toggle_blocked_when_no_paid_balance` FAILS
(no exception raised, toggle just succeeds).

- [ ] **Step 3: Implement the fix**

Replace `update_attendance_cell` (currently lines 322-373):

```python
def update_attendance_cell(lesson_id: int, student_id: int, present: bool) -> bool:
    """
    Toggle present одной ячейки (UPSERT) + корректировка lessons_done дельтой +
    пересчёт Payroll.present_count/payment (не penalty — она про своевременность
    исходной записи урока, не должна меняться от последующей правки посещаемости).

    Бросает UnpaidAttendanceBlocked, если переключают В present:true ученика
    без оплаченных уроков (assert_students_paid) — ДО любых изменений.
    """
    if present:
        assert_students_paid([student_id])

    with transaction.atomic():
        ctx = (
            Lesson.objects
            .filter(id=lesson_id)
            .values('group_id', 'lesson_duration_minutes')
            .first()
        )
        if ctx is None:
            return False

        prev_present = (
            LessonAttendance.objects
            .filter(lesson_id=lesson_id, student_id=student_id)
            .values_list('present', flat=True)
            .first()
        )

        step = _step(ctx['lesson_duration_minutes'])
        nxt = bool(present)

        LessonAttendance.objects.bulk_create(
            [LessonAttendance(lesson_id=lesson_id, student_id=student_id, present=nxt)],
            update_conflicts=True,
            unique_fields=['lesson', 'student'],
            update_fields=['present'],   # ON CONFLICT DO UPDATE SET present=EXCLUDED.present
        )

        delta = Decimal('0')
        if prev_present is None and nxt:
            delta = step
        elif prev_present is False and nxt:
            delta = step
        elif prev_present is True and not nxt:
            delta = -step

        if delta != 0:
            GroupMembership.objects.filter(
                group_id=ctx['group_id'], student_id=student_id,
            ).update(lessons_done=Greatest(F('lessons_done') + delta, _ZERO))

            direction_id = Group.objects.filter(
                id=ctx['group_id']).values_list('direction_id', flat=True).first()
            transaction.on_commit(
                lambda: _sync_renewal_stage(student_id, direction_id))

        # Пересчёт Payroll: total/present из фактических attendance-строк.
        total_students = LessonAttendance.objects.filter(lesson_id=lesson_id).count()
        present_count = LessonAttendance.objects.filter(
            lesson_id=lesson_id, present=True,
        ).count()
        is_half = ctx['lesson_duration_minutes'] == 45
        payment = calculate_payment(total_students, present_count, is_half)
        Payroll.objects.filter(lesson_id=lesson_id).update(
            total_students=total_students,
            present_count=present_count,
            payment=payment,
        )

        return True
```

Add the import at the top of `apps/lessons/repository.py`:
```python
from apps.payroll.calculator import calculate_payment
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_lessons_repository.py -k "test_attendance_toggle_recomputes_payroll or test_attendance_toggle_blocked_when_no_paid_balance" -q`
Expected: both PASS.

- [ ] **Step 5: Catch the exception in the attendance-toggle view**

In `journal_django/apps/lessons/views.py`, update `AttendanceCellView.patch`
(currently lines 177-186):
```python
    def patch(self, request: Request, lesson_id: int, student_id: int) -> Response:
        serializer = AttendanceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ok = services.update_attendance_cell(
            lesson_id, student_id, serializer.validated_data['present']
        )
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response({'ok': True})
```
becomes:
```python
    def patch(self, request: Request, lesson_id: int, student_id: int) -> Response:
        serializer = AttendanceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            ok = services.update_attendance_cell(
                lesson_id, student_id, serializer.validated_data['present']
            )
        except UnpaidAttendanceBlocked as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response({'ok': True})
```
(`UnpaidAttendanceBlocked` is already imported at the top from Task 5, Step 5.)

- [ ] **Step 6: Run the full affected suite**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons apps/renewals -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/lessons/repository.py journal_django/apps/lessons/views.py journal_django/apps/lessons/tests/test_lessons_repository.py
git commit -m "fix(lessons): balance-check + payroll recompute on attendance toggle"
```

---

### Task 8: Frontend — `LessonEditor.tsx` stops computing payroll itself

**Files:**
- Modify: `journal_django/frontend/admin-src/src/components/lessons/LessonEditor.tsx`

- [ ] **Step 1: Remove client-side payment/penalty computation and the `payroll` field**

Remove the import (line 6): `import { calcPayment } from '../../lib/pricing';`

Replace `handleSave` (currently lines 64-114):
```tsx
  const handleSave = async () => {
    if (!date) { toast('Укажите дату', 'error'); return; }
    const attendance = members.map((m) => ({
      student_id: m.student_id,
      present: !!present[m.student_id],
    }));
    const presentCount = attendance.filter((a) => a.present).length;
    const totalStudents = attendance.length;

    if (totalStudents === 0) {
      toast('В группе нет учеников — урок зафиксировать нельзя', 'error');
      return;
    }
    if (presentCount === 0) {
      toast('Отметьте хотя бы одного присутствующего ученика', 'error');
      return;
    }

    const payment = calcPayment(totalStudents, presentCount, false);
    const penalty = 0;

    try {
      if (lesson) {
        await muts.update.mutateAsync({
          id: lesson.id,
          body: { lesson_date: date, record_url: url },
        });
        await Promise.all(attendance.map((a) =>
          muts.toggleAttendance.mutateAsync({
            lessonId: lesson.id, studentId: a.student_id, present: a.present,
          }),
        ));
        toast('Сохранено', 'ok');
      } else {
        await muts.create.mutateAsync({
          lesson_date: date,
          group_id: group.id,
          teacher_id: group.teacher_id,
          lesson_number: slot,
          lesson_duration_minutes: 90,
          lesson_type: 'regular',
          record_url: url,
          submitted_by_token: 'admin-imported',
          attendance,
          payroll: { total_students: totalStudents, present_count: presentCount, payment, penalty },
        });
        toast('Урок создан', 'ok');
      }
      onClose();
    } catch (err) { showError(err); }
  };
```
with:
```tsx
  const handleSave = async () => {
    if (!date) { toast('Укажите дату', 'error'); return; }
    const attendance = members.map((m) => ({
      student_id: m.student_id,
      present: !!present[m.student_id],
    }));
    const presentCount = attendance.filter((a) => a.present).length;
    const totalStudents = attendance.length;

    if (totalStudents === 0) {
      toast('В группе нет учеников — урок зафиксировать нельзя', 'error');
      return;
    }
    if (presentCount === 0) {
      toast('Отметьте хотя бы одного присутствующего ученика', 'error');
      return;
    }

    try {
      if (lesson) {
        await muts.update.mutateAsync({
          id: lesson.id,
          body: { lesson_date: date, record_url: url },
        });
        await Promise.all(attendance.map((a) =>
          muts.toggleAttendance.mutateAsync({
            lessonId: lesson.id, studentId: a.student_id, present: a.present,
          }),
        ));
        toast('Сохранено', 'ok');
      } else {
        await muts.create.mutateAsync({
          lesson_date: date,
          group_id: group.id,
          teacher_id: group.teacher_id,
          lesson_number: slot,
          lesson_duration_minutes: group.lesson_duration_minutes,
          lesson_type: 'regular',
          record_url: url,
          submitted_by_token: 'admin-imported',
          attendance,
        });
        toast('Урок создан', 'ok');
      }
      onClose();
    } catch (err) { showError(err); }
  };
```

(Server now always computes payment/penalty — see Task 5/6. `lesson_duration_minutes`
now uses the group's real duration instead of the hardcoded `90`, fixing a
pre-existing gap for 45-minute groups noticed while touching this file.)

- [ ] **Step 2: Typecheck**

Run: `cd journal_django/frontend/admin-src && npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Build**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Manual browser verification**

Start the dev stack and, in admin SPA → a group's «Уроки» tab:
1. Create a new lesson for a 45-minute group, mark one student present — confirm
   it saves (payment now computed server-side, not visible in this UI either way).
2. Try creating a lesson where the only present student has no paid balance —
   confirm the save fails with a toast showing the server's
   "У учеников без оплаченных уроков..." message (via `useApiError`/`showError`).
3. Confirm the group's calendar/schedule now shows this occurrence as done
   (Task 5's `link_facts` wiring) — previously it wouldn't have updated.

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/components/lessons/LessonEditor.tsx
git commit -m "feat(admin): server always computes lesson payroll, drop client calc"
```

---

### Task 9: Final full-suite verification + dead-code sweep

**Files:** none new — verification only.

- [ ] **Step 1: Grep for leftover references to removed functions**

Run:
```bash
cd journal_django
grep -rn "teacher_spa.repository import insert_lesson\|teacher_spa.repository import insert_attendance\|teacher_spa.repository import increment_counters\|teacher_spa.repository import insert_payroll" apps/ || echo "clean"
grep -rn "PayrollPartSerializer" apps/ || echo "clean"
grep -rn "apps.teacher_spa.calculator import calculate_payment\|apps.teacher_spa.calculator import calculate_penalty" apps/ || echo "clean"
```
Expected: all three print "clean" (no leftover references).

- [ ] **Step 2: Full backend suite**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa apps/lessons apps/payroll apps/scheduling apps/groups apps/finances apps/renewals apps/memberships -q`
Expected: all green.

- [ ] **Step 3: Frontend typecheck + build (both SPAs touched this plan)**

Run:
```bash
cd journal_django/frontend/admin-src && npm run typecheck && npm run build
cd journal_django/frontend/teacher-src && npm run typecheck && npm run build
```
Expected: both succeed (teacher-src wasn't modified in this plan, but verify
it still builds clean since `apps/teacher_spa` backend changed).

- [ ] **Step 4: Report**

Summarize to the user: which apps/files changed across all 9 tasks, confirm
full-suite status, and note anything explicitly left out of scope (legacy
Node scripts / `apps/sync/backfills`, `direction_history` importer, changelog
revert — per the design doc's "Вне охвата" section).
