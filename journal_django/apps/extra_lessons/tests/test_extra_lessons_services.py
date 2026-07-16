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
