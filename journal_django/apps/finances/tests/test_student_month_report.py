"""
Тесты «Бухгалтерского отчёта» по ученикам за месяц
(apps/finances/student_month.py::collect_student_month).

Строка = ученик × оплата: своя строка на каждую оплату, деньги которой
отрабатывались в месяце, и на каждую оплату месяца. Уроки сверх оплаченных —
отдельная строка-долг. Фикстуры — apps/finances/tests/conftest.py; БД общая
(managed=False), поэтому свои строки ищем по student_id.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection

from apps.finances.student_month import collect_student_month

pytestmark = pytest.mark.django_db


def _add_payment(created, student_id, direction_id, lessons_count, unit_price, paid_at,
                 kind='purchase'):
    total = lessons_count * unit_price
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, lessons_count, "
            "kind, unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s,%s,1,%s,%s,%s,%s,%s,'test') RETURNING id",
            [student_id, direction_id, lessons_count, kind, unit_price, total, paid_at],
        )
        pid = cur.fetchone()[0]
    created['payments'].append(pid)
    return pid


def _add_lesson(created, group_id, teacher_id, student_id, date,
                duration=60, is_free=False, present=True):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s,%s,%s,1,%s,'regular','test') RETURNING id",
            [group_id, teacher_id, date, duration],
        )
        lid = cur.fetchone()[0]
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present, is_free) '
            'VALUES (%s,%s,%s,%s)',
            [lid, student_id, present, is_free],
        )
    created['lessons'].append(lid)
    return lid


def _rows(month, student_id):
    return [r for r in collect_student_month(month) if r.student_id == student_id]


def test_lessons_paid_from_two_payments_give_two_rows(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    """
    Часть уроков месяца отработана давней оплатой, часть — оплатой месяца:
    две строки с разной стоимостью урока.
    """
    with connection.cursor() as cur:
        cur.execute("UPDATE students SET platform_id = 'PL-7' WHERE id = %s", [student_fixture])
    old_pid = _add_payment(graph_cleanup, student_fixture, direction_fixture, 2, 500, '2026-06-01')
    new_pid = _add_payment(graph_cleanup, student_fixture, direction_fixture, 4, 600, '2026-07-05')
    # 3 урока в июле: 2 добивают июньскую оплату, третий идёт из июльской.
    for date in ('2026-07-10', '2026-07-11', '2026-07-12'):
        _add_lesson(graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, date)

    rows = _rows('2026-07', student_fixture)

    assert len(rows) == 2
    old_row, new_row = rows
    assert old_row.payment_id == old_pid
    assert old_row.platform_id == 'PL-7'
    assert old_row.attended_lessons == 2
    assert old_row.worked_off == Decimal('1000.00')
    assert old_row.unit_price == Decimal('500.00')
    assert old_row.paid_at == '2026-06-01'
    assert old_row.paid_in_month == Decimal('0')      # оплата не этого месяца
    assert old_row.remaining_lessons == 0
    assert old_row.remaining_value == Decimal('0.00')

    assert new_row.payment_id == new_pid
    assert new_row.attended_lessons == 1
    assert new_row.worked_off == Decimal('600.00')
    assert new_row.unit_price == Decimal('600.00')
    assert new_row.paid_in_month == Decimal('2400.00')
    assert new_row.remaining_lessons == 3
    assert new_row.remaining_value == Decimal('1800.00')


def test_old_payment_not_fully_worked_off_still_shows_advance(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    """Оплата не этого месяца: «Итого оплачено» = 0, но аванс показываем."""
    pid = _add_payment(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-06-01')
    _add_lesson(graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-10')

    rows = _rows('2026-07', student_fixture)

    assert len(rows) == 1
    assert rows[0].payment_id == pid
    assert rows[0].paid_in_month == Decimal('0')
    assert rows[0].worked_off == Decimal('500.00')
    assert rows[0].remaining_lessons == 3
    assert rows[0].remaining_value == Decimal('1500.00')


def test_payment_of_month_without_lessons_shows_price_and_advance(
    student_fixture, direction_fixture, graph_cleanup,
):
    """Оплата месяца без уроков: 0 посещений, но цена урока и аванс на месте."""
    pid = _add_payment(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-07-05')

    rows = _rows('2026-07', student_fixture)

    assert len(rows) == 1
    row = rows[0]
    assert row.payment_id == pid
    assert row.attended_lessons == 0
    assert row.worked_off == Decimal('0.00')
    assert row.unit_price == Decimal('500.00')
    assert row.paid_in_month == Decimal('2000.00')
    assert row.remaining_lessons == 4
    assert row.remaining_value == Decimal('2000.00')


def test_lessons_beyond_paid_give_a_debt_row(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    """Уроки сверх оплаченных не привязаны к оплате — им отдельная строка-долг."""
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 2, 500, '2026-06-01')
    for date in ('2026-07-05', '2026-07-06', '2026-07-07', '2026-07-08'):
        _add_lesson(graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, date)

    rows = _rows('2026-07', student_fixture)

    assert len(rows) == 2
    paid_row, debt_row = rows
    assert paid_row.attended_lessons == 2
    assert paid_row.worked_off == Decimal('1000.00')
    assert paid_row.debt == Decimal('0.00')

    assert debt_row.payment_id is None
    assert debt_row.attended_lessons == 2              # 2 урока сверх оплаченных
    assert debt_row.worked_off == Decimal('0.00')
    assert debt_row.unit_price == Decimal('500.00')    # по цене последней оплаты
    assert debt_row.debt == Decimal('1000.00')
    assert debt_row.paid_in_month == Decimal('0')
    assert debt_row.remaining_lessons == -2           # баланс ученика в минусе


def test_debt_carried_from_previous_month_stays_visible(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    """Долг — величина на конец месяца: перешедший с июня виден и в июле."""
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 500, '2026-06-01')
    for date in ('2026-06-05', '2026-06-06'):
        _add_lesson(graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, date)

    rows = _rows('2026-07', student_fixture)

    assert len(rows) == 1
    debt_row = rows[0]
    assert debt_row.payment_id is None
    assert debt_row.attended_lessons == 0             # в июле в минус не уходил
    assert debt_row.debt == Decimal('500.00')         # но долг с июня остался


def test_half_lesson_counts_as_half(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-06-01')
    _add_lesson(graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-10',
                duration=45)

    row = _rows('2026-07', student_fixture)[0]

    assert row.attended_lessons == 0.5
    assert row.worked_off == Decimal('250.00')
    assert row.remaining_lessons == 3.5


def test_free_lesson_debits_nothing(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    """Бесплатное занятие баланс не списывает — строки по оплате не появляется."""
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-06-01')
    _add_lesson(graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-12',
                is_free=True)

    rows = _rows('2026-07', student_fixture)

    assert len(rows) == 1
    assert rows[0].payment_id is None       # пустая строка ученика без движения
    assert rows[0].attended_lessons == 0


def test_as_of_end_of_month(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    """Уроки и оплаты после конца месяца на отчёт не влияют."""
    pid = _add_payment(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-07-01')
    _add_lesson(graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-10')
    _add_lesson(graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-08-05')
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 4, 500, '2026-08-01')

    rows = _rows('2026-07', student_fixture)

    assert [r.payment_id for r in rows] == [pid]       # августовской оплаты нет
    assert rows[0].attended_lessons == 1
    assert rows[0].remaining_lessons == 3              # августовский урок не списан
    assert rows[0].remaining_value == Decimal('1500.00')


def test_student_without_activity_gets_one_empty_row(student_fixture):
    rows = _rows('2026-07', student_fixture)

    assert len(rows) == 1
    row = rows[0]
    assert row.payment_id is None
    assert row.attended_lessons == 0
    assert row.worked_off == Decimal('0')
    assert row.unit_price is None
    assert row.paid_at is None
    assert row.paid_in_month == Decimal('0')
    assert row.remaining_lessons == 0
    assert row.remaining_value == Decimal('0')
    assert row.debt == Decimal('0')


def test_rows_grouped_by_student_in_name_order(student_fixture):
    rows = collect_student_month('2026-07')
    names = [r.full_name for r in rows]

    assert names == sorted(names)                       # ученики по алфавиту
    assert student_fixture in {r.student_id for r in rows}


def test_invalid_month_raises_value_error():
    with pytest.raises(ValueError):
        collect_student_month('2026-13')
