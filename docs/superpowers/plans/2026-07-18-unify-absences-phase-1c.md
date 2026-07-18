# Унификация пропусков — Фаза 1c (единая модель потребления + сгорание) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> ⚠️ **ДЕНЬГИ-КРИТИЧНО.** Фаза 1c переписывает ядро расчёта ПОТРЕБЛЕНИЯ (баланс/отработано/продления/отчёты) и МИГРИРУЕТ исторические денежные данные. Каждый под-этап обязан завершаться сверкой «снимок балансов/отработано/продлений всех учеников ДО == ПОСЛЕ». Не пушить/не деплоить без явного решения пользователя.

**Goal:** Свести доп.урок и сгорание к ОДНОМУ правилу потребления — *урок состоялся → ученик present=true на записи-уроке → списывается 1 (или 0.5) в дату этой записи*. Исходный пропущенный урок навсегда `present=false`; списывает всегда НОВАЯ запись (`extra`/`burned`). Это убирает спец-механику (`apply/revert_makeup_attendance`, `_makeup_completion_dates`, `.exclude(extra)`, `burned_at`, `burn_surcharge`) и делает «Сжечь» симметричным доп.уроку.

**Architecture:** Эволюция на месте поверх Фаз 1a/1b. Сейчас (1a/1b) доп.урок считается ретроактивной отметкой ИСХОДНОГО урока (`apply_makeup_attendance` флипает его в present=true), а сам `extra` исключается из потребления (`.exclude(lesson__lesson_type='extra')`), плюс месяц денег переносится `_makeup_completion_dates`. 1c переключает это: исходный остаётся `present=false`, потребление идёт от `extra`/`burned` записи (present=true) в её собственную дату; исключение и перенос-месяца удаляются. Спека: `docs/superpowers/specs/2026-07-18-unify-absences-makeup-burn-design.md` (раздел «Деньги и продления», «Триггеры», «Гарды»).

**Tech Stack:** Django 5 + DRF, pytest + pytest-django (реальная `journal_test`), React 19 + TanStack Query v5 (admin), React + @shared (teacher). Команды из `journal_django/`, интерпретатор `.venv/Scripts/python.exe`. Миграции — к ОБЕИМ БД (dev `journal` + `journal_test`); НЕ запускать `recreate_test_db.sh`.

---

## Декомпозиция Фазы 1c на под-этапы (порядок обязателен)

Фаза 1c слишком велика/деньги-критична для одного плана. Три под-этапа; каждый оставляет систему рабочей и с неизменными денежными числами (сверка «до==после»). Этот документ ДЕТАЛИЗИРУЕТ **1c-1** (переключение модели + миграция — риск в основном тут); 1c-2/1c-3 получат свой проход writing-plans после того, как 1c-1 сядет и сверка сойдётся.

- **Фаза 1c-1 — переключение модели потребления (доп.урок) + миграция исторических makeup_done + сверка.** Данный документ. **Самый рискованный: правит финансовое ядро и историю.**
- **Фаза 1c-2 — «Сжечь» через запись-урок (`burned`-Lesson, present=true, флет 200₽ исходному преподавателю группы) + статус `burned` + откат.** Отдельный план. Строится НА новой модели потребления (burned present=true считается штатно, как extra после 1c-1). Заменяет half-baked burn-WIP (`update_attendance_cell`/`burned_at`/`burn_surcharge`).
- **Фаза 1c-3 — фронт: блок карточек в `LessonEditor`, удаление burn-тоггла и assign-триггера из грида, кнопка «Сжечь» в разделе, синхронизация продлений на сгорании.** Отдельный план.

**Что остаётся Фазе 2 (после всей 1c):** физическое удаление мёртвого кода/колонок (`apply/revert_makeup_attendance`, `_makeup_completion_dates`, `LessonAttendance.burned_at`, `Payroll.burn_surcharge_*`) + миграция исторических `burned_at`-правок в `burned`-записи. 1c-1 их только ПЕРЕСТАЁТ ВЫЗЫВАТЬ/ЧИТАТЬ (кроме миграционного отката исходных отметок), физическое удаление — Фаза 2, чтобы каждый шаг был обратим и сверяем.

---

## Фаза 1c-1 — детально

**Goal (1c-1):** Переключить потребление доп.урока с «исходный флипнут present=true, extra исключён» на «исходный остаётся present=false, extra present=true считается в свою дату», мигрировать все исторические `makeup_done` под новую модель, и доказать сверкой, что баланс/отработано/продления/месячные отчёты каждого ученика — БИТ-В-БИТ те же.

### Ключевые решения 1c-1 (фикс, без двусмысленности)

1. **Новое правило потребления:** потребляет любая `LessonAttendance.present=true`, БЕЗ `.exclude(lesson_type='extra')`, в дату `lesson.lesson_date` этой записи. Исходный пропуск (`present=false`) не потребляет. `_makeup_completion_dates` больше не применяется (месяц = дата extra-урока и так).
2. **`record()` (доп.урок) больше НЕ вызывает `apply_makeup_attendance`;** `delete_fact()` больше НЕ вызывает `revert_makeup_attendance`. Потребление/возврат идут естественно от extra-записи (создание/удаление её LessonAttendance present=true).
3. **`lessons_done`-счётчик (group_memberships):** сейчас `record` наращивал его через `apply_makeup_attendance` на ИСХОДНОМ уроке; теперь инкремент должен идти при создании extra-факта (по ученику extra-урока), а декремент — при удалении факта. Проверить, не наращивает ли `insert_lesson`/`record`-путь его дважды. Единицы — вес ИСХОДНОГО урока (0.5 для 45-мин исходного), реализуется через `fact_lesson.lesson_duration_minutes = исходная длительность` (record уже так делает — берёт `locked['duration_minutes']`? НЕТ, берёт длительность НАЗНАЧЕНИЯ; **это надо поправить: extra-факт должен нести длительность ИСХОДНОГО урока, чтобы вес списания был верен** — см. спека «Правило единиц»).
4. **`.exclude(lesson__lesson_type='extra')` удаляется во ВСЕХ местах** (перечень — ниже, Task 2). После удаления `extra` present=true считается везде одинаково (finances + renewals через единый `attended_units_total`).
5. **Миграция исторических `makeup_done`:** для каждого — вернуть ИСХОДНЫЙ урок в `present=false` (снять историческую отметку `apply_makeup_attendance`) и снять соответствующий инкремент `group_memberships.lessons_done`. Потребление переезжает на уже существующую `extra`-запись (present=true) — числа и дата совпадают (см. сверку). Идемпотентно, обратимо (reverse: восстановить present=true на исходном + вернуть инкремент — но reverse деньги-критичен, допускается noop с явной пометкой необратимости при согласии пользователя).
6. **«Сохранено» = баланс + отработано + продления + месячные отчёты + SUM(payroll) каждого ученика ДО==ПОСЛЕ.** Снимок до миграции, снимок после, поэлементное сравнение (Task 5).

### Перечень мест `.exclude(lesson__lesson_type='extra')` / `_makeup_completion_dates` / `burned_at` (обязателен к правке)

- `apps/finances/repository.py`: строки ~133 (`fifo_inputs`), ~241 (`balances_for_students`), ~267 (`attended_units_total`), ~326 (`student_fifo_remaining`), ~391 (ещё один consumption-путь). Плюс `_makeup_completion_dates` (def ~65, вызовы ~142, ~331) и приоритет дат `makeup_dates > burned_at > lesson_date` (~179, ~337).
- `apps/finances/reports.py`: `collect_monthly_report` использует `_makeup_completion_dates` (~106) и учитывает `burned_at` (~17).
- `apps/dashboard/registry_service.py`: строка ~110 (`.exclude(lesson__lesson_type='extra')`).
- `apps/renewals/engine.py::_attended_total` — делегирует в `finances.attended_units_total` (единый источник), правится автоматически, но ПРОВЕРИТЬ.

**ВАЖНО про `burned_at`:** в 1c-1 сгорание ЕЩЁ идёт по старому burn-WIP (`update_attendance_cell` ставит `burned_at`). Пока не трогаем burn-путь (это 1c-2). Значит `burned_at`-приоритет даты в `fifo_inputs`/`student_fifo_remaining` ПОКА ОСТАЁТСЯ (иначе сломаем текущее сгорание). Убираем ТОЛЬКО `.exclude(extra)` и `_makeup_completion_dates` (makeup-специфику). `burned_at` уйдёт в 1c-2/Фазе 2. То есть 1c-1 — хирургически про доп.урок, не про сгорание.

### Структура файлов (1c-1)

- `apps/extra_lessons/services.py` — `record()` убрать `apply_makeup_attendance` + чинить длительность extra-факта (исходная) + инкремент lessons_done по extra-ученику; `delete_fact()` убрать `revert_makeup_attendance` + декремент.
- `apps/lessons/repository.py` — возможно, вынести хелпер инкремента/декремента lessons_done для extra-пути (если record строит факт напрямую).
- `apps/finances/repository.py` — убрать `.exclude(extra)` (5 мест) + перестать применять `_makeup_completion_dates` для месяца (оставить саму функцию до Фазы 2, просто не вызывать в consumption/`fifo_inputs`/reports). Оставить `burned_at`-приоритет.
- `apps/finances/reports.py` — убрать `_makeup_completion_dates` из месячной атрибуции доп.урока (extra-урок сам в своём месяце).
- `apps/dashboard/registry_service.py` — убрать `.exclude(extra)`.
- `apps/extra_lessons/migrations/0008_*` — RunPython: для всех `makeup_done` вернуть исходные уроки в present=false + снять инкремент lessons_done. (Хелпер в `_migration_helpers.py`, тест напрямую.)
- Тесты: адаптировать `test_reconciliation_1a.py`/`test_lifecycle_1b.py` (теперь исходный остаётся false, потребление на extra), `apps/finances/tests/*` (attended/balance/reports/fifo — extra теперь считается), `test_attended_units.py`; новый `test_consumption_switch_reconciliation_1c.py`.

---

## Task 1: Снимок «до» для сверки (характеризационный тест перед изменениями)

**Files:** Test `apps/extra_lessons/tests/test_consumption_switch_reconciliation_1c.py` (new).

- [ ] **Step 1:** Написать тест, который СЕЙЧАС (старая модель) на фикстурном сценарии (ученик, оплата 8 уроков, пропуск, назначенный+проведённый доп.урок) фиксирует эталонные числа: `balance_for_student`, `attended_units_total`, `renewals.engine._attended_total`, `collect_monthly_report` (месяц доп.урока), `SUM(payroll.payment)`. Значения захардкодить как «эталон» (balance 8→7, attended 1, payroll 200, месяц = месяц доп.урока). Прогнать → PASS на СТАРОЙ модели.
- [ ] **Step 2:** Пометить в докстроке: после Task 2-4 эти же числа должны сойтись на НОВОЙ модели (исходный present=false, extra считается). Это и есть «до==после». Commit `test(absences): pin consumption numbers before 1c switch`.

---

## Task 2: Убрать `.exclude(extra)` и `_makeup_completion_dates` из потребления

**Files:** Modify `apps/finances/repository.py`, `apps/finances/reports.py`, `apps/dashboard/registry_service.py`; Test существующие finances/dashboard.

- [ ] **Step 1:** В `apps/finances/repository.py` удалить `.exclude(lesson__lesson_type='extra')` в: `fifo_inputs`, `balances_for_students`, `attended_units_total`, `student_fifo_remaining`, и пятом consumption-пути (~391). Обновить докстроки/комменты (убрать упоминание «extra исключается, т.к. компенсируемый учтён ретроактивно»).
- [ ] **Step 2:** Перестать применять `_makeup_completion_dates` к месяцу в `fifo_inputs` и `student_fifo_remaining`: убрать `makeup_dates` из приоритета дат, оставить `burned_at or lesson_date` (сгорание пока по-старому). Саму функцию `_makeup_completion_dates` НЕ удалять (Фаза 2) — просто не вызывать в этих путях.
- [ ] **Step 3:** В `apps/finances/reports.py::collect_monthly_report` убрать `_makeup_completion_dates`-перенос месяца для доп.урока (extra-урок сам в своём месяце). Оставить `burned_at`-логику.
- [ ] **Step 4:** В `apps/dashboard/registry_service.py` убрать `.exclude(lesson__lesson_type='extra')`.
- [ ] **ВНИМАНИЕ:** После этого шага БЕЗ Task 3 (миграция) финтесты УПАДУТ на исторических makeup_done (двойной учёт: исходный present=true + extra present=true). Это ожидаемо — Task 3 чинит данные, Task 4 чинит `record`. Прогонять точечно, полный зелёный — к Task 5. Commit `refactor(finances): count extra lessons as consumption (drop exclude+makeup-dates) (Phase 1c-1 Task 2)`.

---

## Task 3: Миграция исторических makeup_done (исходный → present=false, lessons_done −)

**Files:** Modify `apps/extra_lessons/_migration_helpers.py`; Create `apps/extra_lessons/migrations/0008_revert_historical_makeup_attendance.py`; Test `apps/extra_lessons/tests/test_makeup_data_migration_1c.py` (new).

- [ ] **Step 1: Хелпер `revert_historical_makeups(connection)`** — для каждого `absence_resolutions.status='makeup_done'`: (а) `UPDATE lesson_attendance SET present=false WHERE lesson_id=<missed_lesson_id> AND student_id=<student_id> AND present=true` (снять историческую отметку apply_makeup); (б) снять инкремент `group_memberships.lessons_done` на вес исходного урока (0.5 если исходный 45-мин, иначе 1) для (group этого урока × student). Идемпотентность: помечать/проверять, что не снято дважды — напр. по факту present=true на исходном (если уже false — пропускать). ОБЯЗАТЕЛЬНО в докстроке: extra-запись уже present=true и теперь (после Task 2) сама даёт потребление в своём месяце — числа не двигаются.
- [ ] **Step 2:** TDD-тест хелпера на синтетике: makeup_done с исходным present=true + extra present=true; после revert — исходный false, extra true, lessons_done скорректирован; повторный вызов — no-op.
- [ ] **Step 3:** Миграция `0008` = `RunPython(revert_historical_makeups, noop)` (reverse — noop с пометкой необратимости; деньги-критично, восстановление вручную при откате). Применить к ОБЕИМ БД. makemigrations --check чист. Commit `feat(absences): migrate historical makeups to present=false original (Phase 1c-1 Task 3)`.

---

## Task 4: `record`/`delete_fact` — без apply/revert_makeup, верная длительность/счётчик

**Files:** Modify `apps/extra_lessons/services.py`; Test `apps/extra_lessons/tests/test_extra_lessons_services.py`.

- [ ] **Step 1:** В `record()`: убрать `if present: lessons_repository.apply_makeup_attendance(...)`. Вместо ретроактивной отметки исходного — потребление идёт от самой extra-записи (present передаётся в `insert_attendance`). НО: (а) extra-факт должен нести `lesson_duration_minutes` = длительность ИСХОДНОГО урока (не назначения!), чтобы вес списания = вес пропуска — заменить в `insert_lesson` `locked['duration_minutes']` на длительность missed-урока (`Lesson.objects.get(id=missed_lesson_id).lesson_duration_minutes`); (б) инкремент `group_memberships.lessons_done` для present-ученика на этот вес — сейчас его давал apply_makeup; теперь добавить явный инкремент по (missed-group × student) при present, ИЛИ переиспользовать `increment_lessons_done` как в record_lesson. Проверить, что НЕ задвоено.
- [ ] **Step 2:** В `delete_fact()`: убрать `revert_makeup_attendance`. Удаление extra-Lesson+attendance само снимает потребление; декремент `lessons_done` — симметрично Step 1.
- [ ] **Step 3:** TDD: адаптировать `test_extra_lessons_services.py` — после record ИСХОДНЫЙ урок остаётся present=false (не true!), extra present=true; lessons_done +1 (вес исходного); после delete_fact всё назад. Money как было. Commit `refactor(absences): consume from extra fact, keep original absent (Phase 1c-1 Task 4)`.

---

## Task 5: Полная сверка «до==после» + прогон

**Files:** Test `apps/extra_lessons/tests/test_consumption_switch_reconciliation_1c.py` (из Task 1 — теперь на новой модели).

- [ ] **Step 1:** Тот же сценарий, что Task 1, теперь на НОВОЙ модели: те же эталонные числа (balance 8→7, attended 1, renewals 1, месяц доп.урока, payroll 200) — но исходный урок present=false, потребление на extra. Числа обязаны совпасть. Плюс явная проверка: `LessonAttendance(missed_lesson, student).present == False` и extra-запись present=true.
- [ ] **Step 2:** Полный прогон: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/ apps/lessons/ apps/finances/ apps/renewals/ apps/dashboard/ apps/changelog/ apps/scheduling/ apps/students/ apps/teacher_spa/ -q`. PASS кроме известных 2 `test_fifo_inputs`. Точечно проверить финтесты, где раньше был `.exclude(extra)`-инвариант (`test_attended_units.py`, `test_balance.py::test_extra_lesson_does_not_double_count_balance` — этот тест САМ проверял старую модель, его смысл меняется: теперь «не задваивает» обеспечивается тем, что исходный false, extra true = ровно 1; адаптировать, сохранив анти-двойной-учёт как инвариант).
- [ ] **Step 3:** Ревью code-quality (opus) по диапазону 1c-1. Commit сверки. **СТОП — доложить пользователю, сверка сошлась, прежде чем 1c-2 (сгорание).**

---

## Вне охвата Фазы 1c-1 (→ 1c-2 / 1c-3 / 2)

- «Сжечь» через `burned`-запись, статус `burned`, откат сгорания, замена burn-WIP — Фаза 1c-2.
- Блок карточек в `LessonEditor`, удаление burn-тоггла/assign-триггера из грида, кнопка «Сжечь» в разделе, renewals-sync на сгорании — Фаза 1c-3.
- Физическое удаление `apply/revert_makeup_attendance`, `_makeup_completion_dates`, `burned_at`, `burn_surcharge_*` + миграция исторических `burned_at` — Фаза 2.
