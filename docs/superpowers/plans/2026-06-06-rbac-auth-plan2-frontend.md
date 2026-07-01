# RBAC + унифицированный вход — План 2: Frontend cutover

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Поднять единую страницу `/login` (выбор роли → форма email+пароль → 2FA), перенести teacher SPA на `/teacher` без token-экрана, перестроить роутинг `server.js`, перевести admin SPA на `/api/auth/me` и редирект на `/login`.

**Architecture:** Standalone vanilla-страница входа на `/` и `/login` дергает `/api/auth/*` и редиректит по `redirect`. Teacher SPA (vanilla) переезжает в `public/teacher/`, читает сессию-cookie. Admin SPA меняет `AuthProvider`/`AuthGate` на единый вход.

**Tech Stack:** vanilla HTML/CSS/JS, Express static, React 19 (admin SPA), Vite.

**Зависит от:** Плана 1 (бэк `/api/auth/*` работает). **Спека:** `docs/superpowers/specs/2026-06-06-rbac-unified-auth-design.md`.

**git:** репозиторий пока без git — `git commit` = чекпойнт.

---

### Task 1: Страница входа — разметка + стиль (KOTOKOD)

**Files:**
- Create: `public/login/index.html`
- Create: `public/login/styles.css`

- [ ] **Step 1: Создать `public/login/index.html`**

```html
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Вход — KOTOKOD</title>
  <link rel="stylesheet" href="/login/styles.css" />
</head>
<body>
  <header class="topbar">
    <!-- логотип из logo.html (на тёмном баре, заливки #F4F4F4 + #50DCFE) -->
    <svg class="logo" fill="none" height="32" viewBox="0 0 207 40" width="166" aria-label="KOTOKOD">
      <use href="#kk"></use>
    </svg>
  </header>

  <main class="wrap">
    <div class="hero">
      <div class="welcome">ДОБРО ПОЖАЛОВАТЬ</div>
      <h1 class="title">Вход в KOTOKOD</h1>
      <p class="subtitle">Выберите, кто вы — и мы подберём правильный вход.</p>
    </div>

    <!-- Экран 1: выбор роли -->
    <section id="screen-role" class="cards">
      <button class="card" data-role="teacher">
        <div class="card-ico">🎓</div>
        <div class="card-title">Преподаватель</div>
        <div class="card-sub">Журнал, группы, расписание</div>
      </button>
      <button class="card" data-role="admin">
        <div class="card-ico">👑</div>
        <div class="card-title">Админ / Менеджер</div>
        <div class="card-sub">CRM, оплаты, отчёты, дашборд</div>
      </button>
    </section>

    <!-- Экран 2: форма входа -->
    <section id="screen-login" class="panel hidden">
      <button class="back" data-back>← Назад</button>
      <div class="login-card">
        <div class="kicker" id="login-kicker">КАБИНЕТ</div>
        <h2 id="login-h">Войти</h2>
        <form id="login-form" novalidate>
          <input id="f-email" class="field" type="email" placeholder="Email" autocomplete="username" required />
          <input id="f-pass" class="field" type="password" placeholder="Пароль" autocomplete="current-password" required />
          <button class="primary" type="submit">→ Войти</button>
          <div class="err hidden" id="login-err"></div>
        </form>
      </div>
    </section>

    <!-- Экран 3: 2FA -->
    <section id="screen-2fa" class="panel hidden">
      <button class="back" data-back>← Назад</button>
      <div class="login-card">
        <div class="kicker">ПОДТВЕРЖДЕНИЕ ВХОДА</div>
        <h2 id="twofa-h">Введите код</h2>
        <p class="muted" id="twofa-hint"></p>
        <div id="twofa-qr-wrap" class="qr hidden"><img id="twofa-qr" alt="QR" /></div>
        <form id="twofa-form" novalidate>
          <input id="f-code" class="field code" inputmode="numeric" placeholder="Код" required />
          <button class="primary" type="submit">Подтвердить</button>
          <button class="ghost hidden" type="button" id="email-resend">Отправить код на почту</button>
          <div id="recovery-box" class="recovery hidden"></div>
          <div class="err hidden" id="twofa-err"></div>
        </form>
      </div>
    </section>
  </main>

  <footer class="foot">© <span id="yr"></span> KOTOKOD</footer>

  <!-- спрятанный спрайт логотипа -->
  <svg width="0" height="0" style="position:absolute"><defs><g id="kk">
    <!-- вставить пути из logo.html (внутренности <g clip-path>...) -->
  </g></defs></svg>

  <script src="/login/login.js"></script>
</body>
</html>
```

> ⚠️ В `<g id="kk">` перенести `<path>`-ы из `logo.html` (содержимое группы). Цвета оставить как есть (тёмный topbar).

- [ ] **Step 2: Создать `public/login/styles.css` (фирменный teal KOTOKOD)**

```css
:root{
  --bg:#fbf9f4; --surface:#fff; --text:#16181d; --text2:#5b616e; --text3:#8b909c;
  --accent:#0d9488; --accent-hover:#0b827a; --border:rgba(20,24,29,.10);
  --r:12px; --r-sm:8px; --space:16px; --topbar:#16181d;
  --font:Inter,system-ui,Segoe UI,Roboto,sans-serif;
}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font-family:var(--font)}
.topbar{height:56px;display:flex;align-items:center;padding:0 24px;background:var(--topbar)}
.logo{display:block}
.wrap{max-width:1040px;margin:0 auto;padding:48px 24px}
.hero{text-align:center;margin-bottom:40px}
.welcome{letter-spacing:.18em;font-size:12px;color:var(--text3);font-weight:600}
.title{font-size:40px;margin:8px 0;font-weight:700;letter-spacing:-.02em}
.subtitle{color:var(--text2);margin:0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px;max-width:760px;margin:0 auto}
.card{cursor:pointer;text-align:left;background:var(--surface);border:1px solid var(--border);border-radius:var(--r);
  padding:24px;transition:border-color .15s ease, transform .15s ease}
.card:hover{border-color:var(--accent);transform:translateY(-2px)}
.card-ico{font-size:28px;margin-bottom:12px}
.card-title{font-weight:700;font-size:18px}
.card-sub{color:var(--text2);font-size:14px;margin-top:4px}
.panel{max-width:440px;margin:0 auto;position:relative}
.back{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-sm);
  padding:8px 14px;cursor:pointer;font-weight:600;margin-bottom:16px}
.login-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:28px}
.kicker{letter-spacing:.14em;font-size:11px;color:var(--text3);font-weight:700}
.login-card h2{margin:6px 0 18px;font-size:24px}
.field{width:100%;padding:14px 16px;border:1px solid var(--border);border-radius:var(--r-sm);
  font-size:15px;margin-bottom:12px;font-family:var(--font);background:#fff}
.field:focus{outline:2px solid var(--accent);outline-offset:1px;border-color:var(--accent)}
.field.code{text-align:center;letter-spacing:.4em;font-size:20px}
.primary{width:100%;padding:14px;border:none;border-radius:var(--r-sm);background:var(--accent);color:#fff;
  font-weight:700;font-size:15px;cursor:pointer}
.primary:hover{background:var(--accent-hover)}
.ghost{width:100%;padding:12px;margin-top:10px;border:1px solid var(--border);border-radius:var(--r-sm);
  background:#fff;cursor:pointer;font-weight:600}
.muted{color:var(--text2);font-size:14px;margin:0 0 14px}
.err{color:#b42318;font-size:14px;margin-top:12px}
.qr{text-align:center;margin-bottom:14px} .qr img{width:180px;height:180px}
.recovery{margin-top:14px;padding:12px;border:1px dashed var(--accent);border-radius:var(--r-sm);
  font-family:JetBrains Mono,monospace;font-size:13px;white-space:pre-wrap}
.hidden{display:none!important}
.foot{text-align:center;color:var(--text3);font-size:13px;padding:24px}
```

- [ ] **Step 3: Commit**

```bash
git add public/login/index.html public/login/styles.css
git commit -m "feat(login): role-select + login + 2FA page markup/styles"
```

---

### Task 2: Логика страницы входа (login.js)

**Files:**
- Create: `public/login/login.js`

- [ ] **Step 1: Реализовать `public/login/login.js`**

```js
const $ = (id) => document.getElementById(id);
document.getElementById('yr').textContent = new Date().getFullYear();

const screens = { role: $('screen-role'), login: $('screen-login'), twofa: $('screen-2fa') };
function show(name){ for (const k in screens) screens[k].classList.toggle('hidden', k !== name); }

let role = null;          // 'teacher' | 'admin'
let challenge = null;     // challenge_token
let enroll = false;       // enrollment-режим

async function post(path, body){
  const r = await fetch(path, {
    method:'POST', credentials:'include',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify(body),
  });
  const j = await r.text().then(t => t ? JSON.parse(t) : null);
  return { ok:r.ok, status:r.status, j };
}
function err(id, msg){ const e=$(id); e.textContent=msg; e.classList.remove('hidden'); }
function clr(id){ const e=$(id); e.textContent=''; e.classList.add('hidden'); }

// Экран выбора роли
document.querySelectorAll('.card').forEach((c) => c.addEventListener('click', () => {
  role = c.dataset.role;
  $('login-kicker').textContent = role === 'teacher' ? 'КАБИНЕТ ПРЕПОДАВАТЕЛЯ' : 'КАБИНЕТ УПРАВЛЕНИЯ';
  $('login-h').textContent = role === 'teacher' ? 'Войти как преподаватель' : 'Войти как админ/менеджер';
  clr('login-err'); $('login-form').reset(); show('login');
}));
document.querySelectorAll('[data-back]').forEach((b) => b.addEventListener('click', () => show('role')));

// Форма входа
$('login-form').addEventListener('submit', async (ev) => {
  ev.preventDefault(); clr('login-err');
  const email = $('f-email').value.trim();
  const password = $('f-pass').value;
  if (!email || !password) return err('login-err', 'Заполните email и пароль');
  const { ok, status, j } = await post('/api/auth/login', { email, password, role });
  if (ok && j.redirect) return (window.location = j.redirect);
  if (status === 429) return err('login-err', j.error || 'Слишком много попыток, попробуйте позже');
  if (j && j.twofa_required) { challenge = j.challenge_token; enroll = false; openTwofa(j.method); return; }
  if (j && j.twofa_enrollment_required) { challenge = j.challenge_token; enroll = true; openEnroll(); return; }
  err('login-err', (j && j.error) || 'Ошибка входа');
});

// 2FA: обычная проверка
function openTwofa(method){
  clr('twofa-err'); $('twofa-form').reset(); $('twofa-qr-wrap').classList.add('hidden');
  $('recovery-box').classList.add('hidden');
  $('twofa-h').textContent = 'Введите код';
  if (method === 'email'){
    $('twofa-hint').textContent = 'Мы отправили код на вашу почту.';
    $('email-resend').classList.remove('hidden');
  } else {
    $('twofa-hint').textContent = 'Код из приложения-аутентификатора.';
    $('email-resend').classList.add('hidden');
  }
  show('twofa');
}

// 2FA: enrollment (по умолчанию TOTP; ссылка для email можно добавить позже)
async function openEnroll(){
  clr('twofa-err'); $('twofa-form').reset();
  const { ok, j } = await post('/api/auth/2fa/setup', { challenge_token: challenge, method: 'totp' });
  if (!ok){ err('twofa-err', (j&&j.error)||'Ошибка настройки 2FA'); return; }
  $('twofa-h').textContent = 'Настройте 2FA';
  $('twofa-hint').textContent = 'Отсканируйте QR в приложении (Google Authenticator / Яндекс.Ключ) и введите код.';
  $('twofa-qr').src = j.qr; $('twofa-qr-wrap').classList.remove('hidden');
  $('email-resend').classList.add('hidden');
  show('twofa');
}

// 2FA submit
$('twofa-form').addEventListener('submit', async (ev) => {
  ev.preventDefault(); clr('twofa-err');
  const code = $('f-code').value.trim();
  if (!code) return err('twofa-err', 'Введите код');
  const path = enroll ? '/api/auth/2fa/enable' : '/api/auth/login/2fa';
  const { ok, j } = await post(path, { challenge_token: challenge, code });
  if (!ok) return err('twofa-err', (j && j.error) || 'Неверный код');
  if (enroll && j.recovery_codes){
    const box = $('recovery-box');
    box.textContent = 'Сохраните резервные коды (показаны один раз):\n' + j.recovery_codes.join('  ');
    box.classList.remove('hidden');
    setTimeout(() => (window.location = j.redirect), 6000); // дать прочитать коды
    return;
  }
  if (j.redirect) window.location = j.redirect;
});

// Повторная отправка email-кода
$('email-resend').addEventListener('click', async () => {
  const { ok, j } = await post('/api/auth/2fa/email/send', { challenge_token: challenge });
  if (ok && j.challenge_token){ challenge = j.challenge_token; err('twofa-err', 'Код отправлен повторно'); }
});
```

- [ ] **Step 2: Commit**

```bash
git add public/login/login.js
git commit -m "feat(login): role-select + login + 2FA flow logic"
```

---

### Task 3: Перенос teacher SPA в public/teacher/ + чистка токен-входа

**Files:**
- Move: `public/Index.html` → `public/teacher/index.html`
- Move: `public/styles.css` → `public/teacher/styles.css` (если используется teacher SPA; проверить ссылку)

- [ ] **Step 1: Переместить файлы**

Run:
```bash
mkdir public\teacher
move public\Index.html public\teacher\index.html
```
(styles.css teacher SPA — если `index.html` ссылается на `/styles.css`, переместить в `/teacher/styles.css` и поправить ссылку; если стили инлайновые — пропустить.)

- [ ] **Step 2: Убрать token-screen и логику токена**

В `public/teacher/index.html`:
- Удалить блок `<div id="tokenScreen" ...>...</div>` (≈ строки 1891–1902 оригинала).
- В JS удалить функции `onTokenInput`/`submitToken` и обращение к `tokenScreen`/`tokenInput`/`tokenError`/`tokenBtn`.
- Убрать `state.token` и все `token: ...` из тел fetch.

- [ ] **Step 3: Заменить хардкод `http://localhost:3000/api/...` на относительные пути**

Заменить во всех fetch `http://localhost:3000/api/` → `/api/` (это убирает CORS-зависимость и работает на проде).

- [ ] **Step 4: Стартовый поток — грузить данные из сессии**

При загрузке страницы вместо token-экрана сразу вызывать данные; на 401 — редирект на логин. Добавить helper и заменить старый `submitToken`-инициализатор на:
```js
async function bootstrap(){
  const r = await fetch('/api/getData', { method:'POST', credentials:'include',
    headers:{'Content-Type':'application/json'}, body:'{}' });
  if (r.status === 401 || r.status === 403){ window.location = '/login'; return; }
  const res = await r.json();
  state.teacher = res.teacher; state.teacherData = res.data || {};
  // ... далее существующий рендер интерфейса (как было после успешного submitToken)
  renderMain(); // вызвать существующую функцию отрисовки
}
window.addEventListener('DOMContentLoaded', bootstrap);
```
(Имя `renderMain` заменить на фактическую функцию, что вызывалась после успешной валидации токена.)

- [ ] **Step 5: Кнопка «Выход»**

Заменить обработчик выхода (ранее чистил token и показывал tokenScreen) на:
```js
async function logout(){
  try { await fetch('/api/auth/logout', { method:'POST', credentials:'include' }); } catch(e){}
  window.location = '/login';
}
```
Привязать к существующей кнопке выхода.

- [ ] **Step 6: Все fetch — `credentials:'include'`**

Убедиться, что каждый `fetch('/api/...')` содержит `credentials:'include'` (cookie уходит на сервер).

- [ ] **Step 7: Commit**

```bash
git add public/teacher/
git commit -m "refactor(teacher-spa): move to /teacher, drop token screen, session cookie"
```

---

### Task 4: Реструктуризация роутинга server.js

**Files:**
- Modify: `server.js`

- [ ] **Step 1: Переписать статик-роутинг и порядок**

Итоговый `server.js` (раздел роутов/статики):
```js
// ===== API =====
// ⚠️ ПОРЯДОК ВАЖЕН: '/api/admin' ДО общего '/api', иначе teacher-guard на '/api'
// перехватит и '/api/admin/*' → admin/manager получат 403 (баг, пойман E2E плана 1).
app.use('/api/auth', authRouter);                                   // публично
app.use('/api/admin', adminRouter);                                 // gating внутри роутера
app.use('/api', requireAuth, requireRole('teacher'), teacherRouter); // teacher

// ===== Login page (/, /login) =====
app.get(['/', '/login'], (_, res) => res.sendFile(path.join(__dirname, 'public', 'login', 'index.html')));
app.use('/login', express.static(path.join(__dirname, 'public', 'login'), { redirect: false }));

// ===== Teacher SPA (/teacher) =====
app.get('/teacher', (_, res) => res.sendFile(path.join(__dirname, 'public', 'teacher', 'index.html')));
app.use('/teacher', express.static(path.join(__dirname, 'public', 'teacher'), { redirect: false }));
app.get('/teacher/*', (_, res) => res.sendFile(path.join(__dirname, 'public', 'teacher', 'index.html')));

// ===== Admin SPA (/admin) =====
app.get('/admin', (_, res) => res.sendFile(path.join(__dirname, 'public', 'admin-dist', 'index.html')));
app.use('/admin', express.static(path.join(__dirname, 'public', 'admin-dist'), { redirect: false }));
app.get('/admin/*', (_, res) => res.sendFile(path.join(__dirname, 'public', 'admin-dist', 'index.html')));
```
Добавить импорты вверху: `const { requireAuth, requireRole } = require('./services/auth');` и `const authRouter = require('./routes/auth');` (если не добавлено в Плане 1). **Удалить** общий `app.use(express.static('public'))` (корень больше не отдаёт старый Index.html).

- [ ] **Step 2: Smoke — маршруты отвечают**

Run (сервер `npm start`):
```bash
curl -s -o /dev/null -w "/ %{http_code}\n" http://localhost:3000/
curl -s -o /dev/null -w "/login %{http_code}\n" http://localhost:3000/login
curl -s -o /dev/null -w "/teacher %{http_code}\n" http://localhost:3000/teacher
curl -s -o /dev/null -w "/admin %{http_code}\n" http://localhost:3000/admin
```
Expected: все `200` (страницы отдаются; авторизация проверяется уже в API/клиенте).

- [ ] **Step 3: Commit**

```bash
git add server.js
git commit -m "feat(server): route /login, /teacher, /admin; gate /api by role"
```

---

### Task 5: Admin SPA — AuthProvider на /api/auth

**Files:**
- Modify: `web/admin/src/providers/AuthProvider.tsx`
- Modify: `web/admin/src/hooks/useAuth.ts` (если тип AuthState менялся — синхронизировать)

- [ ] **Step 1: Переписать AuthProvider**

```tsx
import { createContext, useState, useEffect, type ReactNode } from 'react';
import { api, ApiError } from '../lib/api';

export interface Me {
  account_id: number; email: string; role: 'teacher' | 'manager' | 'admin';
  teacher_id: number | null; name: string; twofa_enabled: boolean;
}
export interface AuthState {
  authenticated: boolean | null;
  me: Me | null;
  logout: () => Promise<void>;
}
export const AuthContext = createContext<AuthState>(null!);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    api<Me>('GET', '/api/auth/me').then(
      (m) => { setMe(m); setAuthenticated(true); },
      (e: unknown) => {
        if (e instanceof ApiError && e.status === 401) setAuthenticated(false);
        else { console.error(e); setAuthenticated(false); }
      },
    );
  }, []);

  useEffect(() => {
    const onExpired = () => { setAuthenticated(false); setMe(null); };
    window.addEventListener('admin:auth-expired', onExpired);
    return () => window.removeEventListener('admin:auth-expired', onExpired);
  }, []);

  const logout = async () => {
    try { await api('POST', '/api/auth/logout'); } catch (_) {}
    setAuthenticated(false); setMe(null);
    window.location.href = '/login';
  };

  return <AuthContext.Provider value={{ authenticated, me, logout }}>{children}</AuthContext.Provider>;
}
```

- [ ] **Step 2: Поправить потребителей `user`/`login`**

Найти использования старого контекста:
Run: `grep -rn "useAuth\|\.user\b\|\.login(" web/admin/src`
Заменить `user` → `me?.name`/`me?.email`; удалить вызовы `login(...)` (вход теперь на `/login`). Любой компонент, открывавший LoginPage внутри SPA, больше не нужен.

- [ ] **Step 3: typecheck**

Run: `npm run admin:typecheck`
Expected: без ошибок (поправить всё, что ссылалось на удалённые `user`/`login`).

- [ ] **Step 4: Commit**

```bash
git add web/admin/src/providers/AuthProvider.tsx web/admin/src/hooks/useAuth.ts
git commit -m "feat(admin-spa): AuthProvider via /api/auth/me, logout → /login"
```

---

### Task 6: Admin SPA — AuthGate + App.tsx редирект на /login

**Files:**
- Modify: `web/admin/src/components/shell/AuthGate.tsx`
- Modify: `web/admin/src/App.tsx`
- Delete: `web/admin/src/pages/LoginPage.tsx` (вход вынесен из SPA)

- [ ] **Step 1: AuthGate → внешний редирект на /login**

```tsx
import { Outlet } from 'react-router-dom';
import { useEffect } from 'react';
import { useAuth } from '../../hooks/useAuth';

export function AuthGate() {
  const { authenticated } = useAuth();
  useEffect(() => {
    if (authenticated === false) window.location.href = '/login';
  }, [authenticated]);
  if (authenticated === null) {
    return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text3)' }}>Загрузка…</div>;
  }
  if (authenticated === false) return null;
  return <Outlet />;
}
```

- [ ] **Step 2: App.tsx — убрать роут /admin/login + импорт LoginPage**

Удалить строку `<Route path="/admin/login" element={<LoginPage />} />` и импорт `LoginPage`. Остальные роуты без изменений.

- [ ] **Step 3: Удалить LoginPage.tsx**

Run: `del web\admin\src\pages\LoginPage.tsx`
(и убрать прочие импорты на него, если grep что-то найдёт.)

- [ ] **Step 4: typecheck + build**

Run: `npm run admin:typecheck && npm run admin:build`
Expected: typecheck чисто, сборка в `public/admin-dist/` успешна.

- [ ] **Step 5: Commit**

```bash
git add web/admin/src/components/shell/AuthGate.tsx web/admin/src/App.tsx
git commit -m "feat(admin-spa): redirect to /login on unauth, drop in-SPA login route"
```

---

### Task 7: E2E проверка обоих клиентов

- [ ] **Step 1: Teacher-вход end-to-end**

Сценарий (нужен teacher-аккаунт; создать `node scripts/create-account.js t@kotokod.ru teacher <teacher_id>`):
1. Открыть `/` → выбрать «Преподаватель» → ввести email+пароль.
2. teacher без 2FA → редирект `/teacher`, журнал грузится из сессии.
3. «Выход» → `/login`.

Expected: вход без токена, данные препода видны, выход возвращает на логин.

- [ ] **Step 2: Admin-вход end-to-end (с 2FA-enrollment)**

1. `/` → «Админ/Менеджер» → email+пароль → экран 2FA-enrollment (QR).
2. Ввести TOTP-код → recovery-коды показаны → редирект `/admin`.
3. Дашборд/страницы грузятся; обновление страницы сохраняет сессию.

Expected: enrollment проходит, admin SPA работает, при истечении сессии — редирект `/login`.

- [ ] **Step 3: Негативный — прямой заход на /admin без сессии**

Открыть `/admin` в инкогнито → AuthGate ловит 401 от `/api/auth/me` → редирект `/login`.

Expected: редирект на логин.

- [ ] **Step 4: Commit (чекпойнт окончания Плана 2)**

```bash
git add -A
git commit -m "test: frontend cutover E2E checkpoint (plan 2 complete)"
```

---

## Self-review (выполнено автором плана)

- **Покрытие спеки разделов 6–8:** страница `/login` 3 экрана (Task 1–2) ✓; server.js роутинг (Task 4) ✓; teacher SPA → /teacher + чистка токена + relative paths + 401→/login + logout (Task 3) ✓; admin SPA AuthProvider→/me, AuthGate→/login, удаление /admin/login (Task 5–6) ✓.
- **Согласованность с Планом 1:** страница дергает `/api/auth/login`, `/api/auth/login/2fa`, `/api/auth/2fa/setup|enable|email/send`, `/api/auth/me`, `/api/auth/logout` — все определены в Плане 1; формат ответов (`redirect`, `twofa_required`, `method`, `challenge_token`, `twofa_enrollment_required`, `qr`, `recovery_codes`) совпадает.
- **Ручные моменты:** точные номера строк token-screen в teacher SPA проверить при редактировании; имя render-функции (`renderMain`) заменить на фактическое; логотип-пути перенести из `logo.html`.
- **Вне Плана 2 (→ План 3):** UI управления учётками, audit-log UI, блок согласия на карточке ученика, навигация в sidebar, доки/CLAUDE.md.
