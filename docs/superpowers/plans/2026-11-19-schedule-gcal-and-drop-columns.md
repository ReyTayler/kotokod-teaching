# График в стиле Google Calendar + удаление «Колонок таблиц» — план

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
> Правила репо: исполнители НЕ запускают git (кроме read-only), не делают `npm run build`, не пересоздают БД;
> в дереве KOTOKOD чужой WIP «Мотивации» — правки точечные; коммитит координатор; review-agent после каждой задачи.

**Goal:** убрать «Колонки таблиц» из KOTOKOD; перевести «График работы» и календари уроков на сутки 00:00–24:00 с прокруткой и видом Google Calendar — в KOTOKOD и Eduson.

**Architecture:** бэкенд графика хранит минуты от полуночи (0–1440) вместо `TimeField`; API по-прежнему `"HH:MM"` с `"24:00"` как концом. Фронт: общие `shared/availability` и `shared/calendar/WeekGrid` — 48 слотов, sticky-шапка/гаттер, автопрокрутка, линия «сейчас». `settings_app` сводится к оболочке с миграцией удаления моделей.

**Spec:** `docs/superpowers/specs/2026-11-19-schedule-gcal-and-drop-columns-design.md`.

**Порядок:** K1 (бэк колонок) → K2 (бэк минут); параллельно фронт K3 (колонки), K4 (WeekGrid), K5 (редактор, после K2-контракта не зависит — контракт API не меняется). Затем Eduson: E1 (бэк минут) ∥ E2 (фронт = порт K4+K5). Финал: полный pytest обоих, tsc, итоговое ревью.

---

### K1 (KOTOKOD, backend-django): удалить бэкенд «Колонок таблиц»

**Files:** `apps/settings_app/*`, `config/urls.py` (строка `path('api/admin/settings', ...)`), `apps/changelog/{registry,summary,humanize}.py`, `apps/notifications/models.py` (комментарий), тесты changelog, упоминающие `settings`/`AdminUserSettings`.

- [ ] Найти все ссылки: `grep -rn "settings_app\|AdminUserSettings\|admin_user_settings\|'settings'" apps config` (кроме Django-`settings`).
- [ ] Удалить `views.py, urls.py, serializers.py, services.py, repository.py, tests/` из `apps/settings_app`; `models.py` оставить пустым с docstring «приложение выводится из эксплуатации: модели удалены миграцией 0003, удалить app — следующим релизом (BACKLOG)».
- [ ] Сгенерировать миграцию `manage.py makemigrations settings_app` → `0003_*` (DeleteModel event-модели и `AdminUserSettings`, снятие pgtrigger). Проверить, что ничего, кроме settings_app, не генерируется.
- [ ] Убрать маршрут из `config/urls.py`; запись из `registry.py`; `'settings'` из `_ENTITY_RU` и прочих словарей `summary.py`/`humanize.py` (только записи сущности журнала, не поле `settings` других моделей — проверить по смыслу).
- [ ] Тесты changelog, использующие `AdminUserSettings` (например, identity `('username',)`), переписать на другую трекаемую модель или удалить, если проверяли только её.
- [ ] Применить: `manage.py migrate settings_app` (dev) и `--settings=config.settings.test` (journal_test).
- [ ] `docs/BACKLOG.md`: пункт «Удалить apps.settings_app из INSTALLED_APPS после выкатки миграции 0003». (Если `docs/BACKLOG.md` содержит чужие правки — только дописать в конец.)
- [ ] Прогон: `pytest apps/changelog apps/notifications -q` → PASS; `manage.py check`.

### K2 (KOTOKOD, backend-django): сутки 00:00–24:00, минуты от полуночи

**Files:** `apps/availability/{models,services,serializers,views}.py`, `migrations/0002_*.py`, все `tests/*`.

- [ ] Модели: заменить `start_time/end_time` на `start_minute/end_minute = models.SmallIntegerField()` (у override — `null=True`). `GRID_START_MIN = 0`, `GRID_END_MIN = 1440`, `SLOT = 30`. CHECK: `start_minute >= 0`, `end_minute <= 1440`, `start_minute < end_minute`, `start_minute % 30 == 0` и `end_minute % 30 == 0` (через `Q` с `Mod` или `ExpressionWrapper`; проверить SQL через `sqlmigrate`); override: both-or-none; частичный UNIQUE «закрыт» — по `start_minute IS NULL`. Индексы не менять.
- [ ] Миграция `0002`: AddField новых (nullable), `RunPython` копирует `h*60+m` из старых полей (обратная функция — обратно в time; 1440 → `time(23,59)` недопустим: в обратной миграции окна, кончающиеся в 24:00, переносить нельзя — бросать понятную ошибку), RemoveField старых и их CHECK, AlterField rule-полей в NOT NULL, новые CHECK. pghistory event-модели обновить (makemigrations сгенерирует). Применить к dev и journal_test.
- [ ] Сервис: интервал = `(int, int)` минут; `validate_intervals` — кратность 30, `0 <= s < e <= 1440`; `fmt(m)` → `"HH:MM"` (`1440 → "24:00"`); `_today` и логика недели без изменений.
- [ ] Сериализатор: регэксп `^(?:([01]\d|2[0-3]):(00|30)|24:00)$`; `"24:00"` разрешён только как конец (`"24:00"` в начале → 400); парсинг в минуты.
- [ ] `windows_payload` и вьюхи — те же строки `"HH:MM"`.
- [ ] Тесты: обновить все под минуты и новые границы. Добавить: `00:00–24:00` проходит; `07:30–09:00` теперь проходит; `"24:00"` начало → 400; `23:45` → 400; миграция данных (тест с `MigrationExecutor` или проверка через ORM после применения — по образцу проекта, если есть; иначе — unit-тест функции переноса).
- [ ] Прогон: `pytest apps/availability apps/scheduling apps/changelog -q` → PASS.

### K3 (KOTOKOD, frontend-design): удалить фронт «Колонок таблиц»

**Files:** удалить `lib/table-settings.ts`, `pages/settings/EntityColumnsEditor.tsx`, `hooks/useAdminSettings.ts`; правки `pages/{students/StudentsListPage,groups/GroupsListPage,teachers/TeachersListPage,lessons/LessonsListPage}.tsx` (`columns` напрямую вместо `useTableColumns`), `lib/labels.ts` (подпись сущности журнала `settings`, если есть), WIP: `pages/settings/SettingsPage.tsx` (убрать вкладку `columns`), удалить WIP-файл `pages/settings/ColumnsSettingsTab.tsx`, ключ `columns` из `SETTINGS_TAB_LABELS`; CSS, относящийся только к редактору колонок (найти по классам `EntityColumnsEditor`).
- [ ] Закоммиченная версия `SettingsPage.tsx` (заглушку) пишет координатор при коммите — агент правит только рабочий файл.
- [ ] `npx tsc --noEmit -p .` в admin-src и teacher-src → 0.

### K4 (KOTOKOD, frontend-design): календари уроков — сутки, вид GCal

**Files:** `shared/calendar/WeekGrid.tsx`, `calendar.css` (+ при необходимости `CalendarView.tsx`).
- [ ] `HOUR_START = 0`, `HOUR_END = 23`; высота часа 48 px; существующий скролл-контейнер `.cal-grid-wrap` + sticky-шапка — сохранить; гаттер времени sticky слева.
- [ ] Подписи часов на линии часа (первая скрыта), часовые линии сплошные, получасовые светлее.
- [ ] Шапка дня: короткий день капсом мелко + крупная дата; «сегодня» — дата в кружке `--accent`.
- [ ] Линия «сейчас»: красная (токен danger/red) с точкой слева; автопрокрутка: если сегодня в видимой неделе — к «сейчас» (центр), иначе к 08:00; повторять при смене недели.
- [ ] Фон окон графика (`.cal-avail`) — по новым границам (до 24:00 = низ сетки).
- [ ] tsc в обоих SPA.

### K5 (KOTOKOD, frontend-design): редактор графика — сутки, вид GCal

**Files:** `shared/availability/{grid.ts,ScheduleEditor.tsx,ScheduleGrid.tsx,schedule.css}`.
- [ ] `grid.ts`: `GRID_START_MIN = 0`, `SLOT_COUNT = 48`, `slotLabel(48) = "24:00"`; `toMinutes("24:00") = 1440`.
- [ ] Сетка: контейнер фиксированной высоты по окну (`max-height: calc(100dvh - …)`), прокрутка; sticky шапка дней и гаттер; час ≈ 48 px (слот 24 px); подписи часов на линии; линии как в K4; шапка дня как в K4; линия «сейчас» в режиме недели текущей недели.
- [ ] Автопрокрутка при открытии/смене режима/недели: к `min(08:00, первое окно) − 1 ч`.
- [ ] Протяжка мышью/пером: при курсоре в 40 px от верхнего/нижнего края контейнера — автопрокрутка (requestAnimationFrame), закраска продолжает работать по ячейкам под курсором.
- [ ] Сводка/скелеты/ошибки — без регрессий; скелет — высоты контейнера.
- [ ] tsc в обоих SPA.

### E1 (Eduson, backend-django): порт K2
Перенести итоговые `apps/availability/*` из KOTOKOD HEAD после K2; миграцию `0002` сгенерировать в Eduson; применить к `eduson`/`eduson_test`; `pytest apps/availability apps/scheduling apps/changelog -q`.

### E2 (Eduson, frontend-design): порт K4+K5
Перенести поведение K4/K5 в Eduson, стиль — визуальный язык Eduson (токены `--avail-*`, `--line*`, акцент чёрный/белый, линия «сейчас» — токен `--bad`), без затирания особенностей Eduson (makeup и т.п.). tsc в обоих SPA.

### F (координатор + review-agent)
Полный `pytest -q` в KOTOKOD и Eduson; tsc; итоговое ревью; коммиты по задаче; push — только по команде владельца.
