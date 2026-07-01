# R1 React Foundation Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Tasks use checkbox syntax.

**Goal:** Заменить vanilla TS admin SPA на React-каркас (providers, router, shell, login, stub-страницы 8 сущностей). После R1 admin SPA — barebones React app: login работает, навигация по секциям работает, страницы пустые (заполнятся в R2).

**Architecture:** React 19 + TanStack Query v5 + React Router v7 + Radix UI primitives. Структура `web/admin/src/{lib,providers,hooks,components,pages}/`. Старый код (`components/`, `entities/`, `lib/registry.ts`, текущий `main.ts`) — backup'ится перед удалением.

**Tech Stack:** React 19, TS 5, Vite 6, TanStack Query 5, React Router 7, Radix UI, Lucide React.

**Cutover strategy:** Hard cutover в одной фазе. Старый TS-SPA откатывается через backup (`_backup-pre-r1/`). Admin SPA после R1 функционально partial — login + навигация + пустые страницы. Восстановление полной функциональности — R2.

---

## File Structure

### Создаются

```
web/admin/src/
├─ main.tsx                   # ReactDOM root + providers wrap
├─ App.tsx                    # <Routes> + AuthGate + AppShell layout
├─ lib/
│  ├─ api.ts                  # fetch wrapper (port from existing)
│  ├─ format.ts               # fmtDate (DD.MM.YYYY) + escapeHtml (для редких innerHTML кейсов)
│  └─ types.ts                # re-export from @shared/types
├─ providers/
│  ├─ QueryProvider.tsx       # QueryClient + Devtools (dev)
│  ├─ AuthProvider.tsx        # auth context: user, login, logout, isLoading
│  └─ ThemeProvider.tsx       # theme: 'light' | 'dark', toggle, persist
├─ hooks/
│  └─ useAuth.ts              # useContext(AuthContext)
├─ components/
│  └─ shell/
│     ├─ AuthGate.tsx         # check session → redirect /login if 401
│     ├─ AppShell.tsx         # sidebar + main with <Outlet />
│     ├─ Sidebar.tsx          # NavLink-и 8 секций + theme/logout
│     ├─ ScrollTopButton.tsx
│     └─ ThemeToggle.tsx
├─ pages/
│  ├─ LoginPage.tsx           # форма с валидацией
│  ├─ students/StudentsListPage.tsx       # stub
│  ├─ groups/GroupsListPage.tsx           # stub
│  ├─ teachers/TeachersListPage.tsx       # stub
│  ├─ tokens/TokensListPage.tsx           # stub
│  ├─ directions/DirectionsListPage.tsx   # stub
│  ├─ lessons/LessonsListPage.tsx         # stub
│  ├─ payroll/PayrollPage.tsx             # stub
│  └─ archive/ArchivePage.tsx             # stub
└─ vite-env.d.ts              # уже есть, не трогаем
```

### Заменяются

- `web/admin/index.html` — script src `/src/main.ts` → `/src/main.tsx`
- `web/admin/vite.config.ts` — добавить `@vitejs/plugin-react`
- `web/admin/tsconfig.json` — добавить `"jsx": "react-jsx"`

### Удаляются (после успешного build R1)

- `web/admin/src/main.ts`
- `web/admin/src/lib/{api.ts,dom.ts,toast.ts,state.ts,registry.ts,router.ts}` (старые)
- `web/admin/src/components/` (modal, table, detail-shell, ...)
- `web/admin/src/entities/` (все 8 entity-файлов)
- `web/admin/src/lib/types.ts` (заменён на re-export из @shared)

### Сохраняется

- `web/admin/src/style.css` — переносится 1-в-1, классы те же
- `web/admin/src/vite-env.d.ts`

---

## Task 1: Backup + install React deps

- [ ] **Step 1: Backup**

```bash
mkdir -p _backup-pre-r1
cp -r web/admin/src _backup-pre-r1/web-admin-src
```

- [ ] **Step 2: Install React + ecosystem**

```bash
npm i react react-dom @tanstack/react-query @tanstack/react-query-devtools react-router-dom @radix-ui/react-dialog @radix-ui/react-dropdown-menu @radix-ui/react-select @radix-ui/react-tooltip @radix-ui/react-toast @radix-ui/react-tabs lucide-react
npm i -D @vitejs/plugin-react @types/react @types/react-dom
```

- [ ] **Step 3: Update vite.config.ts**

`web/admin/vite.config.ts` — добавить:
```ts
import react from '@vitejs/plugin-react';
// ...
export default defineConfig({
  // ... existing
  plugins: [react()],
});
```

- [ ] **Step 4: Update tsconfig.json**

`web/admin/tsconfig.json` — добавить в `compilerOptions`:
```json
"jsx": "react-jsx",
"jsxImportSource": "react"
```

- [ ] **Step 5: Verify**

```bash
node -e "require.resolve('react'); require.resolve('@tanstack/react-query'); console.log('OK')"
npm run admin:typecheck 2>&1 | tail -3
```

Expected: typecheck может ругаться на старые .ts файлы — это ОК, они уйдут в Task 11.

---

## Task 2: lib/api.ts + lib/format.ts + lib/types.ts re-export

- [ ] **Step 1: Создать lib/api.ts**

`web/admin/src/lib/api.ts`:
```ts
export class ApiError extends Error {
  status: number;
  details?: unknown;
  constructor(status: number, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: 'include',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const json = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, json?.error || res.statusText, json?.details);
  return json as T;
}
```

- [ ] **Step 2: Создать lib/format.ts**

`web/admin/src/lib/format.ts`:
```ts
export function fmtDate(s: string | Date | null | undefined): string {
  if (!s) return '—';
  const str = String(s);
  if (/^\d{4}-\d{2}-\d{2}$/.test(str)) {
    const [y, m, d] = str.split('-');
    return `${d}.${m}.${y}`;
  }
  const d = new Date(str);
  if (!isNaN(d.getTime())) {
    return d.toLocaleDateString('ru-RU', {
      timeZone: 'Europe/Moscow',
      day: '2-digit', month: '2-digit', year: 'numeric',
    });
  }
  return str;
}

export function escapeHtml(s: unknown): string {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string));
}
```

- [ ] **Step 3: Создать lib/types.ts re-export**

`web/admin/src/lib/types.ts`:
```ts
export * from '../../../../shared/types';
```

Через path alias не работает в Vite напрямую — используем относительный путь.

- [ ] **Step 4: Verify**

```bash
npm run admin:typecheck 2>&1 | tail -5
```

Expected: errors могут быть в старом коде, но lib/api.ts, format.ts, types.ts должны быть чистыми.

---

## Task 3: providers/QueryProvider.tsx + AuthProvider + ThemeProvider

- [ ] **Step 1: QueryProvider**

`web/admin/src/providers/QueryProvider.tsx`:
```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { type ReactNode, useState } from 'react';

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        retry: (count, err: any) => {
          if (err?.status === 401 || err?.status === 404) return false;
          return count < 1;
        },
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
    },
  }));
  return (
    <QueryClientProvider client={client}>
      {children}
      {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  );
}
```

- [ ] **Step 2: AuthProvider**

`web/admin/src/providers/AuthProvider.tsx`:
```tsx
import { createContext, useState, useEffect, type ReactNode } from 'react';
import { api, ApiError } from '../lib/api';

export interface AuthState {
  authenticated: boolean | null; // null = loading
  user: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthState>(null!);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [user, setUser] = useState<string | null>(null);

  useEffect(() => {
    api('GET', '/api/admin/teachers').then(
      () => { setAuthenticated(true); setUser('admin'); },
      (e) => {
        if (e instanceof ApiError && e.status === 401) setAuthenticated(false);
        else { console.error(e); setAuthenticated(false); }
      },
    );
  }, []);

  const login = async (username: string, password: string) => {
    await api('POST', '/api/admin/login', { username, password });
    setAuthenticated(true);
    setUser(username);
  };

  const logout = async () => {
    try { await api('POST', '/api/admin/logout'); } catch (_) {}
    setAuthenticated(false);
    setUser(null);
  };

  return <AuthContext.Provider value={{ authenticated, user, login, logout }}>{children}</AuthContext.Provider>;
}
```

- [ ] **Step 3: useAuth hook**

`web/admin/src/hooks/useAuth.ts`:
```ts
import { useContext } from 'react';
import { AuthContext } from '../providers/AuthProvider';
export function useAuth() { return useContext(AuthContext); }
```

- [ ] **Step 4: ThemeProvider**

`web/admin/src/providers/ThemeProvider.tsx`:
```tsx
import { createContext, useState, useEffect, useContext, type ReactNode } from 'react';

type Theme = 'light' | 'dark';
const ThemeContext = createContext<{ theme: Theme; toggle: () => void }>(null!);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() =>
    (localStorage.getItem('kotokod-theme') as Theme) || 'light'
  );
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('kotokod-theme', theme);
  }, [theme]);
  const toggle = () => setTheme((t) => t === 'light' ? 'dark' : 'light');
  return <ThemeContext.Provider value={{ theme, toggle }}>{children}</ThemeContext.Provider>;
}

export function useTheme() { return useContext(ThemeContext); }
```

- [ ] **Step 5: Verify**

```bash
npm run admin:typecheck 2>&1 | tail -3
```

---

## Task 4: components/shell/* (AppShell, Sidebar, AuthGate, ScrollTopButton, ThemeToggle)

- [ ] **Step 1: Sidebar (с навигацией на 8 секций)**

`web/admin/src/components/shell/Sidebar.tsx` — NavLink-и из react-router-dom с активным состоянием. Подробнее в exec.

- [ ] **Step 2: AppShell**

Layout: aside.sidebar + main.main с `<Outlet />` из react-router-dom.

- [ ] **Step 3: AuthGate**

Проверяет `auth.authenticated`:
- `null` → loading spinner
- `false` → `<Navigate to="/login" />`
- `true` → `<Outlet />`

- [ ] **Step 4: ScrollTopButton + ThemeToggle**

ScrollTopButton — porт из текущего main.ts.
ThemeToggle — кнопка использует `useTheme().toggle`.

- [ ] **Step 5: Verify**

```bash
npm run admin:typecheck 2>&1 | tail -3
```

(Полный код — см. Task brief для subagent)

---

## Task 5: pages/LoginPage.tsx

- [ ] **Step 1: Создать LoginPage**

`web/admin/src/pages/LoginPage.tsx` — форма из 2 полей, useState для username/password, useAuth().login, navigate('/admin/students') при успехе, обработка 401/400 с toast.

- [ ] **Step 2: Verify typecheck**

---

## Task 6: 8 stub pages для каждой сущности

- [ ] **Step 1: Создать минимальные stubs**

Каждая страница:
```tsx
export default function <Entity>ListPage() {
  return (
    <div>
      <div className="section-header">
        <span className="section-title">{label}</span>
      </div>
      <div className="memberships__empty">R2 in progress</div>
    </div>
  );
}
```

8 файлов: students, groups, teachers, tokens, directions, lessons, payroll, archive.

---

## Task 7: App.tsx (Routes)

- [ ] **Step 1: Создать App.tsx**

`web/admin/src/App.tsx`:
```tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthGate } from './components/shell/AuthGate';
import { AppShell } from './components/shell/AppShell';
import { LoginPage } from './pages/LoginPage';
import StudentsListPage from './pages/students/StudentsListPage';
// ... etc.

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<AuthGate />}>
          <Route element={<AppShell />}>
            <Route path="/admin/students" element={<StudentsListPage />} />
            <Route path="/admin/groups" element={<GroupsListPage />} />
            {/* ... 8 routes */}
            <Route path="/admin" element={<Navigate to="/admin/students" replace />} />
            <Route path="*" element={<Navigate to="/admin/students" replace />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
```

---

## Task 8: main.tsx (entry)

- [ ] **Step 1: Создать main.tsx**

`web/admin/src/main.tsx`:
```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { App } from './App';
import { QueryProvider } from './providers/QueryProvider';
import { AuthProvider } from './providers/AuthProvider';
import { ThemeProvider } from './providers/ThemeProvider';

createRoot(document.getElementById('app')!).render(
  <StrictMode>
    <QueryProvider>
      <ThemeProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ThemeProvider>
    </QueryProvider>
  </StrictMode>
);
```

- [ ] **Step 2: Update index.html**

`web/admin/index.html` — изменить `<script>`:
```html
<script type="module" src="/src/main.tsx"></script>
```

---

## Task 9: Delete old TS code

После того как build проходит:

- [ ] **Step 1: Удалить старые файлы**

```bash
rm -rf web/admin/src/components/modal.ts web/admin/src/components/table.ts web/admin/src/components/detail-shell.ts
rm -rf web/admin/src/entities/
rm -f web/admin/src/main.ts web/admin/src/lib/registry.ts web/admin/src/lib/router.ts web/admin/src/lib/state.ts web/admin/src/lib/dom.ts web/admin/src/lib/toast.ts
```

⚠️ НЕ удалять `web/admin/src/lib/api.ts`, `lib/format.ts`, `lib/types.ts` (это новый код)
⚠️ НЕ удалять `style.css`, `vite-env.d.ts`

- [ ] **Step 2: Build + typecheck**

```bash
npm run admin:typecheck 2>&1 | tail -3
npm run admin:build 2>&1 | tail -6
```

---

## Task 10: Verify + smoke

- [ ] **Step 1: Restart server**

PowerShell-команды для рестарта.

- [ ] **Step 2: Browser smoke**

- `/admin/` → редирект на `/admin/students` после логина
- Логин корректный → sidebar появляется
- Клик по любой секции → URL меняется, stub-страница рендерится
- Theme toggle работает
- Logout → возврат на /login
- Не залогинен + переход на `/admin/students` → редирект на `/login`

- [ ] **Step 3: 77 backend-тестов всё ещё зелёные**

```bash
npm test 2>&1 | tail -3
```

---

## Acceptance criteria

R1 готов когда:

1. ✓ `npm run admin:build` без ошибок, bundle ~150-250 КБ (React + Radix + Query тянут ~80-100 КБ)
2. ✓ `npm run admin:typecheck` 0 ошибок
3. ✓ В браузере: login работает, навигация работает, theme toggle работает
4. ✓ Старый TS-код удалён из `web/admin/src/`
5. ✓ Backup сохранён в `_backup-pre-r1/web-admin-src/`
6. ✓ 77/77 backend тестов
