# PostgreSQL Migration — Phase 0 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Установить инфраструктуру PostgreSQL рядом с journal-backend (нативный локальный Postgres, миграции, низкоуровневые сервисы `db.js` + `sync-failures.js`) без изменения существующего runtime-поведения.

**Architecture:** Параллельная инфраструктура. Никакой код в `server.js` пока не вызывает PG. Repository layer и dual-write — это уже Phase 1+. После завершения Phase 0: `npm start` работает идентично, дополнительно работают `npm run db:migrate`, `npm test`.

**Tech Stack:** Node.js (уже стоит), нативный PostgreSQL 15 для Windows (installer с postgresql.org), npm-пакет `pg`, встроенный `node:test` для unit-тестов. **Docker в проекте не используется.**

**Project state note:** Проект не под git (`Is a git repository: false`). Все шаги `commit` из стандартного шаблона **пропущены**. Если решите инициализировать git позже, рекомендую коммитить после каждой завершённой задачи.

**Reference spec:** `docs/superpowers/specs/2026-05-25-postgres-migration-design.md`

---

## Файловая структура Phase 0

| Путь | Создаётся/Меняется | Ответственность |
|------|--------------------|-----------------|
| `.env` | меняется | добавляются `DATABASE_URL`, `DUAL_WRITE_ENABLED`, `READ_FROM` |
| `.env.example` | создаётся | публичный шаблон для команды/деплоя |
| `package.json` | меняется | зависимость `pg`, скрипты `db:migrate`, `db:reset`, `test` |
| `db/migrations/001_initial_schema.sql` | создаётся | полная схема из spec секции 2 |
| `db/migrate.js` | создаётся | runner: читает миграции, прогоняет недостающие |
| `services/db.js` | создаётся | `Pool`, `tx()`, заглушки CRUD-функций |
| `services/db.test.js` | создаётся | unit-тесты `tx()` (commit/rollback) |
| `services/sync-failures.js` | создаётся | запись ошибок PG в таблицу `sync_failures`, fallback в файл |
| `services/sync-failures.test.js` | создаётся | тесты записи + fallback |
| `logs/.gitkeep` | создаётся | директория для fallback-логов sync-failures |

Файлы `server.js`, `services/sheets.js`, `services/cache.js`, `services/calculator.js`, `public/Index.html` — **не трогаем**.

---

### Task 1: Установить нативный PostgreSQL 15 на Windows

**Это интерактивный шаг — выполняется пользователем вручную.** После него — автоматическая проверка и создание БД.

- [ ] **Step 1: Скачать installer**

Открыть https://www.postgresql.org/download/windows/ → ссылка «Download the installer» → EDB. Скачать PostgreSQL 15.x для Windows x86-64.

- [ ] **Step 2: Запустить installer**

При установке:
- Installation directory: по умолчанию (`C:\Program Files\PostgreSQL\15`)
- Components: оставить все по умолчанию (Server, pgAdmin 4, Stack Builder, Command Line Tools)
- Data directory: по умолчанию
- **Password for postgres superuser:** придумать и запомнить — пригодится в Step 4. Пусть будет, например, `postgres_admin_password` (можете свой).
- Port: 5432 (по умолчанию)
- Locale: Default
- Skip Stack Builder в конце.

- [ ] **Step 3: Проверить что psql виден в PATH**

Run: `psql --version`
Expected: `psql (PostgreSQL) 15.x`

Если команда не найдена — добавить `C:\Program Files\PostgreSQL\15\bin` в системный PATH и перезапустить терминал.

- [ ] **Step 4: Создать пользователя и БД `journal`**

Запросит пароль `postgres` (тот, который задали в Step 2):
```
psql -U postgres -h localhost -c "CREATE USER journal WITH PASSWORD 'journal_dev_password';"
psql -U postgres -h localhost -c "CREATE DATABASE journal OWNER journal;"
```
Expected: `CREATE ROLE` и `CREATE DATABASE`.

- [ ] **Step 5: Проверить, что journal работает**

Run: `psql -U journal -h localhost -d journal -c "SELECT version();"`
(Запросит пароль `journal_dev_password`)
Expected: строка вида `PostgreSQL 15.x ...`

---

### Task 2: Установить пакет `pg`

**Files:**
- Modify: `package.json`

- [ ] **Step 1: Установить `pg`**

Run: `npm install pg`
Expected: `added 1 package` (или больше с транзитивными), без ошибок.

- [ ] **Step 2: Проверить `package.json`**

Открыть `package.json` и убедиться, что в `dependencies` появилось:
```json
"pg": "^8.x.x"
```

---

### Task 3: Обновить `.env` и создать `.env.example`

**Files:**
- Modify: `.env`
- Create: `.env.example`

- [ ] **Step 1: Добавить переменные в `.env`**

Открыть `.env` и добавить в конец:
```
# PostgreSQL (Phase 0)
DATABASE_URL=postgresql://journal:journal_dev_password@localhost:5432/journal
DUAL_WRITE_ENABLED=false
READ_FROM=sheets
```

- [ ] **Step 2: Создать `.env.example`**

```
# Таблица с учениками и направлениями (только чтение)
STUDENTS_SPREADSHEET_ID=<google-sheet-id>

# Таблица с журналом, зарплатой и токенами (чтение + запись)
JOURNAL_SPREADSHEET_ID=<google-sheet-id>

PORT=3000
CACHE_TTL=300

# PostgreSQL (Phase 0)
DATABASE_URL=postgresql://journal:journal_dev_password@localhost:5432/journal
DUAL_WRITE_ENABLED=false
READ_FROM=sheets
```

---

### Task 4: Создать SQL-миграцию `001_initial_schema.sql`

**Files:**
- Create: `db/migrations/001_initial_schema.sql`

- [ ] **Step 1: Создать миграцию**

Полное содержимое файла:

```sql
-- 001_initial_schema.sql
-- Полная начальная схема journal-backend.

BEGIN;

-- ===== Справочники =====

CREATE TABLE teachers (
  id         serial PRIMARY KEY,
  name       text NOT NULL UNIQUE,
  email      text,
  phone      text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tokens (
  token      text PRIMARY KEY,
  teacher_id int NOT NULL REFERENCES teachers(id),
  active     bool NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE directions (
  id            serial PRIMARY KEY,
  name          text NOT NULL UNIQUE,
  sheet_name    text NOT NULL,
  is_individual bool NOT NULL
);

-- ===== Группы и состав =====

CREATE TABLE groups (
  id                      serial PRIMARY KEY,
  name                    text NOT NULL UNIQUE,
  direction_id            int NOT NULL REFERENCES directions(id),
  teacher_id              int NOT NULL REFERENCES teachers(id),
  is_individual           bool NOT NULL,
  lesson_duration_minutes int NOT NULL DEFAULT 90
                          CHECK (lesson_duration_minutes IN (45, 60, 90)),
  lessons_per_week        int NOT NULL DEFAULT 1
                          CHECK (lessons_per_week BETWEEN 1 AND 7),
  group_start_date        date,
  vk_chat                 text,
  created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE group_schedule_slots (
  id          serial PRIMARY KEY,
  group_id    int NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  day_of_week int NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
  start_time  time NOT NULL,
  UNIQUE (group_id, day_of_week, start_time)
);
CREATE INDEX group_schedule_slots_dow_time_idx
  ON group_schedule_slots(day_of_week, start_time);

CREATE TABLE students (
  id                  serial PRIMARY KEY,
  full_name           text NOT NULL,
  birth_date          date,
  phone               text,
  school_grade        int CHECK (school_grade BETWEEN 1 AND 11),
  platform_id         text,
  parent_name         text,
  first_purchase_date date,
  age                 int,
  pm                  text,
  enrollment_status   text NOT NULL DEFAULT 'enrolled'
                      CHECK (enrollment_status IN
                        ('enrolled','not_enrolled','frozen','declined')),
  frozen_until_month  int CHECK (frozen_until_month BETWEEN 1 AND 12),
  CHECK ((enrollment_status = 'frozen') = (frozen_until_month IS NOT NULL)),
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE group_memberships (
  id           serial PRIMARY KEY,
  group_id     int NOT NULL REFERENCES groups(id),
  student_id   int NOT NULL REFERENCES students(id),
  lessons_done numeric(6,1) NOT NULL DEFAULT 0,
  remaining    numeric(6,1) NOT NULL DEFAULT 0,
  start_date   date,
  sheet_row    int,
  active       bool NOT NULL DEFAULT true,
  UNIQUE (group_id, student_id)
);

-- ===== Транзакционные таблицы =====

CREATE TABLE lessons (
  id                      serial PRIMARY KEY,
  group_id                int NOT NULL REFERENCES groups(id),
  teacher_id              int NOT NULL REFERENCES teachers(id),
  original_teacher_id     int REFERENCES teachers(id),
  lesson_date             date NOT NULL,
  lesson_number           numeric(5,1) NOT NULL,
  lesson_duration_minutes int NOT NULL,
  lesson_type             text NOT NULL,
  record_url              text,
  submitted_at            timestamptz NOT NULL DEFAULT now(),
  submitted_by_token      text NOT NULL
);
CREATE INDEX lessons_group_date_idx   ON lessons(group_id, lesson_date);
CREATE INDEX lessons_teacher_date_idx ON lessons(teacher_id, lesson_date);

CREATE TABLE lesson_attendance (
  lesson_id  int NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  student_id int NOT NULL REFERENCES students(id),
  present    bool NOT NULL,
  PRIMARY KEY (lesson_id, student_id)
);

CREATE TABLE payroll (
  id             serial PRIMARY KEY,
  lesson_id      int NOT NULL UNIQUE REFERENCES lessons(id),
  teacher_id     int NOT NULL REFERENCES teachers(id),
  total_students int NOT NULL,
  present_count  int NOT NULL,
  payment        numeric(10,2) NOT NULL,
  penalty        numeric(10,2) NOT NULL DEFAULT 0
);
CREATE INDEX payroll_teacher_lesson_idx ON payroll(teacher_id, lesson_id);

-- ===== Инфраструктура =====

CREATE TABLE sync_failures (
  id            bigserial PRIMARY KEY,
  occurred_at   timestamptz NOT NULL DEFAULT now(),
  operation     text NOT NULL,
  payload       jsonb NOT NULL,
  error_message text NOT NULL,
  resolved_at   timestamptz
);

CREATE TABLE schema_migrations (
  version    int PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
```

> Замечание: миграция обёрнута в `BEGIN/COMMIT` — если упадёт на любом `CREATE TABLE`, БД останется чистой.

---

### Task 5: Создать runner миграций `db/migrate.js`

**Files:**
- Create: `db/migrate.js`

- [ ] **Step 1: Создать runner**

```js
// db/migrate.js
require('dotenv').config();
const fs = require('fs');
const path = require('path');
const { Pool } = require('pg');

const MIGRATIONS_DIR = path.join(__dirname, 'migrations');

async function main() {
  const pool = new Pool({ connectionString: process.env.DATABASE_URL });
  const client = await pool.connect();

  try {
    // Создаём schema_migrations, если её ещё нет — в первый запуск
    await client.query(`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        version    int PRIMARY KEY,
        applied_at timestamptz NOT NULL DEFAULT now()
      )
    `);

    const { rows: applied } = await client.query(
      'SELECT version FROM schema_migrations'
    );
    const appliedVersions = new Set(applied.map(r => r.version));

    const files = fs.readdirSync(MIGRATIONS_DIR)
      .filter(f => /^\d+_.*\.sql$/.test(f))
      .sort();

    let appliedCount = 0;

    for (const file of files) {
      const version = parseInt(file.match(/^(\d+)_/)[1], 10);
      if (appliedVersions.has(version)) {
        console.log(`⏭️  ${file} (already applied)`);
        continue;
      }

      const sql = fs.readFileSync(path.join(MIGRATIONS_DIR, file), 'utf8');
      console.log(`▶️  ${file}`);

      try {
        await client.query(sql);
        await client.query(
          'INSERT INTO schema_migrations (version) VALUES ($1)',
          [version]
        );
        console.log(`✅ ${file}`);
        appliedCount++;
      } catch (err) {
        console.error(`❌ ${file}: ${err.message}`);
        throw err;
      }
    }

    console.log(`\nDone. Applied: ${appliedCount}. Total migrations: ${files.length}.`);
  } finally {
    client.release();
    await pool.end();
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
```

> Намеренно простой: каждая миграция — отдельный `query`, статус трекается через `schema_migrations`. Идемпотентность гарантируется проверкой `appliedVersions`. Каждая миграция сама ответственна за свои транзакции (наша 001 уже обёрнута в `BEGIN/COMMIT`).

---

### Task 6: Добавить npm-скрипты

**Files:**
- Modify: `package.json`

- [ ] **Step 1: Открыть `package.json` и заменить блок `scripts`**

```json
"scripts": {
  "start": "node server.js",
  "dev": "nodemon server.js",
  "db:migrate": "node db/migrate.js",
  "db:reset": "psql -U journal -h localhost -d journal -c \"DROP SCHEMA public CASCADE; CREATE SCHEMA public;\"",
  "test": "node --test"
}
```

> `db:reset` — для разработчика, который хочет всё начисто пересоздать. На проде не использовать.

---

### Task 7: Прогнать миграцию и проверить схему

- [ ] **Step 1: Запустить миграцию**

Run: `npm run db:migrate`
Expected:
```
▶️  001_initial_schema.sql
✅ 001_initial_schema.sql

Done. Applied: 1. Total migrations: 1.
```

- [ ] **Step 2: Запустить миграцию ещё раз — проверить идемпотентность**

Run: `npm run db:migrate`
Expected:
```
⏭️  001_initial_schema.sql (already applied)

Done. Applied: 0. Total migrations: 1.
```

- [ ] **Step 3: Проверить таблицы в БД**

Run: `psql -U journal -h localhost -d journal -c "\dt"`
Expected (порядок не важен):
```
                  List of relations
 Schema |          Name           | Type  |  Owner
--------+-------------------------+-------+---------
 public | directions              | table | journal
 public | group_memberships       | table | journal
 public | group_schedule_slots    | table | journal
 public | groups                  | table | journal
 public | lesson_attendance       | table | journal
 public | lessons                 | table | journal
 public | payroll                 | table | journal
 public | schema_migrations       | table | journal
 public | students                | table | journal
 public | sync_failures           | table | journal
 public | teachers                | table | journal
 public | tokens                  | table | journal
```

- [ ] **Step 4: Проверить, что миграция записана**

Run: `psql -U journal -h localhost -d journal -c "SELECT * FROM schema_migrations;"`
Expected: одна строка `version=1, applied_at=<сегодня>`.

---

### Task 8: Создать `services/db.js`

**Files:**
- Create: `services/db.js`

- [ ] **Step 1: Создать модуль с pool, tx() и заглушками**

```js
// services/db.js
const { Pool } = require('pg');

const pool = new Pool({ connectionString: process.env.DATABASE_URL });

/**
 * Выполняет колбэк внутри транзакции.
 * При throw — ROLLBACK, при resolve — COMMIT.
 * Колбэк получает client с тем же интерфейсом, что pool.query.
 */
async function tx(fn) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const result = await fn(client);
    await client.query('COMMIT');
    return result;
  } catch (err) {
    try { await client.query('ROLLBACK'); } catch (_) { /* ignore */ }
    throw err;
  } finally {
    client.release();
  }
}

// ===== Заглушки на Phase 3+ =====
// Сигнатуры зафиксированы здесь, реализация — позже.
// Это удобно: код, который их импортирует, будет работать сразу,
// а в Phase 0 любая попытка вызова явно сообщит, что функция не готова.

function notImplemented(name) {
  return () => { throw new Error(`db.${name}() is not implemented yet (Phase 3)`); };
}

const incrementCounters = notImplemented('incrementCounters');
const insertLesson      = notImplemented('insertLesson');
const insertAttendance  = notImplemented('insertAttendance');
const insertPayroll     = notImplemented('insertPayroll');

async function shutdown() {
  await pool.end();
}

module.exports = {
  pool,
  tx,
  shutdown,
  incrementCounters,
  insertLesson,
  insertAttendance,
  insertPayroll,
};
```

> Заглушки сделаны через `notImplemented` — конкретные стектрейсы при случайном вызове в Phase 0. Сигнатуры функций ещё не зафиксированы (это сделает Phase 3 при написании реальной логики).

---

### Task 9: Тесты для `tx()`

**Files:**
- Create: `services/db.test.js`

> Тесты используют живой Postgres из docker-compose. Если контейнер не запущен — тесты упадут с понятной ошибкой подключения.

- [ ] **Step 1: Написать тесты**

```js
// services/db.test.js
require('dotenv').config();
const { test, before, after } = require('node:test');
const assert = require('node:assert');
const { tx, pool, shutdown } = require('./db');

const TEST_TABLE = 'tx_test_tmp';

before(async () => {
  await pool.query(`CREATE TABLE IF NOT EXISTS ${TEST_TABLE} (id serial PRIMARY KEY, val text)`);
  await pool.query(`TRUNCATE ${TEST_TABLE}`);
});

after(async () => {
  await pool.query(`DROP TABLE IF EXISTS ${TEST_TABLE}`);
  await shutdown();
});

test('tx() commits when callback resolves', async () => {
  await tx(async (client) => {
    await client.query(`INSERT INTO ${TEST_TABLE} (val) VALUES ('committed')`);
  });

  const { rows } = await pool.query(`SELECT val FROM ${TEST_TABLE} WHERE val = 'committed'`);
  assert.strictEqual(rows.length, 1);
});

test('tx() rolls back when callback throws', async () => {
  await assert.rejects(
    () => tx(async (client) => {
      await client.query(`INSERT INTO ${TEST_TABLE} (val) VALUES ('should-be-rolled-back')`);
      throw new Error('boom');
    }),
    /boom/
  );

  const { rows } = await pool.query(
    `SELECT val FROM ${TEST_TABLE} WHERE val = 'should-be-rolled-back'`
  );
  assert.strictEqual(rows.length, 0);
});

test('tx() returns the callback result', async () => {
  const result = await tx(async (client) => {
    const { rows } = await client.query('SELECT 42 AS answer');
    return rows[0].answer;
  });
  assert.strictEqual(result, 42);
});
```

- [ ] **Step 2: Запустить тесты**

Run: `npm test`
Expected:
```
▶ tx() commits when callback resolves
▶ tx() rolls back when callback throws
▶ tx() returns the callback result
ℹ tests 3
ℹ pass 3
ℹ fail 0
```

---

### Task 10: Создать `services/sync-failures.js` + тесты

**Files:**
- Create: `services/sync-failures.js`
- Create: `services/sync-failures.test.js`
- Create: `logs/.gitkeep`

- [ ] **Step 1: Создать директорию для fallback-логов**

```
logs/.gitkeep
```
(пустой файл — просто чтобы папка существовала)

- [ ] **Step 2: Создать `services/sync-failures.js`**

```js
// services/sync-failures.js
const fs = require('fs');
const path = require('path');
const { pool } = require('./db');

const FALLBACK_LOG = path.join(__dirname, '..', 'logs', 'sync-failures.log');

/**
 * Записывает ошибку синхронизации с PG в таблицу sync_failures.
 * Если запись в таблицу тоже падает (например, PG недоступна) — пишет в файл.
 */
async function record(operation, payload, error) {
  try {
    await pool.query(
      `INSERT INTO sync_failures (operation, payload, error_message)
       VALUES ($1, $2, $3)`,
      [operation, payload, error.message]
    );
  } catch (recordErr) {
    try {
      fs.appendFileSync(FALLBACK_LOG, JSON.stringify({
        ts: new Date().toISOString(),
        operation,
        payload,
        original_error: error.message,
        record_error: recordErr.message,
      }) + '\n');
    } catch (fileErr) {
      // Последний резерв: stderr. Если и это не работает — мы бессильны.
      console.error('sync-failures: cannot record anywhere', {
        operation, original: error.message,
        record: recordErr.message, file: fileErr.message,
      });
    }
  }
}

module.exports = { record };
```

- [ ] **Step 3: Создать `services/sync-failures.test.js`**

```js
// services/sync-failures.test.js
require('dotenv').config();
const { test, before, after, beforeEach } = require('node:test');
const assert = require('node:assert');
const { pool, shutdown } = require('./db');
const { record } = require('./sync-failures');

before(async () => {
  await pool.query('TRUNCATE sync_failures RESTART IDENTITY');
});

beforeEach(async () => {
  await pool.query('TRUNCATE sync_failures RESTART IDENTITY');
});

after(async () => {
  await shutdown();
});

test('record() inserts a row with payload as jsonb', async () => {
  await record(
    'append_lesson',
    { lessonId: 7, students: ['Иванов'] },
    new Error('connection refused')
  );

  const { rows } = await pool.query(
    'SELECT operation, payload, error_message, resolved_at FROM sync_failures'
  );
  assert.strictEqual(rows.length, 1);
  assert.strictEqual(rows[0].operation, 'append_lesson');
  assert.deepStrictEqual(rows[0].payload, { lessonId: 7, students: ['Иванов'] });
  assert.strictEqual(rows[0].error_message, 'connection refused');
  assert.strictEqual(rows[0].resolved_at, null);
});

test('record() stores arbitrary payload shapes', async () => {
  await record('increment_counter', null, new Error('x'));
  await record('increment_counter', 42, new Error('y'));
  await record('increment_counter', ['a', 'b'], new Error('z'));

  const { rows } = await pool.query(
    'SELECT payload FROM sync_failures ORDER BY id'
  );
  assert.deepStrictEqual(rows.map(r => r.payload), [null, 42, ['a', 'b']]);
});
```

- [ ] **Step 4: Запустить все тесты**

Run: `npm test`
Expected: 3 теста из `db.test.js` + 2 теста из `sync-failures.test.js`, всё PASS.
```
ℹ tests 5
ℹ pass 5
ℹ fail 0
```

---

### Task 11: Проверить, что `npm start` работает как раньше

> Phase 0 не должен ломать существующее runtime-поведение. Этот шаг — главный acceptance-критерий.

- [ ] **Step 1: Запустить сервер**

Run: `npm start`
Expected (вывод как до изменений):
```
🚀 Сервер запущен на порту 3000
📊 Таблица учеников: ...
📝 Таблица журнала: ...
🔥 Прогреваем кэш...
✅ Кэш прогреят! Данные загружены в память.
```

Ключевое: **никаких новых логов про PG**, потому что `server.js` не импортирует `db.js`. Если в логах появилось что-то про PG — `db.js` где-то импортирован преждевременно. Найти и убрать.

- [ ] **Step 2: Проверить эндпоинт**

В отдельном терминале:
Run: `curl -X POST http://localhost:3000/api/validateToken -H "Content-Type: application/json" -d "{\"token\":\"INVALID\"}"`
Expected: `{"valid":false,"error":"Неверный токен"}`

- [ ] **Step 3: Открыть SPA и пройти короткий smoke**

Открыть http://localhost:3000 в браузере, ввести любой невалидный токен — должна показаться ошибка валидации (как раньше).

- [ ] **Step 4: Остановить сервер**

Ctrl+C в терминале с `npm start`.

---

### Task 12: Финальная проверка acceptance-критериев Phase 0

Из spec секции «Phase 0»:
> **Acceptance:** `npm start` работает как раньше; `npm run db:migrate` создаёт схему; ничего не пишет в PG.

- [ ] **Step 1: `npm start` работает идентично прежнему** — проверено в Task 11. ✅

- [ ] **Step 2: `npm run db:migrate` создаёт схему** — проверено в Task 7. ✅

- [ ] **Step 3: Ничего не пишет в PG из эндпоинтов**

Запустить сервер и проверить, что таблицы пусты:
```powershell
# Терминал 1
npm start
# Терминал 2 — сделать пару запросов через UI/curl, потом проверить
psql -U journal -h localhost -d journal -c "SELECT count(*) FROM lessons;"
```
Expected: `count = 0`. Только `schema_migrations` содержит одну строку.

Остановить сервер.

- [ ] **Step 4: `npm test` зелёный**

Run: `npm test`
Expected: все 5 тестов PASS.

- [ ] **Step 5: Все новые/изменённые файлы на месте**

Run (PowerShell):
```powershell
Get-ChildItem -Recurse .env.example, db, services\db.js, services\db.test.js, services\sync-failures.js, services\sync-failures.test.js, logs | Select-Object FullName
```
Expected: все 8 путей существуют.

---

## Откат Phase 0

Если что-то пошло не так и нужно вернуть проект в исходное состояние:

```powershell
# В PostgreSQL — снести БД journal
psql -U postgres -h localhost -c "DROP DATABASE journal;"
psql -U postgres -h localhost -c "DROP USER journal;"

# В проекте — снести новые файлы
Remove-Item -Recurse -Force db, logs
Remove-Item services\db.js, services\db.test.js, services\sync-failures.js, services\sync-failures.test.js
Remove-Item .env.example
# Вручную: удалить новые строки про PG из .env и новые скрипты из package.json
npm uninstall pg
```

После — `npm start` снова работает на чистом Sheets-стеке. Сервер PostgreSQL на машине останется установленным — его можно использовать в других проектах или удалить через Windows «Установка и удаление программ».

---

## Что НЕ входит в Phase 0 (это Phase 1+)

- Никаких изменений в `server.js`
- Никаких изменений в `services/sheets.js`, `services/cache.js`, `services/calculator.js`
- `services/repository.js` — Phase 1
- `scripts/backfill.js` — Phase 2
- `scripts/parity-check.js` — Phase 2
- Реализация заглушек в `db.js` — Phase 3
- `docs/smoke-tests.md` — Phase 1 (когда появится repository-рефакторинг, который нужно валидировать)
- Cron-бэкап PG на проде — Phase 5+ (когда PG станет источником правды)

---

## После завершения Phase 0

Можно начинать Phase 1 (Repository layer — рефакторинг `server.js` на `repo.X()`). План для Phase 1 пишется отдельно — после того, как Phase 0 стабилизировался у вас в локальной среде.
