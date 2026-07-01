# Phase 3a — Cutover на PostgreSQL — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести teacher SPA (`/`) с Google Sheets на PostgreSQL — все 8 эндпоинтов читают из PG, `submitLesson` атомарен через `db.tx()`. Запись в Sheets отключается. `cache.js` удаляется. Существующий shape ответов сохраняется (фронт не меняется).

**Architecture:** `services/db.js` получает 7 новых функций (4 writer-заглушки реализуются + 3 новых reader'а). `services/repository.js` — thin wrapper над `db.js` (один уровень indirection для будущих pivot'ов; импорт `sheets` уходит). `server.js` `submitLesson` целиком оборачивается в `db.tx()`. `services/cache.js` удаляется, кеш-вызовы по всему `server.js` зачищаются.

**Tech Stack:** Node.js, Express, `pg` driver, node:test, PostgreSQL 15.

**Reference spec:** `docs/superpowers/specs/2026-05-27-phase3a-cutover-design.md`

**Project state:** проект не под git → шаги `commit` пропускаются. Backend admin (Phase 4.2/4.3) уже работает на PG и не затрагивается.

---

## File structure

| Путь | Создаётся / меняется | Ответственность |
|------|----------------------|-----------------|
| `services/db.js` | расширяется | Pool, tx, **+** readTokens, readAllStudents, readFilledLessons, incrementCounters, insertLesson, insertAttendance, insertPayroll |
| `services/db.test.js` | расширяется | Существующие 3 теста tx() + 5 новых (по одному на новую функцию + rollback-тест) |
| `services/repository.js` | переписывается | Thin proxy: re-exports методов `db.js` под тем же публичным API. Импорт `sheets` удаляется |
| `services/cache.js` | удаляется | Не нужен после cutover |
| `server.js` | существенно правится | `submitLesson` под `tx()`; убираются все `cache.*` вызовы; `/api/refreshData`, `/refresh` становятся no-op |
| `.env.example` | чистится | Удаляются `DUAL_WRITE_ENABLED`, `READ_FROM`, `CACHE_TTL` |
| `docs/baseline/` | создаётся | curl-снимки ДО cutover |
| `docs/post-cutover/` | создаётся | curl-снимки ПОСЛЕ cutover |
| `backups/pre-cutover-YYYY-MM-DD.sql` | создаётся | pg_dump |
| `docs/cutover-runbook.md` | создаётся | Runbook процесса cutover (для отката / повторного запуска) |
| `services/sheets.js` | НЕ трогается | Остаётся для backfill-скриптов (Phase 5 удалит) |
| `public/Index.html` | НЕ трогается | Frontend остаётся идентичным |

---

## Testing strategy

- **Unit-тесты на db.js**: гоняем против локальной PG, есть существующий паттерн (`db.test.js`). Каждая новая функция получает минимум 1 тест: insert testdata → call function → assert shape/effect → cleanup. Плюс rollback-тест на tx().
- **Existing 66 tests** должны остаться зелёными.
- **Manual smoke** в браузере (см. Task 8): login → getData → submitLesson → counter → report → schedule.
- **Curl-snapshots before/after** (Task 1, Task 8) — единственный надёжный способ доказать identичную семантику для всех 8 эндпоинтов.

---

## Tasks

### Task 1: Pre-flight snapshot + pg_dump backup

**Files:**
- Create: `backups/pre-cutover-<date>.sql`
- Create: `docs/baseline/getData-<token>.json`, `validateToken.json`, `getAllData.json`, `report.json`, `schedule.json`

**Цель:** зафиксировать «как было» — состояние Sheets-версии teacher SPA + бэкап PG.

- [ ] **Step 1: убедиться что сервер работает на Sheets-версии**

```powershell
npm test
```
Expected: `tests 66 pass 66 fail 0` (или текущее реальное число — важно что зелёные).

- [ ] **Step 2: запустить сервер**

```powershell
npm start
```
В отдельном окне (или фоном). Ждём пока «🚀 Сервер запущен на порту 3000» появится.

- [ ] **Step 3: достать реальный токен преподавателя для snapshot'ов**

```powershell
PGPASSWORD=journal_dev_password psql -U journal -h localhost -d journal -c "SELECT token FROM tokens WHERE active LIMIT 2;"
```
Запиши 2 токена — `<TOKEN_A>` и `<TOKEN_B>`.

- [ ] **Step 4: snapshot 5 эндпоинтов через curl**

```powershell
mkdir docs\baseline -Force | Out-Null
curl -s -X POST -H "Content-Type: application/json" -d "{`"token`":`"<TOKEN_A>`"}" http://localhost:3000/api/validateToken > docs\baseline\validateToken-tokenA.json
curl -s -X POST -H "Content-Type: application/json" -d "{`"token`":`"invalid`"}" http://localhost:3000/api/validateToken > docs\baseline\validateToken-invalid.json
curl -s -X POST -H "Content-Type: application/json" -d "{`"token`":`"<TOKEN_A>`"}" http://localhost:3000/api/getData > docs\baseline\getData-tokenA.json
curl -s -X POST -H "Content-Type: application/json" -d "{`"token`":`"<TOKEN_B>`"}" http://localhost:3000/api/getData > docs\baseline\getData-tokenB.json
curl -s -X POST -H "Content-Type: application/json" -d "{`"token`":`"<TOKEN_A>`"}" http://localhost:3000/api/getAllData > docs\baseline\getAllData.json
curl -s http://localhost:3000/api/report > docs\baseline\report.html
curl -s http://localhost:3000/api/schedule > docs\baseline\schedule.html
```

Замени `<TOKEN_A>` / `<TOKEN_B>` на реальные. `/api/report` и `/api/schedule` возвращают HTML — сохраняем как `.html`.

Expected: все 7 файлов с разумным содержимым (JSON / HTML; не пустые).

- [ ] **Step 5: остановить сервер**

`Ctrl+C` в окне сервера.

- [ ] **Step 6: pg_dump бэкап**

```powershell
mkdir backups -Force | Out-Null
$date = Get-Date -Format "yyyy-MM-dd-HHmm"
$env:PGPASSWORD = "journal_dev_password"
pg_dump -U journal -h localhost -d journal -F p > "backups/pre-cutover-$date.sql"
```

Expected: файл `backups/pre-cutover-*.sql` существует, размер ≥1 MB.

- [ ] **Step 7: проверка дампа**

```powershell
Get-ChildItem backups\pre-cutover-*.sql | Select-Object Name, Length
Get-Content backups\pre-cutover-*.sql -TotalCount 5
```

Expected: первая строка содержит `-- PostgreSQL database dump`.

---

### Task 2: `services/db.js` — readTokens()

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\services\db.js`
- Test: `C:\Users\ilyap\TestKOTOKOD\services\db.test.js`

- [ ] **Step 1: написать падающий тест**

Открой `services/db.test.js` и добавь в конец файла (перед `after(...)` если нужно — но after уже в конце; просто добавь после последнего теста):

```js
test('readTokens(): returns active tokens mapped to teacher name', async () => {
  // setup: создаём тестового препода и токен
  const t = await pool.query(
    `INSERT INTO teachers (name) VALUES ('__TEST_T_DB__') RETURNING id`
  );
  const teacherId = t.rows[0].id;
  await pool.query(
    `INSERT INTO tokens (token, teacher_id, active) VALUES ('__TEST_TOK_DB__', $1, true)`,
    [teacherId]
  );

  const map = await readTokens();
  assert.strictEqual(map['__TEST_TOK_DB__'], '__TEST_T_DB__');

  // cleanup
  await pool.query(`DELETE FROM tokens WHERE token = '__TEST_TOK_DB__'`);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [teacherId]);
});

test('readTokens(): excludes inactive tokens', async () => {
  const t = await pool.query(
    `INSERT INTO teachers (name) VALUES ('__TEST_T_DB_INACT__') RETURNING id`
  );
  const teacherId = t.rows[0].id;
  await pool.query(
    `INSERT INTO tokens (token, teacher_id, active) VALUES ('__TEST_TOK_INACT__', $1, false)`,
    [teacherId]
  );

  const map = await readTokens();
  assert.strictEqual(map['__TEST_TOK_INACT__'], undefined);

  await pool.query(`DELETE FROM tokens WHERE token = '__TEST_TOK_INACT__'`);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [teacherId]);
});
```

Также в начало `db.test.js` после `const { tx, pool, shutdown } = require('./db');` добавь импорт:

```js
const { readTokens } = require('./db');
```

(Или объединить с существующей destructuring — на твой выбор.)

- [ ] **Step 2: убедиться что тесты падают**

```powershell
npm test 2>&1 | Select-String -Pattern "readTokens"
```
Expected: тесты с именем `readTokens` → fail (функция не определена).

- [ ] **Step 3: реализовать `readTokens` в `services/db.js`**

В `services/db.js`, перед `module.exports`, добавь:

```js
async function readTokens() {
  const { rows } = await pool.query(
    `SELECT t.token, te.name AS teacher_name
       FROM tokens t
       JOIN teachers te ON te.id = t.teacher_id
      WHERE t.active = true
        AND te.active = true`
  );
  const map = {};
  for (const r of rows) map[r.token] = r.teacher_name;
  return map;
}
```

И добавь `readTokens` в `module.exports`:

```js
module.exports = {
  pool,
  tx,
  shutdown,
  readTokens,
  incrementCounters,
  insertLesson,
  insertAttendance,
  insertPayroll,
};
```

- [ ] **Step 4: проверить что тесты прошли**

```powershell
npm test 2>&1 | Select-Object -Last 8
```
Expected: `tests 68 pass 68 fail 0` (66 + 2 новых).

---

### Task 3: `services/db.js` — readAllStudents()

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\services\db.js`
- Test: `C:\Users\ilyap\TestKOTOKOD\services\db.test.js`

**Shape, который надо вернуть** (идентичен Sheets-версии, см. `services/sheets.js:186-263`):

```js
{
  data: {
    [teacherName]: {
      [groupName]: {
        students: [
          { name: string, lessonsDone: number, remaining: number, age: string, sheetName: string, sheetRow: number },
          ...
        ],
        lessonsDone: number,   // max(lessons_done) среди учеников группы (для frontend)
        pm: string,            // students.pm первого ученика группы
        vkChat: string,        // group.vk_chat
        startDate: string,     // group.group_start_date в формате ДД.ММ.ГГГГ
        isGroup: boolean,      // !group.is_individual
      }
    }
  },
  index: {
    [`${studentName}|||${groupName}`]: { sheetName, sheetRow }
  }
}
```

**Замечание про `sheetRow`/`sheetName`:** в PG-схеме `group_memberships.sheet_row` существует (от бэкфилла), `directions.sheet_name` тоже. Их используем чтобы сохранить shape идентичным. В Phase 5 эти колонки удаляются.

- [ ] **Step 1: написать тест**

В `db.test.js` добавь:

```js
test('readAllStudents(): returns nested shape grouped by teacher → group', async () => {
  // setup: direction + teacher + group + student + membership
  const dir = await pool.query(
    `INSERT INTO directions (name, sheet_name, is_individual) VALUES ('__TEST_DIR_RD__', 'TestSheet', false) RETURNING id`
  );
  const te = await pool.query(
    `INSERT INTO teachers (name) VALUES ('__TEST_TE_RD__') RETURNING id`
  );
  const grp = await pool.query(
    `INSERT INTO groups (name, direction_id, teacher_id, is_individual, vk_chat, group_start_date)
     VALUES ('__TEST_G_RD__', $1, $2, false, 'vk.com/x', '2025-09-01') RETURNING id`,
    [dir.rows[0].id, te.rows[0].id]
  );
  const st = await pool.query(
    `INSERT INTO students (full_name, age, pm) VALUES ('__TEST_S_RD__', 12, 'PM1') RETURNING id`
  );
  await pool.query(
    `INSERT INTO group_memberships (group_id, student_id, lessons_done, remaining, sheet_row, active)
     VALUES ($1, $2, 5.5, 4, 99, true)`,
    [grp.rows[0].id, st.rows[0].id]
  );

  const out = await readAllStudents();

  const teachers = Object.keys(out.data);
  assert.ok(teachers.includes('__TEST_TE_RD__'));

  const grpData = out.data['__TEST_TE_RD__']['__TEST_G_RD__'];
  assert.ok(grpData, 'group entry exists');
  assert.strictEqual(grpData.isGroup, true);
  assert.strictEqual(grpData.vkChat, 'vk.com/x');
  assert.strictEqual(grpData.students[0].name, '__TEST_S_RD__');
  assert.strictEqual(grpData.students[0].lessonsDone, 5.5);
  assert.strictEqual(grpData.students[0].remaining, 4);

  const idxKey = '__TEST_S_RD__|||__TEST_G_RD__';
  assert.strictEqual(out.index[idxKey].sheetRow, 99);
  assert.strictEqual(out.index[idxKey].sheetName, 'TestSheet');

  // cleanup
  await pool.query(`DELETE FROM group_memberships WHERE group_id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM students WHERE id = $1`, [st.rows[0].id]);
  await pool.query(`DELETE FROM groups WHERE id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [te.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id = $1`, [dir.rows[0].id]);
});
```

Добавь `readAllStudents` в импорт из `./db` (вверху test-файла).

- [ ] **Step 2: убедиться что тест падает**

```powershell
npm test 2>&1 | Select-String "readAllStudents"
```
Expected: fail с `readAllStudents is not a function` или undefined.

- [ ] **Step 3: реализовать `readAllStudents()` в `db.js`**

Добавь в `db.js` перед `module.exports`:

```js
function fmtDateRu(d) {
  if (!d) return '';
  // Postgres возвращает date как Date или строку 'YYYY-MM-DD'
  const date = d instanceof Date ? d : new Date(d);
  if (isNaN(date.getTime())) return String(d);
  const dd = String(date.getDate()).padStart(2, '0');
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  return `${dd}.${mm}.${date.getFullYear()}`;
}

async function readAllStudents() {
  const { rows } = await pool.query(
    `SELECT
        g.id                AS group_id,
        g.name              AS group_name,
        g.is_individual,
        g.vk_chat,
        g.group_start_date,
        te.name             AS teacher_name,
        s.id                AS student_id,
        s.full_name         AS student_name,
        s.age,
        s.pm,
        gm.id               AS membership_id,
        gm.lessons_done,
        gm.remaining,
        gm.sheet_row,
        d.sheet_name        AS direction_sheet_name
      FROM group_memberships gm
      JOIN groups   g  ON g.id = gm.group_id
      JOIN teachers te ON te.id = g.teacher_id
      JOIN students s  ON s.id = gm.student_id
      JOIN directions d ON d.id = g.direction_id
     WHERE gm.active = true
       AND g.active = true
       AND te.active = true
     ORDER BY te.name, g.name, s.full_name`
  );

  const data = {};
  const index = {};

  for (const r of rows) {
    const teacher = r.teacher_name;
    const group = r.group_name;
    const sheetName = r.is_individual ? 'Индивидуальные' : r.direction_sheet_name;

    if (!data[teacher]) data[teacher] = {};
    if (!data[teacher][group]) {
      data[teacher][group] = {
        students: [],
        lessonsDone: 0,
        pm: r.pm || '',
        vkChat: r.vk_chat || '',
        startDate: fmtDateRu(r.group_start_date),
        isGroup: !r.is_individual,
      };
    }

    const grp = data[teacher][group];
    const done = Number(r.lessons_done) || 0;
    if (done > grp.lessonsDone) grp.lessonsDone = done;

    grp.students.push({
      name: r.student_name,
      lessonsDone: done,
      remaining: Number(r.remaining) || 0,
      age: r.age != null ? String(r.age) : '',
      sheetName,
      sheetRow: r.sheet_row || 0,
    });

    if (r.sheet_row) {
      index[r.student_name + '|||' + group] = { sheetName, sheetRow: r.sheet_row };
    }
  }

  return { data, index };
}
```

Добавь `readAllStudents` в `module.exports`.

- [ ] **Step 4: проверить тест**

```powershell
npm test 2>&1 | Select-Object -Last 8
```
Expected: 69/69 pass (66 + 2 + 1).

---

### Task 4: `services/db.js` — readFilledLessons()

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\services\db.js`
- Test: `C:\Users\ilyap\TestKOTOKOD\services\db.test.js`

**Shape, который надо вернуть** (см. `services/sheets.js:282-348`):

```js
{
  [`${group_name}|||${weekStartStr}`]: '<fixedAt-string>' // например '15.04 18:32'
}
```

Где `fixedAt` — это локализованный момент когда препод первый раз отметил урок в этой группе на этой неделе. В PG источник — `lessons.submitted_at`.

- [ ] **Step 1: тест**

```js
test('readFilledLessons(): collects first submitted_at per group within week', async () => {
  // setup
  const dir = await pool.query(
    `INSERT INTO directions (name, sheet_name, is_individual) VALUES ('__TEST_DIR_RF__', 'X', false) RETURNING id`
  );
  const te = await pool.query(
    `INSERT INTO teachers (name) VALUES ('__TEST_TE_RF__') RETURNING id`
  );
  const grp = await pool.query(
    `INSERT INTO groups (name, direction_id, teacher_id, is_individual)
     VALUES ('__TEST_G_RF__', $1, $2, false) RETURNING id`,
    [dir.rows[0].id, te.rows[0].id]
  );
  await pool.query(
    `INSERT INTO lessons (lesson_date, teacher_id, group_id, lesson_number, lesson_duration_minutes, lesson_type, submitted_by_token, submitted_at)
     VALUES ('2025-04-15', $1, $2, 1, 90, 'regular', '__TEST_TOK_RF__', '2025-04-15 15:30:00+03')`,
    [te.rows[0].id, grp.rows[0].id]
  );

  const out = await readFilledLessons('2025-04-14');
  const key = '__TEST_G_RF__|||2025-04-14';
  assert.ok(out[key], 'group entry exists');
  assert.match(out[key], /15\.04/, 'fixedAt contains 15.04');

  // cleanup
  await pool.query(`DELETE FROM lessons WHERE group_id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM groups WHERE id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [te.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id = $1`, [dir.rows[0].id]);
});

test('readFilledLessons(): excludes lessons outside week range', async () => {
  const dir = await pool.query(
    `INSERT INTO directions (name, sheet_name, is_individual) VALUES ('__TEST_DIR_RF2__', 'X', false) RETURNING id`
  );
  const te = await pool.query(
    `INSERT INTO teachers (name) VALUES ('__TEST_TE_RF2__') RETURNING id`
  );
  const grp = await pool.query(
    `INSERT INTO groups (name, direction_id, teacher_id, is_individual)
     VALUES ('__TEST_G_RF2__', $1, $2, false) RETURNING id`,
    [dir.rows[0].id, te.rows[0].id]
  );
  await pool.query(
    `INSERT INTO lessons (lesson_date, teacher_id, group_id, lesson_number, lesson_duration_minutes, lesson_type, submitted_by_token)
     VALUES ('2025-01-01', $1, $2, 1, 90, 'regular', '__T__')`,
    [te.rows[0].id, grp.rows[0].id]
  );

  const out = await readFilledLessons('2025-04-14');
  assert.strictEqual(out['__TEST_G_RF2__|||2025-04-14'], undefined);

  await pool.query(`DELETE FROM lessons WHERE group_id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM groups WHERE id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [te.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id = $1`, [dir.rows[0].id]);
});
```

Добавь `readFilledLessons` в импорт.

- [ ] **Step 2: запустить — fail**

```powershell
npm test 2>&1 | Select-String "readFilledLessons"
```
Expected: fail.

- [ ] **Step 3: реализация**

В `db.js`:

```js
function fmtFixedAt(d) {
  if (!d) return '';
  const date = d instanceof Date ? d : new Date(d);
  if (isNaN(date.getTime())) return '';
  // МСК — UTC+3, без DST
  const msk = new Date(date.getTime() + 3 * 60 * 60 * 1000);
  const dd = String(msk.getUTCDate()).padStart(2, '0');
  const mm = String(msk.getUTCMonth() + 1).padStart(2, '0');
  const hh = String(msk.getUTCHours()).padStart(2, '0');
  const min = String(msk.getUTCMinutes()).padStart(2, '0');
  return `${dd}.${mm} ${hh}:${min}`;
}

async function readFilledLessons(weekStartStr) {
  const weekStart = new Date(weekStartStr + 'T00:00:00Z');
  const weekEnd = new Date(weekStart);
  weekEnd.setUTCDate(weekEnd.getUTCDate() + 6);
  const weekEndStr = weekEnd.toISOString().slice(0, 10);

  const { rows } = await pool.query(
    `SELECT g.name AS group_name, MIN(l.submitted_at) AS first_at
       FROM lessons l
       JOIN groups g ON g.id = l.group_id
      WHERE l.lesson_date BETWEEN $1::date AND $2::date
      GROUP BY g.name`,
    [weekStartStr, weekEndStr]
  );

  const map = {};
  for (const r of rows) {
    map[r.group_name + '|||' + weekStartStr] = fmtFixedAt(r.first_at);
  }
  return map;
}
```

Добавь в `module.exports`.

- [ ] **Step 4: тесты проходят**

```powershell
npm test 2>&1 | Select-Object -Last 8
```
Expected: 71/71 pass.

---

### Task 5: `services/db.js` — incrementCounters() + insertLesson() + insertAttendance() + insertPayroll()

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\services\db.js`
- Test: `C:\Users\ilyap\TestKOTOKOD\services\db.test.js`

Эти 4 функции работают **через переданный `client`** (для использования внутри `tx()`). Если client не передан — используют `pool` (для удобства standalone-вызовов).

**Сигнатуры:**

```js
incrementCounters(client, membershipIds, step)     // step = 0.5 или 1
insertLesson(client, fields)  → lesson_id          // fields см. ниже
insertAttendance(client, lessonId, attendanceArr)  // [{student_id, present}]
insertPayroll(client, payrollFields)
```

`fields` для insertLesson:
```js
{
  lesson_date,                  // 'YYYY-MM-DD'
  teacher_id,                   // int
  group_id,                     // int
  original_teacher_id,          // int | null
  lesson_number,                // numeric(5,1)
  lesson_duration_minutes,      // int
  lesson_type,                  // 'regular' | 'substitution' | 'reschedule'
  record_url,                   // string | null
  submitted_by_token,           // string
}
```

`payrollFields`:
```js
{
  lesson_id, teacher_id,
  total_students, present_count,
  payment, penalty
}
```

- [ ] **Step 1: один интеграционный тест на весь tx**

```js
test('incrementCounters + insertLesson + insertAttendance + insertPayroll: atomic write', async () => {
  const dir = await pool.query(
    `INSERT INTO directions (name, sheet_name, is_individual) VALUES ('__TEST_DIR_WR__', 'X', false) RETURNING id`
  );
  const te = await pool.query(
    `INSERT INTO teachers (name) VALUES ('__TEST_TE_WR__') RETURNING id`
  );
  const grp = await pool.query(
    `INSERT INTO groups (name, direction_id, teacher_id, is_individual)
     VALUES ('__TEST_G_WR__', $1, $2, false) RETURNING id`,
    [dir.rows[0].id, te.rows[0].id]
  );
  const st = await pool.query(
    `INSERT INTO students (full_name) VALUES ('__TEST_S_WR__') RETURNING id`
  );
  const m = await pool.query(
    `INSERT INTO group_memberships (group_id, student_id, lessons_done, remaining)
     VALUES ($1, $2, 0, 10) RETURNING id`,
    [grp.rows[0].id, st.rows[0].id]
  );

  const lessonId = await tx(async (client) => {
    const lid = await insertLesson(client, {
      lesson_date: '2025-04-15',
      teacher_id: te.rows[0].id,
      group_id: grp.rows[0].id,
      original_teacher_id: null,
      lesson_number: 1,
      lesson_duration_minutes: 90,
      lesson_type: 'regular',
      record_url: null,
      submitted_by_token: '__TEST_TOK_WR__',
    });
    await incrementCounters(client, [m.rows[0].id], 1);
    await insertAttendance(client, lid, [
      { student_id: st.rows[0].id, present: true },
    ]);
    await insertPayroll(client, {
      lesson_id: lid,
      teacher_id: te.rows[0].id,
      total_students: 1,
      present_count: 1,
      payment: 500,
      penalty: 0,
    });
    return lid;
  });

  const lesson = (await pool.query(`SELECT * FROM lessons WHERE id = $1`, [lessonId])).rows[0];
  assert.strictEqual(lesson.lesson_number, '1.0');

  const att = (await pool.query(`SELECT * FROM lesson_attendance WHERE lesson_id = $1`, [lessonId])).rows;
  assert.strictEqual(att.length, 1);
  assert.strictEqual(att[0].present, true);

  const pay = (await pool.query(`SELECT * FROM payroll WHERE lesson_id = $1`, [lessonId])).rows[0];
  assert.strictEqual(Number(pay.payment), 500);

  const mAfter = (await pool.query(`SELECT lessons_done FROM group_memberships WHERE id = $1`, [m.rows[0].id])).rows[0];
  assert.strictEqual(Number(mAfter.lessons_done), 1);

  // cleanup
  await pool.query(`DELETE FROM payroll WHERE lesson_id = $1`, [lessonId]);
  await pool.query(`DELETE FROM lesson_attendance WHERE lesson_id = $1`, [lessonId]);
  await pool.query(`DELETE FROM lessons WHERE id = $1`, [lessonId]);
  await pool.query(`DELETE FROM group_memberships WHERE id = $1`, [m.rows[0].id]);
  await pool.query(`DELETE FROM students WHERE id = $1`, [st.rows[0].id]);
  await pool.query(`DELETE FROM groups WHERE id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [te.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id = $1`, [dir.rows[0].id]);
});

test('insertLesson: rollback on error within tx', async () => {
  const dir = await pool.query(
    `INSERT INTO directions (name, sheet_name, is_individual) VALUES ('__TEST_DIR_RB__', 'X', false) RETURNING id`
  );
  const te = await pool.query(
    `INSERT INTO teachers (name) VALUES ('__TEST_TE_RB__') RETURNING id`
  );
  const grp = await pool.query(
    `INSERT INTO groups (name, direction_id, teacher_id, is_individual)
     VALUES ('__TEST_G_RB__', $1, $2, false) RETURNING id`,
    [dir.rows[0].id, te.rows[0].id]
  );

  await assert.rejects(() => tx(async (client) => {
    await insertLesson(client, {
      lesson_date: '2025-04-15',
      teacher_id: te.rows[0].id,
      group_id: grp.rows[0].id,
      original_teacher_id: null,
      lesson_number: 1,
      lesson_duration_minutes: 90,
      lesson_type: 'regular',
      record_url: null,
      submitted_by_token: '__TEST_TOK_RB__',
    });
    throw new Error('intentional fail');
  }), /intentional fail/);

  const lessons = await pool.query(
    `SELECT 1 FROM lessons WHERE group_id = $1 AND submitted_by_token = '__TEST_TOK_RB__'`,
    [grp.rows[0].id]
  );
  assert.strictEqual(lessons.rows.length, 0, 'no lesson should be written on rollback');

  await pool.query(`DELETE FROM groups WHERE id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [te.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id = $1`, [dir.rows[0].id]);
});
```

Добавь в импорт: `insertLesson, insertAttendance, insertPayroll, incrementCounters`.

- [ ] **Step 2: fail**

```powershell
npm test 2>&1 | Select-Object -Last 8
```
Expected: новые тесты падают (функции — заглушки).

- [ ] **Step 3: реализация. Заменить блок заглушек в `db.js`**

```js
async function incrementCounters(client, membershipIds, step) {
  if (!Array.isArray(membershipIds) || !membershipIds.length) return;
  await client.query(
    `UPDATE group_memberships SET lessons_done = lessons_done + $1 WHERE id = ANY($2::int[])`,
    [step, membershipIds]
  );
}

async function insertLesson(client, f) {
  const { rows } = await client.query(
    `INSERT INTO lessons
       (lesson_date, teacher_id, group_id, original_teacher_id,
        lesson_number, lesson_duration_minutes, lesson_type,
        record_url, submitted_by_token)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
     RETURNING id`,
    [f.lesson_date, f.teacher_id, f.group_id, f.original_teacher_id,
     f.lesson_number, f.lesson_duration_minutes, f.lesson_type,
     f.record_url, f.submitted_by_token]
  );
  return rows[0].id;
}

async function insertAttendance(client, lessonId, attendance) {
  if (!Array.isArray(attendance) || !attendance.length) return;
  const studentIds = attendance.map((a) => a.student_id);
  const presents = attendance.map((a) => !!a.present);
  await client.query(
    `INSERT INTO lesson_attendance (lesson_id, student_id, present)
     SELECT $1, s.id, p.present
       FROM unnest($2::int[], $3::bool[]) AS p(student_id, present)
       JOIN students s ON s.id = p.student_id
     ON CONFLICT (lesson_id, student_id) DO NOTHING`,
    [lessonId, studentIds, presents]
  );
}

async function insertPayroll(client, f) {
  await client.query(
    `INSERT INTO payroll (lesson_id, teacher_id, total_students, present_count, payment, penalty)
     VALUES ($1, $2, $3, $4, $5, $6)`,
    [f.lesson_id, f.teacher_id, f.total_students, f.present_count, f.payment, f.penalty]
  );
}
```

Удали блок `notImplemented`-заглушек:
```js
function notImplemented(name) { ... }
const incrementCounters = notImplemented('incrementCounters');
...
```

`module.exports` обнови (если ещё не):
```js
module.exports = {
  pool, tx, shutdown,
  readTokens, readAllStudents, readFilledLessons,
  incrementCounters, insertLesson, insertAttendance, insertPayroll,
};
```

- [ ] **Step 4: тесты**

```powershell
npm test 2>&1 | Select-Object -Last 8
```
Expected: 73/73 pass (66 + 7 новых).

---

### Task 6: `services/repository.js` — переписать на PG-прокси

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\services\repository.js`

- [ ] **Step 1: переписать файл целиком**

```js
// services/repository.js
//
// Phase 3a: thin proxy над services/db.js (PG canonical).
// Sheets-зависимости удалены. Backfill-скрипты используют sheets.js напрямую.

const db = require('./db');

module.exports = {
  readTokens:        db.readTokens,
  readAllStudents:   db.readAllStudents,
  readFilledLessons: db.readFilledLessons,
};
```

Заметь: `readStudentsRange`, `batchUpdateCounters`, `appendToJournal` — **больше не экспортируются**. Их используют только `submitLesson` (который полностью переписывается в Task 7).

- [ ] **Step 2: верификация что тесты ещё зелёные**

```powershell
npm test 2>&1 | Select-Object -Last 8
```
Expected: 73/73 pass.

---

### Task 7: `server.js` — переписать `submitLesson` под `db.tx()`

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\server.js`

Текущий `submitLesson` живёт примерно в `server.js:76-220` (~145 строк) — читает token, ищет группу в кеше, обновляет счётчики через `repo.batchUpdateCounters`, пишет в журнал через `repo.appendToJournal`, потом в зарплату.

После переписывания: один `db.tx()`, всё атомарно.

- [ ] **Step 1: вверху `server.js` импортировать `db`**

Найди блок импортов в начале файла:
```js
const repo = require('./services/repository');
const cache = require('./services/cache');
const calc = require('./services/calculator');
const adminAuth = require('./services/admin-auth');
const adminRepo = require('./services/admin-repo');
```

Замени на:
```js
const repo = require('./services/repository');
const calc = require('./services/calculator');
const db   = require('./services/db');
const adminAuth = require('./services/admin-auth');
const adminRepo = require('./services/admin-repo');
```

(Импорт `cache` удалён.)

- [ ] **Step 2: переписать `submitLesson` endpoint**

Найди `app.post('/api/submitLesson', ...)` в `server.js` и **замени всё тело callback'а** на следующее. Аккуратно сохрани сигнатуру `app.post(...)` и обрамляющие фигурные скобки:

```js
app.post('/api/submitLesson', async (req, res) => {
    try {
        const {
            token, group, date, recordUrl,
            lessonType, isSubstitution, originalTeacher, students
        } = req.body;

        // 1. Auth
        const tokens = await repo.readTokens();
        const teacher = tokens[token];
        if (!teacher) return res.json({ success: false, error: 'Неверный токен' });

        // 2. Получаем актуальное состояние ученика и группы
        const unified = await repo.readAllStudents();
        const teacherForGroup = isSubstitution && originalTeacher ? originalTeacher : teacher;
        if (!unified.data[teacherForGroup] || !unified.data[teacherForGroup][group]) {
            return res.json({ success: false, error: 'Группа не найдена' });
        }
        const groupData = unified.data[teacherForGroup][group];

        // 3. Расчёты
        const isHalf = /45\s*минут/i.test(group);
        const step = isHalf ? 0.5 : 1;
        const totalStudents = students.length;
        const presentCount = students.filter((s) => s.present).length;
        const presentStudents = students.filter((s) => s.present);
        const done = groupData.students.length
            ? Math.max(...groupData.students.map((s) => s.lessonsDone || 0))
            : 0;
        const lessonNum = Math.round((done + step) * 10) / 10;
        const payment = calc.calculatePayment(totalStudents, presentCount, isHalf);
        const penalty = calc.calculatePenalty(date, calc.formatMskDate());

        // 4. Resolve IDs через PG
        const idsRes = await db.pool.query(
            `SELECT te.id   AS teacher_id,
                    g.id    AS group_id,
                    g.lesson_duration_minutes,
                    ot.id   AS original_teacher_id
               FROM teachers te
               JOIN groups g ON g.teacher_id = te.id AND g.name = $2
               LEFT JOIN teachers ot ON ot.name = NULLIF($3, '')
              WHERE te.name = $1
              LIMIT 1`,
            [teacher, group, isSubstitution ? originalTeacher : '']
        );
        if (!idsRes.rows.length) {
            return res.json({ success: false, error: 'Группа/преподаватель не найдены в БД' });
        }
        const ids = idsRes.rows[0];

        // 5. Соберём mapping student_name → {student_id, membership_id} для группы
        const studRes = await db.pool.query(
            `SELECT s.id AS student_id, s.full_name, gm.id AS membership_id
               FROM students s
               JOIN group_memberships gm ON gm.student_id = s.id
              WHERE gm.group_id = $1 AND gm.active = true`,
            [ids.group_id]
        );
        const byName = new Map(studRes.rows.map((r) => [r.full_name, r]));

        const presentMembershipIds = [];
        const attendance = [];
        for (const s of students) {
            const meta = byName.get(s.name);
            if (!meta) {
                console.warn(`⚠️ submitLesson: студент "${s.name}" не найден в group_memberships для group_id=${ids.group_id}`);
                continue;
            }
            attendance.push({ student_id: meta.student_id, present: !!s.present });
            if (s.present) presentMembershipIds.push(meta.membership_id);
        }

        // 6. Один atomic tx
        const subLabel = isSubstitution ? 'substitution' : (lessonType === 'reschedule' ? 'reschedule' : 'regular');

        const lessonId = await db.tx(async (client) => {
            const lid = await db.insertLesson(client, {
                lesson_date: date,
                teacher_id:  ids.teacher_id,
                group_id:    ids.group_id,
                original_teacher_id: isSubstitution ? (ids.original_teacher_id || null) : null,
                lesson_number: lessonNum,
                lesson_duration_minutes: ids.lesson_duration_minutes,
                lesson_type: subLabel,
                record_url: recordUrl || null,
                submitted_by_token: token,
            });
            await db.incrementCounters(client, presentMembershipIds, step);
            await db.insertAttendance(client, lid, attendance);
            await db.insertPayroll(client, {
                lesson_id: lid,
                teacher_id: ids.teacher_id,
                total_students: totalStudents,
                present_count: presentCount,
                payment,
                penalty,
            });
            return lid;
        });

        console.log(`📝 submitLesson OK: lesson_id=${lessonId}, group="${group}", num=${lessonNum}`);
        res.json({ success: true });

    } catch (error) {
        console.error('❌ submitLesson error:', error);
        res.status(500).json({ success: false, error: error.message });
    }
});
```

- [ ] **Step 3: syntax check**

```powershell
node --check server.js
```
Expected: exit code 0.

- [ ] **Step 4: тесты остаются зелёными**

```powershell
npm test 2>&1 | Select-Object -Last 8
```
Expected: 73/73 pass.

---

### Task 8: `server.js` — зачистить `cache.*` вызовы в остальных эндпоинтах

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\server.js`

Помимо `submitLesson` (уже переписан), `cache` использовали `/api/getData`, `/api/getAllData`, `/api/report`, `/api/schedule` для шарирования `unified_data`. После cutover — просто читаем напрямую через `repo.readAllStudents()`.

Также есть три `refresh`-эндпоинта (`/api/refreshData`, `/api/report/refresh`, `/api/schedule/refresh`) — становятся no-op (кеша нет, нечего сбрасывать).

- [ ] **Step 1: убрать использование `cache` из `/api/getData`**

Найди в `server.js`:
```js
let unified = cache.get('unified_data');
if (!unified) {
    console.log('🔄 Cache MISS — читаем Google Sheets');
    unified = await repo.readAllStudents();
    cache.set('unified_data', unified);
} else {
    console.log('✅ Cache HIT');
}
```

Замени на:
```js
const unified = await repo.readAllStudents();
```

Это паттерн встречается в нескольких эндпоинтах. **Применить ко всем** — `getData`, `getAllData`, `report`, `schedule`. После замены grep'нем чтобы убедиться что `cache.` не осталось.

- [ ] **Step 2: `/api/refreshData` → no-op**

Найди:
```js
app.post('/api/refreshData', async (req, res) => {
    ...
    cache.del('unified_data');
    ...
});
```

Замени всё тело на:
```js
app.post('/api/refreshData', async (_req, res) => {
    // Phase 3a: PG canonical, кеша больше нет — endpoint оставлен ради backward-compat с фронтом.
    res.json({ success: true });
});
```

- [ ] **Step 3: `/api/report/refresh` → no-op (редирект)**

Найди:
```js
app.get('/api/report/refresh', async (req, res) => {
    cache.del(...);
    res.redirect('/api/report');
});
```

Замени на:
```js
app.get('/api/report/refresh', (_req, res) => {
    res.redirect('/api/report');
});
```

- [ ] **Step 4: `/api/schedule/refresh` → no-op (редирект)**

Аналогично:
```js
app.get('/api/schedule/refresh', (_req, res) => {
    res.redirect('/api/schedule');
});
```

- [ ] **Step 5: verify — `cache` больше не используется**

```powershell
Select-String -Path server.js -Pattern "cache\." -SimpleMatch
```
Expected: пусто (никаких упоминаний).

- [ ] **Step 6: syntax + tests**

```powershell
node --check server.js
npm test 2>&1 | Select-Object -Last 8
```
Expected: exit 0; 73/73 pass.

---

### Task 9: удалить `services/cache.js` + почистить `.env.example`

**Files:**
- Delete: `services/cache.js`
- Modify: `.env.example`

- [ ] **Step 1: удалить файл**

```powershell
Remove-Item services\cache.js
```

- [ ] **Step 2: проверка что нигде не импортируется**

```powershell
Select-String -Path *.js,services\*.js,scripts\*.js -Pattern "require.*'\.\./?services/cache'" -SimpleMatch
```
Expected: пусто.

- [ ] **Step 3: почистить `.env.example`**

Открой `.env.example`. Удали строки:
```
DUAL_WRITE_ENABLED=false
READ_FROM=sheets
CACHE_TTL=300
```

Если есть в `.env` локальном — тоже можно удалить (но это не обязательно, неиспользуемые ключи никому не мешают).

- [ ] **Step 4: финал-проверка**

```powershell
npm start 2>&1 | Select-Object -First 8
```

В отдельном окне. Дождись «🚀 Сервер запущен на порту 3000». **Не должно быть** ошибок про отсутствие `cache.js` или `CACHE_TTL`.

Останови сервер `Ctrl+C`.

---

### Task 10: post-cutover snapshot + diff

**Files:**
- Create: `docs/post-cutover/*.json` (и `.html`)
- Create: `docs/cutover-runbook.md`

- [ ] **Step 1: запустить сервер с PG-версией**

```powershell
npm start
```

В отдельном окне.

- [ ] **Step 2: повторить все 7 curl-запросов в `docs/post-cutover/`**

Используй те же два токена что и в Task 1.

```powershell
mkdir docs\post-cutover -Force | Out-Null
curl -s -X POST -H "Content-Type: application/json" -d "{`"token`":`"<TOKEN_A>`"}" http://localhost:3000/api/validateToken > docs\post-cutover\validateToken-tokenA.json
curl -s -X POST -H "Content-Type: application/json" -d "{`"token`":`"invalid`"}" http://localhost:3000/api/validateToken > docs\post-cutover\validateToken-invalid.json
curl -s -X POST -H "Content-Type: application/json" -d "{`"token`":`"<TOKEN_A>`"}" http://localhost:3000/api/getData > docs\post-cutover\getData-tokenA.json
curl -s -X POST -H "Content-Type: application/json" -d "{`"token`":`"<TOKEN_B>`"}" http://localhost:3000/api/getData > docs\post-cutover\getData-tokenB.json
curl -s -X POST -H "Content-Type: application/json" -d "{`"token`":`"<TOKEN_A>`"}" http://localhost:3000/api/getAllData > docs\post-cutover\getAllData.json
curl -s http://localhost:3000/api/report > docs\post-cutover\report.html
curl -s http://localhost:3000/api/schedule > docs\post-cutover\schedule.html
```

- [ ] **Step 3: diff**

```powershell
fc docs\baseline\validateToken-tokenA.json docs\post-cutover\validateToken-tokenA.json
fc docs\baseline\validateToken-invalid.json docs\post-cutover\validateToken-invalid.json
fc docs\baseline\getData-tokenA.json docs\post-cutover\getData-tokenA.json
fc docs\baseline\getData-tokenB.json docs\post-cutover\getData-tokenB.json
fc docs\baseline\getAllData.json docs\post-cutover\getAllData.json
fc docs\baseline\report.html docs\post-cutover\report.html
fc docs\baseline\schedule.html docs\post-cutover\schedule.html
```

**Что ожидаем:**
- `validateToken-*` — идентичны (просто `{valid: true, teacher: "..."}`)
- `getData-*` — могут отличаться:
  - Порядком ключей в JSON (это допустимо)
  - Точными значениями `lessonsDone` (если ты делал правки через админку — PG имеет более свежие значения)
  - **Не должно** быть структурных отличий: пропавших полей, кардинально других значений
- `getAllData` — аналогично
- `report.html`, `schedule.html` — могут различаться `fixedAt`-форматами (МСК-форматирование может округлять секунды иначе); порядок групп; CSS-генерированный текст. Структурно — те же группы, те же ученики

**Что критично:** список учеников в каждой группе должен совпадать. Если в PG-версии у какого-то препода **меньше** групп или учеников — это bug.

- [ ] **Step 4: manual smoke в браузере**

Открой `http://localhost:3000/`. Войди реальным токеном.

Чеклист:
- [ ] Видишь свои группы
- [ ] Кликаешь на группу — видишь учеников с правильными счётчиками
- [ ] Отправляешь **тестовый** урок (выбери группу без последствий, например, тестовую). После отправки — счётчик ученика обновился, нет ошибок в DevTools
- [ ] Проверь /api/report (в новой вкладке через URL) — отображается отчёт
- [ ] Проверь /api/schedule — отображается расписание

Если всё OK — cutover успешен.

- [ ] **Step 5: написать runbook `docs/cutover-runbook.md`**

```markdown
# Cutover Phase 3a runbook

Дата выполнения cutover: <ЗАПОЛНИ>
Дамп до cutover: `backups/pre-cutover-<date>.sql`

## Результат

- 8 teacher-эндпоинтов переведены на PostgreSQL
- `submitLesson` атомарен через `db.tx()`
- `services/cache.js` удалён
- Запись в Google Sheets отключена
- Baseline / post-cutover snapshots: `docs/baseline/` ↔ `docs/post-cutover/`

## Rollback (catastrophe)

1. `npm start` остановить (Ctrl+C)
2. `psql -U journal -h localhost -d journal < backups/pre-cutover-<date>.sql`
3. Восстановить старую версию `services/repository.js` и `server.js` из истории (если под git) или из бэкапов `*.backup-pre-cutover` (если делал).
4. Восстановить `services/cache.js` из истории.
5. `npm start`.

## Rollback (soft, баг в коде)

- Fix-forward + restart.
- Точечный SQL-fix через psql при необходимости.

## Phase 3b — следующий шаг

Админка для операционных таблиц (`lessons`, `lesson_attendance`, `payroll`). Отдельный spec.

## Phase 5 — финальная очистка (отложено)

- Удалить `services/sheets.js`, `googleapis`, `service-account-key.json`
- Удалить колонки `sheet_row` / `sheet_name` из БД
- Удалить `STUDENTS_SPREADSHEET_ID` / `JOURNAL_SPREADSHEET_ID` из `.env`
```

- [ ] **Step 6: финал**

Остановить сервер. Финальный прогон:
```powershell
npm test 2>&1 | Select-Object -Last 8
node --check server.js
```
Expected: 73 pass; exit 0.

---

## Финальная проверка (acceptance)

- [ ] `npm test` — 73/73 pass (66 базовых + 7 новых)
- [ ] `services/cache.js` отсутствует в `services/`
- [ ] `services/repository.js` не импортирует `./sheets`
- [ ] `server.js` не содержит `require('./services/cache')` и `cache.` вызовов
- [ ] `pg_dump` лежит в `backups/`
- [ ] `docs/baseline/*` и `docs/post-cutover/*` существуют
- [ ] `docs/cutover-runbook.md` создан
- [ ] Manual smoke в браузере (Step 4 в Task 10) — все галки

---

## Что НЕ входит в Phase 3a

- Admin для `lessons`/`lesson_attendance`/`payroll` → **Phase 3b** (отдельный spec)
- Удаление `services/sheets.js`, `googleapis` → Phase 5
- Дроп колонок `sheet_row`/`sheet_name` → Phase 5
- Удаление `STUDENTS_SPREADSHEET_ID` / `JOURNAL_SPREADSHEET_ID` из `.env` → Phase 5

---

## Откат (если что-то идёт сильно не так в процессе)

```powershell
# 1. Останови сервер
# 2. Восстанови PG из дампа
$env:PGPASSWORD = "journal_dev_password"
psql -U journal -h localhost -d journal -f backups\pre-cutover-<date>.sql

# 3. Откатить файлы из истории (если под git) или восстановить из *.backup
# Файлы которые мы трогаем:
#   - services/db.js          (расширен)
#   - services/db.test.js     (расширен)
#   - services/repository.js  (переписан)
#   - services/cache.js       (удалён)
#   - server.js               (переписан submitLesson + кеш-вызовы)
#   - .env.example            (почищен)
```
