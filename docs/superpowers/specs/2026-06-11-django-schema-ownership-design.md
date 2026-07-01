# Django как владелец схемы БД — дизайн

**Дата:** 2026-06-11
**Статус:** утверждён к реализации
**Контекст:** `journal_django/` (Django 5.1.4 + DRF, PostgreSQL)

## Проблема

Сейчас схемой БД владеет raw SQL в `db/migrations/001…015.sql` (применяется Node-скриптом `db/migrate.js`, ведёт таблицу `schema_migrations`). Все Django-модели объявлены `managed = False`, Django-миграций в проекте нет вообще (`manage.py migrate` не используется). Django умеет только читать/писать данные, но не описывает и не создаёт схему.

Цель: перевести владение схемой на Django, чтобы **будущие** изменения схемы вести через `manage.py makemigrations` / `migrate`. Текущую схему сохраняем как baseline.

## Решения (зафиксированы с заказчиком)

1. **Цель — baseline сейчас + будущие изменения через Django.** Прод не пересобираем, `db/` не удаляем.
2. **Валидация — scratch-БД + diff схем.** 606 существующих тестов не трогаем (продолжают идти против прода).
3. Начальная Django-миграция должна точно отражать реальную БД — иначе будущие `makemigrations` сгенерируют неверный DDL.

## Подход

**A (основной): сгенерированная начальная миграция + `--fake-initial` + проверка scratch-БД.**
Модели приводятся к точной копии реальной схемы → `makemigrations` генерирует начальные миграции → на проде `migrate --fake-initial` (Django помечает миграцию применённой без DDL) → точность доказывается diff'ом схем на scratch-БД.

**B (точечно): ручной `RunSQL` через `SeparateDatabaseAndState`** — только для объектов, которые Django 5.1 не выражает (составной PK, DB-level дефолты).

**C (отклонён): пустой baseline без constraints** — состояние миграций разойдётся с реальностью, будущие миграции станут опасны.

## Изменения в моделях (Фаза 1)

Состояние миграций строится из моделей, поэтому модели обязаны точно описывать реальную БД.

### Типы дат: `CharField(10)` → `DateField`
Затронуты: `groups.group_start_date`, `students.birth_date`, `students.first_purchase_date`, `memberships.start_date`, `lessons.lesson_date`.
Безопасно в рантайме: даты нигде не читаются через ORM — репозитории идут raw SQL + `_normalize_dates()` (date → 'YYYY-MM-DD'), `DateSafeJSONRenderer` выдаёт строку. Инвариант «дата как строка на выдаче» сохраняется; меняется только тип в описании модели и в генерируемой схеме (реальная колонка и так `date`).

### CHECK → `Meta.constraints` (`CheckConstraint`)
- `groups`: `lesson_duration_minutes IN (45,60,90)`; `lessons_per_week BETWEEN 1 AND 7`
- `group_schedule_slots`: `day_of_week BETWEEN 0 AND 6`
- `students`: `school_grade BETWEEN 1 AND 11`; `enrollment_status IN (...)`; `frozen_until_month BETWEEN 1 AND 12`; `(enrollment_status='frozen') = (frozen_until_month IS NOT NULL)`
- `directions`: `total_lessons >= 0` (или NULL); `color ~ '^#[0-9a-fA-F]{6}$'` (или NULL); `subscription_price >= 0` (или NULL)
- `payments`: `subscriptions_count > 0` (когда не NULL); `unit_price >= 0`; `total_amount = unit_price*subscriptions_count` (когда count не NULL); `direction_id↔subscriptions_count` равенство NULL
- `discounts`: `amount BETWEEN 0 AND 1`
- `accounts`: `role IN ('teacher','manager','admin')`; `twofa_method IN ('totp','email')`; `(role='teacher') = (teacher_id IS NOT NULL)`; `twofa_method<>'totp' OR twofa_secret IS NOT NULL`

### Индексы → `Meta.indexes`
Все некключевые индексы из миграций: partial (`WHERE active=true`) через `condition=Q(active=True)`; DESC через нисходящий порядок (`F('x').desc()` / `Index(..., order_by)`); составные — обычным перечислением полей.

### UNIQUE
- `students.full_name` → `unique=True` (миграция 002, сейчас отсутствует)
- Составные `UniqueConstraint`: `group_schedule_slots(group, day_of_week, start_time)`; `group_memberships(group, student)`; `lessons(lesson_date, group, lesson_number, submitted_by_token)` (natural key)
- Partial unique `accounts.teacher` → `UniqueConstraint(fields=['teacher'], condition=Q(teacher__isnull=False))`
- Уже отражены: `teachers.name`, `directions.name`, `groups.name`, `accounts.email` (`unique=True`), `payroll.lesson` (`OneToOneField`)

### `managed = True`
На всех моделях, кроме спецслучая `lesson_attendance`.

## Спецслучаи Django 5.1 (Фаза 2)

### `lesson_attendance` — составной PK
Реальный PK — `(lesson_id, student_id)`, без surrogate `id`. Нативный `CompositePrimaryKey` появился только в Django 5.2. Решение: в начальной миграции через `SeparateDatabaseAndState` — БД-сторона `RunSQL` создаёт таблицу с настоящим композитным PK, state-сторона — модель в текущем виде (`lesson` как `primary_key=True` + `unique_together`), которую Django отслеживает для будущих диффов.

### DB-level `DEFAULT now()`
`created_at`/`occurred_at`/`updated_at` в реальной БД имеют `DEFAULT now()` на уровне колонки. Django держит `now()` на уровне Python (`default=timezone.now`), DDL-дефолт не ставит. Node-инструменты вставляют строки и полагаются на дефолт БД. Решение: добавить `ALTER TABLE ... ALTER COLUMN ... SET DEFAULT now()` через `RunSQL` в начальной миграции для всех таких колонок.

## Применение на проде (Фаза 3)

`python manage.py migrate --fake-initial` на существующей наполненной БД: Django обнаруживает, что таблицы уже есть, помечает начальную миграцию применённой и **не выполняет DDL**. Нулевой риск для данных. (Альтернатива при необходимости — `migrate <app> --fake`.)

## Валидация (Фаза 4)

1. Создать scratch-БД `journal_scratch_django`, прогнать `manage.py migrate` с нуля, снять `pg_dump --schema-only`.
2. Создать вторую scratch-БД `journal_scratch_sql`, прогнать `db/migrate.js`, снять `pg_dump --schema-only`.
3. Сделать diff двух дампов. Итеративно править модели/начальную миграцию, пока расхождения не исчезнут или не останутся только косметические (имена индексов/constraint'ов), согласованные явно.
4. 606 тестов не трогаем — они продолжают идти против прода и служат регрессией на рантайм-поведение.

## Тулинг и доки (Фаза 5)

- `db/` оставляем: исторический источник + backfill-инструменты (`scripts/`) не затронуты.
- `db/migrate.js` помечаем устаревшим для провижининга свежей БД.
- `docs/deploy-runbook.md`: свежая БД → `manage.py migrate`; существующая (разовый cutover) → `migrate --fake-initial`.
- `package.json`: `db:migrate` оставляем, но помечаем, что канонический путь теперь Django.

## Вне объёма (YAGNI)

- Перевод 606 тестов на Django-управляемую test-БД (отдельный проект).
- Удаление `db/` и Node-тулинга.
- Любые изменения самой схемы (только перенос владения, не модификация).

## Риски

- **Diff на Фазе 4 вскроет много мелких различий** (именование constraint'ов/индексов Django vs handwritten, обработка дефолтов, identity vs serial). Каждое расхождение разбираем индивидуально: правим модель/миграцию (предпочтительно) или сознательно принимаем как косметику. Это основной, итеративный объём работы.
- **Ошибка в `--fake-initial`** (например, применение без `--fake` на проде) попыталась бы создать существующие таблицы → падение. Митигируется строгим порядком в runbook и проверкой на scratch-БД до прода.
- **Расхождение state↔реальность по непокрытому объекту** → будущая миграция сгенерирует неверный DDL. Митигируется требованием пустого diff на Фазе 4.
