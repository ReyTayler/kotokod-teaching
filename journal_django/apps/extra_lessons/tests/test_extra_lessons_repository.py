"""Integration-тесты apps.extra_lessons.repository (реальная БД, пер-ученик AbsenceResolution)."""
from __future__ import annotations

import datetime

import pytest
from django.db import connection

from apps.extra_lessons import repository
from apps.extra_lessons.models import CANCELLED, DONE, SCHEDULED

pytestmark = pytest.mark.django_db


@pytest.fixture
def resolution_cleanup(missed_lesson_fixture):
    """Сносит созданные тестом резолюции ДО teardown missed_lesson_fixture.

    absence_resolutions.missed_lesson — реальный DB-level FK на lessons (Django
    on_delete=CASCADE — только ORM-семантика), а teardown missed_lesson_fixture
    делает raw `DELETE FROM lessons` и НЕ чистит absence_resolutions. Эта фикстура
    зависит от missed_lesson_fixture, поэтому её teardown отрабатывает раньше —
    удаляет резолюции, снимая FK-блокировку удаления урока."""
    yield missed_lesson_fixture
    with connection.cursor() as cur:
        cur.execute(
            'DELETE FROM absence_resolutions WHERE missed_lesson_id = %s',
            [missed_lesson_fixture],
        )


def test_create_resolutions_creates_per_student_rows(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    ids = repository.create_resolutions(
        missed_lesson_id=missed_lesson_fixture,
        assigned_teacher_id=teacher_fixture,
        student_ids=[student_fixture],
        scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0),
        duration_minutes=45,
    )
    assert isinstance(ids, list) and len(ids) == 1
    full = repository.get_resolution_full(ids[0])
    assert full['status'] == SCHEDULED
    assert full['assigned_teacher_id'] == teacher_fixture
    assert full['missed_lesson_id'] == missed_lesson_fixture
    assert full['student_id'] == student_fixture
    assert full['duration_minutes'] == 45
    assert full['fact_lesson_id'] is None


def test_cancel_sets_status_cancelled(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    resolution_id = repository.create_resolutions(
        missed_lesson_id=missed_lesson_fixture, assigned_teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )[0]
    repository.cancel(resolution_id)
    full = repository.get_resolution_full(resolution_id)
    assert full['status'] == CANCELLED


def test_cancel_raises_if_not_scheduled(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    resolution_id = repository.create_resolutions(
        missed_lesson_id=missed_lesson_fixture, assigned_teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )[0]
    repository.cancel(resolution_id)
    with pytest.raises(ValueError):
        repository.cancel(resolution_id)


def test_mark_done_then_reset_to_scheduled_roundtrip(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    resolution_id = repository.create_resolutions(
        missed_lesson_id=missed_lesson_fixture, assigned_teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )[0]
    repository.mark_done(resolution_id, fact_lesson_id=missed_lesson_fixture)  # реальный id не важен
    full = repository.get_resolution_full(resolution_id)
    assert full['status'] == DONE
    assert full['fact_lesson_id'] == missed_lesson_fixture

    repository.reset_to_scheduled(resolution_id)
    full = repository.get_resolution_full(resolution_id)
    assert full['status'] == SCHEDULED
    assert full['fact_lesson_id'] is None


def test_students_not_absent_excludes_present_and_non_participants(
    missed_lesson_fixture, student_fixture,
):
    """student_fixture отмечен present=false на missed_lesson_fixture — не в
    результате. Посторонний id (не участник урока вовсе) — в результате."""
    assert repository.students_not_absent(missed_lesson_fixture, [student_fixture]) == []
    assert repository.students_not_absent(
        missed_lesson_fixture, [student_fixture, 999_999_999],
    ) == [999_999_999]


def test_lock_for_delete_returns_locked_fields(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    resolution_id = repository.create_resolutions(
        missed_lesson_id=missed_lesson_fixture, assigned_teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )[0]
    repository.mark_done(resolution_id, fact_lesson_id=missed_lesson_fixture)
    locked = repository.lock_for_delete(resolution_id)
    assert locked['status'] == DONE
    assert locked['missed_lesson_id'] == missed_lesson_fixture
    assert locked['student_id'] == student_fixture
    assert locked['fact_lesson_id'] == missed_lesson_fixture


def test_has_active_resolution_for_student(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    assert repository.has_active_resolution(missed_lesson_fixture, student_fixture) is False
    repository.create_resolutions(
        missed_lesson_id=missed_lesson_fixture, assigned_teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )
    assert repository.has_active_resolution(missed_lesson_fixture, student_fixture) is True


def test_has_active_resolution_returns_true_when_marked_done(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    """После mark_done резолюция всё ещё активна (проведённый доп.урок блокирует
    задвоение компенсации того же пропуска)."""
    resolution_id = repository.create_resolutions(
        missed_lesson_id=missed_lesson_fixture, assigned_teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )[0]
    repository.mark_done(resolution_id, fact_lesson_id=missed_lesson_fixture)
    assert repository.has_active_resolution(missed_lesson_fixture, student_fixture) is True


def test_has_active_resolution_returns_false_after_cancel(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    """Отменённая резолюция не блокирует повторное назначение."""
    resolution_id = repository.create_resolutions(
        missed_lesson_id=missed_lesson_fixture, assigned_teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )[0]
    assert repository.has_active_resolution(missed_lesson_fixture, student_fixture) is True
    repository.cancel(resolution_id)
    assert repository.has_active_resolution(missed_lesson_fixture, student_fixture) is False
