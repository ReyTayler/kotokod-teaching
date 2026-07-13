# Block Future Lesson Marking + Lock Report Date — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent teachers from marking attendance for lessons scheduled in the future, and lock the lesson-date field in the report form so it always equals the scheduled date, on both the Teacher SPA frontend and the Django backend.

**Architecture:** Backend gets a defense-in-depth guard in `teacher_spa.services.submit_lesson` comparing the submitted date string to MSK "today" (string comparison, day-only). Frontend gets two independent UI changes: the calendar's context menu disables "Отметить урок" (with a visible caption) for occurrences whose date is in the future, and the lesson report form (`LessonForm`) makes the date field permanently read-only instead of editable.

**Tech Stack:** Django 5 + DRF (backend, pytest), React 19 + TypeScript + Vite (teacher-src frontend, manual browser verification — no component test runner exists in teacher-src).

Spec: `docs/superpowers/specs/2026-07-13-block-future-lesson-marking-design.md`

---

### Task 1: Backend — reject future-dated lesson submissions

**Files:**
- Modify: `journal_django/apps/teacher_spa/services.py:111-114`
- Test: `journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py`

- [ ] **Step 1: Write the failing test**

Open `journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py`. Inside `class TestSubmitLesson`, insert a new test method immediately after `test_group_not_found` (which ends at line 189) and before `test_valid_submit_creates_records` (which starts at line 191):

```python
    def test_future_date_rejected(self, teacher_fixture, account_fixture):
        """Дата урока в будущем (позже сегодняшней МСК) → 200 {success:false}, без побочных эффектов."""
        resp = self._submit(account_fixture, {
            'group': '__nonexistent_group__',
            'date': '2099-01-01',
            'students': [],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['success'] is False
        assert 'наступил' in body['error']
```

This uses a group name that doesn't exist (`__nonexistent_group__`, same placeholder `test_group_not_found` uses) precisely to prove the future-date check runs *before* any group lookup — if the check were missing or placed after group resolution, the response would be the existing `'Группа не найдена'` error instead, and the `'наступил' in body['error']` assertion would fail.

- [ ] **Step 2: Run test to verify it fails**

Run (from `journal_django/`, using the project's venv):
```
journal_django/.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_teacher_spa_api.py::TestSubmitLesson::test_future_date_rejected -v
```
Expected: FAIL — `assert 'наступил' in body['error']` fails because `body['error']` is currently `'Группа не найдена'`.

- [ ] **Step 3: Write minimal implementation**

In `journal_django/apps/teacher_spa/services.py`, find lines 111-114:

```python
    group = validated['group']
    date = validated['date']
    record_url = validated.get('recordUrl') or None
    students = validated['students']
```

Replace with:

```python
    group = validated['group']
    date = validated['date']
    record_url = validated.get('recordUrl') or None
    students = validated['students']

    # Дата занятия жёстко фиксирована на фронте (LessonForm не даёт её менять) —
    # это подстраховка от гонки состояний (устаревший кэш календаря) и прямых
    # запросов к API. Сравнение только по дню (строки 'YYYY-MM-DD' сравнимы
    # лексикографически), без учёта времени начала урока.
    if date > format_msk_date():
        return {
            'success': False,
            'error': 'Урок ещё не наступил — отметить его можно только в день занятия или позже.',
        }
```

`format_msk_date` is already imported at the top of this file (used later at line ~174 for the penalty calculation) — no new import needed. Confirm the import is present:

```
grep -n "format_msk_date" journal_django/apps/teacher_spa/services.py
```
Expected output includes both the existing `from apps.teacher_spa.calculator import (...)` block and the new usage line.

- [ ] **Step 4: Run test to verify it passes**

Run:
```
journal_django/.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_teacher_spa_api.py::TestSubmitLesson::test_future_date_rejected -v
```
Expected: PASS.

- [ ] **Step 5: Run the full submitLesson test class to check for regressions**

Run:
```
journal_django/.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_teacher_spa_api.py::TestSubmitLesson -v
```
Expected: all PASS (existing tests use `'date': '2026-06-10'`, which is in the past relative to any real run date, so the new guard does not affect them).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/teacher_spa/services.py journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py
git commit -m "fix(teacher-spa): reject submitLesson for future-dated occurrences"
```

---

### Task 2: Frontend — disable "Отметить урок" for future occurrences

**Files:**
- Modify: `journal_django/frontend/teacher-src/src/pages/calendar/OccurrenceMenu.tsx`
- Modify: `journal_django/frontend/teacher-src/src/styles/pages.css:64-77`

- [ ] **Step 1: Add the future-date check and disabled+captioned menu item**

In `journal_django/frontend/teacher-src/src/pages/calendar/OccurrenceMenu.tsx`, change the import on line 1 to also pull in the date helpers:

```tsx
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { Occurrence } from '../../lib/types';
import { isoDate, todayMsk } from '../../lib/dates';
```

Update the doc comment (lines 4-11) to describe the new state:

```tsx
/**
 * Контекстное меню занятия в календаре (по клику на ячейку): Отметить урок /
 * Открыть карточку группы / Перейти в чат / Подробности. Позиция — точка
 * клика с клампом в вьюпорт; закрытие — клик мимо или Escape.
 *
 * «Отметить урок»: скрыт для done/cancelled (заполнять нечего); задизейблен
 * с подписью для будущей даты (occ.date > сегодня МСК, сравнение по дню, без
 * учёта времени начала) — занятие ещё не наступило; иначе активен.
 * «Перейти в чат» неактивен без groups.vk_chat (occ.vkChat).
 */
```

Replace line 57 (`const canSubmit = occ.status !== 'done' && occ.status !== 'cancelled';`) with:

```tsx
  const todayIso = isoDate(todayMsk());
  const isFillable = occ.status !== 'done' && occ.status !== 'cancelled';
  const isFuture = occ.date > todayIso;
```

Replace the button block (current lines 66-70):

```tsx
      {canSubmit && (
        <button type="button" className="occ-menu-item" role="menuitem" onClick={onSubmitLesson}>
          Отметить урок
        </button>
      )}
```

with:

```tsx
      {isFillable && (
        <button
          type="button"
          className="occ-menu-item"
          role="menuitem"
          disabled={isFuture}
          title={isFuture ? 'Занятие ещё не наступило' : undefined}
          onClick={onSubmitLesson}
        >
          Отметить урок
          {isFuture && <span className="occ-menu-item-hint">доступно в день урока</span>}
        </button>
      )}
```

- [ ] **Step 2: Add the caption style**

In `journal_django/frontend/teacher-src/src/styles/pages.css`, after line 77 (`.occ-menu-item:disabled { color: var(--text4); cursor: not-allowed; }`), add:

```css
.occ-menu-item-hint {
  display: block;
  font-size: 11px;
  color: var(--text4);
  margin-top: 2px;
}
```

- [ ] **Step 3: Type-check the teacher-src build**

Run (from `journal_django/frontend/teacher-src/`):
```
npm run build
```
Expected: build succeeds with no TypeScript errors (this also catches any typo in the `Occurrence`/date-helper usage).

- [ ] **Step 4: Manual verification in the browser**

Start the teacher SPA dev server per the project's existing local dev setup (nginx on :8080 proxying to Django runserver, per `docs/reference_local_nginx` conventions already in place — do not invent a new dev workflow). In the calendar view:
- Click a past or today's occurrence that isn't `done`/`cancelled` → context menu shows an active "Отметить урок" button that opens `LessonForm`.
- Click a future-dated occurrence (any day after today in the same week/next week view) → context menu shows "Отметить урок" grayed out, non-clickable, with the "доступно в день урока" caption underneath, and a native tooltip ("Занятие ещё не наступило") on hover.
- Click a `done`/`cancelled` occurrence → "Отметить урок" is absent entirely, as before.

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/teacher-src/src/pages/calendar/OccurrenceMenu.tsx journal_django/frontend/teacher-src/src/styles/pages.css
git commit -m "feat(teacher-spa): disable marking future-dated occurrences in calendar menu"
```

---

### Task 3: Frontend — lock the date field in the lesson report form

**Files:**
- Modify: `journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx:134-136`

- [ ] **Step 1: Make the DateInput read-only**

In `journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx`, replace lines 134-136:

```tsx
      <Field label="Дата урока">
        <DateInput value={date} onChange={(e) => setDate(e.target.value)} />
      </Field>
```

with:

```tsx
      <Field label="Дата урока">
        <DateInput value={date} onChange={(e) => setDate(e.target.value)} disabled />
      </Field>
```

`DateInput` (`@shared/components/form/DateInput`, i.e. `journal_django/frontend/admin-src/src/components/form/DateInput.tsx:94`) already supports a `disabled` prop that blocks both typing and opening the calendar popover — no change needed to the shared component itself (it belongs to admin-src, which teacher-src only reads from during this migration phase, per the existing comment on `vite.config.ts:7`).

The `onChange` handler is kept (harmless — `disabled` prevents it from ever firing) rather than removed, so `setDate`/`date` stay wired for the rest of the component (`penaltyWarning`, the submit payload) without further edits.

- [ ] **Step 2: Type-check the teacher-src build**

Run (from `journal_django/frontend/teacher-src/`):
```
npm run build
```
Expected: build succeeds with no TypeScript errors.

- [ ] **Step 3: Manual verification in the browser**

- Open "Мои уроки" and click a today's lesson → `LessonForm` opens with today's date shown in a visibly disabled date field; clicking it does not open the calendar popover and does not allow typing.
- Open the calendar, click a past (overdue) occurrence → "Отметить урок" → `LessonForm` opens with that occurrence's date pre-filled and locked; the existing "штраф 40 ₽" warning still appears (since `date !== todayIso`).
- Confirm there is no remaining way to change the date before saving.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx
git commit -m "fix(teacher-spa): lock lesson date field to the scheduled date in report form"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 covers the backend guard; Task 2 covers the frontend "block marking future lessons" requirement (calendar entry point — the only place a future date can be selected, since `MyLessonsPage` only ever shows today); Task 3 covers "date cannot be changed in the report form." All three spec sections have a task.
- **Placeholder scan:** none — every step has literal file paths, line numbers, and complete code/commands.
- **Type consistency:** `isoDate`/`todayMsk` (from `lib/dates.ts`) and `Occurrence.date`/`.status` (from `lib/types.ts`) are used with the same names and shapes established during design exploration; `disabled` prop name matches `DateInput`'s existing `Props` (`admin-src/src/components/form/DateInput.tsx:94`).
