# Раздел «Синхро» в admin SPA — перенос backfill-скриптов на Python + Celery

**Дата:** 2026-07-13
**Статус:** design approved, план ещё не написан

## Проблема

`scripts/backfill-*.js`, `scripts/rebuild-payroll.js`, `scripts/rebuild-counters.js` — рабочие
Node-инструменты (читают Google Sheets, пишут/пересчитывают Postgres), но их можно запускать
только вручную из терминала. Node.js на проде больше нет и заводить его специально ради этих
скриптов не хочется (уже пробовали: пакет `nodejs` из репозиториев Ubuntu 22.04 оказался версии
12 — EOL, плюс притащил с собой лишние GUI-пакеты через транзитивные зависимости). Нужен способ
запускать эти операции из admin SPA, руками, без Node на сервере.

## Решение

Переписать все 8 скриптов на Python как Celery-задачи внутри нового Django-приложения
`apps/sync`, и завести новый раздел «Синхро» в admin SPA, откуда суперадмин может их
запускать и видеть результат.

## Область переноса

| Действие в UI | Источник (Node) | Читает Sheets? | Пишет в БД |
|---|---|---|---|
| Преподаватели | `scripts/backfill-teachers.js` | да | `teachers` |
| Группы | `scripts/backfill-groups.js` | да | `groups`, `group_schedule_slots` |
| Ученики + абонементы | `scripts/backfill-students.js` | да | `students`, `group_memberships` |
| Занятия + посещаемость | `scripts/backfill-lessons.js` | да | `lessons`, `lesson_attendance` |
| Оплаты (только новые) | `scripts/backfill-payments.js` (режим `--append`) | да | `payments` |
| Зарплата (из Sheets) | `scripts/backfill-payroll.js` | да | `payroll` |
| Зарплата по урокам (пересчёт) | `scripts/rebuild-payroll.js` | нет | `payroll` (из `lessons`+`lesson_attendance`) |
| Счётчики уроков групп (пересчёт) | `scripts/rebuild-counters.js` | нет | `group_memberships.lessons_done` (из `lesson_attendance`) |
| Запустить всё | `scripts/backfill-all.js` | да | оркестрирует teachers→groups→students→lessons→payroll (БЕЗ payments) |

**Явно вне области:** `scripts/create-account.js`, `scripts/db-truncate.js` (деструктивный,
никогда не в admin UI) — остаются dev-инструментами только для терминала. Режим
`backfill-payments.js --reset` (полная перезаливка с удалением старых backfill-записей) тоже
остаётся терминальным (Django management command), в UI недоступен.

## Архитектура

```
Admin SPA ("Синхро")
   │  POST /api/admin/sync/<action>/run   { dry_run: bool }
   ▼
DRF view (IsSuperAdmin) → task = run_<action>.delay(dry_run) → 202 { task_id }
   │
   ▼                                            Admin SPA поллит (TanStack Query,
Celery worker (очередь default)                 refetchInterval ~1.5с)
   │  читает Google Sheets (если нужно)              │
   │  пишет в Postgres                                ▼
   ▼                                       GET /api/admin/sync/status/<task_id>
Celery result backend (Redis, уже настроен)   → { state, result | null, error | null }
```

Историю запусков **не персистим** в БД (осознанно, для простоты первой версии) — результат
живёт только в Celery result backend (Redis) и виден, пока открыта страница/не истёк TTL
результата. Ушёл со страницы — результат этого запуска пропал, задача при этом уже
выполнилась и данные в БД записаны.

Dry-run идёт через тот же Celery-путь, что и боевой запуск — единственная разница: флаг
`dry_run=True` не даёт функции делать записи в БД. Один код-путь вместо двух.

## Бэкенд: `apps/sync`

```
apps/sync/
  sheets_client.py       # read_students_range(sheet, range), read_journal_range(sheet, range) —
                          # аналог services/sheets.js, только read-часть (write-функции
                          # appendToJournal/updateStudentCell/batchUpdateCounters сюда не нужны —
                          # их звал только старый Express teacher-report flow, backfill их не использует)
  backfills/
    teachers.py           groups.py            students.py
    lessons.py             payments.py          payroll.py
    rebuild_payroll.py     rebuild_counters.py
    run_all.py
  tasks.py                # 8 @shared_task, каждая возвращает тот же JSON-совместимый dict,
                           # что печатал Node-скрипт (entity/read/inserted/updated/skipped/...)
  views.py                # SyncRunView (POST), SyncStatusView (GET)
  urls.py                 # /api/admin/sync/<action>/run, /api/admin/sync/status/<task_id>
```

**Перенос SQL:** upsert-запросы (`INSERT ... ON CONFLICT ... WHERE distinct-from`) переносятся
как raw SQL через `django.db.connection.cursor()`, один в один с оригиналом — не переписываются
на ORM `bulk_create`. Причина: условие «обновлять, только если реально что-то изменилось»
(иначе pghistory создаёт пустые записи в журнале изменений при каждом перезапуске backfill)
в ORM пришлось бы эмулировать вручную, с риском тонких расхождений с уже проверенной на
реальных данных Node-логикой. Это узаконенное исключение того же рода, что уже есть в
`apps/students`/`apps/accounts` (см. `# ORM-EXCEPTION` в кодовой базе).

**Google Sheets на Python:** новые зависимости `google-api-python-client` + `google-auth` в
`journal_django/requirements.txt`. Тот же `service-account-key.json` (лежит в корне репо,
gitignored) и те же `.env`-переменные `STUDENTS_SPREADSHEET_ID`/`JOURNAL_SPREADSHEET_ID` —
конфигурация не меняется.

**RBAC:** оба эндпоинта — `IsSuperAdmin` (не `IsAdmin`) — массовая запись в
students/payments/payroll заслуживает самого высокого порога в проекте.

**Аудит:** каждый запуск (успешный или нет) пишет `log_event` в `apps.audit` — кто запустил,
какое действие, `dry_run` да/нет, итоговые цифры результата. Без ПДн в `meta`.

**Celery-очередь:** задачи идут в `default` (не `interactive`) — не конкурируют с OTP-письмами
входа за приоритет. `time_limit` с запасом (~10 минут для `run-all` на реальном объёме данных).

## API

```
POST /api/admin/sync/<action>/run
  body: { "dry_run": boolean }
  → 202 { "task_id": "uuid" }
  → 403 если не IsSuperAdmin
  → 404 если <action> не из списка выше

GET  /api/admin/sync/status/<task_id>
  → 200 { "state": "PENDING"|"STARTED"|"SUCCESS"|"FAILURE", "result": {...}|null, "error": "..."|null }
  → 404 если task_id не найден / результат истёк в Redis
```

`<action>` ∈ `{teachers, groups, students, lessons, payments, payroll, rebuild-payroll,
rebuild-counters, run-all}`.

## Фронтенд

Новая страница `journal_django/frontend/admin-src/src/pages/sync/SyncPage.tsx`, роут
`/admin/sync`, пункт в сайдбаре — по схеме недавнего добавления `/admin/calendar`.

Один хук `useSyncAction(action)` инкапсулирует триггер (`POST .../run`) и поллинг статуса
(`GET .../status/<task_id>` с `refetchInterval`, пока `state` не терминальный) —
переиспользуется всеми карточками.

Разметка: `run-all` — отдельная выделенная карточка сверху; остальные 8 действий — под
заголовками «Из Google Sheets» и «Пересчёт из БД (Sheets не трогают)». У каждой карточки —
чекбокс «только предпросмотр» (компонент `Checkbox` из `components/form/`, не нативный input)
и кнопка «Запустить». После запуска под карточкой появляется блок статуса: спиннер на
`PENDING`/`STARTED`, зелёная сводка результата на `SUCCESS`, красный текст ошибки на
`FAILURE`. Цвета/отступы — из `tokens.css`, никакой самодельной вёрстки инпутов.

## Обработка ошибок

- Задача падает (лист переименовали, направление/учитель не найдены по имени и т.п.) →
  Celery-задача не глотает исключение → `state=FAILURE`, текст ошибки виден в `GET .../status`.
- Частичные пропуски (`skipped`, `no_lesson`, `skipped_details`) — не ошибка, а часть штатного
  результата, как и в Node-версии; попадают в `result`, не в `error`.
- `IsSuperAdmin` → 403 остальным ролям.
- `task_id` не найден/просрочен → 404 с сообщением «результат устарел, запусти заново».

## Тестирование

- Юнит-тесты на чистые функции трансформации (`extract_teachers`, `extract_groups`,
  `extract_students_and_memberships`, `extract_lessons`, `extract_payroll`, `parse_lesson_date`,
  `parse_time_slots`, `parse_lesson_duration` и т.д.) — перенос логики один в один, тестируется
  без сети/БД.
- `sheets_client` мокается в тестах — реальный Google API не дёргаем.
- API-тесты на `SyncRunView`/`SyncStatusView`: 403 не-суперадмину, 404 на неизвестный action.
  `CELERY_TASK_ALWAYS_EAGER=True` в тестовом окружении (уже так для auth/dashboard задач) —
  `.delay()` в тестах выполняется синхронно, результат проверяется сразу.
- Ручная проверка (после локального тестирования пользователем): `--dry-run`-эквивалент
  каждого действия на дев-БД, сверка сводки с тем, что раньше выдавал Node-скрипт на тех же
  данных.

## Явные ограничения первой версии (сознательно, YAGNI)

- Нет персистентной истории запусков — только текущий запуск на экране.
- `backfill-payments.js --reset` и `db-truncate.js` — не в UI, только терминал.
- Не поддерживается отмена уже запущенной задачи из UI.
- Оркестратор `run-all` не включает `payments` (как и оригинальный `backfill-all.js`).

## План развёртывания

Всё делается и тестируется **локально**. На прод отдельным шагом по явной команде
пользователя после локального тестирования (сервер: `sudo -u kotokod git pull` + миграции,
если появятся + `pip install -r requirements.txt` под новые зависимости + рестарт
`journal-django`/`journal-celery-worker`, фронт — пересобрать `admin-dist` локально и
закоммитить).
