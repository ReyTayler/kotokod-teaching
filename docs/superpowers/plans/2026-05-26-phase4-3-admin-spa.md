# Phase 4.3 — Admin SPA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Поднять admin SPA на `/admin` — login → sidebar с 5 разделами (Students, Groups, Teachers, Tokens, Directions) → полный CRUD через `/api/admin/*` (Phase 4.2 backend).

**Architecture:** Vanilla HTML/CSS/JS, без bundler'ов. `public/admin.html` (DOM) + `public/admin-app.js` (state, auth, render, fetch). Стили — продолжение существующего `public/styles.css` (OKLCH-токены уже есть после Phase 4.1). State — module-scoped object; разделы рендерятся лениво (по клику в sidebar). Серверные ошибки → тосты в правом верхнем углу.

**Tech Stack:** Vanilla JS (no React/Vue/etc), fetch API, HttpOnly cookie auth (через `/api/admin/login`).

**Reference spec:** `docs/superpowers/specs/2026-05-26-phase4-3-admin-spa-design.md` + базовый `docs/superpowers/specs/2026-05-25-frontend-refresh-admin-ui-design.md`.

**Project state:** проект не под git → шаги `commit` отсутствуют. Backend (`/api/admin/*`) уже работает (49/49 тестов).

---

## File structure

| Путь | Создаётся / меняется | Ответственность |
|------|----------------------|-----------------|
| `public/admin.html` | создаётся | DOM-скелет: `<div id="app">` контейнер + `<div id="modal-host">` + `<div id="toast-host">`. Подключает шрифты, `styles.css`, `admin-app.js`. |
| `public/admin-app.js` | создаётся | Всё JS: state, auth flow, sidebar nav, рендеры 5 разделов, модалка, тосты, API-обёртка. |
| `public/styles.css` | дополняется | Новые классы: `.admin-shell`, `.admin-sidebar`, `.admin-main`, `.admin-login`, `.modal-backdrop`, `.modal`, `.toast`, `.toast--error`, `.toast--ok`, `.data-table`, `.row-actions`. Существующие токены не трогаем. |
| `server.js` | модифицируется | Одна новая строка: `app.get('/admin', ...)` до `express.static`. |
| `docs/admin-smoke-tests.md` | дополняется | Click-сценарий: login → CRUD по 5 разделам → logout. |

---

## Testing strategy

Frontend без unit-фреймворка. Проверка — `npm start` + браузер. Каждая задача завершается **manual verify**: открыть `http://localhost:3000/admin`, выполнить конкретный сценарий, убедиться в ожидаемом результате. Серверные тесты (49/49 из Phase 4.2) должны оставаться зелёными — гоняем `npm test` после правок `server.js`.

---

## Tasks

### Task 1: `/admin` route + DOM skeleton

**Files:**
- Modify: `server.js` (одна строка перед `app.use(express.static('public'))`)
- Create: `public/admin.html`

- [ ] **Step 1: Добавить route в `server.js`**

Найди строку `app.use(express.static('public'));` и вставь перед ней:

```js
app.get('/admin', (_req, res) => res.sendFile(require('path').join(__dirname, 'public', 'admin.html')));
```

(`path` уже импортирован в верхушке файла.)

- [ ] **Step 2: Создать `public/admin.html`**

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0f1117">
  <title>Журнал · Admin</title>
  <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css">
</head>
<body class="admin-body">
  <div id="app"></div>
  <div id="modal-host"></div>
  <div id="toast-host"></div>
  <script defer src="/admin-app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Создать пустой `public/admin-app.js`**

```js
console.log('admin-app loaded');
```

- [ ] **Step 4: Manual verify**

```powershell
npm start
```

Открыть `http://localhost:3000/admin` → загружается белый/тёмный фон (фон уже задан через `styles.css` body), DevTools Console показывает `admin-app loaded`. Никаких 404.

- [ ] **Step 5: Прогнать тесты — schema/server не сломаны**

```powershell
npm test
```

Expected: `tests 49 pass 49 fail 0`.

---

### Task 2: CSS — admin layout primitives

**Files:**
- Modify: `public/styles.css` (append в конец)

- [ ] **Step 1: Дописать в конец `public/styles.css`**

```css
/* ─── ADMIN SPA ────────────────────────────────────────── */

.admin-body {
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
}

/* Login card (центрированная) */
.admin-login {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-4);
}
.admin-login__card {
  width: 100%;
  max-width: 360px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-2);
  padding: var(--sp-6, 24px);
}
.admin-login__title {
  font-size: 22px;
  font-weight: 600;
  margin: 0 0 var(--sp-4) 0;
}
.admin-login__row { margin-bottom: var(--sp-3); }
.admin-login__row label {
  display: block;
  font-size: 13px;
  color: var(--text-2);
  margin-bottom: var(--sp-1);
}
.admin-login__row input {
  width: 100%;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  color: var(--text);
  padding: 10px 12px;
  font: inherit;
}
.admin-login__row input:focus {
  outline: none;
  border-color: var(--accent);
}
.admin-login__submit {
  width: 100%;
  margin-top: var(--sp-3);
  padding: 12px;
  background: var(--accent);
  color: #0b0d13;
  border: 0;
  border-radius: var(--r-md);
  font-weight: 600;
  cursor: pointer;
}
.admin-login__submit:hover { background: var(--accent-hi); }

/* Shell: sidebar + main */
.admin-shell {
  display: grid;
  grid-template-columns: 220px 1fr;
  min-height: 100vh;
}
.admin-sidebar {
  background: var(--surface-1);
  border-right: 1px solid var(--border);
  padding: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.admin-sidebar__brand {
  font-weight: 700;
  font-size: 15px;
  letter-spacing: -0.01em;
  margin-bottom: var(--sp-3);
}
.admin-sidebar__btn {
  text-align: left;
  background: transparent;
  border: 0;
  color: var(--text-2);
  padding: 10px 12px;
  border-radius: var(--r-md);
  font: inherit;
  cursor: pointer;
}
.admin-sidebar__btn:hover { background: var(--surface-2); color: var(--text); }
.admin-sidebar__btn.is-active { background: var(--accent-soft); color: var(--text); }
.admin-sidebar__spacer { flex: 1; }
.admin-sidebar__logout {
  background: transparent; border: 1px solid var(--border);
  color: var(--text-2); padding: 8px 12px;
  border-radius: var(--r-md); cursor: pointer; font: inherit;
}

.admin-main { padding: var(--sp-5, 20px) var(--sp-5, 20px); }
.admin-main__head {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--sp-3); margin-bottom: var(--sp-4);
}
.admin-main__title { font-size: 22px; font-weight: 600; margin: 0; }
.admin-main__search {
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: var(--r-md); padding: 8px 12px;
  color: var(--text); font: inherit; min-width: 220px;
}
.admin-main__add {
  background: var(--accent); color: #0b0d13; border: 0;
  padding: 8px 14px; border-radius: var(--r-md); cursor: pointer; font: inherit; font-weight: 600;
}

/* Data table */
.data-table { width: 100%; border-collapse: collapse; }
.data-table th, .data-table td {
  text-align: left; padding: 10px 12px;
  border-bottom: 1px solid var(--border);
}
.data-table th {
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--text-3); font-weight: 500;
  position: sticky; top: 0; background: var(--bg);
}
.data-table tbody tr { cursor: pointer; }
.data-table tbody tr:hover { background: var(--surface-2); }
.data-table .empty { text-align: center; color: var(--text-3); padding: 32px; }

/* Modal */
.modal-backdrop {
  position: fixed; inset: 0;
  background: rgb(0 0 0 / 0.6);
  display: flex; align-items: center; justify-content: center;
  z-index: 100; padding: var(--sp-4);
}
.modal {
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: var(--r-lg); box-shadow: var(--shadow-2);
  width: 100%; max-width: 560px; max-height: 90vh; overflow-y: auto;
}
.modal__head {
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: center;
}
.modal__title { font-size: 18px; font-weight: 600; margin: 0; }
.modal__close {
  background: transparent; border: 0; color: var(--text-2);
  font-size: 22px; cursor: pointer; line-height: 1;
}
.modal__body { padding: var(--sp-4); display: flex; flex-direction: column; gap: var(--sp-3); }
.modal__foot {
  padding: var(--sp-3) var(--sp-4);
  border-top: 1px solid var(--border);
  display: flex; justify-content: space-between; gap: var(--sp-2);
}
.modal__field label {
  display: block; font-size: 13px; color: var(--text-2); margin-bottom: var(--sp-1);
}
.modal__field input, .modal__field select, .modal__field textarea {
  width: 100%; background: var(--surface-2); border: 1px solid var(--border);
  border-radius: var(--r-md); color: var(--text); padding: 8px 10px; font: inherit;
}
.modal__field input:focus, .modal__field select:focus { outline: none; border-color: var(--accent); }
.btn-primary {
  background: var(--accent); color: #0b0d13; border: 0;
  padding: 8px 16px; border-radius: var(--r-md); font: inherit; font-weight: 600; cursor: pointer;
}
.btn-secondary {
  background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
  padding: 8px 16px; border-radius: var(--r-md); font: inherit; cursor: pointer;
}
.btn-danger {
  background: transparent; color: var(--err); border: 1px solid var(--err);
  padding: 8px 16px; border-radius: var(--r-md); font: inherit; cursor: pointer;
}
.btn-danger.is-confirming { background: var(--err); color: white; }

/* Toast */
#toast-host {
  position: fixed; top: 16px; right: 16px;
  display: flex; flex-direction: column; gap: 8px;
  z-index: 200; pointer-events: none;
}
.toast {
  background: var(--surface-2); border: 1px solid var(--border);
  border-left: 4px solid var(--err);
  border-radius: var(--r-md); padding: 10px 14px;
  box-shadow: var(--shadow-2);
  font-size: 14px; color: var(--text);
  min-width: 240px; max-width: 360px;
  pointer-events: auto;
  animation: toast-in var(--dur-base) var(--ease-out);
}
.toast--ok { border-left-color: var(--ok); }
@keyframes toast-in {
  from { transform: translateX(20px); opacity: 0; }
  to   { transform: translateX(0);    opacity: 1; }
}

/* Slot editor (groups) */
.slot-row { display: grid; grid-template-columns: 1fr 120px 32px; gap: 8px; align-items: center; }
.slot-row__remove {
  background: transparent; border: 1px solid var(--border);
  color: var(--text-2); cursor: pointer; border-radius: var(--r-sm); height: 32px;
}
.slot-add {
  background: transparent; border: 1px dashed var(--border);
  color: var(--text-2); padding: 8px; border-radius: var(--r-md); cursor: pointer;
}

/* Memberships subtable inside Student modal */
.memberships { border-top: 1px solid var(--border); padding-top: var(--sp-3); margin-top: var(--sp-2); }
.memberships__title { font-size: 13px; color: var(--text-2); margin: 0 0 var(--sp-2); }
.memberships__row { display: grid; grid-template-columns: 1fr 80px 80px 32px; gap: 8px; align-items: center; padding: 6px 0; }
.memberships__row input { padding: 6px 8px; }
.memberships__add { display: grid; grid-template-columns: 1fr auto; gap: 8px; margin-top: var(--sp-2); }
```

- [ ] **Step 2: Manual verify**

После перезапуска `npm start` открыть `/admin` — фон тёмный, шрифт Manrope. Никаких видимых элементов (DOM пуст), это ожидается.

---

### Task 3: API wrapper + toast + auth state machine

**Files:**
- Modify: `public/admin-app.js`

- [ ] **Step 1: Заменить содержимое `public/admin-app.js`**

```js
// ============================================================
// admin-app.js — single-file admin SPA logic
// ============================================================

const SECTIONS = [
  { key: 'students',   label: 'Ученики',         endpoint: '/api/admin/students' },
  { key: 'groups',     label: 'Группы',          endpoint: '/api/admin/groups' },
  { key: 'teachers',   label: 'Преподаватели',   endpoint: '/api/admin/teachers' },
  { key: 'tokens',     label: 'Токены',          endpoint: '/api/admin/tokens' },
  { key: 'directions', label: 'Направления',     endpoint: '/api/admin/directions' },
];

const state = {
  authenticated: false,
  activeSection: 'students',
  cache: { students: null, groups: null, teachers: null, tokens: null, directions: null },
};

// ─── API ─────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, credentials: 'same-origin', headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  const ct = res.headers.get('Content-Type') || '';
  const data = ct.includes('application/json') ? await res.json() : null;
  if (!res.ok) {
    const err = new Error((data && data.error) || `HTTP ${res.status}`);
    err.status = res.status;
    err.body = data;
    throw err;
  }
  return data;
}

function showApiError(err) {
  if (err.status === 401) {
    toast('Сессия истекла', 'error');
    setTimeout(() => location.reload(), 1500);
    return;
  }
  const map = {
    400: err.body && err.body.error ? err.body.error : 'Заполните обязательные поля',
    404: 'Запись не найдена',
    409: err.body && err.body.error ? err.body.error : 'Уже существует',
  };
  const msg = map[err.status] || (err.status >= 500 ? 'Серверная ошибка' : err.message);
  toast(msg, 'error');
  if (err.status >= 500) console.error(err);
}

// ─── Toast ───────────────────────────────────────────────
function toast(msg, kind = 'error') {
  const host = document.getElementById('toast-host');
  const el = document.createElement('div');
  el.className = `toast toast--${kind}`;
  el.textContent = msg;
  host.prepend(el);
  while (host.children.length > 3) host.lastElementChild.remove();
  let timer = setTimeout(remove, 4000);
  el.addEventListener('mouseenter', () => clearTimeout(timer));
  el.addEventListener('mouseleave', () => { timer = setTimeout(remove, 2000); });
  function remove() { if (el.parentNode) el.remove(); }
}

// ─── Auth ────────────────────────────────────────────────
async function checkAuth() {
  try {
    await api('GET', '/api/admin/teachers');
    state.authenticated = true;
  } catch (e) {
    if (e.status === 401) state.authenticated = false;
    else throw e;
  }
}

function renderLogin() {
  const app = document.getElementById('app');
  app.innerHTML = `
    <div class="admin-login">
      <form class="admin-login__card" id="login-form">
        <h1 class="admin-login__title">Admin · Журнал</h1>
        <div class="admin-login__row">
          <label for="login-username">Логин</label>
          <input id="login-username" type="text" autocomplete="username" required>
        </div>
        <div class="admin-login__row">
          <label for="login-password">Пароль</label>
          <input id="login-password" type="password" autocomplete="current-password" required>
        </div>
        <button class="admin-login__submit" type="submit">Войти</button>
      </form>
    </div>
  `;
  document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    try {
      await api('POST', '/api/admin/login', { username, password });
      await bootstrap();
    } catch (err) { showApiError(err); }
  });
}

async function handleLogout() {
  try { await api('POST', '/api/admin/logout'); } catch (_) {}
  location.reload();
}

// ─── Shell ───────────────────────────────────────────────
function renderShell() {
  const app = document.getElementById('app');
  const navBtns = SECTIONS.map((s) =>
    `<button class="admin-sidebar__btn${s.key === state.activeSection ? ' is-active' : ''}" data-section="${s.key}">${s.label}</button>`
  ).join('');
  app.innerHTML = `
    <div class="admin-shell">
      <aside class="admin-sidebar">
        <div class="admin-sidebar__brand">Журнал · Admin</div>
        ${navBtns}
        <div class="admin-sidebar__spacer"></div>
        <button class="admin-sidebar__logout" id="logout-btn">Выход</button>
      </aside>
      <main class="admin-main" id="admin-main"></main>
    </div>
  `;
  app.querySelectorAll('[data-section]').forEach((btn) =>
    btn.addEventListener('click', () => setActiveSection(btn.dataset.section))
  );
  document.getElementById('logout-btn').addEventListener('click', handleLogout);
}

async function setActiveSection(key) {
  state.activeSection = key;
  document.querySelectorAll('.admin-sidebar__btn').forEach((b) =>
    b.classList.toggle('is-active', b.dataset.section === key)
  );
  await renderSection();
}

async function renderSection() {
  const main = document.getElementById('admin-main');
  const section = SECTIONS.find((s) => s.key === state.activeSection);
  if (!section) return;
  if (state.cache[section.key] === null) {
    main.innerHTML = `<div class="data-table__empty">Загружаем...</div>`;
    try {
      state.cache[section.key] = await api('GET', section.endpoint);
    } catch (err) { showApiError(err); return; }
  }
  const renderer = SECTION_RENDERERS[section.key];
  if (renderer) renderer(main, state.cache[section.key]);
  else main.innerHTML = `<div>Раздел ${section.label} (TODO)</div>`;
}

const SECTION_RENDERERS = {
  // заполняется в следующих задачах
};

// ─── Bootstrap ───────────────────────────────────────────
async function bootstrap() {
  await checkAuth();
  if (!state.authenticated) {
    renderLogin();
    return;
  }
  renderShell();
  await renderSection();
}

document.addEventListener('DOMContentLoaded', () => {
  bootstrap().catch((err) => {
    console.error(err);
    toast('Не удалось загрузить admin: ' + err.message, 'error');
  });
});
```

- [ ] **Step 2: Manual verify — login flow**

1. `npm start` → открыть `/admin` → видна центрированная login-карточка «Admin · Журнал».
2. Ввести неправильный логин/пароль → красный тост «Invalid credentials» (текст из `body.error`).
3. Ввести правильные → перерисовка в shell с sidebar (5 пунктов) и пустой main-областью (или сообщением «Раздел ... (TODO)» для пустых разделов; для `students` будет тоже TODO пока renderer не добавлен).
4. Без cookie сразу перейти на `/admin` после logout → снова login-карточка.

Если на 5xx сети `toast('Не удалось загрузить admin: ...')` всплывает — это ожидаемое поведение.

---

### Task 4: Teachers section (template renderer)

**Files:**
- Modify: `public/admin-app.js` (добавить renderer + modal helper)

- [ ] **Step 1: Добавить modal helper и helpers для форм в `admin-app.js`**

В конец файла (перед `document.addEventListener`) вставить:

```js
// ─── Modal ───────────────────────────────────────────────
function openModal({ title, fields, initial = {}, onSubmit, onDelete }) {
  const host = document.getElementById('modal-host');
  const formId = 'modal-form-' + Date.now();
  const fieldsHtml = fields.map((f) => renderField(f, initial[f.name])).join('');
  const footer = onDelete
    ? `<button type="button" class="btn-danger" id="modal-delete">Удалить</button>
       <span style="display:flex; gap:8px;">
         <button type="button" class="btn-secondary" id="modal-cancel">Отмена</button>
         <button type="submit" form="${formId}" class="btn-primary">Сохранить</button>
       </span>`
    : `<span></span>
       <span style="display:flex; gap:8px;">
         <button type="button" class="btn-secondary" id="modal-cancel">Отмена</button>
         <button type="submit" form="${formId}" class="btn-primary">Сохранить</button>
       </span>`;
  host.innerHTML = `
    <div class="modal-backdrop">
      <div class="modal">
        <div class="modal__head">
          <h3 class="modal__title">${escapeHtml(title)}</h3>
          <button type="button" class="modal__close" id="modal-close">×</button>
        </div>
        <form class="modal__body" id="${formId}">${fieldsHtml}</form>
        <div class="modal__foot">${footer}</div>
      </div>
    </div>
  `;
  const close = () => { host.innerHTML = ''; };
  host.querySelector('#modal-close').addEventListener('click', close);
  host.querySelector('#modal-cancel').addEventListener('click', close);
  host.querySelector('.modal-backdrop').addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-backdrop')) close();
  });
  document.getElementById(formId).addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = collectFormData(e.target, fields);
    try {
      await onSubmit(data);
      close();
    } catch (err) { showApiError(err); }
  });
  if (onDelete) {
    const btn = host.querySelector('#modal-delete');
    btn.addEventListener('click', async () => {
      if (!btn.classList.contains('is-confirming')) {
        btn.classList.add('is-confirming');
        btn.textContent = 'Точно удалить?';
        return;
      }
      try { await onDelete(); close(); }
      catch (err) { showApiError(err); }
    });
  }
}

function renderField(f, value) {
  const v = value == null ? '' : value;
  if (f.type === 'select') {
    const opts = f.options.map((o) =>
      `<option value="${escapeHtml(o.value)}"${String(o.value) === String(v) ? ' selected' : ''}>${escapeHtml(o.label)}</option>`
    ).join('');
    return `<div class="modal__field"><label>${escapeHtml(f.label)}</label><select name="${f.name}"${f.required ? ' required' : ''}>${opts}</select></div>`;
  }
  if (f.type === 'checkbox') {
    const checked = v ? ' checked' : '';
    return `<div class="modal__field"><label><input type="checkbox" name="${f.name}"${checked}> ${escapeHtml(f.label)}</label></div>`;
  }
  const type = f.type || 'text';
  return `<div class="modal__field"><label>${escapeHtml(f.label)}</label>
    <input type="${type}" name="${f.name}" value="${escapeHtml(String(v))}"${f.required ? ' required' : ''}${f.placeholder ? ` placeholder="${escapeHtml(f.placeholder)}"` : ''}></div>`;
}

function collectFormData(form, fields) {
  const out = {};
  for (const f of fields) {
    const el = form.elements[f.name];
    if (!el) continue;
    if (f.type === 'checkbox') out[f.name] = el.checked;
    else if (f.type === 'number') out[f.name] = el.value === '' ? null : Number(el.value);
    else out[f.name] = el.value;
  }
  return out;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

// ─── Table renderer (общий) ─────────────────────────────
function renderTable({ host, columns, rows, search, onRowClick, onAddNew, title }) {
  const filter = search ? (search.value || '').toLowerCase() : '';
  const filtered = filter ? rows.filter((r) => columns.some((c) => String(r[c.key] ?? '').toLowerCase().includes(filter))) : rows;
  const headHtml = columns.map((c) => `<th>${escapeHtml(c.label)}</th>`).join('');
  const bodyHtml = filtered.length
    ? filtered.map((r, i) =>
        `<tr data-idx="${i}">${columns.map((c) => `<td>${escapeHtml(c.format ? c.format(r) : String(r[c.key] ?? ''))}</td>`).join('')}</tr>`
      ).join('')
    : `<tr><td class="empty" colspan="${columns.length}">Пусто</td></tr>`;
  host.innerHTML = `
    <div class="admin-main__head">
      <h2 class="admin-main__title">${escapeHtml(title)}</h2>
      <input class="admin-main__search" id="section-search" placeholder="Поиск..." value="${escapeHtml(filter)}">
      <button class="admin-main__add" id="section-add">+ Новый</button>
    </div>
    <table class="data-table">
      <thead><tr>${headHtml}</tr></thead>
      <tbody>${bodyHtml}</tbody>
    </table>
  `;
  host.querySelector('#section-search').addEventListener('input', (e) => {
    search.value = e.target.value;
    renderTable({ host, columns, rows, search, onRowClick, onAddNew, title });
  });
  host.querySelector('#section-add').addEventListener('click', onAddNew);
  host.querySelectorAll('tbody tr[data-idx]').forEach((tr) => {
    tr.addEventListener('click', () => onRowClick(filtered[Number(tr.dataset.idx)]));
  });
}

// per-section search state (сохраняется между перерисовками)
const SECTION_SEARCH = { students: { value: '' }, groups: { value: '' }, teachers: { value: '' }, tokens: { value: '' }, directions: { value: '' } };
```

- [ ] **Step 2: Зарегистрировать renderer для Teachers**

В объект `SECTION_RENDERERS` добавить ключ `teachers`:

```js
SECTION_RENDERERS.teachers = function renderTeachers(host, rows) {
  renderTable({
    host, rows, title: 'Преподаватели',
    search: SECTION_SEARCH.teachers,
    columns: [
      { key: 'name',  label: 'Имя' },
      { key: 'email', label: 'Email' },
      { key: 'phone', label: 'Телефон' },
      { key: 'active', label: 'Статус', format: (r) => r.active ? 'активен' : 'архив' },
    ],
    onAddNew: () => openTeacherModal(null),
    onRowClick: (row) => openTeacherModal(row),
  });
};

function openTeacherModal(row) {
  const isNew = !row;
  openModal({
    title: isNew ? 'Новый преподаватель' : `Преподаватель · ${row.name}`,
    fields: [
      { name: 'name',  label: 'Имя',     required: true },
      { name: 'email', label: 'Email' },
      { name: 'phone', label: 'Телефон' },
    ],
    initial: row || {},
    onSubmit: async (data) => {
      if (isNew) {
        const created = await api('POST', '/api/admin/teachers', data);
        state.cache.teachers.push(created);
      } else {
        const updated = await api('PATCH', `/api/admin/teachers/${row.id}`, data);
        Object.assign(row, updated);
      }
      await renderSection();
      toast(isNew ? 'Создано' : 'Сохранено', 'ok');
    },
    onDelete: isNew ? null : async () => {
      await api('DELETE', `/api/admin/teachers/${row.id}`);
      const i = state.cache.teachers.findIndex((t) => t.id === row.id);
      if (i >= 0) state.cache.teachers[i].active = false;
      await renderSection();
      toast('Архивировано', 'ok');
    },
  });
}
```

- [ ] **Step 3: Manual verify**

1. Login → клик «Преподаватели» в sidebar → видна таблица со списком (имена из БД).
2. Клик «+ Новый» → модалка → ввести имя «TEST_T1» → Сохранить → строка появилась в таблице, тост «Создано».
3. Клик по строке «TEST_T1» → модалка с прелейфилом → изменить телефон на `+79991234567` → Сохранить → значение обновилось.
4. Клик по «TEST_T1» снова → клик «Удалить» (надпись «Точно удалить?») → клик ещё раз → строка пропала из таблицы (active=false, фильтр по умолчанию скрывает), тост «Архивировано».
5. Поиск: ввести часть имени → таблица отфильтровалась.
6. Поле «Email» оставить пустым при создании → сохраняется без ошибки.

Чистка: `PGPASSWORD=journal_dev_password psql -U journal -h localhost -d journal -c "DELETE FROM teachers WHERE name LIKE 'TEST_%';"` (если нужно).

---

### Task 5: Directions section

**Files:**
- Modify: `public/admin-app.js`

- [ ] **Step 1: Добавить renderer**

```js
SECTION_RENDERERS.directions = function renderDirections(host, rows) {
  renderTable({
    host, rows, title: 'Направления',
    search: SECTION_SEARCH.directions,
    columns: [
      { key: 'name',          label: 'Название' },
      { key: 'sheet_name',    label: 'Лист (sheet)' },
      { key: 'is_individual', label: 'Индив.', format: (r) => r.is_individual ? 'да' : 'нет' },
      { key: 'active',        label: 'Статус', format: (r) => r.active ? 'активен' : 'архив' },
    ],
    onAddNew: () => openDirectionModal(null),
    onRowClick: (row) => openDirectionModal(row),
  });
};

function openDirectionModal(row) {
  const isNew = !row;
  openModal({
    title: isNew ? 'Новое направление' : `Направление · ${row.name}`,
    fields: [
      { name: 'name',          label: 'Название', required: true },
      { name: 'sheet_name',    label: 'Имя листа в Sheets', required: true },
      { name: 'is_individual', label: 'Индивидуальное', type: 'checkbox' },
    ],
    initial: row || {},
    onSubmit: async (data) => {
      if (isNew) {
        const created = await api('POST', '/api/admin/directions', data);
        state.cache.directions.push(created);
      } else {
        const updated = await api('PATCH', `/api/admin/directions/${row.id}`, data);
        Object.assign(row, updated);
      }
      await renderSection();
      toast(isNew ? 'Создано' : 'Сохранено', 'ok');
    },
    onDelete: isNew ? null : async () => {
      await api('DELETE', `/api/admin/directions/${row.id}`);
      const i = state.cache.directions.findIndex((d) => d.id === row.id);
      if (i >= 0) state.cache.directions[i].active = false;
      await renderSection();
      toast('Архивировано', 'ok');
    },
  });
}
```

- [ ] **Step 2: Manual verify**

1. Раздел «Направления» → таблица заполнена (есть «Программирование», «Английский» и т.п. — из backfill).
2. Создать «TEST_DIR» с `sheet_name=TestDir`, `is_individual=false` → появилось.
3. Открыть, переключить `is_individual=true` → сохранилось.
4. Удалить → ушло в архив (если есть группы, FK не даст hard-delete, но soft работает).

---

### Task 6: Tokens section + generate button

**Files:**
- Modify: `public/admin-app.js`

- [ ] **Step 1: Зарегистрировать renderer**

```js
SECTION_RENDERERS.tokens = function renderTokens(host, rows) {
  renderTable({
    host, rows, title: 'Токены',
    search: SECTION_SEARCH.tokens,
    columns: [
      { key: 'token',        label: 'Токен' },
      { key: 'teacher_name', label: 'Преподаватель' },
      { key: 'active',       label: 'Статус', format: (r) => r.active ? 'активен' : 'отозван' },
    ],
    onAddNew: () => openTokenModal(null),
    onRowClick: (row) => openTokenModal(row),
  });
};

async function ensureTeachersCache() {
  if (state.cache.teachers === null) {
    state.cache.teachers = await api('GET', '/api/admin/teachers');
  }
  return state.cache.teachers;
}

async function openTokenModal(row) {
  const isNew = !row;
  let teachers;
  try { teachers = await ensureTeachersCache(); }
  catch (err) { showApiError(err); return; }
  const teacherOptions = teachers
    .filter((t) => t.active || (row && row.teacher_id === t.id))
    .map((t) => ({ value: t.id, label: t.name }));

  const fields = [
    { name: 'token',      label: 'Токен', required: true },
    { name: 'teacher_id', label: 'Преподаватель', type: 'select', options: teacherOptions, required: true },
  ];
  if (!isNew) fields.push({ name: 'active', label: 'Активен', type: 'checkbox' });

  openModal({
    title: isNew ? 'Новый токен' : `Токен · ${row.token}`,
    fields,
    initial: row || { active: true },
    onSubmit: async (data) => {
      if (isNew) {
        data.teacher_id = Number(data.teacher_id);
        const created = await api('POST', '/api/admin/tokens', data);
        // у списка нет teacher_name — добавляем вручную
        const t = teachers.find((x) => x.id === created.teacher_id);
        created.teacher_name = t ? t.name : '';
        state.cache.tokens.push(created);
      } else {
        const updated = await api('PATCH', `/api/admin/tokens/${encodeURIComponent(row.token)}`, {
          teacher_id: Number(data.teacher_id),
          active: data.active,
        });
        const t = teachers.find((x) => x.id === updated.teacher_id);
        updated.teacher_name = t ? t.name : row.teacher_name;
        Object.assign(row, updated);
      }
      await renderSection();
      toast(isNew ? 'Создано' : 'Сохранено', 'ok');
    },
    onDelete: isNew ? null : async () => {
      await api('DELETE', `/api/admin/tokens/${encodeURIComponent(row.token)}`);
      const i = state.cache.tokens.findIndex((t) => t.token === row.token);
      if (i >= 0) state.cache.tokens[i].active = false;
      await renderSection();
      toast('Отозвано', 'ok');
    },
  });

  // Добавляем кнопку «Сгенерировать» рядом с полем token
  if (isNew) {
    const tokenInput = document.querySelector('#modal-host input[name="token"]');
    const wrapper = tokenInput.parentElement;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-secondary';
    btn.style.marginTop = '6px';
    btn.textContent = 'Сгенерировать';
    btn.addEventListener('click', async () => {
      try {
        const r = await api('POST', '/api/admin/tokens/generate');
        tokenInput.value = r.token;
      } catch (err) { showApiError(err); }
    });
    wrapper.appendChild(btn);
  }
}
```

- [ ] **Step 2: Manual verify**

1. Раздел «Токены» — таблица заполнена (из backfill).
2. Создать новый: «+ Новый» → клик «Сгенерировать» → в поле появилось `XXX-XXX-XXX` → выбрать преподавателя → Сохранить → строка появилась.
3. Открыть существующий → снять чекбокс «Активен» → Сохранить → статус «отозван».
4. Открыть отозванный → Удалить → удаляется (двухшаговая кнопка).
5. По умолчанию отозванные не показываются (сервер фильтрует). Это ожидаемо.

---

### Task 7: Groups section + slot editor

**Files:**
- Modify: `public/admin-app.js`

- [ ] **Step 1: Зарегистрировать renderer**

```js
SECTION_RENDERERS.groups = function renderGroups(host, rows) {
  renderTable({
    host, rows, title: 'Группы',
    search: SECTION_SEARCH.groups,
    columns: [
      { key: 'name', label: 'Название' },
      { key: 'lesson_duration_minutes', label: 'Минут' },
      { key: 'lessons_per_week', label: 'В неделю' },
      { key: 'slots', label: 'Слоты', format: (r) => (r.slots || []).map((s) => formatSlot(s)).join(', ') || '—' },
      { key: 'active', label: 'Статус', format: (r) => r.active ? 'активна' : 'архив' },
    ],
    onAddNew: () => openGroupModal(null),
    onRowClick: (row) => openGroupModal(row),
  });
};

const DOW = ['Вс','Пн','Вт','Ср','Чт','Пт','Сб'];
function formatSlot(s) { return `${DOW[s.day_of_week]} ${String(s.start_time).slice(0,5)}`; }

async function ensureDirectionsCache() {
  if (state.cache.directions === null) state.cache.directions = await api('GET', '/api/admin/directions');
  return state.cache.directions;
}

async function openGroupModal(row) {
  const isNew = !row;
  let teachers, directions;
  try { [teachers, directions] = await Promise.all([ensureTeachersCache(), ensureDirectionsCache()]); }
  catch (err) { showApiError(err); return; }

  const teacherOptions   = teachers.filter((t) => t.active || (row && row.teacher_id === t.id)).map((t) => ({ value: t.id, label: t.name }));
  const directionOptions = directions.filter((d) => d.active || (row && row.direction_id === d.id)).map((d) => ({ value: d.id, label: d.name }));

  const fields = [
    { name: 'name',         label: 'Название группы', required: true },
    { name: 'direction_id', label: 'Направление', type: 'select', options: directionOptions, required: true },
    { name: 'teacher_id',   label: 'Преподаватель', type: 'select', options: teacherOptions, required: true },
    { name: 'is_individual', label: 'Индивидуальная', type: 'checkbox' },
    { name: 'lesson_duration_minutes', label: 'Длительность урока, мин',
      type: 'select', options: [{value:45,label:'45'},{value:60,label:'60'},{value:90,label:'90'}] },
    { name: 'lessons_per_week', label: 'Уроков в неделю', type: 'number' },
    { name: 'group_start_date', label: 'Дата старта', type: 'date' },
    { name: 'vk_chat',          label: 'Ссылка на чат ВК' },
  ];

  // локальный массив слотов — модифицируется через DOM-кнопки
  const slots = row && row.slots ? row.slots.map((s) => ({ ...s, start_time: String(s.start_time).slice(0,5) })) : [];

  openModal({
    title: isNew ? 'Новая группа' : `Группа · ${row.name}`,
    fields,
    initial: row || { lesson_duration_minutes: 90, lessons_per_week: 1 },
    onSubmit: async (data) => {
      const payload = {
        ...data,
        direction_id: Number(data.direction_id),
        teacher_id:   Number(data.teacher_id),
        lesson_duration_minutes: Number(data.lesson_duration_minutes),
        lessons_per_week: data.lessons_per_week == null ? 1 : Number(data.lessons_per_week),
        slots: slots.map((s) => ({ day_of_week: Number(s.day_of_week), start_time: s.start_time })),
      };
      if (isNew) {
        const created = await api('POST', '/api/admin/groups', payload);
        state.cache.groups.push(await api('GET', `/api/admin/groups/${created.id}`));
      } else {
        await api('PATCH', `/api/admin/groups/${row.id}`, payload);
        const fresh = await api('GET', `/api/admin/groups/${row.id}`);
        Object.assign(row, fresh);
      }
      await renderSection();
      toast(isNew ? 'Создано' : 'Сохранено', 'ok');
    },
    onDelete: isNew ? null : async () => {
      await api('DELETE', `/api/admin/groups/${row.id}`);
      const i = state.cache.groups.findIndex((g) => g.id === row.id);
      if (i >= 0) state.cache.groups[i].active = false;
      await renderSection();
      toast('Архивировано', 'ok');
    },
  });

  // Вставляем slot-редактор в конец body модалки
  const body = document.querySelector('#modal-host .modal__body');
  const editor = document.createElement('div');
  editor.className = 'modal__field';
  editor.innerHTML = `<label>Слоты расписания</label><div id="slots-list"></div>
    <button type="button" class="slot-add" id="slot-add">+ Добавить слот</button>`;
  body.appendChild(editor);
  const list = document.getElementById('slots-list');

  function renderSlots() {
    list.innerHTML = slots.map((s, i) => `
      <div class="slot-row">
        <select data-slot-idx="${i}" data-slot-field="day_of_week">
          ${DOW.map((d, idx) => `<option value="${idx}"${Number(s.day_of_week) === idx ? ' selected' : ''}>${d}</option>`).join('')}
        </select>
        <input type="time" data-slot-idx="${i}" data-slot-field="start_time" value="${escapeHtml(s.start_time || '')}">
        <button type="button" class="slot-row__remove" data-slot-remove="${i}">×</button>
      </div>
    `).join('');
    list.querySelectorAll('[data-slot-field]').forEach((el) => {
      el.addEventListener('change', () => {
        const i = Number(el.dataset.slotIdx);
        slots[i][el.dataset.slotField] = el.value;
      });
    });
    list.querySelectorAll('[data-slot-remove]').forEach((b) => {
      b.addEventListener('click', () => { slots.splice(Number(b.dataset.slotRemove), 1); renderSlots(); });
    });
  }
  renderSlots();
  document.getElementById('slot-add').addEventListener('click', () => {
    slots.push({ day_of_week: 1, start_time: '18:00' });
    renderSlots();
  });
}
```

- [ ] **Step 2: Manual verify**

1. Раздел «Группы» — таблица заполнена, в колонке «Слоты» видны примеры вроде `Пн 18:00, Ср 18:00`.
2. Создать новую: «+ Новый» → заполнить (название, направление, преподаватель), добавить два слота → Сохранить → строка появилась со слотами.
3. Открыть существующую → удалить один слот (×) → добавить новый → Сохранить → перезагружается со свежим набором.
4. Архивировать → ушла из таблицы.

---

### Task 8: Students section + memberships subtable

**Files:**
- Modify: `public/admin-app.js`

- [ ] **Step 1: Зарегистрировать renderer**

```js
SECTION_RENDERERS.students = function renderStudents(host, rows) {
  renderTable({
    host, rows, title: 'Ученики',
    search: SECTION_SEARCH.students,
    columns: [
      { key: 'full_name',         label: 'Имя' },
      { key: 'age',               label: 'Возраст' },
      { key: 'pm',                label: 'ПМ' },
      { key: 'enrollment_status', label: 'Статус', format: (r) => formatEnrollment(r) },
    ],
    onAddNew: () => openStudentModal(null),
    onRowClick: (row) => openStudentModal(row),
  });
};

function formatEnrollment(r) {
  if (r.enrollment_status === 'frozen') return `заморожен до ${r.frozen_until_month || '?'}`;
  return r.enrollment_status;
}

async function ensureGroupsCache() {
  if (state.cache.groups === null) state.cache.groups = await api('GET', '/api/admin/groups');
  return state.cache.groups;
}

async function openStudentModal(row) {
  const isNew = !row;
  const fields = [
    { name: 'full_name',           label: 'ФИО', required: true },
    { name: 'birth_date',          label: 'Дата рождения', type: 'date' },
    { name: 'phone',               label: 'Телефон' },
    { name: 'school_grade',        label: 'Класс школы', type: 'number' },
    { name: 'platform_id',         label: 'Platform ID' },
    { name: 'parent_name',         label: 'Имя родителя' },
    { name: 'first_purchase_date', label: 'Дата первой оплаты', type: 'date' },
    { name: 'age',                 label: 'Возраст', type: 'number' },
    { name: 'pm',                  label: 'ПМ' },
    { name: 'enrollment_status',   label: 'Статус', type: 'select',
      options: ['enrolled','not_enrolled','frozen','declined'].map((v) => ({ value: v, label: v })) },
    { name: 'frozen_until_month',  label: 'Заморожен до (месяц 1-12)', type: 'number' },
  ];

  openModal({
    title: isNew ? 'Новый ученик' : `Ученик · ${row.full_name}`,
    fields,
    initial: row || { enrollment_status: 'enrolled' },
    onSubmit: async (data) => {
      // frozen_until_month имеет смысл только при status=frozen
      if (data.enrollment_status !== 'frozen') data.frozen_until_month = null;
      if (isNew) {
        const created = await api('POST', '/api/admin/students', data);
        state.cache.students.push(created);
      } else {
        const updated = await api('PATCH', `/api/admin/students/${row.id}`, data);
        Object.assign(row, updated);
      }
      await renderSection();
      toast(isNew ? 'Создано' : 'Сохранено', 'ok');
    },
    onDelete: isNew ? null : async () => {
      await api('DELETE', `/api/admin/students/${row.id}`);
      const i = state.cache.students.findIndex((s) => s.id === row.id);
      if (i >= 0) state.cache.students[i].enrollment_status = 'not_enrolled';
      await renderSection();
      toast('Деактивировано', 'ok');
    },
  });

  if (!isNew) await attachMembershipsBlock(row);
}

async function attachMembershipsBlock(student) {
  let memberships, groups;
  try {
    [memberships, groups] = await Promise.all([
      api('GET', `/api/admin/group-memberships?student_id=${student.id}`),
      ensureGroupsCache(),
    ]);
  } catch (err) { showApiError(err); return; }

  const body = document.querySelector('#modal-host .modal__body');
  if (!body) return;
  const block = document.createElement('div');
  block.className = 'memberships';
  body.appendChild(block);

  function render() {
    const rowsHtml = memberships.length ? memberships.map((m) => `
      <div class="memberships__row" data-mid="${m.id}">
        <div>${escapeHtml(m.group_name || ('#' + m.group_id))}</div>
        <input type="number" step="0.5" data-mfield="lessons_done" value="${m.lessons_done}">
        <input type="number" step="0.5" data-mfield="remaining"    value="${m.remaining}">
        <button type="button" class="slot-row__remove" data-mremove>×</button>
      </div>
    `).join('') : `<div style="color: var(--text-3); font-size: 13px;">Нет групп</div>`;

    const usedGroupIds = new Set(memberships.map((m) => m.group_id));
    const groupOptions = groups.filter((g) => g.active && !usedGroupIds.has(g.id))
      .map((g) => `<option value="${g.id}">${escapeHtml(g.name)}</option>`).join('');

    block.innerHTML = `
      <h4 class="memberships__title">Группы ученика</h4>
      ${rowsHtml}
      <div class="memberships__add">
        <select id="memb-add-group">${groupOptions || '<option value="">Нет доступных групп</option>'}</select>
        <button type="button" class="btn-secondary" id="memb-add-btn">+ Добавить</button>
      </div>
    `;

    block.querySelectorAll('[data-mid]').forEach((rowEl) => {
      const mid = Number(rowEl.dataset.mid);
      rowEl.querySelectorAll('[data-mfield]').forEach((inp) => {
        inp.addEventListener('change', async () => {
          const patch = { [inp.dataset.mfield]: Number(inp.value) };
          try {
            const updated = await api('PATCH', `/api/admin/group-memberships/${mid}`, patch);
            const i = memberships.findIndex((m) => m.id === mid);
            if (i >= 0) memberships[i] = { ...memberships[i], ...updated };
            toast('Сохранено', 'ok');
          } catch (err) { showApiError(err); }
        });
      });
      rowEl.querySelector('[data-mremove]').addEventListener('click', async () => {
        try {
          await api('DELETE', `/api/admin/group-memberships/${mid}`);
          memberships = memberships.filter((m) => m.id !== mid);
          render();
          toast('Удалено из группы', 'ok');
        } catch (err) { showApiError(err); }
      });
    });

    const addBtn = block.querySelector('#memb-add-btn');
    addBtn.addEventListener('click', async () => {
      const select = block.querySelector('#memb-add-group');
      if (!select.value) return;
      try {
        const created = await api('POST', '/api/admin/group-memberships', {
          student_id: student.id,
          group_id: Number(select.value),
        });
        // обогащаем group_name для отображения
        const g = groups.find((x) => x.id === created.group_id);
        created.group_name = g ? g.name : '';
        memberships.push(created);
        render();
        toast('Добавлен в группу', 'ok');
      } catch (err) { showApiError(err); }
    });
  }
  render();
}
```

- [ ] **Step 2: Manual verify**

1. Раздел «Ученики» — таблица заполнена (300 учеников).
2. Создать «TEST_STUDENT»: ФИО + Возраст 10 + статус `enrolled` → Сохранить → появился, тост «Создано».
3. Открыть «TEST_STUDENT» → внизу модалки блок «Группы ученика», пусто. Выбрать группу из dropdown → «+ Добавить» → строка появилась.
4. В появившейся строке изменить `lessons_done` на 5 → blur → тост «Сохранено», значение в кеше обновилось.
5. Клик `×` рядом со строкой → ушла, тост «Удалено из группы».
6. Закрыть модалку, открыть снова → состав сохранился (в БД).
7. На основной форме сменить статус на `frozen`, ввести `frozen_until_month=8` → Сохранить → проходит.
8. Деактивировать → ушёл из таблицы (статус → not_enrolled).

Чистка: `DELETE FROM group_memberships WHERE student_id IN (SELECT id FROM students WHERE full_name LIKE 'TEST_%'); DELETE FROM students WHERE full_name LIKE 'TEST_%';`

---

### Task 9: Дополнить `docs/admin-smoke-tests.md` UI-чеклистом

**Files:**
- Modify: `docs/admin-smoke-tests.md`

- [ ] **Step 1: В конец файла добавить раздел**

```markdown
---

## UI smoke (Phase 4.3)

`npm start` → открыть http://localhost:3000/admin

### Login

- [ ] Без cookie показывается login-карточка.
- [ ] Неверный пароль → красный тост «Invalid credentials».
- [ ] Правильный логин/пароль → перерисовка в shell с sidebar (5 пунктов).
- [ ] Logout → перезагрузка → снова login.

### Каждый раздел (Students, Groups, Teachers, Tokens, Directions)

- [ ] Клик в sidebar → таблица грузится (первый клик — спиннер «Загружаем», второй — мгновенно из кеша).
- [ ] Поиск в шапке фильтрует таблицу.
- [ ] «+ Новый» → модалка с пустой формой; обязательные поля валидируются сервером (404/400 → тост).
- [ ] Клик по строке → модалка с прелейфилом.
- [ ] Сохранить → строка обновилась/добавилась, тост «Сохранено»/«Создано».
- [ ] Удалить → двухшаговая кнопка («Удалить» → «Точно удалить?»). Строка ушла, тост «Архивировано»/«Деактивировано»/«Отозвано».

### Tokens

- [ ] В модалке нового токена кнопка «Сгенерировать» подставляет XXX-XXX-XXX.

### Groups

- [ ] В модалке slot-редактор: «+ Добавить слот» появляется новая строка (день+время).
- [ ] Удаление слота через ×.
- [ ] После сохранения и повторного открытия слоты те же.

### Students

- [ ] Блок «Группы ученика» внутри Edit-модалки.
- [ ] Добавить в группу — строка появилась без закрытия модалки.
- [ ] Изменить lessons_done — blur сохраняет.
- [ ] × удаляет из группы.

### Сессия

- [ ] Если cookie протухла (можно дождаться 24ч или удалить в DevTools → Application → Cookies) → следующий fetch даёт тост «Сессия истекла» и через 1.5с перезагрузка.

### Уборка

```sql
DELETE FROM group_memberships WHERE student_id IN (SELECT id FROM students WHERE full_name LIKE 'TEST_%');
DELETE FROM students WHERE full_name LIKE 'TEST_%';
DELETE FROM tokens   WHERE token LIKE 'TEST-%';
DELETE FROM teachers WHERE name  LIKE 'TEST_%';
DELETE FROM groups   WHERE name  LIKE 'TEST_%';
DELETE FROM directions WHERE name LIKE 'TEST_%';
```
```

- [ ] **Step 2: Manual verify** — открыть файл, убедиться что markdown корректно отображается.

---

## Финальная проверка

- [ ] `npm test` — 49/49 PASS (backend не сломан).
- [ ] `npm start` — стартует чисто.
- [ ] Teacher SPA (`http://localhost:3000/`) — работает идентично прежнему, никаких регрессий.
- [ ] Admin SPA (`http://localhost:3000/admin`) — login, sidebar, CRUD по 5 разделам, logout — каждый пункт `docs/admin-smoke-tests.md` зелёный.
- [ ] DevTools Console — никаких ошибок при штатных сценариях.

---

## Что НЕ входит в Phase 4.3

- Read-only раздел «Состав» (overview всех memberships). Откладывается в 4.4.
- Клиентская валидация (формат phone, email и т.п.). 4.4.
- Sortable columns, pagination.
- Audit log (`admin_audit_log` таблица). 4.4 опционально.
- Phase 3 cutover — следующая большая фаза.

---

## Откат

```powershell
# Удалить файлы
Remove-Item public\admin.html, public\admin-app.js
# В server.js удалить строку app.get('/admin', ...)
# В public/styles.css удалить блок /* ─── ADMIN SPA ─── */ ... до конца файла
# В docs/admin-smoke-tests.md удалить раздел «UI smoke (Phase 4.3)»
```

Teacher SPA и admin backend остаются работать.
