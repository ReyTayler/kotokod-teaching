# journal-backend

Сервер учёта посещаемости для школы KOTOKOD. Единый вход `/login` с выбором роли + 2FA; teacher SPA `/teacher` (vanilla JS) и admin SPA `/admin` (React 19 + TanStack Query v5 + React Router v7). Всё на PostgreSQL.

> **⚠️ Бэкенд перенесён на Python Django+DRF (`journal_django/`). Express и Nest-каркас УДАЛЕНЫ** (2026-06-11, раздел 08 миграции). Историческое описание Express/routes/Nest ниже — для справки по доменным инвариантам, но самих файлов (`server.js`, `routes/`, `src/`) больше нет. Актуальный бэкенд — `journal_django/` (см. `docs/python-plan/`, `deploy/`). В корне остались только: admin SPA-сборка (`web/`, `public/`) и Node dev-инструменты backfill Sheets→PG (`scripts/`, `services/{db,sheets,auth,calculator,pagination,repo/accounts}.js`).

## 🔒 Безопасность — ОБЯЗАТЕЛЬНО

**Полный свод правил: [`docs/security-guidelines.md`](docs/security-guidelines.md)** — читать перед добавлением ЛЮБОЙ фичи/правки; там же чеклист для PR.

Самое критичное (нарушение = блокер):
- **RBAC**: DRF default = `AllowAny`. КАЖДАЯ новая вьюха ОБЯЗАНА задать `permission_classes` (`IsAdmin`/`IsManagerOrAdmin`/`IsTeacher`). Забыл → эндпоинт открыт всем. Доступ проверяется на API, не только на фронте (фронт-guard = UX/defense-in-depth).
- **Auth**: JWT только в HttpOnly-cookie (не в JS/localStorage); токены — через `issue_tokens_for`/`set_auth_cookies`. Отзыв — инкремент `token_version` (при смене/сбросе пароля и 2FA). Свою аутентификацию не изобретать.
- **CSP `script-src 'self'`**: НИКАКИХ inline-`<script>`, `onclick=`, `eval`. Весь JS — внешним файлом same-origin. Внешний origin (CDN/API/шрифты) — только с обновлением CSP.
- **CSRF**: мутирующие методы шлют `X-CSRFToken`; не ставить `@csrf_exempt`.
- **Rate-limit** (Django + nginx) на всех auth/OTP/reset-эндпоинтах.
- **SQL** только параметризованный (`%s`); идентификаторы — из whitelist.
- **Секреты** только из окружения; не коммитить (`.env`, ключи, дампы `backups/`, ПДн). Аудит чувствительных действий — `log_event`, без секретов в `meta`.

## Критичные соглашения

**Не использовать git и docker, работа ведётся в рамках локальной разработки**

**Эталонная структура проекта**: так как в основе проекта лежит Python Django+DRF, необходимо строго соблюдать структуру для проекта, которая считается эталонной для такого фреймворка из документации и best practice.

**Не придумывать "велосипед"**: использовать максимум возможностей фреймворков, которые указаны в проекте, не писать всё с нуля, если это уже было придумано в самом фреймворке (пример - не использовать свою систему аутентификации и авторизации, когда есть встроенные механизмы от Django).

**Всегда опираться на документации и существующие паттерны**: не выдумывать что-то своё, использовать всегда знания, в первую очередь, из официальных документаций к используемым в проекте инструментам.

**Быть строгим senior-разработчиком**.

**Порядок mount в server.js**: `/api/auth` → `/api/admin` → `/api`. Admin обязан стоять ДО teacher-guard, иначе 403.

**DATE type-parser**: `setTypeParser(1082, v => v)` — DATE приходит строкой YYYY-MM-DD. Без этого уезжает на день назад на MSK.

**`payments` immutable**: только POST/DELETE, никакого PATCH. `total_amount = unit_price × subscriptions_count` — CHECK в БД + пересчёт на сервере. `unit_price` округляется до копеек ДО умножения.

**Half-lesson**: `duration=45min → 0.5 урока`, иначе 1.

**Балансы выводятся, не хранятся**: `getStudentBalance()` = `purchased - attended` per direction.

**FIFO-финансы**: `computeFifo` (services/fifo.js). Цена урока = `total_amount/(subscriptions_count×4)` конкретной оплаты. Guard: оплаты с `subscriptions_count=NULL/0` пропускаются (→ Infinity ломает суммы). Подробнее: `docs/finances.md`.

**Paginator**: пагинация используется встроенная от фреймворка, никаких постоянных пагинаций от SELECT.

**Sort-dir bug pattern**: `(val==='asc'||val==='desc') ? val : default` — чинить в обоих местах: `parsePaginationRequest` и `paginate()`.

**ErrorBoundary key**: `key={location.pathname}`, NOT `key={location.key}` (последнее ремоунтит на каждый setSearchParams → потеря фокуса инпутов).

**`.data-table--loading`**: гасить `pointer-events` только на `tbody`, не на всей таблице.

**`placeholderData: keepPreviousData`** обязателен во всех server-paginated хуках.

**Native form-элементы запрещены** в admin SPA: использовать `SelectInput`, `DateInput`, `Checkbox`, `Combobox` из `components/form/`. Enum-labels — только из `lib/labels.ts`.

**Design tokens** — единственный источник: `journal_django/frontend/admin-src/src/styles/tokens.css`. Никаких hardcoded цветов/радиусов/отступов. Подробнее: `docs/design-system.md`.

**`AuthProvider`**: поле `me`, не `user`. `GET /api/auth/me` возвращает **плоский** объект (`{ account_id, email, role, teacher_id, name, twofa_enabled }`) — БЕЗ обёртки `{ me: {...} }`; `api<Me>()` отдаёт его как есть.

## Конфигурация (.env)

```
DATABASE_URL=postgresql://journal:...@localhost:5432/journal
ADMIN_COOKIE_SECRET=          # 128-hex, обязателен
SMTP_HOST/PORT/USER/PASS/FROM # Beget SMTP для email-OTP
PORT=3000
NODE_ENV=production           # включает Secure cookie
PG_POOL_MAX=20                # опц.
# Legacy (Phase 5):
STUDENTS_SPREADSHEET_ID=
JOURNAL_SPREADSHEET_ID=       # нужен для backfill-payments
```

## Тесты

`node --test` (97+ тестов): auth, twofa, audit, accounts, admin-repo, fifo, calculator, db, teacher-repo, backfill-scripts, parse-time, sync-failures.

## Статус фаз

Всё до Phase R2 + Payments/Discounts + Design system + RBAC — **✅**. Phase 5 (удалить Sheets) — ⏳ частично. Phase 7 (teacher SPA на React) — ⏳ опционально.

## Производительность (учитывать при любой правке)

VPS 2 CPU / 2 ГБ под 50–100 учителей и 10–15 admin. Не читать «всё» там, где нужна часть. Индексы под реальные предикаты (PG не индексирует FK). Пагинация везде.

## Pre-deployment / Backlog

CORS whitelist (сейчас открыт), rate-limit на `/login`, Beget VPS deploy (Ubuntu 22.04, без Docker), soft-delete payments. Структурированный backlog: `docs/BACKLOG.md`.
