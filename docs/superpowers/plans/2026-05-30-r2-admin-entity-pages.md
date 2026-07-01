# R2 Admin Entity Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить 8 stub-страниц admin SPA на полнофункциональные React-страницы (list + detail + form/modal + entity-specific блоки) с TanStack Query-кешом и автоинвалидацией мутаций. После R2 функциональность admin SPA должна полностью соответствовать pre-R1 vanilla-версии.

**Architecture:** Каждая сущность — отдельная папка `pages/<entity>/` с `<Entity>ListPage.tsx`, `<Entity>DetailPage.tsx`, `<Entity>FormModal.tsx`. Серверный state — через хуки `hooks/use<Entity>.ts` (useQuery + useMutation). Общие визуальные паттерны (KOTOKOD hero, dir-card, lesson grid, attendance, slot editor, memberships block, status badge, mono badge) — выносятся в `components/<domain>/`. Параллельное разбиение: A = students + memberships, B = groups + lessons + payroll, C = teachers + tokens + directions + archive.

**Tech Stack:** React 19, TanStack Query v5, React Router v7, Radix UI Dialog, Lucide React, существующий `style.css` (классы не меняем).

**Cutover strategy:** Per-entity. Каждый агент работает в своей папке `pages/<entity>/`. Общие компоненты и хуки создаются в Task 1-4 (фаза подготовки) ДО старта параллельных потоков. После завершения всех потоков — финальный smoke + cleanup.

---

## File Structure

### Создаются (фаза подготовки, Task 1-4)

```
web/admin/src/
├─ lib/
│  ├─ pricing.ts                  # calcPayment(total, present, isHalf)
│  ├─ slots.ts                    # DOW, formatSlot, MONTHS_RU
│  └─ direction-color.ts          # directionColor(dir|name|hex)
├─ hooks/
│  ├─ useApiError.ts              # toast wrapper для ошибок useMutation
│  ├─ useStudents.ts              # query+mutations + studentStats
│  ├─ useGroups.ts                # query+mutations (include slots)
│  ├─ useTeachers.ts              # query+mutations
│  ├─ useTokens.ts                # query+mutations + useGenerateToken
│  ├─ useDirections.ts            # query+mutations
│  ├─ useLessons.ts               # list+detail (lesson-full)+mutations+attendanceToggle
│  ├─ usePayroll.ts               # list+summary+updatePayroll
│  ├─ useMemberships.ts           # filtered list (by group/student) + mutations
│  └─ useArchive.ts               # 4 параллельных запроса include_inactive=1
├─ components/
│  ├─ ui/
│  │  ├─ Pill.tsx                 # pillHtml-equivalent (round badge)
│  │  ├─ MonoBadge.tsx            # monospace token chip
│  │  └─ DirTag.tsx               # direction tag (.dir-tag)
│  ├─ form/
│  │  ├─ ColorInput.tsx           # <input type="color">
│  │  └─ EntityForm.tsx           # generic схема→форма (см. Task 3)
│  └─ memberships/
│     └─ MembershipsBlock.tsx     # student↔group двунаправленный блок
└─ vite-env.d.ts                  # (уже есть — не трогаем)
```

### Расширяются

- `web/admin/src/App.tsx` — добавляются маршруты `/admin/<section>/:id` для каждой сущности

### Создаются (Phase A — students + memberships, Task 5-7)

```
web/admin/src/pages/students/
├─ StudentsListPage.tsx           # таблица + поиск + Add
├─ StudentDetailPage.tsx          # KOTOKOD hero + DetailShell + stats + memberships
├─ StudentFormModal.tsx           # форма с auto-freeze логикой
└─ StudentStatsBlock.tsx          # рендер /students/:id/stats (directions, overall, monthBlock)
```

### Создаются (Phase B — groups + lessons + payroll, Task 8-14)

```
web/admin/src/pages/groups/
├─ GroupsListPage.tsx
├─ GroupDetailPage.tsx            # DetailShell + teacher card + LessonGrid + members
├─ GroupFormModal.tsx             # форма с slot editor
└─ GroupMembersBlock.tsx
web/admin/src/components/lessons/
├─ LessonGrid.tsx                 # квадраты + клик → LessonEditor
└─ LessonEditor.tsx               # inline editor: date, url, attendance grid, save/delete
web/admin/src/pages/lessons/
├─ LessonsListPage.tsx
├─ LessonDetailPage.tsx           # DetailShell + attendance toggle + payroll editor
└─ LessonFormModal.tsx            # только для standalone create через /admin/lessons
web/admin/src/pages/payroll/
└─ PayrollPage.tsx                # mode toggle list/summary + date range
```

### Создаются (Phase C — teachers + tokens + directions + archive, Task 15-18)

```
web/admin/src/pages/teachers/
├─ TeachersListPage.tsx
├─ TeacherDetailPage.tsx          # DetailShell + tokens-card + groups-cards
└─ TeacherFormModal.tsx
web/admin/src/pages/tokens/
├─ TokensListPage.tsx
├─ TokenDetailPage.tsx
└─ TokenFormModal.tsx             # с кнопкой «Сгенерировать»
web/admin/src/pages/directions/
├─ DirectionsListPage.tsx         # grid из dir-card (НЕ таблица)
├─ DirectionDetailPage.tsx
└─ DirectionFormModal.tsx         # ColorInput, total_lessons
web/admin/src/pages/archive/
└─ ArchivePage.tsx                # 4 секции: teachers/groups/directions/tokens
```

### НЕ трогаются

- `web/admin/src/style.css` — все классы сохранены, никаких новых стилей
- `web/admin/src/lib/api.ts`, `lib/format.ts`, `lib/types.ts`
- `web/admin/src/providers/`, `hooks/useAuth.ts`
- `web/admin/src/components/shell/`, `components/ui/{Dialog,Toast,EmptyState,Skeleton}.tsx`
- Бэкенд (`server.js`, `routes/`, `services/`, `shared/`)
- `_backup-pre-r1/` — оставляется для аварийного отката

---

## Глобальные правила

1. **Никаких `state.cache`** — server state живёт только в TanStack Query. Замена «инвалидации в коде»: `qc.invalidateQueries({ queryKey: ['<entity>'] })` после каждой мутации.
2. **Поведенческий контракт совпадает с backup** — тосты в тех же местах, lesson grid с теми же квадратами, KOTOKOD-hero ученика и dir-card направлений рисуются 1-в-1 (классы те же).
3. **Никакого `innerHTML`/`dangerouslySetInnerHTML`** — всё через JSX. Helper `escapeHtml` остаётся только в `lib/format.ts` (на случай редких inline-svg сборок, если понадобится — не используем).
4. **Inline-стили из старого кода переносим как есть** — `style={{ background: 'hsl(...)' }}` для dir-color, student-hero и т.д. Это допустимо: динамические значения, переноса в CSS-классы нет.
5. **Размер файла**: до 300 строк. Если страница больше — выносить sub-компоненты в ту же папку.
6. **Мутации**: каждый хук возвращает объект `{ data, create, update, remove }` где `create/update/remove` — это `useMutation` с готовой `onSuccess: invalidate`.
7. **Запреты**:
   - Параллельный агент A НЕ трогает `pages/groups/`, `pages/lessons/`, `pages/payroll/`, `pages/teachers/`, `pages/tokens/`, `pages/directions/`, `pages/archive/` и хуки B/C
   - Параллельный агент B НЕ трогает `pages/students/`, `pages/teachers/`, `pages/tokens/`, `pages/directions/`, `pages/archive/` и хуки A/C
   - Параллельный агент C НЕ трогает `pages/students/`, `pages/groups/`, `pages/lessons/`, `pages/payroll/` и хуки A/B
   - НИКТО из A/B/C не трогает `lib/`, `components/ui|form|memberships|lessons|detail|table|shell`, `style.css`, `App.tsx` — эти изменения целиком в Task 1-4.

---

## Task 1: Helpers — pricing, slots, direction-color

**Files:**
- Create: `web/admin/src/lib/pricing.ts`
- Create: `web/admin/src/lib/slots.ts`
- Create: `web/admin/src/lib/direction-color.ts`

- [ ] **Step 1: pricing.ts**

`web/admin/src/lib/pricing.ts`:
```ts
export function calcPayment(total: number, present: number, isHalf = false): number {
  if (!Number.isFinite(present) || present === 0) return 0;
  if (isHalf) return 250 * present;
  if (total <= 2) return present === total ? 500 : 300;
  return 200 * present;
}
```

- [ ] **Step 2: slots.ts**

`web/admin/src/lib/slots.ts`:
```ts
import type { GroupScheduleSlot } from './types';

export const DOW = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'] as const;

export const MONTHS_RU = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
] as const;

export function formatSlot(s: Pick<GroupScheduleSlot, 'day_of_week' | 'start_time'>): string {
  const day = DOW[s.day_of_week] || '??';
  const time = String(s.start_time || '').slice(0, 5);
  return `${day} ${time}`;
}
```

- [ ] **Step 3: direction-color.ts**

`web/admin/src/lib/direction-color.ts`:
```ts
import type { Direction } from './types';

const FALLBACK = '#0d9488';

export function directionColor(input: Direction | string | null | undefined): string {
  if (!input) return FALLBACK;
  if (typeof input === 'object') {
    if (input.color && /^#[0-9a-fA-F]{6}$/.test(input.color)) return input.color;
    return hueFromName(input.name || '');
  }
  if (/^#[0-9a-fA-F]{6}$/.test(input)) return input;
  return hueFromName(input);
}

function hueFromName(name: string): string {
  const hue = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  return `hsl(${hue}, 55%, 42%)`;
}
```

- [ ] **Step 4: Verify**

Run: `npm run admin:typecheck 2>&1 | tail -5`
Expected: no new errors.

- [ ] **Step 5: Commit**

```bash
git add web/admin/src/lib/pricing.ts web/admin/src/lib/slots.ts web/admin/src/lib/direction-color.ts
git commit -m "r2: add pricing/slots/direction-color helpers"
```

---

## Task 2: UI primitives — Pill, MonoBadge, DirTag, ColorInput, useApiError

**Files:**
- Create: `web/admin/src/components/ui/Pill.tsx`
- Create: `web/admin/src/components/ui/MonoBadge.tsx`
- Create: `web/admin/src/components/ui/DirTag.tsx`
- Create: `web/admin/src/components/form/ColorInput.tsx`
- Create: `web/admin/src/hooks/useApiError.ts`

- [ ] **Step 1: Pill**

`web/admin/src/components/ui/Pill.tsx`:
```tsx
import { type ReactNode } from 'react';

interface Props { children: ReactNode; }

export function Pill({ children }: Props) {
  return <span className="pill">{children}</span>;
}
```

- [ ] **Step 2: MonoBadge**

`web/admin/src/components/ui/MonoBadge.tsx`:
```tsx
interface Props { value: string; active?: boolean; }

export function MonoBadge({ value, active = true }: Props) {
  return (
    <span className={`mono-badge ${active ? 'mono-badge--active' : 'mono-badge--inactive'}`}>
      {value}
    </span>
  );
}
```

- [ ] **Step 3: DirTag**

`web/admin/src/components/ui/DirTag.tsx`:
```tsx
import { directionColor } from '../../lib/direction-color';
import type { Direction } from '../../lib/types';

interface Props { name?: string | null; direction?: Direction | null; }

export function DirTag({ name, direction }: Props) {
  const label = direction?.name || name || '';
  if (!label) return null;
  const color = directionColor(direction || label);
  return (
    <span className="dir-tag" style={{ color, borderColor: `${color}55`, background: `${color}14` }}>
      {label}
    </span>
  );
}
```

- [ ] **Step 4: ColorInput**

`web/admin/src/components/form/ColorInput.tsx`:
```tsx
import { type InputHTMLAttributes } from 'react';

export function ColorInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input type="color" {...props} />;
}
```

- [ ] **Step 5: useApiError hook**

`web/admin/src/hooks/useApiError.ts`:
```ts
import { useCallback } from 'react';
import { ApiError } from '../lib/api';
import { useToast } from '../components/ui/Toast';

export function useApiError() {
  const { toast } = useToast();
  return useCallback((err: unknown, fallback = 'Ошибка') => {
    if (err instanceof ApiError) {
      toast(err.message || fallback, 'error');
      return;
    }
    if (err instanceof Error) {
      toast(err.message || fallback, 'error');
      return;
    }
    toast(fallback, 'error');
  }, [toast]);
}
```

- [ ] **Step 6: Verify**

Run: `npm run admin:typecheck 2>&1 | tail -5`
Expected: no new errors.

- [ ] **Step 7: Commit**

```bash
git add web/admin/src/components/ui web/admin/src/components/form/ColorInput.tsx web/admin/src/hooks/useApiError.ts
git commit -m "r2: add Pill/MonoBadge/DirTag/ColorInput primitives + useApiError"
```

---

## Task 3: Query/mutation hooks — entity factories

Создаём типизированные хуки для каждой сущности с единым контрактом. Каждый хук должен инвалидировать связанные кеши.

**Files:**
- Create: `web/admin/src/hooks/useStudents.ts`
- Create: `web/admin/src/hooks/useGroups.ts`
- Create: `web/admin/src/hooks/useTeachers.ts`
- Create: `web/admin/src/hooks/useTokens.ts`
- Create: `web/admin/src/hooks/useDirections.ts`
- Create: `web/admin/src/hooks/useLessons.ts`
- Create: `web/admin/src/hooks/usePayroll.ts`
- Create: `web/admin/src/hooks/useMemberships.ts`
- Create: `web/admin/src/hooks/useArchive.ts`

- [ ] **Step 1: useStudents.ts**

`web/admin/src/hooks/useStudents.ts`:
```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Student } from '../lib/types';

interface StudentStats {
  overall: {
    lessons_recorded: number;
    attended_count: number;
    attendance_pct: number | null;
    denominator: number;
    this_month: { lessons_recorded: number; attended_count: number; attendance_pct: number | null };
  };
  directions: Array<{
    direction_id: number;
    direction_name: string;
    direction_color: string | null;
    course_total_lessons: number | null;
    lessons_recorded: number;
    attended_count: number;
    attendance_pct: number | null;
    denominator: number;
    last_attended: string | null;
    this_month: { lessons_recorded: number; attended_count: number; attendance_pct: number | null };
    groups: Array<{
      group_id: number;
      group_name: string;
      membership_active: boolean;
      lessons_recorded: number;
      attended_count: number;
      attendance_pct: number | null;
    }>;
  }>;
}

const KEY = ['students'] as const;

export function useStudents() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => api<Student[]>('GET', '/api/admin/students'),
  });
}

export function useStudent(id: number) {
  return useQuery({
    queryKey: [...KEY, id],
    queryFn: () => api<Student>('GET', `/api/admin/students/${id}`),
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useStudentStats(id: number) {
  return useQuery({
    queryKey: [...KEY, id, 'stats'],
    queryFn: () => api<StudentStats>('GET', `/api/admin/students/${id}/stats`),
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useStudentMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['students'] });
    qc.invalidateQueries({ queryKey: ['archive'] });
  };
  return {
    create: useMutation({
      mutationFn: (body: Partial<Student>) => api<Student>('POST', '/api/admin/students', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Partial<Student> }) =>
        api<Student>('PATCH', `/api/admin/students/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<void>('DELETE', `/api/admin/students/${id}`),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Step 2: useGroups.ts**

`web/admin/src/hooks/useGroups.ts`:
```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Group, GroupScheduleSlot } from '../lib/types';

export interface GroupPayload {
  name: string;
  direction_id: number;
  teacher_id: number;
  is_individual: boolean;
  lesson_duration_minutes: 45 | 60 | 90;
  lessons_per_week: number;
  group_start_date?: string | null;
  vk_chat?: string | null;
  slots: Pick<GroupScheduleSlot, 'day_of_week' | 'start_time'>[];
  active?: boolean;
}

const KEY = ['groups'] as const;

export function useGroups(includeInactive = false) {
  return useQuery({
    queryKey: [...KEY, { includeInactive }],
    queryFn: () => api<Group[]>('GET', `/api/admin/groups${includeInactive ? '?include_inactive=1' : ''}`),
  });
}

export function useGroup(id: number) {
  return useQuery({
    queryKey: [...KEY, id],
    queryFn: () => api<Group>('GET', `/api/admin/groups/${id}`),
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useGroupMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['groups'] });
    qc.invalidateQueries({ queryKey: ['archive'] });
  };
  return {
    create: useMutation({
      mutationFn: (body: GroupPayload) => api<Group>('POST', '/api/admin/groups', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Partial<GroupPayload> }) =>
        api<Group>('PATCH', `/api/admin/groups/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<void>('DELETE', `/api/admin/groups/${id}`),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Step 3: useTeachers.ts**

`web/admin/src/hooks/useTeachers.ts`:
```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Teacher } from '../lib/types';

const KEY = ['teachers'] as const;

export function useTeachers(includeInactive = false) {
  return useQuery({
    queryKey: [...KEY, { includeInactive }],
    queryFn: () => api<Teacher[]>('GET', `/api/admin/teachers${includeInactive ? '?include_inactive=1' : ''}`),
  });
}

export function useTeacher(id: number) {
  return useQuery({
    queryKey: [...KEY, id],
    queryFn: () => api<Teacher>('GET', `/api/admin/teachers/${id}`),
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useTeacherMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['teachers'] });
    qc.invalidateQueries({ queryKey: ['archive'] });
  };
  return {
    create: useMutation({
      mutationFn: (body: Partial<Teacher>) => api<Teacher>('POST', '/api/admin/teachers', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Partial<Teacher> }) =>
        api<Teacher>('PATCH', `/api/admin/teachers/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<void>('DELETE', `/api/admin/teachers/${id}`),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Step 4: useTokens.ts**

`web/admin/src/hooks/useTokens.ts`:
```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Token } from '../lib/types';

const KEY = ['tokens'] as const;

export function useTokens(includeInactive = false) {
  return useQuery({
    queryKey: [...KEY, { includeInactive }],
    queryFn: () => api<Token[]>('GET', `/api/admin/tokens${includeInactive ? '?include_inactive=1' : ''}`),
  });
}

export function useTokenMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['tokens'] });
    qc.invalidateQueries({ queryKey: ['archive'] });
  };
  return {
    create: useMutation({
      mutationFn: (body: { token: string; teacher_id: number }) =>
        api<Token>('POST', '/api/admin/tokens', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ token, body }: { token: string; body: { teacher_id?: number; active?: boolean } }) =>
        api<Token>('PATCH', `/api/admin/tokens/${encodeURIComponent(token)}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (token: string) =>
        api<void>('DELETE', `/api/admin/tokens/${encodeURIComponent(token)}`),
      onSuccess: invalidate,
    }),
    generate: useMutation({
      mutationFn: () => api<{ token: string }>('POST', '/api/admin/tokens/generate'),
    }),
  };
}
```

- [ ] **Step 5: useDirections.ts**

`web/admin/src/hooks/useDirections.ts`:
```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Direction } from '../lib/types';

const KEY = ['directions'] as const;

export function useDirections(includeInactive = false) {
  return useQuery({
    queryKey: [...KEY, { includeInactive }],
    queryFn: () => api<Direction[]>('GET', `/api/admin/directions${includeInactive ? '?include_inactive=1' : ''}`),
  });
}

export function useDirection(id: number) {
  return useQuery({
    queryKey: [...KEY, id],
    queryFn: () => api<Direction>('GET', `/api/admin/directions/${id}`),
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useDirectionMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['directions'] });
    qc.invalidateQueries({ queryKey: ['archive'] });
  };
  return {
    create: useMutation({
      mutationFn: (body: Partial<Direction>) => api<Direction>('POST', '/api/admin/directions', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Partial<Direction> }) =>
        api<Direction>('PATCH', `/api/admin/directions/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<void>('DELETE', `/api/admin/directions/${id}`),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Step 6: useLessons.ts**

`web/admin/src/hooks/useLessons.ts`:
```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Lesson, LessonFull } from '../lib/types';

interface ListFilter {
  group_id?: number;
  teacher_id?: number;
  date_from?: string;
  date_to?: string;
}

function buildQs(f: ListFilter): string {
  const parts: string[] = [];
  if (f.group_id) parts.push(`group_id=${f.group_id}`);
  if (f.teacher_id) parts.push(`teacher_id=${f.teacher_id}`);
  if (f.date_from) parts.push(`date_from=${encodeURIComponent(f.date_from)}`);
  if (f.date_to) parts.push(`date_to=${encodeURIComponent(f.date_to)}`);
  return parts.length ? '?' + parts.join('&') : '';
}

const KEY = ['lessons'] as const;

export function useLessons(filter: ListFilter = {}) {
  return useQuery({
    queryKey: [...KEY, filter],
    queryFn: () => api<Lesson[]>('GET', '/api/admin/lessons' + buildQs(filter)),
  });
}

export function useLessonFull(id: number | null) {
  return useQuery({
    queryKey: [...KEY, id, 'full'],
    queryFn: () => api<LessonFull>('GET', `/api/admin/lessons/${id}`),
    enabled: Number.isFinite(id) && (id || 0) > 0,
  });
}

export function useLessonMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['lessons'] });
    qc.invalidateQueries({ queryKey: ['payroll'] });
    qc.invalidateQueries({ queryKey: ['memberships'] });
    qc.invalidateQueries({ queryKey: ['students'] });
  };
  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) =>
        api<LessonFull>('POST', '/api/admin/lessons', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
        api<Lesson>('PATCH', `/api/admin/lessons/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<void>('DELETE', `/api/admin/lessons/${id}`),
      onSuccess: invalidate,
    }),
    toggleAttendance: useMutation({
      mutationFn: ({ lessonId, studentId, present }:
        { lessonId: number; studentId: number; present: boolean }) =>
        api<{ ok: true }>('PATCH', `/api/admin/lessons/${lessonId}/attendance/${studentId}`, { present }),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Step 7: usePayroll.ts**

`web/admin/src/hooks/usePayroll.ts`:
```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { PayrollEntry, PayrollSummaryRow } from '../lib/types';

interface Filter { teacher_id?: number; date_from?: string; date_to?: string; }

function qs(f: Filter): string {
  const p: string[] = [];
  if (f.teacher_id) p.push(`teacher_id=${f.teacher_id}`);
  if (f.date_from) p.push(`date_from=${encodeURIComponent(f.date_from)}`);
  if (f.date_to) p.push(`date_to=${encodeURIComponent(f.date_to)}`);
  return p.length ? '?' + p.join('&') : '';
}

const KEY = ['payroll'] as const;

export function usePayrollList(filter: Filter = {}) {
  return useQuery({
    queryKey: [...KEY, 'list', filter],
    queryFn: () => api<PayrollEntry[]>('GET', '/api/admin/payroll' + qs(filter)),
  });
}

export function usePayrollSummary(filter: Filter = {}) {
  return useQuery({
    queryKey: [...KEY, 'summary', filter],
    queryFn: () => api<PayrollSummaryRow[]>('GET', '/api/admin/payroll/summary' + qs(filter)),
  });
}

export function usePayrollMutations() {
  const qc = useQueryClient();
  return {
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Partial<PayrollEntry> }) =>
        api<PayrollEntry>('PATCH', `/api/admin/payroll/${id}`, body),
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: ['payroll'] });
        qc.invalidateQueries({ queryKey: ['lessons'] });
      },
    }),
  };
}
```

- [ ] **Step 8: useMemberships.ts**

`web/admin/src/hooks/useMemberships.ts`:
```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { GroupMembership } from '../lib/types';

interface Filter { group_id?: number; student_id?: number; }

function qs(f: Filter): string {
  const p: string[] = [];
  if (f.group_id) p.push(`group_id=${f.group_id}`);
  if (f.student_id) p.push(`student_id=${f.student_id}`);
  return p.length ? '?' + p.join('&') : '';
}

const KEY = ['memberships'] as const;

export function useMemberships(filter: Filter) {
  return useQuery({
    queryKey: [...KEY, filter],
    queryFn: () => api<GroupMembership[]>('GET', '/api/admin/group-memberships' + qs(filter)),
    enabled: !!(filter.group_id || filter.student_id),
  });
}

export function useMembershipMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['memberships'] });
    qc.invalidateQueries({ queryKey: ['students'] });
    qc.invalidateQueries({ queryKey: ['groups'] });
  };
  return {
    create: useMutation({
      mutationFn: (body: { student_id: number; group_id: number }) =>
        api<GroupMembership>('POST', '/api/admin/group-memberships', body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) =>
        api<void>('DELETE', `/api/admin/group-memberships/${id}`),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Step 9: useArchive.ts**

`web/admin/src/hooks/useArchive.ts`:
```ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Teacher, Group, Direction, Token } from '../lib/types';

export interface ArchivePayload {
  teachers: Teacher[];
  groups: Group[];
  directions: Direction[];
  tokens: Token[];
}

export function useArchive() {
  return useQuery({
    queryKey: ['archive'],
    queryFn: async (): Promise<ArchivePayload> => {
      const [teachers, groups, directions, tokens] = await Promise.all([
        api<Teacher[]>('GET', '/api/admin/teachers?include_inactive=1'),
        api<Group[]>('GET', '/api/admin/groups?include_inactive=1'),
        api<Direction[]>('GET', '/api/admin/directions?include_inactive=1'),
        api<Token[]>('GET', '/api/admin/tokens?include_inactive=1'),
      ]);
      return {
        teachers:   teachers.filter((r) => r.active === false),
        groups:     groups.filter((r) => r.active === false),
        directions: directions.filter((r) => r.active === false),
        tokens:     tokens.filter((r) => r.active === false),
      };
    },
  });
}
```

- [ ] **Step 10: Verify**

Run: `npm run admin:typecheck 2>&1 | tail -10`
Expected: 0 errors. Все хуки типизированы корректно.

- [ ] **Step 11: Commit**

```bash
git add web/admin/src/hooks
git commit -m "r2: add TanStack Query hooks for all 8 entities + memberships + archive"
```

---

## Task 4: Detail routes in App.tsx + MembershipsBlock

**Files:**
- Modify: `web/admin/src/App.tsx`
- Create: `web/admin/src/components/memberships/MembershipsBlock.tsx`

- [ ] **Step 1: Дополнить App.tsx маршрутами `/admin/<section>/:id`**

Заменить блок `<Route element={<AppShell />}>` на:

```tsx
<Route element={<AppShell />}>
  <Route path="/admin" element={<Navigate to="/admin/students" replace />} />

  <Route path="/admin/students" element={<StudentsListPage />} />
  <Route path="/admin/students/:id" element={<StudentDetailPage />} />

  <Route path="/admin/groups" element={<GroupsListPage />} />
  <Route path="/admin/groups/:id" element={<GroupDetailPage />} />

  <Route path="/admin/teachers" element={<TeachersListPage />} />
  <Route path="/admin/teachers/:id" element={<TeacherDetailPage />} />

  <Route path="/admin/tokens" element={<TokensListPage />} />
  <Route path="/admin/tokens/:id" element={<TokenDetailPage />} />

  <Route path="/admin/directions" element={<DirectionsListPage />} />
  <Route path="/admin/directions/:id" element={<DirectionDetailPage />} />

  <Route path="/admin/lessons" element={<LessonsListPage />} />
  <Route path="/admin/lessons/:id" element={<LessonDetailPage />} />

  <Route path="/admin/payroll" element={<PayrollPage />} />
  <Route path="/admin/archive" element={<ArchivePage />} />

  <Route path="*" element={<Navigate to="/admin/students" replace />} />
</Route>
```

И добавить импорты detail-страниц в шапку:

```tsx
import StudentDetailPage from './pages/students/StudentDetailPage';
import GroupDetailPage from './pages/groups/GroupDetailPage';
import TeacherDetailPage from './pages/teachers/TeacherDetailPage';
import TokenDetailPage from './pages/tokens/TokenDetailPage';
import DirectionDetailPage from './pages/directions/DirectionDetailPage';
import LessonDetailPage from './pages/lessons/LessonDetailPage';
```

⚠️ Эти detail-страницы ещё не существуют — typecheck упадёт. Это нормально, до Task 5/9/16 они будут заглушками. Создаём временные stub-файлы:

```bash
for f in students/StudentDetailPage groups/GroupDetailPage teachers/TeacherDetailPage tokens/TokenDetailPage directions/DirectionDetailPage lessons/LessonDetailPage; do
  d=$(dirname "web/admin/src/pages/$f")
  mkdir -p "$d"
done
```

Затем в каждой папке (если файл detail ещё не создан) положить заглушку:

```tsx
// web/admin/src/pages/students/StudentDetailPage.tsx (и аналогично для остальных)
export default function StudentDetailPage() {
  return <div className="memberships__empty" style={{ padding: 40 }}>Detail page (R2 in progress)</div>;
}
```

Создай 6 одинаковых файлов с разными именами компонент: `StudentDetailPage`, `GroupDetailPage`, `TeacherDetailPage`, `TokenDetailPage`, `DirectionDetailPage`, `LessonDetailPage`.

- [ ] **Step 2: MembershipsBlock**

`web/admin/src/components/memberships/MembershipsBlock.tsx`:
```tsx
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMemberships, useMembershipMutations } from '../../hooks/useMemberships';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../ui/Toast';
import type { GroupMembership } from '../../lib/types';

type Mode =
  | { mode: 'byStudent'; studentId: number; pickerOptions: { value: number; label: string; disabled?: boolean }[]; pickerLabel: string }
  | { mode: 'byGroup';   groupId: number;   pickerOptions: { value: number; label: string; disabled?: boolean }[]; pickerLabel: string };

interface Props {
  config: Mode;
  renderCard: (m: GroupMembership) => { title: string; meta: React.ReactNode; navigateTo?: string };
  emptyText: string;
}

export function MembershipsBlock({ config, renderCard, emptyText }: Props) {
  const navigate = useNavigate();
  const filter = config.mode === 'byStudent'
    ? { student_id: config.studentId }
    : { group_id: config.groupId };
  const { data: memberships = [], isLoading } = useMemberships(filter);
  const muts = useMembershipMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [selectedId, setSelectedId] = useState<number | ''>('');

  const usedIds = useMemo(() => {
    if (config.mode === 'byStudent') return new Set(memberships.map((m) => m.group_id));
    return new Set(memberships.map((m) => m.student_id));
  }, [memberships, config.mode]);

  const availableOptions = useMemo(() =>
    config.pickerOptions.filter((o) => !usedIds.has(o.value) && !o.disabled),
    [config.pickerOptions, usedIds],
  );

  const handleAdd = async () => {
    if (!selectedId) return;
    try {
      if (config.mode === 'byStudent') {
        await muts.create.mutateAsync({ student_id: config.studentId, group_id: Number(selectedId) });
      } else {
        await muts.create.mutateAsync({ student_id: Number(selectedId), group_id: config.groupId });
      }
      setSelectedId('');
      toast('Добавлен', 'ok');
    } catch (err) { showError(err); }
  };

  const handleRemove = async (id: number) => {
    try {
      await muts.remove.mutateAsync(id);
      toast('Убран', 'ok');
    } catch (err) { showError(err); }
  };

  if (isLoading) {
    return <div className="memberships__empty">Загружаем…</div>;
  }

  return (
    <div className="memberships">
      {memberships.length === 0 ? (
        <div className="memberships__empty">{emptyText}</div>
      ) : (
        memberships.map((m) => {
          const card = renderCard(m);
          return (
            <div
              key={m.id}
              className="link-card membership-card"
              tabIndex={0}
              role="button"
              onClick={(e) => {
                if ((e.target as HTMLElement).closest('[data-mremove]')) return;
                if (card.navigateTo) navigate(card.navigateTo);
              }}
              onKeyDown={(e) => {
                if ((e.key === 'Enter' || e.key === ' ') && card.navigateTo) {
                  e.preventDefault();
                  navigate(card.navigateTo);
                }
              }}
            >
              <div className="link-card-head">
                <div>
                  <div className="link-card-title">{card.title}</div>
                  <div className="link-card-meta">{card.meta}</div>
                </div>
                <button
                  type="button"
                  className="membership-card__remove"
                  data-mremove
                  aria-label="Убрать"
                  onClick={() => { void handleRemove(m.id); }}
                >×</button>
              </div>
              <div className="membership-card__stats">
                <div className="membership-card__stat">
                  <span className="membership-card__stat-label">Пройдено</span>
                  <span className="membership-card__stat-value">{String(m.lessons_done)}</span>
                </div>
                <div className="membership-card__stat">
                  <span className="membership-card__stat-label">Осталось</span>
                  <span className="membership-card__stat-value">{String(m.remaining)}</span>
                </div>
              </div>
            </div>
          );
        })
      )}

      <div className="memberships__add">
        <select
          value={selectedId}
          onChange={(e) => setSelectedId(e.target.value === '' ? '' : Number(e.target.value))}
        >
          <option value="">{config.pickerLabel}</option>
          {availableOptions.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => { void handleAdd(); }}
          disabled={!selectedId || muts.create.isPending}
        >+ Добавить</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify**

Run: `npm run admin:typecheck 2>&1 | tail -5`
Expected: 0 errors (stub-страницы покрыли импорты).

- [ ] **Step 4: Commit**

```bash
git add web/admin/src/App.tsx web/admin/src/pages web/admin/src/components/memberships
git commit -m "r2: add detail routes + MembershipsBlock + detail stubs"
```

---

# Параллельный поток A — students + memberships

Subagent A работает в `pages/students/` и опирается на `MembershipsBlock` + хуки `useStudents`, `useStudentStats`, `useMemberships`. Запрещено трогать другие папки.

## Task 5: StudentsListPage

**Files:**
- Modify: `web/admin/src/pages/students/StudentsListPage.tsx`

- [ ] **Step 1: Заменить stub на полноценную страницу**

```tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStudents } from '../../hooks/useStudents';
import { DataTable, type Column } from '../../components/table/DataTable';
import { Avatar } from '../../components/Avatar';
import { StatusBadge } from '../../components/StatusBadge';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import type { Student } from '../../lib/types';
import StudentFormModal from './StudentFormModal';

export default function StudentsListPage() {
  const { data, isLoading } = useStudents();
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);

  if (isLoading) return <TableSkeleton rows={6} cols={9} />;
  const rows: Student[] = data || [];

  const columns: Column<Student>[] = [
    { key: 'id', label: 'ID', cell: (r) => <span className="id-cell">#{r.id}</span> },
    { key: 'full_name', label: 'Ученик', searchable: true, cell: (r) => (
      <div className="person-cell">
        <Avatar name={r.full_name} size={32} />
        <div><div className="person-name">{r.full_name}</div></div>
      </div>
    )},
    { key: 'birth_date', label: 'Дата рожд.', cell: (r) => fmtDate(r.birth_date) },
    { key: 'age', label: 'Возраст', searchable: true,
      cell: (r) => r.age ? `${r.age} лет` : '—' },
    { key: 'school_grade', label: 'Класс', searchable: true,
      cell: (r) => r.school_grade != null ? String(r.school_grade) : '—' },
    { key: 'phone', label: 'Телефон', searchable: true, cell: (r) => r.phone || '—' },
    { key: 'parent_name', label: 'Родитель', searchable: true, cell: (r) => r.parent_name || '—' },
    { key: 'platform_id', label: 'Platform ID', searchable: true, cell: (r) => r.platform_id || '—' },
    { key: 'pm', label: 'ПМ', searchable: true, cell: (r) => r.pm || '—' },
    { key: 'first_purchase_date', label: 'Первая оплата', cell: (r) => fmtDate(r.first_purchase_date) },
    { key: 'enrollment_status', label: 'Статус', searchable: true,
      cell: (r) => <StatusBadge row={r} /> },
  ];

  return (
    <>
      <DataTable<Student>
        data={rows}
        columns={columns}
        title="Ученики"
        onRowClick={(row) => navigate(`/admin/students/${row.id}`)}
        headerActions={<button className="btn-add" onClick={() => setModalOpen(true)}>+ Новый</button>}
      />
      {modalOpen && (
        <StudentFormModal
          initial={null}
          onClose={() => setModalOpen(false)}
        />
      )}
    </>
  );
}
```

- [ ] **Step 2: Verify**

Run: `npm run admin:typecheck 2>&1 | tail -3`
Expected: ругается на `StudentFormModal` (будет в Task 7). Это ОК для текущего шага — Step 1 завершит typecheck вместе с Task 7.

- [ ] **Step 3: Commit**

```bash
git add web/admin/src/pages/students/StudentsListPage.tsx
git commit -m "r2(students): list page"
```

---

## Task 6: StudentStatsBlock + StudentDetailPage

**Files:**
- Create: `web/admin/src/pages/students/StudentStatsBlock.tsx`
- Modify: `web/admin/src/pages/students/StudentDetailPage.tsx`

- [ ] **Step 1: StudentStatsBlock**

`web/admin/src/pages/students/StudentStatsBlock.tsx`:
```tsx
import { Link } from 'react-router-dom';
import { useStudentStats } from '../../hooks/useStudents';
import { fmtDate } from '../../lib/format';

function pctColor(p: number | null | undefined): string {
  if (p == null) return 'var(--text3)';
  if (p >= 80) return 'var(--green)';
  if (p >= 50) return 'var(--amber)';
  return 'var(--red)';
}

export default function StudentStatsBlock({ studentId }: { studentId: number }) {
  const { data: stats, isLoading, error } = useStudentStats(studentId);

  if (isLoading) return <div className="memberships__empty" style={{ padding: 14 }}>Загружаем…</div>;
  if (error) return <div className="memberships__empty" style={{ padding: 14, color: 'var(--red)' }}>Не удалось загрузить статистику</div>;
  if (!stats) return null;

  const directions = stats.directions.filter((d) => d.lessons_recorded > 0);
  if (directions.length === 0 || stats.overall.lessons_recorded === 0) {
    return <div className="memberships__empty" style={{ padding: 14 }}>Нет данных о посещаемости</div>;
  }

  const overall = stats.overall;
  const overallPct = overall.attendance_pct ?? 0;
  const overallC = pctColor(overall.attendance_pct);
  const monthPct = overall.this_month.attendance_pct;
  const monthC = pctColor(monthPct);

  return (
    <>
      <div className="stats-overall">
        <div className="stats-overall__pct" style={{ color: overallC }}>{overallPct}%</div>
        <div className="stats-overall__detail">
          <div className="stats-overall__num">{overall.attended_count} / {overall.denominator}</div>
          <div className="stats-overall__label">
            Посещено уроков {overall.denominator !== overall.lessons_recorded ? '(к плану курса)' : ''}
          </div>
          {overall.denominator !== overall.lessons_recorded && (
            <div className="stats-overall__sub">проведено: {overall.lessons_recorded}</div>
          )}
        </div>
        {overall.this_month.lessons_recorded > 0 && (
          <>
            <div className="stats-overall__divider" />
            <div className="stats-overall__period">
              <div className="stats-overall__period-label">Этот месяц</div>
              <div className="stats-overall__period-row">
                <span className="stats-overall__period-pct" style={{ color: monthC }}>{monthPct ?? 0}%</span>
                <span className="stats-overall__period-num">{overall.this_month.attended_count} / {overall.this_month.lessons_recorded}</span>
              </div>
            </div>
          </>
        )}
      </div>

      <div className="dir-cards">
        {directions.map((d) => {
          const pct = d.attendance_pct ?? 0;
          const pctC = pctColor(d.attendance_pct);
          const planLabel = d.course_total_lessons
            ? `план курса: ${d.course_total_lessons} уроков`
            : `проведено: ${d.lessons_recorded}`;
          const dirColor = d.direction_color || '#0d9488';
          const mLessons = d.this_month.lessons_recorded;
          const mAttended = d.this_month.attended_count;

          return (
            <div key={d.direction_id} className="dir-card" style={{ ['--dir-color' as string]: dirColor }}>
              <div className="dir-card__header">
                <div className="dir-card__name-row">
                  <div className="dir-card__name">{d.direction_name}</div>
                  <div className="dir-card__sub">{planLabel} · посл. {fmtDate(d.last_attended)}</div>
                </div>
                <div className="dir-card__pct" style={{ color: pctC }}>{pct}%</div>
              </div>
              <div className="dir-card__progress">
                <div className="dir-card__progress-bar">
                  <div
                    className="dir-card__progress-fill"
                    style={{ width: `${Math.min(pct, 100)}%`, background: pctC }}
                  />
                </div>
                <div className="dir-card__counts">
                  <span className="dir-card__num-value">{d.attended_count}</span>
                  <span className="dir-card__num-label">/ {d.denominator}</span>
                  {d.denominator !== d.lessons_recorded && (
                    <span className="dir-card__num-sub">(проведено {d.lessons_recorded})</span>
                  )}
                </div>
              </div>
              <div className="dir-card__chips">
                {mLessons > 0 ? (
                  <span className="dir-chip dir-chip--month" style={{ color: pctColor(d.this_month.attendance_pct) }}>
                    📅 этот месяц: {mAttended}/{mLessons}
                  </span>
                ) : (
                  <span className="dir-chip dir-chip--empty">📅 в этом месяце уроков не было</span>
                )}
              </div>
              <div className="dir-card__groups">
                <div className="dir-card__groups-label">В группах:</div>
                {[...d.groups]
                  .sort((a, b) => Number(b.membership_active) - Number(a.membership_active))
                  .map((g) => {
                    const archived = !g.membership_active;
                    return (
                      <div key={g.group_id} className={`dir-group ${archived ? 'is-archived' : ''}`}>
                        <div className="dir-group__head">
                          <span className="dir-group__name">
                            <Link to={`/admin/groups/${g.group_id}`} className="entity-link">{g.group_name}</Link>
                          </span>
                          {archived && <span className="archive-tag">Архив</span>}
                        </div>
                        <div className="dir-group__stats">
                          <span className="dir-group__num">
                            <b>{g.attended_count}</b> уроков посещено{g.lessons_recorded > 0 ? ` из ${g.lessons_recorded} проведённых` : ''}
                          </span>
                          <span className="dir-group__pct" style={{ color: pctColor(g.attendance_pct) }}>
                            {g.attendance_pct ?? 0}%
                          </span>
                        </div>
                      </div>
                    );
                  })}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
```

- [ ] **Step 2: StudentDetailPage**

`web/admin/src/pages/students/StudentDetailPage.tsx`:
```tsx
import { useState } from 'react';
import { useParams, Navigate } from 'react-router-dom';
import { useStudent } from '../../hooks/useStudents';
import { useGroups } from '../../hooks/useGroups';
import { useDirections } from '../../hooks/useDirections';
import { DetailShell, type DetailField } from '../../components/detail/DetailShell';
import { StatusBadge } from '../../components/StatusBadge';
import { MembershipsBlock } from '../../components/memberships/MembershipsBlock';
import { DirTag } from '../../components/ui/DirTag';
import { PageLoading } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import type { Student } from '../../lib/types';
import StudentFormModal from './StudentFormModal';
import StudentStatsBlock from './StudentStatsBlock';

export default function StudentDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const { data: student, isLoading } = useStudent(id);
  const { data: groups = [] } = useGroups(true);
  const { data: directions = [] } = useDirections(true);
  const [editing, setEditing] = useState(false);

  if (isLoading) return <PageLoading />;
  if (!student) return <Navigate to="/admin/students" replace />;

  const initials = (() => {
    const parts = String(student.full_name || '').trim().split(/\s+/);
    return (parts.length >= 2 ? parts[0][0] + parts[1][0] : (student.full_name || '??').slice(0, 2)).toUpperCase();
  })();
  const hue = [...String(student.full_name || '')].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;

  const pills: Array<{ label: string; value: string }> = [];
  if (student.age) pills.push({ label: 'Возраст', value: `${student.age} лет` });
  if (student.school_grade) pills.push({ label: 'Класс', value: `${student.school_grade}-й` });
  if (student.phone) pills.push({ label: 'Телефон', value: student.phone });
  if (student.parent_name) pills.push({ label: 'Родитель', value: student.parent_name });

  const customHero = (
    <div className="student-hero">
      <div
        className="student-hero__avatar"
        style={{
          background: `hsl(${hue},55%,92%)`,
          borderColor: `hsl(${hue},50%,80%)`,
          color: `hsl(${hue},55%,35%)`,
        }}
      >{initials}</div>
      <div className="student-hero__info">
        <div className="student-hero__name-row">
          <h2 className="student-hero__name">{student.full_name}</h2>
          <StatusBadge row={student} />
        </div>
        {student.parent_name && (
          <div className="student-hero__sub">Родитель: {student.parent_name}</div>
        )}
        <div className="student-hero__id">id {student.id}</div>
        <div className="student-hero__actions">
          <button type="button" className="edit-btn" onClick={() => setEditing(true)}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
            Редактировать
          </button>
        </div>
      </div>
      <div className="student-hero__pills">
        {pills.map((p) => (
          <div key={p.label} className="student-pill">
            <span className="student-pill__label">{p.label}:</span>{' '}
            <span className="student-pill__value">{p.value}</span>
          </div>
        ))}
      </div>
    </div>
  );

  const fields: DetailField<Student>[] = [
    { key: 'id', label: 'ID' },
    { key: 'full_name', label: 'ФИО' },
    { key: 'birth_date', label: 'Дата рожд.', cell: (r) => fmtDate(r.birth_date) },
    { key: 'age', label: 'Возраст', cell: (r) => r.age ? `${r.age} лет` : '—' },
    { key: 'school_grade', label: 'Класс' },
    { key: 'phone', label: 'Телефон' },
    { key: 'parent_name', label: 'Родитель' },
    { key: 'platform_id', label: 'Platform ID' },
    { key: 'pm', label: 'ПМ' },
    { key: 'first_purchase_date', label: 'Первая оплата', cell: (r) => fmtDate(r.first_purchase_date) },
    { key: 'enrollment_status', label: 'Статус', cell: (r) => <StatusBadge row={r} /> },
    { key: 'created_at', label: 'Создан', cell: (r) => fmtDate(r.created_at) },
  ];

  const groupOptions = groups.map((g) => ({ value: g.id, label: g.name, disabled: !g.active }));

  return (
    <>
      <DetailShell<Student>
        title={student.full_name}
        row={student}
        fields={fields}
        cardTitle="Данные ученика"
        customHero={customHero}
        backTo="/admin/students"
      >
        <div className="sub-header">Статистика посещаемости</div>
        <StudentStatsBlock studentId={student.id} />

        <div className="sub-header">Группы ученика</div>
        <MembershipsBlock
          config={{
            mode: 'byStudent',
            studentId: student.id,
            pickerOptions: groupOptions,
            pickerLabel: 'Выберите группу',
          }}
          emptyText="Не записан ни в одну группу"
          renderCard={(m) => {
            const g = groups.find((x) => x.id === m.group_id);
            const dir = g ? directions.find((d) => d.id === g.direction_id) : null;
            return {
              title: m.group_name || `#${m.group_id}`,
              meta: (
                <>
                  {dir && <DirTag direction={dir} />}
                  {g && !g.active && <span className="archive-tag">Архив</span>}
                </>
              ),
              navigateTo: `/admin/groups/${m.group_id}`,
            };
          }}
        />
      </DetailShell>
      {editing && (
        <StudentFormModal initial={student} onClose={() => setEditing(false)} />
      )}
    </>
  );
}
```

- [ ] **Step 3: Verify**

Run: `npm run admin:typecheck 2>&1 | tail -3`
Expected: ругается на StudentFormModal (см. Task 7).

- [ ] **Step 4: Commit**

```bash
git add web/admin/src/pages/students/StudentStatsBlock.tsx web/admin/src/pages/students/StudentDetailPage.tsx
git commit -m "r2(students): detail page with KOTOKOD hero, stats and memberships"
```

---

## Task 7: StudentFormModal с auto-freeze логикой

**Files:**
- Create: `web/admin/src/pages/students/StudentFormModal.tsx`

- [ ] **Step 1: Создать форму**

`web/admin/src/pages/students/StudentFormModal.tsx`:
```tsx
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStudentMutations } from '../../hooks/useStudents';
import { useMemberships, useMembershipMutations } from '../../hooks/useMemberships';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { TextInput } from '../../components/form/TextInput';
import { NumberInput } from '../../components/form/NumberInput';
import { DateInput } from '../../components/form/DateInput';
import { SelectInput } from '../../components/form/SelectInput';
import { MONTHS_RU } from '../../lib/slots';
import type { Student, EnrollmentStatus } from '../../lib/types';

interface FormState {
  full_name: string;
  birth_date: string;
  phone: string;
  age: string;
  school_grade: string;
  parent_name: string;
  enrollment_status: EnrollmentStatus;
  frozen_until_month: string;
  first_purchase_date: string;
  pm: string;
  platform_id: string;
}

function toForm(s: Student | null): FormState {
  return {
    full_name: s?.full_name || '',
    birth_date: s?.birth_date || '',
    phone: s?.phone || '',
    age: s?.age != null ? String(s.age) : '',
    school_grade: s?.school_grade != null ? String(s.school_grade) : '',
    parent_name: s?.parent_name || '',
    enrollment_status: s?.enrollment_status || 'enrolled',
    frozen_until_month: s?.frozen_until_month != null ? String(s.frozen_until_month) : '',
    first_purchase_date: s?.first_purchase_date || '',
    pm: s?.pm || '',
    platform_id: s?.platform_id || '',
  };
}

interface Props { initial: Student | null; onClose: () => void; }

export default function StudentFormModal({ initial, onClose }: Props) {
  const isNew = !initial;
  const navigate = useNavigate();
  const muts = useStudentMutations();
  const memberMuts = useMembershipMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [form, setForm] = useState<FormState>(() => toForm(initial));

  // Memberships ученика — чтобы очистить после статуса frozen/declined
  const { data: memberships = [] } = useMemberships(
    initial ? { student_id: initial.id } : { student_id: 0 },
  );

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();

    let frozenMonth: number | null = form.frozen_until_month === '' ? null : Number(form.frozen_until_month);
    let status: EnrollmentStatus = form.enrollment_status;
    if (frozenMonth != null) status = 'frozen';
    if (status !== 'frozen') frozenMonth = null;

    const body: Partial<Student> = {
      full_name: form.full_name,
      birth_date: form.birth_date || null,
      phone: form.phone || null,
      age: form.age === '' ? null : Number(form.age),
      school_grade: form.school_grade === '' ? null : Number(form.school_grade),
      parent_name: form.parent_name || null,
      enrollment_status: status,
      frozen_until_month: frozenMonth,
      first_purchase_date: form.first_purchase_date || null,
      pm: form.pm || null,
      platform_id: form.platform_id || null,
    };

    try {
      let resultId: number;
      if (isNew) {
        const created = await muts.create.mutateAsync(body);
        toast('Создано', 'ok');
        resultId = created.id;
      } else {
        const updated = await muts.update.mutateAsync({ id: initial!.id, body });
        toast('Сохранено', 'ok');
        resultId = updated.id;
      }

      if (status === 'frozen' || status === 'declined') {
        const targetMemberships = isNew ? [] : memberships;
        await Promise.all(targetMemberships.map((m) => memberMuts.remove.mutateAsync(m.id)));
      }

      onClose();
      if (isNew) navigate(`/admin/students/${resultId}`);
    } catch (err) {
      showError(err);
    }
  };

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      wide
      title={isNew ? 'Новый ученик' : `Редактировать: ${initial!.full_name}`}
      footer={
        <button
          type="submit"
          form="student-form"
          className="btn-primary"
          disabled={muts.create.isPending || muts.update.isPending}
        >Сохранить</button>
      }
    >
      <form id="student-form" onSubmit={onSubmit}>
        <div className="modal-section-label">Личные данные</div>
        <Field label="ФИО" required>
          <TextInput required value={form.full_name} onChange={(e) => set('full_name', e.target.value)} placeholder="Иванов Иван Иванович" />
        </Field>
        <Field label="Дата рождения">
          <DateInput value={form.birth_date} onChange={(e) => set('birth_date', e.target.value)} />
        </Field>
        <Field label="Телефон">
          <TextInput value={form.phone} onChange={(e) => set('phone', e.target.value)} placeholder="+7 (___) ___-__-__" />
        </Field>
        <Field label="Возраст">
          <NumberInput min={0} max={120} value={form.age} onChange={(e) => set('age', e.target.value)} placeholder="12" />
        </Field>
        <Field label="Класс школы">
          <NumberInput min={1} max={11} value={form.school_grade} onChange={(e) => set('school_grade', e.target.value)} placeholder="7" />
        </Field>
        <Field label="Имя родителя">
          <TextInput value={form.parent_name} onChange={(e) => set('parent_name', e.target.value)} />
        </Field>

        <div className="modal-section-label">Обучение</div>
        <Field label="Статус">
          <SelectInput
            value={form.enrollment_status}
            onChange={(e) => set('enrollment_status', e.target.value as EnrollmentStatus)}
            options={[
              { value: 'enrolled', label: 'Учится' },
              { value: 'not_enrolled', label: 'Не учится' },
              { value: 'frozen', label: 'Заморожен' },
              { value: 'declined', label: 'Отказался' },
            ]}
          />
        </Field>
        <Field label="Заморожен до">
          <SelectInput
            value={form.frozen_until_month}
            onChange={(e) => set('frozen_until_month', e.target.value)}
            options={[
              { value: '', label: '— не выбрано —' },
              ...MONTHS_RU.map((m, i) => ({ value: i + 1, label: m })),
            ]}
          />
        </Field>
        <Field label="Дата первой оплаты">
          <DateInput value={form.first_purchase_date} onChange={(e) => set('first_purchase_date', e.target.value)} />
        </Field>
        <Field label="Менеджер (PM)">
          <TextInput value={form.pm} onChange={(e) => set('pm', e.target.value)} />
        </Field>

        <div className="modal-section-label">Система</div>
        <Field label="Platform ID">
          <TextInput value={form.platform_id} onChange={(e) => set('platform_id', e.target.value)} placeholder="внешний идентификатор" />
        </Field>
      </form>
    </Dialog>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
npm run admin:typecheck 2>&1 | tail -3
npm run admin:build 2>&1 | tail -6
```

Expected: 0 typecheck errors, build OK.

- [ ] **Step 3: Smoke в браузере**

- `/admin/students` → таблица отображается, поиск по колонкам работает
- Клик по строке → `/admin/students/:id` → видны hero + stats + memberships
- Add new → форма открывается → сохранение создаёт ученика и редиректит на detail
- Изменить статус на frozen + месяц → запись обновляется, memberships удаляются
- Добавить ученика в группу через picker — карточка появляется без перезагрузки страницы (invalidateQueries сработал)

- [ ] **Step 4: Commit**

```bash
git add web/admin/src/pages/students/StudentFormModal.tsx
git commit -m "r2(students): form modal with auto-freeze logic"
```

---

# Параллельный поток B — groups + lessons + payroll

Subagent B работает в `pages/groups/`, `pages/lessons/`, `pages/payroll/`, `components/lessons/`. Запрещено трогать pages/students, pages/teachers, pages/tokens, pages/directions, pages/archive.

## Task 8: GroupsListPage

**Files:**
- Modify: `web/admin/src/pages/groups/GroupsListPage.tsx`

- [ ] **Step 1: Заменить stub**

```tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useGroups } from '../../hooks/useGroups';
import { useTeachers } from '../../hooks/useTeachers';
import { useDirections } from '../../hooks/useDirections';
import { DataTable, type Column } from '../../components/table/DataTable';
import { Avatar } from '../../components/Avatar';
import { DirTag } from '../../components/ui/DirTag';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import { formatSlot } from '../../lib/slots';
import type { Group } from '../../lib/types';
import GroupFormModal from './GroupFormModal';

export default function GroupsListPage() {
  const { data, isLoading } = useGroups();
  const { data: teachers = [] } = useTeachers(true);
  const { data: directions = [] } = useDirections(true);
  const [modalOpen, setModalOpen] = useState(false);
  const navigate = useNavigate();

  if (isLoading) return <TableSkeleton rows={6} cols={9} />;
  const rows: Group[] = data || [];

  const columns: Column<Group>[] = [
    { key: 'id', label: 'ID', cell: (r) => <span className="id-cell">#{r.id}</span> },
    { key: 'name', label: 'Группа', searchable: true,
      cell: (r) => <div style={{ fontWeight: 600, color: 'var(--text)' }}>{r.name}</div> },
    { key: 'direction_id', label: 'Направление', searchable: true,
      cell: (r) => {
        const dir = directions.find((d) => d.id === r.direction_id);
        return dir ? <DirTag direction={dir} /> : <span className="id-cell">#{r.direction_id}</span>;
      }},
    { key: 'teacher_id', label: 'Преподаватель', searchable: true,
      cell: (r) => {
        const t = teachers.find((x) => x.id === r.teacher_id);
        if (!t) return <span className="id-cell">#{r.teacher_id}</span>;
        return (
          <div className="person-cell">
            <Avatar name={t.name} size={26} />
            <span style={{ fontSize: 12 }}>{t.name.split(' ').slice(0, 2).join(' ')}</span>
          </div>
        );
      }},
    { key: 'is_individual', label: 'Индив.', cell: (r) => r.is_individual ? 'да' : 'нет' },
    { key: 'lesson_duration_minutes', label: 'Минут', cell: (r) => String(r.lesson_duration_minutes ?? '—') },
    { key: 'lessons_per_week', label: 'В неделю', cell: (r) => String(r.lessons_per_week ?? '—') },
    { key: 'group_start_date', label: 'Старт', cell: (r) => fmtDate(r.group_start_date) },
    { key: 'slots', label: 'Слоты', cell: (r) => (r.slots || []).map((s) => formatSlot(s)).join(', ') || '—' },
    { key: 'vk_chat', label: 'Чат ВК', cell: (r) => r.vk_chat || '—' },
    { key: 'active', label: 'Статус',
      cell: (r) => r.active
        ? <span className="badge badge--ok">Активна</span>
        : <span className="badge badge--muted">Архив</span> },
  ];

  return (
    <>
      <DataTable<Group>
        data={rows}
        columns={columns}
        title="Группы"
        onRowClick={(row) => navigate(`/admin/groups/${row.id}`)}
        headerActions={<button className="btn-add" onClick={() => setModalOpen(true)}>+ Новая</button>}
      />
      {modalOpen && (
        <GroupFormModal initial={null} onClose={() => setModalOpen(false)} />
      )}
    </>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/admin/src/pages/groups/GroupsListPage.tsx
git commit -m "r2(groups): list page"
```

---

## Task 9: GroupFormModal со слот-редактором

**Files:**
- Create: `web/admin/src/pages/groups/GroupFormModal.tsx`

- [ ] **Step 1: Создать форму**

`web/admin/src/pages/groups/GroupFormModal.tsx`:
```tsx
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useGroupMutations, type GroupPayload } from '../../hooks/useGroups';
import { useTeachers } from '../../hooks/useTeachers';
import { useDirections } from '../../hooks/useDirections';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { TextInput } from '../../components/form/TextInput';
import { NumberInput } from '../../components/form/NumberInput';
import { DateInput } from '../../components/form/DateInput';
import { Checkbox } from '../../components/form/Checkbox';
import { SelectInput } from '../../components/form/SelectInput';
import { DOW } from '../../lib/slots';
import type { Group, GroupScheduleSlot, LessonDuration } from '../../lib/types';

interface Slot { day_of_week: number; start_time: string; }

interface Props { initial: Group | null; onClose: () => void; }

export default function GroupFormModal({ initial, onClose }: Props) {
  const isNew = !initial;
  const navigate = useNavigate();
  const muts = useGroupMutations();
  const { data: teachers = [] } = useTeachers(true);
  const { data: directions = [] } = useDirections(true);
  const { toast } = useToast();
  const showError = useApiError();

  const [name, setName] = useState(initial?.name || '');
  const [directionId, setDirectionId] = useState<string>(initial?.direction_id ? String(initial.direction_id) : '');
  const [teacherId, setTeacherId] = useState<string>(initial?.teacher_id ? String(initial.teacher_id) : '');
  const [vkChat, setVkChat] = useState(initial?.vk_chat || '');
  const [duration, setDuration] = useState<LessonDuration>(initial?.lesson_duration_minutes || 90);
  const [perWeek, setPerWeek] = useState<string>(initial?.lessons_per_week ? String(initial.lessons_per_week) : '1');
  const [startDate, setStartDate] = useState(initial?.group_start_date || '');
  const [isIndividual, setIsIndividual] = useState(initial?.is_individual || false);
  const [active, setActive] = useState(initial?.active ?? true);
  const [slots, setSlots] = useState<Slot[]>(() =>
    (initial?.slots || []).map((s) => ({
      day_of_week: s.day_of_week,
      start_time: String(s.start_time).slice(0, 5),
    })),
  );

  const teacherOptions = [{ value: '', label: '— выберите —' }, ...teachers
    .filter((t) => t.active || (initial && initial.teacher_id === t.id))
    .map((t) => ({ value: t.id, label: t.name }))];
  const directionOptions = [{ value: '', label: '— выберите —' }, ...directions
    .filter((d) => d.active || (initial && initial.direction_id === d.id))
    .map((d) => ({ value: d.id, label: d.name }))];

  const updateSlot = (i: number, key: 'day_of_week' | 'start_time', value: string) => {
    setSlots((arr) => {
      const next = [...arr];
      next[i] = { ...next[i], [key]: key === 'day_of_week' ? Number(value) : value };
      return next;
    });
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!directionId || !teacherId) {
      toast('Направление и преподаватель обязательны', 'error');
      return;
    }
    const payload: GroupPayload = {
      name,
      direction_id: Number(directionId),
      teacher_id: Number(teacherId),
      is_individual: isIndividual,
      lesson_duration_minutes: duration,
      lessons_per_week: Number(perWeek) || 1,
      group_start_date: startDate || null,
      vk_chat: vkChat || null,
      slots: slots.map((s) => ({ day_of_week: s.day_of_week, start_time: s.start_time })),
    };
    if (!isNew) payload.active = active;

    try {
      if (isNew) {
        const created = await muts.create.mutateAsync(payload);
        toast('Создано', 'ok');
        onClose();
        navigate(`/admin/groups/${created.id}`);
      } else {
        await muts.update.mutateAsync({ id: initial!.id, body: payload });
        toast('Сохранено', 'ok');
        onClose();
      }
    } catch (err) { showError(err); }
  };

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      wide
      title={isNew ? 'Новая группа' : `Редактировать: ${initial!.name}`}
      footer={
        <button type="submit" form="group-form" className="btn-primary" disabled={muts.create.isPending || muts.update.isPending}>
          Сохранить
        </button>
      }
    >
      <form id="group-form" onSubmit={onSubmit}>
        <div className="modal-section-label">Основное</div>
        <Field label="Название группы" required>
          <TextInput required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Направление" required>
          <SelectInput value={directionId} onChange={(e) => setDirectionId(e.target.value)} options={directionOptions} required />
        </Field>
        <Field label="Преподаватель" required>
          <SelectInput value={teacherId} onChange={(e) => setTeacherId(e.target.value)} options={teacherOptions} required />
        </Field>
        <Field label="Ссылка на чат ВК">
          <TextInput value={vkChat} onChange={(e) => setVkChat(e.target.value)} placeholder="https://vk.me/..." />
        </Field>

        <div className="modal-section-label">Расписание уроков</div>
        <Field label="Длительность">
          <SelectInput
            value={String(duration)}
            onChange={(e) => setDuration(Number(e.target.value) as LessonDuration)}
            options={[
              { value: 45, label: '45 мин' },
              { value: 60, label: '60 мин' },
              { value: 90, label: '90 мин' },
            ]}
          />
        </Field>
        <Field label="Уроков в неделю">
          <NumberInput min={1} max={7} value={perWeek} onChange={(e) => setPerWeek(e.target.value)} />
        </Field>
        <Field label="Дата начала">
          <DateInput value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </Field>

        <div className="modal-section-label">Параметры</div>
        <Field label="Индивидуальное занятие">
          <Checkbox checked={isIndividual} onChange={(e) => setIsIndividual(e.target.checked)} />
        </Field>
        {!isNew && (
          <Field label="Группа активна">
            <Checkbox checked={active} onChange={(e) => setActive(e.target.checked)} />
          </Field>
        )}

        <div className="modal-section-label">Слоты расписания</div>
        <div id="slots-list">
          {slots.map((s, i) => (
            <div key={i} className="slot-row">
              <SelectInput
                value={String(s.day_of_week)}
                onChange={(e) => updateSlot(i, 'day_of_week', e.target.value)}
                options={DOW.map((d, idx) => ({ value: idx, label: d }))}
              />
              <input
                type="time"
                value={s.start_time}
                onChange={(e) => updateSlot(i, 'start_time', e.target.value)}
              />
              <button
                type="button"
                className="slot-row__remove"
                onClick={() => setSlots((arr) => arr.filter((_, idx) => idx !== i))}
                aria-label="Удалить слот"
              >×</button>
            </div>
          ))}
        </div>
        <button
          type="button"
          className="slot-add"
          onClick={() => setSlots((arr) => [...arr, { day_of_week: 1, start_time: '18:00' }])}
        >+ Добавить слот</button>
      </form>
    </Dialog>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/admin/src/pages/groups/GroupFormModal.tsx
git commit -m "r2(groups): form modal with slot editor"
```

---

## Task 10: LessonGrid + LessonEditor (components/lessons/)

**Files:**
- Create: `web/admin/src/components/lessons/LessonGrid.tsx`
- Create: `web/admin/src/components/lessons/LessonEditor.tsx`

- [ ] **Step 1: LessonGrid**

`web/admin/src/components/lessons/LessonGrid.tsx`:
```tsx
import { useMemo } from 'react';
import { useLessons } from '../../hooks/useLessons';
import { useDirections } from '../../hooks/useDirections';
import { directionColor } from '../../lib/direction-color';
import type { Group, Lesson } from '../../lib/types';

interface Props {
  group: Group;
  selectedSlot: number | null;
  onSelectSlot: (slot: number, lessonId: number | null) => void;
}

export function LessonGrid({ group, selectedSlot, onSelectSlot }: Props) {
  const { data: lessons = [] } = useLessons({ group_id: group.id });
  const { data: directions = [] } = useDirections(true);
  const direction = directions.find((d) => d.id === group.direction_id) || null;
  const color = directionColor(direction);

  const byNumber = useMemo(() => {
    const map = new Map<number, Lesson>();
    let max = 0;
    for (const l of lessons) {
      const slot = Math.ceil(Number(l.lesson_number));
      if (!map.has(slot)) map.set(slot, l);
      if (slot > max) max = slot;
    }
    return { map, max };
  }, [lessons]);

  const totalSlots = direction?.total_lessons != null ? Number(direction.total_lessons) : null;
  const slotCount = totalSlots ? Math.max(totalSlots, byNumber.max) : Math.max(byNumber.max, 12);

  return (
    <div className="lesson-grid">
      {Array.from({ length: slotCount }, (_, i) => {
        const num = i + 1;
        const lesson = byNumber.map.get(num);
        const filled = !!lesson;
        const isSelected = selectedSlot === num;
        return (
          <button
            key={num}
            type="button"
            className={`lesson-square${filled ? ' is-filled' : ''}${isSelected ? ' is-selected' : ''}`}
            style={{ ['--dir-color' as string]: color }}
            aria-label={`Урок №${num}${filled ? '' : ' (не проведён)'}`}
            data-tip={`Урок №${num}`}
            onClick={() => onSelectSlot(num, lesson ? lesson.id : null)}
          >
            <span className="lesson-square__num">{num}</span>
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: LessonEditor**

`web/admin/src/components/lessons/LessonEditor.tsx`:
```tsx
import { useEffect, useRef, useState } from 'react';
import { useLessonFull, useLessonMutations } from '../../hooks/useLessons';
import { useMemberships } from '../../hooks/useMemberships';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../ui/Toast';
import { calcPayment } from '../../lib/pricing';
import type { Group } from '../../lib/types';

interface Props {
  group: Group;
  slot: number;
  lessonId: number | null;
  color: string;
  onClose: () => void;
}

export function LessonEditor({ group, slot, lessonId, color, onClose }: Props) {
  const { data: lesson, isLoading: lessonLoading } = useLessonFull(lessonId);
  const { data: members = [], isLoading: membersLoading } = useMemberships({ group_id: group.id });
  const muts = useLessonMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const editorRef = useRef<HTMLDivElement | null>(null);
  const isFirstOpenRef = useRef(true);

  const [date, setDate] = useState('');
  const [url, setUrl] = useState('');
  const [present, setPresent] = useState<Record<number, boolean>>({});
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  useEffect(() => {
    if (lesson) {
      setDate(String(lesson.lesson_date).slice(0, 10));
      setUrl(lesson.record_url || '');
      const init: Record<number, boolean> = {};
      for (const a of lesson.attendance || []) init[a.student_id] = !!a.present;
      setPresent(init);
    } else if (lessonId === null) {
      setDate('');
      setUrl('');
      // Новый урок — по умолчанию все присутствуют
      const init: Record<number, boolean> = {};
      for (const m of members) init[m.student_id] = true;
      setPresent(init);
    }
  }, [lesson, lessonId, members]);

  useEffect(() => {
    if (isFirstOpenRef.current && editorRef.current) {
      isFirstOpenRef.current = false;
      editorRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, []);

  if (lessonLoading || membersLoading) {
    return <div ref={editorRef} className="lesson-editor-host--loading" />;
  }

  const togglePresent = (sid: number) => {
    setPresent((p) => ({ ...p, [sid]: !p[sid] }));
  };

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

  const handleDelete = async () => {
    if (!lesson) return;
    if (!confirmingDelete) { setConfirmingDelete(true); return; }
    try {
      await muts.remove.mutateAsync(lesson.id);
      toast('Урок удалён', 'ok');
      onClose();
    } catch (err) { showError(err); }
  };

  return (
    <div ref={editorRef} className="lesson-editor" style={{ ['--dir-color' as string]: color }}>
      <div className="lesson-editor__header">
        <h4>Урок №{slot}{lesson ? '' : ' · новый'}</h4>
        <button type="button" className="btn-secondary" onClick={onClose}>Закрыть</button>
      </div>
      <div className="lesson-editor__row">
        <label>Дата проведения</label>
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </div>
      <div className="lesson-editor__row">
        <label>Ссылка на запись урока</label>
        <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." />
      </div>
      <div className="lesson-editor__row">
        <label>
          Посещаемость <span className="lesson-editor__hint">(клик по карточке — переключение)</span>
        </label>
        <div className="attendance-grid">
          {members.length ? members.map((m) => {
            const isPresent = !!present[m.student_id];
            return (
              <button
                key={m.student_id}
                type="button"
                className={`attendance-card ${isPresent ? 'is-present' : 'is-absent'}`}
                onClick={() => togglePresent(m.student_id)}
              >
                <span className="attendance-card__icon" aria-hidden>{isPresent ? '✓' : '✕'}</span>
                <span className="attendance-card__name">{m.student_name || `#${m.student_id}`}</span>
              </button>
            );
          }) : (
            <div className="memberships__empty">В группе нет учеников</div>
          )}
        </div>
      </div>
      <div className="lesson-editor__footer">
        {lesson && (
          <button
            type="button"
            className={`btn-delete${confirmingDelete ? ' is-confirming' : ''}`}
            onClick={() => { void handleDelete(); }}
          >{confirmingDelete ? 'Точно удалить?' : 'Удалить урок'}</button>
        )}
        <button
          type="button"
          className="btn-primary"
          style={{ marginLeft: 'auto' }}
          onClick={() => { void handleSave(); }}
          disabled={muts.create.isPending || muts.update.isPending || muts.toggleAttendance.isPending || muts.remove.isPending}
        >{lesson ? 'Сохранить' : 'Создать урок'}</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add web/admin/src/components/lessons
git commit -m "r2(lessons): LessonGrid + LessonEditor components"
```

---

## Task 11: GroupDetailPage с lesson grid и members

**Files:**
- Modify: `web/admin/src/pages/groups/GroupDetailPage.tsx`
- Create: `web/admin/src/pages/groups/GroupMembersBlock.tsx`

- [ ] **Step 1: GroupMembersBlock**

`web/admin/src/pages/groups/GroupMembersBlock.tsx`:
```tsx
import { useStudents } from '../../hooks/useStudents';
import { MembershipsBlock } from '../../components/memberships/MembershipsBlock';
import { StatusBadge } from '../../components/StatusBadge';
import type { Group } from '../../lib/types';

export default function GroupMembersBlock({ group }: { group: Group }) {
  const { data: students = [] } = useStudents();
  const studentOptions = students
    .filter((s) => s.enrollment_status !== 'not_enrolled')
    .map((s) => ({ value: s.id, label: s.full_name }));

  return (
    <MembershipsBlock
      config={{
        mode: 'byGroup',
        groupId: group.id,
        pickerOptions: studentOptions,
        pickerLabel: 'Выберите ученика',
      }}
      emptyText="В группе нет учеников"
      renderCard={(m) => {
        const s = students.find((x) => x.id === m.student_id);
        return {
          title: m.student_name || (s ? s.full_name : `#${m.student_id}`),
          meta: s ? (
            <>
              {s.age && <span className="link-card-meta-pill">{s.age} лет</span>}
              {s.school_grade && <span className="link-card-meta-pill">{s.school_grade}-й кл.</span>}
              <StatusBadge row={s} />
            </>
          ) : null,
          navigateTo: `/admin/students/${m.student_id}`,
        };
      }}
    />
  );
}
```

- [ ] **Step 2: GroupDetailPage**

`web/admin/src/pages/groups/GroupDetailPage.tsx`:
```tsx
import { useState } from 'react';
import { useParams, Navigate, useNavigate } from 'react-router-dom';
import { useGroup, useGroupMutations } from '../../hooks/useGroups';
import { useTeachers } from '../../hooks/useTeachers';
import { useDirections } from '../../hooks/useDirections';
import { DetailShell, type DetailField } from '../../components/detail/DetailShell';
import { Avatar } from '../../components/Avatar';
import { DirTag } from '../../components/ui/DirTag';
import { EntityLink } from '../../components/EntityLink';
import { PageLoading } from '../../components/ui/Skeleton';
import { LessonGrid } from '../../components/lessons/LessonGrid';
import { LessonEditor } from '../../components/lessons/LessonEditor';
import { directionColor } from '../../lib/direction-color';
import { fmtDate } from '../../lib/format';
import { formatSlot } from '../../lib/slots';
import { useToast } from '../../components/ui/Toast';
import { useApiError } from '../../hooks/useApiError';
import type { Group } from '../../lib/types';
import GroupFormModal from './GroupFormModal';
import GroupMembersBlock from './GroupMembersBlock';

export default function GroupDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const navigate = useNavigate();
  const { data: group, isLoading } = useGroup(id);
  const { data: teachers = [] } = useTeachers(true);
  const { data: directions = [] } = useDirections(true);
  const muts = useGroupMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<{ slot: number; lessonId: number | null } | null>(null);

  if (isLoading) return <PageLoading />;
  if (!group) return <Navigate to="/admin/groups" replace />;

  const direction = directions.find((d) => d.id === group.direction_id) || null;
  const teacher = teachers.find((t) => t.id === group.teacher_id) || null;
  const color = directionColor(direction);

  const fields: DetailField<Group>[] = [
    { key: 'id', label: 'ID' },
    { key: 'name', label: 'Название' },
    { key: 'direction_id', label: 'Направление',
      cell: () => direction ? <DirTag direction={direction} /> : <>#{group.direction_id}</> },
    { key: 'teacher_id', label: 'Преподаватель',
      cell: () => <EntityLink section="teachers" id={group.teacher_id} text={teacher?.name || `#${group.teacher_id}`} /> },
    { key: 'is_individual', label: 'Индивидуальная', cell: (r) => r.is_individual ? 'да' : 'нет' },
    { key: 'lesson_duration_minutes', label: 'Длительность урока', cell: (r) => `${r.lesson_duration_minutes} мин` },
    { key: 'lessons_per_week', label: 'Уроков в неделю' },
    { key: 'group_start_date', label: 'Дата старта', cell: (r) => fmtDate(r.group_start_date) },
    { key: 'slots', label: 'Расписание', cell: (r) => (r.slots || []).map(formatSlot).join(', ') || '—' },
    { key: 'vk_chat', label: 'Чат ВК' },
    { key: 'active', label: 'Статус', cell: (r) => r.active ? 'Активна' : 'Архив' },
    { key: 'created_at', label: 'Создана', cell: (r) => fmtDate(r.created_at) },
  ];

  const handleDelete = async () => {
    try {
      await muts.remove.mutateAsync(group.id);
      toast('Архивировано', 'ok');
      navigate('/admin/groups');
    } catch (err) { showError(err); }
  };

  return (
    <>
      <DetailShell<Group>
        title={`Группа ${group.name}`}
        subtitle={`#${group.id} · ${group.is_individual ? 'Индивидуальная' : 'Групповая'} · ${group.lesson_duration_minutes} мин`}
        row={group}
        fields={fields}
        cardTitle="Данные группы"
        onEdit={() => setEditing(true)}
        onDelete={handleDelete}
        backTo="/admin/groups"
      >
        {teacher && (
          <div className="teacher-info-card">
            <Avatar name={teacher.name} size={42} />
            <div>
              <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 3 }}>Преподаватель</div>
              <div style={{ fontWeight: 700, color: 'var(--text)' }}>{teacher.name}</div>
              {teacher.email && <div style={{ fontSize: 12, color: 'var(--text3)' }}>{teacher.email}</div>}
            </div>
          </div>
        )}

        <div className="detail__section">
          <h3 className="detail__section-title">Уроки группы</h3>
          <div className="lesson-grid-hint">
            Серые — не проведены, цветные — проведены. Клик по любому квадрату — открыть/создать.
          </div>
          <LessonGrid
            group={group}
            selectedSlot={selected?.slot ?? null}
            onSelectSlot={(slot, lessonId) => setSelected({ slot, lessonId })}
          />
          {selected && (
            <LessonEditor
              group={group}
              slot={selected.slot}
              lessonId={selected.lessonId}
              color={color}
              onClose={() => setSelected(null)}
            />
          )}
        </div>

        <div className="sub-header">Ученики группы</div>
        <GroupMembersBlock group={group} />
      </DetailShell>
      {editing && (
        <GroupFormModal initial={group} onClose={() => setEditing(false)} />
      )}
    </>
  );
}
```

- [ ] **Step 3: Verify build**

```bash
npm run admin:typecheck 2>&1 | tail -3
npm run admin:build 2>&1 | tail -6
```

- [ ] **Step 4: Commit**

```bash
git add web/admin/src/pages/groups/GroupDetailPage.tsx web/admin/src/pages/groups/GroupMembersBlock.tsx
git commit -m "r2(groups): detail page with lesson grid and members"
```

---

## Task 12: LessonsListPage + LessonFormModal

**Files:**
- Modify: `web/admin/src/pages/lessons/LessonsListPage.tsx`
- Create: `web/admin/src/pages/lessons/LessonFormModal.tsx`

- [ ] **Step 1: LessonsListPage**

```tsx
// web/admin/src/pages/lessons/LessonsListPage.tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLessons } from '../../hooks/useLessons';
import { DataTable, type Column } from '../../components/table/DataTable';
import { EntityLink } from '../../components/EntityLink';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import type { Lesson } from '../../lib/types';
import LessonFormModal from './LessonFormModal';

const TYPE_LABEL: Record<string, string> = {
  regular: 'обычный',
  substitution: 'замена',
  reschedule: 'перенос',
};

export default function LessonsListPage() {
  const { data, isLoading } = useLessons();
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);

  if (isLoading) return <TableSkeleton rows={8} cols={9} />;
  const rows: Lesson[] = data || [];

  const columns: Column<Lesson>[] = [
    { key: 'id', label: 'ID', cell: (r) => <span className="id-cell">#{r.id}</span> },
    { key: 'lesson_date', label: 'Дата', searchable: true, cell: (r) => fmtDate(r.lesson_date) },
    { key: 'group_name', label: 'Группа', searchable: true,
      cell: (r) => <EntityLink section="groups" id={r.group_id} text={r.group_name} /> },
    { key: 'teacher_name', label: 'Преподаватель', searchable: true,
      cell: (r) => <EntityLink section="teachers" id={r.teacher_id} text={r.teacher_name} /> },
    { key: 'lesson_number', label: 'Урок #' },
    { key: 'lesson_type', label: 'Тип',
      cell: (r) => TYPE_LABEL[r.lesson_type] || r.lesson_type },
  ];

  return (
    <>
      <DataTable<Lesson>
        data={rows}
        columns={columns}
        title="Уроки"
        onRowClick={(row) => navigate(`/admin/lessons/${row.id}`)}
        headerActions={<button className="btn-add" onClick={() => setModalOpen(true)}>+ Новый</button>}
      />
      {modalOpen && (
        <LessonFormModal onClose={() => setModalOpen(false)} />
      )}
    </>
  );
}
```

- [ ] **Step 2: LessonFormModal (standalone create)**

```tsx
// web/admin/src/pages/lessons/LessonFormModal.tsx
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLessonMutations } from '../../hooks/useLessons';
import { useTeachers } from '../../hooks/useTeachers';
import { useGroups } from '../../hooks/useGroups';
import { useMemberships } from '../../hooks/useMemberships';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { TextInput } from '../../components/form/TextInput';
import { NumberInput } from '../../components/form/NumberInput';
import { DateInput } from '../../components/form/DateInput';
import { SelectInput } from '../../components/form/SelectInput';
import { Checkbox } from '../../components/form/Checkbox';
import { calcPayment } from '../../lib/pricing';
import type { LessonType } from '../../lib/types';

interface Props { onClose: () => void; }

export default function LessonFormModal({ onClose }: Props) {
  const navigate = useNavigate();
  const muts = useLessonMutations();
  const { data: teachers = [] } = useTeachers();
  const { data: groups = [] } = useGroups();
  const { toast } = useToast();
  const showError = useApiError();

  const [lessonDate, setLessonDate] = useState(new Date().toISOString().slice(0, 10));
  const [groupId, setGroupId] = useState<string>('');
  const [teacherId, setTeacherId] = useState<string>('');
  const [lessonNumber, setLessonNumber] = useState('1');
  const [lessonType, setLessonType] = useState<LessonType>('regular');
  const [originalTeacherId, setOriginalTeacherId] = useState<string>('');
  const [recordUrl, setRecordUrl] = useState('');
  const [payment, setPayment] = useState('0');
  const [penalty, setPenalty] = useState('0');

  const { data: members = [] } = useMemberships(groupId ? { group_id: Number(groupId) } : { group_id: 0 });
  const [present, setPresent] = useState<Record<number, boolean>>({});

  const toggle = (sid: number) => setPresent((p) => {
    const next = { ...p, [sid]: !(sid in p ? p[sid] : true) };
    const presentCount = members.filter((m) => (m.student_id in next ? next[m.student_id] : true)).length;
    setPayment(String(calcPayment(members.length, presentCount, false)));
    return next;
  });

  const isPresent = (sid: number) => sid in present ? present[sid] : true;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!groupId || !teacherId) {
      toast('Группа и преподаватель обязательны', 'error');
      return;
    }
    const attendance = members.map((m) => ({ student_id: m.student_id, present: isPresent(m.student_id) }));
    const presentCount = attendance.filter((a) => a.present).length;
    try {
      const created = await muts.create.mutateAsync({
        lesson_date: lessonDate,
        group_id: Number(groupId),
        teacher_id: Number(teacherId),
        lesson_number: Number(lessonNumber),
        lesson_duration_minutes: 90,
        lesson_type: lessonType,
        record_url: recordUrl || null,
        original_teacher_id: lessonType === 'substitution' && originalTeacherId
          ? Number(originalTeacherId) : null,
        submitted_by_token: 'admin-imported',
        attendance,
        payroll: {
          total_students: members.length,
          present_count: presentCount,
          payment: Number(payment) || 0,
          penalty: Number(penalty) || 0,
        },
      });
      toast('Урок создан', 'ok');
      onClose();
      navigate(`/admin/lessons/${created.id}`);
    } catch (err) { showError(err); }
  };

  const teacherOpts = [{ value: '', label: '— выберите —' }, ...teachers
    .filter((t) => t.active).map((t) => ({ value: t.id, label: t.name }))];
  const groupOpts = [{ value: '', label: '— выберите —' }, ...groups
    .filter((g) => g.active).map((g) => ({ value: g.id, label: g.name }))];

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      wide
      title="Новый урок"
      footer={
        <button type="submit" form="lesson-form" className="btn-primary" disabled={muts.create.isPending}>
          Создать урок
        </button>
      }
    >
      <form id="lesson-form" onSubmit={onSubmit}>
        <Field label="Дата" required>
          <DateInput required value={lessonDate} onChange={(e) => setLessonDate(e.target.value)} />
        </Field>
        <Field label="Группа" required>
          <SelectInput required value={groupId} onChange={(e) => setGroupId(e.target.value)} options={groupOpts} />
        </Field>
        <Field label="Преподаватель" required>
          <SelectInput required value={teacherId} onChange={(e) => setTeacherId(e.target.value)} options={teacherOpts} />
        </Field>
        <Field label="Номер урока" required>
          <NumberInput required step={0.5} min={0.5} value={lessonNumber} onChange={(e) => setLessonNumber(e.target.value)} />
        </Field>
        <Field label="Тип">
          <SelectInput
            value={lessonType}
            onChange={(e) => setLessonType(e.target.value as LessonType)}
            options={[
              { value: 'regular', label: 'Обычный' },
              { value: 'substitution', label: 'Замена' },
              { value: 'reschedule', label: 'Перенос' },
            ]}
          />
        </Field>
        {lessonType === 'substitution' && (
          <Field label="Оригинальный препод.">
            <SelectInput value={originalTeacherId} onChange={(e) => setOriginalTeacherId(e.target.value)} options={teacherOpts} />
          </Field>
        )}
        <Field label="Ссылка на запись">
          <TextInput value={recordUrl} onChange={(e) => setRecordUrl(e.target.value)} placeholder="https://..." />
        </Field>

        {groupId && (
          <>
            <h4 className="memberships__title">Посещаемость</h4>
            {members.length === 0 ? (
              <div className="memberships__empty">В группе нет учеников</div>
            ) : members.map((m) => (
              <div key={m.student_id} className="memberships__row">
                <div className="memberships__group">{m.student_name || `#${m.student_id}`}</div>
                <div>
                  <label className="modal__check" style={{ margin: 0 }}>
                    <Checkbox checked={isPresent(m.student_id)} onChange={() => toggle(m.student_id)} />
                    <span className="modal__check-box" />
                  </label>
                </div>
                <div /><div />
              </div>
            ))}

            <h4 className="memberships__title">Зарплата</h4>
            <div className="memberships__row">
              <div>Оплата ₽</div>
              <NumberInput step={0.01} value={payment} onChange={(e) => setPayment(e.target.value)} />
              <div>Штраф ₽</div>
              <NumberInput step={0.01} value={penalty} onChange={(e) => setPenalty(e.target.value)} />
            </div>
          </>
        )}
      </form>
    </Dialog>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add web/admin/src/pages/lessons/LessonsListPage.tsx web/admin/src/pages/lessons/LessonFormModal.tsx
git commit -m "r2(lessons): list page + standalone create modal"
```

---

## Task 13: LessonDetailPage с attendance toggle + payroll editor

**Files:**
- Modify: `web/admin/src/pages/lessons/LessonDetailPage.tsx`

- [ ] **Step 1: LessonDetailPage**

```tsx
import { useParams, Navigate, useNavigate } from 'react-router-dom';
import { useLessonFull, useLessonMutations } from '../../hooks/useLessons';
import { usePayrollMutations } from '../../hooks/usePayroll';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { DetailShell, type DetailField } from '../../components/detail/DetailShell';
import { EntityLink } from '../../components/EntityLink';
import { PageLoading } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import type { LessonFull } from '../../lib/types';

const TYPE_LABEL: Record<string, string> = {
  regular: 'обычный',
  substitution: 'замена',
  reschedule: 'перенос',
};

export default function LessonDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const navigate = useNavigate();
  const { data: lesson, isLoading } = useLessonFull(id);
  const muts = useLessonMutations();
  const payrollMuts = usePayrollMutations();
  const { toast } = useToast();
  const showError = useApiError();

  if (isLoading) return <PageLoading />;
  if (!lesson) return <Navigate to="/admin/lessons" replace />;

  const fields: DetailField<LessonFull>[] = [
    { key: 'id', label: 'ID' },
    { key: 'lesson_date', label: 'Дата', cell: (r) => fmtDate(r.lesson_date) },
    { key: 'lesson_number', label: 'Номер урока' },
    { key: 'lesson_type', label: 'Тип', cell: (r) => TYPE_LABEL[r.lesson_type] || r.lesson_type },
    { key: 'group_name', label: 'Группа',
      cell: (r) => <EntityLink section="groups" id={r.group_id} text={r.group_name} /> },
    { key: 'teacher_name', label: 'Преподаватель',
      cell: (r) => <EntityLink section="teachers" id={r.teacher_id} text={r.teacher_name} /> },
    { key: 'original_teacher_name', label: 'Оригинальный препод',
      cell: (r) => <EntityLink section="teachers" id={r.original_teacher_id} text={r.original_teacher_name} /> },
    { key: 'lesson_duration_minutes', label: 'Длительность, мин' },
    { key: 'record_url', label: 'Запись', cell: (r) => r.record_url || '—' },
    { key: 'submitted_by_token', label: 'Токен' },
    { key: 'submitted_at', label: 'Создано', cell: (r) => fmtDate(r.submitted_at) },
  ];

  const handleDelete = async () => {
    try {
      await muts.remove.mutateAsync(lesson.id);
      toast('Урок удалён', 'ok');
      navigate('/admin/lessons');
    } catch (err) { showError(err); }
  };

  const toggleAttendance = async (sid: number, present: boolean) => {
    try {
      await muts.toggleAttendance.mutateAsync({ lessonId: lesson.id, studentId: sid, present });
      toast('Сохранено', 'ok');
    } catch (err) { showError(err); }
  };

  const updatePayrollField = async (field: 'total_students' | 'present_count' | 'payment' | 'penalty', value: number) => {
    if (!lesson.payroll) return;
    try {
      await payrollMuts.update.mutateAsync({ id: lesson.payroll.id, body: { [field]: value } });
      toast('Сохранено', 'ok');
    } catch (err) { showError(err); }
  };

  return (
    <DetailShell<LessonFull>
      title={`Урок ${fmtDate(lesson.lesson_date)} · ${lesson.group_name || ''}`}
      subtitle={`№${lesson.lesson_number} · ${lesson.teacher_name || ''}${lesson.lesson_type !== 'regular' ? ' · ' + (TYPE_LABEL[lesson.lesson_type] || lesson.lesson_type) : ''}`}
      row={lesson}
      fields={fields}
      cardTitle="Данные урока"
      onDelete={handleDelete}
      deleteLabel="Удалить урок"
      backTo="/admin/lessons"
    >
      <div className="detail__section">
        <h3 className="detail__section-title">Посещаемость</h3>
        {lesson.attendance.length === 0 ? (
          <div className="memberships__empty">Нет записей посещаемости</div>
        ) : (
          <>
            <div className="memberships__head">
              <div>Ученик</div><div>Был</div><div /><div />
            </div>
            {lesson.attendance.map((a) => (
              <div key={a.student_id} className="memberships__row">
                <div className="memberships__group">
                  <EntityLink section="students" id={a.student_id} text={a.student_name || `#${a.student_id}`} />
                </div>
                <div>
                  <label className="modal__check" style={{ margin: 0 }}>
                    <input
                      type="checkbox"
                      defaultChecked={a.present}
                      onChange={(e) => { void toggleAttendance(a.student_id, e.target.checked); }}
                    />
                    <span className="modal__check-box" />
                  </label>
                </div>
                <div /><div />
              </div>
            ))}
          </>
        )}
      </div>

      <div className="detail__section">
        <h3 className="detail__section-title">Зарплата</h3>
        {!lesson.payroll ? (
          <div className="memberships__empty">Зарплата для этого урока не создана</div>
        ) : (
          <>
            <div className="memberships__row">
              <div>Всего</div>
              <input type="number" defaultValue={lesson.payroll.total_students}
                onBlur={(e) => { void updatePayrollField('total_students', Number(e.target.value)); }} />
              <div>Было</div>
              <input type="number" defaultValue={lesson.payroll.present_count}
                onBlur={(e) => { void updatePayrollField('present_count', Number(e.target.value)); }} />
            </div>
            <div className="memberships__row">
              <div>Оплата ₽</div>
              <input type="number" step={0.01} defaultValue={String(lesson.payroll.payment)}
                onBlur={(e) => { void updatePayrollField('payment', Number(e.target.value)); }} />
              <div>Штраф ₽</div>
              <input type="number" step={0.01} defaultValue={String(lesson.payroll.penalty)}
                onBlur={(e) => { void updatePayrollField('penalty', Number(e.target.value)); }} />
            </div>
          </>
        )}
      </div>
    </DetailShell>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/admin/src/pages/lessons/LessonDetailPage.tsx
git commit -m "r2(lessons): detail page with attendance toggle and payroll editor"
```

---

## Task 14: PayrollPage (list/summary + date range)

**Files:**
- Modify: `web/admin/src/pages/payroll/PayrollPage.tsx`

- [ ] **Step 1: PayrollPage**

```tsx
import { useState } from 'react';
import { usePayrollList, usePayrollSummary } from '../../hooks/usePayroll';
import { DataTable, type Column } from '../../components/table/DataTable';
import { EntityLink } from '../../components/EntityLink';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import type { PayrollEntry } from '../../lib/types';

function defaultRange() {
  const now = new Date();
  const msk = new Date(now.getTime() + 3 * 60 * 60 * 1000);
  const y = msk.getUTCFullYear();
  const m = String(msk.getUTCMonth() + 1).padStart(2, '0');
  return {
    dateFrom: `${y}-${m}-01`,
    dateTo: msk.toISOString().slice(0, 10),
  };
}

export default function PayrollPage() {
  const [mode, setMode] = useState<'list' | 'summary'>('list');
  const [{ dateFrom, dateTo }, setRange] = useState(defaultRange);

  return (
    <>
      <div className="section-header">
        <span className="section-title">Зарплата</span>
        <div className="section-actions">
          <button
            className="btn-secondary"
            style={mode === 'list' ? { background: 'var(--accent)', color: '#fff', borderColor: 'var(--accent)' } : undefined}
            onClick={() => setMode('list')}
          >Список</button>
          <button
            className="btn-secondary"
            style={mode === 'summary' ? { background: 'var(--accent)', color: '#fff', borderColor: 'var(--accent)' } : undefined}
            onClick={() => setMode('summary')}
          >Сводка</button>
        </div>
      </div>

      {mode === 'list' ? (
        <PayrollListView />
      ) : (
        <PayrollSummaryView
          dateFrom={dateFrom}
          dateTo={dateTo}
          onRangeChange={setRange}
        />
      )}
    </>
  );
}

function PayrollListView() {
  const { data, isLoading } = usePayrollList();
  if (isLoading) return <TableSkeleton rows={8} cols={7} />;
  const rows: PayrollEntry[] = data || [];

  const columns: Column<PayrollEntry>[] = [
    { key: 'lesson_date', label: 'Дата', searchable: true,
      cell: (r) => <EntityLink section="lessons" id={r.lesson_id} text={fmtDate(r.lesson_date)} /> },
    { key: 'teacher_name', label: 'Преподаватель', searchable: true,
      cell: (r) => <EntityLink section="teachers" id={r.teacher_id} text={r.teacher_name} /> },
    { key: 'group_name', label: 'Группа', searchable: true,
      cell: (r) => <EntityLink section="lessons" id={r.lesson_id} text={r.group_name} /> },
    { key: 'lesson_number', label: 'Урок #' },
    { key: 'present_count', label: 'Было/Всего',
      cell: (r) => `${r.present_count}/${r.total_students}` },
    { key: 'payment', label: 'Оплата ₽',
      cell: (r) => Number(r.payment).toLocaleString('ru') },
    { key: 'penalty', label: 'Штраф ₽',
      cell: (r) => Number(r.penalty).toLocaleString('ru') },
  ];

  return (
    <DataTable<PayrollEntry>
      data={rows}
      columns={columns}
      title="Список выплат"
    />
  );
}

interface SummaryProps {
  dateFrom: string;
  dateTo: string;
  onRangeChange: (r: { dateFrom: string; dateTo: string }) => void;
}

function PayrollSummaryView({ dateFrom, dateTo, onRangeChange }: SummaryProps) {
  const { data, isLoading } = usePayrollSummary({
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  });
  if (isLoading) return <TableSkeleton rows={5} cols={4} />;
  const rows = data || [];

  const totalPayment = rows.reduce((acc, r) => acc + Number(r.sum_payment || 0), 0);
  const totalPenalty = rows.reduce((acc, r) => acc + Number(r.sum_penalty || 0), 0);
  const totalLessons = rows.reduce((acc, r) => acc + Number(r.lessons_count || 0), 0);

  return (
    <>
      <div className="payroll-range">
        <label>Период:</label>
        <input type="date" value={dateFrom} onChange={(e) => onRangeChange({ dateFrom: e.target.value, dateTo })} />
        <span className="payroll-range__sep">—</span>
        <input type="date" value={dateTo} onChange={(e) => onRangeChange({ dateFrom, dateTo: e.target.value })} />
        <button className="btn-secondary" onClick={() => onRangeChange({ dateFrom: '', dateTo: '' })}>Сбросить</button>
      </div>
      <div className="data-table__scroll">
        <table className="data-table">
          <thead>
            <tr><th>Преподаватель</th><th>Уроков</th><th>Сумма оплат ₽</th><th>Сумма штрафов ₽</th></tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={4} style={{ textAlign: 'center', padding: 24, color: 'var(--text3)' }}>
                Нет данных за выбранный период
              </td></tr>
            ) : (
              <>
                {rows.map((r) => (
                  <tr key={r.teacher_id}>
                    <td><EntityLink section="teachers" id={r.teacher_id} text={r.teacher_name} /></td>
                    <td>{r.lessons_count}</td>
                    <td>{Number(r.sum_payment).toLocaleString('ru')}</td>
                    <td>{Number(r.sum_penalty).toLocaleString('ru')}</td>
                  </tr>
                ))}
                <tr style={{ background: 'var(--bg3)', fontWeight: 600 }}>
                  <td>Итого</td>
                  <td>{totalLessons}</td>
                  <td>{totalPayment.toLocaleString('ru')}</td>
                  <td>{totalPenalty.toLocaleString('ru')}</td>
                </tr>
              </>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
```

- [ ] **Step 2: Verify**

```bash
npm run admin:typecheck 2>&1 | tail -3
npm run admin:build 2>&1 | tail -6
```

- [ ] **Step 3: Commit**

```bash
git add web/admin/src/pages/payroll/PayrollPage.tsx
git commit -m "r2(payroll): list+summary with date range"
```

---

# Параллельный поток C — teachers + tokens + directions + archive

Subagent C работает в `pages/teachers/`, `pages/tokens/`, `pages/directions/`, `pages/archive/`. Запрещено трогать pages/students, pages/groups, pages/lessons, pages/payroll.

## Task 15: TeachersListPage + TeacherDetailPage + TeacherFormModal

**Files:**
- Modify: `web/admin/src/pages/teachers/TeachersListPage.tsx`
- Modify: `web/admin/src/pages/teachers/TeacherDetailPage.tsx`
- Create: `web/admin/src/pages/teachers/TeacherFormModal.tsx`

- [ ] **Step 1: TeachersListPage**

```tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTeachers } from '../../hooks/useTeachers';
import { useTokens } from '../../hooks/useTokens';
import { useGroups } from '../../hooks/useGroups';
import { DataTable, type Column } from '../../components/table/DataTable';
import { Avatar } from '../../components/Avatar';
import { Pill } from '../../components/ui/Pill';
import { TableSkeleton } from '../../components/ui/Skeleton';
import type { Teacher } from '../../lib/types';
import TeacherFormModal from './TeacherFormModal';

export default function TeachersListPage() {
  const { data, isLoading } = useTeachers();
  const { data: tokens = [] } = useTokens(true);
  const { data: groups = [] } = useGroups(true);
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);

  if (isLoading) return <TableSkeleton rows={6} cols={7} />;
  const rows: Teacher[] = data || [];

  const columns: Column<Teacher>[] = [
    { key: 'id', label: 'ID', cell: (r) => <span className="id-cell">#{r.id}</span> },
    { key: 'name', label: 'Преподаватель', searchable: true,
      cell: (r) => (
        <div className="person-cell">
          <Avatar name={r.name} size={34} />
          <div><div className="person-name">{r.name}</div></div>
        </div>
      ) },
    { key: 'email', label: 'Email', searchable: true, cell: (r) => r.email || '—' },
    { key: 'phone', label: 'Телефон', searchable: true, cell: (r) => r.phone || '—' },
    { key: 'tokens_count', label: 'Токены',
      cell: (r) => {
        const cnt = tokens.filter((t) => t.teacher_id === r.id && t.active).length;
        return <Pill>{cnt} шт.</Pill>;
      }},
    { key: 'groups_count', label: 'Групп',
      cell: (r) => {
        const cnt = groups.filter((g) => g.teacher_id === r.id && g.active).length;
        return <Pill>{cnt}</Pill>;
      }},
    { key: 'active', label: 'Статус',
      cell: (r) => r.active
        ? <span className="badge badge--ok">Активен</span>
        : <span className="badge badge--muted">Архив</span> },
  ];

  return (
    <>
      <DataTable<Teacher>
        data={rows}
        columns={columns}
        title="Преподаватели"
        onRowClick={(row) => navigate(`/admin/teachers/${row.id}`)}
        headerActions={<button className="btn-add" onClick={() => setModalOpen(true)}>+ Новый</button>}
      />
      {modalOpen && (
        <TeacherFormModal initial={null} onClose={() => setModalOpen(false)} />
      )}
    </>
  );
}
```

- [ ] **Step 2: TeacherDetailPage**

```tsx
import { useState } from 'react';
import { useParams, Navigate, useNavigate } from 'react-router-dom';
import { useTeacher, useTeacherMutations } from '../../hooks/useTeachers';
import { useTokens } from '../../hooks/useTokens';
import { useGroups } from '../../hooks/useGroups';
import { useDirections } from '../../hooks/useDirections';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { DetailShell, type DetailField } from '../../components/detail/DetailShell';
import { EntityLink } from '../../components/EntityLink';
import { MonoBadge } from '../../components/ui/MonoBadge';
import { DirTag } from '../../components/ui/DirTag';
import { PageLoading } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import type { Teacher } from '../../lib/types';
import TeacherFormModal from './TeacherFormModal';

export default function TeacherDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const navigate = useNavigate();
  const { data: teacher, isLoading } = useTeacher(id);
  const { data: tokens = [] } = useTokens(true);
  const { data: groups = [] } = useGroups(true);
  const { data: directions = [] } = useDirections(true);
  const muts = useTeacherMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [editing, setEditing] = useState(false);

  if (isLoading) return <PageLoading />;
  if (!teacher) return <Navigate to="/admin/teachers" replace />;

  const myTokens = tokens.filter((t) => t.teacher_id === teacher.id);
  const myGroups = groups.filter((g) => g.teacher_id === teacher.id);

  const fields: DetailField<Teacher>[] = [
    { key: 'id', label: 'ID' },
    { key: 'email', label: 'Email' },
    { key: 'phone', label: 'Телефон' },
    { key: 'active', label: 'Статус', cell: (r) => r.active ? 'Активен' : 'Архив' },
    { key: 'created_at', label: 'Добавлен', cell: (r) => fmtDate(r.created_at) },
  ];

  const handleDelete = async () => {
    try {
      await muts.remove.mutateAsync(teacher.id);
      toast('Архивировано', 'ok');
      navigate('/admin/teachers');
    } catch (err) { showError(err); }
  };

  return (
    <>
      <DetailShell<Teacher>
        title={teacher.name}
        subtitle={`${teacher.email || ''}${teacher.email && teacher.phone ? ' · ' : ''}${teacher.phone || ''}`}
        row={teacher}
        fields={fields}
        cardTitle="Данные преподавателя"
        onEdit={() => setEditing(true)}
        onDelete={handleDelete}
        backTo="/admin/teachers"
      >
        <div className="sub-header">Токены <span className="count-badge">{myTokens.length}</span></div>
        {myTokens.length === 0 ? (
          <div className="memberships__empty">Нет токенов</div>
        ) : myTokens.map((tk) => (
          <div key={tk.token} className="token-row">
            <EntityLink section="tokens" id={tk.token} text={tk.token} />
            <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: 'var(--text3)' }}>{fmtDate(tk.created_at)}</span>
              <MonoBadge value={tk.active ? 'Активен' : 'Отозван'} active={tk.active} />
            </div>
          </div>
        ))}

        <div className="sub-header">Группы <span className="count-badge">{myGroups.length}</span></div>
        {myGroups.length === 0 ? (
          <div className="memberships__empty">Нет групп</div>
        ) : myGroups.map((g) => {
          const dir = directions.find((d) => d.id === g.direction_id);
          return (
            <div
              key={g.id}
              className="link-card"
              tabIndex={0}
              role="button"
              onClick={() => navigate(`/admin/groups/${g.id}`)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(`/admin/groups/${g.id}`); } }}
            >
              <div className="link-card-head">
                <div>
                  <div className="link-card-title">{g.name}</div>
                  <div className="link-card-meta">
                    {dir && <DirTag direction={dir} />}
                    {!g.active && <span className="archive-tag">Архив</span>}
                  </div>
                </div>
                <span style={{ fontSize: 11, color: 'var(--text3)' }}>#{g.id}</span>
              </div>
            </div>
          );
        })}
      </DetailShell>
      {editing && (
        <TeacherFormModal initial={teacher} onClose={() => setEditing(false)} />
      )}
    </>
  );
}
```

- [ ] **Step 3: TeacherFormModal**

```tsx
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTeacherMutations } from '../../hooks/useTeachers';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { TextInput } from '../../components/form/TextInput';
import { Checkbox } from '../../components/form/Checkbox';
import type { Teacher } from '../../lib/types';

interface Props { initial: Teacher | null; onClose: () => void; }

export default function TeacherFormModal({ initial, onClose }: Props) {
  const isNew = !initial;
  const navigate = useNavigate();
  const muts = useTeacherMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [name, setName] = useState(initial?.name || '');
  const [email, setEmail] = useState(initial?.email || '');
  const [phone, setPhone] = useState(initial?.phone || '');
  const [active, setActive] = useState(initial?.active ?? true);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const body: Partial<Teacher> = { name, email: email || null, phone: phone || null };
    if (!isNew) body.active = active;
    try {
      if (isNew) {
        const created = await muts.create.mutateAsync(body);
        toast('Создано', 'ok');
        onClose();
        navigate(`/admin/teachers/${created.id}`);
      } else {
        await muts.update.mutateAsync({ id: initial!.id, body });
        toast('Сохранено', 'ok');
        onClose();
      }
    } catch (err) { showError(err); }
  };

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={isNew ? 'Новый преподаватель' : `Редактировать: ${initial!.name}`}
      footer={
        <button type="submit" form="teacher-form" className="btn-primary"
          disabled={muts.create.isPending || muts.update.isPending}>Сохранить</button>
      }
    >
      <form id="teacher-form" onSubmit={onSubmit}>
        <Field label="Имя" required>
          <TextInput required value={name} onChange={(e) => setName(e.target.value)} placeholder="Иванов Алексей" />
        </Field>
        <Field label="Email">
          <TextInput type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="teacher@kotokod.ru" />
        </Field>
        <Field label="Телефон">
          <TextInput value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+7 (___) ___-__-__" />
        </Field>
        {!isNew && (
          <Field label="Активен">
            <Checkbox checked={active} onChange={(e) => setActive(e.target.checked)} />
          </Field>
        )}
      </form>
    </Dialog>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add web/admin/src/pages/teachers
git commit -m "r2(teachers): list + detail + form"
```

---

## Task 16: TokensListPage + TokenDetailPage + TokenFormModal (с генератором)

**Files:**
- Modify: `web/admin/src/pages/tokens/TokensListPage.tsx`
- Modify: `web/admin/src/pages/tokens/TokenDetailPage.tsx`
- Create: `web/admin/src/pages/tokens/TokenFormModal.tsx`

- [ ] **Step 1: TokensListPage**

```tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTokens } from '../../hooks/useTokens';
import { useTeachers } from '../../hooks/useTeachers';
import { DataTable, type Column } from '../../components/table/DataTable';
import { Avatar } from '../../components/Avatar';
import { EntityLink } from '../../components/EntityLink';
import { MonoBadge } from '../../components/ui/MonoBadge';
import { TableSkeleton } from '../../components/ui/Skeleton';
import type { Token } from '../../lib/types';
import TokenFormModal from './TokenFormModal';

export default function TokensListPage() {
  const { data, isLoading } = useTokens();
  const { data: teachers = [] } = useTeachers(true);
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);

  if (isLoading) return <TableSkeleton rows={6} cols={4} />;
  const rows: Token[] = data || [];

  const columns: Column<Token>[] = [
    { key: 'token', label: 'Токен', searchable: true,
      cell: (r) => <MonoBadge value={r.token} active={r.active} /> },
    { key: 'teacher_id', label: 'Препод-ID', cell: (r) => `#${r.teacher_id}` },
    { key: 'teacher_name', label: 'Преподаватель', searchable: true,
      cell: (r) => {
        const t = teachers.find((x) => x.id === r.teacher_id);
        const name = r.teacher_name || t?.name || '';
        if (!name) return '—';
        return (
          <div className="person-cell">
            <Avatar name={name} size={26} />
            <EntityLink section="teachers" id={r.teacher_id} text={name} />
          </div>
        );
      }},
    { key: 'active', label: 'Статус',
      cell: (r) => r.active
        ? <span className="badge badge--ok">Активен</span>
        : <span className="badge badge--muted">Отозван</span> },
  ];

  return (
    <>
      <DataTable<Token>
        data={rows}
        columns={columns}
        title="Токены доступа"
        onRowClick={(row) => navigate(`/admin/tokens/${encodeURIComponent(row.token)}`)}
        headerActions={<button className="btn-add" onClick={() => setModalOpen(true)}>+ Новый</button>}
      />
      {modalOpen && (
        <TokenFormModal initial={null} onClose={() => setModalOpen(false)} />
      )}
    </>
  );
}
```

- [ ] **Step 2: TokenDetailPage**

```tsx
import { useState } from 'react';
import { useParams, Navigate, useNavigate } from 'react-router-dom';
import { useTokens, useTokenMutations } from '../../hooks/useTokens';
import { useTeachers } from '../../hooks/useTeachers';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { DetailShell, type DetailField } from '../../components/detail/DetailShell';
import { EntityLink } from '../../components/EntityLink';
import { PageLoading } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import type { Token } from '../../lib/types';
import TokenFormModal from './TokenFormModal';

export default function TokenDetailPage() {
  const params = useParams();
  const tokenStr = params.id || '';
  const navigate = useNavigate();
  const { data: tokens = [], isLoading } = useTokens(true);
  const { data: teachers = [] } = useTeachers(true);
  const muts = useTokenMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [editing, setEditing] = useState(false);

  if (isLoading) return <PageLoading />;
  const token = tokens.find((t) => t.token === tokenStr);
  if (!token) return <Navigate to="/admin/tokens" replace />;

  const teacher = teachers.find((t) => t.id === token.teacher_id);
  const teacherName = token.teacher_name || teacher?.name || '';

  const fields: DetailField<Token>[] = [
    { key: 'token', label: 'Токен' },
    { key: 'teacher_id', label: 'ID преподавателя' },
    { key: 'teacher_name', label: 'Преподаватель',
      cell: () => <EntityLink section="teachers" id={token.teacher_id} text={teacherName} /> },
    { key: 'active', label: 'Статус', cell: (r) => r.active ? 'Активен' : 'Отозван' },
    { key: 'created_at', label: 'Создан', cell: (r) => fmtDate(r.created_at) },
  ];

  const handleDelete = async () => {
    try {
      await muts.remove.mutateAsync(token.token);
      toast('Отозвано', 'ok');
      navigate('/admin/tokens');
    } catch (err) { showError(err); }
  };

  return (
    <>
      <DetailShell<Token>
        title={token.token}
        subtitle={`Преподаватель: ${teacherName || `#${token.teacher_id}`}`}
        row={token}
        fields={fields}
        cardTitle="Данные токена"
        onEdit={() => setEditing(true)}
        onDelete={handleDelete}
        deleteLabel="Отозвать"
        backTo="/admin/tokens"
      />
      {editing && (
        <TokenFormModal initial={token} onClose={() => setEditing(false)} />
      )}
    </>
  );
}
```

- [ ] **Step 3: TokenFormModal**

```tsx
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTokenMutations } from '../../hooks/useTokens';
import { useTeachers } from '../../hooks/useTeachers';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { TextInput } from '../../components/form/TextInput';
import { SelectInput } from '../../components/form/SelectInput';
import { Checkbox } from '../../components/form/Checkbox';
import type { Token } from '../../lib/types';

interface Props { initial: Token | null; onClose: () => void; }

export default function TokenFormModal({ initial, onClose }: Props) {
  const isNew = !initial;
  const navigate = useNavigate();
  const muts = useTokenMutations();
  const { data: teachers = [] } = useTeachers(true);
  const { toast } = useToast();
  const showError = useApiError();
  const [tokenStr, setTokenStr] = useState(initial?.token || '');
  const [teacherId, setTeacherId] = useState<string>(initial?.teacher_id ? String(initial.teacher_id) : '');
  const [active, setActive] = useState(initial?.active ?? true);

  const teacherOptions = [{ value: '', label: '— выберите —' }, ...teachers
    .filter((t) => t.active || (initial && initial.teacher_id === t.id))
    .map((t) => ({ value: t.id, label: t.name }))];

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!teacherId) {
      toast('Выберите преподавателя', 'error');
      return;
    }
    try {
      if (isNew) {
        const created = await muts.create.mutateAsync({ token: tokenStr, teacher_id: Number(teacherId) });
        toast('Создано', 'ok');
        onClose();
        navigate(`/admin/tokens/${encodeURIComponent(created.token)}`);
      } else {
        await muts.update.mutateAsync({
          token: initial!.token,
          body: { teacher_id: Number(teacherId), active },
        });
        toast('Сохранено', 'ok');
        onClose();
      }
    } catch (err) { showError(err); }
  };

  const handleGenerate = async () => {
    try {
      const r = await muts.generate.mutateAsync();
      setTokenStr(r.token);
    } catch (err) { showError(err); }
  };

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={isNew ? 'Новый токен' : `Токен: ${initial!.token}`}
      footer={
        <button type="submit" form="token-form" className="btn-primary"
          disabled={muts.create.isPending || muts.update.isPending}>Сохранить</button>
      }
    >
      <form id="token-form" onSubmit={onSubmit}>
        <Field label="Строка токена" required>
          <TextInput required value={tokenStr} onChange={(e) => setTokenStr(e.target.value)}
            placeholder="XXX-XXX-XXX" disabled={!isNew} />
          {isNew && (
            <button type="button" className="btn-secondary" style={{ marginTop: 6 }}
              onClick={() => { void handleGenerate(); }}
              disabled={muts.generate.isPending}
            >Сгенерировать</button>
          )}
        </Field>
        <Field label="Преподаватель" required>
          <SelectInput required value={teacherId} onChange={(e) => setTeacherId(e.target.value)} options={teacherOptions} />
        </Field>
        {!isNew && (
          <Field label="Активен">
            <Checkbox checked={active} onChange={(e) => setActive(e.target.checked)} />
          </Field>
        )}
      </form>
    </Dialog>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add web/admin/src/pages/tokens
git commit -m "r2(tokens): list + detail + form with generator"
```

---

## Task 17: DirectionsListPage (grid) + DirectionDetailPage + DirectionFormModal

**Files:**
- Modify: `web/admin/src/pages/directions/DirectionsListPage.tsx`
- Modify: `web/admin/src/pages/directions/DirectionDetailPage.tsx`
- Create: `web/admin/src/pages/directions/DirectionFormModal.tsx`

- [ ] **Step 1: DirectionsListPage**

```tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDirections } from '../../hooks/useDirections';
import { useGroups } from '../../hooks/useGroups';
import { EmptyState } from '../../components/ui/EmptyState';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { directionColor } from '../../lib/direction-color';
import DirectionFormModal from './DirectionFormModal';

export default function DirectionsListPage() {
  const { data, isLoading } = useDirections();
  const { data: groups = [] } = useGroups(true);
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);

  if (isLoading) return <TableSkeleton rows={4} cols={4} />;
  const rows = (data || []).filter((r) => r.active);

  return (
    <>
      <div className="section-header">
        <span className="section-title">Направления</span>
        <span className="count-badge">{rows.length}</span>
        <div className="section-actions">
          <button className="btn-add" onClick={() => setModalOpen(true)}>+ Новое</button>
        </div>
      </div>
      {rows.length === 0 ? (
        <EmptyState>Нет активных направлений. Создайте первое через «+ Новое».</EmptyState>
      ) : (
        <div className="dir-grid">
          {rows.map((d) => {
            const color = directionColor(d);
            const cnt = groups.filter((g) => g.direction_id === d.id && g.active).length;
            return (
              <div
                key={d.id}
                className="dir-card"
                tabIndex={0}
                role="button"
                style={{
                  borderColor: `${color}33`,
                  background: `linear-gradient(135deg, ${color}0d, transparent 60%), var(--bg3)`,
                }}
                onClick={() => navigate(`/admin/directions/${d.id}`)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(`/admin/directions/${d.id}`); } }}
              >
                <div className="dir-card-color" style={{ background: color }} />
                <div className="dir-card-name" style={{ color }}>
                  {d.name}
                  {d.is_individual && <span className="dir-card-mark" title="Индивидуальное">∙ Индив</span>}
                </div>
                <div className="dir-card-count">{cnt}</div>
                <div className="dir-card-sub">активных групп</div>
                {d.total_lessons != null && (
                  <div className="dir-card-meta">{d.total_lessons} уроков</div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {modalOpen && (
        <DirectionFormModal initial={null} onClose={() => setModalOpen(false)} />
      )}
    </>
  );
}
```

- [ ] **Step 2: DirectionDetailPage**

```tsx
import { useState } from 'react';
import { useParams, Navigate, useNavigate } from 'react-router-dom';
import { useDirection, useDirectionMutations } from '../../hooks/useDirections';
import { useGroups } from '../../hooks/useGroups';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { DetailShell, type DetailField } from '../../components/detail/DetailShell';
import { PageLoading } from '../../components/ui/Skeleton';
import { directionColor } from '../../lib/direction-color';
import type { Direction } from '../../lib/types';
import DirectionFormModal from './DirectionFormModal';

export default function DirectionDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const navigate = useNavigate();
  const { data: direction, isLoading } = useDirection(id);
  const { data: groups = [] } = useGroups();
  const muts = useDirectionMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [editing, setEditing] = useState(false);

  if (isLoading) return <PageLoading />;
  if (!direction) return <Navigate to="/admin/directions" replace />;

  const color = directionColor(direction);
  const myGroups = groups.filter((g) => g.direction_id === direction.id && g.active);

  const fields: DetailField<Direction>[] = [
    { key: 'id', label: 'ID' },
    { key: 'name', label: 'Название' },
    { key: 'sheet_name', label: 'Имя листа в Sheets' },
    { key: 'is_individual', label: 'Индивидуальное', cell: (r) => r.is_individual ? 'да' : 'нет' },
    { key: 'total_lessons', label: 'Уроков на направление',
      cell: (r) => r.total_lessons == null ? '—' : String(r.total_lessons) },
    { key: 'color', label: 'Цвет',
      cell: (r) => r.color ? (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10, fontFamily: "'JetBrains Mono',monospace", fontSize: 12.5 }}>
          <span style={{ width: 18, height: 18, borderRadius: 5, background: r.color, border: '1px solid var(--border)' }} />
          {r.color}
        </span>
      ) : <span style={{ color: 'var(--text3)' }}>— не задан —</span> },
    { key: 'active', label: 'Статус', cell: (r) => r.active ? 'Активен' : 'Архив' },
  ];

  const handleDelete = async () => {
    try {
      await muts.remove.mutateAsync(direction.id);
      toast('Архивировано', 'ok');
      navigate('/admin/directions');
    } catch (err) { showError(err); }
  };

  return (
    <>
      <DetailShell<Direction>
        title={direction.name}
        subtitle={`Лист: ${direction.sheet_name}`}
        row={direction}
        fields={fields}
        cardTitle="Данные направления"
        onEdit={() => setEditing(true)}
        onDelete={handleDelete}
        backTo="/admin/directions"
      >
        <div className="sub-header">Группы <span className="count-badge">{myGroups.length}</span></div>
        {myGroups.length === 0 ? (
          <div className="memberships__empty">Нет активных групп</div>
        ) : myGroups.map((g) => (
          <div
            key={g.id}
            className="link-card"
            tabIndex={0}
            role="button"
            onClick={() => navigate(`/admin/groups/${g.id}`)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(`/admin/groups/${g.id}`); } }}
          >
            <div className="link-card-head">
              <div>
                <div className="link-card-title">{g.name}</div>
                <div className="link-card-meta">
                  <span style={{ fontSize: 11, color: 'var(--text3)' }}>
                    {g.lesson_duration_minutes} мин · {g.lessons_per_week}×/нед
                  </span>
                </div>
              </div>
              <span style={{ fontSize: 11, color: 'var(--text3)' }}>#{g.id}</span>
            </div>
          </div>
        ))}
        <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text3)' }}>
          Цветовой акцент: <span style={{ color }}>{color}</span>
        </div>
      </DetailShell>
      {editing && (
        <DirectionFormModal initial={direction} onClose={() => setEditing(false)} />
      )}
    </>
  );
}
```

- [ ] **Step 3: DirectionFormModal**

```tsx
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDirectionMutations } from '../../hooks/useDirections';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { TextInput } from '../../components/form/TextInput';
import { NumberInput } from '../../components/form/NumberInput';
import { Checkbox } from '../../components/form/Checkbox';
import { ColorInput } from '../../components/form/ColorInput';
import type { Direction } from '../../lib/types';

interface Props { initial: Direction | null; onClose: () => void; }

export default function DirectionFormModal({ initial, onClose }: Props) {
  const isNew = !initial;
  const navigate = useNavigate();
  const muts = useDirectionMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [name, setName] = useState(initial?.name || '');
  const [sheetName, setSheetName] = useState(initial?.sheet_name || '');
  const [totalLessons, setTotalLessons] = useState<string>(
    initial?.total_lessons != null ? String(initial.total_lessons) : '',
  );
  const [color, setColor] = useState(initial?.color || '#0d9488');
  const [isIndividual, setIsIndividual] = useState(initial?.is_individual || false);
  const [active, setActive] = useState(initial?.active ?? true);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const body: Partial<Direction> = {
      name,
      sheet_name: sheetName,
      total_lessons: totalLessons === '' ? null : Number(totalLessons),
      color: color || null,
      is_individual: isIndividual,
    };
    if (!isNew) body.active = active;

    try {
      if (isNew) {
        const created = await muts.create.mutateAsync(body);
        toast('Создано', 'ok');
        onClose();
        navigate(`/admin/directions/${created.id}`);
      } else {
        await muts.update.mutateAsync({ id: initial!.id, body });
        toast('Сохранено', 'ok');
        onClose();
      }
    } catch (err) { showError(err); }
  };

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={isNew ? 'Новое направление' : `Редактировать: ${initial!.name}`}
      footer={
        <button type="submit" form="direction-form" className="btn-primary"
          disabled={muts.create.isPending || muts.update.isPending}>Сохранить</button>
      }
    >
      <form id="direction-form" onSubmit={onSubmit}>
        <Field label="Название" required>
          <TextInput required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Имя листа в Sheets" required>
          <TextInput required value={sheetName} onChange={(e) => setSheetName(e.target.value)} />
        </Field>
        <Field label="Уроков на направление">
          <NumberInput min={0} value={totalLessons} onChange={(e) => setTotalLessons(e.target.value)} placeholder="например, 36" />
        </Field>
        <Field label="Цвет направления">
          <ColorInput value={color} onChange={(e) => setColor(e.target.value)} />
        </Field>
        <Field label="Индивидуальное">
          <Checkbox checked={isIndividual} onChange={(e) => setIsIndividual(e.target.checked)} />
        </Field>
        {!isNew && (
          <Field label="Активен">
            <Checkbox checked={active} onChange={(e) => setActive(e.target.checked)} />
          </Field>
        )}
      </form>
    </Dialog>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add web/admin/src/pages/directions
git commit -m "r2(directions): grid list + detail + form with color picker"
```

---

## Task 18: ArchivePage (4 секции)

**Files:**
- Modify: `web/admin/src/pages/archive/ArchivePage.tsx`

- [ ] **Step 1: ArchivePage**

```tsx
import { useNavigate } from 'react-router-dom';
import { useArchive } from '../../hooks/useArchive';
import { useQueryClient } from '@tanstack/react-query';
import { useToast } from '../../components/ui/Toast';
import { MonoBadge } from '../../components/ui/MonoBadge';
import { EntityLink } from '../../components/EntityLink';
import { TableSkeleton } from '../../components/ui/Skeleton';
import type { Teacher, Group, Direction, Token } from '../../lib/types';

export default function ArchivePage() {
  const { data, isLoading } = useArchive();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();

  if (isLoading) return <TableSkeleton rows={3} cols={4} />;
  if (!data) return null;

  return (
    <>
      <div className="section-header">
        <span className="section-title">Архив</span>
        <div className="section-actions">
          <button
            className="btn-secondary"
            onClick={() => {
              qc.invalidateQueries({ queryKey: ['archive'] });
              toast('Архив обновлён', 'ok');
            }}
          >↻ Обновить</button>
        </div>
      </div>

      <ArchiveSection
        label="Преподаватели"
        headers={['ID', 'Имя', 'Email']}
        rows={data.teachers}
        renderRow={(r: Teacher) => (
          <tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/admin/teachers/${r.id}`)}>
            <td className="id-cell">#{r.id}</td>
            <td>{r.name}</td>
            <td style={{ color: 'var(--text3)' }}>{r.email || '—'}</td>
          </tr>
        )}
      />
      <ArchiveSection
        label="Группы"
        headers={['ID', 'Название']}
        rows={data.groups}
        renderRow={(r: Group) => (
          <tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/admin/groups/${r.id}`)}>
            <td className="id-cell">#{r.id}</td>
            <td>{r.name}</td>
          </tr>
        )}
      />
      <ArchiveSection
        label="Направления"
        headers={['ID', 'Название', 'Лист']}
        rows={data.directions}
        renderRow={(r: Direction) => (
          <tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/admin/directions/${r.id}`)}>
            <td className="id-cell">#{r.id}</td>
            <td>{r.name}</td>
            <td style={{ color: 'var(--text3)' }}>{r.sheet_name || '—'}</td>
          </tr>
        )}
      />
      <ArchiveSection
        label="Токены"
        headers={['Токен', 'Преподаватель']}
        rows={data.tokens}
        renderRow={(r: Token) => (
          <tr key={r.token} style={{ cursor: 'pointer' }} onClick={() => navigate(`/admin/tokens/${encodeURIComponent(r.token)}`)}>
            <td><MonoBadge value={r.token} active={false} /></td>
            <td><EntityLink section="teachers" id={r.teacher_id} text={r.teacher_name || '—'} /></td>
          </tr>
        )}
      />
    </>
  );
}

interface SectionProps<T> {
  label: string;
  headers: string[];
  rows: T[];
  renderRow: (r: T) => React.ReactNode;
}

function ArchiveSection<T>({ label, headers, rows, renderRow }: SectionProps<T>) {
  return (
    <div className="archive-section">
      <div className="archive-section__head">
        {label}<span className="archive-section__count">{rows.length}</span>
      </div>
      {rows.length === 0 ? (
        <div className="archive-section__empty" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, color: 'var(--text3)', fontSize: 12, padding: 20 }}>
          Нет архивированных записей
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr>{headers.map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>{rows.map(renderRow)}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
npm run admin:typecheck 2>&1 | tail -3
npm run admin:build 2>&1 | tail -6
```

- [ ] **Step 3: Commit**

```bash
git add web/admin/src/pages/archive/ArchivePage.tsx
git commit -m "r2(archive): 4 sections with navigation to detail"
```

---

# Финальная фаза — verification + cleanup

## Task 19: Удалить устаревшие R1 stub-файлы (если остались)

- [ ] **Step 1: Проверить что R1 stub-файлы заменены**

```bash
grep -r "R2 in progress" web/admin/src/pages 2>&1 | head -5
```

Expected: пусто. Если найдены — это пропущенная страница, доделать.

- [ ] **Step 2: Проверить отсутствие mentions старого подхода**

```bash
grep -rn "state.cache" web/admin/src 2>&1 | head -5
grep -rn "state\.cache" web/admin/src 2>&1 | head -5
```

Expected: пусто.

## Task 20: Production build + bundle size

- [ ] **Step 1: Production build**

```bash
npm run admin:build 2>&1 | tail -10
```

Expected: build successful. Если bundle > 280 КБ gzipped — рассмотреть `lazy(() => import(...))` для detail-страниц (не делать в этой задаче — записать в backlog).

- [ ] **Step 2: Backend тесты**

```bash
npm test 2>&1 | tail -3
```

Expected: 77/77 passed (backend не трогали).

## Task 21: Browser smoke (полный CRUD по всем сущностям)

- [ ] **Step 1: Запустить сервер**

```bash
npm start &
# Подождать `Server listening on port 3000`
```

- [ ] **Step 2: Открыть /admin в браузере, залогиниться**

- [ ] **Step 3: По каждой сущности проверить:**

| Сущность | Действие | Ожидание |
|---|---|---|
| Students | List → row click → detail | KOTOKOD hero, stats, memberships появляются |
| Students | Edit → frozen + месяц → save | enrollment_status=frozen, memberships удалены |
| Students | Add new → save | новый ученик в списке без перезагрузки |
| Groups | Detail → клик по квадрату lesson grid | LessonEditor открывается ниже грида |
| Groups | LessonEditor → save | квадрат раскрашивается, members обновляется |
| Groups | LessonEditor → delete | квадрат гасится, payroll исчезает |
| Groups | Memberships add → save | карточка появляется |
| Teachers | Detail → видны tokens, groups | Карточки рендерятся, клики переходят |
| Tokens | Add → «Сгенерировать» | поле автозаполняется XXX-XXX-XXX |
| Tokens | Detail → Отозвать | возврат на список, статус «Отозван» |
| Directions | List → grid из карточек, не таблица | dir-color работает |
| Directions | Edit → ColorInput | сохраняется hex |
| Lessons | List → row click → detail | attendance toggle сохраняется на blur |
| Lessons | Detail → payroll edit поле | onBlur срабатывает, toast «Сохранено» |
| Payroll | List → toggle Summary | переключение режимов работает |
| Payroll | Summary → date range | Запросы перестраиваются, totals считаются |
| Archive | список 4 секций | клик переводит на detail |
| Theme | toggle dark/light | работает, persist между перезагрузками |
| Logout | кнопка | возврат на /login |
| Direct URL `/admin/groups/123` | refresh | страница загружается напрямую |

- [ ] **Step 4: 401 handling**

Удалить cookie вручную из DevTools, кликнуть по любой ссылке → перенаправление на /login.

## Task 22: Финальный commit + обновить CLAUDE.md

- [ ] **Step 1: Обновить CLAUDE.md**

Найти секцию таблицы фаз и добавить:
```
| Phase R2 — Admin SPA на React + TanStack Query | ✅ |
```

В разделе "Структура" обновить описание `web/admin/src/` под новый layout (pages/<entity>/, hooks/, providers/).

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: mark R2 React migration complete in CLAUDE.md"
```

---

## Acceptance criteria

R2 готов когда:

1. ✓ `npm run admin:typecheck` — 0 errors
2. ✓ `npm run admin:build` — успех, bundle < 300 КБ gzipped
3. ✓ `npm test` — 77/77 backend tests passing
4. ✓ Все 8 сущностей: list + detail + form работают, mutations инвалидируют кеш
5. ✓ Lesson grid + LessonEditor функциональны, payroll создаётся при создании урока
6. ✓ Auto-freeze для students работает (frozen → DELETE memberships)
7. ✓ Token generator кнопка работает, MonoBadge отображается
8. ✓ DirectionsListPage рисуется как grid (НЕ таблица)
9. ✓ Archive показывает 4 секции, клик переводит на detail
10. ✓ Theme toggle, scroll-top, logout работают
11. ✓ Прямой URL на detail (например, `/admin/groups/123` после refresh) загружается
12. ✓ Нет упоминаний `state.cache` или старого подхода в `web/admin/src/`
13. ✓ CLAUDE.md обновлён

Backup в `_backup-pre-r1/` остаётся до завершения R3 cleanup.
