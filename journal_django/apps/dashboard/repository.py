"""
DashboardRepository — данные дашборда (revenue, годы, имена). FIFO — через apps/finances.

ORM-порт services/repo/dashboard.js (раздел 09). Сам FIFO-движок и загрузка
партий/посещений живут в apps/finances (не дублируем).

Полуинтервалы дат [period_start, period_end) сохранены (__gte + __lt).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce, ExtractMonth, ExtractYear

from apps.directions.models import Direction
from apps.lessons.models import Lesson
from apps.payments.models import Payment
from apps.students.models import Student


_ZERO = Value(Decimal('0'), output_field=DecimalField(max_digits=20, decimal_places=2))


def revenue_for_period(period_start: str, period_end: str):
    """SUM(total_amount) в полуинтервале [period_start, period_end). Возвращает Decimal."""
    return Payment.objects.filter(
        paid_at__gte=period_start, paid_at__lt=period_end,
    ).aggregate(total=Coalesce(Sum('total_amount'), _ZERO))['total']


def revenue_by_year_month(min_year: int, max_year: int) -> dict[str, Any]:
    """
    Revenue по (год, месяц) за [min_year-01-01, (max_year+1)-01-01).
    Ключ карты 'YYYY-MM' → Decimal.
    """
    rows = (
        Payment.objects
        .filter(paid_at__gte=f'{min_year}-01-01', paid_at__lt=f'{max_year + 1}-01-01')
        .annotate(yy=ExtractYear('paid_at'), m=ExtractMonth('paid_at'))
        .values('yy', 'm')
        .annotate(rev=Coalesce(Sum('total_amount'), _ZERO))
    )
    return {f"{r['yy']}-{r['m']:02d}": r['rev'] for r in rows}


def distinct_source_years() -> list[int]:
    """DISTINCT годы из payments.paid_at и lessons.lesson_date (UNION, без NULL, ASC)."""
    y1 = Payment.objects.annotate(yy=ExtractYear('paid_at')).values_list('yy', flat=True)
    y2 = Lesson.objects.annotate(yy=ExtractYear('lesson_date')).values_list('yy', flat=True)
    return sorted({y for y in set(y1).union(set(y2)) if y is not None})


def students_names(student_ids: list[int]) -> dict[int, str]:
    """id → full_name."""
    if not student_ids:
        return {}
    return dict(
        Student.objects.filter(id__in=student_ids).values_list('id', 'full_name')
    )


def directions_info(direction_ids: list[int]) -> dict[int, dict]:
    """id → {name, color}."""
    if not direction_ids:
        return {}
    return {
        row[0]: {'name': row[1], 'color': row[2]}
        for row in Direction.objects.filter(id__in=direction_ids).values_list('id', 'name', 'color')
    }
