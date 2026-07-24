"""
Построитель «Бухгалтерского отчёта за месяц» для раздела «Отчёты».

Тонкая обёртка над apps.finances.reports (существующая логика сборки —
collect_monthly_report + render_report_bytes, та же, что у CLI-команды
export_accounting_report): собираем данные по месяцу и отдаём xlsx-байты для
ReportJob. Правила half-lesson/FIFO не дублируются.
"""
from __future__ import annotations

from apps.finances.reports import collect_monthly_report, render_report_bytes


def build(month: str) -> tuple[bytes, int, str]:
    """(xlsx-байты, число учеников, имя файла). month — 'YYYY-MM'."""
    rows = collect_monthly_report(month)  # ValueError при кривом месяце → services пометит failure
    content = render_report_bytes(rows)
    filename = f'accounting_{month}.xlsx'
    return content, len(rows), filename
