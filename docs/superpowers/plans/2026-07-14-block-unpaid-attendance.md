# Block Unpaid-Balance Attendance Marking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a teacher from marking a student present in `submitLesson` when that student has no paid lessons left (`remaining <= 0`) — enforced on both backend (authoritative) and frontend (UX).

**Architecture:** Backend validates the already-resolved student IDs against `apps.finances.repository.balances_for_students` (same batch call already used by `read_all_students`) before opening the `submit_lesson` transaction, and rejects the whole request if any `present:true` student has `remaining <= 0`. Frontend (`LessonForm.tsx`) disables the toggle button for such students up front, using the `remaining` field already present in `GroupData.students`, and replaces the (currently buggy, first-student-only) group debt banner with a precise list of blocked students.

**Tech Stack:** Django 5 / DRF (backend), React 19 + TanStack Query v5 + TypeScript (teacher-src frontend), pytest + pytest-django (backend tests). No new libraries.

**Spec:** `docs/superpowers/specs/2026-07-14-block-unpaid-attendance-design.md`

---

### Task 1: Give test fixtures a real paid balance (prerequisite)

Today `membership_fixture` / `half_membership_fixture` create a `group_memberships` row with no matching `payments` row, so `balances_for_students` returns 0 for that student. Once Task 2 adds the balance check, every existing `present: true` test using these fixtures would start failing — not because of a new bug, but because the fixtures represent an unpaid student, which is exactly the case we're about to block. Fix the fixtures first, confirm nothing else breaks, and only then add the new check.

**Files:**
- Modify: `journal_django/apps/teacher_spa/tests/conftest.py:130-221` (`group_fixture`, `half_group_fixture`, `membership_fixture`, `half_membership_fixture`)

- [ ] **Step 1: Add a payment when creating `membership_fixture`**

Replace the existing `membership_fixture` (`journal_django/apps/teacher_spa/tests/conftest.py:187-202`):

```python
@pytest.fixture
def membership_fixture(group_fixture, student_fixture, direction_fixture):
    """
    Создаёт membership для group_fixture + student_fixture, с оплатой на 8 уроков
    (remaining=8) — иначе submitLesson блокирует present:true (нет оплаченных уроков).
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

- [ ] **Step 2: Add a payment when creating `half_membership_fixture`**

Replace the existing `half_membership_fixture` (`journal_django/apps/teacher_spa/tests/conftest.py:205-220`):

```python
@pytest.fixture
def half_membership_fixture(half_group_fixture, student_fixture, direction_fixture):
    """Membership для half_group_fixture, с оплатой на 8 уроков (remaining=8)."""
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO group_memberships (group_id, student_id, lessons_done, active)
            VALUES (%s, %s, 0, true)
            RETURNING id
            """,
            [half_group_fixture, student_fixture],
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

Note: `direction_fixture` is already created transitively via `group_fixture`/`half_group_fixture`; requesting it again in the signature just reuses the same pytest-cached instance (function-scoped) — no duplicate direction is created.

- [ ] **Step 3: Run the full existing suite to confirm nothing broke**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa -q`
Expected: all tests that were passing before (54 in `test_teacher_spa_api.py`, plus `test_teacher_spa_repository.py`) still pass. This confirms the fixture change is balance-neutral for existing behavior (no check exists yet to reject anything).

- [ ] **Step 4: Commit**

```bash
git add journal_django/apps/teacher_spa/tests/conftest.py
git commit -m "test(teacher-spa): give membership fixtures a real paid balance"
```

---

### Task 2: Backend — reject `submitLesson` when a present student has no paid balance

**Files:**
- Modify: `journal_django/apps/teacher_spa/services.py:17-18` (import), `journal_django/apps/teacher_spa/services.py:206-207` (insert check)
- Test: `journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py`

- [ ] **Step 1: Write the failing tests**

Add these two tests to `TestSubmitLesson` in `journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py`, right after `test_absent_student_not_incremented` (after line 361, before `test_payment_calculation_small_group`):

```python
    def test_present_blocked_when_no_paid_balance(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture,
    ):
        """
        Ученик без оплаченных уроков (remaining<=0, membership без payments) +
        present:true → success:false, урок/attendance/payroll не создаются.
        """
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO group_memberships (group_id, student_id, lessons_done, active) '
                'VALUES (%s, %s, 0, true) RETURNING id',
                [group_fixture, student_fixture],
            )
            membership_id = cur.fetchone()[0]

        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body['success'] is False
            assert '__spa_test_student__' in body['error']

            token = f'acct:{account_fixture}'
            assert _get_lesson_id(group_fixture, token) is None
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])

    def test_absent_allowed_without_paid_balance(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture,
    ):
        """Тот же неоплаченный ученик, но present:false — урок создаётся нормально."""
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO group_memberships (group_id, student_id, lessons_done, active) '
                'VALUES (%s, %s, 0, true) RETURNING id',
                [group_fixture, student_fixture],
            )
            membership_id = cur.fetchone()[0]

        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': False}],
            })
            assert resp.status_code == 200
            assert resp.json()['success'] is True

            token = f'acct:{account_fixture}'
            lesson_id = _get_lesson_id(group_fixture, token)
            assert lesson_id is not None
            _cleanup_lesson(lesson_id)
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])
```

- [ ] **Step 2: Run the new tests to verify they fail as expected**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_teacher_spa_api.py -k "test_present_blocked_when_no_paid_balance or test_absent_allowed_without_paid_balance" -q`
Expected: `test_present_blocked_when_no_paid_balance` FAILS (`assert body['success'] is False` — actual is `True`, since there's no check yet). `test_absent_allowed_without_paid_balance` already PASSES (present:false was never blocked) — that's fine, it documents the unaffected path and will guard against regressions later.

- [ ] **Step 3: Implement the balance check**

In `journal_django/apps/teacher_spa/services.py`, add the import at line 18 (right after the existing `link_facts` import):

```python
from apps.accounts.repository import get_by_id_with_teacher
from apps.finances.repository import balances_for_students
from apps.scheduling.repository import link_facts
from apps.teacher_spa import repository
```

Then insert this new step right after the `present_student_ids`/`attendance` loop (after line 206, before the `# 6. subLabel` comment):

```python
    # 5b. Блокировка отметки присутствия ученикам без оплаченных уроков. Баланс
    # считается СЕРВЕРОМ в момент отправки (тот же батч-расчёт, что read_all_students) —
    # клиент remaining не присылает, подделать нечем. Проверка ДО транзакции: при
    # нарушении урок не создаётся вообще (как остальные ранние бизнес-ошибки выше).
    if present_student_ids:
        balances = balances_for_students(present_student_ids)
        blocked_names = [
            s['name'] for s in students
            if s['present'] and by_name.get(s['name'])
            and balances.get(by_name[s['name']]['student_id'], 0) <= 0
        ]
        if blocked_names:
            return {
                'success': False,
                'error': f'У учеников без оплаченных уроков нельзя отметить посещение: {", ".join(blocked_names)}.',
            }
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_teacher_spa_api.py -k "test_present_blocked_when_no_paid_balance or test_absent_allowed_without_paid_balance" -q`
Expected: both PASS.

- [ ] **Step 5: Run the full backend suite to check for regressions**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa apps/scheduling apps/groups -q`
Expected: same pass count as the Task 1 baseline (all green — Task 1 already ensured the paid-balance fixtures cover every pre-existing `present:true` test).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/teacher_spa/services.py journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py
git commit -m "feat(teacher-spa): reject submitLesson attendance for students with no paid balance"
```

---

### Task 3: Frontend — disable marking + fix the group debt banner

**Files:**
- Modify: `journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx`
- Modify: `journal_django/frontend/teacher-src/src/styles/groups.css:145-170` (new `.is-blocked` style)

- [ ] **Step 1: Add the `isBlocked` helper**

In `journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx`, right after the existing `looksLikeUrl` helper (after line 21, before the `LessonForm` JSDoc comment):

```tsx
/** Ученик исчерпал оплаченные уроки (remaining<=0) — отмечать присутствие нельзя (см. submit_lesson на бэке). */
function isBlocked(s: { remaining: number }): boolean {
  return s.remaining <= 0;
}
```

- [ ] **Step 2: Default blocked students to absent on form open**

Replace the `present` state initializer (line 54-56):

```tsx
  const [present, setPresent] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(groupData.students.map((s) => [s.name, !isBlocked(s)])),
  );
```

- [ ] **Step 3: Base "Отметить всех" / debt banner on eligible (non-blocked) students**

Replace the `allPresent` line (line 71):

```tsx
  const eligibleStudents = groupData.students.filter((s) => !isBlocked(s));
  const allPresent = eligibleStudents.length > 0 && eligibleStudents.every((s) => present[s.name]);
```

Replace the `remaining`/`debtWarning` lines (lines 84-85):

```tsx
  const blockedStudents = groupData.students.filter((s) => isBlocked(s));
```

- [ ] **Step 4: Make `toggleAll` skip blocked students**

Replace `toggleAll` (lines 88-91):

```tsx
  const toggleAll = () => {
    const nextVal = !allPresent;
    setPresent(Object.fromEntries(
      groupData.students.map((s) => [s.name, isBlocked(s) ? false : nextVal]),
    ));
  };
```

- [ ] **Step 5: Disable the button per blocked student**

Replace the students render loop (lines 152-165):

```tsx
        <div className="lf-students">
          {groupData.students.map((s) => {
            const blocked = isBlocked(s);
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
                title={blocked ? 'Нет оплаченных уроков — отметить нельзя' : undefined}
              >
                <span className="lf-student-name">{s.name}</span>
                <span className="lf-student-state">
                  {blocked ? 'Нет оплаты' : present[s.name] ? 'Пришёл' : 'Не пришёл'}
                </span>
              </button>
            );
          })}
        </div>
```

- [ ] **Step 6: Replace the single-student debt banner with the real blocked list**

Replace the `debtWarning` banner block (lines 168-173):

```tsx
      {blockedStudents.length > 0 && (
        <div className="lf-warn">
          Нет оплаченных уроков: {blockedStudents.map((s) => s.name).join(', ')}. Отметить их нельзя
          {groupData.pm ? ` — сообщите менеджеру ${groupData.pm}.` : ' — сообщите менеджеру.'}
        </div>
      )}
```

- [ ] **Step 7: Add the `.is-blocked` style**

In `journal_django/frontend/teacher-src/src/styles/groups.css`, right after the existing `.lf-student.is-present` rule (after line 170):

```css
.lf-student.is-blocked {
  opacity: .5;
  cursor: not-allowed;
}
.lf-student.is-blocked .lf-student-state { color: var(--danger); }
```

- [ ] **Step 8: Typecheck**

Run: `cd journal_django/frontend/teacher-src && npm run typecheck`
Expected: no errors.

- [ ] **Step 9: Build**

Run: `cd journal_django/frontend/teacher-src && npm run build`
Expected: build succeeds (produces new hashed bundle in `../teacher-dist/assets/`).

- [ ] **Step 10: Manual browser verification**

There is no component test runner in `teacher-src` (established precedent — see `docs/superpowers/specs/2026-07-13-block-future-lesson-marking-design.md`, "Тесты" section). Start the dev stack (Django `runserver` + local nginx per `docs/` dev setup) and, in the teacher SPA:
1. Open a lesson form for a group with at least one student who has `remaining <= 0` (or temporarily zero out a test student's balance).
2. Confirm that student's row shows "Нет оплаты", is visually dimmed, and clicking it does nothing.
3. Confirm "Отметить всех" only toggles the other (paid) students.
4. Confirm the banner lists exactly the blocked student name(s) and mentions the group's PM contact.
5. Submit the lesson and confirm it succeeds (blocked student recorded absent, others as marked).

- [ ] **Step 11: Commit**

```bash
git add journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx journal_django/frontend/teacher-src/src/styles/groups.css journal_django/frontend/teacher-dist
git commit -m "feat(teacher-spa): block marking students with no paid lessons present"
```
