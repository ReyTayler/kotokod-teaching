# Унификация пропусков — Фаза 2 (удаление мёртвой спец-механики + миграция историч. burned_at) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (или контроллер сам). Шаги — чекбоксы.
>
> ⚠️ **ДЕНЬГИ-КРИТИЧНО + СХЕМА.** Удаляются колонки БД (`LessonAttendance.burned_at`, `Payroll.burn_surcharge_amount/at`) и мигрируются исторические денежные данные. Под-этап 2b (миграция) — с ГЕЙТОМ на сверке «до==после» (balance/attended/payroll/reports/renewals всех учеников). Не пушить/деплоить без явного решения пользователя. Делать САМ (не субагентом) — миграция + схема.

**Goal:** Убрать всю мёртвую спец-механику компенсации/сгорания, оставшуюся после 1c: `apply/revert_makeup_attendance`, `_makeup_completion_dates`, `LessonAttendance.burned_at` + burn-путь в `update_attendance_cell`, `Payroll.burn_surcharge_*` + surcharge-строки в payroll. Исторические `burned_at`-правки конвертировать в штатные `burned`-Lesson + `AbsenceResolution` (историческую надбавку сохранить как payroll нового burned-урока — «прошлое как есть»).

**Architecture:** 3 упорядоченных под-этапа. **2a** — удалить чисто мёртвый код (не вызывается в проде после 1c-1) + его тесты. **2b** — data-миграция историч. `burned_at` → `burned`-Lesson+resolution (ЧИТАЕТ колонки, поэтому ДО их удаления) + сверка. **2c** — удалить колонки/поля/burn-путь/surcharge-вывод + фронт + миграции (schema). Порядок обязателен: 2b перед 2c.

**Tech Stack:** Django 5 + DRF, pytest (journal_test), React 19 (admin-src). Миграции — к ОБЕИМ БД (`journal`+`journal_test`), НЕ `recreate_test_db.sh`. venv `.venv/Scripts/python.exe`, из `journal_django/`. Следующая миграция extra_lessons — 0010; lessons/payroll — свои номера (проверить `ls`).

---

## Установленные факты (перед стартом)

- `_makeup_completion_dates` (finances/repository.py:65) — определена, но НЕ вызывается ни в одном consumption-пути (1c-1 перестал вызывать; reports.py:18 — только коммент). Мёртвая.
- `apply_makeup_attendance`/`revert_makeup_attendance` (lessons/repository.py:477/523) — не вызываются в проде (1c-1 заменил на increment/decrement_lessons_done). Остались тесты + миграционный хелпер 0008 (его НЕ трогать — историческая миграция).
- `burned_at` (LessonAttendance) читается в `fifo_inputs` (~138/174/179) и `student_fifo_remaining` (~325/330/332) как приоритет даты; пишется ТОЛЬКО в `update_attendance_cell` (burn-WIP). После 2b историч. burned_at converted → колонка не нужна.
- `burn_surcharge_amount/at` (Payroll) — пишется в `update_attendance_cell`; читается в payroll `_surcharge_entries`/`payroll_summary` + фронт `PayrollPage.tsx` (is_surcharge) + `shared-types.ts`.
- **Данные:** dev — 2 `burned_at`-строки (по 1 ученику на урок, surcharge 200 каждая, БЕЗ resolution). **Прод — почти наверняка 0** (burned_at-логика = решение 2026-07-16, последний деплой 2026-07-13, absences не пушены). Миграция на проде — вероятный no-op; на dev — 2 строки.

---

## Под-этап 2a — удалить чисто мёртвый код + тесты

### Task 2a.1: Удалить `_makeup_completion_dates`

**Files:** `apps/finances/repository.py`; тесты, если есть на неё прямые.

- [ ] **Step 1:** Убедиться, что нет вызовов: `grep -rn "_makeup_completion_dates" apps/` → только def + комменты + возможные тесты. Удалить функцию (repository.py:65-92) и упоминание в reports.py:18 (коммент). Обновить импорты (`Iterable`/`datetime` если больше не нужны — проверить).
- [ ] **Step 2:** Удалить/адаптировать прямые тесты `_makeup_completion_dates` (grep в `apps/finances/tests/`). Если тест кодирует старую модель — удалить.
- [ ] **Step 3:** Прогон: `.venv/Scripts/python.exe -m pytest apps/finances/ -q`. PASS (кроме 2 предсущест. fifo_inputs). Commit `refactor(finances): drop dead _makeup_completion_dates (Phase 2a)`.

### Task 2a.2: Удалить `apply_makeup_attendance` / `revert_makeup_attendance`

**Files:** `apps/lessons/repository.py:477-551`; тесты в `apps/lessons/tests/`.

- [ ] **Step 1:** `grep -rn "apply_makeup_attendance\|revert_makeup_attendance" apps/` — подтвердить, что вызовов в проде НЕТ (только определения + тесты; хелпер миграции 0008 использует RAW SQL, не эти функции — проверить, что 0008 не импортит их). Если 0008 импортит — НЕ удалять, стоп.
- [ ] **Step 2:** Удалить обе функции. Удалить их юнит-тесты (`grep` по имени в tests). Проверить неиспользуемые импорты в repository.py (`F`, `Greatest` — вероятно ещё нужны другим кодом; удалять только реально осиротевшее).
- [ ] **Step 3:** Прогон: `pytest apps/lessons/ apps/extra_lessons/ -q`. PASS. Commit `refactor(lessons): drop dead apply/revert_makeup_attendance (Phase 2a)`.

---

## Под-этап 2b — миграция историч. `burned_at` → `burned`-Lesson + resolution (ГЕЙТ)

**Модель конвертации (на каждую строку `LessonAttendance` с `burned_at IS NOT NULL AND present=true` на regular-уроке L, ученик S):**

Цель — числовой инвариант: balance/attended/renewals/payroll-суммы/месячные отчёты каждого ученика и преподавателя БИТ-В-БИТ те же. Аналог миграции 0008 (makeup), но для burn + с переносом надбавки.

1. Создать `Lesson`: `lesson_type='burned'`, `lesson_date = burned_at` (сохраняет месяц денег), `group_id=L.group_id`, `teacher_id=L.teacher_id`, `original_teacher_id=NULL`, `lesson_number=L.lesson_number`, `lesson_duration_minutes=L.lesson_duration_minutes`, `submitted_by_token=f'burn-migrated:{L}:{S}'` (уникализирует natural-key), `submitted_at=now()`.
2. `LessonAttendance(new_lesson, S, present=true, burned_at=NULL)`.
3. `Payroll` нового урока: `teacher_id=L.teacher_id`, `total_students=1`, `present_count=1`, `penalty=0`, `payment = <доля surcharge этого ученика>`. Доля: если на L ровно один burned-ученик → `payment = L.payroll.burn_surcharge_amount`; если несколько → делить поровну (целочисленно, остаток первому по student_id). (Прод: 0 строк; dev: 1-на-урок → просто = surcharge.)
4. Откатить исходный: `LessonAttendance(L,S)` → `present=false, burned_at=NULL`.
5. Скорректировать исходный `Payroll` L: `present_count = <кол-во present=true attendance на L после отката>` (baseline). `payment` НЕ трогаем (уже baseline). `burn_surcharge_amount/at` не трогаем (удалятся в 2c). (Если после отката present_baseline изменил ставку — НЕ должен, base payment уже считался от baseline; только present_count-поле выравниваем для консистентности.)
6. `AbsenceResolution(missed_lesson=L, student=S, status='burned', fact_lesson=new_lesson, created_at=now())`. Проверить отсутствие конфликта UNIQUE(missed_lesson, student) — если резолюция уже есть (не должно для историч. burn), пропустить с логом.
7. **lessons_done НЕ трогаем** (историч. flip уже инкрементировал его — как и новая burn() инкрементирует; аналог 0008).

Идемпотентность: повторный прогон — no-op (guard: если на L,S уже present=false ИЛИ уже есть burned-resolution → пропустить). Reverse — noop с пометкой необратимости (деньги-критично).

### Task 2b.1: Снимок «до» (характеризационный тест)

**Files:** Test `apps/extra_lessons/tests/test_burned_at_migration_reconciliation_2b.py` (new).

- [ ] **Step 1:** Тест на СИНТЕТИКЕ (создать regular-урок, ученика, оплату; вручную поставить attendance present=true + burned_at + payroll base+surcharge — симулировать историч. burn через RAW SQL/ORM). Зафиксировать эталон: `balance_for_student`, `attended_units_total`, `renewals._attended_total`, `SUM(payroll payment)` teacher за месяц burned_at, `collect_monthly_report` за месяц burned_at. Прогнать на СТАРОЙ схеме (до миграции) → PASS. Докстрока: после хелпера числа те же.

### Task 2b.2: Хелпер миграции + миграция

**Files:** `apps/extra_lessons/_migration_helpers.py` (добавить `convert_historical_burned_at(connection)`); `apps/extra_lessons/migrations/0010_convert_historical_burned_at.py`; Test из 2b.1.

- [ ] **Step 1:** Написать `convert_historical_burned_at(connection)` строго по «модели конвертации» выше (RAW SQL или ORM через apps registry — как в 0008; свериться с 0008 на паттерн `apps.get_model`). Guard-идемпотентность.
- [ ] **Step 2:** TDD-тест хелпера на синтетике (2b.1): после вызова — исходный present=false/burned_at=NULL, есть burned-Lesson (present=true, lesson_date=old burned_at, payroll=surcharge), resolution status=burned; balance/attended/payroll-суммы/месяц не сдвинулись; повторный вызов — no-op.
- [ ] **Step 3:** Миграция `0010 = RunPython(convert_historical_burned_at, noop)`. Применить к ОБЕИМ БД. `makemigrations --check --dry-run` чист. Commit `feat(absences): migrate historical burned_at to burned lessons (Phase 2b)`.

### Task 2b.3: Полная сверка «до==после» + ГЕЙТ

**Files:** Test из 2b.1 (теперь на мигрированных данных).

- [ ] **Step 1:** На dev-БД (реальные 2 строки) снять снимок ДО (скрипт: по всем затронутым student_id/teacher_id — balance/attended/payroll-суммы по месяцам/reports) — ВЫПОЛНИТЬ ПЕРЕД применением 0010 к dev (т.е. этот шаг логически до 2b.2-Step3 на dev; зафиксировать числа в скратч-файл). После миграции — снимок ПОСЛЕ, поэлементно сравнить. Должны совпасть.
- [ ] **Step 2:** Полный прогон: `pytest apps/extra_lessons/ apps/lessons/ apps/finances/ apps/renewals/ apps/payroll/ apps/dashboard/ apps/changelog/ -q`. PASS (кроме 2 предсущест. fifo).
- [ ] **Step 3:** Code-review (opus) миграции. **СТОП — доложить пользователю: сверка сошлась, прежде чем 2c (удаление колонок).**

---

## Под-этап 2c — удалить колонки/поля/burn-путь/surcharge-вывод + фронт (schema)

### Task 2c.1: Упростить `update_attendance_cell` (убрать burn-путь)

**Files:** `apps/lessons/repository.py:357-474`; тесты.

- [ ] **Step 1:** Переписать `update_attendance_cell` в ПРОСТОЙ toggle (восстановление до-burn-WIP семантики, т.к. burn-WIP не деплоился): без `burned_at`, без base/surcharge-разделения. present/absent toggle + lessons_done delta + пересчёт `Payroll.total_students/present_count/payment = calculate_payment(total, present_total, is_half)`, `penalty` не трогать. UPSERT attendance без поля `burned_at`.
- [ ] **Step 2:** Адаптировать тесты `update_attendance_cell` (убрать проверки burned_at/surcharge; оставить toggle+lessons_done+payment recompute). Commit `refactor(lessons): plain attendance toggle, drop burn path (Phase 2c)`.

### Task 2c.2: Убрать burned_at-приоритет даты в finances

**Files:** `apps/finances/repository.py` (fifo_inputs ~138/174/179, student_fifo_remaining ~325/330/332); reports.py.

- [ ] **Step 1:** В `fifo_inputs`: убрать `burned_at` из `.values(...)`; заменить `date = r['burned_at'] or r['lesson_date']` на `date = r['lesson_date']`. Аналогично `student_fifo_remaining`. Обновить комменты (burned-урок теперь сам несёт свою дату в lesson_date). reports.py — коммент про burned_at убрать/поправить.
- [ ] **Step 2:** Прогон `pytest apps/finances/ -q`. PASS. Commit `refactor(finances): drop burned_at date-priority (Phase 2c)`.

### Task 2c.3: Удалить колонку `LessonAttendance.burned_at`

**Files:** `apps/lessons/models.py:106-111`; миграция lessons (следующий номер).

- [ ] **Step 1:** Убедиться, что `burned_at` больше нигде не читается/пишется: `grep -rn "burned_at" apps/` → только миграции (0008/2b — историч., оставить) + pghistory event-модель (авто). Удалить поле из модели.
- [ ] **Step 2:** `makemigrations lessons` (RemoveField + авто pghistory event-поле). Применить к ОБЕИМ БД. `--check` чист.
- [ ] **Step 3:** Прогон `pytest apps/lessons/ apps/finances/ -q`. Commit `refactor(lessons): drop LessonAttendance.burned_at column (Phase 2c)`.

### Task 2c.4: Удалить `Payroll.burn_surcharge_*` + surcharge-вывод

**Files:** `apps/payroll/models.py:49-52`; `apps/payroll/repository.py` (_surcharge_entries, union, summary surcharge, _ENTRY_VALUES is_surcharge, _SORTABLE); миграция payroll.

- [ ] **Step 1:** `payroll/repository.py`: удалить `_surcharge_entries`; `list_payroll` = `_base_entries(filters)` без union (убрать `.union(...)`, но сохранить контракт rows — is_surcharge больше нет). Убрать `is_surcharge` из `_ENTRY_VALUES` и `_base_entries.annotate`. В `payroll_summary` убрать весь surcharge-блок (surcharge_qs/rows/merge) — остаётся только base. Проверить `dictrows`/pop-переименования.
- [ ] **Step 2:** Удалить поля `burn_surcharge_amount/at` из `Payroll` модели. `makemigrations payroll` (RemoveField + pghistory event). Применить к ОБЕИМ БД.
- [ ] **Step 3:** Адаптировать payroll-тесты (убрать surcharge-сценарии; проверить, что мигрированные burned-уроки теперь base-строки). Прогон `pytest apps/payroll/ -q`. Commit `refactor(payroll): drop burn_surcharge, single base entry list (Phase 2c)`.

### Task 2c.5: Фронт — убрать `is_surcharge`

**Files:** `frontend/admin-src/src/lib/shared-types.ts` (PayrollEntry), `frontend/admin-src/src/pages/payroll/PayrollPage.tsx`.

- [ ] **Step 1:** `shared-types.ts`: убрать `is_surcharge` из `PayrollEntry` + поправить коммент про `payment`.
- [ ] **Step 2:** `PayrollPage.tsx:82,88`: убрать ветки `r.is_surcharge ? ... : ...` (оставить обычный рендер `present_count/total_students` и суммы). Burned-уроки теперь обычные строки payroll.
- [ ] **Step 3:** `cd frontend/admin-src && npx tsc --noEmit` → 0. `git status` — только `*-src/`. Commit `refactor(payroll): drop is_surcharge on front (Phase 2c)`.

### Task 2c.6: Финальная сверка + прогон

- [ ] **Step 1:** Полный прогон: `pytest apps/extra_lessons/ apps/lessons/ apps/finances/ apps/renewals/ apps/payroll/ apps/dashboard/ apps/changelog/ apps/scheduling/ apps/students/ apps/teacher_spa/ -q`. PASS кроме 2 предсущест. fifo.
- [ ] **Step 2:** `makemigrations --check --dry-run` → No changes. tsc admin+teacher = 0. `git status` без dist.
- [ ] **Step 3:** Code-review (opus) по всему диапазону Фазы 2. Починить Important.
- [ ] **Step 4:** STOP — доложить: Фаза 2 готова, весь проект унификации закрыт. Обсудить деплой-порядок (миграции 0010/lessons/payroll ДО нового кода) и push.

---

## Деплой-порядок (важно, к моменту push/деплоя)

Миграция 2b (0010) ОБЯЗАНА пройти ДО удаления колонок (2c-миграции) и ДО нового кода finances/payroll, читающего без burned_at/surcharge. В общем `migrate`-шаге порядок номеров это гарантирует (0010 < lessons/payroll RemoveField). На проде burned_at, скорее всего, пусто → 0010 = no-op, но безопасно.

## Self-Review (по спеке)

- **Спека «Что удаляется из кода»** → 2a (makeup helpers, _makeup_completion_dates), 2c (burned_at, burn_surcharge, exclude уже снят в 1c-1). ✅
- **Спека «Миграция данных Фаза 2» → историч. burned_at → burned-запись+resolution, surcharge НЕ переписывать** → 2b (payment нового burned = историч. surcharge, «прошлое как есть»). ✅
- **Спека «числа бит-в-бит те же» → тест-сверка** → 2b.1/2b.3 (ГЕЙТ). ✅
- **Бэкфилл очереди историч. present=false НЕ поднимаем** → миграция трогает только burned_at-строки, не все пропуски. ✅
- **CLAUDE.md: новые модели → pghistory; тут только удаление полей** → makemigrations сам уберёт pghistory event-поля; registry не меняется (модели не добавляются). ✅
