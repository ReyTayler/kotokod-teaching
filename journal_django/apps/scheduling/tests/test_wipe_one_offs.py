import datetime
import pytest
from django.db import connection
from apps.scheduling.models import PlannedLesson

pytestmark = pytest.mark.django_db


@pytest.fixture
def group_with_group(db):
    # Минимальная группа (direction total_lessons=4, слот вторник) + 4 pending строки.
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name,is_individual,total_lessons,active) "
                    "VALUES ('__wipe_dir__',false,4,true) RETURNING id")
        did = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name) VALUES ('__wipe_t__') RETURNING id")
        tid = cur.fetchone()[0]
        cur.execute("INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                    "lesson_duration_minutes,lessons_per_week,active) "
                    "VALUES ('__wipe_g__',%s,%s,false,60,1,true) RETURNING id", [did, tid])
        gid = cur.fetchone()[0]
    now = datetime.datetime(2026, 7, 1, 12, 0)
    for i, d in enumerate(['2026-07-07', '2026-07-14', '2026-07-21', '2026-07-28'], start=1):
        PlannedLesson.objects.create(
            group_id=gid, seq=i, lesson_number=i, scheduled_date=d,
            scheduled_time=datetime.time(18, 0), teacher_id=tid, status='pending',
            created_at=now, updated_at=now)
    yield gid, tid
    with connection.cursor() as cur:
        cur.execute("DELETE FROM planned_lessons WHERE group_id=%s", [gid])
        cur.execute("DELETE FROM groups WHERE id=%s", [gid])
        cur.execute("DELETE FROM teachers WHERE id=%s", [tid])
        cur.execute("DELETE FROM directions WHERE id=%s", [did])


def test_wipe_one_offs_clears_reschedule_sub_and_marker(group_with_group):
    from apps.scheduling import repository
    gid, tid = group_with_group
    # разовый перенос (moved_from_date) на seq=3
    PlannedLesson.objects.filter(group_id=gid, seq=3).update(
        moved_from_date='2026-07-20', substitute_teacher_id=tid)
    # маркер отмены в диапазоне
    now = datetime.datetime(2026, 7, 1, 12, 0)
    PlannedLesson.objects.create(group_id=gid, seq=None, lesson_number=None,
        scheduled_date='2026-07-22', scheduled_time=datetime.time(18, 0),
        teacher_id=tid, status='cancelled', created_at=now, updated_at=now)

    repository.wipe_one_offs(gid, date_from=datetime.date(2026, 7, 21))

    r3 = PlannedLesson.objects.get(group_id=gid, seq=3)
    assert r3.moved_from_date is None
    assert r3.substitute_teacher_id is None
    assert not PlannedLesson.objects.filter(group_id=gid, status='cancelled').exists()
    # голова (seq=1, дата 07.07) не тронута
    assert PlannedLesson.objects.filter(group_id=gid, seq=1).exists()


def test_wipe_one_offs_from_seq_scopes_by_position_not_date(group_with_group):
    # from_seq берёт курсовые строки по позиции (seq>=from_seq), игнорируя дату
    # полностью (в отличие от ветки без from_seq, скоупящейся по scheduled_date).
    from apps.scheduling import repository
    gid, tid = group_with_group
    # seq=3 (21.07) — входит в хвост from_seq=3.
    PlannedLesson.objects.filter(group_id=gid, seq=3).update(
        moved_from_date='2026-07-20', substitute_teacher_id=tid)
    # seq=1 (07.07) — до from_seq, не должен трогаться, хотя date_from=01.07
    # формально включает и его дату.
    PlannedLesson.objects.filter(group_id=gid, seq=1).update(
        substitute_teacher_id=tid)

    repository.wipe_one_offs(gid, date_from=datetime.date(2026, 7, 1), from_seq=3)

    r3 = PlannedLesson.objects.get(group_id=gid, seq=3)
    assert r3.moved_from_date is None
    assert r3.substitute_teacher_id is None
    r1 = PlannedLesson.objects.get(group_id=gid, seq=1)
    assert r1.substitute_teacher_id == tid


def test_wipe_one_offs_respects_date_to_upper_bound(group_with_group):
    # Маркер и разовая замена ПОСЛЕ date_to не должны сбрасываться.
    from apps.scheduling import repository
    gid, tid = group_with_group
    now = datetime.datetime(2026, 7, 1, 12, 0)
    PlannedLesson.objects.create(group_id=gid, seq=None, lesson_number=None,
        scheduled_date='2026-07-30', scheduled_time=datetime.time(18, 0),
        teacher_id=tid, status='cancelled', created_at=now, updated_at=now)
    PlannedLesson.objects.filter(group_id=gid, seq=4).update(
        moved_from_date='2026-07-27', substitute_teacher_id=tid)

    repository.wipe_one_offs(
        gid, date_from=datetime.date(2026, 7, 1), date_to=datetime.date(2026, 7, 21))

    # 30.07 вне [date_from, date_to] — маркер остаётся.
    assert PlannedLesson.objects.filter(group_id=gid, status='cancelled',
                                         scheduled_date='2026-07-30').exists()
    # seq=4 (28.07) вне диапазона — разовая замена/перенос не сброшены.
    r4 = PlannedLesson.objects.get(group_id=gid, seq=4)
    assert r4.moved_from_date is not None
    assert r4.substitute_teacher_id == tid
