"""
Вес посещения в уроках — единственное определение half-lesson на проект.

Занятие 45 минут весит 0.5 урока, любое другое — 1. От этого веса зависят
балансы учеников, FIFO-списание денег и отчёты; однажды он уже потерялся в
одном месте (прогресс ученика считался сырым COUNT занятий), поэтому в новом
коде вес только импортируется отсюда, а не пишется заново.

Охват на сегодня: финансы (apps/finances/repository.py) и дашборд посещений
(apps/reports/attendance_dashboard.py). Свои копии того же выражения пока
остались в apps/dashboard/registry_service.py — их можно и нужно перевести
сюда; в apps/groups/repository.py и apps/teachers/stats.py запрос идёт от
модели Lesson, и это выражение им не подойдёт без отдельного варианта.

Выражение рассчитано на queryset по lesson_attendance: путь до длительности
идёт через FK `lesson`. Для запросов от самой модели Lesson оно не годится.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Case, DecimalField, Value, When

_DEC = DecimalField(max_digits=12, decimal_places=2)


def attended_units_case() -> Case:
    """SUM(CASE WHEN duration=45 THEN 0.5 ELSE 1) как Decimal-выражение."""
    return Case(
        When(lesson__lesson_duration_minutes=45, then=Value(Decimal('0.5'))),
        default=Value(Decimal('1')),
        output_field=_DEC,
    )
