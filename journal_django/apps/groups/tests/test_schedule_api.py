"""
API-тесты admin-редактирования расписания (Ф3):
  GET  /api/admin/groups/:id/schedule
  POST /api/admin/groups/:id/schedule-change
  POST /api/admin/groups/:id/exceptions
  DELETE /api/admin/groups/:id/exceptions/:eid

Права: IsManagerOrAdmin. Аутентификация — JWT (root conftest клиенты).
"""
from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db


@pytest.fixture
def sched_group(db):
    """Группа + направление + преподаватель. Возвращает group_id."""
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name, active) VALUES ('__sch_t__', true) RETURNING id")
        teacher_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO directions (name,sheet_name,is_individual,total_lessons,active) "
            "VALUES ('__sch_d__','__s__',false,8,true) RETURNING id"
        )
        direction_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name,direction_id,teacher_id,is_individual,lesson_duration_minutes,"
            "group_start_date,active) VALUES ('__sch_g__',%s,%s,false,60,'2026-06-01',true) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]
    yield group_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM lesson_schedule_exceptions WHERE group_id = %s', [group_id])
        cur.execute('DELETE FROM group_schedule_slots WHERE group_id = %s', [group_id])
        cur.execute('DELETE FROM groups WHERE id = %s', [group_id])
        cur.execute('DELETE FROM directions WHERE id = %s', [direction_id])
        cur.execute('DELETE FROM teachers WHERE id = %s', [teacher_id])


class TestAuth:
    def test_schedule_anon_401(self, anon_client, sched_group):
        assert anon_client.get(f'/api/admin/groups/{sched_group}/schedule').status_code == 401

    def test_schedule_teacher_403(self, teacher_client, sched_group):
        assert teacher_client.get(f'/api/admin/groups/{sched_group}/schedule').status_code == 403

    def test_schedule_change_teacher_403(self, teacher_client, sched_group):
        resp = teacher_client.post(
            f'/api/admin/groups/{sched_group}/schedule-change',
            {'effective_from': '2026-06-01', 'slots': [{'day_of_week': 1, 'start_time': '10:00'}]},
            format='json',
        )
        assert resp.status_code == 403


class TestScheduleChange:
    def test_get_empty_schedule(self, manager_client, sched_group):
        resp = manager_client.get(f'/api/admin/groups/{sched_group}/schedule')
        assert resp.status_code == 200
        body = resp.json()
        assert body == {'slots': [], 'exceptions': []}

    def test_apply_and_read(self, manager_client, sched_group):
        resp = manager_client.post(
            f'/api/admin/groups/{sched_group}/schedule-change',
            {'effective_from': '2026-06-01', 'slots': [{'day_of_week': 1, 'start_time': '10:00'}]},
            format='json',
        )
        assert resp.status_code == 200
        slots = resp.json()['slots']
        assert len(slots) == 1
        assert slots[0]['day_of_week'] == 1
        assert slots[0]['start_time'] == '10:00'
        assert slots[0]['effective_from'] == '2026-06-01'
        assert slots[0]['effective_to'] is None

    def test_permanent_change_closes_previous(self, manager_client, sched_group):
        base = f'/api/admin/groups/{sched_group}/schedule-change'
        manager_client.post(base, {'effective_from': '2026-06-01',
                                    'slots': [{'day_of_week': 1, 'start_time': '10:00'}]}, format='json')
        manager_client.post(base, {'effective_from': '2026-07-01',
                                   'slots': [{'day_of_week': 3, 'start_time': '14:00'}]}, format='json')
        body = manager_client.get(f'/api/admin/groups/{sched_group}/schedule').json()
        slots = {(s['day_of_week'], s['start_time']): s for s in body['slots']}
        assert slots[(1, '10:00')]['effective_to'] == '2026-06-30'   # старый закрыт
        assert slots[(3, '14:00')]['effective_from'] == '2026-07-01'  # новый открыт
        assert slots[(3, '14:00')]['effective_to'] is None

    def test_schedule_change_missing_group_404(self, manager_client):
        resp = manager_client.post(
            '/api/admin/groups/99999999/schedule-change',
            {'effective_from': '2026-06-01', 'slots': [{'day_of_week': 1, 'start_time': '10:00'}]},
            format='json',
        )
        assert resp.status_code == 404

    def test_schedule_change_empty_slots_400(self, manager_client, sched_group):
        resp = manager_client.post(
            f'/api/admin/groups/{sched_group}/schedule-change',
            {'effective_from': '2026-06-01', 'slots': []},
            format='json',
        )
        assert resp.status_code == 400


class TestExceptions:
    def _post(self, client, gid, body):
        return client.post(f'/api/admin/groups/{gid}/exceptions', body, format='json')

    def test_create_reschedule(self, manager_client, sched_group):
        resp = self._post(manager_client, sched_group, {
            'kind': 'reschedule', 'original_date': '2026-06-08',
            'new_date': '2026-06-10', 'new_start_time': '15:00',
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body['kind'] == 'reschedule'
        assert body['original_date'] == '2026-06-08'
        assert body['new_date'] == '2026-06-10'
        assert body['new_start_time'] == '15:00'

    def test_create_cancel_and_extra(self, manager_client, sched_group):
        assert self._post(manager_client, sched_group,
                          {'kind': 'cancel', 'original_date': '2026-06-15'}).status_code == 201
        assert self._post(manager_client, sched_group,
                          {'kind': 'extra', 'new_date': '2026-06-20', 'new_start_time': '16:00'}).status_code == 201

    def test_reschedule_missing_dates_400(self, manager_client, sched_group):
        assert self._post(manager_client, sched_group, {'kind': 'reschedule'}).status_code == 400

    def test_cancel_with_new_date_400(self, manager_client, sched_group):
        resp = self._post(manager_client, sched_group,
                          {'kind': 'cancel', 'original_date': '2026-06-15', 'new_date': '2026-06-16'})
        assert resp.status_code == 400

    def test_bad_time_format_400(self, manager_client, sched_group):
        resp = self._post(manager_client, sched_group,
                          {'kind': 'extra', 'new_date': '2026-06-20', 'new_start_time': '25h'})
        assert resp.status_code == 400

    def test_appears_in_schedule_then_delete(self, manager_client, sched_group):
        created = self._post(manager_client, sched_group,
                             {'kind': 'cancel', 'original_date': '2026-06-15'}).json()
        eid = created['id']
        body = manager_client.get(f'/api/admin/groups/{sched_group}/schedule').json()
        assert any(e['id'] == eid for e in body['exceptions'])

        assert manager_client.delete(
            f'/api/admin/groups/{sched_group}/exceptions/{eid}'
        ).status_code == 204
        # повторное удаление → 404
        assert manager_client.delete(
            f'/api/admin/groups/{sched_group}/exceptions/{eid}'
        ).status_code == 404

    def test_exception_missing_group_404(self, manager_client):
        assert self._post(manager_client, 99999999,
                          {'kind': 'cancel', 'original_date': '2026-06-15'}).status_code == 404
