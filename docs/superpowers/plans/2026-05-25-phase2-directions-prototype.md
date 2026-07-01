# Phase 2 (prototype) — Backfill `directions`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Написать минимальный, но боевой бэкфилл для одной (самой простой) сущности `directions` из Sheets в PostgreSQL. Цель прототипа — обкатать общий каркас (idempotency, `--dry-run`, логи, верификация), который потом тиражируется на остальные 7 сущностей.

**Reference spec:** `docs/superpowers/specs/2026-05-25-postgres-migration-v2-design.md` (раздел Phase 2 — Backfill).

**Project state note:** Проект не под git. Шаги `commit` пропускаются.

---

## Контекст

`directions` — справочник направлений (Scratch, Python, Roblox, …). В Sheets отдельной таблицы под направления нет — они берутся из колонки **S** листа «Список всех детей» (теже строки, что и ученики, с третьей строки). Дедуплицируем по `name`.

**Логика классификации** (точная копия `services/sheets.js:217-220`):
```js
const isIndividual = direction.includes('ИНДИВ');
const sheetName = isIndividual
  ? 'Индивидуальные'
  : direction.replace(/\s+ИНДИВ$/i, '').trim();  // для групп — это исходное имя
```

**Skip-фильтры** (из `sheets.js:213-214`):
- Пустая строка → skip.
- `direction.includes('УЧЕНИКА НЕТ')` → skip.

**Целевая таблица** (`db/migrations/001_initial_schema.sql:23-28`):
```sql
CREATE TABLE directions (
  id            serial PRIMARY KEY,
  name          text NOT NULL UNIQUE,
  sheet_name    text NOT NULL,
  is_individual bool NOT NULL
);
```

---

## Файловая структура

| Путь | Создаётся/Меняется | Ответственность |
|------|--------------------|-----------------|
| `scripts/backfill-directions.js` | создаётся | Чтение Sheets, дедуп, upsert в PG, dry-run, лог |
| `scripts/backfill-directions.test.js` | создаётся | Unit-тест чистой функции `extractDirections(rows)` |
| `package.json` | меняется | npm-script `backfill:directions` |
| `docs/backfill-runbook.md` | создаётся | Краткая инструкция: как гонять, что ожидать |

---

## Контракт скрипта

```
node scripts/backfill-directions.js [--dry-run]
```

- Без флагов — читает Sheets, делает upsert в PG, выводит JSON-итог в **stdout**, прогресс — в **stderr**.
- `--dry-run` — читает Sheets, печатает план изменений (что вставится, что обновится), **в БД не пишет**. Хорош для CI / первичной проверки.
- Exit code: `0` при успехе, `1` при любой ошибке (печатает стектрейс в stderr).
- Идемпотентен: второй прогон против непустой PG даёт 0 inserts, 0 updates (если данные в Sheets не менялись).

**Формат JSON-итога:**
```json
{
  "entity": "directions",
  "read": 12,
  "inserted": 3,
  "updated": 1,
  "skipped": 0,
  "duration_ms": 482,
  "dry_run": false
}
```

`skipped` — те направления, у которых `name` уже в PG и `sheet_name`/`is_individual` совпадают (no-op upsert).

---

## Архитектурные решения

1. **Прямые SQL запросы** через `services/db.js` (`pool.query`). ORM не нужен.
2. **Upsert одним запросом** на каждое направление:
   ```sql
   INSERT INTO directions (name, sheet_name, is_individual)
   VALUES ($1, $2, $3)
   ON CONFLICT (name) DO UPDATE
     SET sheet_name    = EXCLUDED.sheet_name,
         is_individual = EXCLUDED.is_individual
   WHERE directions.sheet_name    IS DISTINCT FROM EXCLUDED.sheet_name
      OR directions.is_individual IS DISTINCT FROM EXCLUDED.is_individual
   RETURNING (xmax = 0) AS inserted;
   ```
   `(xmax = 0)` — стандартный трюк Postgres: возвращает `true` для INSERT, `false` для UPDATE. Если UPDATE не сработал (WHERE отсёк) — `RETURNING` ничего не вернёт, и мы это считаем `skipped`.
3. **Чистая функция парсинга** `extractDirections(rows) → Array<{name, sheet_name, is_individual}>` — testable, не зависит от PG.
4. **Чтение из Sheets** — переиспользуем существующий хелпер `services/sheets.js`. Конкретно — пара строк, читающие лист «Список всех детей» начиная с третьей строки. Если такого экспорта нет — берём готовую низкоуровневую функцию и собираем нужный range в скрипте.

---

## Задачи

### Task 1: Чистая функция `extractDirections(rows)` + тест

**Files:**
- Create: `scripts/backfill-directions.js` (только функция-парсер пока, без main)
- Create: `scripts/backfill-directions.test.js`

- [ ] **Step 1: TDD — написать тест**

`scripts/backfill-directions.test.js`:
```js
const { test } = require('node:test');
const assert = require('node:assert');
const { extractDirections } = require('./backfill-directions');

test('extractDirections: дедуп по имени, верный sheet_name', () => {
  const rows = [
    ['Иванов', '', '10', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 'Scratch начинающие'],
    ['Петрова', '', '11', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 'Scratch начинающие'],
    ['Сидоров', '', '9',  '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 'Python ИНДИВ'],
    ['Кузнецов','', '8',  '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''],                    // пустое — skip
    ['Боков',   '', '12', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 'УЧЕНИКА НЕТ'],         // skip
  ];
  const out = extractDirections(rows);
  assert.deepStrictEqual(out.sort((a,b)=>a.name.localeCompare(b.name)), [
    { name: 'Python ИНДИВ',        sheet_name: 'Индивидуальные',     is_individual: true  },
    { name: 'Scratch начинающие',  sheet_name: 'Scratch начинающие', is_individual: false },
  ]);
});

test('extractDirections: trimming пробелов', () => {
  const rows = [
    ['Иванов', '', '10', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '  Scratch  '],
  ];
  const out = extractDirections(rows);
  assert.deepStrictEqual(out, [{ name: 'Scratch', sheet_name: 'Scratch', is_individual: false }]);
});
```

- [ ] **Step 2: Реализация**

`scripts/backfill-directions.js`:
```js
function extractDirections(rows) {
  const seen = new Map();
  for (const row of rows) {
    const direction = String(row[18] || '').trim();  // S
    if (!direction) continue;
    if (direction.includes('УЧЕНИКА НЕТ')) continue;
    if (seen.has(direction)) continue;

    const isIndividual = direction.includes('ИНДИВ');
    const sheet_name   = isIndividual
      ? 'Индивидуальные'
      : direction.replace(/\s+ИНДИВ$/i, '').trim();

    seen.set(direction, { name: direction, sheet_name, is_individual: isIndividual });
  }
  return [...seen.values()];
}

module.exports = { extractDirections };
```

- [ ] **Step 3: `npm test` — все тесты зелёные**

Expected: 5 (старые) + 2 (новые) = 7/7 PASS.

---

### Task 2: Загрузчик строк из Sheets

**Files:**
- Modify: `scripts/backfill-directions.js` (добавить `loadStudentRows()`)

- [ ] **Step 1: Изучить интерфейс `services/sheets.js`**

Цель — найти функцию, которая читает «Список всех детей» начиная со строки 3. В `readAllStudents()` или похожем. Если экспортируется готовый range — переиспользовать; если нет — переиспользовать низкоуровневый `sheets.spreadsheets.values.get`.

- [ ] **Step 2: Реализация**

Добавить в `backfill-directions.js`:
```js
const { google } = require('googleapis');
// Используем тот же auth-флоу, что и services/sheets.js.
// Если в sheets.js есть экспортируемый клиент — переиспользовать.

async function loadStudentRows() {
  // Прочитать диапазон 'Список всех детей'!A3:S из STUDENTS_SPREADSHEET_ID.
  // Вернуть массив массивов (как values.get отдаёт).
}

module.exports = { extractDirections, loadStudentRows };
```

**Acceptance:** скрипт не падает на чтении, печатает в stderr количество прочитанных строк.

---

### Task 3: Upsert в PG + dry-run + JSON-итог

**Files:**
- Modify: `scripts/backfill-directions.js` (добавить main)

- [ ] **Step 1: main-функция**

```js
async function main() {
  const dryRun = process.argv.includes('--dry-run');
  const t0 = Date.now();
  const result = { entity: 'directions', read: 0, inserted: 0, updated: 0, skipped: 0, duration_ms: 0, dry_run: dryRun };

  const rows = await loadStudentRows();
  const directions = extractDirections(rows);
  result.read = directions.length;
  process.stderr.write(`read ${rows.length} rows, extracted ${directions.length} unique directions\n`);

  if (dryRun) {
    for (const d of directions) {
      process.stderr.write(`[dry-run] ${d.name} → sheet=${d.sheet_name}, individual=${d.is_individual}\n`);
    }
    result.duration_ms = Date.now() - t0;
    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
    return;
  }

  const { pool } = require('../services/db');
  for (const d of directions) {
    const res = await pool.query(
      `INSERT INTO directions (name, sheet_name, is_individual)
       VALUES ($1, $2, $3)
       ON CONFLICT (name) DO UPDATE
         SET sheet_name    = EXCLUDED.sheet_name,
             is_individual = EXCLUDED.is_individual
       WHERE directions.sheet_name    IS DISTINCT FROM EXCLUDED.sheet_name
          OR directions.is_individual IS DISTINCT FROM EXCLUDED.is_individual
       RETURNING (xmax = 0) AS inserted`,
      [d.name, d.sheet_name, d.is_individual],
    );
    if (res.rowCount === 0)            result.skipped++;
    else if (res.rows[0].inserted)     result.inserted++;
    else                               result.updated++;
  }

  result.duration_ms = Date.now() - t0;
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  await pool.end();
}

if (require.main === module) {
  main().catch(err => {
    console.error(err);
    process.exit(1);
  });
}
```

- [ ] **Step 2: Поведенческие проверки (вручную)**

```powershell
# dry-run против рабочей Sheets
node scripts/backfill-directions.js --dry-run

# реальный прогон
node scripts/backfill-directions.js | tee /tmp/run1.json

# повторный прогон — ожидаем inserted=0, updated=0, skipped=N
node scripts/backfill-directions.js | tee /tmp/run2.json
```

Expected:
- Первый прогон: `inserted = N`, `updated = 0`, `skipped = 0`.
- Второй прогон: `inserted = 0`, `updated = 0`, `skipped = N`.
- При ручной правке `sheet_name` в БД — следующий прогон поправит обратно (`updated = 1`).

---

### Task 4: npm-скрипт + runbook

**Files:**
- Modify: `package.json`
- Create: `docs/backfill-runbook.md`

- [ ] **Step 1: npm-скрипт**

`package.json`, в `"scripts"`:
```json
"backfill:directions": "node scripts/backfill-directions.js"
```

- [ ] **Step 2: Runbook**

`docs/backfill-runbook.md` — краткая инструкция:
- Зачем нужно (одноразовый импорт Sheets → PG, перед cutover Phase 3).
- Какой порядок (когда план расширится): directions → teachers → tokens → groups → students → memberships → lessons → payroll.
- Как запускать: `npm run backfill:<entity>` или `node scripts/backfill-<entity>.js [--dry-run]`.
- Что делать, если что-то расходится: проверить колонку S в Sheets, перегнать `--dry-run`, посмотреть лог.

---

### Task 5: Финальная проверка

- [ ] `npm test` — 7/7 (5 старых + 2 новых) PASS.
- [ ] `node scripts/backfill-directions.js --dry-run` — печатает список направлений, в БД ничего не пишет.
- [ ] `psql journal -c "SELECT count(*) FROM directions"` — 0 (т.к. ещё не запускали реальный backfill).
- [ ] `npm run backfill:directions` — печатает JSON, count в БД совпадает с количеством уникальных направлений в Sheets.
- [ ] Повторный `npm run backfill:directions` — `inserted=0, updated=0, skipped=N`.
- [ ] Сервер `npm start` всё ещё стартует и работает (проверить, что backfill не сломал кеш-прогрев).

---

## Что НЕ входит в этот прототип

- `teachers`, `tokens`, `groups`, `students`, `group_memberships`, `lessons`, `payroll` — следующие планы Phase 2.
- `verify-backfill.js` — отдельный план, после хотя бы 2-3 entity backfill'ов.
- Прогресс-бары, parallelism, batch insert — directions их N≈10-15, не нужно.
- TLS/secrets для PG — уже настроены в Phase 0.

---

## Что появится после прототипа

Шаблон для остальных сущностей. Каждый следующий backfill следует тому же паттерну:
1. Чистая функция `extractX(rows)` + unit-тест.
2. Loader из Sheets.
3. Upsert с `ON CONFLICT DO UPDATE WHERE IS DISTINCT FROM` + xmax-трюк.
4. `--dry-run` и JSON-итог.
5. npm-script.

Сложности будут только в:
- `lessons` + `lesson_attendance` (журнальные листы, группировка по дате+номеру урока, staging-индекс для idempotency).
- `payroll` (связка с lessons по date+lesson_number+group).
- `groups` + `group_schedule_slots` (парсинг времени из имени группы, multiple slots).

Эти три — отдельные планы.

---

## Откат

Если что-то пошло не так:
```powershell
psql journal -c "TRUNCATE directions CASCADE"
```
(`CASCADE` нужен, потому что `groups.direction_id` ссылается на `directions.id`. Но на этом этапе `groups` пусто.)

Скрипт `scripts/backfill-directions.js` можно удалить — он не меняет ничего вне `directions`.
