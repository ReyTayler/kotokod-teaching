# Phase 4.1 — Visual System Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Создать общий визуальный слой `public/styles.css` с OKLCH-палитрой, типографикой и CSS-компонентами, и применить его к существующему `public/Index.html` без изменения функциональности SPA.

**Architecture:** Один файл `public/styles.css` подключается к `Index.html` через `<link>`. Локальный `<style>`-блок в Index.html переписывается: дубли цветов/радиусов/шрифтов выкидываются (берутся из styles.css), специфичные для teacher-экранов классы остаются, но мигрируют на новые токены.

**Tech Stack:** Чистый CSS (включая OKLCH, CSS custom properties, modern selectors). Без npm-зависимостей, без bundler'а.

**Reference spec:** `docs/superpowers/specs/2026-05-25-frontend-refresh-admin-ui-design.md` (разделы «Visual system», «Teacher SPA»).

**Project state note:** Проект не под git. Шаги `commit` пропущены.

**Verification limitation:** Visual changes can only be verified by humans looking at the rendered page. Subagents implementing CSS cannot self-verify visual quality. Each task ends with a screenshot/manual review step that requires the operator.

---

## Файловая структура Phase 4.1

| Путь | Создаётся/Меняется | Ответственность |
|------|--------------------|-----------------|
| `public/styles.css` | создаётся | Палитра, типографика, motion, компоненты (`.btn`, `.input`, `.card`, `.pill`, `.modal`, `.table`) |
| `public/Index.html` | меняется | `<link>` на styles.css; локальный `<style>`-блок переписан под новые токены |

Файлы `server.js`, `services/*`, `db/`, `public/admin.html` (ещё не существует) — не трогаем.

---

### Task 1: Создать `public/styles.css` с токенами и базой

**Files:**
- Create: `public/styles.css`

- [ ] **Step 1: Записать токены (палитра + типографика + spacing + радиусы + тени + motion)**

Полное содержимое первой части файла:

```css
/* public/styles.css — общая визуальная система journal-backend.
   Подключается из Index.html и (позже) admin.html. */

/* ─── ТОКЕНЫ ─────────────────────────────────────────────── */
:root {
  /* Фоны */
  --bg:            oklch(0.16 0.015 260);
  --surface-1:     oklch(0.20 0.018 260);
  --surface-2:     oklch(0.24 0.020 260);
  --surface-3:     oklch(0.28 0.022 260);
  --border:        oklch(0.32 0.020 260);
  --border-strong: oklch(0.40 0.022 260);

  /* Текст */
  --text:   oklch(0.96 0.005 260);
  --text-2: oklch(0.72 0.010 260);
  --text-3: oklch(0.50 0.010 260);

  /* Акценты */
  --accent:      oklch(0.70 0.18 250);
  --accent-hi:   oklch(0.78 0.20 250);
  --accent-soft: oklch(0.30 0.10 250 / 0.4);

  /* Семантика */
  --ok:   oklch(0.74 0.16 150);
  --warn: oklch(0.78 0.15  85);
  --err:  oklch(0.65 0.20  25);

  /* Радиусы */
  --r-sm: 6px;
  --r-md: 10px;
  --r-lg: 14px;
  --r-xl: 20px;

  /* Тени */
  --shadow-1: 0 1px 0 rgb(255 255 255 / 0.04) inset, 0 1px 2px rgb(0 0 0 / 0.3);
  --shadow-2: 0 1px 0 rgb(255 255 255 / 0.06) inset, 0 4px 12px rgb(0 0 0 / 0.4);

  /* Motion */
  --ease-out:    cubic-bezier(0.16, 1, 0.3, 1);
  --ease-spring: cubic-bezier(0.5, 1.5, 0.3, 1);
  --dur-fast: 120ms;
  --dur-base: 200ms;
  --dur-slow: 360ms;

  /* Spacing (шкала ×1.5) */
  --sp-1:  4px;
  --sp-2:  8px;
  --sp-3:  12px;
  --sp-4:  16px;
  --sp-5:  24px;
  --sp-6:  32px;
  --sp-7:  48px;
  --sp-8:  64px;

  /* Типографика */
  --font-sans: 'Manrope', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;

  --fs-display: 36px;
  --fs-h1:      24px;
  --fs-h2:      18px;
  --fs-body:    15px;
  --fs-small:   13px;
  --fs-code:    14px;

  --lh-tight: 1.2;
  --lh-base:  1.45;

  --touch: 44px;
}

/* ─── СБРОС ──────────────────────────────────────────────── */
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html {
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
}

body {
  font-family: var(--font-sans);
  font-size: var(--fs-body);
  line-height: var(--lh-base);
  font-weight: 500;
  letter-spacing: -0.005em;
  color: var(--text);
  background: var(--bg);
  min-height: 100vh;
}

button, input, select, textarea {
  font: inherit;
  color: inherit;
}

a { color: inherit; text-decoration: none; }

/* Утилиты */
.hidden { display: none !important; }
.mono   { font-family: var(--font-mono); }
.muted  { color: var(--text-2); }
.subtle { color: var(--text-3); }
```

- [ ] **Step 2: Sanity check — CSS парсится без ошибок**

Run (PowerShell):
```powershell
node -e "const fs=require('fs'); const css=fs.readFileSync('public/styles.css','utf8'); console.log('length:', css.length); console.log('has :root:', css.includes(':root'));"
```

Expected: непустой length и `has :root: true`. Это лишь sanity — на этом этапе синтаксис не валидируем строгим парсером, validate визуально в Task 5.

---

### Task 2: Добавить компоненты в `public/styles.css`

**Files:**
- Modify: `public/styles.css` (append)

- [ ] **Step 1: Дописать компоненты в конец styles.css**

Содержимое, добавляемое в конец файла:

```css
/* ─── КОМПОНЕНТЫ ─────────────────────────────────────────── */

/* Кнопка */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  padding: 0 var(--sp-4);
  height: var(--touch);
  min-width: var(--touch);
  border: 1px solid transparent;
  border-radius: var(--r-md);
  background: var(--surface-2);
  color: var(--text);
  font-weight: 600;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out),
              transform var(--dur-fast) var(--ease-out),
              box-shadow var(--dur-fast) var(--ease-out);
  user-select: none;
}
.btn:hover         { background: var(--surface-3); }
.btn:active        { transform: translateY(1px); }
.btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.btn:disabled      { opacity: 0.5; cursor: not-allowed; }

.btn--primary {
  background: var(--accent);
  color: oklch(0.16 0.015 260);
  box-shadow: var(--shadow-1);
}
.btn--primary:hover { background: var(--accent-hi); }

.btn--ghost {
  background: transparent;
  border-color: var(--border);
}
.btn--ghost:hover { background: var(--surface-2); }

.btn--sm { height: 32px; padding: 0 var(--sp-3); font-size: var(--fs-small); }
.btn--lg { height: 52px; padding: 0 var(--sp-5); font-size: var(--fs-h2); }

/* Поле ввода */
.input {
  display: block;
  width: 100%;
  height: var(--touch);
  padding: 0 var(--sp-4);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  color: var(--text);
  font-size: var(--fs-body);
  transition: border-color var(--dur-fast) var(--ease-out),
              background var(--dur-fast) var(--ease-out);
}
.input::placeholder    { color: var(--text-3); }
.input:hover           { border-color: var(--border-strong); }
.input:focus           { outline: none; border-color: var(--accent); background: var(--surface-1); }

textarea.input { height: auto; padding: var(--sp-3) var(--sp-4); min-height: 88px; resize: vertical; }
select.input   { padding-right: var(--sp-5); appearance: none; cursor: pointer; }

/* Карточка */
.card {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: var(--sp-4);
  box-shadow: var(--shadow-1);
  transition: box-shadow var(--dur-base) var(--ease-out),
              transform var(--dur-base) var(--ease-out);
}
.card--hover:hover {
  box-shadow: var(--shadow-2);
  transform: translateY(-1px);
}

/* Pill / status badge */
.pill {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  padding: 2px var(--sp-2);
  border-radius: 999px;
  font-size: var(--fs-small);
  font-weight: 600;
  background: var(--surface-2);
  color: var(--text-2);
}
.pill::before {
  content: '';
  width: 6px; height: 6px; border-radius: 50%;
  background: currentColor;
}
.pill--ok   { color: var(--ok);   background: oklch(0.74 0.16 150 / 0.15); }
.pill--warn { color: var(--warn); background: oklch(0.78 0.15  85 / 0.15); }
.pill--err  { color: var(--err);  background: oklch(0.65 0.20  25 / 0.15); }

/* Модалка */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgb(0 0 0 / 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-4);
  z-index: 100;
  animation: modalFadeIn var(--dur-base) var(--ease-out);
}
.modal {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-2);
  padding: var(--sp-5);
  max-width: 480px;
  width: 100%;
  max-height: calc(100vh - 2 * var(--sp-4));
  overflow-y: auto;
  animation: modalSlideIn var(--dur-base) var(--ease-spring);
}
@keyframes modalFadeIn  { from { opacity: 0; } to { opacity: 1; } }
@keyframes modalSlideIn { from { opacity: 0; transform: translateY(8px) scale(0.98); }
                          to   { opacity: 1; transform: translateY(0) scale(1); } }

/* Таблица */
.table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-body);
}
.table th, .table td {
  padding: var(--sp-3) var(--sp-4);
  text-align: left;
  border-bottom: 1px solid var(--border);
}
.table thead th {
  position: sticky;
  top: 0;
  background: var(--surface-1);
  font-size: var(--fs-small);
  font-weight: 600;
  color: var(--text-2);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.table tbody tr {
  transition: background var(--dur-fast) var(--ease-out);
}
.table tbody tr:hover { background: var(--surface-2); cursor: pointer; }
```

- [ ] **Step 2: Проверить размер файла**

Run (PowerShell):
```powershell
$bytes = (Get-Item public/styles.css).Length; "styles.css size: $bytes bytes"
```

Expected: примерно 5–7 KB. Если меньше 3 KB — что-то не дописалось.

---

### Task 3: Подключить `styles.css` к `Index.html` и убрать дубликаты токенов

**Files:**
- Modify: `public/Index.html` (lines ~11–13, ~14–40)

- [ ] **Step 1: Добавить `<link>` на styles.css в `<head>`**

В Index.html прямо после строки с `<link>` на Google Fonts (рядом со строкой ~11) добавить:

```html
<link rel="stylesheet" href="/styles.css">
```

Расположение важно — **после** Google Fonts (чтобы наш CSS мог переопределить дефолты), но до локального `<style>`-блока.

- [ ] **Step 2: Удалить дублирующиеся токены из локального `<style>`-блока**

В локальном блоке `<style>` (начинается со строки ~14) удалить весь блок `:root { ... }` (текущие старые `--bg`, `--surface`, `--accent`, `--r`, `--fs-*`, `--touch` и т.д.). Эти токены теперь живут в styles.css.

**Также** удалить из локального `<style>` блоки:
- `/* ── СБРОС ── */` (`*, *::before, *::after { box-sizing: ... }`) — сброс уже в styles.css
- `body { font-family, background, color, min-height, padding... }` декларации, которые дублируют styles.css. ОСТАВИТЬ `padding: 16px 14px 80px;` если это специфично для teacher SPA, заверну в `.app-shell` или оставлю на body — решить по месту, если останется в body — это локальный override, ок.
- `.hidden { display: none !important; }` — уже в styles.css.

**Что НЕ удалять** из локального `<style>`:
- Все классы, специфичные для teacher-экранов (`.lesson-card`, `.sched-popup`, `.day-tab`, `.tab-bar`, `.token-input`, и т.п.).
- Media queries для mobile/desktop.
- Анимации `fadeUp` и подобные — они используются в teacher-экранах.
- `body::before { ... radial-gradient ... }` — фоновый эффект teacher SPA.

- [ ] **Step 3: Проверить, что Index.html парсится как валидный HTML и сервер всё ещё может его отдать**

Run (PowerShell):
```powershell
$content = Get-Content public/Index.html -Raw
# Базовая проверка: содержит <link rel="stylesheet" href="/styles.css">
$hasLink = $content -match '<link[^>]*href="/styles\.css"'
"styles.css link present: $hasLink"
# Содержит ли всё ещё <style> блок?
$hasStyle = $content -match '<style>'
"local <style> block present: $hasStyle"
# Длина файла
"file size: $($content.Length) bytes"
```

Expected:
- `styles.css link present: True`
- `local <style> block present: True` (он остаётся — там teacher-специфичные классы)
- Размер должен уменьшиться на ~2–3 KB после удаления дубликатов токенов и сбросов.

---

### Task 4: Мигрировать локальный `<style>`-блок в Index.html на новые токены

**Files:**
- Modify: `public/Index.html` (локальный `<style>`-блок)

> Это самая ёмкая задача — touch на все правила локального стиля. Идея: пройтись поиском и заменить старые имена токенов на новые. После этого верифицировать визуально в Task 5.

- [ ] **Step 1: Карта замен**

| Старое (в локальном стиле) | Новое (из styles.css) |
|----------------------------|------------------------|
| `var(--bg)` | `var(--bg)` (имя совпадает, новое значение из styles.css) |
| `var(--surface)` | `var(--surface-1)` |
| `var(--s2)` | `var(--surface-2)` |
| `var(--border)` | `var(--border)` (имя совпадает) |
| `var(--accent)` | `var(--accent)` (имя совпадает) |
| `var(--accent2)` | `var(--accent-hi)` |
| `var(--green)` | `var(--ok)` |
| `var(--red)` | `var(--err)` |
| `var(--yellow)` | `var(--warn)` |
| `var(--text)` | `var(--text)` |
| `var(--text2)` | `var(--text-2)` |
| `var(--text3)` | `var(--text-3)` |
| `var(--r)` | `var(--r-md)` |
| `var(--rsm)` | `var(--r-sm)` |
| `var(--fs-xs)` | `var(--fs-small)` |
| `var(--fs-sm)` | `var(--fs-small)` |
| `var(--fs-md)` | `var(--fs-body)` |
| `var(--fs-lg)` | `var(--fs-h2)` |
| `var(--fs-xl)` | `var(--fs-h1)` |
| `var(--fs-2xl)` | `var(--fs-display)` |
| `var(--touch)` | `var(--touch)` (имя совпадает) |

Особый случай: `var(--fs-xs-year)` = 20px — оставить как локальный override (нет аналога в общей системе): добавить в локальный `<style>`:
```css
:root { --fs-xs-year: 20px; }
```
Это локальное переопределение для специфичного use-case.

- [ ] **Step 2: Сделать массовую замену**

Открыть Index.html, в локальном `<style>`-блоке применить замены из карты Step 1. Use the editor's Replace All carefully — каждая замена должна быть точной (с `var(--name)`).

- [ ] **Step 3: Заменить старые `transition` правила на новые motion-токены**

Поиск в локальном `<style>`-блоке: любые `transition:` правила, использующие фиксированные значения времени (`0.2s`, `200ms`, `cubic-bezier(...)`, `ease-out`, `ease-in-out`).

Заменить:
- `0.2s ease-out` → `var(--dur-base) var(--ease-out)`
- `0.12s ease` → `var(--dur-fast) var(--ease-out)`
- `cubic-bezier(...)` собственные значения — заменять на `var(--ease-out)` или `var(--ease-spring)` по смыслу (spring для появлений, out для остального).

Это не строгая замена один-в-один — нужно осмысленно. Если непонятно — оставить как есть и пометить в комментарии `/* TODO motion */`, тогда верификация в Task 5 покажет, какие точки jitter'ят.

- [ ] **Step 4: Заменить старые `box-shadow` на новые**

Поиск в локальном блоке: правила `box-shadow:` с конкретными значениями.

Заменить на `var(--shadow-1)` (для обычных карточек/inputs) или `var(--shadow-2)` (для приподнятых элементов на hover, модалок и попапов).

- [ ] **Step 5: Sanity check**

Run (PowerShell):
```powershell
$content = Get-Content public/Index.html -Raw
# Старые токены не должны встречаться
foreach ($old in @('--s2','--accent2','--green','--red','--yellow','--text2','--text3','--rsm','--fs-xs','--fs-sm','--fs-md','--fs-lg','--fs-xl','--fs-2xl')) {
  $count = ([regex]::Matches($content, [regex]::Escape("var($old)"))).Count
  if ($count -gt 0) { "still using $old : $count occurrences" }
}
"---"
"sanity done"
```

Expected: если выводится `sanity done` без строк выше — все старые токены замигрированы.

---

### Task 5: Manual visual smoke test

> CSS визуально проверяется только глазами. План явно фиксирует ручную проверку.

- [ ] **Step 1: Запустить сервер**

Run: `npm start`

- [ ] **Step 2: Открыть http://localhost:3000 в браузере и пройти по каждому экрану**

Чеклист (по чек-листу `docs/smoke-tests.md` + визуальные проверки):

Authentication:
- [ ] Login-экран загружается, фон в новой OKLCH-палитре, поле ввода чёткое
- [ ] Focus-кольцо на input — `--accent` (синий)
- [ ] Button submit — primary стиль, видна иерархия

Журнал:
- [ ] Tab-bar — активный таб выделен, inactive приглушённые
- [ ] Список групп — карточки с лёгкой тенью, hover поднимает
- [ ] Выбор учеников — чекбоксы видны, состояние «выбран» — `--accent`
- [ ] Submit-форма — сводка читабельна, кнопка primary заметна

Расписание:
- [ ] Дни недели — chip-row, активный в `--accent-soft`
- [ ] Статусы уроков — цвета `--ok`/`--warn`/`--err` различимы
- [ ] Popup детали (`.modal`) — открывается с spring-анимацией

Отчёт:
- [ ] Фильтры — chip-стиль
- [ ] Строки таблицы — компактные, hover работает
- [ ] Полоса слева для overdue — 4px `--warn`

Общее:
- [ ] Шрифты Manrope/JetBrains Mono подгружены
- [ ] Нет несогласованных цветов (например, остался HEX или старый OKLCH)
- [ ] Анимации плавные, не jitter

- [ ] **Step 3: Если что-то выглядит сломано — список фиксов**

Для каждого визуального бага: записать в `docs/visual-issues.md` (создать файл, если нет) → исправить → перепроверить.

После того как чеклист зелёный — переходим к Task 6.

---

### Task 6: Финальная проверка acceptance

- [ ] **Step 1: Smoke-tests из `docs/smoke-tests.md` всё ещё зелёные**

Поведение приложения не должно было сломаться. Прогнать ключевые сценарии (token validate, submit lesson, schedule, report) — функционально всё работает.

- [ ] **Step 2: Серверные тесты зелёные**

Run: `npm test`
Expected: 5/5 PASS (тесты `db.js`, `sync-failures.js` не зависят от фронта, должны проходить).

- [ ] **Step 3: Файлы созданы**

Run (PowerShell):
```powershell
Get-ChildItem public/styles.css | Select-Object FullName, Length
```
Expected: путь существует, length ≈ 5–7 KB.

- [ ] **Step 4: Не сломали SPA**

Открыть приложение, прогнать teacher-flow от логина до submit. Если всё работает — Phase 4.1 done.

---

## Откат Phase 4.1

Если визуал сломан и хочется откатить:

```powershell
Remove-Item public/styles.css
# В Index.html:
# 1. Удалить строку <link rel="stylesheet" href="/styles.css">
# 2. Восстановить старый локальный <style>-блок (из v1, до миграции токенов).
```

Поскольку git не используется, надёжный откат — это backup. Перед стартом задачи **сделайте копию Index.html**:

```powershell
Copy-Item public/Index.html public/Index.html.backup-phase4-1
```

После успешного завершения Task 6 backup можно удалить.

---

## Что НЕ входит в Phase 4.1

- Никаких изменений в JS-функциях SPA.
- Никаких изменений в DOM-структуре Index.html.
- Никаких изменений в server.js / services/.
- Admin SPA (admin.html) — это Phase 4.3.
- Admin endpoints — Phase 4.2.

---

## После завершения Phase 4.1

Следующий план — **Phase 2 (PG Backfill)** по spec'у миграции v2. Phase 4.2 и 4.3 (admin endpoints + SPA) идут после Phase 2.
