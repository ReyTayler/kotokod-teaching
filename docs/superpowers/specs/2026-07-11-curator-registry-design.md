# Реестр куратора — вкладка дашборда admin SPA

**Дата:** 2026-07-11
**Статус:** проектирование → реализация (поэтапно)
**Связано:** `apps/dashboard`, `apps/finances`, `apps/scheduling`, `apps/renewals`, `DashboardPage.tsx`

## Цель

Добавить в admin-дашборд вторую вкладку **«Реестр»** — операционный экран куратора/менеджера: кто заканчивает пакет, кто простаивает, что сегодня в расписании, и полный список активных учеников с прогрессом и остатком. Текущая вкладка (финансы) остаётся без изменений.

## ⚠️ ОБНОВЛЕНИЕ 2026-07-11 — Вариант B (масштаб до 1000+ учеников)

Изначальный дизайн кэшировал ПОЛНЫЙ снимок списка и резал срез в Python — не
масштабируется на тысячи (весь список в память на каждый запрос). Переделано:

- **Список `/students` пагинируется на уровне БД.** `registry_service.students_qs`
  строит аннотированный queryset: `balance`/`attended`/`planned`/`last`/`next` —
  коррелированные `Subquery` по `student_id` (без fan-out); фильтр сегмента и
  поиск — `WHERE` (баланс — простой пул `purchased − attended`, SQL-арифметика,
  НЕ FIFO); сортировка — `ORDER BY`; срез — `LIMIT/OFFSET` штатным DRF-пагинатором.
  Строки страницы сериализуются с догрузкой кодов/преподов батчем. **Список не кэшируется.**
- **Сводка `/summary`** (KPI + сигналы + поток) агрегируется по всей активной
  популяции и кэшируется (Redis) + прогревается Celery (`refresh_registry_summary`).
  Сигналы теперь — **только счётчики** (`{count}`), без `student_ids` (фильтрация ушла в WHERE).
- **Индекс** `group_memberships(student_id)` (миграция `memberships/0004`) — под
  membership-подзапросы. `payments(student_id)`/`lesson_attendance(student_id)` уже были.
- Верификация: на dev-БД 211 учеников, SQL-баланс = `balances_for_students` (0 расхождений),
  сегмент-count в БД = счётчики сводки.

Разделы ниже описывают исходный (snapshot) дизайн — оставлены как контекст решения.

## Ключевые решения (утверждены)

1. **Строка реестра = ученик** (не группа). Баланс пулится по `student_id` (общий пул по всем направлениям — инвариант `2026-07-08-student-balance-pooling`), поэтому единица — ученик. Групповые атрибуты (код, преподаватель, прогресс) агрегируются по активным membership ученика.
2. **Подход B — серверная пагинация** списка учеников (масштаб на сотни/тысячи).
3. **Redis + Celery вводятся постепенно, с graceful-degradation.** Без `REDIS_URL` кэш падает на локальный in-memory; без Celery-воркера эндпоинт считает снимок синхронно. Локальная разработка на Windows не ломается.
4. **6 KPI-плашек** как в макете, кликабельны (фильтруют таблицу).
5. **4-й сигнал** = «Нет плана / расписания» (активные группы без плана или без ближайшего занятия).
6. **Окно «Отмен»** = текущий МСК-месяц (как финансовый дашборд).

## Модель данных (переиспользуем, не дублируем)

- **Пул-баланс:** `apps/finances/repository.balances_for_students(ids)` — batch, без N+1.
- **FIFO-остаток/денежная стоимость:** `fifo_inputs()` + `compute_fifo` (один проход по школе).
- **Прогресс/посещения:** `group_memberships.lessons_done` (numeric, half-lesson) + `active`; план группы — число `planned_lessons` (курсовых) на группу.
- **Поток дня / ближайшее занятие:** `planned_lessons` (материализованы). Нужен **админский** вызов без скоупа по преподавателю (расширить `apps/scheduling/repository`).
- **Активный ученик:** `students.enrollment_status='enrolled'` и есть `active=true` membership. `frozen` не считается простоем.

## Архитектура: «снимок реестра» + серверная пагинация

Баланс/прогресс/статус — **вычисляемые** (не колонки), поэтому `ORDER BY` в SQL по ним невозможен. Решение:

```
registry_snapshot()  →  {
  generated_at,
  kpis: {...},
  today_stream: [...],
  signals: { ending, closed, idle, no_plan },   # count + student_ids[]
  students: [ StudentRow, ... ]                  # ВСЕ активные, отсортированы urgency-first, затем по имени
}
```

- Снимок считается **одним проходом** по школе (дорого: FIFO + план + расписание). Это единица кэширования.
- Пагинирующий эндпоинт **нарезает готовый снимок** (slice + фильтр сегмента + поиск), не пересчитывая.

### StudentRow
```
{ student_id, student_name,
  codes: [str], teacher_names: [str],      # primary + "+N" на фронте
  balance,                                  # пул (остаток уроков)
  attended, planned, progress_pct,          # Σ по активным membership
  last_lesson_date, next_lesson_date,
  status }                                  # closed | ending | idle | no_plan | ok
```

### KPI (все считаются из снимка)
| KPI | Формула |
|-----|---------|
| `active_students` | число активных |
| `renewal_upsell` | число с `balance ≤ 2` (= ending + closed) |
| `idle` | число в простое (>14 дней) |
| `avg_progress` | среднее `progress_pct` |
| `lessons_ahead` | `Σ balance` по всем (только положительные) |
| `cancellations` | число отменённых occurrences за текущий МСК-месяц |

### Сигналы (count + список student_ids для фильтра)
- `ending`: `0 < balance ≤ 2`
- `closed`: `balance ≤ 0` (пакет закрыт / долг)
- `idle`: enrolled, есть проведённые занятия, `last_lesson` > 14 дней назад, не frozen
- `no_plan`: активные membership без плана или без ближайшего occurrence

## API (RBAC `IsManagerOrAdmin`, префикс `/api/admin`)

1. `GET /api/admin/registry/summary`
   → `{ generated_at, kpis, today_stream, signals }` (без списка students). Кэшируется.
2. `GET /api/admin/registry/students?page=&page_size=&segment=&search=&sort=&dir=`
   → стандартный пагинированный конверт (`StandardPagination`).
   - `segment ∈ {all, ending, closed, idle, no_plan}` (по умолчанию `all`).
   - `search` — по имени/коду (подстрока, без учёта регистра).
   - `sort ∈ {urgency, name, balance, progress, last_lesson}` (whitelist), `dir ∈ {asc, desc}` (паттерн sort-dir из CLAUDE.md — чинить в обоих местах).
   - Источник — тот же кэшированный снимок; пагинация/фильтр/сортировка в Python поверх снимка.

Оба эндпоинта — тонкие APIView в `apps/dashboard/registry_views.py`, логика в `apps/dashboard/registry_service.py`. `permission_classes = [IsManagerOrAdmin]`.

## Кэширование (Фаза 2) — Redis с fallback

- `CACHES['default']`: `django_redis` на `REDIS_URL`, если задан; иначе `LocMemCache`. Плюс отдельный alias при желании; для старта — один `default`.
- `registry_snapshot()` оборачивается `cache.get_or_set('registry:snapshot', ..., TTL)`; TTL короткий (напр. 120с).
- **Инвалидация:** после мутаций, влияющих на баланс/расписание/членство (payments POST/DELETE, attendance, memberships, scheduling-операции) — `cache.delete('registry:snapshot')`. Реализовать точечно в соответствующих services (без глобальных сигналов на всё подряд).
- Fallback: если Redis недоступен в проде — `django_redis` кидает исключение; оборачиваем чтение так, чтобы при ошибке кэша считать синхронно (не падать). Cache — оптимизация, не источник правды.

## Асинхронность (Фаза 3) — Celery skeleton

- `config/celery.py` — Celery-app, broker/result = `REDIS_URL`. `apps/dashboard/tasks.py` — задача `refresh_registry_summary` (пересчитывает снимок и кладёт в кэш).
- **Celery beat** прогревает снимок в проде каждые N минут → запросы всегда попадают в тёплый кэш.
- **Graceful:** приложение полностью работает без воркера/beat — эндпоинт считает синхронно при холодном кэше. Задача просто держит кэш тёплым.
- **Деплой (Beget, без Docker):** systemd-юниты `celery-worker.service` и `celery-beat.service`; Redis из `apt`. Документируется в `deploy/` (не Docker). На 2 ГБ RAM — `--concurrency=1`, `--pool=solo`/prefork минимально.
- **Локально (Windows):** Celery не запускаем; `REDIS_URL` не задан → LocMemCache + синхронный расчёт.

## Фронтенд (вкладка «Реестр»)

- `DashboardPage`: под-навигация «Финансы | Реестр», активная вкладка в URL `?tab=`. Вкладка «Реестр» — `lazy()`.
- Компоненты в `pages/dashboard/registry/`: `RegistryTab`, `RegistryKpiRow` (переиспользует `KpiCard`), `TodayStreamCard`, `SignalsCard`, `RegistryTable`.
- Хуки: `useRegistrySummary()` (staleTime ~30с) и `useRegistryStudents(params)` — **server-paginated**, `placeholderData: keepPreviousData` (обязательно по CLAUDE.md).
- KPI-плашки и строки сигналов кликабельны → ставят `segment` в URL, таблица перефетчивается.
- Таблица: Статус · Код · Ученик · Препод. · Прогресс (`X/Y`) · Остаток · Последний · Ближайший. Пагинация серверная; поиск (debounce) и сортировка через URL-параметры. Клик по строке → `/admin/students/:id`.
- Дизайн: только `tokens.css` + `lib/labels.ts` для enum-лейблов; native form-элементы запрещены (`SelectInput`/`DateInput`/`Combobox`). `ErrorBoundary key={location.pathname}`. `.data-table--loading` гасит `pointer-events` только на `tbody`.

## Тесты

- **Бэкенд (pytest, journal_test):** границы сигналов (`balance` = 0 / 2 / >2 / <0); активный vs frozen/declined; простой на фиксированную дату (мокнуть `msk_now`); `today_stream` пуст/непуст; пул-баланс ученика с несколькими направлениями; пагинация (page/page_size/segment/search/sort/dir, включая инвалидный `dir` → дефолт); RBAC (teacher → 403). Кэш: снимок инвалидируется после оплаты.
- **Фронт:** smoke — вкладка рендерится, переключение сегмента меняет запрос, «Показать ещё»/страницы работают.

## Производительность

- Снимок — один проход (FIFO уже грузится целиком в дашборде). Батч-мапы имён/расписания (как `build_calendar`), без N+1.
- Redis снимает повторный расчёт с каждого запроса; Celery-beat держит кэш тёплым в проде.
- Индексы под предикаты `enrollment_status`, `group_memberships.active` — проверить, добавить при необходимости (PG не индексирует FK автоматически).

## Фазы реализации

1. **Backend core (без кэша):** `registry_service` + 2 эндпоинта (B, серверная пагинация) + админский scheduling-вызов + тесты. Корректность прежде скорости.
2. **Redis cache:** `CACHES` с fallback, обёртка снимка, точечная инвалидация, env `REDIS_URL`.
3. **Celery skeleton:** app + `refresh_registry_summary` + beat + systemd-доки в `deploy/`. Graceful без воркера.
4. **Frontend:** вкладки в `DashboardPage`, хуки, KPI/сигналы/поток/таблица, сборка бандла.

Каждая фаза — отдельный проверяемый шаг с верификацией и ревью (careful-incremental).

## Вне scope (в бэклоге)

5 идей дашбордов (churn, нагрузка преподавателей, прогноз выручки, тепловая карта, когорты) — `docs/BACKLOG.md`, раздел «Дашборды поверх реестра куратора».
