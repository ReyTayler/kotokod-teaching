# Перевод ученика между группами одного направления — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать администратору атомарно перевести ученика из одной активной группы в другую группу того же направления, честно сохранив исторический счётчик уроков старой группы и явно показав его на карточке новой группы.

**Architecture:** Backend — новый self-referencing FK `GroupMembership.transferred_from` + сервис `transfer_membership()` (деактивирует старую membership, UPSERT-ит новую тем же паттерном, что и `add_membership`, тем же bulk_create ON CONFLICT). Новый эндпоинт `POST /api/admin/memberships/:id/transfer`. Frontend — кнопка «⇄ Перевести» на карточке membership на странице ученика (`MembershipsBlock`, режим `byStudent`), модалка выбора целевой группы (фильтр по direction_id), плашка истории на карточке новой группы.

**Tech Stack:** Django 5 / DRF (`journal_django/apps/memberships`), pytest-django, React 19 + TanStack Query v5 (`journal_django/frontend/admin-src`).

**Design doc:** [`docs/superpowers/specs/2026-07-13-student-group-transfer-design.md`](../specs/2026-07-13-student-group-transfer-design.md)

---

## Task 1: Модель — поле `transferred_from`

**Files:**
- Modify: `journal_django/apps/memberships/models.py:40-45`

- [ ] **Step 1: Добавить поле в модель**

В `journal_django/apps/memberships/models.py`, после `active = models.BooleanField(default=True)` (строка 44) и перед комментарием про `created_at` (строка 45):

```python
    active = models.BooleanField(default=True)
    # Ссылка на membership, из которой ученик был переведён (apps.memberships.services.transfer_membership).
    # Ставится только сервисом перевода — обычный add_membership её не трогает.
    transferred_from = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_column='transferred_from_id',
        related_name='transferred_to',
    )
    # Колонки created_at в таблице group_memberships НЕТ (см. db/migrations/001).
```

Используем `on_delete=models.DO_NOTHING` (не `SET_NULL`) — таблица `managed=True`, но остальные FK модели (`group`, `student`) уже везде `DO_NOTHING` в этом файле, и в проекте нет ORM-каскадных удалений membership (только soft-delete `active=false`) — держим стиль консистентным с соседними полями этой же модели.

- [ ] **Step 2: Сгенерировать миграцию**

Run (из `journal_django/`):
```bash
.venv/Scripts/python.exe manage.py makemigrations memberships
```
Expected: создан файл `apps/memberships/migrations/0005_<auto-name>.py` с `AddField` для `transferred_from` на `GroupMembership`, плюс соответствующие изменения в pghistory event-модели (`groupmembershipevent`) — pghistory сам подхватывает новое поле при генерации миграции, как в прошлых миграциях этого приложения (`0002`, `0003`).

- [ ] **Step 3: Применить миграцию на dev-БД**

Run:
```bash
.venv/Scripts/python.exe manage.py migrate memberships
```
Expected: `Applying memberships.0005_...... OK`.

- [ ] **Step 4: Commit**

```bash
git add journal_django/apps/memberships/models.py journal_django/apps/memberships/migrations/
git commit -m "feat(memberships): add transferred_from FK to GroupMembership"
```

---

## Task 2: Доменные исключения перевода

**Files:**
- Modify: `journal_django/apps/memberships/exceptions.py`

- [ ] **Step 1: Добавить три исключения**

В конец `journal_django/apps/memberships/exceptions.py`, после класса `IndividualGroupFull`:

```python


class DirectionMismatch(Exception):
    """
    Целевая группа принадлежит другому направлению, чем исходная membership.

    Перевод ученика (apps.memberships.services.transfer_membership) разрешён
    только между группами одного направления.
    """

    default_message = 'Перевод разрешён только между группами одного направления.'

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__(message or self.default_message)


class SameGroupTransfer(Exception):
    """Целевая группа перевода совпадает с текущей — переводить некуда."""

    default_message = 'Ученик уже состоит в этой группе.'

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__(message or self.default_message)


class TargetGroupUnavailable(Exception):
    """Целевая группа перевода не найдена или неактивна (архивная)."""

    default_message = 'Целевая группа не найдена или неактивна.'

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__(message or self.default_message)
```

- [ ] **Step 2: Commit**

```bash
git add journal_django/apps/memberships/exceptions.py
git commit -m "feat(memberships): add transfer domain exceptions"
```

---

## Task 3: Repository-тесты перевода (failing first)

**Files:**
- Create: `journal_django/apps/memberships/tests/test_transfer_membership.py`

- [ ] **Step 1: Написать seed-фикстуру и repository-тесты**

Создать `journal_django/apps/memberships/tests/test_transfer_membership.py`:

```python
"""
Тесты apps.memberships.services/repository.transfer_membership().

Самодостаточны, по образцу test_individual_group_limit.py: сеют direction_a
(две обычные группы + одна индивидуальная), direction_b (одна группа, для
негативного теста «другое направление»), teacher, двух students.
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.groups import repository as groups_repo
from apps.memberships import repository
from apps.memberships.exceptions import (
    DirectionMismatch,
    IndividualGroupFull,
    SameGroupTransfer,
    TargetGroupUnavailable,
)

BASE_URL = '/api/admin/memberships'


@pytest.fixture
def seed():
    """direction_a (group_a1, group_a2, group_a_individual), direction_b (group_b1), teacher, s1/s2."""
    ids: dict[str, int] = {}
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO directions (name, is_individual, active) "
            "VALUES ('__tr_dir_a__', false, true) RETURNING id"
        )
        ids['direction_a'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO directions (name, is_individual, active) "
            "VALUES ('__tr_dir_b__', false, true) RETURNING id"
        )
        ids['direction_b'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO teachers (name, active, created_at) "
            "VALUES ('__tr_teacher__', true, NOW()) RETURNING id"
        )
        ids['teacher_id'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status, created_at) "
            "VALUES ('__tr_student_1__', 'enrolled', NOW()) RETURNING id"
        )
        ids['s1'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status, created_at) "
            "VALUES ('__tr_student_2__', 'enrolled', NOW()) RETURNING id"
        )
        ids['s2'] = cur.fetchone()[0]

    def _group(name: str, direction_id: int, is_individual: bool) -> dict:
        return groups_repo.create_group({
            'name': name,
            'direction_id': direction_id,
            'teacher_id': ids['teacher_id'],
            'is_individual': is_individual,
            'lesson_duration_minutes': 90,
            'lessons_per_week': 1,
        })

    group_a1 = _group('__tr_group_a1__', ids['direction_a'], False)
    group_a2 = _group('__tr_group_a2__', ids['direction_a'], False)
    group_a_individual = _group('__tr_group_a_indiv__', ids['direction_a'], True)
    group_b1 = _group('__tr_group_b1__', ids['direction_b'], False)
    ids['group_a1'] = group_a1['id']
    ids['group_a2'] = group_a2['id']
    ids['group_a_individual'] = group_a_individual['id']
    ids['group_b1'] = group_b1['id']

    yield ids

    with connection.cursor() as cur:
        cur.execute(
            'DELETE FROM group_memberships WHERE group_id IN (%s, %s, %s, %s)',
            [ids['group_a1'], ids['group_a2'], ids['group_a_individual'], ids['group_b1']],
        )
        cur.execute(
            'DELETE FROM groups WHERE id IN (%s, %s, %s, %s)',
            [ids['group_a1'], ids['group_a2'], ids['group_a_individual'], ids['group_b1']],
        )
        cur.execute('DELETE FROM students WHERE id IN (%s, %s)', [ids['s1'], ids['s2']])
        cur.execute('DELETE FROM teachers WHERE id = %s', [ids['teacher_id']])
        cur.execute('DELETE FROM directions WHERE id IN (%s, %s)', [ids['direction_a'], ids['direction_b']])


# ---------------------------------------------------------------------------
# Repository-level
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTransferMembershipRepository:

    def test_deactivates_old_and_creates_new(self, seed):
        old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})

        new = repository.transfer_membership(old['id'], seed['group_a2'])

        assert new is not None
        assert new['group_id'] == seed['group_a2']
        assert new['student_id'] == seed['s1']
        assert new['active'] is True

        rows = repository.list_memberships(student_id=seed['s1'], include_inactive=True)
        old_row = next(r for r in rows if r['id'] == old['id'])
        assert old_row['active'] is False

    def test_preserves_old_lessons_done_as_history(self, seed):
        old = repository.add_membership({
            'group_id': seed['group_a1'], 'student_id': seed['s1'], 'lessons_done': 32,
        })

        repository.transfer_membership(old['id'], seed['group_a2'])

        rows = repository.list_memberships(student_id=seed['s1'], include_inactive=True)
        old_row = next(r for r in rows if r['id'] == old['id'])
        assert float(old_row['lessons_done']) == 32.0

    def test_new_membership_starts_at_zero_lessons(self, seed):
        old = repository.add_membership({
            'group_id': seed['group_a1'], 'student_id': seed['s1'], 'lessons_done': 32,
        })

        new = repository.transfer_membership(old['id'], seed['group_a2'])

        assert float(new['lessons_done']) == 0.0

    def test_sets_transferred_from_link(self, seed):
        old = repository.add_membership({
            'group_id': seed['group_a1'], 'student_id': seed['s1'], 'lessons_done': 32,
        })

        new = repository.transfer_membership(old['id'], seed['group_a2'])

        assert new['transferred_from_id'] == old['id']
        assert new['transferred_from_group_name'] == '__tr_group_a1__'
        assert float(new['transferred_from_lessons_done']) == 32.0

    def test_nonexistent_membership_returns_none(self, seed):
        result = repository.transfer_membership(999_999_999, seed['group_a2'])
        assert result is None

    def test_inactive_membership_returns_none(self, seed):
        old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})
        repository.remove_membership(old['id'])

        result = repository.transfer_membership(old['id'], seed['group_a2'])
        assert result is None

    def test_same_group_raises(self, seed):
        old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})

        with pytest.raises(SameGroupTransfer):
            repository.transfer_membership(old['id'], seed['group_a1'])

    def test_different_direction_raises(self, seed):
        old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})

        with pytest.raises(DirectionMismatch):
            repository.transfer_membership(old['id'], seed['group_b1'])

    def test_target_group_not_found_raises(self, seed):
        old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})

        with pytest.raises(TargetGroupUnavailable):
            repository.transfer_membership(old['id'], 999_999_999)

    def test_reactivates_existing_target_membership(self, seed):
        # Ученик уже когда-то был в group_a2 (сейчас неактивен там).
        old_in_a2 = repository.add_membership({'group_id': seed['group_a2'], 'student_id': seed['s1']})
        repository.remove_membership(old_in_a2['id'])

        old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})
        new = repository.transfer_membership(old['id'], seed['group_a2'])

        assert new['id'] == old_in_a2['id']  # тот же id — реактивация, не дубль
        assert new['active'] is True

    def test_individual_group_full_raises(self, seed):
        repository.add_membership({'group_id': seed['group_a_individual'], 'student_id': seed['s2']})
        old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})

        with pytest.raises(IndividualGroupFull):
            repository.transfer_membership(old['id'], seed['group_a_individual'])
```

- [ ] **Step 2: Запустить и убедиться, что тесты падают**

Run (из `journal_django/`):
```bash
.venv/Scripts/python.exe -m pytest apps/memberships/tests/test_transfer_membership.py -q
```
Expected: FAIL — `AttributeError: module 'apps.memberships.repository' has no attribute 'transfer_membership'` (или `ImportError` на `DirectionMismatch`/`SameGroupTransfer`/`TargetGroupUnavailable`, если Task 2 ещё не закоммичен в эту рабочую копию — они уже должны быть добавлены Task 2).

- [ ] **Step 3: Commit**

```bash
git add journal_django/apps/memberships/tests/test_transfer_membership.py
git commit -m "test(memberships): add failing tests for transfer_membership"
```

---

## Task 4: Repository + service — реализация `transfer_membership`

**Files:**
- Modify: `journal_django/apps/memberships/repository.py`
- Modify: `journal_django/apps/memberships/services.py`

- [ ] **Step 1: Добавить `transferred_from_id` в `_MEMBERSHIP_FIELDS` и joined-поля в чтение**

В `journal_django/apps/memberships/repository.py`:

Заменить (строки 27-30):
```python
_MEMBERSHIP_FIELDS = (
    'id', 'group_id', 'student_id', 'lessons_done',
    'start_date', 'sheet_row', 'active',
)
```
на:
```python
_MEMBERSHIP_FIELDS = (
    'id', 'group_id', 'student_id', 'lessons_done',
    'start_date', 'sheet_row', 'active', 'transferred_from_id',
)
```

Заменить `_membership_row` (строки 50-57):
```python
def _membership_row(membership_id: int) -> Optional[dict]:
    """Строка membership (gm.* / RETURNING *) с нормализованной датой и вычисленным remaining."""
    row = _normalize_dates(
        dictrow(GroupMembership.objects.filter(id=membership_id).values(*_MEMBERSHIP_FIELDS))
    )
    if row is not None:
        row['remaining'] = balance_for_student(row['student_id'])
    return row
```
на:
```python
def _membership_row(membership_id: int) -> Optional[dict]:
    """Строка membership (gm.* / RETURNING *) с нормализованной датой и вычисленным remaining."""
    row = _normalize_dates(
        dictrow(
            GroupMembership.objects.filter(id=membership_id).values(
                *_MEMBERSHIP_FIELDS,
                transferred_from_group_name=F('transferred_from__group__name'),
                transferred_from_lessons_done=F('transferred_from__lessons_done'),
            )
        )
    )
    if row is not None:
        row['remaining'] = balance_for_student(row['student_id'])
    return row
```

В `list_memberships` заменить (строки 123-129):
```python
    rows = dictrows(
        qs.order_by('group__name', 'student__full_name').values(
            *_MEMBERSHIP_FIELDS,
            group_name=F('group__name'),
            student_name=F('student__full_name'),
        )
    )
```
на:
```python
    rows = dictrows(
        qs.order_by('group__name', 'student__full_name').values(
            *_MEMBERSHIP_FIELDS,
            group_name=F('group__name'),
            student_name=F('student__full_name'),
            transferred_from_group_name=F('transferred_from__group__name'),
            transferred_from_lessons_done=F('transferred_from__lessons_done'),
        )
    )
```

- [ ] **Step 2: Добавить импорты и `transfer_membership`**

В `journal_django/apps/memberships/repository.py`, заменить импорт исключений (строка 22):
```python
from .exceptions import IndividualGroupFull
```
на:
```python
from apps.core.utils.dates import msk_today

from .exceptions import (
    DirectionMismatch,
    IndividualGroupFull,
    SameGroupTransfer,
    TargetGroupUnavailable,
)
```

Добавить функцию в конец файла, после `remove_membership`:

```python


def transfer_membership(membership_id: int, to_group_id: int) -> Optional[dict]:
    """
    Атомарный перевод активного membership в другую группу ТОГО ЖЕ направления.

    Старая membership деактивируется (active=false, lessons_done остаётся
    честной историей — реальные уроки именно в старой группе). Новая
    membership создаётся/реактивируется тем же UPSERT-паттерном, что и
    add_membership, с transferred_from = старая membership.

    Возвращает None, если исходная membership не найдена/неактивна (view → 404).
    Бросает SameGroupTransfer/TargetGroupUnavailable/DirectionMismatch (400 во view)
    или IndividualGroupFull (409 во view).
    """
    with transaction.atomic():
        old = (
            GroupMembership.objects
            .select_related('group')
            .filter(id=membership_id, active=True)
            .first()
        )
        if old is None:
            return None

        if to_group_id == old.group_id:
            raise SameGroupTransfer()

        target = (
            Group.objects
            .filter(id=to_group_id, active=True)
            .values('direction_id')
            .first()
        )
        if target is None:
            raise TargetGroupUnavailable()
        if target['direction_id'] != old.group.direction_id:
            raise DirectionMismatch()

        # Инвариант индивидуальной группы — до записи, как в add_membership.
        _assert_individual_capacity(to_group_id, exclude_student_id=old.student_id)

        old.active = False
        old.save(update_fields=['active'])

        new_obj = GroupMembership(
            group_id=to_group_id,
            student_id=old.student_id,
            active=True,
            transferred_from_id=old.id,
            start_date=msk_today(),
        )
        GroupMembership.objects.bulk_create(
            [new_obj],
            update_conflicts=True,
            unique_fields=['group', 'student'],
            update_fields=['active', 'transferred_from', 'start_date'],
        )
        new_id = (
            GroupMembership.objects
            .filter(group_id=to_group_id, student_id=old.student_id)
            .values_list('id', flat=True)
            .first()
        )

    return _membership_row(new_id)
```

- [ ] **Step 3: Добавить тонкую обёртку в `services.py`**

В `journal_django/apps/memberships/services.py`, добавить в конец файла:

```python


def transfer_membership(membership_id: int, to_group_id: int) -> Optional[dict]:
    """Переводит ученика в другую группу того же направления (см. repository.transfer_membership)."""
    return repository.transfer_membership(membership_id, to_group_id)
```

- [ ] **Step 4: Прогнать repository-тесты**

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/memberships/tests/test_transfer_membership.py::TestTransferMembershipRepository -q
```
Expected: PASS (11 passed).

- [ ] **Step 5: Прогнать весь набор тестов memberships на регрессию**

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/memberships -q
```
Expected: PASS, без изменений в количестве прежних тестов (новые joined-поля не должны ломать `test_rows_have_group_name` и т.п.).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/memberships/repository.py journal_django/apps/memberships/services.py
git commit -m "feat(memberships): implement transfer_membership repository/service"
```

---

## Task 5: API — сериализатор, view, урл

**Files:**
- Modify: `journal_django/apps/memberships/serializers.py`
- Modify: `journal_django/apps/memberships/views.py`
- Modify: `journal_django/apps/memberships/urls.py`
- Modify: `journal_django/apps/memberships/tests/test_transfer_membership.py`

- [ ] **Step 1: Дописать API-тесты (failing) в существующий файл**

В `journal_django/apps/memberships/tests/test_transfer_membership.py` добавить в конец файла:

```python


# ---------------------------------------------------------------------------
# API-level
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_transfer_no_cookie_401(anon_client, seed):
    old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})
    resp = anon_client.post(f"{BASE_URL}/{old['id']}/transfer", {'to_group_id': seed['group_a2']}, format='json')
    assert resp.status_code == 401


@pytest.mark.django_db
def test_transfer_teacher_403(teacher_client, seed):
    old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})
    resp = teacher_client.post(f"{BASE_URL}/{old['id']}/transfer", {'to_group_id': seed['group_a2']}, format='json')
    assert resp.status_code == 403


@pytest.mark.django_db
def test_transfer_manager_403(manager_client, seed):
    """Запись в memberships — только superadmin (ReadStaffWriteSuperAdmin), как у POST/PATCH/DELETE."""
    old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})
    resp = manager_client.post(f"{BASE_URL}/{old['id']}/transfer", {'to_group_id': seed['group_a2']}, format='json')
    assert resp.status_code == 403


@pytest.mark.django_db
def test_transfer_admin_403(admin_client, seed):
    old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})
    resp = admin_client.post(f"{BASE_URL}/{old['id']}/transfer", {'to_group_id': seed['group_a2']}, format='json')
    assert resp.status_code == 403


@pytest.mark.django_db
def test_transfer_superadmin_200(superadmin_client, seed):
    old = repository.add_membership({
        'group_id': seed['group_a1'], 'student_id': seed['s1'], 'lessons_done': 32,
    })
    resp = superadmin_client.post(f"{BASE_URL}/{old['id']}/transfer", {'to_group_id': seed['group_a2']}, format='json')
    assert resp.status_code == 200
    data = resp.json()
    assert data['group_id'] == seed['group_a2']
    assert data['transferred_from_group_name'] == '__tr_group_a1__'
    assert float(data['transferred_from_lessons_done']) == 32.0


@pytest.mark.django_db
def test_transfer_different_direction_400(superadmin_client, seed):
    old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})
    resp = superadmin_client.post(f"{BASE_URL}/{old['id']}/transfer", {'to_group_id': seed['group_b1']}, format='json')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_transfer_same_group_400(superadmin_client, seed):
    old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})
    resp = superadmin_client.post(f"{BASE_URL}/{old['id']}/transfer", {'to_group_id': seed['group_a1']}, format='json')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_transfer_nonexistent_membership_404(superadmin_client, seed):
    resp = superadmin_client.post(f'{BASE_URL}/999999999/transfer', {'to_group_id': seed['group_a2']}, format='json')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_transfer_missing_to_group_id_400(superadmin_client, seed):
    old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})
    resp = superadmin_client.post(f"{BASE_URL}/{old['id']}/transfer", {}, format='json')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_transfer_individual_group_full_409(superadmin_client, seed):
    repository.add_membership({'group_id': seed['group_a_individual'], 'student_id': seed['s2']})
    old = repository.add_membership({'group_id': seed['group_a1'], 'student_id': seed['s1']})

    resp = superadmin_client.post(
        f"{BASE_URL}/{old['id']}/transfer", {'to_group_id': seed['group_a_individual']}, format='json',
    )
    assert resp.status_code == 409
```

- [ ] **Step 2: Прогнать API-тесты и убедиться, что падают**

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/memberships/tests/test_transfer_membership.py -q -k "test_transfer_"
```
Expected: FAIL — `404 Not Found` на всех (урл `/transfer` ещё не существует).

- [ ] **Step 3: Добавить `MembershipTransferSerializer`**

В `journal_django/apps/memberships/serializers.py`, добавить в конец файла:

```python


class MembershipTransferSerializer(serializers.Serializer):
    """Вход для POST /api/admin/memberships/:id/transfer."""

    to_group_id = serializers.IntegerField(min_value=1)
```

- [ ] **Step 4: Добавить `MembershipTransferView`**

В `journal_django/apps/memberships/views.py`:

Заменить импорты (строки 21-24):
```python
from apps.core.permissions import ReadStaffWriteSuperAdmin
from apps.memberships import services
from apps.memberships.exceptions import IndividualGroupFull
from apps.memberships.serializers import MembershipUpdateSerializer, MembershipWriteSerializer
```
на:
```python
from apps.core.permissions import ReadStaffWriteSuperAdmin
from apps.memberships import services
from apps.memberships.exceptions import (
    DirectionMismatch,
    IndividualGroupFull,
    SameGroupTransfer,
    TargetGroupUnavailable,
)
from apps.memberships.serializers import (
    MembershipTransferSerializer,
    MembershipUpdateSerializer,
    MembershipWriteSerializer,
)
```

Добавить класс в конец файла:

```python


class MembershipTransferView(APIView):
    """
    POST /api/admin/memberships/:id/transfer — перевод ученика в другую
    активную группу того же направления (см. services.transfer_membership).
    """

    permission_classes = [ReadStaffWriteSuperAdmin]

    def post(self, request: Request, pk: int) -> Response:
        serializer = MembershipTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            updated = services.transfer_membership(pk, serializer.validated_data['to_group_id'])
        except IndividualGroupFull as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        except (DirectionMismatch, SameGroupTransfer, TargetGroupUnavailable) as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if updated is None:
            raise NotFound({'error': 'Not found'})

        return Response(updated)
```

- [ ] **Step 5: Подключить урл**

В `journal_django/apps/memberships/urls.py`:

```python
from django.urls import path

from apps.memberships.views import MembershipDetailView, MembershipListCreateView, MembershipTransferView

urlpatterns = [
    path('', MembershipListCreateView.as_view(), name='memberships-list-create'),
    path('/<int:pk>', MembershipDetailView.as_view(), name='memberships-detail'),
    path('/<int:pk>/transfer', MembershipTransferView.as_view(), name='memberships-transfer'),
]
```

- [ ] **Step 6: Прогнать API-тесты, убедиться что проходят**

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/memberships/tests/test_transfer_membership.py -q
```
Expected: PASS (все тесты файла, repository + API).

- [ ] **Step 7: Прогнать весь набор memberships на регрессию**

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/memberships -q
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add journal_django/apps/memberships/serializers.py journal_django/apps/memberships/views.py journal_django/apps/memberships/urls.py journal_django/apps/memberships/tests/test_transfer_membership.py
git commit -m "feat(memberships): add POST /api/admin/memberships/:id/transfer endpoint"
```

---

## Task 6: Журнал изменений (changelog) для перевода

**Files:**
- Modify: `journal_django/apps/changelog/labels.py`
- Modify: `journal_django/apps/changelog/summary.py`
- Modify: `journal_django/apps/changelog/tests/test_summary.py`

- [ ] **Step 1: Добавить правило метки**

В `journal_django/apps/changelog/labels.py`, в блоке `# memberships` (строки 40-43), заменить:
```python
    # memberships
    ('POST', re.compile(r'^/api/admin/memberships$'), 'membership.create'),
    ('PATCH', re.compile(r'^/api/admin/memberships/\d+$'), 'membership.update'),
    ('DELETE', re.compile(r'^/api/admin/memberships/\d+$'), 'membership.delete'),
```
на:
```python
    # memberships
    ('POST', re.compile(r'^/api/admin/memberships/\d+/transfer$'), 'membership.transfer'),
    ('POST', re.compile(r'^/api/admin/memberships$'), 'membership.create'),
    ('PATCH', re.compile(r'^/api/admin/memberships/\d+$'), 'membership.update'),
    ('DELETE', re.compile(r'^/api/admin/memberships/\d+$'), 'membership.delete'),
```
(правило `/transfer` должно стоять выше общего `memberships$`, хотя регексы и так не пересекаются — держим порядок «специфичное выше», как велит докстрока файла).

- [ ] **Step 2: Написать failing-тест на описание операции**

Тесты `membership.*`-веток `build_summary` в этом файле идут не через голые dict-фикстуры (это паттерн только для `describe_event`, строки 27-62), а через полноценный round-trip: `pghistory.context(url=..., method=...)` вокруг реальных ORM-записей → `GET /api/admin/changelog` → сверка `row['summary']` (см. `test_summary_membership`, строки 101-107, и хелпер `_feed_top`, строка 73-74). Новый тест пишем в том же стиле.

В `journal_django/apps/changelog/tests/test_summary.py` заменить импорт (строка 11):
```python
from apps.memberships.models import GroupMembership
```
на:
```python
from apps.memberships.models import GroupMembership
from apps.memberships.repository import transfer_membership
```

Добавить тест после `test_summary_membership` (после строки 107):

```python


def test_summary_membership_transfer(admin_client, group):
    target_group = Group.objects.create(
        name='ПИ1013', direction=group.direction, teacher=group.teacher,
        is_individual=False, created_at=timezone.now(),
    )
    s = Student.objects.create(full_name='Иван Тестов', created_at=timezone.now())
    old = GroupMembership.objects.create(group=group, student=s, active=True, lessons_done=32)

    with pghistory.context(url=f'/api/admin/memberships/{old.id}/transfer', method='POST'):
        transfer_membership(old.id, target_group.id)

    row = _feed_top(admin_client)
    assert row['summary'] == 'Перевод: Иван Тестов из ПИ1012 в ПИ1013'
```

- [ ] **Step 3: Запустить и убедиться, что падает**

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/changelog/tests/test_summary.py -q -k membership_transfer
```
Expected: FAIL — падает на `assert`, потому что ветка `operation == 'membership.transfer'` пока не описана отдельно и уходит в generic-фолбэк (`_generic_phrase`, не начинается с «Перевод:»).

- [ ] **Step 4: Добавить ветку в `build_summary`**

В `journal_django/apps/changelog/summary.py`, в блоке «Членства» (строки 383-393), заменить:
```python
    # --- Членства ---
    memberships = by_entity.get('membership', [])
    if memberships and operation.startswith('membership.'):
        data = memberships[0].get('pgh_data') or {}
        student = lk.student(data.get('student_id'))
        group = lk.group(data.get('group_id'))
        if operation == 'membership.create':
            return f'Зачисление: {student} → {group}'
        if operation == 'membership.delete':
            return f'Отчисление: {student} из {group}'
        return _generic_phrase(memberships[0], 'Членство')
```
на:
```python
    # --- Членства ---
    memberships = by_entity.get('membership', [])
    if memberships and operation.startswith('membership.'):
        data = memberships[0].get('pgh_data') or {}
        student = lk.student(data.get('student_id'))
        group = lk.group(data.get('group_id'))
        if operation == 'membership.create':
            return f'Зачисление: {student} → {group}'
        if operation == 'membership.delete':
            return f'Отчисление: {student} из {group}'
        if operation == 'membership.transfer':
            old_ev = next(
                (e for e in memberships if (e.get('pgh_diff') or {}).get('active') == [True, False]),
                None,
            )
            new_ev = next((e for e in memberships if e is not old_ev), memberships[-1])
            new_data = new_ev.get('pgh_data') or {}
            student_t = lk.student(new_data.get('student_id'))
            from_group = lk.group((old_ev.get('pgh_data') or {}).get('group_id')) if old_ev else '—'
            to_group = lk.group(new_data.get('group_id'))
            return f'Перевод: {student_t} из {from_group} в {to_group}'
        return _generic_phrase(memberships[0], 'Членство')
```

- [ ] **Step 5: Прогнать тест, убедиться что проходит**

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/changelog/tests/test_summary.py -q
```
Expected: PASS (весь файл, без регрессий в соседних тестах).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/changelog/labels.py journal_django/apps/changelog/summary.py journal_django/apps/changelog/tests/test_summary.py
git commit -m "feat(changelog): describe membership.transfer operation"
```

---

## Task 7: Frontend — типы

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/shared-types.ts`

- [ ] **Step 1: Добавить поля в `GroupMembership`**

В `journal_django/frontend/admin-src/src/lib/shared-types.ts`, в интерфейсе `GroupMembership` (строки 101-113), после `student_name?: string;`:

```typescript
export interface GroupMembership {
  id: ID;
  group_id: ID;
  student_id: ID;
  lessons_done: string | number; // numeric(6,1) от pg как string
  remaining: string | number;
  start_date: string | null;
  sheet_row: number | null;
  active: boolean;
  // joined-only:
  group_name?: string;
  student_name?: string;
  transferred_from_id?: ID | null;
  transferred_from_group_name?: string | null;
  transferred_from_lessons_done?: string | number | null;
}
```

- [ ] **Step 2: Typecheck**

Run (из `journal_django/frontend/admin-src`):
```bash
npm run typecheck
```
Expected: без новых ошибок (тип расширен опциональными полями — обратная совместимость).

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/lib/shared-types.ts
git commit -m "feat(admin-src): add transferred_from fields to GroupMembership type"
```

---

## Task 8: Frontend — мутация перевода

**Files:**
- Modify: `journal_django/frontend/admin-src/src/hooks/useMemberships.ts`

- [ ] **Step 1: Добавить `transfer` в `useMembershipMutations`**

В `journal_django/frontend/admin-src/src/hooks/useMemberships.ts`, заменить возвращаемый объект (строки 31-42):
```typescript
  return {
    create: useMutation({
      mutationFn: (body: { student_id: number; group_id: number }) =>
        api<GroupMembership>('POST', '/api/admin/memberships', body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) =>
        api<void>('DELETE', `/api/admin/memberships/${id}`),
      onSuccess: invalidate,
    }),
  };
```
на:
```typescript
  return {
    create: useMutation({
      mutationFn: (body: { student_id: number; group_id: number }) =>
        api<GroupMembership>('POST', '/api/admin/memberships', body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) =>
        api<void>('DELETE', `/api/admin/memberships/${id}`),
      onSuccess: invalidate,
    }),
    transfer: useMutation({
      mutationFn: ({ id, to_group_id }: { id: number; to_group_id: number }) =>
        api<GroupMembership>('POST', `/api/admin/memberships/${id}/transfer`, { to_group_id }),
      onSuccess: invalidate,
    }),
  };
```

- [ ] **Step 2: Typecheck**

Run:
```bash
npm run typecheck
```
Expected: без ошибок.

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/hooks/useMemberships.ts
git commit -m "feat(admin-src): add transfer mutation to useMembershipMutations"
```

---

## Task 9: Frontend — `TransferMembershipModal`

**Files:**
- Create: `journal_django/frontend/admin-src/src/components/memberships/TransferMembershipModal.tsx`
- Modify: `journal_django/frontend/admin-src/src/styles/pages/detail.css`

- [ ] **Step 1: Создать модалку**

Создать `journal_django/frontend/admin-src/src/components/memberships/TransferMembershipModal.tsx`:

```tsx
import { useState } from 'react';
import { Dialog } from '../ui/Dialog';
import { Field } from '../form/Field';
import { SelectInput } from '../form/SelectInput';
import { useMembershipMutations } from '../../hooks/useMemberships';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../ui/Toast';

interface Props {
  membershipId: number;
  currentGroupName: string;
  targetOptions: { value: number; label: string }[];
  onClose: () => void;
}

export function TransferMembershipModal({ membershipId, currentGroupName, targetOptions, onClose }: Props) {
  const muts = useMembershipMutations();
  const showError = useApiError();
  const { toast } = useToast();
  const [toGroupId, setToGroupId] = useState<number | ''>('');

  const handleConfirm = async () => {
    if (!toGroupId) return;
    try {
      await muts.transfer.mutateAsync({ id: membershipId, to_group_id: Number(toGroupId) });
      toast('Переведён', 'ok');
      onClose();
    } catch (err) { showError(err); }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={`Перевести из «${currentGroupName}»`}
      footer={(
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>Отмена</button>
          <button
            type="button"
            className="btn-primary"
            disabled={!toGroupId || muts.transfer.isPending}
            onClick={() => { void handleConfirm(); }}
          >Перевести</button>
        </>
      )}
    >
      <p className="transfer-modal__text">
        Ученик перейдёт в выбранную группу того же направления. Уроки, отработанные
        в «{currentGroupName}», останутся в истории — новая группа стартует с 0,
        но на карточке будет видно, откуда пришёл ученик.
      </p>
      <Field label="Новая группа" required>
        <SelectInput
          value={toGroupId === '' ? '' : String(toGroupId)}
          onChange={(e) => setToGroupId(e.target.value === '' ? '' : Number(e.target.value))}
          options={targetOptions}
          placeholder="Выберите группу…"
        />
      </Field>
    </Dialog>
  );
}
```

- [ ] **Step 2: Добавить CSS**

В `journal_django/frontend/admin-src/src/styles/pages/detail.css`, после блока `.membership-card__stats`/`.membership-card__stat-value` (строки 477-489), добавить:

```css
.membership-card__transfer-btn {
  background: transparent; border: 1px solid var(--border); color: var(--text3);
  width: 28px; height: 28px; border-radius: 8px; cursor: pointer;
  font-size: 14px; line-height: 1; display: flex; align-items: center; justify-content: center;
  transition: background .12s, color .12s, border-color .12s;
}
.membership-card__transfer-btn:hover { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
.membership-card__transferred-note {
  font-size: 12px; color: var(--text3); padding-top: 8px; margin-top: 8px;
  border-top: 1px dashed var(--border);
}
.transfer-modal__text { color: var(--text2); font-size: 14px; margin-bottom: 16px; }
```

- [ ] **Step 3: Typecheck**

Run:
```bash
npm run typecheck
```
Expected: без ошибок.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/components/memberships/TransferMembershipModal.tsx journal_django/frontend/admin-src/src/styles/pages/detail.css
git commit -m "feat(admin-src): add TransferMembershipModal component"
```

---

## Task 10: Frontend — кнопка и плашка в `MembershipsBlock` + страница ученика

**Files:**
- Modify: `journal_django/frontend/admin-src/src/components/memberships/MembershipsBlock.tsx`
- Modify: `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx`

- [ ] **Step 1: Добавить `onTransfer` в `MembershipsBlock`**

В `journal_django/frontend/admin-src/src/components/memberships/MembershipsBlock.tsx`:

Заменить `interface Props` (строки 15-19):
```typescript
interface Props {
  config: Mode;
  renderCard: (m: GroupMembership) => { title: string; meta: React.ReactNode; navigateTo?: string };
  emptyText: string;
}
```
на:
```typescript
interface Props {
  config: Mode;
  renderCard: (m: GroupMembership) => { title: string; meta: React.ReactNode; navigateTo?: string };
  emptyText: string;
  /** Если передан — на каждой карточке появляется кнопка «⇄ Перевести». */
  onTransfer?: (m: GroupMembership) => void;
}
```

Заменить сигнатуру компонента (строка 21):
```typescript
export function MembershipsBlock({ config, renderCard, emptyText }: Props) {
```
на:
```typescript
export function MembershipsBlock({ config, renderCard, emptyText, onTransfer }: Props) {
```

Заменить блок карточки (строки 75-116) — добавить кнопку перевода рядом с «×» и плашку истории после `membership-card__stats`:
```tsx
        memberships.map((m) => {
          const card = renderCard(m);
          return (
            <div
              key={m.id}
              className="link-card membership-card"
              tabIndex={0}
              role="button"
              onClick={(e) => {
                if ((e.target as HTMLElement).closest('[data-mremove]') || (e.target as HTMLElement).closest('[data-mtransfer]')) return;
                if (card.navigateTo) navigate(card.navigateTo);
              }}
              onKeyDown={(e) => {
                if ((e.key === 'Enter' || e.key === ' ') && card.navigateTo) {
                  e.preventDefault();
                  navigate(card.navigateTo);
                }
              }}
            >
              <div className="link-card-head">
                <div>
                  <div className="link-card-title">{card.title}</div>
                  <div className="link-card-meta">{card.meta}</div>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  {onTransfer && (
                    <button
                      type="button"
                      className="membership-card__transfer-btn"
                      data-mtransfer
                      aria-label="Перевести"
                      title="Перевести в другую группу"
                      onClick={() => onTransfer(m)}
                    >⇄</button>
                  )}
                  <button
                    type="button"
                    className="membership-card__remove"
                    data-mremove
                    aria-label="Убрать"
                    onClick={() => { void handleRemove(m.id); }}
                  >×</button>
                </div>
              </div>
              <div className="membership-card__stats">
                <div className="membership-card__stat">
                  <span className="membership-card__stat-label">Пройдено</span>
                  <span className="membership-card__stat-value">{String(m.lessons_done)}</span>
                </div>
              </div>
              {m.transferred_from_group_name && (
                <div className="membership-card__transferred-note">
                  Переведён из «{m.transferred_from_group_name}» — там отработано {String(m.transferred_from_lessons_done)} ур.
                </div>
              )}
            </div>
          );
        })
```

- [ ] **Step 2: Подключить в `StudentDetailPage`**

В `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx`:

Добавить импорт после `import { MembershipsBlock } from '../../components/memberships/MembershipsBlock';`:
```typescript
import { TransferMembershipModal } from '../../components/memberships/TransferMembershipModal';
```

Заменить существующий импорт типа (строка 14):
```typescript
import type { Student } from '../../lib/types';
```
на:
```typescript
import type { GroupMembership, Student } from '../../lib/types';
```

Добавить состояние рядом с `const [editing, setEditing] = useState(false);`:
```typescript
  const [transferMembership, setTransferMembership] = useState<GroupMembership | null>(null);
```

В `MembershipsBlock` (внутри вкладки `learning`, строки 161-183) добавить проп `onTransfer`:
```tsx
            <MembershipsBlock
              config={{
                mode: 'byStudent',
                studentId: student.id,
                pickerOptions: groupOptions,
                pickerLabel: 'Выберите группу',
              }}
              emptyText="Не записан ни в одну группу"
              onTransfer={(m) => setTransferMembership(m)}
              renderCard={(m) => {
                const g = groups.find((x) => x.id === m.group_id);
                const dir = g ? directions.find((d) => d.id === g.direction_id) : null;
                return {
                  title: m.group_name || `#${m.group_id}`,
                  meta: (
                    <>
                      {dir && <DirTag direction={dir} />}
                      {g && !g.active && <span className="archive-tag">Архив</span>}
                    </>
                  ),
                  navigateTo: `/admin/groups/${m.group_id}`,
                };
              }}
            />
```

Добавить рендер модалки в конец возвращаемого JSX, рядом с `{editing && (...)}`:
```tsx
      {transferMembership && (() => {
        const currentGroup = groups.find((g) => g.id === transferMembership.group_id);
        const targetOptions = currentGroup
          ? groups
              .filter((g) => g.active && g.direction_id === currentGroup.direction_id && g.id !== currentGroup.id)
              .map((g) => ({ value: g.id, label: g.name }))
          : [];
        return (
          <TransferMembershipModal
            membershipId={Number(transferMembership.id)}
            currentGroupName={currentGroup?.name || `#${transferMembership.group_id}`}
            targetOptions={targetOptions}
            onClose={() => setTransferMembership(null)}
          />
        );
      })()}
```

- [ ] **Step 3: Typecheck**

Run (из `journal_django/frontend/admin-src`):
```bash
npm run typecheck
```
Expected: без ошибок. Если `GroupMembership` уже импортирован в файле под другим путём/именем — использовать существующий импорт вместо дублирования.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/components/memberships/MembershipsBlock.tsx journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx
git commit -m "feat(admin-src): wire up student group transfer button and modal"
```

---

## Task 11: Ручная проверка в браузере

**Files:** нет изменений — только проверка.

- [ ] **Step 1: Собрать фронт (или запустить dev-сервер)**

Run (из `journal_django/frontend/admin-src`):
```bash
npm run build
```
Expected: сборка без ошибок (проверяет то, что не ловит `tsc --noEmit`, например неиспользуемые импорты при `noUnusedLocals`).

- [ ] **Step 2: Запустить backend и открыть страницу ученика**

Запустить `runserver` (по локальному дев-процессу проекта) и локальный nginx (см. `docs` про `:8080`). Открыть `/admin/students/<id учеником с активной группой в направлении, где есть ещё хотя бы одна активная группа>`.

- [ ] **Step 3: Проверить happy path**

- На карточке активной группы должна появиться кнопка «⇄» рядом с «×».
- Клик по «⇄» открывает модалку «Перевести из «...»» со списком групп **того же направления** (без текущей, без неактивных).
- Выбрать группу → «Перевести» → тост «Переведён».
- Старая группа пропала из активного списка на странице ученика (она деактивирована).
- Новая группа появилась в списке, «Пройдено: 0», и под статистикой — плашка «Переведён из «...» — там отработано N ур.» с реальным числом уроков из старой группы.

- [ ] **Step 4: Проверить журнал изменений**

Открыть `/admin/changelog`, найти операцию перевода — описание должно быть вида «Перевод: {ученик} из {группа А} в {группа Б}», не generic-фолбэком.

---

## Task 12: Финальный регрессионный прогон

**Files:** нет изменений.

- [ ] **Step 1: Полный backend-набор**

Run (из `journal_django/`):
```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: все тесты зелёные (включая новые из Task 3/5/6), без падений в других приложениях.

- [ ] **Step 2: Финальный typecheck фронта**

Run (из `journal_django/frontend/admin-src`):
```bash
npm run typecheck
```
Expected: без ошибок.
