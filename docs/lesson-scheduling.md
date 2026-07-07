# Планирование занятий — материализованные плановые уроки

> Спека модели `PlannedLesson` и операций расписания. Источник правды по датам
> плановых занятий — таблица `planned_lessons` (materialize-on-write). Заменяет
> прежнюю вычисляемую модель (compute-on-read из слотов + `lesson_schedule_exceptions`).

## Зачем материализация

Онлайн-школе нужно недельное расписание группы/индива, развёрнутое от даты старта,
с операциями: разовый перенос даты, смена преподавателя (разово/навсегда), перенос
навсегда день/время (сдвиг хвоста), отмена (сдвиг хвоста +1 неделю, курс
продлевается), доп. занятие. Дата-двигающие операции и смена препода разведены.
Материализованные строки —
источник правды — лучше ложатся на roadmap платформы (видео-комнаты, напоминания,
тема на конкретный урок, FK план→факт) и на семантику отмены-со-сдвигом, которую
compute-on-read выражал плохо.

**Ключевое отличие семантики отмены от прежней:** отмена = **сдвиг всех
последующих непроведённых на +1 неделю**, урок **не** списывается с абонемента,
N уроков курса сохраняются (курс заканчивается на неделю позже). Прежний код
делал «отмена на месте, курс короче» — это неверно.

## Роли сущностей

| Сущность | Роль после перехода |
|----------|---------------------|
| `GroupScheduleSlot` (`group_schedule_slots`) | **recurrence-шаблон**. Версионируемый недельный слот (день Вс=0 + время + `effective_from/to`). Используется генератором при создании плана и при «переносе навсегда». НЕ источник правды по датам. |
| `PlannedLesson` (`planned_lessons`) | **источник правды** по датам/статусам/преподавателю конкретного занятия. |
| `LessonScheduleException` (`lesson_schedule_exceptions`) | **выводится из употребления**. Операции мутируют `planned_lessons` напрямую, аудит — через `log_event`. Удаляется на шаге 9 (боевых данных нет). |
| `occurrences.py` (`_walk`/`_step_for`/`_offset_from_monday`) | переиспользуется как **чистый генератор строк** (expand-on-write), а не compute-on-read. |

## Модель `PlannedLesson`

Таблица `planned_lessons`, `managed=True` поверх настоящей Django-миграции
(`apps/scheduling/migrations/0001_*`). App `scheduling` — логичное место (сейчас без моделей).

Конвенции проекта: half-lesson `lesson_number = seq * step` (45мин → step 0.5),
даты — чистый `DateField`/`TimeField` без TZ, «сейчас» по МСК (`msk_now()`).

| Поле | Тип | Заметки |
|------|-----|---------|
| `id` | AutoField PK | |
| `group` | FK → `groups.Group` | CASCADE, `db_column='group_id'`, `related_name='planned_lessons'` |
| `seq` | Integer, nullable | порядковый номер урока в курсе (1..N); `NULL` для `extra`/маркеров отмены |
| `lesson_number` | Decimal(5,1), nullable | `seq * step` (half-lesson); `NULL` для не-курсовых строк |
| `scheduled_date` | DateField | дата занятия |
| `scheduled_time` | TimeField | время начала |
| `teacher` | FK → `teachers.Teacher` | DO_NOTHING, nullable, `db_column='teacher_id'`. **Преподаватель конкретного занятия.** По умолчанию = учитель группы; операции переноса/смены могут его менять. **Источник правды для скоупа календаря.** |
| `status` | TextField | `pending / overdue / done / cancelled` (константы из `occurrences.py`). `moved` — **зарезервирован в CheckConstraint, но не используется** операциями (перенос показывается через `moved_from_date`) |
| `fact_lesson` | FK → `lessons.Lesson` | SET NULL, nullable, **unique**, `db_column='fact_lesson_id'` — связь план→факт |
| `moved_from_date` | DateField, nullable | отображение разового переноса (откуда); ставится только при реальной смене даты |
| `moved_to_date` | DateField, nullable | **зарезервировано, не используется** (не пишется и не отдаётся в API) |
| `note` | TextField, nullable | |
| `created_at` / `updated_at` | DateTimeField (timestamptz) | DB-default `now()` |

### Ограничения / индексы

- `UniqueConstraint(group, seq)` где `seq IS NOT NULL` — одна строка на позицию курса.
- `Index(group, scheduled_date)` — основной для календаря.
- `CheckConstraint status IN ('pending','overdue','done','cancelled','moved')`.
- `CheckConstraint`: у курсовых строк (`seq IS NOT NULL`) `lesson_number IS NOT NULL`;
  у не-курсовых (`seq IS NULL`) `lesson_number IS NULL`. (Оба заданы ⟺ оба NULL.)

## Операции (чистые функции над датами, TDD)

Файл `apps/scheduling/planner.py` — чистые функции (без ORM), тестируемые в изоляции;
`apps/scheduling/repository.py` — запись результата в БД в транзакции.

**Инвариант всех операций:** никогда не трогать строки `status='done'` (проведённые).
Операции затрагивают только будущие/непроведённые. `seq`/`lesson_number` (порядок
контента) стабильны — двигаются только даты (и опц. `teacher`).

### 1. Генерация плана `generate`

Вход: `start_date`, слоты (активные), `direction.total_lessons` (**обязателен**;
если NULL → группа «unscheduled», план не строим), `duration_minutes` (для step).
Разворачиваем N строк `seq 1..N` еженедельно на день/время слота (переиспользуем
`_walk`). Дефолт `teacher` = учитель группы. **Идемпотентно** — повторный вызов не
плодит дубли (guard по `UniqueConstraint(group, seq)`; не перезаписывает `done`).
Ручной эндпоинт `/plan/generate` и авто-генерация используют `create_only=True`
(не затирают ручные операции).

**Авто-генерация при первичной настройке (Механизм 1).** Когда у активной группы
ВПЕРВЫЕ появляются старт И слот И `total_lessons`, план генерируется автоматически —
`groups.services.{create_group,update_group,apply_schedule_change}` синхронно зовут
`scheduling.services.autogenerate_plan_on_setup(...)` ПОСЛЕ коммита repository
(`ATOMIC_REQUESTS=False` → выход из repository-atomic = commit; сигналы не годятся —
слоты создаются `bulk_create`, `post_save` не летит). Срабатывает **только первый
раз** (guard `plan_exists(active_only=True)`: непустой план / неактивная группа →
выход); идемпотентно; аудит `plan_auto_generate` (source/written/reason); гонка двух
триггеров глушится на `IntegrityError`; сбой авто-генерации не роняет создание группы.

Дата-двигающие операции (перенос) и смена преподавателя **разведены**: перенос не
переназначает препода «побочно», смена препода не двигает дату. Это устраняет
ложную метку «перенесён» при обычной смене учителя.

### 2. Разовый перенос `reschedule`

Обновить **одну** строку (по `id` планового занятия): `scheduled_date/time` и
**опц. `teacher`** (напр. подмена на этот перенос). `moved_from_date` = прежняя дата,
но **только если дата реально изменилась** (перенос на ту же дату — напр. правка
одного времени — метку «перенесён» не ставит). Остальные строки не трогаются;
`seq`/`lesson_number` сохраняются. `done` не переносим (ошибка → 409).

### 3. Смена преподавателя `change_teacher` / `change_teacher_permanent`

Отдельные операции — **не** двигают дату/время и **не** ставят `moved_from_date`.
- **Разово** (`POST /plan/<lid>/change-teacher`): меняет `teacher` одной строки.
  `done` → 409.
- **Навсегда** (`POST /plan/change-teacher-permanent`): проставляет `teacher` всем
  курсовым строкам `seq >= from_seq` в статусе `pending/overdue`. Слот/день не
  версионируются (день не меняется). Дефолт группы (`group.teacher_id`) для будущей
  генерации **не** трогается — при желании меняется отдельно.

Смена препода перекидывает занятия между календарями (скоуп по `planned_lesson.teacher_id`).

### 4. Перенос навсегда `permanent_change`

С позиции `seq=k` меняем **день/время** слота (преподаватель — через `change_teacher_*`):
1. Закрыть текущий активный слот (`effective_to = дата − 1`), открыть новый
   (`effective_from = дата`) с новым днём/временем — версионирование `GroupScheduleSlot`.
2. **Пересчитать** `scheduled_date/time` всех строк `seq >= k` со статусом
   `pending/overdue` на новый день недели, сохраняя недельную каденцию.

Доступно только для групп с **одним** открытым слотом (иначе 400). В UI новый день
недели предзаполняется **текущим** днём занятия (не понедельником) — правка только
времени не уводит занятия на другой день. Трогаем только `pending/overdue`; `done`
не тронут.

### 5. Отмена со сдвигом `cancel`

По `id`/`seq=k` (дата D = дата якорной строки): сдвигаем **только курсовые**
`pending/overdue` строки на +7 дней:
```
UPDATE planned_lessons
SET scheduled_date = scheduled_date + INTERVAL '7 days'
WHERE group_id = G AND scheduled_date >= D AND seq IS NOT NULL AND status IN ('pending','overdue')
```
(время/день недели сохраняются.) Вставляем маркер `status='cancelled', seq=NULL` на
дату D («отменён» в календаре). **Неподвижны:** маркеры отмены и доп. занятия
(`seq=NULL`) и проведённые (`done`) — повторная отмена не сдвигает прежние пины.
Абонемент **не** трогаем (balance = purchased − attended; отменённый не attended).
Курс продлевается на неделю. Отмена доступна только для активной курсовой строки
(не extra/cancelled/done → 400).

### 6. Доп. занятие `extra`

Вставить строку `seq=NULL, lesson_number=NULL` на заданную дату/время с преподавателем.
Вне курса, не влияет на `seq` курсовых строк. При отмене не сдвигается.

## Скоуп календаря по преподавателю

`GET /api/calendar` скоупит **по `planned_lesson.teacher_id`** (не по учителю группы).
Следствие смены преподавателя занятия (разово или навсегда): занятие автоматически
**появляется** у нового препода и **исчезает** у исходного. Дефолт `teacher` строки
= учитель группы; операции переопределяют пер-строчно. Связка с payroll/подменой
(`Lesson.original_teacher`) — на этапе факта, вне планового слоя, через `fact_lesson`.

## API

### Admin (RBAC `IsManagerOrAdmin`, мутации — `X-CSRFToken`, аудит `log_event`)

- `GET  /api/admin/groups/<pk>/plan` — список плановых занятий группы.
- `POST /api/admin/groups/<pk>/plan/generate` — сгенерировать план (идемпотентно).
- `POST /api/admin/groups/<pk>/plan/<lid>/reschedule` — разовый перенос даты (+опц. teacher).
- `POST /api/admin/groups/<pk>/plan/<lid>/change-teacher` — разовая смена преподавателя.
- `POST /api/admin/groups/<pk>/plan/change-teacher-permanent` — смена преподавателя хвоста (`from_seq`).
- `POST /api/admin/groups/<pk>/plan/permanent-change` — перенос навсегда день/время (с seq).
- `POST /api/admin/groups/<pk>/plan/<lid>/cancel` — отмена со сдвигом.
- `POST /api/admin/groups/<pk>/plan/extra` — доп. занятие.

`generate` идемпотентен и **create-only** над непустым планом (не затирает ручные
операции). Полный пересбор существующих групп — команда `backfill_planned_lessons`
(refined-логика, ниже).

### Teacher (RBAC `IsTeacher`)

- `GET /api/calendar?from&to` — читает `planned_lessons`, скоуп по `teacher_id`.

## Бэкфилл (пересборка из фактов — Механизм 2)

Management-команда `apps/scheduling/management/commands/backfill_planned_lessons.py`
для активных групп со стартом+`total_lessons`+слотами пересобирает план чистой
функцией `planner.generate_from_facts` (обёртка `repository.rebuild_from_facts`):

1. **ПРОШЛОЕ = факты.** i-й факт (сорт по `lesson_date,id`) → строка `seq i`,
   `status=done`, **`scheduled_date = fact.lesson_date`** (плановая дата =
   фактическая), номер по порядку (кумулятивный `step`), `teacher`/`fact_lesson_id`
   из факта. Связь план→факт ставится напрямую (без эвристики `link_facts`). Фактов
   больше `total` → все сохраняются как done, будущего нет.
2. **БУДУЩЕЕ.** Оставшиеся уроки (`total − проведено`, в единицах с учётом
   half-lesson) разворачиваются по **текущему открытому** слоту, начиная с
   ближайшего слот-дня **строго после даты последнего проведённого урока** (а не от
   «сегодня»): план продолжается непрерывно с места, где группа остановилась.
   Пример: последний (27-й) урок в СБ `04.07` → 28-й в СБ `11.07`, 29-й `18.07`, …
   Если фактов нет — будущее от `group_start_date`. Номера/`seq` продолжают прошлое.

Непроведённые будущие строки, чья дата уже прошла (группа отстаёт от графика),
читаются как **overdue** «надо заполнить» на уровне `_planned_status` — отдельного
«overdue-прошлого» не материализуем.

**⚠️ Разрушительно и re-runnable:** каждая пересборка = `reset_plan` + `bulk_create`,
разворачивает будущее заново → **перезаписывает ручные операции будущего**
(переносы/отмены/смену препода); команда об этом предупреждает. **Результат
today-независим:** даты зависят от ФАКТОВ, а не от даты прогона — повтор без новых
фактов даёт тот же план. Батч без N+1 (`active_groups`+`slots_by_group`+
`facts_by_group`). `--dry-run` — без записи; `--reset` устарел (reset встроен) →
no-op с предупреждением. Гонять на dev-БД (`journal`, не `journal_test`).

## Порядок вывода старого слоя

1–8. Ввести `planned_lessons`, planner, backfill, admin-API, переключить календарь,
фронт. 9. После подтверждения паритета (даты/статусы календаря совпадают со старым
compute-выводом на тех же данных) — удалить `LessonScheduleException`, compute-on-read
в `services.build_calendar`, `_apply_exceptions`/`_find`/`_attach_status` из `occurrences.py`
(генератор `_walk`/`_step_for`/`_offset_from_monday` остаётся).
