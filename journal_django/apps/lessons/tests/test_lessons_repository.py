"""
Integration-тесты repository слоя lessons (реальная БД, managed=False).

Покрытие:
  - create_lesson_full: INSERT урока + attendance + payroll, инкремент lessons_done.
  - half-lesson (45 мин → шаг 0.5) vs обычный (60 мин → шаг 1).
  - get_lesson_full: meta + attendance[] + payroll, None для отсутствующего.
  - update_lesson: COALESCE-семантика, original_teacher_id nullable.
  - delete_lesson_full: откат lessons_done, CASCADE attendance, удаление payroll.
  - update_attendance_cell: дельта lessons_done (false→true→false), UPSERT.
  - list_lessons: фильтры, сорт, контракт {rows,total,page,page_size}.
  - DATE-инвариант: lesson_date ввод == вывод без сдвига.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection

from apps.lessons import repository

pytestmark = pytest.mark.django_db


def _delete_lesson(lesson_id: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lessons WHERE id = %s', [lesson_id])


# ---------------------------------------------------------------------------
# create_lesson_full
# ---------------------------------------------------------------------------

def test_create_lesson_increments_lessons_done_step_1(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-01',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    try:
        # 60-мин урок → шаг 1
        assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')
        full = repository.get_lesson_full(lesson_id)
        # repo-слой отдаёт psycopg2 date; строку '2026-03-01' даёт renderer (см. API-тест)
        assert full['lesson_date'] == datetime.date(2026, 3, 1)
        assert len(full['attendance']) == 1
        assert full['attendance'][0]['present'] is True
    finally:
        _delete_lesson(lesson_id)


def test_create_lesson_half_lesson_step_05(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-02',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 45,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    try:
        # 45-мин урок → шаг 0.5
        assert lessons_done(group_fixture, student_fixture) == Decimal('0.5')
    finally:
        _delete_lesson(lesson_id)


def test_create_lesson_absent_student_no_increment(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-03',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    try:
        assert lessons_done(group_fixture, student_fixture) == Decimal('0.0')
    finally:
        _delete_lesson(lesson_id)


def test_create_lesson_with_payroll(
    group_fixture, teacher_id_fixture, student_fixture
):
    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-04',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'payroll': {
            'total_students': 5,
            'present_count': 4,
            'payment': 650,
            'penalty': 0,
        },
    })
    try:
        full = repository.get_lesson_full(lesson_id)
        assert full['payroll'] is not None
        assert full['payroll']['total_students'] == 5
        assert full['payroll']['present_count'] == 4
        # numeric → Decimal с масштабом
        assert full['payroll']['payment'] == Decimal('650.00')
    finally:
        _delete_lesson(lesson_id)


# ---------------------------------------------------------------------------
# get_lesson_full
# ---------------------------------------------------------------------------

def test_get_lesson_full_missing_returns_none():
    assert repository.get_lesson_full(999_999_999) is None


# ---------------------------------------------------------------------------
# update_lesson
# ---------------------------------------------------------------------------

def test_update_lesson_coalesce(group_fixture, teacher_id_fixture):
    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-05',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    try:
        # Передаём только lesson_type — остальное должно сохраниться.
        updated = repository.update_lesson(lesson_id, {'lesson_type': 'substitution'})
        assert updated['lesson_type'] == 'substitution'
        assert updated['lesson_date'] == datetime.date(2026, 3, 5)
    finally:
        _delete_lesson(lesson_id)


def test_update_lesson_original_teacher_explicit_null(group_fixture, teacher_id_fixture):
    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-06',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'original_teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    try:
        # Явный null → должен обнулиться.
        updated = repository.update_lesson(lesson_id, {'original_teacher_id': None})
        assert updated['original_teacher_id'] is None

        # Повторно ставим, затем НЕ передаём ключ → должен сохраниться.
        repository.update_lesson(lesson_id, {'original_teacher_id': teacher_id_fixture})
        again = repository.update_lesson(lesson_id, {'lesson_number': 2})
        assert again['original_teacher_id'] == teacher_id_fixture
    finally:
        _delete_lesson(lesson_id)


def test_update_lesson_missing_returns_none():
    assert repository.update_lesson(999_999_999, {'lesson_type': 'regular'}) is None


# ---------------------------------------------------------------------------
# delete_lesson_full
# ---------------------------------------------------------------------------

def test_delete_lesson_rolls_back_lessons_done(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-07',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')

    ok = repository.delete_lesson_full(lesson_id)
    assert ok is True
    # lessons_done откатился
    assert lessons_done(group_fixture, student_fixture) == Decimal('0.0')
    # attendance удалён по CASCADE
    with connection.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
        assert cur.fetchone()[0] == 0


def test_delete_lesson_missing_returns_false():
    assert repository.delete_lesson_full(999_999_999) is False


def test_delete_lesson_unlinks_planned_lesson(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    """Удаление урока возвращает связанную плановую строку в 'pending' (не
    остаётся зависшей 'done' без факта — см. design doc, аудит delete_lesson_full)."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
            "scheduled_time, teacher_id, status, created_at, updated_at) "
            "VALUES (%s, 1, 1, '2026-03-07', '10:00', %s, 'pending', NOW(), NOW()) "
            "RETURNING id",
            [group_fixture, teacher_id_fixture],
        )
        planned_id = cur.fetchone()[0]

    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-07',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    try:
        from apps.scheduling.repository import link_facts
        link_facts(group_fixture)
        with connection.cursor() as cur:
            cur.execute(
                'SELECT fact_lesson_id, status FROM planned_lessons WHERE id = %s',
                [planned_id],
            )
            fact_lesson_id, status = cur.fetchone()
        assert fact_lesson_id == lesson_id
        assert status == 'done'

        assert repository.delete_lesson_full(lesson_id) is True

        with connection.cursor() as cur:
            cur.execute(
                'SELECT fact_lesson_id, status FROM planned_lessons WHERE id = %s',
                [planned_id],
            )
            fact_lesson_id, status = cur.fetchone()
        assert fact_lesson_id is None
        assert status == 'pending'
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM planned_lessons WHERE id = %s', [planned_id])


# ---------------------------------------------------------------------------
# update_attendance_cell
# ---------------------------------------------------------------------------

def test_attendance_toggle_delta(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-08',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    try:
        # Нет посещения → ставим present=true → +1
        ok = repository.update_attendance_cell(lesson_id, student_fixture, True)
        assert ok is True
        assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')

        # true → false → -1
        repository.update_attendance_cell(lesson_id, student_fixture, False)
        assert lessons_done(group_fixture, student_fixture) == Decimal('0.0')

        # false → true снова → +1
        repository.update_attendance_cell(lesson_id, student_fixture, True)
        assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')
    finally:
        _delete_lesson(lesson_id)


def test_attendance_toggle_missing_lesson_returns_false(student_fixture):
    assert repository.update_attendance_cell(999_999_999, student_fixture, True) is False


# ---------------------------------------------------------------------------
# list_lessons
# ---------------------------------------------------------------------------

def test_list_lessons_envelope_and_filter(group_fixture, teacher_id_fixture):
    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-09',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    try:
        result = repository.list_lessons(filters={'group_id': group_fixture})
        assert set(result.keys()) == {'rows', 'total', 'page', 'page_size'}
        assert result['total'] == 1
        assert result['rows'][0]['id'] == lesson_id
        assert result['rows'][0]['group_name'] == '__les_test_group__'
        assert result['rows'][0]['lesson_date'] == datetime.date(2026, 3, 9)
    finally:
        _delete_lesson(lesson_id)


def test_list_lessons_invalid_sort_by_falls_back(group_fixture, teacher_id_fixture):
    # Невалидный sort_by → тихий fallback (как Express paginate), без ошибки.
    lesson_id = repository.create_lesson_full({
        'lesson_date': '2026-03-10',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    try:
        result = repository.list_lessons(
            sort_by='; DROP TABLE lessons; --',
            filters={'group_id': group_fixture},
        )
        assert result['total'] == 1
    finally:
        _delete_lesson(lesson_id)
