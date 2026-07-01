# 07 — Аутентификация (`apps/auth_app`) — ПОСЛЕДНИМ

**Агенты:** `voltagent-lang:django-developer` + `voltagent-qa-sec:security-auditor` (обязательно) + `code-reviewer`.
**Источник (Node):** `services/auth.js`, `services/twofa.js`, `services/mailer.js`, `services/audit.js`, `routes/auth.js`.
**Решение:** переход на **нативный Django auth**. До этого этапа весь Django работает на `HmacSessionAuthentication` (shim).

## Подключение нативного auth (только сейчас!)

- Добавить `django.contrib.auth`, `django.contrib.contenttypes`, `django.contrib.sessions` в `INSTALLED_APPS`.
  ⚠️ Убедиться, что это **не** создаёт лишних таблиц в общей БД без необходимости / согласовать миграции сессий.
- `AUTH_USER_MODEL = 'accounts.Account'` — кастомный `AbstractBaseUser`. bcrypt-хэш `password_hash`:
  либо кастомный password hasher (bcrypt), либо адаптер, читающий существующую схему.
- В конце убрать `HmacSessionAuthentication`, перейти на сессии Django (`session` cookie).

## Эндпоинты `/api/auth/*`

| Метод | Путь | Поведение |
|-------|------|-----------|
| POST | `/login` | email+password+role. Проверка lockout. Если 2FA включена → выдать login-challenge, иначе сессия. Rate-limit. |
| POST | `/login/2fa` | Проверка TOTP / email-OTP / recovery-кода → сессия. Lockout после 5 fails. |
| POST | `/logout` | Сброс сессии. |
| GET | `/me` | Текущий аккаунт. **Поле `me`, не `user`** (`{ me: {...} }`). |
| POST | `/2fa/setup` | Старт enrollment: TOTP (secret+QR) или email. |
| POST | `/2fa/enable` | Подтвердить код → включить, сгенерировать 8 recovery-кодов. |
| POST | `/2fa/disable` | С подтверждением пароля → очистить 2FA, удалить recovery-коды. |
| POST | `/2fa/email/send` | Переотправить email-OTP в пределах TTL 5 мин. |

## 2FA (порт `services/twofa.js`)

- **TOTP**: `pyotp` (эквивалент otplib), ±30 c, issuer «KOTOKOD», provisioning URI + QR (`qrcode`).
- **Email-OTP**: 6-значный код, TTL 5 мин, **stateless** — bcrypt-хэш кода в подписанном challenge-токене (не в БД при логине).
- **Recovery codes**: 8 шт., bcrypt в БД, one-time (`used_at`).
- **Lockout**: 5 неудач → `locked_until` +15 мин.

## Mailer (порт `services/mailer.js`)

SMTP (Beget) для OTP-писем: тема «Код входа KOTOKOD», тело — код + предупреждение 5 мин. Без PII кроме кода.
Использовать Django `EmailBackend` или прямой SMTP, креды из `.env` (SMTP_HOST/PORT/USER/PASS/FROM).

## Audit-writer (сквозной, порт `services/audit.js`)

- `log_event({event, account_id, actor_email, target_id, meta, request})` → INSERT в `security_audit_log`.
- **Санитизация секретных ключей** в meta (regex: password/code/twofa_secret/token/password_hash/recovery).
- Non-blocking (ошибка лога не валит запрос). События: login_success/login_fail, 2fa_enabled/disabled/failed,
  locked, account_created, password_reset, 2fa_reset.

## Verification

- **Тест-зеркало HMAC-cookie**: реальный cookie Express принимается до переключения (shim) — потом снимается.
- Полный 2FA-флоу: TOTP, email-OTP, recovery, lockout — против реального challenge.
- security-auditor: аудит хэшей, отсутствия утечки секретов в ответах и в audit.meta.
- e2e-diff с Express по формату ответов (особенно `/me` → `{me:...}`); при расхождении — адаптировать фронт логина.
