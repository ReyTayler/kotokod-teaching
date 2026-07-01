# Subscriptions & Payments — Design

**Date:** 2026-06-01
**Status:** Draft — awaiting user review
**Scope:** Admin SPA, в продолжение R2. Финансовый учёт оплат и абонементов.

## Цель

Дать управляющему возможность вносить оплаты учеников за абонементы (4 урока на направлении), отслеживать баланс оплаченных уроков и видеть выручку. Расчёты должны быть точными — на их основе строится месячная выручка.

## Бизнес-модель

- **Абонемент** = 4 урока на конкретное направление.
- Каждое направление имеет свою цену абонемента (RUB).
- Ученик покупает N абонементов за одну транзакцию (оплату).
- Купленные уроки «сгорают» при посещении (`present=true`). Половинный урок (`lesson_duration_minutes=45`) тратит 0.5, полный — 1.
- Прогулы (`present=false`) не уменьшают баланс.
- Цена в оплате может быть кастомной — снимок на момент покупки, не влияет на дефолт направления.

## Архитектура

### Принципы

- **Payments immutable по содержимому.** Создаём через POST, удаляем через DELETE. PATCH нет — исправление через delete+create.
- **Баланс — производное.** Никакой mutable-таблицы «остаток». Считается всегда из `payments` и `lesson_attendance`.
- **`unit_price` — snapshot.** Изменение цены направления не задним числом.
- **Cap по ёмкости курса** (`directions.total_lessons`), валидируется на бэке.
- **`total_amount` пересчитывается на сервере** перед INSERT, фронту не доверяем.

### Схема БД

Две миграции, без изменений в существующих таблицах:

```sql
-- 007_directions_subscription_price.sql
ALTER TABLE directions
  ADD COLUMN subscription_price numeric(10,2) CHECK (subscription_price >= 0);
-- NULL = «абонемент не настроен» → форма открывается с кастомной ценой,
--        но продажа не блокируется.

-- 008_payments.sql
CREATE TABLE payments (
  id                   serial PRIMARY KEY,
  student_id           integer NOT NULL REFERENCES students(id)   ON DELETE RESTRICT,
  direction_id         integer NOT NULL REFERENCES directions(id) ON DELETE RESTRICT,
  subscriptions_count  integer NOT NULL CHECK (subscriptions_count > 0),
  unit_price           numeric(10,2) NOT NULL CHECK (unit_price >= 0),
  total_amount         numeric(10,2) NOT NULL,
  paid_at              date    NOT NULL,
  note                 text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  created_by           text,
  CHECK (total_amount = unit_price * subscriptions_count)
);
CREATE INDEX idx_payments_student   ON payments(student_id);
CREATE INDEX idx_payments_direction ON payments(direction_id);
CREATE INDEX idx_payments_paid_at   ON payments(paid_at);
```

**Почему такие решения:**

- `paid_at = date`, не `timestamptz` — для месячных отчётов важна только дата. `pg` type-parser 1082 уже возвращает сырую `YYYY-MM-DD`.
- `ON DELETE RESTRICT` — защита от случайной потери финансовой истории при удалении ученика/направления. Soft-delete (`active=false`, `enrollment_status`) этим не блокируется.
- `created_by` — текст из `req.admin.user`, не FK. По аналогии с `lessons.submitted_by_token`.
- `unit_price` обязателен, `subscription_price` направления может быть NULL — снимок всё равно фиксируется per-payment.

### Формула баланса (выводится на лету)

Per `(student_id, direction_id)`:

```sql
balance =
   COALESCE((
     SELECT SUM(p.subscriptions_count * 4)
     FROM   payments p
     WHERE  p.student_id = $1 AND p.direction_id = $2
   ), 0)
 −
   COALESCE((
     SELECT SUM(CASE WHEN l.lesson_duration_minutes = 45 THEN 0.5 ELSE 1 END)
     FROM   lesson_attendance la
     JOIN   lessons l ON l.id = la.lesson_id
     JOIN   groups  g ON g.id = l.group_id
     WHERE  la.student_id = $1
       AND  la.present    = true
       AND  g.direction_id = $2
   ), 0);
```

**Следствия derived-модели:**

- Тоггл `present` true→false → урок «возвращается» автоматически.
- Удаление урока → каскадное удаление attendance → баланс восстанавливается.
- Перевод группы на другое направление → все её прошлые уроки задним числом считаются за новое направление. Базовая модель курса, побочный эффект логичен.

## API

Новый router `routes/admin/payments.js` + расширение `routes/admin/directions.js`. Все под `requireAdmin`.

### Directions (расширение)

```
GET  /api/admin/directions
PUT  /api/admin/directions/:id
```

В ответ и в `req.validated` добавляется `subscription_price: number | null`.

### Payments

```
GET    /api/admin/payments
       query: ?student_id= &direction_id= &from=YYYY-MM-DD &to=YYYY-MM-DD
       Сортировка: paid_at DESC, id DESC.

POST   /api/admin/payments
       body: {
         student_id:          number,
         direction_id:        number,
         subscriptions_count: number ≥ 1,
         unit_price:          number ≥ 0,
         paid_at:             date,
         note?:               string
       }
       Сервер:
         1. total_amount = unit_price × subscriptions_count.
         2. Проверка: direction.total_lessons > 0 → иначе 400 "no_capacity".
         3. Проверка: SUM(subscriptions_count для этого студент×направление) + новое
            ≤ direction.total_lessons / 4 → иначе 400 "cap_exceeded".
         4. created_by = req.admin.user.
       Ответ: созданная строка payments.

DELETE /api/admin/payments/:id
       Хард-удаление.
       Ответ:
         { deleted: true, warning?: "balance_negative", new_balance?: -3 }
       Если после удаления баланс по (student, direction) < 0 — добавляем warning.

GET    /api/admin/students/:id/balance
       Ответ:
       {
         per_direction: [
           { direction_id, direction_name,
             purchased_lessons, attended_lessons, balance,
             total_paid_amount }
         ],
         total_balance,         // сумма balance по всем направлениям
         total_paid_amount,     // сумма total_amount по всем оплатам
         payments: [ ...payments ]
       }
```

### Zod-схемы (`shared/schemas.js`)

```js
const paymentCreateSchema = z.object({
  student_id:          z.coerce.number().int().positive(),
  direction_id:        z.coerce.number().int().positive(),
  subscriptions_count: z.coerce.number().int().min(1),
  unit_price:          z.coerce.number().min(0),
  paid_at:             z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  note:                z.string().max(500).optional().nullable(),
});

const directionUpdateSchema = (existing).extend({
  subscription_price: z.coerce.number().min(0).nullable().optional(),
});
```

`total_amount` НЕ принимается — пересчитывается на сервере.

## UI

### Sidebar (`components/shell/Sidebar.tsx`)

Две новые записи после «Уроки»:

```
🧾 Абонементы          → /admin/subscriptions
💰 Внести оплату       → открывает <PaymentModal />, не меняет роут
```

«Внести оплату» — глобальная кнопка, открывает модалку поверх любой страницы. State `isPaymentModalOpen` в `AppShell`. Если открыт со страницы ученика — student-id предзаполнен.

### Страница «Абонементы» (`/admin/subscriptions`)

`pages/subscriptions/SubscriptionsPage.tsx`. Таблица направлений с inline-редактированием цены:

| Направление | Цена за абонемент | Уроков в курсе | Цена за урок | Всего оплат |
|---|---|---|---|---|
| Программирование | 7 250 ₽ ✏️ | 32 (8 абон.) | 1 812,50 ₽ | 12 |

- Inline-edit через клик по `subscription_price` → input → blur/Enter сохраняет.
- «Цена за урок» = `subscription_price / 4`, информационно.
- «Всего оплат» = `COUNT(*) FROM payments WHERE direction_id = ...`.
- Направление без `subscription_price` → пометка «не настроено», цена пустая.
- Направление без `total_lessons` → пометка «не задан курс».

### Модалка «Внести оплату» (`pages/payments/PaymentModal.tsx`)

Поля сверху вниз:

1. **Ученик** — `SelectInput` с поиском по имени. Показываем всех (включая frozen/not_enrolled/declined), не-enrolled — серым с пометкой.
2. **Направление** — список направлений с `total_lessons > 0`.
3. **Подсказка** — «Уже куплено: 5 абонементов (20 уроков), осталось 12 из 32 (3 абонемента)». Реалтайм по выбранному студенту+направлению.
4. **Блок-селектор** — N коробок по 4 квадратика, N = `total_lessons / 4`:
   - Закрашены (цвет направления, иконка ✕): `ceil(уже_купленные_абонементы)` штук.
   - Свободные: контур, кликабельные.
   - Клик по свободному блоку → выбираем все блоки от первого свободного до этого включительно. Hover показывает диапазон.
   - Повторный клик по выбранному → откатывает до предыдущего.
   - Под блоками подпись «3 ранее, 2 выбрано, 3 свободно».
5. **Дата оплаты** — `DateInput`, default = сегодня в MSK.
6. **Цена**:
   - По умолчанию `direction.subscription_price`.
   - Кнопка «+ Задать свою сумму за абонемент» раскрывает `NumberInput`.
   - При раскрытом → кнопка «× Вернуть базовую цену».
   - Если `subscription_price = NULL` → форма стартует с раскрытым полем + предупреждение «цена не задана».
7. **Итого** — `subscriptions_count × unit_price`, реалтайм.
8. **Комментарий** — `Textarea`, optional.
9. **Submit** «Внести оплату» / «Отмена».

**Валидация (фронт):**
- Все обязательные поля заполнены.
- `subscriptions_count ≥ 1`.
- `(уже + новое) × 4 ≤ total_lessons` — иначе блок submit.
- Если direction без `total_lessons` или `total_lessons=0` → форма disabled, ссылка «настройте курс в разделе Направления».

**После submit:**
- `POST /api/admin/payments`.
- Invalidate: `useStudentBalance(student_id)`, `usePayments({student_id})`, `useDirections()` (счётчик).
- Toast «Оплата внесена: 14 500 ₽».

`PaymentModal` принимает props:
```ts
{ studentId?: number; directionId?: number; onClose: () => void }
```

### Блок «Баланс» в карточке ученика (`pages/students/StudentBalanceBlock.tsx`)

Размещение: после `StudentStatsBlock`, перед `MembershipsBlock`.

```
┌─ Баланс ──────────────────────────────────┐
│ Оплачено всего: 36 250 ₽                  │
│ Осталось оплаченных уроков: 12            │
│                                           │
│ Программирование     7 уроков    14 500 ₽│
│ Дизайн               5 уроков    21 750 ₽│
│                                           │
│ История оплат                             │
│ 2026-05-15 · Программирование · 2 аб.    │
│            · 7 250 ₽/аб = 14 500 ₽   🗑 │
│ 2026-04-10 · Дизайн · 3 аб.               │
│            · 7 250 ₽/аб = 21 750 ₽   🗑 │
│                                           │
│ [+ Внести оплату]                         │
└───────────────────────────────────────────┘
```

- Per-direction строка только если есть payment или attended-lessons по этому направлению.
- Отрицательный баланс рисуется красным (долг).
- Корзинка → confirm-диалог. Если ответ POST содержит `warning: "balance_negative"` — дополнительный toast «Баланс по направлению X стал −3 урока».
- Кнопка «+ Внести оплату» открывает `PaymentModal` с предзаполненным `studentId`.
- Блок не рендерится, если 0 payments и 0 attended.

### Файловая структура

```
db/migrations/
  007_directions_subscription_price.sql   NEW
  008_payments.sql                        NEW
routes/admin/
  payments.js                             NEW
  directions.js                           EDIT — subscription_price
  index.js                                EDIT — mount payments
services/
  admin-repo.js                           EDIT — createPayment, deletePayment,
                                                 listPayments, getStudentBalance,
                                                 setDirectionSubscriptionPrice
shared/schemas.js                         EDIT — paymentCreateSchema,
                                                 directionSchema.subscription_price
web/admin/src/
  hooks/
    usePayments.ts                        NEW
    useStudentBalance.ts                  NEW
    useDirections.ts                      EDIT — subscription_price mutation
  pages/
    payments/
      PaymentModal.tsx                    NEW
      BlockSelector.tsx                   NEW
    subscriptions/
      SubscriptionsPage.tsx               NEW
    students/
      StudentBalanceBlock.tsx             NEW
      StudentDetailPage.tsx               EDIT — mount balance block
  components/shell/
    Sidebar.tsx                           EDIT — две новые записи
    AppShell.tsx                          EDIT — state модалки + рендер
  lib/types.ts                            EDIT — Payment, DirectionWithPrice, Balance
  lib/format.ts                           EDIT — fmtRub
  App.tsx                                 EDIT — route /admin/subscriptions
  style.css                               EDIT — стили блок-селектора и баланс-блока
```

## Edge cases

| Кейс | Поведение |
|---|---|
| `direction.subscription_price IS NULL` | Форма открывается с custom-полем, продажа разрешена. |
| `direction.total_lessons IS NULL/0` | Продажа блокирована (фронт + бэк 400). |
| Cap превышен | Бэк 400 `cap_exceeded`, фронт блокирует submit + красная подпись. |
| Удаление payment с уже отработанными уроками | 200 + `warning: "balance_negative"`. |
| Hard-delete student/direction с payments | DB 23503 (FK) → бэк перебрасывает в 409 «есть финансовые записи». |
| Перевод группы на другое направление | Списания задним числом перенесены в новое направление. Документировано. |
| Тоггл `present` true→false | Балансы пересчитываются автоматически. |
| Удаление урока | Каскадно уходят attendance → баланс восстанавливается. |
| Дублирующая оплата (та же дата/направление/кол-во) | Разрешена. Не уникальность. |
| Half-lesson detection | `lesson_duration_minutes = 45` → 0.5, иначе 1. Regex по имени группы НЕ используется. |
| Ученик с активной заморозкой | Оплачивать можно — это предоплата на будущее. |
| Custom price = 0 | Разрешено (подарочный абонемент). |
| `paid_at` в будущем | Разрешено (предоплата с фиксированной датой). Не блокируем. |
| `paid_at` сильно в прошлом | Разрешено. Аудит через `created_at`. |

## Что НЕ делаем в v1

- Revenue report (`/api/admin/revenue?month=...`). Схема поддерживает, эндпоинт следующей итерацией.
- Связь оплаты с конкретной группой. Только направление.
- Скидки/промокоды как отдельная сущность. Реализуются через custom unit_price.
- Audit log изменений payments. `created_at` + `created_by` достаточно.
- Bulk payments (несколько направлений за раз).
- Алерты «баланс на нуле / в минусе» в Sidebar.
- Восстановление удалённой оплаты.

## Открытые вопросы

Нет. Все развилки закрыты в брейнсторме 2026-06-01.

## Связанное

- CLAUDE.md — Sheets-инварианты не применимы (новая фича не касается teacher SPA).
- `services/admin-repo.js:442` — конвенция `lesson_duration_minutes = 45 → step 0.5` уже используется в payroll. Переиспользуем.
- Phase 5 (cleanup Sheets) — не блокирует эту фичу. Можно делать параллельно или сначала.
