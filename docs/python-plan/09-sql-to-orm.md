# 09 — Перевод сырого SQL на Django ORM

> План-инструкция. Цель: убрать сырой SQL из всех `apps/*/repository.py`, заменив
> его на ORM-запросы, **без изменения контракта ответа** (байт-в-байт паритет с
> admin SPA и с эталонным Express, проверяемый `scripts/diff_express.py`).

## 0. Краткий итог анализа

Проанализированы все 15 `repository.py` (+ `apps/teacher_spa/services.py`) в
`journal_django/apps/`. Всего ~3735 строк, ~106 вызовов `cursor.execute`,
~88 ручных `_dictfetch*`.

**Хорошие новости (почему миграция реалистична):**

1. **Модели уже описаны полностью.** В каждом app есть `models.py` с
   `managed=True`, явным `db_table`, всеми FK (`related_name`, `db_column`),
   индексами и `CheckConstraint`. ORM-цель уже существует — писать модели с нуля
   не нужно. Покрыты все таблицы: `groups`, `group_schedule_slots`, `directions`,
   `teachers`, `students`, `lessons`, `lesson_attendance`, `payroll`, `payments`,
   `group_memberships`, `admin_user_settings`, `accounts`,
   `account_recovery_codes`, `security_audit_log`, `sync_failures`, `tokens`,
   `discounts`.
2. **Контракт репозиториев — `dict` / `list[dict]`.** Сейчас через
   `_dictfetchall`. ORM `.values()` / `.values_list()` тоже отдаёт `dict` —
   значит можно сохранить тот же контракт и **не трогать `services.py`,
   `serializers.py`, `views.py`**.
3. **Типы добивает renderer.** `apps/core/renderers.py::DateSafeJSONRenderer`
   уже приводит `date → 'YYYY-MM-DD'`, `datetime → ISO 'Z'`, `Decimal → str`.
   ORM возвращает ровно эти Python-типы (`datetime.date`, `Decimal`), поэтому
   паритет проводки сохраняется автоматически.
4. **Сеть безопасности готова.** ~600 pytest-тестов (`test_*_repository.py` +
   `test_*_api.py` на каждый app) + три diff-скрипта
   (`scripts/diff_express.py`, `diff_auth.py`, `diff_teacher.py`) для байт-сверки
   с Express. Это и есть критерий приёмки каждого шага.

**Что усложняет:** часть запросов использует конструкции, которые ORM выражает
неочевидно или не выражает вовсе (см. §3 — классификация и §4 — «кулинарная
книга»).

## 1. Принципы и границы (guardrails)

1. **Паритет важнее «чистоты».** Если ORM-вариант хоть в одном байте расходится
   с Express — он неверен. Единственное узаконенное расхождение —
   FIFO-копейки (см. память `project_fifo_decimal_decision`); его границы не
   расширяем. `apps/finances/fifo.py` — чистый Python, SQL там нет, **не трогаем**.
2. **Repository остаётся единственным домом доступа к данным.** Мы меняем
   *реализацию* функций внутри `repository.py`, но не их сигнатуры и не место.
   Слои `controller → service → repository` сохраняются (память
   `feedback_clean_patterns_plain_language`).
3. **Тот же тип возврата.** Функция, отдававшая `list[dict]`, продолжает отдавать
   `list[dict]` (через `.values()`), отдававшая `dict|None` — `dict|None`,
   `bool` — `bool`, `int` — `int`. Никаких «голых» model-инстансов наружу, иначе
   поедет форма JSON.
4. **Пошагово, один app за коммит** (память `feedback_careful_incremental_refactor`):
   переписали → `pytest apps/<app>` зелёный → `diff_express.py` по эндпоинтам
   раздела чист → следующий. Git нет — поэтому верификация после **каждого**
   файла обязательна, отката не будет.
5. **Сырой SQL допустим точечно.** Где ORM-перевод даёт риск расхождения или
   нечитаемую конструкцию (`json_agg` объектов, MSK-CTE) — оставляем
   `cursor.execute` либо `RawSQL`-аннотацию и помечаем `# ORM-EXCEPTION: <причина>`.
   Цель — «минимум сырого SQL», а не «ноль любой ценой».

## 2. Подготовка (один раз, до переписывания)

1. **Зафиксировать эталон.** Поднять Express (:3000) и Django (:8000) на общей БД,
   прогнать `python scripts/diff_express.py` / `diff_auth.py` / `diff_teacher.py`,
   убедиться, что ДО начала работ diff чист (кроме известных FIFO-ячеек). Это
   базовая линия.
2. **Проверить, что модели реально соответствуют таблицам.** `managed=True`
   означает, что Django считает себя владельцем схемы. Перед стартом —
   `python manage.py makemigrations --check --dry-run`: не должно быть «лишних»
   изменений (иначе модель разошлась с БД и ORM-запрос соберёт неверный SQL).
   Если расхождения есть — сначала выровнять `models.py` под фактическую схему
   (`db/migrations/001..015.sql`), не наоборот.
3. **Завести общий тонкий helper** на время переходного периода в
   `apps/core/utils/` — `dictrows(queryset) -> list[dict]` и
   `dictrow(queryset) -> dict|None`, чтобы единообразно отдавать `.values()` и
   точечно постобрабатывать (например, `_js_number`). Убирает дубль
   `_dictfetch*` из 15 файлов.

## 3. Классификация репозиториев по сложности

### Tier 1 — тривиальные CRUD (начать отсюда)
`settings_app`, `directions`, `teachers`, `discounts`, `tokens`.

Простые `SELECT/INSERT/UPDATE/DELETE` по одной таблице, пагинация по одной
таблице без JOIN, мягкое удаление. Прямой маппинг на
`Model.objects.filter().values()`, `.create()`, `.update()`, `update_or_create()`.
`settings_app` — единственный upsert (`ON CONFLICT`) → `update_or_create()`.

### Tier 2 — пагинация с JOIN + PATCH-семантика
`accounts`, `groups`, `lessons`, `memberships`, `payments`, `payroll`, `audit`.

- Списки с JOIN на справочники (`direction_name`, `teacher_name`, `student_name`)
  → `select_related` + `.annotate(...).values(...)` либо `.values('fk__name')`.
- PATCH через `COALESCE(%s, col)` → в ORM чище: загрузить инстанс, выставить
  только переданные поля, `save(update_fields=[...])` (см. §4.4).
- Транзакции (`groups.create_group` слоты, `lessons.*` пересчёт `lessons_done`,
  `payments.create_payment` с `FOR UPDATE`) → `transaction.atomic()` +
  `select_for_update()` + `bulk_create`.
- `groups` содержит `json_agg` слотов — **гибрид** (см. §4.6): мета через ORM,
  слоты дособрать в Python из `prefetch_related`, либо оставить `RawSQL`.
- `payments` immutable (только POST/DELETE) — следить, чтобы не появился `.save()`
  на UPDATE.

### Tier 3 — аналитика, делать последними и осторожно
`students` (`student_stats` — CTE + `FILTER` + MSK), `finances`
(`student_balance_rows` CTE, `balance_for_direction`, `fifo_inputs`), `dashboard`
(`UNION`, `EXTRACT`, `date_trunc`), `teacher_spa` (CTE/`unnest`).

Здесь либо сложная условная агрегация, либо MSK-таймзона, либо денежная точность.
Допустимо оставить сырой SQL/`RawSQL`, если ORM-перевод увеличивает риск
расхождения. Решение по каждому запросу — отдельно, с diff-проверкой.

## 4. Кулинарная книга переводов (SQL → ORM)

Конкретные паттерны, встречающиеся в коде, и их ORM-эквиваленты.

### 4.1 SELECT * + dict-ряды
```python
# Было:
cur.execute('SELECT * FROM students WHERE id = %s', [sid]); _dictfetchone(cur)
# Стало:
Student.objects.filter(id=sid).values().first()   # dict|None, все поля модели
```
`.values()` без аргументов возвращает все конкретные поля → эквивалент `SELECT *`.

### 4.2 Список с JOIN-алиасами
```python
# Было: SELECT a.*, t.name AS teacher_name FROM accounts a LEFT JOIN teachers t ...
Account.objects.values(
    'id', 'email', 'role', 'teacher_id', 'active', 'twofa_enabled',
    'twofa_method', 'last_login_at',
    teacher_name=F('teacher__name'),     # алиас = LEFT JOIN + AS
)
```
`LEFT JOIN` получается автоматически, т.к. FK `null=True`/`values('fk__field')`.

### 4.3 Пагинация `{rows,total,page,page_size}`
Контракт обязателен (admin SPA). Сохраняем форму вручную:
```python
qs = Model.objects.filter(**flt).order_by(sort_col, '-id')   # вторичный сорт id DESC
total = qs.count()                                            # COUNT(*) без LIMIT
rows = list(qs[(page-1)*page_size : (page-1)*page_size + page_size].values(...))
return {'rows': rows, 'total': total, 'page': page, 'page_size': page_size}
```
Whitelist `sort_by` оставить как сейчас (мапа ключ→поле) — это и защита от
инъекций, и контракт «тихого fallback» Express (без 400). `ASC/DESC` →
префикс `-` в `order_by`. `count()` по упрощённому QS без JOIN/annotate (как
`countFrom` сейчас).

### 4.4 PATCH через COALESCE
```python
# Было: UPDATE ... SET name = COALESCE(%s, name), ... WHERE id=%s RETURNING *
obj = Model.objects.filter(id=pk).first()
if obj is None: return None
for field in ('name', 'direction_id', ...):
    if field in data and data[field] is not None:   # повторить семантику "?? null"
        setattr(obj, field, data[field])
obj.save(update_fields=[...])
return Model.objects.filter(id=pk).values().first()
```
⚠️ Тонкости, которые легко сломать (есть в текущем коде):
- `is_individual`/`active` могут быть `False` — различать «нет ключа» и `False`
  (sentinel), как сейчас в `groups.update_group`.
- `frozen_until_month` в `students.update_student` перезаписывается **всегда**
  (включая `NULL`-сброс) — это НЕ COALESCE-поле.
- `NULLIF(%s,'')` (пустая строка → старое значение) — повторить: пустую строку
  трактовать как «не передано».
- `original_teacher_id` в `lessons.update_lesson` — `CASE WHEN has_original` —
  различать «не передано» и «явный null».

### 4.5 INSERT ... RETURNING *
```python
obj = Model.objects.create(**fields)        # RETURNING * → инстанс
return Model.objects.filter(pk=obj.pk).values().first()   # назад в dict
```
`NULLIF(%s,'')`, `COALESCE(%s,'enrolled')` (дефолты) — повторить в Python до
`create()`.

### 4.6 json_agg / json_build_object (только `groups`)
`json_agg(json_build_object('day_of_week', ..., 'start_time', ...) ORDER BY ... )
FILTER (WHERE ...)` — у ORM нет прямого построителя JSON-объекта.
Две опции (выбрать по diff-результату):
1. **Python-сборка (рекомендуется для читаемости):** забрать группы через ORM,
   слоты — `prefetch_related('schedule_slots')`, собрать список словарей слотов
   в Python в нужном порядке. Внимание: `start_time::text` — формат времени
   должен совпасть (`'HH:MM:SS'`).
2. **`RawSQL`-аннотация:** оставить ровно это под-выражение `json_agg(...)` как
   `annotate(slots=RawSQL(...))`. Минимальный сырой SQL, гарантированный паритет.
   Пометить `# ORM-EXCEPTION: json_agg ordered+filtered`.

### 4.7 Условная агрегация + FILTER (`students.student_stats`)
`COUNT(...) FILTER (WHERE present)`, `SUM(CASE WHEN duration=45 THEN 0.5 ELSE 1)`:
```python
from django.db.models import Count, Sum, Case, When, Value, Q, DecimalField
.annotate(
    attended=Count('id', filter=Q(present=True)),
    units=Sum(Case(When(lesson__lesson_duration_minutes=45, then=Value(Decimal('0.5'))),
                   default=Value(Decimal('1')), output_field=DecimalField())),
)
```
DRF/ORM поддерживает `filter=` на агрегатах. Пост-обработка (`_js_round`,
сборка по направлениям) уже в Python — её **не трогаем**, меняем только источник
строк. ⚠️ MSK-границы месяца (`now() AT TIME ZONE 'Europe/Moscow'`) считать в
Python через `zoneinfo` (как `services/calculator.py`/`apps/.../calculator`) и
передавать готовые даты — точнее и без таймзонных сюрпризов в SQL.

### 4.8 CTE (`students.student_stats`, `finances.student_balance_rows`)
Django 4.2 без нативного CTE. Варианты:
- Переписать `WITH paid AS (...), attended AS (...)` как **отдельные
  агрегирующие запросы** + сборка по `direction_id` в Python (для `≤ сотен`
  направлений на ученика — дёшево). Это и есть «вывод, не хранение» баланса.
- Либо оставить как `cursor.execute` (Tier 3, допустимо).
Не тащить `django-cte` ради двух запросов без явной нужды.

### 4.9 Upsert `ON CONFLICT` (`settings_app`, `memberships`, `lessons`, `teacher_spa`)
```python
AdminUserSettings.objects.update_or_create(
    username=username, defaults={'settings': data, 'updated_at': now()})
```
Для bulk-upsert (Django 4.1+):
`bulk_create(objs, update_conflicts=True, unique_fields=[...], update_fields=[...])`.
`lesson_attendance` (`ON CONFLICT (lesson_id, student_id) DO UPDATE present`) —
именно так. `DO NOTHING` → `ignore_conflicts=True`.

### 4.10 SELECT ... FOR UPDATE (`payments.create_payment`)
```python
with transaction.atomic():
    d = Direction.objects.select_for_update().filter(id=did).values('id','total_lessons').first()
    already = Payment.objects.filter(student_id=sid, direction_id=did)\
                 .aggregate(s=Coalesce(Sum('subscriptions_count'), 0))['s']
    ...
    price = round_kopecks(unit_price); total = price * subscriptions_count
    p = Payment.objects.create(...)
```
⚠️ Сохранить порядок: лок direction → подсчёт already под локом → проверка cap →
INSERT. `unit_price` округлять до копеек **до** умножения (инвариант БД + сервер).

### 4.11 bulk INSERT через unnest (`lessons`, `teacher_spa`)
`INSERT ... SELECT FROM unnest(%s::int[], %s::bool[]) JOIN students` → проверка
существования студентов + массовая вставка:
```python
valid = set(Student.objects.filter(id__in=sids).values_list('id', flat=True))
LessonAttendance.objects.bulk_create(
    [LessonAttendance(lesson_id=lid, student_id=s, present=p)
     for s, p in zip(sids, pres) if s in valid],
    ignore_conflicts=True)        # = ON CONFLICT DO NOTHING
```
Затем инкремент `lessons_done` (см. 4.12). Транзакция — общая.

### 4.12 Атомарный инкремент (`lessons.*`, half-lesson инвариант)
`UPDATE group_memberships SET lessons_done = lessons_done + %s WHERE ...`:
```python
from django.db.models import F
GroupMembership.objects.filter(group_id=gid, student_id__in=present_sids)\
    .update(lessons_done=F('lessons_done') + step)
# GREATEST(x,0) при откате:
.update(lessons_done=Greatest(F('lessons_done') - step, Value(0)))
```
`step = 0.5 if duration == 45 else 1` — **критичный half-lesson инвариант**,
повторить дословно. Дельта-логика toggle (`prev_present` × `next`) — оставить в
Python, менять только способ чтения/записи.

### 4.13 `= ANY(%s)` → `__in`
```python
Student.objects.filter(id__in=ids).values_list('id', 'full_name')  # dict/tuple
```

### 4.14 EXTRACT / date_trunc / UNION (`dashboard`)
```python
from django.db.models.functions import ExtractYear, ExtractMonth, TruncMonth
# DISTINCT годы из двух таблиц:
y1 = Payment.objects.annotate(yy=ExtractYear('paid_at')).values_list('yy', flat=True)
y2 = Lesson.objects.annotate(yy=ExtractYear('lesson_date')).values_list('yy', flat=True)
years = sorted({y for y in set(y1).union(set(y2)) if y is not None})
# revenue по месяцам:
Payment.objects.filter(paid_at__gte=a, paid_at__lt=b)\
    .annotate(yy=ExtractYear('paid_at'), m=ExtractMonth('paid_at'))\
    .values('yy','m').annotate(rev=Coalesce(Sum('total_amount'), Value(0)))
```
⚠️ Полуинтервалы `[start, end)` (`paid_at < period_end`) — сохранить `__lt`,
не `__lte`.

### 4.15 Денежные суммы (`finances`, `payments`)
`SUM(...)::numeric` → `aggregate(Sum(...))` возвращает `Decimal` — то, что нужно.
`COALESCE(...,0)` → `Coalesce(Sum(...), Value(Decimal('0')))`. Числовые поля
баланса (`purchased/attended/balance/total_paid`) **по-прежнему** прогонять через
`_js_number()` (Decimal('8.0')→8, Decimal('7.5')→7.5) — это часть контракта,
ORM сам так не делает.

## 5. Инварианты, которые легко сломать (чек-лист на каждый PR)

- [ ] **half-lesson:** `duration==45 → 0.5`, иначе 1 — в `lessons`, `memberships`,
      `teacher_spa`, `finances` (память `project_conventions`).
- [ ] **`payments` immutable:** только create/delete, никаких UPDATE.
- [ ] **`unit_price` округляется до копеек ДО умножения**, `total_amount =
      price × subscriptions_count`.
- [ ] **Баланс выводится, не хранится:** `purchased − attended`, не кэшировать.
- [ ] **FIFO Decimal:** `fifo.py` не трогаем; `fifo_inputs` guard
      `subscriptions_count NULL/0 → skip` сохранить (иначе ÷0/Infinity).
- [ ] **MSK:** месячные границы — `Europe/Moscow`, считать в Python, не в naive SQL.
- [ ] **Полуинтервалы дат `[a,b)`** → `__gte` + `__lt`.
- [ ] **Вторичная сортировка `id DESC`** и whitelist `sort_by` с тихим fallback.
- [ ] **Секреты** (`password_hash`, `twofa_secret`) не попадают в `.values(...)`
      списков accounts (сейчас вырезаются на уровне SELECT-колонок).
- [ ] **Порядок ключей в `fifo_inputs`** (insertion order для тай-брейка дашборда).
- [ ] **`lessons_done` корректируется в ТОЙ ЖЕ транзакции**, что и attendance.

## 6. Порядок выполнения (волнами)

1. **Волна 0 — подготовка** (§2): базовый diff, `makemigrations --check`,
   общий `dictrows` helper.
2. **Волна 1 — Tier 1:** `settings_app` → `directions` → `teachers` →
   `discounts` → `tokens`. Отрабатываем паттерны 4.1–4.5, 4.9 на простом.
3. **Волна 2 — Tier 2 без денег:** `audit` → `groups` (включая 4.6 json_agg) →
   `memberships` → `lessons` (4.11/4.12 транзакции) → `accounts` (секреты).
4. **Волна 3 — деньги/аналитика (Tier 3):** `payments` (4.10 FOR UPDATE) →
   `finances` (4.8/4.15) → `dashboard` (4.14) → `students` (4.7 student_stats) →
   `teacher_spa`.
5. **Волна 4 — зачистка:** удалить осиротевшие `_dictfetch*`, проверить, что
   `from django.db import connection` остался только там, где осознанная
   `# ORM-EXCEPTION`.

## 7. Протокол верификации (после каждого app)

1. `cd journal_django && .venv/Scripts/python.exe -m pytest -q apps/<app>` — зелёный.
2. Полный прогон `pytest -q` (606 тестов) — без регрессий.
3. `python scripts/diff_express.py` (или `diff_auth`/`diff_teacher` для
   соответствующих разделов) — diff по эндпоинтам раздела **чист** (кроме
   узаконенных FIFO-ячеек). Это главный критерий: байт-в-байт.
4. `python manage.py makemigrations --check --dry-run` — модели не «поплыли».
5. Точечно глазами проверить, что функция отдаёт тот же тип (`dict`/`list`/`bool`)
   и что числа баланса прошли `_js_number`.

Только при всех пяти зелёных — переход к следующему app (память
`feedback_careful_incremental_refactor`; git нет — отката не будет).

## 8. Что осознанно оставляем сырым (ORM-EXCEPTION)

Кандидаты, где сырой SQL/`RawSQL` оправдан (финальное решение — по diff):
- `groups`: `json_agg(json_build_object(...) ORDER BY ... FILTER ...)` если
  Python-сборка слотов даёт расхождение формата времени.
- `students.student_stats` / `finances.student_balance_rows`: CTE-агрегации, если
  переразбиение на под-запросы рискует поехать по копейкам/округлению.
- любые `::text`/кастовые тонкости форматирования, где renderer не спасает.

Каждое исключение — с комментарием `# ORM-EXCEPTION: <причина>` и ссылкой на
diff, который это подтверждает. Цель раздела — **минимум** сырого SQL при
гарантированном паритете, а не ноль ценой регрессий.
