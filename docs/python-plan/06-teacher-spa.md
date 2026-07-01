# 06 — Кабинет учителя (`apps/teacher_spa`)

**Агент:** `voltagent-lang:django-developer` (+ `code-reviewer`, `test-automator`).
**Источник (Node):** `services/teacher-repo.js`, `services/calculator.js`, `routes/teacher.js`.
**Зависит от:** lessons, memberships, groups, teachers. Роль — **`teacher`**.

## Сначала: `calculator` (утилита в core или teacher_spa)

Порт `services/calculator.js`:
- Ставки: `halfLesson=250` (за присутствующего), `smallGroup=500` (1-2 ученика, все пришли),
  `smallPartial=300` (1-2, часть), `perStudent=200` (3+, за присутствующего).
- `calculatePayment(total, present, isHalf)`: present=0 → 0; isHalf → 250×present; total≤2 →
  (present==total ? 500 : 300); total>2 → 200×present.
- `calculatePenalty(lessonDate, submitDate)`: тот же день → 0, иначе 40 ₽.
- МСК-даты: `getWeekStartMsk` (понедельник), `mskMonthRange` — уже есть в `apps/core/utils/dates.py`, переиспользовать.
- Парсинг расписания из названия группы: regex `(пн|вт|ср|чт|пт|сб|вс)\s+HH:MM`; half-lesson по «45 минут» в названии.

## Эндпоинты

| Метод | Путь | Поведение |
|-------|------|-----------|
| POST | `/api/getData` | Данные учителя: teacher→group→student (через `readAllStudents`). |
| POST | `/api/getAllData` | Полный дамп для замен. |
| POST | `/api/submitLesson` | **Атомарная транзакция**: lesson + attendance + payroll + инкремент счётчиков; штраф за позднюю подачу. Валидация тела (порт `submitLessonSchema`). |
| GET | `/api/report` | Статусы недели: done / pending / overdue (сравнение расписания с заполненными уроками). |
| GET | `/api/schedule` | Полное расписание всех групп + группы без времени. |
| GET/POST | `/api/report/refresh`, `/api/schedule/refresh`, `/api/refreshData` | Legacy no-op (вернуть тот же ответ / `{success:true}`). |

## Критичное

- `submitLesson` — всё-или-ничего в `@transaction.atomic` (lesson + attendance + payroll + `lessons_done` на дельту шага).
- half-lesson влияет и на оплату, и на шаг счётчика.
- Структура ответа `getData`/`readAllStudents` должна совпадать с Express **в точности** (фронт vanilla JS завязан на поля).
- Парсинг времени/дней недели — сверить regex с `services/teacher-repo.js` / `scripts/lib/parse-time.js`.

## Verification

- e2e-diff с Express по всем 8 эндпоинтам (тело/HTML идентичны).
- Тест атомарности submitLesson: пустая группа, отсутствующий токен, ошибка на полпути → rollback.
- Тест расчётов оплаты/штрафа на матрице (half/small/partial/perStudent, своевременно/поздно).
