# Dashboard Finance Charts (monthly revenue / worked-off) — Design

**Дата:** 2026-06-03
**Статус:** утверждён к реализации
**Скоуп:** два помесячных area-графика на дашборде (Выручка и Отработано), ось Y — деньги, ось X — месяцы Янв–Дек выбранного года; выбор года через дропдаун.

**Связано с:** `docs/superpowers/specs/2026-06-03-admin-dashboard-design.md` (базовый дашборд + FIFO-модель).

---

## 1. Мотивация

Дашборд показывает агрегаты за один период. Управляющему нужен **тренд по месяцам** — как менялись выручка и отработанные деньги в течение года. Два area-графика (Y = ₽, X = месяц) с выбором года дают эту картину.

## 2. Решения (согласовано)

- **Библиотека:** **Recharts 3.8.1** — единственный из кандидатов с **официальной поддержкой React 19** (peer `^19`, ставится чисто без `--legacy-peer-deps`) И на **SVG** (темится токенами/CSS, в отличие от canvas у Chart.js/ECharts). visx отпал: его peer-deps застряли на React 16–18 → конфликт с React 19 проекта. Recharts даёт декларативный area-chart; дефолтный «generic» вид усмиряем через кастомные `Tooltip`/тики/цвета на токенах (см. §5, обязательно `/design-principles`).
- **Тип:** area (плавная линия с заливкой) — показывает тренд.
- **Два отдельных графика:** Выручка и Отработано, **друг под другом** (вертикально, оба на всю ширину).
- **Горизонт:** ровно 12 месяцев Янв–Дек **выбранного года**. Над графиками дропдаун года; выбор пересобирает оба графика.
- **Период KPI (от/до) и год графиков — независимы.**

## 3. Backend

### Эндпоинт
`GET /api/admin/dashboard/monthly?year=YYYY` — `routes/admin/dashboard.js` (тот же роутер, новый суб-путь `/monthly`), под `requireAdmin`.
- `year` — целое, валидируется `^\d{4}$` и диапазоном (напр. 2000..2100); невалид → 400 `invalid_year`. Без параметра → текущий МСК-год (`mskMonthRange(now).month` → год).

### Ответ
```jsonc
{
  "years": [2025, 2026],
  "available_years": [2024, 2025, 2026],
  "byYear": {
    "2025": [ { "month": 1, "revenue": 0, "worked_off": 0 }, /* …12 */ ],
    "2026": [ { "month": 1, "revenue": 0, "worked_off": 0 }, /* …12 */ ]
  }
}
```
> **Обновление (year-over-year):** эндпоинт принимает `?years=2025,2026` (csv, дедуп/клэмп ≤6; back-compat `?year=`). Ответ — `byYear` (ключ-год → 12 точек) вместо одиночного `series`. Фронт строит «wide»-ряды на месяц и накладывает года на одном графике (`ComposedChart`): основной год — accent `Area`, прошлые — приглушённые серые `Line` (single-accent сохранён). Реализовано.

### Реализация — `services/admin-repo.js`
Новая функция `getMonthlyFinance({ year, now })`:
- **available_years** — distinct годы из обеих дат:
  ```sql
  SELECT DISTINCT y FROM (
    SELECT EXTRACT(YEAR FROM paid_at)::int AS y FROM payments
    UNION
    SELECT EXTRACT(YEAR FROM lesson_date)::int AS y FROM lessons
  ) t WHERE y IS NOT NULL ORDER BY y;
  ```
  Если текущего года нет в списке — добавить его (чтобы дефолт всегда валиден).
- **revenue по месяцам:**
  ```sql
  SELECT EXTRACT(MONTH FROM paid_at)::int AS m, COALESCE(SUM(total_amount),0)::numeric AS rev
    FROM payments
   WHERE paid_at >= $year_start AND paid_at < $next_year_start
   GROUP BY m;
  ```
- **worked_off по месяцам (FIFO):** тот же per-`(student,direction)` проход, что в `getDashboard`, но используем расширенный результат `computeFifo` (см. §4). Суммируем `worked_off_by_month` всех пар в глобальную карту `YYYY-MM → ₽`, берём 12 месяцев выбранного года.
- Собираем `series` — 12 строк (month 1..12), нули где нет данных. Деньги через `_round2`.

## 4. Расширение `computeFifo` (services/fifo.js)

Добавить в возвращаемый объект поле `worked_off_by_month: { [YYYY_MM: string]: number }` — стоимость списанных уроков, сгруппированная по месяцу урока (`consumption.date.slice(0,7)`). Накапливается в том же единственном проходе (не зависит от `monthStart/monthEnd`-окна; то окно по-прежнему даёт `worked_off_month`). Деньги в карте округляются до копеек.

**Обратная совместимость:** поле аддитивное; существующие тесты проверяют отдельные ключи через `strictEqual`, не ломаются. `getDashboard` новое поле игнорирует.

## 5. Frontend

### Зависимости (корневой package.json — фронт-deps живут там)
`recharts@^3.8.1` — **уже установлен** (чисто, без peer-конфликтов). Только build-time (Vite бандлит) — на 2 ГБ VPS влияет лишь размер бандла (~gzip ~40 кБ, tree-shake по импортам из `recharts`).

### Данные
- `shared/types.ts`: `MonthlyFinancePoint { month: number; revenue: number; worked_off: number }`, `MonthlyFinanceData { year: number; available_years: number[]; series: MonthlyFinancePoint[] }`.
- `web/admin/src/hooks/useMonthlyFinance.ts`: `useMonthlyFinance(year?: number)` → `useQuery(['dashboard-monthly', year], …'/api/admin/dashboard/monthly?year=')`, `staleTime` 30с.

### Компоненты (`web/admin/src/pages/dashboard/`)
- **`MonthlyAreaChart.tsx`** — переиспользуемый area-график на Recharts. Props: `data: MonthlyFinancePoint[]`, `valueKey: 'revenue' | 'worked_off'`, `title: string`. Внутри: `ResponsiveContainer` (height ~240) → `AreaChart`; `XAxis dataKey="monthLabel"` (Янв..Дек), `YAxis` с кратким форматтером денег (напр. `420k`), `CartesianGrid` только горизонтальные линии; `Area type="monotone"` с `stroke`/`fill` через **CSS-переменные** (`stroke="var(--accent)"`, `fill="url(#…)"` — `<linearGradient>` из `var(--accent)` низкой непрозрачности); кастомный `<Tooltip content={…}>` — карточка на токенах с `fmtRub`. Цвета/шрифты осей — через `tick={{ fill: 'var(--text3)' }}` и className, без хардкодов. Заголовок графика над контейнером (`--font-display`).
- **`FinanceCharts.tsx`** — контейнер: дропдаун года (**кастомный `SelectInput`** из `components/form/`, опции = `available_years`) + два `MonthlyAreaChart` (Выручка, Отработано) вертикально. Год — в URL `?chart_year=YYYY` через `useSearchParams`; дефолт = текущий (или последний из available_years). Skeleton при загрузке, EmptyState если нет данных за год.
- Месяцы X: переиспользовать `MONTHS_RU` (уже есть в `DashboardPage.tsx` — вынести в `lib/` или дублировать короткие подписи Янв..Дек; вынести в `lib/format.ts` или `lib/slots.ts`, там уже есть `MONTHS_RU`).

### Размещение
На `DashboardPage` блок `FinanceCharts` — **между** `dashboard__kpis` и `DebtsCard`.

### Дизайн (через `/design-principles`)
- Линия — `var(--accent)`; заливка — `color-mix(in oklab, var(--accent) NN%, transparent)`; оба графика один accent (single-accent rule — цвет тут не несёт различающего смысла, это просто «данные»).
- Оси/подписи — `--text3`/`--text4`, сетка (горизонтальные линии) — `--border` тонкая.
- Тултип — карточка на токенах (`--bg2`, `--border`, `--shadow-popover`, `--font-mono` для числа).
- Заголовок графика — `--font-display`; деньги по оси — `--font-mono tabular-nums`.
- Тёмная тема — через токены, без хардкодов.
- Дропдаун года — кастомный `SelectInput`, не native.

## 6. Edge cases

- **Год без данных** — все 12 точек = 0; график рисует плоскую нулевую линию + EmptyState-хинт «Нет данных за YYYY» (или просто плоско). Решение: рисуем оси и плоскую линию (тренд «ноль» информативнее пустоты).
- **Будущие месяцы текущего года** — данных нет → нули (нормально).
- **`available_years` пуст** (совсем пустая БД) — вернуть `[currentYear]`, графики плоские.
- **worked_off для направлений без оплат** — как в базовой модели, не оценивается (перерасход), в `worked_off_by_month` не попадает.
- **Производительность** — monthly-эндпоинт повторяет full-scan FIFO (как `getDashboard`); admin-only, редкий. Тот же порог пересмотра (§9 базовой спеки). Клиентский `staleTime` + отдельный год-ключ кеша.

## 7. Безопасность

- Под `requireAdmin`. Единственный вход — `year`, валидируется регуляркой + диапазоном → нет SQL-инъекций (плюс параметризованный SQL). Границы года в запрос идут как параметры-даты.

## 8. Тесты

- `services/fifo.test.js` — новый тест: `worked_off_by_month` для примера из базовой спеки (списание мая/июня раскладывается по `2026-05`/`2026-06` корректно, с half-lesson).
- `services/admin-repo.test.js` — тест `getMonthlyFinance`: на фикстурах (delta/прямой) проверить, что revenue и worked_off по месяцам выбранного года совпадают с ручным расчётом; `available_years` содержит годы фикстур; `series` всегда 12 строк.
- Charts/UI — без автотеста (нет фронтенд-раннера); ручной smoke.

## 9. Файлы

**Backend**
- `services/fifo.js` — `worked_off_by_month` в результат; `services/fifo.test.js` — тест.
- `services/admin-repo.js` — `getMonthlyFinance()` + экспорт; `services/admin-repo.test.js` — тест.
- `routes/admin/dashboard.js` — суб-путь `GET /monthly` с валидацией `year`.

**Frontend**
- `package.json` — `recharts` (уже установлен).
- `shared/types.ts` — `MonthlyFinancePoint`, `MonthlyFinanceData`.
- `web/admin/src/hooks/useMonthlyFinance.ts`.
- `web/admin/src/pages/dashboard/MonthlyAreaChart.tsx`, `FinanceCharts.tsx`.
- `web/admin/src/pages/dashboard/DashboardPage.tsx` — вставить `<FinanceCharts/>`.
- `web/admin/src/lib/` — вынести короткие подписи месяцев (Янв..Дек) если нужно (рядом с `MONTHS_RU`).
- `web/admin/src/style.css` — стили графиков/тултипа/дропдаун-ряда (через `/design-principles`).

## 10. Вне скоупа

- ~~Сравнение год-к-году на одном графике~~ — **реализовано** (основной год + предыдущий, accent-area vs серая линия; `?years=`).
- Экспорт графика / CSV.
- Дельты и спарклайны в KPI-карточках (отдельное улучшение дизайна).
- Объединение revenue+worked_off на одном графике (решено: два раздельных).
