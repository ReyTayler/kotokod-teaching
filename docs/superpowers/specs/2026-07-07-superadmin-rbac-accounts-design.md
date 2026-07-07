# Дизайн: роль superadmin, перестройка RBAC и управление учётками

**Дата:** 2026-07-07
**Ветка (на момент проектирования):** feature/lesson-scheduling-materialized
**Статус:** утверждён владельцем, готов к формированию плана реализации

## Контекст и цель

Платформа `journal_django` (Django + DRF, admin SPA на React 19) имеет три роли:
`teacher`, `manager`, `admin`. Требуется:

1. Ввести 4-ю роль `superadmin` (полный доступ ко всей admin-платформе).
2. Убрать у `admin` доступ к разделам **Журнал ИБ** (`audit`) и **Учётки** (`accounts`)
   вместе со всеми связанными операциями.
3. Убрать все операции над сущностью **Преподаватель** у `admin` и `manager`
   в admin SPA — оставить только просмотр.
4. Закрыть раздел **Зарплата** (`payroll`) для `manager` и `admin` — только `superadmin`.
5. Раздел **Уроки** (`lessons`) — уточнено владельцем при планировании:
   - **Менеджер** — только просмотр (не создаёт/не редактирует/не удаляет урок,
     не отмечает посещаемость).
   - **Админ** — может создавать/редактировать/удалять урок и отмечать посещаемость
     (наравне с `superadmin`).
   - **Зарплата за урок** (вложенный объект `payroll`: `total_students`,
     `present_count`, `payment`, `penalty`) — скрыта от `manager` и `admin`;
     видит только `superadmin`. Остальным — только посещаемость (attendance-сетка).
6. Операции над **Абонементами** (`memberships`) и **Скидками** (`discounts`) — только `superadmin`.
7. Операции над **Направлениями** (`directions`) — только `superadmin`; остальные роли — просмотр.
8. У учётных записей — имена пользователей; для учёток преподавателей имя брать из имени преподавателя.
9. Возможность **отключения** и **удаления** учётной записи через раздел Учётки.
10. ~~Отображать пароль учётки в разделе Учётки~~ — **ВНЕ ОБЪЁМА** (см. ниже).

### Решения владельца (развилки)

- **Требование 10 (показ пароля):** закрыто. Пароли хранятся только хэшем
  (`set_password`), аккаунт создаётся без пароля (invite-ссылка + self-set + обязательная 2FA).
  Отображение реального пароля потребовало бы обратимого хранения — прямое нарушение
  `docs/security-guidelines.md` и `CLAUDE.md`. Модель хэш+invite сохраняется без изменений.
- **Миграция ролей:** все текущие учётки с `role='admin'` промоутятся в `superadmin`
  (сохраняют полный доступ). Новые `admin` создаются уже урезанными.
- **Отключение vs удаление:** «Отключить» — обратимый тумблер `is_active`.
  «Удалить» — физическое (hard) удаление строки `accounts`, с подтверждением в UI.
- **Журнал изменений (`changelog`):** просмотр — `manager`/`admin`/`superadmin`;
  откат операций — только `admin`/`superadmin` (менеджеру недоступен).

## Аудит текущего состояния (справочно)

- Роли: `accounts/models.py` → `Account.Role` (`teacher|manager|admin`) + CHECK-констрейнт
  `accounts_role_check`.
- Права: `core/permissions.py` → `IsTeacher`, `IsManager`, `IsAdmin`, `IsManagerOrAdmin`
  (чистые проверки членства в роли через `_authenticated_with_role`).
- Текущая раскладка по разделам:
  - `accounts` (Учётки) → `IsAdmin`
  - `audit` (Журнал ИБ) → `IsAdmin`
  - `changelog` (Журнал изменений: list/detail/revert) → `IsAdmin`
  - `teachers` (list/create/detail/patch/delete) → `IsManagerOrAdmin`
  - `payroll`, `lessons`, `memberships`, `discounts`, `directions`,
    `students`, `groups`, `settings_app`, `payments`, `dashboard`,
    `scheduling` (admin-план) → `IsManagerOrAdmin`
- Фронт: route-гварда по ролям нет — все `<Route>` в `App.tsx` открыты, ограничение
  только бэкендом. В `Sidebar.tsx` навигация к Учёткам/Журналу ИБ/Журналу изменений
  показывается по `me?.role === 'admin'`. Write-кнопки внутри страниц ролью не гейтятся.
- Модель учётки: отдельного «имени» нет — только `email`. `me.name` = `teacher_name`
  (для teacher) либо `email` (`auth_app/services.py:254`). `first_name/last_name`
  от `AbstractUser` не используются.
- Пароли: только хэш; аккаунт создаётся без пароля, юзер ставит его по invite;
  сброс = новый invite. `is_active` + `soft_delete()` уже реализуют «отключение».
  Настоящего hard-delete нет.

## Целевой дизайн

### 1. Роли и permission-классы

Роли: `teacher` · `manager` · `admin` · **`superadmin`**.

`core/permissions.py` — явные классы (стиль кодовой базы, без неявных short-circuit):

| Класс | Роли | Назначение |
|---|---|---|
| `IsSuperAdmin` (новый) | `superadmin` | Учётки, Журнал ИБ, Зарплата |
| `IsAdminOrSuperAdmin` (новый) | `admin`, `superadmin` | Откат в Журнале изменений |
| `IsManagerOrAdmin` (расширяем) | `manager`, `admin`, **`superadmin`** | Дашборд, Ученики, Группы, Настройки, Платежи, scheduling-план, чтение Журнала изменений |
| `ReadStaffWriteSuperAdmin` (новый, method-aware) | GET → `manager`/`admin`/`superadmin`; write → `superadmin` | Преподаватели, Направления, Абонементы, Скидки |
| `ReadStaffWriteAdmin` (новый, method-aware) | GET → `manager`/`admin`/`superadmin`; write → `admin`/`superadmin` | Уроки (CRUD + посещаемость) |
| `IsTeacher` | без изменений | teacher SPA |
| `IsManager`, `IsAdmin` | остаются определёнными; ссылки из вьюх заменяются | — |

`ReadStaffWriteSuperAdmin` реализуется через `request.method in rest_framework.permissions.SAFE_METHODS`
и покрывает одним классом как совмещённые list+create вьюхи, так и detail-вьюхи
(GET/PATCH/DELETE). Расширение `IsManagerOrAdmin` — добавить `'superadmin'` в кортеж ролей
(имя сохраняем ради минимальной инвазивности; в docstring отметить, что включает superadmin).

**Инвариант RBAC (`CLAUDE.md`):** каждая изменяемая вьюха обязана иметь `permission_classes`.
Ни один из переводов не должен оставить вьюху на дефолтном `AllowAny`.

### 2. Итоговая матрица прав (admin-платформа)

| Раздел (app) | Просмотр (GET) | Операции (POST/PATCH/DELETE) | Класс |
|---|---|---|---|
| Дашборд (`dashboard`) | manager·admin·super | — | `IsManagerOrAdmin` |
| Ученики (`students`) | manager·admin·super | manager·admin·super | `IsManagerOrAdmin` |
| Группы (`groups`) | manager·admin·super | manager·admin·super | `IsManagerOrAdmin` |
| Настройки (`settings_app`) | manager·admin·super | manager·admin·super | `IsManagerOrAdmin` |
| Платежи (`payments`) | manager·admin·super | manager·admin·super | `IsManagerOrAdmin` |
| Scheduling-план (`scheduling`) | manager·admin·super | manager·admin·super | `IsManagerOrAdmin` |
| **Преподаватели** (`teachers`) | manager·admin·super | **super** | `ReadStaffWriteSuperAdmin` |
| **Уроки** (`lessons`) — урок CRUD + посещаемость | manager·admin·super | **admin·super** | `ReadStaffWriteAdmin` |
| **Уроки** — вложенный `payroll` (зарплата за урок) | **только super** | — | стрип в view/сервисе по роли |
| **Направления** (`directions`) | manager·admin·super | **super** | `ReadStaffWriteSuperAdmin` |
| **Абонементы** (`memberships`) | manager·admin·super | **super** | `ReadStaffWriteSuperAdmin` |
| **Скидки** (`discounts`) | manager·admin·super | **super** | `ReadStaffWriteSuperAdmin` |
| **Зарплата** (`payroll`) | **super** | **super** | `IsSuperAdmin` |
| **Учётки** (`accounts`) | **super** | **super** | `IsSuperAdmin` |
| **Журнал ИБ** (`audit`) | **super** | — | `IsSuperAdmin` |
| Журнал изменений — list/detail (`changelog`) | manager·admin·super | — | `IsManagerOrAdmin` |
| Журнал изменений — revert (`changelog`) | — | **admin·super** | `IsAdminOrSuperAdmin` |

Примечание: «Уроки» = приложение `lessons`. Групповой план/календарь (`scheduling`) —
отдельная сущность, в требованиях не фигурирует, остаётся на manager·admin·super.

### 3. Модель учётки (требование 8)

- `Account.Role`: добавить `SUPERADMIN = 'superadmin', 'Суперадминистратор'`.
- Новое поле `full_name = models.CharField(max_length=200, null=True, blank=True)` —
  для аккаунтов manager/admin/superadmin (вводится вручную). У teacher-аккаунтов пустое.
- **Имя — производное, не копия** (во избежание рассинхрона при переименовании преподавателя):
  `name = full_name or teacher_name or email`.
  - `auth_app/services.py:me()` → `full_name or teacher_name or email`.
  - `accounts` list (`repository.list_accounts`) → добавить `full_name` в поля,
    вернуть вычисленный `name` (или `full_name` + `teacher_name`, склейка в сервисе).
  - `accounts` detail (`get_by_id_with_teacher`) уже отдаёт `teacher_name`; добавить `full_name`.
- `is_superadmin` property; обновить `has_role` (без изменений сигнатуры — она уже
  принимает `*roles`).
- pghistory: `full_name` — не секрет, попадает в трекинг автоматически; требуется
  миграция event-модели. Прогнать `test_registry_covers_all_tracked_models`.
- Сериализаторы `AccountCreateSerializer`/`AccountUpdateSerializer`: принимать
  необязательный `full_name`. Для teacher-аккаунтов `full_name` игнорируется/запрещается
  (имя всегда из преподавателя).

### 4. Отключение и удаление учётки (требование 9)

- **Отключить** — обратимый `is_active=false` (существующий `soft_delete`), плюс обратная
  операция «Включить» (`is_active=true`). Инкремент `token_version` при отключении —
  немедленный разлогин. Событие аудита: `account_disabled` / `account_enabled`.
- **Удалить** — новый hard-delete: `DELETE FROM accounts WHERE id=...`. Событие
  `account_deleted` пишется в Журнал ИБ **до** удаления строки. Teacher-аккаунт удаляется,
  сам преподаватель (`teachers.Teacher`) не трогается. Каскады: `AccountInvite`,
  `AccountRecoveryCode` — `on_delete=CASCADE` (проверить FK); pghistory event-строки
  сохраняются (delete-событие).
- Оба жеста — только раздел Учётки (`IsSuperAdmin`). В UI hard-delete — с confirm-модалкой.

### 5. Миграции и данные

Одна миграция в `apps/accounts/migrations`, строгий порядок операций:

1. `AlterConstraint`/remove+add `accounts_role_check` → whitelist
   `['teacher','manager','admin','superadmin']`.
2. `AddField` `full_name`.
3. `RunPython`: forward — `UPDATE accounts SET role='superadmin' WHERE role='admin'`;
   reverse — no-op (или явный `RuntimeError`, т.к. откат промоута небезопасен).
4. Отдельная миграция pghistory event-модели под новое поле `full_name`.

Констрейнт `accounts_teacher_role_check` не меняется (superadmin — не teacher →
`teacher IS NULL`, инвариант держится).

**`bootstrap_admin` command и `admin_exists()`:** обновить — создавать/проверять роль
`superadmin`. Иначе после промоута не останется ни одного `admin`, и следующий bootstrap
создаст «урезанного» админа без доступа к Учёткам (некому управлять доступами).

### 6. Фронт (admin SPA)

- `Me.role` (`AuthProvider.tsx`): тип `'teacher' | 'manager' | 'admin' | 'superadmin'`.
- **Единый capability-модуль** `lib/permissions.ts` — зеркало матрицы §2:
  функции вида `canWriteTeachers(role)` (super), `canWriteDirections(role)` (super),
  `canWriteSubscriptions(role)` (super), `canWriteLessons(role)` (admin·super — CRUD+посещаемость),
  `canSeeLessonPayroll(role)` (super), `canSeePayroll(role)` (super), `canSeeAccounts(role)` (super),
  `canSeeAudit(role)` (super), `canSeeChangelog(role)` (manager·admin·super),
  `canRevertChangelog(role)` (admin·super).
  Никаких разбросанных `role === '...'` по компонентам.
- Route-guard `<RequireRole roles={[...]}>` в `App.tsx` (defense-in-depth поверх бэкенда):
  - `/admin/accounts`, `/admin/audit`, `/admin/payroll` → `superadmin`.
  - `/admin/changelog` → `manager`/`admin`/`superadmin`.
  - При отказе — редирект на `/admin/dashboard`.
- `Sidebar.tsx` / `MobileNav.tsx`: Зарплата → super; Учётки/Журнал ИБ → super;
  Журнал изменений → manager·admin·super.
- Read-only режим (скрыть/дизейблить write-кнопки создать/редактировать/удалить):
  Преподаватели, Направления, Абонементы, Скидки — для не-super.
- **Уроки**: write-кнопки урока (создать/редактировать/удалить) и отметка посещаемости —
  для manager дизейблятся (view-only), для admin/super активны. Секция «Зарплата»
  (`LessonDetailPage`) и payroll-блок в `LessonFormModal` — скрыты для manager и admin,
  видны только super.
- Страница Учётки (`AccountsPage.tsx`): колонка «Имя»; поле `full_name` в форме
  создания/редактирования (только для не-teacher аккаунтов); тумблер Отключить/Включить;
  кнопка Удалить + confirm-модалка. Работа по req 10 (показ пароля) — не делается.
- Журнал изменений: кнопка «Откатить» видна только `admin`/`superadmin`.

### 7. Тестирование

- **Бэкенд (`node`-независимо, pytest):** для каждого затронутого приложения — матрица
  «роль × эндпоинт → HTTP-статус» (расширяем существующие `test_*_api.py`):
  - `teachers/directions/memberships/discounts`: GET → 200 для manager/admin/super;
    POST/PATCH/DELETE → 403 для manager/admin, 2xx для super.
  - `lessons`: GET → 200 для manager/admin/super; POST/PATCH/DELETE урока и
    PATCH attendance-ячейки → 403 для manager, 2xx для admin/super; вложенный
    `payroll` присутствует в ответе только для super (для manager/admin — отсутствует/None).
  - `payroll/accounts/audit`: любой доступ → 403 для manager/admin, 2xx для super.
  - `changelog`: list/detail → 200 для manager/admin/super; revert → 403 для manager,
    2xx для admin/super.
  - Юнит-тесты новых классов `IsSuperAdmin`, `IsAdminOrSuperAdmin`, `ReadStaffWriteSuperAdmin`.
  - Производное имя (`me` и accounts list/detail): full_name / teacher_name / email.
  - Disable → enable → hard-delete; аудит-события; каскады invites/recovery-codes.
  - Data-миграция: после apply `role='admin'` → `superadmin`.
  - `test_registry_covers_all_tracked_models` (новое поле full_name).
- **Фронт:** проект собирается (`vite build`); ручной прогон гейтинга по каждой роли
  (нет инфраструктуры авто-тестов фронта).

## Вне объёма

- Требование 10 (отображение пароля) — закрыто как противоречащее ИБ.
- teacher SPA (`IsTeacher`) — не затрагивается; «доступ ко всему» у superadmin
  трактуется как admin-платформа, не teacher-кабинет (у superadmin нет `teacher_id`).
- Групповое планирование (`scheduling`) — не затрагивается требованиями, права не меняются.

## Затрагиваемые файлы (ориентир)

Бэкенд: `apps/core/permissions.py`, `apps/accounts/{models,serializers,services,repository,views}.py`,
`apps/accounts/migrations/*`, `apps/accounts/management/commands/bootstrap_admin.py`,
`apps/auth_app/{services,serializers}.py`,
вьюхи `apps/{teachers,lessons,directions,memberships,discounts,payroll,audit,changelog}/views.py`,
тесты `apps/*/tests/test_*_api.py`.

Фронт: `frontend/admin-src/src/providers/AuthProvider.tsx`,
`frontend/admin-src/src/lib/permissions.ts` (новый),
`frontend/admin-src/src/App.tsx`,
`frontend/admin-src/src/components/shell/{Sidebar,MobileNav}.tsx`,
страницы `pages/{teachers,lessons,directions,subscriptions,accounts,changelog}/*`.
