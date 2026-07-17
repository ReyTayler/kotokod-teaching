"""API смены статуса: POST /status (frozen/declined/...), POST /resume. Права
IsManagerOrAdmin; frozen требует обе даты (400 иначе)."""
import datetime

import pytest
from django.db import connection
from django.db.models.functions import Now

from apps.memberships.models import GroupMembership
from apps.renewals import engine
from apps.students.models import Student

BASE = '/api/admin/students'


@pytest.fixture
def indiv_student():
    """Индив-группа (слот ср 10:00, 4 плановые pending-строки) + student + активный
    membership + открытая сделка. Копия фикстуры из
    apps/scheduling/tests/test_freeze_scheduling.py для сквозной проверки заморозки
    индив-формата через реальный HTTP-эндпоинт /status."""
    ids = {}
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name, is_individual, active, total_lessons) "
                    "VALUES ('__api_ist_dir__', true, true, 8) RETURNING id")
        ids['dir'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name, active, created_at) "
                    "VALUES ('__api_ist_t__', true, NOW()) RETURNING id")
        ids['teacher'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, group_start_date, active, created_at) "
            "VALUES ('__api_ist_g__', %s, %s, true, 90, 1, DATE '2026-07-01', true, NOW()) "
            "RETURNING id",
            [ids['dir'], ids['teacher']])
        ids['group'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_schedule_slots (group_id, day_of_week, start_time, effective_from) "
            "VALUES (%s, 3, TIME '10:00', DATE '2000-01-01')", [ids['group']])
        for seq, d in [(1, '2026-07-01'), (2, '2026-07-08'), (3, '2026-07-15'), (4, '2026-07-22')]:
            cur.execute(
                "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
                "scheduled_time, teacher_id, status, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, '10:00', %s, 'pending', NOW(), NOW())",
                [ids['group'], seq, seq, d, ids['teacher']])
    s = Student.objects.create(full_name='__api_ist_stud__', enrollment_status='enrolled',
                               created_at=Now())
    ids['student'] = s.id
    m = GroupMembership.objects.create(group_id=ids['group'], student_id=s.id, active=True)
    ids['membership'] = m.id
    engine.ensure_deal(s.id, cycle_no=1)
    yield ids
    with connection.cursor() as cur:
        cur.execute("DELETE FROM renewal_activity WHERE deal_id IN "
                    "(SELECT id FROM renewal_deal WHERE student_id=%s)", [ids['student']])
        cur.execute("DELETE FROM renewal_deal WHERE student_id=%s", [ids['student']])
        cur.execute("DELETE FROM group_memberships WHERE id=%s", [ids['membership']])
        cur.execute("DELETE FROM students WHERE id=%s", [ids['student']])
        cur.execute("DELETE FROM planned_lessons WHERE group_id=%s", [ids['group']])
        cur.execute("DELETE FROM group_schedule_slots WHERE group_id=%s", [ids['group']])
        cur.execute("DELETE FROM groups WHERE id=%s", [ids['group']])
        cur.execute("DELETE FROM teachers WHERE id=%s", [ids['teacher']])
        cur.execute("DELETE FROM directions WHERE id=%s", [ids['dir']])


@pytest.mark.django_db
def test_freeze_requires_both_dates_400(admin_client):
    s = Student.objects.create(full_name='__api_frz__', enrollment_status='enrolled',
                               created_at=Now())
    resp = admin_client.post(f'{BASE}/{s.id}/status',
                             {'status': 'frozen', 'frozen_from': '2026-07-08'},
                             format='json')
    assert resp.status_code == 400
    Student.objects.filter(id=s.id).delete()


@pytest.mark.django_db
def test_status_change_declined_200(admin_client):
    s = Student.objects.create(full_name='__api_dec__', enrollment_status='enrolled',
                               created_at=Now())
    resp = admin_client.post(f'{BASE}/{s.id}/status', {'status': 'declined'}, format='json')
    assert resp.status_code == 200
    assert Student.objects.get(id=s.id).enrollment_status == 'declined'
    Student.objects.filter(id=s.id).delete()


@pytest.mark.django_db
def test_status_404_unknown_student(admin_client):
    resp = admin_client.post(f'{BASE}/99999999/status', {'status': 'declined'}, format='json')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_resume_requires_frozen(admin_client):
    s = Student.objects.create(full_name='__api_res__', enrollment_status='enrolled',
                               created_at=Now())
    resp = admin_client.post(f'{BASE}/{s.id}/resume',
                             {'actual_resume_date': '2026-08-05'}, format='json')
    assert resp.status_code == 404  # не заморожен → нечего размораживать
    Student.objects.filter(id=s.id).delete()


@pytest.mark.django_db
def test_status_enrolled_on_frozen_returns_400(admin_client):
    """change_student_status запрещает прямой frozen→enrolled (ValueError) —
    API обязан вернуть 400, а не 500."""
    s = Student.objects.create(
        full_name='__api_frz2enr__', enrollment_status='frozen',
        frozen_from=datetime.date(2026, 7, 8), frozen_until=datetime.date(2026, 8, 5),
        created_at=Now())
    resp = admin_client.post(f'{BASE}/{s.id}/status', {'status': 'enrolled'}, format='json')
    assert resp.status_code == 400
    Student.objects.filter(id=s.id).delete()


@pytest.mark.django_db
def test_freeze_individual_student_relays_tail_200(admin_client, indiv_student):
    """Регресс: заморозка ИНДИВ-формата через реальный HTTP /status. Сериализатор
    обязан отдать frozen_from/frozen_until как date-объекты, иначе planner._far_future
    падает на `str + timedelta` (TypeError → 500). Проверяем сквозь всю цепочку
    HTTP → serializer → service → repository → planner, что хвост реально переложился."""
    from apps.scheduling.models import PlannedLesson

    sid = indiv_student['student']
    gid = indiv_student['group']
    mid = indiv_student['membership']

    resp = admin_client.post(
        f'{BASE}/{sid}/status',
        {'status': 'frozen', 'frozen_from': '2026-07-08', 'frozen_until': '2026-08-05',
         'membership_ids': [mid]},
        format='json')

    assert resp.status_code == 200

    s = Student.objects.get(id=sid)
    assert s.enrollment_status == 'frozen'
    assert s.frozen_from == datetime.date(2026, 7, 8)
    assert s.frozen_until == datetime.date(2026, 8, 5)

    # Индив-хвост реально переложен от frozen_until (2026-08-05) по слоту ср 10:00:
    # seq1 (до окна) неподвижен; seq2..4 едут еженедельно от 2026-08-05.
    rows = {r.seq: r for r in PlannedLesson.objects.filter(
        group_id=gid, seq__isnull=False).order_by('seq')}
    assert rows[1].scheduled_date == datetime.date(2026, 7, 1)
    assert rows[2].scheduled_date == datetime.date(2026, 8, 5)
    assert rows[3].scheduled_date == datetime.date(2026, 8, 12)
    assert rows[4].scheduled_date == datetime.date(2026, 8, 19)
