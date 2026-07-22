# Привязка ученика к реальной учётке менеджера — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить свободный текст `Student.pm` на реальную связь `Student.manager → Account` (редактирование — только admin/superadmin), и сделать её единственным источником правды для `RenewalDeal.assignee` во всех сделках ученика (включая закрытые).

**Architecture:** Один Foreign Key на модели `Student` + новый узкий endpoint `PATCH /api/admin/students/:id/manager` (`IsAdminOrSuperAdmin`), который атомарно меняет `student.manager` и `bulk .update()`-ит `assignee` всех `RenewalDeal` ученика. `RenewalDeal.assignee` перестаёт быть независимо редактируемым полем — `engine.ensure_deal` при создании нового цикла берёт менеджера напрямую со `Student`, а `DealPatchSerializer` теряет `assignee_id`.

**Tech Stack:** Django 5 / DRF, PostgreSQL (managed=True модели), django-pghistory (журнал изменений через DB-триггеры), React 19 + TanStack Query v5 (admin SPA).

**Дизайн:** `docs/superpowers/specs/2026-07-22-student-manager-account-link-design.md`. Два отступления от документа, найденные при подготовке плана (обоснование — в тексте задач ниже):
- Пикер менеджера на фронте — `SelectInput` (готовый компонент), а не `Combobox`: в этом же кодовом месте (`RenewalDrawer.tsx`, поле «Ответственный») тот же паттерн «выбрать один account из короткого списка staff-ролей» уже реализован через `SelectInput` — используем ту же связку, а не вводим новый компонент для идентичной задачи.
- Кандидатов на менеджера отдаёт уже существующий `GET /api/admin/renewals/assignees` (и хук `useRenewalAssignees()`) — отдельный read-endpoint не нужен, критерий (`role in manager/admin/superadmin`, `is_active=True`) там уже ровно тот, что нужен.

---

### Task 1: `Student.pm` → `Student.manager` (модель, репозиторий, сериализаторы, миграция, все внешние потребители)

Это самая большая задача плана — единственная, где модель и все её потребители обязаны смениться атомарно (одним коммитом): как только `pm` пропадает из модели, любой код, ссылающийся на него через ORM (`F('student__pm')`), падает с `FieldError` независимо от состояния миграции БД. Разбивать эту задачу на части нельзя — тесты будут красными между частями.

**Files:**
- Modify: `journal_django/apps/students/models.py:39` (поле `pm` → `manager`)
- Modify: `journal_django/apps/students/repository.py` (фильтр `pm`, `create_student`, `update_student`, `list_students`, `get_student`)
- Modify: `journal_django/apps/students/serializers.py` (убрать `pm` из трёх сериализаторов, добавить `manager_id`/`manager_name` в Read)
- Modify: `journal_django/apps/teacher_spa/repository.py:95` (`pm=F('student__pm')` → `pm=F('student__manager__full_name')`)
- Modify: `journal_django/apps/sync/backfills/students.py` (убрать `pm` из парсинга Sheets-строки и из raw SQL upsert)
- Modify: `journal_django/apps/changelog/summary.py:181-218` (`FIELD_RU`: убрать `'pm'`, добавить `'manager_id'`, `'assignee_id'`)
- Modify: `journal_django/apps/students/tests/test_students_repository.py`
- Create: `journal_django/apps/students/migrations/0012_student_manager_fk.py` (через `makemigrations`, не руками)
- Test: `journal_django/apps/students/tests/test_students_repository.py`, `journal_django/apps/teacher_spa/tests/test_teacher_spa_repository.py` (не должен сломаться), `journal_django/apps/sync/tests/test_backfill_students.py` (не должен сломаться)

- [ ] **Step 1: Обновить тест репозитория (пока будет падать — модель ещё не менялась)**

В `journal_django/apps/students/tests/test_students_repository.py` в `_make_student_data()` (строка 51) удалить строку `'pm': None,` — этот ключ больше не нужен в данных на вход `create_student`/`update_student`.

В `test_existing_has_required_fields` (строка 144-153) заменить:
```python
    def test_existing_has_required_fields(self):
        data = _make_student_data(full_name='__test_get_fields__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            result = repository.get_student(sid)
            for field in ['id', 'full_name', 'enrollment_status', 'created_at']:
                assert field in result
        finally:
            _cleanup_student(sid)
```
на:
```python
    def test_existing_has_required_fields(self):
        data = _make_student_data(full_name='__test_get_fields__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            result = repository.get_student(sid)
            for field in ['id', 'full_name', 'enrollment_status', 'created_at', 'manager_id', 'manager_name']:
                assert field in result
        finally:
            _cleanup_student(sid)

    def test_manager_null_by_default(self):
        data = _make_student_data(full_name='__test_get_manager_default__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            result = repository.get_student(sid)
            assert result['manager_id'] is None
            assert result['manager_name'] is None
        finally:
            _cleanup_student(sid)
```

Добавить в конец класса `TestListStudents` (после `test_sort_by_id_asc`, строка 117) новый тест фильтра — вместо старого текстового поиска по `pm` теперь точный фильтр по `manager_id`:
```python
    def test_filter_by_manager_id_no_match(self):
        """Несуществующий manager_id → пустой список (не падает на приведении типа)."""
        result = repository.list_students(filters={'manager_id': '999999999'})
        assert result['rows'] == []
```

- [ ] **Step 2: Убедиться, что тест падает по ожидаемой причине**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_students_repository.py -k "manager" -v`
Expected: FAIL — `KeyError: 'manager_id'` (репозиторий ещё не отдаёт это поле) или `AttributeError`/`FieldError` в зависимости от того, что выполнится первым. Главное — падение из-за отсутствия `manager`, а не из-за опечатки.

- [ ] **Step 3: Модель — заменить `pm` на `manager`**

В `journal_django/apps/students/models.py` заменить строку 39:
```python
    pm = models.TextField(null=True, blank=True)
```
на:
```python
    manager = models.ForeignKey(
        'accounts.Account', on_delete=models.SET_NULL, null=True, blank=True,
        db_column='manager_id', related_name='managed_students',
    )
```

- [ ] **Step 4: Репозиторий — фильтр, create, update, list, get**

В `journal_django/apps/students/repository.py` добавить импорт `F` в шапку (строка 14, рядом с `Now`):
```python
from django.db.models import F
from django.db.models.functions import Now
```

Заменить блок фильтра `pm` (строки 71-73):
```python
    pm = filters.get('pm')
    if pm not in (None, ''):
        qs = qs.filter(pm__icontains=str(pm))
```
на:
```python
    manager_id = filters.get('manager_id')
    if manager_id not in (None, ''):
        qs = qs.filter(manager_id=int(manager_id))
```

В `list_students()` заменить (строка 114):
```python
    rows = dictrows(ordered[offset:offset + page_size].values())
```
на:
```python
    rows = dictrows(ordered[offset:offset + page_size].values(
        'id', 'full_name', 'birth_date', 'platform_id', 'bitrix24_link',
        'parent1_name', 'parent1_phone', 'parent1_email',
        'parent2_name', 'parent2_phone', 'parent2_email',
        'first_purchase_date', 'age', 'manager_id',
        'enrollment_status', 'frozen_from', 'frozen_until', 'created_at',
        manager_name=F('manager__full_name'),
    ))
```
(`.values()` без аргументов «все поля» несовместимо с именованными алиасами через `F()` — Django требует явный список полей, если добавляется хотя бы один kwargs-алиас.)

В `get_student()` заменить (строка 126):
```python
def get_student(student_id: int) -> Optional[dict]:
    """Возвращает одного ученика по id или None (SELECT * FROM students WHERE id=%s)."""
    return dictrow(Student.objects.filter(id=student_id).values())
```
на:
```python
def get_student(student_id: int) -> Optional[dict]:
    """Возвращает одного ученика по id или None."""
    return dictrow(Student.objects.filter(id=student_id).values(
        'id', 'full_name', 'birth_date', 'platform_id', 'bitrix24_link',
        'parent1_name', 'parent1_phone', 'parent1_email',
        'parent2_name', 'parent2_phone', 'parent2_email',
        'first_purchase_date', 'age', 'manager_id',
        'enrollment_status', 'frozen_from', 'frozen_until', 'created_at',
        manager_name=F('manager__full_name'),
    ))
```

В `create_student()` удалить строку (текущая строка 149):
```python
        pm=data.get('pm') or None,
```
(`manager` сюда не добавляем — он не назначается через общий create/update, только через новый endpoint из Task 3.)

В `update_student()` удалить блок (текущие строки 194-195):
```python
    if data.get('pm'):
        obj.pm = data['pm']
```

- [ ] **Step 5: Сериализаторы — убрать `pm`, добавить `manager_id`/`manager_name` в Read**

В `journal_django/apps/students/serializers.py`:

Удалить строку `pm = serializers.CharField(allow_null=True, allow_blank=True)` из `StudentReadSerializer` (строка 43), заменив на:
```python
    manager_id = serializers.IntegerField(allow_null=True)
    manager_name = serializers.CharField(allow_null=True, allow_blank=True)
```

Удалить строку `pm = serializers.CharField(allow_null=True, allow_blank=True, required=False)` из `StudentWriteSerializer` (строка 70) — без замены (менеджер не назначается при создании ученика).

Удалить такую же строку из `StudentUpdateSerializer` (строка 110) — без замены (менеджер не редактируется через общий PATCH).

- [ ] **Step 6: Собрать миграцию (не писать руками — `makemigrations` сам построит и pghistory-триггеры)**

Run: `cd journal_django && .venv/Scripts/python.exe manage.py makemigrations students --name student_manager_fk`

Открыть сгенерированный файл `journal_django/apps/students/migrations/0012_student_manager_fk.py` и убедиться, что в нём есть:
- `migrations.RemoveField('student', 'pm')`
- `migrations.AddField('student', 'manager', models.ForeignKey(..., to='accounts.account', null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, db_column='manager_id', related_name='managed_students'))`
- Аналогичные `RemoveField`/`AddField` на модели `StudentEvent` (pghistory shadow-таблица) — те же два поля
- Пересборка `pgtrigger`-триггеров `insert_insert`/`update_update`/`delete_delete` на таблице `students`, где в SQL-функции колонка `"pm"` заменена на `"manager_id"`

Если чего-то из этого нет — не продолжать: значит, `makemigrations` не увидел изменение так, как ожидалось (например, забыт `db_column`). В этом случае перепроверить `models.py` прежде чем мигрировать.

- [ ] **Step 7: Применить миграцию к dev- и test-БД**

Run: `cd journal_django && .venv/Scripts/python.exe manage.py migrate students`
Run: `cd journal_django && DJANGO_SETTINGS_MODULE=config.settings.test .venv/Scripts/python.exe manage.py migrate students`

- [ ] **Step 8: Тест репозитория должен зазеленеть**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_students_repository.py -v`
Expected: PASS (весь файл).

- [ ] **Step 9: Починить `teacher_spa` — источник данных для поля `pm` в ответе меняется, ключ ответа остаётся прежним**

В `journal_django/apps/teacher_spa/repository.py:95` заменить:
```python
            pm=F('student__pm'),
```
на:
```python
            pm=F('student__manager__full_name'),
```
(JSON-ключ `pm` для teacher-фронта остаётся неизменным — меняется только откуда берётся значение; teacher-src ничего не знает про менеджерский FK и трогать его не нужно.)

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_teacher_spa_repository.py apps/teacher_spa/tests/test_teacher_spa_api.py -v`
Expected: PASS — тест `test_group_fields` проверяет только наличие ключа `'pm'`, не его происхождение.

- [ ] **Step 10: Починить Sheets-backfill (`apps/sync/backfills/students.py`) — иначе `test_run_inserts_student_and_membership` упадёт на `column "pm" does not exist`**

В `journal_django/apps/sync/backfills/students.py`:

Удалить строку 74 из `extract_students_and_memberships`:
```python
                'pm': cell(row, 9) or None,
```

В `run()` заменить SQL-блок (строки 118-157) — убрать `pm` из списка колонок INSERT, из `SET`, из `WHERE ... IS DISTINCT FROM` и из params-словаря:
```python
            cur.execute(
                """
                INSERT INTO students
                    (full_name, age, birth_date, parent1_phone, platform_id,
                     parent1_name, first_purchase_date, enrollment_status,
                     frozen_from, frozen_until)
                VALUES (%(full_name)s, %(age)s, %(birth_date)s, %(phone)s,
                        %(platform)s, %(parent)s, %(first_purchase)s, %(status)s,
                        %(frozen_from)s, %(frozen_until)s)
                ON CONFLICT (full_name) DO UPDATE SET
                    age                 = EXCLUDED.age,
                    birth_date          = EXCLUDED.birth_date,
                    parent1_phone       = EXCLUDED.parent1_phone,
                    platform_id         = EXCLUDED.platform_id,
                    parent1_name        = EXCLUDED.parent1_name,
                    first_purchase_date = EXCLUDED.first_purchase_date,
                    enrollment_status   = EXCLUDED.enrollment_status,
                    frozen_from         = EXCLUDED.frozen_from,
                    frozen_until        = EXCLUDED.frozen_until
                WHERE students.age IS DISTINCT FROM EXCLUDED.age
                   OR students.birth_date          IS DISTINCT FROM EXCLUDED.birth_date
                   OR students.parent1_phone       IS DISTINCT FROM EXCLUDED.parent1_phone
                   OR students.platform_id         IS DISTINCT FROM EXCLUDED.platform_id
                   OR students.parent1_name        IS DISTINCT FROM EXCLUDED.parent1_name
                   OR students.first_purchase_date IS DISTINCT FROM EXCLUDED.first_purchase_date
                   OR students.enrollment_status   IS DISTINCT FROM EXCLUDED.enrollment_status
                   OR students.frozen_from         IS DISTINCT FROM EXCLUDED.frozen_from
                   OR students.frozen_until        IS DISTINCT FROM EXCLUDED.frozen_until
                RETURNING (xmax = 0) AS inserted
                """,
                {
                    'full_name': s['full_name'], 'age': s['age'],
                    'birth_date': s['birth_date'], 'phone': s['parent1_phone'],
                    'platform': s['platform_id'], 'parent': s['parent1_name'],
                    'first_purchase': s['first_purchase_date'], 'status': s['enrollment_status'],
                    'frozen_from': s['frozen_from'], 'frozen_until': s['frozen_until'],
                },
            )
```

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/sync/tests/test_backfill_students.py -v`
Expected: PASS (включая `test_run_inserts_student_and_membership`, который реально бьёт по БД).

- [ ] **Step 11: Обновить русские подписи полей в журнале изменений**

В `journal_django/apps/changelog/summary.py` в словаре `FIELD_RU` (строка 191) заменить:
```python
    'pm': 'ПМ', 'platform_id': 'ID платформы',
```
на:
```python
    'platform_id': 'ID платформы', 'manager_id': 'менеджер', 'assignee_id': 'ответственный менеджер',
```

- [ ] **Step 12: Полный прогон всех задетых тестовых модулей**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students apps/teacher_spa apps/sync apps/changelog -q`
Expected: PASS, 0 failed.

- [ ] **Step 13: Commit**

```bash
git add journal_django/apps/students/models.py journal_django/apps/students/repository.py journal_django/apps/students/serializers.py journal_django/apps/students/migrations/0012_student_manager_fk.py journal_django/apps/students/tests/test_students_repository.py journal_django/apps/teacher_spa/repository.py journal_django/apps/sync/backfills/students.py journal_django/apps/changelog/summary.py
git commit -m "feat(students): replace free-text pm with Student.manager FK to Account"
```

---

### Task 2: Сервис `set_student_manager` — смена менеджера + жёсткая синхронизация со сделками

**Files:**
- Modify: `journal_django/apps/students/services.py`
- Test: `journal_django/apps/students/tests/test_manager_service.py` (создать)

- [ ] **Step 1: Написать падающий тест сервиса**

Create `journal_django/apps/students/tests/test_manager_service.py`:
```python
"""Тесты services.set_student_manager: валидация кандидата + синхронизация RenewalDeal.assignee."""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth.hashers import make_password
from django.db import connection

from apps.accounts.models import Account
from apps.renewals import engine
from apps.renewals.models import RenewalDeal
from apps.students import services


def _make_account(role: str, is_active: bool = True) -> int:
    email = f'__test_manager_svc__{uuid.uuid4().hex[:8]}@test.local'
    pw = make_password('testpass_sentinel')
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO accounts "
            "(email, password, role, is_active, is_staff, is_superuser, "
            "first_name, last_name, full_name, token_version, date_joined) "
            "VALUES (%s, %s, %s, %s, false, false, '', '', %s, 0, NOW()) RETURNING id",
            [email, pw, role, is_active, f'__Test Manager {role}__'],
        )
        return cur.fetchone()[0]


def _make_student() -> int:
    name = f'__test_manager_svc_student__{uuid.uuid4().hex[:8]}'
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status, created_at) "
            "VALUES (%s, 'enrolled', now()) RETURNING id", [name])
        return cur.fetchone()[0]


def _cleanup(student_id: int, account_ids: list[int]) -> None:
    with connection.cursor() as cur:
        cur.execute(
            'DELETE FROM renewal_activity WHERE deal_id IN '
            '(SELECT id FROM renewal_deal WHERE student_id = %s)', [student_id])
        cur.execute('DELETE FROM renewal_deal WHERE student_id = %s', [student_id])
        cur.execute('DELETE FROM students WHERE id = %s', [student_id])
        for acc_id in account_ids:
            cur.execute('DELETE FROM accounts WHERE id = %s', [acc_id])


@pytest.mark.django_db
def test_set_student_manager_updates_student():
    sid = _make_student()
    manager_id = _make_account('manager')
    try:
        result = services.set_student_manager(sid, manager_id)
        assert result is not None
        assert result['manager_id'] == manager_id
    finally:
        _cleanup(sid, [manager_id])


@pytest.mark.django_db
def test_set_student_manager_rejects_teacher_role():
    sid = _make_student()
    teacher_acc = _make_account('teacher')
    try:
        with pytest.raises(ValueError):
            services.set_student_manager(sid, teacher_acc)
    finally:
        _cleanup(sid, [teacher_acc])


@pytest.mark.django_db
def test_set_student_manager_rejects_inactive_account():
    sid = _make_student()
    manager_id = _make_account('manager', is_active=False)
    try:
        with pytest.raises(ValueError):
            services.set_student_manager(sid, manager_id)
    finally:
        _cleanup(sid, [manager_id])


@pytest.mark.django_db
def test_set_student_manager_returns_none_for_missing_student():
    manager_id = _make_account('manager')
    try:
        assert services.set_student_manager(999_999_999, manager_id) is None
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM accounts WHERE id = %s', [manager_id])


@pytest.mark.django_db
def test_set_student_manager_syncs_all_deals_open_and_closed():
    """Жёсткая синхронизация: assignee меняется во ВСЕХ сделках ученика,
    включая уже закрытую (won/lost), а не только в открытой."""
    sid = _make_student()
    old_manager = _make_account('manager')
    new_manager = _make_account('admin')
    try:
        open_deal = engine.ensure_deal(sid, cycle_no=1)
        closed_deal = engine.ensure_deal(sid, cycle_no=2)
        RenewalDeal.objects.filter(id__in=[open_deal.id, closed_deal.id]).update(assignee_id=old_manager)
        closed_deal.outcome_at = closed_deal.stage_entered_at
        closed_deal.save(update_fields=['outcome_at'])

        services.set_student_manager(sid, new_manager)

        open_deal.refresh_from_db()
        closed_deal.refresh_from_db()
        assert open_deal.assignee_id == new_manager
        assert closed_deal.assignee_id == new_manager
    finally:
        _cleanup(sid, [old_manager, new_manager])


@pytest.mark.django_db
def test_set_student_manager_null_clears_assignee():
    sid = _make_student()
    manager_id = _make_account('manager')
    try:
        deal = engine.ensure_deal(sid, cycle_no=1)
        RenewalDeal.objects.filter(id=deal.id).update(assignee_id=manager_id)

        services.set_student_manager(sid, None)

        deal.refresh_from_db()
        assert deal.assignee_id is None
    finally:
        _cleanup(sid, [manager_id])
```

- [ ] **Step 2: Убедиться, что тест падает (функции ещё нет)**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_manager_service.py -v`
Expected: FAIL — `AttributeError: module 'apps.students.services' has no attribute 'set_student_manager'`.

- [ ] **Step 3: Реализовать сервис**

В `journal_django/apps/students/services.py` добавить в конец файла:
```python
@transaction.atomic
def set_student_manager(student_id: int, manager_id: Optional[int], *, actor=None) -> Optional[dict]:
    """
    Сменить ответственного менеджера ученика и синхронно переписать assignee
    ВСЕХ сделок продления этого ученика (открытых и закрытых) — единый источник
    правды вместо независимого назначения на каждой сделке. Возвращает None,
    если ученика нет; ValueError, если manager_id указывает на неподходящую
    учётку (не manager/admin/superadmin или неактивна).
    """
    from apps.accounts.models import Account
    from apps.renewals.models import RenewalDeal
    from apps.students.models import Student

    student = Student.objects.filter(id=student_id).first()
    if student is None:
        return None

    if manager_id is not None:
        # Тот же критерий, что apps.renewals.services.list_assignees() —
        # кандидат в ответственные по сделкам продления.
        is_eligible = Account.objects.filter(
            id=manager_id, role__in=['manager', 'admin', 'superadmin'], is_active=True,
        ).exists()
        if not is_eligible:
            raise ValueError('manager account not found or not eligible')

    student.manager_id = manager_id
    student.save(update_fields=['manager'])
    RenewalDeal.objects.filter(student_id=student_id).update(assignee_id=manager_id)

    return repository.get_student(student_id)
```

- [ ] **Step 4: Тесты должны пройти**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_manager_service.py -v`
Expected: PASS, все 6 тестов.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/students/services.py journal_django/apps/students/tests/test_manager_service.py
git commit -m "feat(students): add set_student_manager service with hard sync into renewal deals"
```

---

### Task 3: Endpoint `PATCH /api/admin/students/:id/manager` (admin/superadmin only)

**Files:**
- Modify: `journal_django/apps/students/serializers.py` (новый `StudentManagerSerializer`)
- Modify: `journal_django/apps/students/views.py` (новый `StudentManagerView`)
- Modify: `journal_django/apps/students/urls.py`
- Test: `journal_django/apps/students/tests/test_manager_api.py` (создать)

- [ ] **Step 1: Написать падающий API-тест**

Create `journal_django/apps/students/tests/test_manager_api.py`:
```python
"""API-тесты /api/admin/students/:id/manager — доступ только admin/superadmin."""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth.hashers import make_password
from django.db import connection

BASE_URL = '/api/admin/students'


def _create_student() -> int:
    name = f'__test_manager_api_student__{uuid.uuid4().hex[:8]}'
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status, created_at) "
            "VALUES (%s, 'enrolled', NOW()) RETURNING id", [name])
        return cur.fetchone()[0]


def _create_account(role: str, is_active: bool = True) -> int:
    email = f'__test_manager_api_acc__{uuid.uuid4().hex[:8]}@test.local'
    pw = make_password('testpass_sentinel')
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO accounts "
            "(email, password, role, is_active, is_staff, is_superuser, "
            "first_name, last_name, token_version, date_joined) "
            "VALUES (%s, %s, %s, %s, false, false, '', '', 0, NOW()) RETURNING id",
            [email, pw, role, is_active],
        )
        return cur.fetchone()[0]


def _cleanup_student(student_id: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM students WHERE id = %s', [student_id])


def _cleanup_account(acc_id: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM accounts WHERE id = %s', [acc_id])


@pytest.mark.django_db
def test_manager_update_forbidden_for_manager_role(manager_client):
    sid = _create_student()
    acc_id = _create_account('manager')
    try:
        resp = manager_client.patch(f'{BASE_URL}/{sid}/manager', {'manager_id': acc_id}, format='json')
        assert resp.status_code == 403
    finally:
        _cleanup_student(sid)
        _cleanup_account(acc_id)


@pytest.mark.django_db
def test_manager_update_allowed_for_admin(admin_client):
    sid = _create_student()
    acc_id = _create_account('manager')
    try:
        resp = admin_client.patch(f'{BASE_URL}/{sid}/manager', {'manager_id': acc_id}, format='json')
        assert resp.status_code == 200
        assert resp.json()['manager_id'] == acc_id
    finally:
        _cleanup_student(sid)
        _cleanup_account(acc_id)


@pytest.mark.django_db
def test_manager_update_allowed_for_superadmin(superadmin_client):
    sid = _create_student()
    acc_id = _create_account('admin')
    try:
        resp = superadmin_client.patch(f'{BASE_URL}/{sid}/manager', {'manager_id': acc_id}, format='json')
        assert resp.status_code == 200
    finally:
        _cleanup_student(sid)
        _cleanup_account(acc_id)


@pytest.mark.django_db
def test_manager_update_rejects_teacher_account(admin_client):
    sid = _create_student()
    acc_id = _create_account('teacher')
    try:
        resp = admin_client.patch(f'{BASE_URL}/{sid}/manager', {'manager_id': acc_id}, format='json')
        assert resp.status_code == 400
    finally:
        _cleanup_student(sid)
        _cleanup_account(acc_id)


@pytest.mark.django_db
def test_manager_update_null_clears_manager(admin_client):
    sid = _create_student()
    acc_id = _create_account('manager')
    try:
        admin_client.patch(f'{BASE_URL}/{sid}/manager', {'manager_id': acc_id}, format='json')
        resp = admin_client.patch(f'{BASE_URL}/{sid}/manager', {'manager_id': None}, format='json')
        assert resp.status_code == 200
        assert resp.json()['manager_id'] is None
    finally:
        _cleanup_student(sid)
        _cleanup_account(acc_id)


@pytest.mark.django_db
def test_manager_update_404_for_missing_student(admin_client):
    acc_id = _create_account('manager')
    try:
        resp = admin_client.patch(f'{BASE_URL}/999999999/manager', {'manager_id': acc_id}, format='json')
        assert resp.status_code == 404
    finally:
        _cleanup_account(acc_id)


@pytest.mark.django_db
def test_manager_field_not_writable_via_general_patch(admin_client):
    """Общий PATCH /students/:id молча игнорирует manager_id — поле не объявлено
    в StudentUpdateSerializer, даже когда его шлёт admin (не только manager)."""
    sid = _create_student()
    acc_id = _create_account('manager')
    try:
        resp = admin_client.patch(f'{BASE_URL}/{sid}', {'manager_id': acc_id, 'age': 10}, format='json')
        assert resp.status_code == 200
        assert resp.json()['manager_id'] is None
        assert resp.json()['age'] == 10
    finally:
        _cleanup_student(sid)
        _cleanup_account(acc_id)
```

- [ ] **Step 2: Убедиться, что тесты падают (endpoint не существует)**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_manager_api.py -v`
Expected: 6 из 7 тестов FAIL с 404 (запросы на `/students/:id/manager` — роута ещё нет). `test_manager_field_not_writable_via_general_patch` уже PASS на этом шаге — он бьёт по существующему общему `PATCH /students/:id`, и `StudentUpdateSerializer` уже не принимает `manager_id` начиная с Task 1.

- [ ] **Step 3: Сериализатор**

В `journal_django/apps/students/serializers.py` добавить в конец файла:
```python
class StudentManagerSerializer(serializers.Serializer):
    """Ввод PATCH /students/:id/manager. null — снять ответственного."""
    manager_id = serializers.IntegerField(allow_null=True)
```

- [ ] **Step 4: View**

В `journal_django/apps/students/views.py` добавить импорт `StudentManagerSerializer` к существующему блоку импорта из `apps.students.serializers` (строки 33-39) и добавить новый класс в конец файла:
```python
class StudentManagerView(APIView):
    """PATCH /api/admin/students/:id/manager — сменить ответственного менеджера.

    В отличие от общего PATCH /students/:id (IsManagerOrAdmin, редактирует
    любой manager/admin/superadmin), это поле доступно только admin/superadmin:
    смена ответственного синхронно переписывает assignee ВСЕХ сделок продления
    ученика (services.set_student_manager)."""

    permission_classes = [IsAdminOrSuperAdmin]

    def patch(self, request: Request, pk: int) -> Response:
        ser = StudentManagerSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            updated = services.set_student_manager(
                pk, ser.validated_data['manager_id'], actor=request.user)
        except ValueError as exc:
            raise ValidationError({'error': str(exc)})
        if updated is None:
            raise NotFound({'error': 'Not found'})
        return Response(updated)
```

- [ ] **Step 5: URL**

В `journal_django/apps/students/urls.py` добавить `StudentManagerView` в импорт (строки 11-22) и новый путь в `urlpatterns` сразу после detail-роута:
```python
    path('/<int:pk>/manager', StudentManagerView.as_view(), name='students-manager'),
```
(разместить после `path('/<int:pk>', StudentDetailView.as_view(), ...)`, до `/stats` — порядок среди путей с литеральным суффиксом после `<int:pk>` не важен для Django-роутинга, но держим рядом с detail для читаемости.)

- [ ] **Step 6: Тесты должны пройти**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_manager_api.py -v`
Expected: PASS, все 7 тестов.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/students/serializers.py journal_django/apps/students/views.py journal_django/apps/students/urls.py journal_django/apps/students/tests/test_manager_api.py
git commit -m "feat(students): add PATCH /students/:id/manager endpoint (admin/superadmin only)"
```

---

### Task 4: Changelog — метка операции для нового endpoint

**Files:**
- Modify: `journal_django/apps/changelog/labels.py`
- Modify: `journal_django/frontend/admin-src/src/lib/labels.ts`
- Test: `journal_django/apps/changelog/tests/test_registry.py`

- [ ] **Step 1: Написать падающий тест на resolve_operation**

В `journal_django/apps/changelog/tests/test_registry.py` добавить рядом с существующими assert'ами на `resolve_operation` (после строки 44, `test_resolve_operation ... 'student.resume'`):
```python
    assert labels.resolve_operation('PATCH', '/api/admin/students/7/manager') == 'student.manager_update'
```

- [ ] **Step 2: Убедиться, что падает**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/changelog/tests/test_registry.py -k resolve_operation -v`
Expected: FAIL — `assert 'student.update' == 'student.manager_update'` (правило ещё не заведено, но URL совпадает с более общим `student.update`, т.к. `/manager` — не `$`-конец... на самом деле URL `/api/admin/students/7/manager` НЕ совпадает с `^/api/admin/students/\d+$` из-за `$` сразу после `\d+`, так что реально вернётся `'other'` — фиксируем это как ожидаемый результат падения.)

- [ ] **Step 3: Добавить правило**

В `journal_django/apps/changelog/labels.py` добавить новую строку в `RULES` сразу после строки со `student.create` (строка 36) и перед строкой `student.update` (строка 37):
```python
    ('PATCH', re.compile(r'^/api/admin/students/\d+/manager$'), 'student.manager_update'),
```

- [ ] **Step 4: Тест должен пройти**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/changelog/tests/test_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Добавить русскую подпись операции на фронте**

В `journal_django/frontend/admin-src/src/lib/labels.ts` добавить строку рядом с существующими `student.*` (после строки 65, `'student.update'`):
```typescript
  'student.manager_update':        'Смена менеджера ученика',
```

- [ ] **Step 6: Полный прогон changelog-тестов**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/changelog -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/changelog/labels.py journal_django/apps/changelog/tests/test_registry.py journal_django/frontend/admin-src/src/lib/labels.ts
git commit -m "feat(changelog): label PATCH /students/:id/manager as student.manager_update"
```

---

### Task 5: `engine.ensure_deal` — единственный источник assignee — `Student.manager`

**Files:**
- Modify: `journal_django/apps/renewals/engine.py:81-95`
- Modify: `journal_django/apps/renewals/repository.py:151`
- Test: `journal_django/apps/renewals/tests/test_engine.py`

- [ ] **Step 1: Написать падающий тест**

В `journal_django/apps/renewals/tests/test_engine.py` добавить (после `test_ensure_deal_is_idempotent`, строка ~36):
```python
@pytest.mark.django_db
def test_ensure_deal_picks_up_student_manager(make_student):
    """Новая сделка сразу получает assignee = текущий менеджер ученика (без
    передачи assignee_id вызывающим кодом — единый источник правды)."""
    from apps.students import services as student_services
    from apps.accounts.models import Account
    from django.contrib.auth.hashers import make_password
    import uuid

    sid = make_student()
    email = f'__test_engine_manager__{uuid.uuid4().hex[:8]}@test.local'
    manager = Account.objects.create(
        email=email, password=make_password('x'), role='manager',
        is_active=True, full_name='__Test Engine Manager__',
    )
    student_services.set_student_manager(sid, manager.id)

    deal = engine.ensure_deal(sid, cycle_no=1)
    assert deal.assignee_id == manager.id
```

- [ ] **Step 2: Убедиться, что падает**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/renewals/tests/test_engine.py -k picks_up_student_manager -v`
Expected: FAIL — `assert None == manager.id` (`ensure_deal` пока не читает `student.manager_id`).

- [ ] **Step 3: Реализовать в engine.py**

В `journal_django/apps/renewals/engine.py` заменить (строки 81-95):
```python
@transaction.atomic
def ensure_deal(student_id: int, cycle_no: int,
                assignee_id: Optional[int] = None) -> RenewalDeal:
    """Создать (или вернуть существующую) сделку цикла ученика. Идемпотентно по UNIQUE."""
    pipeline = _default_pipeline()
    progress_stages = _progress_stages(pipeline)
    progress = progress_stages[0] if progress_stages else _stage(pipeline, kind='progress')
    deal, created = RenewalDeal.objects.get_or_create(
        student_id=student_id, cycle_no=cycle_no,
        defaults={'pipeline': pipeline, 'stage': progress, 'assignee_id': assignee_id},
    )
    if created:
        RenewalActivity.objects.create(
            deal=deal, kind='system', to_stage=progress, body='Сделка создана')
    return deal
```
на:
```python
@transaction.atomic
def ensure_deal(student_id: int, cycle_no: int) -> RenewalDeal:
    """
    Создать (или вернуть существующую) сделку цикла ученика. Идемпотентно по UNIQUE.

    assignee новой сделки — ТЕКУЩИЙ Student.manager (единый источник правды,
    см. apps.students.services.set_student_manager) — не принимается параметром,
    чтобы не было двух путей его установки.
    """
    from apps.students.models import Student

    pipeline = _default_pipeline()
    progress_stages = _progress_stages(pipeline)
    progress = progress_stages[0] if progress_stages else _stage(pipeline, kind='progress')
    manager_id = (Student.objects.filter(id=student_id)
                  .values_list('manager_id', flat=True).first())
    deal, created = RenewalDeal.objects.get_or_create(
        student_id=student_id, cycle_no=cycle_no,
        defaults={'pipeline': pipeline, 'stage': progress, 'assignee_id': manager_id},
    )
    if created:
        RenewalActivity.objects.create(
            deal=deal, kind='system', to_stage=progress, body='Сделка создана')
    return deal
```

- [ ] **Step 4: Обновить единственный продовый вызов с `assignee_id=`**

В `journal_django/apps/renewals/repository.py:151` заменить:
```python
            engine.ensure_deal(deal.student_id, next_cycle, assignee_id=deal.assignee_id)
```
на:
```python
            engine.ensure_deal(deal.student_id, next_cycle)
```
(старый `deal.assignee_id` в этой точке и так уже равен `student.manager_id` — синхронизация поддерживается `set_student_manager`, но читать напрямую со `Student` надёжнее, чем полагаться на то, что инвариант нигде не нарушен исторически.)

- [ ] **Step 5: Тест должен пройти + весь модуль renewals зелёный**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/renewals -q`
Expected: PASS, 0 failed (сигнатура `ensure_deal` больше нигде в проде не вызывалась с `assignee_id=`, кроме только что убранного места — тесты его не передавали вовсе).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/renewals/engine.py journal_django/apps/renewals/repository.py journal_django/apps/renewals/tests/test_engine.py
git commit -m "refactor(renewals): ensure_deal reads assignee from Student.manager, drop assignee_id param"
```

---

### Task 6: Убрать прямой PATCH `assignee_id` на сделке

**Files:**
- Modify: `journal_django/apps/renewals/serializers.py:17-19`
- Modify: `journal_django/apps/renewals/repository.py:159-171`
- Test: `journal_django/apps/renewals/tests/test_api_write.py`

- [ ] **Step 1: Написать падающий тест**

В `journal_django/apps/renewals/tests/test_api_write.py` добавить (рядом с `test_patch_reason_code`, после строки 200):
```python
@pytest.mark.django_db
def test_patch_ignores_assignee_id(admin_client, make_student, make_direction):
    """assignee_id больше не патчится напрямую на сделке — единственный путь
    смены ответственного теперь через Student.manager (жёсткая синхронизация)."""
    from apps.accounts.models import Account
    from django.contrib.auth.hashers import make_password
    import uuid

    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    email = f'__test_patch_ignore_assignee__{uuid.uuid4().hex[:8]}@test.local'
    acc = Account.objects.create(
        email=email, password=make_password('x'), role='manager', is_active=True)
    resp = admin_client.patch(f'{BASE}/{deal.id}', {'assignee_id': acc.id}, format='json')
    assert resp.status_code == 200
    assert resp.json()['assignee_id'] is None
```

- [ ] **Step 2: Убедиться, что падает**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/renewals/tests/test_api_write.py -k patch_ignores_assignee -v`
Expected: FAIL — `assert acc.id is None` (сейчас `assignee_id` всё ещё принимается и применяется).

- [ ] **Step 3: Убрать поле из сериализатора**

В `journal_django/apps/renewals/serializers.py` заменить (строки 17-19):
```python
class DealPatchSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField(required=False, allow_null=True)
    reason_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
```
на:
```python
class DealPatchSerializer(serializers.Serializer):
    reason_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
```

- [ ] **Step 4: Убрать мёртвый ключ из repository.patch_deal**

В `journal_django/apps/renewals/repository.py` заменить (строка 163):
```python
    for k in ('assignee_id', 'reason_code'):
```
на:
```python
    for k in ('reason_code',):
```

- [ ] **Step 5: Тест должен пройти + весь модуль зелёный**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/renewals -q`
Expected: PASS, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/renewals/serializers.py journal_django/apps/renewals/repository.py journal_django/apps/renewals/tests/test_api_write.py
git commit -m "feat(renewals): remove direct assignee_id patch, manager is set only via Student.manager"
```

---

### Task 7: Фронтенд — карточка ученика (типы, форма, детальная страница, список, права)

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/shared-types.ts:80-99`
- Modify: `journal_django/frontend/admin-src/src/pages/students/StudentFormModal.tsx`
- Modify: `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx`
- Modify: `journal_django/frontend/admin-src/src/pages/students/StudentsListPage.tsx`
- Modify: `journal_django/frontend/admin-src/src/lib/table-settings.ts:39`
- Modify: `journal_django/frontend/admin-src/src/hooks/useStudents.ts`
- Modify: `journal_django/frontend/admin-src/src/lib/permissions.ts`

Ручное тестирование в браузере — обязательный шаг (Step 9), т.к. это UI-изменение (CLAUDE.md: «для UI-изменений — открыть в браузере, проверить golden path и края»).

- [ ] **Step 1: Типы**

В `journal_django/frontend/admin-src/src/lib/shared-types.ts` заменить (строка 94):
```typescript
  pm: string | null;
```
на:
```typescript
  manager_id: ID | null;
  manager_name: string | null;
```

- [ ] **Step 2: Права — новая проверка admin/superadmin**

В `journal_django/frontend/admin-src/src/lib/permissions.ts` добавить в конец файла:
```typescript
export const canWriteStudentManager = isAdminUp; // назначение ответственного менеджера ученику
```

- [ ] **Step 3: Мутация смены менеджера**

В `journal_django/frontend/admin-src/src/hooks/useStudents.ts` добавить в объект, возвращаемый `useStudentMutations()` (после `update`, перед `remove`, строка 118):
```typescript
    setManager: useMutation({
      mutationFn: ({ id, managerId }: { id: number; managerId: number | null }) =>
        api<Student>('PATCH', `/api/admin/students/${id}/manager`, { manager_id: managerId }),
      onSuccess: () => {
        invalidate();
        qc.invalidateQueries({ queryKey: ['renewals'] });
      },
    }),
```

- [ ] **Step 4: Убрать `pm` из формы ученика**

В `journal_django/frontend/admin-src/src/pages/students/StudentFormModal.tsx`:
- Убрать `pm: string;` из `interface FormState` (строка 24)
- Убрать `pm: s?.pm || '',` из `toForm()` (строка 43)
- Убрать `pm: form.pm || null,` из тела `onSubmit` (строка 73)
- Убрать блок:
```tsx
        <Field label="Менеджер (PM)">
          <TextInput value={form.pm} onChange={(e) => set('pm', e.target.value)} />
        </Field>
```
(строки 152-154, внутри секции «Обучение») — без замены, менеджер больше не редактируется в этой форме.

- [ ] **Step 5: Список — колонка и фильтр**

В `journal_django/frontend/admin-src/src/lib/table-settings.ts:39` заменить:
```typescript
    { key: 'pm',                  label: 'ПМ' },
```
на:
```typescript
    { key: 'manager_name',        label: 'Менеджер' },
```

В `journal_django/frontend/admin-src/src/pages/students/StudentsListPage.tsx` заменить колонку (строки 95-101):
```tsx
    {
      key: 'pm',
      label: 'ПМ',
      sortable: false,
      searchable: true,
      cell: (r) => r.pm || '—',
    },
```
на:
```tsx
    {
      key: 'manager_id',
      label: 'Менеджер',
      sortable: false,
      searchable: true,
      searchOptions: (assignees || []).map((a) => ({ value: String(a.id), label: a.full_name })),
      cell: (r) => r.manager_name || '—',
    },
```
и добавить в начало компонента (после строки 22, рядом с остальными хуками) загрузку кандидатов для фильтра:
```typescript
  const { data: assignees } = useRenewalAssignees();
```
с импортом:
```typescript
import { useRenewalAssignees } from '../../hooks/useRenewals';
```
(переиспользуем существующий эндпоинт `/api/admin/renewals/assignees` — тот же список staff-учёток нужен и здесь, заводить отдельный read-endpoint не нужно.)

Фильтр `filter[manager_id]` на бэке уже реализован в Task 1 Step 4 (`repository.py`, точное совпадение по `manager_id`, а не `icontains`).

- [ ] **Step 6: Детальная страница — карточка (read-only) + диалог смены (admin/superadmin)**

В `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx`:

Заменить строку в `fields` (строка 226):
```tsx
    { key: 'pm', label: 'ПМ' },
```
на:
```tsx
    { key: 'manager_name', label: 'Менеджер', cell: (r) => r.manager_name || '—' },
```

Добавить импорты (рядом с существующими, после строки 32):
```typescript
import { canSeeChangelog, canWriteStudentManager, type Role } from '../../lib/permissions';
import { useRenewalAssignees } from '../../hooks/useRenewals';
import { SelectInput } from '../../components/form/SelectInput';
```
(`canSeeChangelog` уже импортирован на строке 32 — просто добавить `canWriteStudentManager` в тот же импорт.)

Заменить импорт `useStudent` (строка 4) на:
```typescript
import { useStudent, useStudentMutations } from '../../hooks/useStudents';
```
(`StudentManagerDialog` ниже вызывает `useStudentMutations()` для мутации `setManager` — сейчас в этом файле импортирован только `useStudent`.)

Добавить новый мини-диалог рядом с `StudentResumeDialog` (после его закрывающей `}` на строке 82, перед `const STUDENT_TABS`):
```tsx
// ── Диалог смены ответственного менеджера — только admin/superadmin.
// Меняет Student.manager И синхронно ВСЕ сделки продления ученика (assignee),
// включая уже закрытые — поэтому явное подтверждение перед сохранением. ──
function StudentManagerDialog({ student, onClose }: { student: Student; onClose: () => void }) {
  const { data: assignees } = useRenewalAssignees();
  const muts = useStudentMutations();
  const showError = useApiError();
  const { toast } = useToast();
  const [managerId, setManagerId] = useState<string>(student.manager_id != null ? String(student.manager_id) : '');

  const handleSave = async () => {
    try {
      await muts.setManager.mutateAsync({
        id: student.id,
        managerId: managerId ? Number(managerId) : null,
      });
      toast('Менеджер обновлён', 'ok');
      onClose();
    } catch (err) {
      showError(err, 'Не удалось сменить менеджера');
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title="Сменить менеджера ученика">
      <div className="status-form">
        <Field label="Менеджер">
          <SelectInput
            value={managerId}
            onChange={(e) => setManagerId(e.target.value)}
            options={[
              { value: '', label: '— не назначен —' },
              ...(assignees || []).map((a) => ({ value: String(a.id), label: a.full_name })),
            ]}
          />
        </Field>
        <div className="status-form__hint">
          Смена менеджера сразу переставит ответственного во всех сделках продления
          этого ученика в разделе «Продления» — включая уже закрытые.
        </div>
        <div className="status-form__footer">
          <button type="button" className="btn-cancel" onClick={onClose}>Отмена</button>
          <button
            type="button"
            className="btn-save"
            onClick={handleSave}
            disabled={muts.setManager.isPending}
          >
            Сохранить
          </button>
        </div>
      </div>
    </Dialog>
  );
}
```

Добавить состояние `managingManager` рядом с остальными (после строки 104, `const [resuming, setResuming] = useState(false);`):
```typescript
  const [managingManager, setManagingManager] = useState(false);
```

Добавить кнопку в `student-hero__actions` (после кнопки «Разморозить», строка 176-180), видимую только admin/superadmin:
```tsx
          {canWriteStudentManager(me?.role as Role) && (
            <button type="button" className="edit-btn" onClick={() => setManagingManager(true)}>
              Сменить менеджера
            </button>
          )}
```

Отрендерить диалог рядом с остальными модалками (после `{resuming && (...)}`, строка 334-336):
```tsx
      {managingManager && (
        <StudentManagerDialog student={student} onClose={() => setManagingManager(false)} />
      )}
```

- [ ] **Step 7: TypeScript-проверка**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: 0 errors.

- [ ] **Step 8: Собрать admin-фронт (для ручной проверки в браузере на Step 9) — не добавлять `admin-dist` в коммит Step 10**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: сборка без ошибок. Собранные файлы в `journal_django/frontend/admin-dist/` — рабочий продукт сборки для локальной проверки, в `git add` на Step 10 не включать (коммит — только исходники `src/`).

- [ ] **Step 9: Ручная проверка в браузере**

Запустить дев-сервер (см. навык `run`, если доступен, либо стандартный способ проекта — `runserver` + фронт через nginx :8080 по памяти проекта). Проверить вручную:
- Под ролью manager: на странице ученика кнопки «Сменить менеджера» нет; в форме редактирования ученика поля «Менеджер (PM)» больше нет.
- Под ролью admin: кнопка «Сменить менеджера» есть, диалог открывается, список кандидатов подгружается, сохранение обновляет карточку и колонку в списке учеников.
- Список учеников: фильтр по колонке «Менеджер» — выпадающий список кандидатов, фильтрует корректно.
- Раздел «Продления»: карточка сделки того же ученика показывает того же ответственного, что выставлен на карточке ученика.

- [ ] **Step 10: Commit**

```bash
git add journal_django/frontend/admin-src/src/lib/shared-types.ts journal_django/frontend/admin-src/src/lib/permissions.ts journal_django/frontend/admin-src/src/hooks/useStudents.ts journal_django/frontend/admin-src/src/pages/students/StudentFormModal.tsx journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx journal_django/frontend/admin-src/src/pages/students/StudentsListPage.tsx journal_django/frontend/admin-src/src/lib/table-settings.ts
git commit -m "feat(admin-spa): replace free-text pm with manager account picker (admin/superadmin only)"
```

---

### Task 8: Фронтенд — карточка сделки в «Продлениях»: «Ответственный» становится read-only

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/renewals/RenewalDrawer.tsx`

- [ ] **Step 1: Заменить редактируемый SelectInput на текст с подсказкой**

В `journal_django/frontend/admin-src/src/pages/renewals/RenewalDrawer.tsx` заменить блок (строки 247-256):
```tsx
                  <Field label="Ответственный">
                    <SelectInput
                      value={deal.assignee_id != null ? String(deal.assignee_id) : ''}
                      onChange={(e) => save({ assignee_id: e.target.value ? Number(e.target.value) : null })}
                      options={[
                        { value: '', label: '— не назначен —' },
                        ...(assignees || []).map((a) => ({ value: String(a.id), label: a.full_name })),
                      ]}
                    />
                  </Field>
```
на:
```tsx
                  <Field label="Ответственный">
                    <div className="renewal-drawer__readonly-value" title="Меняется на странице ученика">
                      {deal.assignee_name || '— не назначен —'}
                    </div>
                  </Field>
```

- [ ] **Step 2: Убрать теперь неиспользуемый импорт/хук, если он больше нигде в файле не нужен**

Проверить, используется ли `useRenewalAssignees`/`assignees` (строка 55) где-то ещё в `RenewalDrawer.tsx`.

Run: `grep -n "assignees" journal_django/frontend/admin-src/src/pages/renewals/RenewalDrawer.tsx`

Если единственное оставшееся использование — только что удалённый блок, убрать из импорта строки 9-11 `useRenewalAssignees` (оставив `useRenewalActivity, useRenewalDeal, useRenewalMutations`) и убрать строку 55 `const { data: assignees } = useRenewalAssignees();`.

- [ ] **Step 3: Добавить минимальный CSS-класс для read-only значения, если в проекте ещё нет аналога**

Run: `grep -n "renewal-drawer__readonly-value\|renewal-drawer__balance-value" journal_django/frontend/admin-src/src/styles/pages/renewals.css`

Если `renewal-drawer__readonly-value` отсутствует, добавить рядом с существующими `.renewal-drawer__*` стилями простое правило, визуально согласованное с остальными полями drawer'а (взять за образец существующий `.renewal-drawer__balance-value` — тот же шрифт/отступы, без интерактивности):
```css
.renewal-drawer__readonly-value {
  padding: 8px 0;
  color: var(--text-primary);
}
```

- [ ] **Step 4: TypeScript-проверка + сборка**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: 0 errors.

- [ ] **Step 5: Ручная проверка в браузере**

Открыть карточку сделки в «Продлениях» — поле «Ответственный» показывает имя менеджера ученика текстом, без возможности редактирования; при смене менеджера на странице ученика (Task 7) значение здесь обновляется после инвалидации `['renewals']`.

- [ ] **Step 6: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/renewals/RenewalDrawer.tsx journal_django/frontend/admin-src/src/styles/pages/renewals.css
git commit -m "feat(admin-spa): make renewal deal assignee read-only, sourced from student manager"
```

---

### Task 9: Финальная проверка всего плана

**Files:** нет новых — только верификация.

- [ ] **Step 1: Полный прогон backend-тестов**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS, 0 failed, 0 errors.

- [ ] **Step 2: `makemigrations --check` чист**

Run: `cd journal_django && .venv/Scripts/python.exe manage.py makemigrations --check --dry-run`
Expected: `No changes detected` (модель и миграции синхронны).

- [ ] **Step 3: TypeScript-проверка всего admin-фронта**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: 0 errors.

- [ ] **Step 4: `git status` — dist-артефакты не приезжают в коммит случайно**

Run: `git status`
Ожидается: staged/committed изменения только в исходниках (models/repository/serializers/views/urls/services/engine, frontend `src/`, миграция, тесты, labels) — без незапланированных изменений в `admin-dist/`/`teacher-dist/`, если сборка (Task 7 Step 8) не является частью обычного рабочего процесса коммитов в этом репозитории.

- [ ] **Step 5: Ручной regression-чеклист (после Task 7/8 уже пройден по частям — здесь сводный повторный прогон одним проходом)**

- Manager-роль: не видит кнопку «Сменить менеджера» на странице ученика; PATCH на `/students/:id/manager` от её имени → 403 (уже покрыто тестом, но стоит воспроизвести вручную через DevTools/браузер один раз).
- Admin-роль: меняет менеджера ученика → карточка сделки в «Продлениях» сразу показывает нового ответственного (включая случай, когда у ученика есть закрытая сделка прошлого цикла — она тоже должна была обновиться).
- Список учеников: колонка «Менеджер» и фильтр по ней работают на реальных данных (не только на синтетических тестовых).
- Журнал изменений: смена менеджера ученика показывает операцию «Смена менеджера ученика», а не «Правка ученика» и не «other».
