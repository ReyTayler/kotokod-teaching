"""
Отмена занятия с причиной — только у индивидуальных групп («Мотивация»).

Индив: причина обязательна; запись LessonCancellation + начисление за отмену по
флагу «Компенсация» и ставкам версии на дату. Групповой формат: отмена прежняя —
без тела, без записи и без начисления.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection

from apps.cancellations.models import CancellationReason, LessonCancellation
from apps.payroll.models import CancellationPay, PayRateVersion
from apps.scheduling.models import PlannedLesson

pytestmark = pytest.mark.django_db

DATES = ['2026-10-06', '2026-10-13', '2026-10-20', '2026-10-27']


@pytest.fixture(scope='session')
def django_db_setup():
    pass


@pytest.fixture
def planned():
    """Преподаватель, индив- и групповая группа с планом из 4 занятий (вт 18:00)."""
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name, active) VALUES ('__cx_t__', true) RETURNING id")
        tid = cur.fetchone()[0]
        cur.execute("INSERT INTO directions (name, total_lessons, active) "
                    "VALUES ('__cx_dir__', 4, true) RETURNING id")
        did = cur.fetchone()[0]
        groups = {}
        for key, indiv in (('indiv', True), ('group', False)):
            cur.execute(
                "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
                "lesson_duration_minutes, lessons_per_week, active, lesson_number_offset) "
                "VALUES (%s, %s, %s, %s, 60, 1, true, 0) RETURNING id",
                [f'__cx_{key}__', did, tid, indiv])
            gid = cur.fetchone()[0]
            groups[key] = gid
            cur.execute("INSERT INTO group_schedule_slots (group_id, day_of_week, start_time, "
                        "effective_from) VALUES (%s, 2, '18:00', '2026-10-01')", [gid])
    now = datetime.datetime(2026, 10, 1, 12, 0)
    rows = {}
    for key, gid in groups.items():
        rows[key] = [
            PlannedLesson.objects.create(
                group_id=gid, seq=i, lesson_number=i, scheduled_date=d,
                scheduled_time=datetime.time(18, 0), teacher_id=tid, status='pending',
                created_at=now, updated_at=now)
            for i, d in enumerate(DATES, start=1)
        ]
    version = PayRateVersion.objects.create(
        effective_from=datetime.date(2026, 9, 1), individual_rate=Decimal('600'),
        makeup_rate=Decimal('200'), burned_rate=Decimal('200'), cancel_mode='percent',
        cancel_value=Decimal('50'))
    reasons = {
        'paid': CancellationReason.objects.create(side='teacher', name='__cx_paid__',
                                                  compensation=True, position=0),
        'free': CancellationReason.objects.create(side='teacher', name='__cx_free__',
                                                  compensation=False, position=1),
    }
    yield {'teacher': tid, 'groups': groups, 'rows': rows, 'reasons': reasons}
    gids = list(groups.values())
    with connection.cursor() as cur:
        cur.execute('DELETE FROM payroll_cancellations WHERE group_id = ANY(%s)', [gids])
        cur.execute('DELETE FROM lesson_cancellations WHERE group_id = ANY(%s)', [gids])
        cur.execute('DELETE FROM planned_lessons WHERE group_id = ANY(%s)', [gids])
        cur.execute('DELETE FROM group_schedule_slots WHERE group_id = ANY(%s)', [gids])
        cur.execute('DELETE FROM groups WHERE id = ANY(%s)', [gids])
        cur.execute('DELETE FROM directions WHERE id = %s', [did])
        cur.execute('DELETE FROM teachers WHERE id = %s', [tid])
    CancellationReason.objects.filter(id__in=[r.id for r in reasons.values()]).delete()
    PayRateVersion.objects.filter(id=version.id).delete()


def _url(gid, lid):
    return f'/api/admin/groups/{gid}/plan/{lid}/cancel'


def _body(row, reason, **kw):
    return {'lesson_date': str(row.scheduled_date), 'side': 'teacher', 'reason_id': reason.id, **kw}


def test_individual_requires_reason(manager_client, planned):
    gid = planned['groups']['indiv']
    row = planned['rows']['indiv'][1]
    resp = manager_client.post(_url(gid, row.id), {}, format='json')
    assert resp.status_code == 400
    assert not PlannedLesson.objects.filter(group_id=gid, status='cancelled').exists()


def test_individual_compensated_cancellation_paid(manager_client, planned):
    gid = planned['groups']['indiv']
    row = planned['rows']['indiv'][1]
    resp = manager_client.post(_url(gid, row.id), _body(row, planned['reasons']['paid']), format='json')
    assert resp.status_code == 200, resp.content
    rec = LessonCancellation.objects.get(group_id=gid)
    assert rec.compensated and rec.lesson_seq == 2
    pay = CancellationPay.objects.get(group_id=gid)
    assert pay.payment == Decimal('300.00')       # 50 % от 600
    assert pay.teacher_id == planned['teacher']
    assert 'Преподаватель — __cx_paid__' in pay.rule_note


def test_individual_not_compensated_zero_with_reason(manager_client, planned):
    gid = planned['groups']['indiv']
    row = planned['rows']['indiv'][0]
    resp = manager_client.post(_url(gid, row.id), _body(row, planned['reasons']['free']), format='json')
    assert resp.status_code == 200, resp.content
    pay = CancellationPay.objects.get(group_id=gid)
    assert pay.payment == Decimal('0.00')
    assert pay.rule_note.startswith('Без компенсации')


def test_double_cancel_conflicts(manager_client, planned):
    gid = planned['groups']['indiv']
    row = planned['rows']['indiv'][1]
    body = _body(row, planned['reasons']['paid'])
    assert manager_client.post(_url(gid, row.id), body, format='json').status_code == 200
    # Тот же lid уехал в конец курса: повтор со старой датой — 409, а не вторая отмена.
    assert manager_client.post(_url(gid, row.id), body, format='json').status_code == 409
    assert CancellationPay.objects.filter(group_id=gid).count() == 1


def test_group_format_cancel_unchanged(manager_client, planned):
    gid = planned['groups']['group']
    row = planned['rows']['group'][1]
    resp = manager_client.post(_url(gid, row.id), {}, format='json')
    assert resp.status_code == 200, resp.content
    assert PlannedLesson.objects.filter(group_id=gid, status='cancelled').exists()
    assert not LessonCancellation.objects.filter(group_id=gid).exists()
    assert not CancellationPay.objects.filter(group_id=gid).exists()


def test_group_cancellations_tab(manager_client, planned):
    gid = planned['groups']['indiv']
    row = planned['rows']['indiv'][2]
    manager_client.post(_url(gid, row.id), _body(row, planned['reasons']['paid'], details='звонил'),
                        format='json')
    resp = manager_client.get(f'/api/admin/groups/{gid}/cancellations')
    assert resp.status_code == 200
    rows = resp.json()['rows']
    assert len(rows) == 1 and rows[0]['details'] == 'звонил'
    assert 'compensated' not in rows[0]   # решение о деньгах — не для менеджера


def test_reasons_compensation_hidden_from_manager(manager_client, superadmin_client, planned):
    mgr = manager_client.get('/api/admin/cancellation-reasons').json()
    sup = superadmin_client.get('/api/admin/cancellation-reasons').json()
    assert all('compensation' not in r for r in mgr['teacher'])
    assert all('compensation' in r for r in sup['teacher'])
    assert manager_client.post('/api/admin/cancellation-reasons',
                               {'side': 'client', 'name': 'x'}, format='json').status_code == 403
