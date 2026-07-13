# Раздел «Синхро» в admin SPA — реализация

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перенести `scripts/backfill-*.js` + `rebuild-payroll.js` + `rebuild-counters.js` на Python/Celery внутри нового приложения `apps/sync`, и добавить раздел «Синхро» в admin SPA, откуда суперадмин их запускает и видит результат.

**Architecture:** Каждое действие — Celery-задача (очередь `default`). `POST /api/admin/sync/<action>/run` ставит задачу и возвращает `task_id`; `GET /api/admin/sync/status/<task_id>` отдаёт состояние из Celery result backend (Redis, уже настроен) — SPA поллит через TanStack Query. История не персистится в БД.

**Tech Stack:** Django 5.1, DRF, Celery (уже в проекте), `google-api-python-client` + `google-auth` (новые зависимости), raw SQL через `django.db.connection` (не ORM — см. спеку), React 19 + TanStack Query (admin-src).

**Спека:** `docs/superpowers/specs/2026-07-13-admin-sync-section-design.md` — читать первой, если что-то в плане неясно.

---

## Task 1: Скелет приложения `apps.sync` + зависимости + wiring

**Files:**
- Create: `journal_django/apps/sync/__init__.py`
- Create: `journal_django/apps/sync/apps.py`
- Create: `journal_django/apps/sync/backfills/__init__.py`
- Create: `journal_django/apps/sync/tests/__init__.py`
- Modify: `journal_django/requirements.txt`
- Modify: `journal_django/config/settings/base.py`
- Modify: `journal_django/config/urls.py`

- [ ] **Step 1: Создать пустые `__init__.py`**

```bash
mkdir -p journal_django/apps/sync/backfills journal_django/apps/sync/tests
type nul > journal_django/apps/sync/__init__.py
type nul > journal_django/apps/sync/backfills/__init__.py
type nul > journal_django/apps/sync/tests/__init__.py
```

(На Windows `type nul >` создаёт пустой файл; на Linux/mac — `touch`.)

- [ ] **Step 2: `apps.py`**

```python
from django.apps import AppConfig


class SyncConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.sync'
```

- [ ] **Step 3: Добавить зависимости в `requirements.txt`**

В конец файла `journal_django/requirements.txt` добавить:

```
google-api-python-client==2.149.0   # чтение Google Sheets для apps.sync (порт backfill-скриптов)
google-auth==2.35.0                 # service-account креды для google-api-python-client
```

Установить в venv:

```bash
cd journal_django
.venv/Scripts/python.exe -m pip install google-api-python-client==2.149.0 google-auth==2.35.0
```

- [ ] **Step 4: Зарегистрировать приложение в `INSTALLED_APPS`**

В `journal_django/config/settings/base.py` найти список `INSTALLED_APPS` (заканчивается на `'apps.changelog',`) и добавить после него:

```python
    'apps.changelog',
    'apps.sync',
```

- [ ] **Step 5: Result backend без Redis для eager-режима + явный `CELERY_TASK_STORE_EAGER_RESULT`**

⚠️ Важно: `apps.sync.views.SyncStatusView` всегда читает результат через
`AsyncResult(task_id)` из result backend'а — в проде это Redis (реальный, задача
шла через воркер). Но в dev/тестах (`REDIS_URL` не задан) `CELERY_TASK_ALWAYS_EAGER=True`,
и без `CELERY_TASK_STORE_EAGER_RESULT=True` eager-результат вообще не попадает в
backend. Включить эту опцию — правильно, но **бэкенд по умолчанию всё ещё указывает
на настоящий Redis** (`CELERY_RESULT_BACKEND = REDIS_URL or 'redis://localhost:6379/0'`)
— а в dev/тестах Redis не поднят (осознанно, по конвенции проекта). Если включить
`STORE_EAGER_RESULT` не поменяв backend, `SyncStatusView` в dev/тестах будет пытаться
писать/читать из несуществующего Redis.

Исправление — два изменения в `journal_django/config/settings/base.py`. Найти блок:

```python
CELERY_BROKER_URL = REDIS_URL or 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = REDIS_URL or 'redis://localhost:6379/0'
CELERY_TIMEZONE = 'Europe/Moscow'
CELERY_ENABLE_UTC = False
CELERY_TASK_ALWAYS_EAGER = not REDIS_URL
```

Заменить на:

```python
CELERY_BROKER_URL = REDIS_URL or 'redis://localhost:6379/0'
# cache+memory:// — in-process backend без внешних зависимостей. Раньше здесь тоже
# был 'redis://localhost:6379/0' — не проблема, пока ничего не читало eager-результат
# из backend'а. apps.sync.views.SyncStatusView — первый потребитель, которому это
# нужно и в dev/тестах (REDIS_URL не задан, Redis намеренно не поднят локально).
CELERY_RESULT_BACKEND = REDIS_URL or 'cache+memory://'
CELERY_TIMEZONE = 'Europe/Moscow'
CELERY_ENABLE_UTC = False
CELERY_TASK_ALWAYS_EAGER = not REDIS_URL
# В eager-режиме результат по умолчанию НЕ кладётся в result backend — доступен
# только напрямую из возврата .delay(). SyncStatusView всегда читает через
# AsyncResult(task_id) из backend'а, поэтому без этой опции dev/тесты не работали бы.
CELERY_TASK_STORE_EAGER_RESULT = True
```

- [ ] **Step 6: Заготовка `urls.py` (наполним в Task 14) и wiring**

Создать `journal_django/apps/sync/urls.py`:

```python
"""Маршруты sync. APPEND_SLASH=False — без trailing slash."""
from django.urls import path

urlpatterns: list = []
```

В `journal_django/config/urls.py` после строки
`path('api/admin/calendar', include('apps.scheduling.admin_urls')),`
добавить:

```python
    # Синхро — ручной запуск backfill/пересчётов из Google Sheets (только superadmin)
    path('api/admin/sync', include('apps.sync.urls')),
```

- [ ] **Step 7: Проверить, что Django не падает**

```bash
cd journal_django
.venv/Scripts/python.exe manage.py check
```

Ожидание: `System check identified no issues` (плюс уже известные W342-warnings — не новые).

- [ ] **Step 8: Commit**

```bash
git add journal_django/apps/sync journal_django/requirements.txt journal_django/config/settings/base.py journal_django/config/urls.py
git commit -m "feat(sync): scaffold apps.sync app, deps, settings, urls wiring"
```

---

## Task 2: `backfills/rows.py` — безопасный доступ к ячейкам + JS-подобные parseInt/parseFloat

**Files:**
- Create: `journal_django/apps/sync/backfills/rows.py`
- Test: `journal_django/apps/sync/tests/test_rows.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_rows.py
from apps.sync.backfills.rows import cell, parse_float, parse_int


def test_cell_returns_empty_for_missing_index():
    assert cell(['a', 'b'], 5) == ''


def test_cell_returns_empty_for_falsy_value():
    assert cell(['a', '', None], 1) == ''
    assert cell(['a', '', None], 2) == ''


def test_cell_strips_and_stringifies():
    assert cell(['  Иванов  '], 0) == 'Иванов'


def test_parse_int_leading_digits():
    assert parse_int('12abc') == 12
    assert parse_int('  42') == 42


def test_parse_int_none_on_no_digits():
    assert parse_int('abc') is None
    assert parse_int('') is None
    assert parse_int(None) is None


def test_parse_float_leading_number():
    assert parse_float('3.5abc') == 3.5
    assert parse_float('10') == 10.0


def test_parse_float_none_on_invalid():
    assert parse_float('abc') is None
    assert parse_float('') is None
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
cd journal_django
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_rows.py -v
```

Ожидание: `ModuleNotFoundError: No module named 'apps.sync.backfills.rows'`.

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/backfills/rows.py
"""Безопасный доступ к "рваным" строкам Google Sheets + JS-подобный parseInt/parseFloat.

Google Sheets API отдаёт строки без хвостовых пустых ячеек ("рваные" строки) —
обращение по индексу может выйти за границу. cell() безопасно достаёт значение
как строку. parse_int/parse_float повторяют семантику JS parseInt/parseFloat
(берут ведущее число из строки, а не требуют строгого совпадения) — исходные
Node-скрипты полагались именно на это поведение при разборе таблиц.
"""
from __future__ import annotations

import re

_LEADING_INT_RE = re.compile(r'^\s*(-?\d+)')
_LEADING_FLOAT_RE = re.compile(r'^\s*(-?\d+(?:\.\d+)?)')


def cell(row: list, idx: int) -> str:
    """row[idx] как строка, '' если индекс вне диапазона или значение пустое."""
    if idx >= len(row):
        return ''
    value = row[idx]
    return str(value).strip() if value else ''


def parse_int(raw) -> int | None:
    """Как JS `parseInt(raw, 10)` — ведущие цифры строки, иначе None (аналог NaN)."""
    m = _LEADING_INT_RE.match(str(raw or ''))
    return int(m.group(1)) if m else None


def parse_float(raw) -> float | None:
    """Как JS `parseFloat(raw)` — ведущее число, иначе None (аналог NaN)."""
    m = _LEADING_FLOAT_RE.match(str(raw or ''))
    return float(m.group(1)) if m else None
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_rows.py -v
```

Ожидание: все тесты `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/sync/backfills/rows.py journal_django/apps/sync/tests/test_rows.py
git commit -m "feat(sync): add rows.py cell/parse_int/parse_float helpers"
```

---

## Task 3: `backfills/dates.py` — разбор дат

**Files:**
- Create: `journal_django/apps/sync/backfills/dates.py`
- Test: `journal_django/apps/sync/tests/test_dates.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_dates.py
from apps.sync.backfills.dates import parse_lesson_date, parse_start_date


def test_parse_start_date_valid():
    assert parse_start_date('13.07.2026') == '2026-07-13'


def test_parse_start_date_two_digit_year():
    assert parse_start_date('13.07.26') == '2026-07-13'


def test_parse_start_date_invalid_returns_none():
    assert parse_start_date('не дата') is None
    assert parse_start_date('') is None
    assert parse_start_date(None) is None


def test_parse_start_date_rejects_trailing_junk():
    # parse_start_date заякорен с обеих сторон (^...$) — в отличие от parse_lesson_date
    assert parse_start_date('13.07.2026 доп.текст') is None


def test_parse_lesson_date_valid():
    assert parse_lesson_date('13.07.2026') == '2026-07-13'


def test_parse_lesson_date_allows_trailing_junk():
    # parse_lesson_date заякорен только слева — хвост после даты игнорируется
    assert parse_lesson_date('13.07.2026 доп.текст') == '2026-07-13'


def test_parse_lesson_date_invalid_returns_none():
    assert parse_lesson_date('не дата') is None
    assert parse_lesson_date(None) is None
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_dates.py -v
```

Ожидание: `ModuleNotFoundError`.

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/backfills/dates.py
"""Разбор дат из Google Sheets. Порт parseStartDate/parseLessonDate
(scripts/backfill-students.js, scripts/backfill-lessons.js).

Google Sheets API отдаёт ячейки как обычные JSON-строки (дефолтный render
mode FORMATTED_VALUE) — ветка "value instanceof Date" в оригинальных
JS-скриптах была защитной на случай другого рендера и на практике никогда не
срабатывала с sheets.spreadsheets.values.get() без valueRenderOption. В этом
порту она не нужна — работаем только со строками.

parse_start_date заякорен с обеих сторон (вся строка обязана быть датой) —
для дат рождения/старта абонемента. parse_lesson_date заякорен только слева
(хвост после даты игнорируется) — для дат в журнале уроков, где в ячейке
иногда встречается день недели после даты.
"""
from __future__ import annotations

import re

_DATE_ANCHORED_RE = re.compile(r'^(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})$')
_DATE_PREFIX_RE = re.compile(r'^(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})')


def _to_iso(dd: str, mm: str, yyyy: str) -> str:
    dd = dd.zfill(2)
    mm = mm.zfill(2)
    if len(yyyy) == 2:
        yyyy = '20' + yyyy
    return f'{yyyy}-{mm}-{dd}'


def parse_start_date(value) -> str | None:
    """ДД.ММ.ГГГГ (вся строка) → YYYY-MM-DD, иначе None."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = _DATE_ANCHORED_RE.match(s)
    if not m:
        return None
    return _to_iso(*m.groups())


def parse_lesson_date(value) -> str | None:
    """ДД.ММ.ГГГГ в начале строки (хвост игнорируется) → YYYY-MM-DD, иначе None."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = _DATE_PREFIX_RE.match(s)
    if not m:
        return None
    return _to_iso(*m.groups())
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_dates.py -v
```

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/sync/backfills/dates.py journal_django/apps/sync/tests/test_dates.py
git commit -m "feat(sync): add dates.py parse_start_date/parse_lesson_date"
```

---

## Task 4: `sheets_client.py` — клиент Google Sheets (только чтение)

**Files:**
- Create: `journal_django/apps/sync/sheets_client.py`
- Test: `journal_django/apps/sync/tests/test_sheets_client.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_sheets_client.py
from unittest.mock import MagicMock, patch

from apps.sync import sheets_client


def test_read_students_range_uses_students_spreadsheet_id(monkeypatch):
    monkeypatch.setenv('STUDENTS_SPREADSHEET_ID', 'STU123')
    fake_service = MagicMock()
    fake_service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        'values': [['a', 'b']],
    }

    with patch.object(sheets_client, '_sheets_service', return_value=fake_service):
        rows = sheets_client.read_students_range('Список всех детей', 'A3:S')

    assert rows == [['a', 'b']]
    fake_service.spreadsheets.return_value.values.return_value.get.assert_called_once_with(
        spreadsheetId='STU123', range='Список всех детей!A3:S',
    )


def test_read_journal_range_uses_journal_spreadsheet_id(monkeypatch):
    monkeypatch.setenv('JOURNAL_SPREADSHEET_ID', 'JRN456')
    fake_service = MagicMock()
    fake_service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        'values': [],
    }

    with patch.object(sheets_client, '_sheets_service', return_value=fake_service):
        rows = sheets_client.read_journal_range('Токены', 'A:F')

    assert rows == []
    fake_service.spreadsheets.return_value.values.return_value.get.assert_called_once_with(
        spreadsheetId='JRN456', range='Токены!A:F',
    )


def test_read_range_returns_empty_list_when_no_values(monkeypatch):
    monkeypatch.setenv('STUDENTS_SPREADSHEET_ID', 'STU123')
    fake_service = MagicMock()
    fake_service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {}

    with patch.object(sheets_client, '_sheets_service', return_value=fake_service):
        rows = sheets_client.read_students_range('X', 'A1:A1')

    assert rows == []
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_sheets_client.py -v
```

Ожидание: `ModuleNotFoundError`.

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/sheets_client.py
"""Тонкий клиент Google Sheets (только чтение) — порт read-функций services/sheets.js.

Не переносим write-функции (appendToJournal/updateStudentCell/batchUpdateCounters) —
их звал только старый Express teacher-report flow, backfill-скрипты их не
используют. Тот же service-account-key.json и те же переменные
STUDENTS_SPREADSHEET_ID/JOURNAL_SPREADSHEET_ID из .env, что и у Node-версии.
"""
from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from google.oauth2 import service_account
from googleapiclient.discovery import build

_SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
_KEY_PATH = Path(settings.REPO_ROOT) / 'service-account-key.json'

_service = None


def _sheets_service():
    """Ленивая инициализация клиента — не дёргаем Google API при импорте модуля."""
    global _service
    if _service is None:
        creds = service_account.Credentials.from_service_account_file(str(_KEY_PATH), scopes=_SCOPES)
        _service = build('sheets', 'v4', credentials=creds)
    return _service


def _read_range(spreadsheet_id: str, sheet_name: str, cell_range: str) -> list[list]:
    result = _sheets_service().spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f'{sheet_name}!{cell_range}',
    ).execute()
    return result.get('values', [])


def read_students_range(sheet_name: str, cell_range: str) -> list[list]:
    """Чтение диапазона из таблицы учеников (STUDENTS_SPREADSHEET_ID)."""
    return _read_range(os.environ['STUDENTS_SPREADSHEET_ID'], sheet_name, cell_range)


def read_journal_range(sheet_name: str, cell_range: str) -> list[list]:
    """Чтение диапазона из таблицы журнала (JOURNAL_SPREADSHEET_ID)."""
    return _read_range(os.environ['JOURNAL_SPREADSHEET_ID'], sheet_name, cell_range)
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_sheets_client.py -v
```

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/sync/sheets_client.py journal_django/apps/sync/tests/test_sheets_client.py
git commit -m "feat(sync): add sheets_client.py (read-only Google Sheets client)"
```

---

## Task 5: `backfills/teachers.py`

**Files:**
- Create: `journal_django/apps/sync/backfills/teachers.py`
- Test: `journal_django/apps/sync/tests/test_backfill_teachers.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_backfill_teachers.py
import pytest
from django.db import connection

from apps.sync.backfills import teachers


def test_extract_teachers_from_student_rows():
    student_rows = [
        ['Иванов', '', '', '', '', '', '', '', '', '', '', 'Петрова', 'Группа A'],
        ['Сидоров', '', '', '', '', '', '', '', '', '', '', 'Петрова', 'Группа A'],
        ['Козлов', '', '', '', '', '', '', '', '', '', '', 'Смирнова', 'Группа B'],
    ]
    result = teachers.extract_teachers(student_rows, [])
    assert set(result) == {'Петрова', 'Смирнова'}


def test_extract_teachers_skips_uchenika_net():
    student_rows = [
        ['Х', '', '', '', '', '', '', '', '', '', '', 'УЧЕНИКА НЕТ', 'Группа A'],
    ]
    assert teachers.extract_teachers(student_rows, []) == []


def test_extract_teachers_includes_token_sheet():
    token_rows = [
        ['header'] * 6,
        ['', '', '', '', 'TOKEN1', 'Кузнецова'],
    ]
    result = teachers.extract_teachers([], token_rows)
    assert result == ['Кузнецова']


@pytest.mark.django_db
def test_run_inserts_new_teachers(monkeypatch):
    monkeypatch.setattr(
        teachers.sheets_client, 'read_students_range',
        lambda *a: [['S', '', '', '', '', '', '', '', '', '', '', '__test_sync_teacher__', 'Группа X']],
    )
    monkeypatch.setattr(teachers.sheets_client, 'read_journal_range', lambda *a: [['h'] * 6])

    try:
        result = teachers.run(dry_run=False)
        assert result['read'] == 1
        assert result['inserted'] == 1
        with connection.cursor() as cur:
            cur.execute("SELECT id FROM teachers WHERE name = %s", ['__test_sync_teacher__'])
            assert cur.fetchone() is not None
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM teachers WHERE name = %s", ['__test_sync_teacher__'])


@pytest.mark.django_db
def test_run_dry_run_does_not_write(monkeypatch):
    monkeypatch.setattr(
        teachers.sheets_client, 'read_students_range',
        lambda *a: [['S', '', '', '', '', '', '', '', '', '', '', '__test_sync_teacher_dry__', 'Группа X']],
    )
    monkeypatch.setattr(teachers.sheets_client, 'read_journal_range', lambda *a: [['h'] * 6])

    result = teachers.run(dry_run=True)
    assert result['read'] == 1
    assert result['dry_run'] is True

    with connection.cursor() as cur:
        cur.execute("SELECT id FROM teachers WHERE name = %s", ['__test_sync_teacher_dry__'])
        assert cur.fetchone() is None
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_backfill_teachers.py -v
```

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/backfills/teachers.py
"""Backfill преподавателей из Google Sheets. Порт scripts/backfill-teachers.js."""
from __future__ import annotations

from django.db import connection

from apps.sync import sheets_client
from apps.sync.backfills.rows import cell


def extract_teachers(student_rows: list[list], token_rows: list[list]) -> list[str]:
    names: set[str] = set()

    for row in student_rows:
        teacher = cell(row, 11)
        group = cell(row, 12)
        if not teacher or not group:
            continue
        if 'УЧЕНИКА НЕТ' in teacher or 'УЧЕНИКА НЕТ' in group:
            continue
        names.add(teacher)

    for row in token_rows[1:]:
        teacher = cell(row, 5)
        if teacher:
            names.add(teacher)

    return list(names)


def run(dry_run: bool = False) -> dict:
    result = {'entity': 'teachers', 'read': 0, 'inserted': 0, 'skipped': 0, 'dry_run': dry_run}

    student_rows = sheets_client.read_students_range('Список всех детей', 'A3:S')
    token_rows = sheets_client.read_journal_range('Токены', 'A:F')

    names = extract_teachers(student_rows, token_rows)
    result['read'] = len(names)

    if dry_run:
        return result

    with connection.cursor() as cur:
        for name in names:
            cur.execute(
                """
                INSERT INTO teachers (name) VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                RETURNING id
                """,
                [name],
            )
            if cur.fetchone() is None:
                result['skipped'] += 1
            else:
                result['inserted'] += 1

    return result
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_backfill_teachers.py -v
```

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/sync/backfills/teachers.py journal_django/apps/sync/tests/test_backfill_teachers.py
git commit -m "feat(sync): port backfill-teachers.js to Python"
```

---

## Task 6: `backfills/groups.py`

**Files:**
- Create: `journal_django/apps/sync/backfills/groups.py`
- Test: `journal_django/apps/sync/tests/test_backfill_groups.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_backfill_groups.py
import pytest
from django.db import connection

from apps.sync.backfills import groups


def _row(teacher, group, vk='', direction='Python', start=''):
    row = [''] * 19
    row[11] = teacher
    row[12] = group
    row[13] = start
    row[15] = vk
    row[18] = direction
    return row


def test_extract_groups_basic():
    rows = [_row('Петрова', 'Группа Пн 18:00', direction='Python')]
    result = groups.extract_groups(rows)
    assert len(result) == 1
    g = result[0]
    assert g['name'] == 'Группа Пн 18:00'
    assert g['teacher_name'] == 'Петрова'
    assert g['direction_name'] == 'Python'
    assert g['is_individual'] is False
    assert g['slots'] == [{'day_of_week': 1, 'start_time': '18:00:00'}]


def test_extract_groups_individual():
    rows = [_row('Петрова', 'Иванов Инд', direction='Python ИНДИВ')]
    result = groups.extract_groups(rows)
    assert result[0]['is_individual'] is True


def test_extract_groups_dedupes_by_name_and_backfills_start_date():
    rows = [
        _row('Петрова', 'Группа A', direction='Python', start=''),
        _row('Петрова', 'Группа A', direction='Python', start='01.09.2025'),
    ]
    result = groups.extract_groups(rows)
    assert len(result) == 1
    assert result[0]['group_start_date'] == '2025-09-01'


def test_extract_groups_skips_uchenika_net():
    rows = [_row('УЧЕНИКА НЕТ', 'Группа A')]
    assert groups.extract_groups(rows) == []


@pytest.mark.django_db
def test_run_inserts_group_and_slots(monkeypatch):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_g__') RETURNING id")
        cur.execute("SELECT name FROM directions LIMIT 1")
        direction_row = cur.fetchone()
    assert direction_row is not None, 'Нужна хотя бы одна direction в тестовой БД (сидируется миграциями/фикстурами)'
    direction_name = direction_row[0]

    rows = [_row('__test_sync_teacher_g__', '__test_sync_group__ Пн 18:00', direction=direction_name)]
    monkeypatch.setattr(groups.sheets_client, 'read_students_range', lambda *a: rows)

    try:
        result = groups.run(dry_run=False)
        assert result['read'] == 1
        assert result['inserted'] == 1
        assert result['slots_replaced'] == 1
        with connection.cursor() as cur:
            cur.execute("SELECT id FROM groups WHERE name = %s", ['__test_sync_group__ Пн 18:00'])
            group_row = cur.fetchone()
            assert group_row is not None
            cur.execute("SELECT COUNT(*) FROM group_schedule_slots WHERE group_id = %s", [group_row[0]])
            assert cur.fetchone()[0] == 1
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM groups WHERE name = '__test_sync_group__ Пн 18:00'")
            cur.execute("DELETE FROM teachers WHERE name = '__test_sync_teacher_g__'")


@pytest.mark.django_db
def test_run_dry_run_does_not_write(monkeypatch):
    rows = [_row('Несуществующий', '__test_sync_group_dry__', direction='Python')]
    monkeypatch.setattr(groups.sheets_client, 'read_students_range', lambda *a: rows)

    result = groups.run(dry_run=True)
    assert result['read'] == 1
    assert result['dry_run'] is True
    with connection.cursor() as cur:
        cur.execute("SELECT id FROM groups WHERE name = '__test_sync_group_dry__'")
        assert cur.fetchone() is None
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_backfill_groups.py -v
```

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/backfills/groups.py
"""Backfill групп из Google Sheets. Порт scripts/backfill-groups.js."""
from __future__ import annotations

from django.db import connection

from apps.sync import sheets_client
from apps.sync.backfills.dates import parse_start_date
from apps.sync.backfills.rows import cell
from apps.sync.lib.parse_time import parse_lesson_duration, parse_time_slots


def extract_groups(rows: list[list]) -> list[dict]:
    seen: dict[str, dict] = {}
    for row in rows:
        teacher = cell(row, 11)
        group = cell(row, 12)
        vk = cell(row, 15)
        direction = cell(row, 18)
        start_date = parse_start_date(cell(row, 13))

        if not teacher or not group or not direction:
            continue
        if any('УЧЕНИКА НЕТ' in v for v in (teacher, group, direction)):
            continue

        if group not in seen:
            is_individual = 'ИНДИВ' in direction
            slots = parse_time_slots(group)
            seen[group] = {
                'name': group,
                'direction_name': direction,
                'teacher_name': teacher,
                'is_individual': is_individual,
                'lesson_duration_minutes': parse_lesson_duration(group),
                'lessons_per_week': len(slots) or 1,
                'vk_chat': vk,
                'group_start_date': start_date,
                'slots': slots,
            }
        else:
            g = seen[group]
            if not g['group_start_date'] and start_date:
                g['group_start_date'] = start_date

    return list(seen.values())


def run(dry_run: bool = False) -> dict:
    result = {
        'entity': 'groups', 'read': 0, 'inserted': 0, 'updated': 0,
        'skipped': 0, 'slots_replaced': 0, 'dry_run': dry_run,
    }

    rows = sheets_client.read_students_range('Список всех детей', 'A3:T')
    groups_data = extract_groups(rows)
    result['read'] = len(groups_data)

    if dry_run:
        return result

    with connection.cursor() as cur:
        for g in groups_data:
            cur.execute(
                """
                WITH d AS (SELECT id FROM directions WHERE name = %(direction_name)s),
                     te AS (SELECT id FROM teachers WHERE name = %(teacher_name)s)
                INSERT INTO groups (name, direction_id, teacher_id, is_individual,
                                    lesson_duration_minutes, lessons_per_week, vk_chat, group_start_date)
                SELECT %(name)s, d.id, te.id, %(is_individual)s, %(duration)s, %(per_week)s,
                       NULLIF(%(vk_chat)s, ''), %(start_date)s
                FROM d, te
                ON CONFLICT (name) DO UPDATE SET
                   direction_id            = EXCLUDED.direction_id,
                   teacher_id              = EXCLUDED.teacher_id,
                   is_individual           = EXCLUDED.is_individual,
                   lesson_duration_minutes = EXCLUDED.lesson_duration_minutes,
                   lessons_per_week        = EXCLUDED.lessons_per_week,
                   vk_chat                 = EXCLUDED.vk_chat,
                   group_start_date        = EXCLUDED.group_start_date
                WHERE
                   groups.direction_id            IS DISTINCT FROM EXCLUDED.direction_id
                OR groups.teacher_id              IS DISTINCT FROM EXCLUDED.teacher_id
                OR groups.is_individual           IS DISTINCT FROM EXCLUDED.is_individual
                OR groups.lesson_duration_minutes IS DISTINCT FROM EXCLUDED.lesson_duration_minutes
                OR groups.lessons_per_week        IS DISTINCT FROM EXCLUDED.lessons_per_week
                OR (groups.vk_chat IS DISTINCT FROM NULLIF(EXCLUDED.vk_chat, ''))
                OR groups.group_start_date        IS DISTINCT FROM EXCLUDED.group_start_date
                RETURNING id, (xmax = 0) AS inserted
                """,
                {
                    'direction_name': g['direction_name'], 'teacher_name': g['teacher_name'],
                    'name': g['name'], 'is_individual': g['is_individual'],
                    'duration': g['lesson_duration_minutes'], 'per_week': g['lessons_per_week'],
                    'vk_chat': g['vk_chat'], 'start_date': g['group_start_date'],
                },
            )
            row = cur.fetchone()

            if row is None:
                cur.execute('SELECT id FROM groups WHERE name = %s', [g['name']])
                found = cur.fetchone()
                if found is None:
                    result['skipped'] += 1
                    continue
                group_id = found[0]
                result['skipped'] += 1
            else:
                group_id, inserted = row
                if inserted:
                    result['inserted'] += 1
                else:
                    result['updated'] += 1

            cur.execute('DELETE FROM group_schedule_slots WHERE group_id = %s', [group_id])
            for slot in g['slots']:
                cur.execute(
                    'INSERT INTO group_schedule_slots (group_id, day_of_week, start_time) VALUES (%s, %s, %s)',
                    [group_id, slot['day_of_week'], slot['start_time']],
                )
                result['slots_replaced'] += 1

    return result
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_backfill_groups.py -v
```

Если `test_run_inserts_group_and_slots` падает с "Нужна хотя бы одна direction..." — проверить тестовую БД (`journal_test`) на наличие сидированных `directions`; если пусто, добавить в тест создание временной direction в `setup`/`finally` по аналогии с teacher (создать и удалить), вместо `SELECT ... LIMIT 1`.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/sync/backfills/groups.py journal_django/apps/sync/tests/test_backfill_groups.py
git commit -m "feat(sync): port backfill-groups.js to Python"
```

---

## Task 7: `backfills/students.py`

**Files:**
- Create: `journal_django/apps/sync/backfills/students.py`
- Test: `journal_django/apps/sync/tests/test_backfill_students.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_backfill_students.py
import pytest
from django.db import connection

from apps.sync.backfills import students


def _row(name, teacher='', group='', done='', enroll=''):
    row = [''] * 20
    row[0] = name
    row[2] = '10'
    row[9] = 'PM1'
    row[11] = teacher
    row[12] = group
    row[13] = '01.09.2025'
    row[14] = '5'
    row[16] = done
    row[19] = enroll
    return row


def test_extract_students_basic():
    rows = [_row('Иванов Иван', teacher='Петрова', group='Группа A', done='3.5')]
    result = students.extract_students_and_memberships(rows)
    assert len(result['students']) == 1
    assert result['students'][0]['full_name'] == 'Иванов Иван'
    assert result['students'][0]['age'] == 10
    assert len(result['memberships']) == 1
    assert result['memberships'][0]['lessons_done'] == 3.5


def test_extract_students_skips_uchenika_net_name():
    rows = [_row('УЧЕНИКА НЕТ')]
    result = students.extract_students_and_memberships(rows)
    assert result['students'] == []


def test_extract_students_no_membership_without_teacher():
    rows = [_row('Одиночка', teacher='', group='')]
    result = students.extract_students_and_memberships(rows)
    assert len(result['students']) == 1
    assert result['memberships'] == []
    assert result['students'][0]['enrollment_status'] == 'not_enrolled'


def test_map_enrollment_yes():
    assert students.map_enrollment_from_sheets('Да', True) == {
        'enrollment_status': 'enrolled', 'frozen_until_month': None,
    }


def test_map_enrollment_frozen_with_month():
    result = students.map_enrollment_from_sheets('нет январь', True)
    assert result == {'enrollment_status': 'frozen', 'frozen_until_month': 1}


def test_map_enrollment_declined():
    result = students.map_enrollment_from_sheets('отказ от занятий', True)
    assert result['enrollment_status'] == 'declined'


@pytest.mark.django_db
def test_run_inserts_student_and_membership(monkeypatch):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_s__') RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM directions LIMIT 1")
        direction_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes, lessons_per_week) "
            "VALUES ('__test_sync_group_s__', %s, %s, false, 90, 1) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]

    rows = [_row('__test_sync_student__', teacher='__test_sync_teacher_s__', group='__test_sync_group_s__', done='2')]
    monkeypatch.setattr(students.sheets_client, 'read_students_range', lambda *a: rows)

    try:
        result = students.run(dry_run=False)
        assert result['students_inserted'] == 1
        assert result['memberships_inserted'] == 1
        with connection.cursor() as cur:
            cur.execute("SELECT id FROM students WHERE full_name = %s", ['__test_sync_student__'])
            assert cur.fetchone() is not None
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM group_memberships WHERE group_id = %s", [group_id])
            cur.execute("DELETE FROM students WHERE full_name = '__test_sync_student__'")
            cur.execute("DELETE FROM groups WHERE id = %s", [group_id])
            cur.execute("DELETE FROM teachers WHERE name = '__test_sync_teacher_s__'")
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_backfill_students.py -v
```

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/backfills/students.py
"""Backfill учеников и абонементов из Google Sheets. Порт scripts/backfill-students.js."""
from __future__ import annotations

from django.db import connection

from apps.sync import sheets_client
from apps.sync.backfills.dates import parse_start_date
from apps.sync.backfills.rows import cell, parse_float, parse_int

MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
          'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']


def map_enrollment_from_sheets(raw, has_membership: bool) -> dict:
    s = str(raw or '').strip().lower()
    fallback = (
        {'enrollment_status': 'enrolled', 'frozen_until_month': None}
        if has_membership
        else {'enrollment_status': 'not_enrolled', 'frozen_until_month': None}
    )

    if not s:
        return fallback
    if s == 'да':
        return {'enrollment_status': 'enrolled', 'frozen_until_month': None}
    if s == 'нет':
        return {'enrollment_status': 'not_enrolled', 'frozen_until_month': None}
    if 'отказ' in s:
        return {'enrollment_status': 'declined', 'frozen_until_month': None}

    rest = s[3:].strip() if s.startswith('нет') else s
    for idx, month in enumerate(MONTHS):
        if rest.startswith(month):
            return {'enrollment_status': 'frozen', 'frozen_until_month': idx + 1}
    return fallback


def extract_students_and_memberships(rows: list[list]) -> dict:
    students_map: dict[str, dict] = {}
    memberships: list[dict] = []

    for row in rows:
        name = cell(row, 0)
        if not name or 'УЧЕНИКА НЕТ' in name:
            continue

        teacher = cell(row, 11)
        group = cell(row, 12)
        teacher_ok = bool(teacher) and 'УЧЕНИКА НЕТ' not in teacher
        group_ok = bool(group) and 'УЧЕНИКА НЕТ' not in group
        has_membership = teacher_ok and group_ok

        if name not in students_map:
            enroll = map_enrollment_from_sheets(cell(row, 19) or None, has_membership)
            students_map[name] = {
                'full_name': name,
                'age': parse_int(cell(row, 2)),
                'pm': cell(row, 9) or None,
                'birth_date': parse_start_date(cell(row, 7)),
                'parent1_phone': cell(row, 6) or None,
                'platform_id': cell(row, 4) or None,
                'parent1_name': cell(row, 5) or None,
                'first_purchase_date': parse_start_date(cell(row, 8)),
                'enrollment_status': enroll['enrollment_status'],
                'frozen_until_month': enroll['frozen_until_month'],
            }

        if has_membership:
            done = round((parse_float(cell(row, 16)) or 0) * 10) / 10
            memberships.append({
                'student_name': name,
                'group_name': group,
                'lessons_done': done,
                'start_date': parse_start_date(cell(row, 13)),
                'sheet_row': parse_int(cell(row, 14)),
            })

    return {'students': list(students_map.values()), 'memberships': memberships}


def run(dry_run: bool = False) -> dict:
    result = {
        'entity': 'students+memberships',
        'students_read': 0, 'students_inserted': 0, 'students_updated': 0, 'students_skipped': 0,
        'memberships_read': 0, 'memberships_inserted': 0, 'memberships_updated': 0, 'memberships_skipped': 0,
        'dry_run': dry_run,
    }

    rows = sheets_client.read_students_range('Список всех детей', 'A3:T')
    extracted = extract_students_and_memberships(rows)
    students_data = extracted['students']
    memberships = extracted['memberships']
    result['students_read'] = len(students_data)
    result['memberships_read'] = len(memberships)

    if dry_run:
        return result

    with connection.cursor() as cur:
        for s in students_data:
            cur.execute(
                """
                INSERT INTO students
                    (full_name, age, pm, birth_date, parent1_phone, platform_id,
                     parent1_name, first_purchase_date, enrollment_status, frozen_until_month)
                VALUES (%(full_name)s, %(age)s, %(pm)s, %(birth_date)s, %(phone)s,
                        %(platform)s, %(parent)s, %(first_purchase)s, %(status)s, %(frozen)s)
                ON CONFLICT (full_name) DO UPDATE SET
                    age                 = EXCLUDED.age,
                    pm                  = EXCLUDED.pm,
                    birth_date          = EXCLUDED.birth_date,
                    parent1_phone       = EXCLUDED.parent1_phone,
                    platform_id         = EXCLUDED.platform_id,
                    parent1_name        = EXCLUDED.parent1_name,
                    first_purchase_date = EXCLUDED.first_purchase_date,
                    enrollment_status   = EXCLUDED.enrollment_status,
                    frozen_until_month  = EXCLUDED.frozen_until_month
                WHERE students.age IS DISTINCT FROM EXCLUDED.age
                   OR students.pm  IS DISTINCT FROM EXCLUDED.pm
                   OR students.birth_date          IS DISTINCT FROM EXCLUDED.birth_date
                   OR students.parent1_phone       IS DISTINCT FROM EXCLUDED.parent1_phone
                   OR students.platform_id         IS DISTINCT FROM EXCLUDED.platform_id
                   OR students.parent1_name        IS DISTINCT FROM EXCLUDED.parent1_name
                   OR students.first_purchase_date IS DISTINCT FROM EXCLUDED.first_purchase_date
                   OR students.enrollment_status   IS DISTINCT FROM EXCLUDED.enrollment_status
                   OR students.frozen_until_month  IS DISTINCT FROM EXCLUDED.frozen_until_month
                RETURNING (xmax = 0) AS inserted
                """,
                {
                    'full_name': s['full_name'], 'age': s['age'], 'pm': s['pm'],
                    'birth_date': s['birth_date'], 'phone': s['parent1_phone'],
                    'platform': s['platform_id'], 'parent': s['parent1_name'],
                    'first_purchase': s['first_purchase_date'], 'status': s['enrollment_status'],
                    'frozen': s['frozen_until_month'],
                },
            )
            row = cur.fetchone()
            if row is None:
                result['students_skipped'] += 1
            elif row[0]:
                result['students_inserted'] += 1
            else:
                result['students_updated'] += 1

        for m in memberships:
            cur.execute(
                """
                WITH g AS (SELECT id FROM groups   WHERE name = %(group_name)s),
                     s AS (SELECT id FROM students WHERE full_name = %(student_name)s)
                INSERT INTO group_memberships
                    (group_id, student_id, lessons_done, start_date, sheet_row, active)
                SELECT g.id, s.id, %(lessons_done)s, %(start_date)s, %(sheet_row)s, true FROM g, s
                ON CONFLICT (group_id, student_id) DO UPDATE SET
                    lessons_done = EXCLUDED.lessons_done,
                    start_date   = EXCLUDED.start_date,
                    sheet_row    = EXCLUDED.sheet_row
                WHERE group_memberships.lessons_done IS DISTINCT FROM EXCLUDED.lessons_done
                   OR group_memberships.start_date   IS DISTINCT FROM EXCLUDED.start_date
                   OR group_memberships.sheet_row    IS DISTINCT FROM EXCLUDED.sheet_row
                RETURNING (xmax = 0) AS inserted
                """,
                {
                    'group_name': m['group_name'], 'student_name': m['student_name'],
                    'lessons_done': m['lessons_done'], 'start_date': m['start_date'],
                    'sheet_row': m['sheet_row'],
                },
            )
            row = cur.fetchone()
            if row is None:
                result['memberships_skipped'] += 1
            elif row[0]:
                result['memberships_inserted'] += 1
            else:
                result['memberships_updated'] += 1

    return result
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_backfill_students.py -v
```

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/sync/backfills/students.py journal_django/apps/sync/tests/test_backfill_students.py
git commit -m "feat(sync): port backfill-students.js to Python"
```

---

## Task 8: `backfills/lessons.py`

**Files:**
- Create: `journal_django/apps/sync/backfills/lessons.py`
- Test: `journal_django/apps/sync/tests/test_backfill_lessons.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_backfill_lessons.py
import pytest
from django.db import connection

from apps.sync.backfills import lessons


def _row(date='13.07.2026', teacher='Петрова', group='Группа A', num='1', student='Иванов',
         status='Был', token='TOK1', record='', type_label='', original=''):
    return [date, teacher, group, num, student, status, '', token, record, type_label, original]


def test_extract_lessons_basic():
    rows = [_row()]
    result = lessons.extract_lessons(rows)
    assert len(result['lessons']) == 1
    assert result['lessons'][0]['lesson_date'] == '2026-07-13'
    assert len(result['attendance']) == 1
    assert result['attendance'][0]['present'] is True


def test_extract_lessons_absent_status():
    rows = [_row(status='Не был')]
    result = lessons.extract_lessons(rows)
    assert result['attendance'][0]['present'] is False


def test_extract_lessons_skips_row_without_token():
    rows = [_row(token='')]
    result = lessons.extract_lessons(rows)
    assert result['lessons'] == []


def test_extract_lessons_dedupes_by_key_multiple_students():
    rows = [_row(student='Иванов'), _row(student='Сидоров')]
    result = lessons.extract_lessons(rows)
    assert len(result['lessons']) == 1
    assert len(result['attendance']) == 2


def test_extract_lessons_type_label():
    rows = [_row(type_label='Замена')]
    result = lessons.extract_lessons(rows)
    assert result['lessons'][0]['lesson_type'] == 'substitution'


@pytest.mark.django_db
def test_run_inserts_lesson_and_attendance(monkeypatch):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_l__') RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM directions LIMIT 1")
        direction_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes, lessons_per_week) "
            "VALUES ('__test_sync_group_l__', %s, %s, false, 90, 1) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name) VALUES ('__test_sync_student_l__') RETURNING id")
        student_id = cur.fetchone()[0]

    rows = [_row(teacher='__test_sync_teacher_l__', group='__test_sync_group_l__', student='__test_sync_student_l__')]
    monkeypatch.setattr(lessons.sheets_client, 'read_journal_range', lambda sheet, rng: rows if sheet == 'Журнал группы' else [])

    try:
        result = lessons.run(dry_run=False)
        assert result['lessons_inserted'] == 1
        assert result['attendance_inserted'] == 1
    finally:
        with connection.cursor() as cur:
            cur.execute(
                "DELETE FROM lesson_attendance WHERE student_id = %s", [student_id])
            cur.execute("DELETE FROM lessons WHERE group_id = %s", [group_id])
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])
            cur.execute("DELETE FROM groups WHERE id = %s", [group_id])
            cur.execute("DELETE FROM teachers WHERE id = %s", [teacher_id])
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_backfill_lessons.py -v
```

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/backfills/lessons.py
"""Backfill занятий и посещаемости из Google Sheets. Порт scripts/backfill-lessons.js."""
from __future__ import annotations

from django.db import connection

from apps.sync import sheets_client
from apps.sync.backfills.dates import parse_lesson_date
from apps.sync.backfills.rows import cell, parse_float


def _lesson_type_from_label(label: str) -> str:
    if label == 'Замена':
        return 'substitution'
    if label == 'Перенос':
        return 'reschedule'
    return 'regular'


def extract_lessons(rows: list[list]) -> dict:
    lessons_map: dict[str, dict] = {}
    attendance: list[dict] = []

    for row in rows:
        if not row:
            continue
        date = parse_lesson_date(cell(row, 0))
        teacher = cell(row, 1)
        group = cell(row, 2)
        lesson_num = parse_float(cell(row, 3))
        student = cell(row, 4)
        status = cell(row, 5)
        token = cell(row, 7)
        record = cell(row, 8)
        type_label = cell(row, 9)
        original = cell(row, 10)

        if not date or not teacher or not group or lesson_num is None or not student or not token:
            continue

        key = f'{date}|{group}|{lesson_num}|{token}'
        if key not in lessons_map:
            lessons_map[key] = {
                'lesson_date': date,
                'teacher_name': teacher,
                'group_name': group,
                'lesson_number': lesson_num,
                'submitted_by_token': token,
                'record_url': record or None,
                'lesson_type': _lesson_type_from_label(type_label),
                'original_teacher_name': original or None,
            }

        attendance.append({
            'lesson_key': key,
            'student_name': student,
            'present': status == 'Был',
        })

    return {'lessons': list(lessons_map.values()), 'attendance': attendance}


def run(dry_run: bool = False) -> dict:
    result = {
        'entity': 'lessons+attendance',
        'lessons_read': 0, 'lessons_inserted': 0, 'lessons_skipped': 0,
        'attendance_read': 0, 'attendance_inserted': 0, 'attendance_skipped': 0,
        'dry_run': dry_run,
    }

    group_rows = sheets_client.read_journal_range('Журнал группы', 'A2:K')
    indiv_rows = sheets_client.read_journal_range('Журнал индивы', 'A2:K')
    extracted = extract_lessons(group_rows + indiv_rows)
    lessons_data = extracted['lessons']
    attendance = extracted['attendance']
    result['lessons_read'] = len(lessons_data)
    result['attendance_read'] = len(attendance)

    if dry_run:
        return result

    lesson_id_by_key: dict[str, int] = {}

    with connection.cursor() as cur:
        for l in lessons_data:
            cur.execute(
                """
                WITH g AS (SELECT id, lesson_duration_minutes FROM groups WHERE name = %(group_name)s),
                     te AS (SELECT id FROM teachers WHERE name = %(teacher_name)s),
                     ot AS (SELECT id FROM teachers WHERE name = %(original)s)
                INSERT INTO lessons
                    (lesson_date, teacher_id, group_id, lesson_number,
                     lesson_duration_minutes, lesson_type, record_url,
                     submitted_by_token, original_teacher_id, submitted_at)
                SELECT %(lesson_date)s, te.id, g.id, %(lesson_number)s, g.lesson_duration_minutes,
                       %(lesson_type)s, %(record_url)s, %(token)s,
                       (SELECT id FROM ot), (%(lesson_date)s::date)::timestamptz
                FROM g, te
                ON CONFLICT (lesson_date, group_id, lesson_number, submitted_by_token) DO NOTHING
                RETURNING id
                """,
                {
                    'group_name': l['group_name'], 'teacher_name': l['teacher_name'],
                    'original': l['original_teacher_name'], 'lesson_date': l['lesson_date'],
                    'lesson_number': l['lesson_number'], 'lesson_type': l['lesson_type'],
                    'record_url': l['record_url'], 'token': l['submitted_by_token'],
                },
            )
            row = cur.fetchone()
            key = f"{l['lesson_date']}|{l['group_name']}|{l['lesson_number']}|{l['submitted_by_token']}"

            if row is None:
                cur.execute(
                    """
                    SELECT l.id FROM lessons l
                    JOIN groups g ON g.id = l.group_id
                    WHERE l.lesson_date = %s AND g.name = %s AND l.lesson_number = %s AND l.submitted_by_token = %s
                    """,
                    [l['lesson_date'], l['group_name'], l['lesson_number'], l['submitted_by_token']],
                )
                found = cur.fetchone()
                result['lessons_skipped'] += 1
                if found is None:
                    continue
                lesson_id_by_key[key] = found[0]
            else:
                lesson_id_by_key[key] = row[0]
                result['lessons_inserted'] += 1

        for a in attendance:
            lesson_id = lesson_id_by_key.get(a['lesson_key'])
            if lesson_id is None:
                result['attendance_skipped'] += 1
                continue
            cur.execute(
                """
                WITH s AS (SELECT id FROM students WHERE full_name = %s)
                INSERT INTO lesson_attendance (lesson_id, student_id, present)
                SELECT %s, s.id, %s FROM s
                ON CONFLICT (lesson_id, student_id) DO NOTHING
                """,
                [a['student_name'], lesson_id, a['present']],
            )
            if cur.rowcount > 0:
                result['attendance_inserted'] += 1
            else:
                result['attendance_skipped'] += 1

    return result
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_backfill_lessons.py -v
```

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/sync/backfills/lessons.py journal_django/apps/sync/tests/test_backfill_lessons.py
git commit -m "feat(sync): port backfill-lessons.js to Python"
```

---

## Task 9: `backfills/payments.py` (только режим `--append`)

**Files:**
- Create: `journal_django/apps/sync/backfills/payments.py`
- Test: `journal_django/apps/sync/tests/test_backfill_payments.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_backfill_payments.py
import pytest
from django.db import connection

from apps.sync.backfills import payments


def test_norm_name():
    assert payments.norm_name('  Пётр  Иванов ') == 'петр иванов'
    assert payments.norm_name('Алёна') == 'алена'


def test_parse_date_valid():
    assert payments.parse_date('13.07.2026') == '2026-07-13'


def test_parse_date_invalid():
    assert payments.parse_date('2026-07-13') is None
    assert payments.parse_date('') is None


def test_parse_amount_valid():
    assert payments.parse_amount('1 500,50') == 1500.5


def test_parse_amount_zero_or_negative_is_none():
    assert payments.parse_amount('0') is None
    assert payments.parse_amount('-100') is None
    assert payments.parse_amount('abc') is None


@pytest.mark.django_db
def test_run_inserts_payment_for_archived_direction(monkeypatch):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO students (full_name) VALUES ('__test_sync_pay_student__') RETURNING id")
        student_id = cur.fetchone()[0]

    rows = [['__test_sync_pay_student__', 'заметка', '5000', '13.07.2026', 'Архив']]
    monkeypatch.setattr(payments.sheets_client, 'read_journal_range', lambda *a: rows)

    try:
        result = payments.run(dry_run=False)
        assert result['inserted'] == 1
        assert result['archived'] == 1
        with connection.cursor() as cur:
            cur.execute(
                "SELECT total_amount, direction_id FROM payments WHERE student_id = %s AND created_by = 'backfill-script'",
                [student_id],
            )
            row = cur.fetchone()
            assert row is not None
            assert row[1] is None
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM payments WHERE student_id = %s", [student_id])
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])


@pytest.mark.django_db
def test_run_skips_unknown_student(monkeypatch):
    rows = [['__nonexistent_student__', '', '5000', '13.07.2026', 'Архив']]
    monkeypatch.setattr(payments.sheets_client, 'read_journal_range', lambda *a: rows)

    result = payments.run(dry_run=False)
    assert result['inserted'] == 0
    assert result['skipped'] == 1
    assert 'не найден' in result['skipped_details'][0]['reason']


@pytest.mark.django_db
def test_run_append_mode_skips_duplicates(monkeypatch):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO students (full_name) VALUES ('__test_sync_pay_dup__') RETURNING id")
        student_id = cur.fetchone()[0]

    rows = [['__test_sync_pay_dup__', '', '5000', '13.07.2026', 'Архив']]
    monkeypatch.setattr(payments.sheets_client, 'read_journal_range', lambda *a: rows)

    try:
        first = payments.run(dry_run=False)
        second = payments.run(dry_run=False)
        assert first['inserted'] == 1
        assert second['inserted'] == 0
        assert second['duplicate_skipped'] == 1
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM payments WHERE student_id = %s", [student_id])
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_backfill_payments.py -v
```

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/backfills/payments.py
"""Backfill оплат из Google Sheets — только режим --append (безопасный).

Порт scripts/backfill-payments.js в режиме --append. Режим --reset (удаление
старых backfill-записей и полная перезаливка) сознательно НЕ выставлен в
Celery-задачу/API — слишком рискован для кнопки в браузере (см. спеку).
Доступен только как ручная операция через Django shell/management command,
если понадобится.
"""
from __future__ import annotations

import re

from django.db import connection

from apps.sync import sheets_client
from apps.sync.backfills.rows import cell

SHEET_NAME = 'Свод оплат'
RANGE = 'A2:E'

_DATE_RE = re.compile(r'^(\d{2})\.(\d{2})\.(\d{4})$')


def norm_name(s) -> str:
    return ' '.join(str(s or '').lower().replace('ё', 'е').split())


def parse_date(raw) -> str | None:
    m = _DATE_RE.match(str(raw or '').strip())
    if not m:
        return None
    d, mo, y = m.groups()
    return f'{y}-{mo}-{d}'


def parse_amount(raw) -> float | None:
    s = str(raw or '').replace(' ', '').replace(',', '.')
    try:
        n = float(s)
    except ValueError:
        return None
    return n if n > 0 else None


def run(dry_run: bool = False) -> dict:
    result = {
        'name': 'payments', 'dry_run': dry_run,
        'rows_read': 0, 'inserted': 0, 'duplicate_skipped': 0, 'skipped': 0,
        'archived': 0, 'non_standard': 0, 'skipped_details': [],
    }

    rows = sheets_client.read_journal_range(SHEET_NAME, RANGE)
    result['rows_read'] = len(rows)

    with connection.cursor() as cur:
        cur.execute('SELECT id, full_name FROM students')
        student_idx: dict[str, list[int]] = {}
        for sid, full_name in cur.fetchall():
            student_idx.setdefault(norm_name(full_name), []).append(sid)

        cur.execute('SELECT id, name, subscription_price FROM directions')
        dir_idx = {norm_name(name): (did, price) for did, name, price in cur.fetchall()}

        existing_keys = set()
        cur.execute(
            "SELECT student_id, direction_id, total_amount, paid_at FROM payments WHERE created_by = 'backfill-script'"
        )
        for student_id, direction_id, total_amount, paid_at in cur.fetchall():
            existing_keys.add(f"{student_id}|{direction_id or 'null'}|{total_amount}|{paid_at}")

        for i, row in enumerate(rows):
            row_num = i + 2
            raw_name = cell(row, 0)
            raw_note = cell(row, 1)
            raw_amount = cell(row, 2)
            raw_date = cell(row, 3)
            raw_dir = cell(row, 4)

            if not raw_name and not raw_amount and not raw_date and not raw_dir:
                continue

            st_key = norm_name(raw_name)
            st_matches = student_idx.get(st_key, [])
            if len(st_matches) == 0:
                result['skipped_details'].append({'row': row_num, 'reason': f"ученик '{raw_name}' не найден"})
                result['skipped'] += 1
                continue
            if len(st_matches) > 1:
                result['skipped_details'].append(
                    {'row': row_num, 'reason': f"ученик '{raw_name}' — несколько матчей: {st_matches}"})
                result['skipped'] += 1
                continue
            student_id = st_matches[0]

            amount = parse_amount(raw_amount)
            if amount is None:
                result['skipped_details'].append({'row': row_num, 'reason': f"невалидная сумма '{raw_amount}'"})
                result['skipped'] += 1
                continue

            paid_at = parse_date(raw_date)
            if not paid_at:
                result['skipped_details'].append({'row': row_num, 'reason': f"невалидная дата '{raw_date}'"})
                result['skipped'] += 1
                continue

            dir_key = norm_name(raw_dir)
            direction_id = None
            subscriptions_count = None
            unit_price = amount

            if dir_key in ('архив', ''):
                result['archived'] += 1
            else:
                dir_row = dir_idx.get(dir_key)
                if dir_row is None:
                    result['skipped_details'].append({'row': row_num, 'reason': f"направление '{raw_dir}' не найдено"})
                    result['skipped'] += 1
                    continue
                direction_id, price = dir_row
                price = float(price) if price is not None else None
                if price and price > 0 and round(amount * 100) % round(price * 100) == 0:
                    subscriptions_count = round(round(amount * 100) / round(price * 100))
                    unit_price = price
                else:
                    subscriptions_count = 1
                    unit_price = amount
                    result['non_standard'] += 1

            price_final = round(float(unit_price), 2)
            total_final = (
                f'{price_final * subscriptions_count:.2f}'
                if subscriptions_count is not None
                else f'{price_final:.2f}'
            )

            key = f"{student_id}|{direction_id or 'null'}|{total_final}|{paid_at}"
            if key in existing_keys:
                result['duplicate_skipped'] += 1
                continue

            if dry_run:
                result['inserted'] += 1
                continue

            cur.execute(
                """
                INSERT INTO payments
                    (student_id, direction_id, subscriptions_count, unit_price, total_amount, paid_at, note, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'backfill-script')
                """,
                [student_id, direction_id, subscriptions_count, price_final, total_final, paid_at,
                 raw_note.strip() or None],
            )
            result['inserted'] += 1
            existing_keys.add(key)

    return result
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_backfill_payments.py -v
```

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/sync/backfills/payments.py journal_django/apps/sync/tests/test_backfill_payments.py
git commit -m "feat(sync): port backfill-payments.js (--append mode only) to Python"
```

---

## Task 10: `backfills/payroll.py`

**Files:**
- Create: `journal_django/apps/sync/backfills/payroll.py`
- Test: `journal_django/apps/sync/tests/test_backfill_payroll.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_backfill_payroll.py
import pytest
from django.db import connection

from apps.sync.backfills import payroll


def _row(date='13.07.2026', group='Группа A', num='1', total='2', present='2', payment='400', token='TOK1', penalty=''):
    row = [''] * 10
    row[0] = date
    row[2] = group
    row[3] = num
    row[4] = total
    row[5] = present
    row[6] = payment
    row[8] = token
    row[9] = penalty
    return row


def test_extract_payroll_basic():
    result = payroll.extract_payroll([_row()])
    assert len(result) == 1
    assert result[0]['lesson_date'] == '2026-07-13'
    assert result[0]['payment'] == 400.0
    assert result[0]['penalty'] == 0.0


def test_extract_payroll_with_penalty():
    result = payroll.extract_payroll([_row(penalty='40')])
    assert result[0]['penalty'] == 40.0


def test_extract_payroll_skips_row_without_token():
    result = payroll.extract_payroll([_row(token='')])
    assert result == []


def test_extract_payroll_skips_non_numeric_total():
    result = payroll.extract_payroll([_row(total='n/a')])
    assert result == []


@pytest.mark.django_db
def test_run_inserts_payroll_row(monkeypatch):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_p__') RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM directions LIMIT 1")
        direction_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes, lessons_per_week) "
            "VALUES ('__test_sync_group_p__', %s, %s, false, 90, 1) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lessons (lesson_date, teacher_id, group_id, lesson_number, lesson_duration_minutes, "
            "lesson_type, submitted_by_token, submitted_at) "
            "VALUES ('2026-07-13', %s, %s, 1, 90, 'regular', 'TOK1', now()) RETURNING id",
            [teacher_id, group_id],
        )
        lesson_id = cur.fetchone()[0]

    rows = [_row(group='__test_sync_group_p__')]
    monkeypatch.setattr(payroll.sheets_client, 'read_journal_range', lambda *a: rows)

    try:
        result = payroll.run(dry_run=False)
        assert result['inserted'] == 1
        with connection.cursor() as cur:
            cur.execute("SELECT payment FROM payroll WHERE lesson_id = %s", [lesson_id])
            assert cur.fetchone()[0] == 400
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM payroll WHERE lesson_id = %s", [lesson_id])
            cur.execute("DELETE FROM lessons WHERE id = %s", [lesson_id])
            cur.execute("DELETE FROM groups WHERE id = %s", [group_id])
            cur.execute("DELETE FROM teachers WHERE id = %s", [teacher_id])
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_backfill_payroll.py -v
```

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/backfills/payroll.py
"""Backfill зарплаты из Google Sheets. Порт scripts/backfill-payroll.js."""
from __future__ import annotations

from django.db import connection

from apps.sync import sheets_client
from apps.sync.backfills.dates import parse_lesson_date
from apps.sync.backfills.rows import cell, parse_float, parse_int


def extract_payroll(rows: list[list]) -> list[dict]:
    out = []
    for row in rows:
        if not row:
            continue
        date = parse_lesson_date(cell(row, 0))
        group = cell(row, 2)
        lesson_num = parse_float(cell(row, 3))
        total = parse_int(cell(row, 4))
        present = parse_int(cell(row, 5))
        payment = parse_float(cell(row, 6))
        token = cell(row, 8)
        penalty_raw = cell(row, 9)

        if not date or not group or lesson_num is None or not token:
            continue
        if total is None or present is None or payment is None:
            continue

        out.append({
            'lesson_date': date,
            'group_name': group,
            'lesson_number': lesson_num,
            'submitted_by_token': token,
            'total_students': total,
            'present_count': present,
            'payment': payment,
            'penalty': parse_float(penalty_raw) or 0.0,
        })
    return out


def run(dry_run: bool = False) -> dict:
    result = {
        'entity': 'payroll', 'read': 0, 'inserted': 0, 'updated': 0,
        'skipped': 0, 'no_lesson': 0, 'dry_run': dry_run,
    }

    rows = sheets_client.read_journal_range('Зарплата', 'A2:L')
    payroll_data = extract_payroll(rows)
    result['read'] = len(payroll_data)

    if dry_run:
        return result

    with connection.cursor() as cur:
        for p in payroll_data:
            cur.execute(
                """
                WITH l AS (
                    SELECT l.id, l.teacher_id FROM lessons l
                    JOIN groups g ON g.id = l.group_id
                    WHERE l.lesson_date = %(lesson_date)s AND g.name = %(group_name)s
                      AND l.lesson_number = %(lesson_number)s AND l.submitted_by_token = %(token)s
                )
                INSERT INTO payroll (lesson_id, teacher_id, total_students, present_count, payment, penalty)
                SELECT l.id, l.teacher_id, %(total)s, %(present)s, %(payment)s, %(penalty)s FROM l
                ON CONFLICT (lesson_id) DO UPDATE SET
                    total_students = EXCLUDED.total_students,
                    present_count  = EXCLUDED.present_count,
                    payment        = EXCLUDED.payment,
                    penalty        = EXCLUDED.penalty
                WHERE payroll.total_students IS DISTINCT FROM EXCLUDED.total_students
                   OR payroll.present_count  IS DISTINCT FROM EXCLUDED.present_count
                   OR payroll.payment        IS DISTINCT FROM EXCLUDED.payment
                   OR payroll.penalty        IS DISTINCT FROM EXCLUDED.penalty
                RETURNING (xmax = 0) AS inserted
                """,
                {
                    'lesson_date': p['lesson_date'], 'group_name': p['group_name'],
                    'lesson_number': p['lesson_number'], 'token': p['submitted_by_token'],
                    'total': p['total_students'], 'present': p['present_count'],
                    'payment': p['payment'], 'penalty': p['penalty'],
                },
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    """
                    SELECT 1 FROM lessons l JOIN groups g ON g.id = l.group_id
                    WHERE l.lesson_date = %s AND g.name = %s AND l.lesson_number = %s AND l.submitted_by_token = %s
                    """,
                    [p['lesson_date'], p['group_name'], p['lesson_number'], p['submitted_by_token']],
                )
                if cur.fetchone() is None:
                    result['no_lesson'] += 1
                else:
                    result['skipped'] += 1
            elif row[0]:
                result['inserted'] += 1
            else:
                result['updated'] += 1

    return result
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_backfill_payroll.py -v
```

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/sync/backfills/payroll.py journal_django/apps/sync/tests/test_backfill_payroll.py
git commit -m "feat(sync): port backfill-payroll.js to Python"
```

---

## Task 11: `backfills/rebuild_payroll.py`

**Files:**
- Create: `journal_django/apps/sync/backfills/rebuild_payroll.py`
- Test: `journal_django/apps/sync/tests/test_rebuild_payroll.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_rebuild_payroll.py
import pytest
from django.db import connection

from apps.sync.backfills import rebuild_payroll


@pytest.mark.django_db
def test_run_computes_payment_from_attendance():
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_rp__') RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM directions LIMIT 1")
        direction_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes, lessons_per_week) "
            "VALUES ('__test_sync_group_rp__', %s, %s, false, 90, 1) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name) VALUES ('__test_sync_student_rp__') RETURNING id")
        student_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lessons (lesson_date, teacher_id, group_id, lesson_number, lesson_duration_minutes, "
            "lesson_type, submitted_by_token, submitted_at) "
            "VALUES ('2026-07-13', %s, %s, 1, 90, 'regular', 'TOKRP', "
            "'2026-07-13T12:00:00+03:00'::timestamptz) RETURNING id",
            [teacher_id, group_id],
        )
        lesson_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s, %s, true)",
            [lesson_id, student_id],
        )

    try:
        result = rebuild_payroll.run(dry_run=False)
        assert result['inserted'] >= 1
        with connection.cursor() as cur:
            cur.execute("SELECT payment, penalty FROM payroll WHERE lesson_id = %s", [lesson_id])
            payment, penalty = cur.fetchone()
            assert payment == 500  # total=1, present=1 → smallGroup rate (total<=2, все пришли)
            assert penalty == 0    # submitted_at date == lesson_date
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM payroll WHERE lesson_id = %s", [lesson_id])
            cur.execute("DELETE FROM lesson_attendance WHERE lesson_id = %s", [lesson_id])
            cur.execute("DELETE FROM lessons WHERE id = %s", [lesson_id])
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])
            cur.execute("DELETE FROM groups WHERE id = %s", [group_id])
            cur.execute("DELETE FROM teachers WHERE id = %s", [teacher_id])


@pytest.mark.django_db
def test_run_dry_run_does_not_write():
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_rpd__') RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM directions LIMIT 1")
        direction_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes, lessons_per_week) "
            "VALUES ('__test_sync_group_rpd__', %s, %s, false, 90, 1) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name) VALUES ('__test_sync_student_rpd__') RETURNING id")
        student_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lessons (lesson_date, teacher_id, group_id, lesson_number, lesson_duration_minutes, "
            "lesson_type, submitted_by_token, submitted_at) "
            "VALUES ('2026-07-13', %s, %s, 1, 90, 'regular', 'TOKRPD', now()) RETURNING id",
            [teacher_id, group_id],
        )
        lesson_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s, %s, true)",
            [lesson_id, student_id],
        )

    try:
        rebuild_payroll.run(dry_run=True)
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM payroll WHERE lesson_id = %s", [lesson_id])
            assert cur.fetchone() is None
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM lesson_attendance WHERE lesson_id = %s", [lesson_id])
            cur.execute("DELETE FROM lessons WHERE id = %s", [lesson_id])
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])
            cur.execute("DELETE FROM groups WHERE id = %s", [group_id])
            cur.execute("DELETE FROM teachers WHERE id = %s", [teacher_id])
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_rebuild_payroll.py -v
```

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/backfills/rebuild_payroll.py
"""Пересчёт зарплаты из lessons+lesson_attendance (Sheets не трогает). Порт scripts/rebuild-payroll.js.

Переиспользует уже существующий Python-порт calculate_payment
(apps.teacher_spa.calculator) — второй раз эту логику не пишем.
"""
from __future__ import annotations

from django.db import connection

from apps.teacher_spa.calculator import calculate_payment


def run(dry_run: bool = False) -> dict:
    result = {
        'entity': 'payroll-rebuild', 'lessons_seen': 0, 'inserted': 0, 'updated': 0,
        'unchanged': 0, 'skipped_no_attendance': 0, 'dry_run': dry_run,
    }

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT l.id, l.teacher_id, l.lesson_duration_minutes,
                   to_char(l.lesson_date, 'YYYY-MM-DD') AS lesson_date_str,
                   to_char((l.submitted_at AT TIME ZONE 'Europe/Moscow'), 'YYYY-MM-DD') AS submit_msk_date,
                   COUNT(la.*)::int AS total_students,
                   COALESCE(SUM(CASE WHEN la.present THEN 1 ELSE 0 END), 0)::int AS present_count
            FROM lessons l
            LEFT JOIN lesson_attendance la ON la.lesson_id = l.id
            GROUP BY l.id
            ORDER BY l.lesson_date, l.id
            """
        )
        rows = cur.fetchall()
        result['lessons_seen'] = len(rows)

        for lesson_id, teacher_id, duration, lesson_date_str, submit_date, total, present in rows:
            if total == 0:
                result['skipped_no_attendance'] += 1
                continue

            is_half = duration == 45
            payment = calculate_payment(total, present, is_half)
            penalty = 0 if submit_date == lesson_date_str else 40

            if dry_run:
                continue

            cur.execute(
                """
                INSERT INTO payroll (lesson_id, teacher_id, total_students, present_count, payment, penalty)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (lesson_id) DO UPDATE SET
                    teacher_id     = EXCLUDED.teacher_id,
                    total_students = EXCLUDED.total_students,
                    present_count  = EXCLUDED.present_count,
                    payment        = EXCLUDED.payment,
                    penalty        = EXCLUDED.penalty
                WHERE payroll.teacher_id     IS DISTINCT FROM EXCLUDED.teacher_id
                   OR payroll.total_students IS DISTINCT FROM EXCLUDED.total_students
                   OR payroll.present_count  IS DISTINCT FROM EXCLUDED.present_count
                   OR payroll.payment        IS DISTINCT FROM EXCLUDED.payment
                   OR payroll.penalty        IS DISTINCT FROM EXCLUDED.penalty
                RETURNING (xmax = 0) AS inserted
                """,
                [lesson_id, teacher_id, total, present, payment, penalty],
            )
            row = cur.fetchone()
            if row is None:
                result['unchanged'] += 1
            elif row[0]:
                result['inserted'] += 1
            else:
                result['updated'] += 1

    return result
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_rebuild_payroll.py -v
```

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/sync/backfills/rebuild_payroll.py journal_django/apps/sync/tests/test_rebuild_payroll.py
git commit -m "feat(sync): port rebuild-payroll.js to Python"
```

---

## Task 12: `backfills/rebuild_counters.py`

**Files:**
- Create: `journal_django/apps/sync/backfills/rebuild_counters.py`
- Test: `journal_django/apps/sync/tests/test_rebuild_counters.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_rebuild_counters.py
import pytest
from django.db import connection


from apps.sync.backfills import rebuild_counters


@pytest.mark.django_db
def test_run_fixes_drifted_counter():
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_rc__') RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM directions LIMIT 1")
        direction_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes, lessons_per_week) "
            "VALUES ('__test_sync_group_rc__', %s, %s, false, 90, 1) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name) VALUES ('__test_sync_student_rc__') RETURNING id")
        student_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s, %s, 0, true) RETURNING id",
            [group_id, student_id],
        )
        membership_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lessons (lesson_date, teacher_id, group_id, lesson_number, lesson_duration_minutes, "
            "lesson_type, submitted_by_token, submitted_at) "
            "VALUES ('2026-07-13', %s, %s, 1, 90, 'regular', 'TOKRC', now()) RETURNING id",
            [teacher_id, group_id],
        )
        lesson_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s, %s, true)",
            [lesson_id, student_id],
        )

    try:
        result = rebuild_counters.run(dry_run=False)
        assert result['updated'] >= 1
        with connection.cursor() as cur:
            cur.execute("SELECT lessons_done FROM group_memberships WHERE id = %s", [membership_id])
            assert float(cur.fetchone()[0]) == 1.0
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM lesson_attendance WHERE lesson_id = %s", [lesson_id])
            cur.execute("DELETE FROM lessons WHERE id = %s", [lesson_id])
            cur.execute("DELETE FROM group_memberships WHERE id = %s", [membership_id])
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])
            cur.execute("DELETE FROM groups WHERE id = %s", [group_id])
            cur.execute("DELETE FROM teachers WHERE id = %s", [teacher_id])


@pytest.mark.django_db
def test_run_dry_run_reports_drift_without_writing():
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_rcd__') RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM directions LIMIT 1")
        direction_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, lesson_duration_minutes, lessons_per_week) "
            "VALUES ('__test_sync_group_rcd__', %s, %s, false, 45, 1) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name) VALUES ('__test_sync_student_rcd__') RETURNING id")
        student_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s, %s, 0, true) RETURNING id",
            [group_id, student_id],
        )
        membership_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lessons (lesson_date, teacher_id, group_id, lesson_number, lesson_duration_minutes, "
            "lesson_type, submitted_by_token, submitted_at) "
            "VALUES ('2026-07-13', %s, %s, 1, 45, 'regular', 'TOKRCD', now()) RETURNING id",
            [teacher_id, group_id],
        )
        lesson_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s, %s, true)",
            [lesson_id, student_id],
        )

    try:
        result = rebuild_counters.run(dry_run=True)
        assert result['updated'] == 0
        assert any(d['membership_id'] == membership_id and d['delta'] == 0.5 for d in result['top_drifts'])
        with connection.cursor() as cur:
            cur.execute("SELECT lessons_done FROM group_memberships WHERE id = %s", [membership_id])
            assert float(cur.fetchone()[0]) == 0.0
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM lesson_attendance WHERE lesson_id = %s", [lesson_id])
            cur.execute("DELETE FROM lessons WHERE id = %s", [lesson_id])
            cur.execute("DELETE FROM group_memberships WHERE id = %s", [membership_id])
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])
            cur.execute("DELETE FROM groups WHERE id = %s", [group_id])
            cur.execute("DELETE FROM teachers WHERE id = %s", [teacher_id])
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_rebuild_counters.py -v
```

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/backfills/rebuild_counters.py
"""Пересчёт group_memberships.lessons_done из lesson_attendance. Порт scripts/rebuild-counters.js."""
from __future__ import annotations

from django.db import connection


def run(dry_run: bool = False) -> dict:
    result = {
        'entity': 'counters-rebuild', 'memberships_total': 0, 'updated': 0,
        'unchanged': 0, 'dry_run': dry_run, 'top_drifts': [],
    }

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT gm.id, gm.lessons_done AS stored,
                   COALESCE(SUM(
                     CASE WHEN la.present THEN
                       CASE WHEN l.lesson_duration_minutes = 45 THEN 0.5 ELSE 1 END
                     ELSE 0 END
                   ), 0)::numeric(6,1) AS calculated,
                   s.full_name AS student_name, g.name AS group_name
              FROM group_memberships gm
              JOIN students s ON s.id = gm.student_id
              JOIN groups   g ON g.id = gm.group_id
              LEFT JOIN lessons l ON l.group_id = gm.group_id
              LEFT JOIN lesson_attendance la ON la.lesson_id = l.id AND la.student_id = gm.student_id
             GROUP BY gm.id, gm.lessons_done, s.full_name, g.name
             ORDER BY gm.id
            """
        )
        rows = cur.fetchall()
        result['memberships_total'] = len(rows)

        drifts = []
        for membership_id, stored, calculated, student_name, group_name in rows:
            stored = float(stored)
            calculated = float(calculated)
            if stored == calculated:
                result['unchanged'] += 1
                continue

            drifts.append({
                'membership_id': membership_id, 'student': student_name, 'group': group_name,
                'stored': stored, 'calculated': calculated,
                'delta': round(calculated - stored, 1),
            })

            if not dry_run:
                cur.execute(
                    'UPDATE group_memberships SET lessons_done = %s WHERE id = %s',
                    [calculated, membership_id],
                )
                result['updated'] += 1

        drifts.sort(key=lambda d: abs(d['delta']), reverse=True)
        result['top_drifts'] = drifts[:20]

    return result
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_rebuild_counters.py -v
```

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/sync/backfills/rebuild_counters.py journal_django/apps/sync/tests/test_rebuild_counters.py
git commit -m "feat(sync): port rebuild-counters.js to Python"
```

---

## Task 13: `backfills/run_all.py`

**Files:**
- Create: `journal_django/apps/sync/backfills/run_all.py`
- Test: `journal_django/apps/sync/tests/test_run_all.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_run_all.py
from apps.sync.backfills import run_all


def test_run_all_calls_steps_in_order(monkeypatch):
    call_order = []

    def make_fake(name):
        def fake_run(dry_run=False):
            call_order.append(name)
            return {'entity': name, 'dry_run': dry_run}
        return fake_run

    for step_name, module in run_all.STEPS:
        monkeypatch.setattr(module, 'run', make_fake(step_name))

    result = run_all.run(dry_run=True)

    assert call_order == ['teachers', 'groups', 'students', 'lessons', 'payroll']
    assert result['dry_run'] is True
    assert len(result['steps']) == 5
    assert all(step['dry_run'] is True for step in result['steps'])


def test_run_all_does_not_include_payments():
    step_names = [name for name, _ in run_all.STEPS]
    assert 'payments' not in step_names
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_run_all.py -v
```

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/backfills/run_all.py
"""Оркестратор: teachers → groups → students → lessons → payroll. Порт scripts/backfill-all.js.

payments сюда намеренно не входит — как и в оригинальном backfill-all.js.
"""
from __future__ import annotations

from apps.sync.backfills import groups, lessons, payroll, students, teachers

STEPS = [
    ('teachers', teachers),
    ('groups', groups),
    ('students', students),
    ('lessons', lessons),
    ('payroll', payroll),
]


def run(dry_run: bool = False) -> dict:
    results = [module.run(dry_run=dry_run) for _, module in STEPS]
    return {'dry_run': dry_run, 'steps': results}
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_run_all.py -v
```

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/sync/backfills/run_all.py journal_django/apps/sync/tests/test_run_all.py
git commit -m "feat(sync): port backfill-all.js orchestrator to Python"
```

---

## Task 14: `tasks.py` — Celery-обёртки

**Files:**
- Create: `journal_django/apps/sync/tasks.py`
- Test: `journal_django/apps/sync/tests/test_tasks.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_tasks.py
import pytest

from apps.sync import tasks


@pytest.mark.django_db
def test_backfill_teachers_task_delegates(monkeypatch):
    monkeypatch.setattr(
        'apps.sync.backfills.teachers.run',
        lambda dry_run=False: {'entity': 'teachers', 'dry_run': dry_run},
    )
    result = tasks.backfill_teachers_task.run(dry_run=True)
    assert result == {'entity': 'teachers', 'dry_run': True}


@pytest.mark.django_db
def test_run_all_task_delegates(monkeypatch):
    monkeypatch.setattr(
        'apps.sync.backfills.run_all.run',
        lambda dry_run=False: {'dry_run': dry_run, 'steps': []},
    )
    result = tasks.run_all_task.run(dry_run=False)
    assert result == {'dry_run': False, 'steps': []}
```

(Остальные 6 задач по аналогии не тестируются отдельно юнит-тестом здесь — они однострочные
делегирующие обёртки, покрываются интеграционными тестами `SyncRunView` в Task 15.)

- [ ] **Step 2: Убедиться, что тест падает**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_tasks.py -v
```

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/tasks.py
"""Celery-задачи apps.sync — обёртки над backfills/*.py.

Очередь 'default' (не 'interactive') — не конкурируют с OTP-письмами входа за
приоритет. time_limit с запасом под реальный объём данных из Google Sheets;
run_all-задача самая долгая (5 шагов подряд).
"""
from __future__ import annotations

from celery import shared_task

from apps.sync.backfills import (
    groups, lessons, payments, payroll, rebuild_counters, rebuild_payroll, run_all, students, teachers,
)


@shared_task(name='apps.sync.tasks.backfill_teachers_task', time_limit=120)
def backfill_teachers_task(dry_run: bool = False) -> dict:
    return teachers.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.backfill_groups_task', time_limit=120)
def backfill_groups_task(dry_run: bool = False) -> dict:
    return groups.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.backfill_students_task', time_limit=180)
def backfill_students_task(dry_run: bool = False) -> dict:
    return students.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.backfill_lessons_task', time_limit=300)
def backfill_lessons_task(dry_run: bool = False) -> dict:
    return lessons.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.backfill_payments_task', time_limit=180)
def backfill_payments_task(dry_run: bool = False) -> dict:
    return payments.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.backfill_payroll_task', time_limit=180)
def backfill_payroll_task(dry_run: bool = False) -> dict:
    return payroll.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.rebuild_payroll_task', time_limit=180)
def rebuild_payroll_task(dry_run: bool = False) -> dict:
    return rebuild_payroll.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.rebuild_counters_task', time_limit=180)
def rebuild_counters_task(dry_run: bool = False) -> dict:
    return rebuild_counters.run(dry_run=dry_run)


@shared_task(name='apps.sync.tasks.run_all_task', time_limit=600)
def run_all_task(dry_run: bool = False) -> dict:
    return run_all.run(dry_run=dry_run)
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_tasks.py -v
```

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/sync/tasks.py journal_django/apps/sync/tests/test_tasks.py
git commit -m "feat(sync): add Celery task wrappers for all 9 sync actions"
```

---

## Task 15: `views.py` + `urls.py` — API

**Files:**
- Create: `journal_django/apps/sync/views.py`
- Modify: `journal_django/apps/sync/urls.py`
- Test: `journal_django/apps/sync/tests/test_views.py`

- [ ] **Step 1: Написать падающий тест**

```python
# journal_django/apps/sync/tests/test_views.py
import pytest


@pytest.mark.django_db
def test_run_requires_superadmin(admin_client):
    """admin (не superadmin) не должен пройти — см. apps.core.permissions.IsSuperAdmin."""
    resp = admin_client.post('/api/admin/sync/teachers/run', {'dry_run': True}, format='json')
    assert resp.status_code == 403


@pytest.mark.django_db
def test_run_rejects_anonymous(anon_client):
    resp = anon_client.post('/api/admin/sync/teachers/run', {'dry_run': True}, format='json')
    assert resp.status_code == 401


@pytest.mark.django_db
def test_run_unknown_action_404(superadmin_client):
    resp = superadmin_client.post('/api/admin/sync/does-not-exist/run', {'dry_run': True}, format='json')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_run_and_status_happy_path(superadmin_client, monkeypatch):
    """CELERY_TASK_ALWAYS_EAGER=True в тестах (нет REDIS_URL) — .delay() выполняется
    синхронно; CELERY_TASK_STORE_EAGER_RESULT=True (Task 1) кладёт результат в backend,
    поэтому последующий GET .../status/<task_id> его находит."""
    monkeypatch.setattr(
        'apps.sync.backfills.teachers.run',
        lambda dry_run=False: {'entity': 'teachers', 'read': 3, 'inserted': 3, 'dry_run': dry_run},
    )

    run_resp = superadmin_client.post('/api/admin/sync/teachers/run', {'dry_run': True}, format='json')
    assert run_resp.status_code == 202
    task_id = run_resp.data['task_id']
    assert task_id

    status_resp = superadmin_client.get(f'/api/admin/sync/status/{task_id}')
    assert status_resp.status_code == 200
    assert status_resp.data['state'] == 'SUCCESS'
    assert status_resp.data['result'] == {'entity': 'teachers', 'read': 3, 'inserted': 3, 'dry_run': True}
    assert status_resp.data['error'] is None


@pytest.mark.django_db
def test_status_reports_failure(superadmin_client, monkeypatch):
    def boom(dry_run=False):
        raise RuntimeError('лист не найден')

    monkeypatch.setattr('apps.sync.backfills.teachers.run', boom)

    run_resp = superadmin_client.post('/api/admin/sync/teachers/run', {'dry_run': False}, format='json')
    task_id = run_resp.data['task_id']

    status_resp = superadmin_client.get(f'/api/admin/sync/status/{task_id}')
    assert status_resp.data['state'] == 'FAILURE'
    assert 'лист не найден' in status_resp.data['error']
```

- [ ] **Step 2: Убедиться, что тест падает**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_views.py -v
```

Ожидание: 404 на все запросы (`urls.py` пуст с Task 1) или `ImportError`.

- [ ] **Step 3: Реализация**

```python
# journal_django/apps/sync/views.py
"""SyncRunView/SyncStatusView — триггер и опрос статуса sync-задач (только IsSuperAdmin)."""
from __future__ import annotations

from celery.result import AsyncResult
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import log_event
from apps.core.permissions import IsSuperAdmin
from apps.sync import tasks

ACTIONS = {
    'teachers': tasks.backfill_teachers_task,
    'groups': tasks.backfill_groups_task,
    'students': tasks.backfill_students_task,
    'lessons': tasks.backfill_lessons_task,
    'payments': tasks.backfill_payments_task,
    'payroll': tasks.backfill_payroll_task,
    'rebuild-payroll': tasks.rebuild_payroll_task,
    'rebuild-counters': tasks.rebuild_counters_task,
    'run-all': tasks.run_all_task,
}


class SyncRunView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request: Request, action: str) -> Response:
        task_fn = ACTIONS.get(action)
        if task_fn is None:
            raise NotFound({'error': f'Unknown sync action: {action}'})

        dry_run = bool(request.data.get('dry_run', False))
        async_result = task_fn.delay(dry_run=dry_run)

        log_event(
            'sync.run',
            account_id=getattr(request.user, 'id', None),
            actor_email=getattr(request.user, 'email', None),
            meta={'action': action, 'dry_run': dry_run, 'task_id': async_result.id},
            request=request,
        )
        return Response({'task_id': async_result.id}, status=status.HTTP_202_ACCEPTED)


class SyncStatusView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request: Request, task_id: str) -> Response:
        # Celery не различает "неизвестный task_id" и "ещё не начатую задачу" —
        # оба случая отдают PENDING (ограничение AsyncResult API). На практике не
        # проблема: task_id всегда приходит из предшествующего POST .../run.
        result = AsyncResult(task_id)
        payload = {'state': result.state, 'result': None, 'error': None}
        if result.state == 'SUCCESS':
            payload['result'] = result.result
        elif result.state == 'FAILURE':
            payload['error'] = str(result.result)
        return Response(payload)
```

```python
# journal_django/apps/sync/urls.py (заменить заготовку из Task 1)
"""Маршруты sync. APPEND_SLASH=False — без trailing slash."""
from django.urls import path

from apps.sync.views import SyncRunView, SyncStatusView

urlpatterns = [
    path('/status/<str:task_id>', SyncStatusView.as_view(), name='sync-status'),
    path('/<str:action>/run', SyncRunView.as_view(), name='sync-run'),
]
```

- [ ] **Step 4: Убедиться, что тест проходит**

```bash
.venv/Scripts/python.exe -m pytest apps/sync/tests/test_views.py -v
```

- [ ] **Step 5: Прогнать все тесты `apps.sync` разом**

```bash
.venv/Scripts/python.exe -m pytest apps/sync -v
```

Ожидание: все тесты `PASSED` (порядка 45-55 тестов из Tasks 2-15).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/sync/views.py journal_django/apps/sync/urls.py journal_django/apps/sync/tests/test_views.py
git commit -m "feat(sync): add SyncRunView/SyncStatusView API + audit logging"
```

---

## Task 16: Фронтенд — типы и API-клиент (`lib/sync.ts`)

**Files:**
- Create: `journal_django/frontend/admin-src/src/lib/sync.ts`

Чисто типы/константы, без обращения к сети — юнит-тестов не требует (нет логики,
кроме статичного списка). Проверяется компиляцией TypeScript в Task 20.

- [ ] **Step 1: Создать файл**

```typescript
// journal_django/frontend/admin-src/src/lib/sync.ts
export type SyncAction =
  | 'teachers' | 'groups' | 'students' | 'lessons' | 'payments' | 'payroll'
  | 'rebuild-payroll' | 'rebuild-counters' | 'run-all';

export interface SyncActionDef {
  action: SyncAction;
  label: string;
  group: 'run-all' | 'sheets' | 'rebuild';
}

export const SYNC_ACTIONS: SyncActionDef[] = [
  { action: 'run-all', label: 'Запустить всё (teachers→groups→students→lessons→payroll)', group: 'run-all' },
  { action: 'teachers', label: 'Преподаватели', group: 'sheets' },
  { action: 'groups', label: 'Группы', group: 'sheets' },
  { action: 'students', label: 'Ученики + абонементы', group: 'sheets' },
  { action: 'lessons', label: 'Занятия + посещаемость', group: 'sheets' },
  { action: 'payments', label: 'Оплаты (только новые)', group: 'sheets' },
  { action: 'payroll', label: 'Зарплата', group: 'sheets' },
  { action: 'rebuild-payroll', label: 'Зарплата по урокам (пересчёт)', group: 'rebuild' },
  { action: 'rebuild-counters', label: 'Счётчики уроков групп (пересчёт)', group: 'rebuild' },
];

export type SyncTaskState = 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE';

export interface SyncStatus {
  state: SyncTaskState;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface SyncRunResponse {
  task_id: string;
}
```

- [ ] **Step 2: Commit**

```bash
git add journal_django/frontend/admin-src/src/lib/sync.ts
git commit -m "feat(sync): add frontend types for sync actions/status"
```

---

## Task 17: Фронтенд — `useSyncAction` хук

**Files:**
- Create: `journal_django/frontend/admin-src/src/hooks/useSyncAction.ts`

- [ ] **Step 1: Реализация**

```typescript
// journal_django/frontend/admin-src/src/hooks/useSyncAction.ts
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { SyncAction, SyncRunResponse, SyncStatus } from '../lib/sync';

const TERMINAL_STATES = new Set(['SUCCESS', 'FAILURE']);

/**
 * Инкапсулирует триггер (POST .../run) и поллинг статуса (GET .../status/<task_id>)
 * для одного действия раздела «Синхро». taskId живёт только в памяти компонента —
 * уход со страницы сбрасывает его (история запусков сознательно не персистится).
 */
export function useSyncAction(action: SyncAction) {
  const [taskId, setTaskId] = useState<string | null>(null);

  const trigger = useMutation({
    mutationFn: (dryRun: boolean) =>
      api<SyncRunResponse>('POST', `/api/admin/sync/${action}/run`, { dry_run: dryRun }),
    onSuccess: (data) => setTaskId(data.task_id),
  });

  const statusQuery = useQuery({
    queryKey: ['sync-status', taskId],
    queryFn: () => api<SyncStatus>('GET', `/api/admin/sync/status/${taskId}`),
    enabled: taskId != null,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state && TERMINAL_STATES.has(state) ? false : 1500;
    },
  });

  const isPolling = taskId != null && !(statusQuery.data && TERMINAL_STATES.has(statusQuery.data.state));

  return {
    run: (dryRun: boolean) => trigger.mutate(dryRun),
    isTriggering: trigger.isPending,
    status: statusQuery.data ?? null,
    isPolling,
  };
}
```

- [ ] **Step 2: Commit**

```bash
git add journal_django/frontend/admin-src/src/hooks/useSyncAction.ts
git commit -m "feat(sync): add useSyncAction hook (trigger + status polling)"
```

---

## Task 18: Фронтенд — `SyncActionCard` + `SyncPage` + стили

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/sync/SyncActionCard.tsx`
- Create: `journal_django/frontend/admin-src/src/pages/sync/SyncPage.tsx`
- Create: `journal_django/frontend/admin-src/src/styles/pages/sync.css`
- Modify: `journal_django/frontend/admin-src/src/styles/index.css`

- [ ] **Step 1: `SyncActionCard.tsx`**

```tsx
// journal_django/frontend/admin-src/src/pages/sync/SyncActionCard.tsx
import { useState } from 'react';
import { Checkbox } from '../../components/form/Checkbox';
import { useSyncAction } from '../../hooks/useSyncAction';
import type { SyncActionDef } from '../../lib/sync';

export function SyncActionCard({ def }: { def: SyncActionDef }) {
  const [dryRun, setDryRun] = useState(false);
  const { run, isTriggering, status, isPolling } = useSyncAction(def.action);
  const busy = isTriggering || isPolling;

  return (
    <div className="sync-card">
      <div className="sync-card__row">
        <span className="sync-card__label">{def.label}</span>
        <Checkbox
          label="только предпросмотр"
          checked={dryRun}
          onChange={(e) => setDryRun(e.target.checked)}
          disabled={busy}
        />
        <button type="button" className="btn-add" disabled={busy} onClick={() => run(dryRun)}>
          Запустить
        </button>
      </div>
      {busy && <div className="sync-card__status sync-card__status--pending">Выполняется…</div>}
      {status?.state === 'SUCCESS' && (
        <pre className="sync-card__status sync-card__status--ok">
          {JSON.stringify(status.result, null, 2)}
        </pre>
      )}
      {status?.state === 'FAILURE' && (
        <div className="sync-card__status sync-card__status--error">{status.error}</div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: `SyncPage.tsx`**

```tsx
// journal_django/frontend/admin-src/src/pages/sync/SyncPage.tsx
import { SYNC_ACTIONS } from '../../lib/sync';
import { SyncActionCard } from './SyncActionCard';

export default function SyncPage() {
  const runAll = SYNC_ACTIONS.filter((a) => a.group === 'run-all');
  const sheets = SYNC_ACTIONS.filter((a) => a.group === 'sheets');
  const rebuild = SYNC_ACTIONS.filter((a) => a.group === 'rebuild');

  return (
    <section className="page sync-page">
      <div className="section-header">
        <span className="section-title">Синхро</span>
      </div>

      {runAll.map((def) => <SyncActionCard key={def.action} def={def} />)}

      <div className="sync-page__group-title">Из Google Sheets</div>
      {sheets.map((def) => <SyncActionCard key={def.action} def={def} />)}

      <div className="sync-page__group-title">Пересчёт из БД (Sheets не трогают)</div>
      {rebuild.map((def) => <SyncActionCard key={def.action} def={def} />)}
    </section>
  );
}
```

- [ ] **Step 3: `styles/pages/sync.css`**

```css
/* journal_django/frontend/admin-src/src/styles/pages/sync.css */
.sync-page__group-title {
  margin: var(--space-6) 0 var(--space-2);
  font-size: 13px;
  font-weight: 600;
  color: var(--text3);
}

.sync-card {
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: var(--space-4);
  margin-bottom: var(--space-3);
  background: var(--bg2);
}

.sync-card__row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.sync-card__label {
  flex: 1;
  font-weight: 500;
  color: var(--text);
}

.sync-card__status {
  margin-top: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--r-sm);
  font-size: 13px;
  white-space: pre-wrap;
  background: var(--bg3);
}

.sync-card__status--pending {
  color: var(--text3);
}

.sync-card__status--ok {
  color: var(--success);
  border: 1px solid var(--success);
}

.sync-card__status--error {
  color: var(--danger);
  border: 1px solid var(--danger);
}
```

- [ ] **Step 4: Подключить в `index.css`**

В `journal_django/frontend/admin-src/src/styles/index.css` после строки
`@import './pages/admin-calendar.css';` добавить:

```css
@import './pages/sync.css';
```

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/sync journal_django/frontend/admin-src/src/styles/pages/sync.css journal_django/frontend/admin-src/src/styles/index.css
git commit -m "feat(sync): add SyncPage/SyncActionCard components + styles"
```

---

## Task 19: Фронтенд — роутинг, сайдбар, права

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/permissions.ts`
- Modify: `journal_django/frontend/admin-src/src/App.tsx`
- Modify: `journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx`

- [ ] **Step 1: `lib/permissions.ts`**

После строки `export const canSeePayroll = isSuper;` добавить:

```typescript
export const canSeeSync = isSuper;
```

- [ ] **Step 2: `App.tsx` — роут**

После строки
`<Route path="/admin/changelog" element={<RequireRole roles={['manager','admin','superadmin']}><ChangelogListPage /></RequireRole>} />`
добавить:

```tsx
            <Route path="/admin/sync" element={<RequireRole roles={['superadmin']}><SyncPage /></RequireRole>} />
```

В начало файла (рядом с другими `import ... Page from './pages/...'`) добавить:

```tsx
import SyncPage from './pages/sync/SyncPage';
```

- [ ] **Step 3: `components/shell/Sidebar.tsx` — иконка + пункт меню**

В объект `NAV_ICONS` после блока `accounts: (...)` добавить:

```tsx
  sync: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10"/>
      <polyline points="1 20 1 14 7 14"/>
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
    </svg>
  ),
```

В импорт добавить `canSeeSync`:

```tsx
import { canSeePayroll, canSeeAccounts, canSeeAudit, canSeeChangelog, canSeeSync, type Role } from '../../lib/permissions';
```

После блока `{canSeeChangelog(role) && (...)}` (перед закрывающим `</nav>`) добавить:

```tsx
        {canSeeSync(role) && (
          <NavLink
            to="/admin/sync"
            className={({ isActive }) => `nav-btn${isActive ? ' active' : ''}`}
          >
            {NAV_ICONS['sync']} Синхро
          </NavLink>
        )}
```

Также обновить условие видимости разделителя-`nav-sep` перед этим блоком (строка
`{(canSeeAccounts(role) || canSeeAudit(role) || canSeeChangelog(role)) && (<div className="nav-sep" />)}`)
— добавить `canSeeSync(role)`:

```tsx
        {(canSeeAccounts(role) || canSeeAudit(role) || canSeeChangelog(role) || canSeeSync(role)) && (
          <div className="nav-sep" />
        )}
```

- [ ] **Step 4: Проверить сборку фронта**

```bash
cd journal_django/frontend/admin-src
npm run build
```

Ожидание: сборка проходит без TypeScript-ошибок, `../admin-dist/` обновлён.

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/lib/permissions.ts journal_django/frontend/admin-src/src/App.tsx journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx journal_django/frontend/admin-dist
git commit -m "feat(sync): wire up /admin/sync route and sidebar entry (superadmin only)"
```

---

## Task 20: Финальная проверка

**Files:** нет новых — прогон уже написанного.

- [ ] **Step 1: Полный прогон бэкенд-тестов**

```bash
cd journal_django
.venv/Scripts/python.exe -m pytest -q
```

Ожидание: все тесты зелёные (существующие + ~50 новых из `apps/sync`), 0 failed.

- [ ] **Step 2: `manage.py check --deploy`**

```bash
.venv/Scripts/python.exe manage.py check
```

Ожидание: без новых предупреждений (кроме уже известных W342).

- [ ] **Step 3: Ручная проверка dry-run каждого действия локально**

Локально `REDIS_URL` не задан (по конвенции проекта — Redis на Windows не поднимаем),
поэтому `CELERY_TASK_ALWAYS_EAGER=True`: `.delay()` в `SyncRunView.post` выполняет
задачу СИНХРОННО прямо внутри того же запроса, никакой отдельный celery-воркер не
нужен и не будет использован, даже если его запустить — только `runserver`:

```bash
cd journal_django && .venv/Scripts/python.exe manage.py runserver 8000
```

Через admin SPA (`/admin/sync`, залогинившись superadmin-аккаунтом) прогнать каждое из 9
действий с включённым «только предпросмотр» и свериться, что цифры (`read`/`inserted`/
`skipped` и т.п.) выглядят разумно относительно реальных данных в dev-БД. `GET .../status`
должен сразу отдавать `SUCCESS` (eager-результат уже посчитан к моменту ответа на `POST`).

- [ ] **Step 4: Финальный commit (если что-то поправлено на шаге 3)**

```bash
git add -A
git commit -m "fix(sync): address issues found during manual dry-run verification"
```

(Пропустить, если шаг 3 ничего не потребовал менять.)

---

## Явно НЕ в этом плане (см. спеку, раздел «Ограничения первой версии»)

- Персистентная история запусков.
- `backfill-payments.js --reset` и `db-truncate.js` в UI.
- Отмена уже запущенной задачи из интерфейса.
- Деплой на прод — отдельным шагом по явной команде пользователя после локального
  тестирования (см. `docs/production-admin-guide.md`, раздел 4.3).
