# Admin Dashboard + ErrorBoundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить домашнюю страницу `/admin` (дашборд: 4 финансовых KPI + список долгов, всё считается по FIFO) и глобальный ErrorBoundary вокруг контента админки.

**Architecture:** Бэкенд — один эндпоинт `GET /api/admin/dashboard` (функция `getDashboard()` в `services/admin-repo.js`), который тянет все оплаты-«партии» и все посещения двумя упорядоченными запросами и считает FIFO в JS через чистую функцию `computeFifo` (`services/fifo.js`). Никаких хранимых полей — всё производно на чтении. Фронт — страница `DashboardPage` на TanStack Query, ErrorBoundary оборачивает `<Outlet/>` в `AppShell`.

**Tech Stack:** Node.js/Express, PostgreSQL (`pg`), React 19, TanStack Query v5, React Router v7, TypeScript, Vite.

**Спека:** `docs/superpowers/specs/2026-06-03-admin-dashboard-design.md`

> **⚠️ Git:** репозиторий не инициализирован (`git` нет). Шаги «Commit» оставлены как чекпоинты — либо выполни `git init` один раз в начале, либо трактуй их как точки проверки и пропускай команду `git commit`.

> **🎨 UI:** Задачи 7–9 (страница, карточки, стили, ErrorBoundary fallback) реализуются через скилл **`/design-principles`** — Linear × Stripe, токены из `web/admin/src/style.css`, без native-элементов и hardcoded значений. Вызвать скилл перед написанием JSX/CSS этих задач.

---

## File Structure

**Backend (create):**
- `services/fifo.js` — чистая `computeFifo(lots, consumptions, monthStart, monthEnd)`. Одна ответственность: FIFO-оценка списанных/остаточных денег.
- `services/fifo.test.js` — юнит-тесты `computeFifo`.
- `services/calculator.test.js` — юнит-тест нового хелпера `mskMonthRange`.
- `routes/admin/dashboard.js` — роут `GET /` (под `requireAdmin`).

**Backend (modify):**
- `services/calculator.js` — добавить и экспортировать `mskMonthRange(now)`.
- `services/admin-repo.js` — добавить и экспортировать `getDashboard()`.
- `services/admin-repo.test.js` — интеграционный тест `getDashboard()` (delta-подход).
- `routes/admin/index.js` — смонтировать dashboard-роутер под `requireAdmin`.

**Frontend (create):**
- `web/admin/src/hooks/useDashboard.ts` — `useQuery` обёртка.
- `web/admin/src/pages/dashboard/DashboardPage.tsx` — страница.
- `web/admin/src/pages/dashboard/KpiCard.tsx` — карточка KPI.
- `web/admin/src/pages/dashboard/DebtsCard.tsx` — блок долгов.
- `web/admin/src/components/shell/ErrorBoundary.tsx` — класс-компонент.

**Frontend (modify):**
- `shared/types.ts` — `DashboardData`, `DashboardDebt` (авто re-export через `web/admin/src/lib/types.ts`).
- `web/admin/src/components/shell/AppShell.tsx` — обернуть `<Outlet/>` в ErrorBoundary с reset по `location.key`.
- `web/admin/src/App.tsx` — роут `/admin/dashboard` + редирект `/admin` → dashboard + `*` → dashboard.
- `web/admin/src/components/shell/Sidebar.tsx` — секция «Дашборд» первой + иконка.
- `web/admin/src/style.css` — стили дашборда и fallback-карточки.

---

## Task 1: МСК-хелпер границ месяца

**Files:**
- Modify: `services/calculator.js`
- Test: `services/calculator.test.js` (create)

- [ ] **Step 1: Write the failing test**

Create `services/calculator.test.js`:

```js
const { test } = require('node:test');
const assert = require('node:assert');
const { mskMonthRange } = require('./calculator');

test('mskMonthRange: середина месяца', () => {
  const r = mskMonthRange(new Date('2026-06-15T12:00:00Z'));
  assert.deepStrictEqual(r, { month: '2026-06', month_start: '2026-06-01', month_end: '2026-07-01' });
});

test('mskMonthRange: декабрь → перенос года', () => {
  const r = mskMonthRange(new Date('2026-12-10T12:00:00Z'));
  assert.deepStrictEqual(r, { month: '2026-12', month_start: '2026-12-01', month_end: '2027-01-01' });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test services/calculator.test.js`
Expected: FAIL — `mskMonthRange is not a function`.

- [ ] **Step 3: Implement `mskMonthRange`**

In `services/calculator.js`, add the function (uses existing `formatMskDate`) and export it:

```js
function mskMonthRange(now = new Date()) {
    const today = formatMskDate(now); // 'YYYY-MM-DD' в МСК
    const [y, m] = today.split('-').map(Number);
    const month = `${y}-${String(m).padStart(2, '0')}`;
    const month_start = `${month}-01`;
    const ny = m === 12 ? y + 1 : y;
    const nm = m === 12 ? 1 : m + 1;
    const month_end = `${ny}-${String(nm).padStart(2, '0')}-01`;
    return { month, month_start, month_end };
}
```

Add `mskMonthRange` to the `module.exports` object:

```js
module.exports = {
    getCourseLimit,
    calculatePayment,
    calculatePenalty,
    formatMskDate,
    formatMskDateTime,
    getWeekStartMsk,
    mskMonthRange,
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test services/calculator.test.js`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add services/calculator.js services/calculator.test.js
git commit -m "feat(dashboard): add mskMonthRange helper"
```

---

## Task 2: `computeFifo` — ядро FIFO-оценки

**Files:**
- Create: `services/fifo.js`
- Test: `services/fifo.test.js`

- [ ] **Step 1: Write the failing test**

Create `services/fifo.test.js`:

```js
const { test } = require('node:test');
const assert = require('node:assert');
const { computeFifo } = require('./fifo');

const MS = '2026-06-01';
const ME = '2026-07-01';

function lessons(n, date) {
  return Array.from({ length: n }, () => ({ units: 1, date }));
}

test('пример из спеки: две партии разной цены через границу месяца', () => {
  const lots = [
    { lessons: 4, price_per_lesson: 500 }, // оплата A (старая)
    { lessons: 4, price_per_lesson: 450 }, // оплата B (со скидкой)
  ];
  const cons = [
    ...lessons(3, '2026-05-10'), // 3 урока в мае
    ...lessons(4, '2026-06-10'), // 4 урока в июне
  ];
  const r = computeFifo(lots, cons, MS, ME);
  assert.strictEqual(r.worked_off_total, 3350);  // 1500 + 1850
  assert.strictEqual(r.worked_off_month, 1850);  // июнь: 500 + 3×450
  assert.strictEqual(r.remaining_value, 450);    // 1 урок из B
  assert.strictEqual(r.over_consumed_lessons, 0);
});

test('инвариант: total_paid = worked_off_total + remaining_value (без перерасхода)', () => {
  const lots = [{ lessons: 4, price_per_lesson: 500 }, { lessons: 4, price_per_lesson: 450 }];
  const cons = lessons(5, '2026-06-10');
  const r = computeFifo(lots, cons, MS, ME);
  const totalPaid = 4 * 500 + 4 * 450; // 3800
  assert.strictEqual(r.worked_off_total + r.remaining_value, totalPaid);
});

test('half-lesson (0.5) списывается частично', () => {
  const lots = [{ lessons: 4, price_per_lesson: 500 }];
  const cons = [{ units: 0.5, date: '2026-06-10' }];
  const r = computeFifo(lots, cons, MS, ME);
  assert.strictEqual(r.worked_off_month, 250); // 0.5 × 500
  assert.strictEqual(r.remaining_value, 1750); // 3.5 × 500
});

test('перерасход: лишние уроки без цены не капают в worked_off/remaining', () => {
  const lots = [{ lessons: 4, price_per_lesson: 500 }];
  const cons = lessons(6, '2026-06-10');
  const r = computeFifo(lots, cons, MS, ME);
  assert.strictEqual(r.worked_off_total, 2000);     // только 4 оплаченных
  assert.strictEqual(r.over_consumed_lessons, 2);
  assert.strictEqual(r.remaining_value, 0);
});

test('нет партий: всё потребление — перерасход', () => {
  const r = computeFifo([], lessons(2, '2026-06-10'), MS, ME);
  assert.strictEqual(r.worked_off_total, 0);
  assert.strictEqual(r.over_consumed_lessons, 2);
  assert.strictEqual(r.remaining_value, 0);
});

test('нет потребления: всё в остатке', () => {
  const lots = [{ lessons: 4, price_per_lesson: 500 }];
  const r = computeFifo(lots, [], MS, ME);
  assert.strictEqual(r.worked_off_total, 0);
  assert.strictEqual(r.remaining_value, 2000);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test services/fifo.test.js`
Expected: FAIL — `computeFifo is not a function`.

- [ ] **Step 3: Implement `computeFifo`**

Create `services/fifo.js`:

```js
// FIFO-оценка денег по партиям-оплатам. Чистая функция, без побочных эффектов и БД.
//
// lots:         [{ lessons, price_per_lesson }]  — партии в порядке оплаты (FIFO), старые первыми.
// consumptions: [{ units, date }]               — посещения в порядке даты урока, старые первыми.
//                                                  units = 1 или 0.5; date = 'YYYY-MM-DD'.
// monthStart/monthEnd: 'YYYY-MM-DD' — полуинтервал [monthStart, monthEnd) текущего месяца.
//
// Возвращает (деньги округлены до копеек):
//   worked_off_total     — стоимость всех списанных уроков;
//   worked_off_month     — стоимость уроков, чья дата в [monthStart, monthEnd);
//   remaining_value      — стоимость несписанных партий;
//   over_consumed_lessons — объём уроков сверх оплаченных партий (долг, без цены).
function computeFifo(lots, consumptions, monthStart, monthEnd) {
  let lotIdx = 0;
  let lotRemaining = lots.length ? lots[0].lessons : 0;
  let worked_off_total = 0;
  let worked_off_month = 0;
  let over_consumed_lessons = 0;

  for (const c of consumptions) {
    let need = c.units;
    const inMonth = c.date >= monthStart && c.date < monthEnd;
    while (need > 0 && lotIdx < lots.length) {
      if (lotRemaining <= 0) {
        lotIdx++;
        if (lotIdx >= lots.length) break;
        lotRemaining = lots[lotIdx].lessons;
        continue;
      }
      const take = Math.min(need, lotRemaining);
      const value = take * lots[lotIdx].price_per_lesson;
      worked_off_total += value;
      if (inMonth) worked_off_month += value;
      lotRemaining -= take;
      need -= take;
    }
    if (need > 0) {
      over_consumed_lessons += need; // партии кончились
    }
  }

  let remaining_value = 0;
  if (lotIdx < lots.length) {
    remaining_value += lotRemaining * lots[lotIdx].price_per_lesson;
    for (let i = lotIdx + 1; i < lots.length; i++) {
      remaining_value += lots[i].lessons * lots[i].price_per_lesson;
    }
  }

  const r = (x) => Math.round(x * 100) / 100;
  return {
    worked_off_total: r(worked_off_total),
    worked_off_month: r(worked_off_month),
    remaining_value: r(remaining_value),
    over_consumed_lessons: r(over_consumed_lessons),
  };
}

module.exports = { computeFifo };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test services/fifo.test.js`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add services/fifo.js services/fifo.test.js
git commit -m "feat(dashboard): add computeFifo FIFO valuation"
```

---

## Task 3: `getDashboard()` в admin-repo

**Files:**
- Modify: `services/admin-repo.js`
- Test: `services/admin-repo.test.js`

> Требуется запущенный PostgreSQL с применёнными миграциями (как для остальных тестов в этом файле). Тест использует **delta-подход** (снимок до/после вставки фикстур), потому что `getDashboard` агрегирует всю БД.

- [ ] **Step 1: Write the failing test**

Append to `services/admin-repo.test.js` (before any final cleanup; file already imports `repo`, `pool`, `test`, `assert`):

```js
test('getDashboard: FIFO-агрегаты (delta) + долги', async () => {
  const NOW = new Date('2026-06-15T12:00:00Z');
  const round2 = (x) => Math.round(x * 100) / 100;

  const dir = await pool.query(
    `INSERT INTO directions (name, sheet_name, is_individual, total_lessons)
     VALUES ('__T_DASH_DIR__', 'X', false, 100) RETURNING id`);
  const te = await pool.query(
    `INSERT INTO teachers (name) VALUES ('__T_DASH_TE__') RETURNING id`);
  const grp = await pool.query(
    `INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes)
     VALUES ('__T_DASH_G__', $1, $2, false, 90) RETURNING id`,
    [dir.rows[0].id, te.rows[0].id]);
  const s1 = await pool.query(`INSERT INTO students (full_name) VALUES ('__T_DASH_S1__') RETURNING id`);
  const s2 = await pool.query(`INSERT INTO students (full_name) VALUES ('__T_DASH_S2__') RETURNING id`);
  const dirId = dir.rows[0].id, grpId = grp.rows[0].id;
  const s1Id = s1.rows[0].id, s2Id = s2.rows[0].id;

  // helper: создать урок на дату и отметить присутствие набора учеников
  async function lesson(date, studentIds) {
    const l = await pool.query(
      `INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number,
                            lesson_duration_minutes, lesson_type, submitted_by_token)
       VALUES ($1, $2, $3, 1, 90, 'regular', 'test') RETURNING id`,
      [grpId, te.rows[0].id, date]);
    for (const sid of studentIds) {
      await pool.query(
        `INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES ($1, $2, true)`,
        [l.rows[0].id, sid]);
    }
    return l.rows[0].id;
  }
  async function payment(studentId, paidAt, unitPrice) {
    await pool.query(
      `INSERT INTO payments (student_id, direction_id, subscriptions_count, unit_price, total_amount, paid_at, created_by)
       VALUES ($1, $2, 1, $3, $3, $4, 'test')`,
      [studentId, dirId, unitPrice, paidAt]);
  }

  const before = await repo.getDashboard({ now: NOW });

  // S1: три партии (500/450/250 за урок); потребление 3 в мае + 4 в июне
  await payment(s1Id, '2026-05-02', 2000); // 4 урока @500
  await payment(s1Id, '2026-05-20', 1800); // 4 урока @450
  await payment(s1Id, '2026-06-10', 1000); // 4 урока @250  ← оплата в июне
  // S2: одна партия 4 урока @500; потребление 2 мая + 4 июня = 6 (перерасход на 2)
  await payment(s2Id, '2026-05-05', 2000);

  // уроки мая
  await lesson('2026-05-10', [s1Id, s2Id]);
  await lesson('2026-05-11', [s1Id, s2Id]);
  await lesson('2026-05-12', [s1Id]);
  // уроки июня
  await lesson('2026-06-03', [s1Id, s2Id]);
  await lesson('2026-06-04', [s1Id, s2Id]);
  await lesson('2026-06-05', [s1Id, s2Id]);
  await lesson('2026-06-06', [s1Id, s2Id]);

  const after = await repo.getDashboard({ now: NOW });

  // revenue: только июньская оплата S1 = 1000
  assert.strictEqual(round2(after.revenue_month - before.revenue_month), 1000);
  // worked_off_month: S1 1850 + S2 1000 = 2850
  assert.strictEqual(round2(after.worked_off_month - before.worked_off_month), 2850);
  // deferred_total: S1 остаток (1×450 + 4×250 = 1450) + S2 0 = 1450
  assert.strictEqual(round2(after.deferred_total - before.deferred_total), 1450);
  // carryover = revenue - worked_off (глобально)
  assert.strictEqual(after.carryover_month, round2(after.revenue_month - after.worked_off_month));
  // долг: S2 должен присутствовать с балансом -2 (4 куплено − 6 посещено)
  const s2debt = after.debts.find((d) => d.student_id === s2Id && d.direction_id === dirId);
  assert.ok(s2debt, 'S2 в списке долгов');
  assert.strictEqual(s2debt.balance, -2);
  assert.strictEqual(s2debt.student_name, '__T_DASH_S2__');
  // S1 в плюсе → не долг
  assert.ok(!after.debts.find((d) => d.student_id === s1Id), 'S1 не в долгах');

  // cleanup
  await pool.query(`DELETE FROM payments WHERE student_id = ANY($1)`, [[s1Id, s2Id]]);
  await pool.query(`DELETE FROM lesson_attendance la USING lessons l
                    WHERE la.lesson_id = l.id AND l.group_id = $1`, [grpId]);
  await pool.query(`DELETE FROM lessons WHERE group_id = $1`, [grpId]);
  await pool.query(`DELETE FROM students WHERE id = ANY($1)`, [[s1Id, s2Id]]);
  await pool.query(`DELETE FROM groups WHERE id = $1`, [grpId]);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [te.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id = $1`, [dirId]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test services/admin-repo.test.js`
Expected: FAIL — `repo.getDashboard is not a function`.

- [ ] **Step 3: Implement `getDashboard`**

In `services/admin-repo.js`, add `require` at top (near other requires):

```js
const { mskMonthRange } = require('./calculator');
const { computeFifo } = require('./fifo');
```

Add the function (e.g. after `getStudentBalance`):

```js
function _round2(x) { return Math.round(x * 100) / 100; }

async function getDashboard({ now = new Date() } = {}) {
  const { month, month_start, month_end } = mskMonthRange(now);

  const revRes = await pool.query(
    `SELECT COALESCE(SUM(total_amount), 0)::numeric AS total
       FROM payments WHERE paid_at >= $1 AND paid_at < $2`,
    [month_start, month_end],
  );
  const revenue_month = _round2(Number(revRes.rows[0].total));

  const lotsRes = await pool.query(
    `SELECT student_id, direction_id, total_amount, subscriptions_count
       FROM payments
      WHERE direction_id IS NOT NULL
      ORDER BY student_id, direction_id, paid_at, id`,
  );
  const consRes = await pool.query(
    `SELECT la.student_id, g.direction_id, l.lesson_date,
            CASE WHEN l.lesson_duration_minutes = 45 THEN 0.5 ELSE 1 END AS units
       FROM lesson_attendance la
       JOIN lessons l ON l.id = la.lesson_id
       JOIN groups  g ON g.id = l.group_id
      WHERE la.present = true
      ORDER BY la.student_id, g.direction_id, l.lesson_date, l.id`,
  );

  const lotsByKey = new Map();
  const purchasedByKey = new Map();
  for (const r of lotsRes.rows) {
    const key = `${r.student_id}:${r.direction_id}`;
    const lessons = Number(r.subscriptions_count) * 4;
    if (!lotsByKey.has(key)) lotsByKey.set(key, []);
    lotsByKey.get(key).push({ lessons, price_per_lesson: Number(r.total_amount) / lessons });
    purchasedByKey.set(key, (purchasedByKey.get(key) || 0) + lessons);
  }

  const consByKey = new Map();
  const consumedByKey = new Map();
  for (const r of consRes.rows) {
    const key = `${r.student_id}:${r.direction_id}`;
    const units = Number(r.units);
    if (!consByKey.has(key)) consByKey.set(key, []);
    consByKey.get(key).push({ units, date: r.lesson_date });
    consumedByKey.set(key, (consumedByKey.get(key) || 0) + units);
  }

  let worked_off_month = 0;
  let deferred_total = 0;
  const debtKeys = [];
  const keys = new Set([...lotsByKey.keys(), ...consByKey.keys()]);
  for (const key of keys) {
    const lots = lotsByKey.get(key) || [];
    const cons = consByKey.get(key) || [];
    const fifo = computeFifo(lots, cons, month_start, month_end);
    worked_off_month += fifo.worked_off_month;
    deferred_total += fifo.remaining_value;
    const balance = (purchasedByKey.get(key) || 0) - (consumedByKey.get(key) || 0);
    if (balance < 0) {
      const [sid, did] = key.split(':').map(Number);
      debtKeys.push({ student_id: sid, direction_id: did, balance: _round2(balance) });
    }
  }
  worked_off_month = _round2(worked_off_month);
  deferred_total = _round2(deferred_total);
  const carryover_month = _round2(revenue_month - worked_off_month);

  debtKeys.sort((a, b) => a.balance - b.balance);
  const debts_total = debtKeys.length;
  const topDebts = debtKeys.slice(0, 8);

  const studentIds = [...new Set(topDebts.map((d) => d.student_id))];
  const directionIds = [...new Set(topDebts.map((d) => d.direction_id))];
  const sMap = new Map();
  const dMap = new Map();
  if (studentIds.length) {
    const sRes = await pool.query(`SELECT id, full_name FROM students WHERE id = ANY($1)`, [studentIds]);
    for (const r of sRes.rows) sMap.set(r.id, r.full_name);
  }
  if (directionIds.length) {
    const dRes = await pool.query(`SELECT id, name, color FROM directions WHERE id = ANY($1)`, [directionIds]);
    for (const r of dRes.rows) dMap.set(r.id, r);
  }
  const debts = topDebts.map((d) => ({
    student_id: d.student_id,
    student_name: sMap.get(d.student_id) || '—',
    direction_id: d.direction_id,
    direction_name: dMap.get(d.direction_id) ? dMap.get(d.direction_id).name : '—',
    direction_color: dMap.get(d.direction_id) ? dMap.get(d.direction_id).color : null,
    balance: d.balance,
  }));

  return { month, revenue_month, worked_off_month, carryover_month, deferred_total, debts, debts_total };
}
```

Add `getDashboard` to `module.exports` (append to the existing exports object):

```js
  // dashboard
  getDashboard,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test services/admin-repo.test.js`
Expected: PASS (including new `getDashboard` test).

- [ ] **Step 5: Commit**

```bash
git add services/admin-repo.js services/admin-repo.test.js
git commit -m "feat(dashboard): add getDashboard aggregation"
```

---

## Task 4: Dashboard-роут

**Files:**
- Create: `routes/admin/dashboard.js`
- Modify: `routes/admin/index.js`

- [ ] **Step 1: Create the route**

Create `routes/admin/dashboard.js`:

```js
const express = require('express');
const adminRepo = require('../../services/admin-repo');
const asyncWrap = require('../middleware/async-wrap');

const router = express.Router();

router.get('/', asyncWrap(async (req, res) => {
  res.json(await adminRepo.getDashboard());
}));

module.exports = router;
```

- [ ] **Step 2: Mount it under requireAdmin**

In `routes/admin/index.js`, add the require (with the other routers):

```js
const dashboardRouter   = require('./dashboard');
```

And mount it (with the other `requireAdmin` mounts):

```js
router.use('/dashboard',         requireAdmin, dashboardRouter);
```

- [ ] **Step 3: Smoke-test the endpoint**

Start the server (`npm start`) in one shell. In another, with a valid admin cookie (or temporarily via browser devtools after login), hit `GET /api/admin/dashboard`. Expected: `200` with JSON keys `month, revenue_month, worked_off_month, carryover_month, deferred_total, debts, debts_total`. Without auth: `401`.

Quick unauth check (no cookie → 401):

Run: `curl -i http://localhost:3000/api/admin/dashboard`
Expected: `HTTP/1.1 401`.

- [ ] **Step 4: Run full backend test suite (no regressions)**

Run: `npm test`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add routes/admin/dashboard.js routes/admin/index.js
git commit -m "feat(dashboard): add GET /api/admin/dashboard route"
```

---

## Task 5: Тип `DashboardData`

**Files:**
- Modify: `shared/types.ts`

> `web/admin/src/lib/types.ts` уже делает `export * from '../../../../shared/types'`, поэтому отдельный re-export не нужен.

- [ ] **Step 1: Add the types**

Append to `shared/types.ts`:

```ts
export interface DashboardDebt {
  student_id: number;
  student_name: string;
  direction_id: number;
  direction_name: string;
  direction_color: string | null;
  balance: number; // в уроках, < 0
}

export interface DashboardData {
  month: string;            // 'YYYY-MM'
  revenue_month: number;    // собрано за месяц
  worked_off_month: number; // отработано за месяц (FIFO)
  carryover_month: number;  // revenue_month − worked_off_month (может быть < 0)
  deferred_total: number;   // снимок несписанных партий, ≥ 0
  debts: DashboardDebt[];   // топ-8 худших
  debts_total: number;      // всего пар с долгом
}
```

- [ ] **Step 2: Typecheck**

Run: `npm run admin:typecheck`
Expected: PASS (no new errors).

- [ ] **Step 3: Commit**

```bash
git add shared/types.ts
git commit -m "feat(dashboard): add DashboardData types"
```

---

## Task 6: `useDashboard` hook

**Files:**
- Create: `web/admin/src/hooks/useDashboard.ts`

- [ ] **Step 1: Create the hook**

Create `web/admin/src/hooks/useDashboard.ts`:

```ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { DashboardData } from '../lib/types';

export function useDashboard() {
  return useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api<DashboardData>('GET', '/api/admin/dashboard'),
    staleTime: 30_000,
  });
}
```

- [ ] **Step 2: Typecheck**

Run: `npm run admin:typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/admin/src/hooks/useDashboard.ts
git commit -m "feat(dashboard): add useDashboard hook"
```

---

## Task 7: ErrorBoundary

**Files:**
- Create: `web/admin/src/components/shell/ErrorBoundary.tsx`
- Modify: `web/admin/src/components/shell/AppShell.tsx`
- Modify: `web/admin/src/style.css`

> 🎨 Стилизацию fallback-карточки делать через `/design-principles` (токены, без hardcoded). JSX ниже — каркас с семантическими классами.

- [ ] **Step 1: Create the ErrorBoundary component**

Create `web/admin/src/components/shell/ErrorBoundary.tsx`:

```tsx
import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props { children: ReactNode }
interface State { hasError: boolean }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Полная ошибка/стек — только в консоль, не в UI.
    console.error('[admin] render error:', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-fallback">
          <h2 className="error-fallback__title">Что-то пошло не так</h2>
          <p className="error-fallback__text">Страница не отрисовалась. Попробуйте перезагрузить.</p>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => window.location.reload()}
          >
            Перезагрузить
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
```

- [ ] **Step 2: Wire into AppShell with reset on navigation**

In `web/admin/src/components/shell/AppShell.tsx`, import the boundary:

```tsx
import { ErrorBoundary } from './ErrorBoundary';
```

Wrap the `<Outlet/>` and key it by `location.key` so the boundary resets on navigation (note: `location` is already in scope via `useLocation()` at line 26):

```tsx
        <main className="main" id="admin-main">
          <ErrorBoundary key={location.key}>
            <Outlet />
          </ErrorBoundary>
        </main>
```

- [ ] **Step 3: Add fallback styles (via `/design-principles`)**

Invoke `/design-principles`, then add to `web/admin/src/style.css` a `.error-fallback` block using tokens (centered card, `--space-*` padding, `--r` radius, `--border`, `--shadow-modal`, `--font-display` title). Reuse the existing button class for «Перезагрузить» (confirm the project's primary button class name in `style.css`; the JSX uses `btn btn--primary` — adjust to the actual class if different).

- [ ] **Step 4: Verify manually**

Temporarily add `throw new Error('boom')` at the top of `DebtsCard`/any rendered page, run `npm run admin:dev`, confirm: sidebar stays alive, fallback card shows, «Перезагрузить» works, and navigating away (after removing the throw) recovers. Remove the temporary throw.

- [ ] **Step 5: Typecheck + commit**

Run: `npm run admin:typecheck`
Expected: PASS.

```bash
git add web/admin/src/components/shell/ErrorBoundary.tsx web/admin/src/components/shell/AppShell.tsx web/admin/src/style.css
git commit -m "feat(admin): add ErrorBoundary around content"
```

---

## Task 8: Dashboard page + cards

**Files:**
- Create: `web/admin/src/pages/dashboard/KpiCard.tsx`
- Create: `web/admin/src/pages/dashboard/DebtsCard.tsx`
- Create: `web/admin/src/pages/dashboard/DashboardPage.tsx`
- Modify: `web/admin/src/style.css`

> 🎨 Invoke `/design-principles` before writing JSX/CSS here. The JSX below is the functional skeleton with semantic class names; the skill produces the exact token-based styling (4 KPI cards in a row → 2×2 → stack; debts block full-width; `--font-mono tabular-nums` for numbers; «Авансы» sign colored by meaning).

- [ ] **Step 1: KpiCard**

Create `web/admin/src/pages/dashboard/KpiCard.tsx`:

```tsx
interface Props {
  label: string;
  value: string;
  hint?: string;
  tone?: 'default' | 'info' | 'warning';
}

export function KpiCard({ label, value, hint, tone = 'default' }: Props) {
  return (
    <div className={`kpi-card kpi-card--${tone}`}>
      <div className="kpi-card__label">{label}</div>
      <div className="kpi-card__value">{value}</div>
      {hint && <div className="kpi-card__hint">{hint}</div>}
    </div>
  );
}
```

- [ ] **Step 2: DebtsCard**

Create `web/admin/src/pages/dashboard/DebtsCard.tsx`:

```tsx
import { EntityLink } from '../../components/EntityLink';
import { EmptyState } from '../../components/ui/EmptyState';
import { fmtLessons } from '../../lib/format';
import type { DashboardDebt } from '../../lib/types';
import { Link } from 'react-router-dom';

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
            <li key={`${d.student_id}:${d.direction_id}`} className="dash-debts__row">
              <span className="dash-debts__name">
                <EntityLink section="students" id={d.student_id} text={d.student_name} />
              </span>
              <span className="dash-debts__balance mono">{fmtLessons(d.balance)}</span>
              <span className="dash-debts__dir">{d.direction_name}</span>
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

- [ ] **Step 3: DashboardPage**

Create `web/admin/src/pages/dashboard/DashboardPage.tsx`:

```tsx
import { useDashboard } from '../../hooks/useDashboard';
import { fmtRub } from '../../lib/format';
import { PageLoading } from '../../components/ui/Skeleton';
import { KpiCard } from './KpiCard';
import { DebtsCard } from './DebtsCard';

const MONTHS_RU = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

function monthLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  return `${MONTHS_RU[m - 1]} ${y}`;
}

function signedRub(v: number): string {
  return v > 0 ? `+${fmtRub(v)}` : fmtRub(v);
}

export default function DashboardPage() {
  const { data, isLoading, isError } = useDashboard();

  if (isLoading) return <PageLoading />;
  if (isError || !data) return <div className="page-error">Не удалось загрузить дашборд</div>;

  return (
    <div className="dashboard">
      <header className="dashboard__head">
        <h1 className="dashboard__title">Дашборд</h1>
        <span className="dashboard__month">{monthLabel(data.month)}</span>
      </header>

      <div className="dashboard__kpis">
        <KpiCard label="Выручка за месяц" value={fmtRub(data.revenue_month)} hint="собрано" />
        <KpiCard label="Отработано за месяц" value={fmtRub(data.worked_off_month)} hint="FIFO" />
        <KpiCard
          label="Авансы за месяц"
          value={signedRub(data.carryover_month)}
          hint="выручка − отработано"
          tone={data.carryover_month < 0 ? 'warning' : 'info'}
        />
        <KpiCard label="Остаток всего" value={fmtRub(data.deferred_total)} hint="не отработано" />
      </div>

      <DebtsCard debts={data.debts} total={data.debts_total} />
    </div>
  );
}
```

- [ ] **Step 4: Styles (via `/design-principles`)**

Invoke `/design-principles`, then add `.dashboard`, `.dashboard__kpis` (responsive grid 4→2→1), `.kpi-card` (+ `--info`/`--warning` tone via tokens), `.dash-card`, `.dash-debts` styles to `web/admin/src/style.css`. Numbers use `--font-mono` + `tabular-nums`; titles `--font-display`; cards single border + `--shadow-modal` + `--r`; spacing on `--space-*`.

- [ ] **Step 5: Typecheck**

Run: `npm run admin:typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/admin/src/pages/dashboard/ web/admin/src/style.css
git commit -m "feat(dashboard): add DashboardPage with KPI cards and debts"
```

---

## Task 9: Роутинг + sidebar

**Files:**
- Modify: `web/admin/src/App.tsx`
- Modify: `web/admin/src/components/shell/Sidebar.tsx`

- [ ] **Step 1: Add route + change redirects**

In `web/admin/src/App.tsx`, add the import:

```tsx
import DashboardPage from './pages/dashboard/DashboardPage';
```

Change the index redirect and add the route (inside `<Route element={<AppShell />}>`):

```tsx
            <Route path="/admin" element={<Navigate to="/admin/dashboard" replace />} />
            <Route path="/admin/dashboard" element={<DashboardPage />} />
```

And change the catch-all at the bottom:

```tsx
            <Route path="*" element={<Navigate to="/admin/dashboard" replace />} />
```

- [ ] **Step 2: Add sidebar section + icon**

In `web/admin/src/components/shell/Sidebar.tsx`, add an icon to `NAV_ICONS` (home/grid):

```tsx
  dashboard: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="9" rx="1"/>
      <rect x="14" y="3" width="7" height="5" rx="1"/>
      <rect x="14" y="12" width="7" height="9" rx="1"/>
      <rect x="3" y="16" width="7" height="5" rx="1"/>
    </svg>
  ),
```

Add the section as the **first** entry in `SECTIONS`:

```tsx
export const SECTIONS = [
  { key: 'dashboard', label: 'Дашборд', path: '/admin/dashboard' },
  { key: 'students', label: 'Ученики', path: '/admin/students' },
  // … остальные без изменений
```

- [ ] **Step 3: Typecheck + build**

Run: `npm run admin:typecheck`
Expected: PASS.

Run: `npm run admin:build`
Expected: build succeeds → `public/admin-dist/`.

- [ ] **Step 4: Manual smoke**

Run `npm run admin:dev` (with backend on :3000). Log in, confirm: `/admin` redirects to `/admin/dashboard`; sidebar shows «Дашборд» first and it's active; 4 KPI cards render with values; debts list shows (or «Долгов нет»); clicking a debtor opens the student card; unknown URL redirects to dashboard.

- [ ] **Step 5: Commit**

```bash
git add web/admin/src/App.tsx web/admin/src/components/shell/Sidebar.tsx
git commit -m "feat(dashboard): route dashboard as admin home + sidebar entry"
```

---

## Task 10: Финальная проверка

- [ ] **Step 1: Full backend suite**

Run: `npm test`
Expected: all PASS.

- [ ] **Step 2: Frontend typecheck + build**

Run: `npm run admin:typecheck && npm run admin:build`
Expected: both succeed.

- [ ] **Step 3: Design-principles review of UI**

Re-open dashboard + ErrorBoundary fallback. Verify against design rules: no native form elements, no hardcoded colors/radii, single accent, color only for meaning (warning sign on negative carryover), 4px-grid spacing, mono tabular-nums for numbers, card surfaces consistent (one border + `--shadow-modal`). Fix any drift via `/design-principles`.

- [ ] **Step 4: Final commit (if any fixes)**

```bash
git add -A
git commit -m "chore(dashboard): design polish + final checks"
```

---

## Self-Review Notes

- **Spec coverage:** §2 metrics → Tasks 2–3, 8; §4 FIFO → Tasks 2–3; §5 endpoint → Task 4; §6 ErrorBoundary → Task 7; §7 wiring → Tasks 6, 8, 9; §9 perf/security (admin-only, no params, `staleTime`, server-truncated debts to 8 + `debts_total`) → Tasks 3, 4, 6; §10 tests → Tasks 1–3; §3/§7 `/design-principles` → Tasks 7–8, 10.
- **Note vs spec:** added `debts_total` to the response (not in the spec's example JSON) to honor §9 server-side truncation to 8 while still rendering «…ещё N». Harmless additive field.
- **«Уроки сегодня» / per-payment «отработан»** — intentionally out of scope (spec §12).
- **Type consistency:** `DashboardData`/`DashboardDebt` fields match `getDashboard()` return and page usage; `computeFifo` return keys (`worked_off_total/worked_off_month/remaining_value/over_consumed_lessons`) consistent across Tasks 2–3.
