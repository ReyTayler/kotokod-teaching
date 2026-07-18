"""Integration-тесты apps.extra_lessons.services (реальная БД)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection

from apps.extra_lessons import repository, services
from apps.extra_lessons.exceptions import (
    DuplicateAssignment, MissedLessonNotFound, NotTeachersAssignment, StudentNotAbsent,
)
from apps.extra_lessons.models import CANCELLED, SCHEDULED, AbsenceResolution
from apps.lessons.exceptions import UnpaidAttendanceBlocked
from apps.lessons.models import Lesson, LessonAttendance
from apps.payroll.models import Payroll

pytestmark = pytest.mark.django_db


def _cleanup_fact(lesson_id):
    with connection.cursor() as cur:
        cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lessons WHERE id = %s', [lesson_id])


def _delete_resolutions(missed_lesson_id):
    """Сносит резолюции пропуска (снимает DB-level FK fact_lesson → lessons ДО
    удаления факт-урока в _cleanup_fact)."""
    with connection.cursor() as cur:
        cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id = %s', [missed_lesson_id])


@pytest.fixture
def resolution_cleanup(missed_lesson_fixture):
    """Сносит созданные тестом резолюции ДО teardown missed_lesson_fixture.

    absence_resolutions.missed_lesson — реальный DB-level FK на lessons, а
    teardown missed_lesson_fixture делает raw `DELETE FROM lessons` и НЕ чистит
    absence_resolutions. Фикстура зависит от missed_lesson_fixture, поэтому её
    teardown отрабатывает раньше — снимает FK-блокировку удаления урока."""
    yield missed_lesson_fixture
    _delete_resolutions(missed_lesson_fixture)


class _FakeRequest:
    """Минимальная заглушка request для log_event (без HTTP-контекста)."""
    META = {}
    user = None


def test_create_assignment_happy_path(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
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
    assert result['created'] == 1
    rid = result['resolution_ids'][0]
    full = repository.get_resolution_full(rid)
    assert full['status'] == SCHEDULED
    assert full['missed_lesson_id'] == missed_lesson_fixture


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


def test_create_assignment_raises_on_duplicate(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
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


def test_create_assignment_raises_if_student_not_absent(
    teacher_fixture, missed_lesson_fixture, resolution_cleanup,
):
    """Ученик, отмеченный present=true (или вообще посторонний) на пропущенном
    уроке, не должен получить доп.урок — иначе преподавателю платится зарплата
    за компенсацию несуществующего пропуска."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status) "
            "VALUES ('__el_present_student__', 'enrolled') RETURNING id"
        )
        present_student_id = cur.fetchone()[0]
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s, %s, true)',
            [missed_lesson_fixture, present_student_id],
        )
    try:
        with pytest.raises(StudentNotAbsent):
            services.create_assignment(
                {
                    'missed_lesson_id': missed_lesson_fixture,
                    'teacher_id': teacher_fixture,
                    'student_ids': [present_student_id],
                    'scheduled_date': '2026-04-05',
                    'scheduled_time': '15:00',
                    'duration_minutes': 45,
                },
                _FakeRequest(),
            )
        assert not AbsenceResolution.objects.filter(
            missed_lesson_id=missed_lesson_fixture,
        ).exists()
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM lesson_attendance WHERE student_id = %s', [present_student_id])
            cur.execute('DELETE FROM students WHERE id = %s', [present_student_id])


def test_create_assignment_raises_if_student_unpaid(
    teacher_fixture, missed_lesson_unpaid_fixture, unpaid_student_fixture,
):
    """Ученик без оплаченных уроков (balance<=0) — доп.урок ему назначить
    нельзя, ничего не создаётся (см. docs/security-guidelines.md — денежный
    учёт должен блокировать неоплаченное потребление на всех путях)."""
    with pytest.raises(UnpaidAttendanceBlocked):
        services.create_assignment(
            {
                'missed_lesson_id': missed_lesson_unpaid_fixture,
                'teacher_id': teacher_fixture,
                'student_ids': [unpaid_student_fixture],
                'scheduled_date': '2026-04-05',
                'scheduled_time': '15:00',
                'duration_minutes': 45,
            },
            _FakeRequest(),
        )
    assert not AbsenceResolution.objects.filter(
        missed_lesson_id=missed_lesson_unpaid_fixture,
    ).exists()


def test_record_raises_if_student_balance_dropped_since_assignment(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    """Назначение создано, пока у ученика был баланс; между созданием и
    фактическим проведением доп.урока баланс обнулился (оплата аннулирована/
    урок оплачен другим уроком) — record() обязан блокировать так же, как
    create_assignment, а не полагаться только на проверку в момент назначения."""
    created = services.create_assignment(
        {
            'missed_lesson_id': missed_lesson_fixture, 'teacher_id': teacher_fixture,
            'student_ids': [student_fixture], 'scheduled_date': '2026-04-05',
            'scheduled_time': '15:00', 'duration_minutes': 45,
        },
        _FakeRequest(),
    )
    rid = created['resolution_ids'][0]
    with connection.cursor() as cur:
        cur.execute('DELETE FROM payments WHERE student_id = %s', [student_fixture])

    with pytest.raises(UnpaidAttendanceBlocked):
        services.record(
            rid, teacher_id=teacher_fixture, present=True,
            record_url=None, submitted_by_token='acct:1', submit_date='2026-04-05',
            request=_FakeRequest(),
        )
    assert AbsenceResolution.objects.get(id=rid).status == SCHEDULED


def test_cancel_assignment(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    created = services.create_assignment(
        {
            'missed_lesson_id': missed_lesson_fixture, 'teacher_id': teacher_fixture,
            'student_ids': [student_fixture], 'scheduled_date': '2026-04-05',
            'scheduled_time': '15:00', 'duration_minutes': 45,
        },
        _FakeRequest(),
    )
    rid = created['resolution_ids'][0]
    result = services.cancel_assignment(rid, _FakeRequest())
    assert result['status'] == CANCELLED


def test_record_creates_fact_and_applies_makeup_attendance(
    group_fixture, teacher_fixture, other_teacher_fixture, missed_lesson_fixture,
    student_fixture, lessons_done, resolution_cleanup,
):
    created = services.create_assignment(
        {
            'missed_lesson_id': missed_lesson_fixture, 'teacher_id': other_teacher_fixture,
            'student_ids': [student_fixture], 'scheduled_date': '2026-04-05',
            'scheduled_time': '15:00', 'duration_minutes': 45,
        },
        _FakeRequest(),
    )
    rid = created['resolution_ids'][0]
    assert lessons_done(group_fixture, student_fixture) == Decimal('0')

    result = services.record(
        rid,
        teacher_id=other_teacher_fixture,
        present=True,
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
        # Резолюцию (fact_lesson FK) сносим ДО факт-урока, иначе DB-level FK.
        _delete_resolutions(missed_lesson_fixture)
        _cleanup_fact(result['lesson_id'])


def test_record_rejects_wrong_teacher(
    teacher_fixture, other_teacher_fixture, missed_lesson_fixture, student_fixture,
    resolution_cleanup,
):
    created = services.create_assignment(
        {
            'missed_lesson_id': missed_lesson_fixture, 'teacher_id': teacher_fixture,
            'student_ids': [student_fixture], 'scheduled_date': '2026-04-05',
            'scheduled_time': '15:00', 'duration_minutes': 45,
        },
        _FakeRequest(),
    )
    rid = created['resolution_ids'][0]
    with pytest.raises(NotTeachersAssignment):
        services.record(
            rid, teacher_id=other_teacher_fixture, present=True,
            record_url=None, submitted_by_token='acct:2', submit_date='2026-04-05',
            request=_FakeRequest(),
        )


def test_record_second_call_on_same_assignment_raises_value_error(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    """
    Регрессия (code review, race condition): после успешного record() резолюция
    в статусе done — повторный вызов record() на том же resolution_id обязан
    упасть ValueError'ом. Проверяет именно авторитетную проверку статуса под
    select_for_update() внутри atomic() (repository.lock_for_record), а не
    только неблокирующую предпроверку до atomic() — иначе гонка двух
    параллельных record() создала бы два Lesson-факта + Payroll (задвоенная
    зарплата), а второй mark_done() молча перезаписал бы fact_lesson_id первого.
    """
    created = services.create_assignment(
        {
            'missed_lesson_id': missed_lesson_fixture, 'teacher_id': teacher_fixture,
            'student_ids': [student_fixture], 'scheduled_date': '2026-04-05',
            'scheduled_time': '15:00', 'duration_minutes': 45,
        },
        _FakeRequest(),
    )
    rid = created['resolution_ids'][0]
    result = services.record(
        rid, teacher_id=teacher_fixture, present=True,
        record_url=None, submitted_by_token='acct:1', submit_date='2026-04-05',
        request=_FakeRequest(),
    )
    try:
        with pytest.raises(ValueError):
            services.record(
                rid, teacher_id=teacher_fixture, present=True,
                record_url=None, submitted_by_token='acct:2', submit_date='2026-04-05',
                request=_FakeRequest(),
            )
    finally:
        _delete_resolutions(missed_lesson_fixture)
        _cleanup_fact(result['lesson_id'])


def test_delete_fact_reverts_makeup_attendance(
    group_fixture, teacher_fixture, missed_lesson_fixture, student_fixture, lessons_done,
    resolution_cleanup,
):
    created = services.create_assignment(
        {
            'missed_lesson_id': missed_lesson_fixture, 'teacher_id': teacher_fixture,
            'student_ids': [student_fixture], 'scheduled_date': '2026-04-05',
            'scheduled_time': '15:00', 'duration_minutes': 45,
        },
        _FakeRequest(),
    )
    rid = created['resolution_ids'][0]
    result = services.record(
        rid, teacher_id=teacher_fixture, present=True,
        record_url=None, submitted_by_token='acct:1', submit_date='2026-04-05',
        request=_FakeRequest(),
    )
    assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')

    ok = services.delete_fact(rid, _FakeRequest())
    assert ok is True
    assert lessons_done(group_fixture, student_fixture) == Decimal('0')
    assert not Lesson.objects.filter(id=result['lesson_id']).exists()
    assert not Payroll.objects.filter(lesson_id=result['lesson_id']).exists()

    full = repository.get_resolution_full(rid)
    assert full['status'] == SCHEDULED
    assert full['fact_lesson_id'] is None


def test_delete_fact_second_call_raises_value_error(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    """
    Регрессия (audit, race condition): после успешного delete_fact() резолюция
    вернулась в status=scheduled — повторный вызов delete_fact() на том же
    resolution_id обязан упасть ValueError'ом. Проверяет авторитетную проверку
    статуса под select_for_update() внутри atomic() (repository.lock_for_delete)
    — тот же паттерн, что record()/lock_for_record, иначе гонка двух
    параллельных delete_fact() привела бы ко второму Lesson.DoesNotExist вместо
    чистой ошибки.
    """
    created = services.create_assignment(
        {
            'missed_lesson_id': missed_lesson_fixture, 'teacher_id': teacher_fixture,
            'student_ids': [student_fixture], 'scheduled_date': '2026-04-05',
            'scheduled_time': '15:00', 'duration_minutes': 45,
        },
        _FakeRequest(),
    )
    rid = created['resolution_ids'][0]
    services.record(
        rid, teacher_id=teacher_fixture, present=True,
        record_url=None, submitted_by_token='acct:1', submit_date='2026-04-05',
        request=_FakeRequest(),
    )
    ok = services.delete_fact(rid, _FakeRequest())
    assert ok is True
    with pytest.raises(ValueError):
        services.delete_fact(rid, _FakeRequest())
