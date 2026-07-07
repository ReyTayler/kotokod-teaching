# Раздел «Журнал изменений» в admin SPA — UI-план

Дата: 2026-07-06. Статус: план (реализация не начата). Базируется на утверждённом
дизайне бэкенда [`2026-07-06-changelog-design.md`](./2026-07-06-changelog-design.md)
(§7 API, §6 откат). Только планирование — код не писался, файлы кодовой базы не
менялись.

**Важно про контракт API**: бэкенд для этой фичи ещё не реализован (backend-план,
§10, фазы 0-4 не начаты). Все имена полей ответа (`operation`, `entities`,
`revertable`, `revert_conflicts` и т.п.), упомянутые ниже, — это **предложение
контракта для обсуждения с backend-developer**, а не факт. Перед стартом Шага A
(см. §8) нужно зафиксировать точный JSON совместно, чтобы не переписывать типы
и хуки повторно.

Все пути ниже проверены по факту в `journal_django/frontend/admin-src/src/`
(текущее расположение admin SPA после миграции на Django — старые пути
`web/admin/src/...` из более ранних заметок памяти устарели).

---

## 0. Ключевые находки по конвенциям (для справки внутри плана)

- Admin SPA целиком закрыт `AuthGate` (`components/shell/AuthGate.tsx`) ролями
  `manager`/`admin` (`ADMIN_ROLES`) — учитель вообще не попадает в `/admin/*`,
  его уводит на `/teacher`. Значит **просмотр журнала не требует отдельного
  фронт-гейта** — достаточно того, что страница лежит в обычных маршрутах
  `/admin/*`. Это ровно то, что просил бэкенд-спек (`IsManagerOrAdmin` на чтение).
- Реальная защита — всегда на API (`IsManagerOrAdmin`/`IsAdmin`), фронт-проверки
  — только UX/defense-in-depth, как того требует `docs/security-guidelines.md`.
- React уже экранирует текст в JSX по умолчанию — в отличие от старого
  vanilla-JS admin (`admin-app.js`, где нужен был ручной `escapeHtml`), здесь
  для diff-значений из Google Sheets/PG (эмодзи, длинные строки) экранирование
  не требуется вручную, кроме мест, где сознательно используется
  `dangerouslySetInnerHTML` (в проекте таких нет).
- `DataTable` (`components/table/DataTable.tsx`) не поддерживает `html`-колонки
  как раньше в vanilla-версии — это React-компонент, `cell` — рендер-функция.
- Detail-страницы entity (`Student`, `Group`, ...) используют `DetailShell` —
  но он рассчитан на **одну** сущность с полями и edit/delete. Карточка
  операции журнала — это N затронутых строк с diff'ом каждой, под модель
  DetailShell не подходит → нужна отдельная (bespoke) страница, аналогично
  тому, как `PayrollPage` не использует DetailShell для summary-режима.
- Есть готовый паттерн confirm+revert-подобного действия — `AccountsPage.tsx`:
  `ConfirmModal` на `Dialog`, discriminated union `PendingAction`, `isPending`
  агрегированный из нескольких мутаций. Использовать как образец для отката.

---

## 1. Навигация

**Маршруты** (`App.tsx`, добавить рядом с остальными `<Route>` внутри
`<Route element={<AppShell />}>`):

```
<Route path="/admin/changelog" element={<ChangelogListPage />} />
<Route path="/admin/changelog/:contextId" element={<ChangelogDetailPage />} />
```

**Sidebar** (`components/shell/Sidebar.tsx`):

- Новая иконка `NAV_ICONS['changelog']` — SVG «история» (циферблат со
  стрелкой возврата: круг + стрелка против часовой), по образцу существующих
  16×16 `stroke="currentColor" strokeWidth="1.8"` иконок в файле.
- Добавить в **обычный массив `SECTIONS`** (НЕ в блок `me?.role === 'admin'`,
  где сейчас «Учётки» и «Журнал ИБ» — тот блок жёстко admin-only, а «Журнал
  изменений» по спеке видят manager+admin, то есть все, кто вообще попадает в
  admin SPA). Место — в конце основного списка, перед `nav-sep` и
  admin-only-блоком:
  ```ts
  { key: 'changelog', label: 'Журнал изменений', path: '/admin/changelog' },
  ```
  Название сознательно отличается от «Журнал ИБ» (`audit`, тот — про
  security-события входа/2FA, этот — про изменения данных; их не путать,
  см. §1 бэкенд-спеки).

**RBAC на фронте**:
- Просмотр ленты и карточки — доступен любому, кто внутри `/admin/*`
  (`AuthGate` уже гарантирует manager/admin). Дополнительной проверки роли на
  уровне страницы не нужно.
- Кнопка «Откатить операцию» в карточке — рендерится только при
  `me?.role === 'admin'` (хук `useAuth()`, как в `Sidebar.tsx` строка 196).
  Manager видит карточку и diff, но без кнопки отката — ровно как просил
  заказчик. Бэкенд обязан продублировать проверку через `IsAdmin` на
  `POST .../revert` — фронт-скрытие кнопки не является защитой.

---

## 2. Лента операций (`ChangelogListPage.tsx`)

Полностью по образцу `pages/audit/AuditPage.tsx` (тот же `useListSearchParams`
+ `buildQuery` + `DataTable` + `serverPagination`), 1 строка = 1 контекст
операции.

**Колонки** (`Column<ChangelogContext>[]`):

| key | Заголовок | Рендер |
|---|---|---|
| `created_at` | Время | `fmtDateTime()` — вынести общую функцию из `AuditPage.tsx` (сейчас там локальная, строки 28-41) в `lib/format.ts`, чтобы не дублировать между `AuditPage` и `ChangelogListPage` (единственная причина не копипастить — тот же формат МСК с секундами). `sortable: true`, `width: '13rem'`, класс `mono`, цвет `var(--text2)` — как в AuditPage. |
| `operation` | Операция | Метка через `CHANGELOG_OPERATION_LABELS[op] ?? op` (новая карта в `lib/labels.ts`, см. §7). Если ключа нет в карте — показываем сырой ключ моноширинным текстом приглушённого цвета (`var(--text3)`), никогда не пусто. `searchable: true`, `searchOptions` — из `Object.entries(CHANGELOG_OPERATION_LABELS)`, как `EVENT_OPTIONS` в AuditPage. |
| `actor` | Кто | `r.actor_email` моно + маленький тег роли (`teacher`/`manager`/`admin`) рядом — `<span className="status-badge status-badge--muted">` с ролью, тем же паттерном, что `status-badge` в AuditPage/StatusBadge.tsx. Если актор отсутствует (management-команда backfill без HTTP-контекста, см. бэкенд-спеку §4.2) — показываем `«Система»` приглушённым текстом, не `—` (так понятнее, чем «пусто»). `searchable: true` (icontains по email, как `actor` в фильтрах API). |
| `entities` | Затронуто | Список чипов через новый `EntityChips` (см. §7): для каждой записи `{entity_type, count, sample_id?, sample_label?}` — если `entity_type` относится к сущности с detail-маршрутом (`lesson`→`/admin/lessons/:id`, `group`→`/admin/groups/:id`, `student`→`/admin/students/:id`, `teacher`→`/admin/teachers/:id`, `direction`→`/admin/directions/:id`) и `count === 1` — рендерим `EntityLink` на конкретную запись; иначе — текстовый чип `«Посещаемость ×8»` без ссылки (у `LessonAttendance`, `Payment`, `Payroll`, `Discount`, `GroupMembership`, `PlannedLesson`, `GroupScheduleSlot`, `Account`, `AdminUserSettings` нет detail-маршрутов в SPA — проверено по `App.tsx`, там нет `/admin/payroll/:id` и `/admin/accounts/:id`). Показываем первые 2-3 чипа + `+N` при переполнении. `sortable: false`, `searchable: false` (сложный фильтр по сущности — отдельным контролом, см. §3). |
| — | (без колонки «Действие» — весь ряд кликабелен) | |

Пагинация: `serverPagination` с контрактом `{rows,total,page,page_size}`
(в точности как `AuditPage`/`useAudit`), `onRowClick={(r) => navigate('/admin/changelog/' + r.context_id)}`.

Дефолтная сортировка: `useListSearchParams({ sortBy: 'created_at', sortDir: 'desc' })`.

---

## 3. Фильтры

Из требуемых бэкендом (`actor`, `entity`, `entity_id`, `operation`,
`date_from/date_to`) — часть ложится на **per-column поиск** в `DataTable`
(как у `AuditPage`), часть требует контролов над таблицей (как `date_from/date_to`
в `PayrollPage`):

- **`actor`** (icontains по email) — текстовое поле в шапке колонки «Кто»
  (`searchable: true` без `searchOptions` → `DataTable` рисует обычный
  `<input>`, паттерн `account_email` в `AuditPage`). Синхронизация с URL —
  автоматическая через `f.actor` (per-column фильтр `useListSearchParams`).
- **`operation`** — `searchOptions` в колонке (dropdown из
  `CHANGELOG_OPERATION_LABELS`), тоже через `f.operation`, как `event` в
  `AuditPage`.
- **`entity`** — отдельный `SelectInput` (`components/form/SelectInput.tsx`)
  над таблицей (в `headerActions` пропе `DataTable`, там же где в
  `PayrollPage` лежит выбор режима/дат), опции — из новой карты
  `CHANGELOG_ENTITY_LABELS` в `lib/labels.ts` (Group/Student/Teacher/Lesson/
  Payment/... — человекочитаемые названия трекаемых моделей из бэкенд-спеки §4).
  Помнить про [[project-select-input-gotcha]] — placeholder только первым
  элементом `options`, `onChange` — нативное событие, брать `e.target.value`.
- **`entity_id`** — числовой `TextInput`/`NumberInput`, показывается/активен
  только когда `entity` выбран (иначе бессмысленный фильтр) — рядом с
  `entity`-селектом. Через `getExtra/setExtra`.
- **`date_from`/`date_to`** — пара `DateInput` (`components/form/DateInput.tsx`),
  один блок в `headerActions`, ровно как в `PayrollPage`. **Важно**: менять
  оба сразу через `setExtras({ date_from, date_to })` одним вызовом — правило
  из памяти [[project-url-state-sync]] (`setExtra` дважды подряд читает старый
  `prev` и создаёт race condition; уже есть прецедент в `PayrollPage`).
- Все non-column фильтры (`entity`, `entity_id`, `date_from`, `date_to`) —
  через `getExtra/setExtra/setExtras` из `useListSearchParams`, попадают в URL
  как top-level параметры (не через `f.*` префикс) — та же схема, что у
  `mode`/`date_from`/`date_to` в `PayrollPage`.
- **Deep-link с entity-страниц** (не обязателен в v1, но дёшев и полезен):
  на `StudentDetailPage`/`GroupDetailPage`/... добавить маленькую ссылку
  «История изменений» → `/admin/changelog?entity=student&entity_id=42` —
  переиспользует те же фильтры. Вынести как отдельный шаг (§8, Шаг D), не
  блокирует MVP.

---

## 4. Карточка операции (`ChangelogDetailPage.tsx`)

Bespoke-страница (не `DetailShell` — см. §0), маршрут `/admin/changelog/:contextId`.

**Layout сверху вниз**:

1. Кнопка «Назад» (тот же `back-btn` класс/иконка, что в `DetailShell.tsx`,
   строки 99-108) → `navigate(-1)` или `navigate('/admin/changelog')`.
2. Заголовок операции: метка операции (крупно) + `context_id` моно рядом
   (для сверки/саппорта) + время (`fmtDateTime`) + актор (email + role-тег,
   тот же рендер, что в колонке ленты).
3. Если `!revertable` — приглушённый баннер с причиной (`revert_reason` —
   поле, которое нужно закрепить в контракте: `'accounts_operation'` |
   `'no_context'` | ...), в стиле `EmptyState`, но inline (не на всю страницу):
   `<div className="entity-card" style={{opacity:.8}}>Эта операция не может быть отменена: ...</div>`.
4. Кнопка «Откатить операцию» — только `me?.role === 'admin'` и `revertable`
   (см. §1, §5).
5. Список затронутых строк, сгруппированный по `(entity_type, entity_id)`:
   для каждой группы — заголовок (иконка типа сущности + `EntityLink`, если
   маршрут есть, иначе просто текст + id) + бейдж типа операции
   (`insert`/`update`/`delete`) через уже существующие в проекте классы
   `status-badge--positive` (insert), `status-badge--info` (update),
   `status-badge--negative` (delete) — эти три тона уже определены в
   `styles/components.css` (строки 361-379), новых CSS-классов заводить не
   нужно.
6. Под заголовком группы — `DiffView` (новый компонент, §7): таблица
   поле → было → стало, **только по изменившимся полям** (бэкенд уже отдаёт
   `pgh_diff`, полный снапшот не нужно диффать на фронте). `null → значение`
   рендерится как `— → значение` (не путать пустое поле с «не показано»).
7. **Массовые операции** (регенерация плана — десятки `PlannedLesson`,
   `submitLesson` — пачка `LessonAttendance`): если в группе `entity_type`
   больше N строк (порог **5**, по аналогии с тем, как `EntityCard` уже
   сворачивается) — по умолчанию **свёрнуто** в одну строку-сводку
   `«Посещаемость: 8 записей»` с кнопкой `«Показать»`/`«Скрыть»` (локальный
   `useState`, НЕ `localStorage` — в отличие от `EntityCard`, который хранит
   collapsed глобально для всех сущностей; здесь состояние специфично для
   конкретной операции и не должно «прилипать»).
8. Если строк-событий в одной операции очень много (сотни, отчёты про
   `regenerate` за год) — на фронте ограничить рендер первыми ~200 событиями с
   кнопкой «Показать ещё» (простая клиентская пагинация массива, не серверная
   — правки в API ленты объёмом ответа детальной ручки бэкенд-спека не
   регламентирует, но VPS 2 ГБ (см. CLAUDE.md) не любит рендерить тысячи DOM
   строк разом).

---

## 5. UX отката

**Кнопка** — в шапке карточки, рядом с местом, где `DetailShell` обычно
рисует edit/delete (см. §4 п.4). Стиль — `Button` (`components/ui/Button.tsx`)
`variant="danger"`.

**Модалка подтверждения** — новый `RevertConfirmDialog.tsx`, по образцу
`ConfirmModal` в `AccountsPage.tsx` (`Dialog` + `isPending` + `danger`):

- Заголовок: «Откатить операцию?»
- Тело: метка операции, время, актор, `EntityChips` со сводкой затронутого
  (переиспользуем компонент из §2/§7), явное предупреждение: «Это отменит
  N изменений в M таблицах. Откат необратим; сам откат тоже попадёт в журнал»
  (изменение дизайна от 2026-07-07: redo убран — откатить запись отката или
  повторно откатить уже откаченную операцию нельзя, см. бэкенд-спеку §5).
- Футер: `Button variant="secondary"` «Отмена» + `Button variant="danger"`
  «Откатить» (текст меняется на «Откатываем…» при `isPending`, как в
  `AccountsPage`).

**Мутация** — `hooks/useChangelog.ts`:

```ts
revert: useMutation({
  mutationFn: (contextId: string) =>
    api<RevertResult>('POST', `/api/admin/changelog/${contextId}/revert`),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ['changelog'] });
    // см. ниже про широкую инвалидацию доменных ключей
  },
}),
```

**Инвалидация после успеха**: откат может задеть любую из трекаемых моделей
(Group, Student, Lesson, Payment, Payroll, ...) — точечно перечислять все
возможные query-keys на каждый вызов накладно и хрупко. Предлагается
консервативный подход: `qc.invalidateQueries()` **без ключа** (весь кэш) —
откат admin-only и редкое действие, стоимость лишних refetch на 2 CPU/2 ГБ VPS
пренебрежимо мала по сравнению с риском показать устаревшие данные после
изменения истории. Если backend-developer впоследствии решит, что это
избыточно — можно сузить до списка ключей по `entities[].entity_type` из
ответа детальной ручки.

**409-конфликт**: `ApiError.details` (`lib/api.ts`, уже параметризован под
`unknown`) должен нести структуру конфликтов — предложение типа для
согласования с бэкендом:
```ts
interface RevertConflict {
  entity_type: string;
  entity_id: number | string;
  field?: string;
  conflicting_context_id: string; // операция, из-за которой конфликт
  message: string;
}
```
При `err instanceof ApiError && err.status === 409` — модалка **не
закрывается**, переключается в режим конфликта: список конфликтов, каждый —
чип с `conflicting_context_id`, ссылка «Посмотреть эту операцию» →
`/admin/changelog/{conflicting_context_id}` (открывается в новой вкладке или
обычный `Link`, чтобы не терять текущую модалку — можно `target="_blank"`).
Поясняющий текст ровно как в бэкенд-спеке: «Сначала откатите более поздние
операции по этим строкам». Кнопка футера меняется на «Понятно» (закрыть).
Прочие ошибки (5xx, сеть) — через `useApiError()` toast, модалка закрывается
как в стандартном catch-паттерне `AccountsPage`.

**Success-состояние**: toast «Операция отменена» (`useToast`), модалка
закрывается. Если backend в 200-ответе отдаёт `new_context_id` (создание
новой цепочки revert-событий — уже зафиксировано в бэкенд-спеке §5 как
естественный побочный эффект триггеров) — показать в тосте/на странице ссылку
«Смотреть запись отката» на этот новый context. **Это стоит явно попросить у
backend-developer включить в ответ** `POST .../revert` — без него фронт не
сможет сослаться на созданную запись без лишнего запроса ленты.

---

## 6. Пустые/загрузочные/ошибочные состояния

- **Лента, загрузка**: `<TableSkeleton rows={12} cols={5} />` (как в
  `AuditPage`, но `cols={5}` — на одну колонку больше из-за `entities`).
- **Лента, пусто/нет совпадений**: встроенный empty-state `DataTable`
  («Ничего не найдено» + подсказка сбросить фильтры) — уже покрывает случай,
  ничего доделывать не нужно.
- **Карточка, загрузка**: `PageLoading` (`components/ui/Skeleton.tsx`).
- **Карточка, 404** (несуществующий/ещё не проиндексированный `context_id`):
  `EmptyState` с текстом «Операция не найдена» + ссылка назад на список —
  не бросать необработанное исключение.
- **Ошибки запросов** — единообразно через `useApiError()` (тот же хук, что
  использует весь остальной admin SPA), никакого кастомного error-UI не
  придумывать.
- **Нечитаемые операции** (нет метки в `CHANGELOG_OPERATION_LABELS`) — раздел
  2 уже описывает fallback (сырой ключ, не пусто).
- **Нет актора** (management-команда/backfill) — раздел 2 уже описывает
  fallback («Система»).
- **Сущность без detail-маршрута** (Payment, Payroll, Discount,
  GroupMembership, PlannedLesson, GroupScheduleSlot, Account,
  AdminUserSettings) — текстовый чип без ссылки, не пытаться собрать
  несуществующий URL.
- **Огромный diff** (JSON/длинная строка в поле) — в `DiffView`: значения
  длиннее ~200 символов показывать усечённо с кнопкой «показать полностью»
  (тот же принцип, что сворачивание массовых операций, — не рендерить сразу
  весь объём).

---

## 7. Файловая структура

Новые файлы:

| Файл | Назначение |
|---|---|
| `pages/changelog/ChangelogListPage.tsx` | Лента операций — калька `pages/audit/AuditPage.tsx` |
| `pages/changelog/ChangelogDetailPage.tsx` | Карточка операции — bespoke layout (см. §4) |
| `pages/changelog/RevertConfirmDialog.tsx` | Модалка подтверждения/конфликта отката — калька `ConfirmModal` из `pages/accounts/AccountsPage.tsx` |
| `components/changelog/DiffView.tsx` | Новый переиспользуемый компонент: таблица поле/было/стало по списку изменённых полей. Пригоден за пределами этой фичи — тот же примитив нужен, если позже понадобится diff где-то ещё (например, будущий аудит правок в других разделах) |
| `components/changelog/EntityChips.tsx` | Список чипов «затронутые сущности» — используется в 3 местах (колонка ленты, шапка карточки, тело confirm-модалки), поэтому выносится, а не копируется |
| `hooks/useChangelog.ts` | `useChangelogList(query)`, `useChangelogDetail(contextId)`, `useChangelogMutations()` — паттерн 1:1 с `useAudit.ts`/`useAccounts.ts` (`useQuery`+`keepPreviousData` для списка/деталей, `useMutation`+`invalidate` для отката) |

Изменяемые файлы:

| Файл | Правка |
|---|---|
| `App.tsx` | 2 новых `<Route>` (список + деталь) |
| `components/shell/Sidebar.tsx` | Новая иконка `NAV_ICONS['changelog']`, новая запись в `SECTIONS` (см. §1) |
| `lib/labels.ts` | `CHANGELOG_OPERATION_LABELS` (+ `_OPTIONS`), `CHANGELOG_ENTITY_LABELS` (+ `_OPTIONS`) — по образцу `ENROLLMENT_STATUS_LABELS`/`LESSON_TYPE_LABELS` в этом же файле |
| `lib/format.ts` | Вынести `fmtDateTime()` сюда из локальной копии в `AuditPage.tsx` (после этого `AuditPage` тоже переключить на импорт — маленькая попутная правка, устраняющая дублирование, раз уже трогаем этот слой) |
| `lib/shared-types.ts` | `ChangelogContext` (строка ленты), `ChangelogEventDetail` (одна row-событие с diff), `ChangelogDetail` (контекст + события + `revertable`/`revert_reason`), `RevertConflict`, `RevertResult` |

Ничего из существующих shared-компонентов не дублируется: таблица —
`DataTable`, модалка — `Dialog`, кнопки — `Button`, фильтры — `SelectInput`/
`DateInput`/`TextInput`, пагинация/URL-состояние — `useListSearchParams`,
скелетоны — `TableSkeleton`/`PageLoading`, тосты об ошибках — `useApiError`.
Единственные два новых визуальных примитива — `DiffView` и `EntityChips` —
обоснованы переиспользованием внутри самой фичи (не «ради компонента»).

---

## 8. Порядок реализации фронт-части

Соответствует фазам 2-3 бэкенд-плана (§10 дизайн-документа) — фронт не может
опережать бэкенд, т.к. эндпоинтов пока нет.

1. **Шаг A — контракт + лента (после бэкенд-фазы 1, read-API)**:
   зафиксировать с backend-developer точный JSON списка/деталей (поля
   `operation`, `entities[]`, `actor_*`, `revertable`), добавить типы в
   `shared-types.ts`, `CHANGELOG_*_LABELS` в `labels.ts`, `useChangelogList`
   в `useChangelog.ts`, `ChangelogListPage.tsx` (таблица+фильтры+пагинация),
   маршрут + пункт меню. Верифицировать: лента открывается, фильтры пишутся
   в URL и переживают reload, сортировка по времени работает.
2. **Шаг B — карточка операции**: `useChangelogDetail`, `ChangelogDetailPage`,
   `DiffView`, `EntityChips`, обработка `revertable=false` с причиной,
   сворачивание массовых групп, 404-состояние. Верифицировать на реальной
   составной операции (`submitLesson` — 4 таблицы) и на массовой
   (regenerate плана — десятки `PlannedLesson`).
3. **Шаг C — откат (после бэкенд-фазы 3, revert-endpoint)**: кнопка
   (гейт `me?.role==='admin'`), `RevertConfirmDialog`, `useChangelogMutations().revert`,
   обработка 409 (конфликты + ссылки), success-тост + инвалидация. Явно
   попросить backend-developer вернуть `new_context_id` в 200-ответе (см. §5).
   Верифицировать: простой patch, составная операция, конфликт (изменить
   строку после операции и попробовать откатить старую), запрет для manager
   (кнопка не рендерится, а прямой POST от manager должен получать 403 от
   API — проверить именно API, не только фронт).
4. **Шаг D — полировка**: deep-link «История изменений» с entity-detail
   страниц (`StudentDetailPage`/`GroupDetailPage`/...) в
   `/admin/changelog?entity=...&entity_id=...`; клиентский cap на 200 событий
   в детальной карточке с «показать ещё»; сверка с
   `docs/security-guidelines.md` чеклистом перед мержем (RBAC, CSRF на
   revert — уже покрыт общим `api()`-хелпером, который сам берёт
   `X-CSRFToken` для не-safe методов, см. `lib/api.ts`).

Каждый шаг — отдельная верификация перед следующим (конвенция проекта:
пошагово, ревью после каждого шага; коммиты — только по явной просьбе
пользователя).
