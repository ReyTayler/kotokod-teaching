# Фикс баланса легаси-оплат (subscriptions_count) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Легаси-оплаты (`payments.direction_id IS NULL`, 2176 строк, 13.8 млн ₽) должны учитываться в глобальном балансе ученика (`balance_for_student`) наравне с обычными оплатами — сейчас `subscriptions_count IS NULL` у них не даёт формуле посчитать «куплено уроков», хотя деньги реально уплачены.

**Architecture:** Убираем CHECK-constraint `payments_direction_count_match`, который требует `direction_id` всегда, когда задан `subscriptions_count` (наследие старой модели «баланс по направлению» — в новой модели глобального пула это лишнее, `balance_for_student` не смотрит на `direction_id`). Затем data-миграцией проставляем `subscriptions_count = 1` всем 2176 легаси-строкам (это математически безопасно — у всех них `unit_price == total_amount`, что уже само по себе подтверждает «один абонемент на платёж»). `direction_id` у этих строк остаётся `NULL` — направление сознательно не восстанавливаем (не гадаем).

**Tech Stack:** Django 5.1 ORM-миграции (`apps/payments/migrations/`) — модели в этом проекте `managed=True`, схема управляется нативными Django-миграциями, а НЕ старыми SQL-файлами в `db/migrations/` (те заморожены на 014, ещё из Express-эпохи, использовать НЕ нужно).

**Spec:** обсуждение зафиксировано в переписке (см. контекст к плану ниже) — отдельного файла спеки не писали по прямой просьбе пользователя.

---

### Task 1: Убрать CHECK-constraint `payments_direction_count_match`

**Files:**
- Modify: `journal_django/apps/payments/models.py`
- Create: `journal_django/apps/payments/migrations/0003_remove_direction_count_match_constraint.py`
- Test: `journal_django/apps/payments/tests/test_payments_constraints.py` (новый файл)

- [ ] **Step 1: Прочитать текущее состояние модели**

Открыть `journal_django/apps/payments/models.py` и убедиться, что `class Meta` внутри `Payment` содержит ровно этот список `constraints` (если отличается — сообщить и не продолжать, разобраться сначала):

```python
        constraints = [
            models.CheckConstraint(
                name='payments_subscriptions_count_check',
                condition=models.Q(subscriptions_count__gt=0),
            ),
            models.CheckConstraint(
                name='payments_unit_price_check',
                condition=models.Q(unit_price__gte=0),
            ),
            models.CheckConstraint(
                name='payments_direction_count_match',
                condition=(
                    (models.Q(direction__isnull=True) & models.Q(subscriptions_count__isnull=True))
                    | (models.Q(direction__isnull=False) & models.Q(subscriptions_count__isnull=False)
                       & models.Q(subscriptions_count__gt=0))
                ),
            ),
            models.CheckConstraint(
                name='payments_total_match',
                condition=(
                    models.Q(subscriptions_count__isnull=True)
                    | models.Q(total_amount=models.F('unit_price') * models.F('subscriptions_count'))
                ),
            ),
        ]
```

- [ ] **Step 2: Написать падающий тест**

Создать `journal_django/apps/payments/tests/test_payments_constraints.py`:

```python
"""
Тесты CHECK-constraints таблицы payments после снятия payments_direction_count_match
(2026-07-09): subscriptions_count теперь можно задать НЕЗАВИСИМО от direction_id —
легаси-оплаты (direction_id NULL) тоже должны считаться в глобальном балансе.
"""
from __future__ import annotations

import pytest
from django.db import IntegrityError, connection

from apps.payments.models import Payment


def _make_student():
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status) "
            "VALUES ('__constraint_test_student__', 'enrolled') RETURNING id",
        )
        return cur.fetchone()[0]


@pytest.mark.django_db
class TestPaymentsDirectionCountConstraint:

    def test_subscriptions_count_without_direction_is_allowed(self):
        """Ключевой тест фикса: direction=NULL + subscriptions_count заданный — разрешено."""
        sid = _make_student()
        try:
            p = Payment.objects.create(
                student_id=sid, direction_id=None, subscriptions_count=2,
                unit_price='100.00', total_amount='200.00',
                paid_at='2026-01-01', created_at='2026-01-01T00:00:00Z',
            )
            assert p.id is not None
            assert p.direction_id is None
            assert p.subscriptions_count == 2
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM payments WHERE student_id = %s', [sid])
                cur.execute('DELETE FROM students WHERE id = %s', [sid])

    def test_subscriptions_count_zero_still_rejected(self):
        """payments_subscriptions_count_check по-прежнему работает (constraint не трогали)."""
        sid = _make_student()
        try:
            with pytest.raises(IntegrityError):
                Payment.objects.create(
                    student_id=sid, direction_id=None, subscriptions_count=0,
                    unit_price='100.00', total_amount='0.00',
                    paid_at='2026-01-01', created_at='2026-01-01T00:00:00Z',
                )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM students WHERE id = %s', [sid])

    def test_total_amount_mismatch_still_rejected(self):
        """payments_total_match по-прежнему работает (constraint не трогали)."""
        sid = _make_student()
        try:
            with pytest.raises(IntegrityError):
                Payment.objects.create(
                    student_id=sid, direction_id=None, subscriptions_count=2,
                    unit_price='100.00', total_amount='999.00',  # должно быть 200.00
                    paid_at='2026-01-01', created_at='2026-01-01T00:00:00Z',
                )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM students WHERE id = %s', [sid])
```

- [ ] **Step 3: Запустить и убедиться, что первый тест падает**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/payments/tests/test_payments_constraints.py -v`
Expected: `test_subscriptions_count_without_direction_is_allowed` FAILS с `django.db.utils.IntegrityError` (нарушение `payments_direction_count_match` — constraint ещё не снят). Два других теста должны сразу PASS (они проверяют constraints, которые не трогаем).

- [ ] **Step 4: Убрать constraint из модели**

В `journal_django/apps/payments/models.py`, внутри `class Meta` модели `Payment`, удалить блок `payments_direction_count_match` целиком, оставив:

```python
        constraints = [
            models.CheckConstraint(
                name='payments_subscriptions_count_check',
                condition=models.Q(subscriptions_count__gt=0),
            ),
            models.CheckConstraint(
                name='payments_unit_price_check',
                condition=models.Q(unit_price__gte=0),
            ),
            models.CheckConstraint(
                name='payments_total_match',
                condition=(
                    models.Q(subscriptions_count__isnull=True)
                    | models.Q(total_amount=models.F('unit_price') * models.F('subscriptions_count'))
                ),
            ),
        ]
```

Также обновить модульный докстринг в начале файла (первые строки файла), заменив:

```python
"""
Models for payments — managed=False, поверх существующей БД.

Таблица:
  payments — финансовые записи оплат (immutable: только POST/DELETE)

Схема из db/migrations/008_payments.sql + 009_payments_legacy.sql.
FK student_id/direction_id → ON DELETE RESTRICT (защита истории оплат от хард-удаления).
"""
```

на:

```python
"""
Models for payments — managed=False, поверх существующей БД.

Таблица:
  payments — финансовые записи оплат (immutable: только POST/DELETE)

Схема из db/migrations/008_payments.sql + 009_payments_legacy.sql, дополнена
Django-миграцией 0003 (2026-07-09): убран constraint payments_direction_count_match —
subscriptions_count теперь можно задать независимо от direction_id (легаси-оплаты
без направления тоже должны считаться в balance_for_student, который per-direction
скоуп не использует).
FK student_id/direction_id → ON DELETE RESTRICT (защита истории оплат от хард-удаления).
"""
```

- [ ] **Step 5: Сгенерировать Django-миграцию**

Run:
```bash
cd journal_django
DJANGO_SETTINGS_MODULE=config.settings.test ./.venv/Scripts/python.exe manage.py makemigrations payments
```
Expected: создаётся файл `journal_django/apps/payments/migrations/0003_remove_direction_count_match_constraint.py` (Django сам предложит похожее имя по умолчанию — если предложит другое, переименуйте файл и класс внутри так, чтобы имя файла было `0003_remove_direction_count_match_constraint.py`). Проверьте, что сгенерированное содержимое — это ровно:

```python
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0002_paymentevent_payment_insert_insert_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='payment',
            name='payments_direction_count_match',
        ),
    ]
```

Если сгенерированный файл отличается по содержимому операций (не только по комментарию заголовка `# Generated by Django...`) — не редактируйте руками молча, а сообщите об этом перед тем, как продолжать.

- [ ] **Step 6: Применить миграцию к тестовой БД и прогнать тесты**

Run:
```bash
cd journal_django
DJANGO_SETTINGS_MODULE=config.settings.test ./.venv/Scripts/python.exe manage.py migrate payments
./.venv/Scripts/pytest.exe apps/payments/tests/test_payments_constraints.py -v
```
Expected: миграция применяется без ошибок, все 3 теста PASS.

- [ ] **Step 7: Прогнать весь набор apps/payments (регрессия)**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/payments -v`
Expected: все PASS, 0 failed (снятие constraint не должно ломать существующие тесты — они не проверяли поведение, которое мы убрали, только create/cap_exceeded/balance).

- [ ] **Step 8: Commit**

Стейджить ТОЛЬКО явными путями (в рабочей директории может быть посторонний незакоммиченный WIP — не трогать его):
```bash
git add journal_django/apps/payments/models.py journal_django/apps/payments/migrations/0003_remove_direction_count_match_constraint.py journal_django/apps/payments/tests/test_payments_constraints.py
git diff --cached --stat
```
Убедиться, что в выводе только эти три файла, затем:
```bash
git commit -m "fix(payments): drop payments_direction_count_match — subscriptions_count no longer requires direction_id"
```

---

### Task 2: Бэкафилл `subscriptions_count=1` для легаси-оплат

**Files:**
- Create: `journal_django/apps/payments/migrations/0004_backfill_legacy_subscriptions_count.py`
- Test: `journal_django/apps/payments/tests/test_payments_constraints.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `journal_django/apps/payments/tests/test_payments_constraints.py`:

```python
import importlib

# Имя файла миграции начинается с цифры — не валидный идентификатор Python для
# обычного `import`, поэтому грузим модуль через importlib (сам Django точно так же
# динамически грузит файлы миграций). Ничего в apps/payments/migrations/__init__.py
# менять не нужно — импорт полностью локален для этого теста.
backfill_module = importlib.import_module(
    'apps.payments.migrations.0004_backfill_legacy_subscriptions_count'
)


@pytest.mark.django_db
class TestBackfillLegacySubscriptionsCount:

    def test_backfill_sets_one_for_null_direction_null_subs(self):
        """Легаси-строка (direction=NULL, subscriptions_count=NULL, unit_price=total_amount)
        после бэкафилла получает subscriptions_count=1."""
        sid = _make_student()
        try:
            with connection.cursor() as cur:
                cur.execute(
                    "INSERT INTO payments (student_id, direction_id, subscriptions_count, "
                    "unit_price, total_amount, paid_at, created_by) "
                    "VALUES (%s, NULL, NULL, 9990.00, 9990.00, '2024-03-15', 'backfill-script') "
                    "RETURNING id",
                    [sid],
                )
                pid = cur.fetchone()[0]

            from django.apps import apps as global_apps
            backfill_module.backfill_subscriptions_count(global_apps, None)

            p = Payment.objects.get(id=pid)
            assert p.subscriptions_count == 1
            assert p.direction_id is None  # направление сознательно НЕ восстанавливаем
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM payments WHERE student_id = %s', [sid])
                cur.execute('DELETE FROM students WHERE id = %s', [sid])

    def test_backfill_does_not_touch_properly_tagged_payments(self):
        """Оплата с direction_id уже заданным (и subscriptions_count заданным) — не трогается."""
        sid = _make_student()
        with connection.cursor() as cur:
            cur.execute('SELECT id FROM directions LIMIT 1')
            row = cur.fetchone()
        if not row:
            pytest.skip('No directions in DB — skipping')
        did = row[0]
        try:
            with connection.cursor() as cur:
                cur.execute(
                    "INSERT INTO payments (student_id, direction_id, subscriptions_count, "
                    "unit_price, total_amount, paid_at, created_by) "
                    "VALUES (%s, %s, 3, 1000.00, 3000.00, '2026-01-01', 'test') RETURNING id",
                    [sid, did],
                )
                pid = cur.fetchone()[0]

            from django.apps import apps as global_apps
            backfill_module.backfill_subscriptions_count(global_apps, None)

            p = Payment.objects.get(id=pid)
            assert p.subscriptions_count == 3  # не тронуто бэкафиллом
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM payments WHERE student_id = %s', [sid])
                cur.execute('DELETE FROM students WHERE id = %s', [sid])

    def test_backfilled_payment_counts_in_global_balance(self):
        """Ключевая проверка бага: после бэкафилла легаси-оплата считается в balance_for_student."""
        from apps.finances.repository import balance_for_student

        sid = _make_student()
        try:
            with connection.cursor() as cur:
                cur.execute(
                    "INSERT INTO payments (student_id, direction_id, subscriptions_count, "
                    "unit_price, total_amount, paid_at, created_by) "
                    "VALUES (%s, NULL, NULL, 9990.00, 9990.00, '2024-03-15', 'backfill-script')",
                    [sid],
                )

            assert balance_for_student(sid) == 0  # куплено 0 (subscriptions_count NULL), отработано 0

            from django.apps import apps as global_apps
            backfill_module.backfill_subscriptions_count(global_apps, None)

            assert balance_for_student(sid) == 4  # теперь 1 абонемент × 4 урока, куплено = 4
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM payments WHERE student_id = %s', [sid])
                cur.execute('DELETE FROM students WHERE id = %s', [sid])
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/payments/tests/test_payments_constraints.py -k TestBackfillLegacySubscriptionsCount -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.payments.migrations.0004_backfill_legacy_subscriptions_count'`, так как файла `0004_backfill_legacy_subscriptions_count.py` ещё нет.

- [ ] **Step 3: Создать файл миграции**

Создать `journal_django/apps/payments/migrations/0004_backfill_legacy_subscriptions_count.py`:

```python
"""
Data-миграция: легаси-оплаты (direction_id NULL, subscriptions_count NULL) получают
subscriptions_count=1 — один абонемент на строку. Безопасно ровно потому, что у ВСЕХ
таких строк unit_price == total_amount (проверено на реальных данных 2026-07-09,
0 исключений из 2176 строк) — условие payments_total_match (total_amount =
unit_price * subscriptions_count) при subscriptions_count=1 выполняется автоматически.
direction_id сознательно остаётся NULL — направление не восстанавливаем (не гадаем).

См. также миграцию 0003 (payments_direction_count_match снят) — БЕЗ неё эта миграция
упадёт по CHECK constraint.
"""
from __future__ import annotations

from django.db import migrations


def backfill_subscriptions_count(apps, schema_editor):
    Payment = apps.get_model('payments', 'Payment')
    Payment.objects.filter(
        direction_id__isnull=True, subscriptions_count__isnull=True,
    ).update(subscriptions_count=1)


def revert_backfill(apps, schema_editor):
    """
    Откат: возвращает subscriptions_count в NULL только для строк, которые сама эта
    миграция и создала — по direction_id IS NULL + created_by='backfill-script'
    (уникальный маркер легаси-бэкафилла, подтверждено: ВСЕ строки с этим created_by
    и NULL direction_id/subscriptions_count принадлежат только этому набору).
    """
    Payment = apps.get_model('payments', 'Payment')
    Payment.objects.filter(
        direction_id__isnull=True, subscriptions_count=1, created_by='backfill-script',
    ).update(subscriptions_count=None)


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0003_remove_direction_count_match_constraint'),
    ]

    operations = [
        migrations.RunPython(backfill_subscriptions_count, revert_backfill),
    ]
```

- [ ] **Step 4: Применить миграцию к тестовой БД и прогнать тесты**

Run:
```bash
cd journal_django
DJANGO_SETTINGS_MODULE=config.settings.test ./.venv/Scripts/python.exe manage.py migrate payments
./.venv/Scripts/pytest.exe apps/payments/tests/test_payments_constraints.py -v
```
Expected: миграция применяется без ошибок (в `journal_test` изначально нет легаси-строк, поэтому `RunPython` — no-op на самой БД, но три новых теста, вызывающие функцию напрямую, должны PASS). Все тесты в файле — PASS.

- [ ] **Step 5: Прогнать весь набор apps/payments и apps/finances (регрессия)**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/payments apps/finances -v`
Expected: все PASS, 0 failed.

- [ ] **Step 6: Commit**

Стейджить ТОЛЬКО явными путями:
```bash
git add journal_django/apps/payments/migrations/0004_backfill_legacy_subscriptions_count.py journal_django/apps/payments/tests/test_payments_constraints.py
git diff --cached --stat
```
Убедиться, что в выводе только эти три файла, затем:
```bash
git commit -m "fix(payments): backfill subscriptions_count=1 for legacy direction-less payments"
```

---

### Task 3: Применить обе миграции на dev-БД и проверить реальные данные

**Files:** нет изменений — только применение миграций и верификация на реальных данных.

⚠️ Этот таск меняет реальную dev-БД (`journal`, не `journal_test`). Изменение обратимо (есть `revert_backfill` + `RemoveConstraint` можно откатить через `migrate payments 0002`), но перед стартом стоит ещё раз свериться с пользователем, если что-то в шагах ниже не сходится с ожиданиями.

- [ ] **Step 1: Снимок «до» — сколько легаси-строк и какой баланс у Дуброва Макара**

Run:
```bash
cd journal_django
PYTHONIOENCODING=utf-8 DJANGO_SETTINGS_MODULE=config.settings.development ./.venv/Scripts/python.exe -c "
import sys; sys.stdout.reconfigure(encoding='utf-8')
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
django.setup()
from django.db import connection
with connection.cursor() as cur:
    cur.execute('SELECT COUNT(*) FROM payments WHERE direction_id IS NULL AND subscriptions_count IS NULL')
    print('legacy rows before:', cur.fetchone()[0])
from apps.finances.repository import balance_for_student
print('Дубров Макар (id=150) balance before:', balance_for_student(150))
"
```
Expected: `legacy rows before: 2176`, `balance before: -122` (или близко — баланс мог чуть измениться, если после прошлой сессии были новые уроки/оплаты; главное, что число отрицательное и большое).

- [ ] **Step 2: Применить миграции к dev-БД**

Run:
```bash
cd journal_django
DJANGO_SETTINGS_MODULE=config.settings.development ./.venv/Scripts/python.exe manage.py migrate payments
```
Expected: применяются миграции `0003_remove_direction_count_match_constraint` и `0004_backfill_legacy_subscriptions_count` без ошибок.

- [ ] **Step 3: Снимок «после» — проверить, что бэкафилл сработал и баланс поправился**

Run (тот же скрипт, что в Step 1):
```bash
cd journal_django
PYTHONIOENCODING=utf-8 DJANGO_SETTINGS_MODULE=config.settings.development ./.venv/Scripts/python.exe -c "
import sys; sys.stdout.reconfigure(encoding='utf-8')
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
django.setup()
from django.db import connection
with connection.cursor() as cur:
    cur.execute('SELECT COUNT(*) FROM payments WHERE direction_id IS NULL AND subscriptions_count IS NULL')
    print('legacy rows after (should be 0):', cur.fetchone()[0])
    cur.execute('SELECT COUNT(*) FROM payments WHERE direction_id IS NULL AND subscriptions_count = 1')
    print('legacy rows now subscriptions_count=1:', cur.fetchone()[0])
from apps.finances.repository import balance_for_student
print('Дубров Макар (id=150) balance after:', balance_for_student(150))
"
```
Expected: `legacy rows after (should be 0): 0`, `legacy rows now subscriptions_count=1: 2176`, баланс Дуброва Макара — заметно лучше, близко к небольшому положительному/near-zero числу (не −122).

- [ ] **Step 4: Полный прогон бэкенд-тестов (финальная регрессия)**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe -q`
Expected: без новых failures относительно текущего baseline.

- [ ] **Step 5: Показать сводку пользователю**

Это шаг для контроллера/пользователя, не для чистого автоматического исполнения: собрать и показать пользователю итоговую сводку — сколько строк исправлено, как изменился баланс у Дуброва Макара и ещё нескольких студентов из списка «баланс < −20» (см. переписку, там был список из 129 студентов) — чтобы пользователь подтвердил, что цифры теперь выглядят разумно, прежде чем считать задачу закрытой.
