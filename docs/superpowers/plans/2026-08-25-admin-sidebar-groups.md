# Sidebar admin SPA: сворачиваемые группы + мобильный drawer — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Разделы admin SPA прячутся в сворачиваемые группы (аккордеон, открыта одна), а на узких экранах вместо нижней шторки выезжает слева тот же сайдбар.

**Architecture:** `Sidebar.tsx` разрезается на четыре файла с одной ответственностью у каждого: данные навигации (`navConfig.tsx`), одна группа (`NavGroup.tsx`), сборка панели (`Sidebar.tsx`), мобильная обёртка (`SidebarDrawer.tsx`). Состояние аккордеона выводится из текущего маршрута и живёт в `Sidebar`. Drawer строится на уже установленном `@radix-ui/react-dialog` — Esc, ловушка фокуса, блокировка прокрутки и aria достаются даром.

**Tech Stack:** React 19, react-router-dom v7, `@radix-ui/react-dialog` 1.1, TanStack Query v5, чистый CSS на токенах проекта (`styles/tokens.css`).

**Спека:** `docs/superpowers/specs/2026-08-25-admin-sidebar-groups-design.md`

---

## Важное про проверку и коммиты

**Автотестов у admin SPA нет.** В `journal_django/frontend/admin-src/package.json` только `dev`, `build`, `typecheck` — тестового раннера в проекте не заведено, и заводить его этот план не берётся (это отдельная работа, вне рамок спеки). Поэтому TDD-цикл здесь заменён на другой воспроизводимый шлюз: **после каждой задачи гоняется `npm run typecheck` и он обязан быть чистым**, а в конце добавляется ручной браузерный прогон по списку из Task 7.

Не выдавайте `typecheck` за тесты. Если по ходу отчитываетесь о результате — так и пишите: «typecheck чистый, автотестов нет, браузер прогнан вручную».

**Коммиты не делаются.** Правило проекта (`CLAUDE.md`): коммитить и пушить только по явной просьбе пользователя. Плюс рабочее дерево сейчас полно чужого WIP — `git add` стянул бы посторонние файлы. Все задачи оставляют изменения в рабочем дереве; пользователь решит, что и когда коммитить.

**`npm run build` — только в Task 7**, один раз. Он переписывает `journal_django/frontend/admin-dist/` (хешированные имена файлов), и прогон после каждой задачи засорил бы дерево мусорными артефактами.

Все пути ниже — от корня репозитория. Рабочая директория для npm-команд: `journal_django/frontend/admin-src`.

---

## Структура файлов

| Файл | Что делает | Задача |
|---|---|---|
| `journal_django/frontend/admin-src/src/components/shell/navConfig.tsx` | **Создать.** Данные навигации: `NAV_ICONS`, `NAV_PINNED`, `NAV_GROUPS`, типы, `groupKeyOfPath` | 1 |
| `.../components/shell/ExtraLessonsBadge.tsx` | **Создать.** Бейдж-счётчик отдельным файлом — иначе `NavGroup` импортировал бы его из `Sidebar`, а `Sidebar` импортирует `NavGroup` (цикл) | 1 |
| `.../components/shell/NavGroup.tsx` | **Создать.** Одна сворачиваемая группа | 3 |
| `.../components/shell/Sidebar.tsx` | **Переписать.** Только сборка панели и состояние аккордеона | 4 |
| `.../components/shell/SidebarDrawer.tsx` | **Создать.** Мобильная обёртка на Radix Dialog | 5 |
| `.../components/shell/MobileNav.tsx` | **Удалить** | 6 |
| `.../components/shell/AppShell.tsx` | **Изменить.** `MobileNav` → `SidebarDrawer` | 6 |
| `.../styles/shell.css` | **Изменить.** Стили групп и drawer; блок `.mobile-nav*` удаляется | 3, 5, 6 |

---

## Task 1: Вынести данные навигации в `navConfig.tsx`

Чисто механический перенос плюс новые поля. Ни один компонент поведения пока не меняет — это подготовка, после которой typecheck обязан быть зелёным.

**Files:**
- Create: `journal_django/frontend/admin-src/src/components/shell/navConfig.tsx`
- Create: `journal_django/frontend/admin-src/src/components/shell/ExtraLessonsBadge.tsx`
- Modify: `journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx`
- Modify: `journal_django/frontend/admin-src/src/components/shell/MobileNav.tsx`

- [ ] **Step 1: Создать `ExtraLessonsBadge.tsx`**

Перенести компонент из `Sidebar.tsx` как есть, вместе с комментарием:

```tsx
import { usePendingExtraLessonsCount } from '../../hooks/useExtraLessons';

/** Красный бейдж с числом необработанных пропусков на кнопке «Доп.уроки». */
export function ExtraLessonsBadge() {
  const { data } = usePendingExtraLessonsCount();
  const count = data?.count ?? 0;
  if (count <= 0) return null;
  return (
    <span className="nav-badge" title={`Необработанных пропусков: ${count}`}>
      {count > 99 ? '99+' : count}
    </span>
  );
}
```

- [ ] **Step 2: Создать `navConfig.tsx` — перенести `NAV_ICONS`**

Создать файл со следующей шапкой и **перенести в него объект `NAV_ICONS` из `Sidebar.tsx` целиком, посимвольно, вместе со всеми комментариями** (в том числе комментарием про «i» в круге у ключа `knowledge`). Ничего в существующих иконках не менять и ни одну не удалять: ключи вроде `students` и `lessons` используются за пределами сайдбара, а `pay` — на кнопке «Внести оплату».

```tsx
import type { ReactElement } from 'react';
import {
  canSeePayroll, canSeeAccounts, canSeeAudit, canSeeChangelog,
  canSeeSync, canSeeArchive, type Role,
} from '../../lib/permissions';

export const NAV_ICONS: Record<string, ReactElement> = {
  // ← сюда переносится содержимое NAV_ICONS из Sidebar.tsx без изменений
};
```

- [ ] **Step 3: Добавить в `NAV_ICONS` пять новых иконок**

Четыре иконки строк групп и шеврон. Дописать их **внутрь** объекта `NAV_ICONS`, перед закрывающей скобкой. Стиль ровно тот же, что у остальных: `viewBox="0 0 24 24"`, `fill="none"`, `stroke="currentColor"`, `strokeWidth="1.8"`, скруглённые концы, размер 16×16.

```tsx
  // ── Иконки строк-групп. У вложенных пунктов иконок нет вовсе, поэтому
  //    сходство с иконками отдельных разделов (шапочка ↔ «Преподаватели»,
  //    книга ↔ «Уроки») в сайдбаре нигде не встречается глазу.
  'group-study': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 10 12 5 2 10l10 5 10-5Z"/>
      <path d="M6 12v5c3 2.5 9 2.5 12 0v-5"/>
      <path d="M22 10v5"/>
    </svg>
  ),
  'group-lessons': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 4h5.5A2.5 2.5 0 0 1 10 6.5V20a2 2 0 0 0-2-2H2z"/>
      <path d="M22 4h-5.5A2.5 2.5 0 0 0 14 6.5V20a2 2 0 0 1 2-2h6z"/>
    </svg>
  ),
  'group-finance': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2"/>
      <path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-3"/>
      <path d="M21 10h-4a2 2 0 0 0 0 4h4z"/>
    </svg>
  ),
  'group-system': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/>
      <path d="M1 14h6M9 8h6M17 16h6"/>
    </svg>
  ),
  // Один шеврон вправо; в развёрнутой группе поворачивается средствами CSS —
  // второй SVG «вниз» держать не нужно.
  chevron: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 18 15 12 9 6"/>
    </svg>
  ),
```

- [ ] **Step 4: Добавить в `navConfig.tsx` типы и конфиг**

Дописать после `NAV_ICONS`. Старый `NAV_GROUPS` из `Sidebar.tsx` заменяется этим — состав разделов и порядок сохраняются один в один, добавляются только `key` и `icon`, а «Дашборд» уезжает в `NAV_PINNED`.

```tsx
export interface NavItem {
  key: string;
  label: string;
  path: string;
  /** Ролевой гейт: пункт виден, только если функция вернёт true. Без неё — всем staff. */
  can?: (role: Role | undefined) => boolean;
}

export interface NavGroup {
  /** Устойчивый ключ — по нему хранится состояние аккордеона. */
  key: string;
  title: string;
  /** Ключ в NAV_ICONS для иконки строки группы. */
  icon: string;
  items: NavItem[];
}

/**
 * Закреплено сверху, вне групп. «Дашборд» — точка входа, прятать его внутрь
 * аккордеона незачем; рядом с ним рендерится CTA «Внести оплату».
 */
export const NAV_PINNED: NavItem[] = [
  { key: 'dashboard', label: 'Дашборд', path: '/admin/dashboard' },
];

/**
 * Единый источник навигации admin SPA. Разделы спрятаны в смысловые группы:
 * группа раскрывается кликом, открыта всегда одна. Ролевые пункты несут `can`;
 * группа без единого видимого пункта не рисуется вовсе.
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    key: 'study',
    title: 'Учебная часть',
    icon: 'group-study',
    items: [
      { key: 'students', label: 'Ученики', path: '/admin/students' },
      { key: 'groups', label: 'Группы', path: '/admin/groups' },
      { key: 'teachers', label: 'Преподаватели', path: '/admin/teachers' },
      { key: 'directions', label: 'Направления', path: '/admin/directions' },
    ],
  },
  {
    key: 'lessons',
    title: 'Занятия',
    icon: 'group-lessons',
    items: [
      { key: 'lessons', label: 'Уроки', path: '/admin/lessons' },
      { key: 'extra-lessons', label: 'Доп.уроки', path: '/admin/extra-lessons' },
      { key: 'calendar', label: 'Календарь', path: '/admin/calendar' },
    ],
  },
  {
    key: 'finance',
    title: 'Финансы',
    icon: 'group-finance',
    items: [
      { key: 'subscriptions', label: 'Абонементы', path: '/admin/subscriptions' },
      { key: 'renewals', label: 'Продления', path: '/admin/renewals' },
      { key: 'reports', label: 'Отчёты', path: '/admin/reports' },
      { key: 'payroll', label: 'Зарплата', path: '/admin/payroll', can: canSeePayroll },
    ],
  },
  {
    key: 'system',
    title: 'Система',
    icon: 'group-system',
    items: [
      // Первым в группе: Wiki — единственный её пункт без ролевого условия,
      // то есть единственный, который видят все. Между разделами, закрытыми
      // для большинства ролей, он бы терялся.
      { key: 'knowledge', label: 'Wiki', path: '/admin/knowledge' },
      { key: 'settings', label: 'Настройки', path: '/admin/settings' },
      { key: 'archive', label: 'Архив', path: '/admin/archive', can: canSeeArchive },
      { key: 'accounts', label: 'Учётки', path: '/admin/accounts', can: canSeeAccounts },
      { key: 'audit', label: 'Журнал ИБ', path: '/admin/audit', can: canSeeAudit },
      { key: 'changelog', label: 'Журнал изменений', path: '/admin/changelog', can: canSeeChangelog },
      { key: 'notifications', label: 'Уведомления', path: '/admin/notifications', can: canSeeChangelog },
      { key: 'sync', label: 'Синхро', path: '/admin/sync', can: canSeeSync },
    ],
  },
];

/**
 * Ключ группы, которой принадлежит путь, либо null.
 *
 * Сравнение по началу пути с обязательным «/» на стыке: вложенные маршруты
 * (`/admin/students/42`) должны подсвечивать свою группу, но `/admin/lessons`
 * не должен ловить чужой `/admin/lessons-archive`, если такой однажды заведут.
 */
export function groupKeyOfPath(pathname: string): string | null {
  for (const group of NAV_GROUPS) {
    const hit = group.items.some(
      (it) => pathname === it.path || pathname.startsWith(`${it.path}/`),
    );
    if (hit) return group.key;
  }
  return null;
}
```

- [ ] **Step 5: Вычистить перенесённое из `Sidebar.tsx`**

Из `Sidebar.tsx` удалить: `ExtraLessonsBadge`, `NAV_ICONS`, `interface NavItem`, `interface NavGroup`, `NAV_GROUPS`, `NAV_ITEMS`, а также ставший ненужным импорт `usePendingExtraLessonsCount` и импорты `canSee*` из `lib/permissions` (кроме `canWritePayments` и типа `Role` — они нужны `PayButton` и самому `Sidebar`).

Вместо них — импорты сверху файла:

```tsx
import { NAV_ICONS, NAV_GROUPS } from './navConfig';
import { ExtraLessonsBadge } from './ExtraLessonsBadge';
```

Разметку `Sidebar` пока **не трогать** — она всё ещё рисует группы плоско. Её переписывает Task 4.

- [ ] **Step 6: Починить `MobileNav.tsx`**

`NAV_ITEMS` больше нет, а `MobileNav` живёт до Task 6 — временно собрать плоский список на месте. Заменить импорты и строку с `NAV_ITEMS`:

```tsx
import { NAV_ICONS, NAV_PINNED, NAV_GROUPS } from './navConfig';
import { ExtraLessonsBadge } from './ExtraLessonsBadge';
```

```tsx
  // Плоский список всех разделов (группы — только в десктоп-сайдбаре), ролевые
  // пункты фильтруются своим `can`.
  const visibleSections = [...NAV_PINNED, ...NAV_GROUPS.flatMap((g) => g.items)]
    .filter((it) => !it.can || it.can(role));
```

- [ ] **Step 7: Проверить typecheck**

```bash
cd journal_django/frontend/admin-src && npm run typecheck
```

Ожидается: команда завершается с кодом 0 и без вывода ошибок. Если `tsc` ругается на неиспользованный импорт — значит, в Step 5 что-то не дочистили.

---

## Task 2: Стили групп в `shell.css`

Стили пишутся до компонента, чтобы Task 3 сразу собирался в готовый вид, а не в голый HTML.

**Files:**
- Modify: `journal_django/frontend/admin-src/src/styles/shell.css`

- [ ] **Step 1: Заменить блок группы**

Найти в `shell.css` блок (сейчас строки 45–56):

```css
/* Смысловые группы разделов: заголовок сверху + сами пункты. */
.nav-group { display: flex; flex-direction: column; }
.nav-group + .nav-group { margin-top: var(--space-3); }
.nav-group__title {
  padding: 0 var(--space-3);
  margin: var(--space-2) 0 var(--space-1);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text4);
}
```

Заменить целиком на:

```css
/* Закреплённый блок над группами: «Дашборд» + CTA «Внести оплату». */
.nav-pinned { display: flex; flex-direction: column; margin-bottom: var(--space-3); }

/* Смысловые группы разделов: строка-кнопка + схлопывающийся список пунктов.
   Группа никуда не ведёт — клик по ней только разворачивает. */
.nav-group { display: flex; flex-direction: column; }
.nav-group + .nav-group { margin-top: 1px; }

.nav-group__btn {
  width: 100%;
  display: flex; align-items: center;
  gap: var(--space-2);
  padding: 7px 10px;
  border: none;
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--text2);
  font-family: inherit;
  font-size: 13px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition: background var(--t-fast) var(--ease), color var(--t-fast) var(--ease);
}
.nav-group__btn:hover { background: var(--bg3); color: var(--text); }
.nav-group__btn svg { flex-shrink: 0; opacity: 0.85; }
.nav-group__label { flex: 1; min-width: 0; }
/* Свёрнутая группа с активным разделом внутри: видно, где находишься, не
   разворачивая её. Подсветка живёт на цвете, а не на фоне — фон занят
   активным пунктом, и два фоновых пятна подряд читались бы как две «текущие»
   строки. */
.nav-group__btn--current { color: var(--accent); font-weight: 600; }
.nav-group__btn--current svg { opacity: 1; }

.nav-group__chevron {
  display: inline-flex;
  color: var(--text4);
  transition: transform var(--t-fast) var(--ease);
}
.nav-group--open .nav-group__chevron { transform: rotate(90deg); }

/* Схлопывание строкой грида 0fr → 1fr: анимируется настоящая высота
   содержимого, без JS-замеров и без max-height с угаданным числом. */
.nav-group__panel {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows var(--t-base) var(--ease);
}
.nav-group--open .nav-group__panel { grid-template-rows: 1fr; }
.nav-group__items { overflow: hidden; display: flex; flex-direction: column; }

/* Вложенный пункт рисуется без иконки; отступ слева ставит подпись ровно под
   подпись группы (10px паддинга + 16px иконки + 8px зазора). */
.nav-btn--child { padding-left: 34px; }

@media (prefers-reduced-motion: reduce) {
  .nav-group__panel,
  .nav-group__chevron { transition: none; }
}
```

- [ ] **Step 2: Убедиться, что `.nav-group__title` больше нигде не встречается**

```bash
cd journal_django/frontend/admin-src && grep -rn "nav-group__title" src/
```

Ожидается: пусто (пункт `Sidebar.tsx` с этим классом уберёт Task 4; если grep нашёл только его — это нормально, идём дальше).

---

## Task 3: Компонент `NavGroup`

**Files:**
- Create: `journal_django/frontend/admin-src/src/components/shell/NavGroup.tsx`

- [ ] **Step 1: Написать компонент**

```tsx
import { useId } from 'react';
import { NavLink } from 'react-router-dom';
import { NAV_ICONS, type NavGroup as NavGroupData, type NavItem } from './navConfig';
import { ExtraLessonsBadge } from './ExtraLessonsBadge';

interface Props {
  group: NavGroupData;
  /** Пункты, уже отфильтрованные по роли: компонент про роли ничего не знает. */
  items: NavItem[];
  open: boolean;
  /** Внутри группы лежит текущий раздел. */
  hasActive: boolean;
  onToggle: () => void;
}

export function NavGroup({ group, items, open, hasActive, onToggle }: Props) {
  const listId = useId();
  // Счётчик необработанных пропусков существует ровно для того, чтобы
  // попадаться на глаза. Свёрнутая группа его спрятала бы — поэтому он
  // поднимается на её строку.
  const badgeOnHeader = !open && items.some((it) => it.key === 'extra-lessons');
  return (
    <div className={`nav-group${open ? ' nav-group--open' : ''}`}>
      <button
        type="button"
        className={`nav-group__btn${hasActive ? ' nav-group__btn--current' : ''}`}
        aria-expanded={open}
        aria-controls={listId}
        onClick={onToggle}
      >
        {NAV_ICONS[group.icon]}
        <span className="nav-group__label">{group.title}</span>
        {badgeOnHeader && <ExtraLessonsBadge />}
        <span className="nav-group__chevron" aria-hidden="true">{NAV_ICONS['chevron']}</span>
      </button>
      {/* `inert`, а не `hidden`: hidden снимает панель с раскладки и убивает
          transition высоты, inert же просто гасит фокус и указатель. */}
      <div className="nav-group__panel" id={listId} inert={!open}>
        <div className="nav-group__items">
          {items.map((it) => (
            <NavLink
              key={it.key}
              to={it.path}
              className={({ isActive }) => `nav-btn nav-btn--child${isActive ? ' active' : ''}`}
            >
              <span className="nav-group__label">{it.label}</span>
              {it.key === 'extra-lessons' && <ExtraLessonsBadge />}
            </NavLink>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Проверить typecheck**

```bash
cd journal_django/frontend/admin-src && npm run typecheck
```

Ожидается: код 0. Атрибут `inert` как булев проп поддерживается типами React 19 (в проекте `react@^19.2.6`); если `tsc` его не знает — значит, установлена версия типов старее, и это надо разобрать, а не глушить через `as any`.

---

## Task 4: Переписать `Sidebar` — сборка и состояние аккордеона

**Files:**
- Modify: `journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx`

- [ ] **Step 1: Дописать импорты**

В шапке файла к уже имеющимся добавить:

```tsx
import { useEffect, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { NAV_ICONS, NAV_PINNED, NAV_GROUPS, groupKeyOfPath } from './navConfig';
import { NavGroup } from './NavGroup';
```

`ExtraLessonsBadge` в самом `Sidebar` больше не нужен — его рисует `NavGroup`. Если импорт остался с Task 1, убрать. `Avatar`, `PayButton`, `ThemeToggle`, `useAuth`, `usePaymentModal`, `canWritePayments` и тип `Role` остаются как есть.

- [ ] **Step 2: Заменить тело функции `Sidebar`**

Заменить существующую функцию `Sidebar` целиком на:

```tsx
export function Sidebar({ onClose }: { onClose?: () => void } = {}) {
  const { me, logout } = useAuth();
  const role = me?.role as Role | undefined;
  const { pathname } = useLocation();

  // Состояние аккордеона выводится из маршрута, а не хранится между сессиями:
  // открыта группа текущего раздела. Клик по строке группы открывает её и
  // закрывает предыдущую.
  const activeKey = groupKeyOfPath(pathname);
  const [openKey, setOpenKey] = useState<string | null>(activeKey);
  useEffect(() => {
    const key = groupKeyOfPath(pathname);
    // Переход в раздел другой группы (по ссылке со страницы, не из сайдбара)
    // раскрывает нужную группу. Если пользователь сам свернул группу текущего
    // раздела — она останется свёрнутой до следующей смены пути.
    if (key) setOpenKey(key);
  }, [pathname]);

  const pinned = NAV_PINNED.filter((it) => !it.can || it.can(role));

  return (
    <aside className="sidebar">
      {/* ← блок .sidebar-logo оставить БЕЗ ИЗМЕНЕНИЙ, как в текущем файле:
             логотип, .logo-sub и кнопка onClose со стрелкой «‹» */}
      <nav className="sidebar-nav">
        <div className="nav-pinned">
          {pinned.map((it) => (
            <NavLink
              key={it.key}
              to={it.path}
              className={({ isActive }) => `nav-btn${isActive ? ' active' : ''}`}
            >
              {NAV_ICONS[it.key]} {it.label}
            </NavLink>
          ))}
          <PayButton />
        </div>
        {NAV_GROUPS.map((group) => {
          const items = group.items.filter((it) => !it.can || it.can(role));
          if (items.length === 0) return null;
          return (
            <NavGroup
              key={group.key}
              group={group}
              items={items}
              open={openKey === group.key}
              hasActive={activeKey === group.key}
              onToggle={() => setOpenKey((k) => (k === group.key ? null : group.key))}
            />
          );
        })}
      </nav>
      {/* ← блок .sidebar-footer оставить БЕЗ ИЗМЕНЕНИЙ: Avatar, имя, роль,
             ThemeToggle, кнопка «Выйти» */}
    </aside>
  );
}
```

Блоки `.sidebar-logo` и `.sidebar-footer` копируются из текущего файла дословно — они не меняются, и переписывать их заново незачем.

- [ ] **Step 3: Проверить typecheck**

```bash
cd journal_django/frontend/admin-src && npm run typecheck
```

Ожидается: код 0.

- [ ] **Step 4: Посмотреть глазами в dev-режиме**

```bash
cd journal_django/frontend/admin-src && npm run dev
```

Открыть admin SPA в широком окне. Проверить: закреплённый «Дашборд» и кнопка оплаты сверху; четыре строки групп с иконками и шевронами; открыта группа текущего раздела; клик по другой группе переключает открытую; повторный клик по открытой сворачивает её; вложенные пункты без иконок и выровнены под подпись группы; свёрнутая группа с текущим разделом подсвечена акцентным цветом.

Остановить dev-сервер (Ctrl+C) перед следующей задачей.

---

## Task 5: `SidebarDrawer` и его стили

**Files:**
- Create: `journal_django/frontend/admin-src/src/components/shell/SidebarDrawer.tsx`
- Modify: `journal_django/frontend/admin-src/src/styles/shell.css`

- [ ] **Step 1: Написать компонент**

Берутся примитивы Radix, а не готовая обёртка `components/ui/Dialog.tsx`: у неё своя модальная шапка и `.modal`-стили. Образец такого же использования примитивов — `components/knowledge/ImageLightbox.tsx`.

```tsx
import * as RadixDialog from '@radix-ui/react-dialog';
import { Sidebar } from './Sidebar';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Мобильная навигация: тот же сайдбар, выезжающий слева поверх контента.
 *
 * Закрытие по Esc, ловушку фокуса, возврат фокуса на бургер, блокировку
 * прокрутки страницы и aria-разметку берёт на себя Radix Dialog — писать это
 * руками не нужно.
 */
export function SidebarDrawer({ open, onOpenChange }: Props) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="sidebar-drawer-overlay" />
        <RadixDialog.Content className="sidebar-drawer" aria-describedby={undefined}>
          <RadixDialog.Title className="sr-only">Меню разделов</RadixDialog.Title>
          <Sidebar onClose={() => onOpenChange(false)} />
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
```

- [ ] **Step 2: Добавить стили drawer в `shell.css`**

Дописать в блок `/* ── COLLAPSIBLE SIDEBAR + MOBILE BOTTOM-SHEET NAV ── */`, сразу после правил `.burger-btn` (сам заголовок блока поправит Task 6):

```css
/* Мобильная навигация: тот же сайдбар, выезжающий слева поверх контента.
   Radix держит контент смонтированным, пока идёт CSS-анимация выхода, —
   отсюда парные правила на [data-state="closed"]. */
.sidebar-drawer-overlay {
  position: fixed; inset: 0;
  z-index: calc(var(--z-nav) + 1);
  background: var(--overlay);
  animation: drawer-fade var(--t-base) var(--ease-out);
}
.sidebar-drawer-overlay[data-state="closed"] {
  animation: drawer-fade var(--t-fast) var(--ease-out) reverse;
}

.sidebar-drawer {
  position: fixed; top: 0; left: 0;
  width: min(280px, 86vw);
  height: 100dvh;
  z-index: calc(var(--z-nav) + 2);
  box-shadow: var(--shadow-modal);
  animation: drawer-in var(--t-slow) var(--ease-out);
}
.sidebar-drawer[data-state="closed"] {
  animation: drawer-in var(--t-base) var(--ease-out) reverse;
}
/* Базовый .sidebar (base.css) — липкая колонка на всю высоту экрана. Внутри
   фиксированного drawer он должен быть обычным блоком во всю обёртку. */
.sidebar-drawer .sidebar {
  position: static;
  width: 100%; min-width: 0;
  height: 100%; min-height: 0;
  border-right: none;
}

@keyframes drawer-in {
  from { transform: translateX(-100%); }
  to   { transform: none; }
}
@keyframes drawer-fade {
  from { opacity: 0; }
  to   { opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .sidebar-drawer,
  .sidebar-drawer-overlay { animation: none; }
}
```

- [ ] **Step 3: Проверить typecheck**

```bash
cd journal_django/frontend/admin-src && npm run typecheck
```

Ожидается: код 0. Визуально drawer пока не появится — его ещё никто не рендерит, это делает Task 6.

---

## Task 6: Подключить drawer в `AppShell`, удалить `MobileNav`

**Files:**
- Modify: `journal_django/frontend/admin-src/src/components/shell/AppShell.tsx`
- Delete: `journal_django/frontend/admin-src/src/components/shell/MobileNav.tsx`
- Modify: `journal_django/frontend/admin-src/src/styles/shell.css`

- [ ] **Step 1: Заменить импорт в `AppShell.tsx`**

```tsx
import { SidebarDrawer } from './SidebarDrawer';
```

вместо `import { MobileNav } from './MobileNav';`

- [ ] **Step 2: Заменить рендер мобильной навигации**

Строку

```tsx
        {isNarrow && <MobileNav open={mobileOpen} onClose={() => setMobileOpen(false)} />}
```

заменить на

```tsx
        {isNarrow && <SidebarDrawer open={mobileOpen} onOpenChange={setMobileOpen} />}
```

Остальное в `AppShell` не трогать: брейкпоинт `NARROW_BREAKPOINT = 1500`, `useIsNarrow`, поведение бургера, кнопка «‹» и сброс `setMobileOpen(false)` при смене `location.pathname` работают как раньше.

- [ ] **Step 3: Удалить `MobileNav.tsx`**

```bash
cd journal_django/frontend/admin-src && rm src/components/shell/MobileNav.tsx
```

- [ ] **Step 4: Удалить стили нижней шторки**

Из `shell.css` удалить целиком правила `.mobile-nav-overlay`, `.mobile-nav-overlay.open`, `.mobile-nav`, `.mobile-nav.open`, `[data-theme="dark"] .mobile-nav`, `.mobile-nav-handle`, `.mobile-nav-list`, `.mobile-nav-item`, `.mobile-nav-item:hover`, `.mobile-nav-item.active`, `.mobile-nav-item svg`, `.mobile-nav-item.active svg`, `[data-theme="dark"] .mobile-nav-item:hover`.

Заодно поправить заголовок блока — нижней шторки в нём больше нет:

```css
/* ── COLLAPSIBLE SIDEBAR + MOBILE DRAWER ── */
```

- [ ] **Step 5: Убедиться, что от `MobileNav` не осталось следов**

```bash
cd journal_django/frontend/admin-src && grep -rn "MobileNav\|mobile-nav\|NAV_ITEMS" src/
```

Ожидается: пусто. Любое совпадение — недочищенная ссылка.

- [ ] **Step 6: Проверить typecheck**

```bash
cd journal_django/frontend/admin-src && npm run typecheck
```

Ожидается: код 0.

---

## Task 7: Сборка и ручная приёмка

**Files:**
- Modify (артефакты сборки): `journal_django/frontend/admin-dist/`

- [ ] **Step 1: Собрать**

```bash
cd journal_django/frontend/admin-src && npm run build
```

Ожидается: `vite build` завершается успешно, в `../admin-dist/assets/` появляются новые файлы с новыми хешами, `../admin-dist/index.html` обновляет ссылки на них.

- [ ] **Step 2: Прогнать десктопный сценарий в браузере**

Открыть admin SPA в широком окне (больше 1500px) и проверить по списку:

- закреплённый «Дашборд» и CTA «Внести оплату» сверху, вне групп;
- открыта группа текущего раздела, остальные свёрнуты;
- клик по группе разворачивает её и сворачивает предыдущую; клик по открытой сворачивает её; никуда при этом не переходит;
- переход по ссылке со страницы в раздел другой группы (например, с карточки ученика на группу) раскрывает нужную группу в сайдбаре;
- свёрнутая группа с текущим разделом внутри подсвечена акцентным цветом;
- при свёрнутых «Занятиях» красный счётчик доп.уроков виден на строке группы, при развёрнутых — на пункте «Доп.уроки», и нигде не задваивается;
- вложенные пункты без иконок, выровнены под подпись группы;
- кнопка «‹» прячет сайдбар, бургер возвращает;
- вкладка Network: запрос счётчика пропусков по-прежнему один, а не два.

- [ ] **Step 3: Прогнать мобильный сценарий**

Сузить окно меньше 1500px (или включить device toolbar):

- бургер открывает панель, выезжающую **слева**, справа — затемнение;
- нижняя шторка не появляется нигде;
- закрывается: тапом по затемнению, клавишей Esc, крестиком в шапке панели;
- после закрытия фокус вернулся на бургер;
- пока drawer открыт, страница под ним не прокручивается;
- переход по пункту закрывает drawer;
- Tab внутри открытого drawer не уводит фокус на элементы страницы за ним;
- при свёрнутых группах Tab не попадает на скрытые пункты.

- [ ] **Step 4: Проверить обе темы и роль менеджера**

- Переключить тему тумблером в футере сайдбара: в тёмной теме строки групп, шеврон, подсветка активной группы и затемнение drawer читаются, контраст не проваливается.
- Зайти под ролью «менеджер»: скрытые ролевые пункты («Зарплата», «Учётки», «Журнал ИБ», «Синхро» и прочие) не оставляют пустых мест в группах; если у группы не осталось ни одного видимого пункта — строка группы не рисуется вовсе.

- [ ] **Step 5: Посмотреть, что попало в дерево**

```bash
git status --short journal_django/frontend/
```

Ожидается: изменённые и новые файлы в `admin-src/src/components/shell/`, `admin-src/src/styles/shell.css`, удалённый `MobileNav.tsx`, плюс переcобранные артефакты в `admin-dist/`. Ничего постороннего.

Коммит не делать — по правилам проекта его делает пользователь по своему решению.

---

## Самопроверка плана

**Покрытие спеки.** Каждый раздел спеки закрыт задачей: структура файлов → Task 1, 3, 4, 5, 6; конфиг и `NAV_PINNED` → Task 1 Step 4; иконки групп и отсутствие иконок у вложенных пунктов → Task 1 Step 3 и Task 2 Step 1 (`.nav-btn--child`); состояние аккордеона и `groupKeyOfPath` → Task 1 Step 4, Task 4 Step 2; три состояния строки группы → Task 2 Step 1 (`.nav-group__btn--current`, `.nav-group--open .nav-group__chevron`); анимация `0fr → 1fr` → Task 2 Step 1; бейдж на свёрнутой группе → Task 3 Step 1; drawer на Radix → Task 5; удаляемое → Task 6; дизайн-токены → Task 2 и Task 5 (хардкод-значений нет); доступность, включая `inert` и `prefers-reduced-motion` → Task 3 Step 1, Task 2 Step 1, Task 5 Step 2, приёмка в Task 7 Step 3; производительность (один запрос счётчика) → Task 7 Step 2.

**Согласованность имён.** `NavGroup` — и тип в `navConfig.tsx`, и компонент в `NavGroup.tsx`; чтобы не столкнулись, компонент импортирует тип как `NavGroupData` (Task 3 Step 1), а `Sidebar` импортирует только компонент (Task 4 Step 1). Пропсы `group / items / open / hasActive / onToggle` объявлены в Task 3 и передаются ровно этим набором в Task 4. `SidebarDrawer` принимает `open / onOpenChange` (Task 5) и вызывается с ними же (Task 6). Ключи групп `study / lessons / finance / system` из Task 1 используются только через `group.key` — строковых литералов ключей в других задачах нет. Ключи иконок `group-*` и `chevron` заведены в Task 1 Step 3 и читаются в Task 3 Step 1.

**Известное пересечение имён:** ключ группы `lessons` совпадает с ключом пункта `lessons` и ключом иконки `lessons`. Это безопасно — они живут в разных пространствах (`NavGroup.key`, `NavItem.key`, ключ `NAV_ICONS`), а иконка группы «Занятия» лежит под отдельным ключом `group-lessons`.
