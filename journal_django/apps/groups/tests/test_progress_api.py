"""
API-тесты обзорной матрицы посещаемости:
  GET /api/admin/groups/:id/progress

Права: IsManagerOrAdmin. Аутентификация — JWT (клиенты из conftest).

Проверяем:
  - RBAC (anon 401 / teacher 403 / manager 200);
  - 404 для несуществующей группы;
  - контракт ответа (slots/students + счётчики);
  - слоты доводятся до direction.total_lessons (плановые уроки видны);
  - ячейки: True=был, False=не был, None=не проведён / не в составе;
  - N+1: не более 3 запросов данных на всю матрицу.
"""
from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

pytestmark = pytest.mark.django_db


@pytest.fixture
def progress_group():
    """
    Группа (direction.total_lessons=8) + 2 ученика + 2 проведённых урока
    (№1, №2) с посещаемостью. Возвращает dict с id-шниками для ассертов.

    Урок 1: Аня был, Боря не был.  Урок 2: Аня был, Боря был.
    Боре запись на урок 1 создаём как present=false (в составе, но не был).
    """
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name, active) VALUES ('__pg_t__', true) RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO directions (name,is_individual,total_lessons,active) "
            "VALUES ('__pg_d__',false,8,true) RETURNING id"
        )
        direction_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name,direction_id,teacher_id,is_individual,lesson_duration_minutes,active) "
            "VALUES ('__pg_g__',%s,%s,false,60,true) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]

        # 'Аня' сортируется раньше 'Боря' (порядок строк по имени).
        cur.execute("INSERT INTO students (full_name, enrollment_status) VALUES ('__pg Аня__','enrolled') RETURNING id")
        anya = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name, enrollment_status) VALUES ('__pg Боря__','enrolled') RETURNING id")
        borya = cur.fetchone()[0]
        for sid in (anya, borya):
            cur.execute(
                "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) VALUES (%s,%s,0,true)",
                [group_id, sid],
            )

        lesson_ids = []
        for num, date in ((1, '2026-03-02'), (2, '2026-03-05')):
            cur.execute(
                "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
                "lesson_duration_minutes, lesson_type, submitted_by_token) "
                "VALUES (%s,%s,%s,%s,60,'regular','test') RETURNING id",
                [group_id, teacher_id, date, num],
            )
            lesson_ids.append(cur.fetchone()[0])

        att = [
            (lesson_ids[0], anya, True), (lesson_ids[0], borya, False),
            (lesson_ids[1], anya, True), (lesson_ids[1], borya, True),
        ]
        for lid, sid, present in att:
            cur.execute(
                "INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s,%s,%s)",
                [lid, sid, present],
            )

    yield {'group_id': group_id, 'anya': anya, 'borya': borya, 'lesson_ids': lesson_ids}

    with connection.cursor() as cur:
        cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = ANY(%s)', [lesson_ids])
        cur.execute('DELETE FROM lessons WHERE group_id = %s', [group_id])
        cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [group_id])
        cur.execute('DELETE FROM groups WHERE id = %s', [group_id])
        cur.execute('DELETE FROM students WHERE id = ANY(%s)', [[anya, borya]])
        cur.execute('DELETE FROM directions WHERE id = %s', [direction_id])
        cur.execute('DELETE FROM teachers WHERE id = %s', [teacher_id])


def _url(gid: int) -> str:
    return f'/api/admin/groups/{gid}/progress'


class TestAuth:
    def test_anon_401(self, anon_client, progress_group):
        assert anon_client.get(_url(progress_group['group_id'])).status_code == 401

    def test_teacher_403(self, teacher_client, progress_group):
        assert teacher_client.get(_url(progress_group['group_id'])).status_code == 403

    @pytest.mark.parametrize('client_fixture', ['manager_client', 'admin_client'])
    def test_staff_200(self, request, client_fixture, progress_group):
        client = request.getfixturevalue(client_fixture)
        assert client.get(_url(progress_group['group_id'])).status_code == 200


def test_404_for_missing_group(manager_client):
    resp = manager_client.get(_url(999999999))
    assert resp.status_code == 404
    assert resp.json() == {'error': 'Not found'}


class TestContract:
    def test_slots_extend_to_total_lessons(self, manager_client, progress_group):
        body = manager_client.get(_url(progress_group['group_id'])).json()
        # direction.total_lessons=8 → 8 слотов, из них 2 проведено.
        assert body['total_slots'] == 8
        assert body['held_slots'] == 2
        assert len(body['slots']) == 8
        assert [s['held'] for s in body['slots']] == [True, True] + [False] * 6
        # Плановые слоты — без урока/даты.
        assert body['slots'][2]['lesson_id'] is None
        assert body['slots'][2]['date'] is None
        # DATE-инвариант: дата строкой без сдвига.
        assert body['slots'][0]['date'] == '2026-03-02'

    def test_student_rows_and_cells(self, manager_client, progress_group):
        body = manager_client.get(_url(progress_group['group_id'])).json()
        rows = {r['student_id']: r for r in body['students']}

        anya = rows[progress_group['anya']]
        # Аня: был на обоих проведённых → 2/2 = 100%.
        assert anya['present'] == 2
        assert anya['held'] == 2
        assert anya['pct'] == 100
        # cells выровнены по слотам: был, был, затем None по плановым.
        assert anya['cells'][:2] == [True, True]
        assert anya['cells'][2:] == [None] * 6

        borya = rows[progress_group['borya']]
        # Боря: не был на 1, был на 2 → 1/2 = 50%.
        assert borya['present'] == 1
        assert borya['held'] == 2
        assert borya['pct'] == 50
        assert borya['cells'][:2] == [False, True]

    def test_inactive_members_excluded(self, manager_client, progress_group):
        # Выбывший ученик (membership active=false) не должен быть строкой матрицы.
        gid = progress_group['group_id']
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO students (full_name, enrollment_status) "
                "VALUES ('__pg Выбывший__','enrolled') RETURNING id"
            )
            gone = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                "VALUES (%s,%s,0,false)",
                [gid, gone],
            )
        try:
            body = manager_client.get(_url(gid)).json()
            ids = {r['student_id'] for r in body['students']}
            assert gone not in ids
            assert ids == {progress_group['anya'], progress_group['borya']}
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM group_memberships WHERE student_id = %s', [gone])
                cur.execute('DELETE FROM students WHERE id = %s', [gone])

    def test_no_n_plus_one(self, manager_client, progress_group):
        # Матрица считается ≤3 запросами данных (участники + уроки + посещаемость).
        # Прогреваем кэш аутентификации/аккаунта отдельным запросом.
        manager_client.get(_url(progress_group['group_id']))
        with CaptureQueriesContext(connection) as ctx:
            resp = manager_client.get(_url(progress_group['group_id']))
        assert resp.status_code == 200
        data_queries = [
            q for q in ctx.captured_queries
            if any(t in q['sql'] for t in ('group_memberships', 'lessons', 'lesson_attendance', 'groups'))
        ]
        assert len(data_queries) <= 4  # 3 данные + возможный lookup группы/direction


class TestTransferredLessons:
    """transferred_lessons/transferred_from_group_name в ответе матрицы."""

    def test_transferred_student_gets_capped_count(self, manager_client, progress_group):
        """
        Боря переведён из архивной группы того же направления, где отработал
        5 уроков (direction.total_lessons=8 в фикстуре progress_group) —
        transferred_lessons должен быть 5 (меньше total_slots=8, не капается).
        """
        gid = progress_group['group_id']
        with connection.cursor() as cur:
            cur.execute(
                "SELECT direction_id, teacher_id FROM groups WHERE id = %s", [gid],
            )
            direction_id, teacher_id = cur.fetchone()
            cur.execute(
                "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                "lesson_duration_minutes,active) VALUES ('__pg_old_g__',%s,%s,false,60,false) "
                "RETURNING id",
                [direction_id, teacher_id],
            )
            old_group_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                "VALUES (%s,%s,5,false) RETURNING id",
                [old_group_id, progress_group['borya']],
            )
            old_membership_id = cur.fetchone()[0]
            cur.execute(
                "UPDATE group_memberships SET transferred_from_id = %s "
                "WHERE group_id = %s AND student_id = %s",
                [old_membership_id, gid, progress_group['borya']],
            )
        try:
            body = manager_client.get(_url(gid)).json()
            rows = {r['student_id']: r for r in body['students']}
            borya = rows[progress_group['borya']]
            assert borya['transferred_lessons'] == 5
            assert borya['transferred_from_group_name'] == '__pg_old_g__'

            anya = rows[progress_group['anya']]
            assert anya['transferred_lessons'] == 0
            assert anya['transferred_from_group_name'] is None
        finally:
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE group_memberships SET transferred_from_id = NULL "
                    "WHERE group_id = %s AND student_id = %s",
                    [gid, progress_group['borya']],
                )
                cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [old_group_id])
                cur.execute('DELETE FROM groups WHERE id = %s', [old_group_id])

    def test_transferred_count_capped_at_total_slots(self, manager_client, progress_group):
        """
        Отработано в старой группе (20) больше, чем всего слотов в этой матрице
        (total_slots=8) — transferred_lessons не может превышать total_slots.
        """
        gid = progress_group['group_id']
        with connection.cursor() as cur:
            cur.execute(
                "SELECT direction_id, teacher_id FROM groups WHERE id = %s", [gid],
            )
            direction_id, teacher_id = cur.fetchone()
            cur.execute(
                "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                "lesson_duration_minutes,active) VALUES ('__pg_old_g2__',%s,%s,false,60,false) "
                "RETURNING id",
                [direction_id, teacher_id],
            )
            old_group_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                "VALUES (%s,%s,20,false) RETURNING id",
                [old_group_id, progress_group['anya']],
            )
            old_membership_id = cur.fetchone()[0]
            cur.execute(
                "UPDATE group_memberships SET transferred_from_id = %s "
                "WHERE group_id = %s AND student_id = %s",
                [old_membership_id, gid, progress_group['anya']],
            )
        try:
            body = manager_client.get(_url(gid)).json()
            rows = {r['student_id']: r for r in body['students']}
            assert rows[progress_group['anya']]['transferred_lessons'] == 8
        finally:
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE group_memberships SET transferred_from_id = NULL "
                    "WHERE group_id = %s AND student_id = %s",
                    [gid, progress_group['anya']],
                )
                cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [old_group_id])
                cur.execute('DELETE FROM groups WHERE id = %s', [old_group_id])

    def test_half_lesson_floored(self, manager_client, progress_group):
        """lessons_done=4.5 в старой группе → transferred_lessons=4 (floor, не round)."""
        gid = progress_group['group_id']
        with connection.cursor() as cur:
            cur.execute(
                "SELECT direction_id, teacher_id FROM groups WHERE id = %s", [gid],
            )
            direction_id, teacher_id = cur.fetchone()
            cur.execute(
                "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                "lesson_duration_minutes,active) VALUES ('__pg_old_g3__',%s,%s,false,45,false) "
                "RETURNING id",
                [direction_id, teacher_id],
            )
            old_group_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                "VALUES (%s,%s,4.5,false) RETURNING id",
                [old_group_id, progress_group['borya']],
            )
            old_membership_id = cur.fetchone()[0]
            cur.execute(
                "UPDATE group_memberships SET transferred_from_id = %s "
                "WHERE group_id = %s AND student_id = %s",
                [old_membership_id, gid, progress_group['borya']],
            )
        try:
            body = manager_client.get(_url(gid)).json()
            rows = {r['student_id']: r for r in body['students']}
            assert rows[progress_group['borya']]['transferred_lessons'] == 4
        finally:
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE group_memberships SET transferred_from_id = NULL "
                    "WHERE group_id = %s AND student_id = %s",
                    [gid, progress_group['borya']],
                )
                cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [old_group_id])
                cur.execute('DELETE FROM groups WHERE id = %s', [old_group_id])

    def test_multi_hop_chain_sums_lessons(self, manager_client, progress_group):
        """
        Боря: А(3 урока, архивная) → Б(2 урока, архивная) → текущая группа
        (progress_group, total_slots=8). transferred_lessons = min(3+2, 8) = 5 —
        сумма по всей цепочке, без капа (5 < 8), источник — Б (не А).
        """
        gid = progress_group['group_id']
        with connection.cursor() as cur:
            cur.execute("SELECT direction_id, teacher_id FROM groups WHERE id = %s", [gid])
            direction_id, teacher_id = cur.fetchone()
            cur.execute(
                "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                "lesson_duration_minutes,active) VALUES ('__pg_chain_a__',%s,%s,false,60,false) "
                "RETURNING id",
                [direction_id, teacher_id],
            )
            group_a = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                "lesson_duration_minutes,active) VALUES ('__pg_chain_b__',%s,%s,false,60,false) "
                "RETURNING id",
                [direction_id, teacher_id],
            )
            group_b = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                "VALUES (%s,%s,3,false) RETURNING id",
                [group_a, progress_group['borya']],
            )
            membership_a = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO group_memberships (group_id, student_id, lessons_done, active, transferred_from_id) "
                "VALUES (%s,%s,2,false,%s) RETURNING id",
                [group_b, progress_group['borya'], membership_a],
            )
            membership_b = cur.fetchone()[0]
            cur.execute(
                "UPDATE group_memberships SET transferred_from_id = %s "
                "WHERE group_id = %s AND student_id = %s",
                [membership_b, gid, progress_group['borya']],
            )
        try:
            body = manager_client.get(_url(gid)).json()
            rows = {r['student_id']: r for r in body['students']}
            assert rows[progress_group['borya']]['transferred_lessons'] == 5  # 3+2, не капается (< total_slots=8)
            assert rows[progress_group['borya']]['transferred_from_group_name'] == '__pg_chain_b__'
        finally:
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE group_memberships SET transferred_from_id = NULL "
                    "WHERE group_id = %s AND student_id = %s",
                    [gid, progress_group['borya']],
                )
                cur.execute('DELETE FROM group_memberships WHERE group_id IN (%s, %s)', [group_a, group_b])
                cur.execute('DELETE FROM groups WHERE id IN (%s, %s)', [group_a, group_b])
