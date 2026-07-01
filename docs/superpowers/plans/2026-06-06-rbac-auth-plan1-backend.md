# RBAC + унифицированный вход — План 1: Backend auth foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заложить серверную основу единого входа по email+пароль(+2FA) с ролями: таблицы, auth-ядро, 2FA (TOTP/email), audit-log, роуты `/api/auth/*`, gating teacher/admin и рефактор teacher-эндпоинтов с token-в-теле на сессию.

**Architecture:** Единая таблица `accounts` (email-логин, bcrypt-пароль, роль, teacher_id). HMAC session-cookie с ролью. `requireAuth`/`requireRole` gating. 2FA через `otplib` (TOTP) и email-OTP (stateless challenge_token + Beget SMTP). Все значимые события — в `security_audit_log`.

**Tech Stack:** Node/Express, PostgreSQL (pg), Zod, bcryptjs, otplib, qrcode, nodemailer, express-rate-limit, node:test.

**Спека:** `docs/superpowers/specs/2026-06-06-rbac-unified-auth-design.md`

**Примечание про git:** репозиторий пока без git. Шаги `git commit` — это чекпойнты; выполнять реально после `git init`. Между задачами всегда запускать `npm test`.

---

### Task 1: Установить зависимости

**Files:**
- Modify: `package.json`

- [ ] **Step 1: Установить пакеты**

Run:
```bash
npm install otplib qrcode nodemailer express-rate-limit
```
Expected: пакеты добавлены в `dependencies`, `package-lock.json` обновлён.

- [ ] **Step 2: Проверить, что сервер всё ещё стартует (smoke)**

Run: `node -e "require('otplib');require('qrcode');require('nodemailer');require('express-rate-limit');console.log('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add package.json package-lock.json
git commit -m "chore: add auth deps (otplib, qrcode, nodemailer, express-rate-limit)"
```

---

### Task 2: Миграция 013 — таблица accounts + recovery codes

**Files:**
- Create: `db/migrations/013_accounts.sql`

- [ ] **Step 1: Написать миграцию**

```sql
-- 013_accounts.sql — единая модель учёток (email-логин) + 2FA + recovery codes.
BEGIN;

CREATE TABLE accounts (
  id            serial PRIMARY KEY,
  email         text NOT NULL UNIQUE,        -- ЛОГИН (нормализованный: lowercase + trim)
  password_hash text NOT NULL,               -- bcrypt
  role          text NOT NULL CHECK (role IN ('teacher','manager','admin')),
  teacher_id    int REFERENCES teachers(id),
  active        bool NOT NULL DEFAULT true,
  twofa_method      text CHECK (twofa_method IN ('totp','email')),
  twofa_secret      text,
  twofa_enabled     bool NOT NULL DEFAULT false,
  twofa_confirmed_at timestamptz,
  failed_login_count int NOT NULL DEFAULT 0,
  locked_until       timestamptz,
  last_login_at      timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CHECK ((role = 'teacher') = (teacher_id IS NOT NULL)),
  CHECK (twofa_method <> 'totp' OR twofa_secret IS NOT NULL)
);
CREATE UNIQUE INDEX accounts_teacher_id_uq ON accounts(teacher_id) WHERE teacher_id IS NOT NULL;

CREATE TABLE account_recovery_codes (
  id         serial PRIMARY KEY,
  account_id int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  code_hash  text NOT NULL,
  used_at    timestamptz
);
CREATE INDEX account_recovery_codes_account_idx ON account_recovery_codes(account_id);

COMMIT;
```

- [ ] **Step 2: Применить миграцию**

Run: `npm run db:migrate`
Expected: `OK 013_accounts.sql`

- [ ] **Step 3: Проверить схему**

Run: `psql -U journal -h localhost -d journal -c "\d accounts"`
Expected: таблица с колонками email/role/teacher_id/twofa_*; индекс `accounts_teacher_id_uq`.

- [ ] **Step 4: Commit**

```bash
git add db/migrations/013_accounts.sql
git commit -m "feat(db): accounts + recovery codes (migration 013)"
```

---

### Task 3: Миграция 014 — security_audit_log

**Files:**
- Create: `db/migrations/014_security_audit_log.sql`

- [ ] **Step 1: Написать миграцию**

```sql
-- 014_security_audit_log.sql — журнал событий безопасности (РСБ, Приказ ФСТЭК №21).
BEGIN;

CREATE TABLE security_audit_log (
  id          bigserial PRIMARY KEY,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  account_id  int REFERENCES accounts(id),
  actor_email text,
  event       text NOT NULL,
  ip          text,
  user_agent  text,
  target_id   int,
  meta        jsonb
);
CREATE INDEX security_audit_log_occurred_idx ON security_audit_log(occurred_at DESC);
CREATE INDEX security_audit_log_account_idx  ON security_audit_log(account_id, occurred_at DESC);

COMMIT;
```

- [ ] **Step 2: Применить + проверить**

Run: `npm run db:migrate && psql -U journal -h localhost -d journal -c "\d security_audit_log"`
Expected: `OK 014_security_audit_log.sql`, таблица существует.

- [ ] **Step 3: Commit**

```bash
git add db/migrations/014_security_audit_log.sql
git commit -m "feat(db): security_audit_log (migration 014)"
```

---

### Task 4: Миграция 015 — согласие на ПДн у students

**Files:**
- Create: `db/migrations/015_students_consent.sql`

- [ ] **Step 1: Написать миграцию**

```sql
-- 015_students_consent.sql — фиксация факта согласия на обработку ПДн (152-ФЗ).
BEGIN;

ALTER TABLE students
  ADD COLUMN consent_given bool NOT NULL DEFAULT false,
  ADD COLUMN consent_at    timestamptz,
  ADD COLUMN consent_by    text,
  ADD COLUMN consent_note  text;

COMMIT;
```

- [ ] **Step 2: Применить + проверить**

Run: `npm run db:migrate && psql -U journal -h localhost -d journal -c "\d students" | grep consent`
Expected: 4 колонки `consent_*`.

- [ ] **Step 3: Commit**

```bash
git add db/migrations/015_students_consent.sql
git commit -m "feat(db): students consent columns (migration 015)"
```

---

### Task 5: services/auth.js — нормализация email + генерация токен-пароля (TDD)

**Files:**
- Create: `services/auth.js`
- Test: `services/auth.test.js`

- [ ] **Step 1: Написать падающий тест**

```js
// services/auth.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const auth = require('./auth');

test('normalizeEmail: lowercase + trim', () => {
  assert.strictEqual(auth.normalizeEmail('  Foo@Bar.RU '), 'foo@bar.ru');
});

test('normalizeEmail: невалидный → null', () => {
  assert.strictEqual(auth.normalizeEmail('not-an-email'), null);
  assert.strictEqual(auth.normalizeEmail(''), null);
  assert.strictEqual(auth.normalizeEmail(null), null);
});

test('generateTokenPassword: формат XXXX-XXXX-XXXX', () => {
  const p = auth.generateTokenPassword();
  assert.match(p, /^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$/);
  assert.notStrictEqual(p, auth.generateTokenPassword()); // разные
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test services/auth.test.js`
Expected: FAIL (`Cannot find module './auth'`).

- [ ] **Step 3: Реализовать `services/auth.js` (минимум для теста + перенос sign/verify)**

```js
// services/auth.js
// Унифицированное auth-ядро: HMAC-сессия, пароли, нормализация email,
// генерация токен-пароля, middleware requireAuth/requireRole.
const crypto = require('node:crypto');
const bcrypt = require('bcryptjs');

const COOKIE_NAME = 'session';
const COOKIE_LIFETIME_MS = 24 * 60 * 60 * 1000;
const BCRYPT_COST = 12;
const TOKEN_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // без 0/O/1/I

function b64url(buf) { return Buffer.from(buf).toString('base64url'); }
function unb64url(s) { return Buffer.from(s, 'base64url').toString('utf8'); }

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
  } catch { return null; }
}

async function hashPassword(plain) { return bcrypt.hash(plain, BCRYPT_COST); }
async function comparePassword(plain, hash) {
  if (!hash) return false;
  return bcrypt.compare(plain, hash);
}

function normalizeEmail(raw) {
  if (typeof raw !== 'string') return null;
  const e = raw.trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e)) return null;
  return e;
}

function generateTokenPassword() {
  const part = () => Array.from(crypto.randomBytes(4))
    .map((b) => TOKEN_ALPHABET[b % TOKEN_ALPHABET.length]).join('');
  return `${part()}-${part()}-${part()}`;
}

module.exports = {
  COOKIE_NAME, COOKIE_LIFETIME_MS,
  sign, verify, hashPassword, comparePassword,
  normalizeEmail, generateTokenPassword,
};
```

- [ ] **Step 4: Запустить — убедиться, что зелено**

Run: `node --test services/auth.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/auth.js services/auth.test.js
git commit -m "feat(auth): core helpers (sign/verify, password, normalizeEmail, token-password)"
```

---

### Task 6: Cookie-билдеры + requireAuth/requireRole (TDD)

**Files:**
- Modify: `services/auth.js`
- Modify: `services/auth.test.js`

- [ ] **Step 1: Добавить падающие тесты**

```js
// добавить в services/auth.test.js
test('requireRole: пускает нужную роль, режет лишнюю', () => {
  const next = () => { next.called = true; };
  const resOf = () => {
    const r = {};
    r.status = (c) => { r.code = c; return r; };
    r.json = (b) => { r.body = b; return r; };
    return r;
  };
  // admin к admin-роуту
  let req = { account: { role: 'admin' } }; let res = resOf(); next.called = false;
  auth.requireRole('manager', 'admin')(req, res, next);
  assert.strictEqual(next.called, true);
  // teacher к admin-роуту → 403
  req = { account: { role: 'teacher' } }; res = resOf(); next.called = false;
  auth.requireRole('manager', 'admin')(req, res, next);
  assert.strictEqual(res.code, 403);
  assert.strictEqual(next.called, false);
});
```

- [ ] **Step 2: Запустить — FAIL**

Run: `node --test services/auth.test.js`
Expected: FAIL (`auth.requireRole is not a function`).

- [ ] **Step 3: Реализовать cookie-билдеры + middleware (дополнить services/auth.js)**

Добавить в `services/auth.js` ДО `module.exports`:

```js
function cookieOptions() {
  return {
    httpOnly: true,
    sameSite: 'strict',
    path: '/',
    maxAge: COOKIE_LIFETIME_MS,
    secure: process.env.NODE_ENV === 'production',
  };
}

function issueSession(res, account) {
  const payload = { account_id: account.id, role: account.role, iat: Date.now(), exp: Date.now() + COOKIE_LIFETIME_MS };
  res.cookie(COOKIE_NAME, sign(payload, process.env.ADMIN_COOKIE_SECRET), cookieOptions());
}

function clearSession(res) {
  res.cookie(COOKIE_NAME, '', { ...cookieOptions(), maxAge: 0 });
}

function requireAuth(req, res, next) {
  const token = req.cookies && req.cookies[COOKIE_NAME];
  const payload = verify(token, process.env.ADMIN_COOKIE_SECRET);
  if (!payload) return res.status(401).json({ error: 'Unauthorized' });
  req.account = { account_id: payload.account_id, role: payload.role };
  next();
}

function requireRole(...roles) {
  return (req, res, next) => {
    if (!req.account || !roles.includes(req.account.role)) {
      return res.status(403).json({ error: 'Forbidden' });
    }
    next();
  };
}
```

Дополнить `module.exports`: добавить `issueSession, clearSession, requireAuth, requireRole`.

- [ ] **Step 4: Запустить — PASS**

Run: `node --test services/auth.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/auth.js services/auth.test.js
git commit -m "feat(auth): session cookie + requireAuth/requireRole"
```

---

### Task 7: admin-auth.js → re-export (back-compat)

**Files:**
- Modify: `services/admin-auth.js`

- [ ] **Step 1: Заменить тело на тонкий ре-экспорт (сохранить старые имена)**

```js
// services/admin-auth.js
// DEPRECATED-shim: единое auth-ядро живёт в services/auth.js.
// Сохраняем экспорты ради старых тестов/импортов до полного перехода.
const auth = require('./auth');

// requireAdmin == requireRole('manager','admin') поверх единой сессии.
function requireAdmin(req, res, next) {
  return auth.requireAuth(req, res, () => auth.requireRole('manager', 'admin')(req, res, next));
}

module.exports = {
  sign: auth.sign,
  verify: auth.verify,
  comparePassword: auth.comparePassword,
  COOKIE_LIFETIME_MS: auth.COOKIE_LIFETIME_MS,
  requireAdmin,
};
```

- [ ] **Step 2: Прогнать старый тест**

Run: `node --test services/admin-auth.test.js`
Expected: PASS (sign/verify/comparePassword по-прежнему работают).

- [ ] **Step 3: Commit**

```bash
git add services/admin-auth.js
git commit -m "refactor(auth): admin-auth → shim over services/auth"
```

---

### Task 8: services/audit.js — запись событий безопасности (TDD)

**Files:**
- Create: `services/audit.js`
- Test: `services/audit.test.js`

- [ ] **Step 1: Написать падающий тест (на «не пишем секреты»)**

```js
// services/audit.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const { sanitizeMeta } = require('./audit');

test('sanitizeMeta вырезает секреты', () => {
  const out = sanitizeMeta({ ok: 1, password: 'x', code: '123456', twofa_secret: 's', token: 't' });
  assert.deepStrictEqual(out, { ok: 1 });
});

test('sanitizeMeta: null безопасен', () => {
  assert.strictEqual(sanitizeMeta(null), null);
});
```

- [ ] **Step 2: Запустить — FAIL**

Run: `node --test services/audit.test.js`
Expected: FAIL (`Cannot find module './audit'`).

- [ ] **Step 3: Реализовать services/audit.js**

```js
// services/audit.js — запись в security_audit_log (РСБ). Без секретов в meta.
const { pool } = require('./db');

const SECRET_KEYS = new Set(['password', 'code', 'twofa_secret', 'token', 'password_hash', 'recovery']);

function sanitizeMeta(meta) {
  if (!meta || typeof meta !== 'object') return meta ?? null;
  const out = {};
  for (const [k, v] of Object.entries(meta)) {
    if (SECRET_KEYS.has(k)) continue;
    out[k] = v;
  }
  return out;
}

// req нужен ради ip/user-agent; любые поля опциональны.
async function logEvent({ event, account_id = null, actor_email = null, target_id = null, meta = null, req = null }) {
  const ip = req ? (req.headers['x-forwarded-for'] || req.socket?.remoteAddress || null) : null;
  const ua = req ? (req.headers['user-agent'] || null) : null;
  try {
    await pool.query(
      `INSERT INTO security_audit_log (account_id, actor_email, event, ip, user_agent, target_id, meta)
       VALUES ($1,$2,$3,$4,$5,$6,$7)`,
      [account_id, actor_email, event, ip, ua, target_id, sanitizeMeta(meta)],
    );
  } catch (e) {
    console.error('[audit] failed to log', event, e.message); // аудит не должен ронять запрос
  }
}

module.exports = { logEvent, sanitizeMeta };
```

- [ ] **Step 4: Запустить — PASS**

Run: `node --test services/audit.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/audit.js services/audit.test.js
git commit -m "feat(audit): security_audit_log writer with secret sanitization"
```

---

### Task 9: services/twofa.js — TOTP + email-OTP + recovery (TDD)

**Files:**
- Create: `services/twofa.js`
- Test: `services/twofa.test.js`

- [ ] **Step 1: Написать падающий тест**

```js
// services/twofa.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const twofa = require('./twofa');
const { authenticator } = require('otplib');

test('TOTP: verifyTotp принимает текущий код', () => {
  const secret = twofa.generateSecret();
  const code = authenticator.generate(secret);
  assert.strictEqual(twofa.verifyTotp(secret, code), true);
  assert.strictEqual(twofa.verifyTotp(secret, '000000'), false);
});

test('provisioningUri содержит issuer и логин', () => {
  const uri = twofa.provisioningUri('JBSWY3DPEHPK3PXP', 'a@b.ru');
  assert.match(uri, /^otpauth:\/\/totp\//);
  assert.match(uri, /issuer=KOTOKOD/);
});

test('email-OTP: challenge подтверждается верным кодом и истекает', async () => {
  const SECRET = 'x'.repeat(64);
  const { code, challenge } = await twofa.issueEmailChallenge(7, SECRET, 5 * 60 * 1000);
  assert.match(code, /^\d{6}$/);
  assert.deepStrictEqual(await twofa.verifyEmailChallenge(challenge, code, SECRET), { ok: true, account_id: 7 });
  assert.strictEqual((await twofa.verifyEmailChallenge(challenge, '000000', SECRET)).ok, false);
  const expired = await twofa.issueEmailChallenge(7, SECRET, -1);
  assert.strictEqual((await twofa.verifyEmailChallenge(expired.challenge, expired.code, SECRET)).ok, false);
});

test('recovery codes: 8 штук + хеши верифицируются', async () => {
  const { plain, hashes } = await twofa.generateRecoveryCodes();
  assert.strictEqual(plain.length, 8);
  assert.strictEqual(hashes.length, 8);
  assert.strictEqual(await twofa.verifyRecovery(plain[0], hashes[0]), true);
  assert.strictEqual(await twofa.verifyRecovery('nope', hashes[0]), false);
});
```

- [ ] **Step 2: Запустить — FAIL**

Run: `node --test services/twofa.test.js`
Expected: FAIL (`Cannot find module './twofa'`).

- [ ] **Step 3: Реализовать services/twofa.js**

```js
// services/twofa.js — 2FA: TOTP (otplib) + email-OTP (stateless challenge) + recovery codes.
const crypto = require('node:crypto');
const bcrypt = require('bcryptjs');
const { authenticator } = require('otplib');
const qrcode = require('qrcode');
const { sign, verify } = require('./auth');

authenticator.options = { window: 1 }; // ±1 шаг — терпимость к рассинхрону часов

// ---- TOTP ----
function generateSecret() { return authenticator.generateSecret(); }
function provisioningUri(secret, email) {
  return authenticator.keyuri(email, 'KOTOKOD', secret);
}
async function qrDataUrl(uri) { return qrcode.toDataURL(uri); }
function verifyTotp(secret, code) {
  if (!secret || !code) return false;
  try { return authenticator.verify({ token: String(code), secret }); }
  catch { return false; }
}

// ---- email-OTP (stateless: код хранится bcrypt-хешем внутри подписанного challenge) ----
function generateEmailCode() {
  return String(crypto.randomInt(0, 1_000_000)).padStart(6, '0');
}
async function issueEmailChallenge(accountId, secret, ttlMs = 5 * 60 * 1000) {
  const code = generateEmailCode();
  const code_hash = await bcrypt.hash(code, 8);
  const challenge = sign({ kind: 'email2fa', account_id: accountId, code_hash, exp: Date.now() + ttlMs }, secret);
  return { code, challenge };
}
async function verifyEmailChallenge(challenge, code, secret) {
  const payload = verify(challenge, secret);
  if (!payload || payload.kind !== 'email2fa') return { ok: false };
  const ok = await bcrypt.compare(String(code), payload.code_hash);
  return ok ? { ok: true, account_id: payload.account_id } : { ok: false };
}

// ---- recovery codes ----
async function generateRecoveryCodes(n = 8) {
  const plain = Array.from({ length: n }, () => crypto.randomBytes(5).toString('hex'));
  const hashes = await Promise.all(plain.map((c) => bcrypt.hash(c, 8)));
  return { plain, hashes };
}
async function verifyRecovery(code, hash) {
  if (!code || !hash) return false;
  return bcrypt.compare(String(code), hash);
}

module.exports = {
  generateSecret, provisioningUri, qrDataUrl, verifyTotp,
  generateEmailCode, issueEmailChallenge, verifyEmailChallenge,
  generateRecoveryCodes, verifyRecovery,
};
```

- [ ] **Step 4: Запустить — PASS**

Run: `node --test services/twofa.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/twofa.js services/twofa.test.js
git commit -m "feat(2fa): TOTP + stateless email-OTP + recovery codes"
```

---

### Task 10: services/mailer.js — отправка email-OTP (Beget SMTP)

**Files:**
- Create: `services/mailer.js`
- Modify: `.env` (добавить SMTP-переменные — вручную, не коммитить)

- [ ] **Step 1: Добавить SMTP-переменные в `.env`**

```
SMTP_HOST=smtp.beget.com
SMTP_PORT=465
SMTP_USER=<тестовый ящик>
SMTP_PASS=<пароль>
SMTP_FROM="KOTOKOD <noreply@домен>"
```

- [ ] **Step 2: Реализовать services/mailer.js**

```js
// services/mailer.js — отправка писем (email-OTP) через SMTP (Beget). Письмо без ПДн.
const nodemailer = require('nodemailer');

let _transport = null;
function transport() {
  if (_transport) return _transport;
  _transport = nodemailer.createTransport({
    host: process.env.SMTP_HOST,
    port: Number(process.env.SMTP_PORT) || 465,
    secure: Number(process.env.SMTP_PORT) === 465,
    auth: { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS },
  });
  return _transport;
}

async function sendOtpEmail(to, code) {
  await transport().sendMail({
    from: process.env.SMTP_FROM,
    to,
    subject: 'Код входа KOTOKOD',
    text: `Ваш одноразовый код входа: ${code}\nКод действует 5 минут. Если вы не входили — проигнорируйте письмо.`,
  });
}

module.exports = { sendOtpEmail };
```

- [ ] **Step 3: Ручная проверка отправки (smoke, опционально на dev-ящик)**

Run:
```bash
node -e "require('dotenv').config();require('./services/mailer').sendOtpEmail(process.env.SMTP_USER,'123456').then(()=>console.log('sent')).catch(e=>{console.error(e.message);process.exit(1)})"
```
Expected: `sent` (письмо пришло). Если SMTP не настроен — задачу отметить и вернуться позже.

- [ ] **Step 4: Commit**

```bash
git add services/mailer.js
git commit -m "feat(mailer): email-OTP sender via SMTP"
```

---

### Task 11: services/repo/accounts.js — доступ к учёткам (TDD, DB)

**Files:**
- Create: `services/repo/accounts.js`
- Test: `services/repo/accounts.test.js`

> Тест работает с реальной dev-БД (как `services/admin-repo.test.js`). Требует мигрированную локальную БД и хотя бы одного `teachers` (создаётся в тесте).

- [ ] **Step 1: Написать падающий тест**

```js
// services/repo/accounts.test.js
const { test, after } = require('node:test');
const assert = require('node:assert');
const { pool } = require('../db');
const accounts = require('./accounts');
const auth = require('../auth');

after(async () => { await pool.end(); });

async function freshTeacher() {
  const { rows } = await pool.query(
    `INSERT INTO teachers (name) VALUES ($1) RETURNING id`,
    ['T-' + Date.now() + Math.random()],
  );
  return rows[0].id;
}

test('create/findByEmail/getById', async () => {
  const tid = await freshTeacher();
  const email = `acc${Date.now()}@b.ru`;
  const created = await accounts.createAccount({
    email, password_hash: await auth.hashPassword('pw'), role: 'teacher', teacher_id: tid,
  });
  assert.ok(created.id);
  const byEmail = await accounts.findByEmail(email);
  assert.strictEqual(byEmail.id, created.id);
  const byId = await accounts.getById(created.id);
  assert.strictEqual(byId.email, email);
});

test('setPassword меняет хеш', async () => {
  const tid = await freshTeacher();
  const a = await accounts.createAccount({
    email: `p${Date.now()}@b.ru`, password_hash: await auth.hashPassword('old'), role: 'manager', teacher_id: null,
  });
  await accounts.setPassword(a.id, await auth.hashPassword('new'));
  const after = await accounts.getById(a.id);
  assert.notStrictEqual(after.password_hash, a.password_hash);
});

test('recovery codes: запись и пометка использованным', async () => {
  const a = await accounts.createAccount({
    email: `r${Date.now()}@b.ru`, password_hash: 'h', role: 'admin', teacher_id: null,
  });
  await accounts.replaceRecoveryCodes(a.id, ['h1', 'h2']);
  const codes = await accounts.listRecoveryCodes(a.id);
  assert.strictEqual(codes.length, 2);
  await accounts.markRecoveryUsed(codes[0].id);
  const left = await accounts.listRecoveryCodes(a.id);
  assert.strictEqual(left.filter((c) => !c.used_at).length, 1);
});
```

- [ ] **Step 2: Запустить — FAIL**

Run: `node --test services/repo/accounts.test.js`
Expected: FAIL (`Cannot find module './accounts'`).

- [ ] **Step 3: Реализовать services/repo/accounts.js**

```js
const { pool } = require('../db');
const { paginate, F } = require('../pagination');

const ACCOUNTS_PAGINATION = {
  sortable: { email: 'a.email', role: 'a.role', active: 'a.active', created_at: 'a.created_at' },
  defaultSortBy: 'email', defaultSortDir: 'asc',
  from: 'FROM accounts a LEFT JOIN teachers t ON t.id = a.teacher_id',
  selectColumns: 'a.id, a.email, a.role, a.teacher_id, a.active, a.twofa_enabled, a.twofa_method, a.last_login_at, t.name AS teacher_name',
  secondarySort: 'a.id DESC',
  filters: { email: F.like('a.email'), role: F.exact('a.role'), active: F.bool('a.active') },
};

async function listAccounts(request) { return paginate(ACCOUNTS_PAGINATION, request); }

async function findByEmail(email) {
  const { rows } = await pool.query('SELECT * FROM accounts WHERE email = $1', [email]);
  return rows[0] || null;
}
async function getById(id) {
  const { rows } = await pool.query('SELECT * FROM accounts WHERE id = $1', [id]);
  return rows[0] || null;
}
async function getByIdWithTeacher(id) {
  const { rows } = await pool.query(
    `SELECT a.*, t.name AS teacher_name FROM accounts a
       LEFT JOIN teachers t ON t.id = a.teacher_id WHERE a.id = $1`, [id]);
  return rows[0] || null;
}
async function createAccount({ email, password_hash, role, teacher_id }) {
  const { rows } = await pool.query(
    `INSERT INTO accounts (email, password_hash, role, teacher_id)
     VALUES ($1,$2,$3,$4) RETURNING *`,
    [email, password_hash, role, teacher_id ?? null],
  );
  return rows[0];
}
async function updateAccount(id, { email, role, active }) {
  const { rows } = await pool.query(
    `UPDATE accounts SET
       email  = COALESCE($2, email),
       role   = COALESCE($3, role),
       active = COALESCE($4, active)
     WHERE id = $1 RETURNING *`,
    [id, email ?? null, role ?? null, active ?? null],
  );
  return rows[0] || null;
}
async function setPassword(id, password_hash) {
  const { rowCount } = await pool.query('UPDATE accounts SET password_hash = $2 WHERE id = $1', [id, password_hash]);
  return rowCount > 0;
}
async function softDelete(id) {
  const { rowCount } = await pool.query('UPDATE accounts SET active = false WHERE id = $1', [id]);
  return rowCount > 0;
}
async function setTwofa(id, { method, secret, enabled, confirmed }) {
  const { rows } = await pool.query(
    `UPDATE accounts SET
       twofa_method = $2, twofa_secret = $3, twofa_enabled = $4,
       twofa_confirmed_at = CASE WHEN $5 THEN now() ELSE twofa_confirmed_at END
     WHERE id = $1 RETURNING *`,
    [id, method ?? null, secret ?? null, !!enabled, !!confirmed],
  );
  return rows[0] || null;
}
async function resetTwofa(id) {
  await pool.query('DELETE FROM account_recovery_codes WHERE account_id = $1', [id]);
  const { rows } = await pool.query(
    `UPDATE accounts SET twofa_method=NULL, twofa_secret=NULL, twofa_enabled=false, twofa_confirmed_at=NULL
     WHERE id=$1 RETURNING *`, [id]);
  return rows[0] || null;
}
async function registerLoginSuccess(id) {
  await pool.query('UPDATE accounts SET failed_login_count=0, locked_until=NULL, last_login_at=now() WHERE id=$1', [id]);
}
async function registerLoginFailure(id, maxFails = 5, lockMs = 15 * 60 * 1000) {
  const { rows } = await pool.query(
    `UPDATE accounts SET
       failed_login_count = failed_login_count + 1,
       locked_until = CASE WHEN failed_login_count + 1 >= $2 THEN now() + ($3 || ' milliseconds')::interval ELSE locked_until END
     WHERE id=$1 RETURNING failed_login_count, locked_until`,
    [id, maxFails, String(lockMs)],
  );
  return rows[0] || null;
}
async function replaceRecoveryCodes(accountId, hashes) {
  await pool.query('DELETE FROM account_recovery_codes WHERE account_id=$1', [accountId]);
  for (const h of hashes) {
    await pool.query('INSERT INTO account_recovery_codes (account_id, code_hash) VALUES ($1,$2)', [accountId, h]);
  }
}
async function listRecoveryCodes(accountId) {
  const { rows } = await pool.query('SELECT * FROM account_recovery_codes WHERE account_id=$1 ORDER BY id', [accountId]);
  return rows;
}
async function markRecoveryUsed(id) {
  await pool.query('UPDATE account_recovery_codes SET used_at=now() WHERE id=$1', [id]);
}

module.exports = {
  listAccounts, findByEmail, getById, getByIdWithTeacher, createAccount, updateAccount,
  setPassword, softDelete, setTwofa, resetTwofa, registerLoginSuccess, registerLoginFailure,
  replaceRecoveryCodes, listRecoveryCodes, markRecoveryUsed,
};
```

- [ ] **Step 4: Запустить — PASS**

Run: `node --test services/repo/accounts.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/repo/accounts.js services/repo/accounts.test.js
git commit -m "feat(repo): accounts repository (CRUD, 2FA, recovery, lockout)"
```

---

### Task 12: Zod-схемы для auth и accounts

**Files:**
- Modify: `shared/schemas.js`

- [ ] **Step 1: Добавить схемы (заменить старый loginSchema)**

Заменить блок `// ===== Admin auth =====` (loginSchema по username) на:

```js
// ===== Auth (унифицированный вход) =====

const roleEnum = z.enum(['teacher', 'manager', 'admin']);
const loginRole = z.enum(['teacher', 'admin']); // кнопка на странице: преподаватель|админ-менеджер
const emailStr = z.string().trim().toLowerCase().email();

const loginSchema = z.object({
  email: emailStr,
  password: z.string().min(1),
  role: loginRole,
});

const login2faSchema = z.object({
  challenge_token: z.string().min(1),
  code: z.string().trim().min(1),
});

const twofaSetupSchema = z.object({
  challenge_token: z.string().min(1).optional(),
  method: z.enum(['totp', 'email']),
});

const twofaEnableSchema = z.object({
  challenge_token: z.string().min(1).optional(),
  code: z.string().trim().min(1),
});

const emailSendSchema = z.object({ challenge_token: z.string().min(1) });

// ===== Accounts (admin-управление) =====

const createAccountSchema = z.object({
  email: emailStr,
  role: roleEnum,
  teacher_id: id.nullable().optional(),
}).refine((a) => (a.role === 'teacher') === (a.teacher_id != null),
  { message: 'teacher role requires teacher_id (and only teacher)' });

const updateAccountSchema = z.object({
  email: emailStr.optional(),
  role: roleEnum.optional(),
  active: z.boolean().optional(),
});
```

И добавить эти имена в `module.exports` внизу файла:
`loginSchema, login2faSchema, twofaSetupSchema, twofaEnableSchema, emailSendSchema, createAccountSchema, updateAccountSchema`.

- [ ] **Step 2: Проверить, что схемы парсятся**

Run:
```bash
node -e "const s=require('./shared/schemas');console.log(s.loginSchema.safeParse({email:'A@B.ru',password:'x',role:'admin'}).success)"
```
Expected: `true`

- [ ] **Step 3: Commit**

```bash
git add shared/schemas.js
git commit -m "feat(schemas): auth + accounts zod schemas (email login)"
```

---

### Task 13: routes/auth.js — login без 2FA-ветки (базовый happy-path) (TDD-lite)

**Files:**
- Create: `routes/auth.js`
- Modify: `server.js` (смонтировать `/api/auth`)

> 2FA-ветки добавим в Task 14. Здесь: login (если у аккаунта 2FA выключена и роль не требует — сразу сессия), logout, me.

- [ ] **Step 1: Реализовать routes/auth.js (базовый)**

```js
const express = require('express');
const auth = require('../services/auth');
const accountsRepo = require('../services/repo/accounts');
const { logEvent } = require('../services/audit');
const validate = require('./middleware/validate');
const asyncWrap = require('./middleware/async-wrap');
const { loginSchema } = require('../shared/schemas');

const router = express.Router();

// teacher-кнопка ↔ роль teacher; admin-кнопка ↔ manager|admin
function roleMatches(buttonRole, accountRole) {
  if (buttonRole === 'teacher') return accountRole === 'teacher';
  return accountRole === 'manager' || accountRole === 'admin';
}
function redirectFor(role) { return role === 'teacher' ? '/teacher' : '/admin'; }
const FAIL = { error: 'Неверный email или пароль' };

router.post('/login', validate(loginSchema), asyncWrap(async (req, res) => {
  const { email, password, role } = req.validated;
  const acc = await accountsRepo.findByEmail(email);
  if (!acc || !acc.active) {
    await logEvent({ event: 'login_fail', actor_email: email, meta: { reason: 'no_account' }, req });
    return res.status(401).json(FAIL);
  }
  if (acc.locked_until && new Date(acc.locked_until) > new Date()) {
    await logEvent({ event: 'locked', account_id: acc.id, actor_email: email, req });
    return res.status(429).json({ error: 'Временно заблокировано, попробуйте позже' });
  }
  const ok = await auth.comparePassword(password, acc.password_hash);
  if (!ok || !roleMatches(role, acc.role)) {
    await accountsRepo.registerLoginFailure(acc.id);
    await logEvent({ event: 'login_fail', account_id: acc.id, actor_email: email, meta: { reason: ok ? 'role' : 'password' }, req });
    return res.status(401).json(FAIL);
  }
  // 2FA-ветки появятся в следующей задаче. Пока: если 2FA выключена — сразу сессия.
  if (!acc.twofa_enabled) {
    await accountsRepo.registerLoginSuccess(acc.id);
    auth.issueSession(res, acc);
    await logEvent({ event: 'login_success', account_id: acc.id, actor_email: email, req });
    return res.json({ role: acc.role, redirect: redirectFor(acc.role) });
  }
  return res.status(501).json({ error: '2FA not implemented yet' }); // временно, до Task 14
}));

router.post('/logout', (req, res) => {
  auth.clearSession(res);
  res.json({ ok: true });
});

router.get('/me', auth.requireAuth, asyncWrap(async (req, res) => {
  const acc = await accountsRepo.getByIdWithTeacher(req.account.account_id);
  if (!acc) return res.status(401).json({ error: 'Unauthorized' });
  res.json({
    account_id: acc.id, email: acc.email, role: acc.role,
    teacher_id: acc.teacher_id, name: acc.teacher_name || acc.email, twofa_enabled: acc.twofa_enabled,
  });
});

module.exports = router;
```

> ⚠️ Закрывающая `});` у `/me` должна быть `}));` (asyncWrap). Проверить при вставке.

- [ ] **Step 2: Смонтировать в server.js (перед teacher/admin роутерами)**

В `server.js` добавить импорт и монтирование:
```js
const authRouter = require('./routes/auth');
// ... после app.use(cookieParser());
app.use('/api/auth', authRouter);
```

- [ ] **Step 3: Smoke — сервер стартует**

Run: `node -e "require('./routes/auth');console.log('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add routes/auth.js server.js
git commit -m "feat(auth): /api/auth login(basic)/logout/me"
```

---

### Task 14: routes/auth.js — 2FA-ветки login + endpoints

**Files:**
- Modify: `routes/auth.js`

- [ ] **Step 1: Заменить заглушку 501 на 2FA-ветвление + добавить endpoints**

В начало файла добавить импорты:
```js
const twofa = require('../services/twofa');
const { sendOtpEmail } = require('../services/mailer');
const { login2faSchema, twofaSetupSchema, twofaEnableSchema, emailSendSchema } = require('../shared/schemas');
```

Добавить хелпер (после `redirectFor`):
```js
const CH_TTL = 5 * 60 * 1000;
function issueChallenge(account, stage) {
  return auth.sign(
    { kind: 'login_challenge', stage, account_id: account.id, role: account.role, exp: Date.now() + CH_TTL },
    process.env.ADMIN_COOKIE_SECRET,
  );
}
function readChallenge(token) {
  const p = auth.verify(token, process.env.ADMIN_COOKIE_SECRET);
  return (p && p.kind === 'login_challenge') ? p : null;
}
function requires2fa(role) { return role === 'manager' || role === 'admin'; }
```

Заменить блок `if (!acc.twofa_enabled) {...} return res.status(501)...` на:
```js
  if (acc.twofa_enabled) {
    if (acc.twofa_method === 'email') {
      const { code, challenge } = await twofa.issueEmailChallenge(acc.id, process.env.ADMIN_COOKIE_SECRET);
      await sendOtpEmail(acc.email, code);
      return res.json({ twofa_required: true, method: 'email', challenge_token: challenge });
    }
    return res.json({ twofa_required: true, method: 'totp', challenge_token: issueChallenge(acc, 'verify') });
  }
  if (requires2fa(acc.role)) {
    // 2FA обязательна, но не настроена → enrollment
    return res.json({ twofa_enrollment_required: true, challenge_token: issueChallenge(acc, 'enroll') });
  }
  await accountsRepo.registerLoginSuccess(acc.id);
  auth.issueSession(res, acc);
  await logEvent({ event: 'login_success', account_id: acc.id, actor_email: email, req });
  return res.json({ role: acc.role, redirect: redirectFor(acc.role) });
```

Добавить endpoints перед `module.exports`:
```js
// Завершение входа по 2FA-коду (TOTP / email-OTP / recovery)
router.post('/login/2fa', validate(login2faSchema), asyncWrap(async (req, res) => {
  const { challenge_token, code } = req.validated;
  // email-challenge?
  const emailRes = await twofa.verifyEmailChallenge(challenge_token, code, process.env.ADMIN_COOKIE_SECRET);
  let accountId = emailRes.ok ? emailRes.account_id : null;
  let viaRecovery = false;

  if (!accountId) {
    const ch = readChallenge(challenge_token);
    if (!ch || ch.stage !== 'verify') return res.status(401).json({ error: 'Неверный или просроченный код' });
    const acc = await accountsRepo.getById(ch.account_id);
    if (!acc) return res.status(401).json({ error: 'Неверный или просроченный код' });
    if (acc.twofa_method === 'totp' && twofa.verifyTotp(acc.twofa_secret, code)) {
      accountId = acc.id;
    } else {
      // recovery-код
      for (const rc of await accountsRepo.listRecoveryCodes(acc.id)) {
        if (!rc.used_at && await twofa.verifyRecovery(code, rc.code_hash)) {
          await accountsRepo.markRecoveryUsed(rc.id); accountId = acc.id; viaRecovery = true; break;
        }
      }
    }
  }
  if (!accountId) {
    await logEvent({ event: '2fa_fail', actor_email: null, req });
    return res.status(401).json({ error: 'Неверный или просроченный код' });
  }
  const acc = await accountsRepo.getById(accountId);
  await accountsRepo.registerLoginSuccess(acc.id);
  auth.issueSession(res, acc);
  await logEvent({ event: 'login_success', account_id: acc.id, actor_email: acc.email, meta: { viaRecovery }, req });
  res.json({ role: acc.role, redirect: redirectFor(acc.role) });
}));

// Повторно отправить email-код в рамках текущего входа
router.post('/2fa/email/send', validate(emailSendSchema), asyncWrap(async (req, res) => {
  const ch = readChallenge(req.validated.challenge_token);
  if (!ch) return res.status(401).json({ error: 'Сессия входа истекла' });
  const acc = await accountsRepo.getById(ch.account_id);
  if (!acc || acc.twofa_method !== 'email') return res.status(400).json({ error: 'Метод недоступен' });
  const { code, challenge } = await twofa.issueEmailChallenge(acc.id, process.env.ADMIN_COOKIE_SECRET);
  await sendOtpEmail(acc.email, code);
  res.json({ challenge_token: challenge });
}));

// Enrollment: настройка метода
router.post('/2fa/setup', validate(twofaSetupSchema), asyncWrap(async (req, res) => {
  const ch = readChallenge(req.validated.challenge_token);
  if (!ch || ch.stage !== 'enroll') return res.status(401).json({ error: 'Сессия входа истекла' });
  const acc = await accountsRepo.getById(ch.account_id);
  if (!acc) return res.status(401).json({ error: 'Сессия входа истекла' });
  if (req.validated.method === 'totp') {
    const secret = twofa.generateSecret();
    await accountsRepo.setTwofa(acc.id, { method: 'totp', secret, enabled: false, confirmed: false });
    const uri = twofa.provisioningUri(secret, acc.email);
    return res.json({ method: 'totp', secret, qr: await twofa.qrDataUrl(uri) });
  }
  // email
  await accountsRepo.setTwofa(acc.id, { method: 'email', secret: null, enabled: false, confirmed: false });
  const { code, challenge } = await twofa.issueEmailChallenge(acc.id, process.env.ADMIN_COOKIE_SECRET);
  await sendOtpEmail(acc.email, code);
  res.json({ method: 'email', challenge_token: challenge });
}));

// Enrollment: подтвердить код, включить 2FA, выдать recovery-коды
router.post('/2fa/enable', validate(twofaEnableSchema), asyncWrap(async (req, res) => {
  const { challenge_token, code } = req.validated;
  const ch = readChallenge(challenge_token);
  let accId = ch && ch.stage === 'enroll' ? ch.account_id : null;
  let acc = accId ? await accountsRepo.getById(accId) : null;
  if (!acc) return res.status(401).json({ error: 'Сессия входа истекла' });

  let ok = false;
  if (acc.twofa_method === 'totp') ok = twofa.verifyTotp(acc.twofa_secret, code);
  else {
    const r = await twofa.verifyEmailChallenge(challenge_token, code, process.env.ADMIN_COOKIE_SECRET);
    ok = r.ok && r.account_id === acc.id;
  }
  if (!ok) { await logEvent({ event: '2fa_fail', account_id: acc.id, req }); return res.status(401).json({ error: 'Неверный код' }); }

  await accountsRepo.setTwofa(acc.id, { method: acc.twofa_method, secret: acc.twofa_secret, enabled: true, confirmed: true });
  const { plain, hashes } = await twofa.generateRecoveryCodes();
  await accountsRepo.replaceRecoveryCodes(acc.id, hashes);
  await accountsRepo.registerLoginSuccess(acc.id);
  auth.issueSession(res, acc);
  await logEvent({ event: '2fa_enabled', account_id: acc.id, actor_email: acc.email, req });
  res.json({ role: acc.role, redirect: redirectFor(acc.role), recovery_codes: plain });
}));

// Выключить 2FA (под сессией; для teacher — опционально)
router.post('/2fa/disable', auth.requireAuth, asyncWrap(async (req, res) => {
  await accountsRepo.resetTwofa(req.account.account_id);
  await logEvent({ event: '2fa_disabled', account_id: req.account.account_id, req });
  res.json({ ok: true });
}));
```

- [ ] **Step 2: Smoke — модуль грузится**

Run: `node -e "require('./routes/auth');console.log('ok')"`
Expected: `ok`

- [ ] **Step 3: Ручная проверка happy-path (после Task 16 будет seed-аккаунт). Пока — синтаксис.**

Run: `npm test`
Expected: существующие тесты зелёные (auth/twofa/audit/accounts).

- [ ] **Step 4: Commit**

```bash
git add routes/auth.js
git commit -m "feat(auth): 2FA login branching + setup/enable/disable/email-send endpoints"
```

---

### Task 15: scripts/create-account.js — seed/CLI

**Files:**
- Create: `scripts/create-account.js`
- Modify: `package.json` (скрипт `account:create`)

- [ ] **Step 1: Реализовать скрипт**

```js
// scripts/create-account.js <email> <role> [teacher_id]
// Создаёт учётку, печатает сгенерированный токен-пароль (один раз).
require('dotenv').config();
const auth = require('../services/auth');
const accountsRepo = require('../services/repo/accounts');
const { pool } = require('../services/db');

async function main() {
  const [, , rawEmail, role, teacherId] = process.argv;
  const email = auth.normalizeEmail(rawEmail);
  if (!email || !['teacher', 'manager', 'admin'].includes(role)) {
    console.error('usage: node scripts/create-account.js <email> <teacher|manager|admin> [teacher_id]');
    process.exit(1);
  }
  if ((role === 'teacher') !== (teacherId != null)) {
    console.error('teacher требует teacher_id; manager/admin — без него');
    process.exit(1);
  }
  if (await accountsRepo.findByEmail(email)) { console.error('email уже есть'); process.exit(1); }

  const password = auth.generateTokenPassword();
  const acc = await accountsRepo.createAccount({
    email, password_hash: await auth.hashPassword(password), role,
    teacher_id: teacherId ? Number(teacherId) : null,
  });
  console.log(JSON.stringify({ id: acc.id, email: acc.email, role: acc.role, password }, null, 2));
  console.log('\n⚠️  Пароль показан один раз — сохраните его.');
  await pool.end();
}
main().catch((e) => { console.error(e); process.exit(1); });
```

- [ ] **Step 2: Добавить npm-скрипт**

В `package.json` `scripts`: `"account:create": "node scripts/create-account.js"`.

- [ ] **Step 3: Создать первого admin (ручной запуск)**

Run: `node scripts/create-account.js admin@kotokod.ru admin`
Expected: JSON с `password` (сохранить). В БД появилась учётка admin.

- [ ] **Step 4: Commit**

```bash
git add scripts/create-account.js package.json
git commit -m "feat(scripts): create-account CLI (seed first admin)"
```

---

### Task 16: Gating admin-роутера на единую сессию

**Files:**
- Modify: `routes/admin/index.js`
- Modify: `routes/admin/auth.js` (удалить старый login/logout по username)

- [ ] **Step 1: Удалить старый admin login/logout**

`routes/admin/auth.js` свести к пустому роутеру (вход теперь общий `/api/auth`):
```js
// routes/admin/auth.js — DEPRECATED: вход перенесён в /api/auth.
const express = require('express');
module.exports = express.Router();
```

- [ ] **Step 2: Заменить gating в routes/admin/index.js**

Заменить `const requireAdmin = require('../middleware/require-admin');` на:
```js
const { requireAuth, requireRole } = require('../../services/auth');
const requireAdmin = [requireAuth, requireRole('manager', 'admin')];
```
(Express принимает массив middleware в `router.use('/x', requireAdmin, handler)` — каждый элемент применится по порядку.) Остальные строки `router.use('/students', requireAdmin, ...)` не меняются.

- [ ] **Step 3: Smoke**

Run: `node -e "require('./routes/admin');console.log('ok')"`
Expected: `ok`

- [ ] **Step 4: Ручная проверка: без cookie admin-API даёт 401**

Run (сервер запущен `npm start`):
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/api/admin/teachers
```
Expected: `401`

- [ ] **Step 5: Ручная проверка: login → admin-API 200**

Run:
```bash
curl -s -c /tmp/cj.txt -X POST http://localhost:3000/api/auth/login -H 'Content-Type: application/json' -d '{"email":"admin@kotokod.ru","password":"<из Task 15>","role":"admin"}'
curl -s -b /tmp/cj.txt -o /dev/null -w "%{http_code}\n" http://localhost:3000/api/admin/teachers
```
Expected: первый — `{"role":"admin","redirect":"/admin"}` (если у admin ещё нет 2FA — а при requires2fa он попадёт в enrollment; для теста gating можно временно создать manager без обязательной 2FA или пройти enrollment). Второй — `200` после полноценного входа.

> Примечание: admin/manager по политике требуют 2FA-enrollment при первом входе. Для проверки чистого gating используйте teacher-аккаунт или пройдите enrollment через `/api/auth/2fa/*`.

- [ ] **Step 6: Commit**

```bash
git add routes/admin/index.js routes/admin/auth.js
git commit -m "refactor(admin): gate /api/admin via unified session (requireAuth+requireRole)"
```

---

### Task 17: Рефактор teacher-эндпоинтов — сессия вместо token-в-теле

**Files:**
- Modify: `routes/teacher.js`
- Modify: `server.js` (gating `/api` teacher)
- Modify: `shared/schemas.js` (убрать token из teacher-схем)
- Modify: `services/teacher-repo.js` (если требуется helper teacherById)

- [ ] **Step 1: Добавить helper «имя препода по account» в teacher-repo (если ещё нет)**

В `services/teacher-repo.js` добавить:
```js
async function teacherNameById(teacherId) {
  const { rows } = await pool.query('SELECT name FROM teachers WHERE id = $1', [teacherId]);
  return rows[0] ? rows[0].name : null;
}
```
(добавить `teacherNameById` в `module.exports`; `pool` уже импортируется в файле — проверить, иначе `const { pool } = require('./db')`.)

- [ ] **Step 2: Обновить схемы — убрать token**

В `shared/schemas.js`:
- `validateTokenSchema` — удалить (эндпоинт уходит).
- `getDataSchema` — больше не нужен (token был единственным полем); удалить его использование.
- `submitLessonSchema` — удалить поле `token` из объекта (оставить group/date/recordUrl/lessonType/isSubstitution/originalTeacher/students).
Обновить `module.exports` соответственно.

- [ ] **Step 3: Переписать routes/teacher.js на сессию**

Ключевые правки (показаны изменённые места):
```js
const auth = require('../services/auth');
const accountsRepo = require('../services/repo/accounts');

// Все teacher-роуты под сессией с ролью teacher (gating вешается в server.js).
// Имя препода берём из аккаунта:
async function currentTeacher(req) {
  return require('../services/teacher-repo').teacherNameById(req.account.account_id
    ? (await accountsRepo.getById(req.account.account_id)).teacher_id
    : null);
}
```
Удалить `POST /validateToken`. В `getData`/`getAllData`/`submitLesson`/`report`/`schedule` заменить получение `teacher` из токена на:
```js
const teacher = await currentTeacher(req);
if (!teacher) return res.status(403).json({ error: 'Аккаунт не привязан к преподавателю' });
```
В `submitLesson` убрать `token` из `req.validated`; `submitted_by_token` писать как `acct:${req.account.account_id}`.
Снять `validate(getDataSchema)` с `getData`/`getAllData` (тела больше нет) — оставить `asyncWrap`.

> Полный детальный diff teacher.js — см. спеку раздел 5; каждый из 5 хендлеров меняет только строку получения `teacher` и (для submitLesson) `submitted_by_token`.

- [ ] **Step 4: Gating /api в server.js**

В `server.js` заменить `app.use('/api', teacherRouter);` на:
```js
const { requireAuth, requireRole } = require('./services/auth');
app.use('/api', requireAuth, requireRole('teacher'), teacherRouter);
```
⚠️ Смонтировать `/api/auth` (Task 13) ДО этой строки, иначе requireAuth перехватит логин. Порядок: `app.use('/api/auth', authRouter);` затем `app.use('/api', requireAuth, requireRole('teacher'), teacherRouter);`.

- [ ] **Step 5: Обновить teacher-repo тест (убрать token-flow)**

Запустить и починить:
Run: `node --test services/teacher-repo.test.js`
Expected: PASS (там, где тест дергал token-flow — заменить на прямой вызов с teacher_id).

- [ ] **Step 6: Прогнать все тесты**

Run: `npm test`
Expected: всё зелёное.

- [ ] **Step 7: Commit**

```bash
git add routes/teacher.js server.js shared/schemas.js services/teacher-repo.js services/teacher-repo.test.js
git commit -m "refactor(teacher): session-based auth, drop token-in-body"
```

---

### Task 18: routes/admin/accounts.js + audit.js + монтирование

**Files:**
- Create: `routes/admin/accounts.js`
- Create: `routes/admin/audit.js`
- Modify: `routes/admin/index.js`
- Create: `services/repo/audit.js` (чтение журнала)

- [ ] **Step 1: services/repo/audit.js (paginated чтение)**

```js
const { paginate, F } = require('../pagination');
const AUDIT_PAGINATION = {
  sortable: { occurred_at: 'l.occurred_at', event: 'l.event' },
  defaultSortBy: 'occurred_at', defaultSortDir: 'desc',
  from: 'FROM security_audit_log l LEFT JOIN accounts a ON a.id = l.account_id',
  selectColumns: 'l.*, a.email AS account_email',
  secondarySort: 'l.id DESC',
  filters: { event: F.exact('l.event'), account_id: F.num('l.account_id'), actor_email: F.like('l.actor_email') },
};
async function listAudit(request) { return paginate(AUDIT_PAGINATION, request); }
module.exports = { listAudit };
```

- [ ] **Step 2: routes/admin/accounts.js**

```js
const express = require('express');
const accountsRepo = require('../../services/repo/accounts');
const auth = require('../../services/auth');
const { logEvent } = require('../../services/audit');
const { parsePaginationRequest } = require('../../services/pagination');
const validate = require('../middleware/validate');
const asyncWrap = require('../middleware/async-wrap');
const { requireRole } = require('../../services/auth');
const { createAccountSchema, updateAccountSchema } = require('../../shared/schemas');

const router = express.Router();
router.use(requireRole('admin')); // управление доступами — только admin

router.get('/', asyncWrap(async (req, res) => {
  res.json(await accountsRepo.listAccounts(parsePaginationRequest(req.query, { sortBy: 'email', sortDir: 'asc' })));
}));

router.get('/:id', asyncWrap(async (req, res) => {
  const a = await accountsRepo.getByIdWithTeacher(Number(req.params.id));
  if (!a) return res.status(404).json({ error: 'Not found' });
  res.json({ ...a, password_hash: undefined, twofa_secret: undefined });
}));

router.post('/', validate(createAccountSchema), asyncWrap(async (req, res) => {
  const { email, role, teacher_id } = req.validated;
  if (await accountsRepo.findByEmail(email)) return res.status(409).json({ error: 'Email уже используется' });
  const password = auth.generateTokenPassword();
  const acc = await accountsRepo.createAccount({ email, role, teacher_id, password_hash: await auth.hashPassword(password) });
  await logEvent({ event: 'account_created', account_id: req.account.account_id, target_id: acc.id, meta: { email, role }, req });
  res.status(201).json({ id: acc.id, email: acc.email, role: acc.role, teacher_id: acc.teacher_id, password });
}));

router.patch('/:id', validate(updateAccountSchema), asyncWrap(async (req, res) => {
  const u = await accountsRepo.updateAccount(Number(req.params.id), req.validated);
  if (!u) return res.status(404).json({ error: 'Not found' });
  res.json({ ...u, password_hash: undefined, twofa_secret: undefined });
}));

router.post('/:id/reset-password', asyncWrap(async (req, res) => {
  const acc = await accountsRepo.getById(Number(req.params.id));
  if (!acc) return res.status(404).json({ error: 'Not found' });
  const password = auth.generateTokenPassword();
  await accountsRepo.setPassword(acc.id, await auth.hashPassword(password));
  await logEvent({ event: 'password_reset', account_id: req.account.account_id, target_id: acc.id, req });
  res.json({ password });
}));

router.post('/:id/reset-2fa', asyncWrap(async (req, res) => {
  const acc = await accountsRepo.resetTwofa(Number(req.params.id));
  if (!acc) return res.status(404).json({ error: 'Not found' });
  await logEvent({ event: '2fa_reset', account_id: req.account.account_id, target_id: acc.id, req });
  res.json({ ok: true });
}));

router.delete('/:id', asyncWrap(async (req, res) => {
  const ok = await accountsRepo.softDelete(Number(req.params.id));
  if (!ok) return res.status(404).json({ error: 'Not found' });
  await logEvent({ event: 'account_deactivated', account_id: req.account.account_id, target_id: Number(req.params.id), req });
  res.status(204).end();
}));

module.exports = router;
```

- [ ] **Step 3: routes/admin/audit.js**

```js
const express = require('express');
const auditRepo = require('../../services/repo/audit');
const { parsePaginationRequest } = require('../../services/pagination');
const asyncWrap = require('../middleware/async-wrap');
const { requireRole } = require('../../services/auth');

const router = express.Router();
router.use(requireRole('admin'));

router.get('/', asyncWrap(async (req, res) => {
  res.json(await auditRepo.listAudit(parsePaginationRequest(req.query, { sortBy: 'occurred_at', sortDir: 'desc' })));
}));

module.exports = router;
```

- [ ] **Step 4: Смонтировать в routes/admin/index.js**

```js
const accountsRouter = require('./accounts');
const auditRouter    = require('./audit');
// ...
router.use('/accounts', requireAdmin, accountsRouter);
router.use('/audit-log', requireAdmin, auditRouter);
```

- [ ] **Step 5: Smoke + тесты**

Run: `node -e "require('./routes/admin');console.log('ok')" && npm test`
Expected: `ok` + зелёные тесты.

- [ ] **Step 6: Commit**

```bash
git add routes/admin/accounts.js routes/admin/audit.js routes/admin/index.js services/repo/audit.js
git commit -m "feat(admin): accounts CRUD + audit-log endpoints (admin-only)"
```

---

### Task 19: Интеграционная проверка всего бэка

- [ ] **Step 1: Полный прогон тестов**

Run: `npm test`
Expected: все наборы зелёные (auth, twofa, audit, accounts repo, admin-auth shim, teacher-repo).

- [ ] **Step 2: Ручной E2E через curl (admin с 2FA-enrollment TOTP)**

Сценарий (сервер `npm start`):
1. `POST /api/auth/login {email,password,role:'admin'}` → `{ twofa_enrollment_required, challenge_token }`.
2. `POST /api/auth/2fa/setup {challenge_token, method:'totp'}` → `{ secret, qr }`.
3. Сгенерировать код: `node -e "require('dotenv').config();const {authenticator}=require('otplib');console.log(authenticator.generate('<secret>'))"`.
4. `POST /api/auth/2fa/enable {challenge_token, code}` → cookie + `{ recovery_codes }`.
5. С cookie: `GET /api/auth/me` → роль admin; `GET /api/admin/accounts` → 200.

Expected: каждый шаг отвечает как описано; в `security_audit_log` появились `login_success`/`2fa_enabled`.

- [ ] **Step 3: Проверить audit-log**

Run: `psql -U journal -h localhost -d journal -c "SELECT event, account_id, actor_email FROM security_audit_log ORDER BY id DESC LIMIT 5"`
Expected: события входа/2FA без секретов.

- [ ] **Step 4: Commit (чекпойнт окончания Плана 1)**

```bash
git add -A
git commit -m "test: backend auth foundation E2E checkpoint (plan 1 complete)"
```

---

## Self-review (выполнено автором плана)

- **Покрытие спеки:** миграции 013/014/015 ✓; auth-ядро+hardening (Task 5–6) ✓; admin-auth shim (7) ✓; audit (8) ✓; twofa TOTP+email (9) ✓; mailer (10) ✓; accounts repo (11) ✓; схемы (12) ✓; routes/auth login+2FA+me (13–14) ✓; create-account (15) ✓; admin gating (16) ✓; teacher refactor (17) ✓; accounts/audit admin-роуты (18) ✓.
- **Вне Плана 1 (→ План 2/3):** страница `/login`, server.js static-роутинг, teacher SPA `/teacher`, admin SPA AuthProvider/AuthGate, UI учёток/audit/согласия.
- **Согласованность имён:** `issueSession/clearSession/requireAuth/requireRole` (auth.js) используются в routes; `findByEmail/getById/getByIdWithTeacher/createAccount/setTwofa/resetTwofa/registerLogin*` (accounts.js) совпадают между задачами; `issueEmailChallenge/verifyEmailChallenge/verifyTotp` (twofa.js) совпадают.
- **Известные ручные моменты:** SMTP Beget (Task 10) — реальная отправка зависит от настроенного ящика; проверка gating (Task 16) учитывает обязательный 2FA-enrollment у admin/manager.
