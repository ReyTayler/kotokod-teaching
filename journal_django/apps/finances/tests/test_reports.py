"""
Тесты сборки данных отчёта (apps/finances/reports.py::collect_monthly_report).
Использует существующие фикстуры apps/finances/tests/conftest.py.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection

from apps.finances.reports import collect_monthly_report

pytestmark = pytest.mark.django_db


def _add_payment(created, student_id, direction_id, subs, total, paid_at, kind='purchase'):
    lessons = subs * 4 if kind == 'purchase' else -(subs * 4)
    amount = total if kind == 'purchase' else -total
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, lessons_count, "
            "kind, unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'test') RETURNING id",
            [student_id, direction_id, subs, lessons, kind, total, amount, paid_at],
        )
        pid = cur.fetchone()[0]
    created['payments'].append(pid)
    return pid


def _add_payment_exact(created, student_id, direction_id, lessons_count, unit_price, paid_at):
    """Оплата с явным числом уроков/ценой (в отличие от _add_payment, где lessons=subs*4)."""
    total = lessons_count * unit_price
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, lessons_count, "
            "kind, unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s,%s,1,%s,'purchase',%s,%s,%s,'test') RETURNING id",
            [student_id, direction_id, lessons_count, unit_price, total, paid_at],
        )
        pid = cur.fetchone()[0]
    created['payments'].append(pid)
    return pid


def _add_lesson_attendance(created, group_id, teacher_id, student_id, date, duration=60):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s,%s,%s,1,%s,'regular','test') RETURNING id",
            [group_id, teacher_id, date, duration],
        )
        lid = cur.fetchone()[0]
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s,%s,true)',
            [lid, student_id],
        )
    created['lessons'].append(lid)
    return lid


def test_collect_monthly_report_single_student_full_scenario(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE students SET platform_id = 'PL-42' WHERE id = %s", [student_fixture]
        )
    # Две оплаты ВНУТРИ месяца (2026-07), одна ДО месяца (не должна попасть в payments/paid_month_total,
    # но должна попасть в лайфтайм-баланс).
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000, '2026-07-05')
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 2, 3600, '2026-07-20')
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000, '2026-06-15')
    # 1 обычный урок (1.0) + 1 полу-урок (0.5) внутри месяца = 1.5 посещено.
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-10', duration=60,
    )
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-11', duration=45,
    )
    # Урок ВНЕ месяца — не должен попасть в attended_lessons.
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-08-01', duration=60,
    )

    rows = collect_monthly_report('2026-07')
    row = next(r for r in rows if r.student_id == student_fixture)

    assert row.platform_id == 'PL-42'
    assert row.attended_lessons == 1.5
    assert row.payments == [('2026-07-05', Decimal('2000.00')), ('2026-07-20', Decimal('3600.00'))]
    assert row.paid_month_total == Decimal('5600.00')
    # Баланс не ограничен месяцем (лайфтайм purchased-attended, как balance_for_student):
    # куплено 4+8+4=16 (включая оплату ДО месяца), отработано 1.5+1=2.5 (включая урок ПОСЛЕ
    # месяца) → баланс 13.5.
    assert row.balance == 13.5
    # FIFO по лотам в порядке paid_at: 06-15 (4@500), 07-05 (4@500), 07-20 (8@450).
    # Списано 2.5 из первого лота (06-15) → остаток 1.5@500 + 4@500 + 8@450 = 6350.
    assert row.remaining_value == Decimal('6350.00')
    # Отработано деньгами ИМЕННО за 2026-07: 1.5 урока внутри месяца, всё ещё из
    # первого лота (06-15, 500/урок) — урок 08-01 не входит (вне месяца).
    assert row.worked_off_month == Decimal('750.00')
    assert row.unit_prices_month == [Decimal('500.00')]


def test_collect_monthly_report_student_with_no_activity_gets_zero_row(student_fixture):
    rows = collect_monthly_report('2026-07')
    row = next(r for r in rows if r.student_id == student_fixture)

    assert row.platform_id is None
    assert row.attended_lessons == 0
    assert row.payments == []
    assert row.paid_month_total == Decimal('0')
    assert row.balance == 0
    assert row.remaining_value == Decimal('0')
    assert row.worked_off_month == Decimal('0')
    assert row.unit_prices_month == []


def test_collect_monthly_report_invalid_month_raises_value_error():
    with pytest.raises(ValueError):
        collect_monthly_report('2026-13')


def test_collect_monthly_report_multiple_price_tiers_within_month(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    # Лот A (2 урока @500) заканчивается ВНУТРИ месяца, продолжение — лот B (4 урока @450).
    _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 2, 500, '2026-06-01')
    _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 4, 450, '2026-06-02')

    # 3 урока внутри месяца: 2 добивают лот A (500), 1-й идёт из лота B (450).
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-05', duration=60,
    )
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-06', duration=60,
    )
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-07', duration=60,
    )

    rows = collect_monthly_report('2026-07')
    row = next(r for r in rows if r.student_id == student_fixture)

    assert row.unit_prices_month == [Decimal('500.00'), Decimal('450.00')]
    assert row.worked_off_month == Decimal('1450.00')  # 2*500 + 1*450


def test_collect_monthly_report_extra_lesson_counted_in_makeup_month(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    """
    Регрессия (решение пользователя 2026-07-16): пропуск в одном месяце,
    скомпенсированный доп.уроком в ДРУГОМ месяце, должен относить и
    «посещено», и «отработано» к месяцу ФАКТИЧЕСКОГО проведения доп.урока —
    не к месяцу исходного пропуска, и не задваивать посещаемость.
    """
    from apps.extra_lessons import services as extra_services
    from apps.extra_lessons.models import AbsenceResolution
    from apps.extra_lessons.repository import get_resolution_full

    class _FakeRequest:
        META = {}
        user = None

    _add_payment_exact(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-06-01')

    # Пропуск в июне — пока не компенсирован.
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s,%s,'2026-06-05',1,60,'regular','test') RETURNING id",
            [group_fixture, teacher_id_fixture],
        )
        missed_lid = cur.fetchone()[0]
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s,%s,false)',
            [missed_lid, student_fixture],
        )
    graph_cleanup['lessons'].append(missed_lid)

    created = extra_services.create_assignment(
        {
            'missed_lesson_id': missed_lid, 'teacher_id': teacher_id_fixture,
            'student_ids': [student_fixture], 'scheduled_date': '2026-07-10',
            'scheduled_time': '15:00', 'duration_minutes': 45,
        },
        _FakeRequest(),
    )
    rid = created['resolution_ids'][0]
    try:
        extra_services.record(
            rid, teacher_id=teacher_id_fixture, present=True,
            record_url=None, submitted_by_token='test', submit_date='2026-07-10',
            request=_FakeRequest(),
        )

        june_row = next(
            r for r in collect_monthly_report('2026-06') if r.student_id == student_fixture
        )
        july_row = next(
            r for r in collect_monthly_report('2026-07') if r.student_id == student_fixture
        )

        # Июнь (месяц пропуска) — ничего не отработано и не посещено.
        assert june_row.attended_lessons == 0
        assert june_row.worked_off_month == Decimal('0')
        # Июль (месяц доп.урока) — ровно 1 урок посещён и отработан, без задвоения.
        assert july_row.attended_lessons == 1
        assert july_row.worked_off_month == Decimal('500.00')
    finally:
        full = get_resolution_full(rid)
        if full and full['status'] == 'makeup_done':
            extra_services.delete_fact(rid, _FakeRequest())
        AbsenceResolution.objects.filter(id=rid).delete()
