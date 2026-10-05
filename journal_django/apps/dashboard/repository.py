"""
DashboardRepository — данные дашборда (поступления по периоду и по дням).
FIFO — через apps/finances.

ORM-порт services/repo/dashboard.js (раздел 09). Сам FIFO-движок и загрузка
партий/посещений живут в apps/finances (не дублируем).

Полуинтервалы дат [period_start, period_end) сохранены (__gte + __lt).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Count, DecimalField, Min, Q, Sum, Value
from django.db.models.functions import Coalesce

from apps.payments.models import Payment


_ZERO = Value(Decimal('0'), output_field=DecimalField(max_digits=20, decimal_places=2))


def revenue_for_period(period_start: str, period_end: str):
    """
    SUM(total_amount) в полуинтервале [period_start, period_end), БЕЗ возвратов.
    Возвращает Decimal.

    Возвраты (kind='refund', суммы отрицательные) исключены по решению
    пользователя 2026-10-05: дашборд показывает поступления. Строки возврата
    по-прежнему видны в разделе «Отчёты» и в карточке ученика. Это
    единственный вид с отрицательной суммой (CHECK в БД), поэтому после
    исключения в выборке остаются только неотрицательные суммы.
    """
    return Payment.objects.filter(
        paid_at__gte=period_start, paid_at__lt=period_end,
    ).exclude(kind='refund').aggregate(total=Coalesce(Sum('total_amount'), _ZERO))['total']


def revenue_by_day(date_from: str, date_to: str) -> list[dict[str, Any]]:
    """
    Поступления по дням paid_at в [date_from, date_to] (включительно): сумма
    покупок, доплат к абонементу и доп.уроков и число заказов — оплат с
    total_amount > 0 (строка на 0 ₽ заказом не считается). Возвраты исключены,
    как в revenue_for_period. Только дни, где были оплаты; ASC по дате.
    Индекс payments_paid_at_idx.
    """
    return list(
        Payment.objects
        .filter(paid_at__gte=date_from, paid_at__lte=date_to)
        .exclude(kind='refund')
        .values('paid_at')
        .annotate(
            rev=Coalesce(Sum('total_amount'), _ZERO),
            orders=Count('id', filter=Q(total_amount__gt=0)),
        )
        .order_by('paid_at')
    )


def first_payment_date():
    """Самая ранняя paid_at в базе (date) или None, если оплат нет."""
    return Payment.objects.aggregate(d=Min('paid_at'))['d']
