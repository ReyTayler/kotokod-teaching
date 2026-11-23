"""
«Мотивация» поверх БД: охват (индив + версия ставок), запись урока, ручная
правка, возврат к прежнему движку и API «Настроек → Мотивации».

Прошлое не меняется: версии через API — только с сегодняшнего дня; в тестах
пересчёта версия с прошлой даты заводится прямо ORM (так проверяется сам расчёт).
"""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection

from apps.core.utils.dates import msk_now
from apps.payroll.models import PayRateDirection, PayRateVersion, Payroll
from apps.payroll.recalc import recalculate

pytestmark = pytest.mark.django_db

D = Decimal
LESSON_DAY = datetime.date(2026, 10, 5)


@pytest.fixture
def school():
    """Преподаватель, направление, индив- и групповая группа, ученик."""
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name, active) VALUES ('__mot_t__', true) RETURNING id")
        tid = cur.fetchone()[0]
        cur.execute("INSERT INTO directions (name, total_lessons, active) "
                    "VALUES ('__mot_dir__', 16, true) RETURNING id")
        did = cur.fetchone()[0]
        groups = {}
        for key, indiv in (('indiv', True), ('group', False)):
            cur.execute(
                "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
                "lesson_duration_minutes, active, lesson_number_offset) "
                "VALUES (%s, %s, %s, %s, 45, true, 0) RETURNING id",
                [f'__mot_{key}__', did, tid, indiv])
            groups[key] = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name) VALUES ('__mot_s__') RETURNING id")
        sid = cur.fetchone()[0]
        for gid in groups.values():
            cur.execute('INSERT INTO group_memberships (group_id, student_id, lessons_done, active) '
                        'VALUES (%s, %s, 0, true)', [gid, sid])
    data = {'teacher': tid, 'direction': did, 'student': sid, **groups}
    yield data
    with connection.cursor() as cur:
        gids = list(groups.values())
        cur.execute('DELETE FROM payroll_personal_rate_terms WHERE group_id = ANY(%s)', [gids])
        cur.execute('DELETE FROM payroll_personal_rates WHERE group_id = ANY(%s)', [gids])
        cur.execute('DELETE FROM lesson_attendance WHERE student_id = %s', [sid])
        cur.execute('DELETE FROM payroll WHERE teacher_id = %s', [tid])
        cur.execute('DELETE FROM planned_lessons WHERE group_id = ANY(%s)', [gids])
        cur.execute('DELETE FROM lessons WHERE teacher_id = %s', [tid])
        cur.execute('DELETE FROM group_memberships WHERE student_id = %s', [sid])
        cur.execute('DELETE FROM groups WHERE id = ANY(%s)', [gids])
        cur.execute('DELETE FROM payroll_rate_directions WHERE direction_id = %s', [did])
        cur.execute('DELETE FROM directions WHERE id = %s', [did])
        cur.execute('DELETE FROM students WHERE id = %s', [sid])
        cur.execute('DELETE FROM teachers WHERE id = %s', [tid])


@pytest.fixture
def version():
    """Версия ставок с прошлой даты (только для теста расчёта — API так не даёт)."""
    v = PayRateVersion.objects.create(
        effective_from=datetime.date(2026, 9, 1), individual_rate=D('600'),
        makeup_rate=D('250'), burned_rate=D('150'), cancel_mode='percent',
        cancel_value=D('50'), penalty_enabled=False)
    yield v
    PayRateVersion.objects.filter(id=v.id).delete()


def _lesson(school, group_key, *, day=LESSON_DAY, payment=Decimal('250'), present=True):
    """Урок с одной строкой посещаемости и начислением прежнего движка."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s, %s, %s, 1, 45, 'regular', 'admin-imported') RETURNING id",
            [school[group_key], school['teacher'], day])
        lid = cur.fetchone()[0]
        cur.execute("INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s, %s, %s)",
                    [lid, school['student'], present])
        cur.execute(
            "INSERT INTO payroll (lesson_id, teacher_id, total_students, present_count, payment, penalty) "
            "VALUES (%s, %s, 1, %s, %s, 0)", [lid, school['teacher'], 1 if present else 0, payment])
    return lid


def _pay(lid):
    return Payroll.objects.get(lesson_id=lid)


def test_group_format_untouched(school, version):
    lid = _lesson(school, 'group', payment=D('250'))
    stats = recalculate(lesson_ids=[lid])
    assert stats['lessons'] == 0
    p = _pay(lid)
    assert p.payment == D('250.00') and p.rule_note == ''


def test_individual_before_first_version_untouched(school, version):
    lid = _lesson(school, 'indiv', day=datetime.date(2026, 8, 20), payment=D('250'))
    recalculate(lesson_ids=[lid])
    p = _pay(lid)
    assert p.payment == D('250.00') and p.rule_note == ''


def test_individual_with_version_fixed_rate_ignoring_duration(school, version):
    lid = _lesson(school, 'indiv', payment=D('250'))   # 45 мин: движок дал бы 250
    recalculate(lesson_ids=[lid])
    p = _pay(lid)
    assert p.payment == D('600.00')
    assert p.calc_payment == D('600.00')
    assert 'Индивидуальный урок' in p.rule_note


def test_direction_rate(school, version):
    PayRateDirection.objects.create(version=version, direction_id=school['direction'],
                                    individual_rate=D('700'))
    lid = _lesson(school, 'indiv')
    recalculate(lesson_ids=[lid])
    assert _pay(lid).payment == D('700.00')


def test_manual_survives_recalc_and_reset_restores(school, version):
    from apps.payroll import repository
    lid = _lesson(school, 'indiv')
    recalculate(lesson_ids=[lid])
    pid = _pay(lid).id
    repository.update_payroll(pid, {'payment': D('1000')})
    assert _pay(lid).is_manual
    recalculate(lesson_ids=[lid])
    p = _pay(lid)
    assert p.payment == D('1000.00') and p.calc_payment == D('600.00')
    repository.reset_payroll(pid)
    p = _pay(lid)
    assert not p.is_manual and p.payment == D('600.00')


def test_engine_lesson_manual_edit_survives_attendance_and_resets(school):
    """Урок прежнего движка (групповой формат без версии): правка суммы — ручная,
    расчёт запоминается; правка посещаемости ручную сумму не затирает, а расчёт
    обновляет; «Сбросить к расчёту» возвращает расчёт движка."""
    from apps.lessons import repository as lessons_repo
    from apps.payroll import repository
    lid = _lesson(school, 'group', payment=D('250'))
    pid = _pay(lid).id
    repository.update_payroll(pid, {'payment': D('900'), 'penalty': D('10')})
    p = _pay(lid)
    assert p.is_manual and p.payment == D('900.00') and p.penalty == D('10.00')
    assert p.calc_payment == D('250.00') and p.calc_penalty == D('0.00')

    lessons_repo.update_attendance_cell(lid, school['student'], False, skip_balance_check=True)
    p = _pay(lid)
    assert p.payment == D('900.00') and p.calc_payment == D('0.00')

    lessons_repo.update_attendance_cell(lid, school['student'], True, skip_balance_check=True)
    res = repository.reset_payroll(pid)
    assert res['reset'] is True
    p = _pay(lid)
    # 45 мин, 1 из 1 в группе ≤2 — прежний движок: 250 (half-lesson × 1).
    assert not p.is_manual and p.payment == D('250.00') and p.penalty == D('0.00')


def test_patch_without_money_does_not_mark_manual(school):
    from apps.payroll import repository
    lid = _lesson(school, 'group')
    repository.update_payroll(_pay(lid).id, {'present_count': 1})
    assert not _pay(lid).is_manual


def test_payroll_patch_api_marks_manual(superadmin_client, school):
    lid = _lesson(school, 'group')
    pid = _pay(lid).id
    resp = superadmin_client.patch(f'/api/admin/payroll/{pid}', {'payment': '777'}, format='json')
    assert resp.status_code == 200, resp.content
    assert resp.json()['is_manual'] is True
    resp = superadmin_client.post(f'/api/admin/payroll/{pid}/reset')
    assert resp.status_code == 200 and resp.json()['payment'] == '250.00'


def test_reverts_to_engine_when_version_gone(school, version):
    lid = _lesson(school, 'indiv')
    recalculate(lesson_ids=[lid])
    assert _pay(lid).payment == D('600.00')
    PayRateVersion.objects.filter(id=version.id).delete()
    recalculate(lesson_ids=[lid])
    p = _pay(lid)
    # 45 минут, 1 из 1 — прежний движок: 250.
    assert p.payment == D('250.00') and p.rule_note == '' and not p.is_manual


def test_record_lesson_uses_motivation_for_individual(school, version):
    from apps.lessons import services
    result = services.record_lesson(
        lesson_date=LESSON_DAY.isoformat(), teacher_id=school['teacher'],
        group_id=school['indiv'], original_teacher_id=None, lesson_number=1,
        lesson_duration_minutes=45, lesson_type='regular', record_url=None,
        submitted_by_token='admin-imported', submit_date=LESSON_DAY.isoformat(),
        attendance=[{'student_id': school['student'], 'present': True}],
        skip_balance_check=True,
    )
    assert result['payment'] == 600
    assert _pay(result['lesson_id']).rule_note


def test_attendance_edit_keeps_manual_and_recalculates(school, version):
    from apps.lessons import repository as lessons_repo
    from apps.payroll import repository
    lid = _lesson(school, 'indiv')
    recalculate(lesson_ids=[lid])
    lessons_repo.update_attendance_cell(lid, school['student'], False, skip_balance_check=True)
    p = _pay(lid)
    assert p.present_count == 0 and p.payment == D('0.00')   # никто не пришёл
    repository.update_payroll(p.id, {'payment': D('300')})
    lessons_repo.update_attendance_cell(lid, school['student'], True, skip_balance_check=True)
    p = _pay(lid)
    assert p.is_manual and p.payment == D('300.00') and p.calc_payment == D('600.00')


# ── API ────────────────────────────────────────────────────────────────────

def _version_body(day: str) -> dict:
    return {'effective_from': day, 'individual_rate': '600', 'makeup_rate': '250',
            'burned_rate': '150', 'cancel_mode': 'percent', 'cancel_value': '50',
            'penalty_enabled': False}


def test_rate_versions_superadmin_only(admin_client, manager_client):
    assert admin_client.get('/api/admin/payroll/rate-versions').status_code == 403
    assert manager_client.get('/api/admin/payroll/rate-versions').status_code == 403


def test_rate_version_past_date_rejected(superadmin_client):
    past = (msk_now().date() - datetime.timedelta(days=1)).isoformat()
    resp = superadmin_client.post('/api/admin/payroll/rate-versions', _version_body(past), format='json')
    assert resp.status_code == 400


def test_rate_version_create_today_and_delete(superadmin_client):
    today = msk_now().date().isoformat()
    resp = superadmin_client.post('/api/admin/payroll/rate-versions', _version_body(today), format='json')
    try:
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body['individual_rate'] == '600.00' and body['makeup_rate'] == '250.00'
        listing = superadmin_client.get('/api/admin/payroll/rate-versions').json()
        assert any(v['id'] == body['id'] for v in listing['results'])
        assert 'engine_lessons' in listing
        assert superadmin_client.delete(f"/api/admin/payroll/rate-versions/{body['id']}").status_code == 200
    finally:
        PayRateVersion.objects.filter(effective_from=today).delete()


def test_personal_rate_only_for_individual_group(superadmin_client, school):
    base = {'teacher_id': school['teacher'], 'kind': 'plus_fixed', 'value': '100'}
    resp = superadmin_client.post('/api/admin/payroll/personal-rates',
                                  {**base, 'group_id': school['group']}, format='json')
    assert resp.status_code == 400
    resp = superadmin_client.post('/api/admin/payroll/personal-rates',
                                  {**base, 'group_id': school['indiv']}, format='json')
    assert resp.status_code == 201, resp.content
