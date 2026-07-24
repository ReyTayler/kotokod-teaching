"""Сводка «Ученики без сделок» + ручное создание сделки (POST /api/admin/renewals)."""
import pytest
from django.db import connection
from django.utils import timezone

from apps.renewals import engine
from apps.renewals.models import RenewalDeal, RenewalPipeline, RenewalStage

BASE = '/api/admin/renewals'


def _make_group_membership(did, tid, sid, name='__un_group__'):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO groups (name, direction_id, teacher_id, is_individual, active, created_at, "
                    "lesson_number_offset) "
                    "VALUES (%s, %s, %s, false, true, now(), 0) RETURNING id", [name, did, tid])
        gid = cur.fetchone()[0]
        cur.execute("INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
                    "VALUES (%s,%s,0,true)", [gid, sid])
    return gid


def _cleanup(sid, gid):
    with connection.cursor() as cur:
        cur.execute('DELETE FROM renewal_activity WHERE deal_id IN '
                    '(SELECT id FROM renewal_deal WHERE student_id = %s)', [sid])
        cur.execute('DELETE FROM renewal_deal WHERE student_id = %s', [sid])
        cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [gid])
        cur.execute('DELETE FROM groups WHERE id = %s', [gid])


@pytest.mark.django_db
def test_unassigned_requires_staff(teacher_client):
    assert teacher_client.get(f'{BASE}/unassigned').status_code == 403


@pytest.mark.django_db
def test_unassigned_lists_student_and_create_removes(manager_client, make_student,
                                                     make_direction, make_teacher):
    """Активный ученик без сделки виден в сводке; после создания — исчезает."""
    sid, did, tid = make_student('__un_student__'), make_direction(), make_teacher()
    gid = _make_group_membership(did, tid, sid)
    try:
        rows = manager_client.get(f'{BASE}/unassigned').json()
        mine = [r for r in rows if r['student_id'] == sid]
        assert mine and mine[0]['cycle_no'] == 1
        assert {'student_name', 'directions', 'attended', 'debt'} <= set(mine[0])

        created = manager_client.post(BASE, {'student_id': sid}, format='json')
        assert created.status_code == 201
        assert created.json()['cycle_no'] == 1
        assert created.json()['outcome_at'] is None

        rows = manager_client.get(f'{BASE}/unassigned').json()
        assert not [r for r in rows if r['student_id'] == sid]
    finally:
        _cleanup(sid, gid)


@pytest.mark.django_db
def test_create_conflicts_when_open_deal_exists(manager_client, make_student):
    sid = make_student()
    engine.ensure_deal(sid, cycle_no=1)
    resp = manager_client.post(BASE, {'student_id': sid}, format='json')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_create_unknown_student_404(manager_client):
    assert manager_client.post(BASE, {'student_id': 999999999},
                               format='json').status_code == 404


@pytest.mark.django_db
def test_create_skips_closed_cycle_of_returned_student(manager_client, make_student):
    """Вернувшийся после «Ушёл» ученик: расчётный цикл занят закрытой сделкой —
    новая создаётся со следующим номером, а не теряется в get_or_create."""
    sid = make_student()
    pipe = RenewalPipeline.objects.get(is_default=True)
    lost = RenewalStage.objects.filter(pipeline=pipe, kind='lost').first()
    RenewalDeal.objects.create(student_id=sid, cycle_no=1, pipeline=pipe,
                               stage=lost, outcome_at=timezone.now())

    resp = manager_client.post(BASE, {'student_id': sid}, format='json')
    assert resp.status_code == 201
    assert resp.json()['cycle_no'] == 2
    assert RenewalDeal.objects.filter(student_id=sid, outcome_at__isnull=True,
                                      cycle_no=2).exists()
