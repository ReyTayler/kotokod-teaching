# 00 — Канон структуры, инварианты, verification

Читать ПЕРВЫМ. Эти правила обязательны для всех разделов.

## Канон Django-app (по домену)

```
apps/<feature>/
  models.py        # managed=False поверх существующей таблицы; date-поля = CharField(10), НЕ DateField
  serializers.py   # Read/Write/Update; порт правил из shared/schemas.js; Serializer, НЕ ModelSerializer
  views.py         # ТОНКИЙ: HTTP → service. Никакого SQL и бизнес-правил
  services.py      # бизнес-правила, валидация, транзакции
  repository.py    # ЕДИНСТВЕННОЕ место с SQL (connection.cursor(), плейсхолдеры %s)
  urls.py          # пути ровно как у Express (без trailing slash)
  tests/           # test_*_api.py (e2e) + test_*_repository.py (integration)
```

Слои строго: **View (HTTP) → Service (правила) → Repository (SQL)**. SQL во view/service — нарушение.
Эталон для копирования стиля — `apps/groups`. Для транзакций/FIFO — `apps/payments`.

## Совместимость с node-postgres (фикс в `apps/core`, важно ВЕЗДЕ)

- **DATE → строка `YYYY-MM-DD` (МСК)**: date-поля как `CharField(max_length=10)` + `DateStringField`
  в сериализаторах + `DateSafeJSONRenderer` как safety-net. ⚠️ `inspectdb` даёт `DateField` — заменить вручную.
- **timestamptz** фронт ждёт в формате `Date.toISOString()` = `YYYY-MM-DDTHH:MM:SS.sssZ` (мс + `Z`), не
  python isoformat. Уже фиксится в `apps/core/renderers.py`.
- **numeric/decimal → строка** с сохранением масштаба (`'6290.00'`, `'0.1500'`), не float. psycopg2 отдаёт
  `Decimal`, рендерер сериализует `Decimal→str`.
- **jsonb → dict/list**, не строка (сигнал `connection_created` в `apps/core/apps.py`).
- **bigint/int8 → строка** точечно через `SELECT col::text` (node-pg так отдаёт). Касается `security_audit_log.id`.
  Обычные `serial`/int4 PK остаются числами.
- **psycopg2 плейсхолдеры `%s`**, не `$1`.

## Контракты API

- **Пагинация** ровно `{rows, total, page, page_size}` (см. `services/pagination.js` / `apps/core/pagination.py`).
  НЕ `{items, total_pages}`.
- **Сортировка** только по whitelist (`WhitelistOrderingFilter`); `sort_by` никогда не подставляется в SQL напрямую.
  `sort_dir` ∈ {asc, desc}, иначе default. Чинить в обоих местах при багах.
- **Ошибки** в формате `{error: '...'}` (валидация → `{error:'Validation failed', details}`).
  PG-коды маппятся в HTTP: 23505 unique / 23503 FK → 409. Сверить, что `apps/core/exceptions.py` покрывает
  те же коды, что `shared/pg-errors.js`.
- **`APPEND_SLASH=False`** — пути без trailing slash, как у фронта/Express.

## Доменные инварианты (НЕ сломать)

- **payments immutable**: только POST/DELETE, без PATCH. `total_amount = round_kopecks(unit_price) × subscriptions_count`
  (CHECK в БД + пересчёт на сервере, округление unit_price до копеек ДО умножения). cap: `subscriptions_count ≤ total_lessons/4`.
- **half-lesson**: `lesson_duration_minutes == 45` (или «45 минут» в названии для teacher SPA) → 0.5 урока, иначе 1.
  Действует в lessons, payroll, FIFO, balance, teacher_spa.
- **балансы выводятся, не хранятся**: `purchased − attended` per direction (half-lesson в SUM).
- **FIFO** по фактической цене партии-оплаты (`total_amount/(subscriptions_count×4)`); Decimal + копеечное
  округление; guard: оплаты с `subscriptions_count` NULL/0 пропускать (иначе Infinity ломает суммы).
- **soft-delete**: students → `enrollment_status='not_enrolled'`; groups/accounts/teachers/… → `active=false`.
  Списки по умолчанию скрывают `active=false` ровно там, где это делал Express (сверять diff'ом).
- **порядок mount при cutover**: `/api/auth` → `/api/admin` → `/api/...` (teacher) — admin до teacher-guard.

## Общая БД при strangler-fig

- `managed=False` обязателен. **Никогда** не запускать `migrate` против общей схемы.
- `django.contrib.{auth,contenttypes,sessions,admin}` НЕ включать в `INSTALLED_APPS` до Этапа auth
  (иначе создадут лишние таблицы в продовой БД). `UNAUTHENTICATED_USER=None` в REST_FRAMEWORK.

## Verification (после каждого раздела)

- **e2e-diff**: `journal_django/scripts/diff_express.py` — поднять Express :3000 + Django :8000 на общей БД,
  один и тот же запрос → diff тела/статуса/формата дат должен быть **пуст**.
- **DATE-инвариант**: на каждый раздел с датами — тест «ввод = вывод без сдвига».
- **N+1**: `assert_num_queries` на списках; индексы под реальные предикаты.
- **Финансы**: golden-fixtures из Express → сверка Decimal-в-Decimal до копейки.
- **Запуск тестов**: `pytest` (заменяет `node --test`).

## Производительность

VPS 2 CPU / 2 ГБ. Пагинация везде, никаких безлимитных SELECT. Индексы под предикаты (PG не индексирует FK сам).
Не читать «всё», где нужна часть.
