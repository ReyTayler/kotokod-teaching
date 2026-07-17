"""Оркестрация смены статуса: членства деактивируются, индив-хвост едет, сделка
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
        cur.execute("INSERT INTO directions (name, is_individual, active, total_lessons) "
                    "VALUES ('__st_dir__', false, true, 8) RETURNING id")
        ids['dir'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name, active, created_at) "
                    "VALUES ('__st_t__', true, NOW()) RETURNING id")
        ids['teacher'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, active, created_at) "
            "VALUES ('__st_g__', %s, %s, false, 90, 1, true, NOW()) RETURNING id",
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
        cur.execute("INSERT INTO directions (name, is_individual, active, total_lessons) "
                    "VALUES ('__ist_dir__', true, true, 8) RETURNING id")
        ids['dir'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name, active, created_at) "
                    "VALUES ('__ist_t__', true, NOW()) RETURNING id")
        ids['teacher'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, group_start_date, active, created_at) "
            "VALUES ('__ist_g__', %s, %s, true, 90, 1, DATE '2026-07-01', true, NOW()) RETURNING id",
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
    """resume_student берёт индив-членства БЕЗ фильтра active — значит цепляет и
    давно-неактивную индив-группу, где ученик был раньше (перевёлся/бросил). В
    реалистичном случае это no-op: relay трогает только pending/overdue строки с
    scheduled_date >= frozen_from, а у заброшенной группы таких нет. Проверяем, что
    ничего не падает и её строки (done / прошедшая pending) остаются на месте."""
    from apps.scheduling.models import PlannedLesson

    sid = group_student['student']
    ff = datetime.date(2026, 7, 8)  # frozen_from заморозки основного ученика
    other = {}
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, active, created_at) "
            "VALUES ('__st_g2_indiv__', %s, %s, true, 60, 1, true, NOW()) RETURNING id",
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
        # Заброшенная индив-группа НЕ участвовала в этой заморозке (нет хвоста в
        # окне → resume_individual_group вернул 0) → её членство НЕ воскрешается.
        assert GroupMembership.objects.get(id=other['membership']).active is False
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM planned_lessons WHERE group_id=%s", [other['group']])
            cur.execute("DELETE FROM group_memberships WHERE id=%s", [other['membership']])
            cur.execute("DELETE FROM groups WHERE id=%s", [other['group']])


@pytest.mark.django_db
def test_resume_reactivates_individual_membership(indiv_student):
    """Индив-членство деактивируется при заморозке и ДОЛЖНО реактивироваться при
    разморозке — иначе у личного курса ученика 0 активных членств и никто не может
    записать урок, несмотря на свежепереложенный хвост (регресс Task 9)."""
    sid = indiv_student['student']
    mid = indiv_student['membership']
    services.change_student_status(
        sid, 'frozen', frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5),
        membership_ids=[mid], actor=None)
    # При заморозке индив-членство деактивировано.
    assert GroupMembership.objects.get(id=mid).active is False

    services.resume_student(sid, actual_resume_date=datetime.date(2026, 8, 5), actor=None)
    s = Student.objects.get(id=sid)
    assert s.enrollment_status == 'enrolled'
    # Ключевая проверка регресса: индив-членство снова активно.
    assert GroupMembership.objects.get(id=mid).active is True


@pytest.mark.django_db
def test_resume_reactivates_only_genuinely_frozen_indiv_group(indiv_student):
    """resume_student реактивирует ТОЛЬКО те индив-членства, чей курс реально был
    заморожен (хвост переложился, resume_individual_group вернул >0). Давно-
    завершённый индив-курс (active=False по окончании, без pending-хвоста в окне)
    воскрешать нельзя — иначе он ошибочно всплыл бы в ростерах/student_names_by_group.
    """
    from apps.scheduling.models import PlannedLesson  # noqa: F401

    sid = indiv_student['student']
    frozen_mid = indiv_student['membership']  # настоящий замораживаемый индив-курс

    # Второй, ДАВНО ЗАВЕРШЁННЫЙ индив-курс того же ученика: членство неактивно,
    # единственное занятие done → pending-хвоста в окне заморозки нет.
    done_grp = {}
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, active, created_at) "
            "VALUES ('__ist_done_g__', %s, %s, true, 60, 1, true, NOW()) RETURNING id",
            [indiv_student['dir'], indiv_student['teacher']])
        done_grp['group'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, active) "
            "VALUES (%s, %s, false) RETURNING id", [done_grp['group'], sid])
        done_grp['membership'] = cur.fetchone()[0]
        # DONE-занятие ВНУТРИ окна (>= frozen_from) — не pending/overdue, не двигается.
        cur.execute(
            "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
            "scheduled_time, teacher_id, status, created_at, updated_at) "
            "VALUES (%s, 1, 1.0, %s, '18:00', %s, 'done', NOW(), NOW())",
            [done_grp['group'], datetime.date(2026, 7, 15), indiv_student['teacher']])

    try:
        services.change_student_status(
            sid, 'frozen', frozen_from=datetime.date(2026, 7, 8),
            frozen_until=datetime.date(2026, 8, 5),
            membership_ids=[frozen_mid], actor=None)
        # Заморожен только настоящий индив-курс (по membership_ids); завершённый
        # как был неактивен, так и остаётся.
        assert GroupMembership.objects.get(id=frozen_mid).active is False
        assert GroupMembership.objects.get(id=done_grp['membership']).active is False

        services.resume_student(sid, actual_resume_date=datetime.date(2026, 8, 5), actor=None)

        # Настоящий замороженный курс — реактивирован (хвост переложился → >0).
        assert GroupMembership.objects.get(id=frozen_mid).active is True
        # Завершённый курс — НЕ воскрешён (resume_individual_group вернул 0).
        assert GroupMembership.objects.get(id=done_grp['membership']).active is False
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM planned_lessons WHERE group_id=%s", [done_grp['group']])
            cur.execute("DELETE FROM group_memberships WHERE id=%s", [done_grp['membership']])
            cur.execute("DELETE FROM groups WHERE id=%s", [done_grp['group']])


@pytest.mark.django_db
def test_resume_leaves_active_never_frozen_indiv_group_untouched(indiv_student):
    """Заморозка выбранного подмножества членств (wizard, per-membership чекбоксы):
    у ученика ДВА активных индив-курса, замораживают ТОЛЬКО один (membership_ids).
    Второй остаётся active=True — его расписание идёт своим чередом. resume_student
    НЕ должен трогать этот второй курс: он никогда не был заморожен (заморозка всегда
    деактивирует то, что трогает → active=True = не участвовал ни в какой заморозке).

    Без фильтра active=False resume_individual_group отменил бы легальный будущий
    extra в окне (шаг «а») и переложил бы курсовой хвост (шаг «б») ни в чём не
    повинного, параллельно идущего курса — реальная порча расписания. Red/green:
    без active=False этот тест падает, с ним — проходит."""
    from apps.scheduling.models import PlannedLesson

    sid = indiv_student['student']
    frozen_mid = indiv_student['membership']  # курс A — его и замораживаем
    ff = datetime.date(2026, 7, 8)            # frozen_from заморозки курса A

    # Курс B — ВТОРОЙ активный индив-курс того же ученика (открытый слот ср 18:00),
    # который НЕ замораживают. У него есть будущий extra (seq NULL) и курсовой хвост
    # внутри окна заморозки A — оба должны остаться нетронутыми.
    b = {}
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, lessons_per_week, group_start_date, active, created_at) "
            "VALUES ('__ist_B_indiv__', %s, %s, true, 60, 1, DATE '2026-07-01', true, NOW()) "
            "RETURNING id",
            [indiv_student['dir'], indiv_student['teacher']])
        b['group'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_schedule_slots (group_id, day_of_week, start_time, effective_from) "
            "VALUES (%s, 3, TIME '18:00', DATE '2000-01-01')", [b['group']])
        # АКТИВНОЕ членство — курс B идёт нормально, его не замораживали.
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, active) "
            "VALUES (%s, %s, true) RETURNING id", [b['group'], sid])
        b['membership'] = cur.fetchone()[0]
        # Будущий EXTRA (seq NULL + lesson_number NULL, CHECK seq_number_together)
        # ВНУТРИ окна (>= frozen_from) — при баге отменяется (шаг «а»).
        cur.execute(
            "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
            "scheduled_time, teacher_id, status, created_at, updated_at) "
            "VALUES (%s, NULL, NULL, %s, '18:00', %s, 'pending', NOW(), NOW()) RETURNING id",
            [b['group'], datetime.date(2026, 7, 10), indiv_student['teacher']])
        b['extra'] = cur.fetchone()[0]
        # Курсовой хвост (seq задан, pending, >= frozen_from) — при баге переезжает (шаг «б»).
        for seq, d in [(1, '2026-07-15'), (2, '2026-07-22')]:
            cur.execute(
                "INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, "
                "scheduled_time, teacher_id, status, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, '18:00', %s, 'pending', NOW(), NOW()) RETURNING id",
                [b['group'], seq, seq, d, indiv_student['teacher']])
            b[f'tail{seq}'] = cur.fetchone()[0]

    try:
        # Замораживаем ТОЛЬКО курс A (по membership_ids). Курс B не трогаем.
        services.change_student_status(
            sid, 'frozen', frozen_from=ff, frozen_until=datetime.date(2026, 8, 5),
            membership_ids=[frozen_mid], actor=None)
        # Курс B не участвовал в заморозке — членство осталось активным.
        assert GroupMembership.objects.get(id=b['membership']).active is True

        services.resume_student(sid, actual_resume_date=datetime.date(2026, 8, 5), actor=None)

        # Членство B всё ещё активно — его никто не должен был деактивировать/касаться.
        assert GroupMembership.objects.get(id=b['membership']).active is True
        # Будущий extra курса B НЕ отменён (при баге стал бы CANCELLED шагом «а»).
        assert PlannedLesson.objects.get(id=b['extra']).status == 'pending'
        # Курсовой хвост B на исходных датах (при баге переехал бы от 2026-08-05).
        assert PlannedLesson.objects.get(id=b['tail1']).scheduled_date == datetime.date(2026, 7, 15)
        assert PlannedLesson.objects.get(id=b['tail2']).scheduled_date == datetime.date(2026, 7, 22)
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM planned_lessons WHERE group_id=%s", [b['group']])
            cur.execute("DELETE FROM group_memberships WHERE id=%s", [b['membership']])
            cur.execute("DELETE FROM group_schedule_slots WHERE group_id=%s", [b['group']])
            cur.execute("DELETE FROM groups WHERE id=%s", [b['group']])


@pytest.mark.django_db
def test_resume_conflict_on_taken_indiv_slot_rolls_back_everything(indiv_student):
    """Если за время заморозки в ту же индив-группу легально зашёл ДРУГОЙ ученик
    (active=true, пока членство замороженного было active=false — add_membership
    прошёл бы, активных членств было 0), разморозка обязана упасть на инварианте
    ёмкости, а не создать двух активных. resume_student сам @transaction.atomic →
    IndividualGroupFull откатывает ВСЮ операцию: статус, сделка, расписание и
    частичные реактивации остаются в до-разморозочном состоянии."""
    from apps.memberships.exceptions import IndividualGroupFull
    from apps.scheduling.models import PlannedLesson

    sid = indiv_student['student']
    gid = indiv_student['group']
    mid = indiv_student['membership']

    services.change_student_status(
        sid, 'frozen', frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5),
        membership_ids=[mid], actor=None)
    assert GroupMembership.objects.get(id=mid).active is False

    # Пока ученик заморожен, в ту же индив-группу легально заходит другой ученик.
    other = Student.objects.create(full_name='__ist_other__', enrollment_status='enrolled',
                                   created_at=Now())
    other_m = GroupMembership.objects.create(group_id=gid, student_id=other.id, active=True)

    # До-разморозочное состояние для проверки полного отката.
    stage_before = RenewalDeal.objects.get(
        student_id=sid, outcome_at__isnull=True).stage.key
    seq2_before = PlannedLesson.objects.get(group_id=gid, seq=2).scheduled_date

    try:
        with pytest.raises(IndividualGroupFull):
            services.resume_student(
                sid, actual_resume_date=datetime.date(2026, 8, 26), actor=None)

        # ПОЛНЫЙ откат: ничего из разморозки не закоммитилось.
        s = Student.objects.get(id=sid)
        assert s.enrollment_status == 'frozen'
        assert s.frozen_from == datetime.date(2026, 7, 8)
        assert s.frozen_until == datetime.date(2026, 8, 5)
        assert GroupMembership.objects.get(id=mid).active is False
        assert RenewalDeal.objects.get(
            student_id=sid, outcome_at__isnull=True).stage.key == stage_before == 'frozen'
        # Расписание НЕ переложено на actual_resume_date=08-26 — осталось на 08-05.
        assert PlannedLesson.objects.get(group_id=gid, seq=2).scheduled_date == seq2_before
        assert seq2_before == datetime.date(2026, 8, 5)
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM group_memberships WHERE id=%s", [other_m.id])
            cur.execute("DELETE FROM students WHERE id=%s", [other.id])


@pytest.mark.django_db
def test_change_status_enrolled_on_frozen_is_rejected(group_student):
    """Прямая смена frozen→enrolled через change_student_status запрещена: она
    минует каскад resume_student (хвост расписания, реактивация членств, стадия
    сделки) → тихий рассинхрон. Разморозка только через resume_student()."""
    sid = group_student['student']
    services.change_student_status(
        sid, 'frozen', frozen_from=datetime.date(2026, 7, 8),
        frozen_until=datetime.date(2026, 8, 5),
        membership_ids=[group_student['membership']], actor=None)
    with pytest.raises(ValueError):
        services.change_student_status(sid, 'enrolled', actor=None)
