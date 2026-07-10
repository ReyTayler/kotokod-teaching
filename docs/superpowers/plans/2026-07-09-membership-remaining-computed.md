# `remaining` как вычисляемый баланс ученика — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить хранимую (и рассинхронизирующуюся) колонку `group_memberships.remaining` на вычисляемое значение — общий пул-баланс ученика (`purchased − attended`), тот же, что уже используется в `finances.balance_for_student`.

**Architecture:** Новая батч-функция `apps.finances.repository.balances_for_students()` считает баланс сразу для набора `student_id` (без N+1). Три читателя (`memberships`, `teacher_spa`, `students`) переключаются на неё вместо чтения сырой колонки. Ручная запись через `PATCH`/`POST` убирается, колонка дропается миграцией.

**Tech Stack:** Django 5.2 ORM, pytest + pytest-django (`journal_test` БД), pghistory (auto-migrations для событийных таблиц/триггеров).

Спека: `docs/superpowers/specs/2026-07-09-membership-remaining-design.md`.

---

## Task 1: `apps/finances` — батч-калькулятор баланса

**Files:**
- Modify: `journal_django/apps/finances/repository.py:19-22` (импорты), `151-164` (`balance_for_student`)
- Test: `journal_django/apps/finances/tests/test_balance.py`

- [ ] **Step 1: Написать падающий тест на батч-функцию**

Добавить в конец `journal_django/apps/finances/tests/test_balance.py`:

```python
def test_balances_for_students_batches_multiple(
    teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    """Один вызов на несколько student_id — каждый получает свой баланс, без N+1."""
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000)  # 4 урока куплено
    other_student_id = None
    try:
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO students (full_name, enrollment_status) "
                "VALUES ('__fin_student_2__', 'enrolled') RETURNING id"
            )
            other_student_id = cur.fetchone()[0]
        result = repository.balances_for_students([student_fixture, other_student_id])
        assert result[student_fixture] == 4
        assert result[other_student_id] == 0
    finally:
        if other_student_id is not None:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM students WHERE id = %s', [other_student_id])


def test_balances_for_students_matches_single(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    """Батч-результат совпадает с balance_for_student для того же ученика."""
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000)
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-06-10', duration=60
    )
    batch = repository.balances_for_students([student_fixture])
    single = repository.balance_for_student(student_fixture)
    assert batch[student_fixture] == single == 3


def test_balances_for_students_empty_input():
    """Пустой список id → пустой словарь, без похода в БД с IN ()."""
    assert repository.balances_for_students([]) == {}
```

- [ ] **Step 2: Убедиться, что тест падает (функции ещё нет)**

Run: `cd journal_django && .venv\Scripts\python.exe -m pytest apps/finances/tests/test_balance.py -v -k balances_for_students`
Expected: FAIL — `AttributeError: module 'apps.finances.repository' has no attribute 'balances_for_students'`

- [ ] **Step 3: Реализовать `balances_for_students`, переиспользовать в `balance_for_student`**

В `journal_django/apps/finances/repository.py` заменить блок импортов (строки 19-31):

```python
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Iterable

from django.db.models import Case, DecimalField, F, Sum, Value, When
from django.db.models.functions import Coalesce

from apps.core.utils.decimal import to_decimal

from apps.directions.models import Direction
from apps.lessons.models import LessonAttendance
from apps.payments.models import Payment
```

Заменить `balance_for_student` (строки 151-164) на:

```python
def balances_for_students(student_ids: Iterable[int]) -> dict[int, int | float]:
    """
    Общий баланс (purchased − attended) сразу для набора учеников — без N+1.

    Используется там, где строк много за один раз (teacher_spa.read_all_students
    тянет всю школу разом на 2 CPU/2 ГБ VPS). Каждый переданный student_id
    гарантированно есть в результате (0, если нет ни оплат, ни посещений).
    """
    ids = list(student_ids)
    if not ids:
        return {}

    balances: dict[int, Decimal] = {sid: Decimal('0') for sid in ids}

    purchased = (
        Payment.objects.filter(student_id__in=ids)
        .values('student_id')
        .annotate(s=Coalesce(Sum(F('subscriptions_count') * 4, output_field=_DEC), _ZERO))
    )
    for r in purchased:
        balances[r['student_id']] += r['s']

    attended = (
        LessonAttendance.objects.filter(student_id__in=ids, present=True)
        .values('student_id')
        .annotate(s=Coalesce(Sum(_attended_units_case()), _ZERO))
    )
    for r in attended:
        balances[r['student_id']] -= r['s']

    return {sid: _js_number(v) for sid, v in balances.items()}


def balance_for_student(student_id: int) -> int | float:
    """
    Общий баланс ученика (единый пул по всем направлениям): purchased − attended.
    half-lesson: 45→0.5. Делегирует в balances_for_students — одна формула на двоих.
    """
    return balances_for_students([student_id])[student_id]
```

- [ ] **Step 4: Прогнать новые тесты и весь файл**

Run: `cd journal_django && .venv\Scripts\python.exe -m pytest apps/finances/tests/test_balance.py -v`
Expected: PASS — все тесты, включая старые (`test_balance_for_student_matches`, `test_balance_pools_across_directions`, `test_balance_empty_student`), зелёные (рефакторинг не меняет поведение `balance_for_student`).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/finances/repository.py journal_django/apps/finances/tests/test_balance.py
git commit -m "feat(finances): add batched balances_for_students, delegate balance_for_student"
```

---

## Task 2: `apps/memberships` — вычисляемый `remaining`, убрать ручную запись

**Files:**
- Modify: `journal_django/apps/memberships/repository.py:10-30, 49-53, 99-202` (импорты, `_MEMBERSHIP_FIELDS`, `_membership_row`, `list_memberships`, `add_membership`, `update_membership`)
- Modify: `journal_django/apps/memberships/serializers.py:39-64`
- Test: `journal_django/apps/memberships/tests/test_memberships_repository.py`
- Test: `journal_django/apps/memberships/tests/test_memberships_api.py:305-421`
- Test: `journal_django/apps/memberships/tests/test_individual_group_limit.py:105-112`

- [ ] **Step 1: Написать падающие тесты на вычисляемый `remaining`**

В `journal_django/apps/memberships/tests/test_memberships_repository.py` убрать мёртвый ключ из `_create_test_membership` (строка 55, `'remaining': 0,` — из словаря `data`), и добавить в класс `TestListMemberships`:

```python
    def test_rows_have_computed_remaining(self):
        """remaining — вычисляемое (общий баланс ученика), не хранимая колонка."""
        result = repository.list_memberships()
        if result:
            assert 'remaining' in result[0]
            assert isinstance(result[0]['remaining'], (int, float))
```

и в класс `TestAddMembership`:

```python
    def test_add_includes_computed_remaining(self):
        group_id = _get_valid_group_id()
        student_id = _get_valid_student_id()
        _cleanup_membership_by_pair(group_id, student_id)
        try:
            m = repository.add_membership({'group_id': group_id, 'student_id': student_id})
            assert 'remaining' in m
            assert isinstance(m['remaining'], (int, float))
        finally:
            _cleanup_membership_by_pair(group_id, student_id)
```

- [ ] **Step 2: Убедиться, что новые тесты падают из-за мёртвого ключа / отсутствия логики**

Run: `cd journal_django && .venv\Scripts\python.exe -m pytest apps/memberships/tests/test_memberships_repository.py -v -k "computed_remaining"`
Expected: на этом шаге тесты пройдут технически (колонка `remaining` в БД пока жива и дефолтится в 0, `int`/`float` — тип совпадёт) — это ожидаемо, реальная проверка будет после Step 3, когда логика перейдёт на вычисление. Главное — убедиться, что тесты запускаются и не падают по опечатке (пробный прогон перед рефакторингом).

- [ ] **Step 3: Переключить репозиторий на вычисляемый `remaining`**

В `journal_django/apps/memberships/repository.py` заменить блок импортов (строки 10-22):

```python
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from django.db import transaction
from django.db.models import F

from apps.core.utils.orm import dictrow, dictrows
from apps.finances.repository import balance_for_student, balances_for_students
from apps.groups.models import Group

from .exceptions import IndividualGroupFull
from .models import GroupMembership
```

Заменить `_MEMBERSHIP_FIELDS` (строки 26-29):

```python
_MEMBERSHIP_FIELDS = (
    'id', 'group_id', 'student_id', 'lessons_done',
    'start_date', 'sheet_row', 'active',
)
```

Заменить `_membership_row` (строки 49-53):

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

Заменить `list_memberships` (строки 99-127):

```python
def list_memberships(
    group_id: Optional[int] = None,
    student_id: Optional[int] = None,
    include_inactive: bool = False,
) -> list[dict]:
    """
    Возвращает список membership без пагинации.

    Фильтры: group_id, student_id, include_inactive (по умолчанию только active=true).
    Порядок: g.name, s.full_name. remaining — вычисляемый общий баланс ученика
    (apps.finances), одним батч-запросом на всех учеников выборки.
    """
    qs = GroupMembership.objects.all()
    if not include_inactive:
        qs = qs.filter(active=True)
    if group_id is not None:
        qs = qs.filter(group_id=group_id)
    if student_id is not None:
        qs = qs.filter(student_id=student_id)

    rows = dictrows(
        qs.order_by('group__name', 'student__full_name').values(
            *_MEMBERSHIP_FIELDS,
            group_name=F('group__name'),
            student_name=F('student__full_name'),
        )
    )
    balances = balances_for_students({row['student_id'] for row in rows})
    for row in rows:
        _normalize_dates(row)
        row['remaining'] = balances[row['student_id']]
    return rows
```

Заменить `add_membership` (строки 130-168):

```python
def add_membership(data: dict) -> dict:
    """
    UPSERT membership (ON CONFLICT (group_id, student_id) DO UPDATE SET active=true).

    На вставке: lessons_done дефолтится в 0 (COALESCE(%s,0)). remaining не хранится —
    вычисляется при чтении (общий баланс ученика, apps.finances.repository).
    На конфликте: только active=true, остальные поля сохраняются (паттерн 4.9).
    """
    group_id = data['group_id']
    student_id = data['student_id']
    lessons_done = data.get('lessons_done')

    obj = GroupMembership(
        group_id=group_id,
        student_id=student_id,
        lessons_done=lessons_done if lessons_done is not None else 0,
        start_date=data.get('start_date') or None,
        sheet_row=data.get('sheet_row') or None,
        active=True,
    )
    with transaction.atomic():
        # Инвариант индивидуальной группы: проверяем ДО bulk_create, чтобы
        # pghistory InsertEvent не родился при отклонении (откат снимет lock).
        _assert_individual_capacity(group_id, exclude_student_id=student_id)
        GroupMembership.objects.bulk_create(
            [obj],
            update_conflicts=True,
            unique_fields=['group', 'student'],
            update_fields=['active'],   # ON CONFLICT DO UPDATE SET active=true
        )
    # RETURNING * — перечитываем строку по уникальной паре (id мог не вернуться при конфликте).
    row = _normalize_dates(
        dictrow(
            GroupMembership.objects
            .filter(group_id=group_id, student_id=student_id)
            .values(*_MEMBERSHIP_FIELDS)
        )
    )
    row['remaining'] = balance_for_student(student_id)
    return row
```

Заменить `update_membership` (строки 171-202):

```python
def update_membership(membership_id: int, data: dict) -> Optional[dict]:
    """
    Обновляет membership (PATCH через COALESCE, дословно из memberships.js).

    - lessons_done: COALESCE(%s, col) → set если значение не None (вкл. 0/0.5).
    - start_date/sheet_row: COALESCE(%s, col) → set если значение непусто.
    - active: COALESCE(%s, col) → set если ключ есть и значение не None.
    - remaining больше не пишется вручную — вычисляется при чтении (_membership_row).
    """
    with transaction.atomic():
        obj = GroupMembership.objects.filter(id=membership_id).first()
        if obj is None:
            return None

        # Реактивация (active=True) в индивидуальной группе — проверяем инвариант
        # ДО save(), исключая саму эту строку. PATCH без active / active=False
        # проверку не запускает.
        if data.get('active') is True:
            _assert_individual_capacity(obj.group_id, exclude_membership_id=membership_id)

        if data.get('lessons_done') is not None:
            obj.lessons_done = data['lessons_done']
        if data.get('start_date'):
            obj.start_date = data['start_date']
        if data.get('sheet_row'):
            obj.sheet_row = data['sheet_row']
        if data.get('active') is not None and 'active' in data:
            obj.active = data['active']

        obj.save()
    return _membership_row(membership_id)
```

- [ ] **Step 4: Убрать `remaining` из write-сериализаторов**

В `journal_django/apps/memberships/serializers.py` заменить `MembershipWriteSerializer` и `MembershipUpdateSerializer` (строки 39-64):

```python
class MembershipWriteSerializer(serializers.Serializer):
    """
    Вход для POST /api/admin/memberships (createMembershipSchema).

    Обязательные поля: group_id, student_id.
    Необязательные: lessons_done, start_date. remaining больше не принимается —
    вычисляется при чтении (apps.finances.balance_for_student).
    """

    group_id = serializers.IntegerField(min_value=1)
    student_id = serializers.IntegerField(min_value=1)
    lessons_done = serializers.FloatField(min_value=0, required=False)
    start_date = DateStringField(allow_null=True, required=False)


class MembershipUpdateSerializer(serializers.Serializer):
    """
    Вход для PATCH /api/admin/memberships/:id (updateMembershipSchema).

    Все поля необязательны. remaining не принимается — см. MembershipWriteSerializer.
    """

    lessons_done = serializers.FloatField(min_value=0, required=False)
    start_date = DateStringField(allow_null=True, required=False)
    active = serializers.BooleanField(required=False)
```

- [ ] **Step 5: Прогнать тесты memberships-репозитория**

Run: `cd journal_django && .venv\Scripts\python.exe -m pytest apps/memberships/tests/test_memberships_repository.py -v`
Expected: PASS — включая новые `test_rows_have_computed_remaining`, `test_add_includes_computed_remaining`.

- [ ] **Step 6: Обновить тесты `test_memberships_api.py`, убрать `remaining` из raw INSERT и добавить регресс-тест на игнорирование ручного remaining**

В `journal_django/apps/memberships/tests/test_memberships_api.py` заменить три места (строки ~314, ~382, ~405):

```python
            INSERT INTO group_memberships (group_id, student_id, lessons_done, remaining, active)
            VALUES (%s, %s, 0, 0, true)
```

на:

```python
            INSERT INTO group_memberships (group_id, student_id, lessons_done, active)
            VALUES (%s, %s, 0, true)
```

(во всех трёх местах — фикстура `existing_membership`, `test_delete_returns_204`, `test_delete_sets_active_false`).

Добавить новый тест после `test_patch_updates_start_date` (строка ~356):

```python
@pytest.mark.django_db
def test_patch_remaining_is_ignored(superadmin_client, existing_membership):
    """
    remaining больше нельзя выставить руками — сериализатор его не принимает,
    PATCH с этим полем в теле не должен ничего сломать и не должен повлиять
    на вычисляемое значение в ответе.
    """
    resp = superadmin_client.patch(
        f"{BASE_URL}/{existing_membership['id']}",
        {'remaining': 999},
        format='json',
    )
    assert resp.status_code == 200
    assert resp.json()['remaining'] != 999
```

- [ ] **Step 7: Обновить `test_individual_group_limit.py`**

В `journal_django/apps/memberships/tests/test_individual_group_limit.py` заменить `_insert_inactive` (строки 105-112):

```python
def _insert_inactive(group_id: int, student_id: int) -> int:
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO group_memberships (group_id, student_id, lessons_done, active) '
            'VALUES (%s, %s, 0, false) RETURNING id',
            [group_id, student_id],
        )
        return cur.fetchone()[0]
```

- [ ] **Step 8: Прогнать все тесты memberships**

Run: `cd journal_django && .venv\Scripts\python.exe -m pytest apps/memberships/ -v`
Expected: PASS — все тесты, включая `test_patch_remaining_is_ignored`.

- [ ] **Step 9: Commit**

```bash
git add journal_django/apps/memberships/
git commit -m "feat(memberships): compute remaining from student balance, drop manual write"
```

---

## Task 3: `apps/teacher_spa` — вычисляемый `remaining` в `read_all_students`

**Files:**
- Modify: `journal_django/apps/teacher_spa/repository.py:13-28, 73-156`
- Modify: `journal_django/apps/teacher_spa/tests/conftest.py:154-187` (`membership_fixture`, `half_membership_fixture`)
- Test: `journal_django/apps/teacher_spa/tests/test_teacher_spa_repository.py:41-123`
- Test: `journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py:293-304`

- [ ] **Step 1: Обновить фикстуры — убрать remaining из raw INSERT**

В `journal_django/apps/teacher_spa/tests/conftest.py` заменить `membership_fixture` (строки 154-169):

```python
@pytest.fixture
def membership_fixture(group_fixture, student_fixture):
    """Создаёт membership для group_fixture + student_fixture."""
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO group_memberships (group_id, student_id, lessons_done, active)
            VALUES (%s, %s, 0, true)
            RETURNING id
            """,
            [group_fixture, student_fixture],
        )
        membership_id = cur.fetchone()[0]
    yield membership_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])
```

и `half_membership_fixture` (строки 172-187) — тем же паттерном:

```python
@pytest.fixture
def half_membership_fixture(half_group_fixture, student_fixture):
    """Membership для half_group_fixture."""
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO group_memberships (group_id, student_id, lessons_done, active)
            VALUES (%s, %s, 0, true)
            RETURNING id
            """,
            [half_group_fixture, student_fixture],
        )
        membership_id = cur.fetchone()[0]
    yield membership_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])
```

- [ ] **Step 2: Обновить ожидание в `test_student_fields` (падающий тест — старое значение больше не верно)**

В `journal_django/apps/teacher_spa/tests/test_teacher_spa_repository.py` заменить строку 80:

```python
        # lessonsDone=0 в фикстуре → 0 (JS Number()||0)
        assert stu['lessonsDone'] == 0
        # remaining — вычисляемый общий баланс ученика (нет оплат/посещений) → 0
        assert stu['remaining'] == 0
```

Также заменить 2 raw INSERT в `test_lessons_done_max` (строки 95-101, 104-111):

```python
            cur.execute(
                """
                INSERT INTO group_memberships (group_id, student_id, lessons_done, active)
                VALUES (%s, %s, 5, true) RETURNING id
                """,
                [group_fixture, stu2_id],
            )
            mem2_id = cur.fetchone()[0]
            # Первый ученик без membership — создаём с lessons_done=2
            cur.execute(
                """
                INSERT INTO group_memberships (group_id, student_id, lessons_done, active)
                VALUES (%s, %s, 2, true) RETURNING id
                """,
                [group_fixture, student_fixture],
            )
```

- [ ] **Step 3: Убедиться, что тест падает (репозиторий ещё читает старую колонку)**

Run: `cd journal_django && .venv\Scripts\python.exe -m pytest apps/teacher_spa/tests/test_teacher_spa_repository.py -v -k test_student_fields`
Expected: FAIL — `assert stu['remaining'] == 0` не проходит (репозиторий пока возвращает сырое `10`/значение из INSERT, а INSERT теперь его не пишет вовсе → колонка дефолтится в 0 на уровне БД, так что тест может неожиданно пройти уже на этом шаге за счёт DEFAULT; если это произошло — это нормально, DEFAULT совпал с ожидаемым вычисляемым значением случайно, переходим к Step 4 всё равно, чтобы реализация была верной по сути, а не по совпадению).

- [ ] **Step 4: Переключить `read_all_students` на батч-вычисление**

В `journal_django/apps/teacher_spa/repository.py` добавить импорт (после строки 27, `from apps.teachers.models import Teacher`):

```python
from apps.finances.repository import balances_for_students
```

Заменить `read_all_students` (строки 73-156):

```python
def read_all_students() -> dict:
    """
    Возвращает {'data': {teacher: {group: groupData}}, 'index': {...}}.

    Только активные membership/группы/преподаватели. ORDER te.name, g.name, s.full_name.
    remaining — вычисляемый общий баланс ученика (apps.finances), не хранимая колонка;
    считается одним батч-запросом на всех учеников выборки (без N+1).
    """
    rows = list(
        GroupMembership.objects
        .filter(active=True, group__active=True, group__teacher__active=True)
        .order_by('group__teacher__name', 'group__name', 'student__full_name')
        .values(
            'group_id', 'student_id', 'lessons_done', 'sheet_row',
            group_name=F('group__name'),
            is_individual=F('group__is_individual'),
            vk_chat=F('group__vk_chat'),
            group_start_date=F('group__group_start_date'),
            teacher_name=F('group__teacher__name'),
            student_name=F('student__full_name'),
            age=F('student__age'),
            pm=F('student__pm'),
            membership_id=F('id'),
        )
    )

    balances = balances_for_students({r['student_id'] for r in rows})

    data: dict = {}
    index: dict = {}

    for r in rows:
        teacher = r['teacher_name']
        group = r['group_name']
        # Legacy Google Sheets поле direction.sheet_name удалено (раздел 05).
        # sheetName/sheetRow — вестигиальные поля, фронт их больше не читает по
        # значению; сохраняем ключ и осмысленный маркер «Индивидуальные».
        sheet_name = 'Индивидуальные' if r['is_individual'] else ''

        if teacher not in data:
            data[teacher] = {}
        if group not in data[teacher]:
            data[teacher][group] = {
                'students': [],
                'lessonsDone': 0,
                'pm': r['pm'] or '',
                'vkChat': r['vk_chat'] or '',
                'startDate': fmt_date_ru(r['group_start_date']),
                'isGroup': not r['is_individual'],
            }

        grp = data[teacher][group]

        # lessons_done — Number(x)||0 (None → 0); Decimal → int/float
        raw_done = r['lessons_done']
        if raw_done is None:
            done = 0
        else:
            f = float(raw_done)
            done = int(f) if f == int(f) else f

        remaining = balances[r['student_id']]

        if done > grp['lessonsDone']:
            grp['lessonsDone'] = done

        grp['students'].append({
            'name': r['student_name'],
            'lessonsDone': done,
            'remaining': remaining,
            'age': str(r['age']) if r['age'] is not None else '',
            'sheetName': sheet_name,
            'sheetRow': r['sheet_row'] or 0,
        })

        if r['sheet_row']:
            index[r['student_name'] + '|||' + group] = {
                'sheetName': sheet_name,
                'sheetRow': r['sheet_row'],
            }

    return {'data': data, 'index': index}
```

- [ ] **Step 5: Обновить raw INSERT в `test_teacher_spa_api.py`**

В `journal_django/apps/teacher_spa/tests/test_teacher_spa_api.py` заменить строки 299-303:

```python
            cur.execute(
                "INSERT INTO group_memberships (group_id,student_id,lessons_done,active) "
                "VALUES (%s,%s,0,true) RETURNING id",
                [gid, student_fixture],
            )
```

- [ ] **Step 6: Прогнать тесты teacher_spa**

Run: `cd journal_django && .venv\Scripts\python.exe -m pytest apps/teacher_spa/ -v`
Expected: PASS — все тесты, включая `test_student_fields` (`remaining == 0`) и `test_lessons_done_max`.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/teacher_spa/
git commit -m "feat(teacher_spa): compute remaining via batched student balance"
```

---

## Task 4: `apps/students` — вычисляемый `remaining` в `student_stats`

**Files:**
- Modify: `journal_django/apps/students/repository.py:9-18, 227-330`
- Test: `journal_django/apps/students/tests/test_students_repository.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `journal_django/apps/students/tests/test_students_repository.py` (после класса `TestStudentStats`, перед `TestGetStudentBalance`):

```python
@pytest.mark.django_db
class TestStudentStatsRemaining:
    """remaining в group_stats — вычисляемый общий баланс ученика (не колонка gm.remaining)."""

    def test_group_remaining_matches_balance_for_student(self):
        from apps.finances.repository import balance_for_student

        data = _make_student_data(full_name='__test_stats_remaining__')
        student = repository.create_student(data)
        sid = student['id']
        direction_id = group_id = teacher_id = None
        try:
            with connection.cursor() as cur:
                cur.execute(
                    "INSERT INTO teachers (name, active) VALUES ('__stats_rem_teacher__', true) "
                    "RETURNING id"
                )
                teacher_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO directions (name, is_individual, active) "
                    "VALUES ('__stats_rem_dir__', false, true) RETURNING id"
                )
                direction_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
                    "lesson_duration_minutes, active) "
                    "VALUES ('__stats_rem_group__', %s, %s, false, 60, true) RETURNING id",
                    [direction_id, teacher_id],
                )
                group_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                    "VALUES (%s, %s, 0, true)",
                    [group_id, sid],
                )
                cur.execute(
                    "INSERT INTO payments (student_id, direction_id, subscriptions_count, "
                    "unit_price, total_amount, paid_at, created_by) "
                    "VALUES (%s,%s,1,500,2000,'2026-06-01','test')",
                    [sid, direction_id],
                )

            result = repository.student_stats(sid)
            assert len(result['groups']) == 1
            assert result['groups'][0]['remaining'] == balance_for_student(sid) == 4
        finally:
            with connection.cursor() as cur:
                if group_id is not None:
                    cur.execute('DELETE FROM payments WHERE student_id = %s', [sid])
                    cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [group_id])
                    cur.execute('DELETE FROM groups WHERE id = %s', [group_id])
                if direction_id is not None:
                    cur.execute('DELETE FROM directions WHERE id = %s', [direction_id])
                if teacher_id is not None:
                    cur.execute('DELETE FROM teachers WHERE id = %s', [teacher_id])
            _cleanup_student(sid)
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd journal_django && .venv\Scripts\python.exe -m pytest apps/students/tests/test_students_repository.py -v -k test_group_remaining_matches_balance_for_student`
Expected: FAIL — `assert result['groups'][0]['remaining'] == balance_for_student(sid) == 4` не проходит (сырое `gm.remaining` сейчас 0 по умолчанию, а не 4).

- [ ] **Step 3: Переключить `student_stats` на вычисляемый `remaining`**

В `journal_django/apps/students/repository.py` добавить импорт (после строки 16, `from apps.core.utils.orm import dictrow, dictrows`):

```python
from apps.finances.repository import balance_for_student
```

В SQL внутри `student_stats` убрать `gm.remaining,` из SELECT (строка 241) и из GROUP BY (строка 272):

Было:
```python
             SELECT gm.id AS membership_id,
                    gm.group_id,
                    gm.lessons_done,
                    gm.remaining,
                    gm.active AS membership_active,
```
```python
              GROUP BY gm.id, gm.group_id, gm.lessons_done, gm.remaining, gm.active,
                       g.name, g.is_individual, g.lesson_duration_minutes,
                       d.id, d.name, d.color, d.total_lessons, te.name, te.id
```

Стало:
```python
             SELECT gm.id AS membership_id,
                    gm.group_id,
                    gm.lessons_done,
                    gm.active AS membership_active,
```
```python
              GROUP BY gm.id, gm.group_id, gm.lessons_done, gm.active,
                       g.name, g.is_individual, g.lesson_duration_minutes,
                       d.id, d.name, d.color, d.total_lessons, te.name, te.id
```

Перед циклом `for r in groups_raw:` (строка 293) добавить:

```python
    student_balance = balance_for_student(student_id)
```

В теле цикла заменить строку `'remaining': r['remaining'],` на:

```python
            'remaining':               student_balance,
```

- [ ] **Step 4: Прогнать тесты students**

Run: `cd journal_django && .venv\Scripts\python.exe -m pytest apps/students/tests/test_students_repository.py -v`
Expected: PASS — включая `test_group_remaining_matches_balance_for_student` и все существующие тесты `TestStudentStats`.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/students/
git commit -m "feat(students): compute remaining in student_stats from student balance"
```

---

## Task 5: `apps/groups/importers/direction_history.py` — убрать мёртвую запись

**Files:**
- Modify: `journal_django/apps/groups/importers/direction_history.py:287-293`
- Test: `journal_django/apps/groups/tests/test_direction_history_importer.py:492-499`

- [ ] **Step 1: Убрать `'remaining': 0` из defaults архивной membership**

В `journal_django/apps/groups/importers/direction_history.py` заменить (строки 287-293):

```python
                GroupMembership.objects.update_or_create(
                    group=group, student=student,
                    defaults={
                        'lessons_done': lessons_count,
                        'active': False, 'start_date': LEGACY_LESSON_DATE,
                    },
                )
```

- [ ] **Step 2: Обновить тестовый хелпер `_make_membership`**

В `journal_django/apps/groups/tests/test_direction_history_importer.py` заменить (строки 492-499):

```python
def _make_membership(group_id, student_id, active=True):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s, %s, 0, %s) RETURNING id",
            [group_id, student_id, active],
        )
        return cur.fetchone()[0]
```

- [ ] **Step 3: Прогнать тесты importer'а**

Run: `cd journal_django && .venv\Scripts\python.exe -m pytest apps/groups/tests/test_direction_history_importer.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add journal_django/apps/groups/importers/direction_history.py journal_django/apps/groups/tests/test_direction_history_importer.py
git commit -m "chore(groups): drop dead remaining=0 write in direction history importer"
```

---

## Task 6: Зачистить `remaining` в фикстурах несвязанных приложений

Эти файлы не читают/не пишут `remaining` в прикладной логике — просто сеют тестовые строки `group_memberships` через raw SQL и попутно проставляли `remaining`. Правки чисто механические, нужны только потому, что колонка исчезнет в Task 7.

**Files:**
- Modify: `journal_django/apps/renewals/tests/test_rebuild.py:16-17`
- Modify: `journal_django/apps/renewals/tests/test_lesson_progress.py:26-27`
- Modify: `journal_django/apps/lessons/tests/conftest.py:80-94`
- Modify: `journal_django/apps/lessons/tests/test_lessons_orm_smoke.py:35-36`
- Modify: `journal_django/apps/payments/tests/conftest.py:101-114`

- [ ] **Step 1: `test_rebuild.py`**

Заменить строки 16-17:

```python
        cur.execute("INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                    "VALUES (%s,%s,0,true)", [gid, sid])
```

- [ ] **Step 2: `test_lesson_progress.py`**

Заменить строки 26-27:

```python
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s, %s, %s, true)", [group_id, student_id, lessons_done])
```

- [ ] **Step 3: `apps/lessons/tests/conftest.py`**

Заменить `membership_fixture` (строки 80-94):

```python
@pytest.fixture
def membership_fixture(group_fixture, student_fixture):
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO group_memberships (group_id, student_id, lessons_done, active)
            VALUES (%s, %s, 0, true)
            RETURNING id
            """,
            [group_fixture, student_fixture],
        )
        membership_id = cur.fetchone()[0]
    yield membership_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])
```

- [ ] **Step 4: `test_lessons_orm_smoke.py`**

Заменить строки 35-36:

```python
    GroupMembership.objects.create(group_id=g.id, student_id=s1.id, lessons_done=0)
    GroupMembership.objects.create(group_id=g.id, student_id=s2.id, lessons_done=0)
```

- [ ] **Step 5: `apps/payments/tests/conftest.py`**

Заменить `membership_fixture` (строки 101-114, INSERT-часть):

```python
@pytest.fixture
def membership_fixture(group_fixture, student_fixture):
    """Участие ученика в группе."""
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO group_memberships (group_id, student_id, lessons_done, active)
            VALUES (%s, %s, 0, true)
            RETURNING id
            """,
            [group_fixture, student_fixture],
        )
        membership_id = cur.fetchone()[0]
```

- [ ] **Step 6: Прогнать тесты всех пяти приложений**

Run: `cd journal_django && .venv\Scripts\python.exe -m pytest apps/renewals/ apps/lessons/ apps/payments/ -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/renewals/tests/ journal_django/apps/lessons/tests/ journal_django/apps/payments/tests/
git commit -m "chore(tests): drop dead remaining column from unrelated fixtures"
```

---

## Task 7: Снести колонку `remaining` миграцией + полный прогон

**Files:**
- Modify: `journal_django/apps/memberships/models.py:42`
- Create: `journal_django/apps/memberships/migrations/0003_*.py` (автогенерируется)

- [ ] **Step 1: Убрать поле из модели**

В `journal_django/apps/memberships/models.py` удалить строку 42:

```python
    remaining = models.DecimalField(max_digits=6, decimal_places=1, default=0)
```

(остаётся только `lessons_done = models.DecimalField(max_digits=6, decimal_places=1, default=0)` перед `start_date`).

- [ ] **Step 2: Сгенерировать миграцию**

Run: `cd journal_django && .venv\Scripts\python.exe manage.py makemigrations memberships`
Expected: создан файл `apps/memberships/migrations/0003_remove_groupmembership_remaining_and_more.py` (имя может отличаться в деталях — Django генерирует его по содержимому).

- [ ] **Step 3: Проверить содержимое сгенерированной миграции**

Открыть новый файл и убедиться, что операции покрывают:
- `RemoveField(model_name='groupmembership', name='remaining')`
- `RemoveField(model_name='groupmembershipevent', name='remaining')`
- `RemoveTrigger` + `AddTrigger` для `insert_insert`, `update_update`, `delete_delete` на `groupmembership` (pghistory должен пересобрать SQL триггеров без упоминания `remaining` — сверить по образцу `apps/memberships/migrations/0002_...py`, где эти триггеры создавались С `remaining` в списке колонок).

Если каких-то из этих операций нет — не продолжать: значит, что-то в модели/коде ещё ссылается на поле, и `makemigrations` увидел его по-другому. В этом случае найти источник рассинхрона (`grep -rn "remaining" journal_django/apps/memberships/models.py`) прежде чем мигрировать.

- [ ] **Step 4: Применить миграцию к dev-БД**

Run: `cd journal_django && .venv\Scripts\python.exe manage.py migrate memberships`
Expected: `Applying memberships.0003_...... OK`

- [ ] **Step 5: Прогнать весь тестовый набор**

Run: `cd journal_django && .venv\Scripts\python.exe -m pytest`
Expected: PASS — весь набор зелёный (pytest-django поднимет/промигрирует `journal_test` автоматически на этом прогоне).

Если что-то падает с `column "remaining" of relation "group_memberships" does not exist` — значит остался необнаруженный raw SQL с этой колонкой; найти через `grep -rn "remaining" journal_django/apps --include=*.py` и почистить по аналогии с Task 6.

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/memberships/models.py journal_django/apps/memberships/migrations/
git commit -m "feat(memberships): drop stored remaining column, fully computed now"
```

### Deployment order (Beget VPS, ручной деплой без CI)

`RemoveField` — это contract-фаза expand/contract миграции: код Tasks 1-6 уже не читает и не пишет колонку, но старые воркеры (до перезапуска) её ещё ожидают. Порядок обязателен:

1. Задеплоить код (Tasks 1-7) и перезапустить gunicorn — новый код колонку не трогает, работает и пока она физически ещё есть в БД.
2. Только после этого — `manage.py migrate memberships`.

Наоборот (сначала мигрировать, потом деплоить) — старые воркеры, ещё не перезапущенные, обратятся к `remaining` и получат 500 до перезапуска. Откат безопасен: `RemoveField` реверсируется в `AddField(default=0)` — колонка восстановится (со значением по умолчанию, старые значения не восстановятся, это ожидаемо).

---

## Self-Review Notes

- **Spec coverage:** §1 (батч-калькулятор) → Task 1. §2 (переключить memberships/teacher_spa/students) → Tasks 2-4. §3 (убрать PATCH-поле + снести колонку) → Tasks 2, 7. §4 (admin-фронт без изменений) → ничего не делаем, сверено. §5 (тесты) → Tasks 1-6 покрывают весь список файлов из спеки.
- **Placeholder scan:** нет TBD/TODO, весь код — реальные диффы с точными путями и номерами строк.
- **Type consistency:** `balances_for_students` возвращает `dict[int, int | float]` везде, где вызывается (`memberships/repository.py`, `teacher_spa/repository.py`) — сигнатура не меняется между задачами.
- **Scope:** одна фича (замена хранимого поля на вычисляемое), декомпозиции на подпроекты не требует — задачи следуют зависимостям (сначала общий калькулятор, потом три читателя, потом схема).
