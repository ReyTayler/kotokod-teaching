# Доп.уроки для отдельных учеников групп

Дата: 2026-07-15

## Проблема

Ученик группового формата отсутствовал на конкретном плановом уроке
(`scheduling.PlannedLesson`, уже проведённом — есть `fact_lesson`). Менеджер/
админ/суперадмин назначает такому ученику (или сразу нескольким, пропустившим
**один и тот же** урок) отдельный доп.урок вне обычного расписания группы —
компенсацию пропуска. Проводит его либо тот же, либо другой преподаватель
(доп.урок не привязан к расписанию его группы).

Сейчас в системе нет способа:
- запланировать разовое занятие для явно выбранного подмножества учеников
  (и `PlannedLesson.add_extra`, и оба админских модала создания урока всегда
  берут полный ростер группы — см. разведку перед этим документом);
- начислить преподавателю доп.урока зарплату по отдельной строгой ставке
  (200 ₽/ученика), не совпадающей ни с одной веткой существующего
  `payroll/calculator.py::calculate_payment`;
- зафиксировать, что пропуск компенсирован — то есть задним числом отметить
  присутствие на исходном уроке, не трогая зарплату преподавателя, который
  вёл группу изначально;
- отменить ещё не проведённый доп.урок.

Вне охвата: изменение `add_extra` (групповое доп.занятие всей группой —
существующий, отдельный механизм в `scheduling`, не путать с этой фичей,
несмотря на похожее название); ручной выбор произвольных, не привязанных к
единому пропущенному уроку студентов в одном доп.уроке (см. решение ниже —
один доп.урок = один пропущенный урок).

## Архитектура

Новое приложение `apps/extra_lessons/`. Модель-«оболочка» по аналогии с
`PlannedLesson` (план → факт после проведения):

```python
class ExtraLessonAssignment(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.PROTECT)
    missed_lesson = models.ForeignKey(
        "lessons.Lesson", on_delete=models.PROTECT,
        related_name="extra_lesson_assignments",
    )
    students = models.ManyToManyField(
        "students.Student", through="ExtraLessonParticipant",
    )
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField()
    duration_minutes = models.PositiveSmallIntegerField()  # 30/45/60/90, CHECK
    status = models.CharField(
        choices=[("scheduled", ...), ("done", ...), ("cancelled", ...)],
        default="scheduled",
    )
    fact_lesson = models.OneToOneField(
        "lessons.Lesson", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="extra_lesson_assignment",
    )
    created_at = models.DateTimeField(auto_now_add=True)

class ExtraLessonParticipant(models.Model):
    assignment = models.ForeignKey(ExtraLessonAssignment, on_delete=models.CASCADE)
    student = models.ForeignKey("students.Student", on_delete=models.PROTECT)
    class Meta:
        constraints = [UniqueConstraint(fields=["assignment", "student"], ...)]
```

Группа доп.урока не хранится отдельно — она всегда `missed_lesson.group`
(все участники объединены вокруг одного пропущенного урока, поэтому группа
однозначна).

`lessons.Lesson.lesson_type` получает новое значение `'extra'` (миграция:
расширить CHECK/choices). Факт проведения доп.урока — обычная строка
`Lesson(lesson_type='extra', group=missed_lesson.group, teacher=...)`, что
переиспользует существующие `LessonAttendance`/`Payroll`/changelog-механизмы
вместо изобретения параллельных таблиц.

И `ExtraLessonAssignment`, и `ExtraLessonParticipant` получают
`@pghistory.track(InsertEvent(), UpdateEvent(), DeleteEvent())`, запись в
`apps/changelog/registry.py` (иначе упадёт
`test_registry_covers_all_tracked_models`) и правила меток мутирующих URL в
`apps/changelog/labels.py`.

### Жизненный цикл

1. **`scheduled`** — назначено, не проведено. Видно в календаре преподавателя
   отдельной карточкой на `scheduled_date`/`scheduled_time`.
2. **`scheduled → done`** (проведение) — `apps/extra_lessons/services.py::record_extra_lesson(...)`:
   атомарно создаёт `Lesson`+`LessonAttendance`(участники доп.урока)+`Payroll`,
   проставляет `fact_lesson`, `status='done'`, и — для присутствовавших —
   ретроактивно правит посещаемость исходного урока (см. «Бизнес-правила»).
3. **`scheduled → cancelled`** — админ/менеджер отменяет ещё не проведённый
   доп.урок. Только смена `status`; фактов/зарплаты не существовало —
   отменять, кроме самой записи, нечего.
4. **`done` → удаление** — откат: реверс отметки посещаемости+счётчика на
   исходном уроке, удаление `Payroll`+`Lesson`-факта, `fact_lesson=NULL`,
   `status` возвращается в `'scheduled'` (см. «Бизнес-правила»).

Переход `cancelled → *` не предусмотрен (пересоздаётся новое назначение).

## Бизнес-правила и расчёты

**Зарплата за доп.урок** — не переиспользует `PAY_RATES`
(`payroll/calculator.py`), там ставки зависят от размера группы/типа обычного
урока. Для `lesson_type='extra'` — отдельная строго фиксированная формула:

```python
def calculate_extra_lesson_payment(present_count: int) -> int:
    return 200 * present_count
```

Длительность (30/45/60/90) влияет только на отображение в календаре
(протяжённость карточки), не на ставку — независимо от значения, оплата
всегда `200 × присутствовавших`.

**Штраф за просрочку заполнения** — та же формула, что и для обычных уроков:
`calculate_penalty(lesson_date=scheduled_date, submit_date, count_students)`
→ `40 × count_students`, если `submit_date != scheduled_date`. Переиспользуется
как есть, без изменений.

**Ретроактивная отметка на исходном уроке** — ключевой эффект. При проведении
доп.урока для каждого студента, присутствовавшего на НЁМ (не путать со
списком назначенных — кто-то из назначенных мог не прийти):

- `LessonAttendance.present` на `missed_lesson` переставляется в `True`
  (было `False` — иначе студент не считался бы кандидатом, см. валидацию)
- `GroupMembership.lessons_done` увеличивается на шаг **исходного** урока
  (по его `lesson_duration_minutes`/half-lesson-правилу, НЕ по длительности
  доп.урока — это два независимых параметра)
- `Payroll` исходного урока **не пересчитывается**. `update_attendance_cell`
  (используется для обычной ручной правки посещаемости) в этом случае не
  подходит — она как раз пересчитывает `Payroll`. Нужна отдельная функция
  (условно `apps/lessons/repository.py::mark_makeup_attendance`), которая
  трогает только `LessonAttendance`+`lessons_done`, но не зарплату
  преподавателя, который вёл исходный урок — иначе ему задним числом
  начислялась бы оплата за ученика, которого он не учил.

**Валидация при создании назначения:**
- `missed_lesson.extra_lesson_assignments` — `missed_lesson` обязан иметь
  `fact_lesson` (т.е. проведён; отдельно на уровне `Lesson` это и есть сам
  факт — просто уточнение, что нельзя ссылаться на ещё не проведённый
  `PlannedLesson`)
- кандидаты по умолчанию — участники группы с `present=False` на
  `missed_lesson`; форма разрешает добавить и других студентов вручную
  (перевод между группами и т.п.), без доп.проверки на уровне API — доверяем
  выбору менеджера/админа
- нельзя создать второе активное (`scheduled`/`done`) назначение для той же
  пары `(missed_lesson, student)` — проверка в сервисе перед созданием
  (избегаем задвоенной компенсации одного пропуска)

**Откат при удалении проведённого доп.урока** (симметрично
`delete_lesson_full`+`unlink_fact` из `docs/superpowers/specs/2026-07-14-unify-lesson-recording-design.md`):
- для студентов, присутствовавших на доп.уроке — `LessonAttendance.present`
  на `missed_lesson` возвращается в `False`, `lessons_done` уменьшается на
  тот же шаг исходного урока (`GREATEST(lessons_done - step, 0)`, как и
  обычный откат)
- удаляется `Payroll` доп.урока, затем сам `Lesson`-факт (каскадом —
  `LessonAttendance` доп.урока)
- `ExtraLessonAssignment.fact_lesson=NULL`, `status='scheduled'`
- триггерится ресинк стадии «Продлений» для затронутых студентов (как и в
  обычном пути) — присутствие на исходном уроке изменилось

## API и права доступа

Admin/manager (`permission_classes = [IsManagerOrAdmin]`):
- `POST /api/admin/extra-lessons` — создать назначение
  (`missed_lesson_id`, `teacher_id`, `student_ids[]`, `scheduled_date`,
  `scheduled_time`, `duration_minutes`)
- `GET /api/admin/extra-lessons` — список с пагинацией (фильтры: статус,
  учитель, дата, группа исходного урока) — обзорная страница
- `POST /api/admin/extra-lessons/{id}/cancel` — отменить (только
  `status='scheduled'`, иначе 409)
- `DELETE /api/admin/extra-lessons/{id}` — удалить проведённый, с откатом
  (только `status='done'`, иначе 409)

Teacher (`permission_classes = [IsTeacher]`, только своё назначение):
- `GET /api/calendar` — расширяется: помимо обычных occurrence отдаёт
  `ExtraLessonAssignment` преподавателя как карточки с `kind='extra'`
- `POST /api/teacher/extra-lessons/{id}/record` — фиксация проведения с
  посещаемостью участников (`[{student_id, present}]`); 403, если
  назначение не принадлежит текущему преподавателю; 409, если уже
  `done`/`cancelled`

Все мутирующие URL выше — новые правила в `apps/changelog/labels.py`.

## UI

**Admin SPA:**
- Точка входа — вкладка «Уроки» группы (`LessonGrid`): на строке уже
  проведённого урока — действие «Назначить доп.урок», открывающее форму с
  предзаполненным списком отсутствовавших (чекбоксы, можно снять/добавить),
  выбором учителя, даты/времени/длительности
- Новая страница «Доп.уроки» (аналог `LessonsListPage`) — обзор всех
  назначений с фильтрами и действием «Отменить» для `scheduled`

**Teacher SPA (календарь):**
- Доп.урок — отдельная карточка на своей дате/времени в
  `WeekGrid`/`MonthGrid`/`DayList`, залитая фиксированным насыщенным красным
  (не через `resolveDirectionColor` — отдельная константа), поверх — те же
  CSS-классы статуса (`done`/`cancelled`), что и у обычных occurrence
- Клик — форма фиксации (аналог «Отметить урок»), посещаемость только по
  списку назначенных участников

## Тестирование

- `record_extra_lesson`: создание Lesson+Attendance+Payroll, ретроактивная
  отметка исходного урока, увеличение `lessons_done` на верный шаг
  (проверить отдельно для half-lesson исходного урока)
- Штраф: просрочка/без просрочки
- Отмена `scheduled` → 200; повторная отмена/отмена `done` → 409
- Удаление `done` → полный откат (attendance, lessons_done, Payroll, статус
  `ExtraLessonAssignment` возвращается в `scheduled`)
- Валидация: нельзя создать назначение на непроведённый урок; нельзя
  задвоить `(missed_lesson, student)`
- `test_registry_covers_all_tracked_models` проходит с новыми моделями
