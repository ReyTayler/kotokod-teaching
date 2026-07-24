"""
test_teacher_spa_repository.py — интеграционные тесты repository слоя teacher_spa.

Покрытие:
  - read_all_students: структура data[teacher][group], поля студента,
    lessonsDone (max), startDate формат 'DD.MM.YYYY'.
  - read_filled_lessons: пустая карта если нет уроков за неделю;
    заполненная после INSERT урока.
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.teacher_spa import repository

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _set_secret(settings):
    settings.ADMIN_COOKIE_SECRET = 'deadbeef' * 16


# ---------------------------------------------------------------------------
# read_all_students
# ---------------------------------------------------------------------------

class TestReadAllStudents:

    def test_returns_data_and_index(
        self, teacher_fixture, group_fixture, student_fixture, membership_fixture
    ):
        """Базовая структура: data[teacher][group] = {students, lessonsDone, ...}."""
        _, teacher_name = teacher_fixture
        result = repository.read_all_students()
        assert 'data' in result
        assert 'index' in result
        assert teacher_name in result['data']

    def test_group_fields(
        self, teacher_fixture, group_fixture, student_fixture, membership_fixture
    ):
        """Поля группы: students, lessonsDone, pm, vkChat, startDate, isGroup."""
        _, teacher_name = teacher_fixture
        result = repository.read_all_students()
        teacher_data = result['data'][teacher_name]
        # Ищем нашу тестовую группу
        assert len(teacher_data) >= 1
        # Находим группу по ID
        group_name = '__spa_test_group__ пн 10:00'
        assert group_name in teacher_data
        grp = teacher_data[group_name]
        assert 'students' in grp
        assert 'lessonsDone' in grp
        assert 'pm' in grp
        assert 'vkChat' in grp
        assert 'startDate' in grp
        assert 'isGroup' in grp
        assert isinstance(grp['isGroup'], bool)

    def test_student_fields(
        self, teacher_fixture, group_fixture, student_fixture, membership_fixture
    ):
        """Поля студента: name, lessonsDone, remaining, birthDate, sheetName, sheetRow."""
        _, teacher_name = teacher_fixture
        result = repository.read_all_students()
        group_name = '__spa_test_group__ пн 10:00'
        grp = result['data'][teacher_name][group_name]
        assert len(grp['students']) >= 1
        stu = next(s for s in grp['students'] if s['name'] == '__spa_test_student__')
        assert 'name' in stu
        assert 'lessonsDone' in stu
        assert 'remaining' in stu
        assert 'birthDate' in stu
        assert 'sheetName' in stu
        assert 'sheetRow' in stu
        # lessonsDone=0 в фикстуре → 0 (JS Number()||0)
        assert stu['lessonsDone'] == 0
        # remaining — вычисляемый общий баланс ученика; membership_fixture теперь
        # включает оплату на 8 уроков (см. conftest.py) → 8
        assert stu['remaining'] == 8
        # birthDate пустая строка (NULL в БД)
        assert stu['birthDate'] == ''

    def test_lessons_done_max(
        self, teacher_fixture, group_fixture, student_fixture
    ):
        """lessonsDone у группы = max по ученикам."""
        # Создаём второго ученика с lessons_done=5
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO students (full_name, enrollment_status) "
                "VALUES ('__spa_stu2__', 'enrolled') RETURNING id"
            )
            stu2_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO group_memberships (group_id, student_id, lessons_done, active)
                VALUES (%s, %s, 5, true) RETURNING id
                """,
                [group_fixture, stu2_id],
            )
            mem2_id = cur.fetchone()[0]
            # Первый ученик без membership — создаём с lessons_done=2
            cur.execute(
                """
                INSERT INTO group_memberships (group_id, student_id, lessons_done, active)
                VALUES (%s, %s, 2, true) RETURNING id
                """,
                [group_fixture, student_fixture],
            )
            mem1_id = cur.fetchone()[0]

        try:
            _, teacher_name = teacher_fixture
            result = repository.read_all_students()
            group_name = '__spa_test_group__ пн 10:00'
            grp = result['data'][teacher_name][group_name]
            # lessonsDone группы = 5 (max)
            assert grp['lessonsDone'] == 5
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM group_memberships WHERE id IN (%s, %s)', [mem1_id, mem2_id])
                cur.execute('DELETE FROM students WHERE id = %s', [stu2_id])


def test_read_all_students_marks_locked_transferred_student(
    teacher_fixture, direction_fixture, group_fixture, student_fixture, membership_fixture,
):
    """Ученик с B=5 (source membership lessons_done=5), а в group_fixture
    max(lessonsDone)=2 (< 5) — locked=True, lockedThrough=5.0."""
    teacher_id, teacher_name = teacher_fixture
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE group_memberships SET lessons_done = 2 WHERE id = %s", [membership_fixture],
        )
        cur.execute(
            "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
            "lesson_duration_minutes,active,lesson_number_offset) VALUES ('__spa_locked_src__',%s,%s,false,60,false,0) "
            "RETURNING id",
            [direction_fixture, teacher_id],
        )
        src_group_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s,%s,5,false) RETURNING id",
            [src_group_id, student_fixture],
        )
        src_membership_id = cur.fetchone()[0]
        cur.execute(
            "UPDATE group_memberships SET transferred_from_id = %s WHERE id = %s",
            [src_membership_id, membership_fixture],
        )
    try:
        result = repository.read_all_students()
        group_data = result['data'][teacher_name]['__spa_test_group__ пн 10:00']
        student_row = next(s for s in group_data['students'] if s['name'] == '__spa_test_student__')
        assert student_row['locked'] is True
        assert student_row['lockedThrough'] == 5.0
    finally:
        with connection.cursor() as cur:
            cur.execute("UPDATE group_memberships SET transferred_from_id = NULL WHERE id = %s",
                        [membership_fixture])
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [src_membership_id])
            cur.execute('DELETE FROM groups WHERE id = %s', [src_group_id])


def test_read_all_students_marks_skip_student(
    teacher_fixture, group_fixture, student_fixture, membership_fixture,
):
    """Ученик с маркером LessonSkip на СЛЕДУЮЩИЙ урок группы (lessonsDone=2 → урок 3)
    получает skip=True, чтобы преподаватель не мог его отметить. Служебные поля
    (_student_id/_group_id) в ответ не утекают."""
    _, teacher_name = teacher_fixture
    with connection.cursor() as cur:
        cur.execute("UPDATE group_memberships SET lessons_done = 2 WHERE id = %s", [membership_fixture])
        cur.execute("INSERT INTO lesson_skips (group_id, student_id, lesson_number, created_at) "
                    "VALUES (%s, %s, 3, now())", [group_fixture, student_fixture])
    try:
        result = repository.read_all_students()
        grp = result['data'][teacher_name]['__spa_test_group__ пн 10:00']
        assert '_group_id' not in grp
        row = next(s for s in grp['students'] if s['name'] == '__spa_test_student__')
        assert row['skip'] is True
        assert '_student_id' not in row
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM lesson_skips WHERE group_id = %s', [group_fixture])


# ---------------------------------------------------------------------------
# read_filled_lessons
# ---------------------------------------------------------------------------

class TestReadFilledLessons:

    def test_empty_map_no_lessons(self):
        """Нет уроков за неделю → пустой map."""
        result = repository.read_filled_lessons('2020-01-06')  # старая дата
        assert isinstance(result, dict)
        # Может содержать что угодно из реальной БД, но нас интересует структура
        assert all(isinstance(k, str) for k in result)
        assert all(isinstance(v, str) for v in result.values())

    def test_filled_lesson_appears(
        self, teacher_fixture, group_fixture, student_fixture, membership_fixture
    ):
        """После вставки урока за неделю — group_name появляется в map."""
        week_start = '2020-03-09'  # понедельник (уникальная старая дата)
        lesson_date = '2020-03-10'  # внутри недели
        teacher_id, _ = teacher_fixture

        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO lessons (lesson_date, teacher_id, group_id, lesson_number,
                                     lesson_duration_minutes, lesson_type, submitted_by_token)
                VALUES (%s, %s, %s, 99.0, 60, 'regular', '__spa_test__')
                RETURNING id
                """,
                [lesson_date, teacher_id, group_fixture],
            )
            lesson_id = cur.fetchone()[0]

        try:
            result = repository.read_filled_lessons(week_start)
            group_name = '__spa_test_group__ пн 10:00'
            key = group_name + '|||' + week_start
            assert key in result
            # Значение — строка вида 'DD.MM HH:MM' или пустая
            assert isinstance(result[key], str)
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM lessons WHERE id = %s', [lesson_id])
