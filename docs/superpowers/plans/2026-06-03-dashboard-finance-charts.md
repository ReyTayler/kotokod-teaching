# Dashboard Finance Charts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`. Repo NOT under git — skip commits.

**Goal:** Два помесячных area-графика (Выручка / Отработано) на дашборде с выбором года; данные из нового `GET /api/admin/dashboard/monthly?year=`.

**Architecture:** `computeFifo` расширяется полем `worked_off_by_month`; `getMonthlyFinance()` собирает 12-месячный ряд (revenue через GROUP BY, worked_off через FIFO-карту); фронт рисует на **Recharts 3** (уже установлен).

**Tech:** Node/Express, PostgreSQL, React 19, TanStack Query, Recharts 3.8, TypeScript.

**Спека:** `docs/superpowers/specs/2026-06-03-dashboard-finance-charts.md`

---

## Task 1: `computeFifo` → `worked_off_by_month`

**Files:** `services/fifo.js`, `services/fifo.test.js`

- [ ] **Step 1: Add failing test** to `services/fifo.test.js`:
```js
test('worked_off_by_month: раскладывает списания по месяцам урока', () => {
  const lots = [{ lessons: 4, price_per_lesson: 500 }, { lessons: 4, price_per_lesson: 450 }];
  const cons = [
    ...Array.from({ length: 3 }, () => ({ units: 1, date: '2026-05-10' })),
    ...Array.from({ length: 4 }, () => ({ units: 1, date: '2026-06-10' })),
  ];
  const r = computeFifo(lots, cons, '2026-06-01', '2026-07-01');
  assert.strictEqual(r.worked_off_by_month['2026-05'], 1500);
  assert.strictEqual(r.worked_off_by_month['2026-06'], 1850);
});
```
- [ ] **Step 2:** Run `node --test services/fifo.test.js` → expect new test FAIL (`worked_off_by_month` undefined).
- [ ] **Step 3:** In `services/fifo.js`, accumulate a per-month map. Inside the `while (need > 0 ...)` loop, right after `worked_off_total += value;`, add:
```js
      const ym = c.date.slice(0, 7);
      byMonth[ym] = (byMonth[ym] || 0) + value;
```
Declare `const byMonth = {};` near the other accumulators (before the `for` loop). In the final return object add:
```js
    worked_off_by_month: Object.fromEntries(Object.entries(byMonth).map(([k, v]) => [k, Math.round(v * 100) / 100])),
```
- [ ] **Step 4:** Run `node --test services/fifo.test.js` → all PASS (7 tests).

---

## Task 2: `getMonthlyFinance()` + DRY-рефактор inputs

**Files:** `services/admin-repo.js`, `services/admin-repo.test.js`

- [ ] **Step 1: Add failing test** to `services/admin-repo.test.js` (append; reuse `repo`, `pool`):
```js
test('getMonthlyFinance: помесячный ряд revenue/worked_off + available_years', async () => {
  const round2 = (x) => Math.round(x * 100) / 100;
  const dir = await pool.query(`INSERT INTO directions (name, sheet_name, is_individual, total_lessons) VALUES ('__T_MF_DIR__','X',false,100) RETURNING id`);
  const te = await pool.query(`INSERT INTO teachers (name) VALUES ('__T_MF_TE__') RETURNING id`);
  const grp = await pool.query(`INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes) VALUES ('__T_MF_G__',$1,$2,false,90) RETURNING id`, [dir.rows[0].id, te.rows[0].id]);
  const st = await pool.query(`INSERT INTO students (full_name) VALUES ('__T_MF_S__') RETURNING id`);
  const dirId = dir.rows[0].id, grpId = grp.rows[0].id, stId = st.rows[0].id;
  const lesson = async (date) => {
    const l = await pool.query(`INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, lesson_duration_minutes, lesson_type, submitted_by_token) VALUES ($1,$2,$3,1,90,'regular','test') RETURNING id`, [grpId, te.rows[0].id, date]);
    await pool.query(`INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES ($1,$2,true)`, [l.rows[0].id, stId]);
  };

  // одна оплата: 4 урока @500 (paid May 2026); 2 урока в мае, 1 в июне
  await pool.query(`INSERT INTO payments (student_id, direction_id, subscriptions_count, unit_price, total_amount, paid_at, created_by) VALUES ($1,$2,1,2000,2000,'2026-05-02','test')`, [stId, dirId]);
  await lesson('2026-05-10'); await lesson('2026-05-11'); await lesson('2026-06-05');

  const before = await repo.getMonthlyFinance({ year: 2026 });
  // baseline для delta по нашим месяцам не нужен, т.к. суммы глобальные — проверяем через прямой расчёт делты:
  // вместо delta используем то, что наши данные единственные для этого направления; но revenue/worked_off глобальны.
  // Поэтому проверяем СТРУКТУРУ + что наш месяц не пустой и available_years содержит 2026.
  assert.strictEqual(before.year, 2026);
  assert.strictEqual(before.series.length, 12);
  assert.strictEqual(before.series[0].month, 1);
  assert.strictEqual(before.series[11].month, 12);
  assert.ok(before.available_years.includes(2026));
  // worked_off для мая (index 4) и июня (index 5) должны включать наш вклад (≥ значения)
  assert.ok(before.series[4].worked_off >= 1000); // май: 2×500
  assert.ok(before.series[5].worked_off >= 500);  // июнь: 1×500
  assert.ok(before.series[4].revenue >= 2000);    // май: оплата 2000

  await pool.query(`DELETE FROM payments WHERE student_id=$1`, [stId]);
  await pool.query(`DELETE FROM lesson_attendance la USING lessons l WHERE la.lesson_id=l.id AND l.group_id=$1`, [grpId]);
  await pool.query(`DELETE FROM lessons WHERE group_id=$1`, [grpId]);
  await pool.query(`DELETE FROM students WHERE id=$1`, [stId]);
  await pool.query(`DELETE FROM groups WHERE id=$1`, [grpId]);
  await pool.query(`DELETE FROM teachers WHERE id=$1`, [te.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id=$1`, [dirId]);
});
```
- [ ] **Step 2:** Run `node --test services/admin-repo.test.js` → new test FAIL (`getMonthlyFinance` not a function).
- [ ] **Step 3:** Refactor + implement in `services/admin-repo.js`.
  1. Extract a private helper from `getDashboard`'s lots/cons loading (lines that build `lotsByKey/purchasedByKey/consByKey/consumedByKey/keys`) into:
```js
async function _fifoInputs() {
  const lotsRes = await pool.query(`SELECT student_id, direction_id, total_amount, subscriptions_count FROM payments WHERE direction_id IS NOT NULL ORDER BY student_id, direction_id, paid_at, id`);
  const consRes = await pool.query(`SELECT la.student_id, g.direction_id, l.lesson_date, CASE WHEN l.lesson_duration_minutes = 45 THEN 0.5 ELSE 1 END AS units FROM lesson_attendance la JOIN lessons l ON l.id = la.lesson_id JOIN groups g ON g.id = l.group_id WHERE la.present = true ORDER BY la.student_id, g.direction_id, l.lesson_date, l.id`);
  const lotsByKey = new Map(), purchasedByKey = new Map();
  for (const r of lotsRes.rows) { const key = `${r.student_id}:${r.direction_id}`; const lessons = Number(r.subscriptions_count) * 4; if (!lotsByKey.has(key)) lotsByKey.set(key, []); lotsByKey.get(key).push({ lessons, price_per_lesson: Number(r.total_amount) / lessons }); purchasedByKey.set(key, (purchasedByKey.get(key) || 0) + lessons); }
  const consByKey = new Map(), consumedByKey = new Map();
  for (const r of consRes.rows) { const key = `${r.student_id}:${r.direction_id}`; const units = Number(r.units); if (!consByKey.has(key)) consByKey.set(key, []); consByKey.get(key).push({ units, date: r.lesson_date }); consumedByKey.set(key, (consumedByKey.get(key) || 0) + units); }
  const keys = new Set([...lotsByKey.keys(), ...consByKey.keys()]);
  return { lotsByKey, purchasedByKey, consByKey, consumedByKey, keys };
}
```
  Update `getDashboard` to call `const { lotsByKey, purchasedByKey, consByKey, consumedByKey, keys } = await _fifoInputs();` and delete the inlined loading it replaces (keep everything else identical).
  2. Add `getMonthlyFinance`:
```js
async function getMonthlyFinance({ year = null, now = new Date() } = {}) {
  const y = year || Number(mskMonthRange(now).month.slice(0, 4));
  const yearStart = `${y}-01-01`, nextYearStart = `${y + 1}-01-01`;

  const yrs = await pool.query(`SELECT DISTINCT yy FROM (SELECT EXTRACT(YEAR FROM paid_at)::int AS yy FROM payments UNION SELECT EXTRACT(YEAR FROM lesson_date)::int AS yy FROM lessons) t WHERE yy IS NOT NULL ORDER BY yy`);
  const available_years = yrs.rows.map((r) => r.yy);
  if (!available_years.includes(y)) { available_years.push(y); available_years.sort((a, b) => a - b); }

  const rev = await pool.query(`SELECT EXTRACT(MONTH FROM paid_at)::int AS m, COALESCE(SUM(total_amount),0)::numeric AS rev FROM payments WHERE paid_at >= $1 AND paid_at < $2 GROUP BY m`, [yearStart, nextYearStart]);
  const revByMonth = new Map(rev.rows.map((r) => [r.m, Number(r.rev)]));

  const { lotsByKey, consByKey, keys } = await _fifoInputs();
  const workedByYm = new Map();
  for (const key of keys) {
    const fifo = computeFifo(lotsByKey.get(key) || [], consByKey.get(key) || [], '0001-01-01', '9999-12-31');
    for (const [ym, val] of Object.entries(fifo.worked_off_by_month)) workedByYm.set(ym, (workedByYm.get(ym) || 0) + val);
  }

  const series = [];
  for (let m = 1; m <= 12; m++) {
    const ym = `${y}-${String(m).padStart(2, '0')}`;
    series.push({ month: m, revenue: _round2(revByMonth.get(m) || 0), worked_off: _round2(workedByYm.get(ym) || 0) });
  }
  return { year: y, available_years, series };
}
```
  3. Add `getMonthlyFinance` to `module.exports`.
- [ ] **Step 4:** Run `node --test services/admin-repo.test.js` → all PASS. Then `npm test` → no regressions (getDashboard refactor intact).

---

## Task 3: `/monthly` route

**Files:** `routes/admin/dashboard.js`

- [ ] **Step 1:** Add a second handler (keep existing `GET /`):
```js
const YEAR_RE = /^\d{4}$/;
router.get('/monthly', asyncWrap(async (req, res) => {
  const { year } = req.query;
  if (year && !YEAR_RE.test(year)) return res.status(400).json({ error: 'invalid_year' });
  res.json(await adminRepo.getMonthlyFinance({ year: year ? Number(year) : null }));
}));
```
- [ ] **Step 2:** Verify load: `node -e "require('./routes/admin/index.js'); console.log('ok')"`. Unauth smoke: `curl -i http://localhost:3000/api/admin/dashboard/monthly` (with server up) → 401.

---

## Task 4: Types

**Files:** `shared/types.ts`
- [ ] Append:
```ts
export interface MonthlyFinancePoint { month: number; revenue: number; worked_off: number; }
export interface MonthlyFinanceData { year: number; available_years: number[]; series: MonthlyFinancePoint[]; }
```
- [ ] Run `npm run admin:typecheck` → PASS.

---

## Task 5: Hook

**Files:** `web/admin/src/hooks/useMonthlyFinance.ts`
- [ ] Create:
```ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { MonthlyFinanceData } from '../lib/types';

export function useMonthlyFinance(year?: number) {
  return useQuery({
    queryKey: ['dashboard-monthly', year || 0],
    queryFn: () => api<MonthlyFinanceData>('GET', `/api/admin/dashboard/monthly${year ? `?year=${year}` : ''}`),
    staleTime: 30_000,
  });
}
```
- [ ] `npm run admin:typecheck` → PASS.

---

## Task 6: Charts UI (Recharts, via `/design-principles`)

**Files:** `web/admin/src/pages/dashboard/MonthlyAreaChart.tsx`, `FinanceCharts.tsx`, `DashboardPage.tsx`, `web/admin/src/style.css`

> Invoke `/design-principles` before JSX/CSS. Recharts SVG, цвета/шрифты — через CSS-переменные/токены, кастомный Tooltip, тёмная тема через токены. Дропдаун года — кастомный `SelectInput` (`components/form/SelectInput.tsx`, API: `options:{value,label}[]`, `value`, `onChange:(e:{target:{value}})`). Короткие подписи месяцев — `MONTHS_RU` из `lib/slots.ts` (`'Январь'..'Декабрь'`), брать `.slice(0,3)`.

- [ ] **Step 1: `MonthlyAreaChart.tsx`** — props `{ data: MonthlyFinancePoint[]; valueKey: 'revenue'|'worked_off'; title: string }`. Маппит данные в `{ monthLabel: MONTHS_RU[m-1].slice(0,3), value: point[valueKey] }`. Рендерит `ResponsiveContainer height={240}` → `AreaChart`; `<defs><linearGradient>` от `var(--accent)` (opacity ~0.25 → 0); `Area type="monotone" dataKey="value" stroke="var(--accent)" fill="url(#grad-<valueKey>)"`; `XAxis dataKey="monthLabel"` + `YAxis` с форматтером (короткие тыс.: `v=>v>=1000? (v/1000)+'k':v`); `CartesianGrid` горизонтальный, `stroke="var(--border)"`; кастомный `<Tooltip content>` — карточка `--bg2`/`--border`/`--shadow-popover`, значение через `fmtRub`. Заголовок `<h3 className="chart-card__title">{title}</h3>` над контейнером, обёртка `.chart-card`.
- [ ] **Step 2: `FinanceCharts.tsx`** — год из URL `?chart_year=` (`useSearchParams`), дефолт = последний из `available_years` или текущий. `useMonthlyFinance(year)`. Дропдаун `SelectInput` (options = `available_years.map(y=>({value:y,label:String(y)}))`). Два `MonthlyAreaChart` вертикально: «Выручка по месяцам» (revenue), «Отработано по месяцам» (worked_off). Skeleton при загрузке, EmptyState при отсутствии данных. Обёртка `.finance-charts`.
- [ ] **Step 3: `DashboardPage.tsx`** — вставить `<FinanceCharts />` между `dashboard__kpis` и `<DebtsCard/>`.
- [ ] **Step 4: Styles** (`style.css`, via `/design-principles`): `.finance-charts` (gap, ряд с дропдауном), `.chart-card` (border + `--shadow-modal` + `--r` + padding на 4px-grid), `.chart-card__title` (`--font-display`), tooltip-карточка `.chart-tooltip` на токенах. Recharts-текст осей — `tick={{ fill: 'var(--text3)', fontSize: 12 }}` инлайн (Recharts требует SVG-атрибуты, токены через переменную допустимы).
- [ ] **Step 5:** `npm run admin:typecheck && npm run admin:build` → оба PASS.

---

## Task 7: Финальная проверка
- [ ] `npm test` → all PASS. `npm run admin:typecheck && npm run admin:build` → PASS.
- [ ] Runtime smoke: `node -e "require('dotenv').config(); const r=require('./services/admin-repo'); const {pool}=require('./services/db'); r.getMonthlyFinance({year:2026}).then(d=>{console.log(d.year, d.available_years, d.series.length, d.series.find(s=>s.month===5)); return pool.end();})"` → 12 строк, осмысленные revenue/worked_off за май.
- [ ] Ручной smoke (`npm run admin:dev`): дашборд показывает два графика; смена года в дропдауне пересобирает; тёмная тема ок; design-review (токены, без generic-вида).

## Self-Review
- Spec §3 (endpoint) → T2/T3; §4 (FIFO month map) → T1; §5 (Recharts/SelectInput/charts) → T5/T6; §8 (tests) → T1/T2.
- DRY: `_fifoInputs()` устраняет дублирование загрузки между `getDashboard` и `getMonthlyFinance`.
- Recharts уже установлен (Task 0 выполнен вручную).
