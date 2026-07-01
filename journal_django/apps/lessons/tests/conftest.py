"""
conftest.py для тестов lessons.

Фаза 4: HMAC _make_cookie удалён. Аутентификация — JWT через корневые фикстуры.
Фикстуры direction/group/student/membership сохранены без изменений.
managed=False — работаем с journal_test, чистим прямым DELETE.
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
        pytest.skip('No teachers in DB — skipping lessons tests')
    return row[0]


@pytest.fixture
def teacher_id_fixture():
    return _get_teacher_id()


@pytest.fixture
def direction_fixture():
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO directions (name, sheet_name, is_individual, total_lessons, active)
            VALUES ('__les_test_dir__', '__les_sheet__', false, 8, true)
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
            VALUES ('__les_test_student__', 'enrolled')
            RETURNING id
            """,
        )
        student_id = cur.fetchone()[0]
    yield student_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM students WHERE id = %s', [student_id])


@pytest.fixture
def group_fixture(direction_fixture, teacher_id_fixture):
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO groups (name, direction_id, teacher_id, is_individual,
                                lesson_duration_minutes, active)
            VALUES ('__les_test_group__', %s, %s, false, 60, true)
            RETURNING id
            """,
            [direction_fixture, teacher_id_fixture],
        )
        group_id = cur.fetchone()[0]
    yield group_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM groups WHERE id = %s', [group_id])


@pytest.fixture
def membership_fixture(group_fixture, student_fixture):
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO group_memberships (group_id, student_id, lessons_done, remaining, active)
            VALUES (%s, %s, 0, 0, true)
            RETURNING id
            """,
            [group_fixture, student_fixture],
        )
        membership_id = cur.fetchone()[0]
    yield membership_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])


def _lessons_done(group_id: int, student_id: int):
    """Текущее значение lessons_done для пары (group, student)."""
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
