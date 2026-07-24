"""Оркестрация смены статуса: групповые членства деактивируются, индивидуальные
ОСТАЮТСЯ активными (двигается только расписание — ученик остаётся в группе), сделка
уходит в нужную стадию. Заморозка → deal 'frozen'; отказ → deal 'lost'."""
import datetime

import pytest
from django.db import connection
from django.db.models.functions import Now

from apps.memberships.models import GroupMembership
from apps.renewals import engine
from apps.renewals.models import RenewalDeal
from apps.students import services
from apps.students.models import Student


@pytest.fixture
def group_student():
    """Групповой student + активный membership + открытая сделка."""
    ids = {}
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name, active, total_lessons) "
                    "VALUES ('__st_dir__', true, 8) RETURNING id")
        ids['dir'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name, active, created_at) "
                    "VALUES ('__st_t__', true, NOW()) RETURNING id")
        ids['teacher'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, active, created_at, lesson_number_offset) "
            "VALUES ('__st_g__', %s, %s, false, 90, 1, true, NOW(), 0) RETURNING id",
            [ids['dir'], ids['teacher']])
        ids['group'] = cur.fetchone()[0]
    s = Student.objects.create(full_name='__st_stud__', enrollment_status='enrolled',
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
        cur.execute("DELETE FROM groups WHERE id=%s", [ids['group']])
        cur.execute("DELETE FROM teachers WHERE id=%s", [ids['teacher']])
        cur.execute("DELETE FROM directions WHERE id=%s", [ids['dir']])


@pytest.fixture
def indiv_student():
    """Индивид-группа (слот ср 10:00, 4 плановые строки) + student + активный
    membership + открытая сделка — для проверки каскада заморозки/разморозки
    индивидуального формата."""
    ids = {}
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name, active, total_lessons) "
                    "VALUES ('__ist_dir__', true, 8) RETURNING id")
        ids['dir'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name, active, created_at) "
                    "VALUES ('__ist_t__', true, NOW()) RETURNING id")
        ids['teacher'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, group_start_date, active, created_at, lesson_number_offset) "
            "VALUES ('__ist_g__', %s, %s, true, 90, 1, DATE '2026-07-01', true, NOW(), 0) RETURNING id",
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
    s = Student.objects.create(full_name='__ist_stud__', enrollment_status='enrolled',
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
def test_freeze_group_student(group_student):
    sid = group_student['student']
    services.change_student_status(
        sid, 'frozen',
        frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5),
        membership_ids=[group_student['membership']], actor=None)
    s = Student.objects.get(id=sid)
    assert s.enrollment_status == 'frozen'
    assert s.frozen_from == datetime.date(2026, 7, 8)
    assert s.frozen_until == datetime.date(2026, 8, 5)
    assert GroupMembership.objects.get(id=group_student['membership']).active is False
    deal = RenewalDeal.objects.get(student_id=sid, outcome_at__isnull=True)
    assert deal.stage.key == 'frozen'


@pytest.mark.django_db
def test_decline_group_student(group_student):
    sid = group_student['student']
    services.change_student_status(
        sid, 'declined', membership_ids=[group_student['membership']], actor=None)
    s = Student.objects.get(id=sid)
    assert s.enrollment_status == 'declined'
    assert s.frozen_from is None and s.frozen_until is None
    assert GroupMembership.objects.get(id=group_student['membership']).active is False
    deal = RenewalDeal.objects.get(student_id=sid)
    assert deal.stage.kind == 'lost'
    assert deal.outcome_at is not None


@pytest.mark.django_db
@pytest.mark.parametrize('bad_status', ['not_enrolled', 'garbage'])
def test_unknown_status_raises_and_changes_nothing(group_student, bad_status):
    """Неизвестный статус (в т.ч. удалённый миграцией 0015 'not_enrolled') обязан
    падать, а не молча зачислять ученика. Раньше финальная ветка была безусловным
    `else: enrollment_status = 'enrolled'`, поэтому любая опечатка/легаси-код
    тихо возвращали ушедшего ученика в обучение вместе с открытой сделкой."""
    sid = group_student['student']
    deal_before = RenewalDeal.objects.get(student_id=sid)

    with pytest.raises(ValueError):
        services.change_student_status(
            sid, bad_status, membership_ids=[group_student['membership']], actor=None)

    # Транзакция откатилась: ни статус, ни членство, ни сделка не поехали.
    s = Student.objects.get(id=sid)
    assert s.enrollment_status == 'enrolled'
    assert GroupMembership.objects.get(id=group_student['membership']).active is True
    deal_after = RenewalDeal.objects.get(student_id=sid)
    assert deal_after.stage_id == deal_before.stage_id
    assert deal_after.outcome_at is None


@pytest.mark.django_db
def test_resume_student_reenrolls(group_student):
    sid = group_student['student']
    services.change_student_status(
        sid, 'frozen', frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5),
        membership_ids=[group_student['membership']], actor=None)
    services.resume_student(sid, actual_resume_date=datetime.date(2026, 8, 5), actor=None)
    s = Student.objects.get(id=sid)
    assert s.enrollment_status == 'enrolled'
    assert s.frozen_from is None and s.frozen_until is None
    deal = RenewalDeal.objects.get(student_id=sid, outcome_at__isnull=True)
    assert deal.stage.key != 'frozen'
    # ГРУППОВОЕ членство НЕ реактивируется автоматически при разморозке —
    # возврат в общий класс делает админ вручную (спека student-status-lifecycle).
    # Асимметрия с индив-группой (test_resume_reactivates_individual_membership).
    assert GroupMembership.objects.get(id=group_student['membership']).active is False


@pytest.mark.django_db
def test_resume_ignores_unrelated_individual_group(group_student):
    """resume_student берёт только АКТИВНЫЕ индив-курсы. Давно-неактивная индив-группа,
    где ученик был раньше (перевёлся/бросил, членство active=False), в разморозку не
    попадает вообще — её строки (done / прошедшая pending) остаются на месте, ничего
    не падает."""
    from apps.scheduling.models import PlannedLesson

    sid = group_student['student']
    ff = datetime.date(2026, 7, 8)  # frozen_from заморозки основного ученика
    other = {}
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, active, created_at, lesson_number_offset) "
            "VALUES ('__st_g2_indiv__', %s, %s, true, 60, 1, true, NOW(), 0) RETURNING id",
            [group_student['dir'], group_student['teacher']])
        other['group'] = cur.fetchone()[0]
        # Неактивное членство того же ученика в этой индив-группе (перевёлся ранее).
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, active) "
            "VALUES (%s, %s, false) RETURNING id", [other['group'], sid])
        other['membership'] = cur.fetchone()[0]
        # (1) DONE-строка ВНУТРИ окна (>= frozen_from) — не двигается (не pending/overdue).
        cur.execute(
            "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
            "scheduled_time, teacher_id, status, created_at, updated_at) "
            "VALUES (%s, 1, 1.0, %s, '18:00', %s, 'done', NOW(), NOW()) RETURNING id",
            [other['group'], datetime.date(2026, 7, 15), group_student['teacher']])
        other['pl_done'] = cur.fetchone()[0]
        # (2) PENDING-строка в ПРОШЛОМ (< frozen_from) — вне окна перекладки.
        cur.execute(
            "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
            "scheduled_time, teacher_id, status, created_at, updated_at) "
            "VALUES (%s, 2, 2.0, %s, '18:00', %s, 'pending', NOW(), NOW()) RETURNING id",
            [other['group'], datetime.date(2026, 6, 1), group_student['teacher']])
        other['pl_past'] = cur.fetchone()[0]

    try:
        services.change_student_status(
            sid, 'frozen', frozen_from=ff, frozen_until=datetime.date(2026, 8, 5),
            membership_ids=[group_student['membership']], actor=None)
        # Не должно бросить исключение, несмотря на неактивную индив-группу.
        services.resume_student(sid, actual_resume_date=datetime.date(2026, 8, 5), actor=None)

        done = PlannedLesson.objects.get(id=other['pl_done'])
        past = PlannedLesson.objects.get(id=other['pl_past'])
        assert done.scheduled_date == datetime.date(2026, 7, 15)
        assert done.status == 'done'
        assert past.scheduled_date == datetime.date(2026, 6, 1)
        assert past.status == 'pending'
        # Заброшенная индив-группа неактивна — ни freeze, ни resume её не касаются.
        assert GroupMembership.objects.get(id=other['membership']).active is False
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM planned_lessons WHERE group_id=%s", [other['group']])
            cur.execute("DELETE FROM group_memberships WHERE id=%s", [other['membership']])
            cur.execute("DELETE FROM groups WHERE id=%s", [other['group']])


@pytest.mark.django_db
def test_freeze_individual_keeps_membership_active(indiv_student):
    """Регресс: при заморозке ИНДИВИДУАЛЬНОГО ученика он ОСТАЁТСЯ в группе (членство
    active=True) — двигается только расписание, не членство. Раньше freeze ошибочно
    деактивировал и индив-членства (remove_membership вызывался для всех подряд),
    выкидывая ученика из его личного курса. Разморозка тоже сохраняет членство
    активным (индив-членство вообще не покидает группу)."""
    from apps.scheduling.models import PlannedLesson
    sid = indiv_student['student']
    mid = indiv_student['membership']
    gid = indiv_student['group']
    services.change_student_status(
        sid, 'frozen', frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5),
        membership_ids=[mid], actor=None)
    # КЛЮЧЕВАЯ проверка бага: индив-членство ОСТАЛОСЬ активным (ученик в группе).
    assert GroupMembership.objects.get(id=mid).active is True
    # При этом хвост курса переложен от frozen_until: seq1 (до окна) неподвижен,
    # seq2 уехал на 2026-08-05 — расписание сдвинуто, членство нет.
    rows = {r.seq: r for r in PlannedLesson.objects.filter(group_id=gid, seq__isnull=False)}
    assert rows[1].scheduled_date == datetime.date(2026, 7, 1)
    assert rows[2].scheduled_date == datetime.date(2026, 8, 5)

    services.resume_student(sid, actual_resume_date=datetime.date(2026, 8, 5), actor=None)
    s = Student.objects.get(id=sid)
    assert s.enrollment_status == 'enrolled'
    # Членство по-прежнему активно — оно никогда не покидало группу.
    assert GroupMembership.objects.get(id=mid).active is True


@pytest.mark.django_db
def test_freeze_ignores_inactive_individual_course(indiv_student):
    """Давно-завершённый индив-курс (членство active=False) не участвует ни в
    заморозке, ни в разморозке: и freeze, и resume берут только АКТИВНЫЕ индив-курсы.
    Завершённый курс остаётся неактивным и с нетронутым расписанием — иначе он
    ошибочно всплыл бы в ростерах/student_names_by_group."""
    from apps.scheduling.models import PlannedLesson

    sid = indiv_student['student']
    frozen_mid = indiv_student['membership']  # активный индив-курс — его и замораживаем

    # Второй, ДАВНО ЗАВЕРШЁННЫЙ индив-курс того же ученика: членство неактивно,
    # единственное занятие done.
    done_grp = {}
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, active, created_at, lesson_number_offset) "
            "VALUES ('__ist_done_g__', %s, %s, true, 60, 1, true, NOW(), 0) RETURNING id",
            [indiv_student['dir'], indiv_student['teacher']])
        done_grp['group'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, active) "
            "VALUES (%s, %s, false) RETURNING id", [done_grp['group'], sid])
        done_grp['membership'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
            "scheduled_time, teacher_id, status, created_at, updated_at) "
            "VALUES (%s, 1, 1.0, %s, '18:00', %s, 'done', NOW(), NOW()) RETURNING id",
            [done_grp['group'], datetime.date(2026, 7, 15), indiv_student['teacher']])
        done_grp['pl'] = cur.fetchone()[0]

    try:
        services.change_student_status(
            sid, 'frozen', frozen_from=datetime.date(2026, 7, 8),
            frozen_until=datetime.date(2026, 8, 5),
            membership_ids=[frozen_mid], actor=None)
        # Активный курс заморожен, но остался в группе (active=True); завершённый —
        # не тронут (был и остаётся неактивным).
        assert GroupMembership.objects.get(id=frozen_mid).active is True
        assert GroupMembership.objects.get(id=done_grp['membership']).active is False
        assert PlannedLesson.objects.get(id=done_grp['pl']).scheduled_date == datetime.date(2026, 7, 15)

        services.resume_student(sid, actual_resume_date=datetime.date(2026, 8, 5), actor=None)

        # Завершённый курс так и не тронут: членство неактивно, урок на месте.
        assert GroupMembership.objects.get(id=done_grp['membership']).active is False
        assert PlannedLesson.objects.get(id=done_grp['pl']).scheduled_date == datetime.date(2026, 7, 15)
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM planned_lessons WHERE group_id=%s", [done_grp['group']])
            cur.execute("DELETE FROM group_memberships WHERE id=%s", [done_grp['membership']])
            cur.execute("DELETE FROM groups WHERE id=%s", [done_grp['group']])


@pytest.mark.django_db
def test_freeze_freezes_all_active_individual_courses_together(indiv_student):
    """Заморозка ученика замораживает ВСЕ его активные индив-курсы разом, даже если в
    мастере выбран только один (membership_ids к индивидуальным не применяется —
    ученик уходит на паузу целиком). Оба курса: членство остаётся активным, хвост
    сдвигается. Так на разморозке нет неоднозначности «какой курс был заморожен» —
    все активные индив-курсы замороженного ученика = замороженные."""
    from apps.scheduling.models import PlannedLesson

    sid = indiv_student['student']
    a_mid = indiv_student['membership']  # курс A — единственный в membership_ids
    ff = datetime.date(2026, 7, 8)

    # Курс B — ВТОРОЙ активный индив-курс того же ученика (слот ср 18:00), НЕ выбран
    # в мастере. Его extra и курсовой хвост тоже должны заморозиться вместе с A.
    b = {}
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, group_start_date, active, created_at, lesson_number_offset) "
            "VALUES ('__ist_B_indiv__', %s, %s, true, 60, 1, DATE '2026-07-01', true, NOW(), 0) "
            "RETURNING id",
            [indiv_student['dir'], indiv_student['teacher']])
        b['group'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_schedule_slots (group_id, day_of_week, start_time, effective_from) "
            "VALUES (%s, 3, TIME '18:00', DATE '2000-01-01')", [b['group']])
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, active) "
            "VALUES (%s, %s, true) RETURNING id", [b['group'], sid])
        b['membership'] = cur.fetchone()[0]
        # Будущий EXTRA (seq NULL) внутри окна — заморозка его отменяет (шаг «а»).
        cur.execute(
            "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
            "scheduled_time, teacher_id, status, created_at, updated_at) "
            "VALUES (%s, NULL, NULL, %s, '18:00', %s, 'pending', NOW(), NOW()) RETURNING id",
            [b['group'], datetime.date(2026, 7, 10), indiv_student['teacher']])
        b['extra'] = cur.fetchone()[0]
        # Курсовой хвост (pending, >= frozen_from) — заморозка его перекладывает (шаг «б»).
        for seq, d in [(1, '2026-07-15'), (2, '2026-07-22')]:
            cur.execute(
                "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
                "scheduled_time, teacher_id, status, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, '18:00', %s, 'pending', NOW(), NOW()) RETURNING id",
                [b['group'], seq, seq, d, indiv_student['teacher']])
            b[f'tail{seq}'] = cur.fetchone()[0]

    try:
        # В membership_ids только курс A, но заморозиться должны ОБА индив-курса.
        services.change_student_status(
            sid, 'frozen', frozen_from=ff, frozen_until=datetime.date(2026, 8, 5),
            membership_ids=[a_mid], actor=None)
        # Оба членства активны — индив-формат остаётся в группе.
        assert GroupMembership.objects.get(id=a_mid).active is True
        assert GroupMembership.objects.get(id=b['membership']).active is True
        # Курс B ТОЖЕ заморожен, хотя не был в membership_ids: extra отменён,
        # хвост переложен от frozen_until (2026-08-05) по слоту ср 18:00.
        assert PlannedLesson.objects.get(id=b['extra']).status == 'cancelled'
        assert PlannedLesson.objects.get(id=b['tail1']).scheduled_date == datetime.date(2026, 8, 5)
        assert PlannedLesson.objects.get(id=b['tail2']).scheduled_date == datetime.date(2026, 8, 12)

        # Разморозка досрочно (07-29, ср) перекладывает хвост B обратно от этой даты.
        services.resume_student(sid, actual_resume_date=datetime.date(2026, 7, 29), actor=None)
        assert GroupMembership.objects.get(id=b['membership']).active is True
        assert PlannedLesson.objects.get(id=b['tail1']).scheduled_date == datetime.date(2026, 7, 29)
        assert PlannedLesson.objects.get(id=b['tail2']).scheduled_date == datetime.date(2026, 8, 5)
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM planned_lessons WHERE group_id=%s", [b['group']])
            cur.execute("DELETE FROM group_memberships WHERE id=%s", [b['membership']])
            cur.execute("DELETE FROM group_schedule_slots WHERE group_id=%s", [b['group']])
            cur.execute("DELETE FROM groups WHERE id=%s", [b['group']])


@pytest.mark.django_db
def test_change_status_enrolled_on_frozen_is_rejected(group_student):
    """Прямая смена frozen→enrolled через change_student_status запрещена: она
    минует каскад resume_student (перекладка хвоста расписания, стадия сделки) →
    тихий рассинхрон. Разморозка только через resume_student()."""
    sid = group_student['student']
    services.change_student_status(
        sid, 'frozen', frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5),
        membership_ids=[group_student['membership']], actor=None)
    with pytest.raises(ValueError):
        services.change_student_status(sid, 'enrolled', actor=None)
