# Многократный перевод (A→Б→В→...) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Число уроков в плашке membership и в матрице посещаемости для переведённого ученика должно быть суммой по ВСЕЙ цепочке переводов (А→Б→В→...), а не только по последнему хопу — без изменения схемы БД.

**Architecture:** Новая функция `apps.memberships.repository.cumulative_transferred_lessons(transferred_from_id)` обходит существующую self-FK цепочку `GroupMembership.transferred_from` назад, суммируя `lessons_done`, с защитой от цикла (реактивация membership при возврате в старую группу технически может зациклить цепочку). Два существующих потребителя (`memberships.repository` — плашка, `groups.repository.get_group_progress` — матрица) переключаются с одиночного F()-джойна на вызов этой функции.

**Tech Stack:** Django 5 ORM (`journal_django/apps/memberships`, `journal_django/apps/groups`), pytest-django.

**Design doc:** [`docs/superpowers/specs/2026-07-13-transfer-progress-matrix-design.md`](../specs/2026-07-13-transfer-progress-matrix-design.md), раздел «Дополнение: многократный перевод (A→Б→В→...)».

---

## Task 1: `cumulative_transferred_lessons` + плашка membership

**Files:**
- Modify: `journal_django/apps/memberships/repository.py`
- Modify: `journal_django/apps/memberships/tests/test_transfer_membership.py`

- [ ] **Step 1: Написать failing-тест на цепочку из двух переводов**

В `journal_django/apps/memberships/tests/test_transfer_membership.py`, добавить в конец файла. Использует уже существующие `seed`/`repository` из этого файла (`seed['group_a1']`, `seed['group_a2']`, `seed['s1']`, `seed['teacher_id']`, `seed['direction_a']`) — фикстура `seed` определена в начале этого же файла. Для третьей группы цепочки — `groups_repo.create_group` (импорт `from apps.groups import repository as groups_repo` внутри теста, по аналогии с другими тестами этого файла):

```python


@pytest.mark.django_db
def test_transfer_chain_sums_lessons_across_multiple_hops(seed):
    """
    А(20 уроков, seed['group_a1']) → Б(4 урока, seed['group_a2']) → В (новая группа
    того же направления). В В: transferred_from_lessons_done = 20+4=24 (сумма
    по всей цепочке), transferred_from_group_name = имя Б (непосредственный
    источник, не А).
    """
    from apps.groups import repository as groups_repo

    group_a3 = groups_repo.create_group({
        'name': '__tr_group_a3__', 'direction_id': seed['direction_a'], 'teacher_id': seed['teacher_id'],
        'is_individual': False, 'lesson_duration_minutes': 90, 'lessons_per_week': 1,
    })
    try:
        m_a = repository.add_membership({
            'group_id': seed['group_a1'], 'student_id': seed['s1'], 'lessons_done': 20,
        })
        m_b = repository.transfer_membership(m_a['id'], seed['group_a2'])
        repository.update_membership(m_b['id'], {'lessons_done': 4})
        m_c = repository.transfer_membership(m_b['id'], group_a3['id'])

        assert float(m_c['transferred_from_lessons_done']) == 24.0
        assert m_c['transferred_from_group_name'] == '__tr_group_a2__'
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [group_a3['id']])
            cur.execute('DELETE FROM groups WHERE id = %s', [group_a3['id']])


@pytest.mark.django_db
def test_transfer_chain_cycle_does_not_hang(seed):
    """
    А→Б→В→А обратно (реактивация исходной membership А) — цепочка технически
    зацикливается (А.transferred_from → В → Б → А). Функция должна вернуться
    за конечное время, не бросив исключение и не зависнув.
    """
    m_a = repository.add_membership({
        'group_id': seed['group_a1'], 'student_id': seed['s1'], 'lessons_done': 10,
    })
    m_b = repository.transfer_membership(m_a['id'], seed['group_a2'])
    m_c = repository.transfer_membership(m_b['id'], seed['group_a_individual'])
    # Назад в А — тот же студент, та же пара (group_a1, s1) реактивируется (id == m_a['id']).
    m_back = repository.transfer_membership(m_c['id'], seed['group_a1'])

    assert m_back['id'] == m_a['id']
    # Не зависает — сумма конечна (best-effort, цикл прерывается по seen-множеству).
    assert isinstance(float(m_back['transferred_from_lessons_done']), float)
```

Запустить (из `journal_django/`):
```bash
.venv/Scripts/python.exe -m pytest apps/memberships/tests/test_transfer_membership.py -q -k "chain"
```
Expected: `test_transfer_chain_sums_lessons_across_multiple_hops` — FAIL, `assert 4.0 == 24.0` (сейчас `transferred_from_lessons_done` считается старым одиночным F()-джойном — берётся только последний хоп, Б=4, а не сумма 20+4=24; это и есть настоящий failing-тест, доказывающий баг). `test_transfer_chain_cycle_does_not_hang` — должен ПРОЙТИ уже сейчас (до фикса): цикл в цепочке `transferred_from` — свойство данных, которое создаёт уже существующий `transfer_membership` независимо от этой задачи; текущий код НЕ обходит цепочку (одиночный F()-джойн), поэтому зависнуть не может — тест здесь как контроль, который должен остаться зелёным и после Step 2 (когда появится реальный обход с риском зацикливания). Если этот тест почему-то падает уже на этом шаге — исследовать отдельно, не игнорировать.

- [ ] **Step 2: Добавить `cumulative_transferred_lessons`**

В `journal_django/apps/memberships/repository.py` заменить импорт (строка 12):
```python
import datetime as _dt
from typing import Any, Optional
```
на:
```python
import datetime as _dt
from decimal import Decimal
from typing import Any, Optional
```

Добавить после блока `_MEMBERSHIP_FIELDS` (после строки 36, перед `# ---------------------------------------------------------------------------\n# Helpers`):

```python

_MAX_TRANSFER_CHAIN = 20  # защитный лимит — реальные цепочки в разы короче


def cumulative_transferred_lessons(transferred_from_id: Optional[int]) -> Decimal:
    """
    Сумма lessons_done по всей цепочке переводов, начиная с transferred_from_id
    (сама текущая membership НЕ включается — только предки).

    Ученика могут перевести несколько раз подряд (А→Б→В→...) — transferred_from
    каждой membership указывает на непосредственно предыдущую, образуя связный
    список; функция проходит его назад до конца.

    Защита от цикла: если ученика переводят обратно в группу, где он уже был
    раньше в этой же цепочке, add_membership-паттерн (ON CONFLICT DO UPDATE)
    РЕАКТИВИРУЕТ старую membership-строку той же группы и перезаписывает её
    transferred_from на текущую — из-за этого цепочка технически может
    зациклиться (А.transferred_from → В → Б → А). `seen`-множество и
    _MAX_TRANSFER_CHAIN останавливают обход, не давая ему повиснуть; результат
    в этом редком случае — best-effort сумма до точки повторного визита, не
    гарантированно полная, но и не бесконечный цикл.
    """
    total = Decimal('0')
    seen: set[int] = set()
    current_id = transferred_from_id
    while current_id is not None and current_id not in seen and len(seen) < _MAX_TRANSFER_CHAIN:
        seen.add(current_id)
        row = (
            GroupMembership.objects
            .filter(id=current_id)
            .values('lessons_done', 'transferred_from_id')
            .first()
        )
        if row is None:
            break
        total += row['lessons_done'] or Decimal('0')
        current_id = row['transferred_from_id']
    return total
```

- [ ] **Step 3: Переключить `_membership_row` и `list_memberships` на новую функцию**

Заменить `_membership_row` (текущий код):
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
на:
```python
def _membership_row(membership_id: int) -> Optional[dict]:
    """Строка membership (gm.* / RETURNING *) с нормализованной датой и вычисленным remaining."""
    row = _normalize_dates(
        dictrow(
            GroupMembership.objects.filter(id=membership_id).values(
                *_MEMBERSHIP_FIELDS,
                transferred_from_group_name=F('transferred_from__group__name'),
            )
        )
    )
    if row is not None:
        row['remaining'] = balance_for_student(row['student_id'])
        row['transferred_from_lessons_done'] = (
            cumulative_transferred_lessons(row['transferred_from_id'])
            if row['transferred_from_id'] else None
        )
    return row
```

В `list_memberships`, заменить:
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
    balances = balances_for_students({row['student_id'] for row in rows})
    for row in rows:
        _normalize_dates(row)
        row['remaining'] = balances[row['student_id']]
    return rows
```
на:
```python
    rows = dictrows(
        qs.order_by('group__name', 'student__full_name').values(
            *_MEMBERSHIP_FIELDS,
            group_name=F('group__name'),
            student_name=F('student__full_name'),
            transferred_from_group_name=F('transferred_from__group__name'),
        )
    )
    balances = balances_for_students({row['student_id'] for row in rows})
    for row in rows:
        _normalize_dates(row)
        row['remaining'] = balances[row['student_id']]
        row['transferred_from_lessons_done'] = (
            cumulative_transferred_lessons(row['transferred_from_id'])
            if row['transferred_from_id'] else None
        )
    return rows
```

(Если фактическое содержимое `list_memberships` в файле немного отличается от процитированного — например, порядок строк — искать по неизменному якорю `transferred_from_lessons_done=F('transferred_from__lessons_done')` и заменять именно эту F()-аннотацию на пост-обработку в цикле, сохраняя остальную структуру функции.)

- [ ] **Step 4: Прогнать тесты, убедиться что проходят**

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/memberships/tests/test_transfer_membership.py -q
```
Expected: PASS (весь файл, включая 2 новых теста).

- [ ] **Step 5: Прогнать весь набор memberships на регрессию**

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/memberships -q
```
Expected: PASS, без регрессий (в частности `test_transfer_superadmin_200` в `test_transfer_membership.py`, который проверяет `transferred_from_lessons_done` в API-ответе на одиночном переводе — должен по-прежнему пройти: цепочка из одного хопа суммируется в то же самое число, что и раньше).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/memberships/repository.py journal_django/apps/memberships/tests/test_transfer_membership.py
git commit -m "feat(memberships): sum lessons across full transfer chain, not just one hop"
```

---

## Task 2: Матрица посещаемости — та же цепочка

**Files:**
- Modify: `journal_django/apps/groups/repository.py`
- Modify: `journal_django/apps/groups/tests/test_progress_api.py`

- [ ] **Step 1: Написать failing-тест**

В `journal_django/apps/groups/tests/test_progress_api.py`, добавить в класс `TestTransferredLessons` (в конец класса, тем же уровнем отступа что и остальные методы):

```python

    def test_multi_hop_chain_sums_lessons(self, manager_client, progress_group):
        """
        Боря: А(3 урока, архивная) → Б(2 урока, архивная) → текущая группа
        (progress_group, total_slots=8). transferred_lessons = min(3+2, 8) = 5 —
        сумма по всей цепочке, без капа (5 < 8), источник — Б (не А).
        """
        gid = progress_group['group_id']
        with connection.cursor() as cur:
            cur.execute("SELECT direction_id, teacher_id FROM groups WHERE id = %s", [gid])
            direction_id, teacher_id = cur.fetchone()
            cur.execute(
                "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                "lesson_duration_minutes,active) VALUES ('__pg_chain_a__',%s,%s,false,60,false) "
                "RETURNING id",
                [direction_id, teacher_id],
            )
            group_a = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                "lesson_duration_minutes,active) VALUES ('__pg_chain_b__',%s,%s,false,60,false) "
                "RETURNING id",
                [direction_id, teacher_id],
            )
            group_b = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                "VALUES (%s,%s,3,false) RETURNING id",
                [group_a, progress_group['borya']],
            )
            membership_a = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO group_memberships (group_id, student_id, lessons_done, active, transferred_from_id) "
                "VALUES (%s,%s,2,false,%s) RETURNING id",
                [group_b, progress_group['borya'], membership_a],
            )
            membership_b = cur.fetchone()[0]
            cur.execute(
                "UPDATE group_memberships SET transferred_from_id = %s "
                "WHERE group_id = %s AND student_id = %s",
                [membership_b, gid, progress_group['borya']],
            )
        try:
            body = manager_client.get(_url(gid)).json()
            rows = {r['student_id']: r for r in body['students']}
            assert rows[progress_group['borya']]['transferred_lessons'] == 5  # 3+2, не капается (< total_slots=8)
            assert rows[progress_group['borya']]['transferred_from_group_name'] == '__pg_chain_b__'
        finally:
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE group_memberships SET transferred_from_id = NULL "
                    "WHERE group_id = %s AND student_id = %s",
                    [gid, progress_group['borya']],
                )
                cur.execute('DELETE FROM group_memberships WHERE group_id IN (%s, %s)', [group_a, group_b])
                cur.execute('DELETE FROM groups WHERE id IN (%s, %s)', [group_a, group_b])
```

Запустить:
```bash
.venv/Scripts/python.exe -m pytest apps/groups/tests/test_progress_api.py -q -k multi_hop
```
Expected: FAIL — `assert 2 == 5` (сейчас берётся только последний хоп — 2 урока из Б, а не сумма 3+2=5).

- [ ] **Step 2: Переключить `get_group_progress` на `cumulative_transferred_lessons`**

В `journal_django/apps/groups/repository.py`:

Заменить запрос `members`:
```python
    members = list(
        GroupMembership.objects
        .filter(group_id=group_id, active=True)
        .order_by('student__full_name')
        .values(
            'student_id', 'transferred_from_id', name=F('student__full_name'),
            transferred_from_lessons_done=F('transferred_from__lessons_done'),
            transferred_from_group_name=F('transferred_from__group__name'),
        )
    )
```
на:
```python
    members = list(
        GroupMembership.objects
        .filter(group_id=group_id, active=True)
        .order_by('student__full_name')
        .values(
            'student_id', 'transferred_from_id', name=F('student__full_name'),
            transferred_from_group_name=F('transferred_from__group__name'),
        )
    )
```

Заменить блок расчёта `transferred_lessons`:
```python
        transferred_lessons = 0
        transferred_from_group_name = None
        if member['transferred_from_id']:
            transferred_lessons = min(
                math.floor(float(member['transferred_from_lessons_done'] or 0)),
                slot_count,
            )
            if transferred_lessons > 0:
                transferred_from_group_name = member['transferred_from_group_name']
```
на:
```python
        transferred_lessons = 0
        transferred_from_group_name = None
        if member['transferred_from_id']:
            cumulative = cumulative_transferred_lessons(member['transferred_from_id'])
            transferred_lessons = min(math.floor(float(cumulative)), slot_count)
            if transferred_lessons > 0:
                transferred_from_group_name = member['transferred_from_group_name']
```

Добавить импорт функции. Найти строку `from apps.memberships.models import GroupMembership` внутри тела `get_group_progress` (локальный импорт, не на уровне модуля — см. начало функции рядом с `import math`) и заменить на:
```python
    from apps.memberships.models import GroupMembership
    from apps.memberships.repository import cumulative_transferred_lessons
```

- [ ] **Step 3: Прогнать тесты, убедиться что проходят**

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/groups/tests/test_progress_api.py -q
```
Expected: PASS (весь файл, включая новый тест и ранее написанные `TestTransferredLessons`-тесты — они по-прежнему проходят: одиночный хоп суммируется в то же число, что и раньше).

- [ ] **Step 4: Прогнать groups + teacher_spa на регрессию**

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/groups apps/teacher_spa -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/groups/repository.py journal_django/apps/groups/tests/test_progress_api.py
git commit -m "feat(groups): sum transferred lessons across full chain in progress matrix"
```

---

## Task 3: Финальная проверка

**Files:** нет изменений.

- [ ] **Step 1: Полный backend-набор**

Run (из `journal_django/`):
```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: все тесты зелёные.

- [ ] **Step 2: Финальный typecheck фронта (контракт API не менялся по форме — только источник чисел на бэкенде, TS-типы не трогаем)**

Run (из `journal_django/frontend/admin-src`):
```bash
npm run typecheck
```
Expected: без ошибок (эта задача не трогает фронтенд-файлы вовсе).
