# Student Status Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a coherent student-status lifecycle (`enrolled`/`not_enrolled`/`frozen`/`declined`) that, on status change, cascades to group memberships, individual-lesson scheduling, and the renewals CRM deal — driven from one service with two UI entry points.

**Architecture:** A single orchestration service `apps/students/services.change_student_status` runs inside one transaction and calls existing primitives in `apps.memberships` (soft-remove), `apps.scheduling` (cancel-window + regenerate-tail), and `apps.renewals.engine` (deal stage moves that bypass the manual-transition validator, exactly as `reopen_deal` already does). The renewals "Заморожен" stage becomes a full **auto-stage**: the transition validator is reworked so that **no** auto-stage is reachable or leavable by hand — only the engine moves deals in/out of them.

**Tech Stack:** Django 5 + DRF (managed models over PostgreSQL), pytest, React 19 + TanStack Query v5 (admin SPA). Tests run from `journal_django/` with `pytest` (settings `config.settings.test`, DB `journal_test`).

**Supersedes spec §2.2:** the spec proposed a `manual_entry_allowed` flag to keep `awaiting_payment`/`awaiting_renewal` manually reachable. The user's final decision is stricter and simpler: **all** auto-stages (progress + `awaiting_payment` + `awaiting_renewal` + `frozen`) are fully system-controlled and unreachable by hand. This plan implements that; no `manual_entry_allowed` flag is added. Task 4 updates the spec text to match.

**Important execution notes:**
- Run all `pytest`/`manage.py` commands with the worktree's dedicated venv, from the `journal_django/` directory.
- Never run `scripts/recreate_test_db.sh` (shared test DB, wipes seed data — see memory).
- Do **not** run `npm run build` for the frontend tasks — source edits + `tsc` typecheck only; the dist rebuild is a separate deploy step.
- The working tree has unrelated WIP. Stage only the files each task names; never `git add -A`.

---

## File Structure

**Backend — data model**
- `journal_django/apps/students/models.py` — swap `frozen_until_month` → `frozen_from`/`frozen_until`, rework CHECK constraints.
- `journal_django/apps/students/migrations/0009_add_frozen_dates.py` — add nullable date fields (new).
- `journal_django/apps/students/migrations/0010_backfill_frozen_dates.py` — convert existing month→date (new).
- `journal_django/apps/students/migrations/0011_drop_frozen_month.py` — drop old field + swap constraints (new).
- `journal_django/apps/students/serializers.py` — status serializers.
- `journal_django/apps/students/repository.py` — create/update/soft-delete field swap.

**Backend — renewals**
- `journal_django/apps/renewals/transitions.py` — new auto-stage lockout rule.
- `journal_django/apps/renewals/repository.py` — pass `from_is_auto` to validator.
- `journal_django/apps/renewals/engine.py` — `freeze_deal`, `decline_deal`, `resume_from_freeze`.
- `journal_django/apps/renewals/migrations/0010_frozen_autostage.py` — mark `frozen` stage `is_auto=True` (new).

**Backend — scheduling**
- `journal_django/apps/scheduling/planner.py` — pure `relay_from_date` tail re-lay.
- `journal_django/apps/scheduling/repository.py` — `freeze_individual_group`, `resume_individual_group`.

**Backend — orchestration + API**
- `journal_django/apps/students/services.py` — `change_student_status`, `resume_student`.
- `journal_django/apps/students/serializers.py` — `StudentStatusSerializer`, `StudentResumeSerializer`.
- `journal_django/apps/students/views.py` — `StudentStatusView`, `StudentResumeView`.
- `journal_django/apps/students/urls.py` — two routes.

**Frontend (source only, no build)**
- `journal_django/frontend/admin-src/src/lib/shared-types.ts` — `frozen_from`/`frozen_until`.
- `journal_django/frontend/admin-src/src/components/StatusBadge.tsx` — full-date label.
- `journal_django/frontend/admin-src/src/pages/students/StudentStatusModal.tsx` — status wizard (new).
- `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx` — wire buttons.

**Documentation**
- `docs/superpowers/specs/2026-07-17-student-status-lifecycle-design.md` — align §2.2.

---

## Phase 1 — Data model: frozen dates

### Task 1: Add `frozen_from`/`frozen_until` fields (keep old field)

**Files:**
- Modify: `journal_django/apps/students/models.py`
- Create: `journal_django/apps/students/migrations/0009_add_frozen_dates.py`

- [ ] **Step 1: Add the two nullable fields to the model**

In `journal_django/apps/students/models.py`, inside `class Student`, add right after the `frozen_until_month` line (line 41):

```python
    frozen_until_month = models.IntegerField(null=True, blank=True)
    frozen_from = models.DateField(null=True, blank=True)
    frozen_until = models.DateField(null=True, blank=True)
```

Do **not** touch the `Meta.constraints` block yet (constraints still reference `frozen_until_month`).

- [ ] **Step 2: Generate the migration**

Run (from `journal_django/`): `python manage.py makemigrations students --name add_frozen_dates`
Expected: creates `0009_add_frozen_dates.py` with two `AddField` operations. No constraint changes.

- [ ] **Step 3: Apply and verify**

Run: `python manage.py migrate students`
Expected: `Applying students.0009_add_frozen_dates... OK`

- [ ] **Step 4: Commit**

```bash
git add journal_django/apps/students/models.py journal_django/apps/students/migrations/0009_add_frozen_dates.py
git commit -m "feat(students): add frozen_from/frozen_until date fields"
```

---

### Task 2: Backfill existing frozen students (month → date)

**Files:**
- Create: `journal_django/apps/students/migrations/0010_backfill_frozen_dates.py`
- Test: `journal_django/apps/students/tests/test_frozen_backfill.py`

- [ ] **Step 1: Write the failing test**

Create `journal_django/apps/students/tests/test_frozen_backfill.py`:

```python
"""Проверка логики конвертации frozen_until_month → frozen_until (месяц+инференс года)."""
import datetime

import pytest

from apps.students.migrations import _frozen_backfill_util as util


def test_month_ge_current_stays_this_year():
    # today = 2026-03-10, месяц заморозки 6 (июнь) → 2026-06-01
    today = datetime.date(2026, 3, 10)
    assert util.infer_frozen_until(6, today) == datetime.date(2026, 6, 1)


def test_month_lt_current_rolls_to_next_year():
    # today = 2026-11-10, месяц заморозки 2 (февраль) → 2027-02-01
    today = datetime.date(2026, 11, 10)
    assert util.infer_frozen_until(2, today) == datetime.date(2027, 2, 1)


def test_month_equal_current_is_this_year():
    today = datetime.date(2026, 5, 1)
    assert util.infer_frozen_until(5, today) == datetime.date(2026, 5, 1)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest apps/students/tests/test_frozen_backfill.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.students.migrations._frozen_backfill_util`.

- [ ] **Step 3: Write the util module**

Create `journal_django/apps/students/migrations/_frozen_backfill_util.py`:

```python
"""Чистая логика инференса года для конвертации frozen_until_month → дата.

Отдельный модуль (а не тело миграции), чтобы покрыть логику unit-тестом:
«заморозка до месяца M» — ближайшее наступление 1-го числа месяца M, не раньше
текущего месяца (M >= текущий → этот год; M < текущий → следующий год)."""
from __future__ import annotations

import datetime


def infer_frozen_until(month: int, today: datetime.date) -> datetime.date:
    year = today.year if month >= today.month else today.year + 1
    return datetime.date(year, month, 1)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest apps/students/tests/test_frozen_backfill.py -v`
Expected: 3 passed.

- [ ] **Step 5: Write the data migration**

Create `journal_django/apps/students/migrations/0010_backfill_frozen_dates.py`:

```python
"""Конвертация frozen_until_month → frozen_from/frozen_until для существующих
замороженных учеников.

frozen_until — 1-е число ближайшего наступления месяца (_frozen_backfill_util).
frozen_from — best-effort = сегодня по МСК (точная дата начала паузы в старой
модели не хранилась). ПРОД: значения требуют ручной выверки после миграции
(см. docs/superpowers/specs/2026-07-17-student-status-lifecycle-design.md §2.1).
Обратимо: unwind обнуляет обе даты (frozen_until_month ещё существует)."""
from django.db import migrations

from apps.core.utils.dates import msk_today
from apps.students.migrations._frozen_backfill_util import infer_frozen_until


def forwards(apps, schema_editor):
    Student = apps.get_model('students', 'Student')
    today = msk_today()
    for s in Student.objects.filter(enrollment_status='frozen',
                                    frozen_until_month__isnull=False):
        s.frozen_until = infer_frozen_until(s.frozen_until_month, today)
        s.frozen_from = today
        s.save(update_fields=['frozen_until', 'frozen_from'])


def backwards(apps, schema_editor):
    Student = apps.get_model('students', 'Student')
    Student.objects.update(frozen_from=None, frozen_until=None)


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0009_add_frozen_dates'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
```

- [ ] **Step 6: Apply and verify**

Run: `python manage.py migrate students`
Expected: `Applying students.0010_backfill_frozen_dates... OK` (no-op if test DB has no frozen students).

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/students/migrations/0010_backfill_frozen_dates.py journal_django/apps/students/migrations/_frozen_backfill_util.py journal_django/apps/students/tests/test_frozen_backfill.py
git commit -m "feat(students): backfill frozen dates from legacy frozen_until_month"
```

---

### Task 3: Drop `frozen_until_month`, swap CHECK constraints

**Files:**
- Modify: `journal_django/apps/students/models.py`
- Modify: `journal_django/apps/students/repository.py`
- Modify: `journal_django/apps/students/serializers.py`
- Create: `journal_django/apps/students/migrations/0011_drop_frozen_month.py`
- Test: `journal_django/apps/students/tests/test_frozen_constraints.py`

- [ ] **Step 1: Write the failing test**

Create `journal_django/apps/students/tests/test_frozen_constraints.py`:

```python
"""DB CHECK-инварианты новой пары frozen_from/frozen_until на модели Student."""
import datetime

import pytest
from django.db import IntegrityError, transaction
from django.db.models.functions import Now

from apps.students.models import Student


@pytest.mark.django_db
def test_frozen_requires_both_dates():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Student.objects.create(
                full_name='__frz_no_dates__', enrollment_status='frozen',
                frozen_from=None, frozen_until=None, created_at=Now())


@pytest.mark.django_db
def test_non_frozen_forbids_dates():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Student.objects.create(
                full_name='__enr_with_dates__', enrollment_status='enrolled',
                frozen_from=datetime.date(2026, 1, 1),
                frozen_until=datetime.date(2026, 2, 1), created_at=Now())


@pytest.mark.django_db
def test_from_must_not_exceed_until():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Student.objects.create(
                full_name='__frz_bad_order__', enrollment_status='frozen',
                frozen_from=datetime.date(2026, 3, 1),
                frozen_until=datetime.date(2026, 2, 1), created_at=Now())


@pytest.mark.django_db
def test_valid_frozen_ok():
    s = Student.objects.create(
        full_name='__frz_ok__', enrollment_status='frozen',
        frozen_from=datetime.date(2026, 2, 1),
        frozen_until=datetime.date(2026, 4, 1), created_at=Now())
    assert s.id is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest apps/students/tests/test_frozen_constraints.py -v`
Expected: FAIL — `test_from_must_not_exceed_until` and `test_frozen_requires_both_dates` pass by accident only if constraints exist; they don't yet, so at least the ordering/both-dates tests FAIL (no constraint enforces them).

- [ ] **Step 3: Update the model — remove old field, swap constraints**

In `journal_django/apps/students/models.py`:

Remove the `frozen_until_month` line entirely, keeping:

```python
    frozen_from = models.DateField(null=True, blank=True)
    frozen_until = models.DateField(null=True, blank=True)
```

Replace the whole `Meta.constraints` list with:

```python
        constraints = [
            models.CheckConstraint(
                name='students_enrollment_status_check',
                condition=models.Q(enrollment_status__in=[
                    'enrolled', 'not_enrolled', 'frozen', 'declined']),
            ),
            # frozen ⟺ обе даты заданы; иначе обе NULL.
            models.CheckConstraint(
                name='students_frozen_dates_presence_check',
                condition=(
                    (models.Q(enrollment_status='frozen')
                     & models.Q(frozen_from__isnull=False)
                     & models.Q(frozen_until__isnull=False))
                    | (~models.Q(enrollment_status='frozen')
                       & models.Q(frozen_from__isnull=True)
                       & models.Q(frozen_until__isnull=True))
                ),
            ),
            models.CheckConstraint(
                name='students_frozen_dates_order_check',
                condition=(
                    models.Q(frozen_from__isnull=True)
                    | models.Q(frozen_until__gte=models.F('frozen_from'))
                ),
            ),
        ]
```

- [ ] **Step 4: Update repository create/update/soft-delete**

In `journal_django/apps/students/repository.py`:

In `create_student` (lines ~151-153), replace the `frozen_until_month=...` kwarg with:

```python
        frozen_from=data.get('frozen_from') or None,
        frozen_until=data.get('frozen_until') or None,
```

In `update_student`, replace the trailing `obj.frozen_until_month = data.get('frozen_until_month')` (line ~200) with:

```python
    # frozen_from/frozen_until — всегда перезаписываем (absent → None-сброс),
    # чтобы смена статуса на не-frozen гарантированно занулила даты.
    obj.frozen_from = data.get('frozen_from')
    obj.frozen_until = data.get('frozen_until')
```

In `soft_delete_student` (line ~208), replace `frozen_until_month=None` with:

```python
        enrollment_status='not_enrolled', frozen_from=None, frozen_until=None,
```

- [ ] **Step 5: Update serializers**

In `journal_django/apps/students/serializers.py`:

In `StudentReadSerializer`, replace `frozen_until_month = ...` (line 43) with:

```python
    frozen_from = DateStringField(allow_null=True)
    frozen_until = DateStringField(allow_null=True)
```

In `StudentWriteSerializer`: replace the `frozen_until_month` field (line 69) with:

```python
    frozen_from = DateStringField(allow_null=True, required=False)
    frozen_until = DateStringField(allow_null=True, required=False)
```

and update its `validate` method body to:

```python
    def validate(self, data: dict) -> dict:
        """frozen ⟺ обе даты заданы. Пропускаем, если статус не передан."""
        status = data.get('enrollment_status')
        if status is None:
            return data
        has_dates = data.get('frozen_from') is not None and data.get('frozen_until') is not None
        if (status == 'frozen') != has_dates:
            raise serializers.ValidationError(
                'frozen status requires frozen_from and frozen_until')
        return data
```

In `StudentUpdateSerializer`: replace the `frozen_until_month` field (line 115) with:

```python
    frozen_from = DateStringField(allow_null=True, required=False)
    frozen_until = DateStringField(allow_null=True, required=False)
```

- [ ] **Step 6: Generate the drop/constraint migration**

Run: `python manage.py makemigrations students --name drop_frozen_month`
Expected: creates `0011_drop_frozen_month.py` with `RemoveConstraint` (old `students_frozen_until_month_check`, `students_check`), `RemoveField` (`frozen_until_month`), `AddConstraint` (the three new ones). Verify the generated file removes the field and adds the three constraints.

- [ ] **Step 7: Apply and run the constraint + repository tests**

Run:
```
python manage.py migrate students
pytest apps/students/tests/test_frozen_constraints.py apps/students/tests/test_students_repository.py apps/students/tests/test_students_api.py -v
```
Expected: `test_frozen_constraints.py` 4 passed. If `test_students_repository.py`/`test_students_api.py` reference `frozen_until_month`, they will FAIL — fix each reference to the new fields (rename `frozen_until_month` assertions/inputs to `frozen_from`/`frozen_until` with real dates) in the same commit, then re-run until green.

- [ ] **Step 8: Fix remaining backend references to `frozen_until_month`**

Search and update every non-migration backend reference:
Run: `git grep -n "frozen_until_month" -- journal_django/apps ':!*/migrations/*'`
Expected callers to update: `apps/changelog/summary.py` (field label map), `apps/sync/backfills/students.py` + its test. For `changelog/summary.py`, replace the `frozen_until_month` label entry with two entries `frozen_from`/`frozen_until` (Russian labels e.g. `'Заморожен с'`, `'Заморожен до'`). For `sync/backfills/students.py`, map the legacy sheet value into `frozen_until`/`frozen_from` or drop it if the backfill no longer applies — keep behavior minimal, and update its test to match. Re-run the affected app tests until green.

- [ ] **Step 9: Commit**

```bash
git add journal_django/apps/students/models.py journal_django/apps/students/repository.py journal_django/apps/students/serializers.py journal_django/apps/students/migrations/0011_drop_frozen_month.py journal_django/apps/students/tests/ journal_django/apps/changelog/summary.py journal_django/apps/sync/
git commit -m "feat(students): replace frozen_until_month with frozen_from/frozen_until + constraints"
```

---

## Phase 2 — Renewals: frozen as auto-stage + transition lockout

### Task 4: Rework transition rule — no auto-stage reachable by hand

**Files:**
- Modify: `journal_django/apps/renewals/transitions.py`
- Modify: `journal_django/apps/renewals/repository.py:130-131`
- Modify: `journal_django/apps/renewals/tests/test_transitions.py`
- Modify: `journal_django/apps/renewals/tests/test_api_write.py`
- Modify: `docs/superpowers/specs/2026-07-17-student-status-lifecycle-design.md`

- [ ] **Step 1: Write/replace the failing unit tests**

Replace the body of `journal_django/apps/renewals/tests/test_transitions.py` with (keeping its imports):

```python
"""Правило переходов: НИ ОДНА авто-стадия не достижима и не покидается руками —
их двигает только движок. Ручные decision→decision/won/lost — при завершённом цикле."""
from apps.renewals.transitions import is_allowed


def test_cannot_move_onto_any_auto_stage():
    # decision-авто (Ждём оплату/Ждём продление/Заморожен) — руками нельзя
    assert not is_allowed(from_kind='decision', to_kind='decision',
                          to_is_auto=True, cycle_completed=True)
    # progress-авто — тоже нельзя
    assert not is_allowed(from_kind='decision', to_kind='progress',
                          to_is_auto=True, cycle_completed=True)


def test_cannot_move_off_auto_stage_even_to_lost():
    # с авто-стадии (напр. Урок 1) руками никуда, включая Ушёл
    assert not is_allowed(from_kind='progress', from_is_auto=True,
                          to_kind='lost', to_is_auto=False, cycle_completed=True)


def test_manual_decision_to_lost_allowed_anytime():
    assert is_allowed(from_kind='decision', from_is_auto=False,
                      to_kind='lost', to_is_auto=False, cycle_completed=False)


def test_manual_decision_to_decision_needs_completed_cycle():
    assert not is_allowed(from_kind='decision', from_is_auto=False,
                          to_kind='decision', to_is_auto=False, cycle_completed=False)
    assert is_allowed(from_kind='decision', from_is_auto=False,
                      to_kind='decision', to_is_auto=False, cycle_completed=True)


def test_from_terminal_never_allowed():
    assert not is_allowed(from_kind='won', to_kind='decision', cycle_completed=True)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest apps/renewals/tests/test_transitions.py -v`
Expected: FAIL — `is_allowed()` has no `from_is_auto` kwarg (`TypeError`).

- [ ] **Step 3: Rewrite the validator**

Replace `is_allowed` and `assert_allowed` in `journal_django/apps/renewals/transitions.py` with:

```python
def is_allowed(*, from_kind: str, to_kind: str,
               from_is_auto: bool = False, to_is_auto: bool = False,
               cycle_completed: bool = True) -> bool:
    """
    Авто-стадии (is_auto) двигает ТОЛЬКО движок по событиям. Руками:
    - на авто-стадию встать нельзя (to_is_auto) — прогресс, «Ждём оплату»,
      «Ждём продление», «Заморожен»;
    - с авто-стадии уйти нельзя (from_is_auto) — даже в «Ушёл»; отказ
      оформляется сменой статуса ученика (engine.decline_deal).
    Ручные decision-стадии («Думает», «Игнорит», кастомные) двигаются как раньше:
    в другую ручную decision / «Продлён» — при завершённом цикле; «Ушёл» — всегда.

    Решение пользователя 2026-07-17 (ужесточает прежнее decision+is_auto→True).
    """
    if from_kind in _TERMINAL:
        return False
    if from_is_auto:
        return False
    if to_is_auto:
        return False
    if to_kind == 'progress':
        return False
    if not cycle_completed:
        return to_kind == 'lost'
    return to_kind in {'decision', 'won', 'lost'}


def assert_allowed(*, from_kind: str, to_kind: str,
                   from_is_auto: bool = False, to_is_auto: bool = False,
                   cycle_completed: bool = True) -> None:
    if not is_allowed(from_kind=from_kind, to_kind=to_kind,
                      from_is_auto=from_is_auto, to_is_auto=to_is_auto,
                      cycle_completed=cycle_completed):
        raise InvalidTransition(f'Переход {from_kind} → {to_kind} запрещён')
```

- [ ] **Step 4: Pass `from_is_auto` from move_deal**

In `journal_django/apps/renewals/repository.py`, update the `assert_allowed(...)` call (lines 130-131) to:

```python
        assert_allowed(from_kind=from_stage.kind, to_kind=to_stage.kind,
                       from_is_auto=from_stage.is_auto, to_is_auto=to_stage.is_auto,
                       cycle_completed=engine.cycle_completed(deal))
```

- [ ] **Step 5: Run the transition unit tests**

Run: `pytest apps/renewals/tests/test_transitions.py -v`
Expected: all passed.

- [ ] **Step 6: Update the API write tests to the new rule**

In `journal_django/apps/renewals/tests/test_api_write.py`, the deals start on auto-stage `no_lesson_yet`, so any manual `move` is now blocked (409). Update:
- `test_move_to_decision`: change target from `awaiting_payment` (now auto, blocked) to the manual decision stage `thinking`, and expect **409** (deal is on an auto-stage `no_lesson_yet`, can't leave by hand). Rename to `test_move_off_auto_stage_blocked`.
- `test_move_from_terminal_409`: this moved to `churned` first via API — but `churned` (lost) from an auto-stage is now also blocked. Replace the setup: use `engine.decline_deal(sid)` (Task 6) to reach `lost`, then assert a subsequent manual `move` to `thinking` returns 409.
- `test_move_onto_progress_stage_409`: keep — still 409, but drop the second half that first moves to `awaiting_payment` (no longer reachable); assert only the direct move to `lesson_1` is 409.
- `test_move_off_progress_stage_to_lost_allowed`: **delete** — this path is intentionally removed (lost now goes through status change).

Run: `pytest apps/renewals/tests/test_api_write.py -v`
Expected: all passed (after Task 6 exists; if running before Task 6, temporarily xfail the `decline_deal` reference and revisit — prefer implementing Task 6 first if executing out of order).

- [ ] **Step 7: Align the spec text**

In `docs/superpowers/specs/2026-07-17-student-status-lifecycle-design.md` §2.2, replace the `manual_entry_allowed` paragraph with a note that all auto-stages are fully system-controlled and the validator blocks manual entry/exit for any `is_auto` stage (no extra flag). Keep it to ~4 lines.

- [ ] **Step 8: Commit**

```bash
git add journal_django/apps/renewals/transitions.py journal_django/apps/renewals/repository.py journal_django/apps/renewals/tests/test_transitions.py journal_django/apps/renewals/tests/test_api_write.py docs/superpowers/specs/2026-07-17-student-status-lifecycle-design.md
git commit -m "feat(renewals): lock all auto-stages from manual moves (in and out)"
```

---

### Task 5: Seed `frozen` stage as auto-stage

**Files:**
- Create: `journal_django/apps/renewals/migrations/0010_frozen_autostage.py`
- Test: `journal_django/apps/renewals/tests/test_seed.py`

- [ ] **Step 1: Write the failing test**

Append to `journal_django/apps/renewals/tests/test_seed.py`:

```python
@pytest.mark.django_db
def test_frozen_stage_is_auto():
    from apps.renewals.models import RenewalPipeline, RenewalStage
    pipe = RenewalPipeline.objects.get(is_default=True)
    frozen = RenewalStage.objects.get(pipeline=pipe, key='frozen')
    assert frozen.is_auto is True
    assert frozen.kind == 'decision'
```

(Ensure `import pytest` is present at the top of the file.)

- [ ] **Step 2: Run to verify it fails**

Run: `pytest apps/renewals/tests/test_seed.py::test_frozen_stage_is_auto -v`
Expected: FAIL — `frozen.is_auto is False`.

- [ ] **Step 3: Write the data migration**

Create `journal_django/apps/renewals/migrations/0010_frozen_autostage.py`:

```python
"""Стадия «Заморожен» (key='frozen') становится авто-стадией: в неё/из неё нельзя
войти вручную (transitions.is_allowed блокирует любые is_auto). Двигает её только
движок по смене статуса ученика (engine.freeze_deal / resume_from_freeze).
Идемпотентно; обратимо (is_auto=False)."""
from django.db import migrations


def forwards(apps, schema_editor):
    RenewalStage = apps.get_model('renewals', 'RenewalStage')
    RenewalStage.objects.filter(
        pipeline__is_default=True, key='frozen').update(is_auto=True)


def backwards(apps, schema_editor):
    RenewalStage = apps.get_model('renewals', 'RenewalStage')
    RenewalStage.objects.filter(
        pipeline__is_default=True, key='frozen').update(is_auto=False)


class Migration(migrations.Migration):

    dependencies = [
        ('renewals', '0009_rename_lesson_progress_stages'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
```

- [ ] **Step 4: Apply and verify**

Run:
```
python manage.py migrate renewals
pytest apps/renewals/tests/test_seed.py -v
```
Expected: migration OK; seed tests passed.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals/migrations/0010_frozen_autostage.py journal_django/apps/renewals/tests/test_seed.py
git commit -m "feat(renewals): mark frozen stage as system-controlled auto-stage"
```

---

### Task 6: Engine functions — freeze / decline / resume deal

**Files:**
- Modify: `journal_django/apps/renewals/engine.py`
- Test: `journal_django/apps/renewals/tests/test_freeze_deal.py`

- [ ] **Step 1: Write the failing tests**

Create `journal_django/apps/renewals/tests/test_freeze_deal.py`:

```python
"""Движковые переходы сделки при заморозке/отказе/выходе — в обход валидатора
(как reopen_deal). freeze_deal → 'frozen'; decline_deal → терминальный 'lost';
resume_from_freeze → расчётная авто-стадия по attended/balance."""
import pytest

from apps.renewals import engine
from apps.renewals.models import RenewalDeal, RenewalStage


def _stage_key(deal_id):
    return RenewalDeal.objects.get(id=deal_id).stage.key


@pytest.mark.django_db
def test_freeze_deal_moves_open_deal_to_frozen(make_student, make_direction):
    sid = make_student()
    deal = engine.ensure_deal(sid, cycle_no=1)
    engine.freeze_deal(sid)
    assert _stage_key(deal.id) == 'frozen'
    assert RenewalDeal.objects.get(id=deal.id).outcome_at is None


@pytest.mark.django_db
def test_freeze_deal_noop_without_open_deal(make_student):
    sid = make_student()
    engine.freeze_deal(sid)  # не падает без сделки


@pytest.mark.django_db
def test_decline_deal_closes_as_lost(make_student, make_direction):
    sid = make_student()
    deal = engine.ensure_deal(sid, cycle_no=1)
    engine.decline_deal(sid)
    row = RenewalDeal.objects.get(id=deal.id)
    assert row.stage.kind == 'lost'
    assert row.outcome_at is not None


@pytest.mark.django_db
def test_resume_from_freeze_returns_to_auto_stage(make_student, make_direction):
    sid = make_student()
    deal = engine.ensure_deal(sid, cycle_no=1)
    engine.freeze_deal(sid)
    assert _stage_key(deal.id) == 'frozen'
    engine.resume_from_freeze(sid)
    # attended=0, balance<=0 → 'no_lesson_yet' (первая прогресс-стадия) либо
    # 'awaiting_payment' если баланс<=0. Главное — ушли с 'frozen'.
    assert _stage_key(deal.id) != 'frozen'


@pytest.mark.django_db
def test_resume_noop_if_not_frozen(make_student, make_direction):
    sid = make_student()
    deal = engine.ensure_deal(sid, cycle_no=1)
    before = _stage_key(deal.id)
    engine.resume_from_freeze(sid)  # сделка не на 'frozen' → no-op
    assert _stage_key(deal.id) == before
```

Note: `make_student`/`make_direction` fixtures already exist in `apps/renewals/tests/conftest.py` (used by `test_api_write.py`).

- [ ] **Step 2: Run to verify it fails**

Run: `pytest apps/renewals/tests/test_freeze_deal.py -v`
Expected: FAIL — `engine` has no `freeze_deal`.

- [ ] **Step 3: Implement the three engine functions**

Append to `journal_django/apps/renewals/engine.py`:

```python
def _open_deal_for_update(student_id: int):
    """Открытая сделка ученika с блокировкой (самый поздний цикл). None если нет."""
    return (RenewalDeal.objects
            .select_for_update()
            .select_related('stage', 'pipeline')
            .filter(student_id=student_id, outcome_at__isnull=True)
            .order_by('-cycle_no').first())


@transaction.atomic
def freeze_deal(student_id: int, author_id: Optional[int] = None) -> Optional[RenewalDeal]:
    """Перевести открытую сделку ученика на авто-стадию 'frozen' напрямую (в обход
    move_deal/валидатора — как reopen_deal). No-op, если сделки нет или в воронке
    нет стадии 'frozen'. Идемпотентно (повторный вызов на 'frozen' ничего не пишет)."""
    deal = _open_deal_for_update(student_id)
    if deal is None:
        return None
    frozen = RenewalStage.objects.filter(pipeline=deal.pipeline, key='frozen').first()
    if frozen is None or deal.stage_id == frozen.id:
        return deal if frozen is not None else None
    from_stage = deal.stage
    deal.stage = frozen
    deal.stage_entered_at = timezone.now()
    deal.save(update_fields=['stage', 'stage_entered_at', 'updated_at'])
    RenewalActivity.objects.create(
        deal=deal, kind='system', from_stage=from_stage, to_stage=frozen,
        author_id=author_id, body='Заморозка (смена статуса ученика)')
    return deal


@transaction.atomic
def decline_deal(student_id: int, author_id: Optional[int] = None) -> Optional[RenewalDeal]:
    """Закрыть открытую сделку ученика как терминальную 'lost' («Ушёл») напрямую,
    в обход валидатора. No-op, если открытой сделки нет или нет lost-стадии."""
    deal = _open_deal_for_update(student_id)
    if deal is None:
        return None
    lost = _stage(deal.pipeline, kind='lost')
    if lost is None:
        return None
    from_stage = deal.stage
    deal.stage = lost
    deal.stage_entered_at = timezone.now()
    deal.outcome_at = timezone.now()
    deal.save(update_fields=['stage', 'stage_entered_at', 'outcome_at', 'updated_at'])
    RenewalActivity.objects.create(
        deal=deal, kind='system', from_stage=from_stage, to_stage=lost,
        author_id=author_id, body='Отказ (смена статуса ученика)')
    return deal


@transaction.atomic
def resume_from_freeze(student_id: int, author_id: Optional[int] = None) -> Optional[RenewalDeal]:
    """Выход из заморозки: если открытая сделка ученика стоит на 'frozen', вернуть её
    на РАСЧЁТНУЮ авто-стадию (та же _target_auto_stage, что при создании/reopen) по
    attended/balance. No-op, если сделки нет или она не на 'frozen'."""
    from apps.finances.repository import balance_for_student

    deal = _open_deal_for_update(student_id)
    if deal is None or deal.stage.key != 'frozen':
        return None
    auto = _auto_stages(deal.pipeline)
    progress_stages = _progress_stages(deal.pipeline)
    attended = _attended_total(student_id)
    balance = float(balance_for_student(student_id))
    target, _matured = _target_auto_stage(deal, attended, balance, auto, progress_stages)
    if target is None:
        return deal
    from_stage = deal.stage
    deal.stage = target
    deal.stage_entered_at = timezone.now()
    deal.save(update_fields=['stage', 'stage_entered_at', 'updated_at'])
    RenewalActivity.objects.create(
        deal=deal, kind='system', from_stage=from_stage, to_stage=target,
        author_id=author_id, body='Автопереход после выхода из заморозки')
    return deal
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest apps/renewals/tests/test_freeze_deal.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals/engine.py journal_django/apps/renewals/tests/test_freeze_deal.py
git commit -m "feat(renewals): engine freeze_deal/decline_deal/resume_from_freeze"
```

---

## Phase 3 — Scheduling: freeze / resume individual plan

### Task 7: Pure `relay_from_date` tail re-lay

**Files:**
- Modify: `journal_django/apps/scheduling/planner.py`
- Test: `journal_django/apps/scheduling/tests/test_planner_relay.py`

- [ ] **Step 1: Write the failing test**

Create `journal_django/apps/scheduling/tests/test_planner_relay.py`:

```python
"""Чистая перекладка хвоста курсовых строк на новые даты от resume_date по слоту.
seq/lesson_number сохраняются; moved_from_date обнуляется; порядок по seq."""
import datetime
from decimal import Decimal

from apps.scheduling.occurrences import PENDING, Slot
from apps.scheduling.planner import PlannedRow, relay_from_date


def _row(seq, d):
    return PlannedRow(seq=seq, lesson_number=Decimal(seq),
                      scheduled_date=d, scheduled_time=datetime.time(10, 0),
                      status=PENDING, moved_from_date=datetime.date(2000, 1, 1))


def test_relay_lays_tail_weekly_from_resume():
    # Слот: среда (Вс=0 → ср=3), 10:00. resume = среда 2026-08-05.
    slots = [Slot(day_of_week=3, start_time=datetime.time(10, 0),
                  effective_from=datetime.date(2000, 1, 1))]
    tail = [_row(5, datetime.date(2026, 7, 1)),
            _row(6, datetime.date(2026, 7, 8)),
            _row(7, datetime.date(2026, 7, 15))]
    out = relay_from_date(tail, resume_date=datetime.date(2026, 8, 5),
                          slots=slots, duration_minutes=90)
    assert [r.scheduled_date for r in out] == [
        datetime.date(2026, 8, 5), datetime.date(2026, 8, 12), datetime.date(2026, 8, 19)]
    assert [r.seq for r in out] == [5, 6, 7]
    assert all(r.moved_from_date is None for r in out)
    assert [r.lesson_number for r in out] == [Decimal(5), Decimal(6), Decimal(7)]


def test_relay_empty_tail_returns_empty():
    slots = [Slot(day_of_week=3, start_time=datetime.time(10, 0),
                  effective_from=datetime.date(2000, 1, 1))]
    assert relay_from_date([], resume_date=datetime.date(2026, 8, 5),
                           slots=slots, duration_minutes=90) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest apps/scheduling/tests/test_planner_relay.py -v`
Expected: FAIL — `cannot import name 'relay_from_date'`.

- [ ] **Step 3: Implement the pure function**

Append to `journal_django/apps/scheduling/planner.py` (it already imports `_walk`, `_step_for`, `Slot` indirectly via occurrences — add `_walk` to the existing import from `apps.scheduling.occurrences` at the top if missing):

```python
def relay_from_date(
    tail: list[PlannedRow],
    *,
    resume_date: datetime.date,
    slots: list[Slot],
    duration_minutes: int,
) -> list[PlannedRow]:
    """Переложить хвост курсовых строк (ordered by seq) на новые даты, разворачивая
    слот от resume_date включительно. i-я строка → i-е слот-занятие. seq/lesson_number
    сохраняются; moved_from_date обнуляется (разовые переносы схлопываются); status
    остаётся PENDING. Число нужных занятий = len(tail); генерируем ровно столько
    через occurrences._walk (total = N*step). Пустой хвост / нет слотов → [] / без сдвига."""
    if not tail or not slots:
        return [replace(r) for r in tail]
    ordered = sorted(tail, key=lambda r: (r.seq if r.seq is not None else 0))
    step = _step_for(duration_minutes)
    total_units = int(Decimal(len(ordered)) * step) + 1  # запас; берём первые N занятий
    occ = _walk(resume_date, slots, step, total_units,
                _far_future(resume_date, total_units, step))
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

Add `Slot` and `_walk` to the top import if not present:

```python
from apps.scheduling.occurrences import (
    PENDING, DONE,
    Slot, _offset_from_monday, _step_for, _walk,
)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest apps/scheduling/tests/test_planner_relay.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/scheduling/planner.py journal_django/apps/scheduling/tests/test_planner_relay.py
git commit -m "feat(scheduling): pure relay_from_date tail re-lay for freeze"
```

---

### Task 8: Repository `freeze_individual_group` / `resume_individual_group`

**Files:**
- Modify: `journal_django/apps/scheduling/repository.py`
- Test: `journal_django/apps/scheduling/tests/test_freeze_scheduling.py`

- [ ] **Step 1: Write the failing test**

Create `journal_django/apps/scheduling/tests/test_freeze_scheduling.py`:

```python
"""Заморозка индивид-группы: PENDING-строки в окне (>= frozen_from) отменяются/
перекладываются; extra (seq NULL) в окне → CANCELLED; курсовой хвост едет от
resume_date по слоту. Проведённые (done) и всё до frozen_from — неподвижны."""
import datetime

import pytest
from django.db import connection

from apps.scheduling import repository as sched_repo
from apps.scheduling.models import PlannedLesson
from apps.scheduling.occurrences import CANCELLED, DONE, PENDING


@pytest.fixture
def indiv_group():
    """Индивид-группа со слотом среда 10:00 и 4 плановыми строками (ср., еженедельно)."""
    ids = {}
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name, is_individual, active, total_lessons) "
                    "VALUES ('__frz_dir__', true, true, 8) RETURNING id")
        ids['dir'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name, active, created_at) "
                    "VALUES ('__frz_t__', true, NOW()) RETURNING id")
        ids['teacher'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, group_start_date, active, created_at) "
            "VALUES ('__frz_g__', %s, %s, true, 90, 1, DATE '2026-07-01', true, NOW()) RETURNING id",
            [ids['dir'], ids['teacher']])
        ids['group'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_schedule_slots (group_id, day_of_week, start_time, effective_from) "
            "VALUES (%s, 3, TIME '10:00', DATE '2000-01-01')", [ids['group']])
    now = datetime.datetime(2026, 7, 1, 12, 0)
    for seq, d in [(1, '2026-07-01'), (2, '2026-07-08'), (3, '2026-07-15'), (4, '2026-07-22')]:
        PlannedLesson.objects.create(
            group_id=ids['group'], seq=seq, lesson_number=seq,
            scheduled_date=d, scheduled_time=datetime.time(10, 0),
            teacher_id=ids['teacher'], status=PENDING, created_at=now, updated_at=now)
    # extra в окне заморозки
    PlannedLesson.objects.create(
        group_id=ids['group'], seq=None, lesson_number=None,
        scheduled_date='2026-07-10', scheduled_time=datetime.time(15, 0),
        teacher_id=ids['teacher'], status=PENDING, created_at=now, updated_at=now)
    yield ids
    with connection.cursor() as cur:
        cur.execute("DELETE FROM planned_lessons WHERE group_id=%s", [ids['group']])
        cur.execute("DELETE FROM group_schedule_slots WHERE group_id=%s", [ids['group']])
        cur.execute("DELETE FROM groups WHERE id=%s", [ids['group']])
        cur.execute("DELETE FROM teachers WHERE id=%s", [ids['teacher']])
        cur.execute("DELETE FROM directions WHERE id=%s", [ids['dir']])


@pytest.mark.django_db
def test_freeze_relays_tail_and_cancels_extra(indiv_group):
    gid = indiv_group['group']
    # Заморозка с 2026-07-08 до 2026-08-05 (среда). Окно: seq2,3,4 + extra 07-10.
    sched_repo.freeze_individual_group(
        gid, frozen_from=datetime.date(2026, 7, 8),
        resume_date=datetime.date(2026, 8, 5))

    rows = {r.seq: r for r in PlannedLesson.objects.filter(
        group_id=gid, seq__isnull=False).order_by('seq')}
    # seq1 (до окна) не двигается
    assert rows[1].scheduled_date == datetime.date(2026, 7, 1)
    # хвост seq2..4 переложен от 2026-08-05 еженедельно
    assert rows[2].scheduled_date == datetime.date(2026, 8, 5)
    assert rows[3].scheduled_date == datetime.date(2026, 8, 12)
    assert rows[4].scheduled_date == datetime.date(2026, 8, 19)
    # extra в окне отменён
    extra = PlannedLesson.objects.get(group_id=gid, seq__isnull=True,
                                      scheduled_date=datetime.date(2026, 7, 10))
    assert extra.status == CANCELLED


@pytest.mark.django_db
def test_freeze_keeps_done_rows(indiv_group):
    gid = indiv_group['group']
    PlannedLesson.objects.filter(group_id=gid, seq=2).update(status=DONE)
    sched_repo.freeze_individual_group(
        gid, frozen_from=datetime.date(2026, 7, 8),
        resume_date=datetime.date(2026, 8, 5))
    done = PlannedLesson.objects.get(group_id=gid, seq=2)
    assert done.status == DONE
    assert done.scheduled_date == datetime.date(2026, 7, 8)  # не тронут
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest apps/scheduling/tests/test_freeze_scheduling.py -v`
Expected: FAIL — `repository has no attribute 'freeze_individual_group'`.

- [ ] **Step 3: Implement the repository functions**

Append to `journal_django/apps/scheduling/repository.py`:

```python
def freeze_individual_group(
    group_id: int,
    *,
    frozen_from: datetime.date,
    resume_date: datetime.date,
) -> None:
    """Заморозка индивид-группы (одна транзакция):

    (а) extra/маркеры (seq IS NULL) в статусе pending/overdue с scheduled_date >=
        frozen_from → status=CANCELLED (доп.занятия/переносы в окне отменяются);
    (б) курсовые pending/overdue строки (seq задан) с scheduled_date >= frozen_from —
        «хвост» — перекладываются от resume_date по текущему открытому слоту
        (planner.relay_from_date), moved_from_date схлопывается.

    Проведённые (done) и всё до frozen_from — неподвижны. Слот берётся тот же, что
    у группы (slots_by_group); нет слота → хвост не двигаем (нельзя развернуть)."""
    now = msk_now()
    with transaction.atomic():
        # (а) отменяем extra/маркеры в окне
        PlannedLesson.objects.filter(
            group_id=group_id, seq__isnull=True,
            status__in=_MUTABLE_STATUSES, scheduled_date__gte=frozen_from,
        ).update(status=CANCELLED, updated_at=now)

        # (б) перекладываем курсовой хвост
        tail = list(
            PlannedLesson.objects
            .select_for_update()
            .filter(group_id=group_id, seq__isnull=False,
                    status__in=_MUTABLE_STATUSES, scheduled_date__gte=frozen_from)
            .order_by('seq')
        )
        if not tail:
            return
        g = (Group.objects.filter(id=group_id)
             .values('lesson_duration_minutes').first())
        if g is None:
            return
        slots = slots_by_group([group_id]).get(group_id, [])
        open_slots = [s for s in slots if s.effective_to is None]
        if not open_slots:
            return
        by_seq = {p.seq: p for p in tail}
        relaid = planner.relay_from_date(
            [_row_from_model(p) for p in tail],
            resume_date=resume_date,
            slots=open_slots,
            duration_minutes=g['lesson_duration_minutes'],
        )
        to_update = []
        for cr in relaid:
            p = by_seq[cr.seq]
            p.scheduled_date = cr.scheduled_date
            p.scheduled_time = cr.scheduled_time
            p.moved_from_date = None
            p.updated_at = now
            to_update.append(p)
        PlannedLesson.objects.bulk_update(
            to_update, ['scheduled_date', 'scheduled_time', 'moved_from_date', 'updated_at'])


def resume_individual_group(
    group_id: int,
    *,
    actual_resume_date: datetime.date,
    frozen_from: datetime.date,
) -> None:
    """Досрочный/плановый выход: заново переложить курсовой хвост (pending/overdue,
    scheduled_date >= frozen_from) от actual_resume_date. Идемпотентно с
    freeze_individual_group — та же перекладка хвоста, только другая стартовая дата.
    Отменённые в окне extra НЕ восстанавливаем (осознанно: доп.занятия разовые)."""
    freeze_individual_group(
        group_id, frozen_from=frozen_from, resume_date=actual_resume_date)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest apps/scheduling/tests/test_freeze_scheduling.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/scheduling/repository.py journal_django/apps/scheduling/tests/test_freeze_scheduling.py
git commit -m "feat(scheduling): freeze_individual_group / resume_individual_group"
```

---

## Phase 4 — Orchestration service + API

### Task 9: `change_student_status` orchestration service

**Files:**
- Modify: `journal_django/apps/students/services.py`
- Test: `journal_django/apps/students/tests/test_status_service.py`

- [ ] **Step 1: Write the failing tests**

Create `journal_django/apps/students/tests/test_status_service.py`:

```python
"""Оркестрация смены статуса: членства деактивируются, индив-хвост едет, сделка
уходит в нужную стадию. Заморозка → deal 'frozen'; отказ → deal 'lost'."""
import datetime

import pytest
from django.db import connection
from django.db.models.functions import Now

from apps.memberships.models import GroupMembership
from apps.renewals import engine
from apps.renewals.models import RenewalDeal
from apps.students import services
from apps.students.models import Student


@pytest.fixture
def group_student():
    """Групповой student + активный membership + открытая сделка."""
    ids = {}
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name, is_individual, active, total_lessons) "
                    "VALUES ('__st_dir__', false, true, 8) RETURNING id")
        ids['dir'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name, active, created_at) "
                    "VALUES ('__st_t__', true, NOW()) RETURNING id")
        ids['teacher'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, active, created_at) "
            "VALUES ('__st_g__', %s, %s, false, 90, 1, true, NOW()) RETURNING id",
            [ids['dir'], ids['teacher']])
        ids['group'] = cur.fetchone()[0]
    s = Student.objects.create(full_name='__st_stud__', enrollment_status='enrolled',
                               created_at=Now())
    ids['student'] = s.id
    m = GroupMembership.objects.create(group_id=ids['group'], student_id=s.id, active=True)
    ids['membership'] = m.id
    engine.ensure_deal(s.id, cycle_no=1)
    yield ids
    with connection.cursor() as cur:
        cur.execute("DELETE FROM renewal_activity WHERE deal_id IN "
                    "(SELECT id FROM renewal_deal WHERE student_id=%s)", [ids['student']])
        cur.execute("DELETE FROM renewal_deal WHERE student_id=%s", [ids['student']])
        cur.execute("DELETE FROM group_memberships WHERE id=%s", [ids['membership']])
        cur.execute("DELETE FROM students WHERE id=%s", [ids['student']])
        cur.execute("DELETE FROM groups WHERE id=%s", [ids['group']])
        cur.execute("DELETE FROM teachers WHERE id=%s", [ids['teacher']])
        cur.execute("DELETE FROM directions WHERE id=%s", [ids['dir']])


@pytest.mark.django_db
def test_freeze_group_student(group_student):
    sid = group_student['student']
    services.change_student_status(
        sid, 'frozen',
        frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5),
        membership_ids=[group_student['membership']], actor=None)
    s = Student.objects.get(id=sid)
    assert s.enrollment_status == 'frozen'
    assert s.frozen_from == datetime.date(2026, 7, 8)
    assert s.frozen_until == datetime.date(2026, 8, 5)
    assert GroupMembership.objects.get(id=group_student['membership']).active is False
    deal = RenewalDeal.objects.get(student_id=sid, outcome_at__isnull=True)
    assert deal.stage.key == 'frozen'


@pytest.mark.django_db
def test_decline_group_student(group_student):
    sid = group_student['student']
    services.change_student_status(
        sid, 'declined', membership_ids=[group_student['membership']], actor=None)
    s = Student.objects.get(id=sid)
    assert s.enrollment_status == 'declined'
    assert s.frozen_from is None and s.frozen_until is None
    assert GroupMembership.objects.get(id=group_student['membership']).active is False
    deal = RenewalDeal.objects.get(student_id=sid)
    assert deal.stage.kind == 'lost'
    assert deal.outcome_at is not None


@pytest.mark.django_db
def test_resume_student_reenrolls(group_student):
    sid = group_student['student']
    services.change_student_status(
        sid, 'frozen', frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5),
        membership_ids=[group_student['membership']], actor=None)
    services.resume_student(sid, actual_resume_date=datetime.date(2026, 8, 5), actor=None)
    s = Student.objects.get(id=sid)
    assert s.enrollment_status == 'enrolled'
    assert s.frozen_from is None and s.frozen_until is None
    deal = RenewalDeal.objects.get(student_id=sid, outcome_at__isnull=True)
    assert deal.stage.key != 'frozen'
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest apps/students/tests/test_status_service.py -v`
Expected: FAIL — `services has no attribute 'change_student_status'`.

- [ ] **Step 3: Implement the orchestration**

Append to `journal_django/apps/students/services.py` (add imports at top of file: `from django.db import transaction`):

```python
def _affected_memberships(student_id: int, membership_ids):
    """Активные членства ученика (id, group_id, is_individual), опц. по списку id."""
    from django.db.models import F
    from apps.memberships.models import GroupMembership
    qs = GroupMembership.objects.filter(student_id=student_id, active=True)
    if membership_ids is not None:
        qs = qs.filter(id__in=membership_ids)
    return list(qs.values('id', 'group_id', is_individual=F('group__is_individual')))


@transaction.atomic
def change_student_status(
    student_id: int,
    new_status: str,
    *,
    frozen_from=None,
    frozen_until=None,
    membership_ids=None,
    actor=None,
) -> bool:
    """Единая смена статуса ученика с каскадом (одна транзакция). Возвращает False,
    если ученика нет. Права/валидация — на уровне view/serializer.

    frozen: индив-членства → сдвиг хвоста (frozen_from..frozen_until), групповые →
    active=False; статус+даты проставляются; сделка → 'frozen' (engine.freeze_deal).
    declined: все выбранные членства → active=False, будущие pending отменяются;
    статус; сделка → 'lost' (engine.decline_deal).
    not_enrolled: как declined по членствам, но сделку не трогаем."""
    from apps.renewals import engine
    from apps.scheduling import repository as sched_repo
    from apps.students.models import Student

    student = Student.objects.filter(id=student_id).first()
    if student is None:
        return False

    memberships = _affected_memberships(student_id, membership_ids)

    if new_status == 'frozen':
        for m in memberships:
            if m['is_individual']:
                sched_repo.freeze_individual_group(
                    m['group_id'], frozen_from=frozen_from, resume_date=frozen_until)
            _deactivate_membership(m['id'])
        student.enrollment_status = 'frozen'
        student.frozen_from = frozen_from
        student.frozen_until = frozen_until
        student.save(update_fields=['enrollment_status', 'frozen_from', 'frozen_until'])
        engine.freeze_deal(student_id, author_id=_actor_id(actor))

    elif new_status in ('declined', 'not_enrolled'):
        for m in memberships:
            _cancel_future_plan(m['group_id'], m['is_individual'])
            _deactivate_membership(m['id'])
        student.enrollment_status = new_status
        student.frozen_from = None
        student.frozen_until = None
        student.save(update_fields=['enrollment_status', 'frozen_from', 'frozen_until'])
        if new_status == 'declined':
            engine.decline_deal(student_id, author_id=_actor_id(actor))

    else:  # enrolled — прямой возврат без каскада расписания (используйте resume_student)
        student.enrollment_status = 'enrolled'
        student.frozen_from = None
        student.frozen_until = None
        student.save(update_fields=['enrollment_status', 'frozen_from', 'frozen_until'])

    return True


@transaction.atomic
def resume_student(student_id: int, *, actual_resume_date, actor=None) -> bool:
    """Выход из заморозки (плановый/досрочный). Заново перекладывает индив-хвост от
    actual_resume_date, возвращает статус в enrolled, а сделку — на расчётную
    авто-стадию (engine.resume_from_freeze). False, если ученика нет / не заморожен."""
    from apps.renewals import engine
    from apps.scheduling import repository as sched_repo
    from apps.students.models import Student

    student = Student.objects.filter(id=student_id).first()
    if student is None or student.enrollment_status != 'frozen':
        return False
    frozen_from = student.frozen_from

    # Индив-членства могли быть деактивированы при заморозке — берём все, где
    # группа индивидуальная, чтобы переложить их хвост от фактической даты.
    from django.db.models import F
    from apps.memberships.models import GroupMembership
    indiv = list(GroupMembership.objects
                 .filter(student_id=student_id, group__is_individual=True)
                 .values('group_id'))
    for m in indiv:
        sched_repo.resume_individual_group(
            m['group_id'], actual_resume_date=actual_resume_date, frozen_from=frozen_from)

    student.enrollment_status = 'enrolled'
    student.frozen_from = None
    student.frozen_until = None
    student.save(update_fields=['enrollment_status', 'frozen_from', 'frozen_until'])
    engine.resume_from_freeze(student_id, author_id=_actor_id(actor))
    return True
```

Then the small helpers used above:

```python
def _deactivate_membership(membership_id: int) -> None:
    from apps.memberships.models import GroupMembership
    GroupMembership.objects.filter(id=membership_id).update(active=False)


def _cancel_future_plan(group_id: int, is_individual: bool) -> None:
    """Отменить будущие pending/overdue плановые строки индив-группы (без перегенерации).
    Для групповых расписание не трогаем (там нет персонального плана ученика)."""
    if not is_individual:
        return
    from apps.core.utils.dates import msk_today, msk_now
    from apps.scheduling.models import PlannedLesson
    from apps.scheduling.occurrences import CANCELLED, PENDING, OVERDUE
    PlannedLesson.objects.filter(
        group_id=group_id, status__in=(PENDING, OVERDUE),
        scheduled_date__gte=msk_today(),
    ).update(status=CANCELLED, updated_at=msk_now())


def _actor_id(actor) -> Optional[int]:
    """Account.id из actor (request.user) или None."""
    return getattr(actor, 'id', None) if actor is not None else None
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest apps/students/tests/test_status_service.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/students/services.py journal_django/apps/students/tests/test_status_service.py
git commit -m "feat(students): change_student_status / resume_student orchestration"
```

---

### Task 10: API endpoints + serializers + routes

**Files:**
- Modify: `journal_django/apps/students/serializers.py`
- Modify: `journal_django/apps/students/views.py`
- Modify: `journal_django/apps/students/urls.py`
- Test: `journal_django/apps/students/tests/test_status_api.py`

- [ ] **Step 1: Write the failing tests**

Create `journal_django/apps/students/tests/test_status_api.py`:

```python
"""API смены статуса: POST /status (frozen/declined/...), POST /resume. Права
IsManagerOrAdmin; frozen требует обе даты (400 иначе)."""
import datetime

import pytest
from django.db.models.functions import Now

from apps.students.models import Student

BASE = '/api/admin/students'


@pytest.mark.django_db
def test_freeze_requires_both_dates_400(admin_client):
    s = Student.objects.create(full_name='__api_frz__', enrollment_status='enrolled',
                               created_at=Now())
    resp = admin_client.post(f'{BASE}/{s.id}/status',
                             {'status': 'frozen', 'frozen_from': '2026-07-08'},
                             format='json')
    assert resp.status_code == 400
    Student.objects.filter(id=s.id).delete()


@pytest.mark.django_db
def test_status_change_declined_200(admin_client):
    s = Student.objects.create(full_name='__api_dec__', enrollment_status='enrolled',
                               created_at=Now())
    resp = admin_client.post(f'{BASE}/{s.id}/status', {'status': 'declined'}, format='json')
    assert resp.status_code == 200
    assert Student.objects.get(id=s.id).enrollment_status == 'declined'
    Student.objects.filter(id=s.id).delete()


@pytest.mark.django_db
def test_status_404_unknown_student(admin_client):
    resp = admin_client.post(f'{BASE}/99999999/status', {'status': 'declined'}, format='json')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_resume_requires_frozen(admin_client):
    s = Student.objects.create(full_name='__api_res__', enrollment_status='enrolled',
                               created_at=Now())
    resp = admin_client.post(f'{BASE}/{s.id}/resume',
                             {'actual_resume_date': '2026-08-05'}, format='json')
    assert resp.status_code == 404  # не заморожен → нечего размораживать
    Student.objects.filter(id=s.id).delete()
```

Note: `admin_client` fixture exists in `apps/renewals/tests/conftest.py`; confirm students tests have an equivalent (check `apps/students/tests/conftest.py`). If absent, add an `admin_client` fixture mirroring the renewals one.

- [ ] **Step 2: Run to verify it fails**

Run: `pytest apps/students/tests/test_status_api.py -v`
Expected: FAIL — 404/route not found for `/status`.

- [ ] **Step 3: Add serializers**

Append to `journal_django/apps/students/serializers.py`:

```python
class StudentStatusSerializer(serializers.Serializer):
    """Ввод POST /students/:id/status. frozen ⟺ обе даты; membership_ids опц."""
    status = serializers.ChoiceField(choices=ENROLLMENT_STATUS_CHOICES)
    frozen_from = DateStringField(required=False, allow_null=True)
    frozen_until = DateStringField(required=False, allow_null=True)
    membership_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True)

    def validate(self, data: dict) -> dict:
        if data['status'] == 'frozen':
            if not data.get('frozen_from') or not data.get('frozen_until'):
                raise serializers.ValidationError(
                    'frozen requires frozen_from and frozen_until')
            if data['frozen_from'] > data['frozen_until']:
                raise serializers.ValidationError('frozen_from must be <= frozen_until')
        else:
            if data.get('frozen_from') or data.get('frozen_until'):
                raise serializers.ValidationError(
                    'frozen_from/frozen_until only allowed for frozen status')
        return data


class StudentResumeSerializer(serializers.Serializer):
    """Ввод POST /students/:id/resume."""
    actual_resume_date = DateStringField()
```

- [ ] **Step 4: Add views**

Append to `journal_django/apps/students/views.py` (add serializer imports to the existing import group):

```python
class StudentStatusView(APIView):
    """POST /api/admin/students/:id/status — смена статуса с каскадом. 404 если нет."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        from apps.students.serializers import StudentStatusSerializer
        ser = StudentStatusSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        ok = services.change_student_status(
            pk, data['status'],
            frozen_from=data.get('frozen_from'),
            frozen_until=data.get('frozen_until'),
            membership_ids=data.get('membership_ids'),
            actor=request.user,
        )
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(services.get_student(pk))


class StudentResumeView(APIView):
    """POST /api/admin/students/:id/resume — выход из заморозки. 404 если нет/не заморожен."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        from apps.students.serializers import StudentResumeSerializer
        ser = StudentResumeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ok = services.resume_student(
            pk, actual_resume_date=ser.validated_data['actual_resume_date'],
            actor=request.user)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(services.get_student(pk))
```

- [ ] **Step 5: Add routes**

In `journal_django/apps/students/urls.py`, add the two view imports and two paths:

```python
from apps.students.views import (
    StudentBalanceView,
    StudentCommentDetailView,
    StudentCommentListView,
    StudentDetailView,
    StudentListCreateView,
    StudentRefundView,
    StudentResumeView,
    StudentStatsView,
    StudentStatusView,
)
```

Add to `urlpatterns` (after the refund path):

```python
    path('/<int:pk>/status', StudentStatusView.as_view(), name='students-status'),
    path('/<int:pk>/resume', StudentResumeView.as_view(), name='students-resume'),
```

- [ ] **Step 6: Run to verify it passes**

Run: `pytest apps/students/tests/test_status_api.py -v`
Expected: 4 passed.

- [ ] **Step 7: Run the full backend suites touched by this change**

Run: `pytest apps/students apps/renewals apps/scheduling apps/memberships -q`
Expected: all passed. Fix any regressions (especially renewals move tests) before committing.

- [ ] **Step 8: Commit**

```bash
git add journal_django/apps/students/serializers.py journal_django/apps/students/views.py journal_django/apps/students/urls.py journal_django/apps/students/tests/test_status_api.py journal_django/apps/students/tests/conftest.py
git commit -m "feat(students): status-change and resume API endpoints"
```

---

## Phase 5 — Frontend (source only, no build)

### Task 11: Types + StatusBadge full-date label

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/shared-types.ts`
- Modify: `journal_django/frontend/admin-src/src/components/StatusBadge.tsx`

- [ ] **Step 1: Update the shared type**

In `journal_django/frontend/admin-src/src/lib/shared-types.ts`, find the student shape (around line 95, `enrollment_status: EnrollmentStatus;`) and replace any `frozen_until_month` field with:

```typescript
  frozen_from: string | null;
  frozen_until: string | null;
```

If `frozen_until_month` does not appear in this file, add the two fields next to `enrollment_status`.

- [ ] **Step 2: Update StatusBadge to render the full date**

Replace `journal_django/frontend/admin-src/src/components/StatusBadge.tsx` with:

```tsx
import type { EnrollmentStatus } from '../lib/types';
import { ENROLLMENT_STATUS_LABELS } from '../lib/labels';

const MONTHS = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];

// Color stays on a single semantic axis: enrolled = positive, declined = negative,
// frozen = informational (info), not_enrolled = muted (neutral).
const STATUS_TONE: Record<EnrollmentStatus, 'positive' | 'negative' | 'info' | 'muted'> = {
  enrolled:     'positive',
  declined:     'negative',
  frozen:       'info',
  not_enrolled: 'muted',
};

interface StudentLike { enrollment_status?: string; frozen_until?: string | null; }

function formatFrozenUntil(iso: string): string {
  // iso = 'YYYY-MM-DD' (DateStringField). Форматируем «до 12 августа 2026».
  const [y, m, d] = iso.split('-').map(Number);
  return `до ${d} ${MONTHS[m - 1]} ${y}`;
}

export function StatusBadge({ row }: { row: StudentLike | string }) {
  const status = (typeof row === 'string' ? row : row.enrollment_status) as EnrollmentStatus;
  const safeStatus: EnrollmentStatus = STATUS_TONE[status] ? status : 'enrolled';
  const tone = STATUS_TONE[safeStatus];
  let label = ENROLLMENT_STATUS_LABELS[safeStatus];
  if (typeof row === 'object' && row.enrollment_status === 'frozen' && row.frozen_until) {
    label = `Заморожен · ${formatFrozenUntil(row.frozen_until)}`;
  }
  return (
    <span className={`status-badge status-badge--${tone}`}>
      {label}
    </span>
  );
}
```

- [ ] **Step 3: Typecheck**

Run (from `journal_django/frontend/admin-src/`): `npx tsc --noEmit`
Expected: no errors from `StatusBadge.tsx` / `shared-types.ts`. (Do NOT run `npm run build`.)

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/lib/shared-types.ts journal_django/frontend/admin-src/src/components/StatusBadge.tsx
git commit -m "feat(admin): StatusBadge renders frozen_until full date"
```

---

### Task 12: Status-change wizard modal + wire into StudentDetailPage

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/students/StudentStatusModal.tsx`
- Modify: `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx`

- [ ] **Step 1: Build the modal component**

Create `journal_django/frontend/admin-src/src/pages/students/StudentStatusModal.tsx`. Requirements (follow existing modal patterns in `pages/` — e.g. `PaymentModal.tsx` — for Dialog shell, `SelectInput`/`DateInput`/`Checkbox` from `components/form/`, and TanStack Query `useMutation`):

- Props: `{ studentId: number; open: boolean; onClose: () => void; memberships: Array<{ id: number; group_name: string; is_individual: boolean }>; initialStatus?: EnrollmentStatus }`.
- Step 1 — `SelectInput` bound to `ENROLLMENT_STATUS_OPTIONS`; below it a short helper text per status (enrolled/not_enrolled/frozen/declined) explaining the semantics (esp. «Не учится ≠ Заморожен»).
- Step 2 (only when `status === 'frozen'`) — two `DateInput`s `frozen_from` (default today) and `frozen_until`; inline error if `frozen_from > frozen_until`.
- Step 3 (for frozen/declined/not_enrolled) — `Checkbox` list of `memberships`, grouped «Индивидуальные» / «Групповые»; all checked by default. Selected ids feed `membership_ids`.
- Step 4 — summary line + a submit button. If frozen and any individual membership is selected, show a note «Плановые уроки индива будут сдвинуты; доп.занятия и переносы в окне будут отменены».
- Submit: `useMutation` → `POST /api/admin/students/${studentId}/status` with `{ status, frozen_from?, frozen_until?, membership_ids }`; on success invalidate the student detail + list queries and call `onClose()`.
- Use the project's `api<T>()` helper (same as other pages) and `X-CSRFToken` handling that helper already provides.

Keep it a single focused file (~150-200 lines). Match tokens/styles from `styles/tokens.css`; no hardcoded colors.

- [ ] **Step 2: Wire buttons into StudentDetailPage**

In `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx`:
- Import `StudentStatusModal` and `useState`.
- Near the `StatusBadge` render, add a «Изменить статус» button that opens the modal (pass the student's memberships from the stats/detail query already loaded on the page).
- When `student.enrollment_status === 'frozen'`, add a «Разморозить» button that opens a minimal resume dialog: one `DateInput` `actual_resume_date` (default `student.frozen_until`) → `POST /api/admin/students/${id}/resume`. This resume dialog can be a small inline component in the same file (~40 lines) or a second tiny modal — keep it simple.
- On either mutation success, invalidate the student detail query so the badge refreshes.

- [ ] **Step 3: Typecheck**

Run (from `journal_django/frontend/admin-src/`): `npx tsc --noEmit`
Expected: no errors. (Do NOT run `npm run build`.)

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/students/StudentStatusModal.tsx journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx
git commit -m "feat(admin): student status-change wizard + resume dialog"
```

---

### Task 13: Kanban drop → open status modal for frozen/churned

**Files:**
- Modify: the renewals board component under `journal_django/frontend/admin-src/src/pages/` (locate with `git grep -l "to_stage_id" journal_django/frontend/admin-src/src`).

- [ ] **Step 1: Locate the board drag-drop handler**

Run: `git grep -ln "to_stage_id\|move" journal_django/frontend/admin-src/src/pages` and open the renewals board page/component that performs the stage-move mutation on drop.

- [ ] **Step 2: Intercept drops onto auto/terminal stages**

In the drop handler, before calling the move mutation:
- If the target stage is an auto-stage (`is_auto === true`) that is NOT `frozen`/`churned` (i.e. progress / awaiting_*), **ignore the drop** (no-op; the API would 409 anyway) and optionally show a toast «Эта стадия управляется системой».
- If the target stage `key === 'frozen'`, open `StudentStatusModal` with `initialStatus='frozen'` for that card's student instead of calling move.
- If the target stage `kind === 'lost'` (key `churned`), open `StudentStatusModal` with `initialStatus='declined'` and ensure the modal's summary shows the «ученик будет отчислён из группы и переведён в „Отказался“» note.
- Only genuinely manual stages (`is_auto === false`, `kind === 'decision'/'won'`) proceed with the existing move mutation.

Reuse the `StudentStatusModal` from Task 12 (lift its state into the board page).

- [ ] **Step 3: Typecheck**

Run (from `journal_django/frontend/admin-src/`): `npx tsc --noEmit`
Expected: no errors. (Do NOT run `npm run build`.)

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages
git commit -m "feat(admin): kanban drop on frozen/churned opens status wizard"
```

---

## Final verification

- [ ] **Backend full suite**

Run (from `journal_django/`): `pytest -q`
Expected: all passed. Investigate and fix any failure before declaring done (do not skip).

- [ ] **Frontend typecheck**

Run (from `journal_django/frontend/admin-src/`): `npx tsc --noEmit`
Expected: clean. (The dist rebuild is a separate, manual deploy step — not part of this plan.)

- [ ] **Manual smoke (use the `verify` skill / `run` skill)**

Drive the real flow: freeze an individual student → confirm plan tail shifted and deal shows «Заморожен»; resume early → confirm tail re-laid from the earlier date and deal returned to a computed auto-stage; decline a group student → confirm membership deactivated and deal «Ушёл».
```
