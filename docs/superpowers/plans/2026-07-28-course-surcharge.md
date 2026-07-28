# Доплата к абонементу (`payments.kind='surcharge'`) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** дать возможность внести деньги, которые не покупают уроков, а добивают цену конкретного уже купленного абонемента.

**Architecture:** новый вид строки `payments` (`kind='surcharge'`) со ссылкой на родительскую оплату и номер абонемента внутри неё. Расчёт денег меняется в одном месте: оплата, у которой есть доплаты, дробится на партии по 4 урока, и доплата поднимает цену только своего блока. Оплаты без доплат считаются ровно как раньше.

**Tech Stack:** Django 5 + DRF, PostgreSQL, pytest, React 19 + TanStack Query (admin SPA).

**Спека:** `docs/superpowers/specs/2026-07-28-course-surcharge-design.md`

---

## Правила этого репозитория (обязательно)

- **Коммитить и пушить ТОЛЬКО по явной просьбе пользователя.** Шаги «Commit» = показать `git status --short` и `git diff --stat`. Субагентам git запрещён.
- Рабочий каталог — `journal_django/`, интерпретатор — `.venv/Scripts/python.exe`.
- Тест-БД `journal_test` общая; `scripts/recreate_test_db.*` не запускать.
- `npm run build` не запускать — пересборку `dist` делает владелец.
- Native form-элементы в admin SPA запрещены: только `components/form/`.
- Деньги — только `Decimal`, округление копеек — существующий `round_kopecks`.

## Файловая структура

| Файл | Ответственность |
|---|---|
| `apps/payments/models.py` | поля `parent_payment`, `subscription_index`, CHECK-и |
| `apps/payments/migrations/0010_*.py` | миграция + db-каскад RunSQL |
| `apps/finances/lots.py` (новый) | ЕДИНСТВЕННОЕ место построения партий FIFO + дробление на блоки |
| `apps/finances/repository.py` | `fifo_inputs`, `student_fifo_remaining` переходят на `build_lots` |
| `apps/finances/reports.py` | доплата в поступления месяца |
| `apps/payments/serializers.py` | приём полей доплаты |
| `apps/payments/repository.py` | ветка `surcharge` в `create_payment` |
| `apps/changelog/summary.py` | подписи новых полей |
| `frontend/admin-src/src/pages/students/StudentBalanceBlock.tsx` | блоки абонементов, доплаты, удаление |
| `frontend/admin-src/src/pages/students/SurchargeModal.tsx` (новый) | диалог внесения доплаты |
| `frontend/admin-src/src/hooks/usePayments.ts` | мутация доплаты |
| `apps/payments/tests/test_surcharge.py` (новый) | модель + API + RBAC |
| `apps/finances/tests/test_lots_blocks.py` (новый) | дробление и цены |

---

## Task 1: Поля и миграция

**Files:**
- Modify: `apps/payments/models.py`
- Create: `apps/payments/migrations/0010_*` (генерируется + RunSQL)
- Test: `apps/payments/tests/test_surcharge.py`

- [ ] **Step 1: Написать падающий тест**

Создать `apps/payments/tests/test_surcharge.py`:

```python
"""
Доплата к абонементу (payments.kind='surcharge').

См. docs/superpowers/specs/2026-07-28-course-surcharge-design.md.
Схема journal_test общая — данные создаём и чистим сами.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction


@pytest.fixture
def parent_payment(direction_fixture, student_fixture):
    """Оплата: 9 абонементов, 36 уроков, 44 000 ₽. Возвращает id."""
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO payments (student_id, direction_id, subscriptions_count,
                                  lessons_count, kind, unit_price, total_amount,
                                  paid_at, created_at)
            VALUES (%s, %s, 9, 36, 'purchase', 4888.89, 44000, DATE '2026-01-10', NOW())
            RETURNING id
            """,
            [student_fixture, direction_fixture],
        )
        pid = cur.fetchone()[0]
    yield pid
    with connection.cursor() as cur:
        cur.execute('DELETE FROM payments WHERE parent_payment_id = %s', [pid])
        cur.execute('DELETE FROM payments WHERE id = %s', [pid])


@pytest.mark.django_db
def test_surcharge_row_is_stored(parent_payment, student_fixture, direction_fixture):
    """Доплата хранится без уроков, со ссылкой на оплату и номером абонемента."""
    from apps.payments.models import Payment
    s = Payment.objects.create(
        student_id=student_fixture, direction_id=direction_fixture,
        kind='surcharge', parent_payment_id=parent_payment, subscription_index=2,
        lessons_count=None, subscriptions_count=None,
        unit_price=Decimal('0'), total_amount=Decimal('1000'),
        paid_at='2026-02-10', created_at='2026-02-10T00:00:00+03:00',
    )
    s.refresh_from_db()
    assert s.lessons_count is None
    assert s.subscription_index == 2
    assert s.parent_payment_id == parent_payment


@pytest.mark.django_db
def test_surcharge_requires_parent(student_fixture, direction_fixture):
    """Доплата без родителя запрещена CHECK-констрейнтом."""
    from apps.payments.models import Payment
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Payment.objects.create(
                student_id=student_fixture, direction_id=direction_fixture,
                kind='surcharge', parent_payment_id=None, subscription_index=1,
                lessons_count=None, unit_price=Decimal('0'), total_amount=Decimal('1000'),
                paid_at='2026-02-10', created_at='2026-02-10T00:00:00+03:00',
            )


@pytest.mark.django_db
def test_purchase_cannot_have_parent(parent_payment, student_fixture, direction_fixture):
    """Родитель есть только у доплаты — обычная покупка с parent запрещена."""
    from apps.payments.models import Payment
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Payment.objects.create(
                student_id=student_fixture, direction_id=direction_fixture,
                kind='purchase', parent_payment_id=parent_payment, subscription_index=1,
                lessons_count=4, unit_price=Decimal('1000'), total_amount=Decimal('4000'),
                paid_at='2026-02-10', created_at='2026-02-10T00:00:00+03:00',
            )


@pytest.mark.django_db
def test_deleting_parent_cascades_surcharges(parent_payment, student_fixture, direction_fixture):
    """Удаление оплаты уносит её доплаты (db-каскад)."""
    from apps.payments.models import Payment
    Payment.objects.create(
        student_id=student_fixture, direction_id=direction_fixture,
        kind='surcharge', parent_payment_id=parent_payment, subscription_index=1,
        lessons_count=None, unit_price=Decimal('0'), total_amount=Decimal('500'),
        paid_at='2026-02-10', created_at='2026-02-10T00:00:00+03:00',
    )
    with connection.cursor() as cur:
        cur.execute('DELETE FROM payments WHERE id = %s', [parent_payment])
        cur.execute('SELECT COUNT(*) FROM payments WHERE parent_payment_id = %s', [parent_payment])
        assert cur.fetchone()[0] == 0
```

Фикстуры `direction_fixture` / `student_fixture` уже есть в `apps/payments/tests/conftest.py` — новых не заводить.

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv/Scripts/python.exe -m pytest apps/payments/tests/test_surcharge.py -q`
Expected: FAIL — `Payment() got unexpected keyword arguments: 'parent_payment_id'`

- [ ] **Step 3: Поля в модели**

В `apps/payments/models.py` после `created_by` добавить:

```python
    # Доплата к абонементу (kind='surcharge'): деньги без уроков, добивающие цену
    # уже купленного блока. parent_payment — та оплата, чей абонемент дорожает;
    # subscription_index — номер абонемента внутри неё (1-based). У остальных видов
    # оба поля NULL. См. docs/superpowers/specs/2026-07-28-course-surcharge-design.md.
    parent_payment = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        db_column='parent_payment_id',
        related_name='surcharges',
        null=True,
        blank=True,
    )
    subscription_index = models.IntegerField(null=True, blank=True)
```

В `Meta.constraints` добавить:

```python
            # Форма доплаты: деньги есть, уроков нет, родитель и номер блока обязательны.
            models.CheckConstraint(
                name='payments_surcharge_shape',
                condition=(
                    ~models.Q(kind='surcharge')
                    | (models.Q(lessons_count__isnull=True)
                       & models.Q(total_amount__gt=0)
                       & models.Q(parent_payment__isnull=False)
                       & models.Q(subscription_index__gte=1))
                ),
            ),
            # Родитель и номер блока бывают ТОЛЬКО у доплаты.
            models.CheckConstraint(
                name='payments_parent_only_surcharge',
                condition=(
                    models.Q(kind='surcharge')
                    | (models.Q(parent_payment__isnull=True)
                       & models.Q(subscription_index__isnull=True))
                ),
            ),
```

В существующем `payments_kind_check` добавить `'surcharge'` в список:

```python
                condition=models.Q(kind__in=['purchase', 'refund', 'extra', 'surcharge']),
```

- [ ] **Step 4: Сгенерировать миграцию**

Run: `.venv/Scripts/python.exe manage.py makemigrations payments`
Expected: создан `apps/payments/migrations/0010_*.py` с AddField для `payment` и `paymentevent` (pghistory), пересозданными триггерами и тремя AddConstraint.

Проверить наличие pghistory-поля: `grep -c "paymentevent" apps/payments/migrations/0010_*.py` → ≥ 1.

- [ ] **Step 5: Дописать db-каскад в миграцию**

Django ставит `ON DELETE` на уровне приложения, а тест удаляет строку сырым SQL. В конец `operations` созданной миграции добавить:

```python
        migrations.RunSQL(
            sql="""
                ALTER TABLE payments
                    DROP CONSTRAINT IF EXISTS payments_parent_payment_id_fkey,
                    ADD CONSTRAINT payments_parent_payment_id_fkey
                        FOREIGN KEY (parent_payment_id) REFERENCES payments(id)
                        ON DELETE CASCADE;
            """,
            reverse_sql="""
                ALTER TABLE payments
                    DROP CONSTRAINT IF EXISTS payments_parent_payment_id_fkey,
                    ADD CONSTRAINT payments_parent_payment_id_fkey
                        FOREIGN KEY (parent_payment_id) REFERENCES payments(id);
            """,
        ),
```

Имя реального FK-констрейнта проверить до правки:
`.venv/Scripts/python.exe manage.py sqlmigrate payments 0010 | grep -i "foreign key"` — если Django назвал его иначе, подставить фактическое имя.

- [ ] **Step 6: Применить к обеим базам**

Run: `.venv/Scripts/python.exe manage.py migrate payments`
Run: `.venv/Scripts/python.exe manage.py migrate payments --settings=config.settings.test`
Expected: обе — `Applying payments.0010_... OK`

- [ ] **Step 7: Прогнать тесты**

Run: `.venv/Scripts/python.exe -m pytest apps/payments -q`
Expected: 0 failed, включая 4 новых теста

- [ ] **Step 8: Показать изменения**

Run: `git status --short && git diff --stat`

---

## Task 2: Единое место построения партий (рефактор без смены поведения)

Сейчас партии строятся дважды почти одинаково: `fifo_inputs` (все ученики) и `student_fifo_remaining` (один ученик). Прежде чем добавлять дробление, сводим обе реализации в одну функцию — иначе дробление придётся дублировать.

**Files:**
- Create: `apps/finances/lots.py`
- Modify: `apps/finances/repository.py` (`fifo_inputs` ~строки 126-147, `student_fifo_remaining` ~строки 304-332)
- Test: `apps/finances/tests/test_lots_blocks.py`

- [ ] **Step 1: Написать падающий тест**

Создать `apps/finances/tests/test_lots_blocks.py`:

```python
"""
Построение партий FIFO из оплат (apps/finances/lots.py).

Партия без доплат = вся оплата (прежнее поведение, регресс).
Партия с доплатами дробится на абонементы по 4 урока — дорожает только свой блок.
См. docs/superpowers/specs/2026-07-28-course-surcharge-design.md.
"""
from __future__ import annotations

from decimal import Decimal

from apps.finances.lots import build_lots


def _row(pid, lessons, amount, kind='purchase', direction_id=7):
    return {
        'id': pid, 'lessons_count': lessons, 'total_amount': Decimal(amount),
        'kind': kind, 'direction_id': direction_id,
    }


def test_payment_without_surcharges_is_single_lot():
    """Без доплат — одна партия на оплату, цена как раньше."""
    lots = build_lots([_row(1, 36, '44000')], {})
    assert len(lots) == 1
    assert lots[0]['lessons'] == 36
    assert lots[0]['price_per_lesson'] == Decimal('44000') / Decimal('36')
    assert lots[0]['direction_id'] == 7


def test_extra_payment_has_no_direction():
    """Доплата сверх курса (kind='extra') в лимит направления не входила —
    партия остаётся без направления (прежнее правило, регресс)."""
    lots = build_lots([_row(1, 1, '1500', kind='extra')], {})
    assert lots[0]['direction_id'] is None


def test_zero_lessons_payment_skipped():
    """Guard: оплата без уроков партии не образует (деление на ноль)."""
    assert build_lots([_row(1, 0, '1000')], {}) == []
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv/Scripts/python.exe -m pytest apps/finances/tests/test_lots_blocks.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.finances.lots'`

- [ ] **Step 3: Создать модуль**

Создать `apps/finances/lots.py`:

```python
"""
Построение партий (lots) FIFO из строк оплат — ЕДИНСТВЕННОЕ место этой логики.

Партия — это набор уроков с одной ценой. По умолчанию партия = вся оплата
(цена = сумма / уроки), как было исторически. Если у оплаты есть доплаты к
абонементам (kind='surcharge'), она дробится на блоки по 4 урока: доплата
поднимает цену ТОЛЬКО своего блока. См.
docs/superpowers/specs/2026-07-28-course-surcharge-design.md.

Чистые функции без ORM: вызывающий (apps/finances/repository.py) подаёт строки и
словарь доплат, здесь только арифметика. Deciaml везде — деньги считаются точно.
"""
from __future__ import annotations

from decimal import Decimal

# Абонемент = 4 урока. Та же величина, что LESSONS_PER_MONTH в revenue_forecast,
# но смысл другой (там — темп занятий), поэтому константа своя.
LESSONS_PER_SUBSCRIPTION = 4


def build_lots(rows, surcharges_by_parent):
    """
    rows: оплаты В ПОРЯДКЕ FIFO (paid_at, id), каждая —
          {'id', 'lessons_count', 'total_amount', 'kind', 'direction_id'}.
          Строки kind='refund' вызывающий сюда НЕ подаёт (они не партии, а
          синтетические списания).
    surcharges_by_parent: {parent_payment_id: {subscription_index: Decimal сумма}}.

    Возвращает [{'lessons': int, 'price_per_lesson': Decimal, 'direction_id': int|None}].
    """
    lots = []
    for r in rows:
        raw = r['lessons_count']
        lessons = int(raw) if raw is not None else 0
        if lessons <= 0:
            continue  # guard: NULL/0 — деление на ноль ломает суммы
        # Направление партии: доплата сверх курса (kind='extra') лимит не занимала,
        # поэтому её остаток не привязан к направлению (прежнее правило).
        direction_id = None if r['kind'] == 'extra' else r['direction_id']
        total = Decimal(r['total_amount'])
        surcharges = surcharges_by_parent.get(r['id']) or {}
        if not surcharges:
            lots.append({
                'lessons': lessons,
                'price_per_lesson': total / Decimal(lessons),
                'direction_id': direction_id,
            })
            continue
        lots.extend(_split_into_blocks(lessons, total, surcharges, direction_id))
    return lots


def _split_into_blocks(lessons: int, total: Decimal, surcharges: dict, direction_id):
    """
    Разрезать оплату на абонементы по 4 урока и раздать доплаты по номерам блоков.

    Доля блока в сумме оплаты пропорциональна его урокам, поэтому сумма долей
    равна сумме оплаты точно (Decimal, без округления) — иначе деньги «утекут».
    Последний блок может быть неполным (предоплата 1–3 урока, доплата сверх курса).
    """
    out = []
    remaining = lessons
    index = 1
    base_per_lesson = total / Decimal(lessons)
    while remaining > 0:
        block_lessons = min(LESSONS_PER_SUBSCRIPTION, remaining)
        base = base_per_lesson * Decimal(block_lessons)
        extra = surcharges.get(index, Decimal('0'))
        out.append({
            'lessons': block_lessons,
            'price_per_lesson': (base + extra) / Decimal(block_lessons),
            'direction_id': direction_id,
        })
        remaining -= block_lessons
        index += 1
    return out
```

- [ ] **Step 4: Прогнать тест модуля**

Run: `.venv/Scripts/python.exe -m pytest apps/finances/tests/test_lots_blocks.py -q`
Expected: 3 passed

- [ ] **Step 5: Перевести `fifo_inputs` на общую функцию**

В `apps/finances/repository.py` в `fifo_inputs` заменить ручную сборку партий на вызов `build_lots`. Было (цикл по `lots_rows`, ветка не-refund):

```python
        lessons = int(raw) if raw is not None else 0  # покупки всегда целые
        if not (lessons > 0):  # guard: NULL/0
            continue
        lots_by_key.setdefault(key, []).append({
            'lessons': lessons,
            'price_per_lesson': to_decimal(r['total_amount']) / Decimal(lessons),
            'direction_id': None if r['kind'] == 'extra' else r['direction_id'],
        })
        purchased_by_key[key] = purchased_by_key.get(key, 0) + lessons
```

Стало: собрать строки по ученику, затем один вызов на ученика.

```python
    # Партии строим ОДНОЙ функцией с student_fifo_remaining (apps/finances/lots.py) —
    # иначе дробление на абонементы пришлось бы дублировать и оно бы разъехалось.
    rows_by_key: dict[str, list] = {}
    for r in lots_rows:
        key = str(r['student_id'])
        if r['kind'] == 'refund':
            ...  # ветка refund_cons остаётся как была
            continue
        rows_by_key.setdefault(key, []).append(r)
        raw = r['lessons_count']
        lessons = int(raw) if raw is not None else 0
        if lessons > 0:
            purchased_by_key[key] = purchased_by_key.get(key, 0) + lessons

    surcharges = surcharges_by_parent()
    for key, rows in rows_by_key.items():
        lots_by_key[key] = build_lots(rows, surcharges)
```

Запрос `lots_rows` дополнить полем `'id'` (нужно для сопоставления с доплатами) и исключить сами доплаты из партий — они не покупки:

```python
    lots_rows = (
        Payment.objects
        .exclude(kind='surcharge')          # доплаты партий не образуют
        .order_by('student_id', 'paid_at', 'id')
        .values('id', 'student_id', 'total_amount', 'lessons_count', 'kind', 'paid_at',
                'direction_id')
    )
```

Добавить в тот же модуль helper:

```python
def surcharges_by_parent() -> dict[int, dict[int, Decimal]]:
    """{parent_payment_id: {subscription_index: сумма}} — доплаты к абонементам.
    Один запрос: доплат мало (редкий случай недобора платежа)."""
    out: dict[int, dict[int, Decimal]] = {}
    rows = (
        Payment.objects.filter(kind='surcharge')
        .values('parent_payment_id', 'subscription_index', 'total_amount')
    )
    for r in rows:
        bucket = out.setdefault(r['parent_payment_id'], {})
        idx = r['subscription_index']
        bucket[idx] = bucket.get(idx, Decimal('0')) + to_decimal(r['total_amount'])
    return out
```

- [ ] **Step 6: Перевести `student_fifo_remaining` на ту же функцию**

Там же заменить ручной цикл построения `lots` на:

```python
    payment_rows = (
        Payment.objects.filter(student_id=student_id)
        .exclude(kind='surcharge')
        .order_by('paid_at', 'id')
        .values('id', 'total_amount', 'lessons_count', 'kind', 'paid_at', 'direction_id')
    )
    lots = build_lots(
        [r for r in payment_rows if r['kind'] != 'refund'],
        surcharges_by_parent(),
    )
    refund_cons = [
        {
            'units': -to_decimal(r['lessons_count']) if r['lessons_count'] is not None else Decimal('0'),
            'date': _date_str(r['paid_at']),
            'direction_id': None,
            'refund': True,
        }
        for r in payment_rows if r['kind'] == 'refund'
    ]
```

- [ ] **Step 7: Регресс — существующие финансовые тесты должны пройти без правок**

Run: `.venv/Scripts/python.exe -m pytest apps/finances apps/payments apps/dashboard -q`
Expected: 0 failed. Ни один существующий тест менять НЕЛЬЗЯ: это рефактор без смены поведения. Если тест упал — расчёт разъехался, чинить код, а не тест.

- [ ] **Step 8: Показать изменения**

Run: `git status --short && git diff --stat`

---

## Task 3: Дробление и цены с доплатами

**Files:**
- Modify: `apps/finances/tests/test_lots_blocks.py` (дописать)
- Проверка: код уже написан в Task 2 (`_split_into_blocks`) — эта задача его валидирует и чинит найденное

- [ ] **Step 1: Дописать тесты**

В конец `apps/finances/tests/test_lots_blocks.py`:

```python
def test_surcharge_raises_price_of_its_block_only():
    """Доплата 1000 ₽ ко 2-му абонементу: дорожают только его 4 урока."""
    lots = build_lots([_row(1, 36, '44000')], {1: {2: Decimal('1000')}})
    assert len(lots) == 9                       # 36 уроков = 9 абонементов
    base = Decimal('44000') / Decimal('36')
    assert lots[0]['price_per_lesson'] == base  # 1-й блок — базовая цена
    assert lots[2]['price_per_lesson'] == base  # 3-й блок — базовая цена
    expected = (base * 4 + Decimal('1000')) / Decimal('4')
    assert lots[1]['price_per_lesson'] == expected


def test_total_money_preserved_with_surcharges():
    """Сумма по всем партиям = сумма оплаты + доплат, до копейки."""
    lots = build_lots([_row(1, 36, '44000')], {1: {2: Decimal('1000'), 5: Decimal('500')}})
    total = sum(lot['price_per_lesson'] * Decimal(lot['lessons']) for lot in lots)
    assert total == Decimal('44000') + Decimal('1000') + Decimal('500')


def test_incomplete_last_block():
    """Уроков не кратно 4 (предоплата) — последний блок неполный, деньги сходятся."""
    lots = build_lots([_row(1, 6, '6000')], {1: {2: Decimal('600')}})
    assert [lot['lessons'] for lot in lots] == [4, 2]
    total = sum(lot['price_per_lesson'] * Decimal(lot['lessons']) for lot in lots)
    assert total == Decimal('6600')


def test_surcharge_to_missing_block_is_ignored_safely():
    """Номер блока за пределами оплаты (битые данные) не роняет расчёт и не теряет
    уроки — деньги такой доплаты просто не попадают в партии."""
    lots = build_lots([_row(1, 4, '4000')], {1: {9: Decimal('100')}})
    assert [lot['lessons'] for lot in lots] == [4]
    assert lots[0]['price_per_lesson'] == Decimal('1000')
```

- [ ] **Step 2: Прогнать**

Run: `.venv/Scripts/python.exe -m pytest apps/finances/tests/test_lots_blocks.py -q`
Expected: 7 passed. Если `test_surcharge_to_missing_block_is_ignored_safely` падает — добавить в `_split_into_blocks` защиту: доплаты с номерами больше числа блоков игнорируются (они и так не попадут в цикл, тест это фиксирует).

- [ ] **Step 3: Показать изменения**

Run: `git status --short && git diff --stat`

---

## Task 4: API — приём доплаты и валидация

**Files:**
- Modify: `apps/payments/serializers.py`, `apps/payments/repository.py` (`create_payment`), `apps/payments/services.py`
- Test: `apps/payments/tests/test_surcharge.py` (дописать)

- [ ] **Step 1: Дописать падающие тесты**

```python
BASE_URL = '/api/admin/payments'


def _surcharge_payload(parent_id, index=2, amount='1000'):
    return {
        'kind': 'surcharge',
        'parent_payment_id': parent_id,
        'subscription_index': index,
        'total_amount': amount,
        'paid_at': '2026-02-10',
    }


@pytest.mark.django_db
def test_api_create_surcharge(admin_client, parent_payment, student_fixture):
    """Доплата создаётся, баланс уроков не меняется."""
    from apps.finances.repository import balance_for_student
    before = balance_for_student(student_fixture)

    resp = admin_client.post(BASE_URL, _surcharge_payload(parent_payment), format='json')

    assert resp.status_code == 201, resp.content
    assert resp.json()['kind'] == 'surcharge'
    assert resp.json()['lessons_count'] is None
    assert balance_for_student(student_fixture) == before


@pytest.mark.django_db
def test_api_surcharge_block_out_of_range(admin_client, parent_payment):
    """Номер абонемента больше, чем есть в оплате → 400."""
    resp = admin_client.post(BASE_URL, _surcharge_payload(parent_payment, index=99),
                             format='json')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_api_surcharge_parent_of_another_student(admin_client, parent_payment):
    """Родитель другого ученика → 400 (иначе деньги уедут не туда)."""
    with connection.cursor() as cur:
        cur.execute("INSERT INTO students (full_name, created_at) "
                    "VALUES ('__sur_other__', NOW()) RETURNING id")
        other = cur.fetchone()[0]
    payload = _surcharge_payload(parent_payment)
    payload['student_id'] = other
    resp = admin_client.post(BASE_URL, payload, format='json')
    with connection.cursor() as cur:
        cur.execute('DELETE FROM students WHERE id = %s', [other])
    assert resp.status_code == 400


@pytest.mark.django_db
def test_api_surcharge_does_not_consume_course_cap(admin_client, parent_payment,
                                                   student_fixture, direction_fixture):
    """Доплата не занимает лимит курса: после неё обычная покупка всё ещё возможна
    ровно на остаток уроков направления."""
    admin_client.post(BASE_URL, _surcharge_payload(parent_payment), format='json')
    from apps.payments.models import Payment
    from django.db.models import Sum
    used = (Payment.objects
            .filter(student_id=student_fixture, direction_id=direction_fixture,
                    kind__in=('purchase', 'refund'))
            .aggregate(s=Sum('lessons_count'))['s'])
    assert used == 36  # доплата в сумму уроков не вошла


@pytest.mark.django_db
def test_manager_cannot_create_surcharge(manager_client, parent_payment):
    """RBAC: доплата — деньги, менеджеру запрещена (как и обычная оплата)."""
    resp = manager_client.post(BASE_URL, _surcharge_payload(parent_payment), format='json')
    assert resp.status_code == 403
```

- [ ] **Step 2: Убедиться, что падают**

Run: `.venv/Scripts/python.exe -m pytest apps/payments/tests/test_surcharge.py -q -k api`
Expected: FAIL — сериализатор не знает `kind='surcharge'`

- [ ] **Step 3: Сериализатор**

В `apps/payments/serializers.py` расширить `PaymentCreateSerializer`:

```python
    # kind='surcharge' — доплата к абонементу: денег больше, уроков нет.
    kind = serializers.ChoiceField(
        choices=['purchase', 'extra', 'surcharge'], required=False, default='purchase')
    parent_payment_id = serializers.IntegerField(min_value=1, required=False)
    subscription_index = serializers.IntegerField(min_value=1, required=False)
```

`direction_id` и `lessons_count` для доплаты не обязательны (направление берётся у
родителя, уроков нет) — сделать их условно необязательными через `validate`:

```python
    def validate(self, attrs):
        if attrs.get('kind') == 'surcharge':
            missing = [f for f in ('parent_payment_id', 'subscription_index')
                       if attrs.get(f) is None]
            if missing:
                raise serializers.ValidationError(
                    {f: 'Обязательно для доплаты' for f in missing})
            attrs.pop('lessons_count', None)
            return attrs
        for field in ('direction_id', 'lessons_count'):
            if attrs.get(field) is None:
                raise serializers.ValidationError({field: 'Обязательное поле'})
        return attrs
```

и снять обязательность у полей, которых у доплаты нет:

```python
    direction_id = serializers.IntegerField(min_value=1, required=False)
    lessons_count = serializers.IntegerField(min_value=1, required=False)
```

`validate_lessons_count` оставить как есть — он вызывается только когда поле пришло.

- [ ] **Step 4: Ветка `surcharge` в `create_payment`**

В `apps/payments/repository.py` в начале `create_payment`, ДО работы с направлением, добавить отдельный путь:

```python
    if data.get('kind') == 'surcharge':
        return _create_surcharge(data)
```

и саму функцию рядом:

```python
def _create_surcharge(data: dict) -> dict:
    """
    Доплата к абонементу: деньги без уроков, поднимающие цену конкретного блока.

    Лимит курса не трогаем (уроков не добавляем), направление берём у родителя —
    иначе доплата не попала бы в фильтры отчётов по направлению. Номер блока
    проверяем здесь: в CHECK его не выразить (зависит от строки-родителя).
    """
    from apps.finances.lots import LESSONS_PER_SUBSCRIPTION

    parent = (
        Payment.objects
        .filter(id=data['parent_payment_id'])
        .values('id', 'student_id', 'direction_id', 'lessons_count', 'kind')
        .first()
    )
    if parent is None:
        return {'error': 'parent_not_found'}
    if parent['student_id'] != data['student_id']:
        return {'error': 'parent_other_student'}
    if parent['kind'] not in ('purchase', 'extra'):
        return {'error': 'parent_not_purchase'}

    lessons = int(parent['lessons_count'] or 0)
    blocks = -(-lessons // LESSONS_PER_SUBSCRIPTION)  # ceil
    index = data['subscription_index']
    if not (1 <= index <= blocks):
        return {'error': 'block_out_of_range', 'blocks': blocks}

    obj = Payment.objects.create(
        student_id=data['student_id'],
        direction_id=parent['direction_id'],
        subscriptions_count=None,
        lessons_count=None,
        kind='surcharge',
        parent_payment_id=parent['id'],
        subscription_index=index,
        unit_price=Decimal('0'),
        total_amount=round_kopecks(data['total_amount']),
        paid_at=data['paid_at'],
        note=data.get('note') or None,
        created_by=data.get('created_by') or None,
        created_at=Now(),
    )
    row = _normalize_lessons_count(dictrow(Payment.objects.filter(pk=obj.pk).values()))
    return {'payment': row}
```

- [ ] **Step 5: Ответы view на новые ошибки**

В `apps/payments/views.py` в `post` после существующих веток ошибок добавить:

```python
        if result.get('error') in ('parent_not_found', 'parent_other_student',
                                   'parent_not_purchase', 'block_out_of_range'):
            messages = {
                'parent_not_found': 'Оплата, к которой вносится доплата, не найдена',
                'parent_other_student': 'Оплата принадлежит другому ученику',
                'parent_not_purchase': 'Доплату можно вносить только к оплате курса',
                'block_out_of_range': 'В этой оплате нет абонемента с таким номером',
            }
            return Response(
                {'error': result['error'], 'message': messages[result['error']]},
                status=status.HTTP_400_BAD_REQUEST,
            )
```

- [ ] **Step 6: Прогнать**

Run: `.venv/Scripts/python.exe -m pytest apps/payments -q`
Expected: 0 failed

- [ ] **Step 7: Показать изменения**

Run: `git status --short && git diff --stat`

---

## Task 5: Доплата в поступлениях месяца и подписи журнала

**Files:**
- Modify: `apps/finances/reports.py:86`, `apps/changelog/summary.py`
- Test: `apps/payments/tests/test_surcharge.py` (дописать)

- [ ] **Step 1: Дописать тест**

```python
@pytest.mark.django_db
def test_surcharge_counts_in_month_cash(admin_client, parent_payment, student_fixture):
    """Доплата попадает в поступления своего месяца — ради этого фича и делалась."""
    from apps.finances.reports import collect_monthly_report
    admin_client.post(BASE_URL, _surcharge_payload(parent_payment), format='json')

    rows = collect_monthly_report('2026-02')
    row = next(r for r in rows if r.student_id == student_fixture)
    assert row.paid_month_total == Decimal('1000')


@pytest.mark.django_db
def test_surcharge_raises_refund_amount(admin_client, parent_payment, student_fixture):
    """Возврат считает остаток по подорожавшим ценам: доплата к неотработанному
    абонементу увеличивает сумму к возврату ровно на себя."""
    from apps.finances.repository import student_fifo_remaining
    before = student_fifo_remaining(student_fixture)['remaining_value']

    admin_client.post(BASE_URL, _surcharge_payload(parent_payment), format='json')

    after = student_fifo_remaining(student_fixture)['remaining_value']
    assert after - before == Decimal('1000')


@pytest.mark.django_db
def test_surcharge_with_half_lesson_group(admin_client, parent_payment, student_fixture):
    """45-минутный формат не сбивает деньги: доплата меняет цену урока, а вес
    потребления (0.5) остаётся на стороне посещаемости — суммы партий не зависят
    от длительности занятия."""
    from apps.finances.lots import build_lots
    lots = build_lots(
        [{'id': parent_payment, 'lessons_count': 36, 'total_amount': Decimal('44000'),
          'kind': 'purchase', 'direction_id': 1}],
        {parent_payment: {2: Decimal('1000')}},
    )
    total = sum(lot['price_per_lesson'] * Decimal(lot['lessons']) for lot in lots)
    assert total == Decimal('45000')


def test_changelog_labels_for_surcharge_fields():
    """Новые поля подписаны по-русски, иначе журнал изменений покажет имена колонок."""
    from apps.changelog.summary import FIELD_RU
    assert FIELD_RU['parent_payment_id'] == 'доплата к оплате'
    assert FIELD_RU['subscription_index'] == 'номер абонемента'
```

- [ ] **Step 2: Убедиться, что падают**

Run: `.venv/Scripts/python.exe -m pytest apps/payments/tests/test_surcharge.py -q -k "month_cash or changelog"`
Expected: FAIL — `paid_month_total` равен 0, `KeyError` на подписи

- [ ] **Step 3: Правки**

В `apps/finances/reports.py` расширить фильтр и комментарий:

```python
    # kind__in=['purchase','extra','surcharge']: 'extra' — доплата сверх курса
    # (полноценная партия), 'surcharge' — доплата к абонементу (денег больше,
    # уроков нет). Обе — реально полученные деньги, поэтому в кассу месяца входят.
    # refund не входит: это возврат, он гасит остаток отдельной записью в FIFO.
    payment_rows = (
        Payment.objects
        .filter(kind__in=['purchase', 'extra', 'surcharge'],
                paid_at__gte=month_start, paid_at__lte=month_end)
```

В `apps/changelog/summary.py` в словарь `FIELD_RU` рядом с оплатами добавить:

```python
    'parent_payment_id': 'доплата к оплате', 'subscription_index': 'номер абонемента',
```

- [ ] **Step 4: Прогнать**

Run: `.venv/Scripts/python.exe -m pytest apps/payments apps/finances apps/changelog -q`
Expected: 0 failed

- [ ] **Step 5: Показать изменения**

Run: `git status --short && git diff --stat`

---

## Task 6: Интерфейс — абонементы, доплата, удаление

**Files:**
- Create: `frontend/admin-src/src/pages/students/SurchargeModal.tsx`
- Modify: `frontend/admin-src/src/hooks/usePayments.ts`, `frontend/admin-src/src/pages/students/StudentBalanceBlock.tsx`, `frontend/admin-src/src/lib/shared-types.ts`

- [ ] **Step 1: Типы**

В `lib/shared-types.ts` в тип `Payment` добавить:

```ts
  // Доплата к абонементу (kind='surcharge'): деньги без уроков, поднимающие цену
  // конкретного блока родительской оплаты.
  parent_payment_id?: number | null;
  subscription_index?: number | null;
```

и в union вида оплаты добавить `'surcharge'` (найти существующее объявление `kind`
в этом же типе и расширить его; если это `string` — оставить как есть).

- [ ] **Step 2: Мутация**

В `hooks/usePayments.ts` в объект мутаций добавить:

```ts
    surcharge: useMutation({
      mutationFn: (body: {
        student_id: number;
        parent_payment_id: number;
        subscription_index: number;
        total_amount: string;
        paid_at: string;
        note?: string | null;
      }) => api<Payment>('POST', '/api/admin/payments', { ...body, kind: 'surcharge' }),
      onSuccess: invalidate,
    }),
```

(`invalidate` в этом хуке уже есть — переиспользовать его, новых инвалидаций не добавлять.)

- [ ] **Step 3: Диалог доплаты**

Создать `frontend/admin-src/src/pages/students/SurchargeModal.tsx`:

```tsx
import { useState, type FormEvent } from 'react';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { NumberInput } from '../../components/form/NumberInput';
import { DateInput } from '../../components/form/DateInput';
import { Textarea } from '../../components/form/Textarea';
import { usePaymentMutations } from '../../hooks/usePayments';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';

interface Props {
  studentId: number;
  paymentId: number;
  subscriptionIndex: number;
  onClose: () => void;
}

/**
 * Доплата к конкретному абонементу: деньги без уроков, добивающие его цену
 * (недобор платежа со стороны банка). Баланс уроков не меняется, лимит курса не
 * занимается. См. docs/superpowers/specs/2026-07-28-course-surcharge-design.md.
 */
export function SurchargeModal({ studentId, paymentId, subscriptionIndex, onClose }: Props) {
  const muts = usePaymentMutations();
  const showError = useApiError();
  const { toast } = useToast();
  const [amount, setAmount] = useState('');
  const [paidAt, setPaidAt] = useState(new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState('');

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!amount || Number(amount) <= 0) { toast('Введите сумму доплаты', 'error'); return; }
    try {
      await muts.surcharge.mutateAsync({
        student_id: studentId,
        parent_payment_id: paymentId,
        subscription_index: subscriptionIndex,
        total_amount: amount,
        paid_at: paidAt,
        note: note.trim() || null,
      });
      toast('Доплата внесена', 'ok');
      onClose();
    } catch (err) { showError(err); }
  };

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Доплата к абонементу №${subscriptionIndex}`}
      footer={
        <button type="submit" form="surcharge-form" className="btn-save"
                disabled={muts.surcharge.isPending}>
          Внести
        </button>
      }
    >
      <form id="surcharge-form" className="modal-form" onSubmit={onSubmit}>
        <p className="muted">
          Деньги добивают цену этого абонемента: уроков не прибавится, лимит курса
          не изменится. Отработанные деньги по его урокам пересчитаются, включая
          прошлые месяцы.
        </p>
        <Field label="Сумма, ₽" required>
          <NumberInput min={1} step="0.01" value={amount}
                       onChange={(e) => setAmount(e.target.value)} required />
        </Field>
        <Field label="Дата поступления" required>
          <DateInput value={paidAt} onChange={(e) => setPaidAt(e.target.value)} required />
        </Field>
        <Field label="Комментарий" full>
          <Textarea value={note} onChange={(e) => setNote(e.target.value)}
                    placeholder="например: недобор платежа банком" />
        </Field>
      </form>
    </Dialog>
  );
}
```

Сверить пропсы `Dialog`, `DateInput`, `Textarea` с их фактическими сигнатурами в
`components/` и поправить при расхождении, сохранив смысл.

- [ ] **Step 4: Абонементы в истории платежей**

В `StudentBalanceBlock.tsx`:

- разложить оплату на блоки для показа:

```tsx
/** Абонементы оплаты: по 4 урока, последний может быть неполным. Цена блока —
 *  базовая доля суммы плюс доплаты именно к нему (то же правило, что на бэке
 *  в apps/finances/lots.py). */
function subscriptionBlocks(p: Payment, surcharges: Payment[]) {
  const lessons = Number(p.lessons_count || 0);
  if (lessons <= 0) return [];
  const basePerLesson = Number(p.total_amount) / lessons;
  const blocks = [];
  let remaining = lessons;
  let index = 1;
  while (remaining > 0) {
    const blockLessons = Math.min(4, remaining);
    const extra = surcharges
      .filter((s) => s.subscription_index === index)
      .reduce((acc, s) => acc + Number(s.total_amount), 0);
    blocks.push({
      index,
      lessons: blockLessons,
      pricePerLesson: (basePerLesson * blockLessons + extra) / blockLessons,
      surcharged: extra > 0,
    });
    remaining -= blockLessons;
    index += 1;
  }
  return blocks;
}
```

- в строке оплаты добавить раскрытие списка блоков; у каждого блока — цена урока и
  кнопка «Доплата» (открывает `SurchargeModal`), обе только при `canWrite`;
- доплаты (`kind === 'surcharge'`) не показывать отдельными строками верхнего
  уровня — они принадлежат своей оплате: фильтровать их из основного списка и
  выводить под соответствующим блоком.

- [ ] **Step 5: Предупреждение при удалении оплаты с доплатами**

В обработчике удаления оплаты (`handleDelete`) перед подтверждением показать, сколько
доплат уйдёт вместе с ней:

```tsx
  const surchargesOf = (paymentId: number) =>
    (data.payments || []).filter((p) => p.parent_payment_id === paymentId);
```

и в тексте подтверждения второй фазы (`confirming`) добавить сумму: если у оплаты
есть доплаты, кнопка показывает «Точно? (+N доплат)». Это единственное место, где
пользователь узнает, что удаляет чужие деньги.

- [ ] **Step 6: Проверка типов**

Run: `cd frontend/admin-src && npm run typecheck`
Expected: без ошибок

- [ ] **Step 7: Показать изменения**

Run: `git status --short && git diff --stat`

---

## Task 7: Полная верификация

- [ ] **Step 1: Полный backend-прогон**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 0 failed. Гонять целиком, не по частям: часть приложений использует общую
`journal_test`, часть — свежую `test_journal_test`.

- [ ] **Step 2: Проверить, что партии строятся в одном месте**

Run: `grep -rn "price_per_lesson.*/" apps/ --include=*.py | grep -v tests | grep -v "lots.py"`
Expected: пусто. Любое вхождение вне `apps/finances/lots.py` — вернувшееся дублирование.

- [ ] **Step 3: Ручная проверка в браузере**

1. Ученику с оплатой курса раскрыть историю платежей → видны абонементы с ценой урока.
2. Внести доплату 1000 ₽ ко второму абонементу → цена его уроков выросла, остальных нет.
3. Открыть месячный отчёт за месяц доплаты → сумма попала в поступления.
4. Удалить доплату → цена блока вернулась к базовой.
5. Зайти менеджером → кнопок «Доплата» нет, прямой POST даёт 403.

- [ ] **Step 4: Показать итог**

Run: `git status --short && git diff --stat`
Коммит — по явной просьбе пользователя.
