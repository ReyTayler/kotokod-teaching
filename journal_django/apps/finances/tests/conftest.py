"""
conftest для тестов finances. Граф direction→group→student→payments/lessons/attendance,
чистится прямым DELETE. managed=False — продовая БД.
"""
from __future__ import annotations

import pytest
from django.db import connection


@pytest.fixture(scope='session')
def django_db_setup():
    pass


def _get_teacher_id() -> int:
    with connection.cursor() as cur:
        cur.execute('SELECT id FROM teachers LIMIT 1')
        row = cur.fetchone()
    if not row:
        pytest.skip('No teachers in DB')
    return row[0]


@pytest.fixture
def teacher_id_fixture():
    return _get_teacher_id()


@pytest.fixture
def direction_fixture():
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO directions (name, is_individual, total_lessons, active) "
            "VALUES ('__fin_dir__', false, 16, true) RETURNING id"
        )
        did = cur.fetchone()[0]
    yield did
    with connection.cursor() as cur:
        cur.execute('DELETE FROM directions WHERE id = %s', [did])


@pytest.fixture
def student_fixture():
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status) "
            "VALUES ('__fin_student__', 'enrolled') RETURNING id"
        )
        sid = cur.fetchone()[0]
    yield sid
    with connection.cursor() as cur:
        cur.execute('DELETE FROM students WHERE id = %s', [sid])


@pytest.fixture
def group_fixture(direction_fixture, teacher_id_fixture):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active) "
            "VALUES ('__fin_group__', %s, %s, false, 60, true) RETURNING id",
            [direction_fixture, teacher_id_fixture],
        )
        gid = cur.fetchone()[0]
    yield gid
    with connection.cursor() as cur:
        cur.execute('DELETE FROM groups WHERE id = %s', [gid])


@pytest.fixture
def graph_cleanup():
    """Возвращает список id для удаления уроков/оплат в teardown."""
    created = {'lessons': [], 'payments': []}
    yield created
    with connection.cursor() as cur:
        for lid in created['lessons']:
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lid])
            cur.execute('DELETE FROM lessons WHERE id = %s', [lid])
        for pid in created['payments']:
            cur.execute('DELETE FROM payments WHERE id = %s', [pid])
