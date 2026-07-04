"""
API-тесты GET /api/calendar (role=teacher) — чтение materialize-on-write
planned_lessons (шаг 5).

Покрытие: auth (401/403), валидация окна (400), скоуп по planned_lesson.teacher_id
(включая «перекидывание» урока к другому преподавателю), статусы на чтении
(done/overdue/pending/cancelled/moved), контракт ответа, unscheduled без плана.

Плановые строки сидируем прямым INSERT в planned_lessons (точный контроль дат/
статусов, независимо от системных часов) либо через repository.generate_for_group
(реалистичный materialize из слотов фикстуры). managed-схема journal_test; чистим
planned_lessons в teardown ДО того, как sched_setup удалит группы (FK group_id).
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.scheduling import repository

pytestmark = pytest.mark.django_db

WIN = '?from=2026-06-01&to=2026-06-30'


def _seed_planned(
    group_id, teacher_id, *, seq, lesson_number, date, time='10:00',
    status='pending', fact_lesson_id=None, moved_from=None, moved_to=None,
):
    """Прямой INSERT одной строки planned_lessons (created_at/updated_at — DB-default)."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO planned_lessons "
            "(group_id, seq, lesson_number, scheduled_date, scheduled_time, teacher_id, "
            " status, fact_lesson_id, moved_from_date, moved_to_date, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW()) RETURNING id",
            [group_id, seq, lesson_number, date, time, teacher_id,
             status, fact_lesson_id, moved_from, moved_to],
        )
        return cur.fetchone()[0]


@pytest.fixture
def planned_setup(sched_setup):
    """sched_setup + гарантированная очистка planned_lessons перед удалением групп."""
    yield sched_setup
    with connection.cursor() as cur:
        cur.execute(
            'DELETE FROM planned_lessons WHERE group_id IN (%s, %s)',
            [sched_setup['group_a'], sched_setup['group_b']],
        )


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
    def test_envelope_and_occurrences(self, planned_setup):
        """Реалистичный materialize из слотов фикстуры → чтение календаря."""
        repository.generate_for_group(planned_setup['group_a'])

        resp = planned_setup['client_a'].get('/api/calendar' + WIN)
        assert resp.status_code == 200
        body = resp.json()
        assert 'occurrences' in body and 'unscheduled' in body and 'window' in body
        # Пн 10:00 от 2026-06-01, курс 8 → в июне 5 понедельников.
        dates = [o['date'] for o in body['occurrences']]
        assert dates == ['2026-06-01', '2026-06-08', '2026-06-15', '2026-06-22', '2026-06-29']
        first = body['occurrences'][0]
        assert first['group'] == '__sched_group_A__'
        assert first['groupDisplay'] == '__sched_group_A__'
        assert first['teacher'] == '__sched_A__'
        assert first['teacherOverride'] is None
        assert first['time'] == '10:00'
        assert first['day'] == 1                 # понедельник в конвенции Вс=0
        assert first['seq'] == 1
        assert first['lessonNumber'] == 1
        assert first['isGroup'] is True
        assert first['isExtra'] is False
        assert first['isHalf'] is False          # duration 60
        assert first['color'] == '#4F59F9'
        assert first['students'] == []

    def test_scoped_to_own_teacher(self, planned_setup):
        """Календарь учителя A НЕ содержит группу учителя B (скоуп по teacher_id)."""
        repository.generate_for_group(planned_setup['group_a'])
        repository.generate_for_group(planned_setup['group_b'])

        body = planned_setup['client_a'].get('/api/calendar' + WIN).json()
        groups = {o['group'] for o in body['occurrences']}
        assert '__sched_group_A__' in groups
        assert '__sched_group_B__' not in groups

    def test_reassigned_lesson_hidden_from_original_teacher(self, planned_setup):
        """
        Строка ГРУППЫ A, но с teacher_id=B (препод занятия сменён), НЕ попадает в
        календарь A — основа «перекидывания» урока между календарями (шаг 8).
        Скоуп идёт по planned_lesson.teacher_id, а не по учителю группы.
        """
        gid, ta, tb = (
            planned_setup['group_a'], planned_setup['teacher_a'], planned_setup['teacher_b'],
        )
        _seed_planned(gid, ta, seq=1, lesson_number=1, date='2026-06-01')
        _seed_planned(gid, tb, seq=2, lesson_number=2, date='2026-06-08')

        body = planned_setup['client_a'].get('/api/calendar' + WIN).json()
        dates = [o['date'] for o in body['occurrences']]
        assert '2026-06-01' in dates          # своё занятие
        assert '2026-06-08' not in dates       # ушло к преподавателю B

    def test_status_overdue_for_past(self, planned_setup):
        """Прошедшая (по МСК) строка status='pending' читается как 'overdue'."""
        oid = _seed_planned(
            planned_setup['group_a'], planned_setup['teacher_a'],
            seq=1, lesson_number=1, date='2000-01-03', status='pending',
        )
        body = planned_setup['client_a'].get(
            '/api/calendar?from=2000-01-01&to=2000-02-01',
        ).json()
        o = next(x for x in body['occurrences'] if x['date'] == '2000-01-03')
        assert o['status'] == 'overdue'
        assert o['label'] == 'Надо заполнить'
        assert oid  # sanity

    def test_status_pending_for_future(self, planned_setup):
        """Будущая (по МСК) строка status='pending' читается как 'pending'."""
        _seed_planned(
            planned_setup['group_a'], planned_setup['teacher_a'],
            seq=1, lesson_number=1, date='2099-02-01', status='pending',
        )
        body = planned_setup['client_a'].get(
            '/api/calendar?from=2099-01-15&to=2099-03-01',
        ).json()
        o = next(x for x in body['occurrences'] if x['date'] == '2099-02-01')
        assert o['status'] == 'pending'
        assert o['label'] == 'Пока урока не было'

    def test_status_done_when_stored(self, planned_setup):
        """status='done' проходит как есть (проведённое)."""
        _seed_planned(
            planned_setup['group_a'], planned_setup['teacher_a'],
            seq=1, lesson_number=1, date='2026-06-01', status='done',
        )
        body = planned_setup['client_a'].get('/api/calendar' + WIN).json()
        o = next(x for x in body['occurrences'] if x['date'] == '2026-06-01')
        assert o['status'] == 'done'
        assert o['label'] == 'Заполнено'

    def test_status_done_via_fact_lesson(self, planned_setup):
        """fact_lesson задан → 'done', даже если status ещё 'pending'."""
        group_a, teacher_a = planned_setup['group_a'], planned_setup['teacher_a']
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
                "lesson_duration_minutes, lesson_type, submitted_by_token, submitted_at) "
                "VALUES (%s,%s,'2026-06-08',2,60,'regular','__t__',NOW()) RETURNING id",
                [group_a, teacher_a],
            )
            lesson_id = cur.fetchone()[0]
        _seed_planned(
            group_a, teacher_a, seq=2, lesson_number=2, date='2026-06-08',
            status='pending', fact_lesson_id=lesson_id,
        )
        body = planned_setup['client_a'].get('/api/calendar' + WIN).json()
        o = next(x for x in body['occurrences'] if x['date'] == '2026-06-08')
        assert o['status'] == 'done'

    def test_status_cancelled_passthrough(self, planned_setup):
        """status='cancelled' проходит как есть с лейблом 'Отменён'."""
        _seed_planned(
            planned_setup['group_a'], planned_setup['teacher_a'],
            seq=1, lesson_number=1, date='2026-06-01', status='cancelled',
        )
        body = planned_setup['client_a'].get('/api/calendar' + WIN).json()
        o = next(x for x in body['occurrences'] if x['date'] == '2026-06-01')
        assert o['status'] == 'cancelled'
        assert o['label'] == 'Отменён'

    def test_status_moved_passthrough_with_label(self, planned_setup):
        """status='moved' + moved_to_date → лейбл 'Перенесён на DD.MM', movedTo задан."""
        _seed_planned(
            planned_setup['group_a'], planned_setup['teacher_a'],
            seq=1, lesson_number=1, date='2026-06-01', status='moved',
            moved_to='2026-06-03',
        )
        body = planned_setup['client_a'].get('/api/calendar' + WIN).json()
        o = next(x for x in body['occurrences'] if x['date'] == '2026-06-01')
        assert o['status'] == 'moved'
        assert o['label'] == 'Перенесён на 03.06'
        assert o['movedTo'] == '2026-06-03'

    def test_reschedule_shows_moved_from(self, planned_setup):
        """Разово перенесённая строка (moved_from_date) отображает movedFrom."""
        _seed_planned(
            planned_setup['group_a'], planned_setup['teacher_a'],
            seq=1, lesson_number=1, date='2026-06-02', status='pending',
            moved_from='2026-06-01',
        )
        body = planned_setup['client_a'].get('/api/calendar' + WIN).json()
        o = next(x for x in body['occurrences'] if x['date'] == '2026-06-02')
        assert o['movedFrom'] == '2026-06-01'

    def test_extra_lesson_shape(self, planned_setup):
        """Доп. занятие (seq=NULL) → isExtra=True, seq=None, lessonNumber=None."""
        _seed_planned(
            planned_setup['group_a'], planned_setup['teacher_a'],
            seq=None, lesson_number=None, date='2026-06-10', status='pending',
        )
        body = planned_setup['client_a'].get('/api/calendar' + WIN).json()
        o = next(x for x in body['occurrences'] if x['date'] == '2026-06-10')
        assert o['isExtra'] is True
        assert o['seq'] is None
        assert o['lessonNumber'] is None

    def test_teacher_override_when_group_teacher_differs(self, planned_setup):
        """
        Строка ГРУППЫ B (учитель B), но с teacher_id=A: A видит её, teacherOverride=A
        (препод занятия ≠ учитель группы). Проверяет override-семантику ответа.
        """
        gid_b, ta = planned_setup['group_b'], planned_setup['teacher_a']
        _seed_planned(gid_b, ta, seq=1, lesson_number=1, date='2026-06-01')
        body = planned_setup['client_a'].get('/api/calendar' + WIN).json()
        o = next(x for x in body['occurrences'] if x['group'] == '__sched_group_B__')
        assert o['teacher'] == '__sched_A__'
        assert o['teacherOverride'] == '__sched_A__'

    def test_unscheduled_group_without_plan(self, planned_setup):
        """Группа A (учитель A, есть старт+слот) без плана → unscheduled/not_generated."""
        body = planned_setup['client_a'].get('/api/calendar' + WIN).json()
        reasons = {u['group']: u['reason'] for u in body['unscheduled']}
        assert reasons.get('__sched_group_A__') == 'not_generated'
