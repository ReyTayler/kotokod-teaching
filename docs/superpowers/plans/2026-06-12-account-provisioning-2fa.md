# Account Provisioning via Invite + Mandatory 2FA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **⚠️ Нет git в проекте.** Вместо `git commit` после каждой задачи — чекпоинт: прогон полного набора тестов (`.venv/Scripts/python.exe -m pytest -q` из `journal_django/`) + ручное ревью изменений. Старая логика (606 тестов) обязана оставаться зелёной на каждом чекпоинте.

**Goal:** Заменить выдачу временного пароля на invite-ссылку (сотрудник сам ставит пароль), сделать 2FA обязательной для всех ролей, добавить stateful-инвалидацию сессий через `token_version`, ротацию сессии, дифференцированный rate-limit, расширенный аудит и Django-команду bootstrap первого админа.

**Architecture:** Слои `views → services → repository` сохраняются. Invite — под-домен `apps/accounts` (новая модель `AccountInvite`, без нового Django-app). Выписка invite — в `accounts.services`; потребление (`GET /invite`, `POST /invite/accept`) — в `auth_app.services` (переиспользует `issue_challenge(acc,'enroll')`). Plaintext-токен генерится и хешируется (SHA-256) в service-слое; repository видит только `token_hash`. `token_version` сверяется в `HmacSessionAuthentication` одним точечным SELECT.

**Tech Stack:** Django 5.1 + DRF, PostgreSQL (managed=True модели поверх существующих таблиц), pyotp/bcrypt, pytest. Frontend login — vanilla JS; admin SPA — React 19 + TanStack Query.

**Решения судьи (из архитектурного ревью, обязательны):**
- `password_hash` → **nullable** (миграция DROP NOT NULL). Состояние «приглашён» = есть активный invite и `password_hash IS NULL` / `last_login_at IS NULL`.
- `token_version` сверяется в `HmacSessionAuthentication.authenticate` (не в permission), заодно проверяется `active`. Старые cookie без поля → `token_version=0` (DB DEFAULT 0).
- Инкремент `token_version` — единая repo-функция `bump_token_version`, вызывается из всех мутаций пароля/2FA/email/деактивации.
- invite-токен: `secrets.token_urlsafe(32)` + `sha256` в БД, **без соли** (high-entropy random).
- Cookie `session` остаётся `SameSite=Strict` (Lax не вводим).
- Rate-limit — по IP, дифференцирован по эндпоинтам (in-memory, на cutover → nginx).
- `account_invites`: partial UNIQUE `(account_id) WHERE used_at IS NULL AND revoked_at IS NULL` — БД-гарантия «один активный invite».
- Базовый порог пароля на `invite/accept` — `min_length=8` (правил сложности в проекте нет).

---

## File Structure

**Создаются:**
- `journal_django/apps/accounts/migrations/0002_account_token_version.py` — `token_version` + DB DEFAULT.
- `journal_django/apps/accounts/migrations/0003_account_invites.py` — таблица `account_invites`, индекс, partial-unique, DROP NOT NULL `password_hash`.
- `journal_django/apps/accounts/management/__init__.py`, `.../commands/__init__.py`, `.../commands/bootstrap_admin.py`.
- `journal_django/apps/accounts/tests/test_invites_repository.py`, `test_invites_service.py`, `test_bootstrap_command.py`.
- `journal_django/apps/auth_app/tests/test_invite_flow.py`, `test_token_version.py`.
- `journal_django/frontend/login/set-password.html`, `set-password.js` (страница установки пароля).

**Модифицируются:**
- `journal_django/apps/accounts/models.py` — `Account.token_version`, новая модель `AccountInvite`.
- `journal_django/apps/accounts/repository.py` — `bump_token_version`, `get_auth_state`, invite-функции, статус в списке.
- `journal_django/apps/accounts/services.py` — `issue_invite`, `create_account`/`reset_password` через invite, инкременты версии, новые операции invite.
- `journal_django/apps/accounts/serializers.py` — без изменений контракта входа (create остаётся), но output меняется в views.
- `journal_django/apps/accounts/views.py` — новые эндпоинты `/invite`, `/invite/revoke`; ответы create/reset.
- `journal_django/apps/accounts/urls.py` — маршруты invite.
- `journal_django/apps/auth_app/services.py` — `requires_2fa→True`, `invite_lookup`, `invite_accept`.
- `journal_django/apps/auth_app/serializers.py` — `InviteAcceptSerializer`.
- `journal_django/apps/auth_app/views.py` — `InviteLookupView`, `InviteAcceptView`, рефактор rate-limit.
- `journal_django/apps/auth_app/urls.py` — `/invite`, `/invite/accept`.
- `journal_django/apps/auth_app/sessions.py` — `token_version` в payload.
- `journal_django/apps/core/authentication.py` — сверка `token_version`+`active`.
- `journal_django/apps/core/utils/passwords.py` — `generate_invite_token`, `hash_invite_token`, `INVITE_TTL_HOURS`.
- `journal_django/config/urls_dev.py` — гейт «создайте админа».
- `journal_django/frontend/login/login.js` — обработка `set-password` редиректа (по необходимости).
- `journal_django/frontend/admin-src/src/hooks/useAccounts.ts`, `.../pages/accounts/AccountsPage.tsx` — invite_url вместо password.

---

## ШАГ 0 — `token_version` (изолированная stateful-инвалидация сессий)

Меняет аутентификацию глобально → катим первым и стабилизируем.

### Task 0.1: Поле `token_version` (модель + миграция)

**Files:**
- Modify: `journal_django/apps/accounts/models.py`
- Create: `journal_django/apps/accounts/migrations/0002_account_token_version.py`

- [ ] **Step 1: Добавить поле в модель**

В `models.py`, в класс `Account`, после `created_at = models.DateTimeField()`:

```python
    token_version = models.IntegerField(default=0)
```

- [ ] **Step 2: Написать миграцию**

`0002_account_token_version.py`:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='token_version',
            field=models.IntegerField(default=0),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE accounts ALTER COLUMN token_version SET DEFAULT 0;",
            reverse_sql="ALTER TABLE accounts ALTER COLUMN token_version DROP DEFAULT;",
        ),
    ]
```

- [ ] **Step 3: Применить миграцию к dev-БД**

Run: `cd journal_django && .venv/Scripts/python.exe manage.py migrate accounts`
Expected: `Applying accounts.0002_account_token_version... OK`

- [ ] **Step 4: Чекпоинт — полный прогон**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest -q`
Expected: все тесты PASS (новое поле имеет DEFAULT 0, ничего не ломает).

### Task 0.2: repo-функции `bump_token_version` и `get_auth_state`

**Files:**
- Modify: `journal_django/apps/accounts/repository.py`
- Test: `journal_django/apps/accounts/tests/test_accounts_repository.py`

- [ ] **Step 1: Написать падающий тест**

В `test_accounts_repository.py` добавить:

```python
def test_bump_token_version_increments(account_factory):
    from apps.accounts import repository
    acc_id = account_factory(email='__tv__@example.com', role='manager')
    before = repository.get_auth_state(acc_id)
    assert before['token_version'] == 0
    assert before['active'] is True
    repository.bump_token_version(acc_id)
    after = repository.get_auth_state(acc_id)
    assert after['token_version'] == 1


def test_get_auth_state_missing_returns_none():
    from apps.accounts import repository
    assert repository.get_auth_state(99_999_999) is None
```

- [ ] **Step 2: Прогнать — должно упасть**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/accounts/tests/test_accounts_repository.py -q -k "token_version or auth_state"`
Expected: FAIL (`AttributeError: module ... has no attribute 'bump_token_version'`).

- [ ] **Step 3: Реализовать**

В `repository.py` добавить (рядом с `register_login_success`):

```python
def bump_token_version(account_id: int) -> None:
    """Инкремент token_version (инвалидация всех активных сессий аккаунта)."""
    Account.objects.filter(id=account_id).update(token_version=F('token_version') + 1)


def get_auth_state(account_id: int) -> Optional[dict]:
    """token_version + active для проверки сессии в аутентификации. None если нет."""
    return dictrow(
        Account.objects.filter(id=account_id).values('token_version', 'active')
    )
```

- [ ] **Step 4: Прогнать — должно пройти**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/accounts/tests/test_accounts_repository.py -q -k "token_version or auth_state"`
Expected: PASS.

### Task 0.3: `token_version` в payload сессии

**Files:**
- Modify: `journal_django/apps/auth_app/sessions.py:54-77`

- [ ] **Step 1: Расширить payload**

В `issue_session`, заменить блок `payload`:

```python
    now_ms = int(time.time() * 1000)
    payload: dict[str, Any] = {
        'account_id': account['id'],
        'role': account['role'],
        'iat': now_ms,
        'exp': now_ms + COOKIE_LIFETIME_MS,
        'token_version': account.get('token_version', 0),
    }
```

- [ ] **Step 2: Обновить docstring модуля**

В шапке `sessions.py` строку про «byte-parity Node» дополнить:

```
⚠️ Express снят: byte-parity больше не требуется. Payload расширен полем
   token_version (в КОНЦЕ, после exp). Старые cookie без поля трактуются как
   token_version=0 (см. authentication.py).
```

- [ ] **Step 3: Чекпоинт**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/auth_app -q`
Expected: PASS (account dict из repository содержит token_version; conftest-фабрика → DB DEFAULT 0).

### Task 0.4: Сверка `token_version`+`active` в аутентификации

**Files:**
- Modify: `journal_django/apps/core/authentication.py:135-144`
- Test: `journal_django/apps/auth_app/tests/test_token_version.py` (создать)

- [ ] **Step 1: Написать падающие тесты**

`test_token_version.py`:

```python
"""token_version: смена версии инвалидирует уже выпущенные cookie."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from django.db import connection
from django.test import Client

TEST_SECRET = 'deadbeef' * 16


def _cookie(account_id: int, role: str, token_version: int) -> str:
    now = int(time.time() * 1000)
    payload = {
        'account_id': account_id, 'role': role,
        'iat': now - 1000, 'exp': now + 86_400_000,
        'token_version': token_version,
    }
    enc = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode()
    ).rstrip(b'=').decode()
    sig = hmac.new(TEST_SECRET.encode(), enc.encode(), hashlib.sha256).hexdigest()
    return f'{enc}.{sig}'


@pytest.fixture
def manager_acc():
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO accounts (email, password_hash, role, token_version) "
            "VALUES ('__tv_auth__@x.com', '$2b$12$abcdefghijklmnopqrstuv', 'manager', 0) "
            "RETURNING id"
        )
        acc_id = cur.fetchone()[0]
    yield acc_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM accounts WHERE id = %s', [acc_id])


@pytest.mark.django_db
def test_matching_version_authenticates(manager_acc, settings):
    settings.ADMIN_COOKIE_SECRET = TEST_SECRET
    c = Client()
    c.cookies['session'] = _cookie(manager_acc, 'manager', 0)
    r = c.get('/api/auth/me')
    assert r.status_code == 200


@pytest.mark.django_db
def test_stale_version_rejected(manager_acc, settings):
    settings.ADMIN_COOKIE_SECRET = TEST_SECRET
    from apps.accounts import repository
    repository.bump_token_version(manager_acc)  # БД → 1, cookie несёт 0
    c = Client()
    c.cookies['session'] = _cookie(manager_acc, 'manager', 0)
    r = c.get('/api/auth/me')
    assert r.status_code == 401


@pytest.mark.django_db
def test_inactive_account_rejected(manager_acc, settings):
    settings.ADMIN_COOKIE_SECRET = TEST_SECRET
    with connection.cursor() as cur:
        cur.execute('UPDATE accounts SET active = false WHERE id = %s', [manager_acc])
    c = Client()
    c.cookies['session'] = _cookie(manager_acc, 'manager', 0)
    r = c.get('/api/auth/me')
    assert r.status_code == 401
```

- [ ] **Step 2: Прогнать — `stale`/`inactive` падают**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/auth_app/tests/test_token_version.py -q`
Expected: `test_matching_version_authenticates` PASS, два других FAIL (сверки ещё нет).

- [ ] **Step 3: Реализовать сверку**

В `authentication.py`, в `HmacSessionAuthentication.authenticate`, заменить хвост:

```python
        payload = verify_session_cookie(token)
        if payload is None:
            return None

        # Stateful-проверка: версия токена + активность аккаунта (1 точечный SELECT).
        from apps.accounts import repository as accounts_repo
        state = accounts_repo.get_auth_state(int(payload['account_id']))
        if state is None or not state['active']:
            return None
        if int(payload.get('token_version', 0)) != int(state['token_version']):
            return None

        return ShimUser(payload), None
```

- [ ] **Step 4: Прогнать — всё зелёное**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/auth_app/tests/test_token_version.py -q`
Expected: 3 PASS.

### Task 0.5: Инкременты `token_version` в существующих мутациях

**Files:**
- Modify: `journal_django/apps/accounts/services.py` (`reset_twofa`, `soft_delete`, `update_account`)
- Modify: `journal_django/apps/auth_app/services.py` (`twofa_enable`, `twofa_disable`)
- Test: `journal_django/apps/auth_app/tests/test_token_version.py`

- [ ] **Step 1: Тест на инкремент при reset-2fa и деактивации**

Добавить в `test_token_version.py`:

```python
@pytest.mark.django_db
def test_soft_delete_bumps_version(manager_acc):
    from apps.accounts import services, repository

    class _Req:
        META = {}
    services.soft_delete(manager_acc, actor_account_id=manager_acc, request=_Req())
    assert repository.get_auth_state(manager_acc)['token_version'] == 1
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/auth_app/tests/test_token_version.py -q -k soft_delete`
Expected: FAIL (version остаётся 0).

- [ ] **Step 3: Добавить bump в `accounts/services.py`**

В `reset_twofa` — после успешного `repository.reset_twofa(...)`, перед `log_event`:

```python
    repository.bump_token_version(account_id)
```

В `soft_delete` — после `if not ok: return False`:

```python
    repository.bump_token_version(account_id)
```

В `update_account` — изменить, чтобы инкрементить при смене email:

```python
def update_account(account_id: int, data: dict) -> Optional[dict]:
    row = repository.update_account(
        account_id,
        email=data.get('email'),
        role=data.get('role'),
        active=data.get('active'),
    )
    if row is not None and data.get('email') is not None:
        repository.bump_token_version(account_id)
    return _strip_secrets(row)
```

- [ ] **Step 4: Добавить bump в `auth_app/services.py`**

В `twofa_enable` — после `accounts_repo.set_twofa(...)` (включение 2FA):

```python
    accounts_repo.bump_token_version(acc['id'])
```

В `twofa_disable` — после `accounts_repo.reset_twofa(acc['id'])`:

```python
    accounts_repo.bump_token_version(acc['id'])
```

- [ ] **Step 5: Чекпоинт — полный прогон**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest -q`
Expected: всё PASS.

---

## ШАГ 1 — Ротация сессии после аутентификации

Малый проверочный шаг: зафиксировать, что pre-auth challenge не работает как сессия и после 2FA выдаётся свежая сессия.

### Task 1.1: Тесты-инварианты ротации

**Files:**
- Test: `journal_django/apps/auth_app/tests/test_token_version.py` (дополнить) или `test_auth_api.py`

- [ ] **Step 1: Тест — challenge-токен не принимается как session-cookie**

```python
@pytest.mark.django_db
def test_challenge_token_is_not_a_session(manager_acc, settings):
    settings.ADMIN_COOKIE_SECRET = TEST_SECRET
    from apps.accounts import repository
    from apps.auth_app import services
    acc = repository.get_by_id(manager_acc)
    challenge = services.issue_challenge(acc, 'verify')  # kind=login_challenge
    c = Client()
    c.cookies['session'] = challenge
    r = c.get('/api/auth/me')
    assert r.status_code == 401  # challenge != session: нет account_id-сессии
```

- [ ] **Step 2: Прогнать**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/auth_app/tests/test_token_version.py -q -k challenge`
Expected: PASS (challenge payload содержит `kind`, но проходит HMAC; однако `verify_session_cookie` принимает любой валидный HMAC с `exp` → ShimUser создастся! См. Step 3).

- [ ] **Step 3: Если тест упал (200 вместо 401) — закрыть дыру**

`issue_challenge` payload: `{kind, stage, account_id, role, exp}` — без `iat`, но `verify_session_cookie` его пропустит и `get_auth_state` найдёт аккаунт → сессия пройдёт. Это и есть Session Fixation-риск. Закрыть в `HmacSessionAuthentication.authenticate`: после `verify_session_cookie`, отклонять токены с `kind`:

```python
        payload = verify_session_cookie(token)
        if payload is None:
            return None
        # session-cookie не имеет 'kind'; challenge/email2fa-токены отклоняем.
        if payload.get('kind'):
            return None
```

(вставить перед stateful-проверкой из Task 0.4)

- [ ] **Step 4: Прогнать снова**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/auth_app -q`
Expected: PASS.

---

## ШАГ 2 — Модель invites + repository + сервис выписки

Изолированно, без смены публичного контракта эндпоинтов → 606 тестов остаются зелёными.

### Task 2.1: Модель `AccountInvite` + миграция

**Files:**
- Modify: `journal_django/apps/accounts/models.py`
- Create: `journal_django/apps/accounts/migrations/0003_account_invites.py`

- [ ] **Step 1: Добавить модель**

В `models.py`, после `AccountRecoveryCode`:

```python
class AccountInvite(models.Model):
    """Invite на установку/смену пароля. token_hash = sha256(plaintext)."""

    id = models.AutoField(primary_key=True)
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, db_column='account_id',
        related_name='invites',
    )
    token_hash = models.TextField()
    created_by = models.ForeignKey(
        Account, on_delete=models.DO_NOTHING, db_column='created_by',
        related_name='+', null=True, blank=True,
    )
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = 'account_invites'
        indexes = [
            models.Index(fields=['token_hash'], name='account_invites_hash_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['account'], name='account_invites_one_active',
                condition=models.Q(used_at__isnull=True, revoked_at__isnull=True),
            ),
        ]
```

- [ ] **Step 2: Написать миграцию**

`0003_account_invites.py`:

```python
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_account_token_version'),
    ]

    operations = [
        migrations.CreateModel(
            name='AccountInvite',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('token_hash', models.TextField()),
                ('created_at', models.DateTimeField()),
                ('expires_at', models.DateTimeField()),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('account', models.ForeignKey(db_column='account_id', on_delete=django.db.models.deletion.CASCADE, related_name='invites', to='accounts.account')),
                ('created_by', models.ForeignKey(blank=True, db_column='created_by', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='accounts.account')),
            ],
            options={'db_table': 'account_invites', 'managed': True},
        ),
        migrations.AddIndex(
            model_name='accountinvite',
            index=models.Index(fields=['token_hash'], name='account_invites_hash_idx'),
        ),
        migrations.AddConstraint(
            model_name='accountinvite',
            constraint=models.UniqueConstraint(
                condition=models.Q(('used_at__isnull', True), ('revoked_at__isnull', True)),
                fields=('account',), name='account_invites_one_active'),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE account_invites ALTER COLUMN created_at SET DEFAULT now();",
            reverse_sql="ALTER TABLE account_invites ALTER COLUMN created_at DROP DEFAULT;",
        ),
        # M1: password_hash становится nullable (состояние «приглашён без пароля»).
        migrations.AlterField(
            model_name='account',
            name='password_hash',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE accounts ALTER COLUMN password_hash DROP NOT NULL;",
            reverse_sql="ALTER TABLE accounts ALTER COLUMN password_hash SET NOT NULL;",
        ),
    ]
```

- [ ] **Step 3: Обновить модель `Account.password_hash`**

В `models.py`:

```python
    password_hash = models.TextField(null=True, blank=True)
```

- [ ] **Step 4: Применить + чекпоинт**

Run: `cd journal_django && .venv/Scripts/python.exe manage.py migrate accounts`
Expected: `Applying accounts.0003_account_invites... OK`
Run: `cd journal_django && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

### Task 2.2: Утилиты invite-токена

**Files:**
- Modify: `journal_django/apps/core/utils/passwords.py`
- Test: `journal_django/apps/accounts/tests/test_invites_repository.py` (создать в Task 2.3 покрывает; здесь — доверяем)

- [ ] **Step 1: Реализовать генератор и хешер**

В `passwords.py` добавить (импорт `hashlib` вверху):

```python
import hashlib

INVITE_TTL_HOURS = 48


def generate_invite_token() -> tuple[str, str]:
    """(plaintext, sha256_hex). Plaintext отдаётся один раз, в БД — только hash."""
    token = secrets.token_urlsafe(32)
    return token, hash_invite_token(token)


def hash_invite_token(token: str) -> str:
    """SHA-256 hex от invite-токена. Без соли: high-entropy random (256 бит)."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()
```

- [ ] **Step 2: Чекпоинт**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/core -q`
Expected: PASS.

### Task 2.3: repository invite-функции

**Files:**
- Modify: `journal_django/apps/accounts/repository.py`
- Test: `journal_django/apps/accounts/tests/test_invites_repository.py` (создать)
- Modify: `journal_django/apps/accounts/tests/conftest.py` (фабрика invite + очистка)

- [ ] **Step 1: Очистка invites в фабрике**

В `conftest.py`, в `account_factory` cleanup-блоке, перед `DELETE FROM accounts`:

```python
            cur.execute('DELETE FROM account_invites WHERE account_id = %s', [acc_id])
```

(аналогично в `cleanup_email` cleanup-блоке, перед `DELETE FROM accounts`)

- [ ] **Step 2: Написать падающие тесты**

`test_invites_repository.py`:

```python
"""Repository invite: создание/поиск/гашение/отзыв, один активный, срок."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import repository
from apps.core.utils.passwords import generate_invite_token


@pytest.mark.django_db
def test_create_and_find_active(account_factory):
    acc = account_factory(email='__inv1__@x.com', role='manager')
    _, h = generate_invite_token()
    repository.create_invite(acc, h, created_by=acc)
    found = repository.find_active_by_hash(h)
    assert found is not None and found['account_id'] == acc


@pytest.mark.django_db
def test_expired_not_active(account_factory):
    acc = account_factory(email='__inv2__@x.com', role='manager')
    _, h = generate_invite_token()
    repository.create_invite(acc, h, created_by=acc,
                             expires_at=timezone.now() - timedelta(hours=1))
    assert repository.find_active_by_hash(h) is None


@pytest.mark.django_db
def test_revoke_active(account_factory):
    acc = account_factory(email='__inv3__@x.com', role='manager')
    _, h = generate_invite_token()
    repository.create_invite(acc, h, created_by=acc)
    repository.revoke_active_for_account(acc)
    assert repository.find_active_by_hash(h) is None


@pytest.mark.django_db
def test_accept_marks_used_and_sets_password(account_factory):
    acc = account_factory(email='__inv4__@x.com', role='manager')
    _, h = generate_invite_token()
    repository.create_invite(acc, h, created_by=acc)
    res = repository.accept_invite(h, password_hash='$2b$12$' + 'x' * 22)
    assert res is not None and res['account_id'] == acc
    # второй accept того же токена → None (used)
    assert repository.accept_invite(h, password_hash='$2b$12$' + 'y' * 22) is None
    # token_version инкрементнулся
    assert repository.get_auth_state(acc)['token_version'] == 1
```

- [ ] **Step 3: Прогнать — падает**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/accounts/tests/test_invites_repository.py -q`
Expected: FAIL (нет функций).

- [ ] **Step 4: Реализовать**

В `repository.py` добавить (импорты вверху: `from datetime import timedelta`, `from django.utils import timezone`, и `AccountInvite` в `from .models import ...`):

```python
def create_invite(account_id, token_hash, created_by, ttl_hours=48, expires_at=None):
    """Создать invite. expires_at по умолчанию created_at + ttl_hours."""
    now = timezone.now()
    obj = AccountInvite.objects.create(
        account_id=account_id,
        token_hash=token_hash,
        created_by_id=created_by,
        created_at=now,
        expires_at=expires_at if expires_at is not None else now + timedelta(hours=ttl_hours),
    )
    return dictrow(AccountInvite.objects.filter(pk=obj.pk).values())


def find_active_by_hash(token_hash):
    """Активный invite по hash (не использован, не отозван, не просрочен) или None."""
    return dictrow(
        AccountInvite.objects.filter(
            token_hash=token_hash, used_at__isnull=True, revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).values()
    )


def revoke_active_for_account(account_id):
    """Отозвать все активные invite аккаунта (ленивая очистка)."""
    return AccountInvite.objects.filter(
        account_id=account_id, used_at__isnull=True, revoked_at__isnull=True,
    ).update(revoked_at=Now())


def accept_invite(token_hash, password_hash):
    """
    Атомарно: погасить invite (FOR UPDATE), поставить пароль, инкрементить
    token_version. Возвращает {account_id} или None (невалидный/гонка).
    """
    with transaction.atomic():
        inv = (
            AccountInvite.objects.select_for_update()
            .filter(token_hash=token_hash, used_at__isnull=True, revoked_at__isnull=True)
            .first()
        )
        if inv is None or inv.expires_at <= timezone.now():
            return None
        inv.used_at = timezone.now()
        inv.save(update_fields=['used_at'])
        Account.objects.filter(id=inv.account_id).update(
            password_hash=password_hash,
            token_version=F('token_version') + 1,
        )
        return {'account_id': inv.account_id}
```

- [ ] **Step 5: Прогнать — зелёное**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/accounts/tests/test_invites_repository.py -q`
Expected: 4 PASS.

### Task 2.4: Сервис выписки invite в `accounts.services`

**Files:**
- Modify: `journal_django/apps/accounts/services.py`
- Test: `journal_django/apps/accounts/tests/test_invites_service.py` (создать)

- [ ] **Step 1: Написать падающий тест**

`test_invites_service.py`:

```python
"""Service accounts: выписка/перевыписка invite, create_account без пароля."""
from __future__ import annotations

import pytest

from apps.accounts import services, repository


class _Req:
    META = {}


@pytest.mark.django_db
def test_issue_invite_returns_url(account_factory):
    acc = account_factory(email='__svc1__@x.com', role='manager')
    res = services.issue_invite(acc, actor_account_id=acc, request=_Req())
    assert res['invite_url'].startswith('/login/set-password?token=')
    assert 'expires_at' in res
    # активный invite появился
    from apps.core.utils.passwords import hash_invite_token
    token = res['invite_url'].split('token=', 1)[1]
    assert repository.find_active_by_hash(hash_invite_token(token)) is not None


@pytest.mark.django_db
def test_regenerate_revokes_old(account_factory):
    from apps.core.utils.passwords import hash_invite_token
    acc = account_factory(email='__svc2__@x.com', role='manager')
    r1 = services.issue_invite(acc, actor_account_id=acc, request=_Req())
    t1 = r1['invite_url'].split('token=', 1)[1]
    services.issue_invite(acc, actor_account_id=acc, request=_Req())
    # старый токен больше не активен
    assert repository.find_active_by_hash(hash_invite_token(t1)) is None
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/accounts/tests/test_invites_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Реализовать `issue_invite`**

В `services.py` добавить (импорты: `from django.db import transaction`, `from apps.core.utils.passwords import generate_invite_token, INVITE_TTL_HOURS`):

```python
def _invite_url(token: str) -> str:
    """Относительный URL страницы установки пароля (без хоста — фронт на том же origin)."""
    return f'/login/set-password?token={token}'


def issue_invite(account_id: int, actor_account_id: Optional[int], request) -> dict:
    """
    Выписать invite: отозвать активные старые + создать новый.
    Возвращает {invite_url, expires_at}. Plaintext-токен — только в URL, один раз.
    """
    token, token_hash = generate_invite_token()
    with transaction.atomic():
        repository.revoke_active_for_account(account_id)
        inv = repository.create_invite(
            account_id, token_hash, created_by=actor_account_id,
            ttl_hours=INVITE_TTL_HOURS,
        )
    log_event(
        event='invite_created', account_id=actor_account_id, target_id=account_id,
        request=request,
    )
    return {'invite_url': _invite_url(token), 'expires_at': inv['expires_at']}
```

- [ ] **Step 4: Прогнать — зелёное**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/accounts/tests/test_invites_service.py -q`
Expected: 2 PASS.

---

## ШАГ 3 — auth-эндпоинты invite (`GET /invite`, `POST /invite/accept`)

### Task 3.1: Сервис потребления invite в `auth_app.services`

**Files:**
- Modify: `journal_django/apps/auth_app/services.py`
- Test: `journal_django/apps/auth_app/tests/test_invite_flow.py` (создать)

- [ ] **Step 1: Написать падающие тесты**

`test_invite_flow.py`:

```python
"""invite_lookup / invite_accept: пароль ставится, токен гасится, выдаётся enroll."""
from __future__ import annotations

import pytest

from apps.accounts import services as acc_services, repository
from apps.auth_app import services as auth_services


class _Req:
    META = {}


def _make_invite(account_factory):
    acc = account_factory(email='__if__@x.com', role='manager')
    res = acc_services.issue_invite(acc, actor_account_id=acc, request=_Req())
    token = res['invite_url'].split('token=', 1)[1]
    return acc, token


@pytest.mark.django_db
def test_lookup_valid(account_factory):
    acc, token = _make_invite(account_factory)
    data, status_code = auth_services.invite_lookup(token)
    assert status_code == 200
    assert data == {'valid': True, 'email': '__if__@x.com', 'role': 'manager'}


@pytest.mark.django_db
def test_lookup_invalid_is_opaque(account_factory):
    data, status_code = auth_services.invite_lookup('nonexistent-token')
    assert status_code == 200
    assert data == {'valid': False}  # без email/role/причины (анти-энумерация)


@pytest.mark.django_db
def test_accept_sets_password_and_returns_enroll(account_factory):
    acc, token = _make_invite(account_factory)
    data, status_code, account = auth_services.invite_accept(
        token, 'newpassw0rd', request=_Req())
    assert status_code == 200
    assert account is None  # НЕ сессия
    assert 'challenge_token' in data
    ch = auth_services.read_challenge(data['challenge_token'])
    assert ch['stage'] == 'enroll' and ch['account_id'] == acc
    # пароль установлен
    full = repository.get_by_id(acc)
    from apps.core.utils.passwords import verify_password
    assert verify_password('newpassw0rd', full['password_hash'])


@pytest.mark.django_db
def test_double_accept_rejected(account_factory):
    acc, token = _make_invite(account_factory)
    auth_services.invite_accept(token, 'newpassw0rd', request=_Req())
    data, status_code, account = auth_services.invite_accept(
        token, 'otherpass1', request=_Req())
    assert status_code == 400
    assert account is None
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/auth_app/tests/test_invite_flow.py -q`
Expected: FAIL.

- [ ] **Step 3: Реализовать**

В `auth_app/services.py` добавить (импорт: `from apps.core.utils.passwords import hash_invite_token, hash_password`):

```python
def invite_lookup(token: str) -> Tuple[dict, int]:
    """GET /invite: вернуть {valid, email, role} или единое {valid:False}."""
    inv = accounts_repo.find_active_by_hash(hash_invite_token(token))
    if inv is None:
        return {'valid': False}, 200
    acc = accounts_repo.get_by_id(inv['account_id'])
    if acc is None:
        return {'valid': False}, 200
    return {'valid': True, 'email': acc['email'], 'role': acc['role']}, 200


def invite_accept(token: str, password: str, request=None) -> Tuple[dict, int, Optional[dict]]:
    """
    POST /invite/accept: погасить invite, поставить пароль, выдать enroll-challenge.
    НЕ выдаёт сессию (account=None). Невалидный токен/гонка → 400 (единый ответ).
    """
    res = accounts_repo.accept_invite(hash_invite_token(token), hash_password(password))
    if res is None:
        return {'error': 'Ссылка недействительна'}, 400, None
    account_id = res['account_id']
    acc = accounts_repo.get_by_id(account_id)
    log_event('invite_used', account_id=account_id, actor_email=acc['email'], request=request)
    return {'challenge_token': issue_challenge(acc, 'enroll')}, 200, None
```

- [ ] **Step 4: Прогнать — зелёное**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/auth_app/tests/test_invite_flow.py -q`
Expected: 4 PASS.

### Task 3.2: Serializer + Views + URLs для invite

**Files:**
- Modify: `journal_django/apps/auth_app/serializers.py`
- Modify: `journal_django/apps/auth_app/views.py`
- Modify: `journal_django/apps/auth_app/urls.py`
- Test: `journal_django/apps/auth_app/tests/test_invite_flow.py` (дополнить API-тестом)

- [ ] **Step 1: Serializer**

В `serializers.py` добавить:

```python
class InviteAcceptSerializer(serializers.Serializer):
    """Порт invite/accept: {token, password}. Пароль ≥ 8 символов."""

    token = serializers.CharField(min_length=1)
    password = serializers.CharField(min_length=8)
```

- [ ] **Step 2: Рефактор rate-limit на «ведра» (готовим Шаг 6)**

В `views.py` заменить `_check_rate_limit(request)` на параметризуемую версию:

```python
def _check_rate_limit(request: Request, bucket: str = 'auth',
                      max_hits: int = _RATE_MAX, window_s: int = _RATE_WINDOW_S) -> bool:
    """True если разрешено. Ключ (bucket, ip), окно window_s, лимит max_hits."""
    ip = _get_client_ip(request)
    key = f'{bucket}:{ip}'
    now = time.time()
    cutoff = now - window_s
    with _rate_lock:
        hits = [t for t in _rate_store.get(key, []) if t > cutoff]
        if len(hits) >= max_hits:
            _rate_store[key] = hits
            return False
        hits.append(now)
        _rate_store[key] = hits
        return True
```

(существующие вызовы `_check_rate_limit(request)` продолжают работать — bucket='auth' по умолчанию)

- [ ] **Step 3: Views**

В `views.py` добавить:

```python
class InviteLookupView(APIView):
    """GET /api/auth/invite?token=… — проверка активности invite. AllowAny."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request: Request) -> Response:
        if not _check_rate_limit(request, bucket='invite'):
            return Response(_RATE_EXCEEDED, status=status.HTTP_429_TOO_MANY_REQUESTS)
        token = request.query_params.get('token', '')
        if not token:
            return Response({'valid': False})
        data, http_status = services.invite_lookup(token)
        return Response(data, status=http_status)


class InviteAcceptView(APIView):
    """POST /api/auth/invite/accept {token, password} — установка пароля. AllowAny."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request: Request) -> Response:
        if not _check_rate_limit(request, bucket='invite'):
            return Response(_RATE_EXCEEDED, status=status.HTTP_429_TOO_MANY_REQUESTS)
        s = InviteAcceptSerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        data, http_status, account = services.invite_accept(
            token=s.validated_data['token'],
            password=s.validated_data['password'],
            request=request,
        )
        return Response(data, status=http_status)
```

(добавить `InviteAcceptSerializer` в импорт из serializers)

- [ ] **Step 4: URLs**

В `urls.py` добавить ПОСЛЕ `/me`, ДО `/login/2fa` (важно: `/invite` и `/invite/accept` не конфликтуют):

```python
    path('/invite', InviteLookupView.as_view(), name='auth-invite-lookup'),
    path('/invite/accept', InviteAcceptView.as_view(), name='auth-invite-accept'),
```

(добавить оба view в импорт)

- [ ] **Step 5: API-тест happy-path + гонка**

В `test_invite_flow.py` добавить:

```python
import pytest
from django.test import Client


@pytest.mark.django_db
def test_invite_api_lookup_and_accept(account_factory, settings):
    settings.ADMIN_COOKIE_SECRET = 'deadbeef' * 16
    acc, token = _make_invite(account_factory)
    c = Client()
    r = c.get(f'/api/auth/invite?token={token}')
    assert r.status_code == 200 and r.json()['valid'] is True
    r2 = c.post('/api/auth/invite/accept',
                data={'token': token, 'password': 'newpassw0rd'},
                content_type='application/json')
    assert r2.status_code == 200 and 'challenge_token' in r2.json()
    assert 'session' not in r2.cookies  # сессия не выдаётся
```

- [ ] **Step 6: Чекпоинт — полный прогон**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

---

## ШАГ 4 — Смена контракта админки (ломающий)

### Task 4.1: `create_account` и `reset_password` через invite

**Files:**
- Modify: `journal_django/apps/accounts/services.py`
- Modify: `journal_django/apps/accounts/repository.py` (create_account без обязательного пароля)
- Test: `journal_django/apps/accounts/tests/test_invites_service.py`, `test_accounts_api.py`

- [ ] **Step 1: Тест нового контракта**

В `test_invites_service.py` добавить:

```python
@pytest.mark.django_db
def test_create_account_invited_no_password(cleanup_email):
    cleanup_email.append('__new__@x.com')
    res = services.create_account(
        {'email': '__new__@x.com', 'role': 'manager', 'teacher_id': None},
        actor_account_id=None, request=_Req())
    assert 'password' not in res
    assert res['invite_url'].startswith('/login/set-password?token=')
    assert 'expires_at' in res
    # password_hash в БД пуст
    full = repository.find_by_email('__new__@x.com')
    assert full['password_hash'] is None


@pytest.mark.django_db
def test_reset_password_returns_invite(account_factory):
    acc = account_factory(email='__rp__@x.com', role='manager')
    res = services.reset_password(acc, actor_account_id=acc, request=_Req())
    assert res['invite_url'].startswith('/login/set-password?token=')
    assert 'password' not in res
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/accounts/tests/test_invites_service.py -q -k "invited or reset_password"`
Expected: FAIL.

- [ ] **Step 3: repository.create_account — пароль опционален**

В `repository.py`, `create_account` сигнатуру и тело:

```python
def create_account(email: str, password_hash=None, role: str = None, teacher_id=None) -> dict:
    """INSERT учётки (RETURNING *). password_hash=None → состояние «приглашён»."""
    obj = Account.objects.create(
        email=email,
        password_hash=password_hash,
        role=role,
        teacher_id=teacher_id,
        created_at=Now(),
    )
    return dictrow(Account.objects.filter(pk=obj.pk).values())
```

- [ ] **Step 4: services.create_account / reset_password**

Заменить `create_account` в `services.py`:

```python
def create_account(data: dict, actor_account_id, request: Request) -> dict:
    """Создать «приглашённую» учётку (без пароля) + выписать invite."""
    email = data['email']
    role = data['role']
    teacher_id = data.get('teacher_id')

    if repository.find_by_email(email) is not None:
        return {'error': 'email_taken'}

    acc = repository.create_account(email=email, role=role, teacher_id=teacher_id)
    log_event(
        event='account_created', account_id=actor_account_id, target_id=acc['id'],
        meta={'email': email, 'role': role}, request=request,
    )
    invite = issue_invite(acc['id'], actor_account_id, request)
    return {
        'id': acc['id'], 'email': acc['email'], 'role': acc['role'],
        'teacher_id': acc['teacher_id'],
        'invite_url': invite['invite_url'], 'expires_at': invite['expires_at'],
    }
```

Заменить `reset_password`:

```python
def reset_password(account_id: int, actor_account_id, request: Request) -> Optional[dict]:
    """Смена пароля = новый invite (не temp-пароль). None если учётки нет."""
    acc = repository.get_by_id(account_id)
    if acc is None:
        return None
    invite = issue_invite(account_id, actor_account_id, request)
    log_event(event='password_reset', account_id=actor_account_id,
              target_id=account_id, request=request)
    return {'invite_url': invite['invite_url'], 'expires_at': invite['expires_at']}
```

(удалить неиспользуемый импорт `generate_token_password`, `hash_password` если больше не нужны в services — проверить)

- [ ] **Step 5: Прогнать + поправить старые API-тесты**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/accounts -q`
Expected: новые PASS; старые `test_accounts_api.py`, проверявшие `password` в ответе POST/reset-password, упадут.
Обновить их: ожидать `invite_url` вместо `password` (POST 201 → `{id,email,role,teacher_id,invite_url,expires_at}`; reset-password → `{invite_url,expires_at}`).

- [ ] **Step 6: Чекпоинт**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/accounts -q`
Expected: PASS.

### Task 4.2: Эндпоинты `/invite` и `/invite/revoke` + статус в списке

**Files:**
- Modify: `journal_django/apps/accounts/services.py`, `repository.py`, `views.py`, `urls.py`
- Test: `journal_django/apps/accounts/tests/test_accounts_api.py`

- [ ] **Step 1: services — regenerate / revoke**

В `services.py`:

```python
def regenerate_invite(account_id: int, actor_account_id, request: Request) -> Optional[dict]:
    """Перевыписать invite. None если учётки нет."""
    if repository.get_by_id(account_id) is None:
        return None
    return issue_invite(account_id, actor_account_id, request)


def revoke_invite(account_id: int, actor_account_id, request: Request) -> bool:
    """Отозвать активные invite аккаунта. False если учётки нет."""
    if repository.get_by_id(account_id) is None:
        return False
    repository.revoke_active_for_account(account_id)
    log_event(event='invite_revoked', account_id=actor_account_id,
              target_id=account_id, request=request)
    return True
```

- [ ] **Step 2: Статус в списке (repository)**

В `repository.list_accounts`, аннотировать активный invite через `Exists` и вычислить статус. Заменить блок `rows = dictrows(...)`:

```python
    from django.db.models import Exists, OuterRef
    active_inv = AccountInvite.objects.filter(
        account_id=OuterRef('id'), used_at__isnull=True,
        revoked_at__isnull=True, expires_at__gt=Now(),
    )
    rows = dictrows(
        ordered[offset:offset + page_size].annotate(
            has_active_invite=Exists(active_inv),
        ).values(
            *_LIST_FIELDS,
            teacher_name=F('teacher__name'),
            has_active_invite=Exists(active_inv),
        )
    )
    for r in rows:
        r['status'] = _account_status(r)
```

Добавить helper:

```python
def _account_status(row: dict) -> str:
    """invited | active | expired | disabled (вычисляемый, не хранится)."""
    if not row.get('active'):
        return 'disabled'
    if row.get('last_login_at'):
        return 'active'
    if row.get('has_active_invite'):
        return 'invited'
    return 'expired'
```

- [ ] **Step 3: Views + URLs**

В `views.py` добавить:

```python
class AccountInviteView(APIView):
    """POST /:id/invite — перевыписать invite-ссылку."""

    permission_classes = [IsAdmin]

    def post(self, request: Request, pk: int) -> Response:
        res = services.regenerate_invite(pk, actor_account_id=request.user.account_id, request=request)
        if res is None:
            raise NotFound({'error': 'Not found'})
        return Response(res)


class AccountInviteRevokeView(APIView):
    """POST /:id/invite/revoke — отозвать активный invite."""

    permission_classes = [IsAdmin]

    def post(self, request: Request, pk: int) -> Response:
        ok = services.revoke_invite(pk, actor_account_id=request.user.account_id, request=request)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response({'ok': True})
```

В `urls.py` добавить (ДО `/<int:pk>/reset-2fa`, чтобы литералы не конфликтовали — `/invite/revoke` длиннее, ставить раньше `/invite`):

```python
    path('/<int:pk>/invite/revoke', AccountInviteRevokeView.as_view(), name='accounts-invite-revoke'),
    path('/<int:pk>/invite', AccountInviteView.as_view(), name='accounts-invite'),
```

- [ ] **Step 4: Тесты API**

В `test_accounts_api.py` добавить проверки: POST `/:id/invite` → 200 `{invite_url,expires_at}`; POST `/:id/invite/revoke` → 200 `{ok:true}`; список содержит `status`.

- [ ] **Step 5: Чекпоинт**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

### Task 4.3: Frontend — страница установки пароля + правки admin SPA

**Files:**
- Create: `journal_django/frontend/login/set-password.html`, `set-password.js`
- Modify: `journal_django/config/urls_dev.py` (раздача `/login/set-password`)
- Modify: `journal_django/frontend/admin-src/src/hooks/useAccounts.ts`, `.../pages/accounts/AccountsPage.tsx`

- [ ] **Step 1: set-password.html**

Минимальная страница (стили переиспользуют `login/styles.css`). Экран: ввод пароля → enroll-2FA (тот же поток, что `login.js` openEnroll). Скелет:

```html
<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Установка пароля — KOTOKOD</title>
<link rel="stylesheet" href="/login/styles.css">
</head><body>
<main class="wrap">
  <section id="screen-invalid" class="hidden">
    <h1>Ссылка недействительна</h1>
    <p>Обратитесь к администратору системы.</p>
  </section>
  <section id="screen-set">
    <h1>Задайте пароль</h1>
    <p id="set-email" class="muted"></p>
    <form id="set-form">
      <input id="f-pass" type="password" autocomplete="new-password" placeholder="Новый пароль (≥ 8 символов)" minlength="8" required>
      <div id="set-err" class="err hidden"></div>
      <button type="submit">Сохранить и продолжить</button>
    </form>
  </section>
  <section id="screen-2fa" class="hidden"><!-- QR + код, как в login.js openEnroll --></section>
</main>
<script src="/login/set-password.js"></script>
</body></html>
```

- [ ] **Step 2: set-password.js**

```javascript
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const token = params.get('token') || '';
let challenge = null;

async function req(method, path, body) {
  const r = await fetch(path, {
    method, credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await r.text().then((t) => (t ? JSON.parse(t) : null));
  return { ok: r.ok, status: r.status, j };
}
function show(name) {
  ['invalid', 'set', '2fa'].forEach((k) => $(`screen-${k}`).classList.toggle('hidden', k !== name));
}
function err(msg) { const e = $('set-err'); e.textContent = msg; e.classList.remove('hidden'); }

(async function init() {
  if (!token) return show('invalid');
  const { j } = await req('GET', `/api/auth/invite?token=${encodeURIComponent(token)}`);
  if (!j || !j.valid) return show('invalid');
  $('set-email').textContent = j.email;
  show('set');
})();

$('set-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const password = $('f-pass').value;
  if (password.length < 8) return err('Пароль не короче 8 символов');
  const { ok, j } = await req('POST', '/api/auth/invite/accept', { token, password });
  if (!ok || !j.challenge_token) return err((j && j.error) || 'Ссылка недействительна');
  challenge = j.challenge_token;
  // обязательный 2FA-enrollment: тот же поток, что login.js openEnroll (totp по умолчанию)
  const setup = await req('POST', '/api/auth/2fa/setup', { challenge_token: challenge, method: 'totp' });
  if (!setup.ok) return err('Ошибка настройки 2FA');
  $('screen-2fa').innerHTML =
    '<h1>Настройте 2FA</h1><img id="qr" alt="QR"><form id="enable-form">' +
    '<input id="f-code" inputmode="numeric" autocomplete="one-time-code" placeholder="Код из приложения" required>' +
    '<div id="en-err" class="err hidden"></div><button>Включить</button></form>';
  $('qr').src = setup.j.qr;
  show('2fa');
  $('enable-form').addEventListener('submit', async (e2) => {
    e2.preventDefault();
    const code = $('f-code').value.trim();
    const res = await req('POST', '/api/auth/2fa/enable', { challenge_token: challenge, code });
    if (!res.ok) { const e = $('en-err'); e.textContent = res.j.error || 'Неверный код'; e.classList.remove('hidden'); return; }
    if (res.j.recovery_codes) {
      alert('Сохраните резервные коды:\n' + res.j.recovery_codes.join('  '));
    }
    window.location = res.j.redirect || '/';
  });
});
```

- [ ] **Step 3: Раздача в dev**

В `config/urls_dev.py`, в `dev_urlpatterns`, ПЕРЕД `^login/(?P<path>.*)$` добавить точечный маршрут:

```python
    re_path(r"^login/set-password$",
            lambda req: serve(req, "set-password.html", document_root=_LOGIN_DIR),
            name="dev_set_password"),
```

(существующий `^login/(?P<path>.*)$` уже отдаёт `set-password.js` как статику)

- [ ] **Step 4: admin SPA hooks**

В `useAccounts.ts` заменить `CreatedAccount` и мутации:

```typescript
export interface InviteResult {
  invite_url: string;
  expires_at: string;
}
export interface CreatedAccount extends InviteResult {
  id: number;
  email: string;
  role: Role;
  teacher_id: number | null;
}
```

`create.mutationFn` тип ответа → `CreatedAccount`; `resetPassword.mutationFn` → `api<InviteResult>(...)`; добавить:

```typescript
    invite: useMutation({
      mutationFn: (id: number) => api<InviteResult>('POST', `/api/admin/accounts/${id}/invite`),
      onSuccess: invalidate,
    }),
    revokeInvite: useMutation({
      mutationFn: (id: number) => api<{ ok: true }>('POST', `/api/admin/accounts/${id}/invite/revoke`),
      onSuccess: invalidate,
    }),
```

- [ ] **Step 5: AccountsPage.tsx**

Заменить отображение «временный пароль» на «invite-ссылку» (копировать в буфер). Добавить колонку `status`. Добавить кнопки «Перевыписать ссылку» / «Отозвать». (Детали верстки — по образцу существующего показа пароля; UI-токены из `tokens.css`, native-элементы запрещены.)

- [ ] **Step 6: Сборка admin + typecheck**

Run: `cd journal_django/frontend/admin-src && npm run typecheck && npm run build`
Expected: без ошибок, `../admin-dist/` обновлён.

- [ ] **Step 7: Чекпоинт**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

---

## ШАГ 5 — Обязательная 2FA + bootstrap + гейт пустой системы

### Task 5.1: `requires_2fa → True` для всех ролей

**Files:**
- Modify: `journal_django/apps/auth_app/services.py:47-49`
- Test: `journal_django/apps/auth_app/tests/test_auth_api.py` или `test_invite_flow.py`

- [ ] **Step 1: Тест — legacy-teacher без 2FA уходит в enrollment**

```python
@pytest.mark.django_db
def test_legacy_teacher_without_2fa_enrolls(account_factory, teacher_fixture, settings):
    settings.ADMIN_COOKIE_SECRET = 'deadbeef' * 16
    # teacher с паролем, без 2FA (старые данные)
    from apps.core.utils.passwords import hash_password
    from apps.accounts import repository
    acc = account_factory(email='__lt__@x.com', role='teacher', teacher_id=teacher_fixture)
    repository.set_password(acc, hash_password('legacypass1'))
    from django.test import Client
    c = Client()
    r = c.post('/api/auth/login',
               data={'email': '__lt__@x.com', 'password': 'legacypass1', 'role': 'teacher'},
               content_type='application/json')
    assert r.status_code == 200
    assert r.json().get('twofa_enrollment_required') is True
```

- [ ] **Step 2: Прогнать — падает (teacher логинится без 2FA)**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/auth_app -q -k legacy_teacher`
Expected: FAIL (сейчас teacher получает сессию).

- [ ] **Step 3: Реализовать**

В `services.py`:

```python
def requires_2fa(role: str) -> bool:
    """2FA обязательна для ВСЕХ ролей (включая teacher). Метод выбирается на онбординге."""
    return True
```

- [ ] **Step 4: Прогнать + поправить тесты, ожидавшие teacher-сессию без 2FA**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/auth_app -q`
Expected: новый PASS; ранее зелёные тесты teacher-login-без-2FA теперь ожидают enrollment — обновить.

- [ ] **Step 5: Чекпоинт**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

### Task 5.2: Management-команда `bootstrap_admin`

**Files:**
- Create: `journal_django/apps/accounts/management/__init__.py` (пустой)
- Create: `journal_django/apps/accounts/management/commands/__init__.py` (пустой)
- Create: `journal_django/apps/accounts/management/commands/bootstrap_admin.py`
- Create: `journal_django/apps/accounts/tests/test_bootstrap_command.py`

- [ ] **Step 1: Падающий тест**

`test_bootstrap_command.py`:

```python
"""bootstrap_admin: создаёт admin + печатает invite-URL; --if-empty idempotent."""
from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection


@pytest.fixture
def cleanup_admin():
    emails = []
    yield emails
    with connection.cursor() as cur:
        for e in emails:
            cur.execute('SELECT id FROM accounts WHERE email=%s', [e])
            row = cur.fetchone()
            if row:
                cur.execute('DELETE FROM account_invites WHERE account_id=%s', [row[0]])
                cur.execute('DELETE FROM security_audit_log WHERE target_id=%s OR account_id=%s', [row[0], row[0]])
                cur.execute('DELETE FROM accounts WHERE id=%s', [row[0]])


@pytest.mark.django_db
def test_bootstrap_creates_admin_and_prints_invite(cleanup_admin, settings):
    settings.ADMIN_COOKIE_SECRET = 'deadbeef' * 16
    cleanup_admin.append('__boot__@x.com')
    out = StringIO()
    call_command('bootstrap_admin', '--email=__boot__@x.com', stdout=out)
    assert '/login/set-password?token=' in out.getvalue()
    with connection.cursor() as cur:
        cur.execute("SELECT role, password_hash FROM accounts WHERE email='__boot__@x.com'")
        role, pw = cur.fetchone()
    assert role == 'admin' and pw is None
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/accounts/tests/test_bootstrap_command.py -q`
Expected: FAIL (нет команды).

- [ ] **Step 3: Реализовать команду**

`bootstrap_admin.py`:

```python
"""
Bootstrap первого администратора (замена scripts/create-account.js).

  python manage.py bootstrap_admin --email=admin@example.com [--if-empty]

Создаёт admin-учётку в состоянии «приглашён» (без пароля) и печатает invite-URL.
--if-empty: создавать только если в accounts нет ни одного admin (idempotent).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.accounts import repository, services
from apps.core.utils.passwords import normalize_email


class _NoReq:
    META = {}


class Command(BaseCommand):
    help = 'Создать первого администратора и напечатать invite-ссылку.'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument('--if-empty', action='store_true',
                            help='Создавать только если нет ни одного admin.')

    def handle(self, *args, **opts):
        email = normalize_email(opts['email'])
        if email is None:
            raise CommandError('Некорректный email.')

        if opts['if_empty'] and repository.admin_exists():
            self.stdout.write('Admin уже существует — пропуск (--if-empty).')
            return

        if repository.find_by_email(email) is not None:
            raise CommandError(f'Учётка {email} уже существует.')

        acc = repository.create_account(email=email, role='admin', teacher_id=None)
        invite = services.issue_invite(acc['id'], actor_account_id=None, request=_NoReq())
        self.stdout.write(self.style.SUCCESS(f'Создан admin {email}.'))
        self.stdout.write(f"Invite-ссылка (48 ч): {invite['invite_url']}")
```

Добавить в `repository.py`:

```python
def admin_exists() -> bool:
    """Есть ли хотя бы одна admin-учётка (для bootstrap --if-empty)."""
    return Account.objects.filter(role='admin').exists()
```

- [ ] **Step 4: Прогнать + тест --if-empty**

Добавить тест idempotent:

```python
@pytest.mark.django_db
def test_if_empty_skips_when_admin_exists(account_factory, cleanup_admin, settings):
    settings.ADMIN_COOKIE_SECRET = 'deadbeef' * 16
    account_factory(email='__existing_admin__@x.com', role='admin')
    out = StringIO()
    call_command('bootstrap_admin', '--email=__boot2__@x.com', '--if-empty', stdout=out)
    assert 'пропуск' in out.getvalue()
```

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/accounts/tests/test_bootstrap_command.py -q`
Expected: PASS.

### Task 5.3: Гейт пустой системы (dev)

**Files:**
- Modify: `journal_django/config/urls_dev.py`

- [ ] **Step 1: Вью-гейт для /admin при пустой системе**

В `urls_dev.py` заменить `_admin_spa_view` обёрткой, проверяющей наличие admin:

```python
def _admin_gate_view(request, path=''):
    from apps.accounts import repository
    if not repository.admin_exists():
        return HttpResponse(
            '<!DOCTYPE html><meta charset="utf-8"><title>Нет администратора</title>'
            '<main style="font-family:sans-serif;max-width:480px;margin:80px auto">'
            '<h1>Сначала создайте администратора</h1>'
            '<p>Запустите на сервере:</p>'
            '<pre>python manage.py bootstrap_admin --email=ВАШ_EMAIL</pre>'
            '<p>Откройте напечатанную invite-ссылку, задайте пароль и настройте 2FA.</p>'
            '</main>', content_type='text/html; charset=utf-8',
        )
    return _admin_spa_view(request, path)
```

Заменить в `dev_urlpatterns` обработчики `^admin$` и `^admin/(?P<path>.*)$` на гейт-версию (для `^admin$` → `lambda req: _admin_gate_view(req, '')`).

- [ ] **Step 2: Чекпоинт (ручной)**

Run dev-сервер, при пустой `accounts` открыть `/admin` → должна показаться страница-гейт. (Автотест опционален; гейт — dev-only удобство, в проде — nginx.)

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

---

## ШАГ 6 — Дифференцированный rate-limit + расширенный аудит

### Task 6.1: Дифференцированные пороги rate-limit

**Files:**
- Modify: `journal_django/apps/auth_app/views.py`
- Test: `journal_django/apps/auth_app/tests/test_auth_api.py`

- [ ] **Step 1: Применить пороги по эндпоинтам (по IP)**

Согласно спеке §5 (все ключи — по IP, in-memory временно):
- login: bucket='login', max=5, window=15мин → в `LoginView` вызвать `_check_rate_limit(request, 'login', 5, 15*60)`.
- 2fa verify: bucket='2fa', max=10, window=15мин → `Login2faView`.
- email-send: bucket='email_send', max=3, window=3600 → `Email2faSendView`.
- invite: bucket='invite', max=10, window=15мин → уже в InviteLookup/Accept (Task 3.2).

Обновить вызовы в соответствующих view.

- [ ] **Step 2: Тест на превышение login-порога**

```python
@pytest.mark.django_db
def test_login_rate_limited_after_5(settings):
    settings.ADMIN_COOKIE_SECRET = 'deadbeef' * 16
    from apps.auth_app.views import _reset_rate_store
    _reset_rate_store()
    from django.test import Client
    c = Client()
    for _ in range(5):
        c.post('/api/auth/login', data={'email': 'x@x.com', 'password': 'z', 'role': 'admin'},
               content_type='application/json')
    r = c.post('/api/auth/login', data={'email': 'x@x.com', 'password': 'z', 'role': 'admin'},
               content_type='application/json')
    assert r.status_code == 429
```

- [ ] **Step 3: Прогнать**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/auth_app -q -k rate`
Expected: PASS.

### Task 6.2: Аудит invite-событий (проверка покрытия)

**Files:**
- Test: `journal_django/apps/accounts/tests/test_invites_service.py`

- [ ] **Step 1: Тест — invite_created/used/revoked пишутся в security_audit_log**

```python
@pytest.mark.django_db
def test_invite_events_audited(account_factory):
    from django.db import connection
    acc = account_factory(email='__aud__@x.com', role='manager')
    services.issue_invite(acc, actor_account_id=acc, request=_Req())
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM security_audit_log WHERE event='invite_created' AND target_id=%s", [acc])
        assert cur.fetchone()[0] >= 1
```

(события `invite_used` покрыты в `test_invite_flow`; `invite_revoked` — в API-тесте Task 4.2)

- [ ] **Step 2: Прогнать**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/accounts -q -k audited`
Expected: PASS (события уже логируются в services из Шага 2/4).

### Task 6.3: Финальный полный прогон + e2e happy-path

**Files:**
- Test: `journal_django/apps/auth_app/tests/test_invite_flow.py`

- [ ] **Step 1: e2e тест полного цикла**

```python
@pytest.mark.django_db
def test_e2e_create_accept_enroll(account_factory, cleanup_email, settings):
    settings.ADMIN_COOKIE_SECRET = 'deadbeef' * 16
    cleanup_email.append('__e2e__@x.com')
    # 1. админ создаёт учётку
    res = acc_services.create_account(
        {'email': '__e2e__@x.com', 'role': 'manager', 'teacher_id': None},
        actor_account_id=None, request=_Req())
    token = res['invite_url'].split('token=', 1)[1]
    from django.test import Client
    c = Client()
    # 2. сотрудник смотрит invite
    assert c.get(f'/api/auth/invite?token={token}').json()['valid'] is True
    # 3. ставит пароль
    r = c.post('/api/auth/invite/accept',
               data={'token': token, 'password': 'strongpass1'},
               content_type='application/json')
    challenge = r.json()['challenge_token']
    # 4. 2FA setup
    setup = c.post('/api/auth/2fa/setup',
                   data={'challenge_token': challenge, 'method': 'totp'},
                   content_type='application/json').json()
    import pyotp
    code = pyotp.TOTP(setup['secret']).now()
    # 5. enable → сессия
    en = c.post('/api/auth/2fa/enable',
                data={'challenge_token': challenge, 'code': code},
                content_type='application/json')
    assert en.status_code == 200
    assert 'session' in en.cookies
    assert en.json()['redirect'] == '/admin'
```

- [ ] **Step 2: Финальный прогон всего набора**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest -q`
Expected: всё PASS (606 старых + новые).

---

## Self-Review чеклист (выполнить после реализации)

- [ ] **Покрытие спеки:** invite-flow (Ш2-3), 2FA для всех (Ш5.1), bootstrap+гейт (Ш5.2-5.3), token_version+инвалидация (Ш0), ротация сессии (Ш1), rate-limit (Ш6.1), cookie-флаги (Strict сохранён), аудит (Ш6.2), ленивая чистка invite (revoke в issue_invite). Trusted-device/step-up — НЕ в этом релизе (следующая итерация, см. спеку §«Приоритет»).
- [ ] **Секреты не текут:** invite plaintext только в URL один раз; token_hash в БД; password_hash/twofa_secret в `_SECRET_FIELDS`.
- [ ] **CHECK-инварианты:** bootstrap admin → teacher_id NULL; invite-flow не трогает twofa CHECK.
- [ ] **Анти-энумерация:** `{valid:false}` без email/role; `invite/accept` 400 единый текст.
- [ ] **Гонки:** двойной accept (FOR UPDATE), двойная выписка (partial unique).

---

## Execution Handoff

Реализация по этому плану — через subagent-driven-development: `backend-developer` пишет код задача-за-задачей, `django-developer`/`python-pro` подключаются на специфичных моментах (миграции, ORM-выражения, чистота кода), `security-engineer` ревьюит после Ш3 и Ш6, `documentation-engineer` оформляет итог в `/docs/documentation`. Оркестратор ревьюит между задачами и держит 606+ тестов зелёными на каждом чекпоинте.
