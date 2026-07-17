"""API дран-предпросмотра заморозки: POST /api/admin/students/:id/status/preview.
Права IsManagerOrAdmin. Для каждого ИНДИВ-членства из membership_ids —
{'lesson_on_frozen_from': bool, 'first_lesson_after_resume': date|None}.
Групповые membership_ids молча исключаются (у групп расписание не сдвигается).

Валидация: frozen_from/frozen_until обязательны, frozen_from <= frozen_until,
membership_ids — непустой список int (иначе 400)."""
import datetime

import pytest
from django.db import connection

from apps.scheduling.models import PlannedLesson
from apps.scheduling.occurrences import PENDING

BASE = '/api/admin/students'


@pytest.fixture
def preview_setup(db):
    """Ученик с индив-членством (слот ср 10:00, 4 курсовые строки ср., еженедельно
    + extra) и групповым членством — для проверки исключения групповых из превью."""
    ids = {}
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name, is_individual, active, total_lessons) "
                    "VALUES ('__pvapi_idir__', true, true, 8) RETURNING id")
        ids['idir'] = cur.fetchone()[0]
        cur.execute("INSERT INTO directions (name, is_individual, active, total_lessons) "
                    "VALUES ('__pvapi_gdir__', false, true, 8) RETURNING id")
        ids['gdir'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name, active, created_at) "
                    "VALUES ('__pvapi_t__', true, NOW()) RETURNING id")
        ids['teacher'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status, created_at) "
            "VALUES ('__pvapi_s__', 'enrolled', NOW()) RETURNING id")
        ids['student'] = cur.fetchone()[0]

        # индив-группа + слот ср 10:00
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, group_start_date, active, created_at) "
            "VALUES ('__pvapi_ig__', %s, %s, true, 90, 1, DATE '2026-07-01', true, NOW()) RETURNING id",
            [ids['idir'], ids['teacher']])
        ids['igroup'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_schedule_slots (group_id, day_of_week, start_time, effective_from) "
            "VALUES (%s, 3, TIME '10:00', DATE '2000-01-01')", [ids['igroup']])
        cur.execute(
            "INSERT INTO group_memberships (student_id, group_id, active) "
            "VALUES (%s, %s, true) RETURNING id", [ids['student'], ids['igroup']])
        ids['imembership'] = cur.fetchone()[0]

        # групповая группа + членство
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, group_start_date, active, created_at) "
            "VALUES ('__pvapi_gg__', %s, %s, false, 60, DATE '2026-07-01', true, NOW()) RETURNING id",
            [ids['gdir'], ids['teacher']])
        ids['ggroup'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (student_id, group_id, active) "
            "VALUES (%s, %s, true) RETURNING id", [ids['student'], ids['ggroup']])
        ids['gmembership'] = cur.fetchone()[0]

    now = datetime.datetime(2026, 7, 1, 12, 0)
    for seq, d in [(1, '2026-07-01'), (2, '2026-07-08'), (3, '2026-07-15'), (4, '2026-07-22')]:
        PlannedLesson.objects.create(
            group_id=ids['igroup'], seq=seq, lesson_number=seq,
            scheduled_date=d, scheduled_time=datetime.time(10, 0),
            teacher_id=ids['teacher'], status=PENDING, created_at=now, updated_at=now)

    yield ids

    with connection.cursor() as cur:
        cur.execute("DELETE FROM planned_lessons WHERE group_id IN (%s,%s)",
                    [ids['igroup'], ids['ggroup']])
        cur.execute("DELETE FROM group_memberships WHERE student_id=%s", [ids['student']])
        cur.execute("DELETE FROM group_schedule_slots WHERE group_id IN (%s,%s)",
                    [ids['igroup'], ids['ggroup']])
        cur.execute("DELETE FROM groups WHERE id IN (%s,%s)", [ids['igroup'], ids['ggroup']])
        cur.execute("DELETE FROM students WHERE id=%s", [ids['student']])
        cur.execute("DELETE FROM teachers WHERE id=%s", [ids['teacher']])
        cur.execute("DELETE FROM directions WHERE id IN (%s,%s)", [ids['idir'], ids['gdir']])


@pytest.mark.django_db
def test_preview_returns_200_with_shape(admin_client, preview_setup):
    """Валидный запрос → 200; в результате есть запись для индив-членства с
    ожидаемой формой (lesson_on_frozen_from + first_lesson_after_resume)."""
    sid = preview_setup['student']
    mid = preview_setup['imembership']
    resp = admin_client.post(
        f'{BASE}/{sid}/status/preview',
        {'membership_ids': [mid],
         'frozen_from': '2026-07-08', 'frozen_until': '2026-08-05'},
        format='json')
    assert resp.status_code == 200
    body = resp.json()
    # ключ членства сериализуется в строку в JSON
    entry = body[str(mid)]
    assert entry['lesson_on_frozen_from'] is True
    assert entry['first_lesson_after_resume'] == '2026-08-05'


@pytest.mark.django_db
def test_preview_excludes_group_membership(admin_client, preview_setup):
    """Групповое членство в списке молча исключается — у групп расписание не
    сдвигается, превью только для индивидуальных."""
    sid = preview_setup['student']
    imid = preview_setup['imembership']
    gmid = preview_setup['gmembership']
    resp = admin_client.post(
        f'{BASE}/{sid}/status/preview',
        {'membership_ids': [imid, gmid],
         'frozen_from': '2026-07-08', 'frozen_until': '2026-08-05'},
        format='json')
    assert resp.status_code == 200
    body = resp.json()
    assert str(imid) in body
    assert str(gmid) not in body


@pytest.mark.django_db
def test_preview_missing_dates_400(admin_client, preview_setup):
    sid = preview_setup['student']
    mid = preview_setup['imembership']
    resp = admin_client.post(
        f'{BASE}/{sid}/status/preview',
        {'membership_ids': [mid], 'frozen_from': '2026-07-08'},
        format='json')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_preview_from_after_until_400(admin_client, preview_setup):
    sid = preview_setup['student']
    mid = preview_setup['imembership']
    resp = admin_client.post(
        f'{BASE}/{sid}/status/preview',
        {'membership_ids': [mid],
         'frozen_from': '2026-08-10', 'frozen_until': '2026-08-05'},
        format='json')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_preview_empty_membership_ids_400(admin_client, preview_setup):
    sid = preview_setup['student']
    resp = admin_client.post(
        f'{BASE}/{sid}/status/preview',
        {'membership_ids': [],
         'frozen_from': '2026-07-08', 'frozen_until': '2026-08-05'},
        format='json')
    assert resp.status_code == 400
