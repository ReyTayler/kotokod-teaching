# Бухгалтерский отчёт → реестр признания выручки по платежам — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Переделать «Бухгалтерский отчёт» (`accounting_month`) из строки-на-ученика в реестр платежей: строка = поступление клиента с датой оплаты, ценой 1 урока, признанной выручкой по календарным месяцам до выбранного, выручкой итого и остатком аванса на конец выбранного месяца.

**Architecture:** Правила денег остаются в одном месте — `apps/finances/lots.py::build_lots` (партии) и `apps/finances/fifo.py::compute_fifo` (очередь). В партию добавляется `payment_id`, `compute_fifo` начинает отдавать три новых разреза тех же чисел по платежу (выручка по месяцам, остаток, погашено возвратом). `apps/finances/reports.py` переписывается поверх этих разрезов: потребления обрезаются по конец выбранного месяца (as-of), строки отбираются по наличию признания в выбранном месяце.

**Tech Stack:** Python 3 / Django + DRF, PostgreSQL, openpyxl, pytest. Celery-задача и API раздела «Отчёты» не меняются.

**Спека:** `docs/superpowers/specs/2026-09-08-accounting-payment-ledger-design.md`

**Git:** коммиты в этом проекте делаются ТОЛЬКО по явной просьбе пользователя (CLAUDE.md). Поэтому шагов «commit» в задачах нет — по завершении работа остаётся в рабочем дереве.

**Прогон тестов:** каждая задача гоняет свои тесты точечно, но финальная проверка — ПОЛНЫЙ `pytest -q` из `journal_django/` (частичный прогон по приложениям даёт ложный результат: часть приложений no-op'ит `django_db_setup`, часть пересоздаёт тестовую БД).

---

### Task 1: `month_label` / `next_month` переезжают в core-утилиты

Подписи колонок-месяцев («Июль 2026») нужны и прогнозу, и новому отчёту. Функция живёт в `apps/finances/revenue_forecast.py` — это модуль конкретного отчёта, тянуть из него в другой отчёт нельзя. Переносим в `apps/core/utils/dates.py`, где уже лежат месячные границы.

**Files:**
- Modify: `journal_django/apps/core/utils/dates.py`
- Modify: `journal_django/apps/finances/revenue_forecast.py:70-92`
- Test: `journal_django/apps/core/tests/test_dates.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `journal_django/apps/core/tests/test_dates.py` (если файла нет — создать с этим содержимым, добавив в начало `from apps.core.utils.dates import month_label, next_month`):

```python
def test_month_label_renders_russian_month_and_year():
    from apps.core.utils.dates import month_label
    assert month_label('2026-07') == 'Июль 2026'
    assert month_label('2027-01') == 'Январь 2027'


def test_next_month_rolls_over_the_year():
    from apps.core.utils.dates import next_month
    assert next_month('2026-07') == '2026-08'
    assert next_month('2026-12') == '2027-01'
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `cd journal_django && pytest apps/core/tests/test_dates.py -q`
Expected: FAIL — `ImportError: cannot import name 'month_label'`.

- [ ] **Step 3: Перенести функции в core**

В конец `journal_django/apps/core/utils/dates.py` добавить:

```python
_MONTH_NAMES = (
    'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
)


def month_label(ym: str) -> str:
    """'2026-07' → 'Июль 2026'. Подпись месяца-колонки в отчётах."""
    year, month = int(ym[:4]), int(ym[5:7])
    return f'{_MONTH_NAMES[month - 1]} {year}'


def next_month(ym: str) -> str:
    """'2026-12' → '2027-01'."""
    year, month = int(ym[:4]), int(ym[5:7])
    return f'{year + 1}-01' if month == 12 else f'{year}-{month + 1:02d}'
```

В `journal_django/apps/finances/revenue_forecast.py` удалить определения `_MONTH_NAMES`, `month_label`, `next_month` и заменить импорт дат на:

```python
from apps.core.utils.dates import month_label, msk_month_range, msk_today, next_month
```

(имена остаются атрибутами модуля `revenue_forecast`, поэтому существующие
`from apps.finances.revenue_forecast import month_label, next_month` в тестах
продолжают работать — проверяется на шаге 4).

- [ ] **Step 4: Запустить тесты**

Run: `cd journal_django && pytest apps/core/tests/test_dates.py apps/finances/tests/test_revenue_forecast_split.py apps/reports/tests/test_revenue_forecast.py -q`
Expected: PASS, без ошибок импорта.

---

### Task 2: партия знает свой платёж (`payment_id` в lots)

**Files:**
- Modify: `journal_django/apps/finances/lots.py`
- Test: `journal_django/apps/finances/tests/test_lots_blocks.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `journal_django/apps/finances/tests/test_lots_blocks.py`:

```python
def test_build_lots_marks_every_lot_with_its_payment_id():
    rows = [
        {'id': 11, 'lessons_count': 4, 'total_amount': 2000, 'kind': 'purchase', 'direction_id': 1},
        {'id': 12, 'lessons_count': 8, 'total_amount': 4000, 'kind': 'purchase', 'direction_id': 1},
    ]
    lots = build_lots(rows, {})
    assert [lot['payment_id'] for lot in lots] == [11, 12]


def test_build_lots_blocks_of_one_payment_share_payment_id():
    """Доплата дробит оплату на блоки — но все блоки принадлежат одному платежу."""
    rows = [{'id': 21, 'lessons_count': 8, 'total_amount': 4000, 'kind': 'purchase', 'direction_id': 1}]
    lots = build_lots(rows, {21: {2: Decimal('500')}})
    assert len(lots) == 2
    assert {lot['payment_id'] for lot in lots} == {21}
```

Если в файле ещё нет импортов — добавить в начало:

```python
from decimal import Decimal

from apps.finances.lots import build_lots
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `cd journal_django && pytest apps/finances/tests/test_lots_blocks.py -q`
Expected: FAIL — `KeyError: 'payment_id'`.

- [ ] **Step 3: Реализовать**

В `journal_django/apps/finances/lots.py`:

1. В docstring `build_lots` строку возврата заменить на:

```
    Возвращает [{'lessons': int, 'price_per_lesson': Decimal, 'direction_id': int|None,
                 'payment_id': int}]. payment_id — id оплаты, породившей партию;
    оплата с доплатами даёт несколько партий с ОДНИМ payment_id (по нему отчёты
    собирают их обратно в один платёж).
```

2. В ветке «без доплат» добавить ключ:

```python
            lots.append({
                'lessons': lessons,
                'price_per_lesson': total / Decimal(lessons),
                'direction_id': direction_id,
                'payment_id': r['id'],
            })
            continue
        lots.extend(_split_into_blocks(lessons, total, surcharges, direction_id, r['id']))
```

3. Сигнатуру и тело `_split_into_blocks` дополнить:

```python
def _split_into_blocks(lessons: int, total: Decimal, surcharges: dict, direction_id, payment_id):
```

и в собираемый блок добавить `'payment_id': payment_id,` рядом с `'direction_id': direction_id,`.

- [ ] **Step 4: Запустить тесты**

Run: `cd journal_django && pytest apps/finances/tests/test_lots_blocks.py apps/finances/tests/test_fifo_inputs.py apps/finances/tests/test_refund_remaining.py -q`
Expected: PASS.

---

### Task 3: `compute_fifo` отдаёт три разреза по платежу

**Files:**
- Modify: `journal_django/apps/finances/fifo.py`
- Test: `journal_django/apps/finances/tests/test_fifo.py`

- [ ] **Step 1: Написать падающие тесты**

Дописать в конец `journal_django/apps/finances/tests/test_fifo.py`:

```python
# ---------------------------------------------------------------------------
# Разрезы по платежу (реестр признания выручки, спека 2026-09-08)
# ---------------------------------------------------------------------------

def test_worked_off_by_month_payment_splits_recognition_across_months():
    lots = [{'lessons': 4, 'price_per_lesson': _D(500), 'payment_id': 7}]
    cons = _lessons(1, '2025-09-10') + _lessons(2, '2026-06-10')
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_month_payment'] == {
        ('2025-09', 7): _D(500),
        ('2026-06', 7): _D(1000),
    }
    assert r['remaining_by_payment'] == {7: _D(500)}


def test_payment_slices_are_summed_into_one_payment_key():
    """Оплата с доплатой = две партии с разными ценами, но одним payment_id."""
    lots = [
        {'lessons': 4, 'price_per_lesson': _D(500), 'payment_id': 9},
        {'lessons': 4, 'price_per_lesson': _D(625), 'payment_id': 9},
    ]
    cons = _lessons(6, '2026-06-10')
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_month_payment'] == {('2026-06', 9): _D(3250)}  # 4*500 + 2*625
    assert r['remaining_by_payment'] == {9: _D(1250)}                       # 2*625


def test_refund_fills_refunded_by_payment_and_not_revenue():
    lots = [{'lessons': 4, 'price_per_lesson': _D(500), 'payment_id': 3}]
    cons = [
        {'units': 1, 'date': '2026-06-10'},
        {'units': 2, 'date': '2026-06-20', 'refund': True},
    ]
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_month_payment'] == {('2026-06', 3): _D(500)}
    assert r['refunded_by_payment'] == {3: _D(1000)}
    assert r['remaining_by_payment'] == {3: _D(500)}


def test_payment_cuts_are_exact_and_reconcile_with_lot_value():
    """Инвариант строки отчёта: стоимость партий = выручка + возврат + остаток."""
    lots = [{'lessons': 3, 'price_per_lesson': _D(1000) / _D(3), 'payment_id': 5}]
    cons = [
        {'units': 1, 'date': '2026-06-10'},
        {'units': 1, 'date': '2026-06-20', 'refund': True},
    ]
    r = compute_fifo(lots, cons, MS, ME)
    revenue = sum(r['worked_off_by_month_payment'].values())
    assert revenue + r['refunded_by_payment'][5] + r['remaining_by_payment'][5] == _D(1000)


def test_half_lesson_recognition_lands_in_its_own_month():
    lots = [{'lessons': 4, 'price_per_lesson': _D(500), 'payment_id': 4}]
    cons = [{'units': 0.5, 'date': '2026-05-10'}, {'units': 0.5, 'date': '2026-06-10'}]
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_month_payment'] == {
        ('2025-05'.replace('2025', '2026'), 4): _D(250),
        ('2026-06', 4): _D(250),
    }


def test_lots_without_payment_id_are_skipped_in_payment_cuts():
    """Легаси-вызовы без payment_id должны работать как раньше, без падений."""
    lots = [{'lessons': 4, 'price_per_lesson': _D(500)}]
    r = compute_fifo(lots, _lessons(2, '2026-06-10'), MS, ME)
    assert r['worked_off_by_month_payment'] == {}
    assert r['remaining_by_payment'] == {}
    assert r['refunded_by_payment'] == {}
    assert r['worked_off_month'] == _D('1000.00')
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `cd journal_django && pytest apps/finances/tests/test_fifo.py -q`
Expected: FAIL — `KeyError: 'worked_off_by_month_payment'`.

- [ ] **Step 3: Реализовать разрезы**

В `journal_django/apps/finances/fifo.py`:

1. Рядом с объявлениями `by_month_lot_direction` / `by_month_lesson_direction` добавить:

```python
    # Разрезы ПО ПЛАТЕЖУ (реестр признания выручки, спека 2026-09-08). Партия
    # знает свой payment_id (build_lots), оплата с доплатами даёт несколько
    # партий с одним id — здесь они складываются обратно в один платёж.
    # ВАЖНО: значения НЕ округляются до копеек (в отличие от worked_off_*),
    # потребитель округляет один раз и распределяет невязку — та же дисциплина,
    # что у remaining_lots.price_per_lesson.
    by_month_payment: dict = {}
    remaining_by_payment: dict = {}
    refunded_by_payment: dict = {}
```

2. Внутри цикла, где считается `value`, дополнить обе ветки:

```python
            take = need if need < lot_remaining else lot_remaining  # min(need, lot_remaining)
            value = take * to_decimal(lots[lot_idx]['price_per_lesson'])
            payment_id = lots[lot_idx].get('payment_id')
            if not is_refund:
                ...  # существующий блок без изменений
                if payment_id is not None:
                    mp_key = (c['date'][:7], payment_id)
                    by_month_payment[mp_key] = by_month_payment.get(mp_key, _ZERO) + value
            elif payment_id is not None:
                refunded_by_payment[payment_id] = (
                    refunded_by_payment.get(payment_id, _ZERO) + value
                )
```

(строка `if not is_refund:` уже существует — добавляется только хвост с
`payment_id` внутри неё и ветка `elif`; сам расчёт очереди не трогаем).

3. В `_keep` добавить накопление остатка:

```python
        payment_id = lot.get('payment_id')
        if payment_id is not None:
            remaining_by_payment[payment_id] = (
                remaining_by_payment.get(payment_id, _ZERO) + lessons * price
            )
```

4. В возвращаемый словарь добавить (значения точные, без `round_kopecks`):

```python
        # Разрезы по платежу для реестра признания выручки. Точные Decimal:
        # округление один раз делает отчёт, отдавая невязку последнему месяцу.
        'worked_off_by_month_payment': dict(by_month_payment),
        'remaining_by_payment': dict(remaining_by_payment),
        'refunded_by_payment': dict(refunded_by_payment),
```

5. В модульный docstring, в перечисление возвращаемых ключей, добавить:

```
  worked_off_by_month_payment: { (ym, payment_id): Decimal } — признанная выручка
  в разрезе ПЛАТЕЖА (не направления): чьи именно деньги стали выручкой в этом
  месяце. remaining_by_payment / refunded_by_payment — тот же разрез для
  неотработанного остатка и для денег, погашенных возвратом. Все три — ТОЧНЫЕ
  Decimal без округления (потребитель округляет один раз). Партии без
  payment_id в эти разрезы не попадают.
```

- [ ] **Step 4: Запустить тесты**

Run: `cd journal_django && pytest apps/finances/tests/test_fifo.py apps/finances/tests/test_revenue_forecast_split.py -q`
Expected: PASS (все golden-тесты старых ключей тоже зелёные).

---

### Task 4: сборка данных реестра (`collect_monthly_report`)

**Files:**
- Modify: `journal_django/apps/finances/reports.py` (переписывается целиком)
- Test: `journal_django/apps/finances/tests/test_reports.py` (переписывается целиком)

- [ ] **Step 1: Переписать тест сборки**

Заменить содержимое `journal_django/apps/finances/tests/test_reports.py` на:

```python
"""
Тесты сборки реестра признания выручки
(apps/finances/reports.py::collect_monthly_report).

Строка отчёта = платёж. Фикстуры — apps/finances/tests/conftest.py; БД общая
(managed=False), поэтому строки своего платежа ищем по payment_id.

Спека: docs/superpowers/specs/2026-09-08-accounting-payment-ledger-design.md
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection

from apps.finances.reports import collect_monthly_report

pytestmark = pytest.mark.django_db


def _add_payment(created, student_id, direction_id, subs, total, paid_at, kind='purchase'):
    positive = kind in ('purchase', 'extra')
    lessons = subs * 4 if positive else -(subs * 4)
    amount = total if positive else -total
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, lessons_count, "
            "kind, unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'test') RETURNING id",
            [student_id, direction_id, subs, lessons, kind, total, amount, paid_at],
        )
        pid = cur.fetchone()[0]
    created['payments'].append(pid)
    return pid


def _add_payment_exact(created, student_id, direction_id, lessons_count, unit_price, paid_at):
    total = lessons_count * unit_price
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, lessons_count, "
            "kind, unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s,%s,1,%s,'purchase',%s,%s,%s,'test') RETURNING id",
            [student_id, direction_id, lessons_count, unit_price, total, paid_at],
        )
        pid = cur.fetchone()[0]
    created['payments'].append(pid)
    return pid


def _add_surcharge(created, student_id, parent_id, index, total, paid_at):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, subscriptions_count, lessons_count, kind, "
            "unit_price, total_amount, paid_at, created_by, parent_payment_id, subscription_index) "
            "VALUES (%s,0,0,'surcharge',%s,%s,%s,'test',%s,%s) RETURNING id",
            [student_id, total, total, paid_at, parent_id, index],
        )
        pid = cur.fetchone()[0]
    created['payments'].append(pid)
    return pid


def _add_lesson_attendance(created, group_id, teacher_id, student_id, date, duration=60, is_free=False):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s,%s,%s,1,%s,'regular','test') RETURNING id",
            [group_id, teacher_id, date, duration],
        )
        lid = cur.fetchone()[0]
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present, is_free) '
            'VALUES (%s,%s,true,%s)',
            [lid, student_id, is_free],
        )
    created['lessons'].append(lid)
    return lid


def _row(report, payment_id):
    return next((r for r in report.rows if r.payment_id == payment_id), None)


def test_row_shows_payment_recognition_by_month_total_and_advance(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    with connection.cursor() as cur:
        cur.execute("UPDATE students SET platform_id = 'PL-42' WHERE id = %s", [student_fixture])
    pid = _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-05-01')
    # По одному уроку в мае, июне и июле — признание растянуто на три месяца.
    for date in ('2026-05-10', '2026-06-10', '2026-07-10'):
        _add_lesson_attendance(
            graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, date,
        )

    report = collect_monthly_report('2026-07')
    row = _row(report, pid)

    assert row is not None
    assert row.platform_id == 'PL-42'
    assert row.paid_at == '2026-05-01'
    assert row.total_amount == Decimal('2000')
    assert row.surcharge_amount == Decimal('0')
    assert row.unit_price == Decimal('500.00')
    assert row.revenue_by_month == {
        '2026-05': Decimal('500.00'),
        '2026-06': Decimal('500.00'),
        '2026-07': Decimal('500.00'),
    }
    assert row.revenue_total == Decimal('1500.00')
    assert row.refunded == Decimal('0.00')
    assert row.advance == Decimal('500.00')
    # Шкала месяцев — сплошная, от раннего признания до выбранного месяца.
    assert report.months[0] <= '2026-05'
    assert report.months[-1] == '2026-07'
    assert report.months == sorted(set(report.months))


def test_payment_without_recognition_in_month_is_absent(
    student_fixture, direction_fixture, graph_cleanup,
):
    """Свежая оплата без проведённых уроков строки не даёт (решение 3 спеки)."""
    pid = _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-07-05')

    assert _row(collect_monthly_report('2026-07'), pid) is None


def test_advance_is_as_of_end_of_month(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    """Уроки ПОСЛЕ выбранного месяца не уменьшают аванс и не создают колонок."""
    pid = _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-06-01')
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-10',
    )
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-08-05',
    )

    report = collect_monthly_report('2026-07')
    row = _row(report, pid)

    assert row.revenue_total == Decimal('500.00')      # августовский урок не признан
    assert row.advance == Decimal('1500.00')           # 3 урока по 500 ещё авансом
    assert '2026-08' not in row.revenue_by_month
    assert report.months[-1] == '2026-07'


def test_surcharge_is_shown_in_its_own_column_and_raises_unit_price(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    """Доплата к абонементу своей строки не даёт: она видна в колонке родителя."""
    pid = _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-07-01')
    sid = _add_surcharge(graph_cleanup, student_fixture, pid, 1, 400, '2026-07-02')
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-10',
    )

    report = collect_monthly_report('2026-07')
    row = _row(report, pid)

    assert _row(report, sid) is None                   # сама доплата строкой не является
    assert row.total_amount == Decimal('2000')
    assert row.surcharge_amount == Decimal('400')
    assert row.unit_price == Decimal('600.00')         # (2000 + 400) / 4
    assert row.revenue_total == Decimal('600.00')      # 1 урок по подорожавшей цене
    assert row.advance == Decimal('1800.00')


def test_refund_is_shown_and_row_reconciles(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    pid = _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-07-01')
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-10',
    )
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 1500, '2026-07-20', kind='refund')

    row = _row(collect_monthly_report('2026-07'), pid)

    assert row.revenue_total == Decimal('500.00')
    assert row.refunded == Decimal('1500.00')
    assert row.advance == Decimal('0.00')


def test_every_row_reconciles(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    """Инвариант отчёта: Сумма + Доплаты = Выручка итого + Возвращено + Аванс."""
    _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 3, 1000, '2026-06-01')
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-10',
    )
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-11', duration=45,
    )

    for row in collect_monthly_report('2026-07').rows:
        assert row.total_amount + row.surcharge_amount == (
            row.revenue_total + row.refunded + row.advance
        ), f'строка не сходится: платёж {row.payment_id}'


def test_advance_matches_fifo_remaining_within_a_kopeck(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    """Аванс выводится из суммы строки — он обязан совпадать с FIFO-остатком."""
    from apps.finances.fifo import compute_fifo
    from apps.finances.repository import fifo_inputs

    pid = _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 3, 1000, '2026-06-01')
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-10',
    )

    row = _row(collect_monthly_report('2026-07'), pid)
    inp = fifo_inputs()
    key = str(student_fixture)
    cons = [c for c in inp['cons_by_key'].get(key, []) if c['date'] <= '2026-07-31']
    fifo = compute_fifo(inp['lots_by_key'][key], cons, '2026-07-01', '2026-08-01')

    assert abs(row.advance - fifo['remaining_by_payment'][pid]) <= Decimal('0.01')


def test_half_lesson_recognizes_half_the_price(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    pid = _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-07-01')
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-10', duration=45,
    )

    row = _row(collect_monthly_report('2026-07'), pid)

    assert row.revenue_by_month == {'2026-07': Decimal('250.00')}
    assert row.advance == Decimal('1750.00')


def test_free_lesson_recognizes_nothing(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    """Бесплатное занятие денег не берёт — строки в отчёте не появляется."""
    pid = _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-07-01')
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-10', is_free=True,
    )

    assert _row(collect_monthly_report('2026-07'), pid) is None


def test_extra_payment_gets_its_own_row_without_direction(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    """Доплата за доп.урок сверх курса — самостоятельная партия, значит и строка."""
    from apps.finances.reports import NO_DIRECTION

    _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 1, 500, '2026-06-01')
    extra_pid = _add_payment(
        graph_cleanup, student_fixture, direction_fixture, 1, 1872, '2026-07-01', kind='extra',
    )
    # Первый урок гасит партию-предоплату, второй уходит уже в партию extra.
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-05',
    )
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-06',
    )

    row = _row(collect_monthly_report('2026-07'), extra_pid)

    assert row is not None
    assert row.direction_name == NO_DIRECTION
    assert row.revenue_by_month == {'2026-07': Decimal('468.00')}   # 1872 / 4


def test_rows_sorted_by_student_then_payment_date(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 1, 500, '2026-05-01')
    _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 1, 500, '2026-04-01')
    for date in ('2026-07-05', '2026-07-06'):
        _add_lesson_attendance(
            graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, date,
        )

    rows = [r for r in collect_monthly_report('2026-07').rows if r.student_id == student_fixture]

    assert [r.paid_at for r in rows] == ['2026-04-01', '2026-05-01']


def test_empty_report_still_reports_the_selected_month():
    report = collect_monthly_report('2019-01')
    assert report.rows == []
    assert report.months == ['2019-01']


def test_invalid_month_raises_value_error():
    with pytest.raises(ValueError):
        collect_monthly_report('2026-13')
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `cd journal_django && pytest apps/finances/tests/test_reports.py -q`
Expected: FAIL — `ImportError` / `AttributeError`: у отчёта нет `rows`, `PaymentLedgerRow` не существует.

- [ ] **Step 3: Переписать сборку данных**

Заменить в `journal_django/apps/finances/reports.py` всё, что выше `def _pair_cols`, на:

```python
"""
Реестр признания выручки по платежам («Бухгалтерский отчёт») + запись в Excel.

Строка = поступление клиента: дата оплаты, цена 1 урока по этому платежу,
признанная выручка по календарным месяцам до выбранного включительно, выручка
итого, возвращённые деньги и остаток аванса на конец выбранного месяца.

Правила денег не дублируются: партии строит apps/finances/lots.py::build_lots,
очередь — apps/finances/fifo.py::compute_fifo. Отчёт лишь читает разрезы по
платежу (worked_off_by_month_payment / remaining_by_payment /
refunded_by_payment), которые FIFO отдаёт точными Decimal.

As-of: потребления обрезаются по последний день выбранного месяца ДО вызова
compute_fifo — отсюда и аванс на конец месяца, и отсутствие месяцев позже
выбранного, без отдельной арифметики.

См. docs/superpowers/specs/2026-09-08-accounting-payment-ledger-design.md
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from django.db.models import F, Sum

from apps.core.utils.dates import month_label, msk_month_range, next_month
from apps.core.utils.decimal import round_kopecks
from apps.finances.fifo import compute_fifo
from apps.finances.repository import _date_str, fifo_inputs
from apps.payments.models import Payment
from apps.students.models import Student

NO_DIRECTION = 'Без направления'

_ZERO = Decimal('0')


@dataclass
class PaymentLedgerRow:
    """Одно поступление клиента и судьба его денег на конец выбранного месяца."""

    payment_id: int
    student_id: int
    full_name: str
    platform_id: str | None
    direction_name: str
    paid_at: str                  # 'YYYY-MM-DD'
    total_amount: Decimal         # сумма самой оплаты, без доплат
    surcharge_amount: Decimal     # доплаты к абонементам этой оплаты
    unit_price: Decimal           # (сумма + доплаты) / уроков оплаты
    # 'YYYY-MM' → признанная выручка месяца (только месяцы с признанием).
    revenue_by_month: dict[str, Decimal] = field(default_factory=dict)
    revenue_total: Decimal = _ZERO
    refunded: Decimal = _ZERO
    advance: Decimal = _ZERO


@dataclass
class LedgerReport:
    """Готовые данные листа: месяцы-колонки и строки-платежи."""

    month: str
    months: list[str]
    rows: list[PaymentLedgerRow]


def _months_range(first: str, last: str) -> list[str]:
    """Сплошная шкала календарных месяцев [first, last]."""
    out = [first]
    while out[-1] < last:
        out.append(next_month(out[-1]))
    return out


def _round_by_month(exact_by_month: dict[str, Decimal]) -> tuple[dict[str, Decimal], Decimal]:
    """
    Округлить месяцы до копеек, отдав невязку последнему месяцу с признанием.

    Тот же приём, что в apps/finances/revenue_forecast.py: сумма показанных
    ячеек в точности равна округлённой признанной выручке платежа.
    """
    total = round_kopecks(sum(exact_by_month.values(), _ZERO))
    ordered = sorted(exact_by_month)  # 'YYYY-MM' лексикографически = хронологически
    rounded: dict[str, Decimal] = {}
    accumulated = _ZERO
    for i, ym in enumerate(ordered):
        if i < len(ordered) - 1:
            cell = round_kopecks(exact_by_month[ym])
            accumulated += cell
        else:
            cell = total - accumulated
        rounded[ym] = cell
    return rounded, total


def collect_monthly_report(month: str) -> LedgerReport:
    """
    Реестр платежей, признавших выручку в указанном месяце.

    month: 'YYYY-MM'. В отчёт попадает платёж, у которого в этом месяце есть
    признанная выручка. Признание показывается по всем месяцам от самого
    раннего среди отобранных строк до указанного включительно; аванс — остаток
    на конец указанного месяца.

    Raises:
        ValueError: month не в формате YYYY-MM / невалидный месяц (1-12).
    """
    month_start, month_end = msk_month_range(f'{month}-01')
    # compute_fifo работает с эксклюзивной верхней границей [start, end).
    month_end_exclusive = (
        datetime.date.fromisoformat(month_end) + datetime.timedelta(days=1)
    ).strftime('%Y-%m-%d')

    inp = fifo_inputs()
    worked: dict[tuple[str, int], Decimal] = {}
    remaining: dict[int, Decimal] = {}
    refunded: dict[int, Decimal] = {}
    for key in inp['keys']:
        # As-of: всё, что позже конца месяца, отчёт ещё «не видит».
        cons = [c for c in inp['cons_by_key'].get(key, []) if c['date'] <= month_end]
        fifo = compute_fifo(
            inp['lots_by_key'].get(key, []), cons, month_start, month_end_exclusive,
        )
        # Платёж принадлежит ровно одному ученику, поэтому ключи разных
        # учеников не пересекаются и update() ничего не затирает.
        worked.update(fifo['worked_off_by_month_payment'])
        remaining.update(fifo['remaining_by_payment'])
        refunded.update(fifo['refunded_by_payment'])

    selected = {pid for (ym, pid), value in worked.items() if ym == month and value > 0}
    if not selected:
        return LedgerReport(month=month, months=[month], rows=[])

    exact_by_payment: dict[int, dict[str, Decimal]] = {}
    for (ym, pid), value in worked.items():
        if pid in selected and value > 0:
            exact_by_payment.setdefault(pid, {})[ym] = value

    earliest = min(ym for months in exact_by_payment.values() for ym in months)

    payments = (
        Payment.objects
        .filter(id__in=selected)
        .values('id', 'student_id', 'paid_at', 'total_amount', 'lessons_count',
                direction_name=F('direction__name'))
    )
    surcharge_rows = (
        Payment.objects
        .filter(kind='surcharge', parent_payment_id__in=selected)
        .values('parent_payment_id')
        .annotate(total=Sum('total_amount'))
    )
    surcharge_by_parent = {r['parent_payment_id']: r['total'] for r in surcharge_rows}
    students = {
        s['id']: s
        for s in Student.objects
        .filter(id__in={p['student_id'] for p in payments})
        .values('id', 'full_name', 'platform_id')
    }

    rows: list[PaymentLedgerRow] = []
    for p in payments:
        pid = p['id']
        by_month, revenue_total = _round_by_month(exact_by_payment[pid])
        refund_amount = round_kopecks(refunded.get(pid, _ZERO))
        surcharge = Decimal(surcharge_by_parent.get(pid) or 0)
        gross = Decimal(p['total_amount']) + surcharge
        lessons = int(p['lessons_count'] or 0)
        student = students.get(p['student_id'], {})
        rows.append(PaymentLedgerRow(
            payment_id=pid,
            student_id=p['student_id'],
            full_name=student.get('full_name') or '',
            platform_id=student.get('platform_id'),
            direction_name=p['direction_name'] or NO_DIRECTION,
            paid_at=_date_str(p['paid_at']),
            total_amount=Decimal(p['total_amount']),
            surcharge_amount=surcharge,
            unit_price=round_kopecks(gross / lessons) if lessons > 0 else _ZERO,
            revenue_by_month=by_month,
            revenue_total=revenue_total,
            refunded=refund_amount,
            # Аванс абсорбирует невязку округления: строка сходится всегда
            # (в точной арифметике это и есть remaining_by_payment — см. §4.4 спеки).
            advance=gross - revenue_total - refund_amount,
        ))

    rows.sort(key=lambda r: (r.full_name, r.paid_at, r.payment_id))
    return LedgerReport(month=month, months=_months_range(earliest, month), rows=rows)
```

- [ ] **Step 4: Запустить тесты**

Run: `cd journal_django && pytest apps/finances/tests/test_reports.py -q`
Expected: PASS (тесты рендера xlsx ещё падают — их чинит Task 5).

---

### Task 5: рендер листа Excel

**Files:**
- Modify: `journal_django/apps/finances/reports.py` (всё, что ниже `collect_monthly_report`)
- Test: `journal_django/apps/finances/tests/test_reports_xlsx.py` (переписывается целиком)

- [ ] **Step 1: Переписать тест рендера**

Заменить содержимое `journal_django/apps/finances/tests/test_reports_xlsx.py` на:

```python
"""
Тесты записи листа реестра (apps/finances/reports.py::write_report_xlsx).
Без БД — строки собираются вручную.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

import openpyxl

from apps.finances.reports import LedgerReport, PaymentLedgerRow, write_report_xlsx


def _report():
    return LedgerReport(
        month='2026-07',
        months=['2026-05', '2026-06', '2026-07'],
        rows=[
            PaymentLedgerRow(
                payment_id=1, student_id=10, full_name='Аня А.', platform_id='PL-1',
                direction_name='Minecraft', paid_at='2026-05-01',
                total_amount=Decimal('2000'), surcharge_amount=Decimal('0'),
                unit_price=Decimal('500.00'),
                revenue_by_month={'2026-05': Decimal('500.00'), '2026-07': Decimal('500.00')},
                revenue_total=Decimal('1000.00'), refunded=Decimal('0.00'),
                advance=Decimal('1000.00'),
            ),
            PaymentLedgerRow(
                payment_id=2, student_id=11, full_name='Боря Б.', platform_id=None,
                direction_name='Без направления', paid_at='2026-06-15',
                total_amount=Decimal('2000'), surcharge_amount=Decimal('400'),
                unit_price=Decimal('600.00'),
                revenue_by_month={'2026-06': Decimal('600.00')},
                revenue_total=Decimal('600.00'), refunded=Decimal('1800.00'),
                advance=Decimal('0.00'),
            ),
        ],
    )


def test_header_lists_fixed_columns_then_months_then_totals(tmp_path):
    out = tmp_path / 'ledger.xlsx'

    write_report_xlsx(_report(), out)

    ws = openpyxl.load_workbook(out).active
    assert ws.title == 'Реестр'
    assert [c.value for c in ws[1]] == [
        'ФИО ученика', 'Platform ID', 'Направление оплаты', 'Дата оплаты',
        'Сумма платежа, ₽', 'Доплаты, ₽', 'Цена 1 урока, ₽',
        'Май 2026', 'Июнь 2026', 'Июль 2026',
        'Выручка итого, ₽', 'Возвращено, ₽', 'Аванс, ₽',
    ]
    assert ws.freeze_panes == 'A2'


def test_row_values_and_empty_month_cells(tmp_path):
    out = tmp_path / 'ledger.xlsx'

    write_report_xlsx(_report(), out)

    ws = openpyxl.load_workbook(out).active
    first = [c.value for c in ws[2]]
    # openpyxl всегда читает дату обратно как datetime.datetime — формат ячеек
    # Excel не различает «дату» и «дату-время».
    assert first[:7] == [
        'Аня А.', 'PL-1', 'Minecraft', datetime.datetime(2026, 5, 1), 2000.0, 0.0, 500.0,
    ]
    assert first[7] == 500.0    # май
    assert first[8] is None     # июнь — признания не было
    assert first[9] == 500.0    # июль
    assert first[10:] == [1000.0, 0.0, 1000.0]

    second = [c.value for c in ws[3]]
    assert second[1] == '-'     # пустой platform_id
    assert second[5] == 400.0   # доплаты
    assert second[10:] == [600.0, 1800.0, 0.0]


def test_money_and_date_formats(tmp_path):
    out = tmp_path / 'ledger.xlsx'

    write_report_xlsx(_report(), out)

    ws = openpyxl.load_workbook(out).active
    assert ws.cell(row=2, column=4).number_format == 'DD.MM.YYYY'
    for col in (5, 6, 7, 8, 9, 10, 11, 12, 13):
        assert ws.cell(row=2, column=col).number_format == '#,##0.00'


def test_empty_report_renders_header_only(tmp_path):
    out = tmp_path / 'empty.xlsx'

    write_report_xlsx(LedgerReport(month='2026-07', months=['2026-07'], rows=[]), out)

    ws = openpyxl.load_workbook(out).active
    assert ws.max_row == 1
    assert [c.value for c in ws[1]][7] == 'Июль 2026'
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `cd journal_django && pytest apps/finances/tests/test_reports_xlsx.py -q`
Expected: FAIL — `ImportError: cannot import name 'LedgerReport'` либо старая шапка.

- [ ] **Step 3: Переписать рендер**

Заменить в `journal_django/apps/finances/reports.py` всё, начиная с `def _pair_cols` и до конца файла, на:

```python
_MONEY_FMT = '#,##0.00'
_DATE_FMT = 'DD.MM.YYYY'


def build_report_workbook(report: LedgerReport):
    """Собрать openpyxl.Workbook реестра (одна строка = один платёж), без сохранения.

    Общее ядро для write_report_xlsx (файл на диск, CLI-команда) и
    render_report_bytes (байты для раздела «Отчёты»)."""
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Реестр'

    headers = [
        'ФИО ученика', 'Platform ID', 'Направление оплаты', 'Дата оплаты',
        'Сумма платежа, ₽', 'Доплаты, ₽', 'Цена 1 урока, ₽',
    ]
    headers += [month_label(ym) for ym in report.months]
    headers += ['Выручка итого, ₽', 'Возвращено, ₽', 'Аванс, ₽']
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    months_base = 8                                   # 1-я колонка-месяц
    total_col = months_base + len(report.months)
    refunded_col = total_col + 1
    advance_col = refunded_col + 1

    for row in report.rows:
        values: list = [
            row.full_name, row.platform_id or '-', row.direction_name,
            datetime.date.fromisoformat(row.paid_at),
            float(row.total_amount), float(row.surcharge_amount), float(row.unit_price),
        ]
        # Месяц без признания — пустая ячейка (а не '-'): лист разреженный, а
        # SUM по колонке месяца должен читаться без правок.
        values += [
            float(row.revenue_by_month[ym]) if ym in row.revenue_by_month else None
            for ym in report.months
        ]
        values += [float(row.revenue_total), float(row.refunded), float(row.advance)]
        ws.append(values)

    money_cols = [5, 6, 7, total_col, refunded_col, advance_col]
    money_cols += list(range(months_base, months_base + len(report.months)))
    for excel_row in range(2, len(report.rows) + 2):
        ws.cell(row=excel_row, column=4).number_format = _DATE_FMT
        for col in money_cols:
            ws.cell(row=excel_row, column=col).number_format = _MONEY_FMT

    widths = {1: 32, 2: 14, 3: 22, 4: 13, 5: 16, 6: 12, 7: 15,
              total_col: 16, refunded_col: 14, advance_col: 14}
    for i in range(len(report.months)):
        widths[months_base + i] = 13
    for col_idx, width in widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.freeze_panes = 'A2'
    return wb


def write_report_xlsx(report: LedgerReport, path: str | Path) -> None:
    """Пишет реестр в один лист «Реестр» (файл на диск)."""
    wb = build_report_workbook(report)
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))


def render_report_bytes(report: LedgerReport) -> bytes:
    """Реестр как xlsx-байты (для раздела «Отчёты»)."""
    import io
    wb = build_report_workbook(report)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 4: Запустить тесты**

Run: `cd journal_django && pytest apps/finances/tests/test_reports_xlsx.py apps/finances/tests/test_reports.py -q`
Expected: PASS.

---

### Task 6: builder раздела «Отчёты» и CLI-команда

**Files:**
- Modify: `journal_django/apps/reports/builders/accounting.py`
- Modify: `journal_django/apps/finances/management/commands/export_accounting_report.py`
- Test: `journal_django/apps/reports/tests/test_accounting_report.py`
- Test: `journal_django/apps/finances/tests/test_export_accounting_report_command.py`

- [ ] **Step 1: Поправить тесты под новую шапку**

В `journal_django/apps/reports/tests/test_accounting_report.py` заменить тело `test_builder_returns_valid_workbook` на:

```python
def test_builder_returns_valid_workbook():
    content, count, filename = accounting.build('2026-07')
    assert filename == 'accounting_2026-07.xlsx'
    assert isinstance(count, int)
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(content)).active
    assert ws.title == 'Реестр'
    assert ws.cell(row=1, column=1).value == 'ФИО ученика'
    assert ws.cell(row=1, column=4).value == 'Дата оплаты'
```

В `journal_django/apps/finances/tests/test_export_accounting_report_command.py` заменить тело `test_command_writes_xlsx_with_student_row` на:

```python
def test_command_writes_xlsx_with_payment_row(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup, tmp_path,
):
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000, '2026-07-05')
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s,%s,'2026-07-10',1,60,'regular','test') RETURNING id",
            [group_fixture, teacher_id_fixture],
        )
        lid = cur.fetchone()[0]
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s,%s,true)',
            [lid, student_fixture],
        )
    graph_cleanup['lessons'].append(lid)
    out_path = tmp_path / 'out.xlsx'

    call_command('export_accounting_report', month='2026-07', out=str(out_path))

    assert out_path.exists()
    wb = openpyxl.load_workbook(out_path)
    ws = wb.active
    header = [c.value for c in ws[1]]
    assert header[:4] == ['ФИО ученика', 'Platform ID', 'Направление оплаты', 'Дата оплаты']
    names = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]
    assert '__fin_student__' in names
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `cd journal_django && pytest apps/reports/tests/test_accounting_report.py apps/finances/tests/test_export_accounting_report_command.py -q`
Expected: FAIL — builder падает на `len(rows)` / старой шапке.

- [ ] **Step 3: Обновить builder и команду**

Заменить содержимое `journal_django/apps/reports/builders/accounting.py` на:

```python
"""
Построитель «Бухгалтерского отчёта» (реестр признания выручки по платежам).

Тонкая обёртка над apps.finances.reports (та же логика, что у CLI-команды
export_accounting_report): собираем реестр по месяцу и отдаём xlsx-байты.
Правила half-lesson/FIFO не дублируются.
"""
from __future__ import annotations

from apps.finances.reports import collect_monthly_report, render_report_bytes


def build(month: str) -> tuple[bytes, int, str]:
    """(xlsx-байты, число строк-платежей, имя файла). month — 'YYYY-MM'."""
    report = collect_monthly_report(month)  # ValueError при кривом месяце → services пометит failure
    content = render_report_bytes(report)
    filename = f'accounting_{month}.xlsx'
    return content, len(report.rows), filename
```

В `journal_django/apps/finances/management/commands/export_accounting_report.py`:

1. Заменить docstring модуля на:

```python
"""
python manage.py export_accounting_report --month=2026-07 [--out=path.xlsx]

Реестр признания выручки по платежам за месяц: дата оплаты, цена 1 урока,
признанная выручка по месяцам, выручка итого, возвраты и остаток аванса.

См. docs/superpowers/specs/2026-09-08-accounting-payment-ledger-design.md
"""
```

2. `help` заменить на:

```python
    help = 'Реестр признания выручки по платежам за месяц в Excel.'
```

3. В `handle` заменить сборку и вывод:

```python
        try:
            report = collect_monthly_report(month)
        except ValueError:
            raise CommandError(f'Неверный формат месяца: "{month}". Ожидается YYYY-MM.')

        out = opts['out']
        out_path = Path(out) if out else Path(settings.BASE_DIR) / 'reports' / f'accounting_report_{month}.xlsx'

        write_report_xlsx(report, out_path)

        self.stdout.write(self.style.SUCCESS(
            f'Готово: {len(report.rows)} платежей, файл сохранён в {out_path}'
        ))
```

- [ ] **Step 4: Запустить тесты**

Run: `cd journal_django && pytest apps/reports/tests/test_accounting_report.py apps/finances/tests/test_export_accounting_report_command.py -q`
Expected: PASS.

---

### Task 7: зависимые тесты и описание карточки во фронте

**Files:**
- Modify: `journal_django/apps/extra_lessons/tests/test_reconciliation_1a.py:100-104,161-168`
- Modify: `journal_django/apps/payments/tests/test_surcharge.py:177-188`
- Modify: `journal_django/frontend/admin-src/src/lib/reports.ts:64-69`

- [ ] **Step 1: Переписать сверку в reconciliation-тесте**

В `journal_django/apps/extra_lessons/tests/test_reconciliation_1a.py` заменить хелпер:

```python
def _report_rows(month: str, student_id: int):
    """Строки реестра признания выручки по ученику (строка = платёж)."""
    return [r for r in collect_monthly_report(month).rows if r.student_id == student_id]
```

и блок «Помесячный отчёт за апрель» на:

```python
        # --- Реестр признания выручки за апрель (месяц проведения доп.урока) --
        rows = _report_rows('2026-04', student_fixture)
        assert len(rows) == 1                                    # одна оплата ученика
        row = rows[0]
        assert row.revenue_by_month['2026-04'] == Decimal('1000')  # 1 урок × 1000 ₽
        assert row.advance == Decimal('7000')                      # 7 × 1000 ₽
        assert row.total_amount + row.surcharge_amount == (
            row.revenue_total + row.refunded + row.advance
        )
```

- [ ] **Step 2: Переписать сверку доплаты**

В `journal_django/apps/payments/tests/test_surcharge.py` заменить тело
`test_surcharge_counts_in_month_cash` на:

```python
@pytest.mark.django_db
def test_surcharge_counts_in_month_cash(admin_client, parent_payment, student_fixture):
    """Доплата видна в строке своего родительского платежа — ради этого фича и делалась."""
    from apps.finances.reports import collect_monthly_report
    payload = _surcharge_payload(parent_payment)
    payload['student_id'] = student_fixture
    admin_client.post(BASE_URL, payload, format='json')

    rows = collect_monthly_report('2026-02').rows
    row = next((r for r in rows if r.payment_id == parent_payment), None)
    assert row is not None
    assert row.surcharge_amount == Decimal('1000')
```

Если `parent_payment` — не id, а объект/словарь, взять из него id (посмотреть
фикстуру в начале файла) и сравнить `row.payment_id` именно с ним. Если у
родительского платежа в этой фикстуре нет признанной выручки в 2026-02 (нет
проведённых уроков), тест должен вместо этого проверять отсутствие строки —
это ожидаемое поведение по §4.3 спеки; тогда переименовать тест в
`test_surcharge_is_folded_into_parent_payment_row` и проверять
`collect_monthly_report('2026-02').rows` на отсутствие строки самой доплаты:

```python
    surcharge_ids = {
        p.id for p in Payment.objects.filter(kind='surcharge', parent_payment_id=parent_payment)
    }
    assert not [r for r in rows if r.payment_id in surcharge_ids]
```

- [ ] **Step 3: Обновить описание карточки отчёта**

В `journal_django/frontend/admin-src/src/lib/reports.ts` заменить блок
`ACCOUNTING_MONTH` на:

```ts
  {
    reportType: ACCOUNTING_MONTH,
    title: 'Бухгалтерский отчёт',
    desc: 'Реестр поступлений: каждая оплата, признавшая выручку в выбранном месяце — '
      + 'дата платежа, цена 1 урока, признанная выручка по месяцам, выручка итого, '
      + 'возвраты и остаток аванса на конец месяца.',
    buildParams: (year, month) => ({ month: ym(year, month) }),
  },
```

- [ ] **Step 4: Запустить тесты**

Run: `cd journal_django && pytest apps/extra_lessons/tests/test_reconciliation_1a.py apps/payments/tests/test_surcharge.py -q`
Expected: PASS.

---

### Task 8: полная проверка

**Files:** нет правок кода (только фиксация результата)

- [ ] **Step 1: Полный прогон тестов**

Run: `cd journal_django && pytest -q`
Expected: PASS, ноль падений. Частичный прогон по приложениям недопустим —
часть приложений no-op'ит `django_db_setup`, часть пересоздаёт тестовую БД.

- [ ] **Step 2: Прогон на реальных данных (dev-БД)**

Run: `cd journal_django && python manage.py export_accounting_report --month=2026-07 --out=%TEMP%\ledger_2026-07.xlsx`
Expected: `Готово: N платежей, файл сохранён в ...` с N > 0.

- [ ] **Step 3: Сверка инварианта на боевых строках**

Run:

```bash
cd journal_django && python -c "
from decimal import Decimal
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
django.setup()
from apps.finances.reports import collect_monthly_report
rep = collect_monthly_report('2026-07')
bad = [r.payment_id for r in rep.rows
       if r.total_amount + r.surcharge_amount != r.revenue_total + r.refunded + r.advance]
print('строк:', len(rep.rows), 'месяцев:', len(rep.months), 'не сошлось:', bad)
"
```

Expected: `не сошлось: []`.

- [ ] **Step 4: Собрать фронт**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: сборка без ошибок (меняется только текст описания карточки).

---

## Self-Review

**Покрытие спеки:**

| Раздел спеки | Задача |
|---|---|
| §3 структура листа, порядок колонок, сортировка | Task 5 (рендер), Task 4 (сортировка) |
| §3 инвариант сходимости | Task 4 (`test_every_row_reconciles`), Task 7 |
| §4.1 разрезы по платежу | Task 2, Task 3 |
| §4.2 as-of на конец месяца | Task 4 (`test_advance_is_as_of_end_of_month`) |
| §4.3 отбор строк, доплаты/возвраты/extra | Task 4 (4 отдельных теста) |
| §4.4 округление и невязка | Task 4 (`_round_by_month`, тест на ≤1 коп) |
| §5 границы правки | Task 1–7 (все шесть файлов) |
| §6 производительность | Task 4 (один `fifo_inputs`, три запроса метаданных) |
| §7 тесты | Task 3–7 + полный прогон в Task 8 |

**Согласованность имён:** `PaymentLedgerRow` / `LedgerReport` /
`collect_monthly_report` / `build_report_workbook` / `write_report_xlsx` /
`render_report_bytes` / `NO_DIRECTION` — используются одинаково в Task 4, 5, 6, 7.
Ключи FIFO — `worked_off_by_month_payment`, `remaining_by_payment`,
`refunded_by_payment` — одинаковы в Task 3 и Task 4.
