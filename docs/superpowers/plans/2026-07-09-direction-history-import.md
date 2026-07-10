# Импорт истории направлений учеников Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Management-команда `import_direction_history`, которая читает лист «Переходимость по курсам» из внешнего .xlsx и переносит завершённые направления учеников в архивные группы/уроки/посещения/членства.

**Architecture:** Логика разбита на чистые (без БД) функции парсинга/классификации/агрегации в `apps/groups/importers/direction_history.py` — тестируются без файла и без БД, кроме `parse_sheet` (тестируется с синтетическим xlsx) и `import_to_db` (тестируется с реальной managed=False БД). Тонкая `Command`-обёртка в `apps/groups/management/commands/import_direction_history.py` только парсит аргументы и печатает отчёт.

**Tech Stack:** Django 5.1 ORM (managed=False поверх PostgreSQL), openpyxl (новая зависимость — чтение .xlsx без pandas), pytest + pytest-django.

**Spec:** [docs/superpowers/specs/2026-07-08-direction-history-import-design.md](../specs/2026-07-08-direction-history-import-design.md)

---

### Task 1: Зависимость openpyxl

**Files:**
- Modify: `journal_django/requirements.txt`

- [ ] **Step 1: Добавить зависимость**

В `journal_django/requirements.txt` добавить в конец:

```
openpyxl==3.1.5         # чтение .xlsx для одноразового импорта истории направлений (import_direction_history)
```

- [ ] **Step 2: Установить в venv проекта**

Run: `cd journal_django && ./.venv/Scripts/pip.exe install openpyxl==3.1.5`
Expected: `Successfully installed openpyxl-3.1.5` (плюс возможно `et-xmlfile` как транзитивная зависимость).

- [ ] **Step 3: Проверить импорт**

Run: `cd journal_django && ./.venv/Scripts/python.exe -c "import openpyxl; print(openpyxl.__version__)"`
Expected: `3.1.5`

- [ ] **Step 4: Commit**

```bash
git add journal_django/requirements.txt
git commit -m "chore: add openpyxl dependency for direction-history import"
```

---

### Task 2: `normalize_course_name` — нормализация названия курса

**Files:**
- Create: `journal_django/apps/groups/importers/__init__.py`
- Create: `journal_django/apps/groups/importers/direction_history.py`
- Test: `journal_django/apps/groups/tests/test_direction_history_importer.py`

- [ ] **Step 1: Создать пакет `importers`**

Создать файл `journal_django/apps/groups/importers/__init__.py` (пустой).

- [ ] **Step 2: Написать падающий тест**

Создать `journal_django/apps/groups/tests/test_direction_history_importer.py`:

```python
"""
Тесты импортёра истории направлений (apps/groups/importers/direction_history.py).

normalize_course_name / classify_and_aggregate — чистые функции, без БД.
parse_sheet — читает синтетический .xlsx (без сети/реального файла школы).
import_to_db — интеграционные тесты, реальная БД (managed=False, journal_test).
"""
from __future__ import annotations

import pytest

from apps.groups.importers.direction_history import normalize_course_name


@pytest.mark.parametrize('raw,expected', [
    ('Питон', 'Python'),
    ('Питон 52 урока', 'Python'),
    ('Питон Старый (16 ур)', 'Python'),
    ('Питон Старый (32 урока)', 'Python'),
    ('Python', 'Python'),
    ('Python ИНДИВ', 'Python'),
    ('Роблокс', 'Roblox Группа'),
    ('Роблокс Старый (16 ур)', 'Roblox Группа'),
    ('Роблокс Особые Условия', 'Roblox Группа'),
    ('Roblox ИНДИВ', 'Roblox Группа'),
    ('Скретч', 'Scratch'),
    ('Скретч Старый (16 ур)', 'Scratch'),
    ('Майнкрафт', 'Minecraft'),
    ('Блендер', 'Blender'),
    ('Веб-дизайн', 'Веб-дизайн'),
    ('Веб-дизайн ИНДИВ', 'Веб-дизайн'),
    ('Веб-дизайн Особые Условия', 'Веб-дизайн'),
    ('Веб-разработка', 'Web-разработка'),
])
def test_normalize_course_name_maps_to_canonical_direction(raw, expected):
    assert normalize_course_name(raw) == expected


def test_normalize_course_name_unrecognized_returns_none():
    assert normalize_course_name('Плавание') is None
    assert normalize_course_name('') is None
    assert normalize_course_name(None) is None
```

- [ ] **Step 3: Запустить и убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.groups.importers.direction_history'`.

- [ ] **Step 4: Реализовать**

Создать `journal_django/apps/groups/importers/direction_history.py`:

```python
"""
Импорт истории направлений учеников из внешней таблицы «Переходимость по курсам».

Парсинг/классификация/агрегация — чистые функции (без БД), легко тестируемые.
import_to_db() — единственная функция с побочными эффектами (пишет в БД).

См. docs/superpowers/specs/2026-07-08-direction-history-import-design.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SHEET_NAME = 'Переходимость по курсам'
ARCHIVE_TEACHER_NAME = 'Архив (импорт истории)'
LEGACY_LESSON_DATE = '2023-01-01'

# Статусы «Переход N», которые означают, что направление ЗАВЕРШЕНО и переносится в архив.
STATUS_ARCHIVE = {
    'Закончил и перешёл',
    'Недоучился и перешёл',
    'Ожидание перехода',
    'Отказ',
}
# Статус «Продолжает учиться» — точное совпадение; «Заморозка*» — по префиксу
# (в таблице встречаются варианты «Заморозка Сентябрь», «Заморозка Июль» и т.п.).
STATUS_SKIP_CURRENT_EXACT = {'Продолжает учиться'}


def is_skip_current(status: str) -> bool:
    """Статус означает «направление ещё текущее» — не архивируем, не считаем ошибкой."""
    return status in STATUS_SKIP_CURRENT_EXACT or status.startswith('Заморозка')


# Порядок важен только визуально — паттерны не пересекаются по смыслу.
_COURSE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'питон|python', re.I), 'Python'),
    (re.compile(r'роблокс|roblox', re.I), 'Roblox Группа'),
    (re.compile(r'скретч|scratch', re.I), 'Scratch'),
    (re.compile(r'майнкрафт|minecraft', re.I), 'Minecraft'),
    (re.compile(r'блендер|blender', re.I), 'Blender'),
    (re.compile(r'веб-дизайн', re.I), 'Веб-дизайн'),
    (re.compile(r'веб-разработка|web-разработка', re.I), 'Web-разработка'),
]


def normalize_course_name(raw: str | None) -> str | None:
    """
    Сырое название курса из таблицы -> каноничное имя направления в системе.

    Всегда возвращает ГРУППОВУЮ версию направления, даже если в исходном названии
    явно написано «ИНДИВ» — приписки (Старый/ИНДИВ/Особые Условия/N уроков)
    игнорируются по решению пользователя (см. спеку, раздел «Нормализация»).
    None, если ни один паттерн не подошёл (нераспознанный курс).
    """
    text = (raw or '').strip()
    if not text:
        return None
    for pattern, canonical in _COURSE_PATTERNS:
        if pattern.search(text):
            return canonical
    return None
```

- [ ] **Step 5: Запустить и убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -v`
Expected: все PASS (19 тестов).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/groups/importers/__init__.py journal_django/apps/groups/importers/direction_history.py journal_django/apps/groups/tests/test_direction_history_importer.py
git commit -m "feat(groups): normalize_course_name for direction history import"
```

---

### Task 3: `parse_sheet` — чтение .xlsx

**Files:**
- Modify: `journal_django/apps/groups/importers/direction_history.py`
- Test: `journal_django/apps/groups/tests/test_direction_history_importer.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `journal_django/apps/groups/tests/test_direction_history_importer.py`:

```python
def _build_test_workbook(path):
    """Синтетический .xlsx, повторяющий структуру реального листа «Переходимость по курсам»:
    строка 1 — групповые заголовки «Переход N», строка 2 — заголовки колонок,
    строка 3+ — данные. Хвостовая пустая строка должна отфильтровываться."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Переходимость по курсам'

    ws.append([None, None, None, 'Переход 1', None, None, None, 'Переход 2', None, None, None])
    ws.append([
        'ФИ РЕБ', 'Сколько отзанимался', None,
        'Курс', 'прошёл ур', 'месяцев', 'Статус перехода',
        'Курс', 'прошёл ур', 'месяцев', 'Статус перехода',
    ])
    ws.append([
        'Иванов Пётр', 45, None,
        'Питон', 32, 8, 'Закончил и перешёл',
        'Роблокс', 13, 3.25, 'Продолжает учиться',
    ])
    ws.append([
        'Сидорова Анна', 20, None,
        'Скретч', 20, 5, 'Заморозка Сентябрь',
        None, None, 0, None,
    ])
    # Хвостовая «пустая» строка — как в реальном файле (шаблон без ученика).
    ws.append([None, 0, 0.0, None, None, 0, None, None, None, 0, None])

    wb.save(path)


def test_parse_sheet_reads_students_and_filters_empty_rows(tmp_path):
    from apps.groups.importers.direction_history import parse_sheet

    path = tmp_path / 'test.xlsx'
    _build_test_workbook(path)

    rows = parse_sheet(str(path))

    assert len(rows) == 2

    ivanov = rows[0]
    assert ivanov.full_name == 'Иванов Пётр'
    assert len(ivanov.transitions) == 2
    assert ivanov.transitions[0].course_raw == 'Питон'
    assert ivanov.transitions[0].lessons == 32
    assert ivanov.transitions[0].status == 'Закончил и перешёл'
    assert ivanov.transitions[1].course_raw == 'Роблокс'
    assert ivanov.transitions[1].lessons == 13
    assert ivanov.transitions[1].status == 'Продолжает учиться'

    sidorova = rows[1]
    assert sidorova.full_name == 'Сидорова Анна'
    # Второй слот пуст (course=None) -> не попадает в transitions.
    assert len(sidorova.transitions) == 1
    assert sidorova.transitions[0].course_raw == 'Скретч'
    assert sidorova.transitions[0].lessons == 20
    assert sidorova.transitions[0].status == 'Заморозка Сентябрь'


def test_parse_sheet_strips_whitespace_from_full_name(tmp_path):
    import openpyxl
    from apps.groups.importers.direction_history import parse_sheet

    path = tmp_path / 'test2.xlsx'
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Переходимость по курсам'
    ws.append([None, None, None, 'Переход 1', None, None, None])
    ws.append(['ФИ РЕБ', 'Сколько отзанимался', None, 'Курс', 'прошёл ур', 'месяцев', 'Статус перехода'])
    ws.append(['  Петров Иван  ', 10, None, 'Питон', 10, 2.5, 'Отказ'])
    wb.save(path)

    rows = parse_sheet(str(path))
    assert rows[0].full_name == 'Петров Иван'
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -k parse_sheet -v`
Expected: FAIL — `ImportError: cannot import name 'parse_sheet'`.

- [ ] **Step 3: Реализовать**

Добавить в конец `journal_django/apps/groups/importers/direction_history.py`:

```python
@dataclass
class TransitionSlot:
    course_raw: str
    lessons: int
    status: str


@dataclass
class StudentRow:
    full_name: str
    transitions: list[TransitionSlot]


# 0-indexed колонка «Курс» для каждого слота «Переход N» (лессонс/месяцев/статус —
# следующие 3 колонки подряд). До 6 слотов в реальном файле, но парсер не ограничивает
# их число жёстко — читает все группы по 4 колонки начиная с индекса 3.
_SLOT_START_COLUMNS = [3, 7, 11, 15, 19, 23]


def parse_sheet(path: str) -> list[StudentRow]:
    """
    Читает лист SHEET_NAME файла path. Строки 1-2 — заголовки (групповые + колоночные),
    данные — с 3-й строки (1-indexed openpyxl). Строка без ФИ (col A) — пропускается
    (хвостовые пустые шаблонные строки в реальном файле).
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[SHEET_NAME]

    rows: list[StudentRow] = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        full_name_raw = row[0] if len(row) > 0 else None
        if full_name_raw is None or str(full_name_raw).strip() == '':
            continue

        transitions: list[TransitionSlot] = []
        for start in _SLOT_START_COLUMNS:
            course = row[start] if start < len(row) else None
            lessons_raw = row[start + 1] if start + 1 < len(row) else None
            status_raw = row[start + 3] if start + 3 < len(row) else None
            if course is None or lessons_raw is None:
                continue
            try:
                lessons = int(round(float(lessons_raw)))
            except (TypeError, ValueError):
                continue
            if lessons <= 0:
                continue
            transitions.append(TransitionSlot(
                course_raw=str(course), lessons=lessons, status=str(status_raw or ''),
            ))

        if transitions:
            rows.append(StudentRow(full_name=str(full_name_raw).strip(), transitions=transitions))

    return rows
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -v`
Expected: все PASS (21 тестов).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/groups/importers/direction_history.py journal_django/apps/groups/tests/test_direction_history_importer.py
git commit -m "feat(groups): parse_sheet reads Переходимость по курсам from xlsx"
```

---

### Task 4: `classify_and_aggregate` — классификация и суммирование

**Files:**
- Modify: `journal_django/apps/groups/importers/direction_history.py`
- Test: `journal_django/apps/groups/tests/test_direction_history_importer.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `journal_django/apps/groups/tests/test_direction_history_importer.py`:

```python
def _row(full_name, *slots):
    """slots: list of (course_raw, lessons, status) tuples."""
    from apps.groups.importers.direction_history import StudentRow, TransitionSlot
    return StudentRow(
        full_name=full_name,
        transitions=[TransitionSlot(course_raw=c, lessons=n, status=s) for c, n, s in slots],
    )


def test_classify_and_aggregate_sums_repeated_direction():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [
        _row(
            'Столярова Анастасия',
            ('Питон', 20, 'Закончил и перешёл'),
            ('Веб-разработка', 15, 'Продолжает учиться'),
            ('Питон', 10, 'Ожидание перехода'),  # повторный заход на то же направление
        ),
    ]

    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated[('Столярова Анастасия', 'Python')] == 30
    assert ('Столярова Анастасия', 'Web-разработка') not in aggregated
    assert len(skipped) == 1
    assert skipped[0].course_raw == 'Веб-разработка'
    assert unrecognized == []
    assert unmatched == []


def test_classify_and_aggregate_skips_current_status():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [_row('Иванов Пётр', ('Питон', 32, 'Продолжает учиться'))]
    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated == {}
    assert len(skipped) == 1
    assert skipped[0].full_name == 'Иванов Пётр'
    assert skipped[0].status == 'Продолжает учиться'


def test_classify_and_aggregate_skips_frozen_status_variants():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [_row('Иванов Пётр', ('Питон', 32, 'Заморозка Сентябрь'))]
    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated == {}
    assert len(skipped) == 1


def test_classify_and_aggregate_reports_unrecognized_status():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [_row('Кокорин Владимир', ('Веб-дизайн', 12, 'Что с ним'))]
    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated == {}
    assert skipped == []
    assert len(unrecognized) == 1
    assert unrecognized[0].full_name == 'Кокорин Владимир'
    assert unrecognized[0].status == 'Что с ним'


def test_classify_and_aggregate_reports_unmatched_course_name():
    from apps.groups.importers.direction_history import classify_and_aggregate

    rows = [_row('Петров Иван', ('Плавание', 8, 'Закончил и перешёл'))]
    aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)

    assert aggregated == {}
    assert len(unmatched) == 1
    assert unmatched[0].full_name == 'Петров Иван'
    assert unmatched[0].course_raw == 'Плавание'
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -k classify_and_aggregate -v`
Expected: FAIL — `ImportError: cannot import name 'classify_and_aggregate'`.

- [ ] **Step 3: Реализовать**

Добавить в конец `journal_django/apps/groups/importers/direction_history.py`:

```python
@dataclass
class SkipRecord:
    full_name: str
    course_raw: str
    status: str


@dataclass
class UnrecognizedStatusRecord:
    full_name: str
    course_raw: str
    status: str


@dataclass
class UnmatchedCourseRecord:
    full_name: str
    course_raw: str


def classify_and_aggregate(
    rows: list[StudentRow],
) -> tuple[
    dict[tuple[str, str], int],
    list[SkipRecord],
    list[UnrecognizedStatusRecord],
    list[UnmatchedCourseRecord],
]:
    """
    Классифицирует и суммирует слоты «Переход N» по всем ученикам.

    Возвращает:
      aggregated: {(full_name, direction_name): сумма_уроков} — только архивируемые
      skipped: слоты со статусом «текущее направление» (осознанный пропуск)
      unrecognized: слоты с нераспознанным статусом (пропуск + нужен отчёт)
      unmatched: слоты с нераспознанным названием курса (пропуск + нужен отчёт)
    """
    aggregated: dict[tuple[str, str], int] = {}
    skipped: list[SkipRecord] = []
    unrecognized: list[UnrecognizedStatusRecord] = []
    unmatched: list[UnmatchedCourseRecord] = []

    for row in rows:
        for slot in row.transitions:
            if is_skip_current(slot.status):
                skipped.append(SkipRecord(row.full_name, slot.course_raw, slot.status))
                continue
            if slot.status not in STATUS_ARCHIVE:
                unrecognized.append(UnrecognizedStatusRecord(row.full_name, slot.course_raw, slot.status))
                continue
            direction_name = normalize_course_name(slot.course_raw)
            if direction_name is None:
                unmatched.append(UnmatchedCourseRecord(row.full_name, slot.course_raw))
                continue
            key = (row.full_name, direction_name)
            aggregated[key] = aggregated.get(key, 0) + slot.lessons

    return aggregated, skipped, unrecognized, unmatched
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -v`
Expected: все PASS (26 тестов).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/groups/importers/direction_history.py journal_django/apps/groups/tests/test_direction_history_importer.py
git commit -m "feat(groups): classify_and_aggregate for direction history import"
```

---

### Task 5: `import_to_db` — запись в БД

**Files:**
- Modify: `journal_django/apps/groups/importers/direction_history.py`
- Test: `journal_django/apps/groups/tests/test_direction_history_importer.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `journal_django/apps/groups/tests/test_direction_history_importer.py`:

```python
# ---------------------------------------------------------------------------
# import_to_db — интеграционные тесты (реальная БД, managed=False)
# ---------------------------------------------------------------------------

from django.db import connection


def _make_student(full_name):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status) VALUES (%s, 'enrolled') RETURNING id",
            [full_name],
        )
        return cur.fetchone()[0]


def _make_direction(name):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO directions (name, sheet_name, is_individual, active) "
            "VALUES (%s, %s, false, true) RETURNING id",
            [name, f'__sheet_{name}__'],
        )
        return cur.fetchone()[0]


def _cleanup_import(student_id=None, direction_id=None):
    with connection.cursor() as cur:
        if direction_id is not None:
            cur.execute(
                "SELECT id FROM groups WHERE direction_id = %s", [direction_id],
            )
            group_ids = [r[0] for r in cur.fetchall()]
            for gid in group_ids:
                cur.execute("DELETE FROM lesson_attendance WHERE lesson_id IN "
                            "(SELECT id FROM lessons WHERE group_id = %s)", [gid])
                cur.execute("DELETE FROM group_memberships WHERE group_id = %s", [gid])
                cur.execute("DELETE FROM lessons WHERE group_id = %s", [gid])
            cur.execute("DELETE FROM groups WHERE direction_id = %s", [direction_id])
            cur.execute("DELETE FROM directions WHERE id = %s", [direction_id])
        if student_id is not None:
            cur.execute("DELETE FROM students WHERE id = %s", [student_id])


@pytest.fixture
def import_teacher_cleanup():
    """Удаляет служебного 'Архив (импорт истории)' учителя после теста, если он появился."""
    yield
    with connection.cursor() as cur:
        cur.execute(
            "DELETE FROM teachers WHERE name = 'Архив (импорт истории)' "
            "AND id NOT IN (SELECT DISTINCT teacher_id FROM groups)"
        )


@pytest.mark.django_db
class TestImportToDb:

    def test_creates_teacher_group_lessons_attendance_membership(self, import_teacher_cleanup):
        from apps.groups.importers.direction_history import import_to_db

        sid = _make_student('__import_test_student_1__')
        did = _make_direction('__import_test_direction_1__')
        try:
            aggregated = {('__import_test_student_1__', '__import_test_direction_1__'): 5}
            report = import_to_db(aggregated, dry_run=False)

            assert report.imported_pairs == 1
            assert report.lessons_written == 5
            assert report.already_imported == 0
            assert report.unmatched_students == []

            with connection.cursor() as cur:
                cur.execute("SELECT id FROM teachers WHERE name = 'Архив (импорт истории)'")
                teacher_row = cur.fetchone()
                assert teacher_row is not None

                cur.execute(
                    "SELECT id, active, teacher_id FROM groups WHERE direction_id = %s", [did],
                )
                group_row = cur.fetchone()
                assert group_row is not None
                gid, active, teacher_id = group_row
                assert active is False
                assert teacher_id == teacher_row[0]

                cur.execute("SELECT COUNT(*) FROM lessons WHERE group_id = %s", [gid])
                assert cur.fetchone()[0] == 5

                cur.execute(
                    "SELECT COUNT(*) FROM lesson_attendance la JOIN lessons l ON l.id = la.lesson_id "
                    "WHERE l.group_id = %s AND la.student_id = %s AND la.present = true",
                    [gid, sid],
                )
                assert cur.fetchone()[0] == 5

                cur.execute(
                    "SELECT lessons_done, active FROM group_memberships WHERE group_id = %s AND student_id = %s",
                    [gid, sid],
                )
                membership = cur.fetchone()
                assert membership == (5, False)
        finally:
            _cleanup_import(student_id=sid, direction_id=did)

    def test_dry_run_writes_nothing(self, import_teacher_cleanup):
        from apps.groups.importers.direction_history import import_to_db

        sid = _make_student('__import_test_student_2__')
        did = _make_direction('__import_test_direction_2__')
        try:
            aggregated = {('__import_test_student_2__', '__import_test_direction_2__'): 3}
            report = import_to_db(aggregated, dry_run=True)

            assert report.imported_pairs == 1
            assert report.lessons_written == 3

            with connection.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM groups WHERE direction_id = %s", [did])
                assert cur.fetchone()[0] == 0
                cur.execute("SELECT COUNT(*) FROM teachers WHERE name = 'Архив (импорт истории)'")
                assert cur.fetchone()[0] == 0
        finally:
            _cleanup_import(student_id=sid, direction_id=did)

    def test_rerun_is_idempotent_noop(self, import_teacher_cleanup):
        from apps.groups.importers.direction_history import import_to_db

        sid = _make_student('__import_test_student_3__')
        did = _make_direction('__import_test_direction_3__')
        try:
            aggregated = {('__import_test_student_3__', '__import_test_direction_3__'): 4}
            import_to_db(aggregated, dry_run=False)

            report2 = import_to_db(aggregated, dry_run=False)
            assert report2.imported_pairs == 0
            assert report2.already_imported == 1

            with connection.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM lessons WHERE group_id IN "
                    "(SELECT id FROM groups WHERE direction_id = %s)", [did],
                )
                assert cur.fetchone()[0] == 4  # не задвоилось
        finally:
            _cleanup_import(student_id=sid, direction_id=did)

    def test_unmatched_student_is_reported_and_skipped(self, import_teacher_cleanup):
        from apps.groups.importers.direction_history import import_to_db

        did = _make_direction('__import_test_direction_4__')
        try:
            aggregated = {('__nonexistent_student_xyz__', '__import_test_direction_4__'): 2}
            report = import_to_db(aggregated, dry_run=False)

            assert report.imported_pairs == 0
            assert '__nonexistent_student_xyz__' in report.unmatched_students

            with connection.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM groups WHERE direction_id = %s", [did])
                assert cur.fetchone()[0] == 0
        finally:
            _cleanup_import(direction_id=did)

    def test_unmatched_direction_is_reported_and_skipped(self, import_teacher_cleanup):
        from apps.groups.importers.direction_history import import_to_db

        sid = _make_student('__import_test_student_5__')
        try:
            aggregated = {('__import_test_student_5__', '__nonexistent_direction_xyz__'): 2}
            report = import_to_db(aggregated, dry_run=False)

            assert report.imported_pairs == 0
            assert any('__nonexistent_direction_xyz__' in s for s in report.unmatched_directions_in_db)
        finally:
            _cleanup_import(student_id=sid)

    def test_idempotency_anomaly_when_count_mismatches(self, import_teacher_cleanup):
        from apps.groups.importers.direction_history import import_to_db

        sid = _make_student('__import_test_student_6__')
        did = _make_direction('__import_test_direction_6__')
        try:
            import_to_db({('__import_test_student_6__', '__import_test_direction_6__'): 4}, dry_run=False)

            # Другое ожидаемое количество для той же пары -> не совпадает с уже записанными 4.
            report = import_to_db(
                {('__import_test_student_6__', '__import_test_direction_6__'): 7}, dry_run=False,
            )
            assert report.imported_pairs == 0
            assert report.already_imported == 0
            assert len(report.idempotency_anomalies) == 1

            with connection.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM lessons WHERE group_id IN "
                    "(SELECT id FROM groups WHERE direction_id = %s)", [did],
                )
                assert cur.fetchone()[0] == 4  # не тронуто
        finally:
            _cleanup_import(student_id=sid, direction_id=did)
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -k TestImportToDb -v`
Expected: FAIL — `ImportError: cannot import name 'import_to_db'`.

- [ ] **Step 3: Реализовать**

Добавить в конец `journal_django/apps/groups/importers/direction_history.py`:

```python
@dataclass
class ImportReport:
    dry_run: bool
    total_pairs: int = 0
    imported_pairs: int = 0
    lessons_written: int = 0
    already_imported: int = 0
    unmatched_students: list = field(default_factory=list)
    unmatched_directions_in_db: list = field(default_factory=list)
    idempotency_anomalies: list = field(default_factory=list)


def import_to_db(aggregated: dict, *, dry_run: bool) -> ImportReport:
    """
    Пишет архивные группы/уроки/посещения/членства по агрегированным парам
    (ФИ ученика, имя направления) -> сумма уроков.

    Идемпотентно: для пары с уже записанными N уроками (по submitted_by_token)
    — пропуск (already_imported). Если записано другое количество — не трогаем,
    в idempotency_anomalies (нужна ручная проверка).
    """
    from django.db import transaction
    from django.utils import timezone

    from apps.directions.models import Direction
    from apps.groups.models import Group
    from apps.lessons.models import Lesson, LessonAttendance
    from apps.memberships.models import GroupMembership
    from apps.students.models import Student
    from apps.teachers.models import Teacher

    report = ImportReport(dry_run=dry_run, total_pairs=len(aggregated))

    teacher = None
    if not dry_run:
        teacher, _ = Teacher.objects.get_or_create(
            name=ARCHIVE_TEACHER_NAME, defaults={'created_at': timezone.now()},
        )

    group_cache: dict[int, Group] = {}

    for (full_name, direction_name), lessons_count in aggregated.items():
        student = Student.objects.filter(full_name=full_name).first()
        if student is None:
            report.unmatched_students.append(full_name)
            continue

        direction = Direction.objects.filter(name=direction_name).first()
        if direction is None:
            report.unmatched_directions_in_db.append(
                f'{full_name}: направление «{direction_name}» не найдено в БД'
            )
            continue

        token = f'legacy-import:{student.id}:{direction.id}'
        existing = Lesson.objects.filter(submitted_by_token=token).count()

        if existing == lessons_count:
            report.already_imported += 1
            continue
        if existing:
            report.idempotency_anomalies.append(
                f'{full_name} / {direction_name}: в БД {existing} уроков, ожидалось {lessons_count}'
            )
            continue

        if dry_run:
            report.imported_pairs += 1
            report.lessons_written += lessons_count
            continue

        with transaction.atomic():
            group = group_cache.get(direction.id)
            if group is None:
                group, _ = Group.objects.get_or_create(
                    name=f'{direction.name} — архив',
                    defaults={
                        'direction': direction, 'teacher': teacher, 'active': False,
                        'is_individual': False, 'lesson_duration_minutes': 60,
                        'lessons_per_week': 1, 'created_at': timezone.now(),
                    },
                )
                group_cache[direction.id] = group

            lesson_ids = []
            for n in range(1, lessons_count + 1):
                lesson = Lesson.objects.create(
                    group=group, teacher=teacher, lesson_date=LEGACY_LESSON_DATE,
                    lesson_number=n, lesson_duration_minutes=60, lesson_type='regular',
                    submitted_at=timezone.now(), submitted_by_token=token,
                )
                lesson_ids.append(lesson.id)

            LessonAttendance.objects.bulk_create([
                LessonAttendance(lesson_id=lid, student=student, present=True)
                for lid in lesson_ids
            ])

            GroupMembership.objects.update_or_create(
                group=group, student=student,
                defaults={
                    'lessons_done': lessons_count, 'remaining': 0,
                    'active': False, 'start_date': LEGACY_LESSON_DATE,
                },
            )

        report.imported_pairs += 1
        report.lessons_written += lessons_count

    return report
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -v`
Expected: все PASS (32 теста).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/groups/importers/direction_history.py journal_django/apps/groups/tests/test_direction_history_importer.py
git commit -m "feat(groups): import_to_db writes archive lessons/attendance/membership, idempotent"
```

---

### Task 6: Management-команда

**Files:**
- Create: `journal_django/apps/groups/management/__init__.py`
- Create: `journal_django/apps/groups/management/commands/__init__.py`
- Create: `journal_django/apps/groups/management/commands/import_direction_history.py`
- Test: `journal_django/apps/groups/tests/test_direction_history_importer.py`

- [ ] **Step 1: Создать пакеты**

Создать пустые файлы:
- `journal_django/apps/groups/management/__init__.py`
- `journal_django/apps/groups/management/commands/__init__.py`

- [ ] **Step 2: Написать падающий тест**

Добавить в конец `journal_django/apps/groups/tests/test_direction_history_importer.py`:

```python
def test_command_dry_run_smoke(tmp_path, capsys):
    """Команда читает файл, ничего не пишет в БД в --dry-run, печатает отчёт."""
    from django.core.management import call_command

    path = tmp_path / 'smoke.xlsx'
    _build_test_workbook(path)

    call_command('import_direction_history', str(path), '--dry-run')

    captured = capsys.readouterr()
    assert 'DRY-RUN' in captured.out
    assert 'Учеников в листе' in captured.out
```

- [ ] **Step 3: Запустить и убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -k command_dry_run -v`
Expected: FAIL — `django.core.management.base.CommandError: Unknown command: 'import_direction_history'`.

- [ ] **Step 4: Реализовать**

Создать `journal_django/apps/groups/management/commands/import_direction_history.py`:

```python
"""
python manage.py import_direction_history <путь_к_xlsx> [--dry-run]

Импортирует историю направлений учеников из листа «Переходимость по курсам»
внешней таблицы в архивные группы/уроки/посещения/членства.

См. docs/superpowers/specs/2026-07-08-direction-history-import-design.md

Гонять на dev-БД (journal), не на journal_test.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.groups.importers.direction_history import (
    classify_and_aggregate, import_to_db, parse_sheet,
)


class Command(BaseCommand):
    help = 'Импорт истории направлений учеников из внешней таблицы «Переходимость по курсам».'

    def add_arguments(self, parser):
        parser.add_argument('xlsx_path', type=str, help='Путь к .xlsx файлу')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Не писать в БД: только показать, что было бы сделано.',
        )

    def handle(self, *args, **opts):
        path = opts['xlsx_path']
        dry = opts['dry_run']

        try:
            rows = parse_sheet(path)
        except FileNotFoundError as e:
            raise CommandError(f'Файл не найден: {e}')
        except KeyError as e:
            raise CommandError(f'Лист не найден в файле: {e}')

        aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)
        report = import_to_db(aggregated, dry_run=dry)

        self._print_report(rows, skipped, unrecognized, unmatched, report)

    def _print_report(self, rows, skipped, unrecognized, unmatched, report):
        mode = 'DRY-RUN (запись отключена)' if report.dry_run else 'запись в БД'
        self.stdout.write(self.style.MIGRATE_HEADING(f'Импорт истории направлений — {mode}'))
        self.stdout.write(f'  Учеников в листе:                  {len(rows)}')
        self.stdout.write(f'  Пар ученик×направление к импорту:  {report.total_pairs}')
        label = 'Импортировано (было бы)' if report.dry_run else 'Импортировано'
        self.stdout.write(f'  {label}: {report.imported_pairs} (уроков: {report.lessons_written})')
        self.stdout.write(f'  Уже импортировано ранее:            {report.already_imported}')
        self.stdout.write(f'  Пропущено (текущее направление):    {len(skipped)}')
        self.stdout.write(f'  Нераспознанный статус:              {len(unrecognized)}')
        self.stdout.write(f'  Нераспознанное название курса:      {len(unmatched)}')

        if unrecognized:
            self.stdout.write(self.style.WARNING('  Нераспознанные статусы:'))
            for r in unrecognized:
                self.stdout.write(f'    - {r.full_name} / {r.course_raw}: «{r.status}»')

        if unmatched:
            self.stdout.write(self.style.WARNING('  Нераспознанные курсы:'))
            for r in unmatched:
                self.stdout.write(f'    - {r.full_name}: «{r.course_raw}»')

        if report.unmatched_students:
            self.stdout.write(self.style.WARNING('  Не найденные ученики:'))
            for name in report.unmatched_students:
                self.stdout.write(f'    - {name}')

        if report.unmatched_directions_in_db:
            self.stdout.write(self.style.WARNING('  Направления не найдены в БД:'))
            for name in report.unmatched_directions_in_db:
                self.stdout.write(f'    - {name}')

        if report.idempotency_anomalies:
            self.stdout.write(self.style.ERROR('  Аномалии идемпотентности (нужна ручная проверка):'))
            for a in report.idempotency_anomalies:
                self.stdout.write(f'    - {a}')

        self.stdout.write(self.style.SUCCESS('Готово.'))
```

- [ ] **Step 5: Запустить и убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -v`
Expected: все PASS (33 теста).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/groups/management/__init__.py journal_django/apps/groups/management/commands/__init__.py journal_django/apps/groups/management/commands/import_direction_history.py journal_django/apps/groups/tests/test_direction_history_importer.py
git commit -m "feat(groups): import_direction_history management command"
```

---

### Task 7: Полный прогон тестов + dry-run на реальном файле

**Files:** нет изменений — только верификация.

- [ ] **Step 1: Прогнать весь набор apps/groups**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups -v`
Expected: все PASS, 0 failed.

- [ ] **Step 2: Прогнать полный бэкенд-набор (регрессия)**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe -q`
Expected: без новых failures относительно текущего baseline (899+ passed).

- [ ] **Step 3: Dry-run на реальном файле, на DEV-БД (не journal_test)**

Run:
```bash
cd journal_django
DJANGO_SETTINGS_MODULE=config.settings.development ./.venv/Scripts/python.exe manage.py import_direction_history "C:\Users\ilyap\TestKOTOKOD\КОТОКОД _ Продукт+Преподы.xlsx" --dry-run
```
Expected: команда завершается без исключений, печатает отчёт с реальными числами (учеников в листе, пар к импорту, пропущенных, нераспознанных статусов/курсов, ненайденных учеников/направлений).

- [ ] **Step 4: Показать отчёт пользователю, НЕ запускать реальную запись**

Это осознанная точка остановки (не шаг для агента-исполнителя, а решение для контроллера/пользователя): вывод Step 3 нужно показать пользователю целиком и дождаться его подтверждения, прежде чем запускать команду без `--dry-run`. Реальная запись меняет продовую-подобную dev-БД и должна выполняться только после того, как пользователь увидел список ненайденных учеников/нераспознанных курсов/статусов и подтвердил, что всё верно (или поправил маппинг/данные).
