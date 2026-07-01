# Django-миграция: разделы `students` + `memberships`

## Context

Бэкенд KOTOKOD переносится с legacy Node.js/Express на чистый Python Django + DRF
(strangler-fig: общая PostgreSQL, общая HMAC session-cookie, ответы один-в-один с
Express). Папка `journal_django/` — переписываемый проект; код вне неё — legacy-источник
истины, из которого SQL переносится **дословно**.

**Уже перенесено:** `core` (auth/pagination/exceptions/fields), `groups` (полный CRUD),
и Phase 2 reference-разделы: `teachers`, `directions`, `discounts`, `settings`, `audit`,
`tokens`.

**Эта задача** — следующий шаг: перенести ученики (`students`, 7 эндпоинтов) и членство
в группах (`memberships`, 4 эндпоинта). Это следующая по логике сущность после groups,
она разблокирует последующие разделы (`lessons`, `payments`). Цель — паритет ответов с
Express, проверяемый pytest-тестами и `scripts/diff_express.py`.

Код пишем через агента **voltagent-lang:python-pro** (требование пользователя),
пошагово с верификацией после каждого приложения (git в проекте нет — откат ручной).

## Канонический паттерн (повторяем для каждого приложения)

Эталон — `journal_django/apps/groups/`. Каждое приложение = папка в `apps/` со слоями:

- `models.py` — ORM-модель, **`managed = False`** (таблица уже создана Express-миграциями),
  поля 1:1 со схемой; DATE-колонки как `CharField`/строки (избегаем TZ-сдвига, см.
  `apps/core/fields.py` `DateStringField`).
- `serializers.py` — DRF-сериализаторы Read/Write/Update; правила валидации повторяют
  Zod-схемы из `shared/schemas.js`.
- `views.py` — тонкие `APIView` (НЕ ViewSet), права `IsManagerOrAdmin` из
  `apps.core.permissions`, парсинг пагинации как в `groups/views.py::_parse_list_params`.
- `services.py` — тонкий слой, делегирует в repository, мапит UNIQUE-нарушения.
- `repository.py` — **ЕДИНСТВЕННОЕ место с SQL**, перенос дословно из `services/repo/*.js`
  (`$N` → `%s`, helpers `_dictfetchall`/`_dictfetchone` как в `groups/repository.py`).
- `urls.py` — `path('', ListCreate)`, `path('/<int:pk>', Detail)`, спец-маршруты.
- `tests/` — pytest (`pytest-django`), зеркалят кейсы Express.

Контракт списков: `{ rows, total, page, page_size }` (`apps/core/pagination.py`).
Ошибки: `{ error: '...' }` (через `apps/core/exceptions.custom_exception_handler`).

---

## Приложение 1 — `apps/students/`

Источники: `routes/admin/students.js`, `services/repo/students.js`,
`getStudentBalance` из `services/repo/payments.js`, схемы `createStudentSchema`/
`updateStudentSchema` (`shared/schemas.js:64-95`). Таблица `students` (миграции
001 + 015 consent-поля). **Soft-delete без колонки `active`** — через
`enrollment_status='not_enrolled'` (+ `frozen_until_month=NULL`).

**Эндпоинты (`/api/admin/students`):**
| Метод/путь | Поведение |
|---|---|
| `GET /` | список + пагинация/сортировка/фильтры |
| `GET /:id` | одна запись или 404 |
| `GET /:id/stats` | сводка посещаемости (сложный CTE + пост-обработка) |
| `GET /:id/balance` | баланс по направлениям (FIFO-агрегат) |
| `POST /` | создать → 201 |
| `PATCH /:id` | обновить → 200/404 |
| `DELETE /:id` | soft-delete → 204/404 |

**Repository (`repository.py`) — функции переносим дословно:**
- `list_students(...)` — пагинатор. Whitelist sort: `id, full_name, age, school_grade,
  enrollment_status, first_purchase_date, created_at` (= `STUDENTS_PAGINATION.sortable`,
  default `full_name`/`asc`). Фильтры (повтор `_build_where` из groups): `full_name`,
  `phone`, `parent_name`, `pm`, `platform_id` — LIKE (nullable); `enrollment_status` —
  exact; `school_grade`, `age` — num.
- `get_student(id)` — `SELECT * FROM students WHERE id = %s`.
- `create_student(data)` — INSERT с `NULLIF(...,'')`/`COALESCE(...,'enrolled')` дословно
  из `students.js:42-63`.
- `update_student(id, data)` — UPDATE через COALESCE (`students.js:66-103`); внимание:
  `frozen_until_month = %s` присваивается **напрямую** (не COALESCE — может стать NULL).
- `soft_delete_student(id)` — `UPDATE students SET enrollment_status='not_enrolled',
  frozen_until_month=NULL WHERE id=%s` → bool по `rowcount`.
- `student_stats(student_id)` — перенос `studentStats` (`students.js:121-296`): один
  большой CTE-запрос (`msk_now`/`msk_month`) **+ существенная пост-обработка на JS**
  (per-group → roll-up по направлениям через Map → `overall`-тоталы, округления
  `Math.round(x*1000)/10`). Портируем построчно в Python (dict вместо Map,
  `round(x, 1)`-эквивалент с тем же поведением; локаль-сортировку направлений по `ru`
  заменяем на сортировку по `direction_name`). **Это самая рискованная часть — отдельные
  тесты на форму ответа.**
- `get_student_balance(student_id)` — перенос `getStudentBalance` + зависимость
  `list_payments({student_id})` (`payments.js:101-161, 44-62`). Приложения `payments` в
  Django пока нет → эти функции кладём в `students/repository.py` (или
  `apps/students/balance.py`) с пометкой «temporary home, переедет при переносе payments».
  Таблица `payments` в БД существует.

**Модель:** поля `students` из миграций 001 + 015 (`full_name, birth_date, phone,
school_grade, platform_id, parent_name, first_purchase_date, age, pm, enrollment_status,
frozen_until_month, consent_given, consent_at, consent_by, consent_note, created_at`),
DATE-поля как строки.

**Сериализаторы:** Write/Update по `baseStudentObject`. `createStudentSchema` имеет
`refine`: `frozen` ⟺ `frozen_until_month != null` — повторить в `validate()`. На update
инвариант НЕ проверяем (как в Express — остаётся на DB CHECK).

**views.py:** stats/balance — отдельные `APIView` ИЛИ доп-методы; `/stats` сперва
проверяет существование ученика (404 как в `students.js:23-24`); `/balance` зовёт
`get_student_balance` напрямую (Express для balance существование НЕ проверяет — повторить).

**urls.py** (порядок важен — спец-маршруты до `<int:pk>` не нужны, т.к. суффиксные):
```
path('', StudentListCreateView)
path('/<int:pk>', StudentDetailView)
path('/<int:pk>/stats', StudentStatsView)
path('/<int:pk>/balance', StudentBalanceView)
```

---

## Приложение 2 — `apps/memberships/`

Источники: `routes/admin/memberships.js`, `services/repo/memberships.js`, схемы
`createMembershipSchema`/`updateMembershipSchema` (`shared/schemas.js:164-177`). Таблица
`group_memberships`. Soft-delete через `active=false`.

**Эндпоинты (`/api/admin/memberships`):**
| Метод/путь | Поведение |
|---|---|
| `GET /` | список (фильтры `group_id`, `student_id`, `include_inactive=1`) — **без пагинации** |
| `POST /` | upsert (ON CONFLICT реактивация) → 201 |
| `PATCH /:id` | обновить → 200/404 |
| `DELETE /:id` | soft-delete → 204/404 |

**Repository — дословно из `memberships.js`:**
- `list_memberships(group_id, student_id, include_inactive)` — динамический WHERE
  (`active=true` если не include_inactive) + JOIN groups/students, `ORDER BY g.name,
  s.full_name`. Возвращает список (не пагинатор).
- `add_membership(data)` — INSERT … `ON CONFLICT (group_id, student_id) DO UPDATE SET
  active=true RETURNING *` (сохраняет историч. `lessons_done/remaining`).
- `update_membership(id, data)` — UPDATE COALESCE.
- `remove_membership(id)` — `UPDATE … SET active=false` → bool.

**views.py:** GET — парсинг `group_id`/`student_id`/`include_inactive` из query (как
`memberships.js:9-15`), без `_parse_list_params`. Права `IsManagerOrAdmin`.

---

## Регистрация

- `config/settings/base.py` → добавить `'apps.students'`, `'apps.memberships'` в
  `INSTALLED_APPS`.
- `config/urls.py` → добавить:
  ```
  path('api/admin/students', include('apps.students.urls')),
  path('api/admin/memberships', include('apps.memberships.urls')),
  ```

## Тесты (pytest, `journal_django/`)

Зеркалим существующие `apps/*/tests/`:
- `students/tests/test_students_repository.py` — CRUD, фильтры, сортировка, soft-delete,
  **отдельно форма `student_stats` и `get_student_balance`** (фикстуры: ученик + группа +
  членство + уроки + посещения + оплата).
- `students/tests/test_students_api.py` — статусы 200/201/204/404, контракт пагинации,
  валидация (`frozen` без `frozen_until_month` → 400).
- `memberships/tests/test_*` — list-фильтры, upsert-реактивация, update/remove, 404.
- Чистка созданных строк в teardown (прямой DELETE через `connection`), как в Nest e2e.

## Verification

1. `cd journal_django && python -m pytest apps/students apps/memberships -v` — все зелёные.
2. Поднять оба бэкенда (Express `:3000`, Django) и прогнать `scripts/diff_express.py` по
   `students`/`memberships` — ответы должны совпасть один-в-один (особенно `/stats`,
   `/balance` — числовые поля и округления).
3. Ручной smoke через admin SPA или curl: список+фильтр, создание, stats, balance, upsert
   членства (повторный POST той же пары → реактивация, не дубль).

## Execution

Реализацию выполнять агентом **voltagent-lang:python-pro**, по одному приложению
(`students`, затем `memberships`), с прогоном pytest и код-ревью после каждого. Сначала
`students` (от него зависят данные для тестов membership-сводок).
