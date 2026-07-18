"""
Integration-тесты repository слоя payroll (реальная БД, managed=False).

Покрытие:
  - list_payroll: контракт {rows,total,page,page_size}, JOIN-контекст, фильтр teacher_id,
    тихий fallback невалидного sort_by.
  - payroll_summary: COUNT/SUM по учителю, lessons_count строкой, sum_* Decimal с масштабом,
    фильтр по диапазону дат.
  - update_payroll: COALESCE-семантика, None для отсутствующего id.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection

from apps.payroll import repository

pytestmark = pytest.mark.django_db


def _set_surcharge(payroll_id: int, amount, at: str) -> None:
    with connection.cursor() as cur:
        cur.execute(
            'UPDATE payroll SET burn_surcharge_amount = %s, burn_surcharge_at = %s WHERE id = %s',
            [amount, at, payroll_id],
        )


def test_list_payroll_envelope_and_context(payroll_fixture, teacher_id_fixture, group_fixture):
    payroll_id, lesson_id = payroll_fixture
    result = repository.list_payroll(filters={'teacher_id': teacher_id_fixture, 'group_id': group_fixture})
    assert set(result.keys()) == {'rows', 'total', 'page', 'page_size'}
    assert result['total'] == 1
    row = result['rows'][0]
    assert row['id'] == payroll_id
    assert row['lesson_id'] == lesson_id
    assert row['group_name'] == '__pr_group__'
    assert row['payment'] == Decimal('650.00')
    assert row['lesson_number'] == Decimal('1.0')


def test_list_payroll_invalid_sort_falls_back(payroll_fixture, teacher_id_fixture):
    result = repository.list_payroll(
        sort_by='; DROP TABLE payroll; --', filters={'teacher_id': teacher_id_fixture}
    )
    assert result['total'] >= 1


def test_summary_lessons_count_is_string(payroll_fixture, teacher_id_fixture):
    rows = repository.payroll_summary(teacher_id=teacher_id_fixture)
    assert len(rows) == 1
    r = rows[0]
    # node-pg отдаёт COUNT(*) (bigint) строкой → ::text
    assert r['lessons_count'] == '1'
    assert isinstance(r['lessons_count'], str)
    assert r['sum_payment'] == Decimal('650.00')
    assert r['sum_penalty'] == Decimal('0.00')


def test_summary_date_range_filter(payroll_fixture, teacher_id_fixture):
    # Урок 2026-04-10 — попадает в диапазон.
    inside = repository.payroll_summary(
        teacher_id=teacher_id_fixture, date_from='2026-04-01', date_to='2026-04-30'
    )
    assert inside and inside[0]['lessons_count'] == '1'
    # Вне диапазона — учителя нет в сводке.
    outside = repository.payroll_summary(
        teacher_id=teacher_id_fixture, date_from='2026-05-01', date_to='2026-05-31'
    )
    assert outside == []


def test_list_payroll_surcharge_is_separate_row_dated_by_edit(
    payroll_fixture, teacher_id_fixture, group_fixture,
):
    """
    Урок 2026-04-10 (payroll_fixture), «сгорание» отмечено 2026-05-05 —
    список за апрель должен видеть только базовую строку, список за май —
    только строку-надбавку (is_surcharge=True), с суммой из burn_surcharge_amount,
    а не из payment. Ни разу обе строки не тянут в один месяц (2026-07-17 design).
    """
    payroll_id, lesson_id = payroll_fixture
    _set_surcharge(payroll_id, Decimal('150.00'), '2026-05-05')

    april = repository.list_payroll(filters={
        'teacher_id': teacher_id_fixture, 'date_from': '2026-04-01', 'date_to': '2026-04-30',
    })
    assert april['total'] == 1
    assert april['rows'][0]['id'] == payroll_id
    assert april['rows'][0]['is_surcharge'] is False
    assert april['rows'][0]['payment'] == Decimal('650.00')

    may = repository.list_payroll(filters={
        'teacher_id': teacher_id_fixture, 'date_from': '2026-05-01', 'date_to': '2026-05-31',
    })
    assert may['total'] == 1
    assert may['rows'][0]['id'] == payroll_id
    assert may['rows'][0]['is_surcharge'] is True
    assert may['rows'][0]['payment'] == Decimal('150.00')
    assert str(may['rows'][0]['lesson_date']) == '2026-05-05'

    unfiltered = repository.list_payroll(filters={'teacher_id': teacher_id_fixture})
    assert unfiltered['total'] == 2


def test_list_payroll_no_surcharge_row_when_amount_zero(payroll_fixture, teacher_id_fixture):
    """burn_surcharge_amount=0 (по умолчанию) — списку не из чего строить вторую строку."""
    result = repository.list_payroll(filters={'teacher_id': teacher_id_fixture})
    assert result['total'] == 1
    assert result['rows'][0]['is_surcharge'] is False


def test_summary_splits_surcharge_into_edit_month(payroll_fixture, teacher_id_fixture):
    payroll_id, _ = payroll_fixture
    _set_surcharge(payroll_id, Decimal('150.00'), '2026-05-05')

    april = repository.payroll_summary(
        teacher_id=teacher_id_fixture, date_from='2026-04-01', date_to='2026-04-30',
    )
    assert april[0]['sum_payment'] == Decimal('650.00')
    assert april[0]['lessons_count'] == '1'

    may = repository.payroll_summary(
        teacher_id=teacher_id_fixture, date_from='2026-05-01', date_to='2026-05-31',
    )
    # Надбавка попадает в май (дата правки), хотя сам урок был в апреле; lessons_count
    # не считает надбавку новым уроком, но учителя из сводки терять нельзя.
    assert may[0]['sum_payment'] == Decimal('150.00')
    assert may[0]['lessons_count'] == '0'


def test_update_payroll_coalesce(payroll_fixture):
    payroll_id, _ = payroll_fixture
    # Меняем только payment — остальное сохраняется.
    updated = repository.update_payroll(payroll_id, {'payment': 700})
    assert updated['payment'] == Decimal('700.00')
    assert updated['total_students'] == 5
    assert updated['present_count'] == 4


def test_update_payroll_missing_returns_none():
    assert repository.update_payroll(999_999_999, {'payment': 1}) is None
