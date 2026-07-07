# Superadmin RBAC + Accounts Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ввести 4-ю роль `superadmin`, перестроить RBAC по разделам admin-платформы и расширить управление учётками (имена, отключение, удаление).

**Architecture:** Роли остаются membership-проверкой в `core/permissions.py`; добавляются явные классы (`IsSuperAdmin`, `IsAdminOrSuperAdmin`) и два method-aware класса (`ReadStaffWriteSuperAdmin`, `ReadStaffWriteAdmin`) для read/write-разделения в одной вьюхе. Фронт зеркалит матрицу единым capability-модулем `lib/permissions.ts` + route-guard `RequireRole`. Учётка получает производное имя (`full_name or teacher_name or email`), обратимое отключение (`is_active`) и hard-delete.

**Tech Stack:** Django 5 + DRF, PostgreSQL (managed=False модели, реальная БД в тестах), pytest; React 19 + TanStack Query v5 + React Router v7 (Vite).

**Спека:** `docs/superpowers/specs/2026-07-07-superadmin-rbac-accounts-design.md`

> **Замечание по git:** по `CLAUDE.md` коммит/пуш — только по явной просьбе владельца. Шаги «Commit» ниже — рекомендованные точки фиксации; выполнять их фактически только после разрешения владельца.

> **Замечание по тестам:** гонять дефолтным `pytest` (guard в `config/settings/test.py` защищает боевую БД). Клиент под роль — паттерн `_client(role)` из `apps/lessons/tests/test_lessons_api.py`. Для новой роли в тест-хелперах добавлять `'superadmin'` в карты email/ролей.

---

## Phase A — Backend: роли, модель, миграции

### Task 1: Роль superadmin + поле full_name в модели Account

**Files:**
- Modify: `journal_django/apps/accounts/models.py`
- Test: `journal_django/apps/accounts/tests/test_account_model.py` (create)

- [ ] **Step 1: Написать падающий тест**

Create `journal_django/apps/accounts/tests/test_account_model.py`:

```python
"""Юнит-тесты модели Account: роль superadmin, full_name, is_superadmin."""
from __future__ import annotations

import pytest

from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def test_superadmin_role_choice_exists():
    assert Account.Role.SUPERADMIN == 'superadmin'
    assert ('superadmin', 'Суперадминистратор') in Account.Role.choices


def test_is_superadmin_property():
    acc = Account(email='s@example.com', role='superadmin')
    assert acc.is_superadmin is True
    assert acc.is_admin is False
    assert acc.has_role('superadmin') is True


def test_full_name_field_optional():
    acc = Account(email='m@example.com', role='manager', full_name='Иван Петров')
    assert acc.full_name == 'Иван Петров'
    acc2 = Account(email='m2@example.com', role='manager')
    assert acc2.full_name in (None, '')
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && pytest apps/accounts/tests/test_account_model.py -v`
Expected: FAIL (`AttributeError: SUPERADMIN` / `full_name`).

- [ ] **Step 3: Добавить роль, поле и property**

В `journal_django/apps/accounts/models.py`, в `class Role(models.TextChoices)` добавить:

```python
    class Role(models.TextChoices):
        TEACHER = 'teacher', 'Учитель'
        MANAGER = 'manager', 'Менеджер'
        ADMIN = 'admin', 'Администратор'
        SUPERADMIN = 'superadmin', 'Суперадминистратор'
```

Сразу после поля `role = models.CharField(...)` добавить поле имени:

```python
    # Отображаемое имя (для manager/admin/superadmin; у teacher берётся из преподавателя)
    full_name = models.CharField(max_length=200, null=True, blank=True, verbose_name='full name')
```

Рядом с `is_admin` добавить property:

```python
    @property
    def is_superadmin(self):
        return self.role == self.Role.SUPERADMIN
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd journal_django && pytest apps/accounts/tests/test_account_model.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/accounts/models.py journal_django/apps/accounts/tests/test_account_model.py
git commit -m "feat(accounts): роль superadmin + поле full_name + is_superadmin"
```

---

### Task 2: Миграция — констрейнт роли, поле full_name, промоут admin→superadmin

**Files:**
- Create: `journal_django/apps/accounts/migrations/00NN_superadmin_full_name.py` (номер — следующий по порядку)
- Test: `journal_django/apps/accounts/tests/test_role_migration.py` (create)

- [ ] **Step 1: Определить номер следующей миграции**

Run: `cd journal_django && ls apps/accounts/migrations/`
Взять максимальный номер `NNNN_...` и использовать `NNNN+1`. Ниже — `00NN`.

- [ ] **Step 2: Сгенерировать заготовку и дополнить руками**

Run: `cd journal_django && python manage.py makemigrations accounts --name superadmin_full_name`
Это создаст `AddField full_name`. Затем **вручную** привести файл миграции к виду
(добавить пересоздание CHECK-констрейнта и data-миграцию промоута; порядок операций строгий):

```python
from django.db import migrations, models


def promote_admins(apps, schema_editor):
    Account = apps.get_model('accounts', 'Account')
    Account.objects.filter(role='admin').update(role='superadmin')


def demote_noop(apps, schema_editor):
    # Обратный промоут небезопасен (нельзя отличить исходных admin от super) — no-op.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '<ПРЕДЫДУЩАЯ_МИГРАЦИЯ>'),
    ]

    operations = [
        # 1. Расширить whitelist ролей ДО промоута.
        migrations.RemoveConstraint(
            model_name='account',
            name='accounts_role_check',
        ),
        migrations.AddConstraint(
            model_name='account',
            constraint=models.CheckConstraint(
                name='accounts_role_check',
                condition=models.Q(role__in=['teacher', 'manager', 'admin', 'superadmin']),
            ),
        ),
        # 2. Новое поле.
        migrations.AddField(
            model_name='account',
            name='full_name',
            field=models.CharField(blank=True, max_length=200, null=True, verbose_name='full name'),
        ),
        # 3. Промоут существующих admin → superadmin.
        migrations.RunPython(promote_admins, demote_noop),
    ]
```

> Значение `<ПРЕДЫДУЩАЯ_МИГРАЦИЯ>` и точный класс констрейнта — сверить с текущим
> `accounts_role_check` в последней миграции (условие `role__in=['teacher','manager','admin']`).

- [ ] **Step 3: Написать тест data-миграции**

Create `journal_django/apps/accounts/tests/test_role_migration.py`:

```python
"""Проверяет, что после миграций в БД разрешена роль superadmin и старые admin промоучены."""
from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db


def test_superadmin_role_accepted_by_db():
    # CHECK-констрейнт accounts_role_check должен пропускать 'superadmin'.
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO accounts (email, password, role, is_active, is_staff, is_superuser, "
            "first_name, last_name, date_joined, token_version) "
            "VALUES ('__mig_super__@example.com', '!', 'superadmin', true, false, false, '', '', NOW(), 0) "
            "RETURNING id",
        )
        acc_id = cur.fetchone()[0]
        cur.execute('DELETE FROM accounts WHERE id = %s', [acc_id])
```

- [ ] **Step 4: Применить миграцию и прогнать тест**

Run: `cd journal_django && python manage.py migrate accounts && pytest apps/accounts/tests/test_role_migration.py -v`
Expected: миграция применяется без ошибок; тест PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/accounts/migrations/ journal_django/apps/accounts/tests/test_role_migration.py
git commit -m "feat(accounts): миграция роли superadmin + full_name + промоут admin→superadmin"
```

---

### Task 3: pghistory-миграция под новое поле full_name

**Files:**
- Create: `journal_django/apps/accounts/migrations/00NN_accountevent_full_name.py` (авто)

- [ ] **Step 1: Сгенерировать миграцию event-модели**

Run: `cd journal_django && python manage.py makemigrations accounts`
Ожидается миграция, добавляющая `full_name` в трекинг-модель `AccountEvent` (pghistory).

- [ ] **Step 2: Прогнать changelog registry-тест**

Run: `cd journal_django && pytest apps/changelog/tests/ -k registry -v`
Expected: `test_registry_covers_all_tracked_models` PASS (full_name не секрет, покрыт трекингом).

- [ ] **Step 3: Применить и smoke-тест истории**

Run: `cd journal_django && python manage.py migrate accounts`
Expected: OK.

- [ ] **Step 4: Commit**

```bash
git add journal_django/apps/accounts/migrations/
git commit -m "feat(accounts): pghistory-трекинг поля full_name"
```

---

## Phase B — Backend: permission-классы и разводка вьюх

### Task 4: Новые permission-классы

**Files:**
- Modify: `journal_django/apps/core/permissions.py`
- Test: `journal_django/apps/core/tests/test_permissions.py` (create; проверить наличие `apps/core/tests/__init__.py`)

- [ ] **Step 1: Написать падающие тесты**

Create `journal_django/apps/core/tests/test_permissions.py`:

```python
"""Юнит-тесты permission-классов (без HTTP: мок request.user + method)."""
from __future__ import annotations

from types import SimpleNamespace

from rest_framework.permissions import SAFE_METHODS

from apps.core.permissions import (
    IsSuperAdmin,
    IsAdminOrSuperAdmin,
    IsManagerOrAdmin,
    ReadStaffWriteSuperAdmin,
    ReadStaffWriteAdmin,
)


def _req(role, method='GET'):
    user = SimpleNamespace(is_authenticated=True, role=role)
    return SimpleNamespace(user=user, method=method)


def test_is_superadmin():
    assert IsSuperAdmin().has_permission(_req('superadmin'), None) is True
    for r in ('admin', 'manager', 'teacher'):
        assert IsSuperAdmin().has_permission(_req(r), None) is False


def test_is_admin_or_superadmin():
    for r in ('admin', 'superadmin'):
        assert IsAdminOrSuperAdmin().has_permission(_req(r), None) is True
    for r in ('manager', 'teacher'):
        assert IsAdminOrSuperAdmin().has_permission(_req(r), None) is False


def test_manager_or_admin_includes_superadmin():
    for r in ('manager', 'admin', 'superadmin'):
        assert IsManagerOrAdmin().has_permission(_req(r), None) is True
    assert IsManagerOrAdmin().has_permission(_req('teacher'), None) is False


def test_read_staff_write_superadmin():
    p = ReadStaffWriteSuperAdmin()
    for r in ('manager', 'admin', 'superadmin'):
        assert p.has_permission(_req(r, 'GET'), None) is True
    for r in ('manager', 'admin'):
        assert p.has_permission(_req(r, 'POST'), None) is False
    assert p.has_permission(_req('superadmin', 'DELETE'), None) is True


def test_read_staff_write_admin():
    p = ReadStaffWriteAdmin()
    for r in ('manager', 'admin', 'superadmin'):
        assert p.has_permission(_req(r, 'GET'), None) is True
    assert p.has_permission(_req('manager', 'PATCH'), None) is False
    for r in ('admin', 'superadmin'):
        assert p.has_permission(_req(r, 'PATCH'), None) is True
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && pytest apps/core/tests/test_permissions.py -v`
Expected: FAIL (ImportError новых классов).

- [ ] **Step 3: Реализовать классы**

В `journal_django/apps/core/permissions.py` добавить `SAFE_METHODS` в импорт и расширить
`IsManagerOrAdmin`, затем добавить новые классы:

```python
from rest_framework.permissions import BasePermission, SAFE_METHODS
```

Изменить `IsManagerOrAdmin.has_permission`:

```python
class IsManagerOrAdmin(BasePermission):
    """Allow access to manager, admin or superadmin."""
    message = 'Manager or admin role required.'

    def has_permission(self, request: Request, view: APIView) -> bool:
        return _authenticated_with_role(request, 'manager', 'admin', 'superadmin')
```

Добавить в конец файла:

```python
class IsSuperAdmin(BasePermission):
    """Allow access only to superadmin."""
    message = 'Superadmin role required.'

    def has_permission(self, request: Request, view: APIView) -> bool:
        return _authenticated_with_role(request, 'superadmin')


class IsAdminOrSuperAdmin(BasePermission):
    """Allow access to admin or superadmin."""
    message = 'Admin or superadmin role required.'

    def has_permission(self, request: Request, view: APIView) -> bool:
        return _authenticated_with_role(request, 'admin', 'superadmin')


class ReadStaffWriteSuperAdmin(BasePermission):
    """SAFE-методы — manager/admin/superadmin; мутации — только superadmin."""
    message = 'Read for staff; write for superadmin only.'

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method in SAFE_METHODS:
            return _authenticated_with_role(request, 'manager', 'admin', 'superadmin')
        return _authenticated_with_role(request, 'superadmin')


class ReadStaffWriteAdmin(BasePermission):
    """SAFE-методы — manager/admin/superadmin; мутации — admin/superadmin."""
    message = 'Read for staff; write for admin or superadmin.'

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method in SAFE_METHODS:
            return _authenticated_with_role(request, 'manager', 'admin', 'superadmin')
        return _authenticated_with_role(request, 'admin', 'superadmin')
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd journal_django && pytest apps/core/tests/test_permissions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/core/permissions.py journal_django/apps/core/tests/test_permissions.py
git commit -m "feat(core): permission-классы IsSuperAdmin/IsAdminOrSuperAdmin/ReadStaffWrite*"
```

---

### Task 5: Разводка write-super разделов (teachers, directions, memberships, discounts)

**Files:**
- Modify: `journal_django/apps/teachers/views.py`, `journal_django/apps/directions/views.py`, `journal_django/apps/memberships/views.py`, `journal_django/apps/discounts/views.py`
- Test: расширить `apps/teachers/tests/test_teachers_api.py` (и аналоги при наличии)

- [ ] **Step 1: Написать падающий тест (teachers)**

Добавить в `journal_django/apps/teachers/tests/test_teachers_api.py` (использовать существующий
в файле паттерн клиента под роль; при необходимости добавить `'superadmin'` в карту email):

```python
def test_manager_and_admin_can_read_but_not_write_teachers():
    # GET доступен manager/admin/superadmin
    for role in ('manager', 'admin', 'superadmin'):
        assert _client(role).get(BASE_URL).status_code == 200
    # POST запрещён manager/admin
    payload = {'name': '__perm_probe__'}
    assert _client('manager').post(BASE_URL, payload, format='json').status_code == 403
    assert _client('admin').post(BASE_URL, payload, format='json').status_code == 403
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && pytest apps/teachers/tests/test_teachers_api.py -k perm -v`
Expected: FAIL (сейчас `IsManagerOrAdmin` → POST для manager/admin = 201/409, не 403).

- [ ] **Step 3: Переключить классы**

В каждом из файлов заменить импорт и `permission_classes`:

`journal_django/apps/teachers/views.py` — заменить
`from apps.core.permissions import IsManagerOrAdmin` на
`from apps.core.permissions import ReadStaffWriteSuperAdmin`,
и оба `permission_classes = [IsManagerOrAdmin]` → `permission_classes = [ReadStaffWriteSuperAdmin]`.

Аналогично в `journal_django/apps/directions/views.py`, `journal_django/apps/memberships/views.py`,
`journal_django/apps/discounts/views.py`: импорт `ReadStaffWriteSuperAdmin` и все
`permission_classes = [IsManagerOrAdmin]` → `permission_classes = [ReadStaffWriteSuperAdmin]`.

- [ ] **Step 4: Прогнать тесты затронутых приложений**

Run: `cd journal_django && pytest apps/teachers apps/directions apps/memberships apps/discounts -v`
Expected: новый perm-тест PASS; существующие тесты, где manager/admin делают запись, —
обновить (см. Step 5) или они упадут — это ожидаемо, чинить в Step 5.

- [ ] **Step 5: Обновить существующие write-тесты этих приложений**

В тестах teachers/directions/memberships/discounts, где мутации выполнялись под `manager`/`admin`,
заменить роль клиента на `'superadmin'` (например `_client('superadmin').post(...)`), т.к. запись
теперь только для super. Прогнать снова:

Run: `cd journal_django && pytest apps/teachers apps/directions apps/memberships apps/discounts -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/teachers journal_django/apps/directions journal_django/apps/memberships journal_django/apps/discounts
git commit -m "feat(rbac): teachers/directions/memberships/discounts — запись только superadmin"
```

---

### Task 6: Разводка super-only разделов (payroll, accounts, audit)

**Files:**
- Modify: `journal_django/apps/payroll/views.py`, `journal_django/apps/accounts/views.py`, `journal_django/apps/audit/views.py`
- Test: расширить соответствующие `test_*_api.py`

- [ ] **Step 1: Написать падающий тест (payroll)**

Добавить в `journal_django/apps/payroll/tests/test_payroll_api.py` (по паттерну клиента файла):

```python
def test_payroll_superadmin_only():
    for role in ('manager', 'admin'):
        assert _client(role).get(PAYROLL_LIST_URL).status_code == 403
    assert _client('superadmin').get(PAYROLL_LIST_URL).status_code == 200
```

(`PAYROLL_LIST_URL` — использовать существующую в файле константу URL списка/summary.)

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && pytest apps/payroll/tests -k superadmin_only -v`
Expected: FAIL (сейчас manager/admin → 200).

- [ ] **Step 3: Переключить классы**

- `journal_django/apps/payroll/views.py`: импорт `from apps.core.permissions import IsSuperAdmin`,
  все `permission_classes = [IsManagerOrAdmin]` → `[IsSuperAdmin]`.
- `journal_django/apps/accounts/views.py`: заменить `from apps.core.permissions import IsAdmin`
  на `IsSuperAdmin`, все `permission_classes = [IsAdmin]` → `[IsSuperAdmin]`.
- `journal_django/apps/audit/views.py`: заменить `IsAdmin` на `IsSuperAdmin`,
  `permission_classes = [IsAdmin]` → `[IsSuperAdmin]`.

- [ ] **Step 4: Обновить существующие тесты accounts/audit/payroll**

В `apps/accounts/tests/test_accounts_api.py` и `apps/audit/tests/*` заменить роль,
под которой раньше проверялся успешный доступ (`admin`), на `superadmin`; добавить проверку,
что `admin` теперь получает 403. Учесть, что тест-хелперы могут хардкодить роли —
добавить `'superadmin'`.

- [ ] **Step 5: Прогнать**

Run: `cd journal_django && pytest apps/payroll apps/accounts apps/audit -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/payroll journal_django/apps/accounts journal_django/apps/audit
git commit -m "feat(rbac): payroll/accounts/audit — доступ только superadmin"
```

---

### Task 7: Changelog — просмотр manager/admin/super, откат admin/super

**Files:**
- Modify: `journal_django/apps/changelog/views.py`
- Test: расширить `apps/changelog/tests/test_*_api.py` (или create `test_changelog_rbac.py`)

- [ ] **Step 1: Написать падающий тест**

Добавить в существующий api-тест changelog (по паттерну клиента файла):

```python
def test_changelog_view_manager_revert_admin_only():
    # list — manager/admin/superadmin
    for role in ('manager', 'admin', 'superadmin'):
        assert _client(role).get(CHANGELOG_LIST_URL).status_code == 200
    # revert — manager запрещён, admin/superadmin разрешён (403 vs не-403)
    assert _client('manager').post(REVERT_URL).status_code == 403
    assert _client('admin').post(REVERT_URL).status_code != 403
```

(`CHANGELOG_LIST_URL`/`REVERT_URL` — реальные URL из файла; для revert подобрать существующий
`context_id` или ожидать 404/200, но не 403 для admin.)

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && pytest apps/changelog/tests -k rbac -v`
Expected: FAIL (сейчас всё `IsAdmin`: manager → 403 на list).

- [ ] **Step 3: Переключить классы**

В `journal_django/apps/changelog/views.py`:
- импорт: `from apps.core.permissions import IsManagerOrAdmin, IsAdminOrSuperAdmin`
- `ChangelogListView.permission_classes` → `[IsManagerOrAdmin]`
- `ChangelogDetailView.permission_classes` → `[IsManagerOrAdmin]`
- `ChangelogRevertView.permission_classes` → `[IsAdminOrSuperAdmin]`
- обновить docstring модуля (сейчас «ВЕСЬ раздел — только admin»).

- [ ] **Step 4: Прогнать**

Run: `cd journal_django && pytest apps/changelog -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/changelog
git commit -m "feat(rbac): changelog — просмотр manager/admin/super, откат admin/super"
```

---

### Task 8: Уроки — запись admin/super + стрип payroll по роли

**Files:**
- Modify: `journal_django/apps/lessons/views.py`
- Test: расширить `journal_django/apps/lessons/tests/test_lessons_api.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в `test_lessons_api.py` (в `_ROLE_EMAILS` добавить `'superadmin': '__les_super__@example.com'`;
`_get_or_create_account` уже поддержит новую роль, т.к. teacher_id нужен только для teacher):

```python
def test_lessons_write_admin_super_only_and_payroll_stripped(monkeypatch):
    # GET доступен manager/admin/superadmin
    for role in ('manager', 'admin', 'superadmin'):
        assert _client(role).get(BASE_URL).status_code == 200

    # POST урока: manager → 403, admin/super → не 403
    payload = _valid_lesson_payload()  # использовать существующий помощник/тело из файла
    assert _client('manager').post(BASE_URL, payload, format='json').status_code == 403
    assert _client('admin').post(BASE_URL, payload, format='json').status_code in (201, 400, 409)

    # payroll виден только superadmin в detail
    lesson_id = _create_lesson_via_super()  # helper: создать урок под super, вернуть id
    body_admin = _client('admin').get(f'{BASE_URL}/{lesson_id}').json()
    body_super = _client('superadmin').get(f'{BASE_URL}/{lesson_id}').json()
    assert body_admin.get('payroll') in (None,)  # для admin вырезано
    assert body_super.get('payroll') is not None   # для super присутствует
    _delete_lesson(lesson_id)


def test_attendance_toggle_forbidden_for_manager():
    lesson_id = _create_lesson_via_super()
    # student_id — любой присутствующий в attendance; взять из detail под super
    detail = _client('superadmin').get(f'{BASE_URL}/{lesson_id}').json()
    sid = detail['attendance'][0]['student_id']
    url = f'{BASE_URL}/{lesson_id}/attendance/{sid}'
    assert _client('manager').patch(url, {'present': True}, format='json').status_code == 403
    assert _client('admin').patch(url, {'present': True}, format='json').status_code in (200, 404)
    _delete_lesson(lesson_id)
```

> Если в файле уже есть готовое валидное тело урока и helper удаления (`_delete_lesson` есть),
> переиспользовать их; `_valid_lesson_payload`/`_create_lesson_via_super` — тонкие обёртки
> вокруг существующего POST-тела из текущих тестов создания.

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && pytest apps/lessons/tests/test_lessons_api.py -k "admin_super_only or attendance_toggle" -v`
Expected: FAIL.

- [ ] **Step 3: Реализовать разводку и стрип payroll**

В `journal_django/apps/lessons/views.py`:
- импорт: `from apps.core.permissions import ReadStaffWriteAdmin`
- все `permission_classes = [IsManagerOrAdmin]` (в `LessonListCreateView`, `LessonDetailView`,
  `AttendanceCellView`) → `[ReadStaffWriteAdmin]`.
- Добавить хелпер стрипа payroll по роли и применить к GET-ответам списка и detail:

```python
def _strip_payroll_for_role(data, role):
    """payroll (зарплата за урок) видит только superadmin. Вырезаем для остальных."""
    if role == 'superadmin':
        return data
    if isinstance(data, dict):
        if 'payroll' in data:
            data = {**data, 'payroll': None}
        if 'rows' in data and isinstance(data['rows'], list):
            data = {**data, 'rows': [_row_without_payroll(r) for r in data['rows']]}
    return data


def _row_without_payroll(row):
    payroll_keys = ('payroll_id', 'total_students', 'present_count', 'payment', 'penalty')
    return {k: v for k, v in row.items() if k not in payroll_keys}
```

В `LessonListCreateView.get` и `LessonDetailView.get` обернуть возвращаемые данные:
`return Response(_strip_payroll_for_role(<данные>, request.user.role))`.

> Для списка (`services.list_lessons`) зарплатные поля — плоские (`payment`, `penalty`,
> `total_students`, `present_count`, `payroll_id` — см. `repository.list_lessons`), поэтому
> вырезаем по ключам через `_row_without_payroll`. Для detail (`get_lesson_full`) зарплата —
> вложенный объект `payroll`, обнуляем его.

- [ ] **Step 4: Прогнать**

Run: `cd journal_django && pytest apps/lessons -v`
Expected: PASS (новые + существующие; при необходимости поправить существующие тесты
создания урока на роль `admin`/`superadmin` вместо `manager`).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/lessons
git commit -m "feat(rbac): уроки — запись admin/super, посещаемость admin/super, payroll только super"
```

---

## Phase C — Backend: имя, отключение, удаление учётки

### Task 9: Производное имя учётки (full_name → me, list, detail)

**Files:**
- Modify: `journal_django/apps/auth_app/services.py`, `journal_django/apps/accounts/repository.py`, `journal_django/apps/accounts/serializers.py`
- Test: `journal_django/apps/accounts/tests/test_account_name.py` (create), расширить `test_auth_api.py`

- [ ] **Step 1: Написать падающий тест**

Create `journal_django/apps/accounts/tests/test_account_name.py`:

```python
"""Имя учётки — производное: full_name or teacher_name or email."""
from __future__ import annotations

import pytest

from apps.accounts import repository

pytestmark = pytest.mark.django_db


def test_list_returns_name_from_full_name():
    acc = repository.create_account(email='__nm_mgr__@example.com', role='manager')
    repository.update_full_name(acc['id'], 'Пётр Иванов')
    rows = repository.list_accounts(filters={'email': '__nm_mgr__'})['rows']
    row = next(r for r in rows if r['email'] == '__nm_mgr__@example.com')
    assert row['name'] == 'Пётр Иванов'
    from apps.accounts.models import Account
    Account.objects.filter(id=acc['id']).delete()  # очистка тест-данных
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && pytest apps/accounts/tests/test_account_name.py -v`
Expected: FAIL (`update_full_name`/`name` отсутствуют).

- [ ] **Step 3: Реализовать**

В `journal_django/apps/accounts/repository.py`:
- добавить `'full_name'` в `_LIST_FIELDS`.
- в `list_accounts`, в цикле по `rows`, вычислять имя:

```python
    for row in rows:
        row['status'] = _account_status(row)
        row['name'] = row.get('full_name') or row.get('teacher_name') or row['email']
```

- добавить функцию:

```python
def update_full_name(account_id: int, full_name):
    return Account.objects.filter(id=account_id).update(full_name=full_name) > 0
```

- в `get_by_id_with_teacher` `full_name` уже попадёт (входит в `_account_full_fields()`);
  вычисление `name` для detail сделать в сервисе (Step ниже).

В `journal_django/apps/accounts/services.py`:
- в `get_account` после `_strip_secrets` добавить производное имя:

```python
def get_account(account_id: int) -> Optional[dict]:
    row = _strip_secrets(repository.get_by_id_with_teacher(account_id))
    if row is not None:
        row['name'] = row.get('full_name') or row.get('teacher_name') or row['email']
    return row
```

В `journal_django/apps/auth_app/services.py:me()` заменить строку `'name': ...`:

```python
        'name': acc.get('full_name') or acc.get('teacher_name') or acc['email'],
```

(убедиться, что `me`-запрос тянет `full_name`; при необходимости добавить поле в выборку auth-сервиса).

В `journal_django/apps/accounts/serializers.py`:
- в `AccountCreateSerializer` добавить `full_name = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=200)`;
  в `validate` запретить `full_name` для teacher (имя берётся из преподавателя):

```python
        if is_teacher and attrs.get('full_name'):
            raise serializers.ValidationError('full_name недопустим для teacher-аккаунта')
```

- в `AccountUpdateSerializer` добавить то же поле `full_name` (required=False).
- расширить `ROLES` → `('teacher', 'manager', 'admin', 'superadmin')`.

В `services.create_account`/`update_account` пробросить `full_name` в repository
(`create_account` → передать в `repository.create_account`, добавив параметр `full_name=None`;
`update_account` → вызвать `repository.update_full_name`, если поле пришло).

Расширить `repository.create_account` сигнатурой `full_name=None` и сохранить его при вставке.

- [ ] **Step 4: Прогнать**

Run: `cd journal_django && pytest apps/accounts apps/auth_app -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/accounts journal_django/apps/auth_app
git commit -m "feat(accounts): производное имя учётки (full_name→teacher_name→email)"
```

---

### Task 10: Включение/отключение учётки (обратимо) + аудит

**Files:**
- Modify: `journal_django/apps/accounts/{services,repository,views}.py`, `journal_django/apps/accounts/urls.py`
- Test: `journal_django/apps/accounts/tests/test_account_toggle.py` (create)

- [ ] **Step 1: Написать падающий тест**

Create `journal_django/apps/accounts/tests/test_account_toggle.py`:

```python
"""Отключение/включение учётки (обратимо)."""
from __future__ import annotations

import pytest

from apps.accounts import repository, services

pytestmark = pytest.mark.django_db


class _NoReq:
    META: dict = {}


def test_disable_then_enable():
    acc = repository.create_account(email='__tgl__@example.com', role='manager')
    assert services.set_active(acc['id'], False, actor_account_id=None, request=_NoReq()) is True
    assert repository.get_by_id(acc['id'])['is_active'] is False
    assert services.set_active(acc['id'], True, actor_account_id=None, request=_NoReq()) is True
    assert repository.get_by_id(acc['id'])['is_active'] is True
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && pytest apps/accounts/tests/test_account_toggle.py -v`
Expected: FAIL (`set_active` отсутствует).

- [ ] **Step 3: Реализовать**

В `journal_django/apps/accounts/repository.py` добавить:

```python
def set_active(account_id: int, active: bool) -> bool:
    return Account.objects.filter(id=account_id).update(is_active=active) > 0
```

В `journal_django/apps/accounts/services.py` добавить (переиспользуя `bump_token_version`
при отключении для немедленного разлогина):

```python
def set_active(account_id: int, active: bool, actor_account_id, request: Request) -> bool:
    acc = repository.get_by_id(account_id)
    if acc is None:
        return False
    repository.set_active(account_id, active)
    if not active:
        repository.bump_token_version(account_id)
    log_event(
        event='account_enabled' if active else 'account_disabled',
        account_id=actor_account_id, target_id=account_id, request=request,
    )
    return True
```

В `journal_django/apps/accounts/views.py` добавить вьюху:

```python
class AccountSetActiveView(APIView):
    """POST /:id/set-active — {active: bool}. Отключить/включить учётку."""

    permission_classes = [IsSuperAdmin]

    def post(self, request: Request, pk: int) -> Response:
        active = bool(request.data.get('active'))
        ok = services.set_active(active=active, account_id=pk,
                                 actor_account_id=request.user.id, request=request)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response({'ok': True, 'active': active})
```

В `journal_django/apps/accounts/urls.py` зарегистрировать маршрут
`<int:pk>/set-active` → `AccountSetActiveView`.

Добавить метки для новых событий в `apps/changelog/labels.py` при необходимости
(если аудит-события отражаются там) — сверить с существующими `account_deactivated`.

- [ ] **Step 4: Прогнать**

Run: `cd journal_django && pytest apps/accounts -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/accounts
git commit -m "feat(accounts): обратимое отключение/включение учётки + аудит"
```

---

### Task 11: Hard-delete учётки

**Files:**
- Modify: `journal_django/apps/accounts/{services,repository,views}.py`
- Test: `journal_django/apps/accounts/tests/test_account_delete.py` (create)

- [ ] **Step 1: Написать падающий тест**

Create `journal_django/apps/accounts/tests/test_account_delete.py`:

```python
"""Hard-delete учётки: строка исчезает, инвайты/recovery каскадно удаляются."""
from __future__ import annotations

import pytest

from apps.accounts import repository, services
from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


class _NoReq:
    META: dict = {}


def test_hard_delete_removes_row():
    acc = repository.create_account(email='__del__@example.com', role='manager')
    assert services.hard_delete(acc['id'], actor_account_id=None, request=_NoReq()) is True
    assert Account.objects.filter(id=acc['id']).exists() is False


def test_hard_delete_missing_returns_false():
    assert services.hard_delete(999999, actor_account_id=None, request=_NoReq()) is False
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && pytest apps/accounts/tests/test_account_delete.py -v`
Expected: FAIL (`hard_delete` отсутствует).

- [ ] **Step 3: Реализовать**

В `journal_django/apps/accounts/repository.py`:

```python
def hard_delete(account_id: int) -> bool:
    return Account.objects.filter(id=account_id).delete()[0] > 0
```

> Проверить `on_delete` у `AccountInvite.account` и `AccountRecoveryCode.account` — оба CASCADE
> (см. models.py), поэтому дочерние строки удалятся автоматически.

В `journal_django/apps/accounts/services.py`:

```python
def hard_delete(account_id: int, actor_account_id, request: Request) -> bool:
    acc = repository.get_by_id(account_id)
    if acc is None:
        return False
    # Аудит ДО удаления строки (target_id ещё существует).
    log_event(
        event='account_deleted', account_id=actor_account_id,
        target_id=account_id, meta={'email': acc['email'], 'role': acc['role']},
        request=request,
    )
    return repository.hard_delete(account_id)
```

В `journal_django/apps/accounts/views.py` заменить текущий `AccountDetailView.delete`
(сейчас soft) на hard-delete:

```python
    def delete(self, request: Request, pk: int) -> Response:
        ok = services.hard_delete(pk, actor_account_id=request.user.id, request=request)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(status=status.HTTP_204_NO_CONTENT)
```

> `services.soft_delete` больше не вызывается из DELETE, но остаётся как util —
> оставить или удалить по факту использования (проверить ссылки).

- [ ] **Step 4: Прогнать**

Run: `cd journal_django && pytest apps/accounts -v`
Expected: PASS (существующий тест, ожидавший soft-delete на DELETE, — обновить под hard).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/accounts
git commit -m "feat(accounts): hard-delete учётки через DELETE + аудит account_deleted"
```

---

### Task 12: bootstrap_admin + admin_exists → superadmin

**Files:**
- Modify: `journal_django/apps/accounts/management/commands/bootstrap_admin.py`, `journal_django/apps/accounts/repository.py`
- Test: расширить `journal_django/apps/accounts/tests/test_bootstrap_command.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `test_bootstrap_command.py`:

```python
def test_bootstrap_creates_superadmin(capsys):
    from django.core.management import call_command
    from apps.accounts.models import Account
    call_command('bootstrap_admin', '--email=__boot_super__@example.com')
    acc = Account.objects.get(email='__boot_super__@example.com')
    assert acc.role == 'superadmin'
    acc.delete()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && pytest apps/accounts/tests/test_bootstrap_command.py -k superadmin -v`
Expected: FAIL (создаётся role='admin').

- [ ] **Step 3: Реализовать**

В `journal_django/apps/accounts/repository.py` — `admin_exists()` → проверять superadmin:

```python
def admin_exists() -> bool:
    return Account.objects.filter(role='superadmin').exists()
```

В `bootstrap_admin.py` — создавать superadmin: `repository.create_account(email=email, role='superadmin', teacher_id=None)`; обновить help/тексты («первый суперадминистратор»).

- [ ] **Step 4: Прогнать**

Run: `cd journal_django && pytest apps/accounts/tests/test_bootstrap_command.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/accounts
git commit -m "feat(accounts): bootstrap создаёт superadmin, admin_exists проверяет superadmin"
```

---

### Task 13: Полный прогон бэкенд-набора

- [ ] **Step 1: Прогнать весь backend**

Run: `cd journal_django && pytest -q`
Expected: всё зелёное. Разобрать и починить любые упавшие тесты, которые ожидали старую
матрицу прав (manager/admin, делавшие запись в teachers/lessons/directions/subscriptions/payroll,
или admin в accounts/audit/changelog).

- [ ] **Step 2: Commit (если были правки)**

```bash
git add -A journal_django/apps
git commit -m "test(rbac): привести существующие тесты к новой матрице прав"
```

---

## Phase D — Frontend (admin SPA)

### Task 14: Тип роли + capability-модуль

**Files:**
- Modify: `journal_django/frontend/admin-src/src/providers/AuthProvider.tsx`
- Create: `journal_django/frontend/admin-src/src/lib/permissions.ts`

- [ ] **Step 1: Расширить тип роли**

В `AuthProvider.tsx` в интерфейсе `Me` заменить тип `role`:

```ts
  role: 'teacher' | 'manager' | 'admin' | 'superadmin';
```

- [ ] **Step 2: Создать capability-модуль**

Create `journal_django/frontend/admin-src/src/lib/permissions.ts`:

```ts
export type Role = 'teacher' | 'manager' | 'admin' | 'superadmin';

const isSuper = (r?: Role | null) => r === 'superadmin';
const isAdminUp = (r?: Role | null) => r === 'admin' || r === 'superadmin';
const isStaff = (r?: Role | null) => r === 'manager' || r === 'admin' || r === 'superadmin';

// Разделы (видимость навигации / доступ к роуту)
export const canSeeAccounts = isSuper;
export const canSeeAudit = isSuper;
export const canSeePayroll = isSuper;
export const canSeeChangelog = isStaff;

// Операции над сущностями (write-кнопки)
export const canWriteTeachers = isSuper;
export const canWriteDirections = isSuper;
export const canWriteSubscriptions = isSuper; // абонементы + скидки
export const canWriteLessons = isAdminUp;     // CRUD урока + посещаемость
export const canSeeLessonPayroll = isSuper;   // зарплата за урок
export const canRevertChangelog = isAdminUp;
```

- [ ] **Step 3: Проверить сборку типов**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: без ошибок.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/providers/AuthProvider.tsx journal_django/frontend/admin-src/src/lib/permissions.ts
git commit -m "feat(admin-fe): тип роли superadmin + capability-модуль permissions.ts"
```

---

### Task 15: RequireRole guard + защита роутов

**Files:**
- Create: `journal_django/frontend/admin-src/src/components/shell/RequireRole.tsx`
- Modify: `journal_django/frontend/admin-src/src/App.tsx`

- [ ] **Step 1: Создать компонент-гвард**

Create `journal_django/frontend/admin-src/src/components/shell/RequireRole.tsx`:

```tsx
import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import type { Role } from '../../lib/permissions';

export function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { me } = useAuth();
  if (me && !roles.includes(me.role as Role)) {
    return <Navigate to="/admin/dashboard" replace />;
  }
  return <>{children}</>;
}
```

- [ ] **Step 2: Обернуть чувствительные роуты в App.tsx**

В `App.tsx` импортировать `RequireRole` и обернуть элементы роутов:
- `/admin/accounts`, `/admin/audit`, `/admin/payroll` → `<RequireRole roles={['superadmin']}>`
- `/admin/changelog` → `<RequireRole roles={['manager','admin','superadmin']}>`

Пример:

```tsx
<Route path="/admin/payroll" element={<RequireRole roles={['superadmin']}><PayrollPage /></RequireRole>} />
<Route path="/admin/accounts" element={<RequireRole roles={['superadmin']}><AccountsPage /></RequireRole>} />
<Route path="/admin/audit" element={<RequireRole roles={['superadmin']}><AuditPage /></RequireRole>} />
<Route path="/admin/changelog" element={<RequireRole roles={['manager','admin','superadmin']}><ChangelogListPage /></RequireRole>} />
```

- [ ] **Step 3: Проверить сборку**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit && npm run build`
Expected: сборка проходит.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/components/shell/RequireRole.tsx journal_django/frontend/admin-src/src/App.tsx
git commit -m "feat(admin-fe): RequireRole guard + защита роутов accounts/audit/payroll/changelog"
```

---

### Task 16: Навигация (Sidebar/MobileNav) по ролям

**Files:**
- Modify: `journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx`, `journal_django/frontend/admin-src/src/components/shell/MobileNav.tsx`

- [ ] **Step 1: Гейтить пункт «Зарплата» в основном списке**

В `Sidebar.tsx` секция `SECTIONS` содержит «Зарплата». Отфильтровать её для не-super при рендере
`nav`: заменить `SECTIONS.map(...)` на фильтрацию:

```tsx
import { canSeePayroll, canSeeAccounts, canSeeAudit, canSeeChangelog, type Role } from '../../lib/permissions';
...
const role = me?.role as Role | undefined;
const visibleSections = SECTIONS.filter((s) => s.key !== 'payroll' || canSeePayroll(role));
```

и рендерить `visibleSections` вместо `SECTIONS`.

- [ ] **Step 2: Переписать нижний служебный блок**

Заменить текущее условие `me?.role === 'admin'` на capability-функции — Учётки/Журнал ИБ (super),
Журнал изменений (staff):

```tsx
{canSeeAccounts(role) && (
  <NavLink to="/admin/accounts" className={...}>{NAV_ICONS['accounts']} Учётки</NavLink>
)}
{canSeeAudit(role) && (
  <NavLink to="/admin/audit" className={...}>{NAV_ICONS['audit']} Журнал ИБ</NavLink>
)}
{canSeeChangelog(role) && (
  <NavLink to="/admin/changelog" className={...}>{NAV_ICONS['changelog']} Журнал изменений</NavLink>
)}
```

(разделители `nav-sep` расставить так, чтобы не оставалось «висящих» линий, когда блок пуст.)

- [ ] **Step 3: Повторить гейтинг в MobileNav.tsx**

Применить тот же фильтр по `canSeePayroll`/`canSeeAccounts`/`canSeeAudit`/`canSeeChangelog`
в `MobileNav.tsx` (сверить, как там формируется список пунктов).

- [ ] **Step 4: Проверить сборку**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit && npm run build`
Expected: проходит.

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx journal_django/frontend/admin-src/src/components/shell/MobileNav.tsx
git commit -m "feat(admin-fe): навигация по ролям (Зарплата/Учётки/Журнал ИБ/Изменений)"
```

---

### Task 17: Read-only гейтинг write-кнопок (teachers, directions, subscriptions)

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/teachers/{TeachersListPage,TeacherDetailPage}.tsx`
- Modify: `journal_django/frontend/admin-src/src/pages/directions/{DirectionsListPage,DirectionDetailPage}.tsx`
- Modify: `journal_django/frontend/admin-src/src/pages/subscriptions/{SubscriptionsView,DiscountsView}.tsx`

- [ ] **Step 1: Скрыть write-кнопки Преподавателей**

В `TeachersListPage.tsx`/`TeacherDetailPage.tsx` найти кнопки «Добавить/Создать», «Редактировать»,
«Удалить» (открывают `TeacherFormModal` / вызывают мутации) и обернуть в условие:

```tsx
import { canWriteTeachers, type Role } from '../../lib/permissions';
const { me } = useAuth();
const canWrite = canWriteTeachers(me?.role as Role);
...
{canWrite && <Button onClick={...}>Добавить преподавателя</Button>}
```

- [ ] **Step 2: То же для Направлений**

В `DirectionsListPage.tsx`/`DirectionDetailPage.tsx` обернуть write-кнопки в `canWriteDirections(role)`.

- [ ] **Step 3: То же для Абонементов и Скидок**

В `SubscriptionsView.tsx`/`DiscountsView.tsx` обернуть write-кнопки (создать/редактировать/удалить
абонемент и скидку) в `canWriteSubscriptions(role)`.

- [ ] **Step 4: Проверить сборку**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit && npm run build`
Expected: проходит.

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/teachers journal_django/frontend/admin-src/src/pages/directions journal_django/frontend/admin-src/src/pages/subscriptions
git commit -m "feat(admin-fe): read-only для не-super в разделах teachers/directions/subscriptions"
```

---

### Task 18: Уроки — гейтинг записи и скрытие зарплаты

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/lessons/{LessonsListPage,LessonDetailPage}.tsx`
- Modify: `journal_django/frontend/admin-src/src/pages/lessons/LessonFormModal.tsx`
- Modify (при наличии grid-мутаций): `journal_django/frontend/admin-src/src/components/lessons/LessonGrid.tsx`

- [ ] **Step 1: Гейтить CRUD урока и посещаемость по canWriteLessons**

В `LessonsListPage.tsx`/`LessonDetailPage.tsx` обернуть кнопки создать/редактировать/удалить урок
и элементы отметки посещаемости (toggle-ячейки) в:

```tsx
import { canWriteLessons, canSeeLessonPayroll, type Role } from '../../lib/permissions';
const { me } = useAuth();
const canWrite = canWriteLessons(me?.role as Role);
const canSeePayroll = canSeeLessonPayroll(me?.role as Role);
```

Для attendance-сетки: если `!canWrite` — рендерить ячейки как read-only (не навешивать
onClick/onChange, дизейблить инпуты).

- [ ] **Step 2: Скрыть секцию «Зарплата» в LessonDetailPage**

Обернуть блок `<h3 className="detail__section-title">Зарплата</h3>` и весь payroll-блок
(строки с `lesson.payroll.*`, ~L109–L129) в `{canSeePayroll && ( ... )}`.

> Бэкенд уже вырезает `payroll` для не-super (Task 8), поэтому `lesson.payroll` будет `null` —
> но условие по роли убирает и заголовок секции, а не только тело.

- [ ] **Step 3: Скрыть payroll-блок в LessonFormModal**

В `LessonFormModal.tsx` обернуть блок «Зарплата» (`<h4 className="memberships__title">Зарплата</h4>`
и поля payment/penalty, ~L154–L157) в `{canSeeLessonPayroll(role) && (...)}`. Модалка открывается
только при `canWriteLessons` (admin/super); для admin — скрываем зарплатные поля, при отправке
не слать `payroll` (или слать без него).

> Так как create-урока доступен admin (без права видеть зарплату), убедиться, что при отсутствии
> payroll-полей POST-тело валидно (`payroll` — `required=False` в `LessonCreateSerializer`).

- [ ] **Step 4: Проверить сборку**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit && npm run build`
Expected: проходит.

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/lessons journal_django/frontend/admin-src/src/components/lessons
git commit -m "feat(admin-fe): уроки — запись admin/super, зарплата за урок только super"
```

---

### Task 19: Журнал изменений — кнопка «Откатить» только admin/super

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/changelog/ChangelogListPage.tsx`, `journal_django/frontend/admin-src/src/pages/changelog/ChangelogDetailModal.tsx` (где есть кнопка отката)

- [ ] **Step 1: Гейтить кнопку отката**

Найти кнопку «Откатить»/открытие `RevertConfirmDialog` и обернуть в `canRevertChangelog(role)`:

```tsx
import { canRevertChangelog, type Role } from '../../lib/permissions';
const { me } = useAuth();
...
{canRevertChangelog(me?.role as Role) && <Button onClick={openRevert}>Откатить</Button>}
```

- [ ] **Step 2: Проверить сборку**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit && npm run build`
Expected: проходит.

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/changelog
git commit -m "feat(admin-fe): откат в Журнале изменений только admin/super"
```

---

### Task 20: Страница Учётки — имя, отключение/включение, удаление

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/accounts/AccountsPage.tsx`
- Modify (API-хук): найти хук аккаунтов (`hooks/useAccounts*` или инлайн в странице)

- [ ] **Step 1: Колонка «Имя» в таблице**

В `AccountsPage.tsx` добавить в таблицу колонку `name` (бэкенд уже отдаёт `row.name`, Task 9).
Разместить перед/после `email` по существующему стилю таблицы.

- [ ] **Step 2: Поле full_name в форме создания/редактирования**

В форме учётки добавить `TextInput` для «Имя» (`full_name`). Показывать/разрешать его только
когда роль создаваемой учётки НЕ `teacher` (для teacher имя берётся из преподавателя —
поле скрыть/дизейблить). Пробросить `full_name` в тело POST/PATCH `/api/admin/accounts`.

- [ ] **Step 3: Кнопка «Отключить/Включить»**

Добавить действие в строку/детали учётки: POST `/api/admin/accounts/:id/set-active` с телом
`{ active: !row.is_active }`. Лейбл — «Отключить», если активна, иначе «Включить».
После успеха — инвалидация query аккаунтов (`queryClient.invalidateQueries`).

```tsx
await api('POST', `/api/admin/accounts/${id}/set-active`, { active: !isActive });
```

- [ ] **Step 4: Кнопка «Удалить» + confirm-модалка**

Добавить действие «Удалить» → открывает `Dialog` подтверждения (использовать существующий
`components/ui/Dialog.tsx`), при подтверждении: `DELETE /api/admin/accounts/:id`, затем
инвалидация. Текст модалки предупреждает о необратимости (hard-delete).

- [ ] **Step 5: Проверить сборку**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit && npm run build`
Expected: проходит.

- [ ] **Step 6: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/accounts
git commit -m "feat(admin-fe): Учётки — имя, отключение/включение, удаление с подтверждением"
```

---

### Task 21: Пересобрать admin SPA в admin-dist

**Files:**
- Modify: `journal_django/frontend/admin-dist/*` (артефакты сборки)

- [ ] **Step 1: Прод-сборка**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: обновлённые ассеты в `journal_django/frontend/admin-dist/`.

- [ ] **Step 2: Commit артефактов**

```bash
git add journal_django/frontend/admin-dist
git commit -m "build(admin-fe): пересборка admin SPA под RBAC-изменения"
```

---

## Phase E — Верификация

### Task 22: Полная верификация

- [ ] **Step 1: Backend-набор**

Run: `cd journal_django && pytest -q`
Expected: всё зелёное.

- [ ] **Step 2: Frontend типы+сборка**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit && npm run build`
Expected: без ошибок.

- [ ] **Step 3: Ручной прогон гейтинга по ролям (superpowers:verification-before-completion)**

Через локальный nginx (:8080→runserver) войти под каждой ролью и проверить матрицу §2 спеки:
- `manager`: нет Зарплаты/Учёток/Журнала ИБ; Преподаватели/Направления/Абонементы/Уроки —
  read-only; посещаемость недоступна; Журнал изменений виден, «Откатить» скрыт; зарплаты за урок нет.
- `admin`: как manager, плюс — Уроки: CRUD+посещаемость доступны, зарплаты за урок НЕ видно;
  Журнал изменений — «Откатить» доступен; Учётки/Журнал ИБ/Зарплата — недоступны.
- `superadmin`: всё доступно, включая Учётки (имя/отключение/удаление), Журнал ИБ, Зарплату,
  зарплату за урок.

- [ ] **Step 4: Финальный отчёт**

Свести результаты прогонов (номера passed-тестов, факт сборки) в сообщение владельцу.
Никаких «done» без вывода команд (superpowers:verification-before-completion).

---

## Карта затронутых файлов

**Backend:** `apps/core/permissions.py`, `apps/accounts/{models,serializers,services,repository,views,urls}.py`,
`apps/accounts/migrations/*`, `apps/accounts/management/commands/bootstrap_admin.py`,
`apps/auth_app/services.py`,
`apps/{teachers,directions,memberships,discounts,payroll,audit,changelog,lessons}/views.py`,
тесты `apps/*/tests/test_*`.

**Frontend:** `providers/AuthProvider.tsx`, `lib/permissions.ts` (new),
`components/shell/{RequireRole(new),Sidebar,MobileNav}.tsx`, `App.tsx`,
`pages/{teachers,directions,subscriptions,lessons,changelog,accounts}/*`,
`components/lessons/LessonGrid.tsx`, `frontend/admin-dist/*`.
