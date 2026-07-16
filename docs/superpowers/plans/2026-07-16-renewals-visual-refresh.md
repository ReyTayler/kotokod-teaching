# Продления: визуальный рестайл — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** переоформить страницу «Продления» (карточки канбана, шапки колонок, drawer сделки) в более тёплом визуальном стиле — крупнее радиус, мягкая тень, аватары-монограммы, пилюли-бейджи — сменив заодно акцентный цвет всего admin SPA с `#0c9bc7` на `#4F59F9` (уже используется в teacher SPA).

**Architecture:** правки только во фронтенде admin-src — токены (`tokens.css`), CSS страницы продлений (`styles/pages/renewals.css`), и 2 компонента (`RenewalCardView.tsx`, `RenewalDrawer.tsx`, добавляют уже существующий `components/Avatar.tsx`). Бэкенд, API, данные, структура страницы (drawer остаётся drawer'ом) — не меняются.

**Tech Stack:** React 19 + TypeScript, обычный CSS с custom properties (без CSS-in-JS/Tailwind), Vite build.

Спека: `docs/superpowers/specs/2026-07-16-renewals-visual-refresh-design.md`.

Рабочая директория для фронтенд-команд — `journal_django/frontend/admin-src/`. У проекта нет автотестов фронтенда (проверено ранее) — верификация здесь: `tsc --noEmit` (typecheck) после каждой правки кода + финальная сборка + визуальный смоук на dev-сервере.

---

### Task 1: Токены акцента и тени карточки (`tokens.css`)

**Files:**
- Modify: `journal_django/frontend/admin-src/src/styles/tokens.css:146-150` (светлая тема)
- Modify: `journal_django/frontend/admin-src/src/styles/tokens.css:213-229` (тёмная тема)

- [ ] **Step 1: Заменить акцент светлой темы**

Заменить (строки 146-150):

```css
  /* Single accent — cyan-blue (KOTOKOD logo identity) */
  --accent:        #0c9bc7;
  --accent-hover:  #0a7fa5;
  --accent-soft:   rgba(12, 155, 199, 0.10);
  --accent-soft-h: rgba(12, 155, 199, 0.16);
```

на:

```css
  /* Single accent — indigo, unified with teacher SPA brand (#4F59F9) */
  --accent:        #4F59F9;
  --accent-hover:  #3d46e0;
  --accent-soft:   rgba(79, 89, 249, 0.10);
  --accent-soft-h: rgba(79, 89, 249, 0.16);
```

- [ ] **Step 2: Заменить акцент тёмной темы и добавить `--shadow-card`**

Заменить (строки 213-229):

```css
  --accent:        #3fd2ee;
  --accent-hover:  #6fe0f6;
  --accent-soft:   rgba(63, 210, 238, 0.12);
  --accent-soft-h: rgba(63, 210, 238, 0.20);

  --success: #34d399;
  --warning: #fbbf24;
  --danger:  #f87171;
  --info:    #60a5fa;

  --shadow-modal:   0 12px 32px rgba(0, 0, 0, 0.5),
                    0 4px 8px   rgba(0, 0, 0, 0.3);
  --shadow-popover: 0 4px 16px rgba(0, 0, 0, 0.4),
                    0 1px 4px  rgba(0, 0, 0, 0.2);
  --shadow-xs: 0 1px 2px rgba(0, 0, 0, 0.3);
  --overlay: rgba(0, 0, 0, 0.6);
```

на:

```css
  --accent:        #50DCFE;
  --accent-hover:  #7ae4fe;
  --accent-soft:   rgba(80, 220, 254, 0.12);
  --accent-soft-h: rgba(80, 220, 254, 0.20);

  --success: #34d399;
  --warning: #fbbf24;
  --danger:  #f87171;
  --info:    #60a5fa;

  --shadow-modal:   0 12px 32px rgba(0, 0, 0, 0.5),
                    0 4px 8px   rgba(0, 0, 0, 0.3);
  --shadow-popover: 0 4px 16px rgba(0, 0, 0, 0.4),
                    0 1px 4px  rgba(0, 0, 0, 0.2);
  --shadow-xs: 0 1px 2px rgba(0, 0, 0, 0.3);
  --shadow-card: 0 2px 8px rgba(0, 0, 0, 0.28);
  --overlay: rgba(0, 0, 0, 0.6);
```

(Значения `#50DCFE`/`#7ae4fe` — те же, что уже в проде в
`journal_django/frontend/teacher-src/src/styles/tokens.css:149-152`, не
изобретаются заново.)

- [ ] **Step 3: Добавить `--shadow-card` в светлую тему**

В той же светлой секции токенов (там же, где сейчас `--shadow-xs`, чуть выше
строки 146), найти:

```css
  --shadow-xs: 0 1px 2px rgba(15, 23, 42, 0.08);
```

и добавить сразу после неё новую строку:

```css
  --shadow-xs: 0 1px 2px rgba(15, 23, 42, 0.08);
  --shadow-card: 0 2px 8px rgba(15, 23, 42, 0.06);
```

- [ ] **Step 4: Typecheck (CSS не проверяется tsc, но убеждаемся, что ничего не сломали в TS-файлах по соседству)**

Run (из `journal_django/frontend/admin-src/`): `npm run typecheck`
Expected: чисто, без ошибок (эта задача не трогает `.tsx`).

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/styles/tokens.css
git commit -m "feat(admin): switch accent to indigo #4F59F9, add --shadow-card token"
```

---

### Task 2: Обновить `docs/design-system.md`

**Files:**
- Modify: `docs/design-system.md:3,15`

- [ ] **Step 1: Поправить описание бренд-цвета**

Заменить:

```markdown
Personality: **Linear × Stripe** (precision + sophistication). Cool slate palette, teal accent (`#0d9488` — KOTOKOD identity).
```

на:

```markdown
Personality: **Linear × Stripe** (precision + sophistication). Cool slate palette, indigo accent (`#4F59F9` — KOTOKOD identity, unified with teacher SPA).
```

- [ ] **Step 2: Поправить строку токена в таблице**

Заменить:

```markdown
Accent:   --accent/--accent-hover/--accent-soft
```

на:

```markdown
Accent:   --accent/--accent-hover/--accent-soft  (#4F59F9 — см. tokens.css)
```

- [ ] **Step 3: Commit**

```bash
git add docs/design-system.md
git commit -m "docs(admin): fix stale accent color description (was teal, actually indigo)"
```

---

### Task 3: Карточка сделки — аватар и новая форма (`RenewalCardView.tsx`)

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/renewals/RenewalCardView.tsx`

- [ ] **Step 1: Добавить импорт `Avatar` и переструктурировать `RenewalCardContent`**

Заменить весь текущий файл (75 строк) на:

```tsx
import { useDraggable } from '@dnd-kit/core';
import { Avatar } from '../../components/Avatar';
import { fmtDate } from '../../lib/format';
import type { RenewalCard } from '../../lib/renewals';

// Порог «сделка зависла в стадии» — подсвечиваем SLA-бейдж красным.
const SLA_OVERDUE_DAYS = 5;

/**
 * Разметка карточки без drag-обвязки — переиспользуется и в самой колонке,
 * и в DragOverlay (там своя, немонтируемая копия, которую dnd-kit носит за курсором).
 */
export function RenewalCardContent({ card }: { card: RenewalCard }) {
  const overdue = card.days_in_stage > SLA_OVERDUE_DAYS;
  return (
    <>
      <div className="renewal-card__top">
        <span title={card.assignee_name || 'Не назначен'}>
          <Avatar name={card.assignee_name || '—'} size={28} />
        </span>
        <div className="renewal-card__student">{card.student_name || '—'}</div>
      </div>
      <div className="renewal-card__direction">
        {(card.directions || []).map((d, i) => (
          <span key={d.name} style={d.color ? { color: d.color } : undefined}>
            {i > 0 && ', '}{d.name}
          </span>
        ))}
        {(card.directions || []).length === 0 && '—'}
        {' · Цикл '}{card.cycle_no}
      </div>
      <div className="renewal-card__meta">
        <span
          className={`status-badge${overdue ? ' status-badge--negative' : ' status-badge--muted'}`}
          title="Дней в текущей стадии"
        >
          {card.days_in_stage} дн.
        </span>
        {card.debt && (
          <span className="status-badge status-badge--negative" title="Баланс ученика отрицательный">
            Долг
          </span>
        )}
        {card.next_touch_at && (
          <span className="renewal-card__touch">{fmtDate(card.next_touch_at)}</span>
        )}
      </div>
    </>
  );
}

interface Props {
  card: RenewalCard;
  stageId: number;
  onOpen: (id: number) => void;
}

export function RenewalCardView({ card, stageId, onOpen }: Props) {
  // Данные карточки едут вместе с drag'ом — так доска берёт их прямо из события
  // (event.active.data), а не ищет в кэше. Иначе карточки из «Показать ещё»
  // (локальный стейт) и из поиска (отдельный кэш) не перетаскивались бы.
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: card.id,
    data: { card, fromStageId: stageId },
  });

  return (
    <div
      ref={setNodeRef}
      className={`renewal-card${isDragging ? ' renewal-card--dragging' : ''}`}
      onClick={() => onOpen(card.id)}
      {...listeners}
      {...attributes}
    >
      <RenewalCardContent card={card} />
    </div>
  );
}
```

(Убраны `renewal-card__footer`/`renewal-card__assignee` — имя ответственного
теперь показывается аватаром сверху с `title`-тултипом вместо отдельной
строки внизу.)

- [ ] **Step 2: Typecheck**

Run (из `journal_django/frontend/admin-src/`): `npm run typecheck`
Expected: чисто. Если ругается на путь импорта `Avatar` — проверить, что
`journal_django/frontend/admin-src/src/components/Avatar.tsx` существует
(он уже есть в проекте, использовать без изменений).

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/renewals/RenewalCardView.tsx
git commit -m "feat(admin): add assignee avatar to renewal card, drop text footer"
```

---

### Task 4: CSS карточки, колонки и пилюль-бейджей (`renewals.css`)

**Files:**
- Modify: `journal_django/frontend/admin-src/src/styles/pages/renewals.css`

- [ ] **Step 1: Форма карточки — радиус, тень, цветной верх**

Заменить:

```css
.renewal-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: var(--space-3);
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.renewal-card:hover {
  border-color: var(--border-strong);
}
```

на:

```css
.renewal-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  background: var(--bg2);
  border: 1px solid var(--border);
  border-top: 3px solid var(--accent);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-card);
  padding: var(--space-3);
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.renewal-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-popover);
}
```

- [ ] **Step 2: Новая строка «аватар + имя» вместо старого футера**

Заменить:

```css
.renewal-card__student {
  font-weight: 600;
  font-size: 13px;
  color: var(--text);
}
```

на:

```css
.renewal-card__top {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.renewal-card__student {
  font-weight: 600;
  font-size: 13px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

- [ ] **Step 3: Удалить неиспользуемые больше правила футера**

Найти и удалить полностью (класс больше не используется — карточка сменила
структуру в Task 3):

```css
.renewal-card__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-top: var(--space-1);
  font-size: 12px;
  color: var(--text3);
}
```

- [ ] **Step 4: Пилюли-бейджи, только в карточке и в drawer'е**

После блока стилей `.renewal-card__footer` (там, где он был перед удалением
в Step 3 — то есть прямо перед комментарием `/* ==== DRAWER СДЕЛКИ ==== */`),
добавить:

```css
/* Пилюли вместо прямоугольных бейджей — только в этом разделе (страницы со
   списками/таблицами используют .status-badge без изменений). */
.renewal-card .status-badge,
.renewal-drawer .status-badge {
  border-radius: 999px;
}
```

- [ ] **Step 5: Заголовок колонки — счётчик крупнее, моноширинный**

Заменить:

```css
.renewal-col__stats {
  font-size: 12px;
  color: var(--text3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
```

на:

```css
.renewal-col__stats {
  font-size: 13px;
  font-weight: 600;
  color: var(--text2);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
```

- [ ] **Step 6: Поле поиска в колонке — крупнее радиус**

Заменить:

```css
.renewal-col__search-input {
  width: 100%;
  height: 30px;
  padding: 0 26px 0 var(--space-2);
  font: inherit;
  font-size: 12px;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  color: var(--text);
}
```

на:

```css
.renewal-col__search-input {
  width: 100%;
  height: 30px;
  padding: 0 26px 0 var(--space-2);
  font: inherit;
  font-size: 12px;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  color: var(--text);
}
```

- [ ] **Step 7: Шапка drawer'а — аватар рядом с именем**

Заменить:

```css
.renewal-drawer__title {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
}
```

на:

```css
.renewal-drawer__title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
}
```

- [ ] **Step 8: Кнопка «Внести оплату» — крупнее радиус (заливку даёт смена класса в Task 5)**

Заменить:

```css
.renewal-drawer__pay-btn {
  align-self: flex-start;
}
```

на:

```css
.renewal-drawer__pay-btn {
  align-self: flex-start;
  border-radius: var(--r-lg);
}
```

- [ ] **Step 9: Commit**

```bash
git add journal_django/frontend/admin-src/src/styles/pages/renewals.css
git commit -m "feat(admin): warm card shape, pill badges, bigger radii for renewals"
```

---

### Task 5: Drawer — аватар в шапке и кнопка-CTA (`RenewalDrawer.tsx`)

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/renewals/RenewalDrawer.tsx`

- [ ] **Step 1: Импортировать `Avatar`**

Найти блок импортов в начале файла:

```tsx
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { EntityLink } from '../../components/EntityLink';
```

заменить на:

```tsx
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Avatar } from '../../components/Avatar';
import { EntityLink } from '../../components/EntityLink';
```

- [ ] **Step 2: Добавить аватар в шапку**

Заменить:

```tsx
            <header className="renewal-drawer__head">
              <div className="renewal-drawer__title">
                <EntityLink section="students" id={deal.student_id} text={deal.student_name} />
              </div>
```

на:

```tsx
            <header className="renewal-drawer__head">
              <div className="renewal-drawer__title">
                <Avatar name={deal.student_name || '—'} size={32} />
                <EntityLink section="students" id={deal.student_id} text={deal.student_name} />
              </div>
```

- [ ] **Step 3: Кнопка «Внести оплату» — сплошная заливка вместо контурной**

Заменить:

```tsx
                <button
                  type="button"
                  className="btn-secondary renewal-drawer__pay-btn"
                  onClick={() => openPayment({ studentId: deal.student_id })}
                >
                  Внести оплату
                </button>
```

на:

```tsx
                <button
                  type="button"
                  className="btn-primary renewal-drawer__pay-btn"
                  onClick={() => openPayment({ studentId: deal.student_id })}
                >
                  Внести оплату
                </button>
```

- [ ] **Step 4: Typecheck**

Run (из `journal_django/frontend/admin-src/`): `npm run typecheck`
Expected: чисто.

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/renewals/RenewalDrawer.tsx
git commit -m "feat(admin): add student avatar to renewal drawer, promote pay button"
```

---

### Task 6: Сборка и визуальная проверка

**Files:** нет изменений — только проверка + пересборка `admin-dist`.

- [ ] **Step 1: Полный typecheck**

Run (из `journal_django/frontend/admin-src/`): `npm run typecheck`
Expected: 0 ошибок.

- [ ] **Step 2: Сборка**

Run: `npm run build`
Expected: сборка проходит, новые хэшированные бандлы появляются в
`journal_django/frontend/admin-dist/assets/`.

- [ ] **Step 3: Смоук в браузере**

Запустить dev-сервер (`npm run dev` в `admin-src/`, либо собранный
`admin-dist` через локальный nginx на :8080, проксирующий на
`runserver` — см. память проекта про локальный nginx), открыть раздел
«Продления»:
- доска: карточки — с индиго-верхом, круглым аватаром слева сверху,
  пилюлями-бейджами, мягкой тенью;
- шапка колонки — крупный моноширинный счётчик;
- клик по карточке → drawer: аватар ученика в шапке, пилюли-бейджи,
  кнопка «Внести оплату» залита индиго;
- проверить и светлую, и тёмную тему (переключатель темы в шапке SPA, если
  есть) — тёмный акцент должен быть светлее (`#50DCFE`), не совпадать со
  светлым;
- бегло открыть ещё 1-2 другие страницы (Ученики, Финансы) — убедиться, что
  общий индиго-акцент (кнопки, ссылки, фокус-кольца) не даёт явных
  контрастных провалов после смены токена.

- [ ] **Step 4: Commit пересобранных ассетов**

```bash
git add journal_django/frontend/admin-dist/
git commit -m "chore(admin): rebuild frontend after renewals visual refresh"
```

---

## Что сознательно не делаем (см. спеку, раздел «Риски»)

- Не добавляем KPI-строку с конверсией над доской — нужна новая агрегация
  на бэкенде.
- Не меняем структуру страницы — drawer остаётся всплывающей панелью, не
  становится постоянной 3-й колонкой.
- Не добавляем иконки звонка/сообщения и NEW/HOT-теги — нет данных/правил
  для них.
- Не проверяем предметно ВСЕ страницы SPA на совместимость с новым акцентом —
  только беглый смоук (Task 6, Step 3); если найдутся проблемы на других
  страницах — заводить отдельной задачей, не блокировать этим рестайл
  Продлений.
