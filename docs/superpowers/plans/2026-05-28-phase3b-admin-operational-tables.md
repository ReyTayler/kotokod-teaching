# Phase 3b — Admin for Operational Tables — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать админу UI для CRUD по операционным таблицам (`lessons`, `lesson_attendance`, `payroll`) — просмотр с фильтрами, правка, удаление, создание задним числом — чтобы чинить данные без `psql`.

**Architecture:** Расширение существующего admin-стека. Backend: 10 новых эндпоинтов `/api/admin/lessons*`, `/lesson-attendance/*`, `/payroll*` поверх 9 новых функций в `services/admin-repo.js`. Frontend: 2 новых раздела sidebar («Уроки», «Зарплата»), новая detail-страница урока с inline-edit attendance + payroll, полная create-форма для урока, секция «Уроки группы» на странице группы. Calculator-логика дублируется на клиент (10 строк).

**Tech Stack:** PostgreSQL, Express, node:test, vanilla JS (admin SPA).

**Reference spec:** `docs/superpowers/specs/2026-05-28-phase3b-admin-operational-tables-design.md`

**Project state:** проект не под git → шаги `commit` пропускаются. Phase 3a выполнена: teacher SPA на PG, кеша нет.

---

## File structure

| Путь | Создаётся / меняется | Ответственность |
|------|----------------------|-----------------|
| `services/admin-repo.js` | расширяется | +9 функций для lessons/attendance/payroll |
| `services/admin-repo.test.js` | расширяется | +smoke-тесты на новые функции |
| `server.js` | расширяется | +10 admin-эндпоинтов |
| `public/admin-app.js` | расширяется | +2 SECTION_RENDERERS + 1 DETAIL_RENDERERS + 1 modal + Group detail tab + calculator helper |
| `public/admin.html` | возможно правится | CSS для inline payroll edit (если стилей не хватит) |
| `docs/admin-smoke-tests.md` | расширяется | Новый раздел «Уроки + Зарплата» |
| `services/db.js` | НЕ меняется | Используются существующие `pool` и `tx` |

---

## Testing strategy

- **Unit smoke** в `services/admin-repo.test.js` — гоняем против локальной PG: создать тестовый lesson через `createLessonFull`, прочитать через `getLessonFull`, поправить через `updateLesson`/`updateAttendanceCell`/`updatePayroll`, удалить через `deleteLessonFull`. Cleanup в каждом тесте.
- **Existing 73 тестов** остаются зелёными.
- **Manual UI smoke** — добавлен раздел в `docs/admin-smoke-tests.md` (заполнятся вручную после реализации).

---

## Tasks

### Task 1: admin-repo — lessons CRUD (list, getFull, createFull, update, deleteFull) + 2 smoke-теста

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\services\admin-repo.js`
- Modify: `C:\Users\ilyap\TestKOTOKOD\services\admin-repo.test.js`

- [ ] **Step 1: Добавить в `services/admin-repo.js` (после блока memberships, перед `module.exports`):**

```js
// ===== Lessons (operational) =====

async function listLessons({ group_id, teacher_id, date_from, date_to } = {}) {
  const conds = [];
  const params = [];
  if (group_id)   { params.push(group_id);   conds.push(`l.group_id = $${params.length}`); }
  if (teacher_id) { params.push(teacher_id); conds.push(`l.teacher_id = $${params.length}`); }
  if (date_from)  { params.push(date_from);  conds.push(`l.lesson_date >= $${params.length}`); }
  if (date_to)    { params.push(date_to);    conds.push(`l.lesson_date <= $${params.length}`); }
  const where = conds.length ? `WHERE ${conds.join(' AND ')}` : '';
  const { rows } = await pool.query(
    `SELECT l.*,
            g.name AS group_name,
            te.name AS teacher_name,
            ot.name AS original_teacher_name,
            p.id AS payroll_id, p.total_students, p.present_count, p.payment, p.penalty
       FROM lessons l
       JOIN groups g    ON g.id = l.group_id
       JOIN teachers te ON te.id = l.teacher_id
       LEFT JOIN teachers ot ON ot.id = l.original_teacher_id
       LEFT JOIN payroll p   ON p.lesson_id = l.id
       ${where}
       ORDER BY l.lesson_date DESC, l.lesson_number DESC
       LIMIT 1000`,
    params,
  );
  return rows;
}

async function getLessonFull(id) {
  const lessonRes = await pool.query(
    `SELECT l.*,
            g.name AS group_name,
            te.name AS teacher_name,
            ot.name AS original_teacher_name
       FROM lessons l
       JOIN groups g    ON g.id = l.group_id
       JOIN teachers te ON te.id = l.teacher_id
       LEFT JOIN teachers ot ON ot.id = l.original_teacher_id
       WHERE l.id = $1`,
    [id],
  );
  if (!lessonRes.rows.length) return null;
  const lesson = lessonRes.rows[0];

  const attRes = await pool.query(
    `SELECT la.student_id, la.present, s.full_name AS student_name
       FROM lesson_attendance la
       JOIN students s ON s.id = la.student_id
       WHERE la.lesson_id = $1
       ORDER BY s.full_name`,
    [id],
  );
  lesson.attendance = attRes.rows;

  const payRes = await pool.query(
    `SELECT id, total_students, present_count, payment, penalty FROM payroll WHERE lesson_id = $1`,
    [id],
  );
  lesson.payroll = payRes.rows[0] || null;

  return lesson;
}

async function createLessonFull(input) {
  return tx(async (client) => {
    const l = await client.query(
      `INSERT INTO lessons
         (lesson_date, teacher_id, group_id, original_teacher_id,
          lesson_number, lesson_duration_minutes, lesson_type,
          record_url, submitted_by_token)
       VALUES ($1, $2, $3, $4, $5, $6, $7, NULLIF($8,''), $9)
       RETURNING id`,
      [input.lesson_date, input.teacher_id, input.group_id,
       input.original_teacher_id ?? null,
       input.lesson_number, input.lesson_duration_minutes ?? 90,
       input.lesson_type ?? 'regular',
       input.record_url ?? null,
       input.submitted_by_token ?? 'admin-imported'],
    );
    const lessonId = l.rows[0].id;

    if (Array.isArray(input.attendance) && input.attendance.length) {
      const sids = input.attendance.map((a) => a.student_id);
      const pres = input.attendance.map((a) => !!a.present);
      await client.query(
        `INSERT INTO lesson_attendance (lesson_id, student_id, present)
         SELECT $1, s.id, p.present
           FROM unnest($2::int[], $3::bool[]) AS p(student_id, present)
           JOIN students s ON s.id = p.student_id
         ON CONFLICT (lesson_id, student_id) DO NOTHING`,
        [lessonId, sids, pres],
      );
    }

    if (input.payroll) {
      await client.query(
        `INSERT INTO payroll (lesson_id, teacher_id, total_students, present_count, payment, penalty)
         VALUES ($1, $2, $3, $4, $5, $6)`,
        [lessonId, input.teacher_id,
         input.payroll.total_students ?? 0,
         input.payroll.present_count ?? 0,
         input.payroll.payment ?? 0,
         input.payroll.penalty ?? 0],
      );
    }

    return lessonId;
  });
}

async function updateLesson(id, fields) {
  const { rows } = await pool.query(
    `UPDATE lessons SET
       lesson_date          = COALESCE($2, lesson_date),
       teacher_id           = COALESCE($3, teacher_id),
       lesson_number        = COALESCE($4, lesson_number),
       lesson_type          = COALESCE($5, lesson_type),
       record_url           = COALESCE(NULLIF($6,''), record_url),
       original_teacher_id  = $7
     WHERE id = $1 RETURNING *`,
    [id,
     fields.lesson_date ?? null,
     fields.teacher_id ?? null,
     fields.lesson_number ?? null,
     fields.lesson_type ?? null,
     fields.record_url ?? null,
     fields.original_teacher_id === undefined ? undefined : fields.original_teacher_id],
  );
  // Note: original_teacher_id is explicitly nullable, so undefined → keep, null → clear.
  // Pg pattern: if undefined, fall back to a re-select. Simpler: use COALESCE for it too.
  return rows[0] || null;
}

async function deleteLessonFull(id) {
  return tx(async (client) => {
    await client.query(`DELETE FROM payroll WHERE lesson_id = $1`, [id]);
    const r = await client.query(`DELETE FROM lessons WHERE id = $1`, [id]);
    return r.rowCount > 0;
  });
}
```

**Подсказка:** `updateLesson` имеет нюанс с `original_teacher_id` — это nullable поле, и нужно различать «не менять» vs «явно очистить». Проще всего использовать `COALESCE` и принять, что через PATCH явно очистить нельзя — для clear придётся отдельный path. На MVP примем «через UI нужно поменять lesson_type на не-substitution → original_teacher_id очищается в отдельной логике». **Упростим**: всегда писать `original_teacher_id = $7` без COALESCE, но требовать чтобы клиент явно прислал значение (null или id) если хочет менять; иначе не должен прислать поле и упасть. Чтобы не усложнять — добавь специальную семантику в коде:

Замени реализацию `updateLesson` на эту (проще):

```js
async function updateLesson(id, fields) {
  // Если в fields нет original_teacher_id — сохраняем текущее значение через подзапрос.
  const sql = `UPDATE lessons SET
     lesson_date          = COALESCE($2, lesson_date),
     teacher_id           = COALESCE($3, teacher_id),
     lesson_number        = COALESCE($4, lesson_number),
     lesson_type          = COALESCE($5, lesson_type),
     record_url           = COALESCE(NULLIF($6,''), record_url),
     original_teacher_id  = CASE WHEN $8::bool THEN $7 ELSE original_teacher_id END
   WHERE id = $1 RETURNING *`;
  const hasOriginal = Object.prototype.hasOwnProperty.call(fields, 'original_teacher_id');
  const { rows } = await pool.query(sql, [
    id,
    fields.lesson_date ?? null,
    fields.teacher_id ?? null,
    fields.lesson_number ?? null,
    fields.lesson_type ?? null,
    fields.record_url ?? null,
    hasOriginal ? (fields.original_teacher_id ?? null) : null,
    hasOriginal,
  ]);
  return rows[0] || null;
}
```

Также обнови `module.exports` в конце `services/admin-repo.js` чтобы экспортировать новые функции. Найди существующий `module.exports = { ... }` и добавь:

```js
  // lessons
  listLessons, getLessonFull, createLessonFull, updateLesson, deleteLessonFull,
```

в общий объект.

- [ ] **Step 2: Добавить тест в `services/admin-repo.test.js`**

В конец файла, перед последним `await pool.end()` если есть (вряд ли — db.test.js имеет его, не admin-repo.test.js). Сначала проверь начало файла на импорт — добавь нужные функции:

В строке `const repo = require('./admin-repo');` — этого хватит, `repo.X` будет работать.

Добавь тесты:

```js
test('lessons: createFull → getFull → update → deleteFull', async () => {
  // setup
  const dir = await pool.query(
    `INSERT INTO directions (name, sheet_name, is_individual) VALUES ('__T_DIR_L__', 'X', false) RETURNING id`
  );
  const te = await pool.query(
    `INSERT INTO teachers (name) VALUES ('__T_TE_L__') RETURNING id`
  );
  const grp = await pool.query(
    `INSERT INTO groups (name, direction_id, teacher_id, is_individual)
     VALUES ('__T_G_L__', $1, $2, false) RETURNING id`,
    [dir.rows[0].id, te.rows[0].id]
  );
  const st = await pool.query(
    `INSERT INTO students (full_name) VALUES ('__T_S_L__') RETURNING id`
  );

  // create
  const lessonId = await repo.createLessonFull({
    lesson_date: '2025-05-15',
    teacher_id: te.rows[0].id,
    group_id: grp.rows[0].id,
    lesson_number: 1,
    lesson_duration_minutes: 90,
    lesson_type: 'regular',
    submitted_by_token: 'admin-imported',
    attendance: [{ student_id: st.rows[0].id, present: true }],
    payroll: { total_students: 1, present_count: 1, payment: 500, penalty: 0 },
  });
  assert.ok(lessonId);

  // getFull
  const full = await repo.getLessonFull(lessonId);
  assert.strictEqual(full.group_name, '__T_G_L__');
  assert.strictEqual(full.teacher_name, '__T_TE_L__');
  assert.strictEqual(full.attendance.length, 1);
  assert.strictEqual(full.attendance[0].present, true);
  assert.strictEqual(Number(full.payroll.payment), 500);

  // update
  const upd = await repo.updateLesson(lessonId, { lesson_type: 'reschedule', record_url: 'http://ex.com' });
  assert.strictEqual(upd.lesson_type, 'reschedule');
  assert.strictEqual(upd.record_url, 'http://ex.com');

  // deleteFull
  const ok = await repo.deleteLessonFull(lessonId);
  assert.strictEqual(ok, true);
  const gone = await repo.getLessonFull(lessonId);
  assert.strictEqual(gone, null);

  // cleanup
  await pool.query(`DELETE FROM students WHERE id = $1`, [st.rows[0].id]);
  await pool.query(`DELETE FROM groups WHERE id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [te.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id = $1`, [dir.rows[0].id]);
});

test('listLessons: returns rows with filters applied', async () => {
  const dir = await pool.query(
    `INSERT INTO directions (name, sheet_name, is_individual) VALUES ('__T_DIR_LL__', 'X', false) RETURNING id`
  );
  const te = await pool.query(
    `INSERT INTO teachers (name) VALUES ('__T_TE_LL__') RETURNING id`
  );
  const grp = await pool.query(
    `INSERT INTO groups (name, direction_id, teacher_id, is_individual)
     VALUES ('__T_G_LL__', $1, $2, false) RETURNING id`,
    [dir.rows[0].id, te.rows[0].id]
  );

  const lessonId = await repo.createLessonFull({
    lesson_date: '2025-06-01',
    teacher_id: te.rows[0].id,
    group_id: grp.rows[0].id,
    lesson_number: 1,
    submitted_by_token: 'admin-imported',
  });

  const rows = await repo.listLessons({ group_id: grp.rows[0].id });
  assert.ok(rows.length >= 1);
  assert.ok(rows.some((r) => r.id === lessonId));

  await repo.deleteLessonFull(lessonId);
  await pool.query(`DELETE FROM groups WHERE id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [te.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id = $1`, [dir.rows[0].id]);
});
```

Эти тесты используют `pool` и `repo` — оба должны быть импортированы. Проверь верх файла `admin-repo.test.js` — если `pool` не импортирован, добавь:

```js
const { pool } = require('./db');
```

- [ ] **Step 3: Запустить тесты**

```powershell
npm test 2>&1 | Select-String "tests \d+|pass \d+|fail \d+"
```
Expected: было 73 pass; стало 75 pass (новые 2).

---

### Task 2: admin-repo — attendance + payroll функции + smoke-тесты

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\services\admin-repo.js`
- Modify: `C:\Users\ilyap\TestKOTOKOD\services\admin-repo.test.js`

- [ ] **Step 1: добавить функции в `admin-repo.js`**

В блок «Lessons (operational)» (после deleteLessonFull):

```js
async function updateAttendanceCell(lessonId, studentId, present) {
  const { rowCount } = await pool.query(
    `INSERT INTO lesson_attendance (lesson_id, student_id, present)
     VALUES ($1, $2, $3)
     ON CONFLICT (lesson_id, student_id) DO UPDATE SET present = EXCLUDED.present`,
    [lessonId, studentId, !!present],
  );
  return rowCount > 0;
}

// ===== Payroll =====

async function listPayroll({ teacher_id, date_from, date_to } = {}) {
  const conds = [];
  const params = [];
  if (teacher_id) { params.push(teacher_id); conds.push(`p.teacher_id = $${params.length}`); }
  if (date_from)  { params.push(date_from);  conds.push(`l.lesson_date >= $${params.length}`); }
  if (date_to)    { params.push(date_to);    conds.push(`l.lesson_date <= $${params.length}`); }
  const where = conds.length ? `WHERE ${conds.join(' AND ')}` : '';
  const { rows } = await pool.query(
    `SELECT p.*,
            l.lesson_date, l.lesson_number, l.group_id,
            g.name AS group_name,
            te.name AS teacher_name
       FROM payroll p
       JOIN lessons l    ON l.id = p.lesson_id
       JOIN teachers te  ON te.id = p.teacher_id
       JOIN groups g     ON g.id = l.group_id
       ${where}
       ORDER BY l.lesson_date DESC, l.lesson_number DESC
       LIMIT 1000`,
    params,
  );
  return rows;
}

async function payrollSummary({ teacher_id, date_from, date_to } = {}) {
  const conds = [];
  const params = [];
  if (teacher_id) { params.push(teacher_id); conds.push(`p.teacher_id = $${params.length}`); }
  if (date_from)  { params.push(date_from);  conds.push(`l.lesson_date >= $${params.length}`); }
  if (date_to)    { params.push(date_to);    conds.push(`l.lesson_date <= $${params.length}`); }
  const where = conds.length ? `WHERE ${conds.join(' AND ')}` : '';
  const { rows } = await pool.query(
    `SELECT p.teacher_id,
            te.name AS teacher_name,
            COUNT(*) AS lessons_count,
            COALESCE(SUM(p.payment), 0) AS sum_payment,
            COALESCE(SUM(p.penalty), 0) AS sum_penalty
       FROM payroll p
       JOIN lessons l   ON l.id = p.lesson_id
       JOIN teachers te ON te.id = p.teacher_id
       ${where}
       GROUP BY p.teacher_id, te.name
       ORDER BY te.name`,
    params,
  );
  return rows;
}

async function updatePayroll(id, fields) {
  const { rows } = await pool.query(
    `UPDATE payroll SET
       total_students = COALESCE($2, total_students),
       present_count  = COALESCE($3, present_count),
       payment        = COALESCE($4, payment),
       penalty        = COALESCE($5, penalty)
     WHERE id = $1 RETURNING *`,
    [id,
     fields.total_students ?? null,
     fields.present_count ?? null,
     fields.payment ?? null,
     fields.penalty ?? null],
  );
  return rows[0] || null;
}
```

Обнови `module.exports` — добавь в общий объект:

```js
  updateAttendanceCell,
  // payroll
  listPayroll, payrollSummary, updatePayroll,
```

- [ ] **Step 2: тесты в `admin-repo.test.js`**

```js
test('updateAttendanceCell: toggles present flag', async () => {
  const dir = await pool.query(`INSERT INTO directions (name, sheet_name, is_individual) VALUES ('__T_DIR_A__', 'X', false) RETURNING id`);
  const te = await pool.query(`INSERT INTO teachers (name) VALUES ('__T_TE_A__') RETURNING id`);
  const grp = await pool.query(`INSERT INTO groups (name, direction_id, teacher_id, is_individual) VALUES ('__T_G_A__', $1, $2, false) RETURNING id`, [dir.rows[0].id, te.rows[0].id]);
  const st = await pool.query(`INSERT INTO students (full_name) VALUES ('__T_S_A__') RETURNING id`);
  const lessonId = await repo.createLessonFull({
    lesson_date: '2025-05-15',
    teacher_id: te.rows[0].id,
    group_id: grp.rows[0].id,
    lesson_number: 1,
    submitted_by_token: 'admin-imported',
    attendance: [{ student_id: st.rows[0].id, present: true }],
  });

  await repo.updateAttendanceCell(lessonId, st.rows[0].id, false);

  const full = await repo.getLessonFull(lessonId);
  assert.strictEqual(full.attendance[0].present, false);

  await repo.deleteLessonFull(lessonId);
  await pool.query(`DELETE FROM students WHERE id = $1`, [st.rows[0].id]);
  await pool.query(`DELETE FROM groups WHERE id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [te.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id = $1`, [dir.rows[0].id]);
});

test('payroll: list + summary + update', async () => {
  const dir = await pool.query(`INSERT INTO directions (name, sheet_name, is_individual) VALUES ('__T_DIR_P__', 'X', false) RETURNING id`);
  const te = await pool.query(`INSERT INTO teachers (name) VALUES ('__T_TE_P__') RETURNING id`);
  const grp = await pool.query(`INSERT INTO groups (name, direction_id, teacher_id, is_individual) VALUES ('__T_G_P__', $1, $2, false) RETURNING id`, [dir.rows[0].id, te.rows[0].id]);
  const lessonId = await repo.createLessonFull({
    lesson_date: '2025-05-15',
    teacher_id: te.rows[0].id,
    group_id: grp.rows[0].id,
    lesson_number: 1,
    submitted_by_token: 'admin-imported',
    payroll: { total_students: 3, present_count: 3, payment: 1500, penalty: 0 },
  });

  // list
  const list = await repo.listPayroll({ teacher_id: te.rows[0].id });
  assert.ok(list.some((r) => r.lesson_id === lessonId));

  // summary
  const sum = await repo.payrollSummary({ teacher_id: te.rows[0].id });
  const myRow = sum.find((r) => r.teacher_id === te.rows[0].id);
  assert.ok(myRow);
  assert.ok(Number(myRow.lessons_count) >= 1);
  assert.ok(Number(myRow.sum_payment) >= 1500);

  // update
  const payrollRow = list.find((r) => r.lesson_id === lessonId);
  const updated = await repo.updatePayroll(payrollRow.id, { payment: 2000, penalty: 100 });
  assert.strictEqual(Number(updated.payment), 2000);
  assert.strictEqual(Number(updated.penalty), 100);

  await repo.deleteLessonFull(lessonId);
  await pool.query(`DELETE FROM groups WHERE id = $1`, [grp.rows[0].id]);
  await pool.query(`DELETE FROM teachers WHERE id = $1`, [te.rows[0].id]);
  await pool.query(`DELETE FROM directions WHERE id = $1`, [dir.rows[0].id]);
});
```

- [ ] **Step 3: тесты**

```powershell
npm test 2>&1 | Select-String "tests \d+|pass \d+|fail \d+"
```
Expected: 77 pass (75 + 2 новых).

---

### Task 3: server.js — 5 эндпоинтов для `/api/admin/lessons*`

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\server.js`

Существующий блок admin-эндпоинтов выглядит так (примерно): после `app.use('/api/admin', adminAuth.requireAdmin)` идут роуты `/api/admin/students`, `/api/admin/groups`, etc., затем `app.use(express.static('public'))`.

- [ ] **Step 1: добавить блок lessons-эндпоинтов**

Найди в `server.js` группу admin-эндпоинтов (там есть `/api/admin/students`, `/api/admin/groups`, etc.). В конце admin-блока (перед `app.use(express.static('public'))`), вставь:

```js
// ----- lessons (operational, Phase 3b) -----
app.get('/api/admin/lessons', adminWrap(async (req, res) => {
    const filters = {
        group_id:   req.query.group_id   ? Number(req.query.group_id)   : undefined,
        teacher_id: req.query.teacher_id ? Number(req.query.teacher_id) : undefined,
        date_from:  req.query.date_from || undefined,
        date_to:    req.query.date_to   || undefined,
    };
    res.json(await adminRepo.listLessons(filters));
}));

app.get('/api/admin/lessons/:id', adminWrap(async (req, res) => {
    const l = await adminRepo.getLessonFull(req.params.id);
    if (!l) return res.status(404).json({ error: 'Not found' });
    res.json(l);
}));

app.post('/api/admin/lessons', adminWrap(async (req, res) => {
    const b = req.body || {};
    if (!b.lesson_date || !b.group_id || !b.teacher_id || b.lesson_number == null) {
        return res.status(400).json({ error: 'lesson_date, group_id, teacher_id, lesson_number required' });
    }
    const id = await adminRepo.createLessonFull(b);
    const full = await adminRepo.getLessonFull(id);
    res.status(201).json(full);
}));

app.patch('/api/admin/lessons/:id', adminWrap(async (req, res) => {
    const updated = await adminRepo.updateLesson(req.params.id, req.body || {});
    if (!updated) return res.status(404).json({ error: 'Not found' });
    res.json(updated);
}));

app.delete('/api/admin/lessons/:id', adminWrap(async (req, res) => {
    const ok = await adminRepo.deleteLessonFull(req.params.id);
    if (!ok) return res.status(404).json({ error: 'Not found' });
    res.status(204).end();
}));
```

`adminWrap` — это существующий middleware-хелпер для обработки ошибок (уже есть в server.js, проверь импорт).

- [ ] **Step 2: проверка**

```powershell
node --check server.js
npm test 2>&1 | Select-String "tests \d+|pass \d+|fail \d+"
```
Expected: exit 0; 77 pass.

---

### Task 4: server.js — attendance + payroll эндпоинты (5 шт.)

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\server.js`

- [ ] **Step 1: добавить блок attendance + payroll**

После lessons-блока (предыдущая задача), добавь:

```js
// ----- lesson-attendance (per-cell toggle) -----
app.patch('/api/admin/lesson-attendance/:lessonId/:studentId', adminWrap(async (req, res) => {
    const lessonId  = Number(req.params.lessonId);
    const studentId = Number(req.params.studentId);
    if (!lessonId || !studentId) return res.status(400).json({ error: 'lessonId and studentId required' });
    const present = req.body && typeof req.body.present === 'boolean' ? req.body.present : false;
    await adminRepo.updateAttendanceCell(lessonId, studentId, present);
    res.json({ ok: true, lesson_id: lessonId, student_id: studentId, present });
}));

// ----- payroll -----
app.get('/api/admin/payroll', adminWrap(async (req, res) => {
    const filters = {
        teacher_id: req.query.teacher_id ? Number(req.query.teacher_id) : undefined,
        date_from:  req.query.date_from || undefined,
        date_to:    req.query.date_to   || undefined,
    };
    res.json(await adminRepo.listPayroll(filters));
}));

app.get('/api/admin/payroll/summary', adminWrap(async (req, res) => {
    const filters = {
        teacher_id: req.query.teacher_id ? Number(req.query.teacher_id) : undefined,
        date_from:  req.query.date_from || undefined,
        date_to:    req.query.date_to   || undefined,
    };
    res.json(await adminRepo.payrollSummary(filters));
}));

app.patch('/api/admin/payroll/:id', adminWrap(async (req, res) => {
    const updated = await adminRepo.updatePayroll(req.params.id, req.body || {});
    if (!updated) return res.status(404).json({ error: 'Not found' });
    res.json(updated);
}));
```

- [ ] **Step 2: проверка**

```powershell
node --check server.js
npm test 2>&1 | Select-String "tests \d+|pass \d+|fail \d+"
```
Expected: exit 0; 77 pass.

---

### Task 5: admin-app.js — Sections, calculator, openLessonModal helper

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\public\admin-app.js`

- [ ] **Step 1: добавить «Уроки» и «Зарплата» в SECTIONS**

Найди в `admin-app.js` константу `SECTIONS = [...]` (близко к верху файла). Перед `archive`-элементом добавь два:

```js
  { key: 'lessons',     label: 'Уроки',          endpoint: '/api/admin/lessons' },
  { key: 'payroll',     label: 'Зарплата',       endpoint: '/api/admin/payroll' },
```

В `state.cache` (рядом со state-инициализацией) добавь:
```js
  lessons: null, payroll: null, payrollSummary: null,
```
в существующий объект cache.

В `SECTION_SEARCH` добавь:
```js
  lessons: {}, payroll: {},
```

- [ ] **Step 2: calculator helper для admin**

В начало `admin-app.js` (после блока utility-функций типа `escapeHtml`/`fmtDate`), добавь:

```js
// Calculator (дублирует services/calculator.js для UI; короткая чистая функция)
function calcPayment(totalStudents, presentCount, isHalfLesson) {
  // Полная копия логики calc.calculatePayment — TARGET для синхронизации.
  // Тарифы (из services/calculator.js):
  //   полный урок: 1 → 500, 2 → 800, 3 → 1000, 4 → 1200, 5 → 1300, 6+ → 1500
  //   половинный (45 минут): 1 → 250, 2 → 400, 3 → 500, 4 → 600, 5 → 650, 6+ → 750
  const present = Number(presentCount) || 0;
  if (present === 0) return 0;
  const full = [0, 500, 800, 1000, 1200, 1300, 1500];
  const half = [0, 250, 400, 500, 600, 650, 750];
  const table = isHalfLesson ? half : full;
  const idx = Math.min(present, table.length - 1);
  return table[idx];
}
```

**Внимание:** на этапе реализации обязательно перепроверь точные значения в `services/calculator.js` и синхронизируй. Если расходятся — обновить admin-app.js (приоритет — calculator.js).

- [ ] **Step 3: helper для модалки урока**

В конец `admin-app.js` (перед закрывающим }; или в конце файла, ниже всех модалок типа openStudentModal), добавь helper `openLessonModal(rowOrNullForCreate, { presetGroupId } = {})`:

Большая функция. См. Task 6 — она там полностью прописана, Task 5 только заготавливает место/импорт. Просто оставь стаб:

```js
async function openLessonModal(row, opts = {}) {
  // TODO Task 6: implement full create/edit lesson modal
  alert('openLessonModal stub — implemented in Task 6');
}
```

- [ ] **Step 4: проверка**

```powershell
node --check public\admin-app.js
```
Expected: exit 0. Тесты не трогаем (frontend, нет JS-test runner'а).

---

### Task 6: admin-app.js — реализация openLessonModal (полная форма create + edit)

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\public\admin-app.js`

- [ ] **Step 1: заменить stub из Task 5 на полную реализацию**

Замени `async function openLessonModal(row, opts = {}) { alert(...); }` на:

```js
async function openLessonModal(row, opts = {}) {
  const isNew = !row;
  let teachers, groups, students;
  try {
    [teachers, groups] = await Promise.all([ensureTeachersCache(), ensureGroupsCache()]);
  } catch (err) { showApiError(err); return; }

  // Если open from group detail page, опции групп замораживаем
  const presetGroupId = opts.presetGroupId || (row && row.group_id) || null;

  const teacherOpts = teachers.filter((t) => t.active).map((t) => ({ value: t.id, label: t.name }));
  const groupOpts = groups.filter((g) => g.active).map((g) => ({ value: g.id, label: g.name }));

  // Default values
  const initial = row || {
    lesson_date: new Date().toISOString().slice(0, 10),
    group_id: presetGroupId || '',
    teacher_id: '',
    lesson_type: 'regular',
    lesson_number: 1,
    record_url: '',
    original_teacher_id: '',
  };

  // Build fields for create mode (full form) или edit (reduced)
  const fields = [
    { name: 'lesson_date', label: 'Дата', type: 'date', required: true },
    { name: 'group_id',    label: 'Группа', type: 'select', options: groupOpts, required: true },
    { name: 'teacher_id',  label: 'Преподаватель', type: 'select', options: teacherOpts, required: true },
    { name: 'lesson_number', label: 'Номер урока', type: 'number', required: true, hint: 'Накопительный счётчик в группе' },
    { name: 'lesson_type', label: 'Тип', type: 'select', options: [
      { value: 'regular', label: 'Обычный' },
      { value: 'substitution', label: 'Замена' },
      { value: 'reschedule', label: 'Перенос' },
    ]},
    { name: 'original_teacher_id', label: 'Оригинальный препод. (для замен)', type: 'select', options: [{value:'', label:'— нет —'}, ...teacherOpts] },
    { name: 'record_url', label: 'Ссылка на запись', placeholder: 'https://...' },
  ];

  openModal({
    title: isNew ? 'Новый урок' : `Урок · ${row.lesson_date} · ${row.group_name || ''}`,
    fields,
    initial,
    wide: true,
    onSubmit: async (data) => {
      // Численные нормализация
      data.group_id = Number(data.group_id);
      data.teacher_id = Number(data.teacher_id);
      data.lesson_number = Number(data.lesson_number);
      data.original_teacher_id = data.original_teacher_id ? Number(data.original_teacher_id) : null;
      if (data.lesson_type !== 'substitution') data.original_teacher_id = null;

      if (isNew) {
        // Прочитать выбранных студентов и payment из расширения формы
        const attendance = collectAttendanceFromForm();
        const isHalfLesson = false; // На MVP — admin вручную выставляет payment, half-detection не нужно
        const presentCount = attendance.filter((a) => a.present).length;
        const totalStudents = attendance.length;
        const paymentInput = document.querySelector('#lesson-modal-payment');
        const penaltyInput = document.querySelector('#lesson-modal-penalty');
        const payment = paymentInput ? Number(paymentInput.value) || 0 : 0;
        const penalty = penaltyInput ? Number(penaltyInput.value) || 0 : 0;

        const created = await api('POST', '/api/admin/lessons', {
          ...data,
          lesson_duration_minutes: 90,  // default; on edit user может сменить через групповые поля
          submitted_by_token: 'admin-imported',
          attendance,
          payroll: { total_students: totalStudents, present_count: presentCount, payment, penalty },
        });
        toast('Урок создан', 'ok');
        // Update cache
        state.cache.lessons = null;
        goToDetail('lessons', created);
      } else {
        await api('PATCH', `/api/admin/lessons/${row.id}`, data);
        toast('Сохранено', 'ok');
        state.cache.lessons = null;
        await renderSection();
      }
    },
  });

  // Если create-mode и есть выбранная группа — подгрузить учеников и payment-поля
  if (isNew && presetGroupId) {
    document.querySelector('select[name="group_id"]').value = presetGroupId;
  }

  // Расширение модалки: dynamic attendance + payment fields
  if (isNew) {
    attachAttendanceAndPaymentBlock();
  }
}

async function attachAttendanceAndPaymentBlock() {
  const body = document.querySelector('#modal-host .modal-body');
  if (!body) return;
  const groupSelect = body.querySelector('select[name="group_id"]');
  const block = document.createElement('div');
  block.className = 'memberships';
  block.id = 'lesson-attendance-block';
  body.appendChild(block);

  async function renderBlock() {
    const gid = Number(groupSelect.value);
    if (!gid) { block.innerHTML = '<div class="memberships__empty">Выберите группу для отображения учеников</div>'; return; }
    let members;
    try {
      members = await api('GET', `/api/admin/group-memberships?group_id=${gid}`);
    } catch (err) { showApiError(err); return; }

    const headHtml = `<h4 class="memberships__title">Посещаемость</h4>
      <div class="memberships__head">
        <div>Ученик</div><div>Был</div><div></div><div></div>
      </div>`;
    const rowsHtml = members.map((m) => `
      <div class="memberships__row" data-student-id="${m.student_id}">
        <div class="memberships__group">${escapeHtml(m.student_name || ('#' + m.student_id))}</div>
        <div><label class="modal__check" style="margin:0">
          <input type="checkbox" data-attendance-toggle checked>
          <span class="modal__check-box"></span>
        </label></div>
        <div></div><div></div>
      </div>
    `).join('');

    const paymentHtml = `
      <h4 class="memberships__title">Зарплата</h4>
      <div class="memberships__row">
        <div>Оплата (₽)</div>
        <input type="number" id="lesson-modal-payment" step="0.01" value="0">
        <div>Штраф (₽)</div>
        <input type="number" id="lesson-modal-penalty" step="0.01" value="0">
      </div>
      <div style="font-size:11px;color:var(--text3);margin-top:6px">Подсказка: оплата = тариф × количество присутствующих</div>
    `;

    block.innerHTML = headHtml + rowsHtml + paymentHtml;

    // Auto-calc payment on attendance change
    function updatePayment() {
      const present = block.querySelectorAll('[data-attendance-toggle]:checked').length;
      const auto = calcPayment(members.length, present, false);
      document.getElementById('lesson-modal-payment').value = auto;
    }
    block.querySelectorAll('[data-attendance-toggle]').forEach((cb) => cb.addEventListener('change', updatePayment));
    updatePayment();
  }

  groupSelect.addEventListener('change', renderBlock);
  await renderBlock();
}

function collectAttendanceFromForm() {
  const rows = document.querySelectorAll('#lesson-attendance-block [data-student-id]');
  const out = [];
  rows.forEach((r) => {
    const sid = Number(r.dataset.studentId);
    const checked = r.querySelector('[data-attendance-toggle]').checked;
    out.push({ student_id: sid, present: checked });
  });
  return out;
}
```

- [ ] **Step 2: проверка**

```powershell
node --check public\admin-app.js
```
Expected: exit 0.

---

### Task 7: admin-app.js — SECTION_RENDERERS.lessons (таблица с фильтрами)

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\public\admin-app.js`

- [ ] **Step 1: добавить рендерер**

В блоке `SECTION_RENDERERS` (рядом с другими, например после `directions`):

```js
SECTION_RENDERERS.lessons = async function renderLessons(host, rows) {
  try { await Promise.all([ensureTeachersCache(), ensureGroupsCache()]); } catch (_) {}
  renderTable({
    host, rows, title: 'Уроки',
    colSearch: SECTION_SEARCH.lessons,
    columns: [
      { key: 'id',           label: 'ID', html: true, format: (r) => `<span class="id-cell">#${r.id}</span>` },
      { key: 'lesson_date',  label: 'Дата', format: (r) => fmtDate(r.lesson_date) },
      { key: 'group_name',   label: 'Группа' },
      { key: 'teacher_name', label: 'Преподаватель' },
      { key: 'lesson_number', label: 'Урок #' },
      { key: 'lesson_type',  label: 'Тип', format: (r) => ({regular:'обычный', substitution:'замена', reschedule:'перенос'}[r.lesson_type] || r.lesson_type) },
      { key: 'present_count', label: 'Был/Всего', format: (r) => r.present_count != null ? `${r.present_count}/${r.total_students}` : '—' },
      { key: 'payment',      label: 'Оплата ₽', format: (r) => r.payment ? Number(r.payment).toLocaleString('ru') : '—' },
      { key: 'penalty',      label: 'Штраф ₽', format: (r) => r.penalty ? Number(r.penalty).toLocaleString('ru') : '0' },
    ],
    onAddNew: () => openLessonModal(null),
    onRowClick: (row) => goToDetail('lessons', row),
  });
};
```

Также убедись что endpoint `lessons` загружается в `state.cache.lessons` в существующем generic-обработчике sections (см. `renderSection` или `loadSection` в admin-app.js). Если кеш-инициализация требует ручного добавления — проверь и добавь:

В `state.cache` уже добавлено в Task 5. Существующий `renderSection` использует `state.cache[sectionKey]` — должно работать автоматически.

- [ ] **Step 2: проверка**

```powershell
node --check public\admin-app.js
```

---

### Task 8: admin-app.js — DETAIL_RENDERERS.lessons (страница урока с inline-edit attendance + payroll)

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\public\admin-app.js`

- [ ] **Step 1: добавить detail-рендерер**

В блоке `DETAIL_RENDERERS`:

```js
DETAIL_RENDERERS.lessons = async function renderLessonDetail(host, row) {
  // row пришёл из cache — но содержит lite-данные. Подгрузим full через API.
  let full;
  try {
    full = await api('GET', `/api/admin/lessons/${row.id}`);
  } catch (err) { showApiError(err); return; }

  const extra = renderDetailShell(host, {
    title: `Урок ${full.lesson_date} · ${full.group_name}`,
    subtitle: `№${full.lesson_number} · ${full.teacher_name}${full.lesson_type !== 'regular' ? ' · ' + full.lesson_type : ''}`,
    cardTitle: 'Данные урока',
    row: full,
    fields: [
      { key: 'id',                     label: 'ID' },
      { key: 'lesson_date',            label: 'Дата', format: (r) => fmtDate(r.lesson_date) },
      { key: 'lesson_number',          label: 'Номер урока' },
      { key: 'lesson_type',            label: 'Тип', format: (r) => ({regular:'обычный', substitution:'замена', reschedule:'перенос'}[r.lesson_type] || r.lesson_type) },
      { key: 'group_name',             label: 'Группа' },
      { key: 'teacher_name',           label: 'Преподаватель' },
      { key: 'original_teacher_name',  label: 'Оригинальный препод', format: (r) => r.original_teacher_name || '—' },
      { key: 'lesson_duration_minutes', label: 'Длительность, мин' },
      { key: 'record_url',             label: 'Запись', format: (r) => r.record_url ? r.record_url : '—' },
      { key: 'submitted_by_token',     label: 'Токен' },
      { key: 'submitted_at',           label: 'Создано', format: (r) => fmtDate(r.submitted_at) },
    ],
    onEdit: () => openLessonModal(full),
    onDelete: () => deleteLessonFull(full),
    deleteLabel: 'Удалить урок',
  });

  // Attendance block
  const attSec = document.createElement('div');
  attSec.className = 'detail__section';
  attSec.innerHTML = `<h3 class="detail__section-title">Посещаемость</h3>`;
  const attHost = document.createElement('div');
  attSec.appendChild(attHost);
  extra.appendChild(attSec);

  if (!full.attendance.length) {
    attHost.innerHTML = '<div class="memberships__empty">Нет записей</div>';
  } else {
    attHost.innerHTML = `
      <div class="memberships__head">
        <div>Ученик</div><div>Был</div><div></div><div></div>
      </div>
      ${full.attendance.map((a) => `
        <div class="memberships__row" data-sid="${a.student_id}">
          <div class="memberships__group">${escapeHtml(a.student_name)}</div>
          <div><label class="modal__check" style="margin:0">
            <input type="checkbox" data-att-toggle ${a.present ? 'checked' : ''}>
            <span class="modal__check-box"></span>
          </label></div>
          <div></div><div></div>
        </div>
      `).join('')}`;
    attHost.querySelectorAll('[data-att-toggle]').forEach((cb) => {
      cb.addEventListener('change', async () => {
        const sid = Number(cb.closest('[data-sid]').dataset.sid);
        try {
          await api('PATCH', `/api/admin/lesson-attendance/${full.id}/${sid}`, { present: cb.checked });
          toast('Сохранено', 'ok');
        } catch (err) { showApiError(err); cb.checked = !cb.checked; }
      });
    });
  }

  // Payroll block
  const paySec = document.createElement('div');
  paySec.className = 'detail__section';
  paySec.innerHTML = `<h3 class="detail__section-title">Зарплата</h3>`;
  const payHost = document.createElement('div');
  paySec.appendChild(payHost);
  extra.appendChild(paySec);

  if (!full.payroll) {
    payHost.innerHTML = '<div class="memberships__empty">Зарплата для этого урока не создана</div>';
  } else {
    payHost.innerHTML = `
      <div class="memberships__row">
        <div>Всего</div>
        <input type="number" data-pay-field="total_students" value="${full.payroll.total_students}">
        <div>Было</div>
        <input type="number" data-pay-field="present_count" value="${full.payroll.present_count}">
      </div>
      <div class="memberships__row">
        <div>Оплата ₽</div>
        <input type="number" step="0.01" data-pay-field="payment" value="${full.payroll.payment}">
        <div>Штраф ₽</div>
        <input type="number" step="0.01" data-pay-field="penalty" value="${full.payroll.penalty}">
      </div>
    `;
    payHost.querySelectorAll('[data-pay-field]').forEach((inp) => {
      inp.addEventListener('change', async () => {
        const field = inp.dataset.payField;
        try {
          await api('PATCH', `/api/admin/payroll/${full.payroll.id}`, { [field]: Number(inp.value) });
          toast('Сохранено', 'ok');
        } catch (err) { showApiError(err); }
      });
    });
  }
};

async function deleteLessonFull(row) {
  await api('DELETE', `/api/admin/lessons/${row.id}`);
  state.cache.lessons = null;
  goBackToList();
  toast('Урок удалён', 'ok');
}
```

- [ ] **Step 2: проверка**

```powershell
node --check public\admin-app.js
```

---

### Task 9: admin-app.js — SECTION_RENDERERS.payroll (list + summary view)

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\public\admin-app.js`

- [ ] **Step 1: добавить рендерер**

```js
const PAYROLL_VIEW = { mode: 'list' };  // module-level state

SECTION_RENDERERS.payroll = async function renderPayroll(host, rows) {
  try { await ensureTeachersCache(); } catch (_) {}

  // Toggle view
  const modeBar = `<div style="display:flex;gap:8px;margin-bottom:12px">
    <button class="btn-secondary" data-pay-mode="list" style="${PAYROLL_VIEW.mode==='list'?'background:var(--accent);color:#fff;border-color:var(--accent)':''}">Список</button>
    <button class="btn-secondary" data-pay-mode="summary" style="${PAYROLL_VIEW.mode==='summary'?'background:var(--accent);color:#fff;border-color:var(--accent)':''}">Сводка</button>
  </div>`;

  if (PAYROLL_VIEW.mode === 'list') {
    host.innerHTML = `<div class="section-header">
        <span class="section-title">Зарплата · Список</span>
        <span class="count-badge">${rows ? rows.length : 0}</span>
      </div>${modeBar}<div id="payroll-content"></div>`;
    const content = host.querySelector('#payroll-content');

    renderTable({
      host: content,
      rows: rows || [],
      title: '',
      colSearch: SECTION_SEARCH.payroll,
      columns: [
        { key: 'lesson_date',  label: 'Дата', format: (r) => fmtDate(r.lesson_date) },
        { key: 'teacher_name', label: 'Преподаватель' },
        { key: 'group_name',   label: 'Группа' },
        { key: 'lesson_number', label: 'Урок #' },
        { key: 'present_count', label: 'Было/Всего', format: (r) => `${r.present_count}/${r.total_students}` },
        { key: 'payment',      label: 'Оплата ₽', format: (r) => Number(r.payment).toLocaleString('ru') },
        { key: 'penalty',      label: 'Штраф ₽', format: (r) => Number(r.penalty).toLocaleString('ru') },
      ],
      onAddNew: () => openLessonModal(null),  // создание payroll = создание lesson
      onRowClick: (row) => goToDetail('lessons', { id: row.lesson_id }),
    });
  } else {
    // Summary view — load aggregate
    let summary;
    try { summary = await api('GET', '/api/admin/payroll/summary'); }
    catch (err) { showApiError(err); return; }

    host.innerHTML = `<div class="section-header">
        <span class="section-title">Зарплата · Сводка</span>
        <span class="count-badge">${summary.length}</span>
      </div>${modeBar}
      <div class="data-table__scroll"><table class="data-table"><thead><tr>
        <th>Преподаватель</th><th>Уроков</th><th>Сумма оплат ₽</th><th>Сумма штрафов ₽</th>
      </tr></thead><tbody>${summary.map((r) => `<tr>
        <td>${escapeHtml(r.teacher_name)}</td>
        <td>${r.lessons_count}</td>
        <td>${Number(r.sum_payment).toLocaleString('ru')}</td>
        <td>${Number(r.sum_penalty).toLocaleString('ru')}</td>
      </tr>`).join('')}</tbody></table></div>`;
  }

  // Wire mode buttons
  host.querySelectorAll('[data-pay-mode]').forEach((b) => b.addEventListener('click', () => {
    PAYROLL_VIEW.mode = b.dataset.payMode;
    if (b.dataset.payMode === 'summary') {
      // Re-render section
      renderSection();
    } else {
      state.cache.payroll = null;
      renderSection();
    }
  }));
};
```

- [ ] **Step 2: проверка**

```powershell
node --check public\admin-app.js
```

---

### Task 10: admin-app.js — секция «Уроки группы» внутри Group detail + кнопка создания

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\public\admin-app.js`

- [ ] **Step 1: найти `DETAIL_RENDERERS.groups`**

В этом рендерере уже есть секция «Ученики группы» (memberships) и подобные. Добавь ещё одну секцию «Уроки группы» — после ученики или в конце detail.

```js
// Добавь это в DETAIL_RENDERERS.groups после блока memberships (в самом конце функции):

const lessonsSec = document.createElement('div');
lessonsSec.className = 'detail__section';
lessonsSec.innerHTML = `<h3 class="detail__section-title">Уроки группы
  <button class="btn-add" id="add-lesson-btn" style="margin-left:auto">+ Новый урок</button>
</h3><div id="group-lessons"></div>`;
extra.appendChild(lessonsSec);

const grpLessonsHost = document.getElementById('group-lessons');
let grpLessons;
try {
  grpLessons = await api('GET', `/api/admin/lessons?group_id=${row.id}`);
} catch (err) { showApiError(err); grpLessons = []; }

if (!grpLessons.length) {
  grpLessonsHost.innerHTML = '<div class="memberships__empty">Уроков нет</div>';
} else {
  grpLessonsHost.innerHTML = `<div class="data-table__scroll"><table class="data-table"><thead><tr>
    <th>Дата</th><th>№</th><th>Тип</th><th>Преподаватель</th><th>Было</th><th>Оплата ₽</th>
  </tr></thead><tbody>${grpLessons.map((l) => `<tr data-lesson-id="${l.id}" style="cursor:pointer">
    <td>${fmtDate(l.lesson_date)}</td>
    <td>${l.lesson_number}</td>
    <td>${({regular:'обычный', substitution:'замена', reschedule:'перенос'}[l.lesson_type] || l.lesson_type)}</td>
    <td>${escapeHtml(l.teacher_name)}</td>
    <td>${l.present_count != null ? `${l.present_count}/${l.total_students}` : '—'}</td>
    <td>${l.payment ? Number(l.payment).toLocaleString('ru') : '—'}</td>
  </tr>`).join('')}</tbody></table></div>`;

  grpLessonsHost.querySelectorAll('[data-lesson-id]').forEach((tr) => {
    tr.addEventListener('click', () => goToDetail('lessons', { id: Number(tr.dataset.lessonId) }));
  });
}

document.getElementById('add-lesson-btn').addEventListener('click', () => {
  openLessonModal(null, { presetGroupId: row.id });
});
```

⚠️ Точное место вставки: найди в `DETAIL_RENDERERS.groups` где заканчивается рендеринг (последний `extra.appendChild(...)` или вернётся `}`). Добавь блок ПЕРЕД закрывающей `};` функции.

- [ ] **Step 2: проверка**

```powershell
node --check public\admin-app.js
```

---

### Task 11: admin-smoke-tests.md — добавить раздел «Уроки + Зарплата»

**Files:**
- Modify: `C:\Users\ilyap\TestKOTOKOD\docs\admin-smoke-tests.md`

- [ ] **Step 1: добавить новый раздел в конец файла**

```markdown

---

## Phase 3b — Уроки и Зарплата

### Sidebar навигация

- [ ] В sidebar появились пункты «Уроки» и «Зарплата» между «Направления» и «Архив»
- [ ] Клик «Уроки» → таблица с уроками, столбцы: ID/Дата/Группа/Преподаватель/Урок #/Тип/Был/Всего/Оплата/Штраф
- [ ] Клик «Зарплата» → переключатель «Список / Сводка»

### Lesson detail

- [ ] Клик по строке в Уроках → переход на detail-страницу
- [ ] Видны: данные урока (свёртка), посещаемость, зарплата
- [ ] Toggle «был/не был» сохраняет PATCH мгновенно (тост)
- [ ] Edit полей зарплаты на blur сохраняет
- [ ] Кнопка «✎ Редактировать» открывает модалку с базовыми полями урока
- [ ] Кнопка «🗑 Удалить урок» (двухшаговая) удаляет — урок исчезает из списка, payroll и attendance тоже

### Create lesson

- [ ] Клик «+ Новый» в разделе Уроки → модалка
- [ ] Выбор группы → подгружаются ученики с галочками «был/не был»
- [ ] Снятие/установка галочки → автообновление поля «Оплата ₽»
- [ ] Submit → урок появляется в списке, переходим на detail

### Group detail — секция «Уроки группы»

- [ ] На странице группы (Группы → конкретная группа) внизу есть секция «Уроки группы»
- [ ] Видна таблица всех уроков этой группы
- [ ] Кнопка «+ Новый урок» открывает модалку с уже preset'нутой группой

### Payroll: Список / Сводка

- [ ] «Список» — таблица payroll, фильтры
- [ ] Клик по строке → переход в lesson detail
- [ ] «Сводка» — таблица агрегата (Преподаватель, Уроков, Сумма оплат, Сумма штрафов)

### Чистка тестовых данных

```sql
DELETE FROM payroll WHERE lesson_id IN (SELECT id FROM lessons WHERE submitted_by_token = 'admin-imported' AND lesson_date >= '2025-01-01');
DELETE FROM lesson_attendance WHERE lesson_id IN (SELECT id FROM lessons WHERE submitted_by_token = 'admin-imported' AND lesson_date >= '2025-01-01');
DELETE FROM lessons WHERE submitted_by_token = 'admin-imported' AND lesson_date >= '2025-01-01';
```
```

- [ ] **Step 2: проверка**

```powershell
Get-Content docs\admin-smoke-tests.md | Select-String "Phase 3b"
```
Expected: строки с заголовком.

---

## Финальная проверка

- [ ] `npm test` ≥ 77 pass (73 + 4 новых: lessons full CRUD + listLessons + attendance + payroll)
- [ ] `node --check server.js` exit 0
- [ ] `node --check public\admin-app.js` exit 0
- [ ] `npm start` стартует чисто
- [ ] Все пункты `docs/admin-smoke-tests.md` Phase 3b — пройти руками в браузере (последний шаг user'а)

---

## Что НЕ входит в Phase 3b

- Audit log изменений
- Bulk операции (массовое удаление/импорт CSV)
- Export данных (Excel/PDF)
- Графики/визуализация зарплат
- Уведомления преподавателю об изменениях
- Phase 5 (удаление sheets.js, выпил колонок) — отдельно

---

## Откат

```powershell
# Не нужно ничего удалять из БД — никаких новых миграций не было.
# Просто откатить файлы:
#   - services/admin-repo.js (убрать 9 новых функций)
#   - services/admin-repo.test.js (убрать 4 новых теста)
#   - server.js (убрать 10 эндпоинтов)
#   - public/admin-app.js (убрать SECTION_RENDERERS.lessons/payroll, DETAIL_RENDERERS.lessons, openLessonModal, секцию в Group detail)
#   - docs/admin-smoke-tests.md (убрать раздел Phase 3b)
```
