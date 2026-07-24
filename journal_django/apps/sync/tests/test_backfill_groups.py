# journal_django/apps/sync/tests/test_backfill_groups.py
import pytest
from django.db import connection

from apps.sync.backfills import groups


def _row(teacher, group, vk='', direction='Python', start=''):
    row = [''] * 19
    row[11] = teacher
    row[12] = group
    row[13] = start
    row[15] = vk
    row[18] = direction
    return row


def test_extract_groups_basic():
    rows = [_row('Петрова', 'Группа Пн 18:00', direction='Python')]
    result = groups.extract_groups(rows)
    assert len(result) == 1
    g = result[0]
    assert g['name'] == 'Группа Пн 18:00'
    assert g['teacher_name'] == 'Петрова'
    assert g['direction_name'] == 'Python'
    assert g['is_individual'] is False
    assert g['slots'] == [{'day_of_week': 1, 'start_time': '18:00:00'}]


def test_extract_groups_individual():
    rows = [_row('Петрова', 'Иванов Инд', direction='Python ИНДИВ')]
    result = groups.extract_groups(rows)
    assert result[0]['is_individual'] is True


def test_extract_groups_dedupes_by_name_and_backfills_start_date():
    rows = [
        _row('Петрова', 'Группа A', direction='Python', start=''),
        _row('Петрова', 'Группа A', direction='Python', start='01.09.2025'),
    ]
    result = groups.extract_groups(rows)
    assert len(result) == 1
    assert result[0]['group_start_date'] == '2025-09-01'


def test_extract_groups_skips_uchenika_net():
    rows = [_row('УЧЕНИКА НЕТ', 'Группа A')]
    assert groups.extract_groups(rows) == []


@pytest.mark.django_db
def test_run_inserts_group_and_slots(monkeypatch):
    direction_name = '__test_sync_direction_g__'
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_g__') RETURNING id")
        cur.execute(
            "INSERT INTO directions (name) VALUES (%s)",
            [direction_name],
        )

    rows = [_row('__test_sync_teacher_g__', '__test_sync_group__ Пн 18:00', direction=direction_name)]
    monkeypatch.setattr(groups.sheets_client, 'read_students_range', lambda *a: rows)

    try:
        result = groups.run(dry_run=False)
        assert result['read'] == 1
        assert result['inserted'] == 1
        assert result['slots_replaced'] == 1
        with connection.cursor() as cur:
            cur.execute("SELECT id FROM groups WHERE name = %s", ['__test_sync_group__ Пн 18:00'])
            group_row = cur.fetchone()
            assert group_row is not None
            cur.execute("SELECT COUNT(*) FROM group_schedule_slots WHERE group_id = %s", [group_row[0]])
            assert cur.fetchone()[0] == 1
    finally:
        # group_schedule_slots.group_id FK в тестовой БД создаётся Django-миграцией
        # apps/groups/migrations/0001_initial.py и физически является DEFERRABLE
        # INITIALLY DEFERRED БЕЗ ON DELETE CASCADE на уровне БД (models.CASCADE
        # эмулируется Django ORM в Python, а не DDL-констрейнтом) — поэтому явно
        # удаляем слоты, иначе deferred constraint check упадёт на orphaned-строке
        # после DELETE FROM groups. (В боевой БД, поднятой из исходной сырой SQL-
        # миграции db/migrations/001_initial_schema.sql, у этой же колонки
        # настоящий ON DELETE CASCADE — тестовая БД строится иначе, через
        # Django migrate, и потому имеет другую физическую схему constraint'а.)
        with connection.cursor() as cur:
            cur.execute(
                "DELETE FROM group_schedule_slots WHERE group_id IN "
                "(SELECT id FROM groups WHERE name = '__test_sync_group__ Пн 18:00')"
            )
            cur.execute("DELETE FROM groups WHERE name = '__test_sync_group__ Пн 18:00'")
            cur.execute("DELETE FROM teachers WHERE name = '__test_sync_teacher_g__'")
            cur.execute("DELETE FROM directions WHERE name = %s", [direction_name])


@pytest.mark.django_db
def test_run_twice_skips_unchanged_slots(monkeypatch):
    direction_name = '__test_sync_direction_g2__'
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__test_sync_teacher_g2__') RETURNING id")
        cur.execute(
            "INSERT INTO directions (name) VALUES (%s)",
            [direction_name],
        )

    rows = [_row('__test_sync_teacher_g2__', '__test_sync_group2__ Пн 18:00', direction=direction_name)]
    monkeypatch.setattr(groups.sheets_client, 'read_students_range', lambda *a: rows)

    try:
        first = groups.run(dry_run=False)
        assert first['slots_replaced'] >= 1

        second = groups.run(dry_run=False)
        assert second['slots_replaced'] == 0
    finally:
        with connection.cursor() as cur:
            cur.execute(
                "DELETE FROM group_schedule_slots WHERE group_id IN "
                "(SELECT id FROM groups WHERE name = '__test_sync_group2__ Пн 18:00')"
            )
            cur.execute("DELETE FROM groups WHERE name = '__test_sync_group2__ Пн 18:00'")
            cur.execute("DELETE FROM teachers WHERE name = '__test_sync_teacher_g2__'")
            cur.execute("DELETE FROM directions WHERE name = %s", [direction_name])


@pytest.mark.django_db
def test_run_dry_run_does_not_write(monkeypatch):
    rows = [_row('Несуществующий', '__test_sync_group_dry__', direction='Python')]
    monkeypatch.setattr(groups.sheets_client, 'read_students_range', lambda *a: rows)

    result = groups.run(dry_run=True)
    assert result['read'] == 1
    assert result['dry_run'] is True
    with connection.cursor() as cur:
        cur.execute("SELECT id FROM groups WHERE name = '__test_sync_group_dry__'")
        assert cur.fetchone() is None
