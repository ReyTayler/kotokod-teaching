# Раздел «Календарь» в admin SPA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a manager/admin/superadmin-only "Календарь" section to the admin SPA that shows one selected teacher's schedule, reusing the existing shared `CalendarView` component and the existing `build_calendar()` service.

**Architecture:** Backend adds one new read-only endpoint (`GET /api/admin/calendar?teacher_id=&from=&to=`, `IsManagerOrAdmin`) that calls the existing `services.build_calendar()` unchanged, plus an additive `groupId` field on the occurrence payload. Frontend adds a new page that reuses `shared/calendar/CalendarView` (already shared between teacher and admin SPA), gated by `RequireRole`, with a mandatory teacher-select filter and a read-only lesson popup that links to the group's detail page.

**Tech Stack:** Django + DRF (backend), React 19 + TanStack Query v5 + React Router v7 + TypeScript (admin SPA), pytest (backend tests only — admin-src has no JS test runner, verified via `tsc --noEmit` + manual browser check).

**Spec:** `docs/superpowers/specs/2026-07-13-admin-calendar-design.md`

---

### Task 1: `groupId` field on calendar occurrences (service layer)

**Files:**
- Modify: `journal_django/apps/scheduling/services.py:79-101`
- Test: `journal_django/apps/scheduling/tests/test_build_calendar.py` (new)

- [ ] **Step 1: Write the failing test**

Create `journal_django/apps/scheduling/tests/test_build_calendar.py`:

```python
"""
build_calendar() — сервисный тест (не API): groupId в occurrence-payload.
Нужен для ссылки «Открыть группу» в попапе admin-календаря (см.
docs/superpowers/specs/2026-07-13-admin-calendar-design.md).
"""
from __future__ import annotations

import datetime

import pytest

from apps.scheduling import repository, services

D = datetime.date
W_FROM = D(2026, 6, 1)
W_TO = D(2026, 6, 30)


@pytest.mark.django_db
def test_occurrence_includes_group_id(sched_setup):
    s = sched_setup
    repository.generate_for_group(s['group_a'])

    cal = services.build_calendar(W_FROM, W_TO, teacher_id=s['teacher_a'])

    assert len(cal['occurrences']) > 0
    assert cal['occurrences'][0]['groupId'] == s['group_a']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd journal_django && pytest apps/scheduling/tests/test_build_calendar.py -v`
Expected: FAIL with `KeyError: 'groupId'`.

- [ ] **Step 3: Write minimal implementation**

In `journal_django/apps/scheduling/services.py`, `_planned_occurrence_dict` currently returns (lines 79-101):

```python
    return {
        'group': r['group_name'],
        'groupDisplay': r['group_name'],
```

Change to:

```python
    return {
        'group': r['group_name'],
        'groupId': r['group_pk'],
        'groupDisplay': r['group_name'],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd journal_django && pytest apps/scheduling/tests/test_build_calendar.py -v`
Expected: PASS.

- [ ] **Step 5: Run existing calendar API tests to confirm no regression**

Run: `cd journal_django && pytest apps/scheduling/tests/test_calendar_api.py apps/scheduling/tests/test_teacher_reassignment.py -v`
Expected: all PASS (these tests check specific keys, not exhaustive key sets — an added key doesn't break them).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/scheduling/services.py journal_django/apps/scheduling/tests/test_build_calendar.py
git commit -m "feat(scheduling): include groupId in calendar occurrence payload"
```

---

### Task 2: Extract `_parse_window` helper (pure refactor, no behavior change)

**Files:**
- Modify: `journal_django/apps/scheduling/views.py:33-66`

- [ ] **Step 1: Extract the validation logic**

Current `journal_django/apps/scheduling/views.py` (lines 33-66):

```python
class CalendarView(APIView):
    """GET /api/calendar — плановые занятия преподавателя за окно [from, to]."""

    permission_classes = [IsTeacher]

    def get(self, request: Request) -> Response:
        raw_from = request.query_params.get('from')
        raw_to = request.query_params.get('to')
        if not raw_from or not raw_to:
            return Response(
                {'error': 'Обязательны параметры from и to (YYYY-MM-DD).'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            d_from = datetime.date.fromisoformat(raw_from)
            d_to = datetime.date.fromisoformat(raw_to)
        except ValueError:
            return Response(
                {'error': 'from/to должны быть датами YYYY-MM-DD.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if d_to < d_from:
            return Response(
                {'error': 'to не может быть раньше from.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (d_to - d_from).days > _MAX_WINDOW_DAYS:
            return Response(
                {'error': f'Слишком широкое окно (максимум {_MAX_WINDOW_DAYS} дней).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = services.build_calendar(d_from, d_to, teacher_id=request.user.teacher_id)
        return Response(result)
```

Replace with:

```python
def _parse_window(request: Request) -> tuple[datetime.date, datetime.date] | Response:
    """
    Валидирует ?from=&to= (YYYY-MM-DD, to>=from, ширина ≤ _MAX_WINDOW_DAYS).
    Возвращает (d_from, d_to), либо готовый Response с 400 при ошибке —
    вызывающая сторона проверяет `isinstance(result, Response)`. Общий код
    для CalendarView (teacher) и AdminCalendarView (manager/admin/superadmin).
    """
    raw_from = request.query_params.get('from')
    raw_to = request.query_params.get('to')
    if not raw_from or not raw_to:
        return Response(
            {'error': 'Обязательны параметры from и to (YYYY-MM-DD).'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        d_from = datetime.date.fromisoformat(raw_from)
        d_to = datetime.date.fromisoformat(raw_to)
    except ValueError:
        return Response(
            {'error': 'from/to должны быть датами YYYY-MM-DD.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if d_to < d_from:
        return Response(
            {'error': 'to не может быть раньше from.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if (d_to - d_from).days > _MAX_WINDOW_DAYS:
        return Response(
            {'error': f'Слишком широкое окно (максимум {_MAX_WINDOW_DAYS} дней).'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return d_from, d_to


class CalendarView(APIView):
    """GET /api/calendar — плановые занятия преподавателя за окно [from, to]."""

    permission_classes = [IsTeacher]

    def get(self, request: Request) -> Response:
        window = _parse_window(request)
        if isinstance(window, Response):
            return window
        d_from, d_to = window

        result = services.build_calendar(d_from, d_to, teacher_id=request.user.teacher_id)
        return Response(result)
```

- [ ] **Step 2: Run existing tests to confirm no behavior change**

Run: `cd journal_django && pytest apps/scheduling/tests/test_calendar_api.py -v`
Expected: all PASS, in particular the whole `TestWindowValidation` class (400 on missing/bad/reversed/too-wide window) — same status codes and error bodies as before.

- [ ] **Step 3: Commit**

```bash
git add journal_django/apps/scheduling/views.py
git commit -m "refactor(scheduling): extract _parse_window helper from CalendarView"
```

---

### Task 3: `GET /api/admin/calendar` endpoint

**Files:**
- Modify: `journal_django/apps/scheduling/views.py` (add `AdminCalendarView`, after the `# --- Admin-план ---` separator comment, before `_is_unique_violation`)
- Create: `journal_django/apps/scheduling/admin_urls.py`
- Modify: `journal_django/config/urls.py`
- Test: `journal_django/apps/scheduling/tests/test_admin_calendar.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `journal_django/apps/scheduling/tests/test_admin_calendar.py`:

```python
"""
API-тесты GET /api/admin/calendar (role=manager/admin/superadmin) — тот же
build_calendar(), что и teacher-эндпоинт (см. test_calendar_api.py), но
teacher_id передаётся явно параметром запроса вместо request.user.teacher_id.
"""
from __future__ import annotations

import pytest

from apps.scheduling import repository

pytestmark = pytest.mark.django_db

WIN = '&from=2026-06-01&to=2026-06-30'


class TestAuth:
    def test_no_cookie_401(self, anon_client, sched_setup):
        url = f"/api/admin/calendar?teacher_id={sched_setup['teacher_a']}{WIN}"
        assert anon_client.get(url).status_code == 401

    def test_teacher_role_403(self, teacher_client, sched_setup):
        url = f"/api/admin/calendar?teacher_id={sched_setup['teacher_a']}{WIN}"
        assert teacher_client.get(url).status_code == 403

    def test_manager_ok(self, manager_client, sched_setup):
        url = f"/api/admin/calendar?teacher_id={sched_setup['teacher_a']}{WIN}"
        assert manager_client.get(url).status_code == 200

    def test_admin_ok(self, admin_client, sched_setup):
        url = f"/api/admin/calendar?teacher_id={sched_setup['teacher_a']}{WIN}"
        assert admin_client.get(url).status_code == 200

    def test_superadmin_ok(self, superadmin_client, sched_setup):
        url = f"/api/admin/calendar?teacher_id={sched_setup['teacher_a']}{WIN}"
        assert superadmin_client.get(url).status_code == 200


class TestValidation:
    def test_missing_teacher_id_400(self, manager_client):
        resp = manager_client.get('/api/admin/calendar?from=2026-06-01&to=2026-06-30')
        assert resp.status_code == 400

    def test_non_numeric_teacher_id_400(self, manager_client):
        resp = manager_client.get(
            '/api/admin/calendar?teacher_id=abc&from=2026-06-01&to=2026-06-30',
        )
        assert resp.status_code == 400

    def test_missing_window_400(self, manager_client, sched_setup):
        resp = manager_client.get(f"/api/admin/calendar?teacher_id={sched_setup['teacher_a']}")
        assert resp.status_code == 400


class TestCalendar:
    def test_returns_only_selected_teacher(self, manager_client, sched_setup):
        s = sched_setup
        repository.generate_for_group(s['group_a'])
        repository.generate_for_group(s['group_b'])

        body = manager_client.get(f"/api/admin/calendar?teacher_id={s['teacher_a']}{WIN}").json()
        groups = {o['group'] for o in body['occurrences']}
        assert '__sched_group_A__' in groups
        assert '__sched_group_B__' not in groups

    def test_occurrence_has_group_id(self, manager_client, sched_setup):
        s = sched_setup
        repository.generate_for_group(s['group_a'])

        body = manager_client.get(f"/api/admin/calendar?teacher_id={s['teacher_a']}{WIN}").json()
        assert body['occurrences'][0]['groupId'] == s['group_a']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd journal_django && pytest apps/scheduling/tests/test_admin_calendar.py -v`
Expected: FAIL with 404 (no such URL yet) on every test.

- [ ] **Step 3: Add `AdminCalendarView`**

In `journal_django/apps/scheduling/views.py`, find this existing block:

```python
# ---------------------------------------------------------------------------
# Admin-план (RBAC IsManagerOrAdmin). Операции над planned_lessons
# (generate/reschedule/permanent-change/cancel/extra). Смонтированы под
# /api/admin/groups (ДО teacher-guard /api) → доступ проверяется на API, а не
# только на фронте. Мутации проходят DRF SessionAuthentication/CookieJWT →
# требуют X-CSRFToken (@csrf_exempt не ставим). Аудит — log_event в services.
# ---------------------------------------------------------------------------

def _is_unique_violation(exc: Exception) -> bool:
```

Insert a new `AdminCalendarView` class directly between the separator comment and `_is_unique_violation`:

```python
class AdminCalendarView(APIView):
    """
    GET /api/admin/calendar — плановые занятия ПРОИЗВОЛЬНОГО преподавателя за
    окно [from, to] (role=manager/admin/superadmin). Используется разделом
    «Календарь» admin SPA. teacher_id обязателен параметром запроса — без
    него build_calendar() вернул бы пустой конверт, а не ошибку, поэтому
    валидируем явно (400), не полагаясь на то, что фронт не даст открыть
    сетку без выбранного преподавателя.
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        window = _parse_window(request)
        if isinstance(window, Response):
            return window
        d_from, d_to = window

        raw_teacher_id = request.query_params.get('teacher_id')
        if not raw_teacher_id or not raw_teacher_id.isdigit():
            return Response(
                {'error': 'Обязателен параметр teacher_id (целое число).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = services.build_calendar(d_from, d_to, teacher_id=int(raw_teacher_id))
        return Response(result)


```

- [ ] **Step 4: Register the URL**

Create `journal_django/apps/scheduling/admin_urls.py`:

```python
"""
URL-конфиг admin-календаря — /api/admin/calendar (role=manager/admin/
superadmin). Отдельный файл от urls.py (тот монтируется под /api,
teacher-guard секция): этот монтируется под /api/admin/*, ДО teacher-guard
(см. config/urls.py, правило «Admin обязан стоять ДО teacher-guard»).
"""
from django.urls import path

from apps.scheduling import views

urlpatterns = [
    path('', views.AdminCalendarView.as_view(), name='scheduling-admin-calendar'),
]
```

In `journal_django/config/urls.py`, current line 42:

```python
    path('api/admin/renewals', include('apps.renewals.urls')),
```

Add right after it:

```python
    path('api/admin/renewals', include('apps.renewals.urls')),
    # Календарь (админ, произвольный преподаватель) — /api/admin/calendar
    path('api/admin/calendar', include('apps.scheduling.admin_urls')),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd journal_django && pytest apps/scheduling/tests/test_admin_calendar.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full scheduling test suite to confirm no regression**

Run: `cd journal_django && pytest apps/scheduling -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/scheduling/views.py journal_django/apps/scheduling/admin_urls.py journal_django/config/urls.py journal_django/apps/scheduling/tests/test_admin_calendar.py
git commit -m "feat(scheduling): add GET /api/admin/calendar for manager/admin/superadmin"
```

---

### Task 4: `groupId` + `onOpenGroup` plumbing in the shared calendar component

**Files:**
- Modify: `journal_django/frontend/admin-src/src/shared/calendar/types.ts:20-55`
- Modify: `journal_django/frontend/admin-src/src/shared/calendar/LessonPopup.tsx`
- Modify: `journal_django/frontend/admin-src/src/shared/calendar/CalendarView.tsx`

No JS test runner exists in `admin-src` (`package.json` has no `test` script) — this task is verified with `tsc --noEmit` plus the manual browser check in Task 7.

- [ ] **Step 1: Add `groupId` to `Occurrence`**

In `journal_django/frontend/admin-src/src/shared/calendar/types.ts`, the `Occurrence` interface currently starts (lines 20-28):

```ts
export interface Occurrence {
  /**
   * PlannedLesson.id — заполняется ТОЛЬКО admin-мапингом (useGroupPlanCalendar),
   * нужен для операций плана (reschedule/cancel по id). Teacher /api/calendar
   * это поле не отдаёт (не входит в замороженный ответ, см. services.py) —
   * поэтому optional, чтобы не требовать его от teacher-src/src/lib/types.ts.
   */
  id?: number | null;
  group: string;
```

Add right after the `id` field:

```ts
export interface Occurrence {
  /**
   * PlannedLesson.id — заполняется ТОЛЬКО admin-мапингом (useGroupPlanCalendar),
   * нужен для операций плана (reschedule/cancel по id). Teacher /api/calendar
   * это поле не отдаёт (не входит в замороженный ответ, см. services.py) —
   * поэтому optional, чтобы не требовать его от teacher-src/src/lib/types.ts.
   */
  id?: number | null;
  /**
   * groups.id занятия — отдаёт GET /api/admin/calendar (см. services.py
   * _planned_occurrence_dict). Нужен для кнопки «Открыть группу» в
   * LessonPopup (onOpenGroup). /api/admin/groups/<id>/plan-мапинг
   * (useGroupPlanCalendar) его не выставляет — там уже открыта карточка
   * группы, ссылка не нужна.
   */
  groupId?: number | null;
  group: string;
```

- [ ] **Step 2: Add `onOpenGroup` to `LessonPopup`**

In `journal_django/frontend/admin-src/src/shared/calendar/LessonPopup.tsx`, the export signature currently is (lines 20-32):

```tsx
export function LessonPopup({
  lesson,
  onClose,
  onSubmit,
  onAction,
  role,
}: {
  lesson: Occurrence;
  onClose: () => void;
  onSubmit?: () => void;
  onAction?: (kind: LessonActionKind, lesson: Occurrence) => void;
  role?: 'teacher' | 'admin';
}) {
```

Change to:

```tsx
export function LessonPopup({
  lesson,
  onClose,
  onSubmit,
  onAction,
  onOpenGroup,
  role,
}: {
  lesson: Occurrence;
  onClose: () => void;
  onSubmit?: () => void;
  onAction?: (kind: LessonActionKind, lesson: Occurrence) => void;
  /** Кнопка «Открыть группу» — не связана с onAction/onSubmit, видна независимо от role, если передан И lesson.groupId задан. Используется admin-календарём («Календарь» → /admin/groups/:id), не задействован ни в teacher, ни в GroupDetailPage (там карточка группы уже открыта). */
  onOpenGroup?: (lesson: Occurrence) => void;
  role?: 'teacher' | 'admin';
}) {
```

Then, right after the `{lesson.students.length > 0 && (...)}` block and before the `{canModifyPlan && (...)}` block, insert:

```tsx
      {onOpenGroup && lesson.groupId != null && (
        <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          <Button size="sm" onClick={() => onOpenGroup(lesson)}>Открыть группу</Button>
        </div>
      )}

```

- [ ] **Step 3: Plumb `onOpenGroup` through `CalendarView`**

In `journal_django/frontend/admin-src/src/shared/calendar/CalendarView.tsx`, the `CalendarViewProps` interface currently ends with (lines 82-90):

```ts
  onAction?: (kind: LessonActionKind, occ: Occurrence) => void;
  /**
   * Перехват клика по занятию (teacher: контекстное меню «Отметить урок /
   * Карточка группы / Чат / Подробности» в точке клика). Если передан,
   * встроенный LessonPopup по клику НЕ открывается — вызывающая сторона
   * показывает меню и открывает LessonPopup сама (пункт «Подробности»).
   * Не передан (admin) — прежнее поведение: клик сразу открывает LessonPopup.
   */
  onOccurrenceMenu?: (occ: Occurrence, pos: { x: number; y: number }) => void;
}
```

Add a new prop after `onOccurrenceMenu`:

```ts
  onAction?: (kind: LessonActionKind, occ: Occurrence) => void;
  /**
   * Перехват клика по занятию (teacher: контекстное меню «Отметить урок /
   * Карточка группы / Чат / Подробности» в точке клика). Если передан,
   * встроенный LessonPopup по клику НЕ открывается — вызывающая сторона
   * показывает меню и открывает LessonPopup сама (пункт «Подробности»).
   * Не передан (admin) — прежнее поведение: клик сразу открывает LessonPopup.
   */
  onOccurrenceMenu?: (occ: Occurrence, pos: { x: number; y: number }) => void;
  /** Кнопка «Открыть группу» в LessonPopup (см. LessonPopup.onOpenGroup) — используется admin-календарём раздела «Календарь». */
  onOpenGroup?: (occ: Occurrence) => void;
}
```

Then update the function signature (lines 99-110):

```tsx
export function CalendarView({
  occurrences: occAll,
  unscheduled,
  isLoading,
  isError,
  isFetching,
  onVisibleRangeChange,
  onLessonAction,
  role,
  onAction,
  onOccurrenceMenu,
}: CalendarViewProps) {
```

to:

```tsx
export function CalendarView({
  occurrences: occAll,
  unscheduled,
  isLoading,
  isError,
  isFetching,
  onVisibleRangeChange,
  onLessonAction,
  role,
  onAction,
  onOccurrenceMenu,
  onOpenGroup,
}: CalendarViewProps) {
```

Finally, update the internal `<LessonPopup>` render (lines 369-377):

```tsx
      {selected && (
        <LessonPopup
          lesson={selected}
          onClose={() => setSelected(null)}
          onSubmit={onLessonAction ? () => onLessonAction(selected) : undefined}
          onAction={onAction ? (kind, occ) => { setSelected(null); onAction(kind, occ); } : undefined}
          role={role}
        />
      )}
```

to:

```tsx
      {selected && (
        <LessonPopup
          lesson={selected}
          onClose={() => setSelected(null)}
          onSubmit={onLessonAction ? () => onLessonAction(selected) : undefined}
          onAction={onAction ? (kind, occ) => { setSelected(null); onAction(kind, occ); } : undefined}
          onOpenGroup={onOpenGroup}
          role={role}
        />
      )}
```

- [ ] **Step 4: Typecheck**

Run: `cd journal_django/frontend/admin-src && npm run typecheck`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/shared/calendar/types.ts journal_django/frontend/admin-src/src/shared/calendar/LessonPopup.tsx journal_django/frontend/admin-src/src/shared/calendar/CalendarView.tsx
git commit -m "feat(calendar): add optional groupId field and onOpenGroup link button"
```

---

### Task 5: `useAdminCalendar` hook

**Files:**
- Create: `journal_django/frontend/admin-src/src/hooks/useAdminCalendar.ts`

- [ ] **Step 1: Write the hook**

```ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { CalendarResponse } from '../shared/calendar/types';

/**
 * GET /api/admin/calendar?teacher_id=&from=&to= (role=manager/admin/
 * superadmin) — то же build_calendar(), что и teacher /api/calendar, но
 * teacher_id выбирается вручную (раздел «Календарь» admin SPA). teacherId
 * null → запрос не уходит (enabled=false), пока преподаватель не выбран.
 */
export function useAdminCalendar(teacherId: number | null, from: string, to: string) {
  return useQuery<CalendarResponse>({
    queryKey: ['admin-calendar', teacherId, from, to],
    queryFn: () => api<CalendarResponse>(
      'GET',
      `/api/admin/calendar?teacher_id=${teacherId}&from=${from}&to=${to}`,
    ),
    enabled: teacherId != null,
    placeholderData: (prev) => prev,
    staleTime: 60_000,
  });
}
```

- [ ] **Step 2: Typecheck**

Run: `cd journal_django/frontend/admin-src && npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/hooks/useAdminCalendar.ts
git commit -m "feat(admin-src): add useAdminCalendar hook"
```

---

### Task 6: `AdminCalendarPage`

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/calendar/AdminCalendarPage.tsx`
- Create: `journal_django/frontend/admin-src/src/styles/pages/admin-calendar.css`
- Modify: `journal_django/frontend/admin-src/src/styles/index.css:14`

- [ ] **Step 1: Write the page component**

Create `journal_django/frontend/admin-src/src/pages/calendar/AdminCalendarPage.tsx`:

```tsx
import { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTeachers } from '../../hooks/useTeachers';
import { useAdminCalendar } from '../../hooks/useAdminCalendar';
import { CalendarView } from '../../shared/calendar/CalendarView';
import { Field } from '../../components/form/Field';
import { Combobox } from '../../components/form/Combobox';
import { currentMondayMsk, addDays, isoDate } from '../../shared/calendar/lib';
import type { Occurrence } from '../../shared/calendar/types';

/**
 * Раздел «Календарь» admin SPA — read-only расписание ОДНОГО выбранного
 * преподавателя (RequireRole manager/admin/superadmin в App.tsx). Обёртка
 * над презентационным CalendarView (см. teacher-src CalendarPage.tsx для
 * оригинального паттерна) — без onAction/onLessonAction, попап занятия
 * строго read-only, с кнопкой перехода в план группы (onOpenGroup).
 */
export default function AdminCalendarPage() {
  const navigate = useNavigate();
  const teachers = useTeachers();
  const [teacherId, setTeacherId] = useState<number | null>(null);
  const [range, setRange] = useState(() => {
    const monday = currentMondayMsk();
    return { from: isoDate(monday), to: isoDate(addDays(monday, 6)) };
  });

  const teacherOptions = useMemo(
    () => (teachers.data || []).slice().sort((a, b) => a.name.localeCompare(b.name))
      .map((t) => ({ value: String(t.id), label: t.name })),
    [teachers.data],
  );

  const { data, isLoading, isError, isFetching } = useAdminCalendar(teacherId, range.from, range.to);

  const onVisibleRangeChange = useCallback((from: string, to: string) => {
    setRange((prev) => (prev.from === from && prev.to === to ? prev : { from, to }));
  }, []);

  const onOpenGroup = useCallback((occ: Occurrence) => {
    if (occ.groupId != null) navigate(`/admin/groups/${occ.groupId}`);
  }, [navigate]);

  return (
    <div className="admin-calendar-page">
      <div className="admin-calendar-page__filter">
        <Field label="Преподаватель">
          <Combobox
            value={teacherId != null ? String(teacherId) : ''}
            onChange={(v) => setTeacherId(v ? Number(v) : null)}
            options={teacherOptions}
            placeholder="Выберите преподавателя"
          />
        </Field>
      </div>

      {teacherId == null ? (
        <div className="cal-empty">Выберите преподавателя, чтобы увидеть расписание.</div>
      ) : (
        <CalendarView
          occurrences={data?.occurrences ?? []}
          unscheduled={data?.unscheduled ?? []}
          isLoading={isLoading}
          isError={isError}
          isFetching={isFetching}
          onVisibleRangeChange={onVisibleRangeChange}
          role="admin"
          onOpenGroup={onOpenGroup}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add page CSS**

Create `journal_django/frontend/admin-src/src/styles/pages/admin-calendar.css`:

```css
/* ============================================================
 *  ADMIN CALENDAR PAGE (раздел «Календарь», manager/admin/superadmin)
 *  Обёртка над shared CalendarView — только фильтр-преподаватель
 *  и пустое состояние до выбора. Сам календарь стилизован в
 *  shared/calendar/calendar.css.
 * ============================================================ */

.admin-calendar-page {
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.admin-calendar-page__filter {
  max-width: 320px;
}
```

In `journal_django/frontend/admin-src/src/styles/index.css`, line 14 is:

```css
@import './pages/renewals.css';
```

Add right after it:

```css
@import './pages/renewals.css';
@import './pages/admin-calendar.css';
```

- [ ] **Step 3: Typecheck**

Run: `cd journal_django/frontend/admin-src && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/calendar/AdminCalendarPage.tsx journal_django/frontend/admin-src/src/styles/pages/admin-calendar.css journal_django/frontend/admin-src/src/styles/index.css
git commit -m "feat(admin-src): add AdminCalendarPage"
```

---

### Task 7: Route + navigation entry

**Files:**
- Modify: `journal_django/frontend/admin-src/src/App.tsx`
- Modify: `journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx`

- [ ] **Step 1: Register the route**

In `journal_django/frontend/admin-src/src/App.tsx`, add the import after line 20 (`import LessonDetailPage from './pages/lessons/LessonDetailPage';`):

```tsx
import LessonDetailPage from './pages/lessons/LessonDetailPage';
import AdminCalendarPage from './pages/calendar/AdminCalendarPage';
```

Then, current line 56:

```tsx
            <Route path="/admin/payroll" element={<RequireRole roles={['superadmin']}><PayrollPage /></RequireRole>} />
```

Add right after it:

```tsx
            <Route path="/admin/payroll" element={<RequireRole roles={['superadmin']}><PayrollPage /></RequireRole>} />
            <Route path="/admin/calendar" element={<RequireRole roles={['manager','admin','superadmin']}><AdminCalendarPage /></RequireRole>} />
```

- [ ] **Step 2: Add the sidebar entry**

In `journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx`, add a `calendar` entry to `NAV_ICONS` right after the `lessons` entry (lines 44-49):

```tsx
  lessons: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
      <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
    </svg>
  ),
  calendar: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
      <line x1="16" y1="2" x2="16" y2="6"/>
      <line x1="8" y1="2" x2="8" y2="6"/>
      <line x1="3" y1="10" x2="21" y2="10"/>
    </svg>
  ),
```

Then add a `SECTIONS` entry right after `lessons` (lines 117-129):

```tsx
export const SECTIONS = [
  { key: 'dashboard', label: 'Дашборд', path: '/admin/dashboard' },
  { key: 'students', label: 'Ученики', path: '/admin/students' },
  { key: 'groups', label: 'Группы', path: '/admin/groups' },
  { key: 'teachers', label: 'Преподаватели', path: '/admin/teachers' },
  { key: 'directions', label: 'Направления', path: '/admin/directions' },
  { key: 'lessons', label: 'Уроки', path: '/admin/lessons' },
  { key: 'calendar', label: 'Календарь', path: '/admin/calendar' },
  { key: 'subscriptions', label: 'Абонементы', path: '/admin/subscriptions' },
  { key: 'renewals', label: 'Продления', path: '/admin/renewals' },
  { key: 'payroll', label: 'Зарплата', path: '/admin/payroll' },
  { key: 'archive', label: 'Архив', path: '/admin/archive' },
  { key: 'settings', label: 'Настройки', path: '/admin/settings' },
];
```

`SECTIONS` isn't filtered by role except for `payroll` (superadmin-only) — `manager`/`admin`/`superadmin` are the only roles that reach the admin SPA at all, so the new `calendar` entry needs no extra visibility filter (matches how `renewals` is already handled: the route's `RequireRole` is the actual gate).

- [ ] **Step 3: Typecheck**

Run: `cd journal_django/frontend/admin-src && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/App.tsx journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx
git commit -m "feat(admin-src): wire up /admin/calendar route and sidebar entry"
```

---

### Task 8: End-to-end manual verification

**Files:** none (verification only)

- [ ] **Step 1: Start the backend**

Run: `cd journal_django && python manage.py runserver` (background)

- [ ] **Step 2: Start the admin SPA dev server**

Run: `cd journal_django/frontend/admin-src && npm run dev` (background)

- [ ] **Step 3: Verify as manager/admin/superadmin**

Log in to the admin SPA with a manager, admin, or superadmin account. Confirm:
- Sidebar shows a "Календарь" item.
- `/admin/calendar` shows the empty state ("Выберите преподавателя…") with no calendar grid until a teacher is picked.
- Picking a teacher in the combobox loads their week view (matching what that teacher sees in the teacher SPA calendar).
- Week/month/list toggle, prev/next navigation, and the direction legend/filter all work, same as the teacher SPA calendar.
- Clicking a lesson opens a read-only popup: no "Перенести"/"Отменить"/"Сменить преподавателя"/"Отметить урок" buttons.
- The popup shows an "Открыть группу" button that navigates to `/admin/groups/:id` for that lesson's group.
- Switching the teacher in the combobox reloads the grid for the new teacher.

- [ ] **Step 4: Verify RBAC**

Log in as a teacher-role account (or navigate directly to `/admin/calendar` while authenticated as teacher, if the teacher role can reach the admin SPA login at all): confirm redirect to `/admin/dashboard` (via `RequireRole`). Confirm a direct `curl`/browser request to `/api/admin/calendar?...` without manager/admin/superadmin auth returns 401/403 (already covered by Task 3's automated tests, but worth a spot check with the running server).

- [ ] **Step 5: Report results**

No commit for this task — it's verification only. If any check fails, fix the underlying task and re-run this checklist before considering the feature done.
