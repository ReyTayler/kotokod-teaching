# Хэндофф: продолжение унификации пропусков (доп.уроки + сгорание)

Промпт для НОВОЙ сессии. Скопируй раздел «ПРОМПТ» ниже в новую сессию.

---

## ПРОМПТ

Продолжаем большой проект: унификация «доп.уроков» и «сгорания» в единый пер-ученик
механизм `AbsenceResolution`. Прочитай сначала эти артефакты и память проекта:

- Память: `project_unify_absences_makeup_burn.md` (полный контекст, решения, статус),
  `project_extra_lessons_balance_guard.md`, `project_finances_test_fifo_inputs_bug.md`,
  `feedback_git_single_main_workflow.md`, `project_dirty_tree_commit_hazard.md`.
- Спека: `docs/superpowers/specs/2026-07-18-unify-absences-makeup-burn-design.md`.
- План Фазы 1: `docs/superpowers/plans/2026-07-18-unify-absences-phase-1.md`
  (roadmap 1a/1b/1c + детальный 1a; ВАЖНО — см. поправку про Task 2/3 ниже).

### Что уже сделано и закоммичено в main (НЕ запушено)
- Фаза 0 целиком (гарды extra-уроков + починка двойного учёта в продлениях).
- burn-WIP («сгорание», наполовину применённый) закоммичен как есть (`015f12b`) —
  НЕ пушить/деплоить, там падающие тесты; это отдельная незаконченная фича, которую
  Фаза 1c потом перепроектирует.
- **1a Task 1 (`d72db3b`):** модель `AbsenceResolution` (пер-ученик 1:1) добавлена
  РЯДОМ со старыми `ExtraLessonAssignment`/`ExtraLessonParticipant`; миграция `0002`
  применена к dev и journal_test; зарегистрирована в `changelog/registry.py`.
- **Корневой фикс (`1af0494`):** `changelog/apps.py` — pghistory JSON-поля теперь
  `deconstruct` как база → `makemigrations` больше НЕ плодит битую pghistory-миграцию
  в site-packages. Это был блокер. Проверка: `makemigrations --check --dry-run` чист.

### Что осталось
- **1a Tasks 2-8** (детали в плане Фазы 1, с поправкой ниже):
  - Task 2 — data-миграция.
  - Task 3 — репозиторий пер-ученик + удаление старых моделей.
  - Task 4 — сервисы пер-ученик + `finances._makeup_completion_dates`.
  - Task 5 — сериализаторы/вьюхи/урлы + чистка changelog-реестра.
  - Task 6 — admin-фронт (список пер-ученик, `AssignExtraLessonModal`).
  - Task 7 — teacher-фронт (модалка записи пер-резолюция).
  - Task 8 — тест-сверка «деньги/продления до==после» + полный прогон.
- Затем **Фаза 1b** (авто-создание pending + переименование статусов + очередь +
  авто-очистка при уходе ученика) и **Фаза 1c** (сгорание через раздел = `burned`-урок
  через record_lesson + переключение модели потребления «present=true по всем подтипам,
  исходный пропуск остаётся false» + блок карточек + синхронизация продлений). Обе —
  сначала writing-plans (детальный план), потом исполнение.
- **Фаза 2**: удаление мёртвой спец-механики (`burned_at`, `burn_surcharge`,
  `apply/revert_makeup_attendance`, `_makeup_completion_dates`) + миграция исторических
  `burned_at` + решить, исключать ли `lesson_type='burned'` из потребления.

### ВАЖНАЯ ПОПРАВКА к плану (Task 2/3), следовать ей, а НЕ тексту плана:
План-док описывает Task 2 как «data-миграция + RunSQL DROP старых таблиц». Так делать
НЕЛЬЗЯ — RunSQL-DROP рассинхронит migration-state Django с БД. Правильно:
- **Task 2 = ТОЛЬКО копирование данных** (RunPython `INSERT ... SELECT` из
  extra_lesson_assignments+participants в absence_resolutions, `ON CONFLICT DO NOTHING`),
  БЕЗ DROP. Старые таблицы/модели остаются.
- **Task 3** = переписать `repository.py` на пер-ученик + удалить классы
  `ExtraLessonAssignment`/`ExtraLessonParticipant` из `models.py` + убрать их 2 записи
  из `changelog/registry.py` + `makemigrations extra_lessons` (сгенерит корректную
  DeleteModel + чистку pghistory-триггеров, теперь makemigrations чист) + migrate обе БД.

### Как исполнять (паттерн, проверен на Фазе 0 и 1a Task 1)
- Субагентами (superpowers:subagent-driven-development): свежий субагент на задачу,
  он реализует+тесты по TDD, но **НЕ коммитит**. Контроллер (ты) независимо прогоняет
  тесты, читает дифф на соответствие спеке, **сам коммитит** (точный `git add` только
  нужных файлов + trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`),
  периодически гоняет code-quality ревью (opus) по диапазону коммитов.
- Дерево сейчас ЧИСТОЕ (burn-WIP закоммичен) — stash не нужен.

### Окружение
- venv: `journal_django/.venv/Scripts/python.exe`. Работать из `journal_django/`.
- Тесты: `.venv/Scripts/python.exe -m pytest ...` (pytest.ini → `config.settings.test`,
  БД `journal_test`).
- Дефолт settings: `config.settings.development` (dev БД `journal`).
- Миграции применять к ОБЕИМ БД:
  `.venv/Scripts/python.exe manage.py migrate extra_lessons` и
  `DJANGO_SETTINGS_MODULE=config.settings.test .venv/Scripts/python.exe manage.py migrate extra_lessons`.
- НЕ запускать `recreate_test_db.sh` (рушит seed общей journal_test).
- Известные предсуществующие ПАДЕНИЯ (не трогать, не наши): 2 в
  `apps/finances/tests/test_fifo_inputs.py` (устаревший `_add_payment`) и
  `test_renewals_stage_sync` (из burn-WIP).

### Git
- Карт-бланш на git от юзера: коммить свободно. **НЕ пушить** (origin на ~80 коммитов
  позади; деплой с main без CI — push = отдельное явное решение юзера).
- Коммит только нужных файлов задачи (`git add <файлы>`), не `git add -A`.

### Ключевые решения (зафиксированы, не переспрашивать)
- Модель 1:1 пер-ученик насквозь (никаких participants/групп/слот-адаптеров).
- Admin `create` (multi-select) → N независимых резолюций; teacher `record` → одна
  резолюция → свой Lesson-факт + Payroll 200₽.
- Статусы в 1a прежние (scheduled/done/cancelled); переименование в
  pending/makeup_scheduled/makeup_done — Фаза 1b.
- Сгорание: флет 200₽ исходному преподавателю (Фаза 1c).
- «Деньги сохранены» = тоталы/потребление/продления до==после (Task 8 сверка).

Начни с чтения памяти и плана, затем исполняй 1a Task 2 (с поправкой выше).

---
