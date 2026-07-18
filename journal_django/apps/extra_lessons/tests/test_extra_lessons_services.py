"""Integration-тесты apps.extra_lessons.services (реальная БД)."""
from __future__ import annotations

from decimal import Decimal

import datetime

import pytest
from django.db import connection

from apps.extra_lessons import repository, services
from apps.extra_lessons.exceptions import (
    DuplicateAssignment, MissedLessonNotFound, NotTeachersAssignment, StudentNotAbsent,
)
from apps.extra_lessons.models import MAKEUP_DONE, MAKEUP_SCHEDULED, PENDING, AbsenceResolution
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


@pytest.fixture
def extra_missed_lessons(group_fixture, teacher_fixture):
    """Две дополнительные строки lessons (той же группы) — для сценариев, где
    нужно несколько пропущенных уроков одного ученика (UNIQUE per пропуск×ученик).
    Teardown чистит и резолюции на этих уроках, и сами уроки (FK-порядок)."""
    ids = []
    with connection.cursor() as cur:
        for i, date in enumerate(('2026-04-10', '2026-04-11'), start=1):
            cur.execute(
                """
                INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number,
                                     lesson_duration_minutes, lesson_type, submitted_at,
                                     submitted_by_token)
                VALUES (%s, %s, %s, %s, 60, 'regular', now(), %s) RETURNING id
                """,
                [group_fixture, teacher_fixture, date, i, f'__el_svc_token_{i}__'],
            )
            ids.append(cur.fetchone()[0])
    yield ids
    with connection.cursor() as cur:
        cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id = ANY(%s)', [ids])
        cur.execute('DELETE FROM lessons WHERE id = ANY(%s)', [ids])


class _FakeRequest:
    """Минимальная заглушка request для log_event (без HTTP-контекста)."""
    META = {}
    user = None


def test_create_assignment_happy_path(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    """Пропуск без авто-pending (фикстура не вызывает record_lesson) → назначение
    идёт через create_scheduled_direct и сразу в статусе makeup_scheduled."""
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
    assert full['status'] == MAKEUP_SCHEDULED
    assert full['missed_lesson_id'] == missed_lesson_fixture


def test_create_assignment_transitions_existing_pending(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    """Если pending-резолюция уже авто-создана (при записи урока), назначение
    переводит ИМЕННО ЭТУ строку в makeup_scheduled — не создаёт вторую (UNIQUE)."""
    repository.autocreate_pending(missed_lesson_fixture, [student_fixture])

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

    rows = list(AbsenceResolution.objects.filter(
        missed_lesson_id=missed_lesson_fixture, student_id=student_fixture,
    ))
    assert len(rows) == 1
    assert rows[0].status == MAKEUP_SCHEDULED
    assert rows[0].id == result['resolution_ids'][0]


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
    """Повторное назначение того же пропуска тому же ученику (уже makeup_scheduled)
    → DuplicateAssignment."""
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
        # present_student present=true → авто-pending для него не создавался, и
        # назначение не прошло → у него нет НИКАКОЙ резолюции.
        assert not AbsenceResolution.objects.filter(
            missed_lesson_id=missed_lesson_fixture, student_id=present_student_id,
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
    # missed_lesson_unpaid_fixture авто-создал pending для unpaid_student. Блок по
    # балансу не должен ПЕРЕВЕСТИ его в makeup_scheduled — резолюция остаётся pending.
    assert not AbsenceResolution.objects.filter(
        missed_lesson_id=missed_lesson_unpaid_fixture, status=MAKEUP_SCHEDULED,
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
    assert AbsenceResolution.objects.get(id=rid).status == MAKEUP_SCHEDULED


def test_cancel_assignment_returns_to_pending(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    """Отмена назначенного доп.урока: makeup_scheduled → pending (пропуск снова
    ждёт решения), параметры сброшены."""
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
    assert result['status'] == PENDING
    assert result['assigned_teacher_id'] is None
    assert result['scheduled_date'] is None


def test_cancel_assignment_raises_if_not_makeup_scheduled(
    missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    """Отменить можно только назначенный (makeup_scheduled) доп.урок. Резолюция
    в pending (ещё не назначена) → ValueError (view → 409)."""
    repository.autocreate_pending(missed_lesson_fixture, [student_fixture])
    rid = repository.lock_for_assign(missed_lesson_fixture, student_fixture)['id']
    with pytest.raises(ValueError):
        services.cancel_assignment(rid, _FakeRequest())


def test_cancel_assignment_missing_returns_none(missed_lesson_fixture):
    assert services.cancel_assignment(999_999_999, _FakeRequest()) is None


def test_reassign_after_cancel_is_allowed(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    """Регрессия: после отмены (→pending) повторное назначение того же ученика за
    тот же пропуск обязано работать (переводит ту же строку обратно в
    makeup_scheduled), а не падать на DuplicateAssignment/UNIQUE."""
    payload = {
        'missed_lesson_id': missed_lesson_fixture, 'teacher_id': teacher_fixture,
        'student_ids': [student_fixture], 'scheduled_date': '2026-04-05',
        'scheduled_time': '15:00', 'duration_minutes': 45,
    }
    first = services.create_assignment(payload, _FakeRequest())
    first_rid = first['resolution_ids'][0]
    services.cancel_assignment(first_rid, _FakeRequest())
    assert repository.get_resolution_full(first_rid)['status'] == PENDING

    second = services.create_assignment(payload, _FakeRequest())
    assert second['created'] == 1
    assert repository.get_resolution_full(second['resolution_ids'][0])['status'] == MAKEUP_SCHEDULED
    # UNIQUE(missed_lesson, student) — та же строка, не дубликат.
    assert AbsenceResolution.objects.filter(
        missed_lesson_id=missed_lesson_fixture, student_id=student_fixture,
    ).count() == 1


def test_record_consumes_from_extra_keeps_original_absent(
    group_fixture, teacher_fixture, other_teacher_fixture, missed_lesson_fixture,
    student_fixture, lessons_done, resolution_cleanup,
):
    """Новая модель компенсации: потребление идёт от САМОГО факта доп.урока
    (present=true), а ИСХОДНЫЙ пропущенный урок остаётся present=false навсегда.
    lessons_done всё равно двигается на вес исходного урока (60мин → 1)."""
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
        # Факт доп.урока несёт длительность ИСХОДНОГО урока (60), не резолюции (45).
        assert fact.lesson_duration_minutes == 60
        assert Payroll.objects.get(lesson_id=fact.id).payment == 200

        assert repository.get_resolution_full(rid)['status'] == MAKEUP_DONE

        # Потребление — на самом факте доп.урока (present=true)…
        fact_att = LessonAttendance.objects.get(lesson_id=fact.id, student_id=student_fixture)
        assert fact_att.present is True
        # …а ИСХОДНЫЙ пропущенный урок остаётся present=false (не флипается).
        att = LessonAttendance.objects.get(lesson_id=missed_lesson_fixture, student_id=student_fixture)
        assert att.present is False
        # lessons_done двигается на вес исходного урока (60мин → 1 полный урок).
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
    в статусе makeup_done — повторный вызов record() на том же resolution_id
    обязан упасть ValueError'ом. Проверяет именно авторитетную проверку статуса
    под select_for_update() внутри atomic() (repository.lock_for_record), а не
    только неблокирующую предпроверку до atomic() — иначе гонка двух
    параллельных record() создала бы два Lesson-факта + Payroll (задвоенная
    зарплата), а второй mark_makeup_done() молча перезаписал бы fact_lesson_id
    первого.
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


def test_delete_fact_reverses_consumption(
    group_fixture, teacher_fixture, missed_lesson_fixture, student_fixture, lessons_done,
    resolution_cleanup,
):
    """Откат факта доп.урока симметрично списывает lessons_done обратно (на вес
    факта) и удаляет Lesson+Payroll. Исходный пропуск всё время present=false —
    новая модель компенсации, ретроактивной отметки исходного урока нет."""
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
    # Исходный пропущенный урок остался present=false (потребление — на факте).
    orig = LessonAttendance.objects.get(lesson_id=missed_lesson_fixture, student_id=student_fixture)
    assert orig.present is False

    ok = services.delete_fact(rid, _FakeRequest())
    assert ok is True
    assert lessons_done(group_fixture, student_fixture) == Decimal('0')
    assert not Lesson.objects.filter(id=result['lesson_id']).exists()
    assert not Payroll.objects.filter(lesson_id=result['lesson_id']).exists()
    # Исходный урок по-прежнему present=false.
    orig = LessonAttendance.objects.get(lesson_id=missed_lesson_fixture, student_id=student_fixture)
    assert orig.present is False

    full = repository.get_resolution_full(rid)
    assert full['status'] == PENDING
    assert full['fact_lesson_id'] is None


def test_delete_fact_second_call_raises_value_error(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    """
    Регрессия (audit, race condition): после успешного delete_fact() резолюция
    вернулась в status=pending — повторный вызов delete_fact() на том же
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


def test_autocreate_pending_for_lesson_idempotent(
    missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    """autocreate_pending_for_lesson (вызывается из record_lesson) идемпотентен:
    повторный вызов не создаёт дубликат (ON CONFLICT DO NOTHING)."""
    services.autocreate_pending_for_lesson(missed_lesson_fixture, [student_fixture])
    services.autocreate_pending_for_lesson(missed_lesson_fixture, [student_fixture])

    rows = list(AbsenceResolution.objects.filter(
        missed_lesson_id=missed_lesson_fixture, student_id=student_fixture,
    ))
    assert len(rows) == 1
    assert rows[0].status == PENDING


def test_cleanup_on_student_leave_deletes_open_keeps_done(
    teacher_fixture, missed_lesson_fixture, student_fixture,
    extra_missed_lessons, resolution_cleanup,
):
    """Уход/архивация ученика: pending + makeup_scheduled удаляются, makeup_done
    сохраняется (там уже проведён факт-урок и деньги)."""
    # pending на основном пропуске.
    repository.autocreate_pending(missed_lesson_fixture, [student_fixture])
    # makeup_scheduled на первом доп.пропуске.
    sched_id = repository.create_scheduled_direct(
        missed_lesson_id=extra_missed_lessons[0], student_id=student_fixture,
        assigned_teacher_id=teacher_fixture, scheduled_date=datetime.date(2026, 4, 12),
        scheduled_time=datetime.time(15, 0), duration_minutes=45)
    # makeup_done на втором доп.пропуске.
    done_id = repository.create_scheduled_direct(
        missed_lesson_id=extra_missed_lessons[1], student_id=student_fixture,
        assigned_teacher_id=teacher_fixture, scheduled_date=datetime.date(2026, 4, 13),
        scheduled_time=datetime.time(15, 0), duration_minutes=45)
    repository.mark_makeup_done(done_id, fact_lesson_id=extra_missed_lessons[1])

    deleted = services.cleanup_on_student_leave(student_fixture)
    assert deleted == 2

    assert repository.get_resolution_full(done_id)['status'] == MAKEUP_DONE
    assert repository.get_resolution_full(sched_id) is None
    assert repository.lock_for_assign(missed_lesson_fixture, student_fixture) is None
