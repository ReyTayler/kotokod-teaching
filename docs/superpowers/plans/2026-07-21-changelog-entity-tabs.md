# Журнал изменений на страницах группы и ученика — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить встроенную вкладку «История» на страницы группы и ученика в admin SPA, показывающую записи журнала изменений (changelog), относящиеся конкретно к этой сущности.

**Architecture:** Backend не меняется — существующий эндпоинт `GET /api/admin/changelog?filter[entity]=&filter[entity_id]=` уже фильтрует по сущности. Общие рендереры колонок выносятся из `ChangelogListPage.tsx` в переиспользуемый модуль; новый компактный компонент `EntityChangelogPanel` использует их вместе с существующими `useChangelogList`/`ChangelogDetailModal`. Модалка получает новый проп `readOnly` для скрытия кнопки отката в контексте встроенной вкладки.

**Tech Stack:** React 19, TypeScript, TanStack Query v5, React Router v7, Vite (`journal_django/frontend/admin-src/`). Нет unit-test раннера — верификация через `npm run typecheck`, `npm run build` и ручную проверку в браузере.

Спека: `docs/superpowers/specs/2026-07-21-changelog-entity-tabs-design.md`

---

### Task 1: Вынести общие рендереры колонок журнала

**Files:**
- Create: `journal_django/frontend/admin-src/src/components/changelog/columnRenderers.tsx`
- Modify: `journal_django/frontend/admin-src/src/pages/changelog/ChangelogListPage.tsx:1-58,97-165`

- [ ] **Step 1: Создать модуль с общими рендерерами**

Перенести без изменения поведения: `svgProps`, `ACTION_ICONS`, `actionIcon()`, `ROLE_SHORT`, и добавить две новые экспортируемые функции-обёртки для ячеек «Время» и «Кто», которые сейчас заинлайнены в колонках `ChangelogListPage`.

```tsx
// journal_django/frontend/admin-src/src/components/changelog/columnRenderers.tsx
import type { ReactElement } from 'react';
import { fmtDateTime, fmtDateTimeShort } from '../../lib/format';
import type { ChangelogOperation } from '../../lib/types';

// ─── Иконки действий (16px, по стилю NAV_ICONS) ──────────────────────────────

const svgProps = {
  width: 15, height: 15, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', strokeWidth: 1.8,
  strokeLinecap: 'round', strokeLinejoin: 'round',
} as const;

export const ACTION_ICONS: Record<string, ReactElement> = {
  move:   <svg {...svgProps}><polyline points="17 11 21 7 17 3"/><line x1="21" y1="7" x2="9" y2="7"/><polyline points="7 13 3 17 7 21"/><line x1="3" y1="17" x2="15" y2="17"/></svg>,
  create: <svg {...svgProps}><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  edit:   <svg {...svgProps}><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/></svg>,
  remove: <svg {...svgProps}><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>,
  done:   <svg {...svgProps}><polyline points="20 6 9 17 4 12"/></svg>,
  cancel: <svg {...svgProps}><circle cx="12" cy="12" r="10"/><line x1="4.9" y1="4.9" x2="19.1" y2="19.1"/></svg>,
  revert: <svg {...svgProps}><polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/></svg>,
  other:  <svg {...svgProps}><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>,
};

export function actionIcon(operation: string): ReactElement {
  if (operation === 'changelog.revert') return ACTION_ICONS.revert;
  if (operation === 'plan.reschedule' || operation.includes('schedule_change') ||
      operation === 'plan.permanent_change') return ACTION_ICONS.move;
  if (operation === 'plan.cancel') return ACTION_ICONS.cancel;
  if (operation === 'lesson.submit') return ACTION_ICONS.done;
  if (operation.endsWith('.create') || operation === 'plan.extra' ||
      operation === 'plan.generate' || operation === 'payment.create') return ACTION_ICONS.create;
  if (operation.endsWith('.delete')) return ACTION_ICONS.remove;
  if (operation.endsWith('.update') || operation.startsWith('plan.')) return ACTION_ICONS.edit;
  return ACTION_ICONS.other;
}

// ─── Роли по-русски (для колонки «Кто») ───────────────────────────────────────

export const ROLE_SHORT: Record<string, string> = {
  teacher: 'преподаватель',
  manager: 'менеджер',
  admin:   'админ',
};

// ─── Готовые ячейки для переиспользования в компактных списках ───────────────

export function TimeCell({ occurredAt }: { occurredAt: string }): ReactElement {
  return (
    <span className="mono" style={{ color: 'var(--text2)', fontSize: '0.8125rem' }} title={fmtDateTime(occurredAt)}>
      {fmtDateTimeShort(occurredAt)}
    </span>
  );
}

export function ActorCell({ actor }: { actor: ChangelogOperation['actor'] }): ReactElement {
  return actor ? (
    <span style={{ color: 'var(--text3)' }} title={actor.email ?? undefined}>
      {actor.name}
      {actor.role ? ` (${ROLE_SHORT[actor.role] ?? actor.role})` : ''}
    </span>
  ) : (
    <span style={{ color: 'var(--text3)' }}>Система</span>
  );
}

export function OperationCell({ operation, label }: { operation: string; label: string }): ReactElement {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--text1)' }}>
      <span style={{ color: 'var(--text3)', display: 'inline-flex' }}>{actionIcon(operation)}</span>
      {label}
    </span>
  );
}
```

- [ ] **Step 2: Переключить `ChangelogListPage.tsx` на общий модуль**

Удалить из `ChangelogListPage.tsx` строки 20-58 (`svgProps`, `ACTION_ICONS`, `actionIcon`, `ROLE_SHORT`) и заменить импорт:

```tsx
// было (строка 1-18 частично) — добавить:
import {
  actionIcon,
  ACTION_ICONS,
  TimeCell,
  ActorCell,
  OperationCell,
} from '../../components/changelog/columnRenderers';
```

В колонках заменить инлайн-рендер на использование новых компонентов, сохранив точный текущий визуальный результат:

```tsx
    {
      key: 'occurred_at',
      label: 'Время',
      width: '7rem',
      cell: (r) => <TimeCell occurredAt={r.occurred_at} />,
    },
    {
      key: 'operation',
      label: 'Действие',
      width: '14rem',
      cell: (r) => (
        <OperationCell operation={r.operation} label={CHANGELOG_OPERATION_LABELS[r.operation] ?? r.operation} />
      ),
    },
    {
      key: 'summary',
      label: 'Описание',
      cell: (r) => <span>{r.summary}</span>,
    },
    {
      key: 'actor',
      label: 'Кто',
      width: '13rem',
      cell: (r) => <ActorCell actor={r.actor} />,
    },
```

Колонки `status` и `revert` (строки 138-164 в исходнике) не трогать — они используют `ACTION_ICONS.revert`, который теперь импортируется из общего модуля.

- [ ] **Step 3: Проверить typecheck**

Run: `cd journal_django/frontend/admin-src && npm run typecheck`
Expected: без ошибок (0 errors)

- [ ] **Step 4: Коммит**

```bash
git add journal_django/frontend/admin-src/src/components/changelog/columnRenderers.tsx journal_django/frontend/admin-src/src/pages/changelog/ChangelogListPage.tsx
git commit -m "refactor(changelog): extract shared row renderers into columnRenderers.tsx"
```

---

### Task 2: Проп `readOnly` в `ChangelogDetailModal`

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/changelog/ChangelogDetailModal.tsx:164-218`

- [ ] **Step 1: Изменить сигнатуру пропов и условие рендера кнопки отката**

```tsx
export function ChangelogDetailModal({ contextId, onClose, onRevert, readOnly = false }: {
  contextId: string;
  onClose: () => void;
  onRevert?: (op: ChangelogOperation) => void;
  readOnly?: boolean;
}) {
```

В футере (текущие строки 202-216) заменить условие:

```tsx
          {!readOnly && data && canRevertChangelog(me?.role as Role) && data.revertable && (
            <button
              type="button"
              className="btn-danger"
              onClick={() =>
                onRevert?.({
                  ...data,
                  entities: summarizeEntities(data.events),
                  events_total: data.events.length,
                })
              }
            >
              Откатить операцию
            </button>
          )}
```

- [ ] **Step 2: Проверить, что вызов из `ChangelogListPage.tsx` не сломан**

`ChangelogListPage.tsx` вызывает `<ChangelogDetailModal contextId={openedId} onClose={...} onRevert={(op) => {...}} />` — `readOnly` не передаётся, по умолчанию `false`, поведение общего журнала не меняется. Изменений в `ChangelogListPage.tsx` для этого шага не требуется.

- [ ] **Step 3: Typecheck**

Run: `cd journal_django/frontend/admin-src && npm run typecheck`
Expected: без ошибок

- [ ] **Step 4: Коммит**

```bash
git add journal_django/frontend/admin-src/src/pages/changelog/ChangelogDetailModal.tsx
git commit -m "feat(changelog): add readOnly prop to hide revert action in detail modal"
```

---

### Task 3: Компонент `EntityChangelogPanel`

**Files:**
- Create: `journal_django/frontend/admin-src/src/components/changelog/EntityChangelogPanel.tsx`

- [ ] **Step 1: Написать компонент**

```tsx
// journal_django/frontend/admin-src/src/components/changelog/EntityChangelogPanel.tsx
import { useState } from 'react';
import { useChangelogList } from '../../hooks/useChangelog';
import { DataTable, type Column } from '../table/DataTable';
import { TableSkeleton } from '../ui/Skeleton';
import { ChangelogDetailModal } from '../../pages/changelog/ChangelogDetailModal';
import { CHANGELOG_OPERATION_LABELS } from '../../lib/labels';
import { TimeCell, ActorCell, OperationCell } from './columnRenderers';
import type { ChangelogOperation } from '../../lib/types';

const PAGE_SIZE = 15;

function buildQuery(page: number, entity: string, entityId: number): string {
  const p = new URLSearchParams();
  p.set('page', String(page));
  p.set('page_size', String(PAGE_SIZE));
  p.set('filter[entity]', entity);
  p.set('filter[entity_id]', String(entityId));
  return '?' + p.toString();
}

/** Компактная read-only лента изменений одной сущности — для вкладок «История». */
export function EntityChangelogPanel({ entity, entityId }: { entity: string; entityId: number }) {
  const [page, setPage] = useState(1);
  const [openedId, setOpenedId] = useState<string | null>(null);

  const query = buildQuery(page, entity, entityId);
  const { data, isLoading, isFetching } = useChangelogList(query);

  const rows  = data?.rows  ?? [];
  const total = data?.total ?? 0;

  const columns: Column<ChangelogOperation>[] = [
    {
      key: 'occurred_at',
      label: 'Время',
      width: '7rem',
      cell: (r) => <TimeCell occurredAt={r.occurred_at} />,
    },
    {
      key: 'operation',
      label: 'Действие',
      width: '14rem',
      cell: (r) => (
        <OperationCell operation={r.operation} label={CHANGELOG_OPERATION_LABELS[r.operation] ?? r.operation} />
      ),
    },
    {
      key: 'summary',
      label: 'Описание',
      cell: (r) => <span>{r.summary}</span>,
    },
    {
      key: 'actor',
      label: 'Кто',
      width: '13rem',
      cell: (r) => <ActorCell actor={r.actor} />,
    },
  ];

  if (isLoading) return <TableSkeleton rows={6} cols={4} />;

  return (
    <>
      <DataTable<ChangelogOperation>
        data={rows}
        columns={columns}
        title="История изменений"
        isLoading={isFetching}
        onRowClick={(r) => setOpenedId(r.id)}
        serverPagination={{
          page,
          pageSize: PAGE_SIZE,
          total,
          sortBy: 'occurred_at',
          sortDir: 'desc',
          filters: {},
          onPageChange: setPage,
          onPageSizeChange: () => {},
          onSortChange: () => {},
          onFiltersChange: () => {},
        }}
      />

      {openedId && (
        <ChangelogDetailModal
          contextId={openedId}
          onClose={() => setOpenedId(null)}
          readOnly
        />
      )}
    </>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd journal_django/frontend/admin-src && npm run typecheck`
Expected: без ошибок. Если `DataTable`/`Column` экспортируются иначе (проверить `components/table/DataTable.tsx`) — поправить импорт по фактической сигнатуре.

- [ ] **Step 3: Коммит**

```bash
git add journal_django/frontend/admin-src/src/components/changelog/EntityChangelogPanel.tsx
git commit -m "feat(changelog): add EntityChangelogPanel compact read-only widget"
```

---

### Task 4: Вкладка «История» на странице группы

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/groups/GroupDetailPage.tsx`

- [ ] **Step 1: Импорты и тип вкладок**

Добавить импорты (рядом с существующими импортами `useAuth`/`permissions`, которых в этом файле сейчас нет — добавить новые):

```tsx
import { useAuth } from '../../hooks/useAuth';
import { canSeeChangelog, type Role } from '../../lib/permissions';
import { EntityChangelogPanel } from '../../components/changelog/EntityChangelogPanel';
```

Изменить строку 29:

```tsx
const GROUP_TABS = ['overview', 'students', 'lessons', 'progress', 'schedule', 'history'] as const;
```

- [ ] **Step 2: Получить роль и добавить вкладку**

В теле компонента, рядом с `const { data: group, isLoading } = useGroup(id);` (строка 41), добавить:

```tsx
  const { me } = useAuth();
```

После определения массива `tabs` (после элемента `schedule`, перед закрывающей `];` — исходные строки 162-181), добавить условный push. Заменить объявление `const tabs: TabItem[] = [` .. `];` (строки 99-182) так, чтобы после последнего элемента (`schedule`) шёл ещё один элемент, добавляемый только при наличии прав:

```tsx
  const tabs: TabItem[] = [
    // ...existing overview/students/lessons/progress/schedule entries unchanged...
  ];

  if (canSeeChangelog(me?.role as Role)) {
    tabs.push({
      value: 'history',
      label: 'История',
      content: <EntityChangelogPanel entity="group" entityId={group.id} />,
    });
  }
```

(Существующие 5 объектов внутри массива `tabs` остаются буквально без изменений — меняется только то, что после них добавляется условный `tabs.push(...)`.)

- [ ] **Step 3: Ручная проверка в браузере**

Запустить dev-сервер (`npm run dev` в `admin-src`, либо через локальный nginx-стек проекта), зайти на `/admin/groups/<id>` под ролью admin/manager — вкладка «История» должна появиться последней и показывать записи, где `entity=group, entity_id=<id>`, совпадающие с тем, что выдаёт `/admin/changelog?filter[entity]=group&filter[entity_id]=<id>`. Под ролью, не входящей в `isStaff`, вкладка не должна отображаться (если такая роль вообще может открыть эту страницу).

- [ ] **Step 4: Typecheck + build**

Run: `cd journal_django/frontend/admin-src && npm run typecheck && npm run build`
Expected: без ошибок

- [ ] **Step 5: Коммит**

```bash
git add journal_django/frontend/admin-src/src/pages/groups/GroupDetailPage.tsx
git commit -m "feat(groups): add История tab with entity changelog on group detail page"
```

---

### Task 5: Вкладка «История» на странице ученика

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx`

- [ ] **Step 1: Импорты и тип вкладок**

Добавить импорты:

```tsx
import { useAuth } from '../../hooks/useAuth';
import { canSeeChangelog, type Role } from '../../lib/permissions';
import { EntityChangelogPanel } from '../../components/changelog/EntityChangelogPanel';
```

Изменить строку 81:

```tsx
const STUDENT_TABS = ['learning', 'finance', 'comments', 'history'] as const;
```

- [ ] **Step 2: Получить роль и добавить вкладку**

В теле компонента, рядом с `const { data: student, isLoading } = useStudent(id);` (строка 92), добавить:

```tsx
  const { me } = useAuth();
```

После объявления массива `tabs` (строки 230-281, элементы `learning`/`finance`/`comments` остаются без изменений), добавить:

```tsx
  const tabs: TabItem[] = [
    // ...existing learning/finance/comments entries unchanged...
  ];

  if (canSeeChangelog(me?.role as Role)) {
    tabs.push({
      value: 'history',
      label: 'История',
      content: <EntityChangelogPanel entity="student" entityId={student.id} />,
    });
  }
```

- [ ] **Step 3: Ручная проверка в браузере**

Зайти на `/admin/students/<id>` под ролью admin/manager — вкладка «История» должна появиться последней (после «Комментарии») и показывать записи именно этого ученика.

- [ ] **Step 4: Typecheck + build**

Run: `cd journal_django/frontend/admin-src && npm run typecheck && npm run build`
Expected: без ошибок

- [ ] **Step 5: Коммит**

```bash
git add journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx
git commit -m "feat(students): add История tab with entity changelog on student detail page"
```

---

### Task 6: Финальная регрессия общего журнала

**Files:** нет изменений — только проверка.

- [ ] **Step 1: Убедиться, что общий журнал не сломан**

Открыть `/admin/changelog` под ролью admin: фильтр по действию работает, deep-link `?entity=group&entity_id=<id>` (используемый `RevertConfirmDialog.tsx:79`) по-прежнему подставляет фильтр и подсвечивает бейдж, клик по строке открывает модалку, кнопка «Откатить операцию» доступна и работает для revertable-записей (модалка вызывается БЕЗ `readOnly`).

- [ ] **Step 2: Полный typecheck + build всего admin-src**

Run: `cd journal_django/frontend/admin-src && npm run typecheck && npm run build`
Expected: 0 ошибок, сборка проходит.

- [ ] **Step 3: Финальный коммит (если остались несохранённые правки)**

```bash
git status
```

Если есть незакоммиченные изменения из предыдущих шагов — закоммитить их адресно (без `git add -A`).

---

## Self-review notes

- Backend не тронут — по спеке это осознанное решение (эндпоинт уже параметризован).
- `EntityChangelogPanel` переиспользует `useChangelogList`, `ChangelogDetailModal`, `DataTable`, рендереры из `columnRenderers.tsx` — дублирования логики форматирования нет.
- `readOnly` в `ChangelogDetailModal` не меняет поведение вызова из `ChangelogListPage.tsx` (проп не передаётся → `false` по умолчанию).
- Роль/права: гейт `canSeeChangelog` идентичен гейту роута `/admin/changelog` (`isStaff`), обеспечивает согласованность видимости.
