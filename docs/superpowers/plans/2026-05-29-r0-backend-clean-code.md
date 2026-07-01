# R0 Backend Clean-Code Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Разнести `server.js` (1000+ строк) на структуру `routes/` + Zod-валидация на POST/PATCH, создать `shared/` для типов и схем, сохранить все 77 тестов зелёными.

**Architecture:** Express.Router per-entity под `routes/admin/<entity>.js` и `routes/teacher.js`. Zod-схемы в `shared/schemas.js` (импортируются и бэком и фронтом). `server.js` становится thin entry — middleware + mount routers + static + error handler.

**Tech Stack:** Express 4, Zod 3, Node 24, PostgreSQL 15. NO TypeScript на бэке.

**Project notes:** Проект **НЕ под git**. Каждая «Commit»-инструкция заменяется на проверочную команду (typecheck/build/test). Бэкап делается один раз перед стартом (Task 1).

---

## File Structure

### Создаются (Create)

```
shared/
├─ types.ts              — TS interfaces всех 8 сущностей (для frontend)
├─ schemas.js            — Zod schemas (для бэка через require, для фронта через import)
└─ tsconfig.json         — minimal (для type-check)

routes/
├─ middleware/
│  ├─ validate.js        — zod-валидация → req.validated
│  ├─ async-wrap.js      — wrap async handler, catch → next(err)
│  └─ require-admin.js   — re-export adminAuth.requireAdmin для удобства
├─ teacher.js            — /api/validateToken, /api/getData, /api/submitLesson, /api/getAllData, /api/refreshData, /api/report*, /api/schedule*
└─ admin/
   ├─ index.js           — собирает sub-routers
   ├─ auth.js            — /login, /logout
   ├─ students.js        — CRUD + /:id/stats
   ├─ groups.js          — CRUD + slots
   ├─ teachers.js        — CRUD
   ├─ tokens.js          — CRUD + /generate
   ├─ directions.js      — CRUD
   ├─ memberships.js     — CRUD
   ├─ lessons.js         — CRUD + attendance + /:id/full
   └─ payroll.js         — list + summary + update
```

### Модифицируются (Modify)

- `server.js` — сжимается до ~150 строк (только setup + mount + static + error handler)
- `package.json` — добавляется dep `zod`
- `services/admin-auth.js` — НЕ трогаем
- `services/admin-repo.js` — НЕ трогаем
- `services/db.js` — НЕ трогаем
- `services/calculator.js` — НЕ трогаем

### Тесты — НЕ модифицируются

77 тестов в `services/*.test.js`, `scripts/*.test.js` остаются как есть. Они тестируют сервисы напрямую, не зависят от роутов. Должны пройти после каждого изменения.

---

## Task 1: Backup snapshot + install zod

**Files:**
- Modify: `package.json` (dependency)
- Create: `_backup-pre-r0/` (snapshot папка, gitignored)

- [ ] **Step 1: Создать backup-snapshot**

Run:
```bash
mkdir -p _backup-pre-r0
cp server.js _backup-pre-r0/server.js
```

Expected: файл `_backup-pre-r0/server.js` существует и совпадает с текущим `server.js`.

- [ ] **Step 2: Установить zod**

Run:
```bash
npm install zod
```

Expected: `package.json` содержит `"zod": "^3.x.x"` в dependencies.

- [ ] **Step 3: Baseline — все тесты зелёные**

Run:
```bash
npm test 2>&1 | tail -8
```

Expected: `tests 77`, `pass 77`, `fail 0`.

Если **не** 77/77 — стоп, что-то сломано до начала. Не двигаемся дальше.

---

## Task 2: Создать routes/middleware/

**Files:**
- Create: `routes/middleware/validate.js`
- Create: `routes/middleware/async-wrap.js`
- Create: `routes/middleware/require-admin.js`

- [ ] **Step 1: Создать validate.js**

Content `routes/middleware/validate.js`:
```js
// Универсальная middleware: запускает Zod-схему на req.body.
// При успехе кладёт нормализованные данные в req.validated и зовёт next().
// При ошибке — 400 с структурой { error, details: { field: [messages...] } }.
module.exports = (schema) => (req, res, next) => {
  const result = schema.safeParse(req.body || {});
  if (!result.success) {
    return res.status(400).json({
      error: 'Validation failed',
      details: result.error.flatten().fieldErrors,
    });
  }
  req.validated = result.data;
  next();
};
```

- [ ] **Step 2: Создать async-wrap.js**

Content `routes/middleware/async-wrap.js`:
```js
// Оборачивает async handler чтобы исключения шли в центральный error-handler
// через next(err). Заменяет старый adminWrap из server.js.
module.exports = (fn) => (req, res, next) => {
  Promise.resolve(fn(req, res, next)).catch(next);
};
```

- [ ] **Step 3: Создать require-admin.js**

Content `routes/middleware/require-admin.js`:
```js
// Re-export для краткости импортов в роутерах.
const { requireAdmin } = require('../../services/admin-auth');
module.exports = requireAdmin;
```

- [ ] **Step 4: Smoke (тесты не затронуты, но проверим что Node может загрузить)**

Run:
```bash
node -e "require('./routes/middleware/validate'); require('./routes/middleware/async-wrap'); require('./routes/middleware/require-admin'); console.log('OK')"
```

Expected: вывод `OK`.

---

## Task 3: Создать shared/types.ts + базовая schema/common.js

**Files:**
- Create: `shared/types.ts` (копия из `web/admin/src/lib/types.ts`)
- Create: `shared/schemas.js` (Zod-схемы общие)
- Create: `shared/tsconfig.json`

- [ ] **Step 1: Скопировать types**

Run:
```bash
cp web/admin/src/lib/types.ts shared/types.ts
```

Expected: `shared/types.ts` существует.

- [ ] **Step 2: Создать shared/tsconfig.json**

Content:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "lib": ["ES2022"],
    "strict": false,
    "noEmit": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "isolatedModules": true
  },
  "include": ["**/*.ts"]
}
```

- [ ] **Step 3: Создать shared/schemas.js с базовыми типами**

Content `shared/schemas.js`:
```js
// Zod-схемы для всех POST/PATCH эндпоинтов админки + teacher.
// Импортируются бэком (require) в routes/admin/<entity>.js.
// Frontend получает типы через z.infer<typeof schema>.
const { z } = require('zod');

// ===== Common primitives =====

const id = z.coerce.number().int().positive();
const dateStr = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'YYYY-MM-DD format required');
const hexColor = z.string().regex(/^#[0-9a-fA-F]{6}$/, '#RRGGBB format required');
const enrollmentStatus = z.enum(['enrolled', 'not_enrolled', 'frozen', 'declined']);
const lessonType = z.enum(['regular', 'substitution', 'reschedule']);
const lessonDuration = z.union([z.literal(45), z.literal(60), z.literal(90)]);
const dayOfWeek = z.number().int().min(0).max(6);
const timeStr = z.string().regex(/^\d{2}:\d{2}(:\d{2})?$/);

module.exports = {
  id, dateStr, hexColor, enrollmentStatus, lessonType, lessonDuration, dayOfWeek, timeStr,
};
```

- [ ] **Step 4: Verify Node может загрузить shared/schemas.js**

Run:
```bash
node -e "const s = require('./shared/schemas'); console.log(Object.keys(s).join(', '))"
```

Expected: `id, dateStr, hexColor, enrollmentStatus, lessonType, lessonDuration, dayOfWeek, timeStr`.

- [ ] **Step 5: Тесты остаются зелёными**

Run:
```bash
npm test 2>&1 | tail -3
```

Expected: `pass 77`.

---

## Task 4: routes/admin/auth.js

**Files:**
- Create: `routes/admin/auth.js`
- Test smoke: curl `/api/admin/login`

- [ ] **Step 1: Создать schema для login**

Дополни `shared/schemas.js` (в конце, перед `module.exports`):
```js
// ===== Admin auth =====

const loginSchema = z.object({
  username: z.string().trim().min(1),
  password: z.string().min(1),
});

module.exports = {
  id, dateStr, hexColor, enrollmentStatus, lessonType, lessonDuration, dayOfWeek, timeStr,
  loginSchema,
};
```

- [ ] **Step 2: Создать routes/admin/auth.js**

Content:
```js
const express = require('express');
const adminAuth = require('../../services/admin-auth');
const validate = require('../middleware/validate');
const asyncWrap = require('../middleware/async-wrap');
const { loginSchema } = require('../../shared/schemas');

const router = express.Router();

router.post('/login', validate(loginSchema), asyncWrap(async (req, res) => {
  const { username, password } = req.validated;
  if (username !== process.env.ADMIN_USERNAME) {
    return res.status(401).json({ error: 'Invalid credentials' });
  }
  const ok = await adminAuth.verifyPassword(password, process.env.ADMIN_PASSWORD_HASH);
  if (!ok) return res.status(401).json({ error: 'Invalid credentials' });

  const cookie = adminAuth.signCookie({ user: username }, process.env.ADMIN_COOKIE_SECRET);
  const isProd = process.env.NODE_ENV === 'production';
  res.cookie('admin_session', cookie, {
    httpOnly: true,
    sameSite: 'strict',
    path: '/api/admin',
    maxAge: 24 * 60 * 60 * 1000,
    secure: isProd,
  });
  res.json({ ok: true });
}));

router.post('/logout', (req, res) => {
  res.cookie('admin_session', '', {
    httpOnly: true, sameSite: 'strict', path: '/api/admin', maxAge: 0,
  });
  res.json({ ok: true });
});

module.exports = router;
```

- [ ] **Step 3: Проверить что Node грузит**

Run:
```bash
node -e "require('./routes/admin/auth')"
```

Expected: тихо (без ошибок).

- [ ] **Step 4: Тесты зелёные**

Run:
```bash
npm test 2>&1 | tail -3
```

Expected: `pass 77`.

---

## Task 5: routes/admin/students.js + schemas

**Files:**
- Modify: `shared/schemas.js` (добавить students-схемы)
- Create: `routes/admin/students.js`

- [ ] **Step 1: Добавить students-схемы в shared/schemas.js**

Перед `module.exports`:
```js
// ===== Students =====

const createStudentSchema = z.object({
  full_name: z.string().trim().min(1, 'full_name required'),
  birth_date: dateStr.nullable().optional(),
  phone: z.string().nullable().optional(),
  school_grade: z.number().int().min(1).max(11).nullable().optional(),
  platform_id: z.string().nullable().optional(),
  parent_name: z.string().nullable().optional(),
  first_purchase_date: dateStr.nullable().optional(),
  age: z.number().int().min(0).max(120).nullable().optional(),
  pm: z.string().nullable().optional(),
  enrollment_status: enrollmentStatus.optional(),
  frozen_until_month: z.number().int().min(1).max(12).nullable().optional(),
}).refine(
  (s) => {
    if (s.enrollment_status === undefined) return true;
    return (s.enrollment_status === 'frozen') === (s.frozen_until_month != null);
  },
  { message: 'frozen status requires frozen_until_month' },
);

const updateStudentSchema = createStudentSchema.innerType().partial();
```

И в `module.exports` добавь `createStudentSchema, updateStudentSchema`.

- [ ] **Step 2: Создать routes/admin/students.js**

Content:
```js
const express = require('express');
const adminRepo = require('../../services/admin-repo');
const validate = require('../middleware/validate');
const asyncWrap = require('../middleware/async-wrap');
const { createStudentSchema, updateStudentSchema } = require('../../shared/schemas');

const router = express.Router();

router.get('/', asyncWrap(async (req, res) => {
  const includeInactive = req.query.include_inactive === '1';
  res.json(await adminRepo.listStudents({ includeInactive }));
}));

router.get('/:id', asyncWrap(async (req, res) => {
  const s = await adminRepo.getStudent(req.params.id);
  if (!s) return res.status(404).json({ error: 'Not found' });
  res.json(s);
}));

router.get('/:id/stats', asyncWrap(async (req, res) => {
  const s = await adminRepo.getStudent(req.params.id);
  if (!s) return res.status(404).json({ error: 'Not found' });
  res.json(await adminRepo.studentStats(Number(req.params.id)));
}));

router.post('/', validate(createStudentSchema), asyncWrap(async (req, res) => {
  res.status(201).json(await adminRepo.createStudent(req.validated));
}));

router.patch('/:id', validate(updateStudentSchema), asyncWrap(async (req, res) => {
  const u = await adminRepo.updateStudent(req.params.id, req.validated);
  if (!u) return res.status(404).json({ error: 'Not found' });
  res.json(u);
}));

router.delete('/:id', asyncWrap(async (req, res) => {
  const ok = await adminRepo.softDeleteStudent(req.params.id);
  if (!ok) return res.status(404).json({ error: 'Not found' });
  res.status(204).end();
}));

module.exports = router;
```

- [ ] **Step 3: Verify load**

Run:
```bash
node -e "require('./routes/admin/students')"
```

Expected: тихо.

- [ ] **Step 4: Тесты зелёные**

Run:
```bash
npm test 2>&1 | tail -3
```

Expected: `pass 77`.

---

## Task 6: routes/admin/teachers.js + schemas

**Files:**
- Modify: `shared/schemas.js`
- Create: `routes/admin/teachers.js`

- [ ] **Step 1: Добавить teachers-схемы**

```js
// ===== Teachers =====

const createTeacherSchema = z.object({
  name: z.string().trim().min(1),
  email: z.string().email().nullable().optional().or(z.literal('')),
  phone: z.string().nullable().optional(),
});

const updateTeacherSchema = createTeacherSchema.partial().extend({
  active: z.boolean().optional(),
});
```

Добавь в `module.exports`.

- [ ] **Step 2: Создать routes/admin/teachers.js**

Content:
```js
const express = require('express');
const adminRepo = require('../../services/admin-repo');
const validate = require('../middleware/validate');
const asyncWrap = require('../middleware/async-wrap');
const { createTeacherSchema, updateTeacherSchema } = require('../../shared/schemas');

const router = express.Router();

router.get('/', asyncWrap(async (req, res) => {
  res.json(await adminRepo.listTeachers({ includeInactive: req.query.include_inactive === '1' }));
}));

router.get('/:id', asyncWrap(async (req, res) => {
  const t = await adminRepo.getTeacher(req.params.id);
  if (!t) return res.status(404).json({ error: 'Not found' });
  res.json(t);
}));

router.post('/', validate(createTeacherSchema), asyncWrap(async (req, res) => {
  try {
    res.status(201).json(await adminRepo.createTeacher(req.validated));
  } catch (e) {
    if (e.code === '23505') return res.status(409).json({ error: 'Already exists' });
    throw e;
  }
}));

router.patch('/:id', validate(updateTeacherSchema), asyncWrap(async (req, res) => {
  const u = await adminRepo.updateTeacher(req.params.id, req.validated);
  if (!u) return res.status(404).json({ error: 'Not found' });
  res.json(u);
}));

router.delete('/:id', asyncWrap(async (req, res) => {
  const ok = await adminRepo.softDeleteTeacher(req.params.id);
  if (!ok) return res.status(404).json({ error: 'Not found' });
  res.status(204).end();
}));

module.exports = router;
```

- [ ] **Step 3: Verify load + тесты**

Run:
```bash
node -e "require('./routes/admin/teachers')" && npm test 2>&1 | tail -3
```

Expected: `pass 77`.

---

## Task 7: routes/admin/tokens.js + schemas

**Files:**
- Modify: `shared/schemas.js`
- Create: `routes/admin/tokens.js`

- [ ] **Step 1: Добавить tokens-схемы**

```js
// ===== Tokens =====

const createTokenSchema = z.object({
  token: z.string().regex(/^[A-Z2-9]{3}-[A-Z2-9]{3}-[A-Z2-9]{3}$/, 'XXX-XXX-XXX format required'),
  teacher_id: id,
});

const updateTokenSchema = z.object({
  teacher_id: id.optional(),
  active: z.boolean().optional(),
});
```

Добавь в `module.exports`.

- [ ] **Step 2: Создать routes/admin/tokens.js**

Content:
```js
const express = require('express');
const adminRepo = require('../../services/admin-repo');
const validate = require('../middleware/validate');
const asyncWrap = require('../middleware/async-wrap');
const { createTokenSchema, updateTokenSchema } = require('../../shared/schemas');

const router = express.Router();

router.get('/', asyncWrap(async (req, res) => {
  res.json(await adminRepo.listTokens({ includeInactive: req.query.include_inactive === '1' }));
}));

router.post('/generate', asyncWrap(async (req, res) => {
  res.json({ token: adminRepo.generateRandomToken() });
}));

router.post('/', validate(createTokenSchema), asyncWrap(async (req, res) => {
  try {
    res.status(201).json(await adminRepo.createToken(req.validated));
  } catch (e) {
    if (e.code === '23505') return res.status(409).json({ error: 'Already exists' });
    throw e;
  }
}));

router.patch('/:token', validate(updateTokenSchema), asyncWrap(async (req, res) => {
  const u = await adminRepo.updateToken(req.params.token, req.validated);
  if (!u) return res.status(404).json({ error: 'Not found' });
  res.json(u);
}));

router.delete('/:token', asyncWrap(async (req, res) => {
  const ok = await adminRepo.revokeToken(req.params.token);
  if (!ok) return res.status(404).json({ error: 'Not found' });
  res.status(204).end();
}));

module.exports = router;
```

- [ ] **Step 3: Verify + тесты**

```bash
node -e "require('./routes/admin/tokens')" && npm test 2>&1 | tail -3
```

Expected: `pass 77`.

---

## Task 8: routes/admin/directions.js + schemas

**Files:**
- Modify: `shared/schemas.js`
- Create: `routes/admin/directions.js`

- [ ] **Step 1: Добавить directions-схемы**

```js
// ===== Directions =====

const createDirectionSchema = z.object({
  name: z.string().trim().min(1),
  sheet_name: z.string().trim().min(1),
  is_individual: z.boolean(),
  total_lessons: z.number().int().min(0).nullable().optional(),
  color: hexColor.nullable().optional().or(z.literal('')),
});

const updateDirectionSchema = createDirectionSchema.partial().extend({
  active: z.boolean().optional(),
});
```

Добавь в `module.exports`.

- [ ] **Step 2: Создать routes/admin/directions.js**

Content (по тому же шаблону что teachers — GET/GET/:id/POST/PATCH/DELETE).

```js
const express = require('express');
const adminRepo = require('../../services/admin-repo');
const validate = require('../middleware/validate');
const asyncWrap = require('../middleware/async-wrap');
const { createDirectionSchema, updateDirectionSchema } = require('../../shared/schemas');

const router = express.Router();

router.get('/', asyncWrap(async (req, res) => {
  res.json(await adminRepo.listDirections({ includeInactive: req.query.include_inactive === '1' }));
}));

router.get('/:id', asyncWrap(async (req, res) => {
  const d = await adminRepo.getDirection(req.params.id);
  if (!d) return res.status(404).json({ error: 'Not found' });
  res.json(d);
}));

router.post('/', validate(createDirectionSchema), asyncWrap(async (req, res) => {
  try {
    res.status(201).json(await adminRepo.createDirection(req.validated));
  } catch (e) {
    if (e.code === '23505') return res.status(409).json({ error: 'Already exists' });
    throw e;
  }
}));

router.patch('/:id', validate(updateDirectionSchema), asyncWrap(async (req, res) => {
  const u = await adminRepo.updateDirection(req.params.id, req.validated);
  if (!u) return res.status(404).json({ error: 'Not found' });
  res.json(u);
}));

router.delete('/:id', asyncWrap(async (req, res) => {
  const ok = await adminRepo.softDeleteDirection(req.params.id);
  if (!ok) return res.status(404).json({ error: 'Not found' });
  res.status(204).end();
}));

module.exports = router;
```

- [ ] **Step 3: Verify + тесты**

```bash
node -e "require('./routes/admin/directions')" && npm test 2>&1 | tail -3
```

Expected: `pass 77`.

---

## Task 9: routes/admin/groups.js + schemas

**Files:**
- Modify: `shared/schemas.js`
- Create: `routes/admin/groups.js`

- [ ] **Step 1: Добавить groups-схемы**

```js
// ===== Groups =====

const slotSchema = z.object({
  day_of_week: dayOfWeek,
  start_time: timeStr,
});

const createGroupSchema = z.object({
  name: z.string().trim().min(1),
  direction_id: id,
  teacher_id: id,
  is_individual: z.boolean(),
  lesson_duration_minutes: lessonDuration,
  lessons_per_week: z.number().int().min(1).max(7),
  group_start_date: dateStr.nullable().optional(),
  vk_chat: z.string().nullable().optional(),
  slots: z.array(slotSchema).optional(),
});

const updateGroupSchema = createGroupSchema.partial().extend({
  active: z.boolean().optional(),
});
```

Добавь в `module.exports`.

- [ ] **Step 2: Создать routes/admin/groups.js**

```js
const express = require('express');
const adminRepo = require('../../services/admin-repo');
const validate = require('../middleware/validate');
const asyncWrap = require('../middleware/async-wrap');
const { createGroupSchema, updateGroupSchema } = require('../../shared/schemas');

const router = express.Router();

router.get('/', asyncWrap(async (req, res) => {
  res.json(await adminRepo.listGroups({ includeInactive: req.query.include_inactive === '1' }));
}));

router.get('/:id', asyncWrap(async (req, res) => {
  const g = await adminRepo.getGroup(req.params.id);
  if (!g) return res.status(404).json({ error: 'Not found' });
  res.json(g);
}));

router.post('/', validate(createGroupSchema), asyncWrap(async (req, res) => {
  try {
    res.status(201).json(await adminRepo.createGroup(req.validated));
  } catch (e) {
    if (e.code === '23505') return res.status(409).json({ error: 'Already exists' });
    throw e;
  }
}));

router.patch('/:id', validate(updateGroupSchema), asyncWrap(async (req, res) => {
  const u = await adminRepo.updateGroup(req.params.id, req.validated);
  if (!u) return res.status(404).json({ error: 'Not found' });
  res.json(u);
}));

router.delete('/:id', asyncWrap(async (req, res) => {
  const ok = await adminRepo.softDeleteGroup(req.params.id);
  if (!ok) return res.status(404).json({ error: 'Not found' });
  res.status(204).end();
}));

module.exports = router;
```

- [ ] **Step 3: Verify + тесты**

```bash
node -e "require('./routes/admin/groups')" && npm test 2>&1 | tail -3
```

Expected: `pass 77`.

---

## Task 10: routes/admin/memberships.js + schemas

**Files:**
- Modify: `shared/schemas.js`
- Create: `routes/admin/memberships.js`

- [ ] **Step 1: Добавить memberships-схемы**

```js
// ===== Group memberships =====

const createMembershipSchema = z.object({
  group_id: id,
  student_id: id,
  lessons_done: z.number().min(0).optional(),
  remaining: z.number().min(0).optional(),
  start_date: dateStr.nullable().optional(),
});

const updateMembershipSchema = z.object({
  lessons_done: z.number().min(0).optional(),
  remaining: z.number().min(0).optional(),
  start_date: dateStr.nullable().optional(),
  active: z.boolean().optional(),
});
```

Добавь в `module.exports`.

- [ ] **Step 2: Создать routes/admin/memberships.js**

```js
const express = require('express');
const adminRepo = require('../../services/admin-repo');
const validate = require('../middleware/validate');
const asyncWrap = require('../middleware/async-wrap');
const { createMembershipSchema, updateMembershipSchema } = require('../../shared/schemas');

const router = express.Router();

router.get('/', asyncWrap(async (req, res) => {
  res.json(await adminRepo.listMemberships({
    group_id:   req.query.group_id   ? Number(req.query.group_id)   : undefined,
    student_id: req.query.student_id ? Number(req.query.student_id) : undefined,
    includeInactive: req.query.include_inactive === '1',
  }));
}));

router.post('/', validate(createMembershipSchema), asyncWrap(async (req, res) => {
  res.status(201).json(await adminRepo.addMembership(req.validated));
}));

router.patch('/:id', validate(updateMembershipSchema), asyncWrap(async (req, res) => {
  const u = await adminRepo.updateMembership(req.params.id, req.validated);
  if (!u) return res.status(404).json({ error: 'Not found' });
  res.json(u);
}));

router.delete('/:id', asyncWrap(async (req, res) => {
  const ok = await adminRepo.removeMembership(req.params.id);
  if (!ok) return res.status(404).json({ error: 'Not found' });
  res.status(204).end();
}));

module.exports = router;
```

- [ ] **Step 3: Verify + тесты**

```bash
node -e "require('./routes/admin/memberships')" && npm test 2>&1 | tail -3
```

Expected: `pass 77`.

---

## Task 11: routes/admin/lessons.js + schemas

**Files:**
- Modify: `shared/schemas.js`
- Create: `routes/admin/lessons.js`

- [ ] **Step 1: Добавить lessons-схемы**

```js
// ===== Lessons =====

const attendanceItemSchema = z.object({
  student_id: id,
  present: z.boolean(),
});

const payrollPartSchema = z.object({
  total_students: z.number().int().min(0),
  present_count: z.number().int().min(0),
  payment: z.number().min(0),
  penalty: z.number().min(0).optional(),
});

const createLessonSchema = z.object({
  lesson_date: dateStr,
  group_id: id,
  teacher_id: id,
  original_teacher_id: id.nullable().optional(),
  lesson_number: z.number().min(0.5),
  lesson_duration_minutes: lessonDuration.optional(),
  lesson_type: lessonType.optional(),
  record_url: z.string().nullable().optional(),
  submitted_by_token: z.string().optional(),
  attendance: z.array(attendanceItemSchema).optional(),
  payroll: payrollPartSchema.optional(),
});

const updateLessonSchema = z.object({
  lesson_date: dateStr.optional(),
  teacher_id: id.optional(),
  lesson_number: z.number().min(0.5).optional(),
  lesson_type: lessonType.optional(),
  record_url: z.string().nullable().optional(),
  original_teacher_id: id.nullable().optional(),
});

const updateAttendanceSchema = z.object({
  present: z.boolean(),
});
```

Добавь все 4 в `module.exports`.

- [ ] **Step 2: Создать routes/admin/lessons.js**

```js
const express = require('express');
const adminRepo = require('../../services/admin-repo');
const validate = require('../middleware/validate');
const asyncWrap = require('../middleware/async-wrap');
const {
  createLessonSchema, updateLessonSchema, updateAttendanceSchema,
} = require('../../shared/schemas');

const router = express.Router();

router.get('/', asyncWrap(async (req, res) => {
  res.json(await adminRepo.listLessons({
    group_id:   req.query.group_id   ? Number(req.query.group_id)   : undefined,
    teacher_id: req.query.teacher_id ? Number(req.query.teacher_id) : undefined,
    date_from:  req.query.date_from,
    date_to:    req.query.date_to,
  }));
}));

router.get('/:id', asyncWrap(async (req, res) => {
  const l = await adminRepo.getLessonFull(req.params.id);
  if (!l) return res.status(404).json({ error: 'Not found' });
  res.json(l);
}));

router.post('/', validate(createLessonSchema), asyncWrap(async (req, res) => {
  const id = await adminRepo.createLessonFull(req.validated);
  const full = await adminRepo.getLessonFull(id);
  res.status(201).json(full);
}));

router.patch('/:id', validate(updateLessonSchema), asyncWrap(async (req, res) => {
  const u = await adminRepo.updateLesson(req.params.id, req.validated);
  if (!u) return res.status(404).json({ error: 'Not found' });
  res.json(u);
}));

router.delete('/:id', asyncWrap(async (req, res) => {
  const ok = await adminRepo.deleteLessonFull(req.params.id);
  if (!ok) return res.status(404).json({ error: 'Not found' });
  res.status(204).end();
}));

// Attendance toggle для одной ячейки
router.patch('/:lessonId/attendance/:studentId',
  validate(updateAttendanceSchema),
  asyncWrap(async (req, res) => {
    const ok = await adminRepo.updateAttendanceCell(
      Number(req.params.lessonId),
      Number(req.params.studentId),
      req.validated.present,
    );
    if (!ok) return res.status(404).json({ error: 'Not found' });
    res.json({ ok: true });
  }),
);

module.exports = router;
```

⚠ **ВАЖНО:** URL для attendance был `/api/admin/lesson-attendance/:lessonId/:studentId` (в текущем server.js). Теперь становится `/api/admin/lessons/:lessonId/attendance/:studentId`. Это **breaking change** для админ-UI. **Не забыть** обновить фронт-вызов в `web/admin/src/entities/lessons.ts` и `groups.ts` (см. Task 15).

- [ ] **Step 3: Verify + тесты**

```bash
node -e "require('./routes/admin/lessons')" && npm test 2>&1 | tail -3
```

Expected: `pass 77`.

---

## Task 12: routes/admin/payroll.js + schemas

**Files:**
- Modify: `shared/schemas.js`
- Create: `routes/admin/payroll.js`

- [ ] **Step 1: Добавить payroll-схемы**

```js
// ===== Payroll =====

const updatePayrollSchema = z.object({
  total_students: z.number().int().min(0).optional(),
  present_count: z.number().int().min(0).optional(),
  payment: z.number().min(0).optional(),
  penalty: z.number().min(0).optional(),
});
```

Добавь в `module.exports`.

- [ ] **Step 2: Создать routes/admin/payroll.js**

```js
const express = require('express');
const adminRepo = require('../../services/admin-repo');
const validate = require('../middleware/validate');
const asyncWrap = require('../middleware/async-wrap');
const { updatePayrollSchema } = require('../../shared/schemas');

const router = express.Router();

router.get('/', asyncWrap(async (req, res) => {
  res.json(await adminRepo.listPayroll({
    teacher_id: req.query.teacher_id ? Number(req.query.teacher_id) : undefined,
    date_from:  req.query.date_from,
    date_to:    req.query.date_to,
  }));
}));

router.get('/summary', asyncWrap(async (req, res) => {
  res.json(await adminRepo.payrollSummary({
    teacher_id: req.query.teacher_id ? Number(req.query.teacher_id) : undefined,
    date_from:  req.query.date_from,
    date_to:    req.query.date_to,
  }));
}));

router.patch('/:id', validate(updatePayrollSchema), asyncWrap(async (req, res) => {
  const u = await adminRepo.updatePayroll(req.params.id, req.validated);
  if (!u) return res.status(404).json({ error: 'Not found' });
  res.json(u);
}));

module.exports = router;
```

- [ ] **Step 3: Verify + тесты**

```bash
node -e "require('./routes/admin/payroll')" && npm test 2>&1 | tail -3
```

Expected: `pass 77`.

---

## Task 13: routes/admin/index.js — собрать sub-routers

**Files:**
- Create: `routes/admin/index.js`

- [ ] **Step 1: Создать routes/admin/index.js**

Content:
```js
const express = require('express');
const requireAdmin = require('../middleware/require-admin');

const authRouter        = require('./auth');
const studentsRouter    = require('./students');
const groupsRouter      = require('./groups');
const teachersRouter    = require('./teachers');
const tokensRouter      = require('./tokens');
const directionsRouter  = require('./directions');
const membershipsRouter = require('./memberships');
const lessonsRouter     = require('./lessons');
const payrollRouter     = require('./payroll');

const router = express.Router();

// Auth — БЕЗ requireAdmin (login сам выдаёт cookie)
router.use('/', authRouter);

// Все остальные — за middleware
router.use('/students',          requireAdmin, studentsRouter);
router.use('/groups',            requireAdmin, groupsRouter);
router.use('/teachers',          requireAdmin, teachersRouter);
router.use('/tokens',            requireAdmin, tokensRouter);
router.use('/directions',        requireAdmin, directionsRouter);
router.use('/group-memberships', requireAdmin, membershipsRouter);
router.use('/lessons',           requireAdmin, lessonsRouter);
router.use('/payroll',           requireAdmin, payrollRouter);

module.exports = router;
```

- [ ] **Step 2: Verify все sub-routers грузятся**

Run:
```bash
node -e "require('./routes/admin')"
```

Expected: тихо.

- [ ] **Step 3: Тесты**

```bash
npm test 2>&1 | tail -3
```

Expected: `pass 77`.

---

## Task 14: routes/teacher.js + schemas

**Files:**
- Modify: `shared/schemas.js`
- Create: `routes/teacher.js`

- [ ] **Step 1: Добавить teacher-схемы**

```js
// ===== Teacher SPA endpoints =====

const validateTokenSchema = z.object({
  token: z.string().trim().min(1),
});

const submitLessonSchema = z.object({
  token: z.string().trim().min(1),
  group: z.string(),
  date: dateStr,
  recordUrl: z.string().optional(),
  attendance: z.array(z.object({
    student: z.string(),
    present: z.boolean(),
  })),
  isSubstitution: z.boolean().optional(),
  originalTeacher: z.string().optional(),
  lessonType: lessonType.optional(),
});

const getDataSchema = z.object({
  token: z.string().trim().min(1),
});
```

Добавь в `module.exports`.

- [ ] **Step 2: Создать routes/teacher.js**

Скопируй текущие handler'ы из `server.js` (lines 21-...), оберни в Express.Router. Поскольку payload submitLesson сложный — оставь handler логику как есть, только добавь validate-middleware на верхнем уровне.

Content:
```js
const express = require('express');
const calc = require('../services/calculator');
const repo = require('../services/repository');
const db   = require('../services/db');
const validate = require('./middleware/validate');
const asyncWrap = require('./middleware/async-wrap');
const {
  validateTokenSchema, submitLessonSchema, getDataSchema,
} = require('../shared/schemas');

const router = express.Router();

// POST /api/validateToken
router.post('/validateToken', validate(validateTokenSchema), asyncWrap(async (req, res) => {
  const { token } = req.validated;
  const tokens = await repo.readTokens();
  const teacher = tokens[token];
  if (teacher) res.json({ valid: true, teacher });
  else res.json({ valid: false, error: 'Неверный токен' });
}));

// POST /api/getData
router.post('/getData', validate(getDataSchema), asyncWrap(async (req, res) => {
  const { token } = req.validated;
  const tokens = await repo.readTokens();
  const teacher = tokens[token];
  if (!teacher) return res.json({ error: 'Неверный токен' });
  const unified = await repo.readAllStudents();
  const teacherData = unified.data[teacher] || {};
  res.json({ teacher, data: teacherData });
}));

// POST /api/getAllData
router.post('/getAllData', validate(getDataSchema), asyncWrap(async (req, res) => {
  const { token } = req.validated;
  const tokens = await repo.readTokens();
  if (!tokens[token]) return res.json({ error: 'Неверный токен' });
  const unified = await repo.readAllStudents();
  res.json({ data: unified.data });
}));

// POST /api/refreshData — для совместимости. Сейчас просто пересчитывает.
router.post('/refreshData', validate(getDataSchema), asyncWrap(async (req, res) => {
  const { token } = req.validated;
  const tokens = await repo.readTokens();
  const teacher = tokens[token];
  if (!teacher) return res.json({ error: 'Неверный токен' });
  const unified = await repo.readAllStudents();
  res.json({ teacher, data: unified.data[teacher] || {} });
}));

// POST /api/submitLesson — самый сложный, копируем логику из server.js as-is
// (см. lines ~70-200 в _backup-pre-r0/server.js)
router.post('/submitLesson', validate(submitLessonSchema), asyncWrap(async (req, res) => {
  // ВНИМАНИЕ: эта секция копируется ДОСЛОВНО из _backup-pre-r0/server.js
  // в обработчике app.post('/api/submitLesson', ...). Все инварианты
  // (counter-before-journal порядок, MSK через calc, half-lesson regex,
  // M/L колонки, isSubstitution маршрутизация) ДОЛЖНЫ сохраниться.
  //
  // Тело этого handler — на ~100 строк. См. _backup-pre-r0/server.js
  // и перенеси as-is. После переноса обязательно прогони:
  //   curl -X POST -H 'Content-Type: application/json' \
  //        -d '{"token":"...","group":"...","date":"2026-05-29","attendance":[...]}' \
  //        http://localhost:3000/api/submitLesson
  // и сравни payload + response с baseline.
  throw new Error('submitLesson handler: TODO — перенести из _backup-pre-r0/server.js');
}));

// GET /api/report
router.get('/report', asyncWrap(async (req, res) => {
  // TODO: перенести из _backup-pre-r0/server.js
  res.status(501).json({ error: 'TODO migrate' });
}));

router.get('/report/refresh', asyncWrap(async (req, res) => {
  res.redirect('/api/report');
}));

router.get('/schedule', asyncWrap(async (req, res) => {
  // TODO: перенести из _backup-pre-r0/server.js
  res.status(501).json({ error: 'TODO migrate' });
}));

router.get('/schedule/refresh', asyncWrap(async (req, res) => {
  res.redirect('/api/schedule');
}));

module.exports = router;
```

⚠ Этот task оставляет `submitLesson`, `report`, `schedule` как stubs. Они полноценно переносятся в **Task 14b** ниже — это критичные сценарии teacher SPA, требуют отдельной осторожности.

- [ ] **Step 3: Verify load**

```bash
node -e "require('./routes/teacher')"
```

Expected: тихо.

- [ ] **Step 4: Тесты**

```bash
npm test 2>&1 | tail -3
```

Expected: `pass 77`.

---

## Task 14b: Перенести submitLesson, report, schedule body в routes/teacher.js

**Files:**
- Modify: `routes/teacher.js` (заменить stubs)
- Reference: `_backup-pre-r0/server.js`

- [ ] **Step 1: Открыть `_backup-pre-r0/server.js` и найти handler submitLesson**

Это блок начинается строкой `app.post('/api/submitLesson', async (req, res) => {` и заканчивается соответствующим `});`. Скопируй ВНУТРЕННЕЕ тело async-функции — НЕ начиная с `(req, res) =>`.

- [ ] **Step 2: Заменить stub в routes/teacher.js**

В существующем `router.post('/submitLesson', ...)` замени тело (то что внутри `asyncWrap(async (req, res) => { ... })`) на скопированный код.

Адаптация:
- `req.body` заменить на `req.validated` где применимо (Zod уже распарсил)
- `console.log` оставить как было
- Импорты `calc`, `repo`, `db` уже есть наверху файла

- [ ] **Step 3: Аналогично перенести GET /api/report**

В `_backup-pre-r0/server.js` найди handler `app.get('/api/report', ...)`. Скопируй тело внутри `asyncWrap(async (req, res) => { ... })`.

- [ ] **Step 4: Аналогично перенести GET /api/schedule**

Тот же подход. Точные строки — см. backup.

- [ ] **Step 5: Verify все handlers загружаются**

```bash
node -e "require('./routes/teacher')"
```

Expected: тихо.

- [ ] **Step 6: Тесты**

```bash
npm test 2>&1 | tail -3
```

Expected: `pass 77`. (Тесты на handlers нет, но services используются как раньше).

---

## Task 15: Обновить вызов attendance API во фронте

**Files:**
- Modify: `web/admin/src/entities/lessons.ts`
- Modify: `web/admin/src/entities/groups.ts`

⚠ Task 11 изменил URL `/api/admin/lesson-attendance/:lessonId/:studentId` → `/api/admin/lessons/:lessonId/attendance/:studentId`. Фронт должен обновиться синхронно.

- [ ] **Step 1: Найти все вхождения старого URL**

Run:
```bash
grep -rn "lesson-attendance" web/admin/src/
```

Expected: примерно 2 вхождения в `entities/lessons.ts` и `entities/groups.ts`.

- [ ] **Step 2: Заменить URL во всех найденных местах**

В каждом вызове `api('PATCH', '/api/admin/lesson-attendance/${lesson.id}/${a.student_id}', ...)` поменять путь на `/api/admin/lessons/${lesson.id}/attendance/${a.student_id}`.

- [ ] **Step 3: Verify нет остатков старого пути**

```bash
grep -rn "lesson-attendance" web/admin/src/
```

Expected: пусто.

- [ ] **Step 4: Build + typecheck**

```bash
npm run admin:typecheck && npm run admin:build 2>&1 | tail -3
```

Expected: чисто.

---

## Task 16: server.js — slim down

**Files:**
- Modify: `server.js`

- [ ] **Step 1: Полностью заменить содержимое `server.js`**

Content:
```js
require('dotenv').config();
const express = require('express');
const cors = require('cors');
const path = require('path');
const cookieParser = require('cookie-parser');

const teacherRouter = require('./routes/teacher');
const adminRouter   = require('./routes/admin');

const app = express();
app.use(cors());
app.use(express.json());
app.use(cookieParser());

const PORT = process.env.PORT || 3000;

// ===== API =====
app.use('/api',       teacherRouter);
app.use('/api/admin', adminRouter);

// ===== Admin SPA static =====
app.get('/admin', (_, res) => res.sendFile(path.join(__dirname, 'public', 'admin-dist', 'index.html')));
app.use('/admin', express.static(path.join(__dirname, 'public', 'admin-dist'), { redirect: false }));
app.get('/admin/*', (_, res) => res.sendFile(path.join(__dirname, 'public', 'admin-dist', 'index.html')));

// ===== Teacher SPA static (текущий, до R4) =====
app.use(express.static('public'));

// ===== Centralized error handler =====
app.use((err, req, res, next) => {
  console.error('[ERROR]', err);
  if (res.headersSent) return next(err);
  res.status(err.status || 500).json({
    error: err.message || 'Internal server error',
  });
});

app.listen(PORT, () => {
  console.log(`🚀 Сервер запущен на порту ${PORT}`);
});
```

- [ ] **Step 2: Сравнить размер**

Run:
```bash
wc -l server.js
```

Expected: `<= 50` строк.

- [ ] **Step 3: Verify Node грузит**

```bash
node -e "require('./server')" 2>&1 | head -5
```

(Скрипт начнёт listen на порту — игнорируем, главное чтобы не было import errors.)

Or — лучше — запусти сервер на 5 секунд:

```bash
(node server.js &) > /tmp/test-server.log 2>&1
sleep 3
cat /tmp/test-server.log
pkill -f "node server.js" 2>/dev/null
```

Expected: вывод `🚀 Сервер запущен на порту 3000`.

- [ ] **Step 4: Тесты**

```bash
npm test 2>&1 | tail -3
```

Expected: `pass 77`.

---

## Task 17: Full smoke — все endpoints через curl

**Files:**
- Reference: `docs/admin-smoke-tests.md`

- [ ] **Step 1: Запустить сервер**

```bash
# В отдельном терминале или через PowerShell Start-Process
Start-Process node -ArgumentList "server.js" -WorkingDirectory "C:\Users\ilyap\TestKOTOKOD" -WindowStyle Hidden
Start-Sleep 3
```

- [ ] **Step 2: Smoke admin login**

```bash
curl -s -i -c /tmp/cookies.txt -X POST -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<your-password>"}' \
  http://localhost:3000/api/admin/login
```

Expected: `HTTP/1.1 200 OK`, `Set-Cookie: admin_session=...; HttpOnly; SameSite=Strict; Path=/api/admin`.

- [ ] **Step 3: Smoke negative login**

```bash
curl -s -i -X POST -H "Content-Type: application/json" \
  -d '{"username":"admin"}' \
  http://localhost:3000/api/admin/login
```

Expected: `HTTP/1.1 400`, body `{"error":"Validation failed","details":{"password":[...]}}`.

- [ ] **Step 4: Smoke admin students list**

```bash
curl -s -b /tmp/cookies.txt http://localhost:3000/api/admin/students | head -c 200
```

Expected: JSON-массив с учениками.

- [ ] **Step 5: Smoke validation на POST**

```bash
curl -s -i -b /tmp/cookies.txt -X POST -H "Content-Type: application/json" \
  -d '{}' http://localhost:3000/api/admin/teachers
```

Expected: `HTTP/1.1 400`, `{"error":"Validation failed","details":{"name":[...]}}`.

- [ ] **Step 6: Smoke teacher endpoint**

```bash
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"token":"INVALID"}' \
  http://localhost:3000/api/validateToken
```

Expected: `{"valid":false,"error":"Неверный токен"}`.

- [ ] **Step 7: 401 без cookie**

```bash
curl -s -i http://localhost:3000/api/admin/students
```

Expected: `HTTP/1.1 401`.

- [ ] **Step 8: Final test run**

```bash
npm test 2>&1 | tail -8
```

Expected: `tests 77`, `pass 77`, `fail 0`.

- [ ] **Step 9: Verify admin SPA build still works**

```bash
npm run admin:build 2>&1 | tail -6
```

Expected: build OK без ошибок.

- [ ] **Step 10: Открыть админку в браузере и пройти smoke по чеклисту**

Ручной smoke (см. `docs/admin-smoke-tests.md`):
- Login → sidebar появляется
- Каждая секция: list → row click → detail
- Lesson grid: клик → редактор → save с присутствующими (validation должна срабатывать при пустом)
- Архив: 4 sub-секции грузятся
- Theme toggle: переключение, persist в localStorage
- Logout → reload

- [ ] **Step 11: Обновить CLAUDE.md**

В `CLAUDE.md` обновить раздел «Структура»:

```diff
- server.js                       # все Express-эндпоинты (≈800 строк)
+ server.js                       # thin entry, ~50 строк (middleware + mount routes + static + error)
+ routes/
+   middleware/                   # validate.js (Zod), async-wrap.js, require-admin.js
+   teacher.js                    # /api/validateToken, /api/getData, /api/submitLesson, ...
+   admin/
+     index.js, auth.js, students.js, groups.js, teachers.js, tokens.js,
+     directions.js, memberships.js, lessons.js, payroll.js
+ shared/
+   types.ts                      # TS types всех 8 сущностей (для frontend)
+   schemas.js                    # Zod-схемы (бэк-валидация + типы для frontend)
```

И в раздел «Конфигурация (`.env`)» уже ничего не меняется (Zod использует existing env vars).

- [ ] **Step 12: Удалить backup (после успешного smoke)**

```bash
rm -rf _backup-pre-r0
```

Expected: папка удалена.

---

## Self-Review

После завершения всех 17 задач — пройти чек-лист:

- [ ] **77/77 тестов зелёные** (`npm test`)
- [ ] **Admin SPA build** работает (`npm run admin:build`)
- [ ] **server.js < 60 строк**
- [ ] **Все 9 admin sub-routers загружаются** (`node -e "require('./routes/admin')"`)
- [ ] **Teacher router загружается** (`node -e "require('./routes/teacher')"`)
- [ ] **Curl smoke**: login OK, validation 400, 401 без cookie, students list OK
- [ ] **submitLesson** через curl возвращает тот же response shape что до миграции (сверка через baseline)
- [ ] **CLAUDE.md обновлён** под новую структуру
- [ ] **Нет inline if (!body.x)** в любом route файле (всё через Zod)
- [ ] **Backup `_backup-pre-r0/` удалён** после успешного smoke

---

## Acceptance criteria

R0 считается завершённым когда:

1. `server.js` < 60 строк, только setup + mount + static + error handler
2. Все 9 admin endpoints живут в `routes/admin/<entity>.js`
3. Teacher endpoints в `routes/teacher.js`
4. Все POST/PATCH bodies валидируются через Zod (нет `if (!body.field) return 400` в routes)
5. `shared/schemas.js` экспортирует все схемы, requirable из бэка
6. `shared/types.ts` — TS types готовы для импорта фронтом
7. 77/77 тестов зелёные
8. Curl smoke проходит (login, validation 400, 401, успешный CRUD)
9. CLAUDE.md обновлён
10. Admin SPA в браузере работает идентично (никаких регрессий)

После завершения — следующий план: **R1 React foundation** (отдельный документ).
