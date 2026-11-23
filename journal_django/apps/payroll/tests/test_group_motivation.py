"""Групповые версии: паритет, границы дат, ручные суммы и доступ к API."""
import datetime as dt
from dataclasses import replace
from decimal import Decimal as D

import pytest

from apps.core.utils.dates import MSK, msk_now
from apps.payroll.engine import LessonInput, legacy_lesson_pay, rates_on
from apps.payroll.group_engine import GroupRateCard, group_lesson_pay
from apps.payroll.models import GroupPayRateVersion, Payroll
from apps.payroll.recalc import recalculate
from apps.payroll.tests.test_motivation_integration import school, _lesson

DAY = dt.date(2026, 10, 5)
CARD = GroupRateCard(id=1, effective_from=DAY)


def lesson(**kwargs):
    return replace(LessonInput(teacher_id=1, group_id=1, lesson_date=DAY,
                              lesson_number=D('1'), is_individual=False, direction_id=None,
                              direction_name=None, submitted_at=None, submitted_by_token='admin-imported',
                              present_count=1, total_students=2), **kwargs)


@pytest.mark.parametrize('total,present', [(0, 0), (1, 0), (1, 1), (2, 1), (2, 2), (3, 1), (3, 3), (5, 4)])
@pytest.mark.parametrize('minutes', [45, 60, 90])
@pytest.mark.parametrize('kind,token', [('regular', 'acct:1'), ('extra', 'extra:1'), ('extra', 'makeup:1'), ('burned', 'burn:1')])
def test_defaults_match_legacy(total, present, minutes, kind, token):
    data = lesson(total_students=total, present_count=present, duration_minutes=minutes,
                  lesson_type=kind, submitted_by_token=token,
                  submitted_at=dt.datetime(2026, 10, 6, 12, tzinfo=MSK))
    actual, old = group_lesson_pay(data, CARD), legacy_lesson_pay(data)
    assert (actual.payment, actual.penalty) == (old.payment, old.penalty)


def test_custom_limit_and_half_priority():
    card = replace(CARD, small_group_limit=3, small_full_rate=D('900'),
                   small_partial_rate=D('400'), half_lesson_rate=D('275.25'))
    assert group_lesson_pay(lesson(total_students=3, present_count=3), card).payment == D('900')
    assert group_lesson_pay(lesson(total_students=3, present_count=2), card).payment == D('400')
    assert group_lesson_pay(lesson(total_students=3, present_count=2, duration_minutes=45), card).payment == D('550.50')


def test_penalty_source_and_zero_attendance():
    card = replace(CARD, penalty_mode='per_lesson', penalty_amount=D('75.50'))
    late = lesson(present_count=2, submitted_by_token='acct:1',
                  submitted_at=dt.datetime(2026, 10, 6, 12, tzinfo=MSK))
    assert group_lesson_pay(late, card).penalty == D('75.50')
    assert group_lesson_pay(replace(late, submitted_by_token='admin-imported'), card).penalty == 0
    assert group_lesson_pay(replace(late, present_count=0), card).penalty == 0


def test_rates_selected_by_lesson_day():
    later = replace(CARD, id=2, effective_from=DAY + dt.timedelta(days=1))
    assert rates_on([later, CARD], DAY) == CARD
    assert rates_on([CARD, later], later.effective_from) == later
    assert rates_on([CARD], DAY - dt.timedelta(days=1)) is None


@pytest.mark.django_db
def test_group_recalc_history_snapshot_manual_and_fallback(school):
    from apps.payroll import repository
    version = GroupPayRateVersion.objects.create(effective_from=DAY, half_lesson_rate=D('310.25'))
    lid = _lesson(school, 'group', day=DAY)
    before = _lesson(school, 'group', day=DAY - dt.timedelta(days=1))
    recalculate(lesson_ids=[lid, before])
    p = Payroll.objects.get(lesson_id=lid)
    assert p.payment == D('310.25')
    assert p.group_rate_snapshot['version_id'] == version.id
    assert p.group_rate_snapshot['inputs']['present_count'] == 1
    assert Payroll.objects.get(lesson_id=before).rule_note == ''
    assert recalculate(lesson_ids=[lid])['changed'] == 0
    repository.update_payroll(p.id, {'payment': D('999')})
    recalculate(lesson_ids=[lid])
    p.refresh_from_db()
    assert p.payment == D('999') and p.calc_payment == D('310.25') and p.is_manual
    repository.reset_payroll(p.id)
    p.refresh_from_db()
    assert p.payment == D('310.25') and not p.is_manual
    version.delete()  # доменный API такую прошлую версию удалить не разрешает
    recalculate(lesson_ids=[lid])
    p.refresh_from_db()
    assert p.payment == D('250') and p.rule_note == '' and p.group_rate_snapshot == {}


def payload(day):
    return dict(effective_from=day.isoformat(), calculation_method='attendance_v1', small_group_limit=2,
                small_full_rate='500', small_partial_rate='300', per_student_rate='200',
                half_lesson_rate='250', makeup_rate='200', burned_rate='200',
                penalty_enabled=True, penalty_mode='per_student', penalty_amount='40')


URL = '/api/admin/payroll/group-rate-versions'


@pytest.fixture
def group_admin(superadmin_client):
    yield superadmin_client
    # Общая account-фикстура удаляет учётку сырым SQL; сначала убираем её FK.
    GroupPayRateVersion.objects.all().delete()


@pytest.mark.django_db
def test_api_versions_dates_permissions_preview(superadmin_client, manager_client, teacher_client):
    today = msk_now().date()
    assert manager_client.get(URL).status_code == 403
    assert teacher_client.get(URL).status_code == 403
    assert manager_client.post(URL + '/preview', payload(today), format='json').status_code == 403
    response = superadmin_client.post(URL + '/preview', payload(today), format='json')
    assert response.status_code == 200 and len(response.json()['results']) == 5
    assert not GroupPayRateVersion.objects.exists()
    assert superadmin_client.post(URL, payload(today - dt.timedelta(days=1)), format='json').status_code == 400
    response = superadmin_client.post(URL, payload(today), format='json')
    assert response.status_code == 201, response.content
    pk = response.json()['id']
    assert superadmin_client.post(URL, payload(today), format='json').status_code == 400
    assert superadmin_client.patch(f'{URL}/{pk}', {'half_lesson_rate': '-1'}, format='json').status_code == 400
    assert superadmin_client.patch(f'{URL}/{pk}', {'small_group_limit': 0}, format='json').status_code == 400
    assert superadmin_client.patch(f'{URL}/{pk}', {'calculation_method': 'bad'}, format='json').status_code == 400
    assert superadmin_client.patch(f'{URL}/{pk}', {'half_lesson_rate': '350.25'}, format='json').status_code == 200
    assert superadmin_client.get(URL).json()['results'][0]['is_current']
    assert superadmin_client.delete(f'{URL}/{pk}').status_code == 200
    old = GroupPayRateVersion.objects.create(effective_from=today - dt.timedelta(days=1))
    assert superadmin_client.patch(f'{URL}/{old.id}', {'half_lesson_rate': '999'}, format='json').status_code == 400
    assert superadmin_client.delete(f'{URL}/{old.id}').status_code == 400


@pytest.mark.django_db
def test_api_change_only_group_from_effective_day(school, superadmin_client):
    today = msk_now().date()
    old = _lesson(school, 'group', day=today - dt.timedelta(days=1))
    current = _lesson(school, 'group', day=today)
    indiv = _lesson(school, 'indiv', day=today)
    future = _lesson(school, 'group', day=today + dt.timedelta(days=2))
    data = payload(today)
    data['half_lesson_rate'] = '350'
    first = superadmin_client.post(URL, data, format='json')
    assert first.status_code == 201, first.content
    assert Payroll.objects.get(lesson_id=current).payment == 350
    assert Payroll.objects.get(lesson_id=old).payment == 250
    assert Payroll.objects.get(lesson_id=indiv).payment == 250
    data['effective_from'] = (today + dt.timedelta(days=1)).isoformat()
    data['half_lesson_rate'] = '450'
    second = superadmin_client.post(URL, data, format='json')
    assert second.status_code == 201
    assert Payroll.objects.get(lesson_id=current).payment == 350
    assert Payroll.objects.get(lesson_id=future).payment == 450
    response = superadmin_client.delete(f"{URL}/{second.json()['id']}")
    assert response.status_code == 200
    assert Payroll.objects.get(lesson_id=future).payment == 350
    response = superadmin_client.delete(f"{URL}/{first.json()['id']}")
    assert response.status_code == 200
    assert Payroll.objects.get(lesson_id=current).payment == 250


@pytest.mark.django_db
def test_record_and_attendance_edits_use_group_version(school):
    from apps.lessons import services, repository as lessons_repo
    from apps.payroll import repository
    GroupPayRateVersion.objects.create(effective_from=DAY, half_lesson_rate=D('325.25'))
    result = services.record_lesson(
        lesson_date=DAY.isoformat(), teacher_id=school['teacher'], group_id=school['group'],
        original_teacher_id=None, lesson_number=1, lesson_duration_minutes=45,
        lesson_type='regular', record_url=None, submitted_by_token='admin-imported',
        submit_date=DAY.isoformat(), attendance=[{'student_id': school['student'], 'present': True}],
        skip_balance_check=True)
    assert result['payment'] == 325.25
    lid = result['lesson_id']
    payroll = Payroll.objects.get(lesson_id=lid)
    repository.update_payroll(payroll.id, {'payment': D('800')})
    lessons_repo.update_attendance_cell(lid, school['student'], False, skip_balance_check=True)
    payroll.refresh_from_db()
    assert payroll.is_manual and payroll.payment == 800 and payroll.calc_payment == 0
    assert payroll.group_rate_snapshot['inputs']['present_count'] == 0
    lessons_repo.update_attendance_cell(lid, school['student'], True, skip_balance_check=True)
    payroll.refresh_from_db()
    assert payroll.payment == 800 and payroll.calc_payment == D('325.25')


@pytest.mark.django_db
def test_moving_version_across_neighbor_recalculates_both_periods(school, group_admin):
    superadmin_client = group_admin
    today = msk_now().date()
    first_data = payload(today)
    first_data['half_lesson_rate'] = '300'
    first = superadmin_client.post(URL, first_data, format='json').json()
    second_data = payload(today + dt.timedelta(days=2))
    second_data['half_lesson_rate'] = '400'
    second = superadmin_client.post(URL, second_data, format='json').json()
    early = _lesson(school, 'group', day=today)
    middle = _lesson(school, 'group', day=today + dt.timedelta(days=2))
    late = _lesson(school, 'group', day=today + dt.timedelta(days=4))
    response = superadmin_client.patch(f"{URL}/{first['id']}",
        {'effective_from': (today + dt.timedelta(days=3)).isoformat()}, format='json')
    assert response.status_code == 200, response.content
    assert Payroll.objects.get(lesson_id=early).payment == 250  # до первой версии
    assert Payroll.objects.get(lesson_id=middle).payment == 400
    assert Payroll.objects.get(lesson_id=late).payment == 300
    response = superadmin_client.patch(f"{URL}/{first['id']}",
        {'effective_from': second['effective_from']}, format='json')
    assert response.status_code == 400  # конфликт откатывает перенос и пересчёт
    assert Payroll.objects.get(lesson_id=late).payment == 300


# ── Доп.урок сверх курса в обычной группе: прежняя плоская ставка ──────────────
# Решение владельца 2026-07-24 (extra_lessons.services.record): extra в обычной
# группе = 200 ₽ × присутствующих, без ветвления по 45 минутам и составу;
# «как индив» (total=1 → 500/250) — только у индив-групп.

def _extra(**kwargs):
    return lesson(lesson_type='extra', submitted_by_token='extra:1', **kwargs)


@pytest.mark.parametrize('minutes', [45, 60])
@pytest.mark.parametrize('present', [1, 2])
def test_group_extra_is_flat_per_student(minutes, present):
    data = _extra(total_students=present, present_count=present, duration_minutes=minutes)
    assert group_lesson_pay(data, CARD).payment == D('200') * present
    assert legacy_lesson_pay(data).payment == D('200') * present
    # Ставка за ученика из версии, а не half/small: 45 минут и «малая группа» не влияют.
    card = replace(CARD, per_student_rate=D('333.33'), half_lesson_rate=D('1'),
                   small_full_rate=D('1'), small_partial_rate=D('1'))
    res = group_lesson_pay(data, card)
    assert res.payment == (D('333.33') * present).quantize(D('0.01'))
    assert 'доп.урок сверх курса' in res.rule_note


def test_group_extra_late_report_penalty_by_common_rule():
    data = replace(_extra(present_count=2, total_students=2),
                   submitted_at=dt.datetime(2026, 10, 6, 12, tzinfo=MSK))
    res, old = group_lesson_pay(data, CARD), legacy_lesson_pay(data)
    assert (res.payment, res.penalty) == (D('400'), D('80'))
    assert (old.payment, old.penalty) == (D('400'), D('80'))


@pytest.mark.parametrize('minutes,expected', [(45, D('250')), (60, D('500'))])
def test_individual_extra_legacy_keeps_individual_rate(minutes, expected):
    data = _extra(is_individual=True, total_students=1, present_count=1, duration_minutes=minutes)
    assert legacy_lesson_pay(data).payment == expected


@pytest.fixture
def second_student(school):
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute("INSERT INTO students (full_name) VALUES ('__mot_s2__') RETURNING id")
        sid = cur.fetchone()[0]
    yield sid
    with connection.cursor() as cur:
        cur.execute('DELETE FROM lesson_attendance WHERE student_id = %s', [sid])
        cur.execute('DELETE FROM students WHERE id = %s', [sid])


def _group_extra(school, students, *, day, minutes):
    """Доп.урок сверх курса в обычной группе с начислением прежнего движка."""
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s, %s, %s, 1, %s, 'extra', 'extra:1') RETURNING id",
            [school['group'], school['teacher'], day, minutes])
        lid = cur.fetchone()[0]
        for sid in students:
            cur.execute('INSERT INTO lesson_attendance (lesson_id, student_id, present) '
                        'VALUES (%s, %s, true)', [lid, sid])
        cur.execute(
            'INSERT INTO payroll (lesson_id, teacher_id, total_students, present_count, '
            'payment, penalty) VALUES (%s, %s, %s, %s, %s, 0)',
            [lid, school['teacher'], len(students), len(students), 200 * len(students)])
    return lid


@pytest.mark.django_db
@pytest.mark.parametrize('minutes', [45, 60])
@pytest.mark.parametrize('two', [False, True])
def test_group_extra_with_version_and_fallback_without(school, second_student, minutes, two):
    students = [school['student'], second_student] if two else [school['student']]
    version = GroupPayRateVersion.objects.create(
        effective_from=DAY, per_student_rate=D('310'), half_lesson_rate=D('999'),
        small_full_rate=D('999'), small_partial_rate=D('999'))
    lid = _group_extra(school, students, day=DAY, minutes=minutes)
    recalculate(lesson_ids=[lid])
    p = Payroll.objects.get(lesson_id=lid)
    assert p.payment == D('310') * len(students) and p.rule_note
    version.delete()  # доменный API прошлую версию удалить не даёт — только для отката
    recalculate(lesson_ids=[lid])
    p.refresh_from_db()
    assert p.payment == D('200') * len(students)
    assert p.rule_note == '' and p.group_rate_snapshot == {}


@pytest.mark.django_db
def test_group_lesson_point_recalc_skips_cancellation_orphans(school):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    GroupPayRateVersion.objects.create(effective_from=DAY)
    lid = _lesson(school, 'group', day=DAY)
    with CaptureQueriesContext(connection) as ctx:
        recalculate(lesson_ids=[lid])
    assert Payroll.objects.get(lesson_id=lid).rule_note
    assert not [q for q in ctx.captured_queries if 'payroll_cancellations' in q['sql']]


# ── PATCH урока пересчитывает начисление сразу ───────────────────────────────

@pytest.mark.django_db
def test_update_lesson_date_and_teacher_recalculates_payroll(school):
    from django.db import connection
    from apps.lessons import services
    from apps.payroll import repository
    GroupPayRateVersion.objects.create(effective_from=DAY, half_lesson_rate=D('300'))
    GroupPayRateVersion.objects.create(effective_from=DAY + dt.timedelta(days=10),
                                       half_lesson_rate=D('410.50'))
    lid = _lesson(school, 'group', day=DAY + dt.timedelta(days=1))
    recalculate(lesson_ids=[lid])
    assert Payroll.objects.get(lesson_id=lid).payment == D('300')

    services.update_lesson(lid, {'lesson_date': DAY + dt.timedelta(days=12)})
    p = Payroll.objects.get(lesson_id=lid)
    assert p.payment == D('410.50') and p.calc_payment == D('410.50')
    assert p.group_rate_snapshot['inputs']['lesson_date'] == str(DAY + dt.timedelta(days=12))

    # Ручная сумма переживает правку даты (получатель тот же).
    repository.update_payroll(p.id, {'payment': D('777')})
    services.update_lesson(lid, {'lesson_date': DAY + dt.timedelta(days=2)})
    p.refresh_from_db()
    assert p.is_manual and p.payment == D('777') and p.calc_payment == D('300')

    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name, active) VALUES ('__mot_t2__', true) RETURNING id")
        t2 = cur.fetchone()[0]
    try:
        services.update_lesson(lid, {'teacher_id': t2})
        p.refresh_from_db()
        # Сменился получатель — ручная сумма прежнего к новому не переходит.
        assert p.teacher_id == t2 and not p.is_manual and p.payment == D('300')
    finally:
        with connection.cursor() as cur:
            cur.execute('UPDATE lessons SET teacher_id = %s WHERE teacher_id = %s',
                        [school['teacher'], t2])
            cur.execute('UPDATE payroll SET teacher_id = %s WHERE teacher_id = %s',
                        [school['teacher'], t2])
            cur.execute('DELETE FROM teachers WHERE id = %s', [t2])


@pytest.mark.django_db
def test_preview_has_no_duplicate_cases_for_limit_one():
    from apps.payroll.group_motivation import preview
    data = {f: getattr(GroupRateCard(id=0, effective_from=DAY), f)
            for f in GroupRateCard.__dataclass_fields__ if f != 'id'}
    data['small_group_limit'] = 1
    rows = preview(data)['results']
    keys = [(r['total'], r['present'], r['minutes']) for r in rows]
    assert len(keys) == len(set(keys))
    assert sum(1 for r in rows if r['present'] == 0) == 1
    assert len(preview({**data, 'small_group_limit': 2})['results']) == 5
