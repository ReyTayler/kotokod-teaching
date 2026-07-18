# Хэндофф: продолжение унификации пропусков — Фазы 1c-2 / 1c-3 / 2

> Промпт для НОВОЙ сессии. Продолжаем большой проект: унификация «доп.уроков» и
> «сгорания» в единый пер-ученик механизм `AbsenceResolution`. Фазы 0, 1a, 1b и
> 1c-1 ЗАВЕРШЕНЫ и закоммичены в `main` (НЕ запушены). Осталось: **1c-2**
> (сгорание), **1c-3** (фронт), **Фаза 2** (удаление мёртвого кода + миграция
> исторических `burned_at`).

## Сначала прочитай (обязательно)

- **Память проекта:** `project_unify_absences_makeup_burn.md` (полный контекст,
  решения, статус по всем фазам — САМЫЙ ВАЖНЫЙ), `project_finances_test_fifo_inputs_bug.md`,
  `feedback_git_single_main_workflow.md`, `project_dirty_tree_commit_hazard.md`,
  `feedback_careful_incremental_refactor.md`, `feedback_financial_accounting_precision.md`,
  `feedback_subagent_npm_build_dist_pollution.md`.
- **Спека (единственный источник дизайна):**
  `docs/superpowers/specs/2026-07-18-unify-absences-makeup-burn-design.md`.
- **План Фазы 1c** (roadmap 1c-1/1c-2/1c-3, детализирован только 1c-1):
  `docs/superpowers/plans/2026-07-18-unify-absences-phase-1c.md`.
- Ранее: планы фаз 1 (`...-phase-1.md`), 1b (`...-phase-1b.md`).

## Что уже сделано и закоммичено в `main` (НЕ запушено; origin на ~107 коммитов позади)

- **Фаза 0** — гарды extra-CRUD + единый источник «отработано» (finances=renewals).
- **Фаза 1a** — пер-ученик `AbsenceResolution` заменил групповую
  `ExtraLessonAssignment`+`ExtraLessonParticipant` (модель/repo/services/serializers/
  views/оба фронта), старые модели удалены (миграция 0004 DeleteModel), сверка денег.
- **Фаза 1b** — очередь: статусы `pending/makeup_scheduled/makeup_done` (нет
  терминального `cancelled`; отмена/откат → pending); авто-создание `pending` в
  `apps/lessons/services.py::record_lesson` (regular-only, идемпотентно); авто-очистка
  при уходе ученика (declined/not_enrolled); полный `UNIQUE(missed_lesson, student)`;
  admin-очередь UI. Миграция 0007 = реальный DB-level `ON DELETE CASCADE` на
  `missed_lesson`. Гард удаления урока с makeup_done-детьми (409).
- **Фаза 1c-1 (ДЕНЬГИ-КРИТИЧНО, завершено с «гейтом на сверке»)** — ПЕРЕКЛЮЧЕНА
  модель потребления: исходный пропущенный урок навсегда `present=false`,
  потребление идёт от extra-факта (`present=true`) в его дату. Убран
  `.exclude(lesson__lesson_type='extra')` в 5 местах finances + dashboard + reports;
  `_makeup_completion_dates` больше НЕ применяется к месяцу; `record()` даёт
  extra-факту длительность ИСХОДНОГО урока (вес) + `increment_lessons_done` (вместо
  `apply_makeup_attendance`); `delete_fact` — `decrement_lessons_done` (вместо
  `revert_makeup_attendance`) + восстановлен renewal-stage sync. Миграция 0008
  мигрирует исторические `makeup_done` (длительность факта → исходная; исходный
  present→false; lessons_done не трогается). Code-review (opus): before==after по
  деньгам подтверждён, миграция идемпотентна. Полный прогон: 786 passed.

**Мёртвый код после 1c-1 (не вызывается в проде, УДАЛИТЬ в Фазе 2, НЕ раньше):**
`apps/lessons/repository.py::apply_makeup_attendance` / `revert_makeup_attendance`,
`apps/finances/repository.py::_makeup_completion_dates`.

## Что осталось

### Фаза 1c-2 — «Сжечь» через запись-урок (СЛЕДУЮЩЕЕ; сначала writing-plan)
Спека, разделы «Состояния», «Зарплата», «Гарды»:
- Добавить статус `burned` в `AbsenceResolution.STATUS_CHOICES` (+ миграция CHECK,
  как делали 0006). Переход `pending → burned`; откат `burned → pending`.
- Сервис `burn(resolution_id, request)`: создаёт `Lesson(lesson_type='burned')`
  present=true для ученика, дата=сегодня, длительность=ИСХОДНОГО урока (вес!),
  teacher=исходный преподаватель группы пропуска, payment=флет 200₽
  (`calculate_extra_lesson_payment(1)`), penalty=0 (админское действие,
  submit_date=lesson_date). Транзакция + lock, как в `record()`. Проверка баланса
  (`assert_students_paid`) — нельзя сжечь урок неоплаченному. Резолюция → `burned`,
  fact_lesson=новый Lesson. renewal-stage sync on_commit (как в record 1c-1).
- Откат сгорания (delete burned fact) — симметрично `delete_fact` (decrement
  lessons_done, delete Payroll+Lesson, back_to_pending, renewal-sync).
- **burned present=true считается в потреблении штатно** (после 1c-1 `.exclude`
  снят; `burned` не исключается) — в свою дату/месяц. Проверить сверкой.
- Заменяет half-baked burn-WIP: старый путь сгорания в
  `apps/lessons/repository.py::update_attendance_cell` (`burned_at` + `Payroll.burn_surcharge_*`)
  — в 1c-2 НЕ трогать данные, но новый «Сжечь» идёт мимо него; физически burn-WIP
  и `burned_at`/`burn_surcharge` удаляются в Фазе 2 (+ миграция исторических burned_at).
- API: teacher/admin эндпоинт «Сжечь» + «Откат сгорания». Сериализаторы/вьюхи/урлы.
- Сверка «до==после» + полный прогон.

### Фаза 1c-3 — фронт (после 1c-2; сначала writing-plan)
Спека, раздел «Блокировка ячеек» и «Затронутые файлы (фронт)»:
- `LessonEditor.tsx` (admin): после сохранения урока карточки отсутствовавших —
  серые/некликабельные. Удалить старый burn-тоггл (`togglePresent`→`burnConfirm`) и
  триггер `AssignExtraLessonModal` из грида (всё про пропуск — только через раздел).
- Раздел «Доп.уроки»: на `pending`-строке добавить кнопку «Сжечь» рядом с
  «Назначить доп.урок»; на `burned`-строке — «Откат сгорания». Статус-лейбл `burned`.
- teacher-фронт: если календарь/меню показывает сгорание — учесть.
- `lib/labels.ts` / `shared-types.ts` — статус `burned`.
- tsc обоих фронтов = 0. НЕ запускать `npm run build` (не коммитить dist —
  [[feedback_subagent_npm_build_dist_pollution]]).

### Фаза 2 — удаление мёртвой спец-механики (после всей 1c; сначала writing-plan)
- Удалить `apply/revert_makeup_attendance` (lessons/repository), `_makeup_completion_dates`
  (finances/repository) + все их тесты.
- Удалить `LessonAttendance.burned_at` (колонка + миграция) и весь burn-путь в
  `update_attendance_cell`; `Payroll.burn_surcharge_amount/at` (модель + миграция) +
  вывод surcharge-строк в `apps/payroll/repository.py`.
- **Миграция исторических `burned_at`-правок → `burned`-Lesson + resolution**
  (историческую зарплату `burn_surcharge` НЕ переписывать — прошлое как есть, флет
  200₽ только для новых). Сверка «до==после».

## Как исполнять (паттерн, проверен на всех фазах этой сессии)

- **Сначала writing-plan** (skill `superpowers:writing-plans`) для 1c-2, покажи
  пользователю ключевые решения, дождись «начинай». Деньги-критичные фазы — с
  «гейтом на сверке» (STOP на reconciliation, доложить).
- Субагентами (`superpowers:subagent-driven-development`): свежий субагент на
  задачу, реализует+тесты по TDD, но **НЕ коммитит и НЕ трогает git**. Контроллер
  (ты) независимо прогоняет тесты, читает дифф на соответствие спеке, **сам
  коммитит** (точный `git add` только нужных файлов + trailer
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`), периодически гоняет
  code-quality ревью (`code-reviewer` агент, opus) по диапазону коммитов и чинит
  Important-находки.
- **Фронт делай САМ** (не субагентом) — риск dist-pollution; всегда проверяй
  `git status`, что изменился только `*-src/`, не `*-dist/`.
- Мелкие/деньги-критичные/миграционные правки — делай сам, не субагентом.
- Дерево обычно ЧИСТОЕ между задачами. Проверяй `git status --short` перед `git add`.

## Окружение

- venv: `journal_django/.venv/Scripts/python.exe`. Работать из `journal_django/`.
- Тесты: `.venv/Scripts/python.exe -m pytest <path> -q` (pytest.ini →
  `config.settings.test`, БД `journal_test`).
- Дефолт settings: `config.settings.development` (dev БД `journal`).
- Миграции применять к ОБЕИМ БД:
  `.venv/Scripts/python.exe manage.py migrate extra_lessons` и
  `DJANGO_SETTINGS_MODULE=config.settings.test .venv/Scripts/python.exe manage.py migrate extra_lessons`.
  После — `manage.py makemigrations --check --dry-run` → «No changes detected».
- **НЕ запускать** `recreate_test_db.sh` (рушит seed общей journal_test).
- Bash-инструмент иногда сбрасывает cwd → используй `cd /c/Users/ilyap/TestKOTOKOD/journal_django && ...`.
- Последняя миграция extra_lessons: `0008_revert_historical_makeups`. Следующая — 0009.

## Git

- Карт-бланш на git от юзера: коммить свободно. **НЕ пушить** (origin на ~107
  коммитов позади; деплой с main без CI — push = отдельное явное решение юзера).
- Коммит только нужных файлов задачи (`git add <файлы>`), не `git add -A`.
- Файлы в CRLF — предупреждения «LF will be replaced by CRLF» нормальны.

## Ключевые ГОТЧИ, найденные по ходу (не наступай снова)

1. **`missed_lesson_fixture` авто-создаёт pending** (пишет через `create_lesson_full`
   → `record_lesson` авто-создаёт) — unit-тесты, что делают `create_scheduled_direct`
   на ту же пару, конфликтуют по UNIQUE; переводи существующий pending
   (`lock_for_assign`→`assign_pending`) или удаляй его сначала.
2. **`cursor.executemany(... ON CONFLICT ...)` несовместим с pghistory-контекстом
   под HTTP** («not all arguments converted») — используй ORM `bulk_create(ignore_conflicts=True)`.
3. **Авто-создание pending рикошетит в ~15 app тест-teardown**, что делают raw
   `DELETE FROM lessons` — решено ОДНИМ DB-level `ON DELETE CASCADE` (0007), не
   правкой каждого teardown. Для 1c-2 `burned`-факты: их удаление тоже должно чистить
   зависимости; проверь, что `delete`-гард (LessonHasMakeupResolutions) покрывает и
   `burned` (сейчас гард только на makeup_done — вероятно надо расширить на burned).
4. **Extra/burned-факт несёт длительность ИСХОДНОГО урока** (вес потребления!), а не
   операционную длительность назначения. Календарь берёт операционную из
   `AbsenceResolution.duration_minutes`, потребление — из `fact.lesson_duration_minutes`.
5. **Деньги-миграции — с «гейтом»**: снимок «до» (существующие money-тесты),
   изменение, миграция, сверка «до==после» на реальных record()-данных; синтетические
   тесты, кодирующие СТАРУЮ модель, переписывай на новую.
6. **Мигр. хелперы идемпотентны** (guard-условия), reverse=noop для деньги-критичных.
7. **Деплой-порядок:** миграция потребления ОБЯЗАНА пройти до нового кода fifo.

## Известные предсуществующие падения (НЕ наши, не чинить в рамках фичи)

2 в `apps/finances/tests/test_fifo_inputs.py` (`test_fifo_inputs_builds_lots_and_consumptions`,
`test_fifo_inputs_pools_across_directions`) — устаревший `_add_payment` не пишет
`lessons_count` (см. [[project_finances_test_fifo_inputs_bug]]). Чинить отдельно.

Начни с чтения памяти + спеки + плана 1c, затем writing-plan для **Фазы 1c-2**.
