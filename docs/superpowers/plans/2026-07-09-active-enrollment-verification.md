# Проверка «текущих» направлений против реального членства Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read-only сверка: для слотов «Переход N» со статусом ровно «Продолжает учиться» проверить, есть ли у ученика реально активное членство в группе соответствующего направления на платформе, и вывести расхождения в отчёт.

**Architecture:** Одна чистая функция `verify_active_enrollments(skipped)` в уже существующем `apps/groups/importers/direction_history.py`, переиспользующая `normalize_course_name`. Интегрируется в management-команду как новая read-only секция отчёта (работает одинаково в `--dry-run` и в реальном запуске).

**Tech Stack:** Django ORM (те же модели, что уже используются в `import_to_db`).

**Spec:** [docs/superpowers/specs/2026-07-09-active-enrollment-verification-design.md](../specs/2026-07-09-active-enrollment-verification-design.md)

---

### Task 1: `verify_active_enrollments`

**Files:**
- Modify: `journal_django/apps/groups/importers/direction_history.py`
- Test: `journal_django/apps/groups/tests/test_direction_history_importer.py`

Файл `direction_history.py` уже содержит `normalize_course_name`, `is_skip_current`, `STATUS_ARCHIVE`, `parse_sheet`, `TransitionSlot`, `StudentRow`, `classify_and_aggregate` (+ `SkipRecord`/`UnrecognizedStatusRecord`/`UnmatchedCourseRecord`), `import_to_db` (+ `ImportReport`). Вы ДОПОЛНЯЕТЕ его, не переписываете.

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `journal_django/apps/groups/tests/test_direction_history_importer.py`:

```python
# ---------------------------------------------------------------------------
# verify_active_enrollments — read-only сверка «текущее» ↔ платформа
# ---------------------------------------------------------------------------

def _make_group(direction_id, teacher_id, name):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active) VALUES (%s, %s, %s, false, 60, true) RETURNING id",
            [name, direction_id, teacher_id],
        )
        return cur.fetchone()[0]


def _make_membership(group_id, student_id, active=True):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, remaining, active) "
            "VALUES (%s, %s, 0, 0, %s) RETURNING id",
            [group_id, student_id, active],
        )
        return cur.fetchone()[0]


def _get_teacher_id():
    with connection.cursor() as cur:
        cur.execute('SELECT id FROM teachers LIMIT 1')
        row = cur.fetchone()
    if not row:
        pytest.skip('No teachers in DB — skipping verify_active_enrollments tests')
    return row[0]


def _cleanup_verify(student_id=None, direction_id=None, group_id=None, membership_id=None):
    with connection.cursor() as cur:
        if membership_id is not None:
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])
        if group_id is not None:
            cur.execute('DELETE FROM groups WHERE id = %s', [group_id])
        if direction_id is not None:
            cur.execute('DELETE FROM directions WHERE id = %s', [direction_id])
        if student_id is not None:
            cur.execute('DELETE FROM students WHERE id = %s', [student_id])


@pytest.mark.django_db
class TestVerifyActiveEnrollments:

    def test_active_membership_is_not_a_mismatch(self):
        from apps.groups.importers.direction_history import (
            SkipRecord, verify_active_enrollments,
        )

        teacher_id = _get_teacher_id()
        sid = _make_student('__verify_active_student_1__')
        did = _make_direction('Python')  # совпадает с normalize_course_name('Питон')
        gid = _make_group(did, teacher_id, '__verify_active_group_1__')
        mid = _make_membership(gid, sid, active=True)
        try:
            skipped = [SkipRecord('__verify_active_student_1__', 'Питон', 'Продолжает учиться')]
            mismatches = verify_active_enrollments(skipped)
            assert mismatches == []
        finally:
            _cleanup_verify(student_id=sid, direction_id=did, group_id=gid, membership_id=mid)

    def test_no_active_membership_is_a_mismatch(self):
        from apps.groups.importers.direction_history import (
            SkipRecord, verify_active_enrollments,
        )

        sid = _make_student('__verify_active_student_2__')
        did = _make_direction('Python')
        try:
            skipped = [SkipRecord('__verify_active_student_2__', 'Питон', 'Продолжает учиться')]
            mismatches = verify_active_enrollments(skipped)
            assert len(mismatches) == 1
            assert mismatches[0].full_name == '__verify_active_student_2__'
            assert mismatches[0].direction_name == 'Python'
        finally:
            _cleanup_verify(student_id=sid, direction_id=did)

    def test_inactive_membership_is_a_mismatch(self):
        """active=False membership не считается — ребёнок формально не на направлении сейчас."""
        from apps.groups.importers.direction_history import (
            SkipRecord, verify_active_enrollments,
        )

        teacher_id = _get_teacher_id()
        sid = _make_student('__verify_active_student_3__')
        did = _make_direction('Python')
        gid = _make_group(did, teacher_id, '__verify_active_group_3__')
        mid = _make_membership(gid, sid, active=False)
        try:
            skipped = [SkipRecord('__verify_active_student_3__', 'Питон', 'Продолжает учиться')]
            mismatches = verify_active_enrollments(skipped)
            assert len(mismatches) == 1
        finally:
            _cleanup_verify(student_id=sid, direction_id=did, group_id=gid, membership_id=mid)

    def test_frozen_status_is_not_checked(self):
        """«Заморозка*» не проверяется вообще — это статус ученика, не направления."""
        from apps.groups.importers.direction_history import (
            SkipRecord, verify_active_enrollments,
        )

        sid = _make_student('__verify_active_student_5__')
        try:
            # Нет ни группы, ни членства — но статус «Заморозка» должен быть
            # полностью проигнорирован, а не считаться расхождением.
            skipped = [SkipRecord('__verify_active_student_5__', 'Питон', 'Заморозка Сентябрь')]
            mismatches = verify_active_enrollments(skipped)
            assert mismatches == []
        finally:
            _cleanup_verify(student_id=sid)

    def test_unmatched_student_is_a_mismatch(self):
        from apps.groups.importers.direction_history import (
            SkipRecord, verify_active_enrollments,
        )

        skipped = [SkipRecord('__nonexistent_verify_student__', 'Питон', 'Продолжает учиться')]
        mismatches = verify_active_enrollments(skipped)
        assert len(mismatches) == 1
        assert mismatches[0].full_name == '__nonexistent_verify_student__'

    def test_unrecognized_course_is_a_mismatch_with_none_direction(self):
        from apps.groups.importers.direction_history import (
            SkipRecord, verify_active_enrollments,
        )

        sid = _make_student('__verify_active_student_4__')
        try:
            skipped = [SkipRecord('__verify_active_student_4__', 'Плавание', 'Продолжает учиться')]
            mismatches = verify_active_enrollments(skipped)
            assert len(mismatches) == 1
            assert mismatches[0].direction_name is None
        finally:
            _cleanup_verify(student_id=sid)
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -k TestVerifyActiveEnrollments -v`
Expected: FAIL — `ImportError: cannot import name 'verify_active_enrollments'` (и/или `SkipRecord` уже существует, так что импорт `SkipRecord` не упадёт, но `verify_active_enrollments` — упадёт).

- [ ] **Step 3: Реализовать**

Добавить в конец `journal_django/apps/groups/importers/direction_history.py`:

```python
@dataclass
class ActiveEnrollmentMismatch:
    full_name: str
    course_raw: str
    direction_name: str | None  # None, если курс не нормализовался


# Статус, для которого делаем read-only сверку с реальным членством. «Заморозка*»
# сознательно НЕ проверяется — это глобальный статус ученика (students.enrollment_status),
# а не признак принадлежности к конкретному направлению.
_STATUS_TO_VERIFY = 'Продолжает учиться'


def verify_active_enrollments(skipped: list[SkipRecord]) -> list[ActiveEnrollmentMismatch]:
    """
    Read-only сверка: для слотов со статусом ровно «Продолжает учиться» проверяет,
    есть ли у ученика активное членство (group_memberships.active=True) в группе
    соответствующего направления. Ничего не пишет в БД — только отчёт о расхождениях.
    """
    from apps.memberships.models import GroupMembership
    from apps.students.models import Student

    mismatches: list[ActiveEnrollmentMismatch] = []

    for rec in skipped:
        if rec.status != _STATUS_TO_VERIFY:
            continue

        direction_name = normalize_course_name(rec.course_raw)
        student = Student.objects.filter(full_name=rec.full_name).first()

        if student is None or direction_name is None:
            mismatches.append(ActiveEnrollmentMismatch(rec.full_name, rec.course_raw, direction_name))
            continue

        has_active = GroupMembership.objects.filter(
            student=student, group__direction__name=direction_name, active=True,
        ).exists()
        if not has_active:
            mismatches.append(ActiveEnrollmentMismatch(rec.full_name, rec.course_raw, direction_name))

    return mismatches
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -v`
Expected: все тесты PASS (34 предыдущих + 6 новых = 40). Если тесты `TestVerifyActiveEnrollments` пропускаются (`skipped`) из-за «No teachers in DB» — это ожидаемо в пустой `journal_test` (тот же env quirk, что и раньше); убедитесь при этом, что тесты, не зависящие от учителя (`test_unmatched_student_is_a_mismatch`, `test_unrecognized_course_is_a_mismatch_with_none_direction`), проходят полноценно.

- [ ] **Step 5: Commit**

Стейджить ТОЛЬКО явными путями:
```bash
git add journal_django/apps/groups/importers/direction_history.py journal_django/apps/groups/tests/test_direction_history_importer.py
git diff --cached --stat
```
Убедиться, что в выводе только эти два файла, затем:
```bash
git commit -m "feat(groups): verify_active_enrollments cross-check for Продолжает учиться status"
```

---

### Task 2: Интеграция в management-команду

**Files:**
- Modify: `journal_django/apps/groups/management/commands/import_direction_history.py`
- Test: `journal_django/apps/groups/tests/test_direction_history_importer.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `journal_django/apps/groups/tests/test_direction_history_importer.py`:

```python
def test_command_reports_active_enrollment_mismatches(tmp_path, capsys):
    """Команда печатает секцию расхождений «текущее» ↔ платформа для непроверенных детей."""
    from django.core.management import call_command

    path = tmp_path / 'mismatch.xlsx'
    _build_test_workbook(path)  # Иванов Пётр: Роблокс/«Продолжает учиться», нет такого ученика в БД

    call_command('import_direction_history', str(path), '--dry-run')

    captured = capsys.readouterr()
    assert 'текущее' in captured.out.lower() or 'расхожден' in captured.out.lower()
    assert 'Иванов Пётр' in captured.out
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -k reports_active_enrollment -v`
Expected: FAIL — секция расхождений сейчас не печатается, `assert 'Иванов Пётр' in captured.out` (или первый `assert`) не выполняется, либо тест падает по-другому — команда пока не вызывает `verify_active_enrollments` вовсе.

- [ ] **Step 3: Реализовать**

В `journal_django/apps/groups/management/commands/import_direction_history.py`:

Изменить импорт (добавить `verify_active_enrollments`):

```python
from apps.groups.importers.direction_history import (
    classify_and_aggregate, import_to_db, parse_sheet, verify_active_enrollments,
)
```

В методе `handle`, после строки `aggregated, skipped, unrecognized, unmatched = classify_and_aggregate(rows)` и до `report = import_to_db(...)` добавить:

```python
        enrollment_mismatches = verify_active_enrollments(skipped)
```

Изменить вызов `self._print_report(...)`, добавив новый аргумент:

```python
        self._print_report(rows, skipped, unrecognized, unmatched, enrollment_mismatches, report)
```

Изменить сигнатуру `_print_report`, добавив параметр `enrollment_mismatches`, и добавить новую секцию печати перед финальным `self.stdout.write(self.style.SUCCESS('Готово.'))`:

```python
    def _print_report(self, rows, skipped, unrecognized, unmatched, enrollment_mismatches, report):
```

(это единственное изменение сигнатуры — остальное тело метода перед новой секцией не меняется)

Добавить прямо перед строкой `self.stdout.write(self.style.SUCCESS('Готово.'))`:

```python
        if enrollment_mismatches:
            self.stdout.write(self.style.WARNING(
                '  Расхождения «текущее» ↔ платформа (нет активного членства):'
            ))
            for m in enrollment_mismatches:
                dir_label = m.direction_name or f'не распознано ({m.course_raw})'
                self.stdout.write(f'    - {m.full_name} / {m.course_raw}: направление «{dir_label}» не найдено активным')
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups/tests/test_direction_history_importer.py -v`
Expected: все тесты PASS (40 предыдущих + 1 новый = 41).

- [ ] **Step 5: Commit**

Стейджить ТОЛЬКО явными путями:
```bash
git add journal_django/apps/groups/management/commands/import_direction_history.py journal_django/apps/groups/tests/test_direction_history_importer.py
git diff --cached --stat
```
Убедиться, что в выводе только эти два файла, затем:
```bash
git commit -m "feat(groups): wire verify_active_enrollments into import_direction_history report"
```

---

### Task 3: Полный прогон + повторный dry-run на реальном файле

**Files:** нет изменений — только верификация.

- [ ] **Step 1: Прогнать весь набор**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe apps/groups -v`
Expected: все PASS, 0 failed.

- [ ] **Step 2: Полный бэкенд-набор (регрессия)**

Run: `cd journal_django && ./.venv/Scripts/pytest.exe -q`
Expected: без новых failures относительно текущего baseline (933+ passed).

- [ ] **Step 3: Повторный dry-run на реальном файле, на DEV-БД**

Run:
```bash
cd journal_django
DJANGO_SETTINGS_MODULE=config.settings.development ./.venv/Scripts/python.exe manage.py import_direction_history "C:\Users\ilyap\TestKOTOKOD\КОТОКОД _ Продукт+Преподы.xlsx" --dry-run
```
Expected: команда завершается без исключений, отчёт содержит новую секцию «Расхождения «текущее» ↔ платформа» с реальными строками (если есть).

- [ ] **Step 4: Показать новую секцию отчёта пользователю**

Это точка для контроллера/пользователя, не для агента-исполнителя: показать пользователю именно секцию расхождений (сколько нашлось, какие ФИ/направления) — она новая, реальных данных по ней раньше не видели. Реальный запуск импорта (без `--dry-run`) по-прежнему не запускается без отдельного явного решения пользователя (см. предыдущий план).
