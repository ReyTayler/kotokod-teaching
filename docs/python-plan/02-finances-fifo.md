# 02 — FIFO + balance (`apps/finances` — вычислительный слой, БЕЗ моделей/URL)

**Агенты:** `voltagent-lang:sql-pro` (запросы) + `voltagent-lang:django-developer` (Python-логика)
+ `voltagent-qa-sec:security-auditor` и `code-reviewer` (округления/Decimal).
**Источник (Node):** `services/fifo.js` (`computeFifo`), `services/repo/payments.js` (`getStudentBalance`).
**Зависит от:** payments, lessons, memberships.

> Это **чистый вычислительный слой**: модулей моделей и urls нет. Его используют payments, payroll, dashboard.
> Сейчас частичный расчёт баланса живёт внутри `apps/payments/repository.py` — **свести к единому `finances/`**,
> чтобы все потребители использовали один FIFO.

## `finances/fifo.py` — порт `computeFifo`

Дословный порт на **Decimal**:
- `Decimal(str(x))` на входах, `ROUND_HALF_UP`, квант `Decimal('0.01')`.
- Цена урока партии = `total_amount / (subscriptions_count × 4)`.
- **Guard**: оплаты с `subscriptions_count` NULL/0 — пропускать (иначе Infinity ломает суммы).
- Сортировки: оплаты по дате оплаты (paid_at), посещения по lesson_date.
- Строгий FIFO: старая партия гасится первой.
- Выход: `worked_off_total`, `worked_off_month`, `remaining_value`, `over_consumed_lessons`,
  `worked_off_by_month: {YYYY-MM: value}`. Границы месяца — МСК (учесть переход Dec→Jan).

## `finances/balance.py` — баланс выводится, не хранится

- `purchased − attended` per direction; half-lesson (45 мин) считается как 0.5 в SUM посещений.
- Возврат per_direction[] + total. Числа как int/float по контракту Express; unit_price/total_amount — Decimal→строка.

## Критичное

- **Бухгалтерская точность**: только Decimal, никаких усреднений, FIFO по фактической цене партии
  (см. память `feedback_financial_accounting_precision`).
- Полная сверка с Express: значения должны совпадать **до копейки**.

## Verification (максимум внимания)

- **golden-fixtures**: снять эталонные ответы Express на реальных данных ДО переноса, сверять Decimal-в-Decimal.
- Граничные случаи: half-lesson; over-consumed (долг); `subscriptions_count` NULL/0; переход месяца Dec→Jan по МСК;
  несколько партий-оплат разной цены; частичное гашение партии.
