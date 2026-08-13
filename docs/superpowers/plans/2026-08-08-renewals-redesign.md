# Редизайн раздела «Продления» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести раздел «Продления» на плотную CRM-раскладку: канбан во всю ширину области контента, единая панель фильтров с глобальным поиском, компактные карточки и внятные состояния загрузки/пустоты/ошибки.

**Architecture:** Работа почти целиком фронтовая. Бэкенд трогается ровно в одном месте — карточка доски начинает отдавать `balance` (данные уже читаются ради флага `debt`, лишних запросов ноль). Глобальный поиск не требует правок бэка: `filter[student]` уже применяется в `_board_where`, то есть работает и на уровне всей доски. Ширина канбана снимается точечным правилом `.app-page:has(> .renewals-page) { max-width: none }` в CSS раздела — без JS и без правки общей раскладки.

**Tech Stack:** Django 5 + DRF (raw SQL в `apps/renewals/repository.py`), React 19 + TanStack Query v5 + React Router v7, `@dnd-kit/core`, чистый CSS на дизайн-токенах (`styles/tokens.css`).

**Спека:** `docs/superpowers/specs/2026-08-08-renewals-redesign-design.md`

---

## Что надо знать до начала

**Правила проекта, нарушение которых = переделка:**

- **Никаких hardcoded-цветов, радиусов, отступов.** Только токены из
  `journal_django/frontend/admin-src/src/styles/tokens.css` (`var(--accent)`,
  `var(--space-3)`, `var(--r)` и т.д.). В ТЗ на редизайн были литеральные HEX —
  они уже переведены в токены в спеке, брать оттуда.
- **Никаких нативных form-элементов** в admin SPA: только `SelectInput`,
  `TextInput`, `Checkbox` из `components/form/`.
- **Не запускать `npm run build`** до финальной задачи. Сборка перезаписывает
  `journal_django/frontend/admin-dist/` — это отдельный шумный коммит.
  Для проверки на каждом шаге есть `npm run typecheck`.
- **pytest гонять только полностью** (`pytest -q` из `journal_django/`), не по
  приложениям: часть приложений no-op'ит `django_db_setup`, прогон по частям
  даёт ложно-зелёный результат.
- **Не коммитить и не пушить без явной просьбы пользователя.** Шаги «Commit»
  в этом плане выполняются, коммиты локальные; `git push` — никогда.
- **`git add` только перечисленных файлов.** Рабочее дерево полно чужого WIP,
  `git add -A` стянет лишнее.

**Проверка фронта на каждой задаче:**

```bash
cd journal_django/frontend/admin-src && npm run typecheck
```
Ожидаемо: без вывода, код возврата 0.

---

## Структура файлов

| Файл | Ответственность | Задача |
|---|---|---|
| `journal_django/apps/renewals/repository.py` | `_annotate_debt` отдаёт `balance` вместе с `debt` | 1 |
| `journal_django/apps/renewals/tests/test_api_read.py` | Тест на `balance` в карточке доски | 1 |
| `.../src/components/shell/PageHeader.tsx` | Проп `dense` | 2 |
| `.../src/styles/shell.css` | `.page-header--dense` | 2 |
| `.../src/styles/pages/renewals.css` | Вся вёрстка раздела | 3–8 |
| `.../src/pages/renewals/RenewalsPage.tsx` | Шапка, панель фильтров, чипы, глобальный поиск | 4 |
| `.../src/pages/renewals/RenewalColumn.tsx` | Заголовок колонки, сворачиваемый поиск, состояния | 5, 6 |
| `.../src/pages/renewals/RenewalBoard.tsx` | Skeleton при загрузке, состояние ошибки | 6, 7 |
| `.../src/pages/renewals/RenewalCardView.tsx` | Плотная карточка, семантика срока и долга | 8 |
| `.../src/lib/renewals.ts` | Поле `balance` в типе `RenewalCard` | 8 |

Все пути `.../src/` — от `journal_django/frontend/admin-src/`.

---

### Task 1: Бэкенд — карточка доски отдаёт `balance`

Сейчас карточка отдаёт только булев `debt`. Карточке нужен сам баланс, чтобы
показать «Долг 2 ур.» вместо голого слова «Долг».

**Важно про единицу измерения:** баланс здесь — **в уроках**, не в рублях.
`balances_for_students` считает `SUM(payments.lessons_count) − посещения`
(`apps/finances/repository.py:214`). Drawer сделки уже показывает именно так:
«Баланс — −2 ур.» (`RenewalDrawer.tsx:262`). Никаких рублей.

**Files:**
- Modify: `journal_django/apps/renewals/repository.py:483-492`
- Test: `journal_django/apps/renewals/tests/test_api_read.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `journal_django/apps/renewals/tests/test_api_read.py`:

```python
@pytest.mark.django_db
def test_board_card_has_balance_in_lessons(manager_client, make_student, make_direction,
                                           make_teacher, make_attendance):
    """
    Карточке нужен balance (в УРОКАХ, не в рублях) — из него карточка канбана
    строит бейдж «Долг N ур.». Два посещения без оплат = баланс −2.
    """
    from django.db import connection
    sid = make_student()
    did = make_direction('__renew_balance_dir__')
    tid = make_teacher()
    with connection.cursor() as cur:
        cur.execute("INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
                    "active, created_at, lesson_number_offset) "
                    "VALUES ('__bal_group__', %s, %s, false, true, now(), 0) RETURNING id",
                    [did, tid])
        gid = cur.fetchone()[0]
        cur.execute("INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                    "VALUES (%s,%s,0,true)", [gid, sid])
    try:
        make_attendance(sid, gid, tid, count=2)
        engine.ensure_deal(sid, cycle_no=1)

        resp = manager_client.get(f'{BASE}?view=board')
        cards = [c for col in resp.json()['columns'] for c in col['cards']
                 if c['student_id'] == sid]
        assert cards, 'карточка сделки не попала на доску'
        card = cards[0]
        assert card['balance'] == -2
        assert card['debt'] is True
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM renewal_activity WHERE deal_id IN '
                        '(SELECT id FROM renewal_deal WHERE student_id = %s)', [sid])
            cur.execute('DELETE FROM renewal_deal WHERE student_id = %s', [sid])
            cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [gid])
            cur.execute('DELETE FROM groups WHERE id = %s', [gid])
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
cd journal_django && pytest apps/renewals/tests/test_api_read.py::test_board_card_has_balance_in_lessons -v
```
Ожидаемо: FAIL с `KeyError: 'balance'`.

- [ ] **Step 3: Отдать `balance` из репозитория**

В `journal_django/apps/renewals/repository.py` заменить `_annotate_debt` целиком:

```python
def _annotate_debt(cards: list[dict]) -> list[dict]:
    """
    Баланс ученика и бейдж долга — батчем через apps.finances, без N+1.

    balance измеряется В УРОКАХ (оплачено минус посещено), не в рублях: ту же
    величину показывает drawer сделки («Баланс — −2 ур.»). Карточка канбана
    строит из неё бейдж «Долг N ур.», поэтому число нужно ей целиком, а не
    только знак.
    """
    from apps.finances.repository import balances_for_students
    ids = list({c['student_id'] for c in cards})
    if not ids:
        return cards
    balances = balances_for_students(ids)
    for c in cards:
        balance = float(balances.get(c['student_id'], 0))
        c['balance'] = balance
        c['debt'] = balance < 0
    return cards
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
cd journal_django && pytest apps/renewals/tests/test_api_read.py::test_board_card_has_balance_in_lessons -v
```
Ожидаемо: PASS.

- [ ] **Step 5: Прогнать тесты renewals целиком**

```bash
cd journal_django && pytest apps/renewals -q
```
Ожидаемо: все зелёные. (Полный `pytest -q` будет в финальной задаче.)

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/renewals/repository.py journal_django/apps/renewals/tests/test_api_read.py
git commit -m "feat(renewals): карточка доски отдаёт баланс в уроках"
```

---

### Task 2: Плотный вариант шапки страницы

Шапка раздела занимает 24px заголовком и 16px нижним отступом. Для канбана это
дорого. Вариант объявляется у самого компонента — раздел **не** переопределяет
чужой класс `.page-header` у себя в файле (владение классами).

**Files:**
- Modify: `journal_django/frontend/admin-src/src/components/shell/PageHeader.tsx:9-35`
- Modify: `journal_django/frontend/admin-src/src/styles/shell.css` (после блока `.page-header__actions`, строка ~285)

- [ ] **Step 1: Добавить проп `dense`**

В `PageHeader.tsx` в интерфейс `Props` добавить последним полем:

```tsx
  /** Строка под заголовком: пояснение или мета. */
  sub?: ReactNode;
  /**
   * Плотный режим: заголовок на ступень меньше и сжатый нижний отступ.
   * Для рабочих экранов, где на счету каждая строка данных, — канбан продлений.
   * Обычные разделы (списки, карточки сущностей) остаются на общем ритме.
   */
  dense?: boolean;
}
```

Сигнатуру и корневой элемент заменить на:

```tsx
export function PageHeader({ title, count, crumbs, actions, sub, dense }: Props) {
  return (
    <header className={`page-header${dense ? ' page-header--dense' : ''}`}>
```

- [ ] **Step 2: Добавить стили варианта**

В `journal_django/frontend/admin-src/src/styles/shell.css` сразу после строки
`.page-header__actions .btn-save { margin-left: 0; }` вставить:

```css
/* Плотный вариант шапки: заголовок на ступень ниже, нижний отступ сжат.
   Экономит ~14px до первого ряда данных — на канбане это половина высоты
   строки карточки. Медиазапрос ниже уже уводит заголовок на --fs-3xl, поэтому
   на узких экранах вариант ничего дополнительно не меняет. */
.page-header--dense { padding-bottom: var(--space-3); }
.page-header--dense .page-header__title { font-size: var(--fs-3xl); }
```

- [ ] **Step 3: Проверить типы**

```bash
cd journal_django/frontend/admin-src && npm run typecheck
```
Ожидаемо: код возврата 0, без вывода.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/components/shell/PageHeader.tsx journal_django/frontend/admin-src/src/styles/shell.css
git commit -m "feat(shell): плотный вариант шапки страницы"
```

---

### Task 3: Раскладка раздела — канбан во всю ширину

Канбан зажат дважды: `.app-page { max-width: 1440px }` (потолок, введённый ради
таблиц) и `padding: 0 32px`. Плюс у самой `.renewals-page` стоит собственный
`padding: var(--space-6)`, из-за которого липкая шапка страницы «не дотягивает»
до края: она вырывается на `-32px` из бокса, уже вдвинутого на 24px.

**Files:**
- Modify: `journal_django/frontend/admin-src/src/styles/pages/renewals.css:7-24` (блок `.renewals-page`)
- Modify: `journal_django/frontend/admin-src/src/styles/pages/renewals.css:171-196` (блоки `.renewal-board`, `.renewal-col`)

- [ ] **Step 1: Заменить блок оболочки страницы**

В `renewals.css` заменить блок от `.renewals-page {` до конца
`@media (max-width: 720px) { .renewals-page__kpis … }` (строки 7–24) на:

```css
/* Раздел живёт во всю ширину области контента: канбан — горизонтальная лента,
   и общий потолок --content-max (введённый ради таблиц, чтобы строка из 9
   колонок не растягивалась через монитор) превращал её в узкое окно.
   Правило смотрит на страницу-потомка, поэтому остальные разделы не задеты. */
.app-page:has(> .renewals-page) { max-width: none; }

.renewals-page {
  display: flex;
  flex-direction: column;
  /* Плотнее общего --section-gap: раздел рабочий, вертикаль на вес золота.
     Собственного padding у страницы НЕТ — поля раздаёт .app-page. Пока он был,
     липкая шапка вырывалась на --page-pad-x из уже вдвинутого бокса и не
     дотягивалась до края области контента. */
  gap: var(--space-3);

  /* Сумма того, что стоит НАД лентой: шапка (dense) + гэп + панель фильтров +
     гэп. Из неё считается высота колонок — раньше здесь было магическое
     calc(100vh - 220px), устаревавшее при любой правке шапки.
     ЗНАЧЕНИЕ УТОЧНЯЕТСЯ В ЗАДАЧЕ 9 ПО СОБРАННОМУ МАКЕТУ. */
  --rnl-board-top: 200px;
}

.renewals-page__kpis {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
}

@media (max-width: 720px) {
  .renewals-page__kpis {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 2: Заменить блок ленты и колонки**

В том же файле заменить блоки `.renewal-board`, `.renewal-board--loading`,
`.renewal-col`, `.renewal-col--over` (идут подряд, начинаются после шапки-комментария
`КАНБАН-ДОСКА`) на текст ниже. `.renewal-board--loading` здесь сохраняется как
есть — он ещё используется, его удалит задача 6 вместе с самим состоянием.

```css
/* Лента канбана идёт от края до края области контента: гасим боковые поля
   страницы отрицательным margin и возвращаем их padding'ом, чтобы первая и
   последняя колонки не липли к краю. Величина ОБЯЗАНА совпадать с
   --page-pad-x из .app-page и переключаться вместе с ней на 900px — иначе
   лента вылезет наружу и даст горизонтальный скролл всей страницы (ровно эта
   ошибка уже ловилась в .kb-editor, см. knowledge.css).
   overflow-x живёт ТОЛЬКО здесь: <body> по горизонтали не скроллится. */
.renewal-board {
  display: flex;
  gap: var(--space-3);
  margin-inline: calc(-1 * var(--page-pad-x));
  padding-inline: var(--page-pad-x);
  padding-bottom: var(--space-2);
  overflow-x: auto;
  overscroll-behavior-x: contain;
}

.renewal-board--loading {
  color: var(--text3);
  font-size: var(--fs-md);
  padding: var(--space-6);
}

.renewal-col {
  /* Тянутся на свободном месте, но не ужимаются: на широком мониторе колонки
     не жмутся в левый угол, на узком включается скролл ленты. Потолок нужен,
     чтобы три колонки не расползлись на полэкрана каждая. */
  flex: 1 0 272px;
  min-width: 272px;
  max-width: 360px;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  background: var(--bg3);
  border: 1px solid var(--border);
  border-top: 3px solid var(--border-strong);
  border-radius: var(--r);
  padding: var(--space-3);
  max-height: calc(100vh - var(--rnl-board-top));
}

.renewal-col--over {
  border-color: var(--info);
  background: color-mix(in oklab, var(--info) 6%, var(--bg3));
}

@media (max-width: 900px) {
  /* Брейкпоинт тот же, на котором .app-page переключает поля на --space-4. */
  .renewal-board {
    margin-inline: calc(-1 * var(--space-4));
    padding-inline: var(--space-4);
  }
}
```

- [ ] **Step 3: Включить плотную шапку на странице**

В `journal_django/frontend/admin-src/src/pages/renewals/RenewalsPage.tsx`
в вызове `<PageHeader` добавить проп `dense` первым:

```tsx
      <PageHeader
        dense
        title="Продления"
```

- [ ] **Step 4: Проверить типы**

```bash
cd journal_django/frontend/admin-src && npm run typecheck
```
Ожидаемо: код возврата 0.

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/styles/pages/renewals.css journal_django/frontend/admin-src/src/pages/renewals/RenewalsPage.tsx
git commit -m "feat(renewals): канбан во всю ширину области контента"
```

---

### Task 4: Шапка раздела и панель фильтров

Три изменения разом, потому что живут в одном файле и одном визуальном блоке:

1. «Настройка стадий» из текстовой кнопки → иконка-шестерёнка (действие трогают
   раз в квартал, а место оно занимает постоянно).
2. Глобальный поиск по имени ученика — работает в обоих видах. Отдельное поле
   «Ученик» из тулбара списка удаляется, его роль берёт поиск.
3. Uppercase-подписи над селектами убираются; пустое значение переименовывается
   в самоописательное («Все ответственные»). Активные фильтры выводятся чипами.

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/renewals/RenewalsPage.tsx` (файл целиком)
- Modify: `journal_django/frontend/admin-src/src/styles/pages/renewals.css` (блок `.rnl-toolbar`, строки ~647–710)

- [ ] **Step 1: Переписать `RenewalsPage.tsx`**

Заменить содержимое файла целиком:

```tsx
import { useCallback, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { useDirections } from '../../hooks/useDirections';
import { useRenewalAssignees, useRenewalUnassignedCount } from '../../hooks/useRenewals';
import { useRenewalStages } from '../../hooks/useRenewalStages';
import { RenewalUnassignedDialog } from './RenewalUnassignedDialog';
import { SelectInput } from '../../components/form/SelectInput';
import { TextInput } from '../../components/form/TextInput';
import { Checkbox } from '../../components/form/Checkbox';
import { SearchInput } from '../../components/ui/SearchInput';
import { canWriteRenewalStages, type Role } from '../../lib/permissions';
import { RenewalBoard } from './RenewalBoard';
import { RenewalList } from './RenewalList';
import { RenewalDrawer } from './RenewalDrawer';
import type { RenewalFilters } from '../../lib/renewals';
import { PageHeader } from '../../components/shell/PageHeader';

type ViewMode = 'board' | 'list';

/**
 * Ключи фильтров, живущие в URL — состояние раздела шарится ссылкой.
 * `student` теперь общий для обоих видов: в канбане уходит в filter[student]
 * доски (бэк применяет его в _board_where ко ВСЕМ колонкам), в списке — в
 * тот же фильтр списка. Отдельного поля «Ученик» в тулбаре больше нет.
 */
const FILTER_KEYS = ['student', 'assignee_id', 'direction_id', 'cycle_no', 'stage_id', 'include_closed'];

export default function RenewalsPage() {
  const { me } = useAuth();
  const [sp, setSp] = useSearchParams();
  const view: ViewMode = sp.get('view') === 'list' ? 'list' : 'board';
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const { data: assignees } = useRenewalAssignees();
  const { data: directions } = useDirections();
  const { data: stages } = useRenewalStages();
  // Только число: сам список грузит диалог, и только когда его открыли.
  const { data: unassigned } = useRenewalUnassignedCount();
  const [showUnassigned, setShowUnassigned] = useState(false);
  const unassignedCount = unassigned?.count ?? 0;

  // Цикл/стадия/закрытые применяются только в списочном виде — канбан их
  // игнорирует (доска показывает открытые сделки, разложенные по стадиям).
  const filters: RenewalFilters = {
    student: sp.get('student') ?? undefined,
    assignee_id: sp.get('assignee_id') ?? undefined,
    direction_id: sp.get('direction_id') ?? undefined,
    ...(view === 'list' ? {
      cycle_no: sp.get('cycle_no') ?? undefined,
      stage_id: sp.get('stage_id') ?? undefined,
      include_closed: sp.get('include_closed') ?? undefined,
    } : {}),
  };

  const setView = (v: ViewMode) => {
    const next = new URLSearchParams(sp);
    next.set('view', v);
    setSp(next, { replace: true });
  };

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(sp);
    if (value) next.set(key, value); else next.delete(key);
    setSp(next, { replace: true });
  };

  const resetFilters = () => {
    const next = new URLSearchParams(sp);
    FILTER_KEYS.forEach((k) => next.delete(k));
    setSp(next, { replace: true });
  };

  const closeDrawer = useCallback(() => setSelectedId(null), []);

  // Чипы активных фильтров: в подписи стоит ИМЯ из справочника, а не id —
  // «Ответственный: 17» не сообщает ничего. Справочник мог ещё не догрузиться,
  // тогда показываем сам ключ значением, а не пустоту.
  const assigneeName = (assignees || []).find((a) => String(a.id) === sp.get('assignee_id'))?.full_name;
  const directionName = (directions || []).find((d) => String(d.id) === sp.get('direction_id'))?.name;
  const stageName = (stages || []).find((s) => String(s.id) === sp.get('stage_id'))?.label;

  const chips: { key: string; label: string }[] = [];
  if (sp.get('student')) chips.push({ key: 'student', label: `Поиск: ${sp.get('student')}` });
  if (sp.get('assignee_id')) chips.push({ key: 'assignee_id', label: `Ответственный: ${assigneeName ?? sp.get('assignee_id')}` });
  if (sp.get('direction_id')) chips.push({ key: 'direction_id', label: `Направление: ${directionName ?? sp.get('direction_id')}` });
  if (view === 'list') {
    if (sp.get('cycle_no')) chips.push({ key: 'cycle_no', label: `Цикл ${sp.get('cycle_no')}` });
    if (sp.get('stage_id')) chips.push({ key: 'stage_id', label: `Стадия: ${stageName ?? sp.get('stage_id')}` });
    if (sp.get('include_closed') === 'true') chips.push({ key: 'include_closed', label: 'С закрытыми' });
  }

  return (
    <div className="renewals-page">
      <PageHeader
        dense
        title="Продления"
        actions={
          <>
            <div className="segmented" role="group" aria-label="Вид раздела">
              <button
                type="button"
                className={`segmented__btn${view === 'board' ? ' is-active' : ''}`}
                aria-pressed={view === 'board'}
                onClick={() => setView('board')}
              >Канбан</button>
              <button
                type="button"
                className={`segmented__btn${view === 'list' ? ' is-active' : ''}`}
                aria-pressed={view === 'list'}
                onClick={() => setView('list')}
              >Список</button>
            </div>
            <button
              type="button"
              className={`btn-secondary${unassignedCount > 0 ? ' renewals-page__unassigned-btn--attention' : ''}`}
              onClick={() => setShowUnassigned(true)}
            >
              Без сделок{unassignedCount > 0 ? ` (${unassignedCount})` : ''}
            </button>
            <Link to="/admin/renewals/analytics" className="btn-secondary">Аналитика</Link>
            {canWriteRenewalStages(me?.role as Role) && (
              /* Иконкой, а не подписью: действие открывают раз в квартал, а
                 место в шапке оно занимало постоянно. */
              <Link
                to="/admin/renewals/stages"
                className="ui-iconbtn ui-iconbtn--md"
                aria-label="Настройка стадий"
                title="Настройка стадий"
              >
                <GearGlyph />
              </Link>
            )}
          </>
        }
      />

      <div className="rnl-toolbar">
        <div className="rnl-toolbar__row">
          {/* Поиск — часть панели фильтрации, а не отдельный контрол внутри
              каждой колонки: искать ученика приходится, НЕ зная его стадии. */}
          <SearchInput
            value={sp.get('student') ?? ''}
            onChange={(v) => setFilter('student', v)}
            placeholder="Поиск по имени ученика…"
            width={240}
          />

          {/* Пустое значение названо самоописательно — так триггер объясняет
              себя без uppercase-подписи сверху, которая съедала 20px высоты. */}
          <SelectInput
            className="rnl-toolbar__select"
            value={sp.get('assignee_id') ?? ''}
            onChange={(e) => setFilter('assignee_id', e.target.value)}
            options={[
              { value: '', label: 'Все ответственные' },
              ...(assignees || []).map((a) => ({ value: String(a.id), label: a.full_name })),
            ]}
          />
          <SelectInput
            className="rnl-toolbar__select"
            value={sp.get('direction_id') ?? ''}
            onChange={(e) => setFilter('direction_id', e.target.value)}
            options={[
              { value: '', label: 'Все направления' },
              ...(directions || []).map((d) => ({ value: String(d.id), label: d.name })),
            ]}
          />

          {view === 'list' && (
            <>
              <SelectInput
                className="rnl-toolbar__select"
                value={sp.get('stage_id') ?? ''}
                onChange={(e) => setFilter('stage_id', e.target.value)}
                options={[
                  { value: '', label: 'Все стадии' },
                  ...(stages || []).map((s) => ({ value: String(s.id), label: s.label })),
                ]}
              />
              <TextInput
                className="rnl-toolbar__cycle"
                inputMode="numeric"
                placeholder="Цикл"
                aria-label="Номер цикла"
                value={sp.get('cycle_no') ?? ''}
                onChange={(e) => setFilter('cycle_no', e.target.value.replace(/\D/g, ''))}
              />
              <Checkbox
                label="Закрытые"
                checked={sp.get('include_closed') === 'true'}
                onChange={(e) => setFilter('include_closed', e.target.checked ? 'true' : '')}
              />
            </>
          )}
        </div>

        {chips.length > 0 && (
          <div className="rnl-chips">
            {chips.map((c) => (
              <button
                key={c.key}
                type="button"
                className="rnl-chip"
                onClick={() => setFilter(c.key, '')}
                title="Снять фильтр"
              >
                <span className="rnl-chip__text">{c.label}</span>
                <span className="rnl-chip__x" aria-hidden="true">×</span>
                <span className="sr-only">— снять фильтр</span>
              </button>
            ))}
            <button type="button" className="btn-reset-filters" onClick={resetFilters}>
              Сбросить
            </button>
          </div>
        )}
      </div>

      {view === 'board'
        ? <RenewalBoard filters={filters} onOpen={setSelectedId} />
        : <RenewalList filters={filters} onOpen={setSelectedId} />}

      {selectedId != null && (
        <RenewalDrawer id={selectedId} onClose={closeDrawer} />
      )}

      {showUnassigned && (
        <RenewalUnassignedDialog onClose={() => setShowUnassigned(false)} />
      )}
    </div>
  );
}

function GearGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.2.6.77 1.02 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}
```

- [ ] **Step 2: Заменить стили тулбара**

Сначала убедиться, что старые классы тулбара нигде больше не используются:

```bash
grep -rn "rnl-field\|rnl-toolbar__fields\|rnl-toolbar__aside" journal_django/frontend/admin-src/src/ --include=*.tsx
```
Ожидаемо: пустой вывод (шаг 1 уже убрал их из `RenewalsPage.tsx`).
Если что-то нашлось — эти места надо перевести на новую разметку, а не удалять
стили вслепую.

Затем в `renewals.css` заменить блок от комментария `/* ===== Тулбар фильтров
раздела ===== */` до закрывающего его `@media (max-width: 720px) { … }`
включительно на:

```css
/* ===== Панель фильтров раздела =====
   Один ряд контролов + строка чипов, появляющаяся только когда что-то выбрано.
   Прежний вид (uppercase-подписи над каждым полем) съедал ~20px высоты на
   информацию, которую поле и так сообщает своим значением. */
.rnl-toolbar {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--bg2);
  border: 1px solid var(--border2);
  border-radius: var(--r);
  box-shadow: var(--shadow-panel);
}

.rnl-toolbar__row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  min-width: 0;
}

/* Одна высота у поиска, селектов и поля цикла — иначе ряд разъезжается. */
.rnl-toolbar__select { width: 190px; }
.rnl-toolbar__select .select-input__trigger,
.rnl-toolbar__cycle {
  box-sizing: border-box;
  width: 100%;
  height: 34px;
  padding: 0 10px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-sm);
  outline: none;
  transition: border-color var(--t-fast) var(--ease), box-shadow var(--t-fast) var(--ease);
}
.rnl-toolbar__cycle { width: 88px; }
.rnl-toolbar__cycle::placeholder { color: var(--text4); }
.rnl-toolbar__cycle:focus,
.rnl-toolbar__select .select-input__trigger:focus,
.rnl-toolbar__select.is-open .select-input__trigger {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.rnl-toolbar__select .select-input__value { font-size: var(--fs-sm); }

/* Чипы активных фильтров. Сам чип — кнопка: клик снимает свой фильтр,
   поэтому крестик декоративный (aria-hidden), а смысл несёт подпись. */
.rnl-chips {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.rnl-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px 3px 10px;
  background: var(--accent-soft);
  border: 1px solid transparent;
  border-radius: 999px;
  color: var(--accent);
  font: inherit;
  font-size: var(--fs-xs);
  font-weight: 600;
  cursor: pointer;
  max-width: 320px;
}
.rnl-chip:hover { background: var(--accent-soft-h); }
.rnl-chip__text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rnl-chip__x { font-size: var(--fs-md); line-height: 1; opacity: 0.7; }
.rnl-chip:hover .rnl-chip__x { opacity: 1; }

@media (max-width: 720px) {
  .rnl-toolbar__row > * { flex: 1 1 100%; }
  .rnl-toolbar__select { width: 100%; }
}
```

- [ ] **Step 3: Проверить, что класс `.sr-only` существует**

```bash
grep -rn "\.sr-only" journal_django/frontend/admin-src/src/styles/
```
Ожидаемо: одна или несколько строк с определением.
Если вывод **пустой** — добавить в конец `styles/base.css`:

```css
/* Текст только для диктора: подпись, которую незачем показывать глазами. */
.sr-only {
  position: absolute;
  width: 1px; height: 1px;
  padding: 0; margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}
```

- [ ] **Step 4: Проверить типы**

```bash
cd journal_django/frontend/admin-src && npm run typecheck
```
Ожидаемо: код возврата 0.

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/renewals/RenewalsPage.tsx journal_django/frontend/admin-src/src/styles/pages/renewals.css journal_django/frontend/admin-src/src/styles/base.css
git commit -m "feat(renewals): глобальный поиск, чипы фильтров, компактная шапка"
```

---

### Task 5: Заголовок колонки и сворачиваемый поиск

Поиск в колонке — настоящий серверный поиск по конкретной стадии, поэтому он
остаётся. Но восемь одинаковых инпутов подряд — это шум: они сворачиваются в
иконку-лупу и разворачиваются по клику.

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/renewals/RenewalColumn.tsx` (файл целиком)
- Modify: `journal_django/frontend/admin-src/src/styles/pages/renewals.css` (блоки `.renewal-col__*`, строки ~203–326)

- [ ] **Step 1: Переписать `RenewalColumn.tsx`**

Заменить содержимое файла целиком:

```tsx
import { useDeferredValue, useEffect, useState } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { RenewalCardView } from './RenewalCardView';
import { TextInput } from '../../components/form/TextInput';
import { IconButton } from '../../components/ui/IconButton';
import { EmptyState } from '../../components/ui/EmptyState';
import { fetchRenewalColumnCards, useRenewalColumnSearch } from '../../hooks/useRenewals';
import { useApiError } from '../../hooks/useApiError';
import type { RenewalCard, RenewalColumn as RenewalColumnData, RenewalFilters } from '../../lib/renewals';

interface Props {
  col: RenewalColumnData;
  filters: RenewalFilters;
  onOpen: (id: number) => void;
}

export function RenewalColumn({ col, filters, onOpen }: Props) {
  // Прогресс-стадии («Не было урока», «Урок 1–3») двигает только движок по
  // событиям посещаемости/оплаты — вручную перетащить карточку СЮДА нельзя
  // (droppable отключён), бэк на move в такую стадию тоже ответит 409.
  // Забрать карточку ИЗ такой колонки (заморозить, отметить ушедшим) можно.
  const isAutoOnly = col.kind === 'progress';
  const { setNodeRef, isOver } = useDroppable({ id: col.stage_id, disabled: isAutoOnly });
  const showError = useApiError();

  // Поиск по имени ученика в ЭТОЙ колонке (server-side, ILIKE): ищем на сервере,
  // а не по загруженным карточкам — иначе ученик из непрогруженного «хвоста»
  // колонки не найдётся. Поле свёрнуто в лупу: восемь одинаковых инпутов
  // подряд — шум, а глобальный поиск живёт в панели фильтров.
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search.trim());
  const searching = deferredSearch.length > 0;

  // Колонночный поиск СУЖАЕТ глобальный: два ILIKE по одному полю не сложить,
  // поэтому внутри своей колонки её строка перекрывает общий фильтр.
  const colFilters: RenewalFilters = searching
    ? { ...filters, student: deferredSearch }
    : filters;

  const { data: searchData, isFetching: searchFetching } =
    useRenewalColumnSearch(col.stage_id, colFilters, searching);

  // Источник карточек: результат поиска либо данные доски.
  const baseCards = searching ? (searchData?.cards ?? []) : col.cards;
  const count = searching ? (searchData?.count ?? 0) : col.count;

  const [extraCards, setExtraCards] = useState<RenewalCard[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);

  // Фильтры/поиск сменились, либо счётчик колонки изменился (карточку перенесли
  // в неё/из неё, добавили оплату) — старая догрузка «Показать ещё» больше не
  // актуальна (иначе перенесённая карточка осталась бы «фантомом»), начинаем с нуля.
  const colFiltersKey = JSON.stringify(colFilters);
  useEffect(() => {
    setExtraCards([]);
  }, [col.stage_id, colFiltersKey, col.count]);

  const cards = [...baseCards, ...extraCards];
  const hasMore = count > cards.length;

  const handleShowMore = async () => {
    setLoadingMore(true);
    try {
      const more = await fetchRenewalColumnCards(col.stage_id, cards.length, colFilters);
      setExtraCards((prev) => [...prev, ...more.cards]);
    } catch (err) {
      showError(err, 'Не удалось догрузить карточки');
    } finally {
      setLoadingMore(false);
    }
  };

  const closeSearch = () => { setSearch(''); setSearchOpen(false); };
  const showSearchSpinner = searching && searchFetching && cards.length === 0;

  return (
    <div
      ref={setNodeRef}
      className={`renewal-col${isOver ? ' renewal-col--over' : ''}`}
      style={col.color ? { borderTopColor: col.color } : undefined}
    >
      <div className="renewal-col__head">
        {searchOpen ? (
          <div className="renewal-col__search">
            <TextInput
              className="renewal-col__search-input"
              value={search}
              autoFocus
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Escape') closeSearch(); }}
              placeholder="Имя ученика…"
              aria-label={`Поиск ученика в стадии «${col.label}»`}
            />
            <IconButton
              size="sm"
              label="Закрыть поиск"
              onClick={closeSearch}
              icon={<CloseGlyph />}
            />
          </div>
        ) : (
          <>
            <div className="renewal-col__title">
              <span className="renewal-col__label">{col.label}</span>
              {isAutoOnly && (
                <span className="renewal-col__auto-badge" title="Двигает только система по событиям — вручную перенести сделку сюда нельзя">
                  авто
                </span>
              )}
            </div>
            {/* Счётчик — вторичная метадата, поэтому без плашки. */}
            <span className="renewal-col__stats">{count}</span>
            {/* Подсветка при активном поиске: иначе свёрнутый фильтр невидим
                и «пропавшие» карточки нечем объяснить. */}
            <IconButton
              size="sm"
              label={`Поиск в стадии «${col.label}»`}
              active={searching}
              onClick={() => setSearchOpen(true)}
              icon={<SearchGlyph />}
            />
          </>
        )}
      </div>

      <div className="renewal-col__body">
        {showSearchSpinner ? (
          <div className="renewal-col__note">Ищем…</div>
        ) : cards.length === 0 ? (
          searching ? (
            <div className="renewal-col__note">Никого не найдено</div>
          ) : (
            <EmptyState hint="На этой стадии пока никого нет">Нет учеников</EmptyState>
          )
        ) : (
          cards.map((card) => (
            <RenewalCardView key={card.id} card={card} stageId={col.stage_id} onOpen={onOpen} />
          ))
        )}
      </div>

      {hasMore && (
        <button
          type="button"
          className="renewal-col__more"
          disabled={loadingMore}
          onClick={handleShowMore}
        >
          {loadingMore ? 'Загружаем…' : `Показать ещё (${count - cards.length})`}
        </button>
      )}
    </div>
  );
}

function SearchGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}

function CloseGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}
```

- [ ] **Step 2: Заменить стили колонки**

В `renewals.css` заменить блоки от `.renewal-col__head {` до
`.renewal-col__more:disabled { … }` включительно (строки ~203–326) на:

```css
/* Заголовок колонки. Иерархия: название — главное, счётчик — метадата,
   бейдж «авто» — служебная пометка второй строкой. */
.renewal-col__head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  min-height: 28px;
  padding-left: var(--space-1);
}

.renewal-col__title {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.renewal-col__label {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Пометка прогресс-стадии: сюда двигает только движок. Без рамки — рамка
   превращала служебную подпись в самостоятельный элемент управления. */
.renewal-col__auto-badge {
  font-size: var(--fs-2xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text3);
}

.renewal-col__stats {
  font-size: var(--fs-sm);
  color: var(--text3);
  font-variant-numeric: tabular-nums;
  line-height: 28px;
  white-space: nowrap;
}

/* Развёрнутый поиск занимает всю строку заголовка. */
.renewal-col__search {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  width: 100%;
}

.renewal-col__search-input {
  flex: 1;
  min-width: 0;
  height: 28px;
  padding: 0 var(--space-2);
  font: inherit;
  font-size: var(--fs-xs);
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  color: var(--text);
  outline: none;
}
.renewal-col__search-input::placeholder { color: var(--text4); }
.renewal-col__search-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.renewal-col__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  overflow-y: auto;
  min-height: 40px;
}

/* Короткая служебная строка («Ищем…», «Никого не найдено») — в отличие от
   EmptyState, который объясняет ПУСТУЮ стадию и занимает больше места. */
.renewal-col__note {
  padding: var(--space-3) var(--space-1);
  font-size: var(--fs-xs);
  color: var(--text3);
  text-align: center;
}

/* Пустое состояние внутри колонки уже, чем общее: колонка 272px. */
.renewal-col__body .empty-state { padding: var(--space-4) var(--space-2); }
.renewal-col__body .empty-state__title { font-size: var(--fs-sm); }
.renewal-col__body .empty-state__hint { font-size: var(--fs-xs); max-width: none; }

.renewal-col__more {
  background: transparent;
  border: 1px dashed var(--border-strong);
  border-radius: var(--r-sm);
  color: var(--text3);
  font: inherit;
  font-size: var(--fs-xs);
  padding: var(--space-2);
  cursor: pointer;
}

.renewal-col__more:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--text3);
}

.renewal-col__more:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
```

- [ ] **Step 3: Проверить типы**

```bash
cd journal_django/frontend/admin-src && npm run typecheck
```
Ожидаемо: код возврата 0.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/renewals/RenewalColumn.tsx journal_django/frontend/admin-src/src/styles/pages/renewals.css
git commit -m "feat(renewals): компактный заголовок колонки и сворачиваемый поиск"
```

---

### Task 6: Skeleton при загрузке доски

Сейчас при загрузке показывается строка «Загружаем доску…» — экран пустой, и
непонятно, что появится. Вместо неё — колонки с skeleton-карточками. Заголовки
колонок при этом настоящие: `useRenewalStages` отвечает отдельным запросом и,
как правило, уже в кэше.

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/renewals/RenewalBoard.tsx:201-204`
- Modify: `journal_django/frontend/admin-src/src/styles/pages/renewals.css` (конец файла)

- [ ] **Step 1: Заменить состояние загрузки**

В `RenewalBoard.tsx` заменить блок

```tsx
  if (isLoading) {
    return <div className="renewal-board renewal-board--loading">Загружаем доску…</div>;
  }
```

на

```tsx
  if (isLoading) {
    return <BoardSkeleton stageLabels={(stages || [])
      .filter((s) => s.kind !== 'won' && s.kind !== 'lost')
      .map((s) => s.label)} />;
  }
```

- [ ] **Step 2: Добавить компонент skeleton**

В конец `RenewalBoard.tsx` (после функции `RenewalBoard`) добавить:

```tsx
/**
 * Каркас доски на время загрузки. Заголовки колонок настоящие, когда справочник
 * стадий уже в кэше (он тянется отдельным запросом с длинным staleTime) —
 * тогда переход к данным не «перерисовывает» экран целиком. Без справочника
 * рисуем пять безымянных колонок: столько стадий в воронке по умолчанию.
 */
function BoardSkeleton({ stageLabels }: { stageLabels: string[] }) {
  const columns = stageLabels.length > 0 ? stageLabels : ['', '', '', '', ''];
  return (
    <div className="renewal-board" aria-busy="true" aria-live="polite">
      {columns.map((label, i) => (
        <div key={i} className="renewal-col">
          <div className="renewal-col__head">
            <div className="renewal-col__title">
              {label
                ? <span className="renewal-col__label">{label}</span>
                : <div className="skeleton-block rnl-skeleton__title" />}
            </div>
          </div>
          <div className="renewal-col__body">
            {[0, 1, 2, 3].map((j) => (
              <div key={j} className="rnl-skeleton-card">
                <div className="skeleton-block rnl-skeleton__line rnl-skeleton__line--name" />
                <div className="skeleton-block rnl-skeleton__line rnl-skeleton__line--dir" />
                <div className="skeleton-block rnl-skeleton__line rnl-skeleton__line--meta" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Добавить стили skeleton**

В конец `renewals.css` добавить:

```css
/* ===== Каркас доски на время загрузки =====
   Повторяет геометрию настоящей карточки, чтобы при появлении данных ничего
   не прыгало. Анимация — общая .skeleton-block из components.css. */
.rnl-skeleton-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: var(--space-2) var(--space-3);
}

.rnl-skeleton__title { height: 13px; width: 60%; }
.rnl-skeleton__line { height: 10px; }
.rnl-skeleton__line--name { height: 13px; width: 75%; }
.rnl-skeleton__line--dir  { width: 90%; }
.rnl-skeleton__line--meta { width: 45%; }
```

- [ ] **Step 4: Удалить осиротевший стиль**

В `renewals.css` удалить блок (класс больше нигде не используется):

```css
.renewal-board--loading {
  color: var(--text3);
  font-size: 14px;
  padding: var(--space-6);
}
```

Проверить, что класса действительно не осталось:

```bash
grep -rn "renewal-board--loading" journal_django/frontend/admin-src/src/
```
Ожидаемо: пустой вывод.

- [ ] **Step 5: Проверить типы**

```bash
cd journal_django/frontend/admin-src && npm run typecheck
```
Ожидаемо: код возврата 0.

- [ ] **Step 6: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/renewals/RenewalBoard.tsx journal_django/frontend/admin-src/src/styles/pages/renewals.css
git commit -m "feat(renewals): skeleton доски вместо строки «Загружаем»"
```

---

### Task 7: Состояние ошибки загрузки доски

Сейчас при ошибке запроса доска рендерится пустой — это читается как «учеников
нет». Отдельный баг, который чинится здесь же.

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/renewals/RenewalBoard.tsx:40, 201-206`

- [ ] **Step 1: Забрать из хука признак ошибки и `refetch`**

В `RenewalBoard.tsx` заменить строку

```tsx
  const { data, isLoading } = useRenewalBoard(filters);
```

на

```tsx
  const { data, isLoading, isError, refetch } = useRenewalBoard(filters);
```

- [ ] **Step 2: Показать состояние ошибки**

Сразу ПОСЛЕ блока `if (isLoading) { … }` вставить. Кнопка идёт в проп `action`,
а не в children: children рендерятся внутри `<p class="empty-state__title">`,
и кнопка там была бы невалидной разметкой.

```tsx
  // Без этой ветки сбитый бэкенд давал пустую доску, неотличимую от «никого
  // нет» — менеджер видел бы нулевую воронку и поверил бы ей.
  if (isError) {
    return (
      <EmptyState
        hint="Проверьте соединение и попробуйте ещё раз"
        action={<Button variant="secondary" onClick={() => refetch()}>Повторить</Button>}
      >
        Не удалось загрузить продления
      </EmptyState>
    );
  }
```

- [ ] **Step 3: Добавить импорты**

В начало `RenewalBoard.tsx`, к остальным импортам компонентов, добавить:

```tsx
import { EmptyState } from '../../components/ui/EmptyState';
import { Button } from '../../components/ui/Button';
```

- [ ] **Step 4: Убедиться, что `Button` принимает `variant="secondary"`**

```bash
grep -n "variant" journal_django/frontend/admin-src/src/components/ui/Button.tsx | head
```
Ожидаемо: в списке допустимых значений есть `secondary`. Если такого варианта
нет — использовать то имя варианта, которое объявлено в компоненте для
второстепенной кнопки.

- [ ] **Step 5: Проверить типы**

```bash
cd journal_django/frontend/admin-src && npm run typecheck
```
Ожидаемо: код возврата 0.

- [ ] **Step 6: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/renewals/RenewalBoard.tsx
git commit -m "fix(renewals): ошибка загрузки доски больше не выглядит как пустая воронка"
```

---

### Task 8: Плотная карточка ученика

Целевая высота — 64–88px. Убирается: верхняя цветная полоса (цвет стадии
принадлежит колонке), разноцветный текст направлений, пилюли-бейджи.
Добавляется: явная семантика срока и величина долга.

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/renewals.ts:71-88` (тип `RenewalCard`)
- Modify: `journal_django/frontend/admin-src/src/pages/renewals/RenewalCardView.tsx:10-49`
- Modify: `journal_django/frontend/admin-src/src/styles/pages/renewals.css` (блоки `.renewal-card*`, строки ~328–396)

- [ ] **Step 1: Добавить `balance` в тип карточки**

В `lib/renewals.ts` в интерфейсе `RenewalCard` заменить строки про долг на:

```ts
  /** Баланс ученика В УРОКАХ (оплачено минус посещено). Отрицательный = долг. */
  balance: number;
  /** Баланс < 0. Дублирует знак `balance`; оставлен для читаемости условий. */
  debt: boolean;
```

- [ ] **Step 2: Переписать содержимое карточки**

В `RenewalCardView.tsx` заменить функцию `RenewalCardContent` целиком:

```tsx
export function RenewalCardContent({ card }: { card: RenewalCard }) {
  // Порог SLA — не дедлайн: у стадии нет срока, есть граница, после которой
  // сделка считается застрявшей. Поэтому «зависла», а не «просрочено».
  const stuck = card.days_in_stage > SLA_OVERDUE_DAYS;
  // Направления одним цветом: в этом разделе цвет несёт СОСТОЯНИЕ, а не
  // название продукта — иначе крашеный «Python» спорит с именем ученика.
  const dirs = (card.directions || []).map((d) => d.name).join(', ') || '—';
  return (
    <>
      <div className="renewal-card__top">
        <span title={card.assignee_name || 'Не назначен'}>
          <Avatar name={card.assignee_name || '—'} size={22} />
        </span>
        <div className="renewal-card__student">{card.student_name || '—'}</div>
      </div>
      <div className="renewal-card__direction">{dirs} · Цикл {card.cycle_no}</div>
      <div className="renewal-card__meta">
        <span
          className={`renewal-card__age${stuck ? ' is-stuck' : ''}`}
          title="Сколько дней сделка стоит на текущей стадии"
        >
          {stuck ? `Зависла ${card.days_in_stage} дн.` : `В стадии ${card.days_in_stage} дн.`}
        </span>
        {card.balance < 0 && (
          <span className="renewal-card__debt" title="Посещено больше уроков, чем оплачено">
            Долг {fmtLessons(-card.balance)} ур.
          </span>
        )}
        {card.frozen_until_month && (
          <span className="renewal-card__frozen" title="Заморозка до месяца">
            до {fmtMonth(card.frozen_until_month)}
          </span>
        )}
      </div>
    </>
  );
}
```

- [ ] **Step 3: Поправить импорт форматирования**

В `RenewalCardView.tsx` заменить строку импорта

```tsx
import { fmtMonth } from '../../lib/format';
```

на

```tsx
import { fmtLessons, fmtMonth } from '../../lib/format';
```

- [ ] **Step 4: Заменить стили карточки**

В `renewals.css` заменить блоки от `.renewal-card {` до правила
`.renewal-card .status-badge, .renewal-drawer .status-badge { border-radius: 999px; }`
включительно (строки ~328–396) на:

```css
/* Карточка сделки. Плотность — главное требование раздела: цель 64–88px по
   высоте. Верхняя цветная полоса убрана: цвет стадии принадлежит КОЛОНКЕ,
   на карточке он дублировал бы её и спорил с бейджами состояния. */
.renewal-card {
  display: flex;
  flex-direction: column;
  gap: 3px;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--r);
  box-shadow: var(--shadow-xs);
  padding: var(--space-2) var(--space-3);
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.renewal-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-card);
}

/* Карточка-источник во время драга — тускнеет на месте, сам «полёт» рисует
   .renewal-card--overlay внутри DragOverlay (см. RenewalBoard.tsx). */
.renewal-card--dragging {
  opacity: 0.35;
}

/* Плавающая копия в DragOverlay: dnd-kit порталит её в document.body, поэтому
   она вне overflow/stacking-контекста колонок. Ширина явная — минимальная
   ширина колонки (272px) минус её горизонтальные поля (2 × --space-3). */
.renewal-card--overlay {
  width: 248px;
  cursor: grabbing;
  box-shadow: var(--shadow-popover);
}

.renewal-card__top {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.renewal-card__student {
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.renewal-card__direction {
  font-size: var(--fs-sm);
  color: var(--text3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Ряд состояния. Бейджи-пилюли заменены на цветной текст: рамка и заливка
   вокруг каждой метки на карточке высотой 68px читаются как отдельные
   элементы управления. */
.renewal-card__meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  font-size: var(--fs-2xs);
  font-variant-numeric: tabular-nums;
}

.renewal-card__age { color: var(--text3); }
.renewal-card__age.is-stuck { color: var(--danger); font-weight: 600; }
.renewal-card__debt { color: var(--danger); font-weight: 600; }
.renewal-card__frozen { color: var(--text3); }

/* Пилюли вместо прямоугольных бейджей — в drawer'е сделки (на карточке
   бейджей больше нет). */
.renewal-drawer .status-badge {
  border-radius: 999px;
}
```

- [ ] **Step 5: Проверить типы**

```bash
cd journal_django/frontend/admin-src && npm run typecheck
```
Ожидаемо: код возврата 0.

- [ ] **Step 6: Проверить, что нигде не осталось ссылок на удалённые классы**

```bash
grep -rn "renewal-card .status-badge\|renewal-card__meta .status-badge" journal_django/frontend/admin-src/src/
```
Ожидаемо: пустой вывод.

- [ ] **Step 7: Commit**

```bash
git add journal_django/frontend/admin-src/src/lib/renewals.ts journal_django/frontend/admin-src/src/pages/renewals/RenewalCardView.tsx journal_django/frontend/admin-src/src/styles/pages/renewals.css
git commit -m "feat(renewals): плотная карточка со внятной семантикой срока и долга"
```

---

### Task 9: Финальная проверка и сборка

- [ ] **Step 1: Полный прогон тестов**

```bash
cd journal_django && pytest -q
```
Ожидаемо: все тесты зелёные (~1900).
**Гонять целиком, не по приложениям:** часть приложений no-op'ит
`django_db_setup` (общая `journal_test`), часть пересоздаёт `test_journal_test`.
Прогон по частям даёт ложный результат.

- [ ] **Step 2: Запустить дев-сервер и снять реальную высоту шапки**

```bash
cd journal_django/frontend/admin-src && npm run dev
```

Открыть `/admin/renewals`, в DevTools выполнить в консоли:

```js
const p = document.querySelector('.renewals-page');
const board = document.querySelector('.renewal-board');
Math.round(board.getBoundingClientRect().top)
```

Полученное число + 24px нижнего запаса подставить в `renewals.css`:

```css
.renewals-page {
  --rnl-board-top: <снятое значение + 24>px;
}
```

и заменить комментарий-заглушку «ЗНАЧЕНИЕ УТОЧНЯЕТСЯ В ЗАДАЧЕ 9» на разбор
слагаемых, например: `/* 60 шапка + 12 гэп + 58 фильтры + 12 гэп + 24 запас */`.

Повторить замер на ширине 800px (эмуляция узкого экрана) и, если число заметно
другое, добавить его в медиазапрос `@media (max-width: 900px)`.

- [ ] **Step 3: Браузерная проверка**

На `/admin/renewals` проверить в **обеих темах** (переключатель в сайдбаре) и на
ширинах 1280 / 1600 / 1920:

1. Канбан занимает всю ширину после сайдбара, колонки не обрезаны.
2. Горизонтального скролла у страницы нет — прокручивается только лента.
   Проверка: `document.documentElement.scrollWidth === document.documentElement.clientWidth`.
3. Высота карточки в диапазоне 64–88px:
   `document.querySelector('.renewal-card').getBoundingClientRect().height`.
4. Поиск в панели фильтров сужает ВСЕ колонки и пересчитывает счётчики.
5. Лупа в шапке колонки разворачивает поле, Esc сворачивает, при активном
   поиске лупа подсвечена.
6. Чипы появляются при выборе фильтра, крестик снимает свой фильтр,
   «Сбросить» снимает все.
7. Пустая стадия показывает «Нет учеников», поиск без совпадений —
   «Никого не найдено» (разные состояния, не путать).
8. Долг показан как «Долг N ур.», при неотрицательном балансе бейджа нет.
9. Сделка на стадии дольше 5 дней — «Зависла N дн.» красным.
10. DnD не сломан: карточка перетаскивается между колонками, зоны
    «Продлён»/«Ушёл» появляются при драге, счётчики обновляются сразу.
11. Ширина 800px: лента не вылезает за край, страница не скроллится вбок.

- [ ] **Step 4: Проверить состояние ошибки**

В DevTools → Network включить offline, обновить `/admin/renewals`.
Ожидаемо: «Не удалось загрузить продления» + кнопка «Повторить».
Выключить offline, нажать «Повторить» — доска загружается.

- [ ] **Step 5: Собрать бандл**

```bash
cd journal_django/frontend/admin-src && npm run build
```
Ожидаемо: сборка без ошибок, файлы обновились в
`journal_django/frontend/admin-dist/`.

- [ ] **Step 6: Commit сборки отдельным коммитом**

```bash
git add journal_django/frontend/admin-dist
git commit -m "build(admin): пересборка бандла"
```

- [ ] **Step 7: Показать пользователю итог**

Перечислить: что сделано, результат полного `pytest -q`, какие пункты
браузерной проверки прошли, а какие нет. Не заявлять «готово», пока
браузерная проверка не пройдена — это отдельный шаг, который выполняет
пользователь, если у агента нет браузера.

---

## Что осталось за рамками (по решению пользователя)

- «Без сделок» третьей вкладкой — остаётся кнопкой-модалкой.
- Фильтр «Период» — на доске только открытые сделки, применять его не к чему.
- Системная палитра стадий вместо настраиваемой — цвет по-прежнему из
  «Настройки стадий».
- Аналитика продлений, drawer сделки, страница настройки стадий — не трогаются.
