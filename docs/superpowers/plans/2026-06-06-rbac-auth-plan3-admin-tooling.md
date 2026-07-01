# RBAC + унифицированный вход — План 3: Admin tooling + compliance

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать admin UI для управления учётками (создание, токен-пароль, сброс 2FA, деактивация), просмотра журнала событий ИБ, фиксации согласия на ПДн у ученика; обновить навигацию и документацию.

**Architecture:** React 19 + TanStack Query (рецепт проекта: хук `useXxx` + `useXxxMutations`). Страницы `accounts/`, `audit/` под admin-ролью. Блок согласия на карточке ученика поверх существующих students-API.

**Tech Stack:** React 19, TanStack Query v5, React Router v7, существующие компоненты `components/ui`/`form`.

**Зависит от:** Планов 1 (эндпоинты `/api/admin/accounts`, `/api/admin/audit-log`) и 2 (AuthProvider `me`). **Спека:** `docs/superpowers/specs/2026-06-06-rbac-unified-auth-design.md`.

**git:** репозиторий пока без git — `git commit` = чекпойнт.

---

### Task 1: Типы для учёток и аудита

**Files:**
- Modify: `web/admin/src/lib/types.ts` (или `shared/types.ts` + re-export)

- [ ] **Step 1: Добавить типы**

```ts
export type Role = 'teacher' | 'manager' | 'admin';

export interface Account {
  id: number;
  email: string;
  role: Role;
  teacher_id: number | null;
  teacher_name?: string | null;
  active: boolean;
  twofa_enabled: boolean;
  twofa_method: 'totp' | 'email' | null;
  last_login_at: string | null;
}

export interface AuditEntry {
  id: number;
  occurred_at: string;
  account_id: number | null;
  account_email?: string | null;
  actor_email: string | null;
  event: string;
  ip: string | null;
  target_id: number | null;
  meta: unknown;
}

export interface Paginated<T> { rows: T[]; total: number; page: number; page_size: number; }
```
(Если `Paginated<T>` уже есть в проекте — не дублировать.)

- [ ] **Step 2: typecheck**

Run: `npm run admin:typecheck`
Expected: без ошибок.

- [ ] **Step 3: Commit**

```bash
git add web/admin/src/lib/types.ts
git commit -m "feat(admin-spa): Account/AuditEntry types"
```

---

### Task 2: Хуки useAccounts / useAccountMutations / useAudit

**Files:**
- Create: `web/admin/src/hooks/useAccounts.ts`
- Create: `web/admin/src/hooks/useAudit.ts`

- [ ] **Step 1: useAccounts.ts**

```ts
import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Account, Paginated, Role } from '../lib/types';

const KEY = ['accounts'] as const;

export function useAccounts(query: string) {
  return useQuery({
    queryKey: [...KEY, query],
    queryFn: () => api<Paginated<Account>>('GET', `/api/admin/accounts${query}`),
    placeholderData: keepPreviousData,
  });
}

export interface CreatedAccount { id: number; email: string; role: Role; teacher_id: number | null; password: string; }

export function useAccountMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: KEY });
  return {
    create: useMutation({
      mutationFn: (body: { email: string; role: Role; teacher_id: number | null }) =>
        api<CreatedAccount>('POST', '/api/admin/accounts', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Partial<Pick<Account, 'email' | 'role' | 'active'>> }) =>
        api<Account>('PATCH', `/api/admin/accounts/${id}`, body),
      onSuccess: invalidate,
    }),
    resetPassword: useMutation({
      mutationFn: (id: number) => api<{ password: string }>('POST', `/api/admin/accounts/${id}/reset-password`),
      onSuccess: invalidate,
    }),
    reset2fa: useMutation({
      mutationFn: (id: number) => api<{ ok: true }>('POST', `/api/admin/accounts/${id}/reset-2fa`),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<void>('DELETE', `/api/admin/accounts/${id}`),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Step 2: useAudit.ts**

```ts
import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { AuditEntry, Paginated } from '../lib/types';

export function useAudit(query: string) {
  return useQuery({
    queryKey: ['audit', query],
    queryFn: () => api<Paginated<AuditEntry>>('GET', `/api/admin/audit-log${query}`),
    placeholderData: keepPreviousData,
  });
}
```

- [ ] **Step 3: typecheck + commit**

Run: `npm run admin:typecheck`
Expected: чисто.
```bash
git add web/admin/src/hooks/useAccounts.ts web/admin/src/hooks/useAudit.ts
git commit -m "feat(admin-spa): accounts/audit query hooks"
```

---

### Task 3: Страница учёток (список + создание + действия)

**Files:**
- Create: `web/admin/src/pages/accounts/AccountsPage.tsx`

> Используем `useListSearchParams` (URL-state) как другие списки. Таблица — через существующий `DataTable` (см. `StudentsListPage` для точного API серверного режима) ИЛИ простой `<table className="data-table">`. Ниже — самодостаточный вариант на простой таблице + модалка создания.

- [ ] **Step 1: Реализовать AccountsPage.tsx**

```tsx
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAccounts, useAccountMutations } from '../../hooks/useAccounts';
import { useTeachersAll } from '../../hooks/useTeachers'; // если нет — заменить на useTeachers
import type { Role } from '../../lib/types';
import { Dialog } from '../../components/ui/Dialog';
import { Combobox } from '../../components/form/Combobox';
import { SelectInput } from '../../components/form/SelectInput';
import { TextInput } from '../../components/form/TextInput';

const ROLE_OPTIONS = [
  { value: 'teacher', label: 'Преподаватель' },
  { value: 'manager', label: 'Менеджер' },
  { value: 'admin', label: 'Админ' },
];

export default function AccountsPage() {
  const [sp] = useSearchParams();
  const query = `?${sp.toString()}`;
  const { data, isLoading } = useAccounts(query);
  const m = useAccountMutations();
  const [showCreate, setShowCreate] = useState(false);
  const [secret, setSecret] = useState<string | null>(null); // показанный один раз пароль

  const onResetPassword = async (id: number) => {
    const r = await m.resetPassword.mutateAsync(id);
    setSecret(r.password);
  };

  return (
    <div className="page">
      <div className="page-head">
        <h1>Учётки и доступы</h1>
        <button className="btn btn--primary" onClick={() => setShowCreate(true)}>+ Новая учётка</button>
      </div>

      {isLoading ? <div className="muted">Загрузка…</div> : (
        <table className="data-table">
          <thead><tr>
            <th>Email</th><th>Роль</th><th>Преподаватель</th><th>2FA</th><th>Статус</th><th></th>
          </tr></thead>
          <tbody>
            {data?.rows.map((a) => (
              <tr key={a.id}>
                <td className="mono">{a.email}</td>
                <td>{a.role}</td>
                <td>{a.teacher_name || '—'}</td>
                <td>{a.twofa_enabled ? (a.twofa_method ?? 'on') : '—'}</td>
                <td>{a.active ? 'активна' : 'выключена'}</td>
                <td className="row-actions">
                  <button className="btn btn--sm" onClick={() => onResetPassword(a.id)}>Сброс пароля</button>
                  <button className="btn btn--sm" onClick={() => m.reset2fa.mutate(a.id)}>Сброс 2FA</button>
                  {a.active && <button className="btn btn--sm btn--danger" onClick={() => m.remove.mutate(a.id)}>Выключить</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showCreate && <CreateModal onClose={() => setShowCreate(false)} onCreated={(pw) => { setShowCreate(false); setSecret(pw); }} />}
      {secret && (
        <Dialog open onClose={() => setSecret(null)} title="Пароль создан">
          <p>Скопируйте — показывается один раз:</p>
          <pre className="recovery-code">{secret}</pre>
          <button className="btn btn--primary" onClick={() => setSecret(null)}>Готово</button>
        </Dialog>
      )}
    </div>
  );
}

function CreateModal({ onClose, onCreated }: { onClose: () => void; onCreated: (pw: string) => void }) {
  const m = useAccountMutations();
  const { data: teachers } = useTeachersAll();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>('teacher');
  const [teacherId, setTeacherId] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setErr(null);
    try {
      const r = await m.create.mutateAsync({ email, role, teacher_id: role === 'teacher' ? teacherId : null });
      onCreated(r.password);
    } catch (e) { setErr((e as Error).message); }
  };

  return (
    <Dialog open onClose={onClose} title="Новая учётка">
      <div className="form-grid">
        <TextInput label="Email" value={email} onChange={(e) => setEmail(e.target.value)} type="email" />
        <SelectInput label="Роль" value={role} options={ROLE_OPTIONS} onChange={(e) => setRole(e.target.value as Role)} />
        {role === 'teacher' && (
          <Combobox
            label="Преподаватель"
            value={teacherId ?? undefined}
            options={(teachers ?? []).map((t) => ({ value: t.id, label: t.name }))}
            onChange={(v) => setTeacherId(v as number)}
          />
        )}
        {err && <div className="err">{err}</div>}
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>Отмена</button>
          <button className="btn btn--primary" onClick={submit} disabled={!email}>Создать</button>
        </div>
      </div>
    </Dialog>
  );
}
```

> ⚠️ Сверить точные пропсы `Dialog`/`SelectInput`/`Combobox`/`TextInput` с существующими компонентами (`components/ui`, `components/form`) и `useTeachersAll`/`useTeachers` — подставить фактические имена/сигнатуры. Логика остаётся прежней.

- [ ] **Step 2: typecheck**

Run: `npm run admin:typecheck`
Expected: чисто (после подгонки пропсов под реальные компоненты).

- [ ] **Step 3: Commit**

```bash
git add web/admin/src/pages/accounts/AccountsPage.tsx
git commit -m "feat(admin-spa): accounts management page"
```

---

### Task 4: Страница журнала ИБ (audit-log)

**Files:**
- Create: `web/admin/src/pages/audit/AuditPage.tsx`

- [ ] **Step 1: Реализовать AuditPage.tsx**

```tsx
import { useSearchParams } from 'react-router-dom';
import { useAudit } from '../../hooks/useAudit';
import { fmtDate } from '../../lib/format';

const EVENT_LABELS: Record<string, string> = {
  login_success: 'Вход', login_fail: 'Неуспешный вход', logout: 'Выход',
  '2fa_fail': 'Ошибка 2FA', '2fa_enabled': '2FA включена', '2fa_disabled': '2FA выключена',
  '2fa_reset': 'Сброс 2FA', account_created: 'Учётка создана', password_reset: 'Сброс пароля',
  account_deactivated: 'Учётка выключена', locked: 'Блокировка',
};

export default function AuditPage() {
  const [sp] = useSearchParams();
  const { data, isLoading } = useAudit(`?${sp.toString()}`);
  return (
    <div className="page">
      <div className="page-head"><h1>Журнал безопасности</h1></div>
      {isLoading ? <div className="muted">Загрузка…</div> : (
        <table className="data-table">
          <thead><tr><th>Время</th><th>Событие</th><th>Учётка</th><th>IP</th></tr></thead>
          <tbody>
            {data?.rows.map((e) => (
              <tr key={e.id}>
                <td className="mono">{new Date(e.occurred_at).toLocaleString('ru-RU')}</td>
                <td>{EVENT_LABELS[e.event] || e.event}</td>
                <td className="mono">{e.account_email || e.actor_email || '—'}</td>
                <td className="mono">{e.ip || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
```
(`fmtDate` импорт можно убрать, если не используется — оставлен на случай форматирования.)

- [ ] **Step 2: typecheck + commit**

Run: `npm run admin:typecheck`
```bash
git add web/admin/src/pages/audit/AuditPage.tsx
git commit -m "feat(admin-spa): security audit-log page"
```

---

### Task 5: Навигация + роуты (admin-only) + Sidebar на me

**Files:**
- Modify: `web/admin/src/components/shell/Sidebar.tsx`
- Modify: `web/admin/src/App.tsx`

- [ ] **Step 1: Sidebar — перевести на `me`, добавить пункты accounts/audit (только admin)**

В `Sidebar.tsx`:
- Заменить `const { user, logout } = useAuth();` на `const { me, logout } = useAuth();`.
- Заменить `user || 'Admin'` на `me?.name || 'Admin'`, `user-role` текст — на `me?.role`.
- В массив `SECTIONS` (или отдельным блоком после `settings`) добавить admin-only пункты, отрисовывая их условно:
```tsx
{me?.role === 'admin' && (
  <>
    <div className="nav-sep" />
    <NavLink to="/admin/accounts" className={({isActive})=>`nav-btn${isActive?' active':''}`}>Учётки</NavLink>
    <NavLink to="/admin/audit" className={({isActive})=>`nav-btn${isActive?' active':''}`}>Журнал ИБ</NavLink>
  </>
)}
```
(Добавить иконки в `NAV_ICONS` по желанию — необязательно.)

- [ ] **Step 2: App.tsx — добавить роуты**

Импорты:
```tsx
import AccountsPage from './pages/accounts/AccountsPage';
import AuditPage from './pages/audit/AuditPage';
```
Внутри `<Route element={<AppShell />}>` добавить:
```tsx
<Route path="/admin/accounts" element={<AccountsPage />} />
<Route path="/admin/audit" element={<AuditPage />} />
```

- [ ] **Step 3: typecheck + build**

Run: `npm run admin:typecheck && npm run admin:build`
Expected: чисто, сборка ок.

- [ ] **Step 4: Commit**

```bash
git add web/admin/src/components/shell/Sidebar.tsx web/admin/src/App.tsx
git commit -m "feat(admin-spa): nav + routes for accounts/audit (admin-only)"
```

---

### Task 6: Согласие на ПДн у ученика (схема + repo + UI)

**Files:**
- Modify: `shared/schemas.js` (consent-поля в student-схеме)
- Modify: `services/repo/students.js` (updateStudent — consent-поля)
- Create: `web/admin/src/pages/students/ConsentBlock.tsx`
- Modify: `web/admin/src/pages/students/StudentDetailPage.tsx` (смонтировать блок)
- Modify: `services/audit.js` (использование — лог изменения согласия из роута students PATCH)

- [ ] **Step 1: Схема — добавить consent-поля в baseStudentObject**

В `shared/schemas.js`, в `baseStudentObject` добавить:
```js
  consent_given: z.boolean().optional(),
  consent_at: dateStr.nullable().optional(),
  consent_by: z.string().nullable().optional(),
  consent_note: z.string().nullable().optional(),
```

- [ ] **Step 2: Repo — updateStudent учитывает consent-поля**

В `services/repo/students.js`, в `updateStudent` добавить в SET (по образцу существующих COALESCE-полей):
```sql
       consent_given = COALESCE($X, consent_given),
       consent_at    = COALESCE($Y, consent_at),
       consent_by    = COALESCE($Z, consent_by),
       consent_note  = COALESCE($W, consent_note)
```
(подставить корректные номера параметров и передать значения `?? null`). Также добавить `consent_*` в `SELECT *`/маппинг, если репозиторий перечисляет колонки явно.

- [ ] **Step 3: ConsentBlock.tsx**

```tsx
import { useState } from 'react';
import { api } from '../../lib/api';
import { Checkbox } from '../../components/form/Checkbox';
import { TextInput } from '../../components/form/TextInput';
import { DateInput } from '../../components/form/DateInput';

interface Props {
  studentId: number;
  initial: { consent_given: boolean; consent_at: string | null; consent_by: string | null; consent_note: string | null };
  onSaved?: () => void;
}

export function ConsentBlock({ studentId, initial, onSaved }: Props) {
  const [given, setGiven] = useState(initial.consent_given);
  const [at, setAt] = useState(initial.consent_at ?? '');
  const [by, setBy] = useState(initial.consent_by ?? '');
  const [note, setNote] = useState(initial.consent_note ?? '');
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await api('PATCH', `/api/admin/students/${studentId}`, {
        consent_given: given, consent_at: at || null, consent_by: by || null, consent_note: note || null,
      });
      onSaved?.();
    } finally { setSaving(false); }
  };

  return (
    <section className="detail-block">
      <h3>Согласие на обработку ПДн</h3>
      <Checkbox label="Согласие получено" checked={given} onChange={setGiven} />
      <DateInput label="Дата согласия" value={at} onChange={setAt} />
      <TextInput label="Кто дал (родитель/представитель)" value={by} onChange={(e) => setBy(e.target.value)} />
      <TextInput label="Основание/примечание" value={note} onChange={(e) => setNote(e.target.value)} />
      <button className="btn btn--primary" onClick={save} disabled={saving}>Сохранить</button>
    </section>
  );
}
```
> ⚠️ Сверить пропсы `Checkbox`/`DateInput`/`TextInput` с фактическими компонентами проекта.

- [ ] **Step 4: Смонтировать ConsentBlock в StudentDetailPage**

В `StudentDetailPage.tsx` рядом с `BalanceBlock`/`StatsBlock` добавить:
```tsx
<ConsentBlock
  studentId={student.id}
  initial={{ consent_given: student.consent_given, consent_at: student.consent_at, consent_by: student.consent_by, consent_note: student.consent_note }}
/>
```
(добавить consent-поля в тип `Student` в `lib/types`/`shared/types.ts`.)

- [ ] **Step 5: typecheck + build + тесты бэка**

Run: `npm run admin:typecheck && npm run admin:build && npm test`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add shared/schemas.js services/repo/students.js web/admin/src/pages/students/ConsentBlock.tsx web/admin/src/pages/students/StudentDetailPage.tsx web/admin/src/lib/types.ts
git commit -m "feat(consent): student PDn consent fields + UI block"
```

---

### Task 7: Документация — CLAUDE.md, ROADMAP, чеклист

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/compliance-152fz-checklist.md` (отметить выполненные технические пункты)

- [ ] **Step 1: CLAUDE.md — отразить новую модель**

Добавить/обновить разделы:
- Таблица фаз: строка «RBAC + унифицированный вход (email+2FA, accounts, audit-log)» — ✅.
- Структура: `services/auth.js`, `services/twofa.js`, `services/mailer.js`, `services/audit.js`, `services/repo/accounts.js`/`audit.js`, `routes/auth.js`, `routes/admin/accounts.js`/`audit.js`, `public/login/`, `public/teacher/` (бывш. Index.html), `web/admin/src/pages/accounts|audit/`.
- Эндпоинты: добавить блок `/api/auth/*`; пометить teacher-эндпоинты как требующие сессию (роль teacher) и `/api/admin/*` — manager/admin (accounts/audit — admin).
- Соглашения: новый блок «Аутентификация и роли» (email-логин, единая cookie с ролью, 2FA TOTP/email, audit-log, hardening).
- Конфигурация: добавить `SMTP_*` в `.env`; пометить `ADMIN_USERNAME`/`ADMIN_PASSWORD_HASH` как deprecated.

- [ ] **Step 2: ROADMAP.md — закрыть пункт ролей**

Перенести 🟡-пункт «Роли + GET /api/admin/me» в «✅ Сделано» с пометкой про RBAC/2FA/audit. Phase 5 (выпил Sheets) пометить как **ИБ-релевантный** (локализация 242-ФЗ).

- [ ] **Step 3: Чеклист — отметить технические пункты**

В `docs/compliance-152fz-checklist.md` отметить `[x]` реализованные в коде технические меры (ИАФ/УПД/РСБ: 2FA, RBAC, audit-log, bcrypt, rate-limit; SMTP=Beget). Организационные пункты оставить `[ ]`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/ROADMAP.md docs/compliance-152fz-checklist.md
git commit -m "docs: update CLAUDE.md/ROADMAP/checklist for RBAC auth"
```

---

### Task 8: Финальная интеграционная проверка

- [ ] **Step 1: Полный прогон бэк-тестов**

Run: `npm test`
Expected: зелёно.

- [ ] **Step 2: Сборка фронта**

Run: `npm run admin:typecheck && npm run admin:build`
Expected: чисто.

- [ ] **Step 3: Ручной E2E admin-tooling**

Сценарий (admin вошёл):
1. `/admin/accounts` → создать учётку преподавателя → показан токен-пароль один раз.
2. Сброс пароля / сброс 2FA по строке.
3. `/admin/audit` → видны события (account_created, password_reset, login_success).
4. Карточка ученика → блок согласия → сохранить → перезагрузка сохраняет значения.

Expected: все действия работают, журнал отражает их без секретов.

- [ ] **Step 4: Commit (чекпойнт окончания Плана 3)**

```bash
git add -A
git commit -m "test: admin tooling + compliance E2E checkpoint (plan 3 complete)"
```

---

## Self-review (выполнено автором плана)

- **Покрытие спеки раздела 9 + ИБ:** типы (Task 1) ✓; хуки (Task 2) ✓; страница учёток с создание/токен-пароль/сброс-2FA/деактивация (Task 3) ✓; audit-log UI (Task 4) ✓; навигация admin-only + роуты (Task 5) ✓; consent в БД+UI (Task 6) ✓; доки/чеклист (Task 7) ✓.
- **Согласованность с Планами 1–2:** хуки бьют в `/api/admin/accounts`, `/api/admin/accounts/:id/reset-password|reset-2fa`, `/api/admin/audit-log` (План 1); используют `me` из AuthProvider (План 2); ответ create содержит `password` (План 1 Task 18).
- **Ручные моменты (помечены ⚠️):** точные пропсы UI-компонентов (`Dialog`/`SelectInput`/`Combobox`/`TextInput`/`Checkbox`/`DateInput`) и имя хука `useTeachersAll` — сверить с проектом; номера SQL-параметров в `updateStudent`.
- **Зависимости от организационных мер:** юридические пункты чеклиста остаются на владельце (вне кода).
```
