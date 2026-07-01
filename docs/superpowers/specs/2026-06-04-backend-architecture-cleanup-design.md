# Backend architecture cleanup — design

**Дата:** 2026-06-04
**Цель:** убрать два God-модуля (`services/admin-repo.js` 1361 строка; `services/db.js` — смешивает инфраструктуру и домен), чтобы каждый юнит имел одну ответственность, читался/тестировался изолированно, а роуты зависели только от нужного слайса. Чистое перемещение кода за стабильными интерфейсами — **без изменения поведения**.

## Объём (согласовано)
- ✅ Распил `admin-repo.js` → `services/repo/*`.
- ✅ Распил `db.js` → инфра + `teacher-repo.js`.
- ✅ Удаление мёртвого кода.
- ❌ Phase 5 (вынос Sheets) — вне объёма.
- ❌ git — занесён в `docs/BACKLOG.md`, позже.

## Целевая структура
```
services/
  db.js                # ИНФРА: pool, tx, shutdown, DATE type-parser (~30 строк)
  teacher-repo.js      # домен teacher SPA: readTokens/readAllStudents/readFilledLessons,
                       #   insertLesson/insertAttendance/insertPayroll/incrementCounters (+ fmt helpers)
  pagination.js        # без изменений (ядро)
  calculator.js, fifo.js  # без изменений (чистые)
  admin-repo.js        # BARREL: re-export services/repo/* (back-compat для тестов)
  repo/
    teachers.js  directions.js  discounts.js  tokens.js
    groups.js    students.js    memberships.js
    lessons.js   payroll.js     payments.js    dashboard.js  settings.js
  (repository.js  — УДАЛЁН; routes/teacher.js импортирует teacher-repo напрямую)
```

### Раскладка функций по `repo/*`
- **teachers**: list/get/create/update/softDelete
- **directions**: list/get/create/update/softDelete
- **discounts**: list/get/create/update/softDelete
- **tokens**: list/create/update/revoke + generateRandomToken
- **groups**: list/get/create/update/softDelete (+ GROUPS_PAGINATION, GROUP_SELECT_WITH_SLOTS)
- **students**: list/get/create/update/softDelete + studentStats (+ STUDENTS_PAGINATION)
- **memberships**: list/add/update/remove
- **lessons**: list/getLessonFull/createLessonFull/updateLesson/deleteLessonFull/updateAttendanceCell (+ LESSONS_PAGINATION)
- **payroll**: list/payrollSummary/updatePayroll (+ PAYROLL_PAGINATION)
- **payments**: createPayment/listPayments/getPayment/deletePayment/getStudentBalance/getDirectionPaymentsCount (+ private `_balanceForDirection`)
- **dashboard**: getDashboard/getMonthlyFinance (+ private `_fifoInputs`, `_round2`, `_addDay`)
- **settings**: getAdminSettings/upsertAdminSettings

**Инвариант изоляции:** ни один `repo/*` не импортирует другой `repo/*` (проверено: `getStudentBalance`/`deletePayment` вызывают только функции внутри `payments.js`; dashboard самодостаточен). Зависимости только на ядро: `db`, `pagination`, `calculator`, `fifo`, `crypto`.

## Роуты
Каждый `routes/admin/*.js` импортирует свой домен вместо barrel.
Исключение: `routes/admin/students.js` тянет `repo/students` + `repo/payments` (для `/:id/balance`). Прочие — ровно один модуль. Barrel остаётся только для back-compat тестов.

## db.js
- `db.js` → только `pool`, `tx`, `shutdown`, type-parser.
- `teacher-repo.js` → домен (читает `pool` из `db`).
- `repository.js` удалить; `routes/teacher.js` → `teacher-repo`.
- `db.test.js` разделить: инфра-тесты остаются, доменные → новый `teacher-repo.test.js`. Бэкфилл-скрипты используют только `pool`/`tx`/`shutdown` — не затронуты.

## Удаление мёртвого кода (ПОСЛЕДНИМ, после зелёных тестов)
`_backup-pre-r0/`, `_backup-pre-r1/`, `public/admin.html`, `public/admin-app.js`, `public/Index.html.backup-phase4-1`, `test_log.txt`, `test_output.txt`, 2 скриншота в корне.

## Порядок и проверка (git нет)
1. Распил admin-repo + barrel → `npm test` (97/97).
2. Роуты на слайсы → проверка резолва require + boot.
3. Распил db.js + teacher-repo + удаление repository.js + раздел тестов → `npm test` (97/97).
4. Удаление мёртвого кода → финальный `npm test` + boot.

После каждого шага: `npm test`, grep остаточных ссылок на перемещённое/удалённое, ревью diff'а. Бэкапы удаляются только в шаге 4 — служат сетью до верификации.

## Инварианты (сохраняются)
SQL байт-в-байт, half-lesson шаг (45 мин → 0.5), FIFO-цены по партиям, cap-валидация в tx с FOR UPDATE, округление unit_price до копеек, DATE type-parser side-effect, поверхность экспорта barrel.
