# Django Schema Ownership — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести владение схемой PostgreSQL на Django (managed=True + начальные миграции), сохранив текущую схему как baseline и не пересобирая прод.

**Architecture:** Модели приводятся к точной копии реальной БД (типы, CHECK, индексы, UNIQUE) → `makemigrations` генерирует начальные миграции → спецслучаи Django 5.1 (составной PK, DB-level `DEFAULT now()`) патчатся `RunSQL`/`SeparateDatabaseAndState` → на проде `migrate --fake-initial` (без DDL) → корректность доказывается структурным diff'ом scratch-БД против прод-схемы.

**Tech Stack:** Django 5.1.4, DRF, PostgreSQL (psycopg2), pytest (606 тестов), Windows/PowerShell.

---

## Замечания по процессу (отличия от шаблона)

- **Git в проекте нет.** Шаги «commit» заменены на **чекпоинты проверки**: `manage.py check`, `pytest -q` (606), и структурный diff схем. После каждой задачи — зелёная проверка перед переходом к следующей.
- **TDD-адаптация.** «Тест» здесь двухуровневый: (1) **регрессия рантайма** — 606 существующих pytest должны оставаться зелёными (они идут против прод-БД); (2) **тест точности** — структурный diff между свежей Django-собранной БД и прод-схемой должен быть пустым (или только согласованная косметика имён).
- **Команды даны для bash-инструмента** (`cd /c/Users/ilyap/TestKOTOKOD/journal_django && .venv/Scripts/python.exe ...`). Рабочая директория не персистится между вызовами — всегда префикс `cd`.
- **Спецтаблица `lesson_attendance`** (составной PK) и **DB-level `DEFAULT now()`** покрыты в Task 8–9.

## File Structure

**Модели (правка Meta + типы):**
- `apps/teachers/models.py`, `apps/tokens/models.py`, `apps/directions/models.py`, `apps/groups/models.py`, `apps/students/models.py`, `apps/memberships/models.py`, `apps/lessons/models.py`, `apps/payroll/models.py`, `apps/payments/models.py`, `apps/accounts/models.py`, `apps/audit/models.py`, `apps/settings_app/models.py`

**Создаются генерацией (`makemigrations`):**
- `apps/<app>/migrations/__init__.py` + `apps/<app>/migrations/0001_initial.py` для каждого приложения с моделями

**Создаются вручную:**
- `scripts/compare_schema.py` — структурный сравниватель двух БД (Task 0)

**Правка после генерации:**
- `apps/lessons/migrations/0001_initial.py` — `SeparateDatabaseAndState` для `lesson_attendance` (Task 8)
- начальные миграции приложений с `now()`-колонками — `RunSQL` SET DEFAULT (Task 9)

**Доки/тулинг:**
- `docs/deploy-runbook.md`, `package.json`, `db/migrate.js` (комментарий-deprecation)

---

## Task 0: Эталон схемы + сравниватель + scratch-инфраструктура

**Files:**
- Create: `scripts/compare_schema.py`
- Create (артефакт): `reference_schema.sql` (прод-дамп, во временную папку, не коммитим)

- [ ] **Step 1: Снять эталонную схему прод-БД**

Берём `DATABASE_URL` из `.env`. Снимаем структуру (имя БД ниже — `journal`, проверь в `.env`):

Run:
```
cd /c/Users/ilyap/TestKOTOKOD/journal_django && \
  pg_dump --schema-only --no-owner --no-privileges "$DATABASE_URL" -f /tmp/reference_schema.sql && \
  wc -l /tmp/reference_schema.sql
```
Expected: файл создан, сотни строк. Если `pg_dump` не в PATH — использовать полный путь к бинарю PostgreSQL.

- [ ] **Step 2: Написать структурный сравниватель**

Сравнивает две БД по структуре (колонки/типы/nullable/default, CHECK/UNIQUE-определения, индексы), **игнорируя имена** объектов — чтобы Django-имена vs handwritten-имена не давали шум.

Create `scripts/compare_schema.py`:
```python
"""Структурное сравнение двух PostgreSQL-БД (по DSN).

Сравнивает множества: колонки (table,col,type,nullable,default),
CHECK/UNIQUE-определения (нормализованные, без имён), индексы (def без имени).
Печатает только расхождения. Пустой вывод = схемы структурно совпадают.

Usage:
  python scripts/compare_schema.py "<dsn_a>" "<dsn_b>"
"""
import re
import sys
import psycopg2

SKIP_TABLES = {'schema_migrations', 'django_migrations'}


def _norm(s: str) -> str:
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s


def fetch(dsn):
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    # columns
    cur.execute("""
        SELECT table_name, column_name, data_type, is_nullable,
               COALESCE(column_default,''), COALESCE(numeric_precision,0),
               COALESCE(numeric_scale,0), COALESCE(character_maximum_length,0)
        FROM information_schema.columns
        WHERE table_schema='public'
    """)
    cols = {(t, c): (dt, n, _norm(d), p, s, ml)
            for t, c, dt, n, d, p, s, ml in cur.fetchall() if t not in SKIP_TABLES}
    # check + unique constraints (def without name)
    cur.execute("""
        SELECT conrelid::regclass::text, contype, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE connamespace='public'::regnamespace AND contype IN ('c','u','p','f')
    """)
    cons = {}
    for t, ct, d in cur.fetchall():
        if t in SKIP_TABLES:
            continue
        cons.setdefault(t, set()).add((ct, _norm(d)))
    # indexes (def without name)
    cur.execute("""
        SELECT tablename, indexdef FROM pg_indexes WHERE schemaname='public'
    """)
    idx = {}
    for t, d in cur.fetchall():
        if t in SKIP_TABLES:
            continue
        d2 = _norm(re.sub(r'index \S+ on', 'index on', d))
        idx.setdefault(t, set()).add(d2)
    conn.close()
    return cols, cons, idx


def main():
    a, b = sys.argv[1], sys.argv[2]
    ca, cona, ia = fetch(a)
    cb, conb, ib = fetch(b)

    diffs = []
    for key in sorted(set(ca) | set(cb)):
        if ca.get(key) != cb.get(key):
            diffs.append(f'COLUMN {key}: A={ca.get(key)} B={cb.get(key)}')
    for t in sorted(set(cona) | set(conb)):
        only_a = cona.get(t, set()) - conb.get(t, set())
        only_b = conb.get(t, set()) - cona.get(t, set())
        for x in only_a:
            diffs.append(f'CONSTRAINT only in A [{t}]: {x}')
        for x in only_b:
            diffs.append(f'CONSTRAINT only in B [{t}]: {x}')
    for t in sorted(set(ia) | set(ib)):
        only_a = ia.get(t, set()) - ib.get(t, set())
        only_b = ib.get(t, set()) - ia.get(t, set())
        for x in only_a:
            diffs.append(f'INDEX only in A [{t}]: {x}')
        for x in only_b:
            diffs.append(f'INDEX only in B [{t}]: {x}')

    if diffs:
        print('\n'.join(diffs))
        sys.exit(1)
    print('OK: схемы структурно идентичны')


if __name__ == '__main__':
    main()
```

- [ ] **Step 3: Зафиксировать базовую зелёность тестов**

Run: `cd /c/Users/ilyap/TestKOTOKOD/journal_django && .venv/Scripts/python.exe -m pytest -q 2>&1 | tail -3`
Expected: `606 passed`.

---

## Task 1: Даты `CharField(10)` → `DateField`

Безопасно: даты читаются только raw SQL'ом (репозитории + `_normalize_dates`), не через ORM. Меняем тип в 4 файлах (5 полей).

**Files:** Modify `apps/groups/models.py`, `apps/students/models.py`, `apps/memberships/models.py`, `apps/lessons/models.py`

- [ ] **Step 1: groups.group_start_date**

В `apps/groups/models.py` заменить:
```python
    group_start_date = models.CharField(max_length=10, null=True, blank=True)
```
на:
```python
    group_start_date = models.DateField(null=True, blank=True)
```

- [ ] **Step 2: students.birth_date и first_purchase_date**

В `apps/students/models.py` заменить две строки `birth_date = models.CharField(max_length=10, null=True, blank=True)` и `first_purchase_date = models.CharField(max_length=10, null=True, blank=True)` на `models.DateField(null=True, blank=True)` соответственно (комментарии «DATE хранится строкой» убрать).

- [ ] **Step 3: memberships.start_date**

В `apps/memberships/models.py`:
```python
    start_date = models.DateField(null=True, blank=True)
```

- [ ] **Step 4: lessons.lesson_date**

В `apps/lessons/models.py` заменить `lesson_date = models.CharField(max_length=10)` на:
```python
    lesson_date = models.DateField()
```

- [ ] **Step 5: Проверка — модели валидны и тесты зелёные**

Run:
```
cd /c/Users/ilyap/TestKOTOKOD/journal_django && \
  .venv/Scripts/python.exe manage.py check 2>&1 | tail -5 && \
  .venv/Scripts/python.exe -m pytest -q 2>&1 | tail -3
```
Expected: `check` без ошибок; `606 passed` (даты на выдаче по-прежнему строки — рендерер/репозиторий нормализуют `date`-объекты).

---

## Task 2: Простые таблицы → managed=True + индексы

**Files:** Modify `apps/teachers/models.py`, `apps/tokens/models.py`, `apps/settings_app/models.py`, `apps/discounts/models.py`

- [ ] **Step 1: teachers — partial-индекс**

В `apps/teachers/models.py`, класс `Teacher`, заменить `Meta`:
```python
    class Meta:
        managed = True
        db_table = 'teachers'
        indexes = [
            models.Index(
                fields=['active'], name='teachers_active_idx',
                condition=models.Q(active=True),
            ),
        ]
```

- [ ] **Step 2: tokens — только managed=True**

В `apps/tokens/models.py`, `Token.Meta`:
```python
    class Meta:
        managed = True
        db_table = 'tokens'
```

- [ ] **Step 3: settings_app — managed=True**

В `apps/settings_app/models.py`, `AdminUserSettings.Meta`:
```python
    class Meta:
        managed = True
        db_table = 'admin_user_settings'
```

- [ ] **Step 4: discounts — managed=True + плоский индекс**

В `apps/discounts/models.py`, `Discount.Meta`:
```python
    class Meta:
        managed = True
        db_table = 'discounts'
        indexes = [
            models.Index(fields=['active'], name='discounts_active_idx'),
        ]
```

- [ ] **Step 5: Проверка**

Run: `cd /c/Users/ilyap/TestKOTOKOD/journal_django && .venv/Scripts/python.exe manage.py check 2>&1 | tail -5`
Expected: без ошибок (`W342` от `lesson_attendance` допустим — он pre-existing).

---

## Task 3: directions — managed=True + индекс + CHECK

**Files:** Modify `apps/directions/models.py`

- [ ] **Step 1: Meta с индексом и constraint'ами**

`Direction.Meta`:
```python
    class Meta:
        managed = True
        db_table = 'directions'
        indexes = [
            models.Index(
                fields=['active'], name='directions_active_idx',
                condition=models.Q(active=True),
            ),
        ]
        constraints = [
            models.CheckConstraint(
                name='directions_total_lessons_check',
                condition=models.Q(total_lessons__isnull=True) | models.Q(total_lessons__gte=0),
            ),
            models.CheckConstraint(
                name='directions_color_check',
                condition=models.Q(color__isnull=True) | models.Q(color__regex=r'^#[0-9a-fA-F]{6}$'),
            ),
            models.CheckConstraint(
                name='directions_subscription_price_check',
                condition=models.Q(subscription_price__isnull=True) | models.Q(subscription_price__gte=0),
            ),
        ]
```

- [ ] **Step 2: Проверка**

Run: `cd /c/Users/ilyap/TestKOTOKOD/journal_django && .venv/Scripts/python.exe manage.py check 2>&1 | tail -5`
Expected: без новых ошибок.

---

## Task 4: groups + group_schedule_slots

**Files:** Modify `apps/groups/models.py`

- [ ] **Step 1: Group.Meta**
```python
    class Meta:
        managed = True
        db_table = 'groups'
        indexes = [
            models.Index(
                fields=['active'], name='groups_active_idx',
                condition=models.Q(active=True),
            ),
        ]
        constraints = [
            models.CheckConstraint(
                name='groups_lesson_duration_minutes_check',
                condition=models.Q(lesson_duration_minutes__in=[45, 60, 90]),
            ),
            models.CheckConstraint(
                name='groups_lessons_per_week_check',
                condition=models.Q(lessons_per_week__gte=1) & models.Q(lessons_per_week__lte=7),
            ),
        ]
```

- [ ] **Step 2: GroupScheduleSlot.Meta**
```python
    class Meta:
        managed = True
        db_table = 'group_schedule_slots'
        indexes = [
            models.Index(fields=['day_of_week', 'start_time'],
                         name='group_schedule_slots_dow_time_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['group', 'day_of_week', 'start_time'],
                name='group_schedule_slots_group_id_day_of_week_start_time_key',
            ),
            models.CheckConstraint(
                name='group_schedule_slots_day_of_week_check',
                condition=models.Q(day_of_week__gte=0) & models.Q(day_of_week__lte=6),
            ),
        ]
```

- [ ] **Step 3: Проверка**

Run: `cd /c/Users/ilyap/TestKOTOKOD/journal_django && .venv/Scripts/python.exe manage.py check 2>&1 | tail -5`
Expected: без новых ошибок.

---

## Task 5: students

**Files:** Modify `apps/students/models.py`

- [ ] **Step 1: full_name → unique**

Заменить `full_name = models.TextField()` на:
```python
    full_name = models.TextField(unique=True)
```

- [ ] **Step 2: Student.Meta с CHECK'ами**

`Student.Meta` (CHECK'и без NULL-guard — как в реальной БД; NULL проходит CHECK):
```python
    class Meta:
        managed = True
        db_table = 'students'
        constraints = [
            models.CheckConstraint(
                name='students_school_grade_check',
                condition=models.Q(school_grade__gte=1) & models.Q(school_grade__lte=11),
            ),
            models.CheckConstraint(
                name='students_enrollment_status_check',
                condition=models.Q(enrollment_status__in=[
                    'enrolled', 'not_enrolled', 'frozen', 'declined']),
            ),
            models.CheckConstraint(
                name='students_frozen_until_month_check',
                condition=models.Q(frozen_until_month__gte=1) & models.Q(frozen_until_month__lte=12),
            ),
            models.CheckConstraint(
                name='students_check',
                condition=(
                    (models.Q(enrollment_status='frozen') & models.Q(frozen_until_month__isnull=False))
                    | (~models.Q(enrollment_status='frozen') & models.Q(frozen_until_month__isnull=True))
                ),
            ),
        ]
```

- [ ] **Step 3: Проверка**

Run: `cd /c/Users/ilyap/TestKOTOKOD/journal_django && .venv/Scripts/python.exe manage.py check 2>&1 | tail -5`
Expected: без новых ошибок.

---

## Task 6: memberships + payroll

**Files:** Modify `apps/memberships/models.py`, `apps/payroll/models.py`

- [ ] **Step 1: GroupMembership.Meta**
```python
    class Meta:
        managed = True
        db_table = 'group_memberships'
        constraints = [
            models.UniqueConstraint(
                fields=['group', 'student'],
                name='group_memberships_group_id_student_id_key',
            ),
        ]
```

- [ ] **Step 2: Payroll.Meta**
```python
    class Meta:
        managed = True
        db_table = 'payroll'
        indexes = [
            models.Index(fields=['teacher', 'lesson'], name='payroll_teacher_lesson_idx'),
            models.Index(fields=['lesson'], name='payroll_lesson_id_idx'),
        ]
```

- [ ] **Step 3: Проверка**

Run: `cd /c/Users/ilyap/TestKOTOKOD/journal_django && .venv/Scripts/python.exe manage.py check 2>&1 | tail -5`
Expected: без новых ошибок.

---

## Task 7: lessons + payments + accounts + audit

**Files:** Modify `apps/lessons/models.py`, `apps/payments/models.py`, `apps/accounts/models.py`, `apps/audit/models.py`

- [ ] **Step 1: Lesson.Meta**
```python
    class Meta:
        managed = True
        db_table = 'lessons'
        indexes = [
            models.Index(fields=['group', 'lesson_date'], name='lessons_group_date_idx'),
            models.Index(fields=['teacher', 'lesson_date'], name='lessons_teacher_date_idx'),
            models.Index(fields=['-lesson_date', '-id'], name='lessons_date_desc_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['lesson_date', 'group', 'lesson_number', 'submitted_by_token'],
                name='lessons_natural_key',
            ),
        ]
```

- [ ] **Step 2: LessonAttendance.Meta — managed=True + индекс (composite PK патчим в Task 8)**

`LessonAttendance.Meta`:
```python
    class Meta:
        managed = True
        db_table = 'lesson_attendance'
        unique_together = (('lesson', 'student'),)
        indexes = [
            models.Index(fields=['student'], name='lesson_attendance_student_idx'),
        ]
```

- [ ] **Step 3: Payment.Meta**
```python
    class Meta:
        managed = True
        db_table = 'payments'
        indexes = [
            models.Index(fields=['student'], name='payments_student_idx'),
            models.Index(fields=['direction'], name='payments_direction_idx'),
            models.Index(fields=['paid_at'], name='payments_paid_at_idx'),
            models.Index(fields=['-paid_at', '-id'], name='payments_paid_at_desc_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                name='payments_subscriptions_count_check',
                condition=models.Q(subscriptions_count__gt=0),
            ),
            models.CheckConstraint(
                name='payments_unit_price_check',
                condition=models.Q(unit_price__gte=0),
            ),
            models.CheckConstraint(
                name='payments_direction_count_match',
                condition=(
                    (models.Q(direction__isnull=True) & models.Q(subscriptions_count__isnull=True))
                    | (models.Q(direction__isnull=False) & models.Q(subscriptions_count__isnull=False)
                       & models.Q(subscriptions_count__gt=0))
                ),
            ),
            models.CheckConstraint(
                name='payments_total_match',
                condition=(
                    models.Q(subscriptions_count__isnull=True)
                    | models.Q(total_amount=models.F('unit_price') * models.F('subscriptions_count'))
                ),
            ),
        ]
```

- [ ] **Step 4: Account.Meta + AccountRecoveryCode.Meta**

`Account.Meta`:
```python
    class Meta:
        managed = True
        db_table = 'accounts'
        constraints = [
            models.CheckConstraint(
                name='accounts_role_check',
                condition=models.Q(role__in=['teacher', 'manager', 'admin']),
            ),
            models.CheckConstraint(
                name='accounts_twofa_method_check',
                condition=models.Q(twofa_method__isnull=True)
                | models.Q(twofa_method__in=['totp', 'email']),
            ),
            models.CheckConstraint(
                name='accounts_check',
                condition=(
                    (models.Q(role='teacher') & models.Q(teacher__isnull=False))
                    | (~models.Q(role='teacher') & models.Q(teacher__isnull=True))
                ),
            ),
            models.CheckConstraint(
                name='accounts_check1',
                condition=~models.Q(twofa_method='totp') | models.Q(twofa_secret__isnull=False),
            ),
            models.UniqueConstraint(
                fields=['teacher'], name='accounts_teacher_id_uq',
                condition=models.Q(teacher__isnull=False),
            ),
        ]
```
> Примечание: реальный `accounts_twofa_method_check` — `twofa_method = ANY(...)`; при NULL CHECK проходит, поэтому `__isnull=True OR __in=[...]` структурно эквивалентен (сверим в diff на Task 10, при расхождении убрать `isnull`-ветку).

`AccountRecoveryCode.Meta`:
```python
    class Meta:
        managed = True
        db_table = 'account_recovery_codes'
        indexes = [
            models.Index(fields=['account'], name='account_recovery_codes_account_idx'),
        ]
```

- [ ] **Step 5: SecurityAuditLog.Meta + SyncFailure.Meta**

`SecurityAuditLog.Meta`:
```python
    class Meta:
        managed = True
        db_table = 'security_audit_log'
        indexes = [
            models.Index(fields=['-occurred_at'], name='security_audit_log_occurred_idx'),
            models.Index(fields=['account', '-occurred_at'], name='security_audit_log_account_idx'),
        ]
```

`SyncFailure.Meta`:
```python
    class Meta:
        managed = True
        db_table = 'sync_failures'
```

- [ ] **Step 6: Проверка — check + регрессия тестов**

Run:
```
cd /c/Users/ilyap/TestKOTOKOD/journal_django && \
  .venv/Scripts/python.exe manage.py check 2>&1 | tail -5 && \
  .venv/Scripts/python.exe -m pytest -q 2>&1 | tail -3
```
Expected: `check` ок (только `W342`); `606 passed`.

---

## Task 8: Сгенерировать начальные миграции

**Files:** Create `apps/<app>/migrations/__init__.py` + `0001_initial.py` (через `makemigrations`)

- [ ] **Step 1: makemigrations**

Run: `cd /c/Users/ilyap/TestKOTOKOD/journal_django && .venv/Scripts/python.exe manage.py makemigrations 2>&1 | tail -40`
Expected: создаются миграции для teachers, tokens, directions, groups, students, memberships, lessons, payroll, payments, accounts, audit, settings_app. Без ошибок про неразрешённые зависимости (FK-строки `'app.Model'` Django разрулит сам).

- [ ] **Step 2: makemigrations --check показывает чистоту**

Run: `cd /c/Users/ilyap/TestKOTOKOD/journal_django && .venv/Scripts/python.exe manage.py makemigrations --check --dry-run 2>&1 | tail -5`
Expected: `No changes detected` (состояние моделей полностью покрыто миграциями).

- [ ] **Step 3: Регрессия тестов (миграции не должны влиять — django_db_setup no-op)**

Run: `cd /c/Users/ilyap/TestKOTOKOD/journal_django && .venv/Scripts/python.exe -m pytest -q 2>&1 | tail -3`
Expected: `606 passed` (conftest'ы переопределяют `django_db_setup` как no-op → тесты не создают test-БД и не применяют миграции).

---

## Task 9: Патч — составной PK lesson_attendance

Django 5.1 не выражает составной PK. Оборачиваем `CreateModel` для `lesson_attendance` в `SeparateDatabaseAndState`: state остаётся как сгенерировано, БД-сторона создаёт настоящую таблицу через `RunSQL`.

**Files:** Modify `apps/lessons/migrations/0001_initial.py`

- [ ] **Step 1: Найти CreateModel('LessonAttendance')**

Открыть `apps/lessons/migrations/0001_initial.py`, найти операцию `migrations.CreateModel(name='LessonAttendance', ...)` и индекс `lesson_attendance_student_idx` (он может быть отдельной `AddIndex`).

- [ ] **Step 2: Обернуть в SeparateDatabaseAndState**

Заменить `CreateModel('LessonAttendance', ...)` (и связанную `AddIndex` для `lesson_attendance_student_idx`, если она отдельная — перенести её внутрь) на:
```python
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # <-- сюда дословно перенести исходный CreateModel('LessonAttendance', ...)
                #     и AddIndex(model_name='lessonattendance', index=... student_idx ...)
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        CREATE TABLE lesson_attendance (
                          lesson_id  int  NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
                          student_id int  NOT NULL REFERENCES students(id),
                          present    bool NOT NULL,
                          PRIMARY KEY (lesson_id, student_id)
                        );
                        CREATE INDEX lesson_attendance_student_idx
                          ON lesson_attendance (student_id);
                    """,
                    reverse_sql="DROP TABLE lesson_attendance;",
                ),
            ],
        ),
```
> В `state_operations` кладётся НЕизменённый исходный `CreateModel`/`AddIndex` (Django хранит «как будто обычная таблица»); реальный DDL берётся из `database_operations`.

- [ ] **Step 3: Проверка состояния и тестов**

Run:
```
cd /c/Users/ilyap/TestKOTOKOD/journal_django && \
  .venv/Scripts/python.exe manage.py makemigrations --check --dry-run 2>&1 | tail -5 && \
  .venv/Scripts/python.exe -m pytest -q 2>&1 | tail -3
```
Expected: `No changes detected`; `606 passed`.

---

## Task 10: Патч — DB-level DEFAULT now()

Django держит `now()` на уровне Python; на свежей БД колонки не получат DB-дефолт, на который полагаются Node-инструменты. Добавляем `RunSQL` SET DEFAULT в начальную миграцию **каждого** приложения с такими колонками.

**Files:** Modify начальные миграции: teachers, tokens, groups, students, discounts, payments, accounts, lessons, audit, settings_app

Колонки с `DEFAULT now()`: `teachers.created_at`, `tokens.created_at`, `groups.created_at`, `students.created_at`, `discounts.created_at`, `payments.created_at`, `accounts.created_at`, `lessons.submitted_at`, `security_audit_log.occurred_at`, `sync_failures.occurred_at`, `admin_user_settings.updated_at`.

- [ ] **Step 1: Добавить RunSQL в конец `operations` каждой такой миграции**

Пример для `apps/teachers/migrations/0001_initial.py` — в конец списка `operations`:
```python
        migrations.RunSQL(
            sql="ALTER TABLE teachers ALTER COLUMN created_at SET DEFAULT now();",
            reverse_sql="ALTER TABLE teachers ALTER COLUMN created_at DROP DEFAULT;",
        ),
```
Аналогично:
- `tokens`: `ALTER TABLE tokens ALTER COLUMN created_at SET DEFAULT now();`
- `groups`: `groups.created_at`
- `students`: `students.created_at`
- `discounts`: `discounts.created_at`
- `payments`: `payments.created_at`
- `accounts`: `accounts.created_at`
- `lessons`: `ALTER TABLE lessons ALTER COLUMN submitted_at SET DEFAULT now();`
- `audit` (2 колонки): `security_audit_log.occurred_at` и `sync_failures.occurred_at`
- `settings_app`: `ALTER TABLE admin_user_settings ALTER COLUMN updated_at SET DEFAULT now();`

- [ ] **Step 2: Проверка состояния (RunSQL не влияет на state) + тесты**

Run:
```
cd /c/Users/ilyap/TestKOTOKOD/journal_django && \
  .venv/Scripts/python.exe manage.py makemigrations --check --dry-run 2>&1 | tail -5 && \
  .venv/Scripts/python.exe -m pytest -q 2>&1 | tail -3
```
Expected: `No changes detected`; `606 passed`.

---

## Task 11: Валидация на scratch-БД (итеративный diff)

Доказываем: свежая БД, собранная Django-миграциями, структурно идентична проду.

- [ ] **Step 1: Создать пустую scratch-БД**

Run: `createdb journal_scratch_django` (или `psql "$DATABASE_URL" -c "CREATE DATABASE journal_scratch_django;"` с правкой имени БД в DSN).

- [ ] **Step 2: Прогнать миграции с нуля**

Сформировать DSN на scratch-БД (та же связка кред, другое имя), например `SCRATCH_DSN`. Запустить:
```
cd /c/Users/ilyap/TestKOTOKOD/journal_django && \
  DATABASE_URL="$SCRATCH_DSN" .venv/Scripts/python.exe manage.py migrate 2>&1 | tail -30
```
Expected: все миграции применяются без ошибок (`Applying <app>.0001_initial... OK`).

- [ ] **Step 3: Структурный diff прод vs scratch**

Run:
```
cd /c/Users/ilyap/TestKOTOKOD/journal_django && \
  .venv/Scripts/python.exe ../scripts/compare_schema.py "$DATABASE_URL" "$SCRATCH_DSN" 2>&1 | tail -60
```
Expected (цель): `OK: схемы структурно идентичны`.

- [ ] **Step 4: Реконсиляция расхождений (цикл)**

Для каждой строки вывода:
- **COLUMN ...** (тип/nullable/default отличается) → поправить поле модели или `RunSQL`-дефолт; пересоздать scratch (`dropdb journal_scratch_django && createdb ...`), повторить Step 2–3.
- **CONSTRAINT only in A/B** — если различается только нормализованное определение (не имя) → поправить `CheckConstraint`/`UniqueConstraint`. (Имена сравниватель уже игнорирует.)
- **INDEX only in A/B** → поправить `Meta.indexes` (partial-условие, порядок DESC, набор колонок).

Повторять Step 1–3 до пустого diff. Ожидаемые «упрямые» места: `payments`-чеки (4 шт.), `accounts_check/check1` (логические выражения), partial-индексы `*_active_idx`, DESC-индексы.

- [ ] **Step 5: Снести scratch-БД**

Run: `dropdb journal_scratch_django`

---

## Task 12: Cutover на проде (--fake-initial)

Существующая прод-БД уже содержит все таблицы → применяем миграции как «уже выполненные», без DDL.

- [ ] **Step 1: Снять контрольный дамп схемы ДО**

Run: `cd /c/Users/ilyap/TestKOTOKOD/journal_django && pg_dump --schema-only --no-owner --no-privileges "$DATABASE_URL" -f /tmp/prod_before.sql`

- [ ] **Step 2: migrate --fake-initial**

Run: `cd /c/Users/ilyap/TestKOTOKOD/journal_django && .venv/Scripts/python.exe manage.py migrate --fake-initial 2>&1 | tail -30`
Expected: каждая `0001_initial` помечается `FAKED` (таблицы существуют → DDL не выполняется). Создаётся служебная таблица `django_migrations` (ожидаемо, сосуществует с Node'овой `schema_migrations`).

- [ ] **Step 3: Подтвердить, что схема прода НЕ изменилась**

Run:
```
cd /c/Users/ilyap/TestKOTOKOD/journal_django && \
  pg_dump --schema-only --no-owner --no-privileges "$DATABASE_URL" -f /tmp/prod_after.sql && \
  diff /tmp/prod_before.sql /tmp/prod_after.sql
```
Expected: единственное отличие — появление таблицы `django_migrations` (и её sequence). Прикладные таблицы без изменений.

- [ ] **Step 4: Регрессия — 606 тестов против прод-БД**

Run: `cd /c/Users/ilyap/TestKOTOKOD/journal_django && .venv/Scripts/python.exe -m pytest -q 2>&1 | tail -3`
Expected: `606 passed`.

- [ ] **Step 5: Проверить, что система видит миграции применёнными**

Run: `cd /c/Users/ilyap/TestKOTOKOD/journal_django && .venv/Scripts/python.exe manage.py showmigrations 2>&1 | tail -40`
Expected: все `0001_initial` отмечены `[X]`.

---

## Task 13: Доки и тулинг

**Files:** Modify `docs/deploy-runbook.md`, `package.json`, `db/migrate.js`

- [ ] **Step 1: deploy-runbook — провижининг через Django**

В `docs/deploy-runbook.md` рядом с шагом `npm run db:migrate` (строка ~99) добавить раздел: свежая БД — `python manage.py migrate`; разовый переход существующей БД — `python manage.py migrate --fake-initial`. Пометить `npm run db:migrate` как устаревший для новых установок.

- [ ] **Step 2: db/migrate.js — deprecation-шапка**

В начало `db/migrate.js` добавить комментарий:
```js
// DEPRECATED для провижининга свежей БД: владелец схемы — Django
// (journal_django, manage.py migrate). Этот скрипт оставлен как историческая
// справка и для обслуживания существующих SQL-инсталляций. См.
// docs/superpowers/specs/2026-06-11-django-schema-ownership-design.md
```

- [ ] **Step 3: package.json — пометить канонический путь**

В `package.json` рядом со скриптом `db:migrate` отразить (через соседний `db:migrate:note` или комментарий в docs), что канонический путь миграций схемы — Django. (JSON не поддерживает комментарии — при отсутствии места просто оставить запись в runbook; правка package.json опциональна.)

- [ ] **Step 4: Финальная проверка**

Run:
```
cd /c/Users/ilyap/TestKOTOKOD/journal_django && \
  .venv/Scripts/python.exe manage.py check 2>&1 | tail -5 && \
  .venv/Scripts/python.exe manage.py makemigrations --check --dry-run 2>&1 | tail -3 && \
  .venv/Scripts/python.exe -m pytest -q 2>&1 | tail -3
```
Expected: `check` ок; `No changes detected`; `606 passed`.

---

## Definition of Done

- [ ] Все модели `managed=True` (lesson_attendance — через `SeparateDatabaseAndState`).
- [ ] Начальные Django-миграции существуют; `makemigrations --check` → `No changes detected`.
- [ ] Структурный diff scratch-БД (Django migrate) против прода — пустой (Task 11 Step 3 = `OK`).
- [ ] Прод переведён `--fake-initial`; схема прикладных таблиц не изменилась; `showmigrations` всё `[X]`.
- [ ] 606 pytest зелёные на каждом чекпоинте.
- [ ] Runbook/тулинг отражают, что владелец схемы — Django.
```
