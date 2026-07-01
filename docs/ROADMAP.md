# ROADMAP — journal-backend (единый план развития платформы)

**Назначение:** один источник правды по ВСЕМ планам платформы — что сделано, что в работе,
что впереди. Консолидирует: таблицу фаз `CLAUDE.md`, `docs/BACKLOG.md`, перф-аудит
(`docs/superpowers/specs/2026-06-04-performance-load-audit.md`), `docs/deploy-runbook.md`,
а также forward-looking пункты из всех спек/планов в `docs/superpowers/`.

**Как читать:** разделы отсортированы по приоритету/триггеру. Глубокая детализация
по каждому пункту — в источнике, указанном курсивом. Этот файл — мастер-индекс.

**Легенда:** ✅ сделано · ⏳ в работе/частично · ⬜ запланировано
Триггеры: 🔴 блокер перед действием · 🟣 прод · 🟡 2-й управляющий · 🟢 фаза миграции · ⚡ производительность · 🔵 фича · 🧪 качество/техдолг

---

## ✅ Сделано (контекст)

Миграция и платформа (детали — `CLAUDE.md` таблица фаз + спеки):

| Блок | Статус |
|---|---|
| Phase 0–2 — PG foundation, repository layer, backfill Sheets→PG | ✅ |
| Phase 3a/3b — cutover teacher SPA + admin CRUD (lessons/attendance/payroll) | ✅ |
| Phase 4.1–4.3 — visual refresh, admin backend + SPA | ✅ |
| Phase 6 / R1 / R2 — admin SPA на TS+Vite → React 19 (полные страницы) | ✅ |
| Payments + Discounts (D1–D3) | ✅ |
| Server-side pagination + URL state sync | ✅ |
| Design system refactor (tokens, custom form-элементы) | ✅ |
| Admin Dashboard (FIFO KPIs + период от/до + помесячные графики) + ErrorBoundary | ✅ |
| Расширения статистики (общий дашборд, date-range, динамика, графики) — *было #112–115* | ✅ |
| **Backend architecture cleanup** — `admin-repo`→`services/repo/*`, `db.js`→infra+`teacher-repo`, удаление мёртвого кода | ✅ |
| **RBAC + унифицированный вход** — единый `/login` (роль+email+пароль+2FA), таблица `accounts`, роли teacher/manager/admin, `security_audit_log`, consent-крючок (`students.consent_*`), email-OTP через Beget SMTP (миграции 013–015) | ✅ |
| **Перф: индекс `lesson_attendance(student_id)` (миграция 012) + конфиг пула pg** | ✅ |
| **Docs: перф-аудит + deploy-runbook** | ✅ |

---

## 🔴 Блокер — сделать ДО правки типов уроков

- ⬜ **Whitelist `lesson_type` в формуле баланса.** Добавить `AND l.lesson_type IN ('regular','substitution','reschedule')` в `_balanceForDirection` и `getStudentBalance`. Сейчас эффект нулевой, но при появлении `free_trial`/`cancelled`/`makeup` баланс молча «уедет». *Файл: `services/repo/payments.js`. Усилия: 1 мин. (BACKLOG 🔴)*

---

## 🟣 Production — ближайший крупный блок

- ⬜ **git** — `git init` + `.gitignore` (node_modules, `.env`, `service-account-key.json`, `public/admin-dist/`, логи) + baseline-коммит, далее коммит на каждый шаг. Самый дешёвый выигрыш по прод-безопасности (откат/история/diff). *Отложен пользователем. Усилия: 15 мин. (BACKLOG 🟣)*
- ⬜ **Security-хардеринг (код, перед катом):**
  - CORS whitelist вместо открытого `cors()`;
  - ✅ rate-limit на вход (`express-rate-limit` на `/api/auth/login`, `/login/2fa`, `/2fa/email/send`) — сделано в RBAC; ⚠️ per-IP, см. NAT-техдолг ниже;
  - (опц.) Zod-валидация `:id`-параметров (`/students/abc` сейчас → 500 вместо 400).
  *Усилия: 30–40 мин. (BACKLOG 🟣)*
- ⬜ **Деплой на Beget VPS** (Ubuntu 22.04, 2 ядра/2 ГБ/30 ГБ, без Docker) — по готовому чеклисту. Включает перф-пункты №3/№4. *Полная инструкция: `docs/deploy-runbook.md`.*
  - ⚡ nginx + gzip/brotli + immutable-кэш `/admin/assets/*` + TLS (certbot), не раздавать `.map`;
  - ⚡ тюнинг PostgreSQL под 2 ГБ (`shared_buffers`/`effective_cache_size`/`work_mem`);
  - systemd-сервис, бэкапы `pg_dump` (cron, ротация 7 дней), smoke-проверки.

---

## 🟡 Когда появится 2-й управляющий

- ✅ **Роли + единый вход + `GET /api/auth/me`** (RBAC + 2FA + audit-log + accounts + consent — см. раздел «Сделано» и `docs/superpowers/specs/2026-06-06-rbac-unified-auth-design.md`). Auth теперь — таблица `accounts` (email-логин, bcrypt, роль), cookie `session` `{account_id, role}`, `AuthProvider` тянет `GET /api/auth/me`. *Осталось из перф-аудита п.4: ограничение FIFO-дашборда на owner-уровень при росте числа управляющих.*
- ⬜ **Soft-delete payments + audit-trail.** Сейчас `DELETE /payments/:id` физически стирает запись → потеря аудита и «уезжающие» задним числом отчёты. Миграция: `voided_at/voided_by/void_reason`; формулы баланса `AND voided_at IS NULL`. *Файлы: новая миграция, `services/repo/payments.js` (deletePayment), `routes/admin/payments.js`, `StudentBalanceBlock.tsx`, `usePayments.ts`. Усилия: 1–2 ч. (BACKLOG 🟡)*
- ⬜ **UX `cap_exceeded` в PaymentModal + freshen-on-open.** Refetch при открытии модалки + конкретное сообщение вместо «что-то пошло не так». *Файл: `web/admin/src/pages/payments/PaymentModal.tsx`. Усилия: 30 мин. (BACKLOG 🟡)*
- ⬜ **`submitted_by_token` = `admin:<username>`** при создании урока из админки (сейчас хардкод `'admin-imported'`). После `/me`. *Файл: `LessonEditor.tsx`. Усилия: 5 мин. (BACKLOG)*
- ⬜ **(опц.) Общий `admin_audit_log`** — таблица + endpoint (кто/что менял), undo/история. *Упоминается в спеках 4.3/4.4 как опциональное. Усилия: ~день.*

---

## 🟢 Фазы миграции

- ✅ **Платформа Фаза 1 — каркас NestJS.** Пустой Nest (Fastify-адаптер) поднят рядом с Express на `NEST_PORT` (3001): `ConfigModule`+Zod-env, `nestjs-pino`, `@fastify/{helmet,cors,rate-limit,cookie}`, `DbModule` (общий пул), `AuthGuard`+`RolesGuard` на **общей HMAC-cookie** с Express. Делят один PG и формат сессии — keystone strangler-fig. *План: `docs/superpowers/plans/2026-06-08-phase1-nest-scaffold.md`.*
- ⏳ **Платформа Фаза 2 — перенос ядра Express → чистый NestJS** (конечная цель — снести Express полностью). Каноничная структура `modules/` + `common/` + `database/` (по паттернам NestJS); SQL портируется дословно из `services/repo/*.js`, e2e сверяются с Express один-в-один. **Перенесено:** `modules/groups` — **полный CRUD** `/api/admin/groups` (чтение + запись POST/PATCH/DELETE, роли manager/admin). Валидация — `nestjs-zod` на существующих Zod-схемах `shared/schemas.js`; общий `AllExceptionsFilter` переводит ошибки валидации и БД в HTTP-коды как Express (карта `PG_ERRORS` вынесена в `shared/pg-errors.js`, общая на оба рантайма). Регресс 146/146. Express-роут групп активен до cutover (nginx). *Планы: `docs/superpowers/plans/2026-06-08-phase2-groups-module.md` (чтение), `…-groups-write.md` (запись). Дальше: Students/Lessons/Finance/Auth по одному.*
- ⏳ **Phase 5 — выпил Sheets-кода.** Частично сделано (`repository.js` + мёртвые public-файлы удалены). Осталось: `services/sheets.js`, `services/cache.js`, `googleapis` из `package.json`, `service-account-key.json`, env `DUAL_WRITE_ENABLED`/`READ_FROM`, раздел «Sheets-инварианты» из CLAUDE.md. Решить судьбу `scripts/backfill-*` (скорее оставить как архив). *Risk низкий (PG уже источник правды). Усилия: ~день. (BACKLOG 🟢)* **🔒 ИБ-релевантно: убирает передачу ПДн граждан РФ во внешний сервис вне РФ → закрывает пункт локализации 242-ФЗ (см. `docs/compliance-152fz-checklist.md`).**
- ⬜ **Phase 7 — Teacher SPA на React (R4).** Сейчас `public/Index.html` — vanilla JS ~2500 строк. Мигрировать если будут активные правки teacher-UI / для единого Vite-pipeline. *Усилия: 2–3 дня, не приоритет. (BACKLOG 🟢)*

---

## ⚡ Производительность (оставшееся; обоснование — перф-аудит)

- ⬜ **nginx gzip + immutable-кэш** — см. 🟣 деплой (`deploy-runbook.md`). Бандл 570 КБ → ~150 КБ; повторные заходы ~0.
- ⬜ **PG-тюнинг под 2 ГБ** — см. 🟣 деплой.
- ⬜ **TTL-кэш `readAllStudents` (дисплейные teacher-эндпоинты) + развязка `submitLesson`** от него. `report`/`schedule`/`getData` → из памяти ~1 мс; `submitLesson` 100–200 мс → ~10–30 мс. ⚠️ `lesson_number` (natural key + счётчики) **нельзя из кэша** — брать «max lessons_done» свежим точечным запросом. *Триггер: когда преподов реально много. Усилия: пара часов + тест. (перф-аудит п.5)*
- ⬜ **(опц.) Серверный TTL-кэш дашборда 30–60с** — только если дашборд останется массовым; при ролях (🟡) не нужен. *(перф-аудит п.6)*
- *Принцип (в CLAUDE.md): при любой правке оценивать поведение при ×10 данных и под конкуренцией; CPU-bound JS над большими выборками — вне горячего пути.*

---

## 🔵 Фичи и расширения (без жёсткого триггера)

- ⬜ **Revenue report** — `GET /api/admin/revenue?month=YYYY-MM`: группировка по направлению/ученику, сравнение с прошлым месяцем, CSV. *Файлы: новый `routes/admin/revenue.js`, новый `services/repo/revenue.js` (или расширение `repo/payments.js`), UI. Усилия: ~день. (BACKLOG 🔵, спека payments)*
- ⬜ **Страница всех оплат** (server-side pagination по рецепту listLessons) — когда понадобится «полная история оплат» для бухгалтерии. *Усилия: 4–6 ч. (BACKLOG 🔵)*
- ⬜ **Промокоды как сущность** — таблица `promo_codes` + `payments.promo_code_id`, учёт «выручка до/после скидок». *Усилия: ~день. (BACKLOG 🔵)*
- ⬜ **Оплата с привязкой к группе** (не только направлению) — если в направлении появятся группы с разной ценой. *Усилия: 2–3 ч. (BACKLOG 🔵)*
- ⬜ **Bulk-оплата за несколько направлений** одной квитанцией. *Усилия: 4–6 ч. (BACKLOG 🔵)*
- ⬜ **Алерты «баланс в минусе»** в sidebar/dashboard (бейдж с количеством должников). *Усилия: 2 ч. (BACKLOG 🔵)*
- ⬜ **Settings: расширить на payroll/archive** (DnD-колонки сейчас на 5 сущностях). *Усилия: 30 мин/сущность. (BACKLOG 🔵)*
- ⬜ **Контекстный поповер «настройка колонок»** над таблицей (альтернатива странице Settings). *Усилия: 1–2 ч. (BACKLOG 🔵)*
- ⬜ **Универсальный конфигуратор CSV-отчётов (мини-BI)** — реестр датасетов/полей + безопасный построитель запросов (обобщение `pagination.js`), JSON-конфиг отчёта, `/api/admin/reports/*`, фронт-конструктор. Фазами. *Усилия: фаза 1 ~1.5–2 дня. (BACKLOG 🔵)*
- ⬜ **Редактируемый экспорт дашборда** — диалог настройки CSV (метрики/раскладка/разделитель/BOM). Облегчённая версия мини-BI. *Усилия: 2–3 ч. (BACKLOG 🔵)*
- ⬜ **Экспорт графика в PNG** (`html-to-image`, проверить совместимость с React 19). *Усилия: ~1 ч. (BACKLOG 🔵)*

---

## 🧪 Качество и техдолг

- ⬜ **HTTP-level (supertest) тесты admin-роутов** — сейчас покрыт repo-слой и чистые функции, но нет интеграционных тестов на гейтинг ролей/валидацию на уровне HTTP (`/api/admin/*`, `/api/auth/*`). *Триггер: перед прод-катом RBAC. (RBAC-фича, техдолг)*
- ⬜ **Audit изменения согласия (consent).** Сейчас `students.consent_*` правится без записи в `security_audit_log` — нет следа «кто/когда менял согласие». Добавить событие в audit при изменении consent. *Файлы: `routes/admin/students.js`, `services/audit.js`. ИБ-релевантно (152-ФЗ).*
- ⬜ **Rate-limit `/login` и NAT.** Per-IP лимитер может задевать пользователей за общим NAT (один внешний IP → общий счётчик). Рассмотреть лимит по email/аккаунту в дополнение к IP. *Файл: `routes/auth.js`. (RBAC-фича, техдолг)*
- ⬜ **Удалить `routes/middleware/require-admin.js`** — legacy shim, после RBAC не используется (гейтинг через `services/auth.js`). *Усилия: 5 мин.*
- ⬜ **Vitest + RTL frontend-тесты** — сейчас покрыт только бэк (repo + чистые функции). Роуты и React-компоненты без автотестов. *Триггер: при регрессиях / перед активной разработкой UI. (react-migration спека, future tasks)*
- ⬜ **Audit-колонки `group_memberships`** (#121) — когда/кем менялись. *(react-migration backlog)*
- ⬜ **Half-lesson hardcode в teacher SPA** (#107) — `submitLesson` определяет `isHalf` регуляркой `/45 минут/` по имени группы; завязать на `lesson_duration_minutes` группы (как в admin). *Файл: `routes/teacher.js`.*

---

## Источники (где глубокая детализация)

- `docs/BACKLOG.md` — развёрнутые карточки задач с триггерами (🔴🟡🟣🟢🔵).
- `docs/deploy-runbook.md` — пошаговый деплой (nginx/PG/systemd/certbot/бэкапы).
- `docs/superpowers/specs/2026-06-04-performance-load-audit.md` — перф-аудит + замеры.
- `docs/superpowers/specs/` — design-документы по каждой фазе/фиче.
- `docs/superpowers/plans/` — implementation-планы (в основном исполнены).
- `CLAUDE.md` — архитектура, инварианты, соглашения, таблица фаз.

*Поддержка: при появлении новой задачи — добавлять сюда строкой со статусом/триггером; развёрнутую карточку (если нужна) — в `BACKLOG.md` и ссылаться.*
