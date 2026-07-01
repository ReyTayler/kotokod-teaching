# 01 — Уроки и посещаемость (`apps/lessons`)

**Агент:** `voltagent-lang:django-developer` (+ `code-reviewer` после).
**Источник (Node):** `services/repo/lessons.js`, `routes/admin/lessons.js`.
**Зависит от:** core, groups, teachers, students, memberships (готовы).

## Модели (managed=False)

- `Lesson` → таблица `lessons`: id, group_id, teacher_id, original_teacher_id (nullable), lesson_date
  (**CharField(10)** + DateStringField), lesson_number (`numeric(5,1)` — поддержка 0.5), lesson_duration_minutes,
  lesson_type ('regular'|'substitution'|'reschedule'), record_url, submitted_at (timestamptz), submitted_by_token.
- `LessonAttendance` → таблица `lesson_attendance`: PK `(lesson_id, student_id)`, present (bool). FK lesson → CASCADE.

## Эндпоинты (`/api/admin/lessons`, роли manager/admin)

| Метод | Путь | Поведение |
|-------|------|-----------|
| GET | `/` | Список, пагинация, сорт `lesson_date DESC, id DESC`. Фильтры: group_id, teacher_id, date_from, date_to. JOIN group/teacher/direction для имён. |
| GET | `/:id` | Полный урок: meta + attendance[] + payroll. |
| POST | `/` | `createLessonFull` — **транзакция** (`@transaction.atomic`): INSERT lesson + attendance (bulk) + payroll. |
| PATCH | `/:id` | Обновить meta (date, teacher, number, type, record_url). 200/404. |
| DELETE | `/:id` | Удалить (CASCADE attendance + payroll). 204/404. |
| PATCH | `/:lessonId/attendance/:studentId` | Toggle present для одной ячейки (UPSERT). |

## Критичное

- **half-lesson**: `lesson_duration_minutes == 45` → шаг 0.5 урока, иначе 1.
- При `createLessonFull` и toggle посещаемости — инкремент/декремент `group_memberships.lessons_done`
  на дельту шага внутри той же транзакции (см. `incrementCounters` в `services/teacher-repo.js`).
- `lesson_number` и `lessons_done` — `numeric`, рендерить как число с масштабом (0.5/1.0), не терять дробь.
- SQL копировать дословно из `services/repo/lessons.js` (фильтры, JOIN, пагинация).

## Verification

- e2e-diff с Express по списку (все фильтры), `/:id`, POST/PATCH/DELETE, toggle.
- DATE-инвариант на lesson_date.
- Тест атомарности: при ошибке payroll — lesson и attendance не остаются (rollback).
- `assert_num_queries` на списке (нет N+1 по group/teacher/direction).
