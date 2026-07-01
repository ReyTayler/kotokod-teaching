# Phase 4.2 — Backend admin endpoints + auth

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Цель:** добавить backend для admin SPA (Phase 4.3) — cookie-based auth + полный CRUD для 6 сущностей (students, groups, teachers, tokens, directions, group_memberships). PG уже залит (Phase 2). Sheets-код пока остаётся (живёт до Phase 5), но admin endpoints его не используют.

**Reference spec:** `docs/superpowers/specs/2026-05-25-frontend-refresh-admin-ui-design.md` (раздел «Admin SPA»).

**Project state note:** Проект не под git. Шаги `commit` пропускаются.

**Конфиг (подтверждён):** ADMIN_USERNAME=`admin`, bcrypt-библиотека = `bcryptjs` (pure JS, без node-gyp).

---

## Архитектура

```
┌──── server.js ────────────────────────────────────────┐
│                                                       │
│  app.use(cookieParser())                              │
│                                                       │
│  POST /api/admin/login                                │
│  POST /api/admin/logout                               │
│                                                       │
│  app.use('/api/admin', requireAdmin)  ←─ middleware   │
│                                                       │
│  /api/admin/students        GET POST PATCH DELETE     │
│  /api/admin/groups          GET POST PATCH DELETE     │
│  /api/admin/teachers        GET POST PATCH DELETE     │
│  /api/admin/tokens          GET POST PATCH DELETE     │
│  /api/admin/tokens/generate POST                      │
│  /api/admin/directions      GET POST PATCH DELETE     │
│  /api/admin/group-memberships  POST PATCH DELETE      │
│                                                       │
└───────────────────────────────────────────────────────┘
         │
         ▼
   services/admin-auth.js   ← cookie sign/verify + bcrypt + middleware
   services/admin-repo.js   ← все PG-запросы для 6 сущностей
   services/db.js           ← pool + tx (готов)
```

**Cookie:** `admin_session=<base64url(payload)>.<hmac>`, `HttpOnly; SameSite=Strict; Path=/api/admin`. На prod добавляется `Secure`. Lifetime 24ч.

**Soft delete:** для всех сущностей кроме memberships (там уже `active`) — добавить `active boolean NOT NULL DEFAULT true`. DELETE-эндпоинт ставит `active=false`. Список по умолчанию фильтрует только активные; `?include_inactive=1` показывает все.

---

## Файловая структура

| Путь | Создаётся/Меняется |
|------|--------------------|
| `db/migrations/003_admin_soft_delete.sql` | создаётся |
| `.env` / `.env.example` | меняется (3 новых ключа) |
| `scripts/admin-set-password.js` | создаётся (CLI для bcrypt-хеша) |
| `services/admin-auth.js` | создаётся |
| `services/admin-auth.test.js` | создаётся |
| `services/admin-repo.js` | создаётся (CRUD-запросы) |
| `services/admin-repo.test.js` | создаётся (smoke) |
| `server.js` | меняется (mount endpoints + middleware) |
| `package.json` | меняется (deps + scripts) |
| `docs/admin-smoke-tests.md` | создаётся (curl-чеклист) |

---

## Задачи

### Task 1: Миграция 003 — soft delete columns

**Files:**
- Create: `db/migrations/003_admin_soft_delete.sql`

```sql
BEGIN;

ALTER TABLE teachers   ADD COLUMN active boolean NOT NULL DEFAULT true;
ALTER TABLE groups     ADD COLUMN active boolean NOT NULL DEFAULT true;
ALTER TABLE directions ADD COLUMN active boolean NOT NULL DEFAULT true;

CREATE INDEX teachers_active_idx   ON teachers(active)   WHERE active = true;
CREATE INDEX groups_active_idx     ON groups(active)     WHERE active = true;
CREATE INDEX directions_active_idx ON directions(active) WHERE active = true;

COMMIT;
```

- [ ] `npm run db:migrate` — миграция применяется без ошибок.
- [ ] `npm test` — 42/42 PASS (схема не сломалась).

---

### Task 2: deps + admin password setup

**Files:**
- Modify: `package.json` (deps)
- Create: `scripts/admin-set-password.js`
- Modify: `.env`, создать `.env.example`

- [ ] **Step 1:** `npm install bcryptjs cookie-parser`

- [ ] **Step 2:** `scripts/admin-set-password.js` — генерирует bcrypt-хеш из аргумента или интерактивно:

```js
const bcrypt = require('bcryptjs');
const crypto = require('crypto');

async function main() {
  const password = process.argv[2];
  if (!password) {
    console.error('Usage: node scripts/admin-set-password.js <password>');
    process.exit(1);
  }
  const hash = await bcrypt.hash(password, 12);
  const secret = crypto.randomBytes(64).toString('hex');
  console.log('Add to .env:');
  console.log(`ADMIN_USERNAME=admin`);
  console.log(`ADMIN_PASSWORD_HASH=${hash}`);
  console.log(`ADMIN_COOKIE_SECRET=${secret}`);
}
main().catch((e) => { console.error(e); process.exit(1); });
```

- [ ] **Step 3:** Пользователь запускает `node scripts/admin-set-password.js <свой пароль>` и копирует 3 строки в `.env`. **Скрипт сам ничего не пишет в `.env`** — это явное действие пользователя (избегаем затирания существующих переменных).

- [ ] **Step 4:** `.env.example` (если ещё нет — создать; иначе обновить):

```
STUDENTS_SPREADSHEET_ID=
JOURNAL_SPREADSHEET_ID=
DATABASE_URL=postgresql://journal:journal_dev_password@localhost:5432/journal
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=
ADMIN_COOKIE_SECRET=
PORT=3000
CACHE_TTL=300
```

`.env.example` коммитится; `.env` остаётся локальным.

---

### Task 3: `services/admin-auth.js` — sign/verify + bcrypt + middleware

**Files:**
- Create: `services/admin-auth.js`
- Create: `services/admin-auth.test.js`

**Cookie format:** `<base64url(JSON.stringify({user, iat, exp}))>.<hex(hmacSha256(payload, secret))>`

```js
const crypto = require('node:crypto');
const bcrypt = require('bcryptjs');

const COOKIE_NAME = 'admin_session';
const COOKIE_LIFETIME_MS = 24 * 60 * 60 * 1000;

function b64url(buf) {
  return Buffer.from(buf).toString('base64url');
}
function unb64url(s) {
  return Buffer.from(s, 'base64url').toString('utf8');
}

function sign(payload, secret) {
  const encoded = b64url(JSON.stringify(payload));
  const hmac = crypto.createHmac('sha256', secret).update(encoded).digest('hex');
  return `${encoded}.${hmac}`;
}

function verify(token, secret) {
  if (!token || typeof token !== 'string') return null;
  const dot = token.lastIndexOf('.');
  if (dot < 0) return null;
  const encoded = token.slice(0, dot);
  const givenHmac = token.slice(dot + 1);
  const expectedHmac = crypto.createHmac('sha256', secret).update(encoded).digest('hex');
  if (givenHmac.length !== expectedHmac.length) return null;
  if (!crypto.timingSafeEqual(Buffer.from(givenHmac), Buffer.from(expectedHmac))) return null;
  try {
    const payload = JSON.parse(unb64url(encoded));
    if (!payload.exp || payload.exp < Date.now()) return null;
    return payload;
  } catch {
    return null;
  }
}

async function comparePassword(plain, hash) {
  if (!hash) return false;
  return bcrypt.compare(plain, hash);
}

function cookieAttributes() {
  const isProd = process.env.NODE_ENV === 'production';
  const attrs = ['HttpOnly', 'SameSite=Strict', 'Path=/api/admin', `Max-Age=${COOKIE_LIFETIME_MS / 1000}`];
  if (isProd) attrs.push('Secure');
  return attrs.join('; ');
}

function buildSetCookie(payload) {
  const secret = process.env.ADMIN_COOKIE_SECRET;
  const token = sign(payload, secret);
  return `${COOKIE_NAME}=${token}; ${cookieAttributes()}`;
}

function buildClearCookie() {
  const isProd = process.env.NODE_ENV === 'production';
  const attrs = ['HttpOnly', 'SameSite=Strict', 'Path=/api/admin', 'Max-Age=0'];
  if (isProd) attrs.push('Secure');
  return `${COOKIE_NAME}=; ${attrs.join('; ')}`;
}

function requireAdmin(req, res, next) {
  const token = req.cookies && req.cookies[COOKIE_NAME];
  const payload = verify(token, process.env.ADMIN_COOKIE_SECRET);
  if (!payload) return res.status(401).json({ error: 'Unauthorized' });
  req.admin = { user: payload.user };
  next();
}

module.exports = {
  COOKIE_NAME,
  COOKIE_LIFETIME_MS,
  sign,
  verify,
  comparePassword,
  buildSetCookie,
  buildClearCookie,
  requireAdmin,
};
```

**Тесты (`admin-auth.test.js`):**

```js
const { test } = require('node:test');
const assert = require('node:assert');
const { sign, verify, comparePassword } = require('./admin-auth');

const SECRET = 'test-secret-very-long-and-random-' + Buffer.from('x'.repeat(64)).toString('hex');

test('sign+verify: valid token', () => {
  const exp = Date.now() + 60_000;
  const tok = sign({ user: 'admin', iat: Date.now(), exp }, SECRET);
  const payload = verify(tok, SECRET);
  assert.strictEqual(payload.user, 'admin');
});

test('verify: bad hmac', () => {
  const tok = sign({ user: 'admin', exp: Date.now() + 60_000 }, SECRET);
  const tampered = tok.slice(0, -2) + 'xx';
  assert.strictEqual(verify(tampered, SECRET), null);
});

test('verify: wrong secret', () => {
  const tok = sign({ user: 'admin', exp: Date.now() + 60_000 }, SECRET);
  assert.strictEqual(verify(tok, SECRET + 'X'), null);
});

test('verify: expired', () => {
  const tok = sign({ user: 'admin', exp: Date.now() - 1 }, SECRET);
  assert.strictEqual(verify(tok, SECRET), null);
});

test('verify: malformed', () => {
  assert.strictEqual(verify('', SECRET), null);
  assert.strictEqual(verify('not-a-token', SECRET), null);
  assert.strictEqual(verify(null, SECRET), null);
});

test('comparePassword', async () => {
  const bcrypt = require('bcryptjs');
  const hash = await bcrypt.hash('secret123', 4);  // low cost для теста
  assert.strictEqual(await comparePassword('secret123', hash), true);
  assert.strictEqual(await comparePassword('wrong',     hash), false);
  assert.strictEqual(await comparePassword('x',         ''),   false);
});
```

- [ ] `npm test` — 42 + 6 = 48/48 PASS.

---

### Task 4: `services/admin-repo.js` — CRUD-запросы для 6 сущностей

**Files:**
- Create: `services/admin-repo.js`

Один модуль с шестью под-секциями. Каждая секция экспортирует `list/get/create/update/softDelete` (имена единообразные).

**Шаблон** (на примере teachers):

```js
async function listTeachers({ includeInactive = false } = {}) {
  const where = includeInactive ? '' : 'WHERE active = true';
  const { rows } = await pool.query(`SELECT * FROM teachers ${where} ORDER BY name`);
  return rows;
}
async function getTeacher(id) {
  const { rows } = await pool.query('SELECT * FROM teachers WHERE id = $1', [id]);
  return rows[0] || null;
}
async function createTeacher({ name, email, phone }) {
  const { rows } = await pool.query(
    `INSERT INTO teachers (name, email, phone) VALUES ($1, NULLIF($2,''), NULLIF($3,''))
     RETURNING *`,
    [name, email, phone],
  );
  return rows[0];
}
async function updateTeacher(id, { name, email, phone, active }) {
  const { rows } = await pool.query(
    `UPDATE teachers SET
       name   = COALESCE($2, name),
       email  = COALESCE(NULLIF($3,''), email),
       phone  = COALESCE(NULLIF($4,''), phone),
       active = COALESCE($5, active)
     WHERE id = $1 RETURNING *`,
    [id, name, email, phone, active],
  );
  return rows[0] || null;
}
async function softDeleteTeacher(id) {
  const { rowCount } = await pool.query('UPDATE teachers SET active = false WHERE id = $1', [id]);
  return rowCount > 0;
}
```

Аналогично для остальных сущностей. Группы — самый сложный кейс (нужен slots replace в tx).

**`createGroup` / `updateGroup`** оборачивается в `tx()`: апсёрт основной записи + DELETE/INSERT slots:

```js
async function createGroup(input) {
  return tx(async (client) => {
    const g = await client.query(
      `INSERT INTO groups (name, direction_id, teacher_id, is_individual,
                           lesson_duration_minutes, lessons_per_week, group_start_date, vk_chat)
       VALUES ($1,$2,$3,$4,$5,$6,$7,NULLIF($8,'')) RETURNING *`,
      [input.name, input.direction_id, input.teacher_id, input.is_individual,
       input.lesson_duration_minutes, input.lessons_per_week, input.group_start_date, input.vk_chat]
    );
    for (const s of (input.slots || [])) {
      await client.query(
        'INSERT INTO group_schedule_slots (group_id, day_of_week, start_time) VALUES ($1,$2,$3)',
        [g.rows[0].id, s.day_of_week, s.start_time]
      );
    }
    return g.rows[0];
  });
}
```

**Memberships:** `addStudentToGroup`, `updateMembership`, `removeFromGroup` (soft-delete: `active=false`).

**Tokens:**
- `generateToken()` — `crypto.randomBytes(8).toString('hex')` или формат `XXX-XXX-XXX` для удобства чтения.
- `createToken({ token, teacher_id })`
- `revokeToken(token)` — `UPDATE tokens SET active = false WHERE token = $1`.

**Полная сигнатура модуля:**

```js
module.exports = {
  // students
  listStudents, getStudent, createStudent, updateStudent, softDeleteStudent,
  // groups
  listGroups, getGroup, createGroup, updateGroup, softDeleteGroup,
  // teachers
  listTeachers, getTeacher, createTeacher, updateTeacher, softDeleteTeacher,
  // tokens
  listTokens, createToken, updateToken, revokeToken, generateRandomToken,
  // directions
  listDirections, getDirection, createDirection, updateDirection, softDeleteDirection,
  // memberships
  listMemberships, addMembership, updateMembership, removeMembership,
};
```

**Smoke тест (`admin-repo.test.js`):** один integration test, проверяющий create → get → update → softDelete для **одной** сущности (teachers — самой простой). Цель — поймать опечатку в SQL, не покрыть всю поверхность.

```js
test('teachers: create → get → update → softDelete', async () => {
  const created = await createTeacher({ name: 'TEST_' + Date.now(), email: '', phone: '+79991234567' });
  assert.ok(created.id);
  const fetched = await getTeacher(created.id);
  assert.strictEqual(fetched.name, created.name);
  const updated = await updateTeacher(created.id, { phone: '+70000000000' });
  assert.strictEqual(updated.phone, '+70000000000');
  const deleted = await softDeleteTeacher(created.id);
  assert.strictEqual(deleted, true);
  const afterDelete = await getTeacher(created.id);
  assert.strictEqual(afterDelete.active, false);
});
```

---

### Task 5: server.js — login/logout + mount middleware

**Files:**
- Modify: `server.js`

- [ ] **Step 1:** Импорты:
```js
const cookieParser = require('cookie-parser');
const adminAuth = require('./services/admin-auth');
```

- [ ] **Step 2:** В app setup (после `app.use(express.json())`):
```js
app.use(cookieParser());
```

- [ ] **Step 3:** Login / Logout (до middleware):

```js
app.post('/api/admin/login', async (req, res) => {
  const { username, password } = req.body || {};
  if (!username || !password) return res.status(400).json({ error: 'username and password required' });
  if (username !== process.env.ADMIN_USERNAME) return res.status(401).json({ error: 'Invalid credentials' });
  const ok = await adminAuth.comparePassword(password, process.env.ADMIN_PASSWORD_HASH);
  if (!ok) return res.status(401).json({ error: 'Invalid credentials' });
  const iat = Date.now();
  const exp = iat + adminAuth.COOKIE_LIFETIME_MS;
  res.setHeader('Set-Cookie', adminAuth.buildSetCookie({ user: username, iat, exp }));
  res.json({ ok: true });
});

app.post('/api/admin/logout', (req, res) => {
  res.setHeader('Set-Cookie', adminAuth.buildClearCookie());
  res.json({ ok: true });
});
```

- [ ] **Step 4:** Mount middleware для остальных admin-роутов:
```js
app.use('/api/admin', adminAuth.requireAdmin);
```

⚠️ Это middleware применится ко **всему**, что после mount'а. login/logout должны быть **выше**.

---

### Task 6: Endpoints для students

**Files:**
- Modify: `server.js`

```js
const repo = require('./services/admin-repo');

app.get('/api/admin/students', async (req, res) => {
  res.json(await repo.listStudents({ includeInactive: req.query.include_inactive === '1' }));
});
app.get('/api/admin/students/:id', async (req, res) => {
  const s = await repo.getStudent(req.params.id);
  if (!s) return res.status(404).json({ error: 'Not found' });
  res.json(s);
});
app.post('/api/admin/students', async (req, res) => {
  // валидация: full_name обязателен
  if (!req.body.full_name) return res.status(400).json({ error: 'full_name required' });
  try { res.status(201).json(await repo.createStudent(req.body)); }
  catch (e) { if (e.code === '23505') return res.status(409).json({ error: 'Already exists' }); throw e; }
});
app.patch('/api/admin/students/:id', async (req, res) => {
  const updated = await repo.updateStudent(req.params.id, req.body);
  if (!updated) return res.status(404).json({ error: 'Not found' });
  res.json(updated);
});
app.delete('/api/admin/students/:id', async (req, res) => {
  const ok = await repo.softDeleteStudent(req.params.id);
  if (!ok) return res.status(404).json({ error: 'Not found' });
  res.status(204).end();
});
```

**Соглашения:**
- `200` — успешный GET / PATCH
- `201` — успешный POST
- `204` — успешный DELETE
- `400` — невалидный input
- `401` — auth missing/expired (через middleware)
- `404` — entity not found
- `409` — UNIQUE violation (например, дублирующее имя)

---

### Task 7: Endpoints для groups (+ slots)

**Files:**
- Modify: `server.js`

Аналогично students, но в body принимаем `slots: [{day_of_week, start_time}, ...]`. Endpoint POST и PATCH делегируют в `repo.createGroup` / `repo.updateGroup`, которые внутри обернуты в tx и пересоздают slots.

GET-эндпоинт возвращает группы с массивом `slots`. Реализация в repo:
```sql
SELECT g.*,
  COALESCE(json_agg(json_build_object('day_of_week', s.day_of_week, 'start_time', s.start_time::text))
           FILTER (WHERE s.id IS NOT NULL), '[]') AS slots
FROM groups g
LEFT JOIN group_schedule_slots s ON s.group_id = g.id
WHERE g.active = true OR $1
GROUP BY g.id
ORDER BY g.name
```

---

### Task 8: Endpoints для teachers

**Files:**
- Modify: `server.js`

Шаблон полностью повторяет students. Поля: name, email, phone, active.

---

### Task 9: Endpoints для tokens + /generate

**Files:**
- Modify: `server.js`

```js
app.get('/api/admin/tokens',  async (req, res) => { res.json(await repo.listTokens(req.query)); });
app.post('/api/admin/tokens/generate', (req, res) => {
  res.json({ token: repo.generateRandomToken() });
});
app.post('/api/admin/tokens', async (req, res) => {
  if (!req.body.token || !req.body.teacher_id) return res.status(400).json({ error: 'token and teacher_id required' });
  res.status(201).json(await repo.createToken(req.body));
});
app.patch('/api/admin/tokens/:token', async (req, res) => { ... });
app.delete('/api/admin/tokens/:token', async (req, res) => {
  const ok = await repo.revokeToken(req.params.token);
  if (!ok) return res.status(404).end();
  res.status(204).end();
});
```

`generateRandomToken()`:
```js
function generateRandomToken() {
  // 3 group по 3 символа, base32-ish для удобства чтения
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';  // без 0/O/1/I
  const parts = [];
  for (let g = 0; g < 3; g++) {
    let p = '';
    for (let i = 0; i < 3; i++) p += alphabet[crypto.randomInt(alphabet.length)];
    parts.push(p);
  }
  return parts.join('-');
}
```

---

### Task 10: Endpoints для directions

**Files:**
- Modify: `server.js`

По шаблону teachers. Поля: name, sheet_name, is_individual, active.

⚠️ При hard-delete direction'а с активными группами PG бросит FK-ошибку. soft delete безопасен.

---

### Task 11: Endpoints для group-memberships

**Files:**
- Modify: `server.js`

```js
app.get('/api/admin/group-memberships', async (req, res) => {
  res.json(await repo.listMemberships(req.query));
});
app.post('/api/admin/group-memberships', async (req, res) => {
  if (!req.body.student_id || !req.body.group_id) return res.status(400).json({ error: 'student_id and group_id required' });
  try { res.status(201).json(await repo.addMembership(req.body)); }
  catch (e) { if (e.code === '23505') return res.status(409).json({ error: 'Membership already exists' }); throw e; }
});
app.patch('/api/admin/group-memberships/:id', async (req, res) => { ... });
app.delete('/api/admin/group-memberships/:id', async (req, res) => {
  const ok = await repo.removeMembership(req.params.id);  // soft, active=false
  if (!ok) return res.status(404).end();
  res.status(204).end();
});
```

---

### Task 12: Curl-чеклист `docs/admin-smoke-tests.md`

**Files:**
- Create: `docs/admin-smoke-tests.md`

```markdown
# Admin endpoints — curl smoke

`npm start` → http://localhost:3000.
Cookie сохраняем в файл `cookies.txt`, передаём в последующих запросах.

## Логин

curl -i -c cookies.txt -X POST -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<your-password>"}' \
  http://localhost:3000/api/admin/login

# expect: 200, Set-Cookie: admin_session=...

## Без cookie → 401

curl -i http://localhost:3000/api/admin/students   # expect 401

## С cookie → 200

curl -i -b cookies.txt http://localhost:3000/api/admin/students   # expect 200, JSON

## CRUD teachers (smoke)

curl -b cookies.txt -X POST -H "Content-Type: application/json" \
  -d '{"name":"TEST_TEACHER"}' http://localhost:3000/api/admin/teachers
# expect 201

curl -b cookies.txt http://localhost:3000/api/admin/teachers | jq '.[] | select(.name=="TEST_TEACHER")'

curl -b cookies.txt -X PATCH -H "Content-Type: application/json" \
  -d '{"phone":"+79991234567"}' \
  http://localhost:3000/api/admin/teachers/<id>

curl -b cookies.txt -X DELETE http://localhost:3000/api/admin/teachers/<id>   # expect 204

curl -b cookies.txt 'http://localhost:3000/api/admin/teachers?include_inactive=1' | jq '.[] | select(.name=="TEST_TEACHER")'
# expect: active: false

## Token generation

curl -b cookies.txt -X POST http://localhost:3000/api/admin/tokens/generate
# expect: { "token": "XXX-XXX-XXX" }

## Logout

curl -i -b cookies.txt -X POST http://localhost:3000/api/admin/logout
# expect: Set-Cookie: admin_session=; Max-Age=0
```

Чеклист пройти руками после реализации. По мере раскопок добавлять отрицательные случаи (400, 409, 404).

---

## Финальная проверка

- [ ] `npm test` — все тесты зелёные (42 базовых + 6 auth + 1 repo = 49).
- [ ] `npm start` стартует без ошибок (новые middleware не ломают существующее).
- [ ] Без admin-cookie — обычный teacher SPA работает идентично (auth middleware mounted только на `/api/admin/*`).
- [ ] curl-чеклист `docs/admin-smoke-tests.md` пройден целиком.
- [ ] `cookies.txt` после logout не работает (ответ 401).

---

## Что НЕ входит в Phase 4.2

- Admin SPA (admin.html) — отдельный план Phase 4.3.
- Audit log таблица — Phase 4.4 опционально.
- Cutover на PG — Phase 3 (после 4.2/4.3).

---

## Откат

```powershell
psql -U journal -h localhost -d journal -c "
ALTER TABLE teachers   DROP COLUMN active;
ALTER TABLE groups     DROP COLUMN active;
ALTER TABLE directions DROP COLUMN active;
"
```

Затем удалить:
- `services/admin-auth.js`, `services/admin-repo.js`, тесты.
- npm-deps `bcryptjs`, `cookie-parser` — `npm uninstall`.
- В `server.js` — все `/api/admin/*` роуты, `cookieParser`, импорты.
- В `.env` — `ADMIN_*` строки.

Teacher SPA остаётся работать как было.
