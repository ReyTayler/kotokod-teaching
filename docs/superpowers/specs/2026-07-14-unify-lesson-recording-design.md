# Единое ядро записи урока (teacher SPA + admin SPA)

Дата: 2026-07-14

## Проблема (аудит)

Полный цикл «записать факт урока» — Lesson + LessonAttendance + счётчик
`group_memberships.lessons_done` + Payroll + связка с плановым занятием
(`planned_lessons.fact_lesson_id`/`status`) + синхронизация стадии «Продлений» —
сегодня существует ТОЛЬКО в `apps/teacher_spa/services.py::submit_lesson`.
Админский путь (`apps/lessons` — раздел «Уроки» в группе) — независимая, более
старая реализация с тем же набором операций, но неполная:

- `create_lesson_full` (`apps/lessons/repository.py:186`) не вызывает `link_facts`
  → созданный урок никогда не привязывается к плановому занятию, статус в
  расписании не меняется.
- `update_attendance_cell` (`:322`) правит `LessonAttendance`+счётчик, но не
  трогает `Payroll` вообще → дозапись/снятие ученика не меняет зарплату.
- `delete_lesson_full` (`:286`) откатывает счётчики и удаляет Payroll, но
  `planned_lessons.status` остаётся `'done'` (FK `fact_lesson` — `SET_NULL`,
  зануляет только `fact_lesson_id`) → зависшая «проведённая» плановая строка
  без факта.
- `_sync_renewal_stage` продублирована слово-в-слово в обоих приложениях
  (`teacher_spa/services.py:27-29`, `lessons/repository.py:33-36`).
- `calculate_payment`/`calculate_penalty` живут в `teacher_spa/calculator.py`,
  хотя нужны и админке; админка вместо переиспользования продублировала расчёт
  на фронте (`admin-src/.../lib/pricing.ts::calcPayment`) и шлёt готовые числа
  на бэкенд, который принимает их без проверки (`payroll` — клиентский вход).

Вне охвата (сознательно не трогаем): легаси Node-скрипты и их Django-порты
backfill (`apps/sync/backfills/*`) — одноразовые миграционные инструменты, не
пользовательский путь; `apps/groups/importers/direction_history.py` — архивный
импортёр старых курсов без Payroll по своей природе.

## Архитектура

Новая точка правды: **`apps/lessons/services.py::record_lesson(...)`**
(Lesson/LessonAttendance — модели этого приложения, естественный владелец).
Атомарно (`transaction.atomic`) выполняет:

1. `Lesson.objects.create(...)`
2. Проверка баланса присутствующих учеников (см. ниже) — **до** любых записей,
   как остальные ранние бизнес-ошибки.
3. `apps.scheduling.repository.link_facts(group_id)`
4. Инкремент `group_memberships.lessons_done` для присутствующих
   (по `(group_id, student_id)`, без отдельного резолва `membership_id` —
   упрощение относительно текущего `teacher_spa`, который резолвит через
   `membership_id`; итог тот же).
5. `LessonAttendance.objects.bulk_create(..., ignore_conflicts=True)`
6. `Payroll.objects.create(...)` — **всегда**, сервер сам считает
   `payment`/`penalty` (см. «Payroll» ниже).
7. `transaction.on_commit(...)` → `apps.renewals.engine.sync_lesson_stage_safe`
   напрямую (без промежуточной обёртки — она была чистым дублированием).

**Сигнатура:**

```python
def record_lesson(*,
    lesson_date: str,
    teacher_id: int,
    group_id: int,
    original_teacher_id: int | None,
    lesson_number: float,
    lesson_duration_minutes: int,
    lesson_type: str,
    record_url: str | None,
    submitted_by_token: str,
    submit_date: str,          # для calculate_penalty — см. «Payroll»
    attendance: list[dict],    # [{'student_id': int, 'present': bool}, ...]
) -> dict:
    """Возвращает {'lesson_id', 'payment', 'penalty', 'total_students', 'present_count'}.
    Бросает UnpaidAttendanceBlocked, если у кого-то из present-учеников remaining<=0."""
```

**Что остаётся у вызывающей стороны** (не входит в ядро — у каждого свои правила
резолва входных данных):

| Поле/логика | teacher_spa (`submit_lesson`) | apps/lessons (админка) |
|---|---|---|
| group_id/teacher_id | резолв по имени группы + сессии | приходит явно от клиента |
| lesson_number | `done + step` из `lessonsDone` | вводит админ вручную |
| lesson_type (regular/substitution/reschedule) | выводится из `planned_lessons` | приходит явно от клиента |
| Проверка «дата не в будущем» | да, до вызова ядра | нет (админ правит историю) |
| `submit_date` для штрафа | `format_msk_date()` (сегодня) | `= lesson_date` (см. ниже — штраф не срабатывает) |
| student name → student_id | резолвит `by_name` (группа знает имена) | клиент уже шлёт `student_id` напрямую |

### Проверка баланса — теперь в ядре, действует везде одинаково

Переезжает из `submit_lesson` в `record_lesson`. Использует ту же
`apps.finances.repository.balances_for_students` (батч, авторитетно). Нарушение
→ `apps.lessons.exceptions.UnpaidAttendanceBlocked` (новый файл, по образцу
`apps/groups/exceptions.py::ImmutableGroupFormat`) с готовым текстом
`У учеников без оплаченных уроков нельзя отметить посещение: <имена>.`

Точечно применяется и к `update_attendance_cell` (переключение одной ячейки) —
иначе создать нельзя, а дозаписать отметку можно, что и есть дыра. Реализуется
как отдельная маленькая функция в `apps/lessons/repository.py` (или
`apps/finances`), переиспользуемая обоими путями — не дублировать проверку.

**Как ядро сообщает об отказе разным вызывающим:**
- `apps/lessons/views.py` ловит `UnpaidAttendanceBlocked` → `Response({'error': str(e)}, status=400)`
  (как `ImmutableGroupFormat` в `apps/groups/views.py:134-135`).
- `teacher_spa/services.py::submit_lesson` ловит и заворачивает в
  `{'success': False, 'error': str(e)}` — контракт teacher SPA не меняется.

### Payroll — сервер всегда считает сам

`calculate_payment`/`calculate_penalty` переезжают из
`apps/teacher_spa/calculator.py` в **`apps/payroll/calculator.py`** (единственное
место, оба приложения импортируют оттуда). `record_lesson` считает
`total_students`/`present_count` из переданного `attendance`, вызывает
`calculate_payment(total, present, is_half)` и
`calculate_penalty(lesson_date, submit_date, present)`, и **всегда** создаёт
Payroll — клиентский `payroll` в теле запроса `POST /api/admin/lessons`
**больше не принимается** (убрать `PayrollPartSerializer`/поле `payroll` из
`LessonCreateSerializer`).

**Штраф для админки:** не должен срабатывать никогда при создании через админку
(это подтверждено пользователем: штраф — дисциплина для учителя, админ не
должен случайно штрафоваться за своё же административное действие). Технически
— `apps/lessons/services.py::create_lesson_full` всегда передаёт
`submit_date=lesson_date` в `record_lesson` (даты совпадают →
`calculate_penalty` возвращает 0 по своей же логике «lesson_date == submit_date»).

Если админу нужно вручную скорректировать сумму — уже есть отдельный
`PATCH /api/admin/payroll/:id` (`apps/payroll/repository.py::update_payroll`),
не трогаем, не дублируем возможность override на создании.

## Попутные фиксы (тот же слой кода, обнаружены аудитом)

### `delete_lesson_full` — явный откат `planned_lessons`

Новая функция `apps/scheduling/repository.py::unlink_fact(lesson_id: int) -> None`:
```python
def unlink_fact(lesson_id: int) -> None:
    """Отвязать плановую строку от удаляемого факта: fact_lesson_id=NULL,
    status → 'pending' (read-side _planned_status сам пересчитает overdue/pending
    по дате при следующем чтении календаря)."""
    PlannedLesson.objects.filter(fact_lesson_id=lesson_id).update(
        fact_lesson_id=None, status=PENDING,
    )
```
Вызывается из `delete_lesson_full` внутри той же транзакции, до/вместо
удаления Lesson (порядок не критичен — CASCADE и так занулил бы FK, но `status`
без этого шага остался бы `'done'`).

### `update_attendance_cell` — пересчёт Payroll

После UPSERT ячейки и корректировки счётчика — пересчитать `total_students`
(= COUNT LessonAttendance по `lesson_id`), `present_count` (COUNT present=true),
`payment = calculate_payment(...)`. **`penalty` не трогаем** — она про
своевременность исходной записи урока, не должна меняться от последующей
правки посещаемости.

## Frontend (`admin-src/.../components/lessons/LessonEditor.tsx`)

- Убрать `calcPayment`/расчёт `payment`/`penalty` и поле `payroll` из тела
  запроса `create` (сервер считает сам) — расчёт нигде не отображался в UI,
  чистое упрощение, поведения не меняет.
- `lesson_duration_minutes: 90` — захардкожено; раз уже трогаем этот payload,
  заменить на реальную `group.lesson_duration_minutes` (иначе half-lesson
  группы в админке всегда считались бы как обычный урок — существующий,
  отдельный от текущей задачи баг, но тривиально фиксится тем же диффом).
- Обработка ошибки 400 (`UnpaidAttendanceBlocked`) — уже покрыта общим
  `useApiError`/`showError` хуком (используется у `handleSave`/`handleDelete»
  сейчас) — новых кейсов в компоненте писать не нужно, просто убедиться, что
  текст ошибки от `{'error': ...}` реально всплывает в тосте (проверить
  `useApiError` на этот путь).

## Очистка дублирования

- `apps/teacher_spa/repository.py::insert_lesson/insert_attendance/increment_counters/insert_payroll`
  становятся мёртвым кодом после переноса — удалить.
- `apps/teacher_spa/services.py::_sync_renewal_stage` и
  `apps/lessons/repository.py::_sync_renewal_stage` — удалить обе, вызов
  `apps.renewals.engine.sync_lesson_stage_safe` напрямую из `record_lesson`.
- `apps/teacher_spa/calculator.py` — `calculate_payment`/`calculate_penalty`
  удаляются (переехали в `apps/payroll/calculator.py`); `format_msk_date`
  остаётся в `teacher_spa/calculator.py` (используется только там, для проверки
  будущей даты — не часть общей формулы зарплаты).

## Уже сделанная, но незакоммиченная правка `calculate_penalty`

Пользователь уже поменял штраф с фиксированных 40₽ на `40 × count_students`
(некоммичено). Эта правка переезжает вместе с функцией в
`apps/payroll/calculator.py` как есть — заодно чинится тестовый файл
(`test_calculator.py`, 4 теста сейчас падают на старой 2-аргументной сигнатуре)
на новом месте.

## Тесты (высокоуровнево, детали — в плане реализации)

- `apps/payroll/tests/` — новый `test_calculator.py` (перенесённые+исправленные
  тесты `calculate_payment`/`calculate_penalty`).
- `apps/lessons/tests/` — `create_lesson_full` теперь линкует `planned_lessons`
  (тест по образцу `test_submit_lesson_links_fact_to_planned_lesson` из
  teacher_spa), `update_attendance_cell` пересчитывает payroll, баланс-блокировка
  работает на обоих путях (create + attendance toggle), `delete_lesson_full`
  корректно возвращает плановую строку в `pending`.
- `apps/teacher_spa/tests/` — существующие тесты `submit_lesson` должны остаться
  зелёными без изменения ожидаемого поведения (рефакторинг вызова, не логики) —
  кроме перемещённых `calculate_penalty`/`calculate_payment` импортов в тестах,
  если они там прямо импортируются.
- Полный прогон `apps/teacher_spa apps/lessons apps/payroll apps/scheduling apps/groups apps/finances`.

## Вне охвата

- Легаси Node-скрипты (`scripts/backfill-*.js`) и их Django-порты
  (`apps/sync/backfills/*`) — не переводим на новое ядро, это одноразовые
  инструменты миграции/пересчёта, не пользовательский путь.
- `apps/groups/importers/direction_history.py` — архивный импортёр, Payroll не
  создаёт по своей природе (нет расписания/оплаты для мигрированных курсов).
- `apps/changelog` revert для урока, созданного через новое ядро — начиная с
  этого фикса создание и линковка происходят в ОДНОЙ транзакции/pghistory-
  контексте, так что кросс-контекстный рассинхрон из аудита для НОВЫХ записей
  больше не воспроизводится; тестов на revert не добавляем (не просили,
  отдельная фича).
