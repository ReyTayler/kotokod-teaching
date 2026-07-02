"""
API-тесты GET /api/calendar (role=teacher).

Покрытие: auth (401/403), валидация окна (400), скоуп по учителю,
генерация occurrences, статус 'done' по факту урока.
"""
from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db

WIN = '?from=2026-06-01&to=2026-06-30'


class TestAuth:
    def test_no_cookie_401(self, anon_client):
        assert anon_client.get('/api/calendar' + WIN).status_code == 401

    def test_manager_403(self, manager_client):
        assert manager_client.get('/api/calendar' + WIN).status_code == 403


class TestWindowValidation:
    def test_missing_params_400(self, teacher_client):
        assert teacher_client.get('/api/calendar').status_code == 400

    def test_bad_date_400(self, teacher_client):
        assert teacher_client.get('/api/calendar?from=nope&to=2026-06-30').status_code == 400

    def test_reversed_window_400(self, teacher_client):
        assert teacher_client.get('/api/calendar?from=2026-06-30&to=2026-06-01').status_code == 400

    def test_too_wide_400(self, teacher_client):
        assert teacher_client.get('/api/calendar?from=2026-01-01&to=2026-12-31').status_code == 400


class TestCalendar:
    def test_envelope_and_occurrences(self, sched_setup):
        resp = sched_setup['client_a'].get('/api/calendar' + WIN)
        assert resp.status_code == 200
        body = resp.json()
        assert 'occurrences' in body and 'unscheduled' in body and 'window' in body
        # Пн 10:00 от 2026-06-01, курс 8 → в июне 5 понедельников
        dates = [o['date'] for o in body['occurrences']]
        assert dates == ['2026-06-01', '2026-06-08', '2026-06-15', '2026-06-22', '2026-06-29']
        first = body['occurrences'][0]
        assert first['group'] == '__sched_group_A__'
        assert first['time'] == '10:00'
        assert first['day'] == 1                 # понедельник в конвенции Вс=0
        assert first['lessonNumber'] == 1
        assert first['color'] == '#4F59F9'

    def test_scoped_to_own_teacher(self, sched_setup):
        """Календарь учителя A НЕ содержит группу учителя B."""
        body = sched_setup['client_a'].get('/api/calendar' + WIN).json()
        groups = {o['group'] for o in body['occurrences']}
        assert '__sched_group_A__' in groups
        assert '__sched_group_B__' not in groups

    def test_fact_marks_done(self, sched_setup):
        """Есть урок на дату occurrence → статус 'done'."""
        group_a = sched_setup['group_a']
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
                "lesson_duration_minutes, lesson_type, submitted_by_token, submitted_at) "
                "VALUES (%s,%s,'2026-06-08',2,60,'regular','__t__',NOW()) RETURNING id",
                [group_a, sched_setup['teacher_a']],
            )
            lesson_id = cur.fetchone()[0]
        try:
            body = sched_setup['client_a'].get('/api/calendar' + WIN).json()
            by_date = {o['date']: o for o in body['occurrences']}
            assert by_date['2026-06-08']['status'] == 'done'
            # соседняя дата без факта — не done
            assert by_date['2026-06-01']['status'] in ('pending', 'overdue')
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM lessons WHERE id = %s', [lesson_id])
