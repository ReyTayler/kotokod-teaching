# Миграция бэкенда KOTOKOD: Node → Python (Django + DRF)

Инструкции для агентов-исполнителей. Каждый файл `NN-*.md` — самодостаточный бриф на один раздел.
Реализация ведётся **по одному разделу с паузой на ревью** (e2e-diff + code-review после каждого).

## Цель

Переписать бэкенд школы KOTOKOD с Node.js (Express + начатый NestJS) на **Python Django + DRF**,
отвечающий на те же запросы **байт-в-байт**. Фронтенд (admin SPA React 19, teacher SPA vanilla JS,
страница логина) остаётся как есть. Стратегия — **strangler-fig**: Django поднят параллельно Express
на **той же** PostgreSQL-базе (`managed=False`), разделы переносятся по одному, cutover на nginx — по готовности.

## Где код

- Новый бэкенд: `journal_django/` (venv: `journal_django/.venv/Scripts/python.exe`, Django :8000).
- Старый бэкенд (источник истины при переносе): `routes/`, `services/`, `services/repo/`, `shared/`.
- Общий `.env` в корне репозитория. Express :3000, Django :8000 — на одной БД.

## Что УЖЕ перенесено (не трогать без причины)

core-слой (`apps/core`: HMAC-shim auth, permissions, `StandardPagination`+whitelist sort,
`DateStringField`, `DateSafeJSONRenderer`, Decimal/jsonb/bigint-совместимость с node-pg, МСК-утилиты)
и полный CRUD: `groups` (эталон-pattern), `teachers`, `directions`, `discounts`, `settings`,
`audit` (read-only), `tokens`, `students`, `memberships`, `payments` (capacity-guard + balance).
224 pytest зелёных, live-diff с Express — IDENTICAL.

## Что осталось перенести (порядок исполнения)

| # | Раздел | Файл-бриф | Источник (Node) |
|---|--------|-----------|-----------------|
| 1 | Уроки и посещаемость | `01-lessons.md` | `services/repo/lessons.js`, `routes/admin/lessons.js` |
| 2 | FIFO + balance (вычислительный слой) | `02-finances-fifo.md` | `services/fifo.js`, `services/repo/payments.js` |
| 3 | Расчётный лист (payroll) | `03-payroll.md` | `services/repo/payroll.js`, `routes/admin/payroll.js` |
| 4 | Дашборд | `04-dashboard.md` | `services/repo/dashboard.js`, `routes/admin/dashboard.js` |
| 5 | Аккаунты (admin-only) | `05-accounts.md` | `services/repo/accounts.js`, `routes/admin/accounts.js` |
| 6 | Кабинет учителя (teacher SPA) | `06-teacher-spa.md` | `services/teacher-repo.js`, `services/calculator.js`, `routes/teacher.js` |
| 7 | **Auth (последним)** | `07-auth.md` | `services/auth.js`, `services/twofa.js`, `services/mailer.js`, `routes/auth.js` |
| 8 | Cutover + снос Express | `08-cutover.md` | `server.js`, nginx |

Сквозные инварианты, канон структуры и verification-харнесс — в **`00-conventions-and-invariants.md`** (читать ПЕРВЫМ).

## Решения пользователя (зафиксированы)

- **Backfill-скрипты (Node, Sheets→PG) НЕ переносим** — нужны как dev-инструмент подтягивания актуальных
  данных из Google-таблиц; остаются в Node-проекте до финального перехода компании на веб-приложение.
- **`services/sheets.js`** в Django **не портируем вообще** (Sheets не затрагивает ключевые модули Django).
- **Auth — нативный Django auth, переносится ПОСЛЕДНИМ.** До этого работает `HmacSessionAuthentication` (shim).

## Рекомендуемые агенты (подключённые)

Основной конвейер на voltagent-агентах (язык-специфичные под Python/Django):

| Агент | Роль в миграции |
|-------|------------------|
| **`voltagent-qa-sec:architect-reviewer`** | Ревью структуры `apps/` перед стартом нового слоя (особенно `finances`, `auth`) и финальное ревью перед сносом Express. |
| **`voltagent-lang:django-developer`** | Основной исполнитель: модели (`managed=False`), сериализаторы, тонкие views, services, urls. Раздел за разделом. |
| **`voltagent-lang:sql-pro`** | Raw SQL для `finances`/`payroll`/`dashboard`, проверка покрытия индексами, отсутствие N+1. |
| **`voltagent-qa-sec:test-automator`** | pytest-фикстуры, `factory_boy`, e2e-сверка Django vs Express (`scripts/diff_express.py`), golden-fixtures для финансов. |
| **`voltagent-qa-sec:code-reviewer`** | Ревью после **каждого** раздела: тонкость view, нет SQL во view, слои не смешаны, инварианты целы. |
| **`voltagent-qa-sec:security-auditor`** | Аудит auth-моста и нативного Django auth, Decimal-логики FIFO, перед деплоем. |

Назначение агента на каждый раздел — в шапке соответствующего `NN-*.md`.

> Запасной вариант: язык-нейтральный `general-purpose`. Проектные `backend-developer`/`code-reviewer`
> заточены под старый Node/Sheets-стек — для Python предпочтительнее voltagent-агенты выше.

## Рабочий цикл одного раздела

1. `architect-reviewer` (если новый слой) сверяет план структуры app c `00-conventions`.
2. `django-developer` создаёт app по канону: `models → serializers → views → services → repository → urls`.
   SQL копируется **дословно** из соответствующего `services/repo/*.js`.
3. `sql-pro` — для разделов с raw SQL (finances/payroll/dashboard) пишет/ревьюит запросы.
4. `test-automator` — pytest (unit + e2e-diff с Express); для финансов — golden-fixtures до копейки.
5. `code-reviewer` — ревью изменений против инвариантов из `00-conventions`.
6. `security-auditor` — на финансах и auth.
7. Прогон `scripts/diff_express.py` (Express :3000 vs Django :8000) → diff должен быть пуст.
8. Пауза, ревью пользователем, затем следующий раздел.
