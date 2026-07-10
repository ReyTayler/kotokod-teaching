"""
Unit/integration тесты для StudentsRepository.

Используют реальную БД (managed=False, продовая).
Все созданные строки удаляются в teardown.

Тестируют:
  - list_students: форма ответа {rows, total, page, page_size}
  - list_students: фильтры, сортировка
  - get_student: существующий/несуществующий
  - create_student: RETURNING * работает, поля заполнены
  - update_student: COALESCE обновление, frozen_until_month может стать NULL
  - soft_delete_student: статус 'not_enrolled', frozen_until_month=NULL, повторный → False
  - student_stats: форма ответа (keys: student_id, directions, groups, overall)
  - get_student_balance: форма ответа (keys: paid_by_direction, attended_by_direction, total_balance, total_paid_amount, payments)
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.students import repository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cleanup_student(student_id: int) -> None:
    """Прямой DELETE — как Nest e2e after() через пул."""
    with connection.cursor() as cur:
        cur.execute('DELETE FROM students WHERE id = %s', [student_id])


def _make_student_data(**overrides) -> dict:
    return {
        'full_name': '__test_repo_student__',
        'birth_date': None,
        'platform_id': None,
        'bitrix24_link': None,
        'parent1_name': None,
        'parent1_phone': None,
        'parent1_email': None,
        'parent2_name': None,
        'parent2_phone': None,
        'parent2_email': None,
        'first_purchase_date': None,
        'age': None,
        'pm': None,
        'enrollment_status': 'enrolled',
        'frozen_until_month': None,
        **overrides,
    }


# ---------------------------------------------------------------------------
# TestListStudents
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestListStudents:
    """Тесты list_students()."""

    def test_returns_correct_shape(self):
        result = repository.list_students()
        assert 'rows' in result
        assert 'total' in result
        assert 'page' in result
        assert 'page_size' in result

    def test_page_and_page_size_defaults(self):
        result = repository.list_students()
        assert result['page'] == 1
        assert result['page_size'] == 50

    def test_total_is_int(self):
        result = repository.list_students()
        assert isinstance(result['total'], int)

    def test_rows_is_list(self):
        result = repository.list_students()
        assert isinstance(result['rows'], list)

    def test_page_size_respected(self):
        result = repository.list_students(page=1, page_size=2)
        assert result['page_size'] == 2
        assert len(result['rows']) <= 2

    def test_filter_enrollment_status(self):
        """Фильтр по enrollment_status возвращает только нужный статус."""
        result = repository.list_students(filters={'enrollment_status': 'enrolled'})
        for row in result['rows']:
            assert row['enrollment_status'] == 'enrolled'

    def test_filter_full_name_no_match(self):
        """Несуществующее имя → пустой список."""
        result = repository.list_students(
            filters={'full_name': '__nonexistent_xyz_student_filter__'}
        )
        assert result['rows'] == []

    def test_sort_by_full_name_asc(self):
        """sort_by=full_name&sort_dir=asc принимается без ошибок."""
        result = repository.list_students(sort_by='full_name', sort_dir='asc', page_size=5)
        assert isinstance(result['rows'], list)

    def test_sort_by_created_at_desc(self):
        """sort_by=created_at&sort_dir=desc принимается без ошибок."""
        result = repository.list_students(sort_by='created_at', sort_dir='desc', page_size=5)
        assert isinstance(result['rows'], list)

    def test_sort_by_id_asc(self):
        result = repository.list_students(sort_by='id', sort_dir='asc', page_size=5)
        assert isinstance(result['rows'], list)


# ---------------------------------------------------------------------------
# TestGetStudent
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGetStudent:
    """Тесты get_student()."""

    def test_nonexistent_returns_none(self):
        result = repository.get_student(999_999_999)
        assert result is None

    def test_existing_returns_dict(self):
        data = _make_student_data(full_name='__test_get_student__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            result = repository.get_student(sid)
            assert result is not None
            assert result['id'] == sid
            assert result['full_name'] == '__test_get_student__'
        finally:
            _cleanup_student(sid)

    def test_existing_has_required_fields(self):
        data = _make_student_data(full_name='__test_get_fields__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            result = repository.get_student(sid)
            for field in ['id', 'full_name', 'enrollment_status', 'created_at']:
                assert field in result
        finally:
            _cleanup_student(sid)


# ---------------------------------------------------------------------------
# TestCreateStudent
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCreateStudent:
    """Тесты create_student()."""

    def test_create_returns_dict(self):
        data = _make_student_data(full_name='__test_create_student__')
        student = repository.create_student(data)
        try:
            assert isinstance(student, dict)
            assert 'id' in student
            assert student['full_name'] == '__test_create_student__'
        finally:
            _cleanup_student(student['id'])

    def test_created_student_in_db(self):
        data = _make_student_data(full_name='__test_create_db__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            fetched = repository.get_student(sid)
            assert fetched is not None
            assert fetched['id'] == sid
        finally:
            _cleanup_student(sid)

    def test_enrollment_status_default_enrolled(self):
        """Без enrollment_status — дефолт 'enrolled' (COALESCE в SQL)."""
        data = {'full_name': '__test_create_default_status__'}
        student = repository.create_student(data)
        try:
            assert student['enrollment_status'] == 'enrolled'
        finally:
            _cleanup_student(student['id'])

    def test_create_with_parent_contacts_and_age(self):
        data = _make_student_data(
            full_name='__test_create_full__',
            parent1_name='Иван Петров',
            parent1_phone='+79001234567',
            parent1_email='parent1@example.com',
            parent2_name='Мария Петрова',
            parent2_phone='+79007654321',
            parent2_email='parent2@example.com',
            bitrix24_link='https://bitrix24.example/crm/deal/1',
            age=11,
        )
        student = repository.create_student(data)
        try:
            assert student['parent1_name'] == 'Иван Петров'
            assert student['parent1_phone'] == '+79001234567'
            assert student['parent1_email'] == 'parent1@example.com'
            assert student['parent2_name'] == 'Мария Петрова'
            assert student['parent2_phone'] == '+79007654321'
            assert student['parent2_email'] == 'parent2@example.com'
            assert student['bitrix24_link'] == 'https://bitrix24.example/crm/deal/1'
            assert student['age'] == 11
        finally:
            _cleanup_student(student['id'])

    def test_create_frozen_with_month(self):
        data = _make_student_data(
            full_name='__test_create_frozen__',
            enrollment_status='frozen',
            frozen_until_month=3,
        )
        student = repository.create_student(data)
        try:
            assert student['enrollment_status'] == 'frozen'
            assert student['frozen_until_month'] == 3
        finally:
            _cleanup_student(student['id'])


# ---------------------------------------------------------------------------
# TestUpdateStudent
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestUpdateStudent:
    """Тесты update_student()."""

    def test_update_nonexistent_returns_none(self):
        result = repository.update_student(999_999_999, {'full_name': 'ghost'})
        assert result is None

    def test_update_full_name(self):
        data = _make_student_data(full_name='__test_upd_before__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            updated = repository.update_student(sid, {'full_name': '__test_upd_after__'})
            assert updated['full_name'] == '__test_upd_after__'
        finally:
            _cleanup_student(sid)

    def test_update_coalesce_keeps_old_values(self):
        """Если поля не переданы — старые значения сохраняются."""
        data = _make_student_data(
            full_name='__test_coalesce__',
            age=13,
        )
        student = repository.create_student(data)
        sid = student['id']
        try:
            updated = repository.update_student(sid, {'full_name': '__test_coalesce_new__'})
            assert updated['age'] == 13
        finally:
            _cleanup_student(sid)

    def test_update_frozen_until_month_to_none(self):
        """
        frozen_until_month сбрасывается в NULL вместе со сменой статуса.

        БД-CHECK: (enrollment_status = 'frozen') = (frozen_until_month IS NOT NULL).
        Нельзя обнулить месяц, не убрав статус 'frozen' одновременно.
        JS updateStudent тоже передаёт оба поля при разморозке.
        """
        data = _make_student_data(
            full_name='__test_upd_frozen__',
            enrollment_status='frozen',
            frozen_until_month=5,
        )
        student = repository.create_student(data)
        sid = student['id']
        try:
            # Сброс: передаём и enrollment_status и frozen_until_month=None
            updated = repository.update_student(
                sid,
                {'enrollment_status': 'enrolled', 'frozen_until_month': None},
            )
            assert updated['frozen_until_month'] is None
            assert updated['enrollment_status'] == 'enrolled'
        finally:
            _cleanup_student(sid)

    def test_update_enrollment_status(self):
        data = _make_student_data(full_name='__test_upd_status__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            updated = repository.update_student(sid, {'enrollment_status': 'not_enrolled'})
            assert updated['enrollment_status'] == 'not_enrolled'
        finally:
            _cleanup_student(sid)


# ---------------------------------------------------------------------------
# TestSoftDeleteStudent
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSoftDeleteStudent:
    """Тесты soft_delete_student()."""

    def test_soft_delete_existing_returns_true(self):
        data = _make_student_data(full_name='__test_softdel__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            result = repository.soft_delete_student(sid)
            assert result is True
        finally:
            _cleanup_student(sid)

    def test_soft_delete_sets_not_enrolled(self):
        data = _make_student_data(full_name='__test_softdel_status__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            repository.soft_delete_student(sid)
            fetched = repository.get_student(sid)
            assert fetched['enrollment_status'] == 'not_enrolled'
        finally:
            _cleanup_student(sid)

    def test_soft_delete_clears_frozen_until_month(self):
        """soft_delete сбрасывает frozen_until_month в NULL."""
        data = _make_student_data(
            full_name='__test_softdel_frozen__',
            enrollment_status='frozen',
            frozen_until_month=6,
        )
        student = repository.create_student(data)
        sid = student['id']
        try:
            repository.soft_delete_student(sid)
            fetched = repository.get_student(sid)
            assert fetched['frozen_until_month'] is None
        finally:
            _cleanup_student(sid)

    def test_soft_delete_nonexistent_returns_false(self):
        result = repository.soft_delete_student(999_999_999)
        assert result is False


# ---------------------------------------------------------------------------
# TestStudentStats
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestStudentStats:
    """Тесты student_stats() — форма ответа."""

    def test_shape_for_new_student(self):
        """Ученик без посещений — структура ответа корректная."""
        data = _make_student_data(full_name='__test_stats_shape__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            result = repository.student_stats(sid)
            assert 'student_id' in result
            assert 'directions' in result
            assert 'groups' in result
            assert 'overall' in result
            assert result['student_id'] == sid
            assert isinstance(result['directions'], list)
            assert isinstance(result['groups'], list)
        finally:
            _cleanup_student(sid)

    def test_overall_shape(self):
        """overall содержит нужные ключи."""
        data = _make_student_data(full_name='__test_stats_overall__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            result = repository.student_stats(sid)
            overall = result['overall']
            for key in [
                'lessons_recorded', 'attended_count', 'missed_count',
                'denominator', 'attendance_pct', 'this_month',
            ]:
                assert key in overall, f"Missing key '{key}' in overall"
            assert 'lessons_recorded' in overall['this_month']
            assert 'attended_count' in overall['this_month']
            assert 'attendance_pct' in overall['this_month']
        finally:
            _cleanup_student(sid)

    def test_empty_stats_for_new_student(self):
        """Новый ученик без групп — нули в overall."""
        data = _make_student_data(full_name='__test_stats_zeros__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            result = repository.student_stats(sid)
            assert result['overall']['lessons_recorded'] == 0
            assert result['overall']['attended_count'] == 0
            assert result['overall']['missed_count'] == 0
            assert result['overall']['denominator'] == 0
            assert result['overall']['attendance_pct'] is None
            assert result['directions'] == []
            assert result['groups'] == []
        finally:
            _cleanup_student(sid)


# ---------------------------------------------------------------------------
# TestStudentStatsRemaining
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestStudentStatsRemaining:
    """remaining в group_stats — вычисляемый общий баланс ученика (не колонка gm.remaining)."""

    def test_group_remaining_matches_balance_for_student(self):
        from apps.finances.repository import balance_for_student

        data = _make_student_data(full_name='__test_stats_remaining__')
        student = repository.create_student(data)
        sid = student['id']
        direction_id = group_id = teacher_id = None
        try:
            with connection.cursor() as cur:
                cur.execute(
                    "INSERT INTO teachers (name, active) VALUES ('__stats_rem_teacher__', true) "
                    "RETURNING id"
                )
                teacher_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO directions (name, is_individual, active) "
                    "VALUES ('__stats_rem_dir__', false, true) RETURNING id"
                )
                direction_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
                    "lesson_duration_minutes, active) "
                    "VALUES ('__stats_rem_group__', %s, %s, false, 60, true) RETURNING id",
                    [direction_id, teacher_id],
                )
                group_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                    "VALUES (%s, %s, 0, true)",
                    [group_id, sid],
                )
                cur.execute(
                    "INSERT INTO payments (student_id, direction_id, subscriptions_count, "
                    "lessons_count, unit_price, total_amount, paid_at, created_by) "
                    "VALUES (%s,%s,1,4,2000,2000,'2026-06-01','test')",
                    [sid, direction_id],
                )

            result = repository.student_stats(sid)
            assert len(result['groups']) == 1
            assert result['groups'][0]['remaining'] == balance_for_student(sid) == 4
        finally:
            with connection.cursor() as cur:
                if group_id is not None:
                    cur.execute('DELETE FROM payments WHERE student_id = %s', [sid])
                    cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [group_id])
                    cur.execute('DELETE FROM groups WHERE id = %s', [group_id])
                if direction_id is not None:
                    cur.execute('DELETE FROM directions WHERE id = %s', [direction_id])
                if teacher_id is not None:
                    cur.execute('DELETE FROM teachers WHERE id = %s', [teacher_id])
            _cleanup_student(sid)


# ---------------------------------------------------------------------------
# TestGetStudentBalance
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGetStudentBalance:
    """Тесты get_student_balance() — форма ответа. Постоянный дом — apps/finances/."""

    def test_shape_for_new_student(self):
        """Ученик без оплат — структура ответа корректная."""
        from apps.payments import repository as payments_repo
        data = _make_student_data(full_name='__test_balance_shape__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            result = payments_repo.get_student_balance(sid)
            assert 'paid_by_direction' in result
            assert 'attended_by_direction' in result
            assert 'total_balance' in result
            assert 'total_paid_amount' in result
            assert 'payments' in result
            assert isinstance(result['paid_by_direction'], list)
            assert isinstance(result['attended_by_direction'], list)
            assert isinstance(result['payments'], list)
        finally:
            _cleanup_student(sid)

    def test_zero_balance_for_new_student(self):
        """Ученик без оплат — нулевые балансы."""
        from apps.payments import repository as payments_repo
        data = _make_student_data(full_name='__test_balance_zeros__')
        student = repository.create_student(data)
        sid = student['id']
        try:
            result = payments_repo.get_student_balance(sid)
            assert result['total_balance'] == 0
            assert result['total_paid_amount'] == 0
            assert result['paid_by_direction'] == []
            assert result['attended_by_direction'] == []
            assert result['payments'] == []
        finally:
            _cleanup_student(sid)

    def test_paid_by_direction_shape(self):
        """Если есть оплаты — paid_by_direction содержит нужные ключи."""
        from apps.payments import repository as payments_repo
        with connection.cursor() as cur:
            cur.execute('SELECT student_id FROM payments WHERE direction_id IS NOT NULL LIMIT 1')
            row = cur.fetchone()
        if not row:
            pytest.skip('No payments in DB — skipping paid_by_direction shape test')

        result = payments_repo.get_student_balance(row[0])
        if result['paid_by_direction']:
            d = result['paid_by_direction'][0]
            for key in ['direction_id', 'direction_name', 'direction_color', 'total_paid_amount']:
                assert key in d, f"Missing key '{key}' in paid_by_direction item"

    def test_attended_by_direction_shape(self):
        """Если есть посещения — attended_by_direction содержит нужные ключи."""
        from apps.payments import repository as payments_repo
        with connection.cursor() as cur:
            cur.execute('SELECT student_id FROM lesson_attendance WHERE present = true LIMIT 1')
            row = cur.fetchone()
        if not row:
            pytest.skip('No attendance in DB — skipping attended_by_direction shape test')

        result = payments_repo.get_student_balance(row[0])
        if result['attended_by_direction']:
            d = result['attended_by_direction'][0]
            for key in ['direction_id', 'direction_name', 'direction_color', 'attended_lessons']:
                assert key in d, f"Missing key '{key}' in attended_by_direction item"
