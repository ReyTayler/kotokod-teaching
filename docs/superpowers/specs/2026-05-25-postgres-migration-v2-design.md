# Миграция journal-backend с Google Sheets на PostgreSQL — v2

**Дата:** 2026-05-25
**Статус:** Design approved, готов к написанию плана реализации (Phase 1+)
**Заменяет:** [`2026-05-25-postgres-migration-design.md`](./2026-05-25-postgres-migration-design.md) (v1)

## Почему v2

v1 предполагал безопасный dual-write: Sheets — источник правды, PG — теневая копия, постепенный гранулярный cutover с parity-проверками. В ходе обсуждения выяснилось:

1. Вкладки «Журнал группы», «Журнал индивы», «Зарплата» в Sheets — **чистый лог для приложения**, никто не смотрит их руками.
2. Пользователь не планирует продолжать редактировать данные в Sheets — он готов вносить новых учеников/группы/токены **прямо через приложение** (новый admin UI).

При таких условиях dual-write — лишний слой. v2 делает PG источником правды сразу после backfill, Sheets полностью выводится из контура.

## Цель

Перевести journal-backend целиком на PostgreSQL за минимум фаз: один backfill из Sheets, один cutover, удаление Sheets-кода. Параллельно добавить в SPA admin UI для управления статическими данными (ученики, группы, токены, направления), которые раньше редактировались в Sheets.

## Ключевые решения

| Решение | Выбор |
|---------|-------|
| Источник правды | **PG с момента cutover** (Sheets — input для разового импорта) |
| Хостинг PostgreSQL | Локально — нативный Windows-installer; прод — `apt install postgresql-15` на Beget VPS. Без Docker. |
| Стратегия по данным | Однократный exhaustive backfill + cutover. Без dual-write. |
| Sheets после cutover | Заморожена как архив; код Sheets-интеграции удаляется. |
| Sync Sheets → PG после cutover | **Нет.** Все правки идут через admin UI приложения. |
| Архитектурный паттерн | Repository pattern (та же абстракция, что и в v1) |
| Query library | Нативный `pg` без ORM |
| Фронтенд-refresh | Связывается с admin UI — отдельный блок работы после Phase 3 cutover |

## Текущее состояние (что уже сделано)

**Phase 0 завершена** (см. `docs/superpowers/plans/2026-05-25-phase0-postgres-foundation.md`):
- PostgreSQL 15 локально, БД `journal`, пользователь `journal`.
- Схема из 11 таблиц + `schema_migrations`.
- `pg@8.21.0`, `services/db.js` (с `tx()` и заглушками), `services/sync-failures.js` (нужен для логирования общих PG-ошибок).
- `npm run db:migrate`, `npm test` — работают; 5/5 тестов зелёные.
- `server.js` не изменён, всё ещё работает на Sheets.

## Архитектура

```
[Phase 1-2: переходное состояние]

server.js
    │
    ▼
services/repository.js
    │
    ├──► services/sheets.js  (только для импорта в Phase 2)
    └──► services/db.js       (заполняется реализациями)
                │
                ▼
            PostgreSQL


[Phase 3+: финальное состояние]

server.js
    │
    ▼
services/repository.js
    │
    ▼
services/db.js
    │
    ▼
PostgreSQL
```

После Phase 3 файлы `services/sheets.js`, `service-account-key.json`, зависимость `googleapis` — удаляются.

### Изменения в существующих файлах

- `server.js` — все `sheets.X()` заменяются на `repo.X()` в Phase 1; в Phase 3 — никаких структурных правок, только добавляются новые admin-endpoint'ы.
- `services/sheets.js` — остаётся как есть до Phase 5 (используется только backfill-скриптом); в Phase 5 удаляется.
- `services/cache.js` — пересматривается в Phase 3. С PG на той же машине большой кеш не нужен; возможно, оставим только тонкий слой или удалим.
- `services/calculator.js` — не трогаем, чистая функция.
- `public/Index.html` — переписывается в Phase 4 (admin UI + визуальный refresh). До тех пор не меняется.

### Новые файлы

- `services/repository.js` — единая точка для бизнес-логики, оркестрирует Sheets/PG в Phase 1-2, чистый PG в Phase 3+.
- `scripts/backfill.js` — exhaustive импорт Sheets → PG.
- `scripts/verify-backfill.js` — после backfill сравнивает count-ы и суммы между Sheets и PG, печатает расхождения. **Запускается вручную перед Phase 3 cutover.**
- Новые endpoint'ы в `server.js` (Phase 4): `/api/admin/students`, `/api/admin/groups`, `/api/admin/teachers`, `/api/admin/tokens`, `/api/admin/directions`, `/api/admin/group-memberships`.

### Конфигурация

`.env` остаётся, но логика флагов меняется:
- `DUAL_WRITE_ENABLED` — выбрасывается в Phase 3 (не использовался по делу).
- `READ_FROM` — выбрасывается в Phase 3.
- Добавляется `ADMIN_PASSWORD` (или другая авторизация) для admin-endpoint'ов в Phase 4.

## Схема PostgreSQL

Схема из v1 уже создана и используется. Полное определение — в [`db/migrations/001_initial_schema.sql`](../../db/migrations/001_initial_schema.sql).

**Изменения относительно v1:**
- Поля `group_memberships.sheet_row` и `directions.sheet_name` — остаются для использования backfill-скриптом и удаляются в Phase 5 миграцией `002_drop_sheets_columns.sql`.
- Все остальные таблицы — без изменений.
- `sync_failures` — остаётся как general-purpose error log для PG-ошибок в операционных endpoint'ах. Меняется только семантика (раньше — отлов dual-write расхождений; теперь — фиксация неперехваченных ошибок при операциях).

**Напоминание про инварианты схемы** (детали в v1):
- Дробные счётчики `numeric(6,1)` для 45-минуток.
- `lesson_duration_minutes` в `groups` И в `lessons` (исторический snapshot).
- `enrollment_status` + `frozen_until_month` вместо одной строки.
- `submitted_by_token` — текст, не FK (исторический след).
- День недели — 0=Вс..6=Сб (JS `getDay()`).

## Phases

### Phase 0 — Foundation ✅ ВЫПОЛНЕНА

См. `docs/superpowers/plans/2026-05-25-phase0-postgres-foundation.md`.

### Phase 1 — Repository layer

**Цель:** ввести `services/repository.js` как единый интерфейс между `server.js` и хранилищем. Поведение приложения не меняется — все методы репозитория пока делегируют в `services/sheets.js`.

**Объём:**
- Создать `services/repository.js` с публичным API: `readTokens`, `readAllStudents`, `readFilledLessons`, `submitLesson`.
- В `server.js` все `sheets.X()` → `repo.X()`. Удалить прямой импорт `sheets`.
- Прогнать smoke-tests (см. `docs/smoke-tests.md` — создаётся в Phase 1).

**Acceptance:**
- `npm start` работает идентично прежнему.
- SPA Index.html работает без регрессий (вход, getData, submitLesson, report, schedule, refresh).
- Никаких новых тестов (репозиторий — тупой прокси).

**Откат:** rollback изменений в `server.js`, удалить `services/repository.js`.

### Phase 2 — Backfill (exhaustive)

**Цель:** перелить всё из Sheets в PG. Идемпотентно, можно гонять много раз против пустой/непустой PG.

**Объём:**
- `scripts/backfill.js` — импортирует **все** данные:
  1. `directions` ← колонка S таблицы учеников
  2. `teachers` ← колонка L + лист «Токены»
  3. `tokens` ← лист «Токены»
  4. `groups` + `group_schedule_slots` ← колонка M (парсинг времени)
  5. `students` ← колонки A/C/J + поля под NULL: birth_date/phone/school_grade/platform_id/parent_name/first_purchase_date/enrollment_status
  6. `group_memberships` ← связка с counters/remaining/start_date/sheet_row
  7. `lessons` + `lesson_attendance` ← листы «Журнал группы», «Журнал индивы»
  8. `payroll` ← лист «Зарплата»
- Аргументы: `--dry-run`, `--step=<name>`, прогресс в stderr, итог JSON в stdout.
- `scripts/verify-backfill.js` — сравнение count-ов и сумм Sheets vs PG. Печатает расхождения. Запускается **после** backfill, **до** cutover. Удаляется или забывается в Phase 5.

**Идемпотентность:**
- Upsert по натуральным ключам (`teachers.name`, `groups.name`, `tokens.token`, `students.full_name`, `directions.name`).
- Для журнала — временный staging-индекс `UNIQUE (lesson_date, group_id, lesson_number, submitted_by_token)`, чтобы повторный прогон не дублировал записи.

**Acceptance:**
- `verify-backfill.js` показывает 0 расхождений по count(teachers), count(students), count(groups), count(group_memberships), sum(lessons_done), count(lessons), count(payroll).
- Глазами просмотрены 10 случайных учеников, 5 случайных уроков, 3 случайных payroll-записи.

**Откат:** `npm run db:reset` обнуляет PG. Backfill можно прогнать заново.

### Phase 3 — Cutover

**Цель:** репозиторий и операционные endpoint'ы работают **только из PG**. Запись в Sheets отключается.

**Объём:**
- Имплементировать в `services/db.js` функции, бывшие заглушками: `incrementCounters`, `insertLesson`, `insertAttendance`, `insertPayroll`. + новые `readTokens`, `readAllStudents`, `readFilledLessons` — реализации поверх PG.
- В `services/repository.js` все методы переписываются на PG. Импорт `sheets` — убран.
- `services/cache.js` — пересмотр. С PG на той же машине latency 1-5мс, кеш в виде snapshot становится избыточным. Решения: либо удалить `cache.js`, либо оставить как тонкий запоминатель (TTL 30 сек, только для частых read-эндпоинтов).
- `submitLesson`: меняется на PG-tx (все операции в одной транзакции: счётчики, lesson, attendance, payroll).
- ENV: `DUAL_WRITE_ENABLED`, `READ_FROM` — удаляются из `.env` и кода.

**Что НЕ делается в Phase 3:**
- Не удаляется `services/sheets.js` (понадобится backfill-скрипту в случае повторного прогона).
- Не удаляются Sheets-таблицы (заморозка как архив).

**Acceptance:**
- Все 8 эндпоинтов работают на PG, ответы совпадают с пре-cutover скриншотами/выгрузками.
- `submitLesson` атомарен (либо всё в PG, либо ничего; на падении ничего не остаётся в полузаписанном состоянии).
- `sync_failures` пуста после недели прогона.

**Откат:** сложный — после Phase 3 в PG будут операционные записи, которых нет в Sheets. Откат = backfill из PG обратно в Sheets (зеркальный скрипт нужно написать **до** Phase 3, на случай экстренного отката).

### Phase 4 — Admin UI

**Цель:** заменить редактирование Sheets на формы внутри SPA. **Объединяется с фронтенд-refresh** (отдельный design-блок).

**Минимальный набор CRUD:**

| Сущность | Операции |
|----------|----------|
| Students | create, edit, deactivate (enrollment_status), remove from group |
| Groups | create, edit (name, direction, teacher, slots, duration, frequency, vk_chat), archive |
| Teachers | create, edit (name, email, phone) |
| Tokens | issue (генерация случайной строки или ручной ввод), revoke (active=false) |
| Directions | create, edit (name, is_individual) |
| Group memberships | add student to group, remove student from group, edit lessons_done/remaining |

**Эндпоинты:** `POST/PUT/PATCH/DELETE /api/admin/<entity>`. Защита — отдельная авторизация для admin-ролей (не сам teacher-token, который у каждого препода свой). Возможные варианты: master-password из `.env`, или отдельный токен «admin», или роль `admin` у teacher-токена. **Решается на брейншторме Phase 4.**

**Фронт:** новые формы/таблицы в `public/Index.html`. Брейншторм для Phase 4 включает и UX (где admin-секция живёт, как навигация) и визуальный обновлённый стиль (если делаем refresh параллельно).

**Acceptance:** через admin UI можно полностью повторить любую правку, которая раньше делалась в Sheets. Sheets больше **не нужен** для повседневной работы.

### Phase 5 — Cleanup

**Цель:** окончательно отвязаться от Google Sheets.

**Объём:**
- Удалить `services/sheets.js`.
- Удалить `service-account-key.json` (из репозитория и из дерева; если был, см. project guidelines).
- `npm uninstall googleapis`.
- Удалить `STUDENTS_SPREADSHEET_ID` и `JOURNAL_SPREADSHEET_ID` из `.env` и `.env.example`.
- Миграция `002_drop_sheets_columns.sql`:
  ```sql
  ALTER TABLE group_memberships DROP COLUMN sheet_row;
  ALTER TABLE directions DROP COLUMN sheet_name;
  ```
- Удалить `scripts/backfill.js` и `scripts/verify-backfill.js` (или переместить в `docs/archive/`).

**Acceptance:** `grep -ri sheet src/` пусто (кроме docs/archive); сервер стартует без Google credentials; всё работает.

## Backfill — детали

Уже описано в Phase 2. Дополнительные нюансы для скрипта:

- **Парсинг дня/времени из имени группы** — переиспользует регулярку, что уже в server.js (`(день_недели)[^0-9]*(чч)[:.-](мм)`).
- **`lesson_duration_minutes`:** 45 если в имени группы `/45\s*минут/i`, иначе 90 (60 не появляется в legacy-данных).
- **`lessons_per_week`** — `count(slots)`, считается из распарсенного.
- **`enrollment_status`** — по умолчанию `enrolled`. Если в Sheets есть колонка статуса, парсится: `Да` → enrolled, `Нет` → not_enrolled, `Нет январь`/`Нет декабрь` → frozen + month, `Нет отказ` → declined. Если колонки нет — всех в `enrolled`.
- **Журнал → lessons:** строки журнала группируются по `(date, group, lesson_number)` в один `lesson`. Каждая строка — это один `lesson_attendance` (present=true если «Был», false если «Не был»).
- **Зарплата → payroll:** связь с lessons по `(group, date, lesson_number)`. Если в Sheets есть строка зарплаты без соответствующего урока — лог ошибки и skip.

## Что осталось от v1

- ✅ **Phase 0** — выполнена как есть.
- ✅ **Схема БД** — без изменений (`sheet_row`/`sheet_name` живут до Phase 5).
- ✅ **Repository pattern** — Phase 1 идентичен.
- ✅ **`services/db.js`, `services/sync-failures.js`** — переиспользуются.
- ✅ **МСК-инвариант, half-lesson правило, порядок counters-before-journal** — переносятся в PG-реализацию `submitLesson` (в одной tx — порядок неважен внутри tx, но конвенция кода сохраняется).

## Что отбрасывается из v1

- ❌ Гранулярные per-endpoint флаги `READ_FROM=db|sheets` — не нужны, cutover атомарный.
- ❌ Phase 3 «dual-write enabled» — выпадает целиком.
- ❌ Phase 4 «гранулярный cutover чтения» — выпадает.
- ❌ Phase 5 «cutover на запись» — заменён на единый Phase 3 (Cutover).
- ❌ `scripts/parity-check.js` — заменён на одноразовый `verify-backfill.js`.
- ❌ Cron-проверка parity ежедневно — не нужна (нет постоянной двойной записи).

## Тестирование

- **Phase 1:** ручной smoke-test через `docs/smoke-tests.md` (создаётся в Phase 1).
- **Phase 2:** `verify-backfill.js` сравнивает PG vs Sheets count-ами и суммами + ручная сверка 10/5/3 строк.
- **Phase 3:** перед cutover делается **снимок ответов всех endpoint'ов** через curl/Postman (`docs/cutover-baseline.md`), после cutover ответы сравниваются. Smoke-test ручной из `docs/smoke-tests.md`. Unit-тесты для `services/db.js` дописываются (для реальных функций, а не заглушек).
- **Phase 4:** ручное тестирование admin UI через формы.
- **Phase 5:** один прогон smoke-test после удаления `sheets.js`.

## Риски и митигации

1. **Backfill пропустит данные.** Митигация: `verify-backfill.js` обязателен; ручная сверка 10/5/3 строк; backfill можно перегонять.
2. **Cutover оставит баги в PG-реализации.** Митигация: pre-cutover baseline curl-снимки; PG-tx гарантирует атомарность.
3. **Нет admin UI на момент cutover → нельзя добавить ученика.** Митигация: либо ускоряем Phase 4 до cutover, либо в Phase 3 оставляем эндпоинт «импорт одного ученика из Sheets» как временный костыль.
4. **Откат после Phase 3 болезненный.** Митигация: до Phase 3 пишется зеркальный скрипт `scripts/dump-pg-to-sheets.js` (на крайний случай); Sheets-таблица не удаляется до Phase 5.
5. **`googleapis` зависимость и `service-account-key.json` остаются в репозитории до Phase 5.** Это не риск кода, а вопрос безопасности — `service-account-key.json` уже сейчас не должен попадать в git. Стандартное `.gitignore` нужно при инициализации git.

## Следующий шаг

Передать spec в skill `superpowers:writing-plans` для составления implementation plan по **Phase 1 — Repository layer**. Это наименее рискованный шаг и выгодно сделать его до Phase 2, чтобы потом дополнять repository PG-реализациями уже из чистого слоя.

Phase 2-5 — отдельные планы, пишутся после стабилизации предыдущей фазы.
