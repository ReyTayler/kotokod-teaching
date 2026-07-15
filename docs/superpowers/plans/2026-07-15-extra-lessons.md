# Доп.уроки для отдельных учеников групп — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a manager/admin/superadmin assign a fixed-rate (200₽/student) makeup lesson to one or more students who missed a specific already-conducted group lesson, have the assigned teacher record it through the same Lesson/Payroll machinery as regular lessons, retroactively mark the missed lesson as attended for those students (without touching the original teacher's payroll), and support cancelling a not-yet-conducted assignment.

**Architecture:** New Django app `apps/extra_lessons/` owns a `PlannedLesson`-shaped shell model (`ExtraLessonAssignment` + `ExtraLessonParticipant`) that goes `scheduled → done` (creates a real `lessons.Lesson(lesson_type='extra')` + `LessonAttendance` + `Payroll`, exactly like `record_lesson`, but with its own flat payment formula) or `scheduled → cancelled`. Two new small helpers in `apps/lessons/repository.py` (`apply_makeup_attendance` / `revert_makeup_attendance`) flip the missed lesson's attendance without recomputing its `Payroll`. The teacher calendar (`apps/scheduling/services.py::build_calendar`) merges in `ExtraLessonAssignment` rows as extra occurrence cards, rendered in a fixed saturated red by `shared/calendar/CalendarView.tsx`.

**Tech Stack:** Django 5 / DRF (backend), React 19 + TypeScript (admin-src + teacher-src frontends), pytest + pytest-django, TanStack Query v5.

**Spec:** `docs/superpowers/specs/2026-07-15-extra-lessons-design.md`

---

### Task 1: Scaffold `apps/extra_lessons` app

**Files:**
- Create: `journal_django/apps/extra_lessons/__init__.py`
- Create: `journal_django/apps/extra_lessons/apps.py`
- Create: `journal_django/apps/extra_lessons/migrations/__init__.py`
- Modify: `journal_django/config/settings/base.py`

- [ ] **Step 1: Create the empty package files**

`journal_django/apps/extra_lessons/__init__.py` — empty file.

`journal_django/apps/extra_lessons/migrations/__init__.py` — empty file.

- [ ] **Step 2: Create `apps.py`**

```python
from django.apps import AppConfig


class ExtraLessonsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.extra_lessons'
    label = 'extra_lessons'
```

- [ ] **Step 3: Register the app**

In `journal_django/config/settings/base.py`, find the line `'apps.scheduling',` (part of `INSTALLED_APPS`) and add the new app directly after it:

```python
    'apps.scheduling',
    'apps.extra_lessons',
```

- [ ] **Step 4: Verify Django recognizes the app**

Run: `cd journal_django && python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/extra_lessons journal_django/config/settings/base.py
git commit -m "chore(extra-lessons): scaffold apps.extra_lessons"
```

---

### Task 2: Models — `ExtraLessonAssignment` + `ExtraLessonParticipant`

**Files:**
- Create: `journal_django/apps/extra_lessons/models.py`
- Create: `journal_django/apps/extra_lessons/migrations/0001_initial.py`
- Modify: `journal_django/apps/changelog/registry.py`
- Test: `journal_django/apps/changelog/tests/test_registry.py` (already exists — verifies our new models satisfy it)

- [ ] **Step 1: Write `models.py`**

```python
"""
Models for extra_lessons — доп.уроки, назначаемые отдельным ученикам группы,
пропустившим конкретный основной (уже проведённый) урок.

ExtraLessonAssignment — «оболочка» по аналогии с scheduling.PlannedLesson:
scheduled (назначено) → done (проведено, fact_lesson заполнен) | cancelled.
Группа доп.урока отдельно не хранится — это всегда группа missed_lesson
(участники объединены вокруг одного пропущенного урока, см.
docs/superpowers/specs/2026-07-15-extra-lessons-design.md).
"""
from __future__ import annotations

import pghistory
from django.db import models

SCHEDULED = 'scheduled'
DONE = 'done'
CANCELLED = 'cancelled'
STATUS_CHOICES = [SCHEDULED, DONE, CANCELLED]

# Совпадает с VALID_LESSON_DURATIONS admin-формы обычных уроков + 30 мин
# (доп.урок может быть короче группового занятия).
VALID_DURATIONS = (30, 45, 60, 90)


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class ExtraLessonAssignment(models.Model):
    """Назначение доп.урока — компенсация пропуска ОДНОГО основного урока."""

    id = models.AutoField(primary_key=True)
    teacher = models.ForeignKey(
        'teachers.Teacher',
        on_delete=models.PROTECT,
        related_name='extra_lesson_assignments',
    )
    # Пропущенный основной урок (факт) — ОДИН на всё назначение. Обязан быть
    # уже проведённым (валидация — apps.extra_lessons.services.create_assignment).
    missed_lesson = models.ForeignKey(
        'lessons.Lesson',
        on_delete=models.PROTECT,
        related_name='extra_lesson_assignments',
    )
    students = models.ManyToManyField(
        'students.Student',
        through='ExtraLessonParticipant',
        related_name='extra_lesson_assignments',
    )
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField()
    duration_minutes = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=16, default=SCHEDULED)
    # Факт проведения доп.урока (lessons.Lesson lesson_type='extra'). Заполняется
    # при записи (record), возвращается в NULL при откате (delete_fact).
    fact_lesson = models.OneToOneField(
        'lessons.Lesson',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='extra_lesson_assignment',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'extra_lesson_assignments'
        indexes = [
            models.Index(fields=['teacher', 'scheduled_date'], name='ela_teacher_date_idx'),
            models.Index(fields=['missed_lesson'], name='ela_missed_lesson_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                name='extra_lesson_assignments_status_check',
                condition=models.Q(status__in=STATUS_CHOICES),
            ),
            models.CheckConstraint(
                name='extra_lesson_assignments_duration_check',
                condition=models.Q(duration_minutes__in=VALID_DURATIONS),
            ),
        ]


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class ExtraLessonParticipant(models.Model):
    """Участник доп.урока (through-модель ExtraLessonAssignment ↔ Student)."""

    id = models.AutoField(primary_key=True)
    assignment = models.ForeignKey(
        ExtraLessonAssignment,
        on_delete=models.CASCADE,
        related_name='participants',
    )
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.PROTECT,
        related_name='extra_lesson_participations',
    )

    class Meta:
        managed = True
        db_table = 'extra_lesson_participants'
        constraints = [
            models.UniqueConstraint(
                fields=['assignment', 'student'],
                name='extra_lesson_participants_assignment_student_key',
            ),
        ]
```

- [ ] **Step 2: Generate the migration**

Run: `cd journal_django && python manage.py makemigrations extra_lessons`
Expected: `Migrations for 'extra_lessons': ... 0001_initial.py - Create model ExtraLessonAssignment - Create model ExtraLessonParticipant`

Open the generated file and confirm it matches the model above (FK columns, both CheckConstraints, both indexes, the UniqueConstraint). No hand-editing needed if `makemigrations` produced the expected operations.

- [ ] **Step 3: Apply the migration to the dev/test databases**

Run: `cd journal_django && python manage.py migrate extra_lessons`
Expected: `Applying extra_lessons.0001_initial... OK`

- [ ] **Step 4: Register both models in the changelog registry**

In `journal_django/apps/changelog/registry.py`, in the `TRACKED` dict, add two entries right after `'lessons.LessonAttendance'` (topo between lessons=40 and payroll/attendance=50, since assignments reference an already-created `lessons.Lesson`):

```python
    'lessons.LessonAttendance':       TrackedModel('attendance', True, 50,
                                                   identity=('lesson_id', 'student_id')),
    'extra_lessons.ExtraLessonAssignment':  TrackedModel('extra_lesson_assignment', True, 45),
    'extra_lessons.ExtraLessonParticipant': TrackedModel('extra_lesson_participant', True, 46),
    'payments.Payment':               TrackedModel('payment', True, 50),
```

- [ ] **Step 5: Run the registry test to confirm coverage**

Run: `cd journal_django && pytest apps/changelog/tests/test_registry.py -v`
Expected: `test_registry_covers_all_tracked_models PASSED` (and the other tests in the file still pass — they don't touch the new models).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/extra_lessons/models.py journal_django/apps/extra_lessons/migrations/0001_initial.py journal_django/apps/changelog/registry.py
git commit -m "feat(extra-lessons): add ExtraLessonAssignment/Participant models"
```

---

### Task 3: Payroll calculator — flat 200₽/student rate

**Files:**
- Modify: `journal_django/apps/payroll/calculator.py`
- Modify: `journal_django/apps/payroll/tests/test_calculator.py`

- [ ] **Step 1: Write the failing test**

Append to `journal_django/apps/payroll/tests/test_calculator.py`:

```python
from apps.payroll.calculator import calculate_extra_lesson_payment


class TestCalculateExtraLessonPayment:
    """Доп.урок: строго 200₽ за присутствовавшего, без half/small-group веток."""

    @pytest.mark.parametrize('present,expected', [
        (0, 0), (1, 200), (2, 400), (3, 600),
    ])
    def test_flat_rate_per_present_student(self, present, expected):
        assert calculate_extra_lesson_payment(present) == expected
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd journal_django && pytest apps/payroll/tests/test_calculator.py -k extra_lesson -v`
Expected: `FAILED ... ImportError: cannot import name 'calculate_extra_lesson_payment'`

- [ ] **Step 3: Add the function**

In `journal_django/apps/payroll/calculator.py`, add after `calculate_payment`:

```python
def calculate_extra_lesson_payment(present: int) -> int:
    """
    Доп.урок (компенсация пропуска основного занятия): строго 200₽ за каждого
    присутствовавшего, независимо от длительности доп.урока и общего числа
    участников — НЕ переиспользует PAY_RATES/calculate_payment (та ветвится по
    размеру группы/half-lesson, что здесь не применяется, см. design doc).
    """
    return PAY_RATES['perStudent'] * present
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `cd journal_django && pytest apps/payroll/tests/test_calculator.py -v`
Expected: all PASSED, including the 4 new parametrized cases.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/payroll/calculator.py journal_django/apps/payroll/tests/test_calculator.py
git commit -m "feat(payroll): add flat 200/student rate for extra lessons"
```

---

### Task 4: `apps/lessons/repository.py` — retroactive makeup-attendance helpers

**Files:**
- Modify: `journal_django/apps/lessons/repository.py`
- Test: `journal_django/apps/lessons/tests/test_lessons_repository.py`

These two functions flip a single student's attendance on an already-recorded
lesson and adjust `lessons_done` by that lesson's own step — but, unlike
`update_attendance_cell`, they never touch that lesson's `Payroll` (the
compensating extra lesson has its own separate Payroll row — see Task 6).

- [ ] **Step 1: Write the failing tests**

Append to `journal_django/apps/lessons/tests/test_lessons_repository.py`:

```python
# ---------------------------------------------------------------------------
# apply_makeup_attendance / revert_makeup_attendance (доп.уроки)
# ---------------------------------------------------------------------------

def test_apply_makeup_attendance_flips_present_and_increments_lessons_done(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-10',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    lesson_id = result['lesson_id']
    try:
        assert lessons_done(group_fixture, student_fixture) == Decimal('0')
        payroll_before = repository.Payroll.objects.get(lesson_id=lesson_id)

        repository.apply_makeup_attendance(lesson_id, student_fixture)

        att = repository.LessonAttendance.objects.get(lesson_id=lesson_id, student_id=student_fixture)
        assert att.present is True
        assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')
        # Payroll исходного урока НЕ пересчитывается доп.уроком.
        payroll_after = repository.Payroll.objects.get(lesson_id=lesson_id)
        assert payroll_after.payment == payroll_before.payment
        assert payroll_after.present_count == payroll_before.present_count
    finally:
        _delete_lesson(lesson_id)


def test_apply_makeup_attendance_is_noop_if_already_present(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-11',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    lesson_id = result['lesson_id']
    try:
        assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')
        repository.apply_makeup_attendance(lesson_id, student_fixture)
        # Уже present=True — второй инкремент не происходит (идемпотентно).
        assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')
    finally:
        _delete_lesson(lesson_id)


def test_revert_makeup_attendance_undoes_apply(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-12',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 45,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    lesson_id = result['lesson_id']
    try:
        repository.apply_makeup_attendance(lesson_id, student_fixture)
        assert lessons_done(group_fixture, student_fixture) == Decimal('0.5')

        repository.revert_makeup_attendance(lesson_id, student_fixture)

        att = repository.LessonAttendance.objects.get(lesson_id=lesson_id, student_id=student_fixture)
        assert att.present is False
        assert lessons_done(group_fixture, student_fixture) == Decimal('0')
    finally:
        _delete_lesson(lesson_id)
```

- [ ] **Step 2: Run to confirm they fail**

Run: `cd journal_django && pytest apps/lessons/tests/test_lessons_repository.py -k makeup_attendance -v`
Expected: `AttributeError: module 'apps.lessons.repository' has no attribute 'apply_makeup_attendance'`

- [ ] **Step 3: Implement the two functions**

In `journal_django/apps/lessons/repository.py`, add after `update_attendance_cell`:

```python
def apply_makeup_attendance(lesson_id: int, student_id: int) -> None:
    """
    Ретроактивно отмечает студента присутствовавшим на УЖЕ проведённом уроке —
    вызывается при фиксации доп.урока, которым компенсируется этот пропуск
    (apps.extra_lessons.services.record). Инкрементирует lessons_done на шаг
    ЭТОГО (исходного) урока, но НЕ пересчитывает его Payroll — доп.урок
    оплачивается преподавателю, который его провёл, отдельной строкой
    (см. docs/superpowers/specs/2026-07-15-extra-lessons-design.md).

    No-op, если студент уже present=True на этом уроке (идемпотентно — на
    случай повторного вызова).
    """
    with transaction.atomic():
        ctx = (
            Lesson.objects
            .filter(id=lesson_id)
            .values('group_id', 'lesson_duration_minutes')
            .first()
        )
        if ctx is None:
            return
        updated = LessonAttendance.objects.filter(
            lesson_id=lesson_id, student_id=student_id, present=False,
        ).update(present=True)
        if not updated:
            return
        step = _step(ctx['lesson_duration_minutes'])
        GroupMembership.objects.filter(
            group_id=ctx['group_id'], student_id=student_id,
        ).update(lessons_done=F('lessons_done') + step)
        direction_id = Group.objects.filter(
            id=ctx['group_id']).values_list('direction_id', flat=True).first()
        transaction.on_commit(lambda: _sync_renewal_stage(student_id, direction_id))


def revert_makeup_attendance(lesson_id: int, student_id: int) -> None:
    """
    Откат apply_makeup_attendance — вызывается при удалении доп.урока
    (apps.extra_lessons.services.delete_fact), которым был компенсирован
    пропуск: возвращает present=False и списывает lessons_done обратно.

    No-op, если студент уже present=False на этом уроке.
    """
    with transaction.atomic():
        ctx = (
            Lesson.objects
            .filter(id=lesson_id)
            .values('group_id', 'lesson_duration_minutes')
            .first()
        )
        if ctx is None:
            return
        updated = LessonAttendance.objects.filter(
            lesson_id=lesson_id, student_id=student_id, present=True,
        ).update(present=False)
        if not updated:
            return
        step = _step(ctx['lesson_duration_minutes'])
        GroupMembership.objects.filter(
            group_id=ctx['group_id'], student_id=student_id,
        ).update(lessons_done=Greatest(F('lessons_done') - step, _ZERO))
        direction_id = Group.objects.filter(
            id=ctx['group_id']).values_list('direction_id', flat=True).first()
        transaction.on_commit(lambda: _sync_renewal_stage(student_id, direction_id))
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `cd journal_django && pytest apps/lessons/tests/test_lessons_repository.py -v`
Expected: all PASSED (existing tests unaffected, 3 new ones green).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/lessons/repository.py journal_django/apps/lessons/tests/test_lessons_repository.py
git commit -m "feat(lessons): add retroactive makeup-attendance repository helpers"
```

---

### Task 5: `apps/extra_lessons` conftest + repository (ORM helpers)

**Files:**
- Create: `journal_django/apps/extra_lessons/tests/__init__.py`
- Create: `journal_django/apps/extra_lessons/tests/conftest.py`
- Create: `journal_django/apps/extra_lessons/repository.py`
- Test: `journal_django/apps/extra_lessons/tests/test_extra_lessons_repository.py`

- [ ] **Step 1: Create `tests/__init__.py`** (empty file)

- [ ] **Step 2: Write `conftest.py`**

Mirrors `apps/lessons/tests/conftest.py` (same fixture style), plus a
`missed_lesson_fixture` that seeds a fully-conducted `Lesson` (with one
absent student) to assign a doprol against.

```python
"""conftest.py для тестов extra_lessons — фикстуры-самосев в journal_test."""
from __future__ import annotations

import pytest
from django.db import connection


@pytest.fixture(scope='session')
def django_db_setup():
    pass


@pytest.fixture
def teacher_fixture():
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__el_test_teacher__') RETURNING id")
        teacher_id = cur.fetchone()[0]
    yield teacher_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM teachers WHERE id = %s', [teacher_id])


@pytest.fixture
def other_teacher_fixture():
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__el_test_teacher2__') RETURNING id")
        teacher_id = cur.fetchone()[0]
    yield teacher_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM teachers WHERE id = %s', [teacher_id])


@pytest.fixture
def direction_fixture():
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO directions (name, is_individual, total_lessons, active)
            VALUES ('__el_test_dir__', false, 8, true)
            RETURNING id
            """,
        )
        direction_id = cur.fetchone()[0]
    yield direction_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM directions WHERE id = %s', [direction_id])


@pytest.fixture
def student_fixture():
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO students (full_name, enrollment_status)
            VALUES ('__el_test_student__', 'enrolled') RETURNING id
            """,
        )
        student_id = cur.fetchone()[0]
    yield student_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM students WHERE id = %s', [student_id])


@pytest.fixture
def group_fixture(direction_fixture, teacher_fixture):
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO groups (name, direction_id, teacher_id, is_individual,
                                lesson_duration_minutes, active)
            VALUES ('__el_test_group__', %s, %s, false, 60, true) RETURNING id
            """,
            [direction_fixture, teacher_fixture],
        )
        group_id = cur.fetchone()[0]
    yield group_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM groups WHERE id = %s', [group_id])


@pytest.fixture
def membership_fixture(group_fixture, student_fixture, direction_fixture):
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO group_memberships (group_id, student_id, lessons_done, active)
            VALUES (%s, %s, 0, true) RETURNING id
            """,
            [group_fixture, student_fixture],
        )
        membership_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO payments (student_id, direction_id, subscriptions_count, lessons_count,
                                   unit_price, total_amount, paid_at, created_by)
            VALUES (%s, %s, 2, 8, 1000, 8000, '2026-06-01', 'test') RETURNING id
            """,
            [student_fixture, direction_fixture],
        )
        payment_id = cur.fetchone()[0]
    yield membership_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])
        cur.execute('DELETE FROM payments WHERE id = %s', [payment_id])


@pytest.fixture
def missed_lesson_fixture(group_fixture, teacher_fixture, student_fixture, membership_fixture):
    """Уже проведённый урок группы, на котором student_fixture отсутствовал."""
    from apps.lessons import services as lessons_services

    result = lessons_services.create_lesson_full({
        'lesson_date': '2026-04-01',
        'group_id': group_fixture,
        'teacher_id': teacher_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    lesson_id = result['lesson_id']
    yield lesson_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lessons WHERE id = %s', [lesson_id])


def _lessons_done(group_id: int, student_id: int):
    with connection.cursor() as cur:
        cur.execute(
            'SELECT lessons_done FROM group_memberships WHERE group_id = %s AND student_id = %s',
            [group_id, student_id],
        )
        row = cur.fetchone()
    return row[0] if row else None


@pytest.fixture
def lessons_done():
    return _lessons_done
```

- [ ] **Step 3: Write the failing repository tests**

Create `journal_django/apps/extra_lessons/tests/test_extra_lessons_repository.py`:

```python
"""Integration-тесты apps.extra_lessons.repository (реальная БД)."""
from __future__ import annotations

import datetime

import pytest

from apps.extra_lessons import repository
from apps.extra_lessons.models import CANCELLED, DONE, SCHEDULED

pytestmark = pytest.mark.django_db


def test_create_assignment_creates_shell_and_participants(
    teacher_fixture, missed_lesson_fixture, student_fixture,
):
    assignment_id = repository.create_assignment(
        missed_lesson_id=missed_lesson_fixture,
        teacher_id=teacher_fixture,
        student_ids=[student_fixture],
        scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0),
        duration_minutes=45,
    )
    full = repository.get_assignment_full(assignment_id)
    assert full['status'] == SCHEDULED
    assert full['teacher_id'] == teacher_fixture
    assert full['missed_lesson_id'] == missed_lesson_fixture
    assert full['duration_minutes'] == 45
    assert [p['student_id'] for p in full['participants']] == [student_fixture]
    assert full['fact_lesson_id'] is None


def test_cancel_assignment_sets_status_cancelled(teacher_fixture, missed_lesson_fixture, student_fixture):
    assignment_id = repository.create_assignment(
        missed_lesson_id=missed_lesson_fixture, teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )
    repository.cancel_assignment(assignment_id)
    full = repository.get_assignment_full(assignment_id)
    assert full['status'] == CANCELLED


def test_cancel_assignment_raises_if_not_scheduled(teacher_fixture, missed_lesson_fixture, student_fixture):
    assignment_id = repository.create_assignment(
        missed_lesson_id=missed_lesson_fixture, teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )
    repository.cancel_assignment(assignment_id)
    with pytest.raises(ValueError):
        repository.cancel_assignment(assignment_id)


def test_mark_done_then_reset_to_scheduled_roundtrip(
    teacher_fixture, missed_lesson_fixture, student_fixture,
):
    assignment_id = repository.create_assignment(
        missed_lesson_id=missed_lesson_fixture, teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )
    repository.mark_done(assignment_id, fact_lesson_id=missed_lesson_fixture)  # реальный id не важен для этого теста
    full = repository.get_assignment_full(assignment_id)
    assert full['status'] == DONE
    assert full['fact_lesson_id'] == missed_lesson_fixture

    repository.reset_to_scheduled(assignment_id)
    full = repository.get_assignment_full(assignment_id)
    assert full['status'] == SCHEDULED
    assert full['fact_lesson_id'] is None


def test_participant_student_ids(teacher_fixture, missed_lesson_fixture, student_fixture):
    assignment_id = repository.create_assignment(
        missed_lesson_id=missed_lesson_fixture, teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )
    assert repository.participant_student_ids(assignment_id) == [student_fixture]


def test_has_active_assignment_for_student(teacher_fixture, missed_lesson_fixture, student_fixture):
    assert repository.has_active_assignment(missed_lesson_fixture, student_fixture) is False
    repository.create_assignment(
        missed_lesson_id=missed_lesson_fixture, teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )
    assert repository.has_active_assignment(missed_lesson_fixture, student_fixture) is True
```

- [ ] **Step 4: Run to confirm they fail**

Run: `cd journal_django && pytest apps/extra_lessons/tests/test_extra_lessons_repository.py -v`
Expected: `ModuleNotFoundError: No module named 'apps.extra_lessons.repository'`

- [ ] **Step 5: Implement `repository.py`**

```python
"""
ExtraLessonsRepository — единственное место ORM-доступа раздела extra_lessons.

Батч-запросы без N+1 (participant_names/assignments_in_window собирают все
имена одним IN-запросом на список назначений — см. Task 10 для потребителя
assignments_in_window в календаре).
"""
from __future__ import annotations

import datetime
from typing import Optional

from django.db import transaction
from django.db.models import F

from apps.extra_lessons.models import (
    CANCELLED, DONE, SCHEDULED,
    ExtraLessonAssignment, ExtraLessonParticipant,
)


def create_assignment(
    *,
    missed_lesson_id: int,
    teacher_id: int,
    student_ids: list[int],
    scheduled_date: datetime.date,
    scheduled_time: datetime.time,
    duration_minutes: int,
) -> int:
    """Создаёт назначение (status=scheduled) + участников. Возвращает id."""
    with transaction.atomic():
        obj = ExtraLessonAssignment.objects.create(
            missed_lesson_id=missed_lesson_id,
            teacher_id=teacher_id,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            duration_minutes=duration_minutes,
            status=SCHEDULED,
        )
        ExtraLessonParticipant.objects.bulk_create([
            ExtraLessonParticipant(assignment_id=obj.id, student_id=sid)
            for sid in student_ids
        ])
    return obj.id


def get_assignment_full(assignment_id: int) -> Optional[dict]:
    """Назначение + участники (id+имя) + метаданные пропущенного урока/учителя."""
    row = (
        ExtraLessonAssignment.objects
        .filter(id=assignment_id)
        .values(
            'id', 'teacher_id', 'missed_lesson_id', 'scheduled_date', 'scheduled_time',
            'duration_minutes', 'status', 'fact_lesson_id',
            teacher_name=F('teacher__name'),
            missed_lesson_group_id=F('missed_lesson__group_id'),
            missed_lesson_group_name=F('missed_lesson__group__name'),
            missed_lesson_date=F('missed_lesson__lesson_date'),
        )
        .first()
    )
    if row is None:
        return None
    row['participants'] = list(
        ExtraLessonParticipant.objects
        .filter(assignment_id=assignment_id)
        .order_by('student__full_name')
        .values('student_id', student_name=F('student__full_name'))
    )
    return row


def participant_student_ids(assignment_id: int) -> list[int]:
    return list(
        ExtraLessonParticipant.objects
        .filter(assignment_id=assignment_id)
        .values_list('student_id', flat=True)
    )


def has_active_assignment(missed_lesson_id: int, student_id: int) -> bool:
    """Есть ли уже НЕотменённое назначение доп.урока за этот пропуск у этого
    студента — не даём задвоить компенсацию одного пропуска."""
    return (
        ExtraLessonParticipant.objects
        .filter(
            student_id=student_id,
            assignment__missed_lesson_id=missed_lesson_id,
        )
        .exclude(assignment__status=CANCELLED)
        .exists()
    )


def cancel_assignment(assignment_id: int) -> None:
    """status → cancelled. ValueError, если не 'scheduled' (404 обрабатывает
    вызывающий сервис отдельно — до этого вызова)."""
    with transaction.atomic():
        obj = ExtraLessonAssignment.objects.select_for_update().filter(id=assignment_id).first()
        if obj is None:
            return
        if obj.status != SCHEDULED:
            raise ValueError('Отменить можно только ещё не проведённый доп.урок.')
        obj.status = CANCELLED
        obj.save(update_fields=['status'])


def mark_done(assignment_id: int, *, fact_lesson_id: int) -> None:
    ExtraLessonAssignment.objects.filter(id=assignment_id).update(
        status=DONE, fact_lesson_id=fact_lesson_id,
    )


def reset_to_scheduled(assignment_id: int) -> None:
    """Откат mark_done (удаление факта доп.урока) — см. services.delete_fact."""
    ExtraLessonAssignment.objects.filter(id=assignment_id).update(
        status=SCHEDULED, fact_lesson_id=None,
    )


def list_assignments(
    page: int = 1,
    page_size: int = 50,
    sort_by: str = 'scheduled_date',
    sort_dir: str = 'desc',
    filters: Optional[dict] = None,
) -> dict:
    """Пагинированный список назначений. Контракт: {rows, total, page, page_size}."""
    if filters is None:
        filters = {}
    sortable = {
        'scheduled_date': 'scheduled_date',
        'status': 'status',
        'teacher_name': 'teacher__name',
    }
    sort_field = sortable.get(sort_by) or sortable['scheduled_date']
    order_prefix = '' if sort_dir == 'asc' else '-'

    qs = ExtraLessonAssignment.objects.all()
    status_filter = filters.get('status')
    if status_filter not in (None, ''):
        qs = qs.filter(status=status_filter)
    teacher_id = filters.get('teacher_id')
    if teacher_id not in (None, ''):
        qs = qs.filter(teacher_id=int(teacher_id))

    total = qs.count()
    offset = max(0, (page - 1) * page_size)
    ordered = qs.order_by(f'{order_prefix}{sort_field}', '-id')
    rows = list(
        ordered[offset:offset + page_size].values(
            'id', 'teacher_id', 'missed_lesson_id', 'scheduled_date', 'scheduled_time',
            'duration_minutes', 'status', 'fact_lesson_id',
            teacher_name=F('teacher__name'),
            missed_lesson_group_name=F('missed_lesson__group__name'),
            missed_lesson_date=F('missed_lesson__lesson_date'),
        )
    )
    if rows:
        ids = [r['id'] for r in rows]
        names_by_assignment: dict[int, list[dict]] = {}
        for aid, sid, name in (
            ExtraLessonParticipant.objects
            .filter(assignment_id__in=ids)
            .order_by('student__full_name')
            .values_list('assignment_id', 'student_id', 'student__full_name')
        ):
            names_by_assignment.setdefault(aid, []).append(
                {'student_id': sid, 'student_name': name}
            )
        for r in rows:
            r['participants'] = names_by_assignment.get(r['id'], [])

    return {'rows': rows, 'total': total, 'page': page, 'page_size': page_size}


def assignments_in_window(
    teacher_id: int, window_from: datetime.date, window_to: datetime.date,
) -> list[dict]:
    """Назначения ОДНОГО преподавателя за окно — источник календаря (Task 10)."""
    rows = list(
        ExtraLessonAssignment.objects
        .filter(
            teacher_id=teacher_id,
            scheduled_date__gte=window_from,
            scheduled_date__lte=window_to,
        )
        .values(
            'id', 'scheduled_date', 'scheduled_time', 'duration_minutes', 'status',
            teacher_name=F('teacher__name'),
            missed_lesson_group_name=F('missed_lesson__group__name'),
        )
    )
    if not rows:
        return []
    ids = [r['id'] for r in rows]
    names_by_assignment: dict[int, list[str]] = {}
    for aid, name in (
        ExtraLessonParticipant.objects
        .filter(assignment_id__in=ids)
        .order_by('student__full_name')
        .values_list('assignment_id', 'student__full_name')
    ):
        names_by_assignment.setdefault(aid, []).append(name)
    for r in rows:
        r['student_names'] = names_by_assignment.get(r['id'], [])
    return rows
```

- [ ] **Step 6: Run the tests to confirm they pass**

Run: `cd journal_django && pytest apps/extra_lessons/tests/test_extra_lessons_repository.py -v`
Expected: all PASSED.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/extra_lessons/tests journal_django/apps/extra_lessons/repository.py
git commit -m "feat(extra-lessons): add repository (create/cancel/mark_done/list/window)"
```

---

### Task 6: `apps/extra_lessons/services.py` — create/cancel/record/delete orchestration

**Files:**
- Create: `journal_django/apps/extra_lessons/exceptions.py`
- Create: `journal_django/apps/extra_lessons/services.py`
- Test: `journal_django/apps/extra_lessons/tests/test_extra_lessons_services.py`

- [ ] **Step 1: Write `exceptions.py`**

```python
"""Доменные исключения раздела extra_lessons (см. apps/lessons/exceptions.py для паттерна)."""
from __future__ import annotations


class MissedLessonNotFound(Exception):
    """missed_lesson_id не ссылается на существующий проведённый урок."""


class DuplicateAssignment(Exception):
    """У студента уже есть активное (не отменённое) назначение за этот же пропуск."""

    def __init__(self, student_names: list[str]) -> None:
        self.student_names = student_names
        names = ', '.join(student_names)
        super().__init__(
            f'Уже есть активный доп.урок за этот пропуск у: {names}.'
        )


class NotTeachersAssignment(Exception):
    """Преподаватель пытается провести/посмотреть чужое назначение."""
```

- [ ] **Step 2: Write the failing service tests**

Create `journal_django/apps/extra_lessons/tests/test_extra_lessons_services.py`:

```python
"""Integration-тесты apps.extra_lessons.services (реальная БД)."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection

from apps.extra_lessons import services
from apps.extra_lessons.exceptions import (
    DuplicateAssignment, MissedLessonNotFound, NotTeachersAssignment,
)
from apps.extra_lessons.models import CANCELLED, DONE, SCHEDULED
from apps.lessons.models import Lesson, LessonAttendance
from apps.payroll.models import Payroll

pytestmark = pytest.mark.django_db


def _cleanup_fact(lesson_id):
    with connection.cursor() as cur:
        cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lessons WHERE id = %s', [lesson_id])


class _FakeRequest:
    """Минимальная заглушка request для log_event (без HTTP-контекста)."""
    META = {}
    user = None


def test_create_assignment_happy_path(teacher_fixture, missed_lesson_fixture, student_fixture):
    result = services.create_assignment(
        {
            'missed_lesson_id': missed_lesson_fixture,
            'teacher_id': teacher_fixture,
            'student_ids': [student_fixture],
            'scheduled_date': '2026-04-05',
            'scheduled_time': '15:00',
            'duration_minutes': 45,
        },
        _FakeRequest(),
    )
    assert result['status'] == SCHEDULED
    assert result['missed_lesson_id'] == missed_lesson_fixture


def test_create_assignment_raises_if_missed_lesson_not_found(teacher_fixture, student_fixture):
    with pytest.raises(MissedLessonNotFound):
        services.create_assignment(
            {
                'missed_lesson_id': 999_999_999,
                'teacher_id': teacher_fixture,
                'student_ids': [student_fixture],
                'scheduled_date': '2026-04-05',
                'scheduled_time': '15:00',
                'duration_minutes': 45,
            },
            _FakeRequest(),
        )


def test_create_assignment_raises_on_duplicate(teacher_fixture, missed_lesson_fixture, student_fixture):
    data = {
        'missed_lesson_id': missed_lesson_fixture,
        'teacher_id': teacher_fixture,
        'student_ids': [student_fixture],
        'scheduled_date': '2026-04-05',
        'scheduled_time': '15:00',
        'duration_minutes': 45,
    }
    services.create_assignment(data, _FakeRequest())
    with pytest.raises(DuplicateAssignment):
        services.create_assignment(data, _FakeRequest())


def test_cancel_assignment(teacher_fixture, missed_lesson_fixture, student_fixture):
    created = services.create_assignment(
        {
            'missed_lesson_id': missed_lesson_fixture, 'teacher_id': teacher_fixture,
            'student_ids': [student_fixture], 'scheduled_date': '2026-04-05',
            'scheduled_time': '15:00', 'duration_minutes': 45,
        },
        _FakeRequest(),
    )
    result = services.cancel_assignment(created['id'], _FakeRequest())
    assert result['status'] == CANCELLED


def test_record_creates_fact_and_applies_makeup_attendance(
    group_fixture, teacher_fixture, other_teacher_fixture, missed_lesson_fixture,
    student_fixture, lessons_done,
):
    created = services.create_assignment(
        {
            'missed_lesson_id': missed_lesson_fixture, 'teacher_id': other_teacher_fixture,
            'student_ids': [student_fixture], 'scheduled_date': '2026-04-05',
            'scheduled_time': '15:00', 'duration_minutes': 45,
        },
        _FakeRequest(),
    )
    assert lessons_done(group_fixture, student_fixture) == Decimal('0')

    result = services.record(
        created['id'],
        teacher_id=other_teacher_fixture,
        attendance=[{'student_id': student_fixture, 'present': True}],
        record_url=None,
        submitted_by_token='acct:1',
        submit_date='2026-04-05',
        request=_FakeRequest(),
    )
    try:
        assert result['payment'] == 200
        assert result['penalty'] == 0

        fact = Lesson.objects.get(id=result['lesson_id'])
        assert fact.lesson_type == 'extra'
        assert fact.teacher_id == other_teacher_fixture
        assert Payroll.objects.get(lesson_id=fact.id).payment == 200

        # Ретроактивная отметка на исходном (пропущенном) уроке.
        att = LessonAttendance.objects.get(lesson_id=missed_lesson_fixture, student_id=student_fixture)
        assert att.present is True
        assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')
    finally:
        _cleanup_fact(result['lesson_id'])


def test_record_rejects_wrong_teacher(teacher_fixture, other_teacher_fixture, missed_lesson_fixture, student_fixture):
    created = services.create_assignment(
        {
            'missed_lesson_id': missed_lesson_fixture, 'teacher_id': teacher_fixture,
            'student_ids': [student_fixture], 'scheduled_date': '2026-04-05',
            'scheduled_time': '15:00', 'duration_minutes': 45,
        },
        _FakeRequest(),
    )
    with pytest.raises(NotTeachersAssignment):
        services.record(
            created['id'], teacher_id=other_teacher_fixture,
            attendance=[{'student_id': student_fixture, 'present': True}],
            record_url=None, submitted_by_token='acct:2', submit_date='2026-04-05',
            request=_FakeRequest(),
        )


def test_delete_fact_reverts_makeup_attendance(
    group_fixture, teacher_fixture, missed_lesson_fixture, student_fixture, lessons_done,
):
    created = services.create_assignment(
        {
            'missed_lesson_id': missed_lesson_fixture, 'teacher_id': teacher_fixture,
            'student_ids': [student_fixture], 'scheduled_date': '2026-04-05',
            'scheduled_time': '15:00', 'duration_minutes': 45,
        },
        _FakeRequest(),
    )
    result = services.record(
        created['id'], teacher_id=teacher_fixture,
        attendance=[{'student_id': student_fixture, 'present': True}],
        record_url=None, submitted_by_token='acct:1', submit_date='2026-04-05',
        request=_FakeRequest(),
    )
    assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')

    ok = services.delete_fact(created['id'], _FakeRequest())
    assert ok is True
    assert lessons_done(group_fixture, student_fixture) == Decimal('0')
    assert not Lesson.objects.filter(id=result['lesson_id']).exists()
    assert not Payroll.objects.filter(lesson_id=result['lesson_id']).exists()

    from apps.extra_lessons import repository
    full = repository.get_assignment_full(created['id'])
    assert full['status'] == SCHEDULED
    assert full['fact_lesson_id'] is None
```

- [ ] **Step 3: Run to confirm they fail**

Run: `cd journal_django && pytest apps/extra_lessons/tests/test_extra_lessons_services.py -v`
Expected: `ModuleNotFoundError: No module named 'apps.extra_lessons.services'`

- [ ] **Step 4: Implement `services.py`**

```python
"""
ExtraLessonsService — оркестрация назначения/отмены/фиксации/удаления
доп.урока. Транзакции — здесь (как apps.lessons.services.record_lesson);
repository — чистые ORM-операции.
"""
from __future__ import annotations

import datetime
from typing import Optional

from django.db import transaction

from apps.audit.services import log_event
from apps.extra_lessons import repository
from apps.extra_lessons.exceptions import (
    DuplicateAssignment, MissedLessonNotFound, NotTeachersAssignment,
)
from apps.extra_lessons.models import DONE, SCHEDULED
from apps.lessons import repository as lessons_repository
from apps.lessons.models import Lesson
from apps.payroll.calculator import calculate_extra_lesson_payment, calculate_penalty
from apps.payroll.models import Payroll
from apps.students.models import Student

# insert_payroll (apps.lessons.repository) принимает ровно этот набор полей —
# переиспользуем его вместо повторной ORM-вставки Payroll здесь (единственное
# отличие доп.урока — ОТКУДА берутся payment/penalty, см. record() ниже).


def _actor(request):
    return getattr(getattr(request, 'user', None), 'email', None)


def _to_date(value: str) -> datetime.date:
    return datetime.date.fromisoformat(value)


def _to_time(value: str) -> datetime.time:
    parts = [int(x) for x in value.split(':')]
    return datetime.time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)


def create_assignment(data: dict, request) -> dict:
    """
    Создаёт назначение доп.урока. Валидация:
      - missed_lesson_id обязан существовать (иначе MissedLessonNotFound)
      - ни у одного из student_ids не должно быть уже активного назначения
        за этот же пропуск (иначе DuplicateAssignment)
    """
    missed_lesson_id = data['missed_lesson_id']
    if not Lesson.objects.filter(id=missed_lesson_id).exists():
        raise MissedLessonNotFound(f'Урок #{missed_lesson_id} не найден.')

    student_ids = data['student_ids']
    duplicates = [
        sid for sid in student_ids
        if repository.has_active_assignment(missed_lesson_id, sid)
    ]
    if duplicates:
        names = list(
            Student.objects.filter(id__in=duplicates).values_list('full_name', flat=True)
        )
        raise DuplicateAssignment(names)

    assignment_id = repository.create_assignment(
        missed_lesson_id=missed_lesson_id,
        teacher_id=data['teacher_id'],
        student_ids=student_ids,
        scheduled_date=_to_date(data['scheduled_date']),
        scheduled_time=_to_time(data['scheduled_time']),
        duration_minutes=data['duration_minutes'],
    )
    log_event(
        'extra_lesson_create',
        actor_email=_actor(request),
        target_id=assignment_id,
        meta={'missed_lesson_id': missed_lesson_id, 'student_ids': student_ids},
        request=request,
    )
    return repository.get_assignment_full(assignment_id)


def cancel_assignment(assignment_id: int, request) -> Optional[dict]:
    """None → назначения нет (404). ValueError → уже done/cancelled (view → 409)."""
    if repository.get_assignment_full(assignment_id) is None:
        return None
    repository.cancel_assignment(assignment_id)
    log_event(
        'extra_lesson_cancel', actor_email=_actor(request),
        target_id=assignment_id, meta={}, request=request,
    )
    return repository.get_assignment_full(assignment_id)


def get_assignment_for_teacher(assignment_id: int, teacher_id: int) -> Optional[dict]:
    """None → не найдено ИЛИ принадлежит другому преподавателю (единый 404 —
    не раскрываем чужим существование назначения)."""
    full = repository.get_assignment_full(assignment_id)
    if full is None or full['teacher_id'] != teacher_id:
        return None
    return full


def record(
    assignment_id: int,
    *,
    teacher_id: int,
    attendance: list[dict],
    record_url: Optional[str],
    submitted_by_token: str,
    submit_date: str,
    request,
) -> Optional[dict]:
    """
    Фиксация проведения доп.урока. Атомарно:
      1. Lesson(lesson_type='extra') — group/lesson_number унаследованы от
         пропущенного урока, teacher/duration — от назначения.
      2. LessonAttendance для участников ЭТОГО доп.урока (кто реально пришёл).
      3. Payroll — payment=200×present (calculate_extra_lesson_payment),
         penalty — та же формула просрочки, что у обычных уроков.
      4. Для присутствовавших — apply_makeup_attendance на ИСХОДНОМ уроке.
      5. ExtraLessonAssignment → status=done, fact_lesson=новый Lesson.

    None → назначения нет (view → 404). NotTeachersAssignment → чужое
    назначение (view → 403). ValueError → уже done/cancelled (view → 409).
    """
    full = repository.get_assignment_full(assignment_id)
    if full is None:
        return None
    if full['teacher_id'] != teacher_id:
        raise NotTeachersAssignment('Это назначение принадлежит другому преподавателю.')
    if full['status'] != SCHEDULED:
        raise ValueError('Доп.урок уже проведён или отменён.')

    present_count = sum(1 for a in attendance if a['present'])
    payment = calculate_extra_lesson_payment(present_count)
    penalty = calculate_penalty(
        full['scheduled_date'].isoformat(), submit_date, present_count,
    )

    with transaction.atomic():
        lesson_id = lessons_repository.insert_lesson({
            'lesson_date': full['scheduled_date'].isoformat(),
            'teacher_id': teacher_id,
            'group_id': full['missed_lesson_group_id'],
            'original_teacher_id': None,
            # lesson_number наследуется от пропущенного урока — доп.урок
            # компенсирует именно ЭТУ позицию курса, показываем это в списке
            # уроков (lesson_type='extra' отличает его от исходного).
            'lesson_number': Lesson.objects.get(id=full['missed_lesson_id']).lesson_number,
            'lesson_duration_minutes': full['duration_minutes'],
            'lesson_type': 'extra',
            'record_url': record_url,
            'submitted_by_token': submitted_by_token,
        })
        lessons_repository.insert_attendance(lesson_id, attendance)
        lessons_repository.insert_payroll({
            'lesson_id': lesson_id,
            'teacher_id': teacher_id,
            'total_students': len(attendance),
            'present_count': present_count,
            'payment': payment,
            'penalty': penalty,
        })
        for a in attendance:
            if a['present']:
                lessons_repository.apply_makeup_attendance(full['missed_lesson_id'], a['student_id'])
        repository.mark_done(assignment_id, fact_lesson_id=lesson_id)

    log_event(
        'extra_lesson_record', actor_email=_actor(request),
        target_id=assignment_id,
        meta={'lesson_id': lesson_id, 'payment': payment, 'penalty': penalty},
        request=request,
    )
    return {'lesson_id': lesson_id, 'payment': payment, 'penalty': penalty}


def delete_fact(assignment_id: int, request) -> bool:
    """
    Откатывает проведённый доп.урок: возвращает исходному уроку прежнюю
    посещаемость/lessons_done, удаляет Payroll+Lesson доп.урока, возвращает
    назначение в status=scheduled. ValueError → назначение не в статусе done
    (view → 409). False → назначения нет (view → 404).
    """
    full = repository.get_assignment_full(assignment_id)
    if full is None:
        return False
    if full['status'] != DONE:
        raise ValueError('Удалить факт можно только у проведённого доп.урока.')

    fact_lesson_id = full['fact_lesson_id']
    with transaction.atomic():
        present_ids = list(
            Lesson.objects.get(id=fact_lesson_id).attendance
            .filter(present=True).values_list('student_id', flat=True)
        )
        for sid in present_ids:
            lessons_repository.revert_makeup_attendance(full['missed_lesson_id'], sid)
        Payroll.objects.filter(lesson_id=fact_lesson_id).delete()
        Lesson.objects.filter(id=fact_lesson_id).delete()
        repository.reset_to_scheduled(assignment_id)

    log_event(
        'extra_lesson_delete', actor_email=_actor(request),
        target_id=assignment_id, meta={'fact_lesson_id': fact_lesson_id}, request=request,
    )
    return True


def list_assignments(
    page: int = 1, page_size: int = 50, sort_by: str = 'scheduled_date',
    sort_dir: str = 'desc', filters: Optional[dict] = None,
) -> dict:
    return repository.list_assignments(
        page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir, filters=filters,
    )
```

- [ ] **Step 5: Run the tests to confirm they pass**

Run: `cd journal_django && pytest apps/extra_lessons/tests/test_extra_lessons_services.py -v`
Expected: all PASSED.

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/extra_lessons/exceptions.py journal_django/apps/extra_lessons/services.py journal_django/apps/extra_lessons/tests/test_extra_lessons_services.py
git commit -m "feat(extra-lessons): add services (create/cancel/record/delete)"
```

---

### Task 7: Serializers

**Files:**
- Create: `journal_django/apps/extra_lessons/serializers.py`
- Test: `journal_django/apps/extra_lessons/tests/test_extra_lessons_serializers.py`

- [ ] **Step 1: Write the failing tests**

Create `journal_django/apps/extra_lessons/tests/test_extra_lessons_serializers.py`:

```python
"""Unit-тесты сериализаторов extra_lessons (без БД)."""
from __future__ import annotations

from apps.extra_lessons.serializers import (
    ExtraLessonCreateSerializer, ExtraLessonRecordSerializer,
)


def test_create_serializer_valid():
    s = ExtraLessonCreateSerializer(data={
        'missed_lesson_id': 1, 'teacher_id': 2, 'student_ids': [3, 4],
        'scheduled_date': '2026-04-05', 'scheduled_time': '15:00', 'duration_minutes': 45,
    })
    assert s.is_valid(), s.errors


def test_create_serializer_rejects_bad_duration():
    s = ExtraLessonCreateSerializer(data={
        'missed_lesson_id': 1, 'teacher_id': 2, 'student_ids': [3],
        'scheduled_date': '2026-04-05', 'scheduled_time': '15:00', 'duration_minutes': 20,
    })
    assert not s.is_valid()
    assert 'duration_minutes' in s.errors


def test_create_serializer_rejects_empty_students():
    s = ExtraLessonCreateSerializer(data={
        'missed_lesson_id': 1, 'teacher_id': 2, 'student_ids': [],
        'scheduled_date': '2026-04-05', 'scheduled_time': '15:00', 'duration_minutes': 45,
    })
    assert not s.is_valid()
    assert 'student_ids' in s.errors


def test_create_serializer_rejects_duplicate_students():
    s = ExtraLessonCreateSerializer(data={
        'missed_lesson_id': 1, 'teacher_id': 2, 'student_ids': [3, 3],
        'scheduled_date': '2026-04-05', 'scheduled_time': '15:00', 'duration_minutes': 45,
    })
    assert not s.is_valid()
    assert 'student_ids' in s.errors


def test_create_serializer_rejects_unknown_field():
    s = ExtraLessonCreateSerializer(data={
        'missed_lesson_id': 1, 'teacher_id': 2, 'student_ids': [3],
        'scheduled_date': '2026-04-05', 'scheduled_time': '15:00', 'duration_minutes': 45,
        'payroll': {'payment': 999},
    })
    assert not s.is_valid()


def test_record_serializer_valid():
    s = ExtraLessonRecordSerializer(data={
        'attendance': [{'student_id': 1, 'present': True}],
    })
    assert s.is_valid(), s.errors


def test_record_serializer_rejects_empty_attendance():
    s = ExtraLessonRecordSerializer(data={'attendance': []})
    assert not s.is_valid()
```

- [ ] **Step 2: Run to confirm they fail**

Run: `cd journal_django && pytest apps/extra_lessons/tests/test_extra_lessons_serializers.py -v`
Expected: `ModuleNotFoundError: No module named 'apps.extra_lessons.serializers'`

- [ ] **Step 3: Implement `serializers.py`**

```python
"""
Сериализаторы-валидаторы extra_lessons. StrictSerializer — тот же паттерн,
что apps/scheduling/serializers.py (отклонять неизвестные поля).
"""
from __future__ import annotations

import re

from rest_framework import serializers

from apps.core.fields import DateStringField
from apps.extra_lessons.models import VALID_DURATIONS

_TIME_RE = re.compile(r'^\d{2}:\d{2}(:\d{2})?$')


class StrictSerializer(serializers.Serializer):
    """Базовый сериализатор, отклоняющий неизвестные поля."""

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {k: 'Неизвестное поле.' for k in sorted(unknown)}
            )
        return attrs


class ExtraLessonCreateSerializer(StrictSerializer):
    """POST /api/admin/extra-lessons — назначить доп.урок."""

    missed_lesson_id = serializers.IntegerField(min_value=1)
    teacher_id = serializers.IntegerField(min_value=1)
    student_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False,
    )
    scheduled_date = DateStringField()
    scheduled_time = serializers.CharField()
    duration_minutes = serializers.ChoiceField(choices=VALID_DURATIONS)

    def validate_scheduled_time(self, value):
        if not value or not _TIME_RE.match(value):
            raise serializers.ValidationError('Время должно быть в формате HH:MM или HH:MM:SS.')
        return value

    def validate_student_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError('Ученики не должны повторяться.')
        return value


class ExtraLessonAttendanceItemSerializer(serializers.Serializer):
    student_id = serializers.IntegerField(min_value=1)
    present = serializers.BooleanField()


class ExtraLessonRecordSerializer(StrictSerializer):
    """POST /api/extra-lessons/:id/record — фиксация проведения (teacher)."""

    record_url = serializers.CharField(
        allow_null=True, allow_blank=True, required=False, trim_whitespace=False,
    )
    attendance = ExtraLessonAttendanceItemSerializer(many=True, allow_empty=False)
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `cd journal_django && pytest apps/extra_lessons/tests/test_extra_lessons_serializers.py -v`
Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/extra_lessons/serializers.py journal_django/apps/extra_lessons/tests/test_extra_lessons_serializers.py
git commit -m "feat(extra-lessons): add request serializers"
```

---

### Task 8: Views, URLs, config mount, changelog labels

**Files:**
- Create: `journal_django/apps/extra_lessons/views.py`
- Create: `journal_django/apps/extra_lessons/urls.py`
- Create: `journal_django/apps/extra_lessons/teacher_urls.py`
- Modify: `journal_django/config/urls.py`
- Modify: `journal_django/apps/changelog/labels.py`
- Test: `journal_django/apps/extra_lessons/tests/test_extra_lessons_api.py`

- [ ] **Step 1: Write `views.py`**

```python
"""
Тонкие APIView для extra_lessons.

Admin (IsManagerOrAdmin, менеджер/админ/суперадмин — явное требование фичи,
не общий ReadStaffWriteAdmin раздела lessons):
  GET  /api/admin/extra-lessons             → список {rows,total,page,page_size}
  POST /api/admin/extra-lessons             → 201 (назначение)
  GET  /api/admin/extra-lessons/:id         → 200 | 404
  DELETE /api/admin/extra-lessons/:id       → 204 | 404 | 409 (не done)
  POST /api/admin/extra-lessons/:id/cancel  → 200 | 404 | 409 (не scheduled)

Teacher (IsTeacher, скоуп — своё назначение):
  GET  /api/extra-lessons/:id         → 200 | 404 (чужое = 404, не 403 — не
                                         раскрываем существование чужих назначений)
  POST /api/extra-lessons/:id/record  → 200 | 404 | 403 (чужое) | 409 (не scheduled)
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin, IsTeacher
from apps.extra_lessons import services
from apps.extra_lessons.exceptions import (
    DuplicateAssignment, MissedLessonNotFound, NotTeachersAssignment,
)
from apps.extra_lessons.serializers import (
    ExtraLessonCreateSerializer, ExtraLessonRecordSerializer,
)

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 500


def _parse_list_params(request: Request) -> dict:
    qp = request.query_params
    try:
        page = max(1, int(qp.get('page') or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        raw_page_size = int(qp.get('page_size') or 0)
    except (TypeError, ValueError):
        raw_page_size = 0
    page_size = min(_MAX_PAGE_SIZE, max(1, raw_page_size or _DEFAULT_PAGE_SIZE))
    sort_by = qp.get('sort_by') or 'scheduled_date'
    sort_dir = qp.get('sort_dir')
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'desc'
    filters = {}
    if qp.get('status'):
        filters['status'] = qp['status']
    if qp.get('teacher_id'):
        filters['teacher_id'] = qp['teacher_id']
    return {'page': page, 'page_size': page_size, 'sort_by': sort_by, 'sort_dir': sort_dir, 'filters': filters}


class ExtraLessonListCreateView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        params = _parse_list_params(request)
        return Response(services.list_assignments(**params))

    def post(self, request: Request) -> Response:
        serializer = ExtraLessonCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = services.create_assignment(serializer.validated_data, request)
        except MissedLessonNotFound as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except DuplicateAssignment as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_201_CREATED)


class ExtraLessonDetailView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        from apps.extra_lessons import repository
        full = repository.get_assignment_full(pk)
        if full is None:
            raise NotFound({'error': 'Not found'})
        return Response(full)

    def delete(self, request: Request, pk: int) -> Response:
        try:
            ok = services.delete_fact(pk, request)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExtraLessonCancelView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        try:
            result = services.cancel_assignment(pk, request)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)


class TeacherExtraLessonDetailView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request: Request, pk: int) -> Response:
        result = services.get_assignment_for_teacher(pk, request.user.teacher_id)
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)


class TeacherExtraLessonRecordView(APIView):
    permission_classes = [IsTeacher]

    def post(self, request: Request, pk: int) -> Response:
        serializer = ExtraLessonRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        try:
            result = services.record(
                pk,
                teacher_id=request.user.teacher_id,
                attendance=v['attendance'],
                record_url=v.get('record_url') or None,
                submitted_by_token=f'acct:{request.user.id}',
                submit_date=timezone_today_msk(),
                request=request,
            )
        except NotTeachersAssignment as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)


def timezone_today_msk() -> str:
    """'YYYY-MM-DD' — сегодня по МСК (для штрафа за просрочку заполнения)."""
    from apps.core.utils.dates import msk_now
    return msk_now().date().isoformat()
```

- [ ] **Step 2: Write `urls.py` (admin) and `teacher_urls.py`**

`journal_django/apps/extra_lessons/urls.py`:

```python
"""URL-маршруты admin-раздела extra_lessons. Монтируется как
/api/admin/extra-lessons в config/urls.py. APPEND_SLASH=False."""
from django.urls import path

from apps.extra_lessons.views import (
    ExtraLessonCancelView, ExtraLessonDetailView, ExtraLessonListCreateView,
)

urlpatterns = [
    path('', ExtraLessonListCreateView.as_view(), name='extra-lessons-list-create'),
    path('/<int:pk>', ExtraLessonDetailView.as_view(), name='extra-lessons-detail'),
    path('/<int:pk>/cancel', ExtraLessonCancelView.as_view(), name='extra-lessons-cancel'),
]
```

`journal_django/apps/extra_lessons/teacher_urls.py`:

```python
"""URL-маршруты teacher-раздела extra_lessons. Монтируется как
/api/extra-lessons в config/urls.py (после /api/admin — teacher-guard)."""
from django.urls import path

from apps.extra_lessons.views import (
    TeacherExtraLessonDetailView, TeacherExtraLessonRecordView,
)

urlpatterns = [
    path('/<int:pk>', TeacherExtraLessonDetailView.as_view(), name='teacher-extra-lessons-detail'),
    path('/<int:pk>/record', TeacherExtraLessonRecordView.as_view(), name='teacher-extra-lessons-record'),
]
```

- [ ] **Step 3: Mount both in `config/urls.py`**

In `journal_django/config/urls.py`, add the admin mount next to the other `/api/admin/*` includes (right after the lessons/payroll block), and the teacher mount next to the teacher_spa/scheduling includes:

```python
    # Phase 6 — lessons + attendance
    path('api/admin/lessons', include('apps.lessons.urls')),
    # Phase 7 — payroll
    path('api/admin/payroll', include('apps.payroll.urls')),
    # Доп.уроки (компенсация пропусков) — admin CRUD
    path('api/admin/extra-lessons', include('apps.extra_lessons.urls')),
```

and:

```python
    # Phase 10 — teacher SPA (/api, после /api/admin — admin стоит выше, как в Express)
    path('api', include('apps.teacher_spa.urls')),
    # Планирование занятий — календарь плановых occurrences (/api/calendar, role=teacher)
    path('api', include('apps.scheduling.urls')),
    # Доп.уроки — фиксация проведения преподавателем (/api/extra-lessons, role=teacher)
    path('api/extra-lessons', include('apps.extra_lessons.teacher_urls')),
```

- [ ] **Step 4: Add changelog label rules**

In `journal_django/apps/changelog/labels.py`, add after the `lessons` block (before `# payroll / settings`):

```python
    # extra_lessons (доп.уроки)
    ('POST', re.compile(r'^/api/admin/extra-lessons$'), 'extra_lesson.create'),
    ('POST', re.compile(r'^/api/admin/extra-lessons/\d+/cancel$'), 'extra_lesson.cancel'),
    ('DELETE', re.compile(r'^/api/admin/extra-lessons/\d+$'), 'extra_lesson.delete'),
    ('POST', re.compile(r'^/api/extra-lessons/\d+/record$'), 'extra_lesson.record'),
```

- [ ] **Step 5: Write the failing API tests**

Create `journal_django/apps/extra_lessons/tests/test_extra_lessons_api.py` (follows the auth-fixture pattern used across the repo's `*_api.py` tests — reuse the root `api_client`/`login_as` fixtures already available to every app's tests):

```python
"""API-тесты extra_lessons: RBAC + основные сценарии через HTTP."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_manager_can_create_assignment(api_client, login_as, teacher_fixture, missed_lesson_fixture, student_fixture):
    login_as(api_client, role='manager')
    resp = api_client.post('/api/admin/extra-lessons', {
        'missed_lesson_id': missed_lesson_fixture,
        'teacher_id': teacher_fixture,
        'student_ids': [student_fixture],
        'scheduled_date': '2026-04-05',
        'scheduled_time': '15:00',
        'duration_minutes': 45,
    }, format='json')
    assert resp.status_code == 201
    assert resp.data['status'] == 'scheduled'


def test_teacher_cannot_create_assignment(api_client, login_as, teacher_fixture, missed_lesson_fixture, student_fixture):
    login_as(api_client, role='teacher')
    resp = api_client.post('/api/admin/extra-lessons', {
        'missed_lesson_id': missed_lesson_fixture,
        'teacher_id': teacher_fixture,
        'student_ids': [student_fixture],
        'scheduled_date': '2026-04-05',
        'scheduled_time': '15:00',
        'duration_minutes': 45,
    }, format='json')
    assert resp.status_code == 403


def test_unauthenticated_gets_401_or_403(api_client, missed_lesson_fixture, teacher_fixture, student_fixture):
    resp = api_client.post('/api/admin/extra-lessons', {
        'missed_lesson_id': missed_lesson_fixture,
        'teacher_id': teacher_fixture,
        'student_ids': [student_fixture],
        'scheduled_date': '2026-04-05',
        'scheduled_time': '15:00',
        'duration_minutes': 45,
    }, format='json')
    assert resp.status_code in (401, 403)


def test_cancel_conflict_when_already_cancelled(api_client, login_as, teacher_fixture, missed_lesson_fixture, student_fixture):
    login_as(api_client, role='admin')
    created = api_client.post('/api/admin/extra-lessons', {
        'missed_lesson_id': missed_lesson_fixture, 'teacher_id': teacher_fixture,
        'student_ids': [student_fixture], 'scheduled_date': '2026-04-05',
        'scheduled_time': '15:00', 'duration_minutes': 45,
    }, format='json').data
    api_client.post(f'/api/admin/extra-lessons/{created["id"]}/cancel')
    resp = api_client.post(f'/api/admin/extra-lessons/{created["id"]}/cancel')
    assert resp.status_code == 409
```

> If this repo's convention for `api_client`/`login_as` fixture names differs, check an existing `apps/lessons/tests/test_lessons_api.py` or `apps/scheduling/tests/test_calendar_api.py` for the exact fixture names/signatures used for authenticated requests and match them here — don't invent new auth plumbing.

- [ ] **Step 6: Run to confirm they fail, then implement until green**

Run: `cd journal_django && pytest apps/extra_lessons/tests/test_extra_lessons_api.py -v`
Iterate on `views.py`/`urls.py` until all pass. Expected final: all PASSED.

- [ ] **Step 7: Run the changelog label test + the full extra_lessons suite**

Run: `cd journal_django && pytest apps/changelog/tests/test_registry.py apps/extra_lessons -v`
Expected: all PASSED.

- [ ] **Step 8: Sanity-check the whole suite hasn't regressed**

Run: `cd journal_django && pytest apps/lessons apps/payroll apps/scheduling apps/changelog -q`
Expected: all PASSED (no regressions in the apps this feature touches).

- [ ] **Step 9: Commit**

```bash
git add journal_django/apps/extra_lessons/views.py journal_django/apps/extra_lessons/urls.py journal_django/apps/extra_lessons/teacher_urls.py journal_django/apps/extra_lessons/tests/test_extra_lessons_api.py journal_django/config/urls.py journal_django/apps/changelog/labels.py
git commit -m "feat(extra-lessons): add admin+teacher views/urls, mount, changelog labels"
```

---

### Task 9: Frontend changelog labels

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/labels.ts`

- [ ] **Step 1: Add operation labels**

In `journal_django/frontend/admin-src/src/lib/labels.ts`, in `CHANGELOG_OPERATION_LABELS`, add after the `lesson.*` entries:

```typescript
  'extra_lesson.create': 'Назначение доп.урока',
  'extra_lesson.cancel': 'Отмена доп.урока',
  'extra_lesson.delete': 'Удаление доп.урока',
  'extra_lesson.record': 'Проведение доп.урока',
```

- [ ] **Step 2: Add entity labels**

In the same file, in `CHANGELOG_ENTITY_LABELS`, add after `payroll`:

```typescript
  extra_lesson_assignment:  'Доп.урок (назначение)',
  extra_lesson_participant: 'Доп.урок (участник)',
```

- [ ] **Step 3: Verify the admin frontend still typechecks**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: build succeeds (no TS errors).

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/lib/labels.ts
git commit -m "feat(admin): add changelog labels for extra_lesson operations"
```

---

### Task 10: Calendar merge — extra lesson cards in `/api/calendar`

**Files:**
- Modify: `journal_django/apps/scheduling/services.py`
- Modify: `journal_django/frontend/admin-src/src/shared/calendar/types.ts`
- Modify: `journal_django/frontend/teacher-src/src/lib/types.ts`
- Test: `journal_django/apps/scheduling/tests/test_calendar_api.py`

- [ ] **Step 1: Write the failing backend test**

Add to `journal_django/apps/scheduling/tests/test_calendar_api.py` (check the file's existing fixture names first — reuse them; this sketch assumes `teacher_id_fixture`/`group_fixture`-style fixtures matching the file's own conftest):

```python
def test_calendar_includes_extra_lesson_assignment(
    api_client, login_as, teacher_id_fixture, other_teacher_id_fixture,
    group_fixture, student_fixture, membership_fixture,
):
    from apps.extra_lessons import services as extra_services
    from apps.lessons import services as lessons_services

    fact = lessons_services.create_lesson_full({
        'lesson_date': '2026-05-01', 'group_id': group_fixture,
        'teacher_id': teacher_id_fixture, 'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    assignment = extra_services.create_assignment({
        'missed_lesson_id': fact['lesson_id'], 'teacher_id': other_teacher_id_fixture,
        'student_ids': [student_fixture], 'scheduled_date': '2026-05-03',
        'scheduled_time': '16:00', 'duration_minutes': 30,
    }, request=None)

    login_as(api_client, role='teacher', teacher_id=other_teacher_id_fixture)
    resp = api_client.get('/api/calendar?from=2026-05-01&to=2026-05-07')
    assert resp.status_code == 200
    extra_occs = [o for o in resp.data['occurrences'] if o.get('extraLessonId') == assignment['id']]
    assert len(extra_occs) == 1
    assert extra_occs[0]['date'] == '2026-05-03'
    assert extra_occs[0]['time'] == '16:00'
    assert extra_occs[0]['status'] == 'pending'
```

> Match this test's fixture names to whatever `apps/scheduling/tests/conftest.py` actually defines (e.g. it may already have a second-teacher fixture, or you may need to add one following the existing `teacher_id_fixture` pattern) — read that conftest before writing this test for real.

- [ ] **Step 2: Run to confirm it fails**

Run: `cd journal_django && pytest apps/scheduling/tests/test_calendar_api.py -k extra_lesson -v`
Expected: FAILS (no `extraLessonId` key present / assertion on empty list).

- [ ] **Step 3: Extend `apps/scheduling/services.py`**

Add the import at the top (next to the existing `from apps.scheduling import repository`):

```python
from apps.extra_lessons import repository as extra_lessons_repository
```

Add two new helpers right after `_planned_occurrence_dict`:

```python
def _extra_lesson_status(status_value: str, scheduled_date, scheduled_time, now_msk) -> str:
    """Статус карточки доп.урока → тот же алфавит OccStatus, что и у planned_lessons."""
    if status_value == 'done':
        return DONE
    if status_value == 'cancelled':
        return CANCELLED
    occ_dt = datetime.datetime.combine(scheduled_date, scheduled_time, tzinfo=MSK)
    return OVERDUE if now_msk >= occ_dt else PENDING


def _extra_lesson_occurrence_dict(r: dict, now_msk: datetime.datetime) -> dict:
    """Строка extra_lessons.assignments_in_window → dict календаря (occurrence-
    форма). extraLessonId — дискриминатор для фронта (WeekGrid красит красным,
    OccurrenceMenu подставляет «Провести доп.урок» вместо «Отметить урок»)."""
    status = _extra_lesson_status(r['status'], r['scheduled_date'], r['scheduled_time'], now_msk)
    label = f"Доп.урок · {r['missed_lesson_group_name']}"
    return {
        'group': label,
        'groupId': None,
        'groupDisplay': label,
        'teacher': r['teacher_name'],
        'teacherOverride': None,
        'direction': None,
        'color': None,
        'isGroup': len(r['student_names']) > 1,
        'durationMinutes': r['duration_minutes'],
        'vkChat': None,
        'date': _iso(r['scheduled_date']),
        'time': _hhmm(r['scheduled_time']),
        'day': _report_day(r['scheduled_date']),
        'seq': None,
        'lessonNumber': None,
        'isHalf': False,
        'isExtra': False,
        'extraLessonId': r['id'],
        'status': status,
        'label': _planned_label(status),
        'movedFrom': None,
        'movedTo': None,
        'students': [{'name': n} for n in r['student_names']],
    }
```

In `build_calendar`, right after the `occurrences` loop over `rows` and before the `occurrences.sort(...)` line, add:

```python
    for r in extra_lessons_repository.assignments_in_window(teacher_id, window_from, window_to):
        occurrences.append(_extra_lesson_occurrence_dict(r, now))
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `cd journal_django && pytest apps/scheduling/tests/test_calendar_api.py -v`
Expected: all PASSED (existing calendar tests unaffected, new one green).

- [ ] **Step 5: Add `extraLessonId` to the shared Occurrence TS type**

In `journal_django/frontend/admin-src/src/shared/calendar/types.ts`, add to the `Occurrence` interface, right after `isExtra: boolean;`:

```typescript
  /**
   * Присутствует только для карточек ExtraLessonAssignment (доп.урок за
   * пропуск конкретного основного урока, apps.extra_lessons) — отличать от
   * isExtra (групповое доп.занятие вне курса, apps.scheduling.PlannedLesson).
   * CalendarView красит такие карточки фиксированным красным (не по
   * направлению); OccurrenceMenu подставляет «Провести доп.урок».
   */
  extraLessonId?: number | null;
```

- [ ] **Step 6: Mirror the same field in teacher-src's own type**

In `journal_django/frontend/teacher-src/src/lib/types.ts`, add the identical field (same comment) to its `Occurrence` interface, right after `isExtra: boolean;`.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/scheduling/services.py journal_django/apps/scheduling/tests/test_calendar_api.py journal_django/frontend/admin-src/src/shared/calendar/types.ts journal_django/frontend/teacher-src/src/lib/types.ts
git commit -m "feat(calendar): merge extra lesson assignments into /api/calendar"
```

---

### Task 11: Teacher calendar — red styling + record flow

**Files:**
- Modify: `journal_django/frontend/admin-src/src/shared/calendar/lib.ts`
- Modify: `journal_django/frontend/admin-src/src/shared/calendar/CalendarView.tsx`
- Modify: `journal_django/frontend/teacher-src/src/pages/calendar/OccurrenceMenu.tsx`
- Modify: `journal_django/frontend/teacher-src/src/pages/calendar/CalendarPage.tsx`
- Create: `journal_django/frontend/teacher-src/src/hooks/useExtraLesson.ts`
- Create: `journal_django/frontend/teacher-src/src/components/lessons/ExtraLessonRecordModal.tsx`

- [ ] **Step 1: Add the fixed red constant**

In `journal_django/frontend/admin-src/src/shared/calendar/lib.ts`, next to the existing `NO_DIRECTION_COLOR` constant, add:

```typescript
/** Насыщенный красный для карточек доп.урока (ExtraLessonAssignment) — фиксирован,
 * НЕ выводится из направления/группы (в отличие от resolveDirectionColor). */
export const EXTRA_LESSON_COLOR = '#d32f2f';
```

- [ ] **Step 2: Use it in `colorOf`**

In `journal_django/frontend/admin-src/src/shared/calendar/CalendarView.tsx`, update the import and the `colorOf` callback:

```typescript
import { resolveDirectionColor, NO_DIRECTION_COLOR, EXTRA_LESSON_COLOR } from './lib';
```

```typescript
  const colorOf = useCallback(
    (occ: Occurrence): string =>
      occ.extraLessonId != null
        ? EXTRA_LESSON_COLOR
        : resolveDirectionColor(occ.color, occ.direction ?? occ.group),
    [],
  );
```

- [ ] **Step 3: Add a "Провести доп.урок" item to the teacher's context menu**

In `journal_django/frontend/teacher-src/src/pages/calendar/OccurrenceMenu.tsx`, change the fillable button's label and hide "Открыть карточку группы" for extra-lesson cards (no real group to open):

```tsx
      {isFillable && (
        <button
          type="button"
          className="occ-menu-item"
          role="menuitem"
          disabled={isFuture}
          title={isFuture ? 'Занятие ещё не наступило' : undefined}
          onClick={onSubmitLesson}
        >
          {occ.extraLessonId != null ? 'Провести доп.урок' : 'Отметить урок'}
          {isFuture && <span className="occ-menu-item-hint">доступно в день урока</span>}
        </button>
      )}
      {occ.extraLessonId == null && (
        <button type="button" className="occ-menu-item" role="menuitem" onClick={onOpenGroup}>
          Открыть карточку группы
        </button>
      )}
```

(Remove the old unconditional "Открыть карточку группы" button that this replaces.)

- [ ] **Step 4: Create the teacher-side extra-lesson hook**

Create `journal_django/frontend/teacher-src/src/hooks/useExtraLesson.ts`:

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@shared/lib/api';

export interface ExtraLessonParticipant {
  student_id: number;
  student_name: string;
}

export interface ExtraLessonDetail {
  id: number;
  status: 'scheduled' | 'done' | 'cancelled';
  scheduled_date: string;
  scheduled_time: string;
  duration_minutes: number;
  missed_lesson_group_name: string;
  missed_lesson_date: string;
  participants: ExtraLessonParticipant[];
}

export function useExtraLesson(id: number | null) {
  return useQuery({
    queryKey: ['extra-lesson', id],
    queryFn: () => api<ExtraLessonDetail>('GET', `/api/extra-lessons/${id}`),
    enabled: id != null,
  });
}

export function useRecordExtraLesson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: {
      id: number;
      body: { record_url?: string; attendance: { student_id: number; present: boolean }[] };
    }) => api<{ lesson_id: number; payment: number; penalty: number }>(
      'POST', `/api/extra-lessons/${id}/record`, body,
    ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['calendar'] });
      qc.invalidateQueries({ queryKey: ['extra-lesson', vars.id] });
    },
  });
}
```

- [ ] **Step 5: Create the record modal**

Create `journal_django/frontend/teacher-src/src/components/lessons/ExtraLessonRecordModal.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Modal } from '../ui/Modal';
import { useExtraLesson, useRecordExtraLesson } from '../../hooks/useExtraLesson';

interface Props {
  assignmentId: number;
  onClose: () => void;
}

/** Фиксация проведения доп.урока — посещаемость только по назначенным участникам. */
export function ExtraLessonRecordModal({ assignmentId, onClose }: Props) {
  const { data, isLoading } = useExtraLesson(assignmentId);
  const record = useRecordExtraLesson();
  const [url, setUrl] = useState('');
  const [present, setPresent] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    const init: Record<number, boolean> = {};
    for (const p of data.participants) init[p.student_id] = true;
    setPresent(init);
  }, [data]);

  if (isLoading || !data) {
    return (
      <Modal title="Доп.урок" onClose={onClose}>
        <div className="cal-empty">Загрузка…</div>
      </Modal>
    );
  }

  const togglePresent = (sid: number) => setPresent((p) => ({ ...p, [sid]: !p[sid] }));

  const handleSubmit = async () => {
    setError(null);
    const attendance = data.participants.map((p) => ({
      student_id: p.student_id,
      present: !!present[p.student_id],
    }));
    try {
      await record.mutateAsync({ id: assignmentId, body: { record_url: url || undefined, attendance } });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить доп.урок');
    }
  };

  return (
    <Modal
      title={`Доп.урок за ${data.missed_lesson_date}`}
      subtitle={`${data.missed_lesson_group_name} · ${data.scheduled_date} ${data.scheduled_time}`}
      onClose={onClose}
    >
      <div className="lesson-form__row">
        <label>Ссылка на запись урока</label>
        <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." />
      </div>
      <div className="lesson-form__row">
        <label>Посещаемость</label>
        <div className="attendance-grid">
          {data.participants.map((p) => {
            const isPresent = !!present[p.student_id];
            return (
              <button
                key={p.student_id}
                type="button"
                className={`attendance-card ${isPresent ? 'is-present' : 'is-absent'}`}
                onClick={() => togglePresent(p.student_id)}
              >
                <span className="attendance-card__icon" aria-hidden>{isPresent ? '✓' : '✕'}</span>
                <span className="attendance-card__name">{p.student_name}</span>
              </button>
            );
          })}
        </div>
      </div>
      {error && <div className="cal-error">{error}</div>}
      <div className="lesson-form__footer">
        <button
          type="button"
          className="btn-save"
          onClick={() => { void handleSubmit(); }}
          disabled={record.isPending}
        >
          Сохранить доп.урок
        </button>
      </div>
    </Modal>
  );
}
```

> Check `journal_django/frontend/teacher-src/src/components/ui/Modal.tsx`'s actual prop names (`title`/`subtitle`/`onClose`) before finalizing — match whatever `CalendarPage.tsx`'s existing `<Modal title={marking.group} subtitle="Запись урока" onClose={...}>` usage shows (already referenced in the file you're editing in Step 6).

- [ ] **Step 6: Wire the modal into `CalendarPage.tsx`**

In `journal_django/frontend/teacher-src/src/pages/calendar/CalendarPage.tsx`, add the import:

```typescript
import { ExtraLessonRecordModal } from '../../components/lessons/ExtraLessonRecordModal';
```

Replace the `{marking && (...)}` block's contents to branch on `marking.extraLessonId`:

```tsx
      {marking && (
        marking.extraLessonId != null ? (
          <ExtraLessonRecordModal assignmentId={marking.extraLessonId} onClose={() => setMarking(null)} />
        ) : (markingData ? (
          <LessonForm
            group={marking.group}
            groupData={markingData}
            initialDate={marking.date}
            isSubstitution={!!marking.teacherOverride}
            onClose={() => setMarking(null)}
          />
        ) : (
          <Modal title={marking.group} subtitle="Запись урока" onClose={() => setMarking(null)}>
            {all.isError
              ? <div className="cal-error">Не удалось загрузить данные группы. Попробуйте ещё раз.</div>
              : <div className="cal-empty">Загружаем данные группы…</div>}
          </Modal>
        ))
      )}
```

- [ ] **Step 7: Manual verification**

Run the teacher SPA dev server (see project's `run` skill / `deploy/README.md` for the local dev command), open the calendar as a teacher account with a seeded `ExtraLessonAssignment` (create one via the admin API or Django shell), and confirm:
  - the card renders in saturated red regardless of the direction color of neighboring cards
  - clicking it opens a context menu with "Провести доп.урок" (no "Отметить урок", no "Открыть карточку группы")
  - submitting the record modal marks it done, refreshes the calendar, and the card's status visual updates (done overlay)

- [ ] **Step 8: Commit**

```bash
git add journal_django/frontend/admin-src/src/shared/calendar/lib.ts journal_django/frontend/admin-src/src/shared/calendar/CalendarView.tsx journal_django/frontend/teacher-src/src/pages/calendar/OccurrenceMenu.tsx journal_django/frontend/teacher-src/src/pages/calendar/CalendarPage.tsx journal_django/frontend/teacher-src/src/hooks/useExtraLesson.ts journal_django/frontend/teacher-src/src/components/lessons/ExtraLessonRecordModal.tsx
git commit -m "feat(teacher-spa): render extra lessons in red, add record modal"
```

---

### Task 12: Admin — types, API hooks

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/types.ts`
- Create: `journal_django/frontend/admin-src/src/hooks/useExtraLessons.ts`

- [ ] **Step 1: Add types**

In `journal_django/frontend/admin-src/src/lib/types.ts`, add near the existing `Lesson`/`LessonFull` types:

```typescript
export interface ExtraLessonParticipant {
  student_id: number;
  student_name: string;
}

export interface ExtraLessonAssignment {
  id: number;
  teacher_id: number;
  teacher_name: string;
  missed_lesson_id: number;
  missed_lesson_group_id: number;
  missed_lesson_group_name: string;
  missed_lesson_date: string;
  scheduled_date: string;
  scheduled_time: string;
  duration_minutes: number;
  status: 'scheduled' | 'done' | 'cancelled';
  fact_lesson_id: number | null;
  participants: ExtraLessonParticipant[];
}
```

- [ ] **Step 2: Create the hooks file**

Create `journal_django/frontend/admin-src/src/hooks/useExtraLessons.ts`:

```typescript
import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { ExtraLessonAssignment, Paginated } from '../lib/types';

export interface ExtraLessonsListParams {
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: 'asc' | 'desc';
  filters: Record<string, string>;
}

function buildQuery(p: ExtraLessonsListParams): string {
  const qs = new URLSearchParams();
  qs.set('page', String(p.page));
  qs.set('page_size', String(p.page_size));
  qs.set('sort_by', p.sort_by);
  qs.set('sort_dir', p.sort_dir);
  for (const [k, v] of Object.entries(p.filters)) {
    if (v) qs.set(k, v);
  }
  return qs.toString();
}

export function useExtraLessons(params: ExtraLessonsListParams) {
  return useQuery({
    queryKey: ['extra-lessons', params],
    queryFn: () => api<Paginated<ExtraLessonAssignment>>(
      'GET', `/api/admin/extra-lessons?${buildQuery(params)}`,
    ),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useExtraLessonMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['extra-lessons'] });
    qc.invalidateQueries({ queryKey: ['lessons'] });
    qc.invalidateQueries({ queryKey: ['memberships'] });
    qc.invalidateQueries({ queryKey: ['calendar'] });
  };
  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) =>
        api<ExtraLessonAssignment>('POST', '/api/admin/extra-lessons', body),
      onSuccess: invalidate,
    }),
    cancel: useMutation({
      mutationFn: (id: number) =>
        api<ExtraLessonAssignment>('POST', `/api/admin/extra-lessons/${id}/cancel`),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<void>('DELETE', `/api/admin/extra-lessons/${id}`),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Step 3: Typecheck**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/lib/types.ts journal_django/frontend/admin-src/src/hooks/useExtraLessons.ts
git commit -m "feat(admin): add ExtraLessonAssignment types and API hooks"
```

---

### Task 13: Admin — "Назначить доп.урок" entry point in `LessonEditor`

**Files:**
- Create: `journal_django/frontend/admin-src/src/components/lessons/AssignExtraLessonModal.tsx`
- Modify: `journal_django/frontend/admin-src/src/components/lessons/LessonEditor.tsx`

Scope note: v1 offers only the students who were marked absent (`present: false`)
on this lesson as candidates — the design doc allows manually adding other
students too (the API already accepts any `student_ids`), but that's deferred;
document it as a known simplification, not a silent gap.

- [ ] **Step 1: Create the assignment modal**

Create `journal_django/frontend/admin-src/src/components/lessons/AssignExtraLessonModal.tsx`:

```tsx
import { useState } from 'react';
import { useTeachers } from '../../hooks/useTeachers';
import { useExtraLessonMutations } from '../../hooks/useExtraLessons';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../ui/Toast';
import { Modal } from '../ui/Modal';
import { SelectInput } from '../form/SelectInput';
import { DateInput } from '../form/DateInput';
import { TimeInput } from '../form/TimeInput';
import { Checkbox } from '../form/Checkbox';

interface Candidate {
  student_id: number;
  student_name: string;
}

interface Props {
  missedLessonId: number;
  candidates: Candidate[];
  defaultTeacherId: number;
  onClose: () => void;
}

const DURATION_OPTIONS = [30, 45, 60, 90].map((v) => ({ value: v, label: `${v} мин` }));

export function AssignExtraLessonModal({ missedLessonId, candidates, defaultTeacherId, onClose }: Props) {
  const { data: teachers = [] } = useTeachers();
  const muts = useExtraLessonMutations();
  const { toast } = useToast();
  const showError = useApiError();

  const [teacherId, setTeacherId] = useState(defaultTeacherId);
  const [date, setDate] = useState('');
  const [time, setTime] = useState('');
  const [duration, setDuration] = useState(45);
  const [selected, setSelected] = useState<Record<number, boolean>>(
    () => Object.fromEntries(candidates.map((c) => [c.student_id, true])),
  );

  const toggle = (sid: number) => setSelected((s) => ({ ...s, [sid]: !s[sid] }));

  const handleSubmit = async () => {
    const studentIds = candidates.filter((c) => selected[c.student_id]).map((c) => c.student_id);
    if (studentIds.length === 0) {
      toast('Выберите хотя бы одного ученика', 'error');
      return;
    }
    if (!date || !time) {
      toast('Укажите дату и время доп.урока', 'error');
      return;
    }
    try {
      await muts.create.mutateAsync({
        missed_lesson_id: missedLessonId,
        teacher_id: teacherId,
        student_ids: studentIds,
        scheduled_date: date,
        scheduled_time: time,
        duration_minutes: duration,
      });
      toast('Доп.урок назначен', 'ok');
      onClose();
    } catch (err) { showError(err); }
  };

  return (
    <Modal title="Назначить доп.урок" onClose={onClose}>
      <div className="lesson-editor__row">
        <label>Преподаватель</label>
        <SelectInput
          options={teachers.map((t) => ({ value: t.id, label: t.name }))}
          value={teacherId}
          onChange={(e) => setTeacherId(Number(e.target.value))}
        />
      </div>
      <div className="lesson-editor__row">
        <label>Дата</label>
        <DateInput value={date} onChange={(e) => setDate(e.target.value)} />
      </div>
      <div className="lesson-editor__row">
        <label>Время</label>
        <TimeInput value={time} onChange={(e) => setTime(e.target.value)} />
      </div>
      <div className="lesson-editor__row">
        <label>Длительность</label>
        <SelectInput
          options={DURATION_OPTIONS}
          value={duration}
          onChange={(e) => setDuration(Number(e.target.value))}
        />
      </div>
      <div className="lesson-editor__row">
        <label>Ученики (отсутствовавшие на этом уроке)</label>
        {candidates.map((c) => (
          <Checkbox
            key={c.student_id}
            label={c.student_name}
            checked={!!selected[c.student_id]}
            onChange={() => toggle(c.student_id)}
          />
        ))}
      </div>
      <div className="lesson-editor__footer">
        <button
          type="button"
          className="btn-save"
          style={{ marginLeft: 'auto' }}
          onClick={() => { void handleSubmit(); }}
          disabled={muts.create.isPending}
        >
          Назначить
        </button>
      </div>
    </Modal>
  );
}
```

> `useApiError`/`useToast`/`Modal` import paths are copied from `LessonEditor.tsx`'s own imports (same directory depth) — verify they resolve; adjust relative paths (`../ui/Toast` vs `../../hooks/useApiError`) to match this file's actual location under `components/lessons/`.

- [ ] **Step 2: Add the entry point button to `LessonEditor.tsx`**

In `journal_django/frontend/admin-src/src/components/lessons/LessonEditor.tsx`, add the import:

```typescript
import { AssignExtraLessonModal } from './AssignExtraLessonModal';
```

Add state near the other `useState` calls:

```typescript
  const [assigningExtra, setAssigningExtra] = useState(false);
```

In the footer (`lesson-editor__footer`), add a new button — only rendered when there's a saved lesson (`lesson`) with at least one absent student:

```tsx
        {lesson && Object.values(present).some((p) => !p) && (
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setAssigningExtra(true)}
          >
            Назначить доп.урок
          </button>
        )}
```

Render the modal at the end of the component's returned JSX (sibling to the outer `<div className="lesson-editor">`):

```tsx
      {assigningExtra && lesson && (
        <AssignExtraLessonModal
          missedLessonId={lesson.id}
          candidates={members
            .filter((m) => !present[m.student_id])
            .map((m) => ({ student_id: m.student_id, student_name: m.student_name || `#${m.student_id}` }))}
          defaultTeacherId={lesson.teacher_id}
          onClose={() => setAssigningExtra(false)}
        />
      )}
```

- [ ] **Step 3: Typecheck**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Manual verification**

Start the admin dev server, open a group's "Уроки" tab, open an already-conducted lesson with at least one absent student, click "Назначить доп.урок", fill the form, submit, and confirm a `POST /api/admin/extra-lessons` succeeds (Network tab) and a toast confirms success.

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/components/lessons/AssignExtraLessonModal.tsx journal_django/frontend/admin-src/src/components/lessons/LessonEditor.tsx
git commit -m "feat(admin): add 'Назначить доп.урок' entry point in LessonEditor"
```

---

### Task 14: Admin — `ExtraLessonsListPage` (oversight + cancel)

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/extra-lessons/ExtraLessonsListPage.tsx`
- Modify: `journal_django/frontend/admin-src/src/App.tsx`
- Modify: `journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx`

- [ ] **Step 1: Create the list page**

Create `journal_django/frontend/admin-src/src/pages/extra-lessons/ExtraLessonsListPage.tsx` (mirrors `LessonsListPage.tsx`'s structure):

```tsx
import { useDeferredValue } from 'react';
import { useListSearchParams } from '../../hooks/useListSearchParams';
import { useExtraLessons, useExtraLessonMutations } from '../../hooks/useExtraLessons';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { DataTable, type Column } from '../../components/table/DataTable';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import type { ExtraLessonAssignment } from '../../lib/types';

const STATUS_LABELS: Record<string, string> = {
  scheduled: 'Запланирован',
  done: 'Проведён',
  cancelled: 'Отменён',
};

export default function ExtraLessonsListPage() {
  const search = useListSearchParams({ sortBy: 'scheduled_date', sortDir: 'desc' });
  const { page, pageSize, sortBy, sortDir, filters, setPage, setPageSize, setSort, setFilters } = search;
  const debouncedFilters = useDeferredValue(filters);

  const { data, isLoading, isFetching } = useExtraLessons({
    page, page_size: pageSize, sort_by: sortBy, sort_dir: sortDir, filters: debouncedFilters,
  });
  const muts = useExtraLessonMutations();
  const showError = useApiError();
  const { toast } = useToast();

  const rows: ExtraLessonAssignment[] = data?.rows || [];
  const total = data?.total || 0;

  const handleCancel = async (id: number) => {
    try {
      await muts.cancel.mutateAsync(id);
      toast('Доп.урок отменён', 'ok');
    } catch (err) { showError(err); }
  };

  const columns: Column<ExtraLessonAssignment>[] = [
    { key: 'scheduled_date', label: 'Дата', sortable: true, searchable: false, cell: (r) => fmtDate(r.scheduled_date) },
    { key: 'missed_lesson_group_name', label: 'Группа (пропуск)', sortable: false, searchable: false },
    { key: 'teacher_name', label: 'Преподаватель', sortable: true, searchable: false },
    {
      key: 'participants', label: 'Ученики', sortable: false, searchable: false,
      cell: (r) => r.participants.map((p) => p.student_name).join(', '),
    },
    { key: 'status', label: 'Статус', sortable: true, searchable: false, cell: (r) => STATUS_LABELS[r.status] || r.status },
    {
      key: 'actions', label: '', sortable: false, searchable: false,
      cell: (r) => r.status === 'scheduled' ? (
        <button type="button" className="btn-secondary" onClick={() => { void handleCancel(r.id); }}>
          Отменить
        </button>
      ) : null,
    },
  ];

  if (isLoading) return <TableSkeleton rows={8} cols={columns.length} />;

  return (
    <DataTable<ExtraLessonAssignment>
      data={rows}
      columns={columns}
      title="Доп.уроки"
      isLoading={isFetching}
      serverPagination={{
        page, pageSize, total, sortBy, sortDir, filters,
        onPageChange: setPage, onPageSizeChange: setPageSize,
        onSortChange: setSort, onFiltersChange: setFilters,
      }}
    />
  );
}
```

> `Column`/`DataTable` prop shape (e.g. whether `key: 'actions'` with no matching data field is accepted) — verify against `LessonsListPage.tsx`'s own `Column` usage and `DataTable`'s type definition; adjust if `Column<T>['key']` is constrained to `keyof T`.

- [ ] **Step 2: Add the route**

In `journal_django/frontend/admin-src/src/App.tsx`, add the import next to `LessonsListPage`:

```typescript
import ExtraLessonsListPage from './pages/extra-lessons/ExtraLessonsListPage';
```

Add the route next to the lessons routes:

```tsx
            <Route path="/admin/extra-lessons" element={<RequireRole roles={['manager','admin','superadmin']}><ExtraLessonsListPage /></RequireRole>} />
```

- [ ] **Step 3: Add the sidebar nav entry**

In `journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx`, add a nav entry next to the `lessons` entry:

```typescript
  { key: 'extra-lessons', label: 'Доп.уроки', path: '/admin/extra-lessons' },
```

(Reuse the existing `lessons` icon from the `ICONS` map above, or add a new SVG entry keyed `'extra-lessons'` if the sidebar requires every nav key to have its own icon — check how the `key`→icon lookup works in this file before assuming reuse is wired automatically.)

- [ ] **Step 4: Typecheck**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Manual verification**

Start the admin dev server, log in as manager/admin/superadmin, navigate to "Доп.уроки", confirm the list renders assignments created in earlier manual tests and "Отменить" works on a `scheduled` row.

- [ ] **Step 6: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/extra-lessons journal_django/frontend/admin-src/src/App.tsx journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx
git commit -m "feat(admin): add ExtraLessonsListPage with cancel action"
```

---

### Task 15: Final verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `cd journal_django && pytest -q`
Expected: all PASSED, no regressions anywhere in the suite.

- [ ] **Step 2: Run both frontend builds**

Run: `cd journal_django/frontend/admin-src && npm run build`
Run: `cd journal_django/frontend/teacher-src && npm run build`
Expected: both succeed with no TS errors.

- [ ] **Step 3: `python manage.py check` + `makemigrations --check`**

Run: `cd journal_django && python manage.py check && python manage.py makemigrations --check --dry-run`
Expected: no issues, no missing migrations.

- [ ] **Step 4: Manual end-to-end walkthrough**

Using the `run`/`verify` skills (or the project's documented local dev setup —
nginx + `runserver`, see `deploy/README.md`):

1. As admin: open a group's "Уроки" tab, find a conducted lesson with an
   absent student, click "Назначить доп.урок", assign it to a teacher
   (optionally a different one than the group's own), submit.
2. Confirm the new row appears in "Доп.уроки" with status "Запланирован".
3. Log in as the assigned teacher, confirm a bright-red card appears on the
   calendar at the chosen date/time, click it, choose "Провести доп.урок",
   mark attendance, submit.
4. Confirm: the missed lesson's attendance cell for that student now shows
   present in the group's "Уроки" tab; the original lesson's payroll
   (`payment`) is unchanged; a new `Lesson`/`Payroll` row exists for the
   extra lesson with `payment = 200 × present_count`.
5. As admin, delete the extra lesson's fact from "Доп.уроки" (if a delete
   action was wired) or via `DELETE /api/admin/extra-lessons/:id`, and
   confirm the missed lesson's attendance/lessons_done reverts.
6. Create a second, not-yet-conducted assignment and cancel it; confirm it
   disappears from the teacher's calendar (or shows a cancelled/greyed card,
   per however `_planned_label`/CSS renders `cancelled` status) and cannot be
   cancelled twice (409).

Report any discrepancy from this plan's assumptions before considering the
feature done — do not claim success without having actually driven this flow.

---

## Notes on scope deliberately left out (YAGNI)

- **Manual "add other students" in the assignment UI** — the API accepts any
  `student_ids`, but Task 13's UI only offers the lesson's actual absentees.
  Extend `AssignExtraLessonModal` with a student search/combobox later if
  the manager/admin workflow actually needs it.
- **Admin-side recording of an extra lesson** (bypassing the assigned
  teacher) — not requested; only the assigned teacher can call
  `POST /api/extra-lessons/:id/record`. If admins need to backfill a missed
  teacher submission, that's a separate follow-up mirroring how
  `create_lesson_full` exists alongside `submit_lesson` for regular lessons.
- **Changelog `summary.py` human-readable templates** for `extra_lesson_*`
  operations — the generic by-name fallback (`docs` in `summary.py`) already
  guarantees a non-empty description; bespoke templates (like the
  `planned_lessons`/`payroll` ones) can be added later if the raw fallback
  reads poorly in practice.
