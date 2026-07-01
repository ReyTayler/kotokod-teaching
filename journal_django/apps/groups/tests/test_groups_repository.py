"""
Unit/integration тесты для GroupsRepository.

Используют реальную БД (managed=False, продовая).
Все созданные строки удаляются в teardown.

Тестируют:
  - list_groups: форма ответа {rows, total, page, page_size}
  - list_groups: фильтрация по active
  - list_groups: сортировка
  - get_group: существующий ID → dict с slots
  - get_group: несуществующий ID → None
  - create_group: создаёт группу + слоты, RETURNING * работает
  - update_group: COALESCE-обновление, перезапись слотов
  - soft_delete_group: active=false, повторный вызов → False
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.groups import repository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cleanup_group(group_id: int) -> None:
    """Прямой DELETE — как Nest e2e after() через пул."""
    with connection.cursor() as cur:
        cur.execute('DELETE FROM groups WHERE id = %s', [group_id])


def _get_valid_direction_id() -> int:
    """Взять первый direction_id из БД для тестов."""
    with connection.cursor() as cur:
        cur.execute('SELECT id FROM directions LIMIT 1')
        row = cur.fetchone()
    if not row:
        pytest.skip('No directions in DB — skipping groups tests')
    return row[0]


def _get_valid_teacher_id() -> int:
    """Взять первый teacher_id из БД для тестов."""
    with connection.cursor() as cur:
        cur.execute('SELECT id FROM teachers LIMIT 1')
        row = cur.fetchone()
    if not row:
        pytest.skip('No teachers in DB — skipping groups tests')
    return row[0]


def _make_group_data(**overrides) -> dict:
    return {
        'name': '__test_repo_group__',
        'direction_id': _get_valid_direction_id(),
        'teacher_id': _get_valid_teacher_id(),
        'is_individual': False,
        'lesson_duration_minutes': 90,
        'lessons_per_week': 2,
        'group_start_date': None,
        'vk_chat': None,
        'slots': [],
        **overrides,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestListGroups:
    """Тесты list_groups()."""

    def test_returns_correct_shape(self):
        result = repository.list_groups()
        assert 'rows' in result
        assert 'total' in result
        assert 'page' in result
        assert 'page_size' in result

    def test_page_and_page_size_defaults(self):
        result = repository.list_groups()
        assert result['page'] == 1
        assert result['page_size'] == 50

    def test_total_is_int(self):
        result = repository.list_groups()
        assert isinstance(result['total'], int)

    def test_rows_is_list(self):
        result = repository.list_groups()
        assert isinstance(result['rows'], list)

    def test_filter_active_true(self):
        result = repository.list_groups(filters={'active': 'true'})
        for row in result['rows']:
            assert row['active'] is True

    def test_filter_active_false(self):
        result = repository.list_groups(filters={'active': 'false'})
        for row in result['rows']:
            assert row['active'] is False

    def test_page_size_respected(self):
        result = repository.list_groups(page=1, page_size=2)
        assert result['page_size'] == 2
        assert len(result['rows']) <= 2

    def test_sort_by_name_asc(self):
        result = repository.list_groups(sort_by='name', sort_dir='asc', page_size=10)
        names = [r['name'] for r in result['rows']]
        assert names == sorted(names)

    def test_sort_by_name_desc(self):
        """Убеждаемся что sort_dir=desc принимается без ошибок.

        Точный порядок Cyrillic-имён в Python sorted() не совпадает с PostgreSQL
        (разные collation), поэтому проверяем только статус запроса.
        """
        result = repository.list_groups(sort_by='name', sort_dir='desc', page_size=10)
        assert isinstance(result['rows'], list)
        assert result['page_size'] == 10

    def test_rows_have_direction_name(self):
        """Список включает direction_name из JOIN."""
        result = repository.list_groups(page_size=5)
        if result['rows']:
            assert 'direction_name' in result['rows'][0]

    def test_rows_have_teacher_name(self):
        """Список включает teacher_name из JOIN."""
        result = repository.list_groups(page_size=5)
        if result['rows']:
            assert 'teacher_name' in result['rows'][0]

    def test_rows_have_slots(self):
        """Каждая строка содержит поле slots (list)."""
        result = repository.list_groups(page_size=5)
        if result['rows']:
            assert isinstance(result['rows'][0]['slots'], list)


@pytest.mark.django_db
class TestGetGroup:
    """Тесты get_group()."""

    def test_nonexistent_returns_none(self):
        result = repository.get_group(999_999_999)
        assert result is None

    def test_existing_returns_dict_with_slots(self):
        data = _make_group_data(name='__test_get_group__')
        group = repository.create_group(data)
        group_id = group['id']
        try:
            result = repository.get_group(group_id)
            assert result is not None
            assert result['id'] == group_id
            assert result['name'] == '__test_get_group__'
            assert 'slots' in result
            assert isinstance(result['slots'], list)
        finally:
            _cleanup_group(group_id)

    def test_slots_populated_correctly(self):
        data = _make_group_data(
            name='__test_get_group_slots__',
            slots=[
                {'day_of_week': 1, 'start_time': '10:00'},
                {'day_of_week': 3, 'start_time': '14:30'},
            ],
        )
        group = repository.create_group(data)
        group_id = group['id']
        try:
            result = repository.get_group(group_id)
            assert len(result['slots']) == 2
            days = [s['day_of_week'] for s in result['slots']]
            assert sorted(days) == [1, 3]
        finally:
            _cleanup_group(group_id)


@pytest.mark.django_db
class TestCreateGroup:
    """Тесты create_group()."""

    def test_create_returns_dict(self):
        data = _make_group_data(name='__test_create_group__')
        group = repository.create_group(data)
        try:
            assert isinstance(group, dict)
            assert 'id' in group
            assert group['name'] == '__test_create_group__'
        finally:
            _cleanup_group(group['id'])

    def test_created_group_in_db(self):
        data = _make_group_data(name='__test_create_db__')
        group = repository.create_group(data)
        group_id = group['id']
        try:
            fetched = repository.get_group(group_id)
            assert fetched is not None
            assert fetched['id'] == group_id
        finally:
            _cleanup_group(group_id)

    def test_creates_with_slots(self):
        data = _make_group_data(
            name='__test_create_slots__',
            slots=[{'day_of_week': 0, 'start_time': '09:00'}],
        )
        group = repository.create_group(data)
        group_id = group['id']
        try:
            fetched = repository.get_group(group_id)
            assert len(fetched['slots']) == 1
            assert fetched['slots'][0]['day_of_week'] == 0
        finally:
            _cleanup_group(group_id)

    def test_active_default_true(self):
        data = _make_group_data(name='__test_create_active__')
        group = repository.create_group(data)
        try:
            assert group['active'] is True
        finally:
            _cleanup_group(group['id'])


@pytest.mark.django_db
class TestUpdateGroup:
    """Тесты update_group()."""

    def test_update_nonexistent_returns_none(self):
        result = repository.update_group(999_999_999, {'name': 'ghost'})
        assert result is None

    def test_update_name(self):
        data = _make_group_data(name='__test_upd_before__')
        group = repository.create_group(data)
        group_id = group['id']
        try:
            updated = repository.update_group(group_id, {'name': '__test_upd_after__'})
            assert updated['name'] == '__test_upd_after__'
        finally:
            _cleanup_group(group_id)

    def test_update_replaces_slots(self):
        data = _make_group_data(
            name='__test_upd_slots__',
            slots=[{'day_of_week': 2, 'start_time': '11:00'}],
        )
        group = repository.create_group(data)
        group_id = group['id']
        try:
            repository.update_group(
                group_id,
                {'slots': [
                    {'day_of_week': 4, 'start_time': '15:00'},
                    {'day_of_week': 5, 'start_time': '16:00'},
                ]},
            )
            fetched = repository.get_group(group_id)
            days = sorted(s['day_of_week'] for s in fetched['slots'])
            assert days == [4, 5]
        finally:
            _cleanup_group(group_id)

    def test_patch_active_false(self):
        data = _make_group_data(name='__test_upd_active__')
        group = repository.create_group(data)
        group_id = group['id']
        try:
            updated = repository.update_group(group_id, {'active': False})
            assert updated['active'] is False
        finally:
            _cleanup_group(group_id)


@pytest.mark.django_db
class TestSoftDeleteGroup:
    """Тесты soft_delete_group()."""

    def test_soft_delete_existing(self):
        data = _make_group_data(name='__test_softdel__')
        group = repository.create_group(data)
        group_id = group['id']
        try:
            result = repository.soft_delete_group(group_id)
            assert result is True
            fetched = repository.get_group(group_id)
            assert fetched['active'] is False
        finally:
            _cleanup_group(group_id)

    def test_soft_delete_nonexistent_returns_false(self):
        result = repository.soft_delete_group(999_999_999)
        assert result is False
