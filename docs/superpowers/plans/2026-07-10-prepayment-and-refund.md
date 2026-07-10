# Предоплата, единая сумма и возврат средств — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать возможность вносить оплату за произвольное число уроков (в т.ч. предоплату 1–3 урока), задавать единую сумму за несколько блоков, оформлять возврат неотработанного остатка и видеть, кто внёс каждую оплату.

**Architecture:** Единица учёта переводится с «абонемента» (`subscriptions_count × 4`) на **урок** (`lessons_count`). `total_amount` — авторитетные деньги, `unit_price` и `subscriptions_count` — производные/презентационные. Возврат — append-only строка `kind='refund'` с отрицательными количествами, входящая в FIFO как синтетическое списание остатка. Всё логируется существующим pghistory (Payment уже трекается и откатывается).

**Tech Stack:** Django 5.2 + DRF, PostgreSQL (managed models поверх существующей схемы), pghistory; admin SPA — React 19 + TanStack Query v5. Тесты — pytest (`journal_test`).

**Спека:** [docs/superpowers/specs/2026-07-10-prepayment-and-refund-design.md](../specs/2026-07-10-prepayment-and-refund-design.md)

**Как гонять тесты:** из `journal_django/` — `pytest apps/<app>/tests/<file>.py::<test> -v` (дефолтный pytest использует `journal_test`, см. память про guard в `config/settings/test.py`). Фронт — из `journal_django/frontend/admin-src/`: `npm run build` для проверки типов.

---

## Итоговый контракт API (после всех фаз)

`POST /api/admin/payments` тело:
```json
{ "student_id": 1, "direction_id": 2, "lessons_count": 4, "total_amount": "4000.00", "paid_at": "2026-07-10", "note": null }
```
- `lessons_count` — кратно 4 (блоки) ИЛИ 1|2|3 (предоплата).
- `total_amount` — авторитетная сумма. Сервер выводит `unit_price = round(total_amount / lessons_count)` и `subscriptions_count = lessons_count // 4` (если делится нацело, иначе NULL).
- `unit_price` в теле НЕ передаётся (устраняем двусмысленность per-block/per-lesson; «единая сумма» из фазы 3 — это UI-способ посчитать `total_amount`).

`POST /api/admin/students/{id}/refund` — тело пустое; сервер считает остаток и создаёт строку возврата. Права: `admin`/`superadmin`.

---

## Карта файлов

**Бэкенд:**
- `apps/payments/models.py` — колонки `lessons_count`, `kind`; новые CHECK.
- `apps/payments/migrations/0005_*` — схема (колонки + констрейнты).
- `apps/payments/migrations/0006_*` — data-миграция (`lessons_count`, `kind`, `created_by`).
- `apps/payments/repository.py` — `create_payment` (cap в уроках, вывод unit_price/subs), новый `refund_student`.
- `apps/payments/services.py` — passthrough `create_payment`, новый `refund_student`.
- `apps/payments/serializers.py` — `PaymentCreateSerializer` на `lessons_count` + `total_amount`.
- `apps/payments/views.py` — `created_by = full_name`.
- `apps/finances/repository.py` — `balances_for_students`, `fifo_inputs` на `lessons_count`; новый `student_fifo_remaining`.
- `apps/finances/fifo.py` — `compute_fifo` учитывает флаг `refund` у consumption.
- `apps/students/views.py` — `StudentRefundView`.
- `apps/students/urls.py` — маршрут `/<pk>/refund`.
- `apps/changelog/labels.py` — правило `payment.refund`.
- `apps/changelog/summary.py` — humanize предоплаты/возврата, подписи полей.

**Фронтенд:**
- `frontend/admin-src/src/lib/types.ts` — тип `Payment` (+`lessons_count`, `kind`, `created_by`).
- `frontend/admin-src/src/hooks/usePayments.ts` — `PaymentCreateInput`, `refund`-мутация.
- `frontend/admin-src/src/pages/payments/PaymentModal.tsx` — предоплата + переключатель суммы.
- `frontend/admin-src/src/pages/payments/BlockSelector.tsx` — без изменений (переиспользуем).
- `frontend/admin-src/src/pages/students/RefundModal.tsx` — новая модалка.
- `frontend/admin-src/src/pages/students/StudentBalanceBlock.tsx` — красная строка возврата, `created_by`, кнопка возврата (RBAC).

---

# ФАЗА 1 — Модель на `lessons_count` (поведение блок-оплат неизменно)

Цель: перевести хранение и финансы на `lessons_count`, не меняя внешнее поведение для обычных блок-оплат. Прогон существующих тестов зелёный.

### Task 1.1: Колонки `lessons_count` и `kind` в модели + схема-миграция

**Files:**
- Modify: `apps/payments/models.py`
- Create: `apps/payments/migrations/0005_add_lessons_count_kind.py`

- [ ] **Step 1: Добавить поля и констрейнты в модель**

В `apps/payments/models.py` в класс `Payment` добавить поля (после `subscriptions_count`):
```python
    lessons_count = models.IntegerField(null=True, blank=True)
    kind = models.TextField(default='purchase')
```
И заменить блок `constraints` целиком на:
```python
        constraints = [
            models.CheckConstraint(
                name='payments_kind_check',
                condition=models.Q(kind__in=['purchase', 'refund']),
            ),
            models.CheckConstraint(
                name='payments_unit_price_check',
                condition=models.Q(unit_price__gte=0),
            ),
            # purchase: положительные количества и сумма; refund: отрицательные.
            models.CheckConstraint(
                name='payments_purchase_signs',
                condition=(
                    ~models.Q(kind='purchase')
                    | (models.Q(lessons_count__gt=0) & models.Q(total_amount__gte=0))
                ),
            ),
            models.CheckConstraint(
                name='payments_refund_signs',
                condition=(
                    ~models.Q(kind='refund')
                    | (models.Q(lessons_count__lt=0) & models.Q(total_amount__lte=0))
                ),
            ),
        ]
```
Убрать старые констрейнты `payments_subscriptions_count_check` и `payments_total_match` (заменены выше). Обновить docstring класса: «Источник правды о количестве — `lessons_count`; `subscriptions_count` — презентационный; `total_amount` авторитетен, `unit_price` информационный».

- [ ] **Step 2: Сгенерировать миграцию**

Run: `python manage.py makemigrations payments --name add_lessons_count_kind`
Expected: создаёт `0005_add_lessons_count_kind.py` с AddField ×2, RemoveConstraint ×2, AddConstraint ×4.

Проверить, что имя файла — `0005_add_lessons_count_kind.py` и `dependencies = [('payments', '0004_backfill_legacy_subscriptions_count')]`. Колонки добавляются nullable — существующие строки не ломаются.

- [ ] **Step 3: Применить миграцию**

Run: `python manage.py migrate payments`
Expected: `Applying payments.0005_add_lessons_count_kind... OK`.

- [ ] **Step 4: Commit**

```bash
git add apps/payments/models.py apps/payments/migrations/0005_add_lessons_count_kind.py
git commit -m "feat(payments): add lessons_count + kind columns, refund-aware constraints"
```

### Task 1.2: Data-миграция — backfill `lessons_count`, `kind`, `created_by`

**Files:**
- Create: `apps/payments/migrations/0006_backfill_lessons_count_and_author.py`

- [ ] **Step 1: Написать data-миграцию**

Создать `apps/payments/migrations/0006_backfill_lessons_count_and_author.py`:
```python
"""
Data-миграция:
  • lessons_count = subscriptions_count * 4 для всех существующих строк
    (subscriptions_count у всех строк проставлен: обычные оплаты + легаси после 0004).
  • kind = 'purchase' для всех существующих строк.
  • created_by = 'Павлов Илья' для ВСЕХ существующих оплат (учётка
    ilyapavlov200311@gmail.com) — по требованию заказчика.

⚠️ Перезаписывает created_by='backfill-script' (маркер отката 0006... т.е. 0004).
0004 уже применена; её обратная миграция при откате должна опираться на
direction_id IS NULL AND subscriptions_count=1, а не на маркер created_by.
Форвард 0006 идёт строго после 0004, поэтому здесь маркер уже не нужен.
"""
from __future__ import annotations

from django.db import migrations
from django.db.models import F


def backfill(apps, schema_editor):
    Payment = apps.get_model('payments', 'Payment')
    # lessons_count из subscriptions_count (× 4); строки без subs не ожидаются,
    # но на всякий случай их не трогаем (останутся NULL → guard в финансах отсечёт).
    Payment.objects.filter(subscriptions_count__isnull=False, lessons_count__isnull=True) \
        .update(lessons_count=F('subscriptions_count') * 4)
    Payment.objects.update(kind='purchase')
    Payment.objects.update(created_by='Павлов Илья')


def noop_reverse(apps, schema_editor):
    # Необратимо: created_by исходных значений не восстанавливаем.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0005_add_lessons_count_kind'),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
```

- [ ] **Step 2: Применить**

Run: `python manage.py migrate payments`
Expected: `Applying payments.0006_backfill_lessons_count_and_author... OK`.

- [ ] **Step 3: Проверить данные вручную**

Run:
```bash
python manage.py shell -c "from apps.payments.models import Payment; print(Payment.objects.exclude(lessons_count=None).count(), Payment.objects.filter(created_by='Павлов Илья').count(), Payment.objects.exclude(kind='purchase').count())"
```
Expected: первое и второе число равны общему числу оплат; третье — `0`.

- [ ] **Step 4: Commit**

```bash
git add apps/payments/migrations/0006_backfill_lessons_count_and_author.py
git commit -m "feat(payments): backfill lessons_count, kind=purchase, author=Павлов Илья"
```

### Task 1.3: `balances_for_students` — сумма по `lessons_count`

**Files:**
- Modify: `apps/finances/repository.py:166-170`
- Test: `apps/finances/tests/test_balance.py`

- [ ] **Step 1: Обновить тест баланса**

В `apps/finances/tests/test_balance.py` найти тест, проверяющий покупку 1 абонемента, и убедиться, что он опирается на количество уроков = 4 (после миграции значение то же). Добавить явный тест на суммирование `lessons_count`:
```python
def test_balance_uses_lessons_count(student_fixture, direction_fixture):
    from django.db import connection
    from apps.finances.repository import balance_for_student
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, "
            "lessons_count, kind, unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s, %s, 1, 4, 'purchase', 1000, 4000, '2026-01-01', 't')",
            [student_fixture, direction_fixture],
        )
    assert balance_for_student(student_fixture) == 4
```

- [ ] **Step 2: Запустить — упадёт (balance считает по subscriptions_count×4)**

Run: `pytest apps/finances/tests/test_balance.py::test_balance_uses_lessons_count -v`
Expected: тест может пройти случайно (4 = 1×4). Чтобы убедиться, что источник — `lessons_count`, во вставке задать `subscriptions_count=99, lessons_count=4` и ожидать `4`. Тогда до правки FAIL (вернёт 396), после — PASS.

- [ ] **Step 3: Заменить формулу**

В `apps/finances/repository.py` в `balances_for_students` заменить:
```python
        .annotate(s=Coalesce(Sum(F('subscriptions_count') * 4, output_field=_DEC), _ZERO))
```
на:
```python
        .annotate(s=Coalesce(Sum('lessons_count', output_field=_DEC), _ZERO))
```
Обновить docstring: «purchased = SUM(lessons_count) (включает отрицательные строки возврата → net)».

- [ ] **Step 4: Запустить — PASS**

Run: `pytest apps/finances/tests/test_balance.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/finances/repository.py apps/finances/tests/test_balance.py
git commit -m "refactor(finances): balance sums lessons_count instead of subscriptions_count*4"
```

### Task 1.4: `fifo_inputs` — партии по `lessons_count`, готовность к refund

**Files:**
- Modify: `apps/finances/repository.py:89-145`
- Test: `apps/finances/tests/test_fifo_inputs.py`

- [ ] **Step 1: Обновить тест входов FIFO**

В `apps/finances/tests/test_fifo_inputs.py` добавить проверку, что размер партии берётся из `lessons_count` (вставить оплату с `subscriptions_count=99, lessons_count=4, total_amount=4000` и ожидать `lots_by_key[str(sid)][0]['lessons'] == 4` и `price_per_lesson == Decimal('1000')`).

- [ ] **Step 2: Запустить — FAIL**

Run: `pytest apps/finances/tests/test_fifo_inputs.py -v`
Expected: FAIL (сейчас lessons = subscriptions_count×4 = 396).

- [ ] **Step 3: Переписать чтение партий**

В `apps/finances/repository.py::fifo_inputs` заменить чтение `lots_rows` и цикл на:
```python
    lots_rows = (
        Payment.objects
        .order_by('student_id', 'paid_at', 'id')
        .values('student_id', 'total_amount', 'lessons_count', 'kind', 'paid_at')
    )
    ...
    lots_by_key: dict[str, list] = {}
    purchased_by_key: dict[str, int] = {}
    refund_cons: dict[str, list] = {}   # синтетические списания-возвраты
    for r in lots_rows:
        key = str(r['student_id'])
        lessons = int(r['lessons_count']) if r['lessons_count'] is not None else 0
        if r['kind'] == 'refund':
            # возврат: гасит остаток на дату возврата (units = |lessons|), без выручки
            refund_cons.setdefault(key, []).append({
                'units': to_decimal(-lessons),
                'date': _date_str(r['paid_at']),
                'direction_id': None,
                'refund': True,
            })
            continue
        if not (lessons > 0):  # guard: NULL/0
            continue
        lots_by_key.setdefault(key, []).append({
            'lessons': lessons,
            'price_per_lesson': to_decimal(r['total_amount']) / Decimal(lessons),
        })
        purchased_by_key[key] = purchased_by_key.get(key, 0) + lessons
```
После построения `cons_by_key` из посещений — влить в него возвраты и пересортировать по дате (возврат позже посещений того же дня):
```python
    for key, refs in refund_cons.items():
        cons_by_key.setdefault(key, []).extend(refs)
    for key, lst in cons_by_key.items():
        lst.sort(key=lambda c: (c['date'], 1 if c.get('refund') else 0))
```
Убедиться, что consumption-записи посещений получают `'refund': False` по умолчанию — в `compute_fifo` читаем через `c.get('refund')`, так что явно проставлять не нужно.

- [ ] **Step 4: Запустить — PASS**

Run: `pytest apps/finances/tests/test_fifo_inputs.py apps/finances/tests/test_fifo.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/finances/repository.py apps/finances/tests/test_fifo_inputs.py
git commit -m "refactor(finances): fifo lots from lessons_count; refunds as synthetic consumptions"
```

### Task 1.5: `compute_fifo` — не начислять выручку на возврат

**Files:**
- Modify: `apps/finances/fifo.py:56-80`
- Test: `apps/finances/tests/test_fifo.py`

- [ ] **Step 1: Тест: refund гасит остаток без выручки**

В `apps/finances/tests/test_fifo.py` добавить:
```python
def test_refund_consumption_zeroes_remaining_without_revenue():
    from decimal import Decimal
    from apps.finances.fifo import compute_fifo
    lots = [{'lessons': 4, 'price_per_lesson': Decimal('1000')}]
    cons = [
        {'units': Decimal('1'), 'date': '2026-01-05', 'direction_id': None},
        {'units': Decimal('3'), 'date': '2026-01-31', 'direction_id': None, 'refund': True},
    ]
    r = compute_fifo(lots, cons, '2026-01-01', '2026-02-01')
    assert r['remaining_value'] == Decimal('0.00')      # хвост погашен возвратом
    assert r['worked_off_total'] == Decimal('1000.00')  # только 1 реальный урок
```

- [ ] **Step 2: Запустить — FAIL**

Run: `pytest apps/finances/tests/test_fifo.py::test_refund_consumption_zeroes_remaining_without_revenue -v`
Expected: FAIL (`worked_off_total` == 4000, refund посчитан как выручка).

- [ ] **Step 3: Учесть флаг refund в цикле**

В `apps/finances/fifo.py::compute_fifo` внутри `for c in consumptions:` добавить чтение флага и не накапливать выручку для возврата. Заменить тело обработки одной итерации так:
```python
    for c in consumptions:
        need = to_decimal(c['units'])
        in_month = month_start <= c['date'] < month_end
        direction_id = c.get('direction_id')
        is_refund = bool(c.get('refund'))
        while need > 0 and lot_idx < len(lots):
            if lot_remaining <= 0:
                lot_idx += 1
                if lot_idx >= len(lots):
                    break
                lot_remaining = to_decimal(lots[lot_idx]['lessons'])
                continue
            take = need if need < lot_remaining else lot_remaining
            value = take * to_decimal(lots[lot_idx]['price_per_lesson'])
            if not is_refund:
                worked_off_total += value
                ym = c['date'][:7]
                by_month[ym] = by_month.get(ym, _ZERO) + value
                if direction_id is not None:
                    by_direction[direction_id] = by_direction.get(direction_id, _ZERO) + value
                if in_month:
                    worked_off_month += value
            lot_remaining -= take
            need -= take
        if need > 0 and not is_refund:
            over_consumed_lessons += need
```
Обновить docstring: «consumption может нести `refund: True` — гасит партии (для remaining_value), но не идёт в worked_off/over_consumed».

- [ ] **Step 4: Запустить — PASS**

Run: `pytest apps/finances/tests/test_fifo.py -v`
Expected: PASS (все прежние + новый).

- [ ] **Step 5: Commit**

```bash
git add apps/finances/fifo.py apps/finances/tests/test_fifo.py
git commit -m "feat(finances): compute_fifo skips revenue for refund consumptions"
```

### Task 1.6: `create_payment` — контракт `lessons_count`+`total_amount`, cap в уроках

**Files:**
- Modify: `apps/payments/repository.py:43-104`
- Modify: `apps/payments/serializers.py`
- Test: `apps/payments/tests/test_payments_repository.py`

- [ ] **Step 1: Обновить сериализатор**

Заменить `apps/payments/serializers.py` тело `PaymentCreateSerializer` на:
```python
class PaymentCreateSerializer(serializers.Serializer):
    student_id = serializers.IntegerField(min_value=1)
    direction_id = serializers.IntegerField(min_value=1)
    lessons_count = serializers.IntegerField(min_value=1)
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'))
    paid_at = DateStringField()
    note = serializers.CharField(max_length=500, allow_null=True, required=False, default=None)

    def validate_lessons_count(self, value):
        # Фаза 1: только целые блоки (кратно 4). Фаза 2 разрешит 1|2|3.
        if value % 4 != 0:
            raise serializers.ValidationError('lessons_count должен быть кратен 4')
        return value
```

- [ ] **Step 2: Тест репозитория на новый контракт**

В `apps/payments/tests/test_payments_repository.py` обновить вызов `create_payment` на новый вход и проверки:
```python
def test_create_payment_derives_unit_and_subs(student_fixture, direction_fixture):
    from decimal import Decimal
    from apps.payments.repository import create_payment
    res = create_payment({
        'student_id': student_fixture, 'direction_id': direction_fixture,
        'lessons_count': 4, 'total_amount': Decimal('4000.00'),
        'paid_at': '2026-01-01', 'created_by': 'Тест Тестов',
    })
    p = res['payment']
    assert p['lessons_count'] == 4
    assert p['kind'] == 'purchase'
    assert p['subscriptions_count'] == 1
    assert str(p['unit_price']) == '1000.00'
    assert str(p['total_amount']) == '4000.00'
    assert p['created_by'] == 'Тест Тестов'
```

- [ ] **Step 3: Запустить — FAIL**

Run: `pytest apps/payments/tests/test_payments_repository.py::test_create_payment_derives_unit_and_subs -v`
Expected: FAIL (create_payment ждёт subscriptions_count/unit_price).

- [ ] **Step 4: Переписать `create_payment`**

В `apps/payments/repository.py::create_payment` заменить извлечение полей и тело на:
```python
    student_id = data['student_id']
    direction_id = data['direction_id']
    lessons_count = data['lessons_count']
    total_amount = data['total_amount']
    paid_at = data['paid_at']
    note = data.get('note')
    created_by = data.get('created_by')

    with transaction.atomic():
        dir_row = (
            Direction.objects.select_for_update()
            .filter(id=direction_id)
            .values('id', 'total_lessons')
            .first()
        )
        if dir_row is None:
            return {'error': 'direction_not_found'}
        if not dir_row['total_lessons'] or dir_row['total_lessons'] <= 0:
            return {'error': 'no_capacity'}

        # cap в уроках: считаем только покупки этого направления
        already = (
            Payment.objects
            .filter(student_id=student_id, direction_id=direction_id, kind='purchase')
            .aggregate(s=Coalesce(Sum('lessons_count'), Value(0)))['s']
        )
        if already + lessons_count > dir_row['total_lessons']:
            return {
                'error': 'cap_exceeded',
                'already': already,
                'cap_subscriptions': int(dir_row['total_lessons'] // 4),
            }

        total = round_kopecks(total_amount)
        unit_price = round_kopecks(total / Decimal(lessons_count))
        subs = lessons_count // 4 if lessons_count % 4 == 0 else None

        obj = Payment.objects.create(
            student_id=student_id,
            direction_id=direction_id,
            subscriptions_count=subs,
            lessons_count=lessons_count,
            kind='purchase',
            unit_price=unit_price,
            total_amount=total,
            paid_at=paid_at,
            note=note or None,
            created_by=created_by or None,
            created_at=Now(),
        )
        row = dictrow(Payment.objects.filter(pk=obj.pk).values())

    return {'payment': row}
```
Добавить импорт `Decimal` вверху файла: `from decimal import Decimal`. Добавить `_PAYMENT_FIELDS` поля `'lessons_count', 'kind'` (в порядке после `subscriptions_count`).

- [ ] **Step 5: Запустить — PASS**

Run: `pytest apps/payments/tests/test_payments_repository.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/payments/repository.py apps/payments/serializers.py apps/payments/tests/test_payments_repository.py
git commit -m "feat(payments): create_payment on lessons_count+total_amount, cap in lessons"
```

### Task 1.7: View — `created_by` = ФИО пользователя

**Files:**
- Modify: `apps/payments/views.py:58`
- Test: `apps/payments/tests/test_payments_api.py`

- [ ] **Step 1: Тест API на автора и новый контракт**

В `apps/payments/tests/test_payments_api.py` обновить POST-кейсы на `{lessons_count, total_amount}` и добавить проверку `created_by`:
```python
def test_create_payment_stores_author_full_name(admin_client, student_fixture, direction_fixture):
    resp = admin_client.post('/api/admin/payments', {
        'student_id': student_fixture, 'direction_id': direction_fixture,
        'lessons_count': 4, 'total_amount': '4000.00', 'paid_at': '2026-01-01',
    }, content_type='application/json')
    assert resp.status_code == 201
    assert resp.json()['created_by']  # непустое имя, не 'acct:...'
    assert not resp.json()['created_by'].startswith('acct:')
```
(Если у фикстуры `admin_client` аккаунт без `full_name`, задать его в фикстуре или ожидать email — см. существующий admin-фикстур в корневом conftest.)

- [ ] **Step 2: Запустить — FAIL**

Run: `pytest apps/payments/tests/test_payments_api.py::test_create_payment_stores_author_full_name -v`
Expected: FAIL (`created_by` начинается с `acct:`).

- [ ] **Step 3: Писать ФИО автора**

В `apps/payments/views.py` в `post` заменить строку 58:
```python
        data['created_by'] = f'acct:{request.user.id}' if request.user else None
```
на:
```python
        user = request.user
        data['created_by'] = (getattr(user, 'full_name', None) or getattr(user, 'email', None)) if user else None
```

- [ ] **Step 4: Запустить — PASS**

Run: `pytest apps/payments/tests/test_payments_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/payments/views.py apps/payments/tests/test_payments_api.py
git commit -m "feat(payments): store author full name in created_by"
```

### Task 1.8: Починить существующие фикстуры и тесты под новые колонки

**Files:**
- Modify: `apps/payments/tests/conftest.py:201-215`
- Modify: `apps/payments/tests/test_payments_constraints.py`
- Modify: `apps/finances/tests/conftest.py` (если есть прямые INSERT payments)
- Modify: `apps/changelog/tests/*` (если вставляют payments)

- [ ] **Step 1: Обновить `payment_fixture`**

В `apps/payments/tests/conftest.py` в `payment_fixture` заменить INSERT на явные `lessons_count`, `kind`:
```python
            INSERT INTO payments
               (student_id, direction_id, subscriptions_count, lessons_count, kind,
                unit_price, total_amount, paid_at, created_by)
            VALUES (%s, %s, 1, 4, 'purchase', 1000.00, 4000.00, '2026-01-01', 'test')
```

- [ ] **Step 2: Прогнать весь payments+finances+changelog**

Run: `pytest apps/payments apps/finances apps/changelog -v`
Expected: часть тестов может падать из-за прямых INSERT без `lessons_count`/`kind` или из-за снятого CHECK `payments_total_match`. Пройтись по падениям, в каждом прямом INSERT добавить `lessons_count`/`kind`, в тестах на старый CHECK `payments_total_match` — заменить на новые констрейнты (`payments_purchase_signs`).

- [ ] **Step 3: Обновить `test_payments_constraints.py`**

Тесты, проверявшие `payments_total_match` (total = unit×subs), заменить на проверку новых знаковых констрейнтов: покупка с `lessons_count <= 0` → IntegrityError; refund с `lessons_count >= 0` → IntegrityError; `kind='bogus'` → IntegrityError. Пример:
```python
def test_purchase_requires_positive_lessons(...):
    with pytest.raises(IntegrityError):
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, "
            "lessons_count, kind, unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s, %s, NULL, 0, 'purchase', 100, 100, '2026-01-01', 't')",
            [student_id, direction_id])
```

- [ ] **Step 4: Полный прогон**

Run: `pytest apps/payments apps/finances apps/changelog apps/students apps/renewals -v`
Expected: PASS (все зелёные).

- [ ] **Step 5: Commit**

```bash
git add apps/payments/tests apps/finances/tests apps/changelog/tests
git commit -m "test(payments): fixtures and constraint tests for lessons_count/kind"
```

### Task 1.9: Changelog humanize — подписи новых полей

**Files:**
- Modify: `apps/changelog/summary.py:181-217` (FIELD_RU), `:294-302` (payment describe), `:388-394` (build_summary payments)
- Test: `apps/changelog/tests/test_summary.py`

- [ ] **Step 1: Тест humanize оплаты по lessons_count**

В `apps/changelog/tests/test_summary.py` добавить проверку, что описание оплаты содержит сумму (как раньше) и не падает при `lessons_count`/`kind` в data. Достаточно расширить существующий payment-тест новыми полями в `pgh_data`.

- [ ] **Step 2: Добавить подписи полей**

В `apps/changelog/summary.py` в `FIELD_RU` добавить:
```python
    'lessons_count': 'кол-во уроков', 'kind': 'тип операции',
```

- [ ] **Step 3: Учесть refund/предоплату в describe_event**

В `describe_event`, ветка `if entity == 'payment':` заменить на:
```python
    if entity == 'payment':
        student = lk.student(data.get('student_id'))
        amount = _fmt_num(data.get('total_amount'))
        is_refund = data.get('kind') == 'refund'
        if label == 'delete':
            return (f'Отменён возврат {amount} ₽: {student}' if is_refund
                    else f'Удалена оплата {amount} ₽: {student}')
        if label == 'insert':
            if is_refund:
                lc = _fmt_num(abs(int(data.get('lessons_count') or 0)))
                return f'Возврат {amount} ₽ ({lc} уроков): {student}'
            lc = data.get('lessons_count')
            tag = '' if (lc is None or int(lc) % 4 == 0) else f' (предоплата, {_fmt_num(lc)} уроков)'
            return f'Оплата {amount} ₽{tag}: {student}'
        return f'Оплата {student}: изменено — {_fields_ru(diff.keys())}'
```
Аналогично в `build_summary`, ветка `payments:` — использовать `kind` для выбора глагола:
```python
    payments = by_entity.get('payment', [])
    if payments:
        data = payments[0].get('pgh_data') or {}
        student = lk.student(data.get('student_id'))
        amount = data.get('total_amount')
        is_refund = data.get('kind') == 'refund'
        if payments[0]['pgh_label'] == 'delete':
            verb = 'Отменён возврат' if is_refund else 'Удалена оплата'
        else:
            verb = 'Возврат' if is_refund else 'Оплата'
        return f'{verb} {amount} ₽: {student}'
```

- [ ] **Step 4: Запустить**

Run: `pytest apps/changelog/tests/test_summary.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/changelog/summary.py apps/changelog/tests/test_summary.py
git commit -m "feat(changelog): humanize refund/prepayment payments; field labels"
```

### Task 1.10: Фронт — контракт `lessons_count`+`total_amount` (блоки как есть)

**Files:**
- Modify: `frontend/admin-src/src/lib/types.ts` (тип `Payment`)
- Modify: `frontend/admin-src/src/hooks/usePayments.ts:14-21,56-59`
- Modify: `frontend/admin-src/src/pages/payments/PaymentModal.tsx:188-201`

- [ ] **Step 1: Расширить тип `Payment`**

В `frontend/admin-src/src/lib/types.ts` в интерфейс `Payment` добавить поля:
```typescript
  lessons_count: number | null;
  kind: 'purchase' | 'refund';
  created_by: string | null;
```

- [ ] **Step 2: Обновить `PaymentCreateInput`**

В `frontend/admin-src/src/hooks/usePayments.ts` заменить `PaymentCreateInput`:
```typescript
export interface PaymentCreateInput {
  student_id: number;
  direction_id: number;
  lessons_count: number;
  total_amount: number;
  paid_at: string;
  note?: string | null;
}
```

- [ ] **Step 3: Обновить submit в модалке**

В `frontend/admin-src/src/pages/payments/PaymentModal.tsx::handleSubmit` заменить тело `muts.create.mutateAsync({...})` на:
```typescript
      await muts.create.mutateAsync({
        student_id: stId!,
        direction_id: dirId!,
        lessons_count: count * 4,
        total_amount: total,   // computedUnitPrice * count
        paid_at: paidAt,
        note: finalNote || null,
      });
```
(`total` уже = `computedUnitPrice * count`; `count` — число блоков.)

- [ ] **Step 4: Проверить сборку**

Run (из `frontend/admin-src/`): `npm run build`
Expected: успешная сборка типов, ошибок нет.

- [ ] **Step 5: Commit**

```bash
git add frontend/admin-src/src/lib/types.ts frontend/admin-src/src/hooks/usePayments.ts frontend/admin-src/src/pages/payments/PaymentModal.tsx
git commit -m "feat(admin): payment create sends lessons_count+total_amount"
```

**Чекпоинт фазы 1:** полный прогон `pytest` (backend) зелёный; `npm run build` (front) зелёный; блок-оплаты работают как раньше. Прогнать вручную: внести оплату 1 блок и 2 блока, проверить баланс и историю.

---

# ФАЗА 2 — Предоплата 1–3 урока

### Task 2.1: Сервер — разрешить `lessons_count ∈ {1,2,3}`

**Files:**
- Modify: `apps/payments/serializers.py` (`validate_lessons_count`)
- Test: `apps/payments/tests/test_payments_api.py`

- [ ] **Step 1: Тест предоплаты**

```python
def test_prepayment_two_lessons(admin_client, student_fixture, direction_fixture):
    resp = admin_client.post('/api/admin/payments', {
        'student_id': student_fixture, 'direction_id': direction_fixture,
        'lessons_count': 2, 'total_amount': '2000.00', 'paid_at': '2026-01-01',
    }, content_type='application/json')
    assert resp.status_code == 201
    body = resp.json()
    assert body['lessons_count'] == 2
    assert body['subscriptions_count'] is None
    assert str(body['unit_price']) == '1000.00'

def test_reject_five_lessons(admin_client, student_fixture, direction_fixture):
    resp = admin_client.post('/api/admin/payments', {
        'student_id': student_fixture, 'direction_id': direction_fixture,
        'lessons_count': 5, 'total_amount': '5000.00', 'paid_at': '2026-01-01',
    }, content_type='application/json')
    assert resp.status_code == 400
```

- [ ] **Step 2: Запустить — FAIL**

Run: `pytest apps/payments/tests/test_payments_api.py::test_prepayment_two_lessons -v`
Expected: FAIL (валидатор фазы 1 требует кратности 4).

- [ ] **Step 3: Ослабить валидатор**

В `apps/payments/serializers.py` заменить `validate_lessons_count`:
```python
    def validate_lessons_count(self, value):
        # Одна оплата: либо целые блоки (кратно 4), либо предоплата 1|2|3.
        if value % 4 == 0 or value in (1, 2, 3):
            return value
        raise serializers.ValidationError('lessons_count: кратно 4 (блоки) или 1–3 (предоплата)')
```

- [ ] **Step 4: Запустить — PASS**

Run: `pytest apps/payments/tests/test_payments_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/payments/serializers.py apps/payments/tests/test_payments_api.py
git commit -m "feat(payments): allow prepayment of 1-3 lessons"
```

### Task 2.2: Фронт — режим «Предоплата (1–3 урока)» в модалке

**Files:**
- Modify: `frontend/admin-src/src/pages/payments/PaymentModal.tsx`

- [ ] **Step 1: Состояние режима количества**

В `PaymentModal` добавить состояние:
```typescript
  const [mode, setMode] = useState<'blocks' | 'prepay'>('blocks');
  const [prepayLessons, setPrepayLessons] = useState(0);   // 1..3
```
Сбросить оба в `useEffect` при открытии (`setMode('blocks'); setPrepayLessons(0);`).

- [ ] **Step 2: Единое число уроков и цена**

Ввести производные:
```typescript
  const perLesson = basePrice != null ? Math.round((basePrice / 4) * 100) / 100 : null;
  const lessonsCount = mode === 'blocks' ? count * 4 : prepayLessons;
  // total: блоки — computedUnitPrice*count; предоплата — perLesson*prepayLessons (по умолч.)
  const prepayTotal = perLesson != null ? Math.round(perLesson * prepayLessons * 100) / 100 : 0;
```
В существующий `total` внести режим: `const total = mode === 'blocks' ? computedUnitPrice * count : prepayTotal;`

- [ ] **Step 3: UI переключателя и селектора предоплаты**

В `renderBlocksArea()` над `<BlockSelector>` добавить переключатель режима (кнопки-сегменты из существующих классов) и, при `mode==='prepay'`, три кнопки 1/2/3 урока вместо блок-селектора. Пример вставки после хинта «Уже куплено»:
```tsx
        <div className="payment-form__segment">
          <button type="button" className={`seg${mode==='blocks'?' seg--on':''}`}
            onClick={() => { setMode('blocks'); clearError('count'); }}>Блоки по 4</button>
          <button type="button" className={`seg${mode==='prepay'?' seg--on':''}`}
            onClick={() => { setMode('prepay'); setCount(0); setDiscountIds([]); clearError('count'); }}>Предоплата 1–3</button>
        </div>
        {mode === 'prepay' ? (
          <Field label="Уроков в предоплату" error={errors.count}>
            <div className="prepay-picker">
              {[1,2,3].map((n) => (
                <button key={n} type="button"
                  className={`prepay-cell${prepayLessons===n?' is-on':''}`}
                  onClick={() => { setPrepayLessons(n); clearError('count'); }}>{n}</button>
              ))}
            </div>
          </Field>
        ) : (
          <Field label="Блоки (4 урока в блоке)" error={errors.count}>
            <BlockSelector .../>  {/* существующий */}
          </Field>
        )}
```

- [ ] **Step 4: Валидация и submit**

В `validate()` учесть режим: при `mode==='prepay'` требовать `prepayLessons ∈ {1,2,3}` (иначе `errors.count = FILL_FIELD`), cap-проверку для предоплаты — `alreadyPurchasedLessons + prepayLessons ≤ direction.total_lessons` (добавить `alreadyPurchasedLessons = alreadyPurchased*4` производную из существующих оплат — или суммировать `p.lessons_count`). В `handleSubmit` отправлять `lessons_count: lessonsCount, total_amount: total`. Скидки скрывать при `mode==='prepay'` (условие `discountsApplicable = mode==='blocks' && count === 1`).

- [ ] **Step 5: Сборка + ручная проверка**

Run: `npm run build`
Expected: PASS. Вручную: внести предоплату 2 урока, проверить баланс +2 и запись в истории.

- [ ] **Step 6: Commit**

```bash
git add frontend/admin-src/src/pages/payments/PaymentModal.tsx
git commit -m "feat(admin): prepayment 1-3 lessons mode in payment modal"
```

---

# ФАЗА 3 — Единая сумма за несколько блоков (frontend-only)

Бэкенд уже принимает `total_amount` как авторитетную сумму — серверных правок не требуется.

### Task 3.1: Переключатель «Цена за абонемент / Единой суммой»

**Files:**
- Modify: `frontend/admin-src/src/pages/payments/PaymentModal.tsx`

- [ ] **Step 1: Состояние способа цены**

```typescript
  const [priceMode, setPriceMode] = useState<'per_block' | 'total'>('per_block');
  const [totalInput, setTotalInput] = useState<number | ''>('');
```
Сбросить в `useEffect` открытия. Показывать переключатель только при `mode==='blocks' && count >= 2` (для одного блока незачем; для предоплаты сумма задаётся вручную отдельно).

- [ ] **Step 2: Пересчёт total и производной цены за блок**

```typescript
  const total = mode === 'prepay'
    ? prepayTotal
    : priceMode === 'total'
      ? (typeof totalInput === 'number' ? totalInput : 0)
      : computedUnitPrice * count;
  const derivedPerBlock = (priceMode === 'total' && count > 0 && typeof totalInput === 'number')
    ? Math.round((totalInput / count) * 100) / 100
    : null;
```

- [ ] **Step 3: UI поля единой суммы**

В блоке цены (Field «Цена за абонемент») при `priceMode==='total'` показывать `NumberInput` для общей суммы и подпись «≈ {derivedPerBlock} ₽/абонемент». Переключатель — две кнопки-сегмента. При `count < 2` принудительно `priceMode='per_block'`.

- [ ] **Step 4: Валидация**

В `validate()`: при `priceMode==='total'` требовать `totalInput` > 0. `handleSubmit` уже шлёт `total_amount: total` — ничего менять не нужно.

- [ ] **Step 5: Сборка + ручная проверка**

Run: `npm run build`
Expected: PASS. Вручную: 3 блока, «Единой суммой» = 1000 ₽ → в истории `total_amount=1000.00`, показывается «≈ 333.33 ₽/абонемент».

- [ ] **Step 6: Commit**

```bash
git add frontend/admin-src/src/pages/payments/PaymentModal.tsx
git commit -m "feat(admin): single total-sum entry for multi-block payments"
```

---

# ФАЗА 4 — Возврат средств

### Task 4.1: `student_fifo_remaining` — остаток уроков и денег

**Files:**
- Modify: `apps/finances/repository.py` (новая функция)
- Test: `apps/finances/tests/test_balance.py` или новый `test_refund.py`

- [ ] **Step 1: Тест остатка**

Создать `apps/finances/tests/test_refund_remaining.py`:
```python
import pytest
from decimal import Decimal
from django.db import connection
from apps.finances.repository import student_fifo_remaining

pytestmark = pytest.mark.django_db

def test_remaining_after_one_lesson(student_fixture, direction_fixture,
                                    group_fixture, lesson_60_fixture, attendance_60_fixture):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, "
            "lessons_count, kind, unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s, %s, 1, 4, 'purchase', 1000, 4000, '2026-01-01', 't')",
            [student_fixture, direction_fixture])
    r = student_fifo_remaining(student_fixture)
    assert r['remaining_lessons'] == 3
    assert r['remaining_value'] == Decimal('3000.00')
```
(Использовать фикстуры из `apps/payments/tests/conftest.py` — при необходимости продублировать нужные в `apps/finances/tests/conftest.py`.)

- [ ] **Step 2: Запустить — FAIL**

Run: `pytest apps/finances/tests/test_refund_remaining.py -v`
Expected: FAIL (функции нет).

- [ ] **Step 3: Реализовать функцию**

В `apps/finances/repository.py` добавить:
```python
def student_fifo_remaining(student_id: int) -> dict:
    """
    Неотработанный остаток ученика: сколько уроков и денег ещё не списано.
    remaining_lessons = баланс (purchased − attended, half-lesson учтён).
    remaining_value   = FIFO remaining_value по партиям-оплатам ученика.
    """
    from apps.finances.fifo import compute_fifo

    remaining_lessons = balance_for_student(student_id)

    lots_rows = (
        Payment.objects.filter(student_id=student_id, kind='purchase')
        .order_by('paid_at', 'id')
        .values('total_amount', 'lessons_count')
    )
    lots = []
    for r in lots_rows:
        lessons = int(r['lessons_count']) if r['lessons_count'] is not None else 0
        if lessons > 0:
            lots.append({
                'lessons': lessons,
                'price_per_lesson': to_decimal(r['total_amount']) / Decimal(lessons),
            })

    cons_rows = (
        LessonAttendance.objects.filter(student_id=student_id, present=True)
        .annotate(units=_attended_units_case())
        .order_by('lesson__lesson_date', 'lesson_id')
        .values('units', lesson_date=F('lesson__lesson_date'))
    )
    cons = [{'units': to_decimal(r['units']), 'date': _date_str(r['lesson_date']),
             'direction_id': None} for r in cons_rows]

    fifo = compute_fifo(lots, cons, '0001-01-01', '9999-12-31')
    return {
        'remaining_lessons': remaining_lessons,
        'remaining_value': fifo['remaining_value'],
    }
```
Добавить `from decimal import Decimal` если ещё не импортирован (уже есть).

- [ ] **Step 4: Запустить — PASS**

Run: `pytest apps/finances/tests/test_refund_remaining.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/finances/repository.py apps/finances/tests/test_refund_remaining.py apps/finances/tests/conftest.py
git commit -m "feat(finances): student_fifo_remaining (unworked lessons + money)"
```

### Task 4.2: `refund_student` в репозитории оплат

**Files:**
- Modify: `apps/payments/repository.py`
- Test: `apps/payments/tests/test_payments_repository.py`

- [ ] **Step 1: Тест возврата**

```python
def test_refund_zeroes_balance(student_fixture, direction_fixture,
                               lesson_60_fixture, attendance_60_fixture):
    from decimal import Decimal
    from django.db import connection
    from apps.payments.repository import refund_student
    from apps.finances.repository import balance_for_student, student_fifo_remaining
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, "
            "lessons_count, kind, unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s, %s, 1, 4, 'purchase', 1000, 4000, '2026-01-01', 't')",
            [student_fixture, direction_fixture])
    res = refund_student(student_fixture, created_by='Админ')
    assert res['refunded_amount'] == Decimal('3000.00')
    assert res['new_balance'] == 0
    assert res['refund']['kind'] == 'refund'
    assert res['refund']['lessons_count'] == -3
    assert balance_for_student(student_fixture) == 0
    assert student_fifo_remaining(student_fixture)['remaining_value'] == Decimal('0.00')

def test_refund_nothing_to_refund(student_fixture):
    from apps.payments.repository import refund_student
    assert refund_student(student_fixture, created_by='Админ') == {'error': 'nothing_to_refund'}
```

- [ ] **Step 2: Запустить — FAIL**

Run: `pytest apps/payments/tests/test_payments_repository.py::test_refund_zeroes_balance -v`
Expected: FAIL (функции нет).

- [ ] **Step 3: Реализовать `refund_student`**

В `apps/payments/repository.py` добавить:
```python
def refund_student(student_id: int, created_by: str | None = None) -> dict:
    """
    Оформляет возврат неотработанного остатка ученика (единый пул).

    Возвращает {'error': 'nothing_to_refund'} если остатка нет, иначе
    {'refund': row, 'new_balance': 0, 'refunded_amount': Decimal}.
    Строка возврата: kind='refund', lessons_count/total_amount отрицательные.
    """
    from apps.finances.repository import student_fifo_remaining
    from apps.students.models import Student

    with transaction.atomic():
        # лочим ученика от гонок параллельных списаний/оплат
        if not Student.objects.select_for_update().filter(id=student_id).exists():
            return {'error': 'student_not_found'}

        rem = student_fifo_remaining(student_id)
        remaining_lessons = rem['remaining_lessons']
        remaining_value = rem['remaining_value']
        if remaining_lessons <= 0 or remaining_value <= 0:
            return {'error': 'nothing_to_refund'}

        obj = Payment.objects.create(
            student_id=student_id,
            direction_id=None,
            subscriptions_count=None,
            lessons_count=-remaining_lessons,
            kind='refund',
            unit_price=Decimal('0'),
            total_amount=-remaining_value,
            paid_at=Now(),
            note=f'Возврат {remaining_lessons} уроков на сумму {remaining_value} ₽',
            created_by=created_by or None,
            created_at=Now(),
        )
        row = dictrow(Payment.objects.filter(pk=obj.pk).values())

    return {'refund': row, 'new_balance': 0, 'refunded_amount': remaining_value}
```
Примечание: `paid_at=Now()` пишет дату сервера; DATE-колонка усечёт до дня. `lessons_count=-remaining_lessons` — remaining_lessons может быть дробным (half-lesson), но колонка `IntegerField`; в этом проекте баланс в уроках почти всегда целый, но при 0.5 нужно хранить дробь. **Если half-lesson остатки реальны** — на этапе ревью заменить `lessons_count` на хранение через доп. логику; по умолчанию считаем остаток целым (уточнить с заказчиком; в спеке допускается дробный — тогда потребуется Decimal-колонка, вынести в отдельную мини-задачу). Для остатка `x.5` временно: округлять вниз нельзя (потеряем деньги) — поэтому в guard при дробном остатке возвращать ошибку `fractional_remaining` и логировать. Добавить:
```python
        if remaining_lessons != int(remaining_lessons):
            return {'error': 'fractional_remaining', 'remaining_lessons': remaining_lessons}
```
(деньги `total_amount` всё равно точные; ограничение только на целочисленность `lessons_count`).

- [ ] **Step 4: Тест дробного остатка**

Добавить тест: посещение урока 45 мин (half) → остаток 3.5 → `refund_student` вернёт `{'error': 'fractional_remaining', ...}`. Это осознанное ограничение MVP (задокументировано).

- [ ] **Step 5: Запустить — PASS**

Run: `pytest apps/payments/tests/test_payments_repository.py -k refund -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/payments/repository.py apps/payments/tests/test_payments_repository.py
git commit -m "feat(payments): refund_student zeroes unworked remainder"
```

### Task 4.3: Сервис + endpoint возврата (RBAC admin/superadmin)

**Files:**
- Modify: `apps/payments/services.py`
- Modify: `apps/students/views.py`
- Modify: `apps/students/urls.py`
- Test: `apps/payments/tests/test_payments_api.py` (или `apps/students/tests/`)

- [ ] **Step 1: Сервис-обёртка**

В `apps/payments/services.py` добавить:
```python
def refund_student(student_id: int, created_by: Optional[str] = None) -> dict:
    return repository.refund_student(student_id, created_by=created_by)
```

- [ ] **Step 2: Тест API возврата (RBAC + успех + guard)**

```python
def test_refund_endpoint_admin(admin_client, student_fixture, direction_fixture):
    admin_client.post('/api/admin/payments', {
        'student_id': student_fixture, 'direction_id': direction_fixture,
        'lessons_count': 4, 'total_amount': '4000.00', 'paid_at': '2026-01-01',
    }, content_type='application/json')
    resp = admin_client.post(f'/api/admin/students/{student_fixture}/refund',
                             {}, content_type='application/json')
    assert resp.status_code == 201
    assert resp.json()['refunded_amount'] in ('4000.00', 4000.0, '4000')
    assert resp.json()['new_balance'] == 0

def test_refund_endpoint_forbidden_for_manager(manager_client, student_fixture):
    resp = manager_client.post(f'/api/admin/students/{student_fixture}/refund',
                               {}, content_type='application/json')
    assert resp.status_code == 403

def test_refund_endpoint_empty(admin_client, student_fixture):
    resp = admin_client.post(f'/api/admin/students/{student_fixture}/refund',
                             {}, content_type='application/json')
    assert resp.status_code == 400
    assert resp.json()['error'] == 'nothing_to_refund'
```
(Фикстуры `admin_client`/`manager_client` — из корневого conftest; если `manager_client` отсутствует, использовать существующую фикстуру роли manager или создать по образцу admin.)

- [ ] **Step 3: Запустить — FAIL**

Run: `pytest apps/payments/tests/test_payments_api.py -k refund -v`
Expected: FAIL (маршрута нет → 404).

- [ ] **Step 4: View + маршрут**

В `apps/students/views.py` добавить (импорты `IsAdminOrSuperAdmin` из `apps.core.permissions`, `services` из `apps.payments`):
```python
class StudentRefundView(APIView):
    """POST /api/admin/students/{id}/refund — возврат неотработанного остатка."""

    permission_classes = [IsAdminOrSuperAdmin]

    def post(self, request: Request, pk: int) -> Response:
        user = request.user
        author = (getattr(user, 'full_name', None) or getattr(user, 'email', None)) if user else None
        result = payment_services.refund_student(pk, created_by=author)
        if result.get('error') == 'student_not_found':
            raise NotFound({'error': 'Not found'})
        if result.get('error') == 'nothing_to_refund':
            return Response({'error': 'nothing_to_refund'}, status=status.HTTP_400_BAD_REQUEST)
        if result.get('error') == 'fractional_remaining':
            return Response(
                {'error': 'fractional_remaining', 'remaining_lessons': result['remaining_lessons']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(result, status=status.HTTP_201_CREATED)
```
Добавить недостающие импорты в начало `apps/students/views.py`:
```python
from rest_framework import status
from rest_framework.exceptions import NotFound
from apps.core.permissions import IsAdminOrSuperAdmin
from apps.payments import services as payment_services
```
В `apps/students/urls.py` добавить в `urlpatterns` и в импорт:
```python
    path('/<int:pk>/refund', StudentRefundView.as_view(), name='students-refund'),
```

- [ ] **Step 5: Запустить — PASS**

Run: `pytest apps/payments/tests/test_payments_api.py -k refund -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/payments/services.py apps/students/views.py apps/students/urls.py apps/payments/tests/test_payments_api.py
git commit -m "feat(students): POST /students/{id}/refund (admin/superadmin only)"
```

### Task 4.4: Метка операции + журнал/откат возврата

**Files:**
- Modify: `apps/changelog/labels.py:44-46`
- Test: `apps/changelog/tests/test_revert.py` (или ближайший по смыслу)

- [ ] **Step 1: Тест метки**

В тесте labels/summary проверить `resolve_operation('POST', '/api/admin/students/5/refund') == 'payment.refund'`.

- [ ] **Step 2: Добавить правило**

В `apps/changelog/labels.py` в блок payments добавить (перед generic students-правилами по порядку не критично — путь специфичен):
```python
    ('POST', re.compile(r'^/api/admin/students/\d+/refund$'), 'payment.refund'),
```
Разместить рядом с `payment.create`/`payment.delete` (строки 44–46).

- [ ] **Step 3: Тест отката возврата восстанавливает баланс**

В `apps/changelog/tests/test_revert.py` добавить сценарий: оплата 4 урока → возврат (POST refund) → откат операции `payment.refund` через changelog-revert → баланс снова 4, `student_fifo_remaining.remaining_value` снова 4000. (Опереться на существующие хелперы revert в тестах changelog.)

- [ ] **Step 4: Запустить**

Run: `pytest apps/changelog/tests -k "revert or label or summary" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/changelog/labels.py apps/changelog/tests
git commit -m "feat(changelog): payment.refund label + revert restores balance"
```

### Task 4.5: Фронт — мутация возврата + RefundModal

**Files:**
- Modify: `frontend/admin-src/src/hooks/usePayments.ts`
- Create: `frontend/admin-src/src/pages/students/RefundModal.tsx`
- Modify: `frontend/admin-src/src/pages/students/StudentBalanceBlock.tsx`

- [ ] **Step 1: Мутация возврата и хук остатка**

В `frontend/admin-src/src/hooks/usePayments.ts` в `usePaymentMutations` добавить в возвращаемый объект:
```typescript
    refund: useMutation({
      mutationFn: (studentId: number) =>
        api<{ refund: Payment; new_balance: number; refunded_amount: number }>(
          'POST', `/api/admin/students/${studentId}/refund`, {}),
      onSuccess: invalidate,
    }),
```

- [ ] **Step 2: RefundModal**

Создать `frontend/admin-src/src/pages/students/RefundModal.tsx`:
```tsx
import { Dialog } from '../../components/ui/Dialog';
import { fmtRub, fmtLessons } from '../../lib/format';
import { usePaymentMutations } from '../../hooks/usePayments';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';

interface Props {
  open: boolean;
  onClose: () => void;
  studentId: number;
  remainingValue: number;   // неотработанные деньги
  remainingLessons: number; // неотработанные уроки
}

export function RefundModal({ open, onClose, studentId, remainingValue, remainingLessons }: Props) {
  const muts = usePaymentMutations();
  const showError = useApiError();
  const { toast } = useToast();

  const handleConfirm = async () => {
    try {
      const res = await muts.refund.mutateAsync(studentId);
      toast(`Возврат оформлен: ${fmtRub(res.refunded_amount)}`, 'ok');
      onClose();
    } catch (err) { showError(err); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title="Возврат средств">
      <div className="refund-modal">
        <p>Будет списан весь неотработанный остаток ученика:</p>
        <div className="refund-modal__amount">
          К возврату клиенту: <strong>{fmtRub(remainingValue)}</strong>
        </div>
        <div className="refund-modal__lessons muted">
          Сгорит {fmtLessons(remainingLessons)} оплаченных уроков. Баланс станет 0.
        </div>
        <div className="payment-form__footer">
          <button type="button" className="btn-cancel" onClick={onClose}>Отмена</button>
          <button type="button" className="btn-save" onClick={() => { void handleConfirm(); }}
            disabled={muts.refund.isPending || remainingValue <= 0}>
            Подтвердить возврат
          </button>
        </div>
      </div>
    </Dialog>
  );
}
```

- [ ] **Step 3: Кнопка возврата в балансе (RBAC)**

В `StudentBalanceBlock.tsx`: импортировать `useAuth` (провайдер с `me`), `RefundModal`, добавить состояние `refundOpen`. Кнопку «Возврат средств» показывать только при `me?.role === 'admin' || me?.role === 'superadmin'` и `data.total_balance > 0`. Остаток денег для модалки взять из `data` (см. шаг 4 — сервер должен отдавать `remaining_value`; если баланс-эндпоинт его не отдаёт, добавить в `get_student_balance` поле `remaining_value` через `student_fifo_remaining`). Открывать `RefundModal` с `remainingValue={data.remaining_value}` и `remainingLessons={data.total_balance}`.

- [ ] **Step 4: Отдать `remaining_value` из баланс-эндпоинта**

В `apps/finances/balance.py::get_student_balance` добавить в результат:
```python
    from apps.finances.repository import student_fifo_remaining
    remaining = student_fifo_remaining(student_id)
    ...
    return {
        ...
        'remaining_value': repository._js_number(remaining['remaining_value']),
    }
```
Обновить тип `StudentBalance` в `frontend/admin-src/src/lib/types.ts` (+`remaining_value: number`). Добавить бэкенд-тест в `apps/finances/tests/test_balance.py`, что поле присутствует и равно ожидаемому.

- [ ] **Step 5: Сборка + прогон**

Run: `npm run build` (front) и `pytest apps/finances -v` (back)
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/admin-src/src apps/finances/balance.py apps/finances/tests/test_balance.py
git commit -m "feat(admin): refund modal + button (admin/superadmin), remaining_value in balance"
```

### Task 4.6: История оплат — красная строка возврата + автор

**Files:**
- Modify: `frontend/admin-src/src/pages/students/StudentBalanceBlock.tsx:130-160`

- [ ] **Step 1: Отрисовка строки возврата и автора**

В списке `data.payments.map((p) => ...)` заменить `<li>` рендер на ветвление по `p.kind`:
```tsx
            {data.payments.map((p) => (
              <li key={p.id}
                  className={`balance-block__history-row${p.kind === 'refund' ? ' is-refund' : ''}`}>
                <div className="balance-block__history-main">
                  <span>{fmtDate(p.paid_at)}</span>
                  <span> · </span>
                  {p.kind === 'refund' ? (
                    <span className="refund-badge">Возврат {fmtRub(p.total_amount)}</span>
                  ) : p.subscriptions_count != null ? (
                    <>
                      <span>{p.direction_name || <em className="muted">Архив</em>}</span>
                      <span> · </span>
                      <span>{p.subscriptions_count} аб.</span>
                      <span> · </span>
                      <span>{fmtRub(p.unit_price)}/аб = <strong>{fmtRub(p.total_amount)}</strong></span>
                    </>
                  ) : (
                    <>
                      <span>предоплата, {p.lessons_count} уроков</span>
                      <span> · </span>
                      <span><strong>{fmtRub(p.total_amount)}</strong></span>
                    </>
                  )}
                  {p.created_by && <span className="muted"> · внёс: {p.created_by}</span>}
                  {p.note && <span className="muted"> — «{p.note}»</span>}
                </div>
                {/* кнопка удаления — как раньше */}
              </li>
            ))}
```

- [ ] **Step 2: Стиль красной строки**

В соответствующий CSS (файл стилей balance-block; найти по классу `balance-block__history-row`) добавить, используя токены из `styles/tokens.css` (не хардкодить цвет — взять переменную красного, напр. `var(--color-danger)`):
```css
.balance-block__history-row.is-refund { color: var(--color-danger); }
.balance-block__history-row .refund-badge { font-weight: 600; }
```
Если переменной для danger нет — использовать существующую (grep `--red`/`--danger` в `tokens.css`) или добавить токен в `tokens.css`.

- [ ] **Step 3: Сборка + ручная проверка**

Run: `npm run build`
Expected: PASS. Вручную: оформить возврат → в истории строка красная «Возврат … ₽», у обычных оплат виден «внёс: Павлов Илья».

- [ ] **Step 4: Commit**

```bash
git add frontend/admin-src/src
git commit -m "feat(admin): refund rows in red + author name in payment history"
```

**Чекпоинт фазы 4:** `pytest` весь зелёный; `npm run build` зелёный. Ручной сценарий: оплата → 1 посещение → возврат → баланс 0, красная строка, дашборд «Долги/Остатки» показывает 0 по ученику, откат возврата в журнале возвращает деньги.

---

## Финальная проверка

- [ ] Полный backend прогон: `pytest -q` из `journal_django/` — всё зелёное.
- [ ] Frontend: `npm run build` из `frontend/admin-src/` — без ошибок типов.
- [ ] Ручной e2e: блок-оплата, предоплата 2 урока, единая сумма за 3 блока (1000 ₽), возврат; проверить баланс, историю (красный возврат, автор), журнал изменений (описания + откат возврата), дашборд-финансы (возврат не в выручке).
- [ ] Проверить RBAC: возврат недоступен teacher/manager (403 на API, кнопка скрыта в UI).

## Замечания по рискам

- **Дробный остаток (half-lesson).** `lessons_count` целочислен; возврат при остатке `x.5` пока отклоняется (`fractional_remaining`). Если такие кейсы реальны — отдельной задачей завести Decimal-хранение количества или хранить остаток уроков как есть в деньгах. Обсудить с заказчиком до релиза фазы 4.
- **Cap и возврат.** Возврат (direction_id=NULL) не освобождает per-direction cap. Приемлемо (возвраты редки, пул общий). Задокументировано в `create_payment`.
- **Renewals.** Проверить `apps/renewals` сигналы/`rebuild_renewal_deals`: убедиться, что строка `kind='refund'` и предоплата не создают ложных сделок (сделки строятся по посещённым урокам, не по оплатам — ожидаемо безопасно, но прогнать `apps/renewals` тесты).
- **Миграция 0006** перезаписывает `created_by`. Согласовано с заказчиком (все существующие → «Павлов Илья»).
