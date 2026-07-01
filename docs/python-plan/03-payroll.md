# 03 — Расчётный лист (`apps/payroll`)

**Агенты:** `voltagent-lang:sql-pro` (raw SQL) + `voltagent-lang:django-developer`, `code-reviewer` после.
**Источник (Node):** `services/repo/payroll.js`, `routes/admin/payroll.js`.
**Зависит от:** lessons, teachers.

## Модель (managed=False)

`Payroll` → таблица `payroll`: id, lesson_id (UNIQUE FK), teacher_id, total_students, present_count,
payment (`numeric(10,2)`), penalty (`numeric(10,2)`).

## Эндпоинты (`/api/admin/payroll`, роли manager/admin)

| Метод | Путь | Поведение |
|-------|------|-----------|
| GET | `/` | Список, пагинация, сорт `lesson_date DESC`. JOIN lessons/teachers для контекста. |
| GET | `/summary` | SUM(payment), SUM(penalty) по учителю. Фильтры date_from/date_to. |
| PATCH | `/:id` | Частичное обновление: total_students, present_count, payment, penalty. |

## Критичное

- payment/penalty — `numeric` → строка с масштабом (`'500.00'`), не float.
- SQL и агрегаты — дословно из `services/repo/payroll.js`; raw SQL через cursor.
- Сорт по `lesson_date` идёт через JOIN на lessons — sort whitelist обязателен.

## Verification

- e2e-diff с Express: список (с пагинацией/сортом), `/summary` (по диапазонам дат), PATCH.
- `assert_num_queries` на списке.
