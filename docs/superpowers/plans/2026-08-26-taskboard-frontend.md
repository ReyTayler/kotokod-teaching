# Раздел «Задачи» — фронтенд (этапы 4–5). План реализации

> **Для исполнителя:** ОБЯЗАТЕЛЬНАЯ ПОД-СКИЛЛ: используй `superpowers:subagent-driven-development`
> (рекомендуется) или `superpowers:executing-plans` для выполнения задача-за-задачей.
> Шаги помечены чекбоксами (`- [ ]`).

**Цель:** раздел «Задачи» в admin SPA — доска с перетаскиванием, панель справа,
вид «Неделя», настройка воронок и стадий, блок задач на странице ученика.

**Архитектура:** React 19 + TanStack Query v5 + React Router v7. Данные — через
существующий помощник `api()` из `lib/api.ts`. Перетаскивание — `@dnd-kit/core`,
уже стоящий в проекте и используемый доской продлений. Доска не грузится одним
запросом: колонки со счётчиками отдельным запросом, карточки каждой колонки —
своим пагинированным.

**Стек:** TypeScript, `@tanstack/react-query`, `@dnd-kit/core`, Vite.

**Бэкенд:** готов и покрыт 146 тестами. Спека — `docs/superpowers/specs/2026-08-24-taskboard-design.md`,
план бэкенда — `docs/superpowers/plans/2026-08-24-taskboard-backend.md`.

---

## Правила проекта, обязательные к соблюдению

1. **Коммиты — только по явной просьбе владельца.** Шаги «Коммит» содержат готовые
   команды, но выполнять их можно только с разрешения.
2. **НИКОГДА не запускать `npm run build`.** Он пишет в `../admin-dist` и засоряет
   рабочее дерево собранными файлами. Проверка типов — только
   `npm run typecheck` (`tsc --noEmit`) из `journal_django/frontend/admin-src`.
3. **Нативные form-элементы запрещены.** Только `SelectInput`, `DateInput`,
   `Checkbox`, `Combobox`, `TextInput`, `Textarea`, `NumberInput`, `ColorInput`
   из `components/form/`.
4. **Подписи перечислений — только из `lib/labels.ts`.** Никаких строк в JSX.
5. **Цвета, радиусы, отступы — только через токены** `styles/tokens.css`.
   Хардкод цветов — блокер.
6. **`placeholderData: keepPreviousData`** во всех серверно-пагинированных хуках.
7. **`.data-table--loading`** гасит `pointer-events` только на `tbody`.
8. **Проверка ролей** — компонентом `RequireRole` в маршруте, не внутри страницы.

## Контракт бэкенда — что уже есть

База `/api/admin/tasks`. Все ответы списков — конверт проекта
`{rows, total, page, page_size}` (тип `Paginated<T>` в `lib/shared-types.ts`).

```
GET    /api/admin/tasks                      список (фильтры + пагинация)
POST   /api/admin/tasks                      создать
GET    /api/admin/tasks/assignees            справочник исполнителей
GET    /api/admin/tasks/boards               воронки
POST   /api/admin/tasks/boards               создать воронку        (superadmin)
PATCH  /api/admin/tasks/boards/<id>          правка/архивирование   (superadmin)
DELETE /api/admin/tasks/boards/<id>          удалить                (superadmin)
GET    /api/admin/tasks/boards/<id>/columns  колонки со счётчиками (без карточек)
GET    /api/admin/tasks/boards/<id>/stages   стадии воронки
POST   /api/admin/tasks/boards/<id>/stages   создать стадию         (superadmin)
PATCH  /api/admin/tasks/stages/<id>          правка стадии          (superadmin)
DELETE /api/admin/tasks/stages/<id>          удалить стадию         (superadmin)
POST   /api/admin/tasks/stages/reorder       порядок колонок        (superadmin)
GET    /api/admin/tasks/columns/<stage_id>   карточки колонки (пагинация)
GET    /api/admin/tasks/week?date_from=&date_to=[&фильтры]   недельный вид
GET    /api/admin/tasks/tags                 теги
POST   /api/admin/tasks/tags                 создать тег            (superadmin)
PATCH  /api/admin/tasks/tags/<id>            переименовать          (superadmin)
DELETE /api/admin/tasks/tags/<id>            удалить                (superadmin)
GET    /api/admin/tasks/types                типы
POST|PATCH|DELETE /api/admin/tasks/types[/<id>]                     (superadmin)
GET    /api/admin/tasks/<pk>                 карточка
PATCH  /api/admin/tasks/<pk>                 правка полей и тегов
DELETE /api/admin/tasks/<pk>                 удалить                (admin)
POST   /api/admin/tasks/<pk>/move            перенос в стадию
POST   /api/admin/tasks/<pk>/complete        кнопка «Выполнено»
POST   /api/admin/tasks/<pk>/comment         комментарий → созданная запись
GET    /api/admin/tasks/<pk>/activity        лента
```

Фильтры списка и недельного вида: `board_id`, `stage_id`, `assignee_id`,
`student_id`, `group_id`, `priority`, `task_type_id`, `tag_id`, `only_open`,
`overdue`, `q`. Некорректное значение даёт 400, не 500.

**Коды конфликтов (409)** приходят как `{error: '...'}` и попадают в
`ApiError.message` — так же, как их читают продления
(`const code = err instanceof ApiError ? err.message : undefined`):

| Код | Когда |
|---|---|
| `has_tasks` | удалить воронку/стадию с задачами; сменить категорию стадии с задачами |
| `last_stage_of_category` | удалить последнюю открытую или последнюю закрытую стадию |
| `duplicate_name` / `duplicate_label` | название воронки/стадии/тега/типа занято |
| `stages_from_different_boards` | переупорядочивание стадий разных воронок (400) |
| `incomplete_stage_set` | переупорядочивание неполным набором стадий (400) |

## Структура файлов

| Файл | Ответственность |
|---|---|
| `src/lib/tasks.ts` | типы раздела, разбор кодов конфликтов |
| `src/hooks/useTasks.ts` | запросы и мутации карточек |
| `src/hooks/useTaskStructure.ts` | воронки, стадии, теги, типы, исполнители |
| `src/pages/tasks/TasksPage.tsx` | страница: выбор воронки, переключатель вида, фильтры |
| `src/pages/tasks/TaskBoard.tsx` | доска: колонки, перетаскивание |
| `src/pages/tasks/TaskColumn.tsx` | колонка: счётчик, быстрое добавление, «Показать ещё» |
| `src/pages/tasks/TaskCard.tsx` | карточка на доске |
| `src/pages/tasks/TaskDrawer.tsx` | панель справа: просмотр, правка, лента |
| `src/pages/tasks/TaskCompleteDialog.tsx` | выбор результата при закрытии |
| `src/pages/tasks/TaskWeekView.tsx` | вид «Неделя» |
| `src/pages/tasks/TaskStagesSettings.tsx` | настройка воронок и стадий |
| `src/components/detail/StudentTasksBlock.tsx` | блок задач на странице ученика |
| `src/styles/pages/tasks.css` | стили раздела |

Разнесение повторяет `src/pages/renewals/` — установленный паттерн проекта.

---

## Задача 1: Типы, подписи и хуки чтения

**Файлы:**
- Создать: `journal_django/frontend/admin-src/src/lib/tasks.ts`
- Создать: `journal_django/frontend/admin-src/src/hooks/useTasks.ts`
- Создать: `journal_django/frontend/admin-src/src/hooks/useTaskStructure.ts`
- Изменить: `journal_django/frontend/admin-src/src/lib/labels.ts`

- [ ] **Шаг 1: Типы раздела**

Создать `src/lib/tasks.ts`:

```ts
export type TaskPriority = 'low' | 'normal' | 'high';
export type TaskResolution = 'done' | 'cancelled' | 'irrelevant';
export type StageCategory = 'open' | 'closed';

export interface TaskTag {
  id: number;
  label: string;
  color: string | null;
}

export interface TaskType {
  id: number;
  label: string;
}

export interface TaskAssignee {
  id: number;
  full_name: string | null;
  role: string;
}

export interface TaskBoard {
  id: number;
  name: string;
  description: string | null;
  sort_order: number;
  is_archived: boolean;
}

export interface TaskStage {
  id: number;
  board_id: number;
  label: string;
  color: string | null;
  category: StageCategory;
  sort_order: number;
}

/** Колонка доски: счётчик без карточек — доска не грузится одним запросом. */
export interface TaskColumnCount {
  stage_id: number;
  label: string;
  color: string | null;
  category: StageCategory;
  sort_order: number;
  count: number;
}

export interface TaskRow {
  id: number;
  board_id: number;
  stage_id: number;
  stage_label: string;
  stage_category: StageCategory;
  stage_color: string | null;
  title: string;
  description: string | null;
  assignee_id: number | null;
  assignee_name: string | null;
  created_by_id: number | null;
  created_by_name: string | null;
  student_id: number | null;
  student_name: string | null;
  group_id: number | null;
  group_name: string | null;
  task_type_id: number | null;
  task_type_label: string | null;
  tags: TaskTag[];
  due_date: string | null;
  priority: TaskPriority;
  resolution: TaskResolution | null;
  is_closed: boolean;
  is_overdue: boolean;
  closed_at: string | null;
  stage_entered_at: string;
  updated_at: string;
  created_at: string;
}

export interface TaskActivityItem {
  id: number;
  kind: 'stage_change' | 'assign' | 'comment' | 'system';
  author_id: number | null;
  author_name: string | null;
  text: string | null;
  meta: Record<string, unknown> | null;
  created_at: string;
}

export interface TaskFilters {
  board_id?: number;
  stage_id?: number;
  assignee_id?: number;
  student_id?: number;
  group_id?: number;
  priority?: TaskPriority;
  task_type_id?: number;
  tag_id?: number;
  only_open?: boolean;
  overdue?: boolean;
  q?: string;
}

/** Собрать query-строку, отбрасывая пустые значения. */
export function taskFilterQS(f: TaskFilters): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) {
    if (v === undefined || v === null || v === '' || v === false) continue;
    qs.set(k, String(v));
  }
  return qs.toString();
}
```

- [ ] **Шаг 2: Подписи перечислений**

Дописать в `src/lib/labels.ts` (найди, как оформлены соседние словари, и повтори
стиль — обычно это `Record<string, string>` с экспортируемой функцией-геттером):

```ts
export const TASK_PRIORITY_LABELS: Record<string, string> = {
  low: 'Низкий',
  normal: 'Обычный',
  high: 'Высокий',
};

export const TASK_RESOLUTION_LABELS: Record<string, string> = {
  done: 'Выполнено',
  cancelled: 'Отменено',
  irrelevant: 'Неактуально',
};

export const TASK_ACTIVITY_LABELS: Record<string, string> = {
  stage_change: 'Смена стадии',
  assign: 'Смена исполнителя',
  comment: 'Комментарий',
  system: 'Системная запись',
};

/** Человеческий текст для кодов конфликта раздела «Задачи» (приходят в ApiError.message). */
export const TASK_CONFLICT_LABELS: Record<string, string> = {
  has_tasks: 'В этой воронке или стадии есть задачи — сначала перенесите или закройте их',
  last_stage_of_category: 'Это последняя стадия своего вида: без неё воронка перестанет работать',
  duplicate_name: 'Такое название уже занято',
  duplicate_label: 'Такое название уже занято',
  stages_from_different_boards: 'Стадии разных воронок нельзя переставлять вместе',
  incomplete_stage_set: 'Передан неполный набор стадий воронки',
};
```

- [ ] **Шаг 3: Хуки структуры**

Создать `src/hooks/useTaskStructure.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type {
  TaskAssignee, TaskBoard, TaskColumnCount, TaskStage, TaskTag, TaskType,
} from '../lib/tasks';

const KEY = ['tasks'] as const;

export function useTaskBoards() {
  return useQuery({
    queryKey: [...KEY, 'boards'],
    queryFn: () => api<TaskBoard[]>('GET', '/api/admin/tasks/boards'),
    staleTime: 60_000,
  });
}

export function useTaskStages(boardId: number | undefined) {
  return useQuery({
    queryKey: [...KEY, 'stages', boardId],
    queryFn: () => api<TaskStage[]>('GET', `/api/admin/tasks/boards/${boardId}/stages`),
    enabled: boardId !== undefined,
    staleTime: 60_000,
  });
}

/** Колонки со счётчиками. Отдельно от карточек — доска не грузится одним запросом. */
export function useTaskColumns(boardId: number | undefined) {
  return useQuery({
    queryKey: [...KEY, 'columns', boardId],
    queryFn: () => api<TaskColumnCount[]>(
      'GET', `/api/admin/tasks/boards/${boardId}/columns`),
    enabled: boardId !== undefined,
    staleTime: 15_000,
  });
}

export function useTaskAssignees() {
  return useQuery({
    queryKey: [...KEY, 'assignees'],
    queryFn: () => api<TaskAssignee[]>('GET', '/api/admin/tasks/assignees'),
    staleTime: 300_000,
  });
}

export function useTaskTags() {
  return useQuery({
    queryKey: [...KEY, 'tags'],
    queryFn: () => api<TaskTag[]>('GET', '/api/admin/tasks/tags'),
    staleTime: 300_000,
  });
}

export function useTaskTypes() {
  return useQuery({
    queryKey: [...KEY, 'types'],
    queryFn: () => api<TaskType[]>('GET', '/api/admin/tasks/types'),
    staleTime: 300_000,
  });
}

/** Все мутации структуры доступны только суперадмину — маршрут закрыт RequireRole. */
export function useStageMutations(boardId: number | undefined) {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: [...KEY, 'stages', boardId] });
    qc.invalidateQueries({ queryKey: [...KEY, 'columns', boardId] });
  };
  return {
    create: useMutation({
      mutationFn: (body: { label: string; category: string; color?: string | null }) =>
        api<TaskStage>('POST', `/api/admin/tasks/boards/${boardId}/stages`, body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: { id: number; label?: string; category?: string; color?: string | null }) =>
        api<TaskStage>('PATCH', `/api/admin/tasks/stages/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<void>('DELETE', `/api/admin/tasks/stages/${id}`),
      onSuccess: invalidate,
    }),
    reorder: useMutation({
      // Бэкенд требует ПОЛНЫЙ набор стадий воронки — иначе 400 incomplete_stage_set.
      mutationFn: (order: number[]) =>
        api<TaskStage[]>('POST', '/api/admin/tasks/stages/reorder', { order }),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Шаг 4: Хуки карточек**

Создать `src/hooks/useTasks.ts`:

```ts
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Paginated } from '../lib/shared-types';
import type { TaskActivityItem, TaskFilters, TaskRow } from '../lib/tasks';
import { taskFilterQS } from '../lib/tasks';

const KEY = ['tasks'] as const;

/** Карточки одной колонки доски. page — 1-based, как в StandardPagination. */
export function useTaskColumnCards(stageId: number, filters: TaskFilters, page = 1) {
  return useQuery({
    queryKey: [...KEY, 'column-cards', stageId, filters, page],
    queryFn: () => api<Paginated<TaskRow>>(
      'GET', `/api/admin/tasks/columns/${stageId}?page=${page}&${taskFilterQS(filters)}`),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useTaskList(filters: TaskFilters, page = 1) {
  return useQuery({
    queryKey: [...KEY, 'list', filters, page],
    queryFn: () => api<Paginated<TaskRow>>(
      'GET', `/api/admin/tasks?page=${page}&${taskFilterQS(filters)}`),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useTaskWeek(dateFrom: string, dateTo: string, filters: TaskFilters) {
  return useQuery({
    queryKey: [...KEY, 'week', dateFrom, dateTo, filters],
    queryFn: () => api<TaskRow[]>(
      'GET',
      `/api/admin/tasks/week?date_from=${dateFrom}&date_to=${dateTo}&${taskFilterQS(filters)}`),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useTask(id: number | undefined) {
  return useQuery({
    queryKey: [...KEY, 'detail', id],
    queryFn: () => api<TaskRow>('GET', `/api/admin/tasks/${id}`),
    enabled: id !== undefined,
  });
}

export function useTaskActivity(id: number | undefined) {
  return useQuery({
    queryKey: [...KEY, 'activity', id],
    queryFn: () => api<TaskActivityItem[]>('GET', `/api/admin/tasks/${id}/activity`),
    enabled: id !== undefined,
  });
}

/** Мутации карточки. Сбрасываем и колонки, и счётчики — карточка могла сменить стадию. */
export function useTaskMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: KEY });
  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) =>
        api<TaskRow>('POST', '/api/admin/tasks', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: { id: number } & Record<string, unknown>) =>
        api<TaskRow>('PATCH', `/api/admin/tasks/${id}`, body),
      onSuccess: invalidate,
    }),
    move: useMutation({
      mutationFn: (v: { id: number; to_stage_id: number; resolution?: string }) =>
        api<TaskRow>('POST', `/api/admin/tasks/${v.id}/move`,
          { to_stage_id: v.to_stage_id, resolution: v.resolution }),
      onSuccess: invalidate,
    }),
    complete: useMutation({
      mutationFn: (v: { id: number; resolution: string }) =>
        api<TaskRow>('POST', `/api/admin/tasks/${v.id}/complete`, { resolution: v.resolution }),
      onSuccess: invalidate,
    }),
    comment: useMutation({
      mutationFn: (v: { id: number; body: string }) =>
        api<TaskActivityItem>('POST', `/api/admin/tasks/${v.id}/comment`, { body: v.body }),
      onSuccess: (_d, v) => {
        qc.invalidateQueries({ queryKey: [...KEY, 'activity', v.id] });
      },
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<void>('DELETE', `/api/admin/tasks/${id}`),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Шаг 5: Проверка типов**

```
cd journal_django/frontend/admin-src && npm run typecheck
```
Ожидаемо: без ошибок. **`npm run build` не запускать.**

- [ ] **Шаг 6: Коммит** (только с разрешения владельца)

```bash
git add journal_django/frontend/admin-src/src/lib/tasks.ts journal_django/frontend/admin-src/src/hooks/useTasks.ts journal_django/frontend/admin-src/src/hooks/useTaskStructure.ts journal_django/frontend/admin-src/src/lib/labels.ts
git commit -m "feat(tasks): типы, подписи и хуки раздела задач"
```

---

## Задача 2: Маршрут, пункт меню, каркас страницы

**Файлы:**
- Создать: `src/pages/tasks/TasksPage.tsx`
- Создать: `src/styles/pages/tasks.css`
- Изменить: `src/App.tsx`
- Изменить: `src/components/shell/navConfig.tsx`
- Изменить: `src/styles/` (точка подключения css — найди, где подключается `renewals.css`)

- [ ] **Шаг 1: Каркас страницы**

Создать `src/pages/tasks/TasksPage.tsx`. Страница держит выбранную воронку,
режим вида и фильтры; сами доска и неделя появятся в следующих задачах.

```tsx
import { useState } from 'react';
import PageHeader from '../../components/shell/PageHeader';
import SelectInput from '../../components/form/SelectInput';
import { useTaskBoards } from '../../hooks/useTaskStructure';
import type { TaskFilters } from '../../lib/tasks';

type ViewMode = 'board' | 'week';

export default function TasksPage() {
  const boards = useTaskBoards();
  const [boardId, setBoardId] = useState<number | undefined>(undefined);
  const [view, setView] = useState<ViewMode>('board');
  const [filters] = useState<TaskFilters>({});

  const active = (boards.data ?? []).filter((b) => !b.is_archived);
  const currentBoardId = boardId ?? active[0]?.id;

  return (
    <div className="page tasks-page">
      <PageHeader title="Задачи" />
      <div className="tasks-toolbar">
        <SelectInput
          label="Воронка"
          value={currentBoardId ? String(currentBoardId) : ''}
          onChange={(v) => setBoardId(Number(v))}
          options={active.map((b) => ({ value: String(b.id), label: b.name }))}
        />
        <div className="tasks-view-switch">
          <button
            type="button"
            className={view === 'board' ? 'is-active' : ''}
            onClick={() => setView('board')}
          >
            Доска
          </button>
          <button
            type="button"
            className={view === 'week' ? 'is-active' : ''}
            onClick={() => setView('week')}
          >
            Неделя
          </button>
        </div>
      </div>
      {currentBoardId === undefined
        ? <p className="tasks-empty">Нет ни одной воронки</p>
        : <p className="tasks-empty">Вид «{view}» появится в следующей задаче</p>}
    </div>
  );
}
```

**Важно:** проверь фактические пропсы `SelectInput` и `PageHeader` в их файлах и
подстрой вызовы под них — сигнатуры в проекте могли отличаться от показанных.

- [ ] **Шаг 2: Стили**

Создать `src/styles/pages/tasks.css`. Только токены, никаких hardcoded цветов:

```css
.tasks-toolbar {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
}

.tasks-view-switch {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.tasks-view-switch button {
  padding: var(--space-2) var(--space-3);
  background: var(--surface);
  color: var(--text-muted);
  border: 0;
  cursor: pointer;
}

.tasks-view-switch button.is-active {
  background: var(--accent-soft);
  color: var(--accent);
}

.tasks-empty {
  color: var(--text-muted);
}
```

Сверься с фактическими именами токенов в `src/styles/tokens.css` — если какого-то
из использованных выше нет, возьми существующий аналог. Токен, которого нет,
схлопнется молча и стиль просто не применится.

Подключи файл там же, где подключается `renewals.css`.

- [ ] **Шаг 3: Маршрут**

В `src/App.tsx` добавить импорт и маршруты рядом с маршрутами продлений:

```tsx
import TasksPage from './pages/tasks/TasksPage';
```

```tsx
<Route path="/admin/tasks" element={<RequireRole roles={['manager','admin','superadmin']}><TasksPage /></RequireRole>} />
```

- [ ] **Шаг 4: Пункт меню**

В `src/components/shell/navConfig.tsx` добавить пункт в группу «Учебная часть»
(там же, где «Продления»):

```tsx
      { key: 'tasks', label: 'Задачи', path: '/admin/tasks' },
```

Если для пункта нужна иконка — посмотри, как заведена иконка `renewals` в этом же
файле, и добавь по аналогии.

- [ ] **Шаг 5: Проверка**

```
cd journal_django/frontend/admin-src && npm run typecheck
```
Ожидаемо: без ошибок.

Затем вручную: запустить `npm run dev`, открыть `/admin/tasks`, убедиться, что
пункт меню виден, страница открывается, в выпадающем списке есть воронка
«Общие задачи», переключатель вида работает.

- [ ] **Шаг 6: Коммит** (только с разрешения)

```bash
git add journal_django/frontend/admin-src/src
git commit -m "feat(tasks): раздел в меню, маршрут и каркас страницы"
```

---

## Задача 3: Доска с колонками и перетаскиванием

**Файлы:**
- Создать: `src/pages/tasks/TaskBoard.tsx`, `TaskColumn.tsx`, `TaskCard.tsx`
- Изменить: `src/pages/tasks/TasksPage.tsx`, `src/styles/pages/tasks.css`

- [ ] **Шаг 1: Изучить образец**

Прочитай `src/pages/renewals/RenewalBoard.tsx` и `RenewalColumn.tsx` — там уже
решены `DndContext`, `useDroppable`, подсветка колонки при наведении и оптимистичный
перенос. Повтори тот же подход, не изобретая свой.

- [ ] **Шаг 2: Карточка**

Создать `src/pages/tasks/TaskCard.tsx`:

```tsx
import type { TaskRow } from '../../lib/tasks';
import { TASK_PRIORITY_LABELS } from '../../lib/labels';

interface Props {
  task: TaskRow;
  onOpen: (id: number) => void;
}

export default function TaskCard({ task, onOpen }: Props) {
  return (
    <button
      type="button"
      className={`task-card${task.is_closed ? ' task-card--closed' : ''}`}
      onClick={() => onOpen(task.id)}
    >
      <span className="task-card__num">#{task.id}</span>
      <span className="task-card__title">{task.title}</span>
      <span className="task-card__meta">
        {task.assignee_name && <span>{task.assignee_name}</span>}
        {task.due_date && (
          <span className={task.is_overdue ? 'task-card__due is-overdue' : 'task-card__due'}>
            {task.due_date}
          </span>
        )}
        {task.priority !== 'normal' && (
          <span className="task-card__priority">{TASK_PRIORITY_LABELS[task.priority]}</span>
        )}
      </span>
      {task.tags.length > 0 && (
        <span className="task-card__tags">
          {task.tags.map((t) => <span key={t.id} className="task-tag">{t.label}</span>)}
        </span>
      )}
    </button>
  );
}
```

Закрытая карточка рисуется зачёркнутым заголовком с галочкой — это делается
классом `task-card--closed` в css, как в WEEEK.

- [ ] **Шаг 3: Колонка**

Создать `src/pages/tasks/TaskColumn.tsx`. Колонка получает счётчик из
`useTaskColumns`, а карточки — своим пагинированным запросом
`useTaskColumnCards`, с кнопкой «Показать ещё» при `total > загружено`.
Вверху — поле быстрого добавления, создающее карточку одним заголовком
(`create.mutate({ board_id, title, stage_id })`).

- [ ] **Шаг 4: Доска**

Создать `src/pages/tasks/TaskBoard.tsx`: `DndContext` вокруг колонок,
`onDragEnd` вызывает `move.mutate`. **Если целевая стадия имеет
`category === 'closed'`, сначала показать диалог выбора результата** (задача 5) —
без результата бэкенд ответит 400.

- [ ] **Шаг 5: Проверка**

```
cd journal_django/frontend/admin-src && npm run typecheck
```

Вручную: карточки видны по колонкам, счётчики совпадают, перетаскивание между
открытыми колонками работает и переживает перезагрузку страницы.

- [ ] **Шаг 6: Коммит** (только с разрешения)

---

## Задача 4: Панель справа

**Файлы:** создать `src/pages/tasks/TaskDrawer.tsx`; изменить `TasksPage.tsx`, `tasks.css`.

- [ ] **Шаг 1: Изучить образец** — `src/pages/renewals/RenewalDrawer.tsx`.

- [ ] **Шаг 2: Панель**

Панель открывается по клику на карточку, показывает: номер и заголовок (правится
на месте), описание, исполнителя (`Combobox` по `useTaskAssignees`), ученика и
группу, срок (`DateInput`), приоритет и тип (`SelectInput`), теги (`Combobox`
множественный), «в стадии с» из `stage_entered_at`, постановщика из
`created_by_name`, ленту из `useTaskActivity` и поле комментария.

Правка полей уходит одним `update.mutate`; ответ мутации комментария уже содержит
созданную запись, так что перезапрашивать всю ленту не нужно.

- [ ] **Шаг 3: Проверка типов и ручная проверка.**

- [ ] **Шаг 4: Коммит** (только с разрешения)

---

## Задача 5: Закрытие задачи и быстрое добавление

**Файлы:** создать `src/pages/tasks/TaskCompleteDialog.tsx`; изменить `TaskDrawer.tsx`, `TaskBoard.tsx`, `TaskColumn.tsx`.

- [ ] **Шаг 1: Диалог результата**

`TaskCompleteDialog` на базе `components/ui/Dialog.tsx`: выбор результата из
`TASK_RESOLUTION_LABELS` и подтверждение.

- [ ] **Шаг 2: Кнопка «Выполнено»**

В панели справа — кнопка, открывающая диалог и вызывающая `complete.mutate`.
Она доступна из ЛЮБОЙ колонки: на бэкенде это действие, переносящее карточку в
первую закрытую стадию воронки, а не флаг.

- [ ] **Шаг 3: Закрытие перетаскиванием**

Перенос в колонку с `category === 'closed'` открывает тот же диалог и вызывает
`move.mutate` с выбранным результатом.

- [ ] **Шаг 4: Возврат в работу**

Перенос закрытой карточки в открытую колонку идёт без диалога — бэкенд сам
обнуляет результат и дату закрытия.

- [ ] **Шаг 5: Проверка типов и ручная проверка.**

- [ ] **Шаг 6: Коммит** (только с разрешения)

---

## Задача 6: Фильтр-бар

**Файлы:** изменить `TasksPage.tsx`, `tasks.css`.

- [ ] **Шаг 1:** Фильтры: исполнитель, ученик, приоритет, тег, «только открытые»,
«просроченные», поиск по заголовку. Все — компонентами из `components/form/`.

- [ ] **Шаг 2:** Значения фильтров держать в `searchParams`, чтобы состояние
переживало перезагрузку и делилось ссылкой. **Помни: `ErrorBoundary` должен иметь
`key={location.pathname}`, а не `key={location.key}`** — иначе каждый
`setSearchParams` ремонтирует поддерево и инпут теряет фокус.

- [ ] **Шаг 3:** Фильтры применяются и к доске, и к недельному виду — бэкенд
принимает их на обеих ручках.

- [ ] **Шаг 4: Проверка и коммит** (только с разрешения)

---

## Задача 7: Вид «Неделя»

**Файлы:** создать `src/pages/tasks/TaskWeekView.tsx`; изменить `TasksPage.tsx`, `tasks.css`.

- [ ] **Шаг 1:** Колонки — дни недели, карточка попадает в колонку по `due_date`.
Задачи без срока в этот вид не попадают — так решено в спеке.

- [ ] **Шаг 2:** Перелистывание недель стрелками. **Диапазон запроса не шире
62 дней** — бэкенд вернёт 400.

- [ ] **Шаг 3:** Переиспользовать `TaskCard` — карточка одна и та же.

- [ ] **Шаг 4: Проверка и коммит** (только с разрешения)

---

## Задача 8: Настройка воронок и стадий

**Файлы:** создать `src/pages/tasks/TaskStagesSettings.tsx`; изменить `App.tsx`, `navConfig.tsx`.

- [ ] **Шаг 1: Изучить образец** — `src/pages/renewals/RenewalStagesSettings.tsx`,
включая то, как он показывает конфликты: `const code = err instanceof ApiError ? err.message : undefined`.

- [ ] **Шаг 2:** Страница по маршруту `/admin/tasks/stages`, закрытая
`RequireRole roles={['superadmin']}`. Создание и переименование воронок,
архивирование, создание/переименование/удаление стадий с выбором категории и
цвета (`ColorInput`), переупорядочивание перетаскиванием.

- [ ] **Шаг 3:** Коды конфликтов показывать текстом из `TASK_CONFLICT_LABELS`.
Особенно важны `has_tasks` и `last_stage_of_category` — без понятного объяснения
пользователь не поймёт, почему стадия не удаляется.

- [ ] **Шаг 4:** Переупорядочивание отправляет **полный** набор стадий воронки —
неполный бэкенд отклонит с `incomplete_stage_set`.

- [ ] **Шаг 5: Проверка и коммит** (только с разрешения)

---

## Задача 9: Блок задач на странице ученика

**Файлы:** создать `src/components/detail/StudentTasksBlock.tsx`; изменить страницу ученика.

- [ ] **Шаг 1:** Блок запрашивает `useTaskList({ student_id })`, показывает
открытые списком, закрытые — под свёрткой.

- [ ] **Шаг 2:** Кнопка «Поставить задачу» создаёт карточку с уже заполненным
учеником.

- [ ] **Шаг 3:** Клик по задаче ведёт на `/admin/tasks` с открытой панелью —
идентификатор задачи класть в query-параметр.

- [ ] **Шаг 4: Проверка и коммит** (только с разрешения)

---

## Задача 10: Финальная проверка

- [ ] **Шаг 1: Проверка типов**

```
cd journal_django/frontend/admin-src && npm run typecheck
```
Ожидаемо: без ошибок.

- [ ] **Шаг 2: Проверка запрещённых практик**

```
cd journal_django/frontend/admin-src/src && grep -rn "<select\|<input type=\"date\"\|<input type=\"checkbox\"" pages/tasks/
```
Ожидаемо: пусто — нативные form-элементы в разделе запрещены.

```
cd journal_django/frontend/admin-src/src && grep -rnE "#[0-9a-fA-F]{6}" pages/tasks/ styles/pages/tasks.css
```
Ожидаемо: пусто — цвета только через токены. Единственное исключение — значения
цветов стадий, приходящие с бэкенда: они подставляются в `style`, а не в css.

- [ ] **Шаг 3: Ручная проверка в браузере**

Пройти сценарии: создать задачу быстрым добавлением; перетащить между колонками;
закрыть перетаскиванием в закрытую колонку с выбором результата; вернуть в работу;
поставить исполнителя и срок; оставить комментарий; отфильтровать по исполнителю;
переключиться на «Неделю»; завести стадию и переставить порядок; открыть страницу
ученика и увидеть его задачи.

- [ ] **Шаг 4: Убедиться, что в дереве нет собранных файлов**

```
git status --short journal_django/frontend/
```
Ожидаемо: только исходники в `admin-src/src`. Если появился `admin-dist` —
значит кто-то запустил `npm run build`; собранное коммитить нельзя.

- [ ] **Шаг 5: Коммит** (только с разрешения)
