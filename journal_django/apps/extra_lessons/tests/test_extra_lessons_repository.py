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


def test_students_not_absent_excludes_present_and_non_participants(
    missed_lesson_fixture, student_fixture,
):
    """student_fixture отмечен present=false на missed_lesson_fixture — не в
    результате. Посторонний id (не участник урока вовсе) — в результате."""
    assert repository.students_not_absent(missed_lesson_fixture, [student_fixture]) == []
    assert repository.students_not_absent(
        missed_lesson_fixture, [student_fixture, 999_999_999],
    ) == [999_999_999]


def test_lock_assignment_for_delete_returns_locked_fields(
    teacher_fixture, missed_lesson_fixture, student_fixture,
):
    assignment_id = repository.create_assignment(
        missed_lesson_id=missed_lesson_fixture, teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )
    repository.mark_done(assignment_id, fact_lesson_id=missed_lesson_fixture)
    locked = repository.lock_assignment_for_delete(assignment_id)
    assert locked['status'] == DONE
    assert locked['missed_lesson_id'] == missed_lesson_fixture
    assert locked['fact_lesson_id'] == missed_lesson_fixture


def test_has_active_assignment_for_student(teacher_fixture, missed_lesson_fixture, student_fixture):
    assert repository.has_active_assignment(missed_lesson_fixture, student_fixture) is False
    repository.create_assignment(
        missed_lesson_id=missed_lesson_fixture, teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )
    assert repository.has_active_assignment(missed_lesson_fixture, student_fixture) is True


def test_has_active_assignment_returns_true_when_marked_done(teacher_fixture, missed_lesson_fixture, student_fixture):
    """After marking assignment as done, has_active_assignment should still return True
    (a completed makeup lesson blocks duplicate assignments for the same missed lesson)."""
    assignment_id = repository.create_assignment(
        missed_lesson_id=missed_lesson_fixture, teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )
    repository.mark_done(assignment_id, fact_lesson_id=missed_lesson_fixture)
    assert repository.has_active_assignment(missed_lesson_fixture, student_fixture) is True


def test_has_active_assignment_returns_false_after_cancel(teacher_fixture, missed_lesson_fixture, student_fixture):
    """After cancelling assignment, has_active_assignment should return False
    (a cancelled assignment does not block re-assignment)."""
    assignment_id = repository.create_assignment(
        missed_lesson_id=missed_lesson_fixture, teacher_id=teacher_fixture,
        student_ids=[student_fixture], scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45,
    )
    assert repository.has_active_assignment(missed_lesson_fixture, student_fixture) is True
    repository.cancel_assignment(assignment_id)
    assert repository.has_active_assignment(missed_lesson_fixture, student_fixture) is False
