# Phase 3a — Cutover на PostgreSQL — Design

**Дата:** 2026-05-27
**Статус:** Design approved, готов к writing-plans
**Базовый spec:** [`2026-05-25-postgres-migration-v2-design.md`](./2026-05-25-postgres-migration-v2-design.md) — Phase 3 v2-плана разбита на 3a (этот документ) и 3b (admin для операционных таблиц, отдельный spec позже).

## Цель

Перевести teacher SPA (`/`) с Google Sheets на PostgreSQL. После cutover все 8 teacher-эндпоинтов читают из PG; `submitLesson` пишет в PG атомарной транзакцией. Запись в Sheets отключается. `services/cache.js` удаляется. `services/sheets.js` остаётся для backfill-скриптов до Phase 5.

## Состояние до cutover (что уже сделано)

- Phase 0-2: PG поднят, схема залита, бэкфилл прогнан с расширенными колонками (phone, birth_date, school_grade, parent_name, platform_id, first_purchase_date, enrollment_status, group_start_date, directions.color, directions.total_lessons).
- Phase 4.2/4.3: admin SPA работает на PG. CRUD по 6 сущностям.
- В PG могут быть расхождения с Sheets (правки через админку). После cutover PG — единственный источник истины; Sheets-журнал перестаёт обновляться.

## Архитектура

```
Phase 3a финальное состояние:

server.js
   │
   ▼
services/repository.js   ← thin wrapper, только read-методы
   │
   ▼
services/db.js           ← pool + tx() + все CRUD-функции
   │
   ▼
PostgreSQL

Removed:
  services/cache.js                      — удаляется
  services/sheets.js import from server  — убирается (файл остаётся)
```

`services/sheets.js` физически не удаляется (backfill-скрипты его используют); просто не подключается из `server.js` / `repository.js`.

## Маппинг read-методов на PG

| Старый метод (Sheets) | PG-реализация |
|----------------------|---------------|
| `readTokens()` → `{ [token]: teacher_name }` | `SELECT t.token, te.name FROM tokens t JOIN teachers te ON te.id = t.teacher_id WHERE t.active = true AND te.active = true`. Reduce в объект `{ [token]: te.name }`. |
| `readAllStudents()` → `{ data: {[teacher]: {[group]: {isGroup, students:[...], ...}}}, index: {[name|||group]: {sheetRow, sheetName}} }` | См. ниже «Форма readAllStudents». |
| `readFilledLessons(weekStartIso)` → `Map<key, true>` где `key = "${group_name}|${lesson_date}|${lesson_number}"` | `SELECT l.lesson_date, g.name AS group_name, l.lesson_number FROM lessons l JOIN groups g ON g.id = l.group_id WHERE l.lesson_date >= $1`. Map собирается в JS. |
| `readStudentsRange(sheetName, cell)` | **Удаляется**. Использовался только для чтения текущего значения счётчика в `submitLesson`. В PG значение читается из `group_memberships.lessons_done` прямым запросом или из `readAllStudents` cache. |

### Форма `readAllStudents()` после cutover

Старый shape, который ожидает teacher SPA и server.js endpoints:

```js
{
  data: {
    [teacherName]: {
      [groupName]: {
        isGroup: boolean,           // !is_individual
        groupName,                  // редундант
        teacherName,                // редундант
        students: [
          { name, lessonsDone, remaining, vkChat /* group-level */, ... },
          ...
        ],
        vkChat: string,             // group.vk_chat
        // и т.д. — что использует frontend
      }
    }
  },
  index: {
    [`${studentName}|||${groupName}`]: {
      sheetRow: number,             // НЕ нужно после cutover
      sheetName: string             // НЕ нужно
    }
  }
}
```

**После cutover поле `index` упрощается:** `sheetRow` и `sheetName` уходят. Структура `index` остаётся (если фронт её читает), но указывает на `{ membership_id }` (для PG-операций). Если фронт `loc.sheetRow` / `loc.sheetName` нигде не читает — `index` тоже можно дропнуть.

**Действие:** при имплементации сверить, читает ли `public/Index.html` поля `loc.*`. Если нет — выкинуть. Если да — заменить на безвредные значения, чтоб не падало.

### SQL для `readAllStudents`

```sql
SELECT
  g.id                  AS group_id,
  g.name                AS group_name,
  g.is_individual,
  g.vk_chat,
  g.lesson_duration_minutes,
  te.name               AS teacher_name,
  s.id                  AS student_id,
  s.full_name           AS student_name,
  gm.id                 AS membership_id,
  gm.lessons_done,
  gm.remaining,
  d.name                AS direction_name,
  d.sheet_name          AS direction_sheet_name   -- остаётся до Phase 5
FROM group_memberships gm
JOIN groups   g  ON g.id = gm.group_id
JOIN teachers te ON te.id = g.teacher_id
JOIN students s  ON s.id = gm.student_id
JOIN directions d ON d.id = g.direction_id
WHERE gm.active = true
  AND g.active = true
  AND te.active = true
ORDER BY te.name, g.name, s.full_name;
```

В JS перегруппировка в nested map.

## `submitLesson` → одна tx

После cutover `server.js` `POST /api/submitLesson` целиком выполняется внутри `db.tx()`:

```
tx(async client => {
  1. SELECT teacher по token из tokens (с проверкой active)
  2. SELECT group_id, students, lessons_done — текущее состояние
  3. Compute payment/penalty через services/calculator.js (без изменений)
  4. INSERT INTO lessons (lesson_date, teacher_id, group_id, original_teacher_id,
     lesson_number, lesson_duration_minutes, lesson_type, record_url, submitted_by_token)
     RETURNING id AS lesson_id
  5. UPDATE group_memberships SET lessons_done = lessons_done + $step
     WHERE id = ANY($membership_ids_of_present_students)
  6. INSERT INTO lesson_attendance (lesson_id, student_id, present) — bulk via UNNEST
  7. INSERT INTO payroll (lesson_id, teacher_id, total_students, present_count, payment, penalty)
})
```

Если любой шаг падает — `ROLLBACK`. Никаких полузаписанных состояний.

Порядок counters-before-journal больше не критичен (всё в одной tx). Конвенция кода сохраняется ради читаемости — counters остаются раньше lesson INSERT.

## Изменения в `server.js`

- Убран `const cache = require('./services/cache');` + все вызовы `cache.get/set/del/updateLessonCounter`
- `submitLesson` переписан полностью под `db.tx()` (см. выше)
- `/api/report`, `/api/schedule`, `/api/getAllData` — читают через `repo.readAllStudents()` без кеша
- Эндпоинты `/api/refreshData`, `/api/report/refresh`, `/api/schedule/refresh` — становятся **no-op** (кеша нет). Возвращают 200 / редирект ради backward-compat с фронтом. Не удаляем эндпоинты, чтобы Index.html не падал.

## `.env` cleanup

Удаляются (выбрасываются полностью из `.env.example` и из кода):
- `DUAL_WRITE_ENABLED` — не использовалось по делу
- `READ_FROM` — не использовалось
- `CACHE_TTL` — не нужно

`STUDENTS_SPREADSHEET_ID`, `JOURNAL_SPREADSHEET_ID`, `service-account-key.json` — **остаются** (нужны backfill-скриптам до Phase 5).

## Cutover процесс (runbook)

Все шаги ниже выполняются за один заход:

1. **Pre-flight:** `npm test` зелёный (66/66).
2. **Baseline snapshot:** `curl` все 8 teacher-эндпоинтов через реальные токены и сохранить ответы в `docs/baseline/`:
   - `getData-<token>.json` (1-2 токена)
   - `getAllData.json` (любой токен)
   - `validateToken-<token>.json` (valid + invalid)
   - `report.json` (текущая неделя)
   - `schedule.json`
3. **DB backup:** `pg_dump -U journal -h localhost -d journal > backups/pre-cutover-$(date +%Y-%m-%d).sql`.
4. **Имплементация:**
   - Реализовать в `services/db.js`: `readTokens`, `readAllStudents`, `readFilledLessons`, `incrementCounters`, `insertLesson`, `insertAttendance`, `insertPayroll`.
   - Переписать `services/repository.js` как thin proxy над `db.js`. Удалить импорт `sheets`.
   - Удалить `services/cache.js` + все импорты.
   - Переписать `submitLesson` в `server.js` под `db.tx()`.
   - Очистить `.env.example` от выбрасываемых ключей.
5. **Unit-тесты** для новых функций в `db.js`: `services/db.test.js` дополняется (см. «Тесты»).
6. **`npm test`** — все зелёные (≥66 + новые).
7. **`npm start`** — стартует чисто без ошибок.
8. **Post-cutover snapshot:** повторить шаг 2 в `docs/post-cutover/`.
9. **Diff verification:** `diff -r docs/baseline docs/post-cutover`. Допустимые расхождения:
   - Различия в timestamps (`fixedAt`, и т.д.)
   - Порядок элементов в массивах (если был случайным)
   - Минорные округления чисел
   Всё остальное — bug, fix-forward.
10. **Manual smoke** в браузере:
    - Открыть `/`, войти преподавателем
    - Проверить getData (список групп/учеников)
    - Отправить тестовый урок
    - Проверить, что счётчики ученика обновились
    - Проверить `/api/report` — отчёт корректен
    - Проверить `/api/schedule` — расписание корректно

## Тесты

### Новые unit-тесты в `services/db.test.js`

Используют локальную PG (есть существующий паттерн tx-тестов):

1. `readTokens()` — вставить токен, проверить return shape `{ token: name }`. Cleanup.
2. `readAllStudents()` — вставить тестовую группу+ученика, проверить shape `{ data, index }`. Cleanup.
3. `readFilledLessons(date)` — вставить тестовый lesson на дату X, проверить попадает в map при weekStart=X-1. Cleanup.
4. `insertLesson()` + `insertAttendance()` + `insertPayroll()` + `incrementCounters()` — внутри одной `tx()`, проверить все строки записались. Cleanup.
5. Rollback-тест: вызов с заведомо невалидными данными → `tx` падает → ничего не пишется.

### Существующие 66 тестов

Должны остаться зелёными. Admin auth/repo, backfill extract-функции — не затрагиваются.

### Manual smoke

Шаг 10 cutover-runbook.

## Rollback

**Catastrophe** (PG в плохом состоянии, всё сломано):
```
1. Stop server (npm start процесс)
2. psql -U journal -d journal < backups/pre-cutover-YYYY-MM-DD.sql
3. git checkout <commit-before-cutover> -- services/ server.js
4. npm start
```

**Soft-rollback** (минорный баг в коде):
- Fix-forward + restart server.
- При необходимости — точечный SQL-fix через psql.

## Что НЕ входит в Phase 3a

- Admin endpoints/UI для операционных таблиц (`lessons`, `lesson_attendance`, `payroll`) → **Phase 3b** (отдельный spec)
- Удаление `services/sheets.js`, `googleapis`, `service-account-key.json` → Phase 5
- Удаление колонок `sheet_row`/`sheet_name` из БД → Phase 5
- Удаление `STUDENTS_SPREADSHEET_ID`, `JOURNAL_SPREADSHEET_ID` из `.env` → Phase 5

## Известные риски и митигация

| Риск | Митигация |
|------|-----------|
| Frontend ждёт поля, которых PG-shape не возвращает | Baseline snapshot + diff поймает |
| `submitLesson` падает на edge-кейсах (пустой список учеников, отсутствующий токен) | Unit-тесты + manual smoke; tx гарантирует атомарность |
| Расхождения PG ↔ Sheets из-за правок в админке до cutover | Принято: PG источник истины с момента cutover. Sheets-данные «замораживаются». |
| `readAllStudents()` медленный (большой JOIN) | Profiling после cutover; добавить индекс при необходимости. Минимум 300 учеников × 170 групп — должно быть <100мс |
| Тесты гоняют против локальной PG — нужна schema | Уже есть db.test.js паттерн; новые тесты следуют тому же. |

## Acceptance

- [ ] Все 8 teacher-эндпоинтов работают на PG с identичной семантикой (curl-diff пустой / только timestamps)
- [ ] `submitLesson` атомарен — на ошибке любого шага tx откатывается
- [ ] `npm test` ≥66/66 + новые ~5 тестов
- [ ] `pg_dump` лежит в `backups/`
- [ ] `cache.js` удалён
- [ ] В Sheets-журнал и Sheets-зарплата ничего не пишется (доказывается отсутствием новых строк после теста)
- [ ] Teacher SPA `/` визуально работает идентично прежнему
