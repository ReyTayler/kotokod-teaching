# Phase 3b — Admin для операционных таблиц — Design

**Дата:** 2026-05-28
**Статус:** Design approved, готов к writing-plans
**Базовые spec'и:**
- [`2026-05-25-postgres-migration-v2-design.md`](./2026-05-25-postgres-migration-v2-design.md) — общая v2-миграция
- [`2026-05-27-phase3a-cutover-design.md`](./2026-05-27-phase3a-cutover-design.md) — Phase 3a (выполнена)

## Цель

Дать админу возможность чинить **операционные** таблицы (`lessons`, `lesson_attendance`, `payroll`) через UI вместо `psql`. Use-case: «препод отправил урок с ошибкой» / «нужно вставить пропущенный урок» / «у преподавателя ошибочная сумма за неделю».

## Состояние до Phase 3b

Phase 3a завершена: teacher SPA на PG, кеша нет, submitLesson атомарен. Admin SPA умеет CRUD по 6 справочным сущностям (students/groups/teachers/tokens/directions/group-memberships). Операционные таблицы (`lessons`/`lesson_attendance`/`payroll`) ни в админке, ни через `services/admin-repo.js` не доступны.

## Архитектура

### Backend

`server.js` получает 3 группы эндпоинтов, поверх расширения `services/admin-repo.js`.

#### `/api/admin/lessons`

| Метод | Путь | Тело / параметры | Что делает |
|-------|------|------------------|------------|
| GET   | `/api/admin/lessons` | `?group_id&teacher_id&date_from&date_to` | Список с опциональными фильтрами. ORDER BY lesson_date DESC, lesson_number DESC. |
| GET   | `/api/admin/lessons/:id` | — | Один урок + attendance + payroll одним JSON'ом для detail-страницы |
| POST  | `/api/admin/lessons` | `{lesson_date, group_id, teacher_id, original_teacher_id?, lesson_number, lesson_type, record_url?, attendance:[{student_id,present}], payroll:{total_students,present_count,payment,penalty}}` | Атомарное создание (lesson + attendance + payroll) в одной `db.tx()`. `submitted_by_token` ставится `"admin-imported"`. |
| PATCH | `/api/admin/lessons/:id` | `{lesson_date?, teacher_id?, lesson_number?, lesson_type?, record_url?, original_teacher_id?}` | Правка полей урока (без attendance/payroll). |
| DELETE | `/api/admin/lessons/:id` | — | В `tx()`: `DELETE FROM payroll WHERE lesson_id` → `DELETE FROM lessons WHERE id` (CASCADE снесёт attendance). |

GET-ответ для detail (`/lessons/:id`):

```json
{
  "id": 123,
  "lesson_date": "2025-04-15",
  "lesson_number": "5.0",
  "lesson_type": "regular",
  "record_url": null,
  "submitted_by_token": "...",
  "submitted_at": "2025-04-15T15:30:00Z",
  "lesson_duration_minutes": 90,
  "teacher_id": 7,
  "teacher_name": "Иванов",
  "original_teacher_id": null,
  "original_teacher_name": null,
  "group_id": 42,
  "group_name": "Python И11",
  "attendance": [
    { "student_id": 100, "student_name": "Петров", "present": true }
  ],
  "payroll": {
    "id": 555,
    "total_students": 1,
    "present_count": 1,
    "payment": "500.00",
    "penalty": "0.00"
  }
}
```

#### `/api/admin/lesson-attendance`

| Метод | Путь | Тело | Что делает |
|-------|------|------|-----------|
| PATCH | `/api/admin/lesson-attendance/:lessonId/:studentId` | `{present:bool}` | Точечно меняет галочку. Save-on-toggle UX. |

PK таблицы `lesson_attendance` композитный `(lesson_id, student_id)`. Поэтому путь — двухсегментный.

#### `/api/admin/payroll`

| Метод | Путь | Параметры / Тело | Что делает |
|-------|------|------------------|------------|
| GET   | `/api/admin/payroll` | `?teacher_id&date_from&date_to` | Список payroll-строк JOIN с lessons+groups (для отображения preподавателя/группы/даты). |
| GET   | `/api/admin/payroll/summary` | `?teacher_id&date_from&date_to` | Агрегат: `[{teacher_id, teacher_name, lessons_count, sum_payment, sum_penalty}]` |
| PATCH | `/api/admin/payroll/:id` | `{total_students?, present_count?, payment?, penalty?}` | Правка существующей payroll-строки. |

DELETE payroll отдельно **не нужен**: payroll живёт строго один к одному с lesson; чтобы удалить — удаляешь lesson через `DELETE /api/admin/lessons/:id`.

### Frontend

`public/admin-app.js` + `public/admin.html`:

- **Sidebar** получает 2 новых пункта между «Направления» и «Архив»:
  - «Уроки» (svg-иконка book/calendar)
  - «Зарплата» (svg-иконка money/coin)
- **`SECTIONS` массив** расширяется на 2 элемента. `state.cache` получает поля `lessons: null, payroll: null, payrollSummary: null`.
- **`SECTION_RENDERERS.lessons`** — таблица с фильтрами в шапке (по группе/преподу/периоду — datapickers сверху таблицы, не per-column, потому что period это range). Колонки: ID, Дата, Группа, Преподаватель, Урок #, Тип, Всего/Было, Оплата, Штраф, Действие. Клик по строке → detail.
- **`SECTION_RENDERERS.payroll`** — переключатель view вверху: «Список» / «Сводка».
  - Список view: таблица payroll JOIN lesson+group: Дата, Преподаватель, Группа, Урок #, Всего/Было, Оплата, Штраф. Клик → lesson detail.
  - Сводка view: таблица агрегата: Преподаватель, Уроков, Сумма оплат, Сумма штрафов. Без клика.
  - Фильтры (общие для обоих view): период (date_from / date_to), preподаватель (select из активных).
- **`DETAIL_RENDERERS.lessons`** — новая. Содержит:
  - Heading: дата · группа · преподаватель · урок #
  - Action-bar: «← Назад», «✎ Редактировать» (модалка для базовых полей), «🗑 Удалить» (двухшаговая)
  - Карточка «Данные урока» (свернутая): id, lesson_date, lesson_number, lesson_type, record_url, original_teacher (если substitution), submitted_by_token, submitted_at, duration_minutes
  - Секция «Посещаемость» — таблица учеников: ФИО · toggle «был/не был». PATCH on toggle. При успехе тост.
  - Секция «Зарплата» — inline-edit-карточка: 4 поля (total_students, present_count, payment, penalty) с save-on-blur. Внизу — кнопка «Пересчитать» (auto-fill через services/calculator.js — но на бэке через отдельный mini-endpoint или клиентским кодом, если duplicate calculator — лучше backend).
- **`openLessonModal(row|null)`** — модалка create/edit:
  - **Create-form (полная)**: дата (date), группа (select, preset если открыто из Group detail), preподаватель (default = group.teacher_id, можно override), тип (select regular/substitution/reschedule), original_teacher (показывается если тип = substitution; select из всех активных teachers), record_url (text), lesson_number (number, auto-suggest = `max(lesson_number) for group + 1 or +0.5`), список учеников группы (auto-populate из memberships) — каждая строка с toggle «был/не был», поля payment/penalty (auto-calc через POST `/api/admin/lessons/calculate-payment` или calc.js на клиенте; редактируемое).
  - **Edit-form (сокращённая)**: те же поля кроме attendance/payroll/students (они правятся на detail-page). Только: дата, lesson_number, тип, record_url, teacher_id, original_teacher_id.
- **Group detail** — добавляется секция «Уроки группы» под существующими секциями. Компактная таблица (date desc): Дата · Препод · Урок # · Тип · payment. Снизу — кнопка «+ Новый урок» → `openLessonModal(null)` с preset'нутой группой.
- **Calculator на фронте** — переносим логику `services/calculator.js` (`calculatePayment(total, present, isHalf)`) в `admin-app.js` как функцию. Дублирование (~10 строк), но избегаем round-trip к серверу при изменении total/present в форме. Penalty считается по дате (МСК) — для admin'а penalty неважен (обычно 0 для исторических уроков), default 0, editable.

### Изменения в существующих файлах

| Файл | Что меняется |
|------|--------------|
| `services/admin-repo.js` | +9 функций: `listLessons`, `getLessonFull` (с attendance+payroll), `createLessonFull` (tx), `updateLesson`, `deleteLessonFull` (tx), `updateAttendanceCell`, `listPayroll`, `payrollSummary`, `updatePayroll` |
| `server.js` | +10 admin-эндпоинтов (см. таблицу выше) |
| `public/admin-app.js` | +2 SECTION_RENDERERS, +1 DETAIL_RENDERERS, +1 openLessonModal, +1 секция в Group detail, +calculator helper |
| `public/admin.html` | +sidebar icons + CSS для filter date-pickers (если ещё не было), CSS для inline-edit payroll |
| `services/admin-repo.test.js` | smoke-тесты на новые функции |
| `docs/admin-smoke-tests.md` | новый раздел «Уроки + Зарплата» |

### Тесты

- `services/admin-repo.test.js` расширяется smoke-тестами:
  - Lessons: create-full → get-full (verify attendance + payroll присутствуют) → update lesson field → delete-full (verify attendance/payroll тоже ушли)
  - Attendance: updateAttendanceCell → re-fetch → assert present
  - Payroll: list with filters → summary aggregation
- Существующие 73 теста — остаются зелёными.
- Manual smoke — добавляется раздел в `docs/admin-smoke-tests.md`.

### Что НЕ входит

- Audit log (история изменений)
- Bulk операции (массовое удаление, импорт CSV)
- Export данных (Excel/CSV/PDF)
- Графики/визуализация зарплат
- Уведомления преподавателю об изменении его данных

## Acceptance

- 10 новых admin-эндпоинтов работают (curl-чеклист)
- Sidebar показывает «Уроки» и «Зарплата»; обе секции рендерят таблицы с фильтрами
- Lesson detail-страница: данные урока + attendance (toggle) + payroll (inline-edit) — всё работает
- Lesson create-модалка: полная форма (поля + ученики + payment) → submit → урок появляется в списке + правильно записан в PG
- Lesson edit: правка полей сохраняется
- Lesson delete: lesson + attendance + payroll все удаляются атомарно
- Group detail: «Уроки группы» секция показывает уроки группы + кнопка «+ Новый урок»
- Payroll: list view + summary view работают, фильтры применяются
- `npm test` — 73 + новые smoke = ≥80 pass

## Известные риски

| Риск | Митигация |
|------|-----------|
| Calculator дублируется (бэк services/calculator.js + клиент admin-app.js) | Маленькая чистая функция, ~10 строк. Если разойдётся — найдём в smoke. |
| Удаление урока ломает зарплату преподавателя за прошедший период | Двухшаговая кнопка «Удалить» с явным confirm. Документировать в admin-smoke. |
| Несколько payroll-строк на один lesson (нарушение UNIQUE) | PG schema гарантирует UNIQUE (`lesson_id` в payroll). Бэк PATCH/INSERT всегда работает с единственной строкой. |
| Дата в create-форме — какой год по умолчанию? | По умолчанию — сегодня (МСК), редактируется. |
| Lesson_number конфликт (другой урок с тем же `(date,group,number,token)`) | UNIQUE constraint в PG → 409 на POST → тост «Урок с такими параметрами уже есть». Frontend суммирует max+step как подсказку. |

## Что после Phase 3b

- Phase 5 — финальная очистка (удаление sheets.js, миграция 006 drop колонок, очистка .env)
- Опционально Phase 4.4 — мелкие UX-фиксы по dogfood'у
