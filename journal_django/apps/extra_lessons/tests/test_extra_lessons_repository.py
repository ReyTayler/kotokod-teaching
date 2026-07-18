"""Integration-тесты apps.extra_lessons.repository (реальная БД, пер-ученик AbsenceResolution)."""
from __future__ import annotations

import datetime

import pytest
from django.db import connection

from apps.extra_lessons import repository
from apps.extra_lessons.models import MAKEUP_DONE, MAKEUP_SCHEDULED, PENDING

pytestmark = pytest.mark.django_db


def _assign_fixture_pending(missed_lesson_id, student_id, teacher_id):
    """Авто-созданный фикстурой pending → makeup_scheduled. missed_lesson_fixture
    пишет урок через record_lesson, который теперь авто-создаёт pending, поэтому
    прямой create_scheduled_direct на ту же пару конфликтует по UNIQUE — берём
    существующий pending и назначаем его."""
    rid = repository.lock_for_assign(missed_lesson_id, student_id)['id']
    repository.assign_pending(
        rid, assigned_teacher_id=teacher_id,
        scheduled_date=datetime.date(2026, 4, 5), scheduled_time=datetime.time(15, 0),
        duration_minutes=45)
    return rid


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
                [group_fixture, teacher_fixture, date, i, f'__el_test_token_{i}__'],
            )
            ids.append(cur.fetchone()[0])
    yield ids
    with connection.cursor() as cur:
        cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id = ANY(%s)', [ids])
        cur.execute('DELETE FROM lessons WHERE id = ANY(%s)', [ids])


def test_autocreate_pending_creates_pending(
    missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    n = repository.autocreate_pending(missed_lesson_fixture, [student_fixture])
    assert n == 1
    rows = repository.list_resolutions(
        filters={'status': PENDING})['rows']
    mine = [r for r in rows if r['missed_lesson_id'] == missed_lesson_fixture
            and r['student_id'] == student_fixture]
    assert len(mine) == 1
    assert mine[0]['status'] == PENDING
    assert mine[0]['fact_lesson_id'] is None

    # Идемпотентность: повторный вызов не создаёт дубликат (ON CONFLICT DO NOTHING).
    repository.autocreate_pending(missed_lesson_fixture, [student_fixture])
    rows = repository.list_resolutions(filters={'status': PENDING})['rows']
    mine = [r for r in rows if r['missed_lesson_id'] == missed_lesson_fixture
            and r['student_id'] == student_fixture]
    assert len(mine) == 1


def test_autocreate_pending_empty_is_noop(missed_lesson_fixture):
    assert repository.autocreate_pending(missed_lesson_fixture, []) == 0


def test_assign_pending_moves_to_makeup_scheduled(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    repository.autocreate_pending(missed_lesson_fixture, [student_fixture])
    locked = repository.lock_for_assign(missed_lesson_fixture, student_fixture)
    assert locked is not None
    assert locked['status'] == PENDING

    repository.assign_pending(
        locked['id'], assigned_teacher_id=teacher_fixture,
        scheduled_date=datetime.date(2026, 4, 5), scheduled_time=datetime.time(15, 0),
        duration_minutes=45)

    full = repository.get_resolution_full(locked['id'])
    assert full['status'] == MAKEUP_SCHEDULED
    assert full['assigned_teacher_id'] == teacher_fixture
    assert full['scheduled_date'] == datetime.date(2026, 4, 5)
    assert full['duration_minutes'] == 45
    assert full['fact_lesson_id'] is None


def test_create_scheduled_direct(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    """Edge: pending-строки нет — резолюция создаётся сразу в makeup_scheduled."""
    # Убрать авто-pending (missed_lesson_fixture пишет урок через record_lesson,
    # который авто-создаёт pending) — этот путь проверяет именно ОТСУТСТВИЕ pending.
    with connection.cursor() as cur:
        cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id=%s AND student_id=%s',
                    [missed_lesson_fixture, student_fixture])
    resolution_id = repository.create_scheduled_direct(
        missed_lesson_id=missed_lesson_fixture, student_id=student_fixture,
        assigned_teacher_id=teacher_fixture, scheduled_date=datetime.date(2026, 4, 5),
        scheduled_time=datetime.time(15, 0), duration_minutes=45)

    full = repository.get_resolution_full(resolution_id)
    assert full['status'] == MAKEUP_SCHEDULED
    assert full['assigned_teacher_id'] == teacher_fixture
    assert full['missed_lesson_id'] == missed_lesson_fixture
    assert full['student_id'] == student_fixture
    assert full['duration_minutes'] == 45
    assert full['fact_lesson_id'] is None


def test_back_to_pending_resets(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    resolution_id = _assign_fixture_pending(missed_lesson_fixture, student_fixture, teacher_fixture)

    # Из makeup_scheduled → pending: параметры сбрасываются.
    repository.back_to_pending(resolution_id)
    full = repository.get_resolution_full(resolution_id)
    assert full['status'] == PENDING
    assert full['assigned_teacher_id'] is None
    assert full['scheduled_date'] is None
    assert full['scheduled_time'] is None
    assert full['duration_minutes'] is None
    assert full['fact_lesson_id'] is None

    # Из makeup_done → pending: факт тоже сбрасывается.
    repository.assign_pending(
        resolution_id, assigned_teacher_id=teacher_fixture,
        scheduled_date=datetime.date(2026, 4, 5), scheduled_time=datetime.time(15, 0),
        duration_minutes=45)
    repository.mark_makeup_done(resolution_id, fact_lesson_id=missed_lesson_fixture)
    assert repository.get_resolution_full(resolution_id)['status'] == MAKEUP_DONE

    repository.back_to_pending(resolution_id)
    full = repository.get_resolution_full(resolution_id)
    assert full['status'] == PENDING
    assert full['assigned_teacher_id'] is None
    assert full['scheduled_date'] is None
    assert full['duration_minutes'] is None
    assert full['fact_lesson_id'] is None


def test_mark_makeup_done_sets_fact(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    resolution_id = _assign_fixture_pending(missed_lesson_fixture, student_fixture, teacher_fixture)

    repository.mark_makeup_done(resolution_id, fact_lesson_id=missed_lesson_fixture)
    full = repository.get_resolution_full(resolution_id)
    assert full['status'] == MAKEUP_DONE
    assert full['fact_lesson_id'] == missed_lesson_fixture


def test_has_active_resolution(
    teacher_fixture, missed_lesson_fixture, student_fixture, resolution_cleanup,
):
    # Нет строки → False.
    assert repository.has_active_resolution(missed_lesson_fixture, student_fixture) is False

    # pending НЕ считается активной (её как раз назначают).
    repository.autocreate_pending(missed_lesson_fixture, [student_fixture])
    assert repository.has_active_resolution(missed_lesson_fixture, student_fixture) is False

    resolution_id = repository.lock_for_assign(missed_lesson_fixture, student_fixture)['id']
    repository.assign_pending(
        resolution_id, assigned_teacher_id=teacher_fixture,
        scheduled_date=datetime.date(2026, 4, 5), scheduled_time=datetime.time(15, 0),
        duration_minutes=45)
    # makeup_scheduled → активна.
    assert repository.has_active_resolution(missed_lesson_fixture, student_fixture) is True

    # makeup_done → всё ещё активна (блокирует задвоение компенсации).
    repository.mark_makeup_done(resolution_id, fact_lesson_id=missed_lesson_fixture)
    assert repository.has_active_resolution(missed_lesson_fixture, student_fixture) is True

    # Откат в pending → снова НЕ активна.
    repository.back_to_pending(resolution_id)
    assert repository.has_active_resolution(missed_lesson_fixture, student_fixture) is False


def test_delete_open_for_student_keeps_done(
    teacher_fixture, missed_lesson_fixture, student_fixture,
    extra_missed_lessons, resolution_cleanup,
):
    """Уход ученика: pending + makeup_scheduled удаляются, makeup_done сохраняется.
    Строки на РАЗНЫХ пропущенных уроках (UNIQUE per пропуск×ученик)."""
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

    deleted = repository.delete_open_for_student(student_fixture)
    assert deleted == 2

    # makeup_done остаётся.
    assert repository.get_resolution_full(done_id)['status'] == MAKEUP_DONE
    # pending и makeup_scheduled удалены.
    assert repository.get_resolution_full(sched_id) is None
    assert repository.lock_for_assign(missed_lesson_fixture, student_fixture) is None


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
    resolution_id = _assign_fixture_pending(missed_lesson_fixture, student_fixture, teacher_fixture)
    repository.mark_makeup_done(resolution_id, fact_lesson_id=missed_lesson_fixture)

    locked = repository.lock_for_delete(resolution_id)
    assert locked['status'] == MAKEUP_DONE
    assert locked['missed_lesson_id'] == missed_lesson_fixture
    assert locked['student_id'] == student_fixture
    assert locked['fact_lesson_id'] == missed_lesson_fixture
