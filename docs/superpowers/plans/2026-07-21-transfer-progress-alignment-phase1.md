# Transfer Progress Alignment — Phase 1 + 1b Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a student is transferred between groups, stop the receiving group from ever double-counting lessons the student already completed elsewhere — block attendance marking on lessons the student has already lived through (Phase 1), and let a brand-new/solo-member receiving group continue the course from the student's own progress instead of forcing them to "sleep" through their own first N lessons (Phase 1b).

**Architecture:** A single derived number, `B` (`apps.memberships.repository.cumulative_transferred_lessons` — already exists), is compared against each lesson's `lesson_number` at the two points attendance gets written (`record_lesson`, `update_attendance_cell`). No new state is needed for Phase 1 — it's a stateless predicate. Phase 1b adds exactly one persisted field (`Group.lesson_number_offset`) so a qualifying group's plan (`apps.scheduling`) and its sole member's `lessons_done` both start counting from `B` instead of `0`, reusing the scheduler's existing `start_seq`/`start_number` continuation mechanism (`planner.generate`) — no new scheduler machinery.

**Tech Stack:** Django 5 / DRF, PostgreSQL (managed models), React 19 (admin SPA + teacher SPA), pytest.

**Scope note:** This plan covers Phase 1 + 1b only, per `docs/superpowers/specs/2026-07-21-transfer-progress-alignment-design.md`. Phase 2 (blocking transfer until source-group absences are resolved) is a separate, later plan.

**Precision refinement over the spec:** the spec describes the lock predicate as `lesson_number ≤ floor(B)`. This plan uses the more precise `lesson_number ≤ B` (direct `Decimal`-to-`Decimal` comparison, no `floor`) — both values are already expressed in the same lesson-number unit (whole lessons or half-lesson steps of 0.5), so comparing directly is exact and correctly handles a half-lesson target group receiving a whole-lesson-history transfer (or vice versa) without rounding artifacts. Same intent as the spec, more precise arithmetic.

**Accepted limitation (documented, not fixed here):** `record_lesson` silently drops locked students from the attendance list before computing `total_students`/`present_count`/payroll. In the pathological case where *every* present student in a submission turns out to be locked, the lesson still gets created with an emptied attendance list (mirrors existing behavior for an all-absent lesson via the admin path). Not fixed in this plan — exceptionally rare given Phase 1b makes the common trigger (solo new group) a non-issue.

**~~Accepted limitation #2~~ — FIXED 2026-07-22 (was wrongly assessed as safe).** The user hit this in real use: А(18 уроков) → Б → В seeded В with `lesson_number_offset = 36` instead of 18, so В's course started at lesson №37 and **skipped 18 lessons of actual programme content**. The "failure direction is safe / only over-locks" reasoning below was **wrong**: it accounted for `locked_through` but overlooked that `_seed_transfer_continuation` derives the *offset itself* from the same `cumulative_transferred_lessons`, so the inflation propagates into course numbering, not just the lock window. The fix also turned out not to need the new `GroupMembership` flag predicted below — `group.lesson_number_offset > 0` **is** already an exact marker of "this membership's `lessons_done` is cumulative-inclusive", so the chain-walk now simply **stops** at the first continuation node instead of summing past it (`apps/memberships/repository.py::cumulative_transferred_lessons`). Regression test: `test_place_student.py::TestTransferContinuationPhase1b::test_second_consecutive_continuation_does_not_double_count` (verified to fail with `36.0 != 18.0` when the fix is disabled). `test_transfer_chain_sums_lessons_across_multiple_hops` now explicitly disqualifies Phase 1b on its intermediate hop, so it still tests genuine multi-hop summing across *plain* groups. Original (now-obsolete) assessment follows.

**Original text, superseded:** Phase 1b seeds a continuation membership's `lessons_done` to the *cumulative* total B (not a locally-earned count starting at 0). `cumulative_transferred_lessons`'s chain-walk assumes every membership's `lessons_done` is local-only and unconditionally sums it with every ancestor's — it has no way to know a given membership's `lessons_done` already *includes* its ancestors' history. Consequence: if a student is transferred into a second (or later) Phase-1b-qualifying solo/fresh group in the same chain (or, worse, a transfer chain cycles back through a reactivated membership that was itself Phase-1b-seeded), `cumulative_transferred_lessons`/`locked_through` over-counts, compounding with each such hop — confirmed by hand-tracing `apps/memberships/tests/test_transfer_membership.py::test_transfer_chain_cycle_does_not_hang`'s original scenario, where the naive result inflates to 70.0 instead of the "true" 10.0 (that test now explicitly disqualifies all three hops from Phase 1b via `has_course_lessons`/other-active-member guards, to keep testing cycle-termination in isolation from this interaction). **The failure direction is safe**: it only ever *over*-locks (blocks a returning student from being marked present for longer than strictly necessary) — it can never cause double-counted attendance/balance/payroll, since Phase 1 (Tasks 4-5) always compares `lesson_number` against this (possibly inflated) B using `<=`, and an inflated B only widens the locked range, never permits a lesson through that shouldn't be. A proper fix would require a way to distinguish "seeded/cumulative-inclusive" `lessons_done` from "locally-earned" `lessons_done` on `GroupMembership` (e.g. a new flag), which is out of scope for this plan. Trigger requires two-or-more consecutive transfers of the same student into solo/fresh/individual groups — considered rare enough to defer.

---

### Task 1: `Group.lesson_number_offset` field + migration

**Files:**
- Modify: `journal_django/apps/groups/models.py`
- Create: `journal_django/apps/groups/migrations/0005_group_lesson_number_offset.py` (generated)

- [ ] **Step 1: Add the field to the model**

In `journal_django/apps/groups/models.py`, inside `class Group(models.Model):`, add after `vk_chat`:

```python
    # Фаза 1b transfer-progress-alignment: если группа была продолжена курсом
    # переведённого ученика (см. apps.memberships.repository.place_student_in_group),
    # здесь хранится B (сколько уроков ученик уже отработал в старой группе) —
    # план группы (apps.scheduling) генерируется начиная с этого номера, не с 0.
    lesson_number_offset = models.DecimalField(max_digits=6, decimal_places=1, default=Decimal('0'))
```

Add `from decimal import Decimal` to the imports at the top of the file (next to `import datetime`).

- [ ] **Step 2: Generate the migration**

Run: `cd journal_django && ./.venv/Scripts/python.exe manage.py makemigrations groups`
Expected: `Migrations for 'groups': apps\groups\migrations\0005_group_lesson_number_offset.py - Add field lesson_number_offset to group`

- [ ] **Step 3: Apply to the test database**

Run: `cd journal_django && ./.venv/Scripts/python.exe manage.py migrate groups --settings=config.settings.test`
Expected: `Applying groups.0005_group_lesson_number_offset... OK`

- [ ] **Step 4: Commit**

```bash
git add journal_django/apps/groups/models.py journal_django/apps/groups/migrations/0005_group_lesson_number_offset.py
git commit -m "feat(groups): add lesson_number_offset field for transfer continuation"
```

---

### Task 2: `memberships.repository.locked_through` / `locked_through_map`

**Files:**
- Modify: `journal_django/apps/memberships/repository.py`
- Test: `journal_django/apps/memberships/tests/test_transfer_membership.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `journal_django/apps/memberships/tests/test_transfer_membership.py` (reuses the existing `seed` fixture in that file):

```python
class TestLockedThrough:

    def test_zero_for_non_transferred_student(self, seed):
        m = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})
        assert repository.locked_through(seed['s1'], seed['group_a1']) == Decimal('0')

    def test_equals_cumulative_transferred_for_transferred_student(self, seed):
        old = repository.add_membership({
            'group_id': seed['group_a1'], 'student_id': seed['s1'], 'lessons_done': 12,
        })
        new = repository.transfer_membership(old['id'], seed['group_a2'])
        assert repository.locked_through(seed['s1'], new['group_id']) == Decimal('12')

    def test_locked_through_map_only_includes_transferred(self, seed):
        old = repository.add_membership({
            'group_id': seed['group_a1'], 'student_id': seed['s1'], 'lessons_done': 12,
        })
        new = repository.transfer_membership(old['id'], seed['group_a2'])
        repository.add_membership({'group_id': seed['group_a2'], 'student_id': seed['s2']})

        result = repository.locked_through_map(seed['group_a2'], [seed['s1'], seed['s2']])

        assert result == {seed['s1']: Decimal('12')}
```

Add `from decimal import Decimal` to that test file's imports (confirmed not currently imported there).

- [ ] **Step 2: Run to verify it fails**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/memberships/tests/test_transfer_membership.py::TestLockedThrough -v`
Expected: FAIL — `AttributeError: module 'apps.memberships.repository' has no attribute 'locked_through'`

- [ ] **Step 3: Implement**

In `journal_django/apps/memberships/repository.py`, add after `cumulative_transferred_lessons` (right after its closing `return total`, before the `# Helpers` section):

```python
def locked_through_map(group_id: int, student_ids: list[int]) -> dict[int, Decimal]:
    """
    {student_id: B} только для учеников из student_ids, у которых АКТИВНАЯ
    membership в group_id имеет transferred_from (переведённые). Остальные в
    словаре отсутствуют — трактовать как Decimal('0') (не заблокированы).

    Один батч-запрос на переведённых + cumulative_transferred_lessons на каждого —
    переводы редки (тот же паттерн, что apps.groups.repository.get_group_progress
    для transferred-строк матрицы прогресса).
    """
    if not student_ids:
        return {}
    rows = (
        GroupMembership.objects
        .filter(group_id=group_id, student_id__in=student_ids, active=True,
                transferred_from_id__isnull=False)
        .values('student_id', 'transferred_from_id')
    )
    return {
        r['student_id']: cumulative_transferred_lessons(r['transferred_from_id'])
        for r in rows
    }


def locked_through(student_id: int, group_id: int) -> Decimal:
    """B для одного ученика/группы. См. locked_through_map для батча (N студентов)."""
    return locked_through_map(group_id, [student_id]).get(student_id, Decimal('0'))
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/memberships/tests/test_transfer_membership.py::TestLockedThrough -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/memberships/repository.py journal_django/apps/memberships/tests/test_transfer_membership.py
git commit -m "feat(memberships): add locked_through/locked_through_map helpers"
```

---

### Task 3: `AttendanceLockedByTransfer` exception

**Files:**
- Modify: `journal_django/apps/lessons/exceptions.py`

- [ ] **Step 1: Add the exception**

Append to `journal_django/apps/lessons/exceptions.py`:

```python
class AttendanceLockedByTransfer(Exception):
    """
    Попытка отметить посещаемость (present ИЛИ absent) ученику, переведённому в
    эту группу, на уроке с lesson_number <= уже отработанного им в старой группе
    (apps.memberships.repository.locked_through). Такой урок ученик фактически
    уже прошёл в предыдущей группе — отмечать его здесь нельзя (двойной учёт
    посещаемости/баланса/зарплаты). Действует, пока группа не догонит его прогресс.
    """

    def __init__(self, unlocks_at) -> None:
        self.unlocks_at = unlocks_at
        super().__init__(
            f'Этот ученик переведён и уже отработал этот урок в другой группе — '
            f'отметить его здесь нельзя. Включится с урока №{unlocks_at}.'
        )
```

This has no test of its own — it's exercised by Task 4's tests.

- [ ] **Step 2: Commit**

```bash
git add journal_django/apps/lessons/exceptions.py
git commit -m "feat(lessons): add AttendanceLockedByTransfer exception"
```

---

### Task 4: Enforce the lock in `update_attendance_cell`

**Files:**
- Modify: `journal_django/apps/lessons/repository.py:383-471` (the `update_attendance_cell` function)
- Modify: `journal_django/apps/lessons/views.py` (map exception to 409)
- Test: `journal_django/apps/lessons/tests/test_lessons_repository.py` (append)
- Test: `journal_django/apps/lessons/tests/test_lessons_api.py` (append)

- [ ] **Step 1: Write the failing repository test**

Append to `journal_django/apps/lessons/tests/test_lessons_repository.py`:

```python
def test_attendance_cell_blocked_for_locked_transferred_student(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, membership_fixture,
):
    """Ученик переведён с B=5 отработанными; урок с lesson_number=3 (<=5) блокирован."""
    from apps.lessons.exceptions import AttendanceLockedByTransfer
    from apps.memberships import repository as memberships_repo

    # Вторая группа того же направления — источник, откуда «переведён» ученик.
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active) VALUES ('__les_locked_src__', %s, %s, false, 60, true) "
            "RETURNING id",
            [direction_fixture, teacher_id_fixture],
        )
        src_group_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s, %s, 5, false) RETURNING id",
            [src_group_id, student_fixture],
        )
        src_membership_id = cur.fetchone()[0]
        cur.execute(
            'UPDATE group_memberships SET transferred_from_id = %s '
            'WHERE group_id = %s AND student_id = %s',
            [src_membership_id, group_fixture, student_fixture],
        )

    result = services.create_lesson_full({
        'lesson_date': '2026-03-08', 'group_id': group_fixture, 'teacher_id': teacher_id_fixture,
        'lesson_number': 3, 'lesson_duration_minutes': 60,
    })
    lesson_id = result['lesson_id']
    try:
        with pytest.raises(AttendanceLockedByTransfer):
            repository.update_attendance_cell(lesson_id, student_fixture, True)
        with pytest.raises(AttendanceLockedByTransfer):
            repository.update_attendance_cell(lesson_id, student_fixture, False)
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
            cur.execute('DELETE FROM lessons WHERE id = %s', [lesson_id])
            cur.execute('UPDATE group_memberships SET transferred_from_id = NULL '
                        'WHERE group_id = %s AND student_id = %s', [group_fixture, student_fixture])
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [src_membership_id])
            cur.execute('DELETE FROM groups WHERE id = %s', [src_group_id])


def test_attendance_cell_allowed_once_group_catches_up(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, membership_fixture,
):
    """B=5; урок с lesson_number=6 (>5) — разрешён."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active) VALUES ('__les_locked_src2__', %s, %s, false, 60, true) "
            "RETURNING id",
            [direction_fixture, teacher_id_fixture],
        )
        src_group_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s, %s, 5, false) RETURNING id",
            [src_group_id, student_fixture],
        )
        src_membership_id = cur.fetchone()[0]
        cur.execute(
            'UPDATE group_memberships SET transferred_from_id = %s '
            'WHERE group_id = %s AND student_id = %s',
            [src_membership_id, group_fixture, student_fixture],
        )

    result = services.create_lesson_full({
        'lesson_date': '2026-03-08', 'group_id': group_fixture, 'teacher_id': teacher_id_fixture,
        'lesson_number': 6, 'lesson_duration_minutes': 60,
    })
    lesson_id = result['lesson_id']
    try:
        assert repository.update_attendance_cell(lesson_id, student_fixture, True) is True
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
            cur.execute('DELETE FROM lessons WHERE id = %s', [lesson_id])
            cur.execute('UPDATE group_memberships SET transferred_from_id = NULL '
                        'WHERE group_id = %s AND student_id = %s', [group_fixture, student_fixture])
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [src_membership_id])
            cur.execute('DELETE FROM groups WHERE id = %s', [src_group_id])
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_lessons_repository.py -k locked -v`
Expected: FAIL — first test doesn't raise `AttendanceLockedByTransfer` (no enforcement yet).

- [ ] **Step 3: Implement the enforcement**

In `journal_django/apps/lessons/repository.py`, this line already exists near the top:

```python
from .exceptions import LessonHasMakeupResolutions, UnpaidAttendanceBlocked
```

Change it to also import the new exception:

```python
from .exceptions import AttendanceLockedByTransfer, LessonHasMakeupResolutions, UnpaidAttendanceBlocked
```

Add one more import line next to the other `apps.memberships` import:

```python
from apps.memberships.repository import locked_through
```

Then in `update_attendance_cell`, change the `ctx` fetch to also select `lesson_number`, and add the lock check right after fetching `ctx` (before the existing `if present: assert_students_paid(...)` line):

```python
        ctx = (
            Lesson.objects
            .select_for_update()
            .filter(id=lesson_id)
            .values('group_id', 'lesson_duration_minutes', 'lesson_number')
            .first()
        )
        if ctx is None:
            return False

        locked_b = locked_through(student_id, ctx['group_id'])
        if locked_b > 0 and ctx['lesson_number'] <= locked_b:
            step = _step(ctx['lesson_duration_minutes'])
            raise AttendanceLockedByTransfer(locked_b + step)

        if present:
            assert_students_paid([student_id])
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_lessons_repository.py -k locked -v`
Expected: `2 passed`

- [ ] **Step 5: Wire the 409 mapping in the view**

In `journal_django/apps/lessons/views.py`, add `AttendanceLockedByTransfer` to the import from `apps.lessons.exceptions`, and add it to the existing `except (SystemLessonProtected, AttendanceCompensatedElsewhere)` tuple in `AttendanceCellView.patch`:

```python
        except (SystemLessonProtected, AttendanceCompensatedElsewhere, AttendanceLockedByTransfer) as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
```

- [ ] **Step 6: Write and run the API-level 409 test**

Append to `journal_django/apps/lessons/tests/test_lessons_api.py`:

```python
def test_attendance_cell_locked_by_transfer_409(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, membership_fixture,
):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active) VALUES ('__les_api_locked_src__', %s, %s, false, 60, true) "
            "RETURNING id",
            [direction_fixture, teacher_id_fixture],
        )
        src_group_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s, %s, 5, false) RETURNING id",
            [src_group_id, student_fixture],
        )
        src_membership_id = cur.fetchone()[0]
        cur.execute(
            'UPDATE group_memberships SET transferred_from_id = %s '
            'WHERE group_id = %s AND student_id = %s',
            [src_membership_id, group_fixture, student_fixture],
        )
    lesson_id = _create_lesson(group_fixture, teacher_id_fixture)
    try:
        resp = _client('admin').patch(
            f'{BASE_URL}/{lesson_id}/attendance/{student_fixture}', {'present': True}, format='json',
        )
        assert resp.status_code == 409
    finally:
        _delete_lesson(lesson_id)
        with connection.cursor() as cur:
            cur.execute('UPDATE group_memberships SET transferred_from_id = NULL '
                        'WHERE group_id = %s AND student_id = %s', [group_fixture, student_fixture])
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [src_membership_id])
            cur.execute('DELETE FROM groups WHERE id = %s', [src_group_id])
```

Note: `_create_lesson(group_id, teacher_id)` (defined at the top of this file) always inserts with `lesson_number=1`, which is `<= 5` (our `B`) — no extra argument needed, this test's use of it is correct as written.

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_lessons_api.py -k locked_by_transfer -v`
Expected: `1 passed`

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/lessons/repository.py journal_django/apps/lessons/views.py journal_django/apps/lessons/tests/test_lessons_repository.py journal_django/apps/lessons/tests/test_lessons_api.py
git commit -m "feat(lessons): block attendance marking on lessons already covered by transfer"
```

---

### Task 5: Silently exclude locked students from `record_lesson`

**Files:**
- Modify: `journal_django/apps/lessons/services.py:47-137` (`record_lesson`)
- Test: `journal_django/apps/lessons/tests/test_lessons_repository.py` (append; this file already imports `services`)

- [ ] **Step 1: Write the failing test**

Append to `journal_django/apps/lessons/tests/test_lessons_repository.py`:

```python
def test_record_lesson_silently_excludes_locked_students(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, membership_fixture,
):
    """B=5 для student_fixture; урок №3 (locked) исключает его из attendance/total_students,
    но обычный ученик той же группы (student2) отмечается нормально."""
    with connection.cursor() as cur:
        cur.execute("INSERT INTO students (full_name, enrollment_status) "
                    "VALUES ('__les_locked_s2__', 'enrolled') RETURNING id")
        student2_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s, %s, 0, true) RETURNING id",
            [group_fixture, student2_id],
        )
        membership2_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, lessons_count, "
            "unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s, %s, 2, 8, 1000, 8000, '2026-06-01', 'test') RETURNING id",
            [student2_id, direction_fixture],
        )
        payment2_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active) VALUES ('__les_rl_locked_src__', %s, %s, false, 60, true) "
            "RETURNING id",
            [direction_fixture, teacher_id_fixture],
        )
        src_group_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s, %s, 5, false) RETURNING id",
            [src_group_id, student_fixture],
        )
        src_membership_id = cur.fetchone()[0]
        cur.execute(
            'UPDATE group_memberships SET transferred_from_id = %s '
            'WHERE group_id = %s AND student_id = %s',
            [src_membership_id, group_fixture, student_fixture],
        )

    result = services.record_lesson(
        lesson_date='2026-03-08', teacher_id=teacher_id_fixture, group_id=group_fixture,
        original_teacher_id=None, lesson_number=3, lesson_duration_minutes=60,
        lesson_type='regular', record_url=None, submitted_by_token='test',
        submit_date='2026-03-08',
        attendance=[
            {'student_id': student_fixture, 'present': True},
            {'student_id': student2_id, 'present': True},
        ],
    )
    lesson_id = result['lesson_id']
    try:
        full = services.get_lesson_full(lesson_id)
        student_ids_in_attendance = {a['student_id'] for a in full['attendance']}
        assert student_fixture not in student_ids_in_attendance
        assert student2_id in student_ids_in_attendance
        assert full['payroll']['total_students'] == 1
        assert full['payroll']['present_count'] == 1
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
            cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [lesson_id])
            cur.execute('DELETE FROM lessons WHERE id = %s', [lesson_id])
            cur.execute('UPDATE group_memberships SET transferred_from_id = NULL '
                        'WHERE group_id = %s AND student_id = %s', [group_fixture, student_fixture])
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [src_membership_id])
            cur.execute('DELETE FROM groups WHERE id = %s', [src_group_id])
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership2_id])
            cur.execute('DELETE FROM payments WHERE id = %s', [payment2_id])
            cur.execute('DELETE FROM students WHERE id = %s', [student2_id])
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_lessons_repository.py -k excludes_locked -v`
Expected: FAIL — `student_fixture` currently still ends up in attendance (`total_students == 2`).

- [ ] **Step 3: Implement the filtering**

In `journal_django/apps/lessons/services.py`, add the import at the top:

```python
from apps.memberships.repository import locked_through_map
```

Then at the very start of `record_lesson`, before `present_student_ids = [...]`, add:

```python
    all_student_ids = [a['student_id'] for a in attendance]
    locked_map = locked_through_map(group_id, all_student_ids)
    if locked_map:
        lesson_num_dec = Decimal(str(lesson_number))
        attendance = [
            a for a in attendance
            if lesson_num_dec > locked_map.get(a['student_id'], Decimal('0'))
        ]

    present_student_ids = [a['student_id'] for a in attendance if a['present']]
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_lessons_repository.py -k excludes_locked -v`
Expected: `1 passed`

- [ ] **Step 5: Run the full lessons test suite to check for regressions**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons -q`
Expected: all pass (no regressions from the new filtering — no other test transfers students mid-suite).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/lessons/services.py journal_django/apps/lessons/tests/test_lessons_repository.py
git commit -m "feat(lessons): record_lesson excludes locked transferred students silently"
```

---

### Task 6: Phase 1b — `place_student_in_group` seeds continuation for qualifying groups

**Files:**
- Modify: `journal_django/apps/memberships/repository.py:288-380` (`place_student_in_group`)
- Test: `journal_django/apps/memberships/tests/test_place_student.py` (append)

- [ ] **Step 1: Write the failing tests**

Add `from decimal import Decimal` to the imports at the top of `journal_django/apps/memberships/tests/test_place_student.py` (not currently imported there). Then append:

```python
class TestTransferContinuationPhase1b:

    def test_seeds_lessons_done_and_offset_for_solo_new_group(self, seed):
        """Ученик с B=20 переводится в СВЕЖУЮ группу (0 уроков, будет один) —
        новая membership стартует с lessons_done=20, группа получает offset=20."""
        old = repository.add_membership({
            'group_id': seed['group_a1'], 'student_id': seed['s1'], 'lessons_done': 20,
        })
        new = repository.place_student_in_group(
            seed['s1'], seed['group_a2'], from_membership_id=old['id'],
        )
        assert float(new['lessons_done']) == 20.0

        from apps.groups.models import Group
        offset = Group.objects.filter(id=seed['group_a2']).values_list(
            'lesson_number_offset', flat=True,
        ).first()
        assert offset == Decimal('20.0')

    def test_no_seed_when_group_has_other_active_member(self, seed):
        """group_a2 уже занят s2 — s1 переводится туда же (не индивидуальная группа,
        значит это допустимо), continuation НЕ применяется (не «сольная» группа)."""
        repository.add_membership({'group_id': seed['group_a2'], 'student_id': seed['s2']})
        old = repository.add_membership({
            'group_id': seed['group_a1'], 'student_id': seed['s1'], 'lessons_done': 20,
        })
        new = repository.place_student_in_group(
            seed['s1'], seed['group_a2'], from_membership_id=old['id'],
        )
        assert float(new['lessons_done']) == 0.0

        from apps.groups.models import Group
        offset = Group.objects.filter(id=seed['group_a2']).values_list(
            'lesson_number_offset', flat=True,
        ).first()
        assert offset == Decimal('0.0')

    def test_no_seed_for_fresh_enrollment_without_source(self, seed):
        new = repository.place_student_in_group(seed['s1'], seed['group_a2'])
        assert float(new['lessons_done']) == 0.0

    def test_no_seed_when_target_group_already_has_regular_lesson(self, seed):
        """group_a2 уже вело курс (есть regular-урок) — offset не переписываем."""
        from apps.lessons import services as lessons_services
        lessons_services.create_lesson_full({
            'lesson_date': '2026-03-01', 'group_id': seed['group_a2'],
            'teacher_id': seed['teacher_id'], 'lesson_number': 1,
            'lesson_duration_minutes': 90,
        })
        old = repository.add_membership({
            'group_id': seed['group_a1'], 'student_id': seed['s1'], 'lessons_done': 20,
        })
        new = repository.place_student_in_group(
            seed['s1'], seed['group_a2'], from_membership_id=old['id'],
        )
        assert float(new['lessons_done']) == 0.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/memberships/tests/test_place_student.py::TestTransferContinuationPhase1b -v`
Expected: FAIL — `test_seeds_lessons_done_and_offset_for_solo_new_group` fails (`lessons_done` stays 0.0, offset stays 0).

- [ ] **Step 3: Implement the qualifying-condition hook**

In `journal_django/apps/memberships/repository.py`, add near the bottom of the file (after `place_student_in_group`, before `transfer_membership`):

```python
def _seed_transfer_continuation(to_group_id: int, student_id: int, from_membership_id: Optional[int]) -> None:
    """
    Фаза 1b: если ученик — ЕДИНСТВЕННЫЙ активный участник group_id БЕЗ проведённых
    regular/substitution/reschedule уроков, и placement пришёл с историей
    (from_membership_id задан, B>0) — группа продолжает курс с того места, где
    ученик остановился, вместо того чтобы «спать» первые B уроков своей новой
    группы (см. docs/superpowers/specs/2026-07-21-transfer-progress-alignment-design.md,
    Фаза 1b).

    Действие: новая membership.lessons_done = B (не 0 — иначе ad-hoc lesson_number
    у teacher_spa, = max(lessons_done)+step, стартовал бы с 1, а не с B+1);
    group.lesson_number_offset = B; план группы пересобирается с этим офсетом.

    No-op: from_membership_id не задан, B<=0, в группе есть другой активный
    участник, в группе уже есть проведённый regular/substitution/reschedule урок.

    Вызывать ВНУТРИ той же транзакции, что создание membership.
    """
    if from_membership_id is None:
        return
    b = cumulative_transferred_lessons(from_membership_id)
    if b <= 0:
        return

    other_active = (
        GroupMembership.objects
        .filter(group_id=to_group_id, active=True)
        .exclude(student_id=student_id)
        .exists()
    )
    if other_active:
        return

    from apps.lessons.models import Lesson
    has_course_lessons = Lesson.objects.filter(
        group_id=to_group_id, lesson_type__in=('regular', 'substitution', 'reschedule'),
    ).exists()
    if has_course_lessons:
        return

    GroupMembership.objects.filter(
        group_id=to_group_id, student_id=student_id, active=True,
    ).update(lessons_done=b)
    Group.objects.filter(id=to_group_id).update(lesson_number_offset=b)

    from apps.scheduling.repository import reset_plan, generate_for_group
    reset_plan(to_group_id)
    generate_for_group(to_group_id)
```

Then in `place_student_in_group`, add the call right after `new_id = (...)` and before the `with` block ends (still at 8-space indent, inside `with transaction.atomic():`):

```python
        new_id = (
            GroupMembership.objects
            .filter(group_id=to_group_id, student_id=student_id)
            .values_list('id', flat=True)
            .first()
        )

        _seed_transfer_continuation(to_group_id, student_id, from_membership_id)

    return _membership_row(new_id)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/memberships/tests/test_place_student.py::TestTransferContinuationPhase1b -v`
Expected: `4 passed`

- [ ] **Step 5: Run the full memberships suite to check for regressions**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/memberships -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/memberships/repository.py journal_django/apps/memberships/tests/test_place_student.py
git commit -m "feat(memberships): seed transfer continuation for solo new-group placements"
```

---

### Task 7: `scheduling.repository.generate_for_group` honors `lesson_number_offset`

**Files:**
- Modify: `journal_django/apps/scheduling/repository.py:1108-1153` (`generate_for_group`)
- Test: `journal_django/apps/scheduling/tests/test_plan_autogenerate.py` (append)

- [ ] **Step 1: Write the failing test**

`journal_django/apps/scheduling/tests/test_plan_autogenerate.py` already has an `autogen_setup` fixture (wraps the `sched_setup` conftest fixture) giving a group (`autogen_setup['group_a']`) with `group_start_date='2026-06-01'`, a Monday-10:00 slot, and `direction.total_lessons=8` — a full generate on it produces exactly 8 rows (confirmed by `test_generates_plan_and_audits` in the same file). Append this test to that file:

```python
def test_generate_for_group_honors_lesson_number_offset(autogen_setup):
    """
    Группе (total_lessons=8, ещё без плана) выставлен lesson_number_offset=6 —
    план должен начинаться с lesson_number=7.0 (первый урок ПОСЛЕ офсета),
    seq=1 (первая созданная строка), и содержать оставшиеся 8-6=2 строки, а не 8.
    """
    from decimal import Decimal
    from apps.groups.models import Group

    gid = autogen_setup['group_a']
    Group.objects.filter(id=gid).update(lesson_number_offset=Decimal('6'))
    result = repository.generate_for_group(gid)
    assert result['written'] == 2
    rows = sorted(result['plan'], key=lambda r: r['seq'])
    assert rows[0]['seq'] == 1
    assert float(rows[0]['lesson_number']) == 7.0
    assert float(rows[-1]['lesson_number']) == 8.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/scheduling/tests/test_plan_autogenerate.py -k lesson_number_offset -v`
Expected: FAIL — `written == 8` and `rows[0]['lesson_number'] == 1.0` (offset not yet threaded through).

- [ ] **Step 3: Implement**

In `journal_django/apps/scheduling/repository.py`, in `generate_for_group`, add `lesson_number_offset` to the `.values()` call:

```python
    g = (
        Group.objects
        .filter(id=group_id)
        .values(
            'id', 'lesson_duration_minutes', 'group_start_date', 'teacher_id',
            'lesson_number_offset',
            total_lessons=F('direction__total_lessons'),
        )
        .first()
    )
```

Then change the `planner.generate(...)` call inside `if reason is None:` to pass the offset:

```python
    written = 0
    if reason is None:
        offset = g['lesson_number_offset'] or Decimal('0')
        step = _step_for(g['lesson_duration_minutes'])
        start_seq = int(offset / step) + 1 if offset > 0 else 1
        rows = planner.generate(
            start_date=g['group_start_date'],
            slots=g_slots,
            total_lessons=g['total_lessons'],
            duration_minutes=g['lesson_duration_minutes'],
            default_teacher_id=g['teacher_id'],
            start_seq=start_seq,
            start_number=offset,
        )
        # create_only: повторный generate не затирает ручные операции над планом —
        # только досоздаёт недостающие seq (напр. при увеличении длины курса).
        written = persist_plan(group_id, rows, create_only=True)  # атомарен сам по себе
```

`_step_for` and `Decimal` are already imported at the top of this file (confirmed in Task exploration — `_step_for` is in the existing `from apps.scheduling.occurrences import (...)` line, `Decimal` in `from decimal import Decimal`).

- [ ] **Step 4: Run to verify it passes**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/scheduling/tests/test_plan_autogenerate.py -k lesson_number_offset -v`
Expected: `1 passed`

- [ ] **Step 5: Run the full scheduling suite to check for regressions**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/scheduling -q`
Expected: all pass (default `lesson_number_offset=0` for every pre-existing group → `start_seq=1, start_number=0`, identical to current behavior).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/scheduling/repository.py apps/scheduling/tests/test_plan_autogenerate.py
git commit -m "feat(scheduling): generate_for_group honors group's lesson_number_offset"
```

---

### Task 8: Expose raw `B` on the progress matrix for the tooltip

**Files:**
- Modify: `journal_django/apps/groups/repository.py:378-520ish` (`get_group_progress`)
- Test: `journal_django/apps/groups/tests/test_progress_api.py` (append)

- [ ] **Step 1: Write the failing test**

`journal_django/apps/groups/tests/test_progress_api.py` has a `progress_group` fixture yielding `{'group_id', 'anya', 'borya', 'lesson_ids'}` (direction.total_lessons=8, no separate "old group" — the existing `TestTransferredLessons` tests in that file build the old/source group inline). Append this test to the `TestTransferredLessons` class, following the exact same inline-old-group pattern as `test_transferred_student_gets_capped_count` right above it:

```python
    def test_locked_through_exposes_raw_uncapped_value(self, manager_client, progress_group):
        """locked_through — сырое B (cumulative_transferred_lessons), НЕ капается
        total_slots=8 (в отличие от transferred_lessons, который капается для покраски)."""
        gid = progress_group['group_id']
        with connection.cursor() as cur:
            cur.execute("SELECT direction_id, teacher_id FROM groups WHERE id = %s", [gid])
            direction_id, teacher_id = cur.fetchone()
            cur.execute(
                "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                "lesson_duration_minutes,active) VALUES ('__pg_old_g2__',%s,%s,false,60,false) "
                "RETURNING id",
                [direction_id, teacher_id],
            )
            old_group_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                "VALUES (%s,%s,20,false) RETURNING id",
                [old_group_id, progress_group['borya']],
            )
            old_membership_id = cur.fetchone()[0]
            cur.execute(
                "UPDATE group_memberships SET transferred_from_id = %s "
                "WHERE group_id = %s AND student_id = %s",
                [old_membership_id, gid, progress_group['borya']],
            )
        try:
            body = manager_client.get(_url(gid)).json()
            rows = {r['student_id']: r for r in body['students']}
            borya = rows[progress_group['borya']]
            assert borya['transferred_lessons'] == 8       # капается total_slots=8
            assert float(borya['locked_through']) == 20.0  # сырое B — НЕ капается
        finally:
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE group_memberships SET transferred_from_id = NULL "
                    "WHERE group_id = %s AND student_id = %s",
                    [gid, progress_group['borya']],
                )
                cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [old_group_id])
                cur.execute('DELETE FROM groups WHERE id = %s', [old_group_id])
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/groups/tests/test_progress_api.py -k locked_through_exposes -v`
Expected: FAIL — `KeyError: 'locked_through'`

- [ ] **Step 3: Implement**

In `journal_django/apps/groups/repository.py`, inside `get_group_progress`'s per-member loop (around line 543-549), the code currently reads:

```python
        transferred_lessons = 0
        transferred_from_group_name = None
        if member['transferred_from_id']:
            cumulative = cumulative_transferred_lessons(member['transferred_from_id'])
            transferred_lessons = min(math.floor(float(cumulative)), slot_count)
            if transferred_lessons > 0:
                transferred_from_group_name = member['transferred_from_group_name']
```

`cumulative` is already the raw, uncapped value — just carry it forward. Change the block to also track it, defaulting to `Decimal('0')` when there's no transfer, and add it to the `students.append({...})` dict:

```python
        transferred_lessons = 0
        transferred_from_group_name = None
        locked_through = Decimal('0')
        if member['transferred_from_id']:
            cumulative = cumulative_transferred_lessons(member['transferred_from_id'])
            locked_through = cumulative
            transferred_lessons = min(math.floor(float(cumulative)), slot_count)
            if transferred_lessons > 0:
                transferred_from_group_name = member['transferred_from_group_name']

        students.append({
            'student_id': sid,
            'name': member['name'],
            'present': present,
            'held': held,
            'pct': round(present / held * 100) if held else 0,
            'cells': cells,
            'compensated': compensated,
            'transferred_lessons': transferred_lessons,
            'transferred_from_group_name': transferred_from_group_name,
            'locked_through': locked_through,
        })
```

Add `from decimal import Decimal` near the top of `journal_django/apps/groups/repository.py` (confirmed not currently imported there — the file only has `import datetime` at module level; `import math` is a separate local import inside `get_group_progress` itself and stays as-is).

- [ ] **Step 4: Run to verify it passes**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/groups/tests/test_progress_api.py -k locked_through -v`
Expected: `1 passed`

- [ ] **Step 5: Run the full groups suite to check for regressions**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/groups -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/groups/repository.py journal_django/apps/groups/tests/test_progress_api.py
git commit -m "feat(groups): expose raw locked_through on progress matrix rows"
```

---

### Task 9: Frontend — `GroupProgressView` tooltip shows the unlock lesson number

**Files:**
- Modify: `journal_django/frontend/admin-src/src/shared/progress/types.ts`
- Modify: `journal_django/frontend/admin-src/src/shared/progress/GroupProgressView.tsx`

- [ ] **Step 1: Add the field to the type**

In `journal_django/frontend/admin-src/src/shared/progress/types.ts`, add to `ProgressStudent`:

```typescript
  // Сырое B (cumulative_transferred_lessons), НЕ капается total_slots —
  // используется только для текста тултипа «догоняем к уроку N».
  locked_through: string | number;
```

- [ ] **Step 2: Use it in the tooltip text**

In `journal_django/frontend/admin-src/src/shared/progress/GroupProgressView.tsx`, find the tooltip label construction for the `'transferred'` status (around line 130-131, `const label = st === 'transferred' ? ...`). Change it to include the unlock lesson number:

```typescript
                const label = st === 'transferred'
                  ? `Урок №${slot.slot}: Перевод из «${s.transferred_from_group_name}» — догоняем к уроку №${Math.floor(Number(s.locked_through)) + 1}`
                  : STATUS_LABEL[st];
```

- [ ] **Step 3: Typecheck**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/shared/progress/types.ts journal_django/frontend/admin-src/src/shared/progress/GroupProgressView.tsx
git commit -m "feat(admin): progress tooltip shows the unlock lesson number for transferred students"
```

---

### Task 10: Frontend admin — `LessonEditor` greys out locked students

**Files:**
- Modify: `journal_django/frontend/admin-src/src/components/lessons/LessonEditor.tsx`

No backend change needed here — `useMemberships({ group_id })` already returns `transferred_from_id` and `transferred_from_lessons_done` for every member (see `MembershipReadSerializer`), which is exactly `B`.

- [ ] **Step 1: Compute `locked` per member and disable their card**

In `journal_django/frontend/admin-src/src/components/lessons/LessonEditor.tsx`, add a helper above the component (or inline in the render):

```typescript
function isLockedByTransfer(m: { transferred_from_id?: number | null; transferred_from_lessons_done?: string | number | null }, slotLessonNumber: number): boolean {
  if (!m.transferred_from_id || m.transferred_from_lessons_done == null) return false;
  return slotLessonNumber <= Number(m.transferred_from_lessons_done);
}
```

Then, where `members.map((m) => { ... })` renders each `attendance-card` (around line 143), compute the slot's lesson number the same way `handleSave` already does (`slot * step`, `step = group.lesson_duration_minutes === 45 ? 0.5 : 1`) — hoist that `step`/`slotLessonNumber` computation above the `members.map` call:

```typescript
  const step = group.lesson_duration_minutes === 45 ? 0.5 : 1;
  const slotLessonNumber = slot * step;
```

And in the map body:

```typescript
          {members.length ? members.map((m) => {
            const isPresent = !!present[m.student_id];
            const memberLocked = locked || isLockedByTransfer(m, slotLessonNumber);
            const lockedByTransfer = !locked && isLockedByTransfer(m, slotLessonNumber);
            return (
              <button
                key={m.student_id}
                type="button"
                className={`attendance-card ${isPresent ? 'is-present' : 'is-absent'}${memberLocked ? ' is-locked' : ''}`}
                onClick={memberLocked ? undefined : () => setPresent((p) => ({ ...p, [m.student_id]: !p[m.student_id] }))}
                disabled={memberLocked}
                aria-disabled={memberLocked}
                title={lockedByTransfer
                  ? `Переведён — уже отработано в «${m.transferred_from_group_name || 'другой группе'}», догоняем к уроку №${Math.floor(Number(m.transferred_from_lessons_done)) + 1}`
                  : undefined}
              >
                <span className="attendance-card__icon" aria-hidden>{isPresent ? '✓' : '✕'}</span>
                <span className="attendance-card__name">{m.student_name || `#${m.student_id}`}</span>
              </button>
            );
          }) : (
```

Also update `handleSave`'s `attendance` construction to exclude locked-by-transfer members from the submitted list (mirrors the backend's silent-exclusion so the admin doesn't see a spurious `present: false` row created for someone who should have no row at all):

```typescript
    const attendance = members
      .filter((m) => !isLockedByTransfer(m, slotLessonNumber))
      .map((m) => ({
        student_id: m.student_id,
        present: !!present[m.student_id],
      }));
```

(`slotLessonNumber`/`step` must be computed before `handleSave` — hoist them to component top-level, above both `handleSave` and the render, not duplicated in each.)

- [ ] **Step 2: Typecheck**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/components/lessons/LessonEditor.tsx
git commit -m "feat(admin): LessonEditor greys out students locked by transfer"
```

---

### Task 11: Backend — `teacher_spa.read_all_students` carries lock info

**Files:**
- Modify: `journal_django/apps/teacher_spa/repository.py:74-155` (`read_all_students`)

- [ ] **Step 1: Add `transferred_from_id`/`lesson_duration_minutes` to the query and compute `B` per row**

In `journal_django/apps/teacher_spa/repository.py`, add to the `.values(...)` call in `read_all_students`:

```python
        .values(
            'group_id', 'student_id', 'lessons_done', 'sheet_row', 'transferred_from_id',
            group_name=F('group__name'),
            is_individual=F('group__is_individual'),
            vk_chat=F('group__vk_chat'),
            group_start_date=F('group__group_start_date'),
            teacher_name=F('group__teacher__name'),
            student_name=F('student__full_name'),
            age=F('student__age'),
            pm=F('student__pm'),
            membership_id=F('id'),
            duration_minutes=F('group__lesson_duration_minutes'),
        )
```

Then, inside the per-row loop, after computing `done`/`remaining`, compute the student's own `B` (lazy import to avoid a top-of-file circular-import risk, same convention as elsewhere in this codebase):

```python
        locked_through = None
        if r['transferred_from_id']:
            from apps.memberships.repository import cumulative_transferred_lessons
            locked_through = cumulative_transferred_lessons(r['transferred_from_id'])

        grp['students'].append({
            'name': r['student_name'],
            'lessonsDone': done,
            'remaining': remaining,
            'age': str(r['age']) if r['age'] is not None else '',
            'sheetName': sheet_name,
            'sheetRow': r['sheet_row'] or 0,
            'lockedThrough': float(locked_through) if locked_through is not None else None,
        })
```

Also store `duration_minutes` on `grp` the first time it's created (in the `if group not in data[teacher]:` block), so a second pass can compute the group's `step`:

```python
            data[teacher][group] = {
                'students': [],
                'lessonsDone': 0,
                'pm': r['pm'] or '',
                'vkChat': r['vk_chat'] or '',
                'startDate': fmt_date_ru(r['group_start_date']),
                'isGroup': not r['is_individual'],
                'durationMinutes': r['duration_minutes'],
            }
```

- [ ] **Step 2: Second pass — mark each student `locked: bool` once the group's final `lessonsDone` is known**

Right before the `return {'data': data, 'index': index}` line, add:

```python
    for teacher_groups in data.values():
        for grp in teacher_groups.values():
            step = 0.5 if grp['durationMinutes'] == 45 else 1
            next_number = grp['lessonsDone'] + step
            for s in grp['students']:
                s['locked'] = s['lockedThrough'] is not None and next_number <= s['lockedThrough']
```

- [ ] **Step 3: Run the existing teacher_spa test suite**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa -q`
Expected: all pass (new fields are additive — existing tests asserting exact dict equality on `students` entries may need the two new keys added to their expected fixtures; if any test does an exact-equality assertion on the student dict, extend its expected value with `'lockedThrough': None, 'locked': False` rather than switching to a subset match).

- [ ] **Step 4: If Step 3 surfaces exact-equality test failures, fix them**

Locate the failing assertions (likely in `apps/teacher_spa/tests/test_teacher_spa_repository.py`), and add `'lockedThrough': None, 'locked': False` to each expected student dict literal that currently doesn't have a transferred student, matching the exact key order used elsewhere isn't required (dict equality in Python is order-independent).

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa -q`
Expected: all pass.

- [ ] **Step 5: Add one new test for the locked case**

`journal_django/apps/teacher_spa/tests/conftest.py` provides `teacher_fixture` (yields `(teacher_id, teacher_name)`), `direction_fixture`, `group_fixture(teacher_fixture, direction_fixture)`, `student_fixture`, and `membership_fixture(group_fixture, student_fixture, direction_fixture)` (with an 8-lesson payment so `remaining=8`). Append this test to `journal_django/apps/teacher_spa/tests/test_teacher_spa_repository.py`:

```python
def test_read_all_students_marks_locked_transferred_student(
    teacher_fixture, direction_fixture, group_fixture, student_fixture, membership_fixture,
):
    """Ученик с B=5 (source membership lessons_done=5), а в group_fixture
    max(lessonsDone)=2 (< 5) — locked=True, lockedThrough=5.0."""
    teacher_id, teacher_name = teacher_fixture
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE group_memberships SET lessons_done = 2 WHERE id = %s", [membership_fixture],
        )
        cur.execute(
            "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
            "lesson_duration_minutes,active) VALUES ('__spa_locked_src__',%s,%s,false,60,false) "
            "RETURNING id",
            [direction_fixture, teacher_id],
        )
        src_group_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s,%s,5,false) RETURNING id",
            [src_group_id, student_fixture],
        )
        src_membership_id = cur.fetchone()[0]
        cur.execute(
            "UPDATE group_memberships SET transferred_from_id = %s WHERE id = %s",
            [src_membership_id, membership_fixture],
        )
    try:
        result = repository.read_all_students()
        group_data = result['data'][teacher_name]['__spa_test_group__ пн 10:00']
        student_row = next(s for s in group_data['students'] if s['name'] == '__spa_test_student__')
        assert student_row['locked'] is True
        assert student_row['lockedThrough'] == 5.0
    finally:
        with connection.cursor() as cur:
            cur.execute("UPDATE group_memberships SET transferred_from_id = NULL WHERE id = %s",
                        [membership_fixture])
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [src_membership_id])
            cur.execute('DELETE FROM groups WHERE id = %s', [src_group_id])
```

Note: `group_fixture`'s name literal is `'__spa_test_group__ пн 10:00'` (confirmed from that conftest) — reuse it exactly since `read_all_students` keys groups by name.

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/teacher_spa/repository.py journal_django/apps/teacher_spa/tests/test_teacher_spa_repository.py
git commit -m "feat(teacher_spa): read_all_students marks students locked by transfer"
```

---

### Task 12: Frontend teacher-src — `LessonForm` greys out locked students

**Files:**
- Modify: `journal_django/frontend/teacher-src/src/lib/types.ts`
- Modify: `journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx`

- [ ] **Step 1: Add the new fields to the student type**

In `journal_django/frontend/teacher-src/src/lib/types.ts`, the type used by `GroupData.students` is `TStudent`:

```typescript
export interface TStudent {
  name: string;
  lessonsDone: number;
  remaining: number;
  age: string;
  sheetName: string;
  sheetRow: number;
}
```

Add the two new fields:

```typescript
export interface TStudent {
  name: string;
  lessonsDone: number;
  remaining: number;
  age: string;
  sheetName: string;
  sheetRow: number;
  locked: boolean;
  lockedThrough: number | null;
}
```

- [ ] **Step 2: Extend the blocking predicate in `LessonForm.tsx`**

In `journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx`, change `isBlocked` to a richer check that also covers the transfer lock, distinguishing the two reasons for the tooltip/label:

```typescript
/** Причина, по которой ученика нельзя отметить — либо нет оплаты, либо переведён и ждёт, пока группа его догонит. */
function blockedReason(s: { remaining: number; locked: boolean; lockedThrough: number | null }): 'unpaid' | 'locked' | null {
  if (s.locked) return 'locked';
  if (s.remaining <= 0) return 'unpaid';
  return null;
}

function isBlocked(s: { remaining: number; locked: boolean; lockedThrough: number | null }): boolean {
  return blockedReason(s) !== null;
}
```

Then update the per-student card rendering (around line 169-190) to show the right label/title per reason:

```typescript
          {groupData.students.map((s) => {
            const reason = blockedReason(s);
            const blocked = reason !== null;
            return (
              <button
                type="button"
                key={s.name}
                className={`lf-student${present[s.name] ? ' is-present' : ''}${blocked ? ' is-blocked' : ''}`}
                onClick={() => {
                  if (blocked) return;
                  setPresent((p) => ({ ...p, [s.name]: !p[s.name] }));
                }}
                aria-pressed={!!present[s.name]}
                disabled={blocked}
                title={
                  reason === 'locked'
                    ? `Переведён — включится с урока №${(s.lockedThrough ?? 0) + 1}`
                    : reason === 'unpaid'
                      ? 'Нет оплаченных уроков — отметить нельзя'
                      : undefined
                }
              >
                <span className="lf-student-name">{s.name}</span>
                <span className="lf-student-state">
                  {reason === 'locked' ? 'Ожидает перевода' : reason === 'unpaid' ? 'Нет оплаты' : present[s.name] ? 'Пришёл' : 'Не пришёл'}
                </span>
              </button>
            );
          })}
```

`blockedStudents` (used for the warning banner listing names) already filters via `isBlocked(s)` — no change needed there, but its message hard-codes "Нет оплаченных уроков"; leave that banner as-is for unpaid-only (it's a secondary hint, the per-card title/label is now the authoritative distinction) — this is a deliberate scope limit, not an oversight.

- [ ] **Step 3: Typecheck**

Run: `cd journal_django/frontend/teacher-src && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/teacher-src/src/lib/types.ts journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx
git commit -m "feat(teacher): LessonForm greys out students locked by transfer"
```

---

### Task 13: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all pass, no new failures/skips beyond the pre-existing baseline.

- [ ] **Step 2: Typecheck both frontends**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Run: `cd journal_django/frontend/teacher-src && npx tsc --noEmit`
Expected: no errors in either.

- [ ] **Step 3: Manual smoke test (dev server)**

Start the local dev stack (nginx + runserver, per `docs/local-nginx` conventions already used in this project) and walk through:
1. Create two groups in the same direction (A1 with a few held lessons, A2 brand-new/empty).
2. Transfer a student with some `lessons_done` from A1 into A2 via the admin `PlaceStudentModal`.
3. Confirm A2's plan (`GroupPlanTable`) now numbers lessons starting from `B+1`, not `1`.
4. Open the first lesson of A2 in `LessonEditor` (admin) and in the teacher `LessonForm` — confirm the transferred student is NOT locked (since A2 is solo/fresh, Phase 1b applies) and can be marked present normally.
5. Transfer a *different* student into an EXISTING group that already has held lessons fewer than the student's `B` — confirm that student shows as locked/greyed in both `LessonEditor` and `LessonForm` on the lessons up to `B`, and becomes selectable once the group's `lesson_number` exceeds `B`.
6. Confirm the group's Progress matrix tooltip for the transferred student shows the correct "догоняем к уроку №N".

Document the outcome (pass/fail per step) before considering this plan complete — do not claim success without having actually driven this flow.

- [ ] **Step 4: Report status to the user**

Do not commit anything further from this task (Step 1-2 already validated by CI-equivalent local runs; Step 3 is exploratory/manual, no code changes result from it).
