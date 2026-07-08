# Общий пул баланса ученика (отвязка списания от направления) — Design

**Date:** 2026-07-08
**Status:** Draft — approved by user in brейнсторме, готов план
**Scope:** `apps/finances`, `apps/payments`, `apps/dashboard` (backend) + `StudentBalanceBlock`, `DebtsCard`, `useStudentBalance` (admin SPA frontend).

## Проблема

При переносе исторических данных оплат/посещений обнаружилось много кейсов: ученик вносил оплату за направление A, в какой-то момент прекращал заниматься на A и переходил на B — и оплата с A фактически применялась на B. Текущая модель ([2026-06-01-subscriptions-payments-design.md](2026-06-01-subscriptions-payments-design.md)) считает баланс **строго по `(student_id, direction_id)`**: FIFO-партии и посещения группируются раздельно по направлению, остаток по старому направлению не переносится на новое автоматически, и остаётся «зависшим» — не сгорает, но и не может быть потрачен.

Рассматривался вариант с ручным «переносом остатка» между направлениями (отдельная сущность/операция), но это не решает проблему системно — таких переходов много, и они должны обрабатываться сами, без ручного вмешательства администратора на каждый случай.

## Решение

Меняем бизнес-правило: **оплата привязывается к направлению только как информационная пометка (тег)**, а не как жёсткий скоуп для списания. Списание уроков идёт **одним общим FIFO-пулом на ученика**, независимо от того, на каком направлении сделана оплата и на каком направлении посещён урок.

Следствие: старая проблема «зависшего остатка» исчезает архитектурно — деньги, помеченные направлением A, автоматически спишутся уроками на направлении B, если это следующий по очереди (FIFO по дате оплаты) непотраченный лот. Ручной перенос остатка не нужен.

## Что не меняется

- **Схема БД не меняется.** `payments.direction_id` остаётся NOT NULL (кроме легаси), миграций не требуется — меняется только код агрегации/чтения.
- **`cap_exceeded`-валидация** ([apps/payments/repository.py:61-82](../../../journal_django/apps/payments/repository.py#L61-L82)) — без изменений: ограничивает суммарное количество купленных абонементов **с тегом направления X** вместимостью курса X (`direction.total_lessons`). Это про продажу, не про списание.
- **Подсказка «уже куплено / осталось» в `PaymentModal`** — без изменений, использует ту же по-тегу сумму `subscriptions_count`.
- **Страница «Абонементы»** (`subscription_price` по направлениям) — без изменений.
- **`pghistory`/changelog** — не затрагиваются, таблица `payments` не меняется.

## Изменения в бэкенде

### `apps/finances/repository.py::fifo_inputs()`

Ключ партий и посещений меняется с `f"{student_id}:{direction_id}"` на `student_id`:
- `lots_by_key`/`purchased_by_key` — партии (`Payment`) сортируются по `paid_at` глобально по всем направлениям одного ученика. `direction_id` оплаты в группировку не входит, из выборки не убирается (нужен дальше для «оплачено по направлениям»).
- `cons_by_key`/`consumed_by_key` — посещения (`LessonAttendance`) сортируются по `lesson_date` глобально. Каждая запись потребления получает атрибут `direction_id` **направления урока** (`lesson.group.direction_id`) — используется только для атрибуции в отчётах, не для партиционирования FIFO.

### `apps/finances/fifo.py::compute_fifo()`

Сам алгоритм FIFO (старые партии гасятся первыми) не меняется. Добавляется новый вход/выход:
- `consumptions[i]` дополнительно содержит `direction_id` (направление урока).
- Возврат дополняется `worked_off_by_direction: {direction_id: Decimal}` — сумма стоимости потреблённых уроков, накапливаемая по направлению урока, симметрично существующему `worked_off_by_month`.

### `apps/finances/repository.py::balance_for_direction()` → `balance_for_student()`

Убирается параметр `direction_id`. Баланс = `SUM(subscriptions_count × 4) − SUM(attended units)`, оба агрегата — по всему ученику, без фильтра по направлению.

### `apps/finances/repository.py::student_balance_rows()` → перестройка

Вместо одного списка «баланс по направлению» — три независимых агрегата:
1. **Общий баланс**: `total_balance = total_purchased − total_attended` (глобально).
2. **`paid_by_direction`**: `SUM(total_amount)` и `SUM(subscriptions_count × 4)` сгруппировано по **тегу оплаты** (`payments.direction_id`) — информационно, не баланс.
3. **`attended_by_direction`**: `SUM(attended units)` сгруппировано по **направлению урока** (`lesson.group.direction_id`) — информационно, не баланс.

### `GET /api/students/:id/balance` — новая форма ответа

```json
{
  "total_balance": 12,
  "total_paid_amount": 36250,
  "paid_by_direction": [
    { "direction_id": 1, "direction_name": "Программирование", "direction_color": "#4F59F9", "total_paid_amount": 14500 }
  ],
  "attended_by_direction": [
    { "direction_id": 1, "direction_name": "Программирование", "direction_color": "#4F59F9", "attended_lessons": 7 }
  ],
  "payments": [ /* без изменений, каждая строка со своим тегом direction_name */ ]
}
```

Поле `per_direction` (со смешанными `balance`/`total_paid_amount`) удаляется.

### `apps/dashboard/services.py::get_dashboard()`

Список долгов (`debts`) считается по `student_id`, без `direction_id`/`direction_name`/`direction_color`. Один должник = одна строка с общим балансом.
`worked_off_month`/`deferred_total` — формула сумм по `keys` не меняется, меняется только состав `keys` (per-student вместо per-(student,direction)); итоговые числа при этом изменятся из-за смены порядка FIFO-погашения (ожидаемо и корректно — это и есть цель рефакторинга).

### `apps/dashboard/services.py::get_monthly_finance()`

Без изменений в API — `worked_off` по месяцам уже был агрегирован без разбивки по направлению. Новый `worked_off_by_direction` из `compute_fifo` в этот эндпоинт не выводится (не запрашивалось).

## Изменения во фронтенде

### `hooks/useStudentBalance.ts` + `lib/types.ts`

Тип `Balance`: `per_direction` → `paid_by_direction` + `attended_by_direction` (оба — информационные массивы без `balance`), `total_balance`/`total_paid_amount` — без изменений.

### `pages/students/StudentBalanceBlock.tsx`

- Общий баланс (как сейчас) — «Оплачено всего» + «Осталось оплаченных уроков» (одно число, без направления).
- Два новых **сворачиваемых** блока (тот же паттерн chevron+toggle, что уже есть у «История оплат», по умолчанию свёрнуты):
  - «Оплачено по направлениям» — строки `direction_name` + `total_paid_amount` (₽).
  - «Отработано по направлениям» — строки `direction_name` + `attended_lessons` (уроков).
- Оба блока рендерятся только если соответствующий массив непуст.
- История оплат — без изменений (уже показывает тег направления на каждой строке).

### `pages/dashboard/DebtsCard.tsx`

Убираются `direction_name`/`direction_color`, `key={d.student_id}` вместо `${student_id}:${direction_id}`, колонка с направлением из строки списка убирается.

## Тесты к переписыванию

- `apps/finances/tests/test_fifo.py` — добавить кейсы на `worked_off_by_direction`.
- `apps/finances/tests/test_fifo_inputs.py` — ключи `student_id` вместо `student_id:direction_id`, `direction_id` внутри consumption-записей.
- `apps/finances/tests/test_finances_orm_smoke.py` — под новую агрегацию.
- `apps/payments/tests/test_payments_repository.py`, `test_payments_api.py` — новая форма `GET /balance`.
- `apps/dashboard` тесты (если есть) — `debts` без `direction_id`.
- Frontend: типы, `useStudentBalance` — при наличии тестов на компонент.

## Явно не делаем

- Не мигрируем и не правим исторические данные — баланс выводится, смена формулы применяется мгновенно.
- Не добавляем `worked_off_by_direction` в `get_monthly_finance` API — только внутренний выход `compute_fifo`, наружу пока не нужен.
- Не строим отдельную сущность/операцию «перенос остатка между направлениями» — проблема решается архитектурно.
