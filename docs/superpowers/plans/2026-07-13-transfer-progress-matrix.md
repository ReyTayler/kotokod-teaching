# Разметка перевода в матрице посещаемости — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** В матрице посещаемости группы (`GroupProgressView`, общая для admin и teacher SPA) закрасить пустые ячейки переведённого ученика статусом «Перевод», не трогая ни одной ячейки с реальной отметкой посещения.

**Architecture:** Backend — `apps.groups.repository.get_group_progress` считает `transferred_lessons`/`transferred_from_group_name` на лету по существующему `GroupMembership.transferred_from` (без новых полей в БД), добавляет их в ответ. Frontend — общий `GroupProgressView.tsx` для каждого ученика перед рендером ленты расходует «бюджет» `transferred_lessons` только на `cell === null`-позиции слева направо, никогда не перекрывая `true`/`false`.

**Tech Stack:** Django 5 / DRF (`journal_django/apps/groups`), React 19 (`journal_django/frontend/admin-src/src/shared/progress`, shared с teacher-src через алиас).

**Design doc:** [`docs/superpowers/specs/2026-07-13-transfer-progress-matrix-design.md`](../specs/2026-07-13-transfer-progress-matrix-design.md)

---

## Task 1: Backend — `transferred_lessons` в `get_group_progress`

**Files:**
- Modify: `journal_django/apps/groups/repository.py`
- Modify: `journal_django/apps/groups/tests/test_progress_api.py`

- [ ] **Step 1: Написать failing-тест**

В `journal_django/apps/groups/tests/test_progress_api.py` добавить новый тест-класс в конец файла:

```python


class TestTransferredLessons:
    """transferred_lessons/transferred_from_group_name в ответе матрицы."""

    def test_transferred_student_gets_capped_count(self, manager_client, progress_group):
        """
        Боря переведён из архивной группы того же направления, где отработал
        5 уроков (direction.total_lessons=8 в фикстуре progress_group) —
        transferred_lessons должен быть 5 (меньше total_slots=8, не капается).
        """
        gid = progress_group['group_id']
        with connection.cursor() as cur:
            cur.execute(
                "SELECT direction_id, teacher_id FROM groups WHERE id = %s", [gid],
            )
            direction_id, teacher_id = cur.fetchone()
            cur.execute(
                "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                "lesson_duration_minutes,active) VALUES ('__pg_old_g__',%s,%s,false,60,false) "
                "RETURNING id",
                [direction_id, teacher_id],
            )
            old_group_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                "VALUES (%s,%s,5,false) RETURNING id",
                [old_group_id, progress_group['borya']],
            )
            old_membership_id = cur.fetchone()[0]
            cur.execute(
                "UPDATE group_memberships SET transferred_from_id = %s "
                "WHERE group_id = %s AND student_id = %s",
                [old_membership_id, gid, progress_group['borya']],
            )
        try:
            body = manager_client.get(_url(gid)).json()
            rows = {r['student_id']: r for r in body['students']}
            borya = rows[progress_group['borya']]
            assert borya['transferred_lessons'] == 5
            assert borya['transferred_from_group_name'] == '__pg_old_g__'

            anya = rows[progress_group['anya']]
            assert anya['transferred_lessons'] == 0
            assert anya['transferred_from_group_name'] is None
        finally:
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE group_memberships SET transferred_from_id = NULL "
                    "WHERE group_id = %s AND student_id = %s",
                    [gid, progress_group['borya']],
                )
                cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [old_group_id])
                cur.execute('DELETE FROM groups WHERE id = %s', [old_group_id])

    def test_transferred_count_capped_at_total_slots(self, manager_client, progress_group):
        """
        Отработано в старой группе (20) больше, чем всего слотов в этой матрице
        (total_slots=8) — transferred_lessons не может превышать total_slots.
        """
        gid = progress_group['group_id']
        with connection.cursor() as cur:
            cur.execute(
                "SELECT direction_id, teacher_id FROM groups WHERE id = %s", [gid],
            )
            direction_id, teacher_id = cur.fetchone()
            cur.execute(
                "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                "lesson_duration_minutes,active) VALUES ('__pg_old_g2__',%s,%s,false,60,false) "
                "RETURNING id",
                [direction_id, teacher_id],
            )
            old_group_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                "VALUES (%s,%s,20,false) RETURNING id",
                [old_group_id, progress_group['anya']],
            )
            old_membership_id = cur.fetchone()[0]
            cur.execute(
                "UPDATE group_memberships SET transferred_from_id = %s "
                "WHERE group_id = %s AND student_id = %s",
                [old_membership_id, gid, progress_group['anya']],
            )
        try:
            body = manager_client.get(_url(gid)).json()
            rows = {r['student_id']: r for r in body['students']}
            assert rows[progress_group['anya']]['transferred_lessons'] == 8
        finally:
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE group_memberships SET transferred_from_id = NULL "
                    "WHERE group_id = %s AND student_id = %s",
                    [gid, progress_group['anya']],
                )
                cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [old_group_id])
                cur.execute('DELETE FROM groups WHERE id = %s', [old_group_id])

    def test_half_lesson_floored(self, manager_client, progress_group):
        """lessons_done=4.5 в старой группе → transferred_lessons=4 (floor, не round)."""
        gid = progress_group['group_id']
        with connection.cursor() as cur:
            cur.execute(
                "SELECT direction_id, teacher_id FROM groups WHERE id = %s", [gid],
            )
            direction_id, teacher_id = cur.fetchone()
            cur.execute(
                "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                "lesson_duration_minutes,active) VALUES ('__pg_old_g3__',%s,%s,false,45,false) "
                "RETURNING id",
                [direction_id, teacher_id],
            )
            old_group_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                "VALUES (%s,%s,4.5,false) RETURNING id",
                [old_group_id, progress_group['borya']],
            )
            old_membership_id = cur.fetchone()[0]
            cur.execute(
                "UPDATE group_memberships SET transferred_from_id = %s "
                "WHERE group_id = %s AND student_id = %s",
                [old_membership_id, gid, progress_group['borya']],
            )
        try:
            body = manager_client.get(_url(gid)).json()
            rows = {r['student_id']: r for r in body['students']}
            assert rows[progress_group['borya']]['transferred_lessons'] == 4
        finally:
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE group_memberships SET transferred_from_id = NULL "
                    "WHERE group_id = %s AND student_id = %s",
                    [gid, progress_group['borya']],
                )
                cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [old_group_id])
                cur.execute('DELETE FROM groups WHERE id = %s', [old_group_id])
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run (из `journal_django/`):
```bash
.venv/Scripts/python.exe -m pytest apps/groups/tests/test_progress_api.py -q -k Transferred
```
Expected: FAIL — `KeyError: 'transferred_lessons'` (поля ещё нет в ответе).

- [ ] **Step 3: Добавить поля в `get_group_progress`**

В `journal_django/apps/groups/repository.py`, найти определение `members` внутри `get_group_progress` (текущий код):
```python
    members = list(
        GroupMembership.objects
        .filter(group_id=group_id, active=True)
        .order_by('student__full_name')
        .values('student_id', name=F('student__full_name'))
    )
```
заменить на:
```python
    members = list(
        GroupMembership.objects
        .filter(group_id=group_id, active=True)
        .order_by('student__full_name')
        .values(
            'student_id', name=F('student__full_name'),
            transferred_from_id=F('transferred_from_id'),
            transferred_from_lessons_done=F('transferred_from__lessons_done'),
            transferred_from_group_name=F('transferred_from__group__name'),
        )
    )
```

Найти конец цикла построения строки ученика (текущий код):
```python
        students.append({
            'student_id': sid,
            'name': member['name'],
            'present': present,
            'held': held,
            'pct': round(present / held * 100) if held else 0,
            'cells': cells,
        })
```
заменить на:
```python
        transferred_lessons = 0
        transferred_from_group_name = None
        if member['transferred_from_id']:
            transferred_lessons = min(
                math.floor(float(member['transferred_from_lessons_done'] or 0)),
                slot_count,
            )
            if transferred_lessons > 0:
                transferred_from_group_name = member['transferred_from_group_name']

        students.append({
            'student_id': sid,
            'name': member['name'],
            'present': present,
            'held': held,
            'pct': round(present / held * 100) if held else 0,
            'cells': cells,
            'transferred_lessons': transferred_lessons,
            'transferred_from_group_name': transferred_from_group_name,
        })
```

(`math` уже импортирован в начале функции — `import math` на первой строке тела `get_group_progress`, используется дальше в `slot`-вычислениях.)

- [ ] **Step 4: Прогнать тесты, убедиться что проходят**

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/groups/tests/test_progress_api.py -q
```
Expected: PASS (весь файл, включая старые тесты — `test_no_n_plus_one` не должен сломаться: новые поля добавлены в ТОТ ЖЕ `.values()`-запрос `members`, лишнего запроса нет).

- [ ] **Step 5: Прогнать полный набор groups + teacher_spa на регрессию**

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/groups apps/teacher_spa -q
```
Expected: PASS, без регрессий (teacher_spa делегирует в тот же repository-метод, `GET /api/group-progress` должен отдавать те же новые поля автоматически).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/groups/repository.py journal_django/apps/groups/tests/test_progress_api.py
git commit -m "feat(groups): add transferred_lessons to group progress matrix"
```

---

## Task 2: Frontend — типы

**Files:**
- Modify: `journal_django/frontend/admin-src/src/shared/progress/types.ts`

- [ ] **Step 1: Добавить поля в `ProgressStudent`**

В `journal_django/frontend/admin-src/src/shared/progress/types.ts`:

Заменить:
```typescript
export interface ProgressStudent {
  student_id: number;
  name: string;
  present: number;
  held: number;
  pct: number;
  cells: (boolean | null)[];
}
```
на:
```typescript
export interface ProgressStudent {
  student_id: number;
  name: string;
  present: number;
  held: number;
  pct: number;
  cells: (boolean | null)[];
  transferred_lessons: number;
  transferred_from_group_name: string | null;
}
```

- [ ] **Step 2: Typecheck**

Run (из `journal_django/frontend/admin-src`):
```bash
npm run typecheck
```
Expected: ошибки в `GroupProgressView.tsx` пока НЕ ожидаются (поля пока нигде не читаются) — если typecheck уже что-то ловит, разобраться перед следующей задачей.

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/shared/progress/types.ts
git commit -m "feat(admin-src): add transferred_lessons to ProgressStudent type"
```

---

## Task 3: Frontend — статус «Перевод» в `GroupProgressView`

**Files:**
- Modify: `journal_django/frontend/admin-src/src/shared/progress/GroupProgressView.tsx`

- [ ] **Step 1: Расширить `CellStatus` и лейблы**

В `journal_django/frontend/admin-src/src/shared/progress/GroupProgressView.tsx`, заменить:
```typescript
type CellStatus = 'present' | 'absent' | 'planned';

function cellStatus(cell: boolean | null): CellStatus {
  if (cell === true) return 'present';
  if (cell === false) return 'absent';
  return 'planned';
}

const STATUS_LABEL: Record<CellStatus, string> = {
  present: 'Был',
  absent: 'Не был',
  planned: 'Не проведён',
};
```
на:
```typescript
type CellStatus = 'present' | 'absent' | 'planned' | 'transferred';

function cellStatus(cell: boolean | null): CellStatus {
  if (cell === true) return 'present';
  if (cell === false) return 'absent';
  return 'planned';
}

const STATUS_LABEL: Record<CellStatus, string> = {
  present: 'Был',
  absent: 'Не был',
  planned: 'Не проведён',
  transferred: 'Перевод',
};
```

- [ ] **Step 2: Добавить чип в легенду**

Заменить:
```tsx
          <span className="progress-legend__item"><span className="progress-chip is-present" />Был</span>
          <span className="progress-legend__item"><span className="progress-chip is-absent" />Не был</span>
          <span className="progress-legend__item"><span className="progress-chip is-planned" />Не проведён</span>
```
на:
```tsx
          <span className="progress-legend__item"><span className="progress-chip is-present" />Был</span>
          <span className="progress-legend__item"><span className="progress-chip is-absent" />Не был</span>
          <span className="progress-legend__item"><span className="progress-chip is-planned" />Не проведён</span>
          <span className="progress-legend__item"><span className="progress-chip is-transferred" />Перевод</span>
```

- [ ] **Step 3: Расширить `TipState` полем группы-источника**

Заменить:
```typescript
interface TipState {
  slot: number;
  status: CellStatus;
  date: string | null;
  x: number;
  y: number;
}
```
на:
```typescript
interface TipState {
  slot: number;
  status: CellStatus;
  date: string | null;
  transferredFromGroupName: string | null;
  x: number;
  y: number;
}
```

- [ ] **Step 4: Посчитать статусы ленты с «бюджетом» переводных ячеек и обновить `showTip`**

Заменить сигнатуру и тело `showTip`:
```typescript
  const showTip = (e: MouseEvent<HTMLElement>, slot: ProgressSlot, cell: boolean | null) => {
    const r = e.currentTarget.getBoundingClientRect();
    setTip({
      slot: slot.slot,
      status: cellStatus(cell),
      date: slot.date,
      x: r.left + r.width / 2,
      y: r.top,
    });
  };
```
на:
```typescript
  const showTip = (
    e: MouseEvent<HTMLElement>, slot: ProgressSlot, status: CellStatus, transferredFromGroupName: string | null,
  ) => {
    const r = e.currentTarget.getBoundingClientRect();
    setTip({
      slot: slot.slot,
      status,
      date: slot.date,
      transferredFromGroupName,
      x: r.left + r.width / 2,
      y: r.top,
    });
  };
```

Внутри `data.students.map((s) => (...))`, ПЕРЕД `<div key={s.student_id} className="progress-row">`, посчитать статусы ленты один раз на строку (заменить блок рендера ленты целиком):

Было:
```tsx
        {data.students.map((s) => (
          <div key={s.student_id} className="progress-row">
            <div className="progress-row__who">
              <Avatar name={s.name} size={30} />
              <span className="progress-row__name" title={s.name}>{s.name}</span>
            </div>

            <div className="progress-ribbon">
              {s.cells.map((cell, i) => {
                const slot = slots[i];
                const st = cellStatus(cell);
                return (
                  <span
                    key={slot.slot}
                    className={`progress-sq is-${st}`}
                    role="img"
                    aria-label={`Урок №${slot.slot}: ${STATUS_LABEL[st]}${slot.date ? `, ${fmtLessonDate(slot.date)}` : ''}`}
                    onMouseEnter={(e) => showTip(e, slot, cell)}
                  />
                );
              })}
            </div>
```
Стало:
```tsx
        {data.students.map((s) => {
          let transferredLeft = s.transferred_lessons;
          const cellStatuses = s.cells.map((cell) => {
            if (cell === null && transferredLeft > 0) { transferredLeft--; return 'transferred' as const; }
            return cellStatus(cell);
          });
          return (
          <div key={s.student_id} className="progress-row">
            <div className="progress-row__who">
              <Avatar name={s.name} size={30} />
              <span className="progress-row__name" title={s.name}>{s.name}</span>
            </div>

            <div className="progress-ribbon">
              {s.cells.map((cell, i) => {
                const slot = slots[i];
                const st = cellStatuses[i];
                const label = st === 'transferred'
                  ? `Урок №${slot.slot}: Перевод из «${s.transferred_from_group_name}»`
                  : `Урок №${slot.slot}: ${STATUS_LABEL[st]}${slot.date ? `, ${fmtLessonDate(slot.date)}` : ''}`;
                return (
                  <span
                    key={slot.slot}
                    className={`progress-sq is-${st}`}
                    role="img"
                    aria-label={label}
                    onMouseEnter={(e) => showTip(e, slot, st, st === 'transferred' ? s.transferred_from_group_name : null)}
                  />
                );
              })}
            </div>
```

И закрыть map правильно — после блока `<div className="progress-row__stat">...</div>` (существующий, не трогаем его содержимое) заменить закрывающее:
```tsx
          </div>
        ))}
      </div>
```
на:
```tsx
          </div>
          );
        })}
      </div>
```

- [ ] **Step 5: Обновить рендер тултипа**

Заменить:
```tsx
      {tip && (
        <div
          className={`progress-tip is-${tip.status}`}
          style={{ left: tip.x, top: tip.y }}
          role="tooltip"
        >
          <span className="progress-tip__lesson">Урок №{tip.slot}</span>
          <span className="progress-tip__date">{tip.date ? fmtLessonDate(tip.date) : 'ещё не проведён'}</span>
          <span className="progress-tip__status">
            <span className="progress-tip__dot" />{STATUS_LABEL[tip.status]}
          </span>
        </div>
      )}
```
на:
```tsx
      {tip && (
        <div
          className={`progress-tip is-${tip.status}`}
          style={{ left: tip.x, top: tip.y }}
          role="tooltip"
        >
          <span className="progress-tip__lesson">Урок №{tip.slot}</span>
          <span className="progress-tip__date">
            {tip.status === 'transferred'
              ? `из «${tip.transferredFromGroupName}»`
              : (tip.date ? fmtLessonDate(tip.date) : 'ещё не проведён')}
          </span>
          <span className="progress-tip__status">
            <span className="progress-tip__dot" />{STATUS_LABEL[tip.status]}
          </span>
        </div>
      )}
```

- [ ] **Step 6: Typecheck**

Run:
```bash
npm run typecheck
```
Expected: без ошибок.

- [ ] **Step 7: Commit**

```bash
git add journal_django/frontend/admin-src/src/shared/progress/GroupProgressView.tsx
git commit -m "feat(admin-src): render transferred-lesson cells in progress matrix"
```

---

## Task 4: Frontend — CSS для статуса «Перевод»

**Files:**
- Modify: `journal_django/frontend/admin-src/src/shared/progress/progress.css`

- [ ] **Step 1: Добавить `.is-transferred` для чипа, ячейки и тултипа**

В `journal_django/frontend/admin-src/src/shared/progress/progress.css`:

После строки `.progress-chip.is-planned { background: var(--bg3); border: 1.5px dashed var(--border-strong); }` (строка 17) добавить:
```css
.progress-chip.is-transferred { background: var(--accent-soft); border-color: color-mix(in oklch, var(--accent) 45%, transparent); }
```

После строки `.progress-sq.is-planned { background: var(--bg3); border: 1.5px dashed var(--border-strong); }` (строка 51) добавить:
```css
.progress-sq.is-transferred { background: var(--accent-soft); border-color: color-mix(in oklch, var(--accent) 42%, transparent); }
```

После строки `.progress-sq.is-absent:hover  { border-color: var(--danger); }` (строка 57) добавить:
```css
.progress-sq.is-transferred:hover { border-color: var(--accent); }
```

После строки `.progress-tip.is-planned .progress-tip__dot { background: var(--text4); }` (строка 83) добавить:
```css
.progress-tip.is-transferred .progress-tip__status { color: var(--accent); }
.progress-tip.is-transferred .progress-tip__dot { background: var(--accent); }
```

(Точные номера строк — по состоянию файла на момент написания плана; ориентироваться на соседство с `.is-planned`-правилами того же селектора, а не жёстко на номер строки, если файл успел измениться.)

- [ ] **Step 2: Typecheck + build**

Run (из `journal_django/frontend/admin-src`):
```bash
npm run typecheck
npm run build
```
Expected: оба без ошибок.

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/shared/progress/progress.css
git commit -m "feat(admin-src): style transferred-lesson cells in progress matrix"
```

---

## Task 5: Финальная проверка

**Files:** нет изменений.

- [ ] **Step 1: Полный backend-набор**

Run (из `journal_django/`):
```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: все тесты зелёные, без падений в других приложениях.

- [ ] **Step 2: Финальный typecheck + build фронта**

Run (из `journal_django/frontend/admin-src`):
```bash
npm run typecheck
npm run build
```
Expected: без ошибок.

- [ ] **Step 3: Смоук через реальный HTTP (без браузера — по образцу предыдущей фичи)**

Поднять `manage.py runserver 8000` + `deploy/nginx/local/start-local-nginx.ps1`, дождаться готовности (`curl http://127.0.0.1:8000/api/auth/csrf` → 204), проверить, что `GET /api/admin/groups/<id>/progress` для существующей группы с переведённым учеником (если такой есть в dev-БД после предыдущей фичи — иначе просто убедиться что эндпоинт по-прежнему 200 и не 500 для любой активной группы) отдаёт JSON с новыми полями `transferred_lessons`/`transferred_from_group_name` в объектах `students`. Остановить оба процесса после проверки (`start-local-nginx.ps1 -Stop` + убить процесс на порту 8000).
