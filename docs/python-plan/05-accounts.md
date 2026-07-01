# 05 — Аккаунты (`apps/accounts`, admin-only)

**Агенты:** `voltagent-lang:django-developer` + `voltagent-qa-sec:security-auditor` (секреты/хэши), `code-reviewer`.
**Источник (Node):** `services/repo/accounts.js`, `routes/admin/accounts.js`.
**Зависит от:** core, teachers. **Делать вместе с / прямо перед Этапом auth** (общий bcrypt, 2FA-сброс).

## Модели (managed=False)

- `Account` → `accounts`: id, email (unique, нормализован lowercase+trim), password_hash, role
  ('teacher'|'manager'|'admin'), teacher_id (nullable), active, twofa_method, twofa_secret, twofa_enabled,
  twofa_confirmed_at, failed_login_count, locked_until, last_login_at, created_at.
- `AccountRecoveryCode` → `account_recovery_codes`: id, account_id (FK CASCADE), code_hash, used_at.

Инвариант БД: `role='teacher' ⇔ teacher_id IS NOT NULL`.

## Эндпоинты (`/api/admin/accounts`, **роль admin**)

| Метод | Путь | Поведение |
|-------|------|-----------|
| GET | `/` | Список (пагинация, сорт email/role/active/created_at). Без секретов. |
| GET | `/:id` | Один аккаунт. **`password_hash` и `twofa_secret` НИКОГДА не отдавать.** |
| POST | `/` | Создать + сгенерировать temp-пароль (bcrypt cost=12), вернуть пароль один раз. |
| PATCH | `/:id` | email / role / active. |
| POST | `/:id/reset-password` | Новый temp-пароль. |
| POST | `/:id/reset-2fa` | Очистить twofa-поля + удалить recovery-коды. |
| DELETE | `/:id` | Soft-delete (`active=false`). |

## Критичное

- Секретные поля исключать из всех сериализаторов вывода.
- bcrypt cost=12 для паролей (как `services/auth.js`).
- Все мутации логировать в `security_audit_log` через writer (см. `07-auth.md` / сквозной audit-writer):
  события account_created / password_reset / 2fa_reset / account_deactivated, **с санитизацией секретов**.

## Verification

- e2e-diff с Express; проверить, что секреты не утекают ни в одном ответе.
- Тест инварианта role↔teacher_id (409/400 при нарушении).
