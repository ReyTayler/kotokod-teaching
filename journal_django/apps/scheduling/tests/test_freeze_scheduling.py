"""Заморозка индивид-группы: PENDING-строки в окне (>= frozen_from) отменяются/
перекладываются; extra (seq NULL) в окне → CANCELLED; курсовой хвост едет от
resume_date по слоту. Проведённые (done) и всё до frozen_from — неподвижны."""
import datetime

import pytest
from django.db import connection

from apps.scheduling import repository as sched_repo
from apps.scheduling.models import PlannedLesson
from apps.scheduling.occurrences import CANCELLED, DONE, PENDING


@pytest.fixture
def indiv_group():
    """Индивид-группа со слотом среда 10:00 и 4 плановыми строками (ср., еженедельно)."""
    ids = {}
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name, is_individual, active, total_lessons) "
                    "VALUES ('__frz_dir__', true, true, 8) RETURNING id")
        ids['dir'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name, active, created_at) "
                    "VALUES ('__frz_t__', true, NOW()) RETURNING id")
        ids['teacher'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, group_start_date, active, created_at) "
            "VALUES ('__frz_g__', %s, %s, true, 90, 1, DATE '2026-07-01', true, NOW()) RETURNING id",
            [ids['dir'], ids['teacher']])
        ids['group'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_schedule_slots (group_id, day_of_week, start_time, effective_from) "
            "VALUES (%s, 3, TIME '10:00', DATE '2000-01-01')", [ids['group']])
    now = datetime.datetime(2026, 7, 1, 12, 0)
    for seq, d in [(1, '2026-07-01'), (2, '2026-07-08'), (3, '2026-07-15'), (4, '2026-07-22')]:
        PlannedLesson.objects.create(
            group_id=ids['group'], seq=seq, lesson_number=seq,
            scheduled_date=d, scheduled_time=datetime.time(10, 0),
            teacher_id=ids['teacher'], status=PENDING, created_at=now, updated_at=now)
    # extra в окне заморозки
    PlannedLesson.objects.create(
        group_id=ids['group'], seq=None, lesson_number=None,
        scheduled_date='2026-07-10', scheduled_time=datetime.time(15, 0),
        teacher_id=ids['teacher'], status=PENDING, created_at=now, updated_at=now)
    yield ids
    with connection.cursor() as cur:
        cur.execute("DELETE FROM planned_lessons WHERE group_id=%s", [ids['group']])
        cur.execute("DELETE FROM group_schedule_slots WHERE group_id=%s", [ids['group']])
        cur.execute("DELETE FROM groups WHERE id=%s", [ids['group']])
        cur.execute("DELETE FROM teachers WHERE id=%s", [ids['teacher']])
        cur.execute("DELETE FROM directions WHERE id=%s", [ids['dir']])


@pytest.mark.django_db
def test_freeze_relays_tail_and_cancels_extra(indiv_group):
    gid = indiv_group['group']
    # Заморозка с 2026-07-08 до 2026-08-05 (среда). Окно: seq2,3,4 + extra 07-10.
    relaid = sched_repo.freeze_individual_group(
        gid, frozen_from=datetime.date(2026, 7, 8),
        resume_date=datetime.date(2026, 8, 5))
    # Реально переложены 3 курсовые строки (seq2,3,4) — положительный счётчик.
    assert relaid == 3

    rows = {r.seq: r for r in PlannedLesson.objects.filter(
        group_id=gid, seq__isnull=False).order_by('seq')}
    # seq1 (до окна) не двигается
    assert rows[1].scheduled_date == datetime.date(2026, 7, 1)
    # хвост seq2..4 переложен от 2026-08-05 еженедельно
    assert rows[2].scheduled_date == datetime.date(2026, 8, 5)
    assert rows[3].scheduled_date == datetime.date(2026, 8, 12)
    assert rows[4].scheduled_date == datetime.date(2026, 8, 19)
    # extra в окне отменён
    extra = PlannedLesson.objects.get(group_id=gid, seq__isnull=True,
                                      scheduled_date=datetime.date(2026, 7, 10))
    assert extra.status == CANCELLED


@pytest.mark.django_db
def test_freeze_keeps_done_rows(indiv_group):
    gid = indiv_group['group']
    PlannedLesson.objects.filter(group_id=gid, seq=2).update(status=DONE)
    # Окно: seq2 (done, неподвижна), seq3, seq4 → переложены 2 строки.
    relaid = sched_repo.freeze_individual_group(
        gid, frozen_from=datetime.date(2026, 7, 8),
        resume_date=datetime.date(2026, 8, 5))
    assert relaid == 2
    done = PlannedLesson.objects.get(group_id=gid, seq=2)
    assert done.status == DONE
    assert done.scheduled_date == datetime.date(2026, 7, 8)  # не тронут


@pytest.mark.django_db
def test_resume_relays_tail_from_actual_resume_date(indiv_group):
    """resume_individual_group — та же перекладка хвоста, только именем аргумента
    actual_resume_date вместо resume_date; frozen_from — та же нижняя граница окна."""
    gid = indiv_group['group']
    relaid = sched_repo.resume_individual_group(
        gid, actual_resume_date=datetime.date(2026, 8, 5),
        frozen_from=datetime.date(2026, 7, 8))
    # Переложены 3 курсовые строки — сигнал «группа участвовала в разморозке».
    assert relaid == 3

    rows = {r.seq: r for r in PlannedLesson.objects.filter(
        group_id=gid, seq__isnull=False).order_by('seq')}
    assert rows[1].scheduled_date == datetime.date(2026, 7, 1)  # до окна не тронут
    assert rows[2].scheduled_date == datetime.date(2026, 8, 5)
    assert rows[3].scheduled_date == datetime.date(2026, 8, 12)
    assert rows[4].scheduled_date == datetime.date(2026, 8, 19)


@pytest.mark.django_db
def test_freeze_cancels_extra_but_skips_relay_when_no_open_slot(indiv_group):
    """Если у группы нет ОТКРЫТОГО слота (effective_to закрыт) — extra/маркеры
    в окне всё равно отменяются (это первый, безусловный шаг), а курсовой хвост
    НЕ перекладывается (некуда — неизвестен день недели/время). Партиальный
    коммит внутри одной atomic-транзакции: намеренное поведение, не баг."""
    gid = indiv_group['group']
    from apps.groups.models import GroupScheduleSlot
    GroupScheduleSlot.objects.filter(group_id=gid).update(
        effective_to=datetime.date(2026, 7, 5))  # закрываем единственный слот

    # Хвост в окне есть, но открытого слота нет → перекладки не было → 0.
    relaid = sched_repo.freeze_individual_group(
        gid, frozen_from=datetime.date(2026, 7, 8),
        resume_date=datetime.date(2026, 8, 5))
    assert relaid == 0

    # extra всё равно отменён
    extra = PlannedLesson.objects.get(group_id=gid, seq__isnull=True,
                                      scheduled_date=datetime.date(2026, 7, 10))
    assert extra.status == CANCELLED
    # хвост НЕ перелёг — остался на исходных датах внутри окна заморозки
    rows = {r.seq: r for r in PlannedLesson.objects.filter(
        group_id=gid, seq__isnull=False).order_by('seq')}
    assert rows[2].scheduled_date == datetime.date(2026, 7, 8)
    assert rows[3].scheduled_date == datetime.date(2026, 7, 15)
    assert rows[4].scheduled_date == datetime.date(2026, 7, 22)


@pytest.mark.django_db
def test_freeze_cancels_extra_when_no_tail_to_relay(indiv_group):
    """Если весь курсовой хвост уже done (перекладывать нечего) — extra в окне
    всё равно отменяется, функция не падает на пустом хвосте."""
    gid = indiv_group['group']
    PlannedLesson.objects.filter(group_id=gid, seq__isnull=False).update(status=DONE)

    # Весь хвост done → перекладывать нечего → 0 (но extra всё равно отменён).
    relaid = sched_repo.freeze_individual_group(
        gid, frozen_from=datetime.date(2026, 7, 8),
        resume_date=datetime.date(2026, 8, 5))
    assert relaid == 0

    extra = PlannedLesson.objects.get(group_id=gid, seq__isnull=True,
                                      scheduled_date=datetime.date(2026, 7, 10))
    assert extra.status == CANCELLED
