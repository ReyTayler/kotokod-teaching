# PostgreSQL Migration — Phase 1 (Repository Layer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ввести слой `services/repository.js` как единственную точку доступа к данным из `server.js`. На этой фазе репозиторий — тупой прокси над `services/sheets.js`, поведение приложения не меняется.

**Architecture:** Чистый рефакторинг. Структура: `server.js → services/repository.js → services/sheets.js`. После Phase 3 второй стрелки не будет, репозиторий начнёт ходить в PG. Сейчас просто переключаем импорт и зовы — за счёт этого Phase 3 потом сводится к подмене внутренностей репозитория.

**Tech Stack:** Без новых зависимостей. Только Node.js.

**Reference spec:** `docs/superpowers/specs/2026-05-25-postgres-migration-v2-design.md` (раздел «Phase 1»).

**Project state note:** Проект не под git. Шаги `commit` пропущены. Если планируете git init — коммитьте после каждой задачи.

---

## Файловая структура Phase 1

| Путь | Создаётся/Меняется | Ответственность |
|------|--------------------|-----------------|
| `services/repository.js` | создаётся | Прокси над `sheets.js`. В Phase 3 здесь появятся PG-реализации. |
| `server.js` | меняется | Импорт `sheets` заменяется на `repo`; все 19 вызовов `sheets.X()` → `repo.X()`. |
| `docs/smoke-tests.md` | создаётся | Ручной чеклист регрессионного тестирования. |

Файлы `services/sheets.js`, `services/db.js`, `services/sync-failures.js`, `services/cache.js`, `services/calculator.js`, `db/`, `public/Index.html`, `.env`, `package.json` — **не трогаем**.

---

### Task 1: Создать `services/repository.js`

**Files:**
- Create: `services/repository.js`

- [ ] **Step 1: Написать файл-прокси**

Содержимое целиком:

```js
// services/repository.js
//
// Единая точка доступа к данным для server.js.
// На Phase 1 — тонкий прокси над services/sheets.js.
// В Phase 3 внутренности подменяются на PG-реализации,
// публичный API остаётся идентичным.

const sheets = require('./sheets');

module.exports = {
  // Чтение
  readTokens:        sheets.readTokens,
  readAllStudents:   sheets.readAllStudents,
  readStudentsRange: sheets.readStudentsRange,
  readFilledLessons: sheets.readFilledLessons,

  // Запись
  batchUpdateCounters: sheets.batchUpdateCounters,
  appendToJournal:     sheets.appendToJournal,
};
```

> Сигнатуры — те же, что в `sheets.js`. Это даёт mechanical replace в `server.js` без правок логики вызовов.

- [ ] **Step 2: Sanity check — модуль грузится без ошибок**

Run: `node -e "console.log(Object.keys(require('./services/repository')))"`

Expected:
```
[
  'readTokens',
  'readAllStudents',
  'readStudentsRange',
  'readFilledLessons',
  'batchUpdateCounters',
  'appendToJournal'
]
```

Если в выводе нет какого-то ключа — `sheets.js` не экспортирует эту функцию (баг рефакторинга). Чинить до перехода к Task 2.

---

### Task 2: Переписать `server.js` на `repo`

**Files:**
- Modify: `server.js`

**Подход:** механическая замена. Сначала меняем импорт, потом — все 19 callsite. На любом шаге сервер должен оставаться запускаемым (но если делаем все правки одним заходом — это нормально, лишь бы тест в Task 3 был зелёным).

- [ ] **Step 1: Заменить импорт в начале файла**

В `server.js:6` (текущая строка):
```js
const sheets = require('./services/sheets');
```
Заменить на:
```js
const repo = require('./services/repository');
```

- [ ] **Step 2: Заменить все `sheets.X()` на `repo.X()` (19 мест)**

Используйте Replace All в редакторе с поиском `sheets.` и заменой на `repo.` — **с проверкой**, что в server.js больше нигде нет совпадений на это слово (например, в комментариях).

После замены проверьте grep-ом, что нигде не осталось `sheets.`:

Run: `node -e "const fs = require('fs'); const src = fs.readFileSync('server.js', 'utf8'); const matches = src.match(/sheets\./g); console.log('sheets. occurrences:', matches ? matches.length : 0);"`

Expected: `sheets. occurrences: 0`

> Если осталось — это либо комментарий с «sheets.» (правьте вручную), либо забытый callsite (тоже правьте).

- [ ] **Step 3: Проверить, что server.js парсится**

Run: `node -c server.js`

Expected: команда возвращается без ошибок (выводит пусто и exit 0). Если SyntaxError — посмотреть указанную строку.

---

### Task 3: Запустить сервер и проверить, что прогрев кеша не сломался

- [ ] **Step 1: Поднять сервер в фоне**

Run (PowerShell): `Start-Job -ScriptBlock { Set-Location 'C:\Users\ilyap\TestKOTOKOD'; npm start } | Out-Null; Start-Sleep -Seconds 10; Get-Job | Receive-Job -Keep`

Expected (после ~5-10 секунд прогрева кеша):
```
> journal-backend@1.0.0 start
> node server.js

🚀 Сервер запущен на порту 3000
📊 Таблица учеников: <id>
📝 Таблица журнала: <id>
🔥 Прогреваем кэш...
📚 Читаем учеников из таблицы: <id>
📄 Получено строк из таблицы: <N>
📊 Всего преподавателей: <N>
📊 Всего групп: <N>
✅ Кэш прогреят! Данные загружены в память.
```

Если упало с `TypeError: repo.X is not a function` — какая-то функция не пробрасывается в repository.js. Проверить экспорты `services/sheets.js`.

- [ ] **Step 2: Сделать пробный запрос (валидация невалидного токена)**

Run: `Invoke-RestMethod -Uri "http://localhost:3000/api/validateToken" -Method POST -Body '{"token":"INVALID"}' -ContentType "application/json"`

Expected: `valid=False, error='Неверный токен'`

- [ ] **Step 3: Остановить сервер**

Run: `Get-Job | Stop-Job; Get-Job | Remove-Job`

---

### Task 4: Создать `docs/smoke-tests.md`

**Files:**
- Create: `docs/smoke-tests.md`

- [ ] **Step 1: Записать чеклист**

Содержимое:

```markdown
# Smoke tests (ручной чеклист)

Прогоняется перед мерджем каждой фазы миграции и после крупных рефакторингов.
Сервер локально: `npm start` → http://localhost:3000.

Авторизация: для прохождения чеклиста нужен валидный teacher-токен.
Если токенов нет — посмотреть на листе «Токены» в таблице журнала.

---

## Авторизация
- [ ] /api/validateToken с **валидным** токеном → `{valid: true, teacher: '...'}`
- [ ] /api/validateToken с **невалидным** токеном → `{valid: false, error: 'Неверный токен'}`
- [ ] /api/validateToken с **пустым** body → ошибка валидации

## Чтение данных
- [ ] /api/getData с валидным токеном → возвращает группы только этого препода
- [ ] /api/getAllData (для замен) → возвращает все группы всех преподов
- [ ] /api/refreshData → сбрасывает кеш, читает заново, возвращает данные препода

## Отправка урока (submitLesson)
- [ ] Обычный урок (90 минут, 3 ученика, 2 присутствуют) → success, payment > 0, lessonNum = previous + 1
- [ ] 45-минутный урок (в названии группы есть «45 минут») → шаг счётчика 0.5, оплата по тарифу halfLesson
- [ ] Замена (isSubstitution=true, originalTeacher указан) → запись в журнал с колонками «Замена» / «За кого»

## Отчёт и расписание
- [ ] /api/report → таблица текущей недели, статусы done/pending/overdue корректны
- [ ] /api/report/refresh → сбрасывает кеш и редиректит на /api/report
- [ ] /api/schedule → все группы со временами, отсортированные по дню+времени
- [ ] /api/schedule/refresh → сбрасывает кеш и редиректит на /api/schedule

## SPA (public/Index.html)
- [ ] Открыть http://localhost:3000 → загружается интерфейс
- [ ] Ввести валидный токен → попадаем на экран со списком групп
- [ ] Выбрать группу → видны ученики, можно отметить присутствие
- [ ] Отправить урок → success-сообщение, счётчики обновились в таблице Sheets

---

## Когда чеклист красный

Если хотя бы один пункт упал — **не мерджить** фазу, разбираться. До Phase 3 (cutover) откат прост: вернуть импорт `const sheets = require('./services/sheets')` и заменить `repo.` обратно на `sheets.`.
```

---

### Task 5: Прогнать smoke-tests руками

> Этот шаг автоматизировать нельзя — нужен валидный teacher-токен и взгляд глазами на UI/таблицы. План явно фиксирует ручную проверку как условие приёмки.

- [ ] **Step 1: Поднять сервер**

Run: `npm start` (в отдельном терминале, оставить открытым)

- [ ] **Step 2: Пройти все пункты `docs/smoke-tests.md`**

Открыть `docs/smoke-tests.md`, по чеклисту — `Invoke-RestMethod` для curl-проверок, браузер для SPA.

Все пункты должны быть зелёные. Если красные — задокументировать в комментарии к этой задаче, какой именно сломался, и чинить.

- [ ] **Step 3: Остановить сервер**

Ctrl+C в окне с `npm start`.

---

### Task 6: Финальная проверка acceptance-критериев Phase 1

Из v2 spec:
> **Acceptance:**
> - `npm start` работает идентично прежнему.
> - SPA Index.html работает без регрессий.
> - Никаких новых юнит-тестов (репозиторий — тупой прокси).

- [ ] **Step 1: `npm start` работает идентично** — Task 3 ✅

- [ ] **Step 2: SPA работает** — Task 5 smoke ✅

- [ ] **Step 3: Нет регрессий в существующих тестах**

Run: `npm test`
Expected: 5/5 PASS (тесты из Phase 0 — `db.js`, `sync-failures.js` — должны проходить без изменений).

- [ ] **Step 4: В `server.js` больше нет ссылок на `sheets`**

Run: `node -e "const fs=require('fs'); const s=fs.readFileSync('server.js','utf8'); console.log('require sheets:', /require\(.+sheets/.test(s)); console.log('sheets. usage:', /\bsheets\./.test(s));"`

Expected:
```
require sheets: false
sheets. usage: false
```

- [ ] **Step 5: Файлы созданы**

Run (PowerShell): `Get-ChildItem services\repository.js, docs\smoke-tests.md | Select-Object FullName`
Expected: оба файла существуют.

---

## Откат Phase 1

Если после Phase 1 что-то сломалось и нужно вернуть как было:

```powershell
# В server.js:
# 1. Заменить `const repo = require('./services/repository')`
#    на `const sheets = require('./services/sheets')`
# 2. Заменить все `repo.` на `sheets.` (19 мест)
Remove-Item services\repository.js
```

`docs/smoke-tests.md` оставить — полезно и без рефакторинга.

---

## Что НЕ входит в Phase 1 (это Phase 2+)

- Никаких изменений в `services/sheets.js` — слой остаётся как есть.
- Никаких новых endpoint'ов.
- Никакой PG-логики в `repository.js` — только прокси.
- Никаких unit-тестов на репозиторий — он сейчас не делает ничего самостоятельного.
- `services/cache.js` — пересмотр откладываем до Phase 3.

---

## После завершения Phase 1

Следующий план — **Phase 2 (Backfill)**: `scripts/backfill.js` + `scripts/verify-backfill.js`. Пишется отдельно после стабилизации Phase 1.

Параллельно можно начать **брейншторм Phase 4 (Admin UI + фронтенд-refresh)**, потому что он не зависит от Phase 2/3, а только от наличия PG-схемы (есть).
