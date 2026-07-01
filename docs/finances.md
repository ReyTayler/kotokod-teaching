# Финансы: Payments, Discounts, FIFO

## Payments — правила immutability

- **Только POST/DELETE**, никакого PATCH. Опечатка → DELETE + POST.
- `total_amount = unit_price × subscriptions_count` — CHECK в БД + пересчёт на сервере.
- `unit_price` округляется до копеек (`Math.round(p*100)/100`) ДО умножения — защита от floating-point CHECK violation.
- **Cap-валидация в транзакции** с `SELECT directions FOR UPDATE`: `(SUM(subscriptions_count) + new) × 4 ≤ direction.total_lessons` → иначе 400 `cap_exceeded`. Race-safe.
- **ON DELETE RESTRICT** на FK payments→students/directions: нельзя удалить сущность с финансовой историей.
- `paid_at` — date (не timestamptz), нас интересует день.
- **Legacy payments** (миграция 009): direction_id и subscriptions_count могут быть NULL — для backfill истории.

## Half-lesson

`lesson_duration_minutes = 45 → 0.5 урока`, иначе 1.  
Используется в `repo/lessons.js`, `repo/payments.js` (формула баланса), `teacher-repo.js` (incrementCounters).

## Баланс студента

`getStudentBalance(student_id)` = `purchased - attended` per direction. Выводится, не хранится. Toggle attendance автоматически меняет баланс.

## Discounts

- Применяются **только при `subscriptions_count=1`** (правило бизнеса).
- Несколько скидок суммируются additively: `final_price = base × (1 − Σamounts)`, cap at 0.
- Применяются к base ИЛИ custom price.
- **Note auto-prefix**: фронт добавляет «Скидки: X (−N%), Y (−M%)\n<комментарий>».

## FIFO-финансы (Dashboard)

Источник истины: `services/fifo.js` → `computeFifo`.

**Принцип**: уроки списываются FIFO по партиям-оплатам (старые первыми). Цена урока = `payments.total_amount / (subscriptions_count × 4)` конкретной оплаты (НЕ `subscription_price/4`). Без усреднений.

**Два типа метрик**:
- **Потоки** (revenue/worked_off/carryover) — считаются за период `?from=&to=` (пусто = текущий МСК-месяц).
- **Снимок** (deferred_total/debts) — всегда «сейчас», от периода не зависит.

**Guard**: оплаты с `direction_id IS NOT NULL` но `subscriptions_count NULL/0` пропускаются (`lessons > 0`) — иначе деление на 0 → `Infinity` ломает все суммы.

**Реализация**: `getDashboard()` / `getMonthlyFinance()` через общий `_fifoInputs()` тянут все партии + посещения, считают в JS.

`worked_off` в monthly — FIFO по месяцу урока (`computeFifo.worked_off_by_month`, один проход на все года).

Входы (`from`/`to`/`year`) валидируются, SQL параметризован.

Спека: `docs/superpowers/specs/2026-06-03-admin-dashboard-design.md`
