# Миграция journal-backend с Google Sheets на PostgreSQL (v1, SUPERSEDED)

> ⚠️ **Этот документ заменён** на [`2026-05-25-postgres-migration-v2-design.md`](./2026-05-25-postgres-migration-v2-design.md).
> Причина: пользователь решил отказаться от dual-write/parity-фаз. Новый план — однократный backfill, затем PG как единственный источник правды, Sheets полностью отключается. Phase 0 этого документа выполнена и переиспользована в v2.
> Текст ниже сохранён как историческая справка.

---

**Дата:** 2026-05-25
**Статус:** Superseded
**Целевое окружение:** локально — нативный PostgreSQL для Windows (installer с postgresql.org); прод — Beget VPS (Ubuntu 22.04, 2 CPU / 2 ГБ RAM / 30 ГБ NVMe), `apt install postgresql-15`. **Docker в проекте не используется.**

## Цель

Перевести данные journal-backend с Google Sheets на PostgreSQL поэтапно, без даунтайма и без риска потери данных. На время разработки и тестирования — писать в оба хранилища (dual-write); Google Sheets остаётся источником правды до полного cutover.

## Ключевые решения (зафиксированы при брейншторме)

| Решение | Выбор |
|---------|-------|
| Источник правды во время dual-write | Sheets (PG — теневая копия) |
| Хостинг PostgreSQL | Локально — нативный Windows-installer; прод — `apt install postgresql-15` рядом с Node на VPS (без Docker) |
| Стратегия по существующим данным | Одноразовый backfill при включении dual-write |
| Поведение при ошибке записи в PG | Log + запись в `sync_failures`, запрос возвращает success |
| Стиль схемы | Сразу нормализованная (никаких 1:1 зеркал Sheets) |
| Архитектурный паттерн | Repository pattern — единая точка над `sheets.js` и `db.js` |
| Query library | Нативный `pg` без ORM |

## Архитектура слоёв

```
server.js (эндпоинты)
        │
        ▼
services/repository.js          ← новый. Единая точка для бизнес-логики.
        │
   ┌────┴────┐
   ▼         ▼
sheets.js   db.js               ← новый. Тонкий слой над `pg`.
   │         │
   ▼         ▼
Google     PostgreSQL
Sheets     (локально/на VPS)
        │
        ▼
services/sync-failures.js       ← логирует ошибки PG в таблицу sync_failures
```

### Изменения в существующих файлах

- `server.js` — все вызовы `sheets.xxx()` заменяются на `repo.xxx()`. Импорт `sheets` удаляется.
- `services/sheets.js` — не трогаем. Его теперь дёргает только repository.
- `services/cache.js` — не трогаем. Привязан к репозиторию, которому всё равно, откуда данные.
- `services/calculator.js` — не трогаем.

### Новые файлы

- `services/repository.js` — публичный API (`readTokens`, `readAllStudents`, `submitLesson`, ...). Внутри — оркестрация Sheets+PG.
- `services/db.js` — `Pool` из `pg`, типизированные функции (`appendLesson`, `incrementLessonCounter`, ...).
- `services/sync-failures.js` — логирование ошибок PG, fallback в файл.
- `db/migrations/001_initial_schema.sql` — вся схема одним файлом.
- `db/migrate.js` — минимальный runner: читает папку, проверяет `schema_migrations`, прогоняет недостающее.
- `scripts/backfill.js` — одноразовый перелив Sheets → PG.
- `scripts/parity-check.js` — сверяет Sheets vs PG, печатает расхождения.
- `docs/smoke-tests.md` — ручной чеклист перед мерджем каждой фазы.
- `services/db.test.js` — unit-тесты низкоуровневых db-функций через `node:test`.

### Конфигурация (`.env`)

```
DATABASE_URL=postgresql://user:pass@localhost:5432/journal
DUAL_WRITE_ENABLED=true        # выключаемо без деплоя
READ_FROM=sheets               # sheets|db — глобальный флаг для будущего cutover
# В Phase 4 заменяется на пер-эндпоинт флаги:
# READ_SCHEDULE_FROM=sheets
# READ_REPORT_FROM=sheets
# и т.д.
```

## Схема PostgreSQL

Все таблицы — `snake_case`, money через `numeric`, времена через `timestamptz` (в UTC, конверсия в МСК на уровне приложения как сейчас).

```sql
-- Справочники
teachers (
  id           serial PRIMARY KEY,
  name         text NOT NULL UNIQUE,
  email        text,
  phone        text,
  created_at   timestamptz NOT NULL DEFAULT now()
);

tokens (
  token        text PRIMARY KEY,
  teacher_id   int NOT NULL REFERENCES teachers(id),
  active       bool NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now()
);

directions (
  id            serial PRIMARY KEY,
  name          text NOT NULL UNIQUE,           -- "Python", "Scratch", "Индивидуальные"
  sheet_name    text NOT NULL,                  -- имя листа в Sheets для маппинга
  is_individual bool NOT NULL                   -- определяет колонку счётчика (M vs L)
);

-- Группы и состав
groups (
  id                      serial PRIMARY KEY,
  name                    text NOT NULL UNIQUE,
  direction_id            int NOT NULL REFERENCES directions(id),
  teacher_id              int NOT NULL REFERENCES teachers(id),
  is_individual           bool NOT NULL,
  lesson_duration_minutes int NOT NULL DEFAULT 90
                          CHECK (lesson_duration_minutes IN (45, 60, 90)),
  lessons_per_week        int NOT NULL DEFAULT 1
                          CHECK (lessons_per_week BETWEEN 1 AND 7),
  group_start_date        date,
  vk_chat                 text,
  created_at              timestamptz NOT NULL DEFAULT now()
);

group_schedule_slots (
  id           serial PRIMARY KEY,
  group_id     int NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  day_of_week  int NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),  -- 0=Вс ... 6=Сб (JS getDay)
  start_time   time NOT NULL,
  UNIQUE (group_id, day_of_week, start_time)
);
CREATE INDEX ON group_schedule_slots(day_of_week, start_time);
-- Инвариант (на уровне приложения): count(slots для group_id) === groups.lessons_per_week

students (
  id                  serial PRIMARY KEY,
  full_name           text NOT NULL,
  birth_date          date,
  phone               text,
  school_grade        int CHECK (school_grade BETWEEN 1 AND 11),
  platform_id         text,
  parent_name         text,
  first_purchase_date date,
  age                 int,                            -- legacy: возраст из Sheets
  pm                  text,
  enrollment_status   text NOT NULL DEFAULT 'enrolled'
                      CHECK (enrollment_status IN
                        ('enrolled','not_enrolled','frozen','declined')),
  frozen_until_month  int CHECK (frozen_until_month BETWEEN 1 AND 12),
  CHECK ((enrollment_status = 'frozen') = (frozen_until_month IS NOT NULL)),
  created_at          timestamptz NOT NULL DEFAULT now()
);

group_memberships (
  id              serial PRIMARY KEY,
  group_id        int NOT NULL REFERENCES groups(id),
  student_id      int NOT NULL REFERENCES students(id),
  lessons_done    numeric(6,1) NOT NULL DEFAULT 0,
  remaining       numeric(6,1) NOT NULL DEFAULT 0,
  start_date      date,
  sheet_row       int,                                -- мост к Sheets во время dual-write
  active          bool NOT NULL DEFAULT true,
  UNIQUE (group_id, student_id)
);

-- Транзакционные таблицы (append-only по природе)
lessons (
  id                      serial PRIMARY KEY,
  group_id                int NOT NULL REFERENCES groups(id),
  teacher_id              int NOT NULL REFERENCES teachers(id),
  original_teacher_id     int REFERENCES teachers(id),         -- NULL если не замена
  lesson_date             date NOT NULL,
  lesson_number           numeric(5,1) NOT NULL,
  lesson_duration_minutes int NOT NULL,                        -- историческая длительность
  lesson_type             text NOT NULL,                       -- 'regular' | 'reschedule' | 'substitution'
  record_url              text,
  submitted_at            timestamptz NOT NULL DEFAULT now(),
  submitted_by_token      text NOT NULL                        -- аудит, не FK (токен может быть отозван)
);
CREATE INDEX ON lessons(group_id, lesson_date);
CREATE INDEX ON lessons(teacher_id, lesson_date);

lesson_attendance (
  lesson_id    int NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  student_id   int NOT NULL REFERENCES students(id),
  present      bool NOT NULL,
  PRIMARY KEY (lesson_id, student_id)
);

payroll (
  id              serial PRIMARY KEY,
  lesson_id       int NOT NULL UNIQUE REFERENCES lessons(id),
  teacher_id      int NOT NULL REFERENCES teachers(id),
  total_students  int NOT NULL,
  present_count   int NOT NULL,
  payment         numeric(10,2) NOT NULL,
  penalty         numeric(10,2) NOT NULL DEFAULT 0
);
CREATE INDEX ON payroll(teacher_id, lesson_id);

-- Инфраструктура
sync_failures (
  id            bigserial PRIMARY KEY,
  occurred_at   timestamptz NOT NULL DEFAULT now(),
  operation     text NOT NULL,                  -- 'append_lesson', 'increment_counter', ...
  payload       jsonb NOT NULL,                 -- всё, что нужно для ручного повтора
  error_message text NOT NULL,
  resolved_at   timestamptz
);

schema_migrations (
  version      int PRIMARY KEY,
  applied_at   timestamptz NOT NULL DEFAULT now()
);
```

### Нюансы схемы под существующие инварианты проекта

- **Дробные счётчики:** `numeric(6,1)` в `lessons_done`, `remaining`, `lesson_number` — корректно хранит шаг `0.5` для 45-минутных групп.
- **Шаг счётчика:** `step = lesson_duration_minutes === 45 ? 0.5 : 1`. 60- и 90-минутные → шаг 1. Логика в `calculator.js`.
- **Длительность в `lessons` И в `groups`:** у группы могут поменять длительность, исторические уроки должны помнить свою.
- **`sheet_row` в `group_memberships`:** временный мостик для dual-write — когда репозиторий обновляет счётчик, ему нужно знать, какую строку трогать в Sheets. Удаляется в Phase 6.
- **`submitted_by_token` как текст, не FK:** токен может быть отозван (удалён из `tokens`), но исторический «кто провёл урок» должен остаться.
- **МСК-инвариант:** `timestamptz` в UTC, форматирование в МСК — на стороне Node (как сейчас в `calculator.js`).
- **Enrollment status:** разнесён на два поля (`enrollment_status` + `frozen_until_month`) вместо одной строки «Нет январь». Запрос «все замороженные» становится `WHERE enrollment_status='frozen'`, а UI собирает строку обратно.
- **День недели:** 0=Вс...6=Сб, как в JS `getDay()` — чтобы не плодить конверсий.

## Механика dual-write

### Порядок операций в `submitLesson`

```
1. Auth (read tokens)          → repo.readTokens()
2. Read group data             → repo.readAllStudents()  (источник: Sheets, как сейчас)
3. Расчёты в calculator.js     (без изменений)

4. SHEETS WRITES (источник правды — без них request падает):
   a. batchUpdateCounters     → sheets.batchUpdateCounters()
   b. appendToJournal         → sheets.appendToJournal()
   c. appendToJournal salary  → sheets.appendToJournal('Зарплата')

5. PG WRITES (теневая копия — в try/catch, при ошибке → sync_failures):
   try {
     await db.tx(async (client) => {
       await db.incrementCounters(client, counterUpdates);
       const lessonId = await db.insertLesson(client, lessonData);
       await db.insertAttendance(client, lessonId, students);
       await db.insertPayroll(client, lessonId, payrollData);
     });
   } catch (err) {
     await syncFailures.record('submit_lesson', payload, err);
   }

6. Response → success (UX не зависит от PG)
```

### Принципы

- **Sheets всегда первым.** Если Sheets упал — PG не трогаем, request падает. Инвариант «счётчики до журнала» внутри Sheets-блока не меняется.
- **PG-операции в одной транзакции.** 4 PG-вставки в `submitLesson` = одна tx. Либо всё, либо ничего.
- **`sync_failures` хранит payload целиком.** Скрипт-репроигрыватель читает payload, дёргает `db.tx(...)`, на успехе ставит `resolved_at`.
- **Кеш не трогаем до Phase 5.** `cache.updateLessonCounter` работает поверх результата Sheets — источника правды.

### API репозитория

```js
// reads — пока проксируют в sheets.js
async readTokens()
async readAllStudents()
async readFilledLessons(weekStart)

// writes — пишут в Sheets, потом теневая запись в PG
async submitLesson({
  teacher, group, date, recordUrl, lessonType,
  isSubstitution, originalTeacher, students,
  counterUpdates, lessonData, payrollData
})
```

Репозиторий принимает уже посчитанные данные. Бизнес-расчёты остаются в `server.js` + `calculator.js`. Репозиторий — тупой исполнитель.

### Маппинг имён → id

Sheets оперирует именами (teacher, group, student_name), PG — id. Внутри репозитория:

```js
async function resolveIds({ teacher, group, students }) {
  // SELECT id FROM teachers WHERE name = $1 — иначе INSERT
  // SELECT id FROM groups WHERE name = $1 — иначе INSERT
  // SELECT id FROM students WHERE full_name = $1 — иначе INSERT
}
```

Появился новый ученик в Sheets, которого нет в PG — репозиторий **upsert-ит его на лету**. То же для групп и токенов.

### Что НЕ делаем сейчас

- Outbox/queue с фоновыми ретраями — pure log + `sync_failures`.
- Прометей/метрики — вручную через cron + parity-check.
- Изменение существующих эндпоинтов сверх замены `sheets.X()` → `repo.X()`.

## Backfill

Скрипт `scripts/backfill.js`, запуск через `npm run db:backfill`. Идемпотентный.

### Порядок переливания

```
1. teachers           — колонка L таблицы учеников (уникальные) + все с листа «Токены»
2. directions         — колонка S (уникальные)
3. groups             — колонка M, парсим день/время → group_schedule_slots
                        lesson_duration_minutes: 45 если /45\s*минут/i, иначе 90
                        is_individual по направлению "ИНДИВ"
4. tokens             — лист «Токены» (колонки E/F)
5. students           — колонка A (ФИ), C (age), J (ПМ)
                        birth_date/phone/school_grade/platform_id/parent_name/first_purchase_date — NULL
                        enrollment_status: парсинг колонки если есть, иначе 'enrolled'
6. group_memberships  — students × groups, lessons_done (Q), remaining (R),
                        sheet_row (O), start_date (N)
7. lessons + attendance — из «Журнал группы» и «Журнал индивы»,
                          группируем строки (date+group+lesson_num) → один lesson
8. payroll            — из листа «Зарплата», link by (group, date, lesson_num)
```

### Идемпотентность

Каждый блок использует upsert по натуральному ключу:

```sql
INSERT INTO teachers (name) VALUES ($1)
  ON CONFLICT (name) DO NOTHING
  RETURNING id;
```

Для журнала natural unique key отсутствует. Решение: **временный staging-индекс**

```sql
CREATE UNIQUE INDEX lessons_backfill_dedup
  ON lessons (lesson_date, group_id, lesson_number, submitted_by_token);
```

Покрывает 99% реальных дубликатов. Индекс убирается миграцией после стабилизации.

### Аргументы CLI

- `--dry-run` — читает Sheets, печатает план, не пишет.
- `--step=<name>` — прогнать только один шаг.
- Прогресс в stderr, статистика JSON в stdout.

### Что backfill НЕ делает

- Не удаляет ничего из PG. Повторный запуск = upsert поверх.
- Не «правит» расхождения. Переименованный ученик → два разных students. Это ловит `parity-check.js`.
- Не пишет в `sync_failures`. Ошибка backfill = ошибка скрипта, она в stdout/stderr.

## Фазы переезда

Каждая фаза = отдельный PR, откатывается флагом без отката кода.

### Phase 0 — Фундамент

- Нативный PostgreSQL 15 локально (Windows-installer)
- Добавить `pg` в `package.json`
- `db/migrate.js` + `001_initial_schema.sql`
- `services/db.js` — pool, `tx()`, заглушки функций
- `services/sync-failures.js`
- ENV: `DATABASE_URL`, `DUAL_WRITE_ENABLED=false`, `READ_FROM=sheets`

**Acceptance:** `npm start` работает как раньше; `npm run db:migrate` создаёт схему; ничего не пишет в PG.
**Откат:** удалить новые файлы.

### Phase 1 — Repository layer

- `services/repository.js` — пока тупой прокси в `sheets.js`
- `server.js` переписан: все `sheets.X()` → `repo.X()`

**Acceptance:** прежнее поведение, smoke-тесты пройдены.
**Откат:** `git revert`.

### Phase 2 — Backfill

- `scripts/backfill.js` готов
- Запуск `--dry-run` на тестовой копии Sheets
- Сверка глазами: 10 случайных учеников, 5 случайных уроков

**Acceptance:** `parity-check.js` показывает 0 расхождений.
**Откат:** `TRUNCATE` всех таблиц (`scripts/db-reset.js`).

### Phase 3 — Dual-write включён

- `DUAL_WRITE_ENABLED=true`
- В `repository.js` появляется PG-блок в `submitLesson`

**Acceptance:** через 7 дней — 0 расхождений, `sync_failures` пуста или содержит только разобранные incidents.
**Откат:** `DUAL_WRITE_ENABLED=false`.

### Phase 4 — Cutover чтения, гранулярно

- `READ_FROM=sheets` → пер-эндпоинт флаги
- Начинаем с read-only: `/api/schedule`, потом `/api/report`
- `services/repository.js` получает реализации `readAllStudents`/`readFilledLessons` из PG

**Acceptance:** UX не изменился (сравнение скриншотами/выгрузками).
**Откат:** флаг обратно в `sheets`.

### Phase 5 — Cutover на запись

- В `submitLesson` порядок переворачивается: **сначала PG (с tx), потом Sheets (best-effort)**
- Sheets теперь shadow copy. Sheets-fail → log + `sync_failures`, ответ всё равно success.
- Кеш переезжает на инвалидацию по PG или удаляется (PG локально на VPS отдаёт `unified_data` за миллисекунды).

**Acceptance:** неделя стабильной работы.
**Откат:** требует **подготовленного зеркального backfill из PG в Sheets ДО старта Phase 5**.

### Phase 6 — Sheets retire

- Удаляем dual-write в Sheets (или оставляем ручной бэкап раз в день — дамп из PG в новую таблицу)
- Удаляем `services/sheets.js`, `googleapis`, `service-account-key.json`
- Удаляем `group_memberships.sheet_row`, `directions.sheet_name`

**Acceptance:** неделя на одной PG без регрессий.

### Сроки

Не привязаны к датам. Минимум 7 дней между Phase 3 и Phase 4.

### Сквозной критический инвариант

До Phase 5 — Sheets-операции в `submitLesson` идут **первыми и обязательны**. Существующее правило «счётчики до журнала» внутри Sheets-блока не меняется.

## Тестирование и эксплуатация

### Что добавляем

1. **`scripts/parity-check.js`** — сверка Sheets vs PG. Запуск:
   - Локально вручную после backfill
   - На проде ежедневно по cron: `0 3 * * * cd /opt/journal && node scripts/parity-check.js > /var/log/journal/parity.log 2>&1`
   - Exit 1 при расхождении → точка для будущих алертов.

   Сверяет: `count(teachers)`, `count(students)`, `count(group_memberships)`, `sum(lessons_done)` (главный индикатор), `count(lessons)` за последнюю неделю.
   Аргументы: `--verbose`, `--since=YYYY-MM-DD`.

2. **`docs/smoke-tests.md`** — markdown-чеклист перед мерджем каждой фазы:
   ```
   [ ] validateToken: верный/неверный/пустой
   [ ] getData: показывает группы своего препода
   [ ] submitLesson обычный (90 мин, 3 ученика, 2 присутствуют)
   [ ] submitLesson 45-минутный (шаг 0.5)
   [ ] submitLesson замена (isSubstitution=true)
   [ ] /api/report: текущая неделя, статусы done/pending/overdue
   [ ] /api/schedule: все группы с временами
   [ ] /api/refreshData: сброс кеша
   ```

3. **Unit-тесты для `services/db.js`** — через `node:test` (встроен в Node ≥18). Один файл `services/db.test.js`. Покрытие:
   - `incrementCounters`
   - `insertLesson` + `insertAttendance` + `insertPayroll` в одной tx
   - rollback при ошибке внутри tx

### Что НЕ добавляем

- Mocks Google Sheets (хрупко).
- E2E через supertest (текущий код не приспособлен).
- CI (отдельный проект).

### Эксплуатация во время dual-write

Ежедневный ритуал (5 минут):

1. `tail -50 /var/log/journal/parity.log` — расхождения?
2. `SELECT count(*) FROM sync_failures WHERE resolved_at IS NULL;`
3. Если > 0 → читаем payload, чиним руками, ставим `resolved_at`.

### Бэкапы PostgreSQL на Beget VPS

```bash
# /etc/cron.daily/pg-backup
#!/bin/bash
pg_dump journal | gzip > /var/backups/journal/journal-$(date +%Y%m%d).sql.gz
find /var/backups/journal -name '*.sql.gz' -mtime +14 -delete
```

Раз в неделю — копия на внешний носитель (S3 / другой VPS / rsync на локалку). Критично после Phase 6.

### Метрики (вручную, без Prometheus)

- `count(lessons) per day` в PG vs строки журнала за день в Sheets
- `sync_failures` за сутки — должно быть 0
- Время ответа `/api/submitLesson` — не должно вырасти больше чем на 50–100мс

## Следующий шаг

Передать spec в skill `superpowers:writing-plans` для составления детального плана реализации Phase 0 (фундамент). Дальнейшие фазы планируются отдельно — каждая после стабилизации предыдущей.
