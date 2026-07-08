"""
Баланс ученика — выводится, не хранится (purchased − attended per direction).

Единый дом расчёта баланса (раньше жил в apps/payments/repository.py).
Порт getStudentBalance (services/repo/payments.js): числа баланса как int/float
(через _js_number), сырые поля оплат (unit_price/total_amount) — Decimal→строка
делает renderer.

balance_for_student переэкспортируется из repository для удобства потребителей.
"""
from __future__ import annotations

from apps.finances import repository
from apps.finances.repository import balance_for_student  # re-export

__all__ = ['balance_for_student', 'get_student_balance']


def get_student_balance(student_id: int) -> dict:
    """
    Баланс ученика по всем направлениям + список оплат.

    Порт payments.js getStudentBalance. list_payments импортируется лениво,
    чтобы не создавать цикл finances ↔ payments.
    """
    from apps.payments.repository import list_payments

    direction_rows = repository.student_balance_rows(student_id)

    per_direction = [
        {
            'direction_id':      r['direction_id'],
            'direction_name':    r['direction_name'],
            'direction_color':   r['direction_color'],
            'purchased_lessons': repository._js_number(r['purchased_lessons']),
            'attended_lessons':  repository._js_number(r['attended_lessons']),
            'balance':           repository._js_number(r['balance']),
            'total_paid_amount': repository._js_number(r['total_paid_amount']),
        }
        for r in direction_rows
    ]

    total_balance = sum(d['balance'] for d in per_direction)
    total_paid = repository.total_paid_amount(student_id)
    payments = list_payments(student_id=student_id)

    return {
        'per_direction':     per_direction,
        'total_balance':     total_balance,
        'total_paid_amount': total_paid,
        'payments':          payments,
    }
