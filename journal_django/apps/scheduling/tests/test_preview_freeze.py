"""Дран-предпросмотр заморозки индивид-группы (preview_freeze): НЕ пишет в БД,
только считает. lesson_on_frozen_from — есть ли курсовой урок ровно на frozen_from;
first_lesson_after_resume — первая дата хвоста после перекладки от frozen_until.

Фикстура повторяет indiv_group из test_freeze_scheduling.py (слот ср 10:00,
4 курсовые строки ср., еженедельно, + extra в окне) — те же даты/слот, чтобы
предсказать точную дату перекладки, как в test_freeze_relays_tail_and_cancels_extra."""
import datetime

import pytest
from django.db import connection

from apps.scheduling import repository as sched_repo
from apps.scheduling.models import PlannedLesson
from apps.scheduling.occurrences import DONE, PENDING


@pytest.fixture
def indiv_group():
    """Индивид-группа со слотом среда 10:00 и 4 плановыми строками (ср., еженедельно)."""
    ids = {}
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name, is_individual, active, total_lessons) "
                    "VALUES ('__prev_dir__', true, true, 8) RETURNING id")
        ids['dir'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name, active, created_at) "
                    "VALUES ('__prev_t__', true, NOW()) RETURNING id")
        ids['teacher'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, group_start_date, active, created_at) "
            "VALUES ('__prev_g__', %s, %s, true, 90, 1, DATE '2026-07-01', true, NOW()) RETURNING id",
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
    # extra в окне заморозки (seq NULL) — не курсовая строка
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
def test_lesson_on_frozen_from_true_when_date_matches(indiv_group):
    """frozen_from ровно на дату курсового урока (seq2, 2026-07-08) → True."""
    res = sched_repo.preview_freeze(
        indiv_group['group'],
        frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5))
    assert res['lesson_on_frozen_from'] is True


@pytest.mark.django_db
def test_lesson_on_frozen_from_false_when_no_lesson(indiv_group):
    """frozen_from на дату без курсового урока (2026-07-09) → False.
    Extra 2026-07-10 (seq NULL) тоже не считается уроком-предупреждением."""
    res = sched_repo.preview_freeze(
        indiv_group['group'],
        frozen_from=datetime.date(2026, 7, 9),
        frozen_until=datetime.date(2026, 8, 5))
    assert res['lesson_on_frozen_from'] is False


@pytest.mark.django_db
def test_first_lesson_after_resume_matches_relay(indiv_group):
    """Хвост seq2..4 перекладывается от frozen_until=2026-08-05 (среда) по слоту
    ср 10:00 → первая дата 2026-08-05 (как в test_freeze_relays_tail_and_cancels_extra)."""
    res = sched_repo.preview_freeze(
        indiv_group['group'],
        frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5))
    assert res['first_lesson_after_resume'] == datetime.date(2026, 8, 5)


@pytest.mark.django_db
def test_preview_does_not_write(indiv_group):
    """Ключевой инвариант: preview_freeze НИЧЕГО не пишет. После вызова все
    строки — на исходных датах/статусах (в отличие от freeze_individual_group)."""
    gid = indiv_group['group']
    before = {
        r.id: (r.scheduled_date, r.status)
        for r in PlannedLesson.objects.filter(group_id=gid)
    }
    sched_repo.preview_freeze(
        gid,
        frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5))
    after = {
        r.id: (r.scheduled_date, r.status)
        for r in PlannedLesson.objects.filter(group_id=gid)
    }
    assert after == before
    # Точечно: хвост НЕ переехал, extra НЕ отменён (в отличие от реальной заморозки)
    rows = {r.seq: r for r in PlannedLesson.objects.filter(
        group_id=gid, seq__isnull=False)}
    assert rows[2].scheduled_date == datetime.date(2026, 7, 8)
    assert rows[3].scheduled_date == datetime.date(2026, 7, 15)
    assert rows[4].scheduled_date == datetime.date(2026, 7, 22)
    extra = PlannedLesson.objects.get(group_id=gid, seq__isnull=True)
    assert extra.status == PENDING


@pytest.mark.django_db
def test_first_lesson_none_when_no_open_slot(indiv_group):
    """Нет ОТКРЫТОГО слота (effective_to закрыт) → хвост некуда перекладывать →
    first_lesson_after_resume=None (паритет с freeze: relay пропускается)."""
    gid = indiv_group['group']
    from apps.groups.models import GroupScheduleSlot
    GroupScheduleSlot.objects.filter(group_id=gid).update(
        effective_to=datetime.date(2026, 7, 5))
    res = sched_repo.preview_freeze(
        gid,
        frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5))
    assert res['first_lesson_after_resume'] is None


@pytest.mark.django_db
def test_first_lesson_none_when_no_tail(indiv_group):
    """Нет хвоста в окне (frozen_from после всех курсовых строк) →
    first_lesson_after_resume=None, lesson_on_frozen_from=False."""
    res = sched_repo.preview_freeze(
        indiv_group['group'],
        frozen_from=datetime.date(2026, 8, 1),
        frozen_until=datetime.date(2026, 8, 20))
    assert res['first_lesson_after_resume'] is None
    assert res['lesson_on_frozen_from'] is False


@pytest.mark.django_db
def test_first_lesson_none_when_tail_all_done(indiv_group):
    """Весь курсовой хвост done (перекладывать нечего) → None, не падает."""
    gid = indiv_group['group']
    PlannedLesson.objects.filter(group_id=gid, seq__isnull=False).update(status=DONE)
    res = sched_repo.preview_freeze(
        gid,
        frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5))
    assert res['first_lesson_after_resume'] is None
