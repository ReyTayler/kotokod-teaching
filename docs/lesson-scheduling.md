# Планирование занятий — материализованные плановые уроки

> Спека модели `PlannedLesson` и операций расписания. Источник правды по датам
> плановых занятий — таблица `planned_lessons` (materialize-on-write). Заменяет
> прежнюю вычисляемую модель (compute-on-read из слотов + `lesson_schedule_exceptions`).

## Зачем материализация

Онлайн-школе нужно недельное расписание группы/индива, развёрнутое от даты старта,
с тремя операциями: разовый перенос, перенос навсегда (сдвиг хвоста), отмена
(сдвиг хвоста +1 неделю, курс продлевается). Материализованные строки —
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
| `status` | TextField | `pending / overdue / done / cancelled / moved` (константы из `occurrences.py`) |
| `fact_lesson` | FK → `lessons.Lesson` | SET NULL, nullable, **unique**, `db_column='fact_lesson_id'` — связь план→факт |
| `moved_from_date` | DateField, nullable | для отображения разового переноса (откуда) |
| `moved_to_date` | DateField, nullable | для отображения разового переноса (куда) — на строке-оригинале со `status='moved'` |
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

### 2. Разовый перенос `reschedule`

Обновить **одну** строку (по `id` планового занятия): `scheduled_date/time` и
**опц. `teacher`** (разовая смена препода на это занятие); проставить
`moved_from_date` = прежняя дата. Остальные строки не трогаются. `seq`/`lesson_number`
сохраняются. Если сменён `teacher` — занятие уходит из календаря исходного препода
и появляется у нового (скоуп по `teacher_id`). `done` не переносим (ошибка).

### 3. Перенос навсегда `permanent_change`

С позиции `seq=k` (или с даты D) меняем день/время слота **и/или преподавателя**:
1. Закрыть текущий активный слот (`effective_to = дата − 1`), открыть новый
   (`effective_from = дата`) с новым днём/временем — версионирование `GroupScheduleSlot`.
2. **Пересчитать** `scheduled_date/time` всех строк `seq >= k` со статусом
   `pending/overdue` на новый день недели, сохраняя недельную каденцию.
3. Если задан новый преподаватель — проставить `teacher` на этих строках и обновить
   дефолт для будущей генерации (учитель группы или дефолт слота — см. реализацию).

Проведённые (`done`) и уже вручную перенесённые ранее (`moved`) — по правилам
реализации; базово трогаем только `pending/overdue`.

### 4. Отмена со сдвигом `cancel`

На дату D (или по `id`/`seq=k`):
```
UPDATE planned_lessons
SET scheduled_date = scheduled_date + INTERVAL '7 days'
WHERE group_id = G AND scheduled_date >= D AND status <> 'done'
```
(время/день недели сохраняются — +7 дней это тот же день недели.) Опционально
вставить маркер-строку `status='cancelled', seq=NULL, lesson_number=NULL` на дату D
для отображения «отменён». Абонемент **не** трогаем (balance = purchased − attended;
отменённый не attended). Все N курсовых строк сохраняются → курс продлевается на
неделю. Поле `teacher` при отмене не участвует.

### 5. Доп. занятие `extra`

Вставить строку `seq=NULL, lesson_number=NULL` на заданную дату/время с preподавателем.
Вне курса, не влияет на `seq` курсовых строк.

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
- `POST /api/admin/groups/<pk>/plan/<lid>/reschedule` — разовый перенос (+опц. teacher).
- `POST /api/admin/groups/<pk>/plan/permanent-change` — перенос навсегда (с seq/даты).
- `POST /api/admin/groups/<pk>/plan/<lid>/cancel` — отмена со сдвигом.
- `POST /api/admin/groups/<pk>/plan/extra` — доп. занятие.

### Teacher (RBAC `IsTeacher`)

- `GET /api/calendar?from&to` — читает `planned_lessons`, скоуп по `teacher_id`.

## Бэкфилл

Management-команда `apps/scheduling/management/commands/backfill_planned_lessons.py`:
для активных групп с `group_start_date` и `direction.total_lessons` сгенерировать
`planned_lessons` из старта/слотов; прошлые строки слинковать с фактами
(`fact_lesson`, по `group_id` + дате) и проставить `status='done'`. **Идемпотентно**;
гонять на dev-БД (`journal`, не `journal_test`). См. `docs/backfill-runbook.md` для
паттерна runbook.

## Порядок вывода старого слоя

1–8. Ввести `planned_lessons`, planner, backfill, admin-API, переключить календарь,
фронт. 9. После подтверждения паритета (даты/статусы календаря совпадают со старым
compute-выводом на тех же данных) — удалить `LessonScheduleException`, compute-on-read
в `services.build_calendar`, `_apply_exceptions`/`_find`/`_attach_status` из `occurrences.py`
(генератор `_walk`/`_step_for`/`_offset_from_monday` остаётся).
