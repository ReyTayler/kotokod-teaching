# Журнал изменений (backend) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бэкенд журнала изменений: захват 100 % изменений данных триггерами PG (django-pghistory), группировка по HTTP-запросу, read-API ленты/деталей и откат операции целиком (только admin).

**Architecture:** `@pghistory.track()` на 14 доменных моделях → event-таблицы со снапшотами строк; контекст запроса (user/url/method) через middleware + `CookieJWTAuthentication`; новое приложение `apps/changelog` (labels, registry, repository, services, views); revert-сервис восстанавливает строки из снапшотов в FK-безопасном порядке с конфликт-детекцией. Спека: `docs/superpowers/specs/2026-07-06-changelog-design.md`.

**Tech Stack:** Django 5.1 + DRF, django-pghistory 3.9.x (+django-pgtrigger), PostgreSQL, pytest (journal_test).

**Конвенции проекта, обязательные при выполнении:**
- Коммиты — ТОЛЬКО по явной просьбе пользователя (CLAUDE.md). Вместо commit-шагов — checkpoint-шаги «прогнать тесты».
- Каждая новая вьюха обязана иметь `permission_classes` (здесь везде `IsAdmin`).
- Тесты гонять дефолтным `pytest` из `journal_django/` (использует journal_test, dev-БД не трогает).
- Фронтенд — НЕ в этом плане (отдельный план по `docs/superpowers/specs/2026-07-06-changelog-ui-plan.md` после фазы read-API).

**Верифицированные факты о django-pghistory (док. 3.8–3.9):**
- Дефолтные трекеры — только `InsertEvent(), UpdateEvent()` → `DeleteEvent()` указывать ЯВНО.
- Все FK event-таблиц (включая `pgh_obj`) — `db_constraint=False`, `on_delete=DO_NOTHING` → история переживает удаление строк, существующие тесты не ломаются.
- `pghistory.context()` как функция (не контекст-менеджер) дописывает metadata в уже открытую middleware сессию; вложенные вызовы мержат metadata.
- `pghistory.models.Events` — агрегатный proxy (CTE по event-таблицам): `pgh_data`, `pgh_diff`, `pgh_context_id`, `pgh_obj_model`, `pgh_obj_id`, `pgh_label`, `pgh_created_at`.
- `PGHISTORY_MIDDLEWARE_METHODS` — задать `('POST','PUT','PATCH','DELETE')`, чтобы GET не создавал контекстов.
- `event.revert()` библиотеки НЕ используем (он для одиночных строк) — свой сервис по контексту.

---

### Task 1: Зависимости и settings

**Files:**
- Modify: `journal_django/requirements.txt`
- Modify: `journal_django/config/settings/base.py`

- [ ] **Step 1.1: Установить пакет и узнать резолв версий**

Run (из `journal_django/`, в venv проекта):
```bash
python -m pip install "django-pghistory==3.9.*"
python -m pip show django-pghistory django-pgtrigger
```
Expected: установлены django-pghistory 3.9.x и django-pgtrigger (зависимость). Записать точные версии.

- [ ] **Step 1.2: Пин в requirements.txt**

В `journal_django/requirements.txt` после строки `django-ratelimit==4.1.0 ...` добавить (версии — фактические из Step 1.1):

```
django-pghistory==3.9.2                # журнал изменений: PG-триггеры + контекст (спека 2026-07-06)
django-pgtrigger==4.13.3               # зависимость pghistory (триггеры декларативно из миграций)
```

- [ ] **Step 1.3: INSTALLED_APPS + настройки pghistory**

В `journal_django/config/settings/base.py` в `INSTALLED_APPS` после `'corsheaders',` добавить:

```python
    'pgtrigger',
    'pghistory',
```

и в конец списка приложений (после `'apps.scheduling',`):

```python
    'apps.changelog',
```

В `MIDDLEWARE` добавить последним элементом:

```python
    'apps.changelog.middleware.ChangelogMiddleware',
```

После блока `MIDDLEWARE` добавить:

```python
# ---------------------------------------------------------------------------
# django-pghistory — журнал изменений (apps.changelog)
# Контекст открывается только на мутирующих методах: GET-запросы не создают
# записей в pghistory_context.
# ---------------------------------------------------------------------------
PGHISTORY_MIDDLEWARE_METHODS = ('POST', 'PUT', 'PATCH', 'DELETE')
```

- [ ] **Step 1.4: Проверка конфигурации**

Run: `python manage.py check`
Expected: `System check identified no issues` (упадёт ImportError на `apps.changelog` — это ок до Task 2; тогда сперва Task 2, потом повторить check).

---

### Task 2: Каркас apps/changelog + middleware

**Files:**
- Create: `journal_django/apps/changelog/__init__.py` (пустой)
- Create: `journal_django/apps/changelog/apps.py`
- Create: `journal_django/apps/changelog/migrations/__init__.py` (пустой)
- Create: `journal_django/apps/changelog/middleware.py`
- Create: `journal_django/apps/changelog/tests/__init__.py` (пустой)

- [ ] **Step 2.1: apps.py**

```python
"""AppConfig приложения changelog (журнал изменений)."""
from django.apps import AppConfig


class ChangelogConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.changelog'
```

- [ ] **Step 2.2: middleware.py**

```python
"""
ChangelogMiddleware — открывает pghistory-контекст на мутирующих запросах.

Переопределяем get_context: базовый HistoryMiddleware читает request.user,
которого в этом проекте на этапе middleware НЕТ (нет AuthenticationMiddleware,
DRF аутентифицирует лениво внутри вьюхи через CookieJWTAuthentication).
Данные пользователя дописывает CookieJWTAuthentication.authenticate()
вызовом pghistory.context(...) (см. apps/core/authentication.py).
"""
from __future__ import annotations

import pghistory.middleware


class ChangelogMiddleware(pghistory.middleware.HistoryMiddleware):
    def get_context(self, request):
        return {
            'url': request.path,
            'method': request.method,
        }
```

- [ ] **Step 2.3: Проверка**

Run: `python manage.py check`
Expected: no issues.

Run: `python manage.py migrate`
Expected: применяются миграции приложений `pgtrigger`/`pghistory` (таблица `pghistory_context`).

---

### Task 3: Пилотный трекинг (Direction) — TDD

**Files:**
- Test: `journal_django/apps/changelog/tests/test_tracking.py`
- Modify: `journal_django/apps/directions/models.py`

- [ ] **Step 3.1: Failing-тесты захвата всех путей записи**

`journal_django/apps/changelog/tests/test_tracking.py`:

```python
"""
Тесты захвата изменений триггерами pghistory.

Ключевое: пути записи МИМО сигналов Django (queryset.update, bulk_create,
queryset.delete) обязаны попадать в журнал — ради этого выбран pghistory.
"""
from __future__ import annotations

import pytest
from django.apps import apps

from apps.directions.models import Direction

pytestmark = pytest.mark.django_db


def _event_model(app_label: str, model_name: str):
    return apps.get_model(app_label, model_name)


def _make_direction(name: str = '__chg_dir__') -> Direction:
    return Direction.objects.create(name=name, sheet_name='chg', is_individual=False)


def test_insert_captured():
    d = _make_direction()
    ev = _event_model('directions', 'DirectionEvent')
    events = ev.objects.filter(pgh_obj_id=d.id)
    assert events.count() == 1
    assert events.first().pgh_label == 'insert'


def test_save_update_captured():
    d = _make_direction()
    d.name = '__chg_dir_2__'
    d.save()
    ev = _event_model('directions', 'DirectionEvent')
    labels = list(ev.objects.filter(pgh_obj_id=d.id)
                  .order_by('pgh_id').values_list('pgh_label', flat=True))
    assert labels == ['insert', 'update']


def test_queryset_update_captured():
    """Soft-delete в проекте — .update(active=False): сигналы молчат, триггер обязан видеть."""
    d = _make_direction()
    Direction.objects.filter(id=d.id).update(active=False)
    ev = _event_model('directions', 'DirectionEvent')
    last = ev.objects.filter(pgh_obj_id=d.id).order_by('-pgh_id').first()
    assert last.pgh_label == 'update'
    assert last.active is False


def test_bulk_create_captured():
    Direction.objects.bulk_create([
        Direction(name='__chg_bulk_1__', sheet_name='chg', is_individual=False),
        Direction(name='__chg_bulk_2__', sheet_name='chg', is_individual=False),
    ])
    ev = _event_model('directions', 'DirectionEvent')
    assert ev.objects.filter(
        pgh_label='insert', name__startswith='__chg_bulk_'
    ).count() == 2


def test_delete_captured_and_snapshot_kept():
    d = _make_direction()
    d_id = d.id
    Direction.objects.filter(id=d_id).delete()
    ev = _event_model('directions', 'DirectionEvent')
    last = ev.objects.filter(pgh_obj_id=d_id).order_by('-pgh_id').first()
    assert last.pgh_label == 'delete'
    # Снапшот пережил удаление строки (FK без constraint)
    assert last.name == '__chg_dir__'
```

- [ ] **Step 3.2: Убедиться, что тесты падают**

Run: `pytest apps/changelog/tests/test_tracking.py -v`
Expected: FAIL — `LookupError: App 'directions' doesn't have a 'DirectionEvent' model`.

- [ ] **Step 3.3: Подключить трекинг Direction**

В `journal_django/apps/directions/models.py`: после `from django.db import models` добавить `import pghistory`, и над `class Direction(models.Model):`:

```python
@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class Direction(models.Model):
```

- [ ] **Step 3.4: Миграция**

Run:
```bash
python manage.py makemigrations directions
python manage.py migrate
```
Expected: новая миграция создаёт модель `DirectionEvent` + pgtrigger-триггеры на `directions`.

- [ ] **Step 3.5: Тесты зелёные**

Run: `pytest apps/changelog/tests/test_tracking.py -v`
Expected: 5 passed.

Run: `pytest apps/directions -v`
Expected: существующие тесты directions не сломаны.

---

### Task 4: Трекинг остальных моделей

**Files:**
- Modify: `journal_django/apps/teachers/models.py`
- Modify: `journal_django/apps/students/models.py`
- Modify: `journal_django/apps/groups/models.py` (Group И GroupScheduleSlot)
- Modify: `journal_django/apps/memberships/models.py`
- Modify: `journal_django/apps/lessons/models.py` (Lesson И LessonAttendance)
- Modify: `journal_django/apps/payments/models.py`
- Modify: `journal_django/apps/payroll/models.py`
- Modify: `journal_django/apps/discounts/models.py`
- Modify: `journal_django/apps/scheduling/models.py` (PlannedLesson)
- Modify: `journal_django/apps/settings_app/models.py` (AdminUserSettings)
- Modify: `journal_django/apps/accounts/models.py` (Account, с exclude)
- Test: `journal_django/apps/changelog/tests/test_tracking.py` (дополнить)

- [ ] **Step 4.1: Тест исключения секретов Account (failing)**

Добавить в `test_tracking.py`:

```python
def test_account_secrets_not_tracked():
    """У AccountEvent нет колонок секретов и технического шума."""
    ev = _event_model('accounts', 'AccountEvent')
    field_names = {f.name for f in ev._meta.get_fields()}
    for forbidden in ('password', 'twofa_secret', 'token_version',
                      'last_login', 'failed_login_count', 'locked_until'):
        assert forbidden not in field_names
    assert 'email' in field_names
    assert 'role' in field_names
```

Run: `pytest apps/changelog/tests/test_tracking.py::test_account_secrets_not_tracked -v`
Expected: FAIL (`AccountEvent` не существует).

- [ ] **Step 4.2: Декораторы на все модели**

В каждый файл: `import pghistory` в импорты. Над каждым классом — одинаковый декоратор (пример для Group; повторить дословно для Teacher, Student, GroupScheduleSlot, GroupMembership, Lesson, LessonAttendance, Payment, Payroll, Discount, PlannedLesson, AdminUserSettings):

```python
@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class Group(models.Model):
```

Только для Account (`apps/accounts/models.py`) — с exclude:

```python
@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
    exclude=[
        'password', 'twofa_secret',           # секреты — НИКОГДА в журнал
        'token_version', 'last_login',        # технический шум (меняются при каждом входе)
        'failed_login_count', 'locked_until',
    ],
)
class Account(AbstractUser):
```

НЕ трекать: AccountInvite, AccountRecoveryCode, SecurityAuditLog, SyncFailure.

- [ ] **Step 4.3: Миграции**

Run:
```bash
python manage.py makemigrations teachers students groups memberships lessons payments payroll discounts scheduling settings_app accounts
python manage.py migrate
```
Expected: по миграции на app, создаются `<Model>Event`-таблицы + триггеры.

- [ ] **Step 4.4: Прогон**

Run: `pytest apps/changelog -v` → 6 passed.
Run: `pytest` (полный)
Expected: весь сьют зелёный. Если existing-тесты упали на IntegrityError вокруг event-таблиц — это баг конфигурации (FK должны быть unconstrained), разбираться, НЕ отключать трекинг.

---

### Task 5: Контекст пользователя из JWT — TDD

**Files:**
- Test: `journal_django/apps/changelog/tests/test_context.py`
- Modify: `journal_django/apps/core/authentication.py`

- [ ] **Step 5.1: Failing-тест «API-мутация несёт актора и url»**

`journal_django/apps/changelog/tests/test_context.py`:

```python
"""
Контекст журнала: middleware даёт url/method, CookieJWTAuthentication — актора.
Проверяем через реальный API-вызов (admin_client из conftest).
"""
from __future__ import annotations

import pytest
from django.apps import apps

pytestmark = pytest.mark.django_db


def test_api_mutation_has_actor_and_url(admin_client):
    resp = admin_client.post('/api/admin/directions', {
        'name': '__chg_ctx_dir__', 'sheet_name': 'chg', 'is_individual': False,
    }, format='json')
    assert resp.status_code in (200, 201), resp.content

    ev_model = apps.get_model('directions', 'DirectionEvent')
    ev = ev_model.objects.filter(name='__chg_ctx_dir__').order_by('-pgh_id').first()
    assert ev is not None
    assert ev.pgh_context is not None
    meta = ev.pgh_context.metadata
    assert meta['url'] == '/api/admin/directions'
    assert meta['method'] == 'POST'
    assert meta['email'] == '__root_admin__@test.local'
    assert meta['role'] == 'admin'
    assert isinstance(meta['account_id'], int)


def test_orm_write_without_request_has_no_context():
    from apps.directions.models import Direction
    d = Direction.objects.create(name='__chg_noctx__', sheet_name='chg', is_individual=False)
    ev_model = apps.get_model('directions', 'DirectionEvent')
    ev = ev_model.objects.filter(pgh_obj_id=d.id).first()
    assert ev.pgh_context_id is None
```

Run: `pytest apps/changelog/tests/test_context.py -v`
Expected: первый тест FAIL (в metadata нет email/account_id), второй PASS.

- [ ] **Step 5.2: Дописать контекст в CookieJWTAuthentication**

В `journal_django/apps/core/authentication.py`: добавить `import pghistory` в импорты. В `CookieJWTAuthentication.authenticate` перед `return self.get_user(validated_token), validated_token`:

```python
        user = self.get_user(validated_token)

        # Журнал изменений: дописать актора в pghistory-контекст запроса.
        # Функция-вызов (не контекст-менеджер) добавляет metadata ТОЛЬКО если
        # middleware уже открыл сессию (мутирующие методы) — на GET no-op.
        pghistory.context(account_id=user.id, email=user.email, role=user.role)

        return user, validated_token
```

- [ ] **Step 5.3: Тесты зелёные**

Run: `pytest apps/changelog/tests/test_context.py -v` → 2 passed.
Run: `pytest apps/auth_app apps/core -v` → auth-тесты не сломаны.

---

### Task 6: registry.py + labels.py — TDD

**Files:**
- Create: `journal_django/apps/changelog/registry.py`
- Create: `journal_django/apps/changelog/labels.py`
- Test: `journal_django/apps/changelog/tests/test_registry.py`

- [ ] **Step 6.1: Failing-тесты**

`journal_django/apps/changelog/tests/test_registry.py`:

```python
from __future__ import annotations

import pytest
from django.apps import apps

from apps.changelog import labels, registry

pytestmark = pytest.mark.django_db


def test_registry_covers_all_tracked_models():
    """Каждая модель с event-моделью есть в registry, и наоборот."""
    tracked_in_db = set()
    for model in apps.get_models():
        name = model.__name__
        if name.endswith('Event') and model._meta.app_label != 'pghistory':
            tracked_in_db.add(f"{model._meta.app_label}.{name[:-5]}")
    assert tracked_in_db == set(registry.TRACKED.keys())


def test_event_model_lookup():
    ev = registry.event_model('groups.Group')
    assert ev is apps.get_model('groups', 'GroupEvent')


def test_account_not_revertable():
    assert registry.TRACKED['accounts.Account'].revertable is False
    assert registry.TRACKED['groups.Group'].revertable is True


def test_operation_from_url():
    assert labels.resolve_operation('POST', '/api/admin/groups') == 'group.create'
    assert labels.resolve_operation('PATCH', '/api/admin/groups/5') == 'group.update'
    assert labels.resolve_operation('POST', '/api/admin/groups/5/plan/12/reschedule') == 'plan.reschedule'
    assert labels.resolve_operation('POST', '/api/submitLesson') == 'lesson.submit'
    assert labels.resolve_operation('DELETE', '/api/admin/payments/9') == 'payment.delete'
    assert labels.resolve_operation('GET', '/api/admin/groups') == 'other'
```

Run: `pytest apps/changelog/tests/test_registry.py -v` → FAIL (модулей нет).

- [ ] **Step 6.2: registry.py**

```python
"""
Реестр трекаемых моделей журнала изменений.

Единственный источник знания «какие модели в журнале, как их зовут в API,
можно ли откатывать, в каком порядке восстанавливать по FK».

topo-порядок: родители раньше детей (для re-insert при откате delete).
"""
from __future__ import annotations

from dataclasses import dataclass

from django.apps import apps


@dataclass(frozen=True)
class TrackedModel:
    entity: str        # ключ сущности для API/фронта
    revertable: bool
    topo: int          # меньше = раньше вставлять при восстановлении


# Порядок topo: справочники → группы/ученики → членства/план → уроки → факты.
TRACKED: dict[str, TrackedModel] = {
    'directions.Direction':          TrackedModel('direction', True, 10),
    'teachers.Teacher':              TrackedModel('teacher', True, 10),
    'students.Student':              TrackedModel('student', True, 10),
    'discounts.Discount':            TrackedModel('discount', True, 10),
    'settings_app.AdminUserSettings': TrackedModel('settings', True, 10),
    'accounts.Account':              TrackedModel('account', False, 15),
    'groups.Group':                  TrackedModel('group', True, 20),
    'groups.GroupScheduleSlot':      TrackedModel('schedule_slot', True, 30),
    'memberships.GroupMembership':   TrackedModel('membership', True, 30),
    'scheduling.PlannedLesson':      TrackedModel('planned_lesson', True, 30),
    'lessons.Lesson':                TrackedModel('lesson', True, 40),
    'lessons.LessonAttendance':      TrackedModel('attendance', True, 50),
    'payments.Payment':              TrackedModel('payment', True, 50),
    'payroll.Payroll':               TrackedModel('payroll', True, 50),
}


def event_model(model_label: str):
    """'groups.Group' → класс GroupEvent (авто-генерируется pghistory)."""
    app_label, model_name = model_label.split('.')
    return apps.get_model(app_label, f'{model_name}Event')


def tracked_model(model_label: str):
    """'groups.Group' → класс Group."""
    app_label, model_name = model_label.split('.')
    return apps.get_model(app_label, model_name)
```

- [ ] **Step 6.3: labels.py**

```python
"""
Метки операций журнала: (HTTP-метод, url) → машинный ключ операции.

Русские названия — на фронте (lib/labels.ts). Ключ 'other' — fallback
для незамапленных мутаций: журнал остаётся читаемым, событие не теряется.
Порядок правил важен: более специфичные пути выше.
"""
from __future__ import annotations

import re

# (method, compiled regex, operation)
RULES: list[tuple[str, re.Pattern, str]] = [
    # scheduling (план занятий) — до generic groups-правил
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/generate$'), 'plan.generate'),
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/permanent-change$'), 'plan.permanent_change'),
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/change-teacher-permanent$'), 'plan.change_teacher_permanent'),
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/extra$'), 'plan.extra'),
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/\d+/reschedule$'), 'plan.reschedule'),
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/\d+/change-teacher$'), 'plan.change_teacher'),
    ('POST', re.compile(r'^/api/admin/groups/\d+/plan/\d+/cancel$'), 'plan.cancel'),
    # groups
    ('POST', re.compile(r'^/api/admin/groups/\d+/schedule-change$'), 'group.schedule_change'),
    ('POST', re.compile(r'^/api/admin/groups$'), 'group.create'),
    ('PATCH', re.compile(r'^/api/admin/groups/\d+$'), 'group.update'),
    ('DELETE', re.compile(r'^/api/admin/groups/\d+$'), 'group.delete'),
    # справочники
    ('POST', re.compile(r'^/api/admin/directions$'), 'direction.create'),
    ('PATCH', re.compile(r'^/api/admin/directions/\d+$'), 'direction.update'),
    ('DELETE', re.compile(r'^/api/admin/directions/\d+$'), 'direction.delete'),
    ('POST', re.compile(r'^/api/admin/teachers$'), 'teacher.create'),
    ('PATCH', re.compile(r'^/api/admin/teachers/\d+$'), 'teacher.update'),
    ('DELETE', re.compile(r'^/api/admin/teachers/\d+$'), 'teacher.delete'),
    ('POST', re.compile(r'^/api/admin/students$'), 'student.create'),
    ('PATCH', re.compile(r'^/api/admin/students/\d+$'), 'student.update'),
    ('DELETE', re.compile(r'^/api/admin/students/\d+$'), 'student.delete'),
    ('POST', re.compile(r'^/api/admin/discounts$'), 'discount.create'),
    ('PATCH', re.compile(r'^/api/admin/discounts/\d+$'), 'discount.update'),
    ('DELETE', re.compile(r'^/api/admin/discounts/\d+$'), 'discount.delete'),
    # memberships
    ('POST', re.compile(r'^/api/admin/memberships$'), 'membership.create'),
    ('PATCH', re.compile(r'^/api/admin/memberships/\d+$'), 'membership.update'),
    ('DELETE', re.compile(r'^/api/admin/memberships/\d+$'), 'membership.delete'),
    # payments (immutable: только create/delete)
    ('POST', re.compile(r'^/api/admin/payments$'), 'payment.create'),
    ('DELETE', re.compile(r'^/api/admin/payments/\d+$'), 'payment.delete'),
    # lessons
    ('PATCH', re.compile(r'^/api/admin/lessons/\d+/attendance/\d+$'), 'lesson.attendance_update'),
    ('POST', re.compile(r'^/api/admin/lessons$'), 'lesson.create'),
    ('PATCH', re.compile(r'^/api/admin/lessons/\d+$'), 'lesson.update'),
    ('DELETE', re.compile(r'^/api/admin/lessons/\d+$'), 'lesson.delete'),
    # payroll / settings
    ('PATCH', re.compile(r'^/api/admin/payroll/\d+$'), 'payroll.update'),
    ('PUT', re.compile(r'^/api/admin/settings$'), 'settings.update'),
    # accounts
    ('POST', re.compile(r'^/api/admin/accounts/\d+/reset-password$'), 'account.reset_password'),
    ('POST', re.compile(r'^/api/admin/accounts/\d+/reset-2fa$'), 'account.reset_2fa'),
    ('POST', re.compile(r'^/api/admin/accounts/\d+/invite/revoke$'), 'account.invite_revoke'),
    ('POST', re.compile(r'^/api/admin/accounts/\d+/invite$'), 'account.invite_create'),
    ('POST', re.compile(r'^/api/admin/accounts$'), 'account.create'),
    ('PATCH', re.compile(r'^/api/admin/accounts/\d+$'), 'account.update'),
    ('DELETE', re.compile(r'^/api/admin/accounts/\d+$'), 'account.delete'),
    # teacher SPA
    ('POST', re.compile(r'^/api/submitLesson$'), 'lesson.submit'),
    # auth-мутации данных (2FA-поля Account меняются юзером)
    ('POST', re.compile(r'^/api/auth/2fa/enable$'), 'account.twofa_enable'),
    ('POST', re.compile(r'^/api/auth/2fa/disable$'), 'account.twofa_disable'),
    ('POST', re.compile(r'^/api/auth/invite/accept$'), 'account.invite_accept'),
]

FALLBACK = 'other'


def resolve_operation(method: str, url: str) -> str:
    """Ключ операции по методу и пути; metadata['operation'] имеет приоритет
    у вызывающего (см. repository._operation_of)."""
    for rule_method, pattern, operation in RULES:
        if method == rule_method and pattern.match(url):
            return operation
    return FALLBACK


def rule_for_operation(operation: str):
    """Обратный поиск для фильтра ленты: operation → (method, regex) или None."""
    for rule_method, pattern, rule_operation in RULES:
        if rule_operation == operation:
            return rule_method, pattern
    return None
```

- [ ] **Step 6.4: Тесты зелёные**

Run: `pytest apps/changelog/tests/test_registry.py -v` → 4 passed.

---

### Task 7: Read-API — лента операций

**Files:**
- Create: `journal_django/apps/changelog/repository.py`
- Create: `journal_django/apps/changelog/services.py`
- Create: `journal_django/apps/changelog/views.py`
- Create: `journal_django/apps/changelog/urls.py`
- Modify: `journal_django/config/urls.py`
- Test: `journal_django/apps/changelog/tests/test_api_list.py`

- [ ] **Step 7.1: Failing-тесты**

`journal_django/apps/changelog/tests/test_api_list.py`:

```python
"""
GET /api/admin/changelog — лента операций (1 строка = 1 контекст).
Контракт пагинации проекта: { rows, total, page, page_size }.
RBAC: только admin.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _mutate(client, name='__chg_list_dir__'):
    resp = client.post('/api/admin/directions', {
        'name': name, 'sheet_name': 'chg', 'is_individual': False,
    }, format='json')
    assert resp.status_code in (200, 201), resp.content
    return resp


def test_rbac_admin_only(admin_client, manager_client, teacher_client, anon_client):
    assert admin_client.get('/api/admin/changelog').status_code == 200
    assert manager_client.get('/api/admin/changelog').status_code == 403
    assert teacher_client.get('/api/admin/changelog').status_code == 403
    assert anon_client.get('/api/admin/changelog').status_code in (401, 403)


def test_feed_row_shape(admin_client):
    _mutate(admin_client)
    data = admin_client.get('/api/admin/changelog').json()
    assert set(data) == {'rows', 'total', 'page', 'page_size'}
    row = data['rows'][0]
    assert row['operation'] == 'direction.create'
    assert row['actor']['email'] == '__root_admin__@test.local'
    assert row['actor']['role'] == 'admin'
    assert row['method'] == 'POST'
    assert row['url'] == '/api/admin/directions'
    assert row['events_total'] == 1
    assert row['entities'] == [{'entity': 'direction', 'inserts': 1, 'updates': 0, 'deletes': 0}]
    assert row['revertable'] is True
    assert 'occurred_at' in row and 'id' in row


def test_filter_by_actor_and_operation(admin_client):
    _mutate(admin_client)
    ok = admin_client.get(
        '/api/admin/changelog?filter[actor]=root_admin&filter[operation]=direction.create'
    ).json()
    assert ok['total'] >= 1
    miss = admin_client.get('/api/admin/changelog?filter[actor]=nobody@x').json()
    assert miss['total'] == 0
    miss2 = admin_client.get('/api/admin/changelog?filter[operation]=group.delete').json()
    assert miss2['total'] == 0


def test_filter_by_entity(admin_client):
    resp = _mutate(admin_client)
    direction_id = resp.json().get('id') or resp.json().get('direction', {}).get('id')
    found = admin_client.get(
        f'/api/admin/changelog?filter[entity]=direction&filter[entity_id]={direction_id}'
    ).json()
    assert found['total'] == 1
    empty = admin_client.get('/api/admin/changelog?filter[entity]=group').json()
    assert empty['total'] == 0


def test_pagination(admin_client):
    for i in range(3):
        _mutate(admin_client, name=f'__chg_pg_{i}__')
    page = admin_client.get('/api/admin/changelog?page=2&page_size=1').json()
    assert page['page'] == 2 and page['page_size'] == 1
    assert len(page['rows']) == 1
    assert page['total'] >= 3
```

Run: `pytest apps/changelog/tests/test_api_list.py -v` → FAIL (404).

Примечание: в `test_filter_by_entity` форма ответа POST /directions — проверить фактическую (см. `apps/directions/views.py:43`) и взять id оттуда.

- [ ] **Step 7.2: repository.py**

```python
"""
ChangelogRepository — доступ к pghistory_context + event-таблицам.

Лента: пагинация по Context (индекс по created_at), затем ОДИН агрегатный
проход по Events только для контекстов страницы (без UNION по всей истории).
"""
from __future__ import annotations

from typing import Any, Optional

from django.db.models import Exists, OuterRef
from pghistory.models import Context, Events

from apps.changelog import labels, registry


def _operation_of(metadata: dict) -> str:
    return metadata.get('operation') or labels.resolve_operation(
        metadata.get('method', ''), metadata.get('url', ''),
    )


def _actor_of(metadata: dict) -> Optional[dict]:
    if 'account_id' not in metadata:
        return None
    return {
        'account_id': metadata['account_id'],
        'email': metadata.get('email'),
        'role': metadata.get('role'),
    }


def _entity_of(pgh_model_label: str) -> Optional[str]:
    """'groups.Group' (pgh_obj_model) → 'group'; None для нетрекаемых."""
    cfg = registry.TRACKED.get(pgh_model_label)
    return cfg.entity if cfg else None


def _apply_filters(qs, filters: dict[str, Any]):
    actor = filters.get('actor')
    if actor not in (None, ''):
        qs = qs.filter(metadata__email__icontains=str(actor))

    operation = filters.get('operation')
    if operation not in (None, ''):
        if operation == 'changelog.revert':
            qs = qs.filter(metadata__operation='changelog.revert')
        else:
            rule = labels.rule_for_operation(str(operation))
            if rule is None:
                return qs.none()
            method, pattern = rule
            qs = qs.filter(metadata__method=method,
                           metadata__url__regex=pattern.pattern)

    date_from = filters.get('date_from')
    if date_from not in (None, ''):
        qs = qs.filter(created_at__date__gte=date_from)
    date_to = filters.get('date_to')
    if date_to not in (None, ''):
        qs = qs.filter(created_at__date__lte=date_to)

    entity = filters.get('entity')
    if entity not in (None, ''):
        model_label = next(
            (ml for ml, cfg in registry.TRACKED.items() if cfg.entity == entity),
            None,
        )
        if model_label is None:
            return qs.none()
        event_qs = registry.event_model(model_label).objects.filter(
            pgh_context_id=OuterRef('pk'),
        )
        entity_id = filters.get('entity_id')
        if entity_id not in (None, ''):
            event_qs = event_qs.filter(pgh_obj_id=int(entity_id))
        qs = qs.filter(Exists(event_qs))

    return qs


def list_operations(page: int, page_size: int, filters: dict) -> dict:
    qs = _apply_filters(Context.objects.all(), filters).order_by('-created_at', '-id')

    total = qs.count()
    offset = max(0, (page - 1) * page_size)
    contexts = list(qs[offset:offset + page_size].values('id', 'created_at', 'metadata'))
    ctx_ids = [c['id'] for c in contexts]

    # Агрегаты событий страницы одним проходом по Events (CTE только по нужным uuid).
    per_ctx: dict = {cid: {} for cid in ctx_ids}
    if ctx_ids:
        ev_rows = Events.objects.filter(pgh_context_id__in=ctx_ids).values(
            'pgh_context_id', 'pgh_obj_model', 'pgh_label',
        )
        for ev in ev_rows:
            bucket = per_ctx[ev['pgh_context_id']].setdefault(
                ev['pgh_obj_model'], {'insert': 0, 'update': 0, 'delete': 0},
            )
            if ev['pgh_label'] in bucket:
                bucket[ev['pgh_label']] += 1

    rows = []
    for ctx in contexts:
        meta = ctx['metadata'] or {}
        buckets = per_ctx.get(ctx['id'], {})
        entities = []
        revertable = bool(buckets)
        for model_label, counts in sorted(buckets.items()):
            cfg = registry.TRACKED.get(model_label)
            if cfg is None or not cfg.revertable:
                revertable = False
            entities.append({
                'entity': _entity_of(model_label) or model_label,
                'inserts': counts['insert'],
                'updates': counts['update'],
                'deletes': counts['delete'],
            })
        rows.append({
            'id': str(ctx['id']),
            'occurred_at': ctx['created_at'],
            'actor': _actor_of(meta),
            'operation': _operation_of(meta),
            'url': meta.get('url'),
            'method': meta.get('method'),
            'entities': entities,
            'events_total': sum(
                sum(c.values()) for c in buckets.values()
            ),
            'revertable': revertable,
        })

    return {'rows': rows, 'total': total, 'page': page, 'page_size': page_size}
```

Примечание для исполнителя: пустые контексты (мутирующий запрос без изменений)
дают `events_total=0`, `revertable=False` — фронт их отфильтрует или покажет
серыми; НЕ вырезать на SQL-уровне в v1 (14 EXISTS на всю таблицу дороже, чем
редкие пустые строки).

- [ ] **Step 7.3: services.py**

```python
"""ChangelogService — тонкий слой между views и repository (+ revert в Task 9)."""
from __future__ import annotations

from apps.changelog import repository


def list_operations(page: int = 1, page_size: int = 50, filters: dict | None = None) -> dict:
    return repository.list_operations(
        page=page, page_size=page_size, filters=filters or {},
    )
```

- [ ] **Step 7.4: views.py + urls.py + mount**

`journal_django/apps/changelog/views.py`:

```python
"""
Views раздела «Журнал изменений» (/api/admin/changelog).

RBAC: ВЕСЬ раздел — только admin (решение владельца, спека §11).
"""
from __future__ import annotations

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.changelog import services
from apps.core.permissions import IsAdmin


def _parse_list_params(request: Request) -> dict:
    qp = request.query_params
    page = max(1, int(qp.get('page', 1) or 1))
    page_size = min(200, max(1, int(qp.get('page_size', 50) or 50)))

    filters: dict = {}
    for key, value in qp.items():
        if key.startswith('filter[') and key.endswith(']'):
            filters[key[7:-1]] = value

    return {'page': page, 'page_size': page_size, 'filters': filters}


class ChangelogListView(APIView):
    """GET /api/admin/changelog — лента операций."""

    permission_classes = [IsAdmin]

    def get(self, request: Request) -> Response:
        return Response(services.list_operations(**_parse_list_params(request)))
```

`journal_django/apps/changelog/urls.py`:

```python
"""
URL маршруты журнала изменений.

Монтируются в config/urls.py как:
  path('api/admin/changelog', include('apps.changelog.urls'))
"""
from django.urls import path

from apps.changelog.views import ChangelogListView

urlpatterns = [
    path('', ChangelogListView.as_view(), name='changelog-list'),
]
```

В `journal_django/config/urls.py` после строки audit-log:

```python
    path('api/admin/changelog', include('apps.changelog.urls')),
```

- [ ] **Step 7.5: Тесты зелёные**

Run: `pytest apps/changelog/tests/test_api_list.py -v` → 5 passed.

---

### Task 8: Read-API — детали операции (diff)

**Files:**
- Modify: `journal_django/apps/changelog/repository.py`
- Modify: `journal_django/apps/changelog/services.py`
- Modify: `journal_django/apps/changelog/views.py`
- Modify: `journal_django/apps/changelog/urls.py`
- Test: `journal_django/apps/changelog/tests/test_api_detail.py`

- [ ] **Step 8.1: Failing-тесты**

`journal_django/apps/changelog/tests/test_api_detail.py`:

```python
"""GET /api/admin/changelog/<uuid> — события операции с diff «было/стало»."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _create_and_rename(client):
    resp = client.post('/api/admin/directions', {
        'name': '__chg_det_1__', 'sheet_name': 'chg', 'is_individual': False,
    }, format='json')
    body = resp.json()
    direction_id = body.get('id') or body.get('direction', {}).get('id')
    client.patch(f'/api/admin/directions/{direction_id}',
                 {'name': '__chg_det_2__'}, format='json')
    feed = client.get('/api/admin/changelog?page_size=2').json()['rows']
    update_op = next(r for r in feed if r['operation'] == 'direction.update')
    return direction_id, update_op['id']


def test_detail_diff(admin_client):
    direction_id, ctx_id = _create_and_rename(admin_client)
    data = admin_client.get(f'/api/admin/changelog/{ctx_id}').json()
    assert data['operation'] == 'direction.update'
    assert data['revertable'] is True
    assert len(data['events']) == 1
    ev = data['events'][0]
    assert ev['entity'] == 'direction'
    assert ev['obj_id'] == direction_id
    assert ev['label'] == 'update'
    assert ev['diff']['name'] == ['__chg_det_1__', '__chg_det_2__']


def test_detail_404(admin_client):
    resp = admin_client.get('/api/admin/changelog/00000000-0000-0000-0000-000000000000')
    assert resp.status_code == 404


def test_detail_rbac(manager_client):
    resp = manager_client.get('/api/admin/changelog/00000000-0000-0000-0000-000000000000')
    assert resp.status_code == 403
```

Run: `pytest apps/changelog/tests/test_api_detail.py -v` → FAIL (404 на всё).

- [ ] **Step 8.2: repository.get_operation**

Добавить в `apps/changelog/repository.py`:

```python
def get_operation(context_id) -> Optional[dict]:
    """Детали операции: контекст + события с diff. None, если контекста нет."""
    ctx = Context.objects.filter(pk=context_id).values('id', 'created_at', 'metadata').first()
    if ctx is None:
        return None
    meta = ctx['metadata'] or {}

    events = []
    revertable = True
    ev_rows = list(
        Events.objects.filter(pgh_context_id=context_id)
        .order_by('pgh_created_at', 'pgh_id')
        .values('pgh_model', 'pgh_obj_model', 'pgh_obj_id', 'pgh_label',
                'pgh_data', 'pgh_diff', 'pgh_created_at')
    )
    if not ev_rows:
        revertable = False
    for ev in ev_rows:
        cfg = registry.TRACKED.get(ev['pgh_obj_model'])
        if cfg is None or not cfg.revertable:
            revertable = False
        events.append({
            'model': ev['pgh_obj_model'],
            'entity': _entity_of(ev['pgh_obj_model']) or ev['pgh_obj_model'],
            'obj_id': ev['pgh_obj_id'],
            'label': ev['pgh_label'],
            'data': ev['pgh_data'],
            'diff': ev['pgh_diff'],
        })

    return {
        'id': str(ctx['id']),
        'occurred_at': ctx['created_at'],
        'actor': _actor_of(meta),
        'operation': _operation_of(meta),
        'url': meta.get('url'),
        'method': meta.get('method'),
        'revertable': revertable,
        'events': events,
    }
```

Примечание: `pgh_obj_id` в Events приходит текстом (UNION приводит типы) —
если тест упадёт на `ev['obj_id'] == direction_id`, привести к int по
`registry`-модели: `int(...)` для целочисленных PK.

- [ ] **Step 8.3: services + view + url**

В `services.py`:

```python
def get_operation(context_id) -> dict | None:
    return repository.get_operation(context_id)
```

В `views.py`:

```python
from rest_framework.exceptions import NotFound


class ChangelogDetailView(APIView):
    """GET /api/admin/changelog/<uuid:context_id> — детали операции."""

    permission_classes = [IsAdmin]

    def get(self, request: Request, context_id) -> Response:
        data = services.get_operation(context_id)
        if data is None:
            raise NotFound('Операция не найдена.')
        return Response(data)
```

В `urls.py`:

```python
from apps.changelog.views import ChangelogDetailView, ChangelogListView

urlpatterns = [
    path('', ChangelogListView.as_view(), name='changelog-list'),
    path('/<uuid:context_id>', ChangelogDetailView.as_view(), name='changelog-detail'),
]
```

- [ ] **Step 8.4: Тесты зелёные**

Run: `pytest apps/changelog/tests/test_api_detail.py -v` → 3 passed.

---

### Task 9: Revert-сервис — TDD

**Files:**
- Create: `journal_django/apps/changelog/revert.py`
- Test: `journal_django/apps/changelog/tests/test_revert.py`

- [ ] **Step 9.1: Failing-тесты**

`journal_django/apps/changelog/tests/test_revert.py`:

```python
"""
Откат операции по контексту: обратный порядок, конфликт-детекция,
запрет accounts, восстановление hard-delete с поправкой sequence.
"""
from __future__ import annotations

import pghistory
import pytest
from django.apps import apps

from apps.changelog import revert
from apps.changelog.revert import RevertConflict, RevertForbidden
from apps.directions.models import Direction

pytestmark = pytest.mark.django_db


def _ctx_of(direction_id):
    """UUID контекста последнего события по Direction."""
    ev = apps.get_model('directions', 'DirectionEvent')
    return (ev.objects.filter(pgh_obj_id=direction_id, pgh_context_id__isnull=False)
            .order_by('-pgh_id').first().pgh_context_id)


def _make(name='__chg_rev__'):
    return Direction.objects.create(name=name, sheet_name='chg', is_individual=False)


def test_revert_update():
    d = _make()
    with pghistory.context(url='/t', method='PATCH'):
        Direction.objects.filter(id=d.id).update(name='__chg_rev_new__')
    summary = revert.revert_context(_ctx_of(d.id))
    d.refresh_from_db()
    assert d.name == '__chg_rev__'
    assert summary['reverted_events'] == 1


def test_revert_insert_deletes_row():
    with pghistory.context(url='/t', method='POST'):
        d = _make('__chg_rev_ins__')
    revert.revert_context(_ctx_of(d.id))
    assert not Direction.objects.filter(id=d.id).exists()


def test_revert_delete_restores_row_and_sequence():
    d = _make('__chg_rev_del__')
    d_id = d.id
    with pghistory.context(url='/t', method='DELETE'):
        Direction.objects.filter(id=d_id).delete()
    revert.revert_context(_ctx_of(d_id))
    restored = Direction.objects.get(id=d_id)
    assert restored.name == '__chg_rev_del__'
    # sequence поправлен: следующая вставка не конфликтует по PK
    d2 = _make('__chg_rev_after__')
    assert d2.id > d_id


def test_revert_composite_operation():
    """Insert + update разных строк в одном контексте откатываются вместе."""
    d1 = _make('__chg_comp_1__')
    with pghistory.context(url='/t', method='POST'):
        d2 = Direction.objects.create(name='__chg_comp_2__', sheet_name='chg',
                                      is_individual=False)
        Direction.objects.filter(id=d1.id).update(active=False)
    revert.revert_context(_ctx_of(d2.id))
    d1.refresh_from_db()
    assert d1.active is True
    assert not Direction.objects.filter(id=d2.id).exists()


def test_revert_conflict_on_later_change():
    d = _make('__chg_confl__')
    with pghistory.context(url='/t', method='PATCH'):
        Direction.objects.filter(id=d.id).update(name='__chg_confl_v2__')
    ctx = _ctx_of(d.id)
    # Более позднее изменение той же строки → конфликт
    Direction.objects.filter(id=d.id).update(name='__chg_confl_v3__')
    with pytest.raises(RevertConflict) as exc_info:
        revert.revert_context(ctx)
    assert exc_info.value.conflicts
    d.refresh_from_db()
    assert d.name == '__chg_confl_v3__'  # ничего не изменилось (atomic)


def test_revert_accounts_forbidden(admin_client):
    """Операции с Account не откатываются (v1)."""
    resp = admin_client.post('/api/admin/accounts', {
        'email': '__chg_acc__@test.local', 'role': 'manager',
    }, format='json')
    assert resp.status_code in (200, 201), resp.content
    ev = apps.get_model('accounts', 'AccountEvent')
    ctx = (ev.objects.filter(email='__chg_acc__@test.local')
           .order_by('-pgh_id').first().pgh_context_id)
    with pytest.raises(RevertForbidden):
        revert.revert_context(ctx)


def test_revert_is_itself_tracked():
    d = _make('__chg_track_rev__')
    with pghistory.context(url='/t', method='PATCH'):
        Direction.objects.filter(id=d.id).update(name='__chg_track_rev2__')
    revert.revert_context(_ctx_of(d.id))
    ev = apps.get_model('directions', 'DirectionEvent')
    last = ev.objects.filter(pgh_obj_id=d.id).order_by('-pgh_id').first()
    assert last.pgh_context is not None
    assert last.pgh_context.metadata.get('operation') == 'changelog.revert'
```

Run: `pytest apps/changelog/tests/test_revert.py -v` → FAIL (модуля revert нет).

Примечание: форма POST /api/admin/accounts — сверить с `apps/accounts/views.py:76`
(какие поля обязательны) и поправить тело запроса в тесте.

- [ ] **Step 9.2: revert.py**

```python
"""
Откат операции журнала изменений по pghistory-контексту.

Алгоритм (спека §6):
  1. Собрать события контекста из конкретных event-моделей (типизированные поля).
  2. Конфликт-детекция: текущее состояние каждой строки должно совпадать
     со снапшотом события (для delete — строка должна отсутствовать).
     Любое расхождение → RevertConflict, транзакция не начата/откатана.
  3. Применение в FK-безопасном порядке:
       a) undo-insert: удалить вставленные строки (дети раньше родителей);
       b) undo-delete: вставить удалённые строки (родители раньше детей);
       c) undo-update: вернуть предыдущий снапшот строки.
  4. Поправить sequences после вставок с явным PK.
Всё в одной transaction.atomic + pghistory.context(operation='changelog.revert')
— сам откат попадает в журнал как новая операция (redo-след).
"""
from __future__ import annotations

from django.db import connection, transaction

import pghistory
from pghistory.models import Context

from apps.changelog import registry


class RevertError(Exception):
    """База ошибок отката."""


class RevertForbidden(RevertError):
    """Контекст содержит неоткатываемые модели (accounts) или пуст."""


class RevertConflict(RevertError):
    """Данные изменились после операции — откат отклонён."""

    def __init__(self, conflicts: list[dict]):
        self.conflicts = conflicts
        super().__init__(f'{len(conflicts)} конфликт(ов)')


def _tracked_attnames(event_model, model) -> list[str]:
    """attname-поля модели, которые есть и в event-модели (без pgh_*)."""
    event_names = {f.name for f in event_model._meta.get_fields()}
    return [
        f.attname for f in model._meta.concrete_fields
        if f.name in event_names or f.attname in event_names
    ]


def _snapshot_matches(current, event, attnames) -> list[str]:
    """Список полей, где текущая строка отличается от снапшота события."""
    return [
        a for a in attnames
        if getattr(current, a) != getattr(event, a)
    ]


def _load_events(context_id) -> list[tuple[str, object]]:
    """[(model_label, event_instance), ...] всех событий контекста."""
    result = []
    for model_label in registry.TRACKED:
        event_model = registry.event_model(model_label)
        for ev in event_model.objects.filter(pgh_context_id=context_id):
            result.append((model_label, ev))
    return result


def _check_conflicts(events: list[tuple[str, object]]) -> list[dict]:
    conflicts = []
    for model_label, ev in events:
        model = registry.tracked_model(model_label)
        event_model = registry.event_model(model_label)
        attnames = _tracked_attnames(event_model, model)
        pk = ev.pgh_obj_id
        current = model.objects.filter(pk=pk).first()

        if ev.pgh_label == 'delete':
            if current is not None:
                conflicts.append({'model': model_label, 'obj_id': pk,
                                  'reason': 'row_exists'})
        else:  # insert / update — строка должна существовать и совпадать
            if current is None:
                conflicts.append({'model': model_label, 'obj_id': pk,
                                  'reason': 'row_missing'})
                continue
            changed = _snapshot_matches(current, ev, attnames)
            if changed:
                conflicts.append({'model': model_label, 'obj_id': pk,
                                  'reason': 'changed_later', 'fields': changed})
    return conflicts


def _previous_event(model_label, ev):
    """Предыдущее событие той же строки (для undo-update)."""
    event_model = registry.event_model(model_label)
    return (event_model.objects
            .filter(pgh_obj_id=ev.pgh_obj_id, pgh_id__lt=ev.pgh_id)
            .order_by('-pgh_id').first())


def _fix_sequence(model) -> None:
    """После INSERT с явным PK сдвинуть sequence, иначе будущие вставки упадут."""
    table = model._meta.db_table
    pk_col = model._meta.pk.column
    with connection.cursor() as cur:
        cur.execute(
            'SELECT pg_get_serial_sequence(%s, %s)', [table, pk_col],
        )
        seq = cur.fetchone()[0]
        if seq is None:
            return
        cur.execute(
            f'SELECT setval(%s, GREATEST((SELECT COALESCE(MAX("{pk_col}"), 1) '
            f'FROM "{table}"), 1))',
            [seq],
        )


def revert_context(context_id) -> dict:
    """Откатить операцию. Возвращает сводку; бросает Revert*-исключения."""
    if not Context.objects.filter(pk=context_id).exists():
        raise RevertError('Операция не найдена.')

    events = _load_events(context_id)
    if not events:
        raise RevertForbidden('Операция не содержит изменений данных.')

    forbidden = sorted({
        ml for ml, _ in events if not registry.TRACKED[ml].revertable
    })
    if forbidden:
        raise RevertForbidden(
            'Откат недоступен: операция затрагивает ' + ', '.join(forbidden),
        )

    # undo-update идёт с конца: у одной строки может быть несколько update
    # в контексте — восстанавливаем к состоянию ДО первого из них.
    inserts = [(ml, ev) for ml, ev in events if ev.pgh_label == 'insert']
    updates = [(ml, ev) for ml, ev in events if ev.pgh_label == 'update']
    deletes = [(ml, ev) for ml, ev in events if ev.pgh_label == 'delete']

    # Конфликты сверяем по ПОСЛЕДНЕМУ событию каждой строки в контексте.
    last_by_row: dict[tuple, tuple] = {}
    for ml, ev in events:
        key = (ml, ev.pgh_obj_id)
        if key not in last_by_row or ev.pgh_id > last_by_row[key][1].pgh_id:
            last_by_row[key] = (ml, ev)
    conflicts = _check_conflicts(list(last_by_row.values()))
    if conflicts:
        raise RevertConflict(conflicts)

    with transaction.atomic(), pghistory.context(
        operation='changelog.revert', revert_of=str(context_id),
    ):
        # a) удалить вставленное: дети раньше родителей
        for ml, ev in sorted(inserts, key=lambda p: -registry.TRACKED[p[0]].topo):
            model = registry.tracked_model(ml)
            model.objects.filter(pk=ev.pgh_obj_id).delete()

        # b) вернуть удалённое: родители раньше детей
        touched_models = set()
        for ml, ev in sorted(deletes, key=lambda p: registry.TRACKED[p[0]].topo):
            model = registry.tracked_model(ml)
            event_model = registry.event_model(ml)
            attnames = _tracked_attnames(event_model, model)
            model(**{a: getattr(ev, a) for a in attnames}).save(force_insert=True)
            touched_models.add(model)

        # c) вернуть обновлённое к состоянию до контекста:
        #    для каждой строки берём ПЕРВЫЙ update контекста и его предыдущее событие
        first_update_by_row: dict[tuple, tuple] = {}
        for ml, ev in updates:
            key = (ml, ev.pgh_obj_id)
            if key not in first_update_by_row or ev.pgh_id < first_update_by_row[key][1].pgh_id:
                first_update_by_row[key] = (ml, ev)
        for ml, ev in first_update_by_row.values():
            model = registry.tracked_model(ml)
            event_model = registry.event_model(ml)
            prev = _previous_event(ml, ev)
            if prev is None:
                raise RevertConflict([{'model': ml, 'obj_id': ev.pgh_obj_id,
                                       'reason': 'no_previous_state'}])
            attnames = _tracked_attnames(event_model, model)
            model.objects.filter(pk=ev.pgh_obj_id).update(
                **{a: getattr(prev, a) for a in attnames if a != model._meta.pk.attname},
            )

        for model in touched_models:
            _fix_sequence(model)

    return {
        'reverted_events': len(events),
        'inserts_undone': len(inserts),
        'deletes_undone': len(deletes),
        'updates_undone': len(first_update_by_row),
    }
```

- [ ] **Step 9.3: Тесты зелёные**

Run: `pytest apps/changelog/tests/test_revert.py -v` → 7 passed.

Известная тонкость: в `test_revert_update` откат должен опираться на
insert-событие как «предыдущее» — оно создано ВНЕ контекста (без middleware),
что нормально: `_previous_event` ищет по pgh_id, не по контексту.

---

### Task 10: Revert-endpoint

**Files:**
- Modify: `journal_django/apps/changelog/services.py`
- Modify: `journal_django/apps/changelog/views.py`
- Modify: `journal_django/apps/changelog/urls.py`
- Test: `journal_django/apps/changelog/tests/test_api_revert.py`

- [ ] **Step 10.1: Failing-тесты**

`journal_django/apps/changelog/tests/test_api_revert.py`:

```python
"""POST /api/admin/changelog/<uuid>/revert — только admin, аудит в security_audit_log."""
from __future__ import annotations

import pytest

from apps.audit.models import SecurityAuditLog

pytestmark = pytest.mark.django_db


def _last_op_id(client):
    return client.get('/api/admin/changelog?page_size=1').json()['rows'][0]['id']


def _create_direction(client):
    resp = client.post('/api/admin/directions', {
        'name': '__chg_api_rev__', 'sheet_name': 'chg', 'is_individual': False,
    }, format='json')
    assert resp.status_code in (200, 201)


def test_revert_endpoint_success(admin_client):
    _create_direction(admin_client)
    op_id = _last_op_id(admin_client)
    resp = admin_client.post(f'/api/admin/changelog/{op_id}/revert')
    assert resp.status_code == 200, resp.content
    assert resp.json()['reverted_events'] == 1
    # аудит-событие безопасности записано
    assert SecurityAuditLog.objects.filter(event='changelog_revert').exists()


def test_revert_endpoint_conflict_409(admin_client):
    from apps.directions.models import Direction
    _create_direction(admin_client)
    op_id = _last_op_id(admin_client)
    Direction.objects.filter(name='__chg_api_rev__').update(name='__chg_api_rev2__')
    resp = admin_client.post(f'/api/admin/changelog/{op_id}/revert')
    assert resp.status_code == 409
    assert resp.json()['conflicts']


def test_revert_endpoint_rbac(admin_client, manager_client, teacher_client):
    _create_direction(admin_client)
    op_id = _last_op_id(admin_client)
    assert manager_client.post(f'/api/admin/changelog/{op_id}/revert').status_code == 403
    assert teacher_client.post(f'/api/admin/changelog/{op_id}/revert').status_code == 403


def test_revert_endpoint_404(admin_client):
    resp = admin_client.post(
        '/api/admin/changelog/00000000-0000-0000-0000-000000000000/revert')
    assert resp.status_code == 404
```

Run: `pytest apps/changelog/tests/test_api_revert.py -v` → FAIL (404).

- [ ] **Step 10.2: services.revert_operation + view + url**

В `services.py`:

```python
from typing import Optional

from rest_framework.request import Request

from apps.audit.services import log_event
from apps.changelog import revert as revert_module


def revert_operation(context_id, request: Optional[Request] = None) -> dict:
    """Откатить операцию + записать событие безопасности changelog_revert."""
    summary = revert_module.revert_context(context_id)
    user = getattr(request, 'user', None) if request is not None else None
    log_event(
        'changelog_revert',
        account_id=getattr(user, 'id', None),
        actor_email=getattr(user, 'email', None),
        meta={'context_id': str(context_id), **summary},
        request=request,
    )
    return summary
```

В `views.py`:

```python
from apps.changelog.revert import RevertConflict, RevertError, RevertForbidden


class ChangelogRevertView(APIView):
    """POST /api/admin/changelog/<uuid:context_id>/revert — откат операции."""

    permission_classes = [IsAdmin]

    def post(self, request: Request, context_id) -> Response:
        try:
            summary = services.revert_operation(context_id, request=request)
        except RevertConflict as exc:
            return Response({'error': 'conflict', 'conflicts': exc.conflicts},
                            status=409)
        except RevertForbidden as exc:
            return Response({'error': 'forbidden', 'detail': str(exc)}, status=400)
        except RevertError:
            raise NotFound('Операция не найдена.')
        return Response(summary)
```

В `urls.py` добавить маршрут:

```python
    path('/<uuid:context_id>/revert', ChangelogRevertView.as_view(),
         name='changelog-revert'),
```

- [ ] **Step 10.3: Тесты зелёные**

Run: `pytest apps/changelog/tests/test_api_revert.py -v` → 4 passed.

---

### Task 11: Retention — prune_changelog

**Files:**
- Create: `journal_django/apps/changelog/management/__init__.py` (пустой)
- Create: `journal_django/apps/changelog/management/commands/__init__.py` (пустой)
- Create: `journal_django/apps/changelog/management/commands/prune_changelog.py`
- Test: `journal_django/apps/changelog/tests/test_prune.py`

- [ ] **Step 11.1: Failing-тест**

`journal_django/apps/changelog/tests/test_prune.py`:

```python
from __future__ import annotations

from datetime import timedelta

import pytest
from django.apps import apps
from django.core.management import call_command
from django.utils import timezone

from apps.directions.models import Direction

pytestmark = pytest.mark.django_db


def test_prune_removes_old_events_keeps_fresh():
    d = Direction.objects.create(name='__chg_prune__', sheet_name='chg',
                                 is_individual=False)
    ev_model = apps.get_model('directions', 'DirectionEvent')
    ev = ev_model.objects.get(pgh_obj_id=d.id)
    # состарить событие
    ev_model.objects.filter(pk=ev.pk).update(
        pgh_created_at=timezone.now() - timedelta(days=400))

    call_command('prune_changelog', '--keep-months', '12')
    assert not ev_model.objects.filter(pgh_obj_id=d.id).exists()

    d2 = Direction.objects.create(name='__chg_prune_fresh__', sheet_name='chg',
                                  is_individual=False)
    call_command('prune_changelog', '--keep-months', '12')
    assert ev_model.objects.filter(pgh_obj_id=d2.id).exists()
```

Run: `pytest apps/changelog/tests/test_prune.py -v` → FAIL (unknown command).

- [ ] **Step 11.2: Команда**

`prune_changelog.py`:

```python
"""
prune_changelog — retention журнала изменений (спека §8: 12 месяцев).

Удаляет события старше --keep-months и контексты старше порога, на которые
не осталось ссылок. Запускать cron'ом на VPS (раз в сутки, см. deploy-runbook).
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef
from django.utils import timezone

from pghistory.models import Context

from apps.changelog import registry


class Command(BaseCommand):
    help = 'Удалить события журнала изменений старше N месяцев (default 12).'

    def add_arguments(self, parser):
        parser.add_argument('--keep-months', type=int, default=12)

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options['keep_months'] * 30)
        total = 0
        for model_label in registry.TRACKED:
            event_model = registry.event_model(model_label)
            deleted, _ = event_model.objects.filter(
                pgh_created_at__lt=cutoff).delete()
            total += deleted

        ctx_qs = Context.objects.filter(created_at__lt=cutoff)
        for model_label in registry.TRACKED:
            event_model = registry.event_model(model_label)
            ctx_qs = ctx_qs.exclude(Exists(
                event_model.objects.filter(pgh_context_id=OuterRef('pk'))))
        ctx_deleted, _ = ctx_qs.delete()

        self.stdout.write(self.style.SUCCESS(
            f'Удалено событий: {total}, контекстов: {ctx_deleted} '
            f'(старше {options["keep_months"]} мес).'))
```

- [ ] **Step 11.3: Тест зелёный**

Run: `pytest apps/changelog/tests/test_prune.py -v` → 1 passed.

---

### Task 12: Документация + полный прогон

**Files:**
- Modify: `docs/endpoints.md` (раздел changelog)
- Modify: `CLAUDE.md` (одна строка в «Критичные соглашения»)
- Modify: `docs/superpowers/specs/2026-07-06-changelog-design.md` (статус)

- [ ] **Step 12.1: docs/endpoints.md**

Добавить раздел (рядом с audit-log), кратко: три эндпоинта, права IsAdmin,
контракт `{rows,total,page,page_size}`, фильтры, коды 409/400 у revert.

- [ ] **Step 12.2: CLAUDE.md**

В раздел «Критичные соглашения» добавить строку:

```
**Журнал изменений (pghistory)**: новые доменные модели ОБЯЗАНЫ получать `@pghistory.track(...)` + запись в `apps/changelog/registry.py` (тест `test_registry_covers_all_tracked_models` упадёт, если забыть). Мутации мимо ORM-триггеров не бывает; метки операций — `apps/changelog/labels.py`.
```

- [ ] **Step 12.3: Полный прогон**

Run: `pytest`
Expected: весь сьют зелёный (97+ старых + ~25 новых).

Run: `python manage.py check --deploy 2>&1 | head -30`
Expected: без новых ошибок относительно текущего состояния.

- [ ] **Step 12.4: Обновить статус спеки**

В `2026-07-06-changelog-design.md` сменить статус на «бэкенд реализован
(см. план 2026-07-06-changelog-backend.md), фронтенд — следующий план».

---

## Self-review (выполнен при написании)

- Покрытие спеки: §2 (Task 3-4), §4 (Task 1-2, 5-6), §5 (Task 4 exclude, Task 7/8/10 RBAC+CSRF+audit), §6 (Task 9), §7 (Task 7-8, 10), §8 (Task 11), §9 (тесты в каждой task), §10 фазы 0/1/3/4 (фаза 2 — фронт, отдельный план).
- Заведомо проверяемые допущения помечены «Примечание» (форма ответа POST-эндпоинтов, tip-типы pgh_obj_id) — исполнитель сверяет с реальным кодом, тесты это ловят.
- manage.py-обёртка контекста для management-команд НЕ делается (v1, YAGNI): события команд остаются без контекста и не видны в ленте; захват данных при этом полный.
