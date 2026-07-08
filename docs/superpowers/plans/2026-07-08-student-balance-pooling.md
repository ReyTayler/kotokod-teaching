# Общий пул баланса ученика (отвязка списания от направления) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Списание уроков идёт одним общим FIFO-пулом на ученика (не по направлению); `payments.direction_id` становится информационным тегом; баланс, дашборд и карточка сделки продления пересчитываются под новую модель.

**Architecture:** Меняем ключ группировки в `apps/finances/repository.py::fifo_inputs()` с `"student_id:direction_id"` на `student_id`; `compute_fifo()` получает новый выход `worked_off_by_direction` (атрибуция по направлению урока, не оплаты); баланс-агрегаты (`balance_for_student`, `paid_by_direction_rows`, `attended_by_direction_rows`) заменяют старые per-direction. Все даунстрим-потребители (`apps/payments`, `apps/dashboard`, `apps/renewals`, фронтенд) переключаются на новые функции/формы ответа. Схема БД не меняется — миграций нет.

**Tech Stack:** Django ORM (managed=False поверх продовой PostgreSQL), pytest + pytest-django, React 19 + TanStack Query v5 (admin SPA), TypeScript.

**Spec:** [docs/superpowers/specs/2026-07-08-student-balance-pooling-design.md](../specs/2026-07-08-student-balance-pooling-design.md)

---

### Task 1: FIFO — атрибуция `worked_off_by_direction`

**Files:**
- Modify: `journal_django/apps/finances/fifo.py`
- Test: `journal_django/apps/finances/tests/test_fifo.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `journal_django/apps/finances/tests/test_fifo.py`:

```python
def test_worked_off_by_direction():
    lots = [
        {'lessons': 4, 'price_per_lesson': _D(500)},
        {'lessons': 4, 'price_per_lesson': _D(450)},
    ]
    cons = [
        {'units': 1, 'date': '2026-06-10', 'direction_id': 1},
        {'units': 1, 'date': '2026-06-11', 'direction_id': 1},
        {'units': 1, 'date': '2026-06-12', 'direction_id': 2},
    ]
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_direction'][1] == _D('1000.00')
    assert r['worked_off_by_direction'][2] == _D('500.00')


def test_worked_off_by_direction_absent_key_is_ignored():
    # Golden-кейсы выше не передают direction_id — не должно падать, просто {}.
    lots = [{'lessons': 4, 'price_per_lesson': _D(500)}]
    cons = _lessons(2, '2026-06-10')
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_direction'] == {}
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd journal_django && pytest apps/finances/tests/test_fifo.py -v`
Expected: `test_worked_off_by_direction` и `test_worked_off_by_direction_absent_key_is_ignored` — FAIL с `KeyError: 'worked_off_by_direction'`.

- [ ] **Step 3: Реализовать**

В `journal_django/apps/finances/fifo.py` заменить тело `compute_fifo` (строки 36-85) на:

```python
def compute_fifo(lots, consumptions, month_start: str, month_end: str) -> dict:
    """
    Порт computeFifo (services/fifo.js) на Decimal.

    Семантика идентична Node: индекс текущей партии lot_idx, остаток lot_remaining;
    каждое посещение гасится из партий по FIFO, недостача → over_consumed_lessons.
    Каждая запись consumption может нести 'direction_id' (направление урока) —
    используется только для атрибуции worked_off_by_direction в отчётах, партию
    FIFO-очереди это не меняет (лоты и посещения уже приходят единым пулом на
    ученика — см. apps/finances/repository.py::fifo_inputs).
    """
    lot_idx = 0
    lot_remaining = to_decimal(lots[0]['lessons']) if lots else _ZERO
    worked_off_total = _ZERO
    worked_off_month = _ZERO
    over_consumed_lessons = _ZERO
    by_month: dict[str, Decimal] = {}
    by_direction: dict = {}

    for c in consumptions:
        need = to_decimal(c['units'])
        # Полуинтервал [month_start, month_end); сравнение строк 'YYYY-MM-DD' = хронологическое.
        in_month = month_start <= c['date'] < month_end
        direction_id = c.get('direction_id')
        while need > 0 and lot_idx < len(lots):
            if lot_remaining <= 0:
                lot_idx += 1
                if lot_idx >= len(lots):
                    break
                lot_remaining = to_decimal(lots[lot_idx]['lessons'])
                continue
            take = need if need < lot_remaining else lot_remaining  # min(need, lot_remaining)
            value = take * to_decimal(lots[lot_idx]['price_per_lesson'])
            worked_off_total += value
            ym = c['date'][:7]
            by_month[ym] = by_month.get(ym, _ZERO) + value
            if direction_id is not None:
                by_direction[direction_id] = by_direction.get(direction_id, _ZERO) + value
            if in_month:
                worked_off_month += value
            lot_remaining -= take
            need -= take
        if need > 0:
            over_consumed_lessons += need

    remaining_value = _ZERO
    if lot_idx < len(lots):
        remaining_value += lot_remaining * to_decimal(lots[lot_idx]['price_per_lesson'])
        for i in range(lot_idx + 1, len(lots)):
            remaining_value += to_decimal(lots[i]['lessons']) * to_decimal(lots[i]['price_per_lesson'])

    return {
        'worked_off_total': round_kopecks(worked_off_total),
        'worked_off_month': round_kopecks(worked_off_month),
        'remaining_value': round_kopecks(remaining_value),
        'over_consumed_lessons': round_kopecks(over_consumed_lessons),
        'worked_off_by_month': {k: round_kopecks(v) for k, v in by_month.items()},
        'worked_off_by_direction': {k: round_kopecks(v) for k, v in by_direction.items()},
    }
```

Также обновить блок-комментарий модуля (строки 20-26), добавив описание нового поля:

```python
lots:         [{ 'lessons': n, 'price_per_lesson': Decimal }]  — в порядке оплаты (старые первыми).
consumptions: [{ 'units': 1|0.5, 'date': 'YYYY-MM-DD', 'direction_id': int|None }] — в порядке даты урока.
              direction_id — направление УРОКА (не оплаты), опционально (может отсутствовать).

Возврат (Decimal, округлены до копеек):
  worked_off_total, worked_off_month, remaining_value, over_consumed_lessons,
  worked_off_by_month: { 'YYYY-MM': Decimal }, worked_off_by_direction: { direction_id: Decimal }.
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `cd journal_django && pytest apps/finances/tests/test_fifo.py -v`
Expected: все тесты PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/finances/fifo.py journal_django/apps/finances/tests/test_fifo.py
git commit -m "feat(finances): worked_off_by_direction attribution in compute_fifo"
```

---

### Task 2: `fifo_inputs()` — общий пул по ученику

**Files:**
- Modify: `journal_django/apps/finances/repository.py:66-130`
- Test: `journal_django/apps/finances/tests/test_fifo_inputs.py`
- Test: `journal_django/apps/finances/tests/test_finances_orm_smoke.py`

- [ ] **Step 1: Написать падающие тесты**

В `journal_django/apps/finances/tests/test_fifo_inputs.py` заменить оба теста (обращения к ключу `f'{student}:{direction}'` → `str(student)`, добавить проверку `direction_id` в consumption-записях):

```python
def test_fifo_inputs_builds_lots_and_consumptions(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    # Две партии разной цены: 1 подписка ×4=4 урока по 500; 1×4=4 по 450.
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000, 2000, '2026-05-01')
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 1800, 1800, '2026-05-15')
    # Легаси-оплата (direction=NULL) — должна быть исключена WHERE direction_id IS NOT NULL.
    _add_legacy_payment(graph_cleanup, student_fixture, '2026-05-20')
    # 3 посещения в мае, 4 в июне.
    for _ in range(3):
        _add_lesson_with_attendance(
            graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-05-10'
        )
    for _ in range(4):
        _add_lesson_with_attendance(
            graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-06-10'
        )

    inputs = repository.fifo_inputs()
    key = str(student_fixture)

    assert key in inputs['keys']
    lots = inputs['lots_by_key'][key]
    # Легаси direction=NULL исключена WHERE → ровно 2 партии.
    assert len(lots) == 2
    assert lots[0]['lessons'] == 4
    assert lots[0]['price_per_lesson'] == Decimal('500')
    assert lots[1]['price_per_lesson'] == Decimal('450')
    assert inputs['purchased_by_key'][key] == 8

    cons = inputs['cons_by_key'][key]
    assert len(cons) == 7
    # lesson_date — строка, units — Decimal, direction_id — направление урока.
    assert isinstance(cons[0]['date'], str)
    assert cons[0]['date'] == '2026-05-10'
    assert cons[0]['direction_id'] == direction_fixture
    assert inputs['consumed_by_key'][key] == Decimal('7')

    # End-to-end: совпадает с golden из fifo.test.js (3 по 500 в мае + 1×500+3×450 в июне).
    r = compute_fifo(lots, cons, '2026-06-01', '2026-07-01')
    assert r['worked_off_total'] == Decimal('3350.00')
    assert r['worked_off_month'] == Decimal('1850.00')
    assert r['remaining_value'] == Decimal('450.00')


def test_fifo_inputs_half_lesson_units(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000, 2000, '2026-06-01')
    # 45-мин урок → units = 0.5
    _add_lesson_with_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-06-10', duration=45
    )
    inputs = repository.fifo_inputs()
    key = str(student_fixture)
    assert inputs['cons_by_key'][key][0]['units'] == Decimal('0.5')
    assert inputs['consumed_by_key'][key] == Decimal('0.5')


def test_fifo_inputs_pools_across_directions(
    teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    """
    Ключевой сценарий редизайна: оплата на direction_fixture (A), урок отработан в
    ДРУГОМ направлении (B) — обе записи должны попасть в ОДИН ключ (student_id),
    т.к. списание теперь общим пулом, без разбивки по направлению.
    """
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO directions (name, sheet_name, is_individual, active) "
            "VALUES ('__fifo_dir_b__', '__fifo_sheet_b__', false, true) RETURNING id"
        )
        direction_b = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active) "
            "VALUES ('__fifo_group_b__', %s, %s, false, 60, true) RETURNING id",
            [direction_b, teacher_id_fixture],
        )
        group_b = cur.fetchone()[0]
    try:
        _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000, 2000, '2026-05-01')
        _add_lesson_with_attendance(
            graph_cleanup, group_b, teacher_id_fixture, student_fixture, '2026-05-10'
        )
        inputs = repository.fifo_inputs()
        key = str(student_fixture)
        assert len(inputs['lots_by_key'][key]) == 1
        assert len(inputs['cons_by_key'][key]) == 1
        assert inputs['cons_by_key'][key][0]['direction_id'] == direction_b
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM groups WHERE id = %s', [group_b])
            cur.execute('DELETE FROM directions WHERE id = %s', [direction_b])
```

В `journal_django/apps/finances/tests/test_finances_orm_smoke.py` заменить `test_fifo_inputs` (строки 81-92):

```python
@pytest.mark.django_db
def test_fifo_inputs():
    d, t, g, s = _seed()
    res = repository.fifo_inputs()
    key = str(s.id)
    assert key in res['keys']
    assert res['purchased_by_key'][key] == 4
    # цена за урок = 4000 / 4 = 1000
    assert res['lots_by_key'][key][0]['price_per_lesson'] == Decimal('1000')
    assert res['consumed_by_key'][key] == Decimal('1')
    assert res['cons_by_key'][key][0]['date'] == '2026-01-05'
    assert res['cons_by_key'][key][0]['units'] == Decimal('1')
    assert res['cons_by_key'][key][0]['direction_id'] == d.id
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `cd journal_django && pytest apps/finances/tests/test_fifo_inputs.py apps/finances/tests/test_finances_orm_smoke.py::test_fifo_inputs -v`
Expected: FAIL — `KeyError` на ключ `f'{sid}:{did}'` не найден (т.к. старый код всё ещё строит составной ключ).

- [ ] **Step 3: Реализовать**

В `journal_django/apps/finances/repository.py` заменить `fifo_inputs()` (строки 66-130):

```python
def fifo_inputs() -> dict:
    """
    Загружает FIFO-входы по ключу student_id (общий пул на ученика).

    С 2026-07-08 payments.direction_id и направление урока — раздельные измерения:
    оплата с тегом направления A может быть погашена уроком в направлении B (см.
    docs/superpowers/specs/2026-07-08-student-balance-pooling-design.md). Партии
    (lots) сортируются по paid_at глобально по ученику; посещения (consumptions) —
    по lesson_date глобально. direction_id урока сохраняется в каждой
    consumption-записи только для атрибуции worked_off_by_direction в отчётах.

    Возвращает lots_by_key / purchased_by_key / cons_by_key / consumed_by_key / keys.
    Guard: оплаты с subscriptions_count NULL/0 (lessons ≤ 0) пропускаются —
    иначе деление на 0 / Infinity ломает суммы.
    """
    lots_rows = (
        Payment.objects
        .filter(direction_id__isnull=False)
        .order_by('student_id', 'paid_at', 'id')
        .values('student_id', 'total_amount', 'subscriptions_count')
    )

    cons_rows = (
        LessonAttendance.objects
        .filter(present=True)
        .annotate(units=_attended_units_case())
        .order_by('student_id', 'lesson__lesson_date', 'lesson_id')
        .values(
            'student_id', 'units',
            direction_id=F('lesson__group__direction_id'),
            lesson_date=F('lesson__lesson_date'),
        )
    )

    lots_by_key: dict[str, list] = {}
    purchased_by_key: dict[str, int] = {}
    for r in lots_rows:
        key = str(r['student_id'])
        subs = r['subscriptions_count']
        lessons = int(subs) * 4 if subs is not None else 0
        if not (lessons > 0):  # guard: NULL/0 subscriptions_count
            continue
        lots_by_key.setdefault(key, []).append({
            'lessons': lessons,
            'price_per_lesson': to_decimal(r['total_amount']) / Decimal(lessons),
        })
        purchased_by_key[key] = purchased_by_key.get(key, 0) + lessons

    cons_by_key: dict[str, list] = {}
    consumed_by_key: dict[str, Decimal] = {}
    for r in cons_rows:
        key = str(r['student_id'])
        units = to_decimal(r['units'])
        cons_by_key.setdefault(key, []).append({
            'units': units,
            'date': _date_str(r['lesson_date']),
            'direction_id': r['direction_id'],
        })
        consumed_by_key[key] = consumed_by_key.get(key, Decimal('0')) + units

    # keys в порядке вставки: сначала ключи партий (порядок строк lots), затем
    # ключи посещений, которых ещё не было. Порядок важен для тай-брейка дашборда.
    keys = list(lots_by_key.keys())
    for k in cons_by_key:
        if k not in lots_by_key:
            keys.append(k)
    return {
        'lots_by_key': lots_by_key,
        'purchased_by_key': purchased_by_key,
        'cons_by_key': cons_by_key,
        'consumed_by_key': consumed_by_key,
        'keys': keys,
    }
```

- [ ] **Step 4: Запустить и убедиться, что проходят**

Run: `cd journal_django && pytest apps/finances/tests/test_fifo_inputs.py apps/finances/tests/test_finances_orm_smoke.py::test_fifo_inputs -v`
Expected: все PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/finances/repository.py journal_django/apps/finances/tests/test_fifo_inputs.py journal_django/apps/finances/tests/test_finances_orm_smoke.py
git commit -m "feat(finances): fifo_inputs pools lots/consumptions by student, not direction"
```

---

### Task 3: `balance_for_direction` → `balance_for_student`

**Files:**
- Modify: `journal_django/apps/finances/repository.py:137-150`
- Modify: `journal_django/apps/payments/repository.py:142-172`
- Modify: `journal_django/apps/renewals/repository.py:37,70`
- Test: `journal_django/apps/finances/tests/test_finances_orm_smoke.py`
- Test: `journal_django/apps/finances/tests/test_balance.py`
- Test: `journal_django/apps/payments/tests/test_payments_repository.py`

- [ ] **Step 1: Написать падающие тесты**

В `journal_django/apps/finances/tests/test_finances_orm_smoke.py` заменить `test_balance_for_direction` (строки 53-57):

```python
@pytest.mark.django_db
def test_balance_for_student():
    d, t, g, s = _seed()
    # purchased 4 − attended 1 = 3
    assert repository.balance_for_student(s.id) == 3
```

В `journal_django/apps/finances/tests/test_balance.py` заменить `test_balance_for_direction_matches` (строки 73-82):

```python
def test_balance_for_student_matches(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000)
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-06-10', duration=60
    )
    bal = repository.balance_for_student(student_fixture)
    assert bal == 3
    assert isinstance(bal, int)
```

В `journal_django/apps/payments/tests/test_payments_repository.py` заменить два метода `test_balance_for_direction_full_lessons_is_int` и `test_balance_for_direction_half_lesson_is_float` (строки 358-408):

```python
    def test_balance_for_student_full_lessons_is_int(
        self,
        payment_fixture,
        student_fixture,
        membership_fixture,
        lesson_60_fixture,
    ):
        """60мин урок: attended=1 (int), balance=3 (int)."""
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s, %s, true)',
                [lesson_60_fixture, student_fixture],
            )

        try:
            bal = repository._balance_for_student(student_fixture)
            assert bal == 3
            assert isinstance(bal, int)
        finally:
            with connection.cursor() as cur:
                cur.execute(
                    'DELETE FROM lesson_attendance WHERE lesson_id = %s AND student_id = %s',
                    [lesson_60_fixture, student_fixture],
                )

    def test_balance_for_student_half_lesson_is_float(
        self,
        payment_fixture,
        student_fixture,
        membership_fixture,
        lesson_45_fixture,
    ):
        """45мин урок: balance=3.5 (float)."""
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s, %s, true)',
                [lesson_45_fixture, student_fixture],
            )

        try:
            bal = repository._balance_for_student(student_fixture)
            assert bal == 3.5
            assert isinstance(bal, float)
        finally:
            with connection.cursor() as cur:
                cur.execute(
                    'DELETE FROM lesson_attendance WHERE lesson_id = %s AND student_id = %s',
                    [lesson_45_fixture, student_fixture],
                )
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `cd journal_django && pytest apps/finances/tests/test_finances_orm_smoke.py::test_balance_for_student apps/finances/tests/test_balance.py::test_balance_for_student_matches apps/payments/tests/test_payments_repository.py::TestBalanceNumericTypes -v`
Expected: FAIL — `AttributeError: module 'apps.finances.repository' has no attribute 'balance_for_student'` (и аналогично `_balance_for_student` в payments).

- [ ] **Step 3: Реализовать**

В `journal_django/apps/finances/repository.py` заменить `balance_for_direction()` (строки 137-150):

```python
def balance_for_student(student_id: int) -> int | float:
    """
    Общий баланс ученика (единый пул по всем направлениям): purchased − attended.
    half-lesson: 45→0.5. Возврат _js_number (int|float).
    """
    purchased = Payment.objects.filter(
        student_id=student_id,
    ).aggregate(s=Coalesce(Sum(F('subscriptions_count') * 4, output_field=_DEC), _ZERO))['s']

    attended = LessonAttendance.objects.filter(
        student_id=student_id, present=True,
    ).aggregate(s=Coalesce(Sum(_attended_units_case()), _ZERO))['s']

    return _js_number(purchased - attended)
```

Обновить модульный докстринг (строки 1-16), заменив упоминание `balance_for_direction() ← _balance_for_direction (payments.js)` на `balance_for_student() ← общий пул (2026-07-08 редизайн)`.

В `journal_django/apps/payments/repository.py` заменить `delete_payment()` и `_balance_for_direction()` (строки 142-172):

```python
def delete_payment(payment_id: int) -> dict:
    """
    Хард-удаляет оплату и пересчитывает общий баланс ученика (единый пул).

    Возвращает {'deleted': False} или {'deleted': True, student_id, direction_id, new_balance}.
    """
    row = (
        Payment.objects.filter(id=payment_id)
        .values('student_id', 'direction_id')
        .first()
    )
    if row is None:
        return {'deleted': False}

    Payment.objects.filter(id=payment_id).delete()

    student_id = row['student_id']
    direction_id = row['direction_id']
    balance = _balance_for_student(student_id)
    return {
        'deleted': True,
        'student_id': student_id,
        'direction_id': direction_id,
        'new_balance': balance,
    }


def _balance_for_student(student_id: int) -> int | float:
    """Общий баланс ученика (единый пул). Делегирует в единый дом apps/finances."""
    from apps.finances.repository import balance_for_student
    return balance_for_student(student_id)
```

В `journal_django/apps/renewals/repository.py` заменить строку 37 и строку 70:

```python
    from apps.finances.repository import balance_for_student
```

```python
    data['balance'] = balance_for_student(data['student_id'])
```

- [ ] **Step 4: Запустить и убедиться, что проходят**

Run: `cd journal_django && pytest apps/finances apps/payments apps/renewals -v`
Expected: все PASS (включая существующие тесты renewals, которые не проверяют значение `balance`, только его наличие).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/finances/repository.py journal_django/apps/finances/tests/test_finances_orm_smoke.py journal_django/apps/finances/tests/test_balance.py journal_django/apps/payments/repository.py journal_django/apps/payments/tests/test_payments_repository.py journal_django/apps/renewals/repository.py
git commit -m "refactor(finances): balance_for_direction -> balance_for_student (global pool)"
```

---

### Task 4: `student_balance_rows()` → `paid_by_direction_rows()` + `attended_by_direction_rows()`

**Files:**
- Modify: `journal_django/apps/finances/repository.py:153-198`
- Test: `journal_django/apps/finances/tests/test_finances_orm_smoke.py`

- [ ] **Step 1: Написать падающие тесты**

В `journal_django/apps/finances/tests/test_finances_orm_smoke.py` заменить `test_student_balance_rows` (строки 66-78) на два теста:

```python
@pytest.mark.django_db
def test_paid_by_direction_rows():
    d, t, g, s = _seed()
    rows = repository.paid_by_direction_rows(s.id)
    assert len(rows) == 1
    r = rows[0]
    assert r['direction_id'] == d.id
    assert r['direction_name'] == 'FIN-DIR'
    assert r['direction_color'] == '#abcdef'
    assert repository._js_number(r['total_paid_amount']) == 4000


@pytest.mark.django_db
def test_attended_by_direction_rows():
    d, t, g, s = _seed()
    rows = repository.attended_by_direction_rows(s.id)
    assert len(rows) == 1
    r = rows[0]
    assert r['direction_id'] == d.id
    assert r['direction_name'] == 'FIN-DIR'
    assert repository._js_number(r['attended_lessons']) == 1
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `cd journal_django && pytest apps/finances/tests/test_finances_orm_smoke.py::test_paid_by_direction_rows apps/finances/tests/test_finances_orm_smoke.py::test_attended_by_direction_rows -v`
Expected: FAIL — `AttributeError: module 'apps.finances.repository' has no attribute 'paid_by_direction_rows'`.

- [ ] **Step 3: Реализовать**

В `journal_django/apps/finances/repository.py` заменить `student_balance_rows()` (строки 153-198) на:

```python
def paid_by_direction_rows(student_id: int) -> list[dict]:
    """
    Оплачено по направлениям (по тегу оплаты payments.direction_id) — ТОЛЬКО
    информационная разбивка, не баланс (баланс общий — см. balance_for_student).
    """
    paid = (
        Payment.objects
        .filter(student_id=student_id)
        .exclude(direction_id__isnull=True)  # легаси (direction_id NULL) не джойнятся
        .values('direction_id')
        .annotate(total_paid=Sum('total_amount'))
    )
    totals = {r['direction_id']: r['total_paid'] for r in paid}
    if not totals:
        return []

    rows: list[dict] = []
    for d in Direction.objects.filter(id__in=totals).order_by('name').values('id', 'name', 'color'):
        rows.append({
            'direction_id': d['id'],
            'direction_name': d['name'],
            'direction_color': d['color'],
            'total_paid_amount': totals[d['id']],
        })
    return rows


def attended_by_direction_rows(student_id: int) -> list[dict]:
    """
    Отработано по направлениям (по направлению УРОКА, не оплаты) — ТОЛЬКО
    информационная разбивка, не баланс.
    """
    attended = (
        LessonAttendance.objects
        .filter(student_id=student_id, present=True)
        .values(did=F('lesson__group__direction_id'))
        .annotate(attended=Sum(_attended_units_case()))
    )
    totals = {r['did']: r['attended'] for r in attended if r['did'] is not None}
    if not totals:
        return []

    rows: list[dict] = []
    for d in Direction.objects.filter(id__in=totals).order_by('name').values('id', 'name', 'color'):
        rows.append({
            'direction_id': d['id'],
            'direction_name': d['name'],
            'direction_color': d['color'],
            'attended_lessons': totals[d['id']],
        })
    return rows
```

- [ ] **Step 4: Запустить и убедиться, что проходят**

Run: `cd journal_django && pytest apps/finances/tests/test_finances_orm_smoke.py -v`
Expected: все PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/finances/repository.py journal_django/apps/finances/tests/test_finances_orm_smoke.py
git commit -m "refactor(finances): split student_balance_rows into paid/attended by-direction rows"
```

---

### Task 5: `get_student_balance()` — новая форма ответа

**Files:**
- Modify: `journal_django/apps/finances/balance.py`
- Test: `journal_django/apps/finances/tests/test_balance.py`

- [ ] **Step 1: Написать падающие тесты**

Полностью заменить содержимое `journal_django/apps/finances/tests/test_balance.py`:

```python
"""
Тесты единого дома баланса (apps/finances/balance.py + repository).

С 2026-07-08 баланс общий пул на ученика (не per-direction) —
apps/finances/repository.py::balance_for_student. paid_by_direction /
attended_by_direction — информационные разбивки, НЕ баланс.
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.finances import balance, repository

pytestmark = pytest.mark.django_db


def _add_payment(created, student_id, direction_id, subs, total, paid_at='2026-06-01'):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, unit_price, "
            "total_amount, paid_at, created_by) VALUES (%s,%s,%s,%s,%s,%s,'test') RETURNING id",
            [student_id, direction_id, subs, total, total, paid_at],
        )
        pid = cur.fetchone()[0]
    created['payments'].append(pid)
    return pid


def _add_lesson_attendance(created, group_id, teacher_id, student_id, date, duration=60):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s,%s,%s,1,%s,'regular','test') RETURNING id",
            [group_id, teacher_id, date, duration],
        )
        lid = cur.fetchone()[0]
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s,%s,true)',
            [lid, student_id],
        )
    created['lessons'].append(lid)
    return lid


def test_total_balance_is_int_when_whole(student_fixture, direction_fixture, graph_cleanup):
    # 1 подписка ×4 = 4 куплено, 0 посещений → total_balance 4 (int).
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000)
    result = balance.get_student_balance(student_fixture)
    assert result['total_balance'] == 4
    assert isinstance(result['total_balance'], int)


def test_total_balance_is_float_with_half_lesson(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000)
    # 45-мин урок → attended 0.5 → total_balance 3.5 (float)
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-06-10', duration=45
    )
    result = balance.get_student_balance(student_fixture)
    assert result['total_balance'] == 3.5
    assert isinstance(result['total_balance'], float)


def test_balance_for_student_matches(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000)
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-06-10', duration=60
    )
    bal = repository.balance_for_student(student_fixture)
    assert bal == 3
    assert isinstance(bal, int)


def test_balance_pools_across_directions(
    teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup
):
    """
    Ключевой сценарий редизайна: оплата за направление A, но урок отработан в
    ДРУГОМ направлении B — списывается из общего пула, а не остаётся зависшей.
    """
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO directions (name, sheet_name, is_individual, active) "
            "VALUES ('__fin_dir_b__', '__fin_sheet_b__', false, true) RETURNING id"
        )
        direction_b = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active) "
            "VALUES ('__fin_group_b__', %s, %s, false, 60, true) RETURNING id",
            [direction_b, teacher_id_fixture],
        )
        group_b = cur.fetchone()[0]
    try:
        # Оплата на направление A (direction_fixture) — 4 урока.
        _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000)
        # Урок отработан на направлении B (group_b).
        _add_lesson_attendance(
            graph_cleanup, group_b, teacher_id_fixture, student_fixture, '2026-06-10', duration=60
        )
        result = balance.get_student_balance(student_fixture)
        # 4 куплено на A, 1 отработан на B → общий баланс 3 (списался из общего пула).
        assert result['total_balance'] == 3
        paid_a = next(d for d in result['paid_by_direction'] if d['direction_id'] == direction_fixture)
        assert paid_a['total_paid_amount'] == 2000
        attended_b = next(d for d in result['attended_by_direction'] if d['direction_id'] == direction_b)
        assert attended_b['attended_lessons'] == 1
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM groups WHERE id = %s', [group_b])
            cur.execute('DELETE FROM directions WHERE id = %s', [direction_b])


def test_balance_empty_student(student_fixture, graph_cleanup):
    result = balance.get_student_balance(student_fixture)
    assert result['paid_by_direction'] == []
    assert result['attended_by_direction'] == []
    assert result['total_balance'] == 0
    assert result['payments'] == []
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `cd journal_django && pytest apps/finances/tests/test_balance.py -v`
Expected: FAIL — `KeyError: 'total_balance'`/`'paid_by_direction'` (старый `get_student_balance` ещё отдаёт `per_direction`).

- [ ] **Step 3: Реализовать**

Полностью заменить содержимое `journal_django/apps/finances/balance.py`:

```python
"""
Баланс ученика — выводится, не хранится. С 2026-07-08 общий пул по всем
направлениям (payments.direction_id — информационный тег, не скоуп списания).

Единый дом расчёта баланса. paid_by_direction/attended_by_direction — только
информационные разбивки (см. docs/superpowers/specs/2026-07-08-student-balance-pooling-design.md).

balance_for_student переэкспортируется из repository для удобства потребителей.
"""
from __future__ import annotations

from apps.finances import repository
from apps.finances.repository import balance_for_student  # re-export

__all__ = ['balance_for_student', 'get_student_balance']


def get_student_balance(student_id: int) -> dict:
    """
    Общий баланс ученика (единый пул) + информационные разбивки по направлениям
    + список оплат. list_payments импортируется лениво, чтобы не создавать цикл
    finances ↔ payments.
    """
    from apps.payments.repository import list_payments

    total_balance = repository.balance_for_student(student_id)

    paid_by_direction = [
        {
            'direction_id':      r['direction_id'],
            'direction_name':    r['direction_name'],
            'direction_color':   r['direction_color'],
            'total_paid_amount': repository._js_number(r['total_paid_amount']),
        }
        for r in repository.paid_by_direction_rows(student_id)
    ]
    attended_by_direction = [
        {
            'direction_id':     r['direction_id'],
            'direction_name':   r['direction_name'],
            'direction_color':  r['direction_color'],
            'attended_lessons': repository._js_number(r['attended_lessons']),
        }
        for r in repository.attended_by_direction_rows(student_id)
    ]

    total_paid = repository.total_paid_amount(student_id)
    payments = list_payments(student_id=student_id)

    return {
        'total_balance':         total_balance,
        'total_paid_amount':     total_paid,
        'paid_by_direction':     paid_by_direction,
        'attended_by_direction': attended_by_direction,
        'payments':              payments,
    }
```

- [ ] **Step 4: Запустить и убедиться, что проходят**

Run: `cd journal_django && pytest apps/finances -v`
Expected: все PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/finances/balance.py journal_django/apps/finances/tests/test_balance.py
git commit -m "feat(finances): get_student_balance returns pooled total_balance + informational breakdowns"
```

---

### Task 6: `apps/students` и `apps/payments` — обновить тесты формы ответа `/balance`

**Files:**
- Modify: `journal_django/apps/students/tests/test_students_api.py:24,233-258`
- Modify: `journal_django/apps/students/tests/test_students_repository.py:15,405-459`
- Modify: `journal_django/apps/payments/tests/test_payments_repository.py:296-444` (`TestBalanceNumericTypes` — оставшиеся методы после Task 3)

- [ ] **Step 1: Написать падающие тесты**

В `journal_django/apps/students/tests/test_students_api.py` заменить строку 24 (докстринг) и блок строк 232-258:

```python
  - GET /:id/balance → 200 с {paid_by_direction, attended_by_direction, total_balance, total_paid_amount, payments}
```

```python
@pytest.mark.django_db
def test_balance_returns_200_for_new_student(admin_client):
    """Express не проверяет существование — просто возвращает данные."""
    from apps.students import repository
    student = repository.create_student({'full_name': '__test_api_balance__'})
    try:
        resp = admin_client.get(f"{BASE_URL}/{student['id']}/balance")
        assert resp.status_code == 200
        body = resp.json()
        assert 'paid_by_direction' in body
        assert 'attended_by_direction' in body
        assert 'total_balance' in body
        assert 'total_paid_amount' in body
        assert 'payments' in body
    finally:
        _cleanup_student(student['id'])


@pytest.mark.django_db
def test_balance_nonexistent_student_returns_200(admin_client):
    """Express не проверяет существование при /balance — возвращает пустые данные."""
    resp = admin_client.get(f'{BASE_URL}/999999999/balance')
    assert resp.status_code == 200
    body = resp.json()
    assert body['paid_by_direction'] == []
    assert body['attended_by_direction'] == []
    assert body['total_balance'] == 0
    assert body['total_paid_amount'] == 0
    assert body['payments'] == []
```

В `journal_django/apps/students/tests/test_students_repository.py` заменить строку 15 (докстринг класса) и весь класс `TestGetStudentBalance` (строки 407-459):

```python
  - get_student_balance: форма ответа (keys: paid_by_direction, attended_by_direction, total_balance, total_paid_amount, payments)
```

```python
@pytest.mark.django_db
class TestGetStudentBalance:
    """Тесты get_student_balance() — форма ответа. Постоянный дом — apps/finances/."""

    def test_shape_for_new_student(self):
        """Ученик без оплат — структура ответа корректная."""
        from apps.payments import repository as payments_repo
        data = _make_student_data(full_name='__test_balance_shape__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            result = payments_repo.get_student_balance(sid)
            assert 'paid_by_direction' in result
            assert 'attended_by_direction' in result
            assert 'total_balance' in result
            assert 'total_paid_amount' in result
            assert 'payments' in result
            assert isinstance(result['paid_by_direction'], list)
            assert isinstance(result['attended_by_direction'], list)
            assert isinstance(result['payments'], list)
        finally:
            _cleanup_student(sid)

    def test_zero_balance_for_new_student(self):
        """Ученик без оплат — нулевые балансы."""
        from apps.payments import repository as payments_repo
        data = _make_student_data(full_name='__test_balance_zeros__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            result = payments_repo.get_student_balance(sid)
            assert result['total_balance'] == 0
            assert result['total_paid_amount'] == 0
            assert result['paid_by_direction'] == []
            assert result['attended_by_direction'] == []
            assert result['payments'] == []
        finally:
            _cleanup_student(sid)

    def test_paid_by_direction_shape(self):
        """Если есть оплаты — paid_by_direction содержит нужные ключи."""
        from apps.payments import repository as payments_repo
        with connection.cursor() as cur:
            cur.execute('SELECT student_id FROM payments WHERE direction_id IS NOT NULL LIMIT 1')
            row = cur.fetchone()
        if not row:
            pytest.skip('No payments in DB — skipping paid_by_direction shape test')

        result = payments_repo.get_student_balance(row[0])
        if result['paid_by_direction']:
            d = result['paid_by_direction'][0]
            for key in ['direction_id', 'direction_name', 'direction_color', 'total_paid_amount']:
                assert key in d, f"Missing key '{key}' in paid_by_direction item"

    def test_attended_by_direction_shape(self):
        """Если есть посещения — attended_by_direction содержит нужные ключи."""
        from apps.payments import repository as payments_repo
        with connection.cursor() as cur:
            cur.execute('SELECT student_id FROM lesson_attendance WHERE present = true LIMIT 1')
            row = cur.fetchone()
        if not row:
            pytest.skip('No attendance in DB — skipping attended_by_direction shape test')

        result = payments_repo.get_student_balance(row[0])
        if result['attended_by_direction']:
            d = result['attended_by_direction'][0]
            for key in ['direction_id', 'direction_name', 'direction_color', 'attended_lessons']:
                assert key in d, f"Missing key '{key}' in attended_by_direction item"
```

В `journal_django/apps/payments/tests/test_payments_repository.py` заменить оставшиеся методы класса `TestBalanceNumericTypes`, которые всё ещё используют `per_direction` (строки 309-350 и 429-443):

```python
    def test_total_balance_is_int_when_whole(self, payment_fixture, student_fixture):
        """Нет посещений → total_balance = 4 → int."""
        balance = repository.get_student_balance(student_fixture)
        assert balance['total_balance'] == 4
        assert isinstance(balance['total_balance'], int)

    def test_total_balance_is_float_with_half_lesson(
        self,
        payment_fixture,
        student_fixture,
        membership_fixture,
        lesson_45_fixture,
    ):
        """lesson_duration_minutes=45 → attended_lessons=0.5 → total_balance=3.5 → float."""
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s, %s, true)',
                [lesson_45_fixture, student_fixture],
            )

        try:
            balance = repository.get_student_balance(student_fixture)
            assert balance['total_balance'] == 3.5
            assert isinstance(balance['total_balance'], float)
        finally:
            with connection.cursor() as cur:
                cur.execute(
                    'DELETE FROM lesson_attendance WHERE lesson_id = %s AND student_id = %s',
                    [lesson_45_fixture, student_fixture],
                )
```

```python
    def test_no_payments_returns_empty_breakdowns(self):
        """Ученик без оплат → paid_by_direction/attended_by_direction пусты, total_balance=0."""
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO students (full_name, enrollment_status) VALUES ('__bal_empty__', 'enrolled') RETURNING id",
            )
            sid = cur.fetchone()[0]
        try:
            balance = repository.get_student_balance(sid)
            assert balance['paid_by_direction'] == []
            assert balance['attended_by_direction'] == []
            assert balance['total_balance'] == 0
            assert balance['payments'] == []
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM students WHERE id = %s', [sid])
```

(Методы `test_purchased_is_int_when_whole` и `test_balance_is_int_when_whole` удалить целиком — их дублирует `test_total_balance_is_int_when_whole`, отдельного поля `purchased_lessons` в новой форме ответа больше нет.)

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `cd journal_django && pytest apps/students/tests/test_students_api.py apps/students/tests/test_students_repository.py apps/payments/tests/test_payments_repository.py -v`
Expected: FAIL на местах, где тест ещё ждёт `per_direction`/`purchased_lessons` (уже удалены из ответа Task 5) — до этого шага тесты обращались к старым полям.

- [ ] **Step 3: Реализация**

Реализация уже сделана в Task 5 (`get_student_balance` возвращает новую форму) — этот таск только про синхронизацию тестов, разбросанных по `apps/students` и `apps/payments`, которые не были задеты в Task 3/5.

- [ ] **Step 4: Запустить и убедиться, что проходят**

Run: `cd journal_django && pytest apps/students apps/payments -v`
Expected: все PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/students/tests/test_students_api.py journal_django/apps/students/tests/test_students_repository.py journal_django/apps/payments/tests/test_payments_repository.py
git commit -m "test: sync students/payments balance tests with pooled StudentBalance shape"
```

---

### Task 7: Дашборд — долги без разбивки по направлению

**Files:**
- Modify: `journal_django/apps/dashboard/services.py:56-105`
- Modify: `journal_django/apps/dashboard/repository.py:64-71` (удалить `directions_info`)
- Test: `journal_django/apps/dashboard/tests/test_dashboard_api.py:81-100`

- [ ] **Step 1: Написать падающий тест**

В `journal_django/apps/dashboard/tests/test_dashboard_api.py` дополнить `test_dashboard_shape_and_types` (после строки 100):

```python
@pytest.mark.parametrize('role', ['manager', 'admin'])
def test_dashboard_shape_and_types(role):
    resp = _client(role).get(BASE)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        'month', 'from', 'to', 'revenue_month', 'worked_off_month',
        'carryover_month', 'deferred_total', 'debts', 'debts_total',
    }
    # Денежные значения — JSON-числа, не строки (как Express Number()).
    for k in ('revenue_month', 'worked_off_month', 'carryover_month', 'deferred_total'):
        assert isinstance(body[k], (int, float)), f'{k} must be number, got {type(body[k])}'
    assert isinstance(body['debts'], list)
    assert isinstance(body['debts_total'], int)
    # top-долги ≤ 8, balance — число, отсортированы по возрастанию.
    assert len(body['debts']) <= 8
    balances = [d['balance'] for d in body['debts']]
    for b in balances:
        assert isinstance(b, (int, float))
    assert balances == sorted(balances)
    # Долг — общий пул по ученику (2026-07-08), без разбивки по направлению.
    for d in body['debts']:
        assert set(d.keys()) == {'student_id', 'student_name', 'balance'}
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd journal_django && pytest apps/dashboard/tests/test_dashboard_api.py::test_dashboard_shape_and_types -v`
Expected: FAIL на последней проверке — текущий `debts` содержит ещё `direction_id`/`direction_name`/`direction_color`.

- [ ] **Step 3: Реализовать**

В `journal_django/apps/dashboard/services.py` заменить `get_dashboard()` (строки 34-105):

```python
def get_dashboard(from_: Optional[str] = None, to: Optional[str] = None) -> dict:
    """
    Сводка: revenue_month, worked_off_month, carryover, deferred_total, top-долги.

    Порт dashboard.js getDashboard. Период [period_start, period_end):
    с from/to — заданный диапазон (to эксклюзивно через _add_day), иначе текущий МСК-месяц.
    Долги считаются по student_id (общий пул, без разбивки по направлению —
    см. docs/superpowers/specs/2026-07-08-student-balance-pooling-design.md).
    """
    month, month_start, month_end = msk_month_range_triple()
    has_range = bool(from_ or to)
    period_start = (from_ or '0001-01-01') if has_range else month_start
    period_end = (_add_day(to) if to else '9999-12-31') if has_range else month_end

    revenue_month = js_round2(repository.revenue_for_period(period_start, period_end))

    inp = fifo_inputs()
    lots_by_key = inp['lots_by_key']
    cons_by_key = inp['cons_by_key']
    purchased_by_key = inp['purchased_by_key']
    consumed_by_key = inp['consumed_by_key']

    worked_off_month = _ZERO
    deferred_total = _ZERO
    debt_keys: list[dict] = []
    for key in inp['keys']:
        fifo = compute_fifo(
            lots_by_key.get(key, []), cons_by_key.get(key, []), period_start, period_end
        )
        worked_off_month += fifo['worked_off_month']
        deferred_total += fifo['remaining_value']
        balance = to_decimal(purchased_by_key.get(key, 0)) - to_decimal(consumed_by_key.get(key, 0))
        if balance < 0:
            debt_keys.append({
                'student_id': int(key),
                'balance': js_round2(balance),
            })

    worked_off_month = js_round2(worked_off_month)
    deferred_total = js_round2(deferred_total)
    carryover_month = js_round2(revenue_month - worked_off_month)

    # Стабильная сортировка по возрастанию баланса (insertion order — тай-брейк, как в JS).
    debt_keys.sort(key=lambda d: d['balance'])
    debts_total = len(debt_keys)
    top_debts = debt_keys[:8]

    student_ids = list(dict.fromkeys(d['student_id'] for d in top_debts))
    s_map = repository.students_names(student_ids)

    debts = [{
        'student_id': d['student_id'],
        'student_name': s_map.get(d['student_id'], '—'),
        'balance': js_number(d['balance']),
    } for d in top_debts]

    return {
        'month': month,
        'from': from_ or None,
        'to': to or None,
        'revenue_month': js_number(revenue_month),
        'worked_off_month': js_number(worked_off_month),
        'carryover_month': js_number(carryover_month),
        'deferred_total': js_number(deferred_total),
        'debts': debts,
        'debts_total': debts_total,
    }
```

В `journal_django/apps/dashboard/repository.py` удалить функцию `directions_info()` (строки 64-71) — становится неиспользуемой (единственный вызов был в `get_dashboard`, только что удалён). Также удалить теперь неиспользуемый импорт `from apps.directions.models import Direction` (строка 17), если больше ничего в файле его не использует.

- [ ] **Step 4: Запустить и убедиться, что проходят**

Run: `cd journal_django && pytest apps/dashboard -v`
Expected: все PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/dashboard/services.py journal_django/apps/dashboard/repository.py journal_django/apps/dashboard/tests/test_dashboard_api.py
git commit -m "refactor(dashboard): debts keyed by student only, drop unused directions_info"
```

---

### Task 8: Полный прогон бэкенд-тестов

**Files:** нет изменений — только верификация.

- [ ] **Step 1: Прогнать весь бэкенд-набор**

Run: `cd journal_django && pytest -q`
Expected: все тесты PASS (0 failed). Если что-то красное вне уже тронутых файлов — значит остался необнаруженный потребитель `per_direction`/`balance_for_direction`/`student_balance_rows`; найти через `grep -rn "per_direction\|balance_for_direction\|student_balance_rows" journal_django/apps` и починить по аналогии с Task 3/4/5.

- [ ] **Step 2: Commit** (только если Step 1 потребовал правок)

```bash
git add -u
git commit -m "fix: address remaining balance_for_direction/per_direction stragglers"
```

---

### Task 9: Фронтенд — типы

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/shared-types.ts:200-217,275-282`

- [ ] **Step 1: Обновить типы**

В `journal_django/frontend/admin-src/src/lib/shared-types.ts` заменить блок `// ===== Balance =====` (строки 200-217):

```typescript
// ===== Balance =====

export interface PaidByDirection {
  direction_id: ID;
  direction_name: string;
  direction_color: string | null;
  total_paid_amount: number | string;
}

export interface AttendedByDirection {
  direction_id: ID;
  direction_name: string;
  direction_color: string | null;
  attended_lessons: number;
}

export interface StudentBalance {
  total_balance: number;              // общий пул ученика, не по направлению
  total_paid_amount: number | string;
  paid_by_direction: PaidByDirection[];
  attended_by_direction: AttendedByDirection[];
  payments: Payment[];
}
```

Заменить `DashboardDebt` (строки 275-282):

```typescript
export interface DashboardDebt {
  student_id: number;
  student_name: string;
  balance: number; // в уроках, < 0 (общий пул ученика, без направления)
}
```

- [ ] **Step 2: Типчек**

Run: `cd journal_django/frontend/admin-src && npm run typecheck`
Expected: ошибки в `StudentBalanceBlock.tsx` и `DebtsCard.tsx` (используют старые поля `per_direction`/`direction_id`/`direction_name`/`direction_color` — будут исправлены в Task 10/11). Это ожидаемо на этом шаге.

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/lib/shared-types.ts
git commit -m "feat(admin-fe): StudentBalance/DashboardDebt types for pooled balance"
```

---

### Task 10: Фронтенд — `StudentBalanceBlock.tsx`

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/students/StudentBalanceBlock.tsx`
- Modify: `journal_django/frontend/admin-src/src/styles/pages/detail.css:544-550`

- [ ] **Step 1: Переписать компонент**

Заменить содержимое `journal_django/frontend/admin-src/src/pages/students/StudentBalanceBlock.tsx` целиком:

```tsx
import { useState } from 'react';
import { useStudentBalance } from '../../hooks/useStudentBalance';
import { usePaymentMutations } from '../../hooks/usePayments';
import { usePaymentModal } from '../../providers/PaymentModalProvider';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { fmtRub, fmtLessons, fmtDate } from '../../lib/format';

interface Props {
  studentId: number;
}

export function StudentBalanceBlock({ studentId }: Props) {
  const balance = useStudentBalance(studentId);
  const muts = usePaymentMutations();
  const { open } = usePaymentModal();
  const showError = useApiError();
  const { toast } = useToast();

  const [confirmingId, setConfirmingId] = useState<number | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [paidOpen, setPaidOpen] = useState(false);
  const [attendedOpen, setAttendedOpen] = useState(false);

  if (balance.isLoading) return null;
  const data = balance.data;
  if (!data) return null;
  if (
    data.paid_by_direction.length === 0 &&
    data.attended_by_direction.length === 0 &&
    data.payments.length === 0
  ) return null;

  const handleDelete = async (id: number) => {
    if (confirmingId !== id) { setConfirmingId(id); return; }
    try {
      const res = await muts.remove.mutateAsync(id);
      toast('Оплата удалена', 'ok');
      if (res.warning === 'balance_negative') {
        toast(`Внимание: баланс стал ${fmtLessons(res.new_balance)}`, 'error');
      }
      setConfirmingId(null);
    } catch (err) {
      showError(err);
      setConfirmingId(null);
    }
  };

  return (
    <section className="balance-block">
      <div className="balance-block__head">
        <h3>Баланс</h3>
        <button type="button" className="btn-save" onClick={() => open({ studentId })}>
          + Внести оплату
        </button>
      </div>

      <div className="balance-block__totals">
        <div>Оплачено всего: <strong>{fmtRub(data.total_paid_amount)}</strong></div>
        <div>
          Осталось оплаченных уроков:&nbsp;
          <strong className={data.total_balance < 0 ? 'balance-neg' : ''}>
            {fmtLessons(data.total_balance)}
          </strong>
        </div>
      </div>

      {data.paid_by_direction.length > 0 && (
        <>
          <button
            type="button"
            className="balance-block__history-toggle"
            onClick={() => setPaidOpen((o) => !o)}
            aria-expanded={paidOpen}
          >
            <span className={`balance-block__chevron${paidOpen ? ' is-open' : ''}`}>▸</span>
            Оплачено по направлениям
          </button>
          {paidOpen && (
            <div className="balance-block__directions">
              {data.paid_by_direction.map((d) => (
                <div key={d.direction_id} className="balance-block__direction-row">
                  <span className="dir-tag" style={{ background: d.direction_color || '#999' }} />
                  <span className="balance-block__direction-name">{d.direction_name}</span>
                  <span>{fmtRub(d.total_paid_amount)}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {data.attended_by_direction.length > 0 && (
        <>
          <button
            type="button"
            className="balance-block__history-toggle"
            onClick={() => setAttendedOpen((o) => !o)}
            aria-expanded={attendedOpen}
          >
            <span className={`balance-block__chevron${attendedOpen ? ' is-open' : ''}`}>▸</span>
            Отработано по направлениям
          </button>
          {attendedOpen && (
            <div className="balance-block__directions">
              {data.attended_by_direction.map((d) => (
                <div key={d.direction_id} className="balance-block__direction-row">
                  <span className="dir-tag" style={{ background: d.direction_color || '#999' }} />
                  <span className="balance-block__direction-name">{d.direction_name}</span>
                  <span>{fmtLessons(d.attended_lessons)} уроков</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {data.payments.length > 0 && (
        <>
          <button
            type="button"
            className="balance-block__history-toggle"
            onClick={() => setHistoryOpen((o) => !o)}
            aria-expanded={historyOpen}
          >
            <span className={`balance-block__chevron${historyOpen ? ' is-open' : ''}`}>▸</span>
            История оплат <span className="muted">({data.payments.length})</span>
          </button>
          {historyOpen && (
          <ul className="balance-block__history">
            {data.payments.map((p) => (
              <li key={p.id} className="balance-block__history-row">
                <div className="balance-block__history-main">
                  <span>{fmtDate(p.paid_at)}</span>
                  <span> · </span>
                  <span>{p.direction_name || <em className="muted">Архив</em>}</span>
                  <span> · </span>
                  {p.subscriptions_count != null ? (
                    <>
                      <span>{p.subscriptions_count} аб.</span>
                      <span> · </span>
                      <span>{fmtRub(p.unit_price)}/аб = <strong>{fmtRub(p.total_amount)}</strong></span>
                    </>
                  ) : (
                    <span><strong>{fmtRub(p.total_amount)}</strong></span>
                  )}
                  {p.note && <span className="muted"> — «{p.note}»</span>}
                </div>
                <button
                  type="button"
                  className={`btn-delete${confirmingId === p.id ? ' is-confirming' : ''}`}
                  onClick={() => { void handleDelete(p.id); }}
                  title="Удалить оплату"
                  aria-label="Удалить"
                >
                  {confirmingId === p.id ? 'Точно удалить?' : '🗑'}
                </button>
              </li>
            ))}
          </ul>
          )}
        </>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Обновить CSS под 3-колоночную строку**

В `journal_django/frontend/admin-src/src/styles/pages/detail.css` заменить правило `.balance-block__direction-row` (строки 544-550):

```css
.balance-block__direction-row {
  display: grid;
  grid-template-columns: 12px 1fr auto;
  gap: 12px;
  align-items: center;
  padding: 4px 0;
}
```

- [ ] **Step 3: Типчек**

Run: `cd journal_django/frontend/admin-src && npm run typecheck`
Expected: ошибки только в `DebtsCard.tsx` (Task 11 ещё не сделан). `StudentBalanceBlock.tsx` — без ошибок.

- [ ] **Step 4: Ручная проверка в браузере**

Запустить dev-сервер (`npm run dev` в `journal_django/frontend/admin-src`, либо через existующий `/run`-скилл проекта), открыть карточку ученика с оплатами на двух направлениях и посещениями в обоих — убедиться, что:
- «Осталось оплаченных уроков» показывает одно число (не список).
- Оба новых блока сворачиваются/разворачиваются по клику, по умолчанию свёрнуты.
- История оплат работает как раньше.

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/students/StudentBalanceBlock.tsx journal_django/frontend/admin-src/src/styles/pages/detail.css
git commit -m "feat(admin-fe): StudentBalanceBlock shows pooled balance + collapsible direction breakdowns"
```

---

### Task 11: Фронтенд — `DebtsCard.tsx`

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/dashboard/DebtsCard.tsx`

- [ ] **Step 1: Переписать компонент**

Заменить содержимое `journal_django/frontend/admin-src/src/pages/dashboard/DebtsCard.tsx` целиком:

```tsx
import { Link } from 'react-router-dom';
import { EntityLink } from '../../components/EntityLink';
import { EmptyState } from '../../components/ui/EmptyState';
import { fmtLessons } from '../../lib/format';
import type { DashboardDebt } from '../../lib/types';

interface Props {
  debts: DashboardDebt[];
  total: number;
}

export function DebtsCard({ debts, total }: Props) {
  return (
    <section className="dash-card dash-debts">
      <header className="dash-card__head">
        <h2 className="dash-card__title">Долги</h2>
        <span className="dash-card__count">{total}</span>
      </header>
      {debts.length === 0 ? (
        <EmptyState>Долгов нет</EmptyState>
      ) : (
        <ul className="dash-debts__list">
          {debts.map((d) => (
            <li key={d.student_id} className="dash-debts__row">
              <span className="dash-debts__name">
                <EntityLink section="students" id={d.student_id} text={d.student_name} />
              </span>
              <span className="dash-debts__balance mono">{fmtLessons(d.balance)}</span>
            </li>
          ))}
          {total > debts.length && (
            <li className="dash-debts__more">
              <Link to="/admin/students">… ещё {total - debts.length} → все ученики</Link>
            </li>
          )}
        </ul>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Типчек и билд**

Run: `cd journal_django/frontend/admin-src && npm run typecheck && npm run build`
Expected: без ошибок (0 TS errors, build succeeds).

- [ ] **Step 3: Ручная проверка в браузере**

Открыть `/admin` (дашборд), убедиться, что карточка «Долги» показывает студента и баланс без колонки направления, и вёрстка не съехала (убрана одна из колонок в списке).

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/dashboard/DebtsCard.tsx
git commit -m "feat(admin-fe): DebtsCard drops per-direction column for pooled balance"
```

---

### Task 12: Финальная сверка

**Files:** нет изменений — только верификация.

- [ ] **Step 1: Полный прогон бэкенда**

Run: `cd journal_django && pytest -q`
Expected: все тесты PASS.

- [ ] **Step 2: Полный прогон фронтенда**

Run: `cd journal_django/frontend/admin-src && npm run typecheck && npm run build`
Expected: без ошибок, сборка проходит.

- [ ] **Step 3: Ручная сквозная проверка (verify-скилл)**

Открыть в браузере сценарий из спеки: ученик с оплатой на направлении A и посещёнными уроками на направлении B (созданными вручную через админку или сидом) — убедиться, что общий баланс уменьшился (списался из пула A на посещения B), и обе информационные разбивки на карточке ученика показывают корректные, но раздельные цифры (оплачено — по A, отработано — по B).

- [ ] **Step 4: Итоговый commit (если остались незакоммиченные правки)**

```bash
git status
git add -u
git commit -m "chore: final verification pass for student balance pooling"
```
