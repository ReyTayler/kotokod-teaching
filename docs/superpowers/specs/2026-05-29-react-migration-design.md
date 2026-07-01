# React Migration + Backend Clean-code — Design

**Date:** 2026-05-29
**Status:** Design approved, awaiting implementation plan
**Estimate:** 15-18 working days (with code-review iterations)

## Motivation

Текущий admin SPA (`web/admin/src/`) реализован на vanilla TypeScript + Vite — ~3000 строк, ручной cache, `innerHTML`-based рендеринг, ручная инвалидация. Teacher SPA (`public/Index.html`) — 3551 строка inline JS, унаследовано с до-TS-эпохи.

Боли, накапливающиеся с ростом:
1. **Ручная cache invalidation** (`state.cache.payroll = null` после save) — забываемая → баги вроде «после save lesson зарплата не обновляется»
2. **Circular dependencies** ES-модулей (`main.ts ↔ registry.ts ↔ entities`) — каждое добавление новой связи требует распутывания
3. **innerHTML + addEventListener** — нет реактивности, всё перерисовывается целиком, теряется состояние (открытая модалка, прокрутка)
4. **Race conditions** (счётчик `__editorGen`) — обходим вручную там, где фреймворк делает автоматически (AbortController)
5. **Дублирование между admin и teacher** — типы, helpers, calc-функции

Решение: переезд обоих SPA на React + TanStack Query (cache/server state) + React Router. Параллельно — clean-code на бэке: разбить server.js на routers + Zod-валидация на границах API.

## Goals

1. Admin SPA полностью на React, без потери функциональности (lesson grid, KOTOKOD-hero, auto-freeze, статистика по направлениям, URL-роутинг)
2. Teacher SPA полностью на React, идентичный submitLesson API contract (бэк-тесты переживают)
3. Backend: server.js → routes/ + Zod схемы на POST/PATCH, центральный error handler
4. Все 77 backend-тестов остаются зелёными
5. Visual design (КОТОКОД, light+dark theme) сохраняется 1-в-1 — переносим текущий `style.css` без изменений

## Non-goals

- Tailwind CSS — переписывать стиль слишком дорого, KOTOKOD уже хорош
- shadcn/ui — тянет Tailwind
- Redux/Zustand — TanStack Query + React useState закрывают всё
- TypeScript на бэке — отдельная задача
- Phase 5 (выпил sheets.js + googleapis) — отдельная задача #117
- Vitest + RTL frontend тесты — отложим в backlog
- Монорепо / npm workspaces — оверкилл для нашего размера

## Stack

### Frontend (admin + teacher)
- React 19 + TypeScript 5 + Vite 6 (последнее уже стоит)
- TanStack Query v5 — server state, кеш с tag-based инвалидацией
- React Router v7 — URL-роутинг, заменяет наш `lib/router.ts`
- Radix UI primitives — Dialog, DropdownMenu, Select, Tooltip, Toast, Tabs (unstyled, accessible)
- Lucide React — иконки (уже используем такой стиль)
- Forms — vanilla `useState` (формы небольшие)

### Backend
- Express 4 — остаётся
- Zod 3 — валидация POST/PATCH bodies
- Структура `routes/` с express.Router, разнесённая по сущностям

### Build/Tooling
- Vite 6 + @vitejs/plugin-react для обоих SPA
- `npm run admin:build` / `npm run teacher:build` / `npm run build` (оба)
- TypeScript path alias `@shared/*` → `../shared/*` для общих типов

## Architecture

### Целевая структура репозитория

```
journal-backend/
├─ server.js                       # thin entry (~150 строк): middleware + mount routes
├─ routes/                          # NEW
│  ├─ teacher.js                   # /api/validateToken, /api/getData, /api/submitLesson, ...
│  ├─ admin/
│  │  ├─ index.js                  # собирает sub-routers под /api/admin
│  │  ├─ auth.js                   # /login, /logout
│  │  ├─ students.js               # CRUD + /:id/stats
│  │  ├─ groups.js                 # CRUD + slots
│  │  ├─ teachers.js, tokens.js, directions.js
│  │  ├─ lessons.js                # CRUD + attendance + /:id/full
│  │  ├─ payroll.js                # list + summary + edit
│  │  └─ memberships.js            # CRUD
│  └─ middleware/
│     ├─ admin-auth.js             # requireAdmin
│     ├─ async-wrap.js             # asyncHandler (текущий adminWrap)
│     └─ validate.js               # zod-валидация helper
├─ shared/                          # NEW — кросс-проектные типы и схемы
│  ├─ types.ts                     # Student, Group, Lesson, …
│  ├─ schemas.js                   # Zod schemas (read by бэк) + .ts for типов на фронте
│  └─ tsconfig.json
├─ services/                        # без изменений — admin-repo.js, db.js, calculator.js, admin-auth.js
├─ db/migrations/                   # без изменений
├─ scripts/                         # без изменений
│
├─ web/admin/                       # ПЕРЕПИСАН на React
│  ├─ index.html
│  ├─ vite.config.ts
│  ├─ tsconfig.json
│  └─ src/
│     ├─ main.tsx, App.tsx
│     ├─ style.css                  # перенесён 1-в-1 из текущего web/admin/src/style.css
│     ├─ lib/                       # api.ts, types.ts (re-export @shared), format.ts
│     ├─ providers/                 # QueryProvider, AuthProvider, ThemeProvider
│     ├─ hooks/                     # useStudents, useStudentMutation, ... per сущность
│     ├─ components/                # ui/, table/, detail/, form/, shell/
│     └─ pages/                     # students/, groups/, ... — один файл = один URL
│
├─ web/teacher/                     # НОВЫЙ — React teacher SPA
│  ├─ index.html
│  ├─ vite.config.ts
│  ├─ tsconfig.json
│  └─ src/
│     ├─ main.tsx, App.tsx
│     ├─ style.css                  # перенесён из public/styles.css
│     ├─ lib/, providers/, hooks/, components/, pages/
│
├─ public/
│  ├─ admin-dist/                   # Vite output для admin
│  └─ teacher-dist/                 # Vite output для teacher (NEW, заменяет Index.html+styles.css)
│
└─ docs/superpowers/                 # spec + plan
```

### Admin SPA — детали

См. секцию 3 общего обсуждения. Ключевое:

- **8 entity-страниц** в `pages/<entity>/` — `<Entity>ListPage.tsx`, `<Entity>DetailPage.tsx`, `<Entity>Form.tsx`, плюс entity-specific (LessonGrid, StudentStats, GroupMembers)
- **Routing** через React Router v7:
  - `/admin` → redirect на `/admin/students`
  - `/admin/<section>` → list
  - `/admin/<section>/:id` → detail (tokens: `:id` это token-строка)
  - `/admin/archive` → archive
- **AuthGate** компонент: checks `useQuery(/api/admin/teachers)` → 401 redirect на `/login`
- **AppShell** компонент: sidebar + `<Outlet />` для main
- **Все мутации** через `useMutation` с автоинвалидацией: `qc.invalidateQueries({ queryKey: ['<entity>'] })`
- **Cookie-auth** — те же HttpOnly cookies, никаких токенов в localStorage

### Teacher SPA — детали

Простой flow: token → выбор группы → submit lesson. Структура `pages/`:

- `TokenLoginPage.tsx` — ввод XXX-XXX-XXX, POST `/api/validateToken`
- `HomePage.tsx` — список своих групп (из `/api/getData`)
- `SubmitLessonPage.tsx` — выбор группы + дата + ссылка + attendance (toggles)
- `SubmitLessonSuccessPage.tsx` — «Зафиксировано», сумма, дата DD.MM.YYYY
- `SubstitutePage.tsx` — замена за другого препода (через `/api/getAllData`)
- `ReportPage.tsx`, `SchedulePage.tsx`

Token хранится в `TokenProvider` context — memory + опционально localStorage.

### Backend — детали

См. секцию 2. Каждый router использует `validate(schema)` middleware для POST/PATCH. Пример:

```js
router.post('/', validate(createStudentSchema), async (req, res) => {
  res.status(201).json(await adminRepo.createStudent(req.validated));
});
```

Zod-схемы в `shared/schemas.js`. Для frontend они же даёт типы:

```ts
import { z } from 'zod';
import { createStudentSchema } from '@shared/schemas';
type CreateStudentInput = z.infer<typeof createStudentSchema>;
```

### Cross-cutting

- **Shared types** — в `shared/types.ts`. Бэк не использует (он на JS), но фронт оба SPA импортит
- **Shared schemas** — Zod, реализуется в `shared/schemas.js` (бэк требует .js для Node-require) с co-located `schemas.ts` для типов через `z.infer`. Альтернативно: Vite Node-плагин для импорта .ts из бэка, но это сложнее
- **Path alias**: в `web/admin/tsconfig.json` и `web/teacher/tsconfig.json` — `"@shared/*": ["../../shared/*"]` (web/<spa> на 2 уровня глубже корня)
- **calcPayment дублируется** в `services/calculator.js` (бэк, authoritative) и в `web/teacher/src/lib/calc-payment.ts` (preview только). Минимальный код, не стоит расшаривать
- **fmtDate, MSK helpers** — дублируем в обоих SPA, маленькие
- **UI компоненты, hooks** — НЕ шарим. Admin и teacher имеют разные UX, разную сложность

### Импорты + tooling

- `npm i -D @vitejs/plugin-react react @types/react react-dom @types/react-dom @tanstack/react-query @tanstack/react-query-devtools react-router-dom @radix-ui/react-dialog @radix-ui/react-dropdown-menu @radix-ui/react-select @radix-ui/react-tooltip @radix-ui/react-toast @radix-ui/react-tabs lucide-react zod`
- Backend: `npm i zod`
- В `web/<spa>/vite.config.ts` добавить `import react from '@vitejs/plugin-react'` + `plugins: [react()]`
- В `tsconfig.json` каждого SPA: `"jsx": "react-jsx"`, `"jsxImportSource": "react"`

## Process

### Phase order

| # | Phase | Days | Subagents | Output |
|---|---|---|---|---|
| R0 | Backend split + Zod | 2-2.5 | `backend-developer` → `code-reviewer` | routes/, schemas/, shared/, тонкий server.js. 77/77 тестов зелёные. |
| R1 | React foundation | 1.5 | inline (focused setup) | Providers, Router, AppShell, AuthGate, LoginPage. Все 8 entity-страниц как пустые stubs. |
| R2 | Admin entity pages | 4-5 | 3× `frontend-developer` параллельно | Все 8 сущностей с list, detail, form, mutations, инвалидацией |
| R3 | Admin polish + smoke | 1 | `code-reviewer` + я | Удалены старые модули, smoke по docs/admin-smoke-tests.md, обновлён CLAUDE.md |
| R4 | Teacher SPA | 3.5-4 | 1× `frontend-developer` | Token login, выбор группы, submit lesson + остальное |
| R5 | Cross-SPA verification | 0.5-1 | `code-reviewer` | Final pass, обновление CLAUDE.md, удаление мёртвых файлов |
| **Total** | | **12-15** | | |

С учётом ревью-итераций: **15-18 дней реалистично**.

### R2 параллельное разбиение

| Agent | Сущности | Reasoning |
|---|---|---|
| A | `students` + `memberships` | Memberships обслуживают UI ученика, связаны |
| B | `groups` + `lessons` + `payroll` | Lesson grid в group detail → lesson edit → payroll. Тесно связанные. |
| C | `teachers` + `tokens` + `directions` + `archive` | Простые CRUD, без cross-зависимостей |

Каждому даю:
- Готовые `shared/types.ts` и Zod-схемы (созданы в R0)
- Готовые `web/admin/src/components/ui/`, `form/`, `table/`, `detail/`, `shell/` (созданы в R1)
- Список TanStack Query хуков для его сущностей (готовы в R1)
- Acceptance criteria из CLAUDE.md (lesson grid поведение, auto-freeze, KOTOKOD-hero, fmtDate DD.MM.YYYY)
- ✘ НЕ трогать `style.css` и общие компоненты — только свои `pages/<entity>/`

### Quality gates между фазами

| Gate | Что проверяется |
|---|---|
| R0 | `npm test` → 77/77, curl-smoke `/api/admin/*` (login, GET, POST с валидным/невалидным body, PATCH, DELETE) |
| R1 | Login в браузере, AppShell рисуется, переходы между пустыми страницами, theme работает |
| R2 | По каждой сущности: list рендерится, detail открывается, CRUD работает, кеш-инвалидация после mutation работает (видно мгновенно). Lesson grid создаёт урок, statistics ученика рендерится. |
| R3 | Полный smoke по `docs/admin-smoke-tests.md` (login + все секции + lesson grid + payroll rebuild). `code-reviewer` подтверждает что инварианты CLAUDE.md соблюдены. |
| R4 | Teacher SPA: token → выбор группы → submitLesson → success. Comparing payload с baseline — идентичен. `incrementCounters` шаг для half-lesson корректен. |
| R5 | Удалены `public/admin.html`, `public/admin-app.js`, `public/Index.html`, `public/styles.css`, старый `web/admin/src/components|entities|lib`. Обновлён CLAUDE.md. Build production обоих SPA OK. |

### Risk mitigation

| Risk | Mitigation |
|---|---|
| Регрессия submitLesson (business critical) | После R4 — сравнить POST payload новой формы и старой через curl-replay. Tests services/db.test.js и admin-repo.test.js проверяют core logic. |
| Cookie auth ломается в dev (CORS) | Vite proxy `/api → :3000` уже работает в текущем admin, переиспользуем. |
| TanStack Query кеш не инвалидируется | Code-reviewer проверяет каждую mutation на наличие `invalidateQueries`. Pattern: `useEntityMutation()` возвращает все CRUD сразу. |
| Параллельные агенты в R2 конфликтуют | `shared/`, `components/`, `hooks/`, `style.css` создаются в R1 ДО разделения. Агенты только читают эти файлы, пишут в `pages/<entity>/`. |
| Стили ломаются | Переношу `style.css` 1-в-1. Классы те же (`entity-card`, `link-card`, `dir-card`). React компоненты используют `className="..."` как раньше. |
| Bundle size взрыв | После R3 проверяю build. Если >200 KB gzipped — лениво-загружаю роуты через `lazy(() => import(...))`. |
| Git tag/rollback | Перед R0 — `git tag pre-react-migration` (если в git). Если не в git — backup папки `public/admin-dist`, `web/admin`, `services`, `server.js` в `_backup/`. |

### Clean-code procedure

Применяется во время миграции, не отдельной фазой:

1. **Удалить устаревшее** (после соответствующего gate):
   - После R3: `public/admin.html`, `public/admin-app.js`, старый `web/admin/src/{components,entities,lib/registry.ts}`
   - После R4: `public/Index.html`, `public/styles.css`
   - Дубликаты `calcPayment` → консолидировать
   - Мёртвые `any` где можно типизировать
2. **Naming convention**:
   - Hooks: `useStudent` (one) / `useStudents` (list) / `useStudentMutation()` (CRUD bundle)
   - Pages: `<Entity>ListPage.tsx`, `<Entity>DetailPage.tsx`, `<Entity>Form.tsx`
   - Components: PascalCase, файл = export default
3. **Размер файлов**: 200-300 строк max. Если страница больше — выносить sub-компоненты в `pages/<entity>/*.tsx`
4. **Backend conventions**:
   - Routers тонкие — только маршрутизация + Zod + вызов adminRepo
   - Все валидации через `validate(schema)`, никаких inline `if (!body.x)`
   - Centralized error handler (`app.use((err, req, res) => ...)`)

### Subagent briefing template

Каждому subagent'у даю стандартный prompt с:
1. **Цель фазы**: что выходит
2. **Готовые файлы**: на которые опираться (импорты, переиспользуемые компоненты)
3. **Acceptance criteria**: тесты прохождения, инварианты CLAUDE.md
4. **Запреты**: что НЕ трогать (общие модули, бэк, тесты)
5. **Verification**: `npm run admin:typecheck`, `npm run admin:build` должны пройти
6. **Report format**: краткий отчёт, не более 300 слов

## Open questions / future tasks

После завершения миграции лежат в backlog:
- #107 — half-lesson hardcode (`lesson_duration_minutes:90`, `isHalf=false`)
- #112-115 — расширения статистики (общий дашборд, date-range, динамика, графики)
- #117 — Phase 5 cleanup (`services/sheets.js`, `googleapis`)
- #119 — Deploy на Beget VPS
- #121 — Audit-колонки memberships
- (новые) — Vitest + RTL frontend тесты, если найдём регрессии

**Заменяется этой миграцией:**
- #116 (удалить public/admin.html + admin-app.js) — войдёт в R3 cleanup
- #118 (Teacher SPA на TS+Vite) — заменяется React-версией в R4

## Acceptance criteria для миграции

Миграция считается готовой когда:

1. ✅ Старые файлы удалены: `public/admin.html`, `public/admin-app.js`, `public/Index.html`, `public/styles.css`, `web/admin/src/components`, `web/admin/src/entities`, `web/admin/src/lib/registry.ts`
2. ✅ `npm run admin:build` + `npm run teacher:build` без ошибок
3. ✅ `npm run admin:typecheck` + `npm run teacher:typecheck` — 0 ошибок
4. ✅ `npm test` → 77/77 проходят
5. ✅ Admin smoke: login → CRUD всех 8 сущностей → lesson grid создание → payroll отображение → archive → theme toggle → URL роутинг
6. ✅ Teacher smoke: token login → submitLesson → success screen → проверка `incrementCounters` и `payroll` insert в БД (через curl reply)
7. ✅ CLAUDE.md обновлён под новую структуру
8. ✅ `docs/admin-smoke-tests.md` обновлён под React (если разметка/классы поменялись)
