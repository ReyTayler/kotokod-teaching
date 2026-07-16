"""
Integration-тесты слоя lessons (реальная БД, managed=False).

create/attendance-toggle идут через apps.lessons.services (record_lesson —
единое ядро, см. apps.lessons.repository для low-level ORM-хелперов). Остальное
(update_lesson/delete_lesson_full/list_lessons) — repository напрямую, как раньше.

Покрытие:
  - create (через services.create_lesson_full): INSERT урока + attendance +
    payroll (сервер считает сам), инкремент lessons_done, link_facts.
  - half-lesson (45 мин → шаг 0.5) vs обычный (60 мин → шаг 1).
  - get_lesson_full: meta + attendance[] + payroll, None для отсутствующего.
  - update_lesson: COALESCE-семантика, original_teacher_id nullable.
  - delete_lesson_full: откат lessons_done, CASCADE attendance, удаление payroll,
    возврат planned_lessons в pending.
  - update_attendance_cell: дельта lessons_done (false→true→false), UPSERT,
    пересчёт payroll, блокировка без оплаченных уроков.
  - list_lessons: фильтры, сорт, контракт {rows,total,page,page_size}.
  - DATE-инвариант: lesson_date ввод == вывод без сдвига.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection

from apps.lessons import repository, services
from apps.lessons.exceptions import UnpaidAttendanceBlocked

pytestmark = pytest.mark.django_db


def _delete_lesson(lesson_id: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lessons WHERE id = %s', [lesson_id])


# ---------------------------------------------------------------------------
# create (services.create_lesson_full → record_lesson)
# ---------------------------------------------------------------------------

def test_create_lesson_increments_lessons_done_step_1(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-01',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    lesson_id = result['lesson_id']
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
    result = services.create_lesson_full({
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
        _delete_lesson(result['lesson_id'])


def test_create_lesson_absent_student_no_increment(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
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
        _delete_lesson(result['lesson_id'])


def test_create_lesson_with_payroll(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture
):
    """Payroll теперь всегда считается сервером из attendance — total=1,
    present=1 → small-group-full formula = 500. Клиентский payroll больше не
    принимается (payroll не передаём вообще)."""
    result = services.create_lesson_full({
        'lesson_date': '2026-03-04',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    lesson_id = result['lesson_id']
    try:
        full = repository.get_lesson_full(lesson_id)
        assert full['payroll'] is not None
        assert full['payroll']['total_students'] == 1
        assert full['payroll']['present_count'] == 1
        assert full['payroll']['payment'] == Decimal('500.00')
    finally:
        _delete_lesson(lesson_id)


def test_create_lesson_blocked_without_paid_balance(
    group_fixture, teacher_id_fixture, student_fixture,
):
    """Ученик без оплаченных уроков (membership без payments) + present:true →
    UnpaidAttendanceBlocked, урок не создаётся вообще."""
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO group_memberships (group_id, student_id, lessons_done, active) '
            'VALUES (%s, %s, 0, true) RETURNING id',
            [group_fixture, student_fixture],
        )
        membership_id = cur.fetchone()[0]
    try:
        with pytest.raises(UnpaidAttendanceBlocked):
            services.create_lesson_full({
                'lesson_date': '2026-03-04',
                'group_id': group_fixture,
                'teacher_id': teacher_id_fixture,
                'lesson_number': 1,
                'lesson_duration_minutes': 60,
                'attendance': [{'student_id': student_fixture, 'present': True}],
            })
        with connection.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM lessons WHERE group_id = %s AND lesson_date = %s',
                [group_fixture, '2026-03-04'],
            )
            assert cur.fetchone()[0] == 0
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])


# ---------------------------------------------------------------------------
# get_lesson_full
# ---------------------------------------------------------------------------

def test_get_lesson_full_missing_returns_none():
    assert repository.get_lesson_full(999_999_999) is None


# ---------------------------------------------------------------------------
# update_lesson
# ---------------------------------------------------------------------------

def test_update_lesson_coalesce(group_fixture, teacher_id_fixture):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-05',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    lesson_id = result['lesson_id']
    try:
        # Передаём только lesson_type — остальное должно сохраниться.
        updated = repository.update_lesson(lesson_id, {'lesson_type': 'substitution'})
        assert updated['lesson_type'] == 'substitution'
        assert updated['lesson_date'] == datetime.date(2026, 3, 5)
    finally:
        _delete_lesson(lesson_id)


def test_update_lesson_original_teacher_explicit_null(group_fixture, teacher_id_fixture):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-06',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'original_teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    lesson_id = result['lesson_id']
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
    result = services.create_lesson_full({
        'lesson_date': '2026-03-07',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    lesson_id = result['lesson_id']
    assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')

    ok = repository.delete_lesson_full(lesson_id)
    assert ok is True
    # lessons_done откатился
    assert lessons_done(group_fixture, student_fixture) == Decimal('0.0')
    # attendance удалён по CASCADE
    with connection.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
        assert cur.fetchone()[0] == 0


def test_delete_lesson_unlinks_planned_lesson(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    """Удаление урока возвращает связанную плановую строку в 'pending' (не
    остаётся зависшей 'done' без факта)."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
            "scheduled_time, teacher_id, status, created_at, updated_at) "
            "VALUES (%s, 1, 1, '2026-03-07', '10:00', %s, 'pending', NOW(), NOW()) "
            "RETURNING id",
            [group_fixture, teacher_id_fixture],
        )
        planned_id = cur.fetchone()[0]

    result = services.create_lesson_full({
        'lesson_date': '2026-03-07',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    lesson_id = result['lesson_id']
    try:
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


def test_delete_lesson_missing_returns_false():
    assert repository.delete_lesson_full(999_999_999) is False


# ---------------------------------------------------------------------------
# update_attendance_cell
# ---------------------------------------------------------------------------

def test_attendance_toggle_delta(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-08',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    lesson_id = result['lesson_id']
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


def test_attendance_toggle_recomputes_payroll(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    """Переключение ячейки посещаемости пересчитывает present_count/payment
    в Payroll (не penalty — она про своевременность исходной записи). НАПОМИНАНИЕ:
    update_attendance_cell пока НЕ пересчитывает payroll и НЕ проверяет баланс —
    это отдельная, следующая задача плана (не ваша). Если этот тест сейчас
    падает на "before"/"after" payroll-ассертах, это ОЖИДАЕМО в конце ВАШЕЙ
    задачи — следующая задача сделает его зелёным. НЕ пытайтесь чинить
    update_attendance_cell сами."""
    result = services.create_lesson_full({
        'lesson_date': '2026-03-08',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    lesson_id = result['lesson_id']
    try:
        before = repository.get_lesson_full(lesson_id)
        assert before['payroll']['present_count'] == 0
        assert before['payroll']['payment'] == Decimal('0.00')

        ok = repository.update_attendance_cell(lesson_id, student_fixture, True)
        assert ok is True

        after = repository.get_lesson_full(lesson_id)
        assert after['payroll']['present_count'] == 1
        # total_students=1, present=1 → small-group-full = 500
        assert after['payroll']['payment'] == Decimal('500.00')
    finally:
        _delete_lesson(lesson_id)


def test_attendance_toggle_blocked_when_no_paid_balance(
    group_fixture, teacher_id_fixture, student_fixture,
):
    """Ученик без оплаченных уроков (membership без payments) — переключить в
    present:true нельзя, поднимает UnpaidAttendanceBlocked, ничего не меняется.
    НАПОМИНАНИЕ: как и предыдущий тест, это поведение реализует СЛЕДУЮЩАЯ
    задача плана, не ваша — если падает, это ожидаемо сейчас."""
    with connection.cursor() as cur:
        cur.execute(
            'INSERT INTO group_memberships (group_id, student_id, lessons_done, active) '
            'VALUES (%s, %s, 0, true) RETURNING id',
            [group_fixture, student_fixture],
        )
        membership_id = cur.fetchone()[0]

    result = services.create_lesson_full({
        'lesson_date': '2026-03-08',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    lesson_id = result['lesson_id']
    try:
        with pytest.raises(UnpaidAttendanceBlocked):
            repository.update_attendance_cell(lesson_id, student_fixture, True)
        with connection.cursor() as cur:
            cur.execute(
                'SELECT present FROM lesson_attendance WHERE lesson_id = %s AND student_id = %s',
                [lesson_id, student_fixture],
            )
            assert cur.fetchone()[0] is False
    finally:
        _delete_lesson(lesson_id)
        with connection.cursor() as cur:
            cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])


# ---------------------------------------------------------------------------
# list_lessons
# ---------------------------------------------------------------------------

def test_list_lessons_envelope_and_filter(group_fixture, teacher_id_fixture):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-09',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    lesson_id = result['lesson_id']
    try:
        list_result = repository.list_lessons(filters={'group_id': group_fixture})
        assert set(list_result.keys()) == {'rows', 'total', 'page', 'page_size'}
        assert list_result['total'] == 1
        assert list_result['rows'][0]['id'] == lesson_id
        assert list_result['rows'][0]['group_name'] == '__les_test_group__'
        assert list_result['rows'][0]['lesson_date'] == datetime.date(2026, 3, 9)
    finally:
        _delete_lesson(lesson_id)


def test_list_lessons_invalid_sort_by_falls_back(group_fixture, teacher_id_fixture):
    # Невалидный sort_by → тихий fallback (как Express paginate), без ошибки.
    result = services.create_lesson_full({
        'lesson_date': '2026-03-10',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
    })
    lesson_id = result['lesson_id']
    try:
        list_result = repository.list_lessons(
            sort_by='; DROP TABLE lessons; --',
            filters={'group_id': group_fixture},
        )
        assert list_result['total'] == 1
    finally:
        _delete_lesson(lesson_id)


# ---------------------------------------------------------------------------
# apply_makeup_attendance / revert_makeup_attendance (доп.уроки)
# ---------------------------------------------------------------------------

def test_apply_makeup_attendance_flips_present_and_increments_lessons_done(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-10',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    lesson_id = result['lesson_id']
    try:
        assert lessons_done(group_fixture, student_fixture) == Decimal('0')
        payroll_before = repository.Payroll.objects.get(lesson_id=lesson_id)

        repository.apply_makeup_attendance(lesson_id, student_fixture)

        att = repository.LessonAttendance.objects.get(lesson_id=lesson_id, student_id=student_fixture)
        assert att.present is True
        assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')
        # Payroll исходного урока НЕ пересчитывается доп.уроком.
        payroll_after = repository.Payroll.objects.get(lesson_id=lesson_id)
        assert payroll_after.payment == payroll_before.payment
        assert payroll_after.present_count == payroll_before.present_count
    finally:
        _delete_lesson(lesson_id)


def test_apply_makeup_attendance_is_noop_if_already_present(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-11',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': True}],
    })
    lesson_id = result['lesson_id']
    try:
        assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')
        repository.apply_makeup_attendance(lesson_id, student_fixture)
        # Уже present=True — второй инкремент не происходит (идемпотентно).
        assert lessons_done(group_fixture, student_fixture) == Decimal('1.0')
    finally:
        _delete_lesson(lesson_id)


def test_revert_makeup_attendance_undoes_apply(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-12',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 45,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    lesson_id = result['lesson_id']
    try:
        repository.apply_makeup_attendance(lesson_id, student_fixture)
        assert lessons_done(group_fixture, student_fixture) == Decimal('0.5')

        repository.revert_makeup_attendance(lesson_id, student_fixture)

        att = repository.LessonAttendance.objects.get(lesson_id=lesson_id, student_id=student_fixture)
        assert att.present is False
        assert lessons_done(group_fixture, student_fixture) == Decimal('0')
    finally:
        _delete_lesson(lesson_id)


def test_revert_makeup_attendance_leaves_payroll_unchanged(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-13',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    lesson_id = result['lesson_id']
    try:
        repository.apply_makeup_attendance(lesson_id, student_fixture)
        payroll_before = repository.Payroll.objects.get(lesson_id=lesson_id)

        repository.revert_makeup_attendance(lesson_id, student_fixture)

        # Payroll исходного урока НЕ пересчитывается откатом доп.урока.
        payroll_after = repository.Payroll.objects.get(lesson_id=lesson_id)
        assert payroll_after.payment == payroll_before.payment
        assert payroll_after.present_count == payroll_before.present_count
    finally:
        _delete_lesson(lesson_id)


def test_revert_makeup_attendance_is_noop_if_already_absent(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    result = services.create_lesson_full({
        'lesson_date': '2026-03-14',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [{'student_id': student_fixture, 'present': False}],
    })
    lesson_id = result['lesson_id']
    try:
        assert lessons_done(group_fixture, student_fixture) == Decimal('0')
        repository.revert_makeup_attendance(lesson_id, student_fixture)
        # Уже present=False — декремент ниже уже имеющегося значения не происходит.
        assert lessons_done(group_fixture, student_fixture) == Decimal('0')
    finally:
        _delete_lesson(lesson_id)


def test_apply_and_revert_makeup_attendance_noop_for_missing_lesson(student_fixture):
    # lesson_id не существует → ctx is None → return, без исключений.
    assert repository.apply_makeup_attendance(999_999_999, student_fixture) is None
    assert repository.revert_makeup_attendance(999_999_999, student_fixture) is None


def test_apply_makeup_attendance_noop_if_no_attendance_row(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lessons_done
):
    # Урок существует, но у студента вообще нет строки attendance (пустой
    # attendance при создании) — updated=0, silent no-op (нет INSERT-ветки).
    result = services.create_lesson_full({
        'lesson_date': '2026-03-15',
        'group_id': group_fixture,
        'teacher_id': teacher_id_fixture,
        'lesson_number': 1,
        'lesson_duration_minutes': 60,
        'attendance': [],
    })
    lesson_id = result['lesson_id']
    try:
        repository.apply_makeup_attendance(lesson_id, student_fixture)
        assert lessons_done(group_fixture, student_fixture) == Decimal('0')
        assert not repository.LessonAttendance.objects.filter(
            lesson_id=lesson_id, student_id=student_fixture,
        ).exists()
    finally:
        _delete_lesson(lesson_id)
