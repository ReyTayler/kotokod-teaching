"""Маршруты раздела «Отчёты». APPEND_SLASH=False — без trailing slash."""
from django.urls import path

from apps.reports.views import (
    ReportDownloadView,
    ReportRunView,
    ReportStatusView,
)

urlpatterns = [
    # Литеральные /status|/download — до /<report_type>/run (str-конвертер жадный).
    path('/status/<str:task_id>', ReportStatusView.as_view(), name='reports-status'),
    path('/download/<str:task_id>', ReportDownloadView.as_view(), name='reports-download'),
    path('/<str:report_type>/run', ReportRunView.as_view(), name='reports-run'),
]
