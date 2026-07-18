# Унификация пропусков — Фаза 1c-3 (фронт: блок карточек + «Сжечь»/«Откат сгорания») — Implementation Plan

> **For agentic workers:** фронт делается КОНТРОЛЛЕРОМ САМ (не субагентом) — риск dist-pollution. НЕ запускать `npm run build`. После каждой правки: `git status` показывает только `*-src/`, не `*-dist/`. Верификация — `tsc --noEmit = 0` обоих фронтов.

**Goal:** Довести UX сгорания до бэка 1c-2: в разделе «Доп.уроки» на `pending`-строке — кнопка «Сжечь» (рядом с «Назначить доп.урок»), на `burned`-строке — «Откат сгорания» + статус-лейбл; в `LessonEditor` убрать старый burn-тоггл (`togglePresent → burnConfirm`) и триггер `AssignExtraLessonModal` из грида, а карточки посещаемости сохранённого урока сделать нередактируемыми (отсутствовавшие — серые). Всё про пропуск — только через раздел.

**Architecture:** Только admin-фронт (teacher SPA сгорание не показывает — grep по `burn/Сжечь/сгор` в `teacher-src` пуст, менять нечего). `burned` — новый статус `AbsenceResolution`. Новая мутация `burn` в `useExtraLessons`. `LessonEditor` для СОХРАНЁННОГО урока становится read-only по посещаемости (в новой модели посещаемость завершённого урока — свершившийся факт; изменения пропуска идут через раздел). Для НОВОГО урока (lessonId===null) грид остаётся интерактивным.

**Tech Stack:** React 19 + TanStack Query v5 + TS (admin-src). Native form-элементы запрещены (не применимо здесь — только кнопки). tsc из `frontend/admin-src`.

---

## Ключевые решения 1c-3 (фикс)

1. **Сохранённый урок = посещаемость read-only.** После сохранения ВЕСЬ грид карточек нередактируем; отсутствовавшие (present=false) — серые/приглушённые. Убираем `togglePresent`/`confirmBurn`/burn-`Dialog` и «Назначить доп.урок»-триггер из футера `LessonEditor`. Ретроактивная правка посещаемости завершённого урока (в любую сторону) больше не поддерживается из редактора урока — компенсация/сжигание пропуска только из раздела «Доп.уроки». Новый урок (lessonId===null) — грид интерактивен как раньше.
2. **`handleSave` сохранённого урока** обновляет только `lesson_date`/`record_url` (петля `toggleAttendance` удаляется — посещаемость не меняется). Создание нового урока — без изменений.
3. **«Сжечь»** (pending) — с подтверждением в самой кнопке (паттерн `is-confirming`, как «Откатить»), т.к. списывает урок с баланса. Успех-тост «Пропуск сожжён…».
4. **«Откат сгорания»** (burned) — переиспользует существующую `remove`-мутацию (DELETE `/api/admin/extra-lessons/:id` уже обобщён на бэке 1c-2 на makeup_done|burned), с подтверждением.
5. **Статус-лейблы:** `burned → «Сгорел»` (STATUS_LABELS в списке). changelog-метка `extra_lesson.burn → «Сгорание пропуска»` (admin `lib/labels.ts`).

---

## Структура файлов (1c-3)

- `frontend/admin-src/src/lib/shared-types.ts:169` — `status` union += `'burned'`.
- `frontend/admin-src/src/lib/labels.ts` — `'extra_lesson.burn': 'Сгорание пропуска'`.
- `frontend/admin-src/src/hooks/useExtraLessons.ts` — мутация `burn`.
- `frontend/admin-src/src/pages/extra-lessons/ExtraLessonsListPage.tsx` — кнопка «Сжечь» (pending), «Откат сгорания» (burned), STATUS_LABELS += burned.
- `frontend/admin-src/src/components/lessons/LessonEditor.tsx` — убрать burn-тоггл/assign-триггер, read-only грид сохранённого урока.
- `frontend/admin-src/src/styles/*` — класс приглушённой/некликабельной карточки (design tokens).

---

## Task 1: Тип + метки (`burned`)

**Files:** `lib/shared-types.ts`, `lib/labels.ts`, `pages/extra-lessons/ExtraLessonsListPage.tsx`.

- [ ] **Step 1:** `shared-types.ts:169` — добавить `'burned'` в union:

```ts
  status: 'pending' | 'makeup_scheduled' | 'makeup_done' | 'burned';
```

- [ ] **Step 2:** `lib/labels.ts` — рядом с прочими `extra_lesson.*` (после `extra_lesson.record`):

```ts
  'extra_lesson.burn':             'Сгорание пропуска',
```

- [ ] **Step 3:** `ExtraLessonsListPage.tsx` — STATUS_LABELS += burned:

```ts
const STATUS_LABELS: Record<string, string> = {
  pending: 'Ждёт решения',
  makeup_scheduled: 'Назначен',
  makeup_done: 'Проведён',
  burned: 'Сгорел',
};
```

- [ ] **Step 4:** tsc: `cd frontend/admin-src && npx tsc --noEmit` → 0 ошибок. Commit `feat(absences): burned status/label on admin front (Phase 1c-3 Task 1)`.

---

## Task 2: Мутация `burn` в `useExtraLessons`

**Files:** `hooks/useExtraLessons.ts`.

- [ ] **Step 1:** В `useExtraLessonMutations` добавить `burn` (POST, без тела; ответ `{lesson_id, payment}` — типизируем узко):

```ts
    burn: useMutation({
      mutationFn: (id: number) =>
        api<{ lesson_id: number; payment: number }>('POST', `/api/admin/extra-lessons/${id}/burn`),
      onSuccess: invalidate,
    }),
```

(Ставить рядом с `cancel`/`remove`; `invalidate` уже сбрасывает extra-lessons/lessons/memberships/calendar — сгорание двигает и баланс, и продления, этого достаточно.)

- [ ] **Step 2:** tsc → 0. Commit `feat(absences): burn mutation hook (Phase 1c-3 Task 2)`.

---

## Task 3: Кнопки «Сжечь» / «Откат сгорания» в разделе

**Files:** `pages/extra-lessons/ExtraLessonsListPage.tsx`.

- [ ] **Step 1:** Добавить состояние подтверждения сжигания и хэндлеры (рядом с `confirmingRollbackId`):

```ts
  const [confirmingBurnId, setConfirmingBurnId] = useState<number | null>(null);
```

```ts
  const handleBurn = async (id: number) => {
    if (confirmingBurnId !== id) {
      setConfirmingBurnId(id);
      return;
    }
    try {
      await muts.burn.mutateAsync(id);
      toast('Пропуск сожжён, урок списан с баланса', 'ok');
    } catch (err) { showError(err); }
    setConfirmingBurnId(null);
  };
```

- [ ] **Step 2:** В колонке `actions`, ветка `pending` — добавить «Сжечь» рядом с «Назначить доп.урок» (обернуть в фрагмент):

```tsx
        if (r.status === 'pending') {
          const burning = confirmingBurnId === r.id;
          return (
            <div className="table-actions">
              <button type="button" className="btn-primary" onClick={() => setAssigning(r)}>
                Назначить доп.урок
              </button>
              <button
                type="button"
                className={`btn-delete${burning ? ' is-confirming' : ''}`}
                onClick={() => { void handleBurn(r.id); }}
              >
                {burning ? 'Точно сжечь?' : 'Сжечь'}
              </button>
            </div>
          );
        }
```

- [ ] **Step 3:** Добавить ветку `burned` (после `makeup_done`), «Откат сгорания» через ту же `remove`-мутацию/`handleRollback` (уже сбрасывает `confirmingRollbackId`, тост подходящий — но для burned дадим свой тост; проще: отдельная ветка, reuse `handleRollback` с общим тостом «Факт удалён…»). Реализация — отдельная ветка с собственным подтверждением:

```tsx
        if (r.status === 'burned') {
          const confirming = confirmingRollbackId === r.id;
          return (
            <button
              type="button"
              className={`btn-delete${confirming ? ' is-confirming' : ''}`}
              onClick={() => { void handleRollback(r.id); }}
            >
              {confirming ? 'Точно откатить?' : 'Откат сгорания'}
            </button>
          );
        }
```

(`handleRollback` уже вызывает `muts.remove` (DELETE) — на бэке 1c-2 он откатывает и burned. Тост «Факт доп.урока удалён…» для сгорания не идеален, но приемлем; при желании — обобщить текст до «Факт удалён, пропуск снова ждёт решения».)

- [ ] **Step 4:** Обобщить тост `handleRollback` (покрывает makeup_done и burned):

```ts
      toast('Факт удалён, пропуск снова ждёт решения', 'ok');
```

- [ ] **Step 5:** `.table-actions` — если класса нет в стилях, добавить (flex, gap токен). Проверить существование; если есть аналог (`.btn-row`/`.actions-cell`) — переиспользовать, не плодить.

- [ ] **Step 6:** tsc → 0. Commit `feat(absences): burn + unburn buttons in section (Phase 1c-3 Task 3)`.

---

## Task 4: `LessonEditor` — убрать burn-тоггл/assign-триггер, read-only грид сохранённого урока

**Files:** `components/lessons/LessonEditor.tsx`.

- [ ] **Step 1: Удалить** состояние/логику сгорания и назначения из грида:
  - state: `savedPresent`, `burnConfirmStudentId`, `assigningExtra`;
  - функции `togglePresent` (заменить), `confirmBurn`;
  - импорты `Dialog`, `AssignExtraLessonModal`, `fmtDate`, функцию `currentMonthLabel`;
  - блок `{assigningExtra && ...}`, блок `{burnConfirmStudentId !== null && ...}` (весь Dialog);
  - футер-кнопку «Назначить доп.урок».

- [ ] **Step 2: Read-only грид для сохранённого урока.** `const locked = !!lesson;` Карточка:

```tsx
          {members.length ? members.map((m) => {
            const isPresent = !!present[m.student_id];
            return (
              <button
                key={m.student_id}
                type="button"
                className={`attendance-card ${isPresent ? 'is-present' : 'is-absent'}${locked ? ' is-locked' : ''}`}
                onClick={locked ? undefined : () => setPresent((p) => ({ ...p, [m.student_id]: !p[m.student_id] }))}
                disabled={locked}
                aria-disabled={locked}
              >
                <span className="attendance-card__icon" aria-hidden>{isPresent ? '✓' : '✕'}</span>
                <span className="attendance-card__name">{m.student_name || `#${m.student_id}`}</span>
              </button>
            );
          }) : (
            <div className="memberships__empty">В группе нет учеников</div>
          )}
```

Подсказку «(клик по карточке — переключение)» показывать только для нового урока:

```tsx
          Посещаемость {!locked && <span className="lesson-editor__hint">(клик по карточке — переключение)</span>}
```

- [ ] **Step 3: `handleSave`** для сохранённого урока — только date/url (убрать петлю `toggleAttendance`):

```ts
      if (lesson) {
        await muts.update.mutateAsync({
          id: lesson.id,
          body: { lesson_date: date, record_url: url },
        });
        toast('Сохранено', 'ok');
      } else {
        // ... создание нового урока без изменений ...
      }
```

Убрать `muts.toggleAttendance` из `disabled` кнопки сохранения (больше не используется здесь):

```tsx
          disabled={muts.create.isPending || muts.update.isPending || muts.remove.isPending}
```

- [ ] **Step 4:** Инициализация: `savedPresent` больше не нужен — убрать оба `setSavedPresent`. `present` для сохранённого урока инициализируется из `lesson.attendance` (как есть).

- [ ] **Step 5:** tsc → 0 (проверить, что не осталось неиспользуемых импортов/переменных — `noUnusedLocals` уронит сборку). Commit `feat(absences): lock attendance grid after save, drop burn-toggle (Phase 1c-3 Task 4)`.

---

## Task 5: Стиль заблокированной/серой карточки

**Files:** `frontend/admin-src/src/styles/*` (найти, где определён `.attendance-card`).

- [ ] **Step 1:** Найти `.attendance-card` (grep). Добавить `.attendance-card.is-locked`: `cursor: default; opacity` из токена/приглушение; `.attendance-card.is-absent.is-locked` — серый нейтральный фон (design tokens `tokens.css`, НЕ hardcode цвет). Отсутствовавшие после блокировки читаемо «серые».
- [ ] **Step 2:** tsc не затрагивает CSS; визуально соответствует spec «серые, не кликаются». Commit `style(absences): locked attendance card styles (Phase 1c-3 Task 5)`.

---

## Task 6: Финальная верификация

- [ ] **Step 1:** `cd frontend/admin-src && npx tsc --noEmit` → 0. (teacher-src не менялся; при желании прогнать `cd frontend/teacher-src && npx tsc --noEmit` → 0 для страховки.)
- [ ] **Step 2:** `git status --short` — изменения ТОЛЬКО в `frontend/admin-src/src/`, никакого `*-dist/` / `web/` / `public/` (dist-pollution). Если появился билд-артефакт — откатить его, не коммитить.
- [ ] **Step 3:** Прогнать backend changelog-тест меток (метка `extra_lesson.burn` должна резолвиться, если есть тест покрытия): `.venv/Scripts/python.exe -m pytest apps/changelog/ -q`.
- [ ] **Step 4:** STOP — доложить пользователю: 1c-3 готова, вся Фаза 1c закрыта. Дальше — Фаза 2 (физ. удаление мёртвого кода + миграция исторических burned_at), отдельным writing-plan.

---

## Self-Review (по спеке)

- **Спека «Блокировка ячеек» → серые некликабельные после сохранения** → Task 4 (`is-locked`, `disabled`) + Task 5 (стиль). ✅
- **Спека → удалить burn-тоггл (togglePresent→burnConfirm) и assign-триггер из грида** → Task 4 Step 1. ✅
- **Спека «Затронутые файлы (фронт)» → кнопки «Сжечь»/«Откат», статусы** → Task 3. ✅
- **shared-types/labels — статус burned** → Task 1. ✅
- **teacher-фронт — сгорание** → grep пуст, менять нечего (зафиксировано). ✅
- **НЕ запускать npm run build (dist-pollution [[feedback_subagent_npm_build_dist_pollution]])** → Task 6 Step 2. ✅
- **«Откат сгорания» использует уже обобщённый DELETE** → Task 3 (reuse `remove`). ✅
