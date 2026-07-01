# Дизайн: разграничение прав доступа (RBAC) + унифицированный вход + ИБ РФ

**Дата:** 2026-06-06
**Статус:** проектирование → план
**Триггер:** запрос пользователя на разграничение доступа по ролям + соответствие
требованиям информационной безопасности по законам РФ. Закрывает заодно
roadmap-долг 🟡 «Роли + `GET /api/admin/me`».

> ⚠️ **Дисклеймер:** автор спеки — разработчик, не юрист. Раздел про ИБ РФ покрывает
> **технические** меры в коде. Организационно-юридические обязанности (уведомление РКН,
> согласия, политики, модель угроз, реагирование на утечки) вынесены в отдельный чеклист
> `docs/compliance-152fz-checklist.md` и требуют проверки профильным юристом/DPO.

## Цель

Единый вход для двух клиентов по **email + паролю (+ 2FA)** с выбором роли на
странице `/login`, маршрутизация в нужный клиент (teacher SPA или admin SPA) по роли.
Полноценная основа RBAC взамен двух разрозненных механизмов auth, плюс технические меры
ИБ по требованиям РФ (152-ФЗ, Приказ ФСТЭК №21): аутентификация, управление доступом,
регистрация событий безопасности, фиксация согласия на обработку ПДн.

## Проблема (текущее состояние)

- **Teacher auth** — только по токену `XXX-XXX-XXX` из таблицы `tokens` → `teacher_id`.
  Teacher SPA (vanilla `public/Index.html`, ~2500 строк) хранит токен в localStorage и
  шлёт его **в теле каждого запроса**. Сессии/телефона/пароля/2FA нет. В fetch захардкожен
  `http://localhost:3000/api/...`.
- **Admin auth** — один захардкоженный `ADMIN_USERNAME` + `ADMIN_PASSWORD_HASH` из `.env`,
  HMAC-cookie `admin_session` (Path=`/api/admin`). `AuthProvider` хардкодит `user='admin'`.
- **Роутинг** — `/` отдаёт teacher SPA, `/admin` — React admin SPA. Страницы `/login` нет.
- **ИБ:** нет журнала событий безопасности (РСБ), нет 2FA, нет фиксации согласия на ПДн,
  нет защиты от брутфорса. ПДн детей/родителей/преподов обрабатываются без этих мер.

## Принятые решения (из брейншторма)

1. **Модель учёток** — единая таблица `accounts` (**email-логин**, password_hash, role, teacher_id).
2. **Сессия** — единая HMAC-cookie для обеих ролей; teacher-эндпоинты уходят от token-в-теле.
3. **Пароль** = генерируемый из админки токен-пароль (хранится хешем).
4. **Страница входа** — отдельная мини-страница (vanilla static), общая для ролей.
5. **Роли** — структура на 3 роли `teacher|manager|admin`; `manager`≡`admin` по правам пока.
6. **Teacher SPA** — остаётся vanilla, только адаптируется (путь `/teacher`, новый вход).
7. **Переход** — преподы без email-учётки войти не могут, пока admin её не заведёт.
8. **Визуал логина** — лейаут референса в фирменном стиле KOTOKOD (teal `--accent`,
   Inter/Steppe, токены), логотип из `logo.html`.
9. **Объём** — одна спека; implementation-план разбит на последовательные фазы.
10. **ИБ-меры в объёме:** 2FA (два метода на выбор), audit-log (РСБ), усиление
    паролей/сессий (ИАФ), фиксация согласия на ПДн в БД. Орг-часть — отдельный чеклист.
11. **Логин — email** (не телефон). Email есть у всех сотрудников; залить в БД.
12. **2FA-методы (выбор пользователя):** (а) **TOTP** через `otplib` (Google Authenticator/
    Яндекс.Ключ), (б) **код на email** через SMTP — **Beget** (российский, уже настроен;
    на этапе разработки — тестовый ящик). SMS отклонён (платно + слабее).
13. **Обязательность 2FA** определит классификация ИСПДн/модель угроз (организационный шаг).
    По умолчанию: обязательна для `admin`/`manager` (привилегированный удалённый доступ),
    опциональна для `teacher`. Закон (Приказ ФСТЭК №21): для УЗ-1/2 — строго; для УЗ-3 —
    обязательна по модели угроз при удалённом интернет-доступе; для УЗ-4 — хватает пароля.

## Архитектура

### 1. Модель данных — миграция `013_accounts.sql`

```sql
CREATE TABLE accounts (
  id            serial PRIMARY KEY,
  email         text NOT NULL UNIQUE,        -- ЛОГИН (нормализованный: lowercase + trim)
  password_hash text NOT NULL,               -- bcrypt от токен-пароля
  role          text NOT NULL CHECK (role IN ('teacher','manager','admin')),
  teacher_id    int REFERENCES teachers(id), -- NOT NULL для teacher, NULL иначе
  active        bool NOT NULL DEFAULT true,
  -- 2FA (метод на выбор: 'totp' | 'email'); метод 'email' шлёт код на логин-email
  twofa_method      text CHECK (twofa_method IN ('totp','email')),
  twofa_secret      text,                    -- base32 secret (только для метода 'totp')
  twofa_enabled     bool NOT NULL DEFAULT false,
  twofa_confirmed_at timestamptz,
  CHECK (twofa_method <> 'totp' OR twofa_secret IS NOT NULL),  -- totp требует secret
  -- анти-брутфорс / аудит входа
  failed_login_count int NOT NULL DEFAULT 0,
  locked_until       timestamptz,
  last_login_at      timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CHECK ((role = 'teacher') = (teacher_id IS NOT NULL))
);
CREATE UNIQUE INDEX accounts_teacher_id_uq ON accounts(teacher_id) WHERE teacher_id IS NOT NULL;

CREATE TABLE account_recovery_codes (
  id         serial PRIMARY KEY,
  account_id int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  code_hash  text NOT NULL,                  -- bcrypt одноразового кода
  used_at    timestamptz                     -- NULL = не использован
);
CREATE INDEX account_recovery_codes_account_idx ON account_recovery_codes(account_id);
```

- `email` — единый логин; хранится нормализованным (lowercase + trim), UNIQUE.
- Роли: `teacher | manager | admin`; `manager`≡`admin` по правам пока (разводится позже без миграции).
- Один аккаунт на препода (частичный UNIQUE по `teacher_id`).
- 2FA-секрет хранится в `accounts.twofa_secret` (см. примечание о шифровании в разделе ИБ).
- Таблица `tokens` **перестаёт быть auth-механизмом**; остаётся для исторической связи
  (`lessons.submitted_by_token`). Управление токенами в админке → управление учётками.
- `.env`-админ выводится из обихода: первый admin сидится скриптом.

### 1а. Миграция `014_security_audit_log.sql` (РСБ — Приказ ФСТЭК №21)

```sql
CREATE TABLE security_audit_log (
  id          bigserial PRIMARY KEY,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  account_id  int REFERENCES accounts(id),   -- NULL для неуспешного входа по несуществующему email
  actor_email text,                          -- email из попытки (для login_fail по несущ. адресу)
  event       text NOT NULL,                 -- login_success|login_fail|logout|2fa_fail|
                                             -- 2fa_enabled|2fa_disabled|2fa_reset|
                                             -- account_created|password_reset|account_deactivated|locked
  ip          text,
  user_agent  text,
  target_id   int,                           -- id затронутой сущности (напр. account/student)
  meta        jsonb                          -- доп. контекст без секретов
);
CREATE INDEX security_audit_log_occurred_idx ON security_audit_log(occurred_at DESC);
CREATE INDEX security_audit_log_account_idx  ON security_audit_log(account_id, occurred_at DESC);
```

- Журнал append-only (запись, не правится). Просмотр — только admin.
- **Никогда** не пишем пароли/токены/2FA-секреты в `meta`.

### 1б. Миграция `015_students_consent.sql` (фиксация согласия на ПДн)

```sql
ALTER TABLE students
  ADD COLUMN consent_given   bool NOT NULL DEFAULT false,
  ADD COLUMN consent_at      timestamptz,
  ADD COLUMN consent_by      text,           -- кто дал (ФИО родителя/законного представителя)
  ADD COLUMN consent_note    text;           -- основание/источник (бумажное/скан/устно при записи)
```

- Технический крючок под организационное требование (письменное согласие родителя по ст. 64 СК РФ).
- Редактируется на карточке ученика в admin SPA; в audit-log пишется факт изменения согласия.
- Юридическая форма самого согласия — вне кода (чеклист).

### 2. Аутентификация и сессия — `services/auth.js` + `services/twofa.js`

**`services/auth.js`** (новый, обобщает `admin-auth.js`):
- **Cookie** `session` (переименование `admin_session`), `Path=/`, `HttpOnly; SameSite=Strict;
  Max-Age=86400` (+`Secure` в prod), HMAC.
- **Payload** `{ account_id, role, iat, exp }`.
- **Функции:** `sign`/`verify`; `comparePassword`; `generateTokenPassword()` →
  `XXXX-XXXX-XXXX` через `crypto.randomBytes` (криптостойко, без неоднозначных символов);
  `normalizeEmail(raw)` → lowercase + trim + валидация формата (или `null`).
- **Усиление (ИАФ):** bcrypt cost ≥ 12; секреты (пароли, 2FA, recovery) **не логируются
  никогда**; при `password_reset` и `2fa_disabled` — инвалидация активных сессий (бамп
  `iat`-порога / версии). Лимит неудач: `failed_login_count`, при превышении (напр. 5)
  → `locked_until` (напр. +15 мин) + событие `locked`.

**`services/twofa.js`** (новый, обёртка над `otplib` + `qrcode`):
- *TOTP:* `generateSecret()` → base32; `provisioningUri(secret, email)` →
  `otpauth://totp/KOTOKOD:<email>?issuer=KOTOKOD`; `qrDataUrl(uri)` → data:image/png
  (`qrcode`) для vanilla-страницы; `verifyTotp(secret, code)` → bool (окно ±1 шаг).
- *Email-OTP:* `generateEmailCode()` → 6 цифр (`crypto`). Проверка — **stateless через
  подписанный `challenge_token`**: внутри хранится bcrypt-хеш кода + exp (код в БД не хранится).
- *Recovery:* `generateRecoveryCodes(n=8)` → plaintext (показать раз) + bcrypt-хеши для БД.

**`services/mailer.js`** (новый) — отправка email-OTP через `nodemailer` (SMTP из `.env`:
`SMTP_HOST/PORT/USER/PASS/FROM`). Письмо содержит **только одноразовый код** (без ПДн).
SMTP — **Beget** (российский; на этапе разработки — тестовый ящик).

**Middleware:**
- `requireAuth` — валидирует cookie, кладёт `req.account = { account_id, role }`; иначе 401.
- `requireRole(...roles)` — после `requireAuth`; иначе 403.

`services/admin-auth.js` остаётся тонким ре-экспортом (back-compat тестов).

### 3. Роуты аутентификации — `routes/auth.js` (`/api/auth`, без сессии)

**Политика 2FA:** обязательна для `admin`/`manager` (привилегированный доступ ко всем ПДн
и финансам); для `teacher` — опциональна (можно включить per-account; легко сделать
обязательной для всех, поменяв одно условие).

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/auth/login` | `{ email, password, role }`: normalize email → найти активный аккаунт → проверить `locked_until` → bcrypt → проверить совпадение роли. Дальше ветвление по 2FA (ниже). Любая ошибка → 401 «Неверный email или пароль» (анти-энумерация). |
| POST | `/api/auth/login/2fa` | `{ challenge_token, code }`: проверить токен (TTL ~5 мин) + код (TOTP / email-OTP / recovery) → полная сессия. |
| POST | `/api/auth/2fa/email/send` | под `challenge_token` (метод='email'): сгенерить код, отправить на email аккаунта (= логин), вернуть новый `challenge_token` с хешем кода + таймер анти-спама. |
| POST | `/api/auth/2fa/setup` | под `challenge_token`/сессией: `{ method }`. Для `totp` → `secret`+`qrDataUrl` (раз); для `email` → отправить код подтверждения на почту. |
| POST | `/api/auth/2fa/enable` | подтвердить кодом → зафиксировать `twofa_method`, `twofa_enabled=true`, выдать recovery-коды (раз). |
| POST | `/api/auth/2fa/disable` | под сессией + код/пароль → выключить 2FA (для teacher). |
| POST | `/api/auth/logout` | Чистит cookie. |
| GET  | `/api/auth/me` | `{ account_id, email, role, teacher_id, name, twofa_enabled }`. |

**Ветвление login (happy/2FA):**
1. Пароль верен, `twofa_enabled` → НЕ ставим сессию; возвращаем
   `{ twofa_required:true, method, challenge_token }`. Если `method='email'` — фронт
   вызывает `/2fa/email/send` и показывает ввод кода; если `'totp'` — сразу ввод кода
   из приложения → `/login/2fa`.
2. Пароль верен, 2FA выключена, но **роль требует 2FA** (admin/manager) →
   `{ twofa_enrollment_required:true, challenge_token }`. Фронт ведёт через `/2fa/setup` +
   `/2fa/enable`, затем сессия.
3. Пароль верен, 2FA не требуется (teacher без 2FA) → ставим сессию,
   `{ role, redirect:'/teacher' }`.

- **Rate-limit** на `/login` и `/login/2fa` (`express-rate-limit`, напр. 10/15 мин на IP) —
  поверх per-account `locked_until`.
- Каждое значимое событие пишется в `security_audit_log` (login_success/fail, 2fa_fail,
  2fa_enabled/disabled, locked).

### 4. Авторизация эндпоинтов (gating)

| Префикс | Middleware |
|---|---|
| `/api/auth/*` | публично (login/2fa/logout/me) |
| `/api/*` (teacher) | `requireAuth` + `requireRole('teacher')` |
| `/api/admin/*` | `requireAuth` + `requireRole('manager','admin')` |

- Управление учётками, сброс 2FA, просмотр audit-log — дополнительно `requireRole('admin')`.

### 5. Рефактор teacher-эндпоинтов — `routes/teacher.js` + схемы

- Убрать `token` из `validateTokenSchema`/`getDataSchema`/`submitLessonSchema`; источник
  препода — `req.account.teacher_id`.
- `POST /api/validateToken` **удаляется**.
- `getData`/`getAllData`/`submitLesson`/`report`/`schedule` берут препода из сессии.
- `submitLesson`: `submitted_by_token` → `acct:<account_id>`.
- Обновить `services/teacher-repo.js` и тест `teacher-repo.test.js`.

### 6. Страница входа — `/login` (standalone, vanilla, KOTOKOD)

Отдельная статическая мини-страница (без отдельного build), на `/` и `/login`.
- **Экран 1 — выбор роли:** карточки «Преподаватель» и «Админ/Менеджер» (компоновка
  «логин экран.png»), стиль KOTOKOD (teal `--accent`, Inter/Steppe), логотип из `logo.html`
  (его заливки `#F4F4F4`+`#50DCFE` — под тёмную подложку → тёмный лого-бар или переопределить fill).
- **Экран 2 — форма входа** (та же страница, «← Назад»): поле **email**, пароль, «Войти»
  (компоновка «форма входа.png»).
- **Экран 3 — 2FA:** ввод 6-значного кода. Для метода email — кнопка «Отправить код на
  почту» + таймер повторной отправки; для TOTP — подсказка про приложение; ссылка
  «использовать recovery-код». При enrollment — выбор метода: TOTP (показ QR `qrDataUrl`)
  или email (подтверждение почты кодом) + показ recovery-кодов один раз.
- Поведение: POST на `/api/auth/*`, по `redirect` → `window.location`. Валидация email —
  vanilla без зависимостей. Соответствие `.claude/skills/design-principles`.

### 7. Реструктуризация роутинга — `server.js`

```
/                  → public/login/index.html
/login             → public/login/index.html
/teacher, /teacher/* → public/teacher/index.html  (бывш. public/Index.html) + SPA fallback
/admin, /admin/*   → как сейчас (React)
/api/auth/*        → routes/auth      (public)
/api/*             → teacher router   (requireAuth + requireRole 'teacher')
/api/admin/*       → admin router     (requireAuth + requireRole 'manager','admin')
```

- Teacher SPA: перенос в `public/teacher/`, убрать token-screen, относительные пути,
  401→`/login`, «Выход» → POST `/api/auth/logout` + редирект.
- `express.static('public')` сузить, чтобы корень не отдавал старый Index.html.

### 8. Admin SPA (React) — правки

- `AuthProvider`: `GET /api/auth/me` вместо `user='admin'`; хранит `{account_id, email, role,
  name, teacher_id, twofa_enabled}`.
- `AuthGate`/`lib/api.ts`: 401 → редирект на **`/login`**.
- Удалить внутренний роут `/admin/login`.

### 9. Управление учётками + ИБ-страницы (admin)

**Backend:**
- `services/repo/accounts.js` — CRUD accounts (paginate).
- `routes/admin/accounts.js`:

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/admin/accounts?page=&...` | Paginated (join `teacher_name`) |
| GET | `/api/admin/accounts/:id` | Одна учётка |
| POST | `/api/admin/accounts` | Создать (email, role, teacher_id); сервер генерит токен-пароль (plaintext раз) |
| PATCH | `/api/admin/accounts/:id` | email/role/active |
| POST | `/api/admin/accounts/:id/reset-password` | Новый токен-пароль (раз) + инвалидация сессий |
| POST | `/api/admin/accounts/:id/reset-2fa` | Сброс 2FA (потеря устройства) |
| DELETE | `/api/admin/accounts/:id` | Soft (active=false) |
| GET | `/api/admin/audit-log?page=&filter[...]` | Просмотр журнала событий ИБ |

- Все — `requireRole('admin')`. Zod-схемы в `shared/schemas.js`, типы в `shared/types.ts`.
- Все мутации учёток → запись в `security_audit_log`.

**Admin UI:**
- `web/admin/src/pages/accounts/` — список/создание (**email**, роль, teacher, метод 2FA по
  умолчанию)/перевыпуск пароля/сброс 2FA/деактивация + хуки `useAccounts`/`useAccountMutations`.
- `web/admin/src/pages/audit/` — просмотр `security_audit_log` (paginated, фильтры).
- Карточка ученика: блок согласия на ПДн (`consent_*`).

### 10. Миграция данных / переход

- Скрипт `scripts/create-account.js <email> <role> [teacher_id]` → создаёт аккаунт, печатает
  токен-пароль. Им сидим первого admin (на первом входе — enrollment 2FA).
- **Залить email сотрудников** в `accounts.email` (это логин — есть у всех).
- Преподы без email-учётки войти не могут, пока admin её не заведёт.
- `scripts/admin-set-password.js` — выводится из обихода/адаптируется под seed.

### 11. Соответствие требованиям ИБ РФ (технические меры в коде)

| Мера (Приказ ФСТЭК №21 / 152-ФЗ) | Реализация в проекте |
|---|---|
| **ИАФ** — идентификация/аутентификация | email+пароль (bcrypt cost≥12) + **2FA (TOTP или email-OTP)**; rate-limit + `locked_until`; криптостойкая генерация секретов; анти-энумерация |
| **УПД** — управление доступом | RBAC (`requireRole`), least privilege (manager vs admin), session-cookie с ролью |
| **РСБ** — регистрация событий безопасности | `security_audit_log` (входы, 2FA, действия с учётками, согласия) |
| **Локализация (242-ФЗ)** | хостинг Beget VPS (РФ); 2FA-TOTP self-hosted (otplib); email-OTP через Beget SMTP (РФ, код без ПДн); **⚠️ выпил Google Sheets — Phase 5 (вне объёма, отмечен как ИБ-релевантный)** |
| **Согласие на ПДн (152-ФЗ)** | `students.consent_*` фиксирует факт; форма согласия — организационно (чеклист) |
| **Защита канала** | TLS/HTTPS (certbot) — `docs/deploy-runbook.md` |
| **Целостность/доступность** | бэкапы `pg_dump` (cron) — `docs/deploy-runbook.md` |

**Примечание о шифровании 2FA-секрета в покое:** по умолчанию `twofa_secret` хранится в БД
(доступ к БД ограничен). Опционально — шифровать колонку приложением (ключ в `.env`/KMS);
вынесено как возможное усиление, не в базовом объёме.

**Примечание о email-2FA:** код приходит на тот же email, что и логин (один канал) — TOTP
криптографически сильнее (отдельный фактор «владение устройством»); метод выбирает пользователь.

**Организационно-юридические обязанности — `docs/compliance-152fz-checklist.md`** (вне кода):
уведомление РКН/реестр операторов; политика обработки ПДн (публикация); согласия отдельным
документом (с 01.09.2025), для детей — письменно от родителя; классификация ИСПДн + модель
угроз (ПП 1119); регламент реагирования на утечки (РКН: 24ч/72ч); назначение ответственного
за обработку ПДн.

## Поток данных (happy path, admin с 2FA)

1. `/` → выбор роли → «Админ/Менеджер» → форма.
2. Email+пароль → `POST /api/auth/login {role:'admin'}`.
3. Сервер: normalize email → аккаунт → не locked → bcrypt OK → роль OK → `twofa_enabled` →
   `{ twofa_required, challenge_token }` (вход ещё не завершён — `login_success` пишется
   только после успешной 2FA на шаге 4).
4. Экран кода → `POST /api/auth/login/2fa {challenge_token, code}` → TOTP OK → cookie
   `session` → `{ role:'admin', redirect:'/admin' }` (+ `login_success` в audit).
5. `/admin` грузится, `GET /api/auth/me` заполняет `AuthProvider`.

## Обработка ошибок

- Неверный email/пароль/неактивен/несовпадение роли → 401 единое сообщение.
- Аккаунт заблокирован (`locked_until`) → 429/403 «Временно заблокировано, попробуйте позже».
- Неверный/просроченный `challenge_token` или 2FA-код → 401 + `2fa_fail` в audit.
- Невалидный email → 400. Брутфорс → 429. Дубликат email при создании → 409.
- Истёкшая cookie → 401 → редирект `/login`.

## Тестирование

- `services/auth.test.js` — sign/verify/expire, `requireRole`, `normalizeEmail`,
  `generateTokenPassword`, lock-логика.
- `services/twofa.test.js` — TOTP (secret/verify/окно), email-OTP (генерация + проверка
  через challenge_token + expiry), provisioningUri, recovery-коды (одноразовость).
- `services/repo/accounts.test.js` — CRUD, reset-password (hash меняется), reset-2fa,
  частичный UNIQUE teacher_id, CHECK роли↔teacher_id.
- `routes/auth` — login happy / wrong-password / wrong-role / inactive / locked / bad-email;
  2FA required → 2fa verify; enrollment flow; me; logout.
- `security_audit_log` — события пишутся, секреты не попадают в `meta`.
- Обновить `admin-auth.test.js` (ре-экспорт), `teacher-repo.test.js` (без токена).

## Зависимости (npm)

- `otplib` (TOTP, MIT) + `qrcode` (QR data URL, MIT) — 2FA-TOTP, self-hosted.
- `nodemailer` (MIT) — отправка email-OTP через SMTP (желательно российский провайдер).
- `express-rate-limit` (MIT) — анти-брутфорс.
- Без платных SMS-шлюзов; email-код не содержит ПДн (локализация).

## Влияние на производительность

- Роль в cookie → gating без обращения к БД.
- 2FA-verify (otplib) — дешёвый HMAC; bcrypt на login — CPU-bound (~50–100мс), ограничен
  rate-limit + lock, не на горячем пути.
- audit-log — append-only INSERT, индексы по времени/аккаунту; не на горячем пути teacher SPA.
- `accounts`/recovery-codes малы; запросы по PK/UNIQUE.

## Фазы реализации (детализация — в плане)

1. **БД + auth-ядро:** миграции `013`/`014`/`015`, `services/auth.js` (+ hardening),
   `services/repo/accounts.js`, `scripts/create-account.js`, тесты. Seed первого admin.
2. **Роуты auth + gating:** `routes/auth.js` (login без 2FA-ветки пока — базовый), gating
   teacher/admin, рефактор teacher-эндпоинтов от token-в-теле, схемы/тесты.
3. **2FA:** `services/twofa.js` (TOTP) + `services/mailer.js` (email-OTP), 2FA-ветки login +
   endpoints (оба метода), recovery-коды, audit-события, тесты.
4. **Страница `/login`:** `public/login/` (3 экрана: роль/пароль/2FA), реструктуризация
   `server.js`, поле email + валидация.
5. **Teacher SPA → `/teacher`:** перенос, удаление token-screen, относительные пути,
   401→/login, logout.
6. **Admin SPA:** `AuthProvider`→`/me`, 401→`/login`, удаление `/admin/login`.
7. **Admin: учётки + audit-log + согласие:** `routes/admin/accounts.js` + repo + страницы
   `accounts/`, `audit/` + блок согласия на карточке ученика + хуки.
8. **Чеклист ИБ:** `docs/compliance-152fz-checklist.md` (орг-меры) + правка `CLAUDE.md`/ROADMAP.

Каждая фаза — самостоятельный чекпойнт (тесты зелёные, ручная проверка).

## Вне объёма (YAGNI)

- Различие прав manager vs admin (структура заложена, развести позже).
- Самостоятельная регистрация / восстановление пароля пользователем.
- Обязательная 2FA для teacher (по умолчанию опциональна; легко включить).
- Шифрование `twofa_secret` в покое (отмечено как опц. усиление).
- WebAuthn/passkeys как фактор 2FA — будущее усиление (TOTP/email достаточно сейчас).
- Phase 5 (выпил Sheets) — отдельный roadmap-пункт, отмечен как ИБ-релевантный.
- Полный `admin_audit_log` действий над *всеми* ПДн (сейчас — события ИБ + учётки + согласие).
- Audit-log действий, soft-delete payments — отдельные roadmap-пункты.
- Юридическое сопровождение орг-мер (чеклист — не консультация).
```
