import pytest
from django.core.management import call_command
from django.db import connection

from apps.renewals.models import RenewalDeal


@pytest.mark.django_db
def test_rebuild_creates_deal_for_active_membership(make_student, make_direction, make_teacher):
    # groups.teacher_id — NOT NULL FK (NO ACTION), поэтому нужен реальный teacher.
    sid, did, tid = make_student(), make_direction(), make_teacher()
    with connection.cursor() as cur:
        cur.execute("INSERT INTO groups (name, direction_id, teacher_id, is_individual, active, created_at) "
                    "VALUES ('__rg__', %s, %s, false, true, now()) RETURNING id", [did, tid])
        gid = cur.fetchone()[0]
        cur.execute("INSERT INTO group_memberships (group_id, student_id, lessons_done, remaining, active) "
                    "VALUES (%s,%s,0,4,true)", [gid, sid])
    try:
        call_command('rebuild_renewal_deals')
        assert RenewalDeal.objects.filter(student_id=sid, direction_id=did, cycle_no=1).exists()
    finally:
        # Порядок: activity → deal → membership → group (FK groups→teacher/direction —
        # NO ACTION, поэтому group удаляем ДО teardown teacher/direction в conftest).
        with connection.cursor() as cur:
            cur.execute('DELETE FROM renewal_activity WHERE deal_id IN '
                        '(SELECT id FROM renewal_deal WHERE student_id = %s)', [sid])
            cur.execute('DELETE FROM renewal_deal WHERE student_id = %s', [sid])
            cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [gid])
            cur.execute('DELETE FROM groups WHERE id = %s', [gid])
