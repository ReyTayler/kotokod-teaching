# Subscriptions & Payments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Финансовый учёт абонементов (4 урока/направление) и оплат с per-direction балансом ученика, выводимым на лету из payments + lesson_attendance.

**Architecture:** Две новые таблицы в PG (subscription_price на directions; payments — immutable). Баланс не хранится — выводится SQL-формулой. Frontend: страница «Абонементы» (CRUD цены направления), модалка «Внести оплату» с блок-селектором, блок «Баланс» в карточке ученика. Точность финансовых расчётов гарантируется CHECK-constraint'ами в БД и пересчётом `total_amount` на сервере.

**Tech Stack:** Node.js / Express / PostgreSQL (pg, no ORM); React 19 + TanStack Query v5 + Radix Dialog + Vite + TypeScript; Zod v4 для валидации.

**Project memory note:**
- Git в проекте не используется → шагов «commit» в плане НЕТ. После каждого этапа — ручная проверка/тесты.
- Тесты бэка: `node --test`. Файлы `services/*.test.js`. Шаблон — `services/admin-repo.test.js`.
- Фронт тестов нет; верификация через `npm run admin:typecheck` + `npm run admin:build` + ручной smoke-test в браузере.

**Спецификация:** `docs/superpowers/specs/2026-06-01-subscriptions-payments-design.md`

---

## File Structure

### Создаются

```
db/migrations/007_directions_subscription_price.sql
db/migrations/008_payments.sql
routes/admin/payments.js
web/admin/src/hooks/usePayments.ts
web/admin/src/hooks/useStudentBalance.ts
web/admin/src/pages/payments/BlockSelector.tsx
web/admin/src/pages/payments/PaymentModal.tsx
web/admin/src/pages/subscriptions/SubscriptionsPage.tsx
web/admin/src/pages/students/StudentBalanceBlock.tsx
web/admin/src/providers/PaymentModalProvider.tsx
```

### Модифицируются

```
shared/schemas.js                                # paymentCreateSchema, directionSchema.subscription_price
shared/types.ts                                  # Payment, Balance, Direction.subscription_price
services/admin-repo.js                           # subscription_price в directions CRUD; payments CRUD; getStudentBalance
services/admin-repo.test.js                      # тесты на новые функции
routes/admin/directions.js                       # subscription_price проходит через PATCH
routes/admin/students.js                         # GET /:id/balance
routes/admin/index.js                            # mount /payments router
web/admin/src/lib/format.ts                      # fmtRub helper
web/admin/src/components/shell/Sidebar.tsx       # запись «Абонементы» + кнопка «Внести оплату»
web/admin/src/components/shell/AppShell.tsx      # обёртка PaymentModalProvider
web/admin/src/pages/students/StudentDetailPage.tsx  # монтаж StudentBalanceBlock + кнопка «Внести оплату»
web/admin/src/pages/directions/DirectionFormModal.tsx  # поле subscription_price
web/admin/src/App.tsx                            # route /admin/subscriptions
web/admin/src/style.css                          # стили блок-селектора, баланс-блока, страницы абонементов
```

---

## Task 1: Миграция 007 — поле subscription_price на directions

**Files:**
- Create: `db/migrations/007_directions_subscription_price.sql`

- [ ] **Step 1: Создать SQL-файл миграции**

```sql
-- 007_directions_subscription_price.sql
-- Цена одного абонемента (4 урока) на направление.
-- NULL = «не настроено» — продажу не блокируем, но форма открывается
-- с раскрытым полем «своя сумма».

BEGIN;

ALTER TABLE directions
  ADD COLUMN subscription_price numeric(10,2)
  CHECK (subscription_price IS NULL OR subscription_price >= 0);

COMMIT;
```

- [ ] **Step 2: Применить миграцию**

Run: `npm run db:migrate`
Expected: `applied: 007_directions_subscription_price.sql` в выводе. Если уже применена — `nothing to apply`.

- [ ] **Step 3: Проверить колонку**

Run: `psql -U journal -h localhost -d journal -c "\d directions"`
Expected: строка `subscription_price | numeric(10,2)` присутствует, дефолт null.

---

## Task 2: Миграция 008 — таблица payments

**Files:**
- Create: `db/migrations/008_payments.sql`

- [ ] **Step 1: Создать SQL-файл миграции**

```sql
-- 008_payments.sql
-- Финансовые записи оплат. Immutable по содержимому (никакого UPDATE из бэка).
-- total_amount пересчитывается на сервере и закрепляется CHECK'ом.
-- ON DELETE RESTRICT защищает от хард-удаления student/direction с историей оплат.

BEGIN;

CREATE TABLE payments (
  id                   serial PRIMARY KEY,
  student_id           int NOT NULL REFERENCES students(id)   ON DELETE RESTRICT,
  direction_id         int NOT NULL REFERENCES directions(id) ON DELETE RESTRICT,
  subscriptions_count  int NOT NULL CHECK (subscriptions_count > 0),
  unit_price           numeric(10,2) NOT NULL CHECK (unit_price >= 0),
  total_amount         numeric(10,2) NOT NULL,
  paid_at              date NOT NULL,
  note                 text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  created_by           text,
  CHECK (total_amount = unit_price * subscriptions_count)
);

CREATE INDEX payments_student_idx   ON payments(student_id);
CREATE INDEX payments_direction_idx ON payments(direction_id);
CREATE INDEX payments_paid_at_idx   ON payments(paid_at);

COMMIT;
```

- [ ] **Step 2: Применить миграцию**

Run: `npm run db:migrate`
Expected: `applied: 008_payments.sql`.

- [ ] **Step 3: Проверить таблицу**

Run: `psql -U journal -h localhost -d journal -c "\d payments"`
Expected: все 10 колонок, 3 индекса, 2 FK с RESTRICT, 3 CHECK'а.

- [ ] **Step 4: Дополнить scripts/db-truncate.js**

Open `scripts/db-truncate.js` и в массив `TABLES` добавить `'payments'` сразу после `'payroll'`:

```js
const TABLES = [
  'payments',          // ← новый
  'payroll',
  'lesson_attendance',
  'lessons',
  'group_memberships',
  'group_schedule_slots',
  'groups',
  'students',
  'tokens',
  'teachers',
  'sync_failures',
];
```

Это нужно, чтобы `npm run db:truncate -- --yes` не падал на FK при сбросе. payments стоит первым в truncate-порядке — чтобы FK к students/directions сначала освободить.

---

## Task 3: shared/schemas.js — Zod для payments + расширение direction

**Files:**
- Modify: `shared/schemas.js`

- [ ] **Step 1: Добавить paymentCreateSchema**

В `shared/schemas.js` после `adminSettingsSchema` (перед секцией Teacher SPA endpoints) вставить:

```js
// ===== Payments =====

const paymentCreateSchema = z.object({
  student_id:          id,
  direction_id:        id,
  subscriptions_count: z.coerce.number().int().min(1),
  unit_price:          z.coerce.number().min(0),
  paid_at:             dateStr,
  note:                z.string().max(500).nullable().optional(),
});
```

`total_amount` НЕ принимается — сервер пересчитает.

- [ ] **Step 2: Расширить direction-схемы**

Найти `baseDirectionObject` и добавить поле `subscription_price`:

```js
const baseDirectionObject = z.object({
  name: z.string().trim().min(1),
  sheet_name: z.string().trim().min(1),
  is_individual: z.boolean(),
  total_lessons: z.number().int().min(0).nullable().optional(),
  color: hexColor.nullable().optional().or(z.literal('')),
  subscription_price: z.coerce.number().min(0).nullable().optional(),  // ← новое
});
```

`createDirectionSchema` и `updateDirectionSchema` уже наследуют через `baseDirectionObject`, дополнительно ничего менять не нужно.

- [ ] **Step 3: Экспортировать paymentCreateSchema**

В `module.exports`:

```js
module.exports = {
  // ...existing...
  paymentCreateSchema,
};
```

- [ ] **Step 4: Sanity-check на синтаксис**

Run: `node -e "require('./shared/schemas.js')"`
Expected: пусто (модуль без ошибок).

---

## Task 4: shared/types.ts — TS-типы Payment и Balance

**Files:**
- Modify: `shared/types.ts`

- [ ] **Step 1: Добавить subscription_price в Direction**

Найти `interface Direction` и добавить поле:

```ts
export interface Direction {
  id: ID;
  name: string;
  sheet_name: string;
  is_individual: boolean;
  active: boolean;
  total_lessons: number | null;
  color: string | null;
  subscription_price: number | string | null;  // ← новое, numeric от pg может прийти строкой
}
```

- [ ] **Step 2: Добавить типы Payment и Balance в конец файла**

В конец `shared/types.ts` перед `ApiErrorBody` или после него добавить:

```ts
// ===== Payments =====

export interface Payment {
  id: ID;
  student_id: ID;
  direction_id: ID;
  subscriptions_count: number;
  unit_price: number | string;   // numeric(10,2) → строка от pg
  total_amount: number | string;
  paid_at: string;               // 'YYYY-MM-DD'
  note: string | null;
  created_at: string;
  created_by: string | null;
  // joined-only:
  student_name?: string;
  direction_name?: string;
}

// ===== Balance =====

export interface DirectionBalance {
  direction_id: ID;
  direction_name: string;
  direction_color: string | null;
  purchased_lessons: number;  // SUM(subscriptions_count * 4)
  attended_lessons: number;   // dotted: half=0.5
  balance: number;            // purchased − attended (может быть < 0)
  total_paid_amount: number | string;
}

export interface StudentBalance {
  per_direction: DirectionBalance[];
  total_balance: number;
  total_paid_amount: number | string;
  payments: Payment[];
}
```

- [ ] **Step 3: Sanity typecheck**

Run: `npm run admin:typecheck`
Expected: 0 ошибок. Если есть ошибки в существующем коде из-за нового обязательного `subscription_price` — это ожидаемо в местах, где Direction конструируется руками; чинить такие места в следующих тасках.

---

## Task 5: admin-repo — subscription_price в createDirection/updateDirection

**Files:**
- Modify: `services/admin-repo.js:52-73`

- [ ] **Step 1: Обновить createDirection**

Заменить функцию (примерно строка 52):

```js
async function createDirection({ name, sheet_name, is_individual, total_lessons, color, subscription_price }) {
  const { rows } = await pool.query(
    `INSERT INTO directions (name, sheet_name, is_individual, total_lessons, color, subscription_price)
     VALUES ($1, $2, $3, $4, NULLIF($5,''), $6) RETURNING *`,
    [name, sheet_name, !!is_individual, total_lessons ?? null, color ?? null, subscription_price ?? null],
  );
  return rows[0];
}
```

- [ ] **Step 2: Обновить updateDirection**

Заменить функцию (примерно строка 60):

```js
async function updateDirection(id, { name, sheet_name, is_individual, active, total_lessons, color, subscription_price }) {
  const { rows } = await pool.query(
    `UPDATE directions SET
       name               = COALESCE($2, name),
       sheet_name         = COALESCE($3, sheet_name),
       is_individual      = COALESCE($4, is_individual),
       active             = COALESCE($5, active),
       total_lessons      = COALESCE($6, total_lessons),
       color              = COALESCE(NULLIF($7,''), color),
       subscription_price = CASE WHEN $8::numeric IS NOT NULL OR $9::boolean THEN $8::numeric ELSE subscription_price END
     WHERE id = $1 RETURNING *`,
    [
      id,
      name ?? null,
      sheet_name ?? null,
      is_individual ?? null,
      active ?? null,
      total_lessons ?? null,
      color ?? null,
      subscription_price ?? null,
      subscription_price === null,  // явный «обнуляющий» флаг
    ],
  );
  return rows[0] || null;
}
```

Логика: если фронт прислал `subscription_price === null` явно — обнуляем; если не прислал — сохраняем текущее значение. Иначе работает обычный COALESCE через явное `null`-значение нельзя различить. Простая альтернатива — отдельный flag-параметр.

- [ ] **Step 3: Sanity test**

Run: `node --test services/admin-repo.test.js`
Expected: существующие тесты по directions проходят. Если что-то падает — проверить, что не сломал старые поля.

---

## Task 6: admin-repo — payments CRUD функции

**Files:**
- Modify: `services/admin-repo.js` (новая секция в конце файла перед module.exports)

- [ ] **Step 1: Добавить секцию Payments**

В `services/admin-repo.js` перед `module.exports = { ... }` вставить:

```js
// ===== Payments =====

async function createPayment({ student_id, direction_id, subscriptions_count, unit_price, paid_at, note, created_by }) {
  // 1. Подтянуть направление и проверить ёмкость курса.
  const dirRes = await pool.query(
    `SELECT id, total_lessons FROM directions WHERE id = $1`,
    [direction_id],
  );
  const dir = dirRes.rows[0];
  if (!dir) return { error: 'direction_not_found' };
  if (!dir.total_lessons || dir.total_lessons <= 0) return { error: 'no_capacity' };

  // 2. Подсчитать уже купленные абонементы по направлению.
  const sumRes = await pool.query(
    `SELECT COALESCE(SUM(subscriptions_count), 0)::int AS already
       FROM payments
      WHERE student_id = $1 AND direction_id = $2`,
    [student_id, direction_id],
  );
  const already = sumRes.rows[0].already;
  const capSubs = Math.floor(dir.total_lessons / 4);
  if (already + subscriptions_count > capSubs) {
    return { error: 'cap_exceeded', already, cap_subscriptions: capSubs };
  }

  // 3. Insert. total_amount пересчитывается ЗДЕСЬ, фронту не доверяем.
  const total = (Number(unit_price) * subscriptions_count).toFixed(2);
  const { rows } = await pool.query(
    `INSERT INTO payments
       (student_id, direction_id, subscriptions_count, unit_price, total_amount, paid_at, note, created_by)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
     RETURNING *`,
    [student_id, direction_id, subscriptions_count, unit_price, total, paid_at, note ?? null, created_by ?? null],
  );
  return { payment: rows[0] };
}

async function listPayments({ student_id, direction_id, from, to } = {}) {
  const where = [];
  const params = [];
  if (student_id)   { params.push(student_id);   where.push(`p.student_id   = $${params.length}`); }
  if (direction_id) { params.push(direction_id); where.push(`p.direction_id = $${params.length}`); }
  if (from)         { params.push(from);         where.push(`p.paid_at >= $${params.length}`); }
  if (to)           { params.push(to);           where.push(`p.paid_at <= $${params.length}`); }
  const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : '';
  const { rows } = await pool.query(
    `SELECT p.*, s.full_name AS student_name, d.name AS direction_name
       FROM payments p
       JOIN students   s ON s.id = p.student_id
       JOIN directions d ON d.id = p.direction_id
       ${whereSql}
      ORDER BY p.paid_at DESC, p.id DESC`,
    params,
  );
  return rows;
}

async function getPayment(id) {
  const { rows } = await pool.query(`SELECT * FROM payments WHERE id = $1`, [id]);
  return rows[0] || null;
}

async function deletePayment(id) {
  // Возвращаем удалённую запись чтобы посчитать новый баланс и отдать warning.
  const { rows } = await pool.query(
    `DELETE FROM payments WHERE id = $1 RETURNING student_id, direction_id`,
    [id],
  );
  if (!rows[0]) return { deleted: false };
  const { student_id, direction_id } = rows[0];
  const balance = await _balanceForDirection(student_id, direction_id);
  return { deleted: true, student_id, direction_id, new_balance: balance };
}

async function _balanceForDirection(student_id, direction_id) {
  const { rows } = await pool.query(
    `SELECT
       COALESCE((SELECT SUM(subscriptions_count * 4)::numeric
                   FROM payments
                  WHERE student_id = $1 AND direction_id = $2), 0)
       -
       COALESCE((SELECT SUM(CASE WHEN l.lesson_duration_minutes = 45 THEN 0.5 ELSE 1 END)
                   FROM lesson_attendance la
                   JOIN lessons l ON l.id = la.lesson_id
                   JOIN groups  g ON g.id = l.group_id
                  WHERE la.student_id = $1
                    AND la.present    = true
                    AND g.direction_id = $2), 0)
       AS balance`,
    [student_id, direction_id],
  );
  return Number(rows[0].balance);
}

async function getStudentBalance(student_id) {
  // Все направления, где у студента есть оплата ИЛИ хотя бы один attended-урок.
  const { rows: directionRows } = await pool.query(
    `WITH paid AS (
       SELECT direction_id,
              SUM(subscriptions_count * 4)::numeric AS purchased,
              SUM(total_amount)::numeric           AS total_paid
         FROM payments
        WHERE student_id = $1
        GROUP BY direction_id
     ),
     attended AS (
       SELECT g.direction_id,
              SUM(CASE WHEN l.lesson_duration_minutes = 45 THEN 0.5 ELSE 1 END)::numeric AS attended
         FROM lesson_attendance la
         JOIN lessons l ON l.id = la.lesson_id
         JOIN groups  g ON g.id = l.group_id
        WHERE la.student_id = $1
          AND la.present    = true
        GROUP BY g.direction_id
     )
     SELECT
       d.id                                  AS direction_id,
       d.name                                AS direction_name,
       d.color                               AS direction_color,
       COALESCE(p.purchased, 0)::numeric     AS purchased_lessons,
       COALESCE(a.attended,  0)::numeric     AS attended_lessons,
       (COALESCE(p.purchased,0) - COALESCE(a.attended,0))::numeric AS balance,
       COALESCE(p.total_paid, 0)::numeric    AS total_paid_amount
     FROM directions d
     LEFT JOIN paid     p ON p.direction_id = d.id
     LEFT JOIN attended a ON a.direction_id = d.id
     WHERE p.direction_id IS NOT NULL OR a.direction_id IS NOT NULL
     ORDER BY d.name`,
    [student_id],
  );

  const payments = await listPayments({ student_id });

  const per_direction = directionRows.map((r) => ({
    direction_id: r.direction_id,
    direction_name: r.direction_name,
    direction_color: r.direction_color,
    purchased_lessons: Number(r.purchased_lessons),
    attended_lessons: Number(r.attended_lessons),
    balance: Number(r.balance),
    total_paid_amount: Number(r.total_paid_amount),
  }));

  const total_balance = per_direction.reduce((s, d) => s + d.balance, 0);
  const total_paid_amount = per_direction.reduce((s, d) => s + Number(d.total_paid_amount), 0);

  return { per_direction, total_balance, total_paid_amount, payments };
}

async function getDirectionPaymentsCount(direction_id) {
  const { rows } = await pool.query(
    `SELECT COUNT(*)::int AS c FROM payments WHERE direction_id = $1`,
    [direction_id],
  );
  return rows[0].c;
}
```

- [ ] **Step 2: Добавить экспорты**

В `module.exports = { ... }` (в конце файла) добавить:

```js
  createPayment,
  listPayments,
  getPayment,
  deletePayment,
  getStudentBalance,
  getDirectionPaymentsCount,
```

- [ ] **Step 3: Sanity-загрузка модуля**

Run: `node -e "const r = require('./services/admin-repo'); console.log(Object.keys(r).filter(k => k.includes('ayment')))"`
Expected: `[ 'createPayment', 'listPayments', 'getPayment', 'deletePayment', 'getDirectionPaymentsCount' ]` (`getStudentBalance` тоже, фильтр по подстроке).

---

## Task 7: Backend test — admin-repo payments round-trip

**Files:**
- Modify: `services/admin-repo.test.js` (добавить в конец до последней закрывающей)

- [ ] **Step 1: Дописать тест**

В конец `services/admin-repo.test.js` (перед последним пустым местом) добавить:

```js
test('payments: createPayment → balance → deletePayment', async () => {
  // Setup: direction with total_lessons=8 (2 subscriptions = 8 lessons), student, group, lesson
  const dir = await pool.query(
    `INSERT INTO directions (name, sheet_name, is_individual, total_lessons, subscription_price)
     VALUES ('__T_DIR_P__', 'X', false, 8, 1000)
     RETURNING id`
  );
  const dirId = dir.rows[0].id;
  const te = await pool.query(`INSERT INTO teachers (name) VALUES ('__T_TE_P__') RETURNING id`);
  const grp = await pool.query(
    `INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes)
     VALUES ('__T_G_P__', $1, $2, false, 90) RETURNING id`,
    [dirId, te.rows[0].id]
  );
  const st = await pool.query(`INSERT INTO students (full_name) VALUES ('__T_S_P__') RETURNING id`);
  const stId = st.rows[0].id;

  // 1. Create payment for 1 subscription = 4 lessons.
  const r1 = await repo.createPayment({
    student_id: stId, direction_id: dirId,
    subscriptions_count: 1, unit_price: 1000,
    paid_at: '2026-06-01', created_by: 'admin',
  });
  assert.ok(r1.payment, `expected payment, got ${JSON.stringify(r1)}`);
  assert.strictEqual(Number(r1.payment.total_amount), 1000);

  // 2. Balance: purchased=4, attended=0 → 4.
  const b1 = await repo.getStudentBalance(stId);
  assert.strictEqual(b1.total_balance, 4);
  assert.strictEqual(b1.per_direction.length, 1);
  assert.strictEqual(b1.per_direction[0].balance, 4);

  // 3. Cap-exceeded: try to buy 2 more (already=1, cap=2, would-be=3 > 2).
  const r2 = await repo.createPayment({
    student_id: stId, direction_id: dirId,
    subscriptions_count: 2, unit_price: 1000,
    paid_at: '2026-06-02', created_by: 'admin',
  });
  assert.strictEqual(r2.error, 'cap_exceeded');

  // 4. Buy 1 more = total 2 subscriptions.
  const r3 = await repo.createPayment({
    student_id: stId, direction_id: dirId,
    subscriptions_count: 1, unit_price: 1000,
    paid_at: '2026-06-02', created_by: 'admin',
  });
  assert.ok(r3.payment);

  // 5. Now buying 1 more should fail (already=2, cap=2).
  const r4 = await repo.createPayment({
    student_id: stId, direction_id: dirId,
    subscriptions_count: 1, unit_price: 1000,
    paid_at: '2026-06-03', created_by: 'admin',
  });
  assert.strictEqual(r4.error, 'cap_exceeded');

  // 6. Create a present-lesson, balance should drop by 1.
  const lessonId = await repo.createLessonFull({
    lesson_date: '2026-06-01',
    teacher_id: te.rows[0].id,
    group_id: grp.rows[0].id,
    lesson_number: 1,
    lesson_duration_minutes: 90,
    lesson_type: 'regular',
    submitted_by_token: 'admin-imported',
    attendance: [{ student_id: stId, present: true }],
    payroll: { total_students: 1, present_count: 1, payment: 500, penalty: 0 },
  });
  const b2 = await repo.getStudentBalance(stId);
  assert.strictEqual(b2.total_balance, 7);  // purchased=8, attended=1

  // 7. Delete one payment → balance check: purchased=4, attended=1 → 3.
  const del = await repo.deletePayment(r1.payment.id);
  assert.strictEqual(del.deleted, true);
  assert.strictEqual(del.new_balance, 3);

  // Cleanup
  await pool.query(`DELETE FROM payments WHERE student_id = $1`, [stId]);
  await repo.deleteLessonFull(lessonId);
  await pool.query(`DELETE FROM students WHERE id = $1`, [stId]);
  await pool.query(`DELETE FROM groups WHERE id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [te.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id = $1`, [dirId]);
});

test('payments: createPayment errors on direction without total_lessons', async () => {
  const dir = await pool.query(
    `INSERT INTO directions (name, sheet_name, is_individual, total_lessons) VALUES ('__T_DIR_NOC__', 'X', false, NULL) RETURNING id`
  );
  const st = await pool.query(`INSERT INTO students (full_name) VALUES ('__T_S_NOC__') RETURNING id`);
  const r = await repo.createPayment({
    student_id: st.rows[0].id, direction_id: dir.rows[0].id,
    subscriptions_count: 1, unit_price: 100, paid_at: '2026-06-01',
  });
  assert.strictEqual(r.error, 'no_capacity');

  await pool.query(`DELETE FROM students WHERE id = $1`, [st.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id = $1`, [dir.rows[0].id]);
});

test('payments: half-lesson consumes 0.5 from balance', async () => {
  const dir = await pool.query(
    `INSERT INTO directions (name, sheet_name, is_individual, total_lessons, subscription_price)
     VALUES ('__T_DIR_HALF__', 'X', false, 4, 1000) RETURNING id`
  );
  const te = await pool.query(`INSERT INTO teachers (name) VALUES ('__T_TE_HALF__') RETURNING id`);
  const grp = await pool.query(
    `INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes)
     VALUES ('__T_G_HALF__', $1, $2, false, 45) RETURNING id`,
    [dir.rows[0].id, te.rows[0].id]
  );
  const st = await pool.query(`INSERT INTO students (full_name) VALUES ('__T_S_HALF__') RETURNING id`);

  await repo.createPayment({
    student_id: st.rows[0].id, direction_id: dir.rows[0].id,
    subscriptions_count: 1, unit_price: 1000, paid_at: '2026-06-01',
  });
  const lessonId = await repo.createLessonFull({
    lesson_date: '2026-06-01', teacher_id: te.rows[0].id, group_id: grp.rows[0].id,
    lesson_number: 1, lesson_duration_minutes: 45, lesson_type: 'regular',
    submitted_by_token: 'admin-imported',
    attendance: [{ student_id: st.rows[0].id, present: true }],
    payroll: { total_students: 1, present_count: 1, payment: 250, penalty: 0 },
  });
  const b = await repo.getStudentBalance(st.rows[0].id);
  assert.strictEqual(b.total_balance, 3.5);  // 4 - 0.5

  await pool.query(`DELETE FROM payments WHERE student_id = $1`, [st.rows[0].id]);
  await repo.deleteLessonFull(lessonId);
  await pool.query(`DELETE FROM students WHERE id = $1`, [st.rows[0].id]);
  await pool.query(`DELETE FROM groups WHERE id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [te.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id = $1`, [dir.rows[0].id]);
});
```

- [ ] **Step 2: Запустить тесты**

Run: `node --test services/admin-repo.test.js`
Expected: все три новых теста PASS. Старые тоже PASS.

---

## Task 8: routes/admin/payments.js — Express router

**Files:**
- Create: `routes/admin/payments.js`

- [ ] **Step 1: Создать файл**

```js
const express = require('express');
const adminRepo = require('../../services/admin-repo');
const validate = require('../middleware/validate');
const asyncWrap = require('../middleware/async-wrap');
const { paymentCreateSchema } = require('../../shared/schemas');

const router = express.Router();

router.get('/', asyncWrap(async (req, res) => {
  const filters = {
    student_id: req.query.student_id ? Number(req.query.student_id) : undefined,
    direction_id: req.query.direction_id ? Number(req.query.direction_id) : undefined,
    from: req.query.from || undefined,
    to: req.query.to || undefined,
  };
  res.json(await adminRepo.listPayments(filters));
}));

router.get('/:id', asyncWrap(async (req, res) => {
  const p = await adminRepo.getPayment(req.params.id);
  if (!p) return res.status(404).json({ error: 'Not found' });
  res.json(p);
}));

router.post('/', validate(paymentCreateSchema), asyncWrap(async (req, res) => {
  const result = await adminRepo.createPayment({
    ...req.validated,
    created_by: req.admin?.user || null,
  });
  if (result.error === 'direction_not_found') {
    return res.status(404).json({ error: 'Direction not found' });
  }
  if (result.error === 'no_capacity') {
    return res.status(400).json({ error: 'no_capacity', message: 'У направления не задан total_lessons' });
  }
  if (result.error === 'cap_exceeded') {
    return res.status(400).json({
      error: 'cap_exceeded',
      already: result.already,
      cap_subscriptions: result.cap_subscriptions,
    });
  }
  res.status(201).json(result.payment);
}));

router.delete('/:id', asyncWrap(async (req, res) => {
  const r = await adminRepo.deletePayment(req.params.id);
  if (!r.deleted) return res.status(404).json({ error: 'Not found' });
  const body = { deleted: true, new_balance: r.new_balance };
  if (r.new_balance < 0) body.warning = 'balance_negative';
  res.json(body);
}));

module.exports = router;
```

- [ ] **Step 2: Sanity-загрузка**

Run: `node -e "require('./routes/admin/payments')"`
Expected: пусто.

---

## Task 9: routes/admin/students.js — endpoint /:id/balance

**Files:**
- Modify: `routes/admin/students.js`

- [ ] **Step 1: Найти, где смонтированы student routes**

Run: `cat routes/admin/students.js`
Найти секцию с GET `/:id/stats` (паттерн `GET /:id/`) и сразу после неё добавить новый handler.

- [ ] **Step 2: Добавить handler**

После роута `/:id/stats` (или в логически правильном месте, рядом с другими `:id/...` роутами) вставить:

```js
router.get('/:id/balance', asyncWrap(async (req, res) => {
  const balance = await adminRepo.getStudentBalance(Number(req.params.id));
  res.json(balance);
}));
```

- [ ] **Step 3: Sanity-загрузка**

Run: `node -e "require('./routes/admin/students')"`
Expected: пусто.

---

## Task 10: routes/admin/index.js — mount payments router

**Files:**
- Modify: `routes/admin/index.js`

- [ ] **Step 1: Импортировать роутер**

В верхней части файла, рядом с другими импортами:

```js
const paymentsRouter = require('./payments');
```

- [ ] **Step 2: Смонтировать после payroll**

Найти строку `router.use('/payroll', requireAdmin, payrollRouter);` и сразу после неё:

```js
router.use('/payments', requireAdmin, paymentsRouter);
```

- [ ] **Step 3: Поднять сервер**

Run: `npm start`
Expected: «Server listening on port 3000» без ошибок про missing module. Ctrl+C.

---

## Task 11: Backend smoke roundtrip через curl

**Files:**
- ничего не создаём, только проверяем уже написанное

- [ ] **Step 1: Запустить сервер в фоне**

Run: `npm start` (run_in_background=true).

- [ ] **Step 2: Залогиниться и получить cookie**

```bash
curl -s -c /tmp/admin-cookie.txt -X POST http://localhost:3000/api/admin/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<свой пароль>"}'
```
Expected: `{"user":"admin"}` и cookie в файле.

- [ ] **Step 3: Создать оплату**

Подставить реальные student_id и direction_id (предварительно `curl -b /tmp/admin-cookie.txt http://localhost:3000/api/admin/students` и `.../directions`):

```bash
curl -s -b /tmp/admin-cookie.txt -X POST http://localhost:3000/api/admin/payments \
  -H "Content-Type: application/json" \
  -d '{"student_id":1,"direction_id":1,"subscriptions_count":1,"unit_price":7250,"paid_at":"2026-06-01"}'
```
Expected: 201 + объект payment с `total_amount: "7250.00"`.

- [ ] **Step 4: Получить баланс ученика**

```bash
curl -s -b /tmp/admin-cookie.txt http://localhost:3000/api/admin/students/1/balance | jq .
```
Expected: `per_direction[0].balance` ≥ 4, `payments[0].id` = только что созданный.

- [ ] **Step 5: Попробовать без cap (на bare direction без total_lessons)**

```bash
curl -s -b /tmp/admin-cookie.txt -X POST http://localhost:3000/api/admin/payments \
  -H "Content-Type: application/json" \
  -d '{"student_id":1,"direction_id":<id-без-total_lessons>,"subscriptions_count":1,"unit_price":100,"paid_at":"2026-06-01"}'
```
Expected: 400 + `{"error":"no_capacity"...}`.

- [ ] **Step 6: Удалить оплату**

```bash
curl -s -b /tmp/admin-cookie.txt -X DELETE http://localhost:3000/api/admin/payments/<id-payment>
```
Expected: `{deleted: true, new_balance: 0}` (или с warning если уже были attended уроки).

- [ ] **Step 7: Остановить сервер**

Прервать background-task.

---

## Task 12: Frontend lib — fmtRub helper

**Files:**
- Modify: `web/admin/src/lib/format.ts`

- [ ] **Step 1: Прочитать текущий format.ts**

Run: `cat web/admin/src/lib/format.ts`

- [ ] **Step 2: Добавить fmtRub**

В конец файла добавить:

```ts
export function fmtRub(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  // 7 250 ₽ / 7 250,50 ₽
  const rounded = Math.round(n * 100) / 100;
  const intPart = Math.floor(Math.abs(rounded)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  const fracCents = Math.round((Math.abs(rounded) - Math.floor(Math.abs(rounded))) * 100);
  const sign = rounded < 0 ? '−' : '';
  const fracPart = fracCents ? `,${String(fracCents).padStart(2, '0')}` : '';
  return `${sign}${intPart}${fracPart} ₽`;
}

export function fmtLessons(value: number): string {
  // 7, 7.5, 0, -3
  const n = Number(value);
  if (!Number.isFinite(n)) return '0';
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(1).replace('.', ',');
}
```

- [ ] **Step 3: Typecheck**

Run: `npm run admin:typecheck`
Expected: 0 ошибок.

---

## Task 13: Hook usePayments

**Files:**
- Create: `web/admin/src/hooks/usePayments.ts`

- [ ] **Step 1: Создать файл**

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Payment } from '../lib/types';

const KEY = ['payments'] as const;

export interface PaymentFilters {
  student_id?: number;
  direction_id?: number;
  from?: string;
  to?: string;
}

export interface PaymentCreateInput {
  student_id: number;
  direction_id: number;
  subscriptions_count: number;
  unit_price: number;
  paid_at: string;
  note?: string | null;
}

export interface PaymentDeleteResult {
  deleted: true;
  new_balance: number;
  warning?: 'balance_negative';
}

function buildQuery(f: PaymentFilters | undefined): string {
  if (!f) return '';
  const params = new URLSearchParams();
  if (f.student_id)   params.set('student_id',   String(f.student_id));
  if (f.direction_id) params.set('direction_id', String(f.direction_id));
  if (f.from)         params.set('from', f.from);
  if (f.to)           params.set('to', f.to);
  const s = params.toString();
  return s ? `?${s}` : '';
}

export function usePayments(filters?: PaymentFilters) {
  return useQuery({
    queryKey: [...KEY, filters || {}],
    queryFn: () => api<Payment[]>('GET', `/api/admin/payments${buildQuery(filters)}`),
  });
}

export function usePaymentMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['payments'] });
    qc.invalidateQueries({ queryKey: ['students'] });        // balance/stats invalidation
    qc.invalidateQueries({ queryKey: ['student-balance'] }); // explicit balance key
    qc.invalidateQueries({ queryKey: ['directions'] });      // counter in SubscriptionsPage
  };
  return {
    create: useMutation({
      mutationFn: (body: PaymentCreateInput) =>
        api<Payment>('POST', '/api/admin/payments', body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) =>
        api<PaymentDeleteResult>('DELETE', `/api/admin/payments/${id}`),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Step 2: Typecheck**

Run: `npm run admin:typecheck`
Expected: 0 ошибок.

---

## Task 14: Hook useStudentBalance

**Files:**
- Create: `web/admin/src/hooks/useStudentBalance.ts`

- [ ] **Step 1: Создать файл**

```ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { StudentBalance } from '../lib/types';

export function useStudentBalance(studentId: number | undefined) {
  return useQuery({
    queryKey: ['student-balance', studentId],
    queryFn: () => api<StudentBalance>('GET', `/api/admin/students/${studentId}/balance`),
    enabled: Number.isFinite(studentId) && (studentId as number) > 0,
  });
}
```

- [ ] **Step 2: Typecheck**

Run: `npm run admin:typecheck`
Expected: 0 ошибок.

---

## Task 15: BlockSelector компонент

**Files:**
- Create: `web/admin/src/pages/payments/BlockSelector.tsx`

- [ ] **Step 1: Создать файл**

```tsx
import { useState } from 'react';

interface Props {
  totalSubscriptions: number;     // N коробок
  alreadyPurchased: number;       // сколько закрашено
  selected: number;               // сколько выбрано прямо сейчас
  color: string | null | undefined;
  onChange: (next: number) => void;
}

export function BlockSelector({ totalSubscriptions, alreadyPurchased, selected, color, onChange }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const accent = color || 'var(--accent, #7c3aed)';

  // Коробки нумеруются 0..N-1.
  // [0 .. alreadyPurchased-1]                       — закрашенные (locked).
  // [alreadyPurchased .. alreadyPurchased+selected-1] — выбранные.
  // [alreadyPurchased+selected .. N-1]              — свободные.

  const handleClick = (idx: number) => {
    if (idx < alreadyPurchased) return; // locked
    // Если кликнули в уже выбранный диапазон → откатить
    if (idx < alreadyPurchased + selected) {
      onChange(idx - alreadyPurchased);
      return;
    }
    // Иначе выбрать диапазон до idx (включительно)
    onChange(idx - alreadyPurchased + 1);
  };

  const cells = [];
  for (let i = 0; i < totalSubscriptions; i++) {
    const isLocked = i < alreadyPurchased;
    const isSelected = i >= alreadyPurchased && i < alreadyPurchased + selected;
    const isHoverPreview = hover !== null && !isLocked && !isSelected
      && i >= alreadyPurchased && i <= alreadyPurchased + hover;
    cells.push(
      <button
        key={i}
        type="button"
        className={`block-cell${isLocked ? ' block-cell--locked' : ''}${isSelected ? ' block-cell--selected' : ''}${isHoverPreview ? ' block-cell--hover' : ''}`}
        style={{ ['--dir-color' as string]: accent }}
        onClick={() => handleClick(i)}
        onMouseEnter={() => !isLocked && setHover(i - alreadyPurchased + 1)}
        onMouseLeave={() => setHover(null)}
        disabled={isLocked}
        aria-label={isLocked ? `Уже куплен абонемент №${i + 1}` : `Абонемент №${i + 1}`}
      >
        <span className="block-cell__icons">✕✕✕✕</span>
      </button>
    );
  }

  const free = totalSubscriptions - alreadyPurchased - selected;
  return (
    <div className="block-selector">
      <div className="block-selector__row">{cells}</div>
      <div className="block-selector__legend">
        {alreadyPurchased > 0 && <span>{alreadyPurchased} ранее</span>}
        {alreadyPurchased > 0 && <span> · </span>}
        <span>{selected} выбрано</span>
        <span> · </span>
        <span>{free} свободно</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `npm run admin:typecheck`
Expected: 0 ошибок.

---

## Task 16: PaymentModal компонент

**Files:**
- Create: `web/admin/src/pages/payments/PaymentModal.tsx`

- [ ] **Step 1: Создать файл**

```tsx
import { useEffect, useMemo, useState } from 'react';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { SelectInput } from '../../components/form/SelectInput';
import { NumberInput } from '../../components/form/NumberInput';
import { DateInput } from '../../components/form/DateInput';
import { Textarea } from '../../components/form/Textarea';
import { useStudents } from '../../hooks/useStudents';
import { useDirections } from '../../hooks/useDirections';
import { usePayments, usePaymentMutations } from '../../hooks/usePayments';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { fmtRub } from '../../lib/format';
import { BlockSelector } from './BlockSelector';

interface Props {
  open: boolean;
  onClose: () => void;
  studentId?: number;
  directionId?: number;
}

function todayMSK(): string {
  // МСК = UTC+3 (без DST), как в остальной кодовой базе.
  const now = new Date();
  const msk = new Date(now.getTime() + (3 * 60 - now.getTimezoneOffset()) * 60_000);
  return msk.toISOString().slice(0, 10);
}

export function PaymentModal({ open, onClose, studentId, directionId }: Props) {
  const students = useStudents();
  const directions = useDirections();
  const muts = usePaymentMutations();
  const showError = useApiError();
  const { toast } = useToast();

  const [stId, setStId] = useState<number | undefined>(studentId);
  const [dirId, setDirId] = useState<number | undefined>(directionId);
  const [count, setCount] = useState(0);
  const [customPriceOpen, setCustomPriceOpen] = useState(false);
  const [customPrice, setCustomPrice] = useState<number | ''>('');
  const [paidAt, setPaidAt] = useState(todayMSK());
  const [note, setNote] = useState('');

  // Reset при каждом открытии или смене предзаполнения
  useEffect(() => {
    if (open) {
      setStId(studentId);
      setDirId(directionId);
      setCount(0);
      setCustomPriceOpen(false);
      setCustomPrice('');
      setPaidAt(todayMSK());
      setNote('');
    }
  }, [open, studentId, directionId]);

  // Подгружаем уже-оплаты для этой пары student+direction.
  const existing = usePayments({ student_id: stId, direction_id: dirId });
  const alreadyPurchased = useMemo(() => {
    if (!existing.data) return 0;
    return existing.data.reduce((s, p) => s + Number(p.subscriptions_count), 0);
  }, [existing.data]);

  const direction = useMemo(
    () => directions.data?.find((d) => d.id === dirId),
    [directions.data, dirId],
  );
  const totalSubs = useMemo(() => {
    if (!direction?.total_lessons) return 0;
    return Math.floor(direction.total_lessons / 4);
  }, [direction]);

  // Авто-раскрытие custom если у направления нет цены
  useEffect(() => {
    if (direction && (direction.subscription_price === null || direction.subscription_price === undefined)) {
      setCustomPriceOpen(true);
    }
  }, [direction]);

  const basePrice = direction?.subscription_price != null ? Number(direction.subscription_price) : null;
  const unitPrice = customPriceOpen
    ? (typeof customPrice === 'number' ? customPrice : 0)
    : (basePrice ?? 0);
  const total = unitPrice * count;
  const remainingFree = totalSubs - alreadyPurchased - count;
  const canBuyMore = remainingFree >= 0 && count > 0;

  const noCapacity = !direction?.total_lessons || direction.total_lessons <= 0;

  const studentOptions = useMemo(() => {
    if (!students.data) return [];
    return students.data
      .slice()
      .sort((a, b) => a.full_name.localeCompare(b.full_name))
      .map((s) => ({
        value: String(s.id),
        label: s.enrollment_status === 'enrolled'
          ? s.full_name
          : `${s.full_name} (${labelStatus(s.enrollment_status)})`,
      }));
  }, [students.data]);

  const directionOptions = useMemo(() => {
    if (!directions.data) return [];
    return directions.data
      .filter((d) => d.active)
      .map((d) => ({
        value: String(d.id),
        label: d.total_lessons ? d.name : `${d.name} (курс не задан)`,
      }));
  }, [directions.data]);

  const handleSubmit = async () => {
    if (!stId || !dirId || count < 1 || unitPrice < 0 || !paidAt) {
      toast('Заполните все поля', 'error');
      return;
    }
    if (noCapacity) {
      toast('У направления не задан total_lessons', 'error');
      return;
    }
    if (alreadyPurchased + count > totalSubs) {
      toast('Превышена ёмкость курса', 'error');
      return;
    }
    try {
      await muts.create.mutateAsync({
        student_id: stId,
        direction_id: dirId,
        subscriptions_count: count,
        unit_price: unitPrice,
        paid_at: paidAt,
        note: note.trim() || null,
      });
      toast(`Оплата внесена: ${fmtRub(total)}`, 'ok');
      onClose();
    } catch (err) {
      showError(err);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title="Внести оплату" wide>
      <div className="payment-form">
        <Field label="Ученик">
          <SelectInput
            value={stId ? String(stId) : ''}
            onChange={(v) => setStId(v ? Number(v) : undefined)}
            options={studentOptions}
            placeholder="Выберите ученика"
          />
        </Field>

        <Field label="Направление">
          <SelectInput
            value={dirId ? String(dirId) : ''}
            onChange={(v) => { setDirId(v ? Number(v) : undefined); setCount(0); }}
            options={directionOptions}
            placeholder="Выберите направление"
          />
        </Field>

        {dirId && direction && (
          <>
            {noCapacity ? (
              <div className="payment-form__warn">
                У направления «{direction.name}» не задан total_lessons. Настройте курс в разделе
                «Направления», чтобы продавать абонементы.
              </div>
            ) : (
              <>
                <div className="payment-form__hint">
                  Уже куплено: {alreadyPurchased} абонементов ({alreadyPurchased * 4} уроков),
                  свободно {totalSubs - alreadyPurchased} из {totalSubs}.
                </div>

                <Field label="Блоки (4 урока в блоке)">
                  <BlockSelector
                    totalSubscriptions={totalSubs}
                    alreadyPurchased={alreadyPurchased}
                    selected={count}
                    color={direction.color}
                    onChange={setCount}
                  />
                </Field>

                <Field label="Дата оплаты">
                  <DateInput value={paidAt} onChange={(e) => setPaidAt(e.target.value)} />
                </Field>

                <Field label="Цена за абонемент">
                  {!customPriceOpen ? (
                    <div className="payment-form__price-row">
                      <span className="payment-form__price">
                        {basePrice != null ? fmtRub(basePrice) : 'не настроена'}
                      </span>
                      <button
                        type="button"
                        className="btn-link"
                        onClick={() => { setCustomPriceOpen(true); setCustomPrice(basePrice ?? ''); }}
                      >
                        + Задать свою сумму за абонемент
                      </button>
                    </div>
                  ) : (
                    <div className="payment-form__price-row">
                      <NumberInput
                        value={customPrice}
                        min={0}
                        step="0.01"
                        onChange={(e) => setCustomPrice(e.target.value === '' ? '' : Number(e.target.value))}
                        style={{ width: 160 }}
                      />
                      <span>₽</span>
                      {basePrice != null && (
                        <button
                          type="button"
                          className="btn-link"
                          onClick={() => { setCustomPriceOpen(false); setCustomPrice(''); }}
                        >
                          × Вернуть базовую цену
                        </button>
                      )}
                    </div>
                  )}
                </Field>

                <Field label="Комментарий">
                  <Textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
                </Field>

                <div className="payment-form__total">
                  Итого: <strong>{fmtRub(total)}</strong>
                  {count > 0 && ` (${count} × ${fmtRub(unitPrice)})`}
                </div>
              </>
            )}
          </>
        )}

        <div className="payment-form__footer">
          <button type="button" className="btn-secondary" onClick={onClose}>Отмена</button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => { void handleSubmit(); }}
            disabled={!canBuyMore || noCapacity || muts.create.isPending}
          >
            Внести оплату
          </button>
        </div>
      </div>
    </Dialog>
  );
}

function labelStatus(s: string): string {
  if (s === 'frozen') return 'заморожен';
  if (s === 'not_enrolled') return 'не учится';
  if (s === 'declined') return 'отказался';
  return s;
}
```

- [ ] **Step 2: Typecheck**

Run: `npm run admin:typecheck`
Expected: 0 ошибок. Если жалуется на отсутствующие компоненты (`Field`, `SelectInput`, ...) — проверить что они существуют (они есть согласно структуре R2, см. CLAUDE.md).

---

## Task 17: PaymentModalProvider — глобальный контекст

**Files:**
- Create: `web/admin/src/providers/PaymentModalProvider.tsx`

- [ ] **Step 1: Создать файл**

```tsx
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import { PaymentModal } from '../pages/payments/PaymentModal';

interface ModalState {
  open: boolean;
  studentId?: number;
  directionId?: number;
}

interface ContextValue {
  open: (opts?: { studentId?: number; directionId?: number }) => void;
}

const Ctx = createContext<ContextValue | null>(null);

export function PaymentModalProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ModalState>({ open: false });

  const open = useCallback((opts?: { studentId?: number; directionId?: number }) => {
    setState({ open: true, studentId: opts?.studentId, directionId: opts?.directionId });
  }, []);
  const close = useCallback(() => setState((s) => ({ ...s, open: false })), []);

  return (
    <Ctx.Provider value={{ open }}>
      {children}
      <PaymentModal
        open={state.open}
        studentId={state.studentId}
        directionId={state.directionId}
        onClose={close}
      />
    </Ctx.Provider>
  );
}

export function usePaymentModal(): ContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('usePaymentModal must be used within PaymentModalProvider');
  return v;
}
```

- [ ] **Step 2: Typecheck**

Run: `npm run admin:typecheck`
Expected: 0 ошибок.

---

## Task 18: Интеграция PaymentModalProvider в AppShell

**Files:**
- Modify: `web/admin/src/components/shell/AppShell.tsx`

- [ ] **Step 1: Импортировать провайдер**

В верх файла:

```tsx
import { PaymentModalProvider } from '../../providers/PaymentModalProvider';
```

- [ ] **Step 2: Обернуть содержимое shell**

Заменить return:

```tsx
return (
  <PaymentModalProvider>
    <div className="shell">
      {showSidebar && <Sidebar onClose={() => setSidebarOpen(false)} />}
      <main className="main" id="admin-main">
        <Outlet />
      </main>
      {showBurger && (
        <button
          type="button"
          className="burger-btn"
          onClick={onBurger}
          aria-label="Открыть меню"
          aria-expanded={mobileOpen}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="6" x2="21" y2="6"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
        </button>
      )}
      {isNarrow && <MobileNav open={mobileOpen} onClose={() => setMobileOpen(false)} />}
      <ScrollTopButton />
    </div>
  </PaymentModalProvider>
);
```

- [ ] **Step 3: Typecheck**

Run: `npm run admin:typecheck`
Expected: 0 ошибок.

---

## Task 19: Sidebar — две новые записи

**Files:**
- Modify: `web/admin/src/components/shell/Sidebar.tsx`

- [ ] **Step 1: Добавить иконки**

В `NAV_ICONS` объект добавить две новые иконки (внутри объекта, рядом с `payroll`):

```tsx
subscriptions: (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="5" width="18" height="14" rx="2"/>
    <line x1="3" y1="10" x2="21" y2="10"/>
    <line x1="7" y1="15" x2="11" y2="15"/>
  </svg>
),
pay: (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"/>
    <path d="M12 6v12M9 9h4.5a2 2 0 0 1 0 4H9a2 2 0 0 0 0 4h6"/>
  </svg>
),
```

- [ ] **Step 2: Добавить в SECTIONS**

В массив `SECTIONS` добавить subscriptions сразу после `lessons`:

```tsx
{ key: 'lessons', label: 'Уроки', path: '/admin/lessons' },
{ key: 'subscriptions', label: 'Абонементы', path: '/admin/subscriptions' },
{ key: 'payroll', label: 'Зарплата', path: '/admin/payroll' },
```

Кнопку «Внести оплату» в SECTIONS НЕ добавляем (она НЕ роут).

- [ ] **Step 3: Импортировать usePaymentModal**

В верх файла:

```tsx
import { usePaymentModal } from '../../providers/PaymentModalProvider';
```

- [ ] **Step 4: Отрендерить кнопку «Внести оплату»**

В компоненте `Sidebar`, внутри `<nav className="sidebar-nav">`, после `.map(...)` (т.е. сразу после закрывающего `)}` map'а), но до конца nav, добавить:

```tsx
<div className="nav-sep" />
<PayButton />
```

И в конец файла (после `Sidebar`):

```tsx
function PayButton() {
  const { open } = usePaymentModal();
  return (
    <button
      type="button"
      className="nav-btn nav-btn--cta"
      onClick={() => open()}
    >
      {NAV_ICONS['pay']} Внести оплату
    </button>
  );
}
```

- [ ] **Step 5: Typecheck**

Run: `npm run admin:typecheck`
Expected: 0 ошибок.

---

## Task 20: Route /admin/subscriptions в App.tsx

**Files:**
- Modify: `web/admin/src/App.tsx`

- [ ] **Step 1: Импортировать страницу**

В верх файла рядом с другими импортами:

```tsx
import SubscriptionsPage from './pages/subscriptions/SubscriptionsPage';
```

- [ ] **Step 2: Добавить route**

Сразу после `<Route path="/admin/payroll" ...>`:

```tsx
<Route path="/admin/subscriptions" element={<SubscriptionsPage />} />
```

- [ ] **Step 3: Typecheck**

Файл ещё не создан — typecheck упадёт. Это ожидаемо, починим в следующем таске.

---

## Task 21: SubscriptionsPage

**Files:**
- Create: `web/admin/src/pages/subscriptions/SubscriptionsPage.tsx`

- [ ] **Step 1: Создать файл**

```tsx
import { useState } from 'react';
import { useDirections, useDirectionMutations } from '../../hooks/useDirections';
import { usePayments } from '../../hooks/usePayments';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { fmtRub } from '../../lib/format';
import { Skeleton } from '../../components/ui/Skeleton';

export default function SubscriptionsPage() {
  const directions = useDirections();
  const payments = usePayments();
  const muts = useDirectionMutations();
  const { toast } = useToast();
  const showError = useApiError();

  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<string>('');

  if (directions.isLoading) return <Skeleton />;

  const rows = (directions.data || []).slice().sort((a, b) => a.name.localeCompare(b.name));

  const paymentsCountByDir = new Map<number, number>();
  for (const p of payments.data || []) {
    paymentsCountByDir.set(p.direction_id, (paymentsCountByDir.get(p.direction_id) || 0) + 1);
  }

  const startEdit = (id: number, current: number | null) => {
    setEditingId(id);
    setDraft(current != null ? String(current) : '');
  };
  const commit = async (id: number) => {
    const v = draft.trim();
    const num = v === '' ? null : Number(v);
    if (v !== '' && !Number.isFinite(num)) {
      toast('Введите число или оставьте пустым', 'error');
      return;
    }
    try {
      await muts.update.mutateAsync({ id, body: { subscription_price: num as number | null } });
      toast('Цена обновлена', 'ok');
      setEditingId(null);
    } catch (err) {
      showError(err);
    }
  };

  return (
    <section className="page">
      <div className="section-head">
        <h2>Абонементы</h2>
        <div className="section-actions">
          <span className="muted">Цена за 4 урока на каждое направление</span>
        </div>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Направление</th>
            <th>Цена за абонемент</th>
            <th>Уроков в курсе</th>
            <th>Цена за урок</th>
            <th>Всего оплат</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => {
            const price = d.subscription_price != null ? Number(d.subscription_price) : null;
            const total = d.total_lessons || 0;
            const subs = total > 0 ? Math.floor(total / 4) : 0;
            const perLesson = price != null && price > 0 ? price / 4 : null;
            const count = paymentsCountByDir.get(d.id) || 0;
            const isEditing = editingId === d.id;
            return (
              <tr key={d.id}>
                <td>
                  <span className="dir-tag" style={{ background: d.color || '#999' }} /> {d.name}
                </td>
                <td>
                  {isEditing ? (
                    <span className="inline-edit">
                      <input
                        type="number"
                        min={0}
                        step="0.01"
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') { void commit(d.id); }
                          if (e.key === 'Escape') { setEditingId(null); }
                        }}
                        autoFocus
                        style={{ width: 120 }}
                      />
                      <button type="button" className="btn-link" onClick={() => { void commit(d.id); }}>Сохранить</button>
                      <button type="button" className="btn-link" onClick={() => setEditingId(null)}>Отмена</button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="btn-link"
                      onClick={() => startEdit(d.id, price)}
                      title="Изменить цену"
                    >
                      {price != null ? fmtRub(price) : <em>не настроено</em>} ✏️
                    </button>
                  )}
                </td>
                <td>
                  {total > 0 ? `${total} (${subs} абон.)` : <em>не задан курс</em>}
                </td>
                <td>{perLesson != null ? fmtRub(perLesson) : '—'}</td>
                <td>{count}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `npm run admin:typecheck`
Expected: 0 ошибок.

---

## Task 22: StudentBalanceBlock

**Files:**
- Create: `web/admin/src/pages/students/StudentBalanceBlock.tsx`

- [ ] **Step 1: Создать файл**

```tsx
import { useState } from 'react';
import { useStudentBalance } from '../../hooks/useStudentBalance';
import { usePaymentMutations } from '../../hooks/usePayments';
import { usePaymentModal } from '../../providers/PaymentModalProvider';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { fmtRub, fmtLessons } from '../../lib/format';

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

  if (balance.isLoading) return null;
  const data = balance.data;
  if (!data) return null;
  if (data.per_direction.length === 0 && data.payments.length === 0) return null;

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
        <button type="button" className="btn-primary" onClick={() => open({ studentId })}>
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

      {data.per_direction.length > 0 && (
        <div className="balance-block__directions">
          {data.per_direction.map((d) => (
            <div key={d.direction_id} className="balance-block__direction-row">
              <span className="dir-tag" style={{ background: d.direction_color || '#999' }} />
              <span className="balance-block__direction-name">{d.direction_name}</span>
              <span className={d.balance < 0 ? 'balance-neg' : ''}>
                {fmtLessons(d.balance)} уроков
              </span>
              <span className="muted">{fmtRub(d.total_paid_amount)}</span>
            </div>
          ))}
        </div>
      )}

      {data.payments.length > 0 && (
        <>
          <h4 className="balance-block__history-head">История оплат</h4>
          <ul className="balance-block__history">
            {data.payments.map((p) => (
              <li key={p.id} className="balance-block__history-row">
                <div className="balance-block__history-main">
                  <span>{p.paid_at}</span>
                  <span> · </span>
                  <span>{p.direction_name}</span>
                  <span> · </span>
                  <span>{p.subscriptions_count} аб.</span>
                  <span> · </span>
                  <span>{fmtRub(p.unit_price)}/аб = <strong>{fmtRub(p.total_amount)}</strong></span>
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
        </>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `npm run admin:typecheck`
Expected: 0 ошибок.

---

## Task 23: Монтаж StudentBalanceBlock в StudentDetailPage

**Files:**
- Modify: `web/admin/src/pages/students/StudentDetailPage.tsx`

- [ ] **Step 1: Импортировать**

В верх файла:

```tsx
import { StudentBalanceBlock } from './StudentBalanceBlock';
```

- [ ] **Step 2: Поместить блок после StudentStatsBlock, перед MembershipsBlock**

Найти `<StudentStatsBlock` в JSX. Сразу после его закрытия добавить:

```tsx
<StudentBalanceBlock studentId={Number(id)} />
```

Где `id` — параметр из `useParams<{id: string}>()` (см. соседнюю переменную в файле).

- [ ] **Step 3: Typecheck**

Run: `npm run admin:typecheck`
Expected: 0 ошибок.

---

## Task 24: DirectionFormModal — поле subscription_price

**Files:**
- Modify: `web/admin/src/pages/directions/DirectionFormModal.tsx`

- [ ] **Step 1: Найти где определены state и поля формы**

Run: `cat web/admin/src/pages/directions/DirectionFormModal.tsx`

- [ ] **Step 2: Добавить state**

Рядом с другими `useState` (для `total_lessons` и `color`) добавить:

```tsx
const [subscriptionPrice, setSubscriptionPrice] = useState<string>('');
```

В `useEffect`, который заполняет форму из существующего direction, добавить:

```tsx
setSubscriptionPrice(d.subscription_price != null ? String(d.subscription_price) : '');
```

(найти секцию с другими `setColor`, `setTotalLessons` и т.д. — там же).

- [ ] **Step 3: Добавить Field в форму**

Рядом с полем `total_lessons` (или после него):

```tsx
<Field label="Цена за абонемент (₽)">
  <NumberInput
    value={subscriptionPrice}
    min={0}
    step="0.01"
    onChange={(e) => setSubscriptionPrice(e.target.value)}
    placeholder="не настроена"
  />
</Field>
```

- [ ] **Step 4: Включить в submit**

В обработчике submit, в body PATCH/POST добавить:

```tsx
subscription_price: subscriptionPrice.trim() === '' ? null : Number(subscriptionPrice),
```

- [ ] **Step 5: Typecheck**

Run: `npm run admin:typecheck`
Expected: 0 ошибок.

---

## Task 25: style.css — стили блок-селектора, баланс-блока, страницы абонементов

**Files:**
- Modify: `web/admin/src/style.css`

- [ ] **Step 1: Добавить блок стилей в конец файла**

```css
/* ===== Payments / Subscriptions ===== */

.block-selector { display: flex; flex-direction: column; gap: 8px; }
.block-selector__row { display: flex; gap: 10px; flex-wrap: wrap; }
.block-selector__legend { color: var(--text-muted); font-size: 13px; }

.block-cell {
  --dir-color: #7c3aed;
  border: 2px solid var(--dir-color);
  background: transparent;
  border-radius: 6px;
  padding: 4px 8px;
  cursor: pointer;
  font-family: monospace;
  letter-spacing: 2px;
  color: var(--dir-color);
  transition: background 100ms, transform 80ms;
}
.block-cell:hover:not(:disabled) { background: color-mix(in oklab, var(--dir-color) 18%, transparent); }
.block-cell--selected { background: var(--dir-color); color: #fff; }
.block-cell--hover { background: color-mix(in oklab, var(--dir-color) 30%, transparent); color: #fff; }
.block-cell--locked {
  background: var(--dir-color);
  color: #fff;
  opacity: 0.55;
  cursor: not-allowed;
}
.block-cell__icons { font-size: 14px; }

.payment-form { display: flex; flex-direction: column; gap: 14px; }
.payment-form__hint { font-size: 13px; color: var(--text-muted); }
.payment-form__warn {
  background: color-mix(in oklab, var(--danger, #c44) 12%, transparent);
  border-left: 3px solid var(--danger, #c44);
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 13px;
}
.payment-form__price-row { display: flex; gap: 12px; align-items: center; }
.payment-form__price { font-size: 18px; font-weight: 600; }
.payment-form__total { font-size: 16px; text-align: right; padding-top: 8px; border-top: 1px solid var(--border); }
.payment-form__footer { display: flex; justify-content: flex-end; gap: 10px; padding-top: 8px; }

.balance-block {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 20px;
  margin: 16px 0;
}
.balance-block__head {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 12px;
}
.balance-block__head h3 { margin: 0; }
.balance-block__totals {
  display: flex; gap: 24px; flex-wrap: wrap;
  padding: 10px 0; border-bottom: 1px solid var(--border);
  margin-bottom: 12px;
}
.balance-block__directions { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.balance-block__direction-row {
  display: grid;
  grid-template-columns: 12px 1fr auto auto;
  gap: 12px;
  align-items: center;
  padding: 4px 0;
}
.balance-block__direction-name { font-weight: 500; }
.balance-block__history-head { margin: 14px 0 6px; font-size: 14px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }
.balance-block__history { list-style: none; padding: 0; margin: 0; }
.balance-block__history-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 6px 0; border-top: 1px dashed var(--border);
}
.balance-block__history-row:first-child { border-top: none; }
.balance-block__history-main { font-size: 14px; }
.balance-neg { color: var(--danger, #c44); font-weight: 600; }

.nav-btn--cta {
  background: color-mix(in oklab, var(--accent, #7c3aed) 12%, transparent);
  border-left: 3px solid var(--accent, #7c3aed);
  font-weight: 600;
}
.nav-btn--cta:hover {
  background: color-mix(in oklab, var(--accent, #7c3aed) 22%, transparent);
}
```

- [ ] **Step 2: Typecheck (CSS не проверяется, но билд должен пройти)**

Run: `npm run admin:build`
Expected: bundle создаётся без ошибок, итоговый размер сопоставим с предыдущей сборкой.

---

## Task 26: End-to-end smoke в браузере

**Files:** ничего не создаём.

- [ ] **Step 1: Запустить Vite dev**

Run: `npm run admin:dev` (run_in_background=true).

- [ ] **Step 2: Запустить бэк**

Run: `npm start` (run_in_background=true).

- [ ] **Step 3: Открыть `/admin` в браузере, войти**

Логин под `admin`. Проверить, что страница не белая.

- [ ] **Step 4: Открыть `/admin/subscriptions`**

Ожидаем: таблица направлений, цены пустые («не настроено») или с числами. Кликнуть по «не настроено», ввести `7250`, Enter. Цена сохранилась.

- [ ] **Step 5: Нажать «Внести оплату» в sidebar**

Открылась модалка. Выбрать ученика → направление → один блок → дата сегодня → итого должно посчитаться. Нажать «Внести оплату» → toast «Оплата внесена: 7 250 ₽».

- [ ] **Step 6: Открыть карточку выбранного ученика**

Ожидаем: блок «Баланс» появился, показывает 4 оставшихся урока по направлению, total 4. История оплат содержит запись.

- [ ] **Step 7: Удалить оплату**

Кликнуть 🗑 → «Точно удалить?» → клик ещё раз. Toast «Оплата удалена». Блок «Баланс» либо исчез (если истории больше нет), либо показывает 0.

- [ ] **Step 8: Купить два абонемента**

Снова открыть модалку, выбрать того же ученика и направление с total_lessons=8 (2 абонемента). Селектор должен показать 2 коробки. Кликнуть по второй → 2 выбрано. Цена итого = 14 500 ₽. Внести.

- [ ] **Step 9: Попробовать купить третий**

Открыть модалку, выбрать тех же → селектор показывает 2 закрашенных, 0 свободных, кнопка submit disabled. Подпись «0 свободно».

- [ ] **Step 10: Кастомная цена**

Открыть модалку для другой пары, нажать «+ Задать свою сумму». Поле появилось. Ввести 5000. Итого пересчиталось. Внести. В истории оплат на карточке `unit_price = 5000`.

- [ ] **Step 11: Половинный урок (опционально, если есть данные)**

Если есть группа с `lesson_duration_minutes=45`, создать урок с одним present-студентом → баланс должен уменьшиться на 0.5.

- [ ] **Step 12: Остановить процессы**

Прервать обе background задачи.

---

## Self-review

После выполнения всех тасков:

- [ ] **Spec coverage**: каждое требование из спеки имеет таск.
  - subscription_price на directions → Task 1, 5, 24
  - payments table + immutable → Task 2, 6, 8 (нет PATCH endpoint)
  - cap-валидация → Task 6 (server) + Task 16 (client)
  - custom unit_price snapshot → Task 16 (кнопка)
  - per-direction + total + history → Task 22
  - старт с нуля → не нужен скрипт, дефолт payments=пусто
  - delete с warning → Task 6, 8, 22
  - sidebar entries → Task 19
  - block selector UI → Task 15
  - half-lesson 0.5 → Task 6 формула, Task 7 тест

- [ ] **Placeholder scan**: нет TODO/TBD в коде, есть имена функций/типов/полей.

- [ ] **Type consistency**:
  - `paymentCreateSchema` → `PaymentCreateInput` ✓
  - `createPayment` возвращает `{ payment }` или `{ error }` — потребитель (`routes/admin/payments.js`) ловит оба ✓
  - `deletePayment` возвращает `{ deleted, new_balance, warning? }` — клиент `PaymentDeleteResult` совпадает ✓
  - `StudentBalance.per_direction[*].balance` — number, фронт читает как number ✓

---

## Out of scope (next iterations)

- `GET /api/admin/revenue?month=YYYY-MM` — отдельный план.
- Audit log изменений payments.
- Связь оплаты с конкретной группой (только direction в v1).
- Алерты «балансы в минусе» в sidebar.
- Восстановление удалённой оплаты.
