"""
Тонкие APIView для /api/admin/dashboard.

Зеркалит Express routes/admin/dashboard.js:
  GET /api/admin/dashboard          → сводка (params from/to)  | 400 {error:'invalid_date'}
  GET /api/admin/dashboard/monthly  → year-over-year (params year/years) | 400 {error:'invalid_year'}

Права: только manager или admin (IsManagerOrAdmin).
Валидация дат/годов — дословный порт (isValidIsoDate / YEAR_RE).
"""
from __future__ import annotations

import datetime
import re

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin
from apps.dashboard import services

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_YEAR_RE = re.compile(r'^\d{4}$')


def _is_valid_iso_date(v) -> bool:
    """
    Формат YYYY-MM-DD + реальная календарная дата. Порт dashboard.js isValidIsoDate
    (отсекает 2026-13-99, 2026-02-30 и non-string из ?from[]=).
    """
    if not isinstance(v, str) or not _DATE_RE.match(v):
        return False
    try:
        datetime.date.fromisoformat(v)
        return True
    except ValueError:
        return False


class DashboardView(APIView):
    """GET /api/admin/dashboard — финансовая сводка."""

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        from_ = request.query_params.get('from')
        to = request.query_params.get('to')
        if (from_ and not _is_valid_iso_date(from_)) or (to and not _is_valid_iso_date(to)):
            return Response({'error': 'invalid_date'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(services.get_dashboard_cached(from_=from_ or None, to=to or None))


class DashboardMonthlyView(APIView):
    """GET /api/admin/dashboard/monthly — помесячный year-over-year."""

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        qp = request.query_params
        years = qp.get('years')
        year = qp.get('year')
        year_list = None

        if years is not None:
            # ?years=2025,2026 — список для year-over-year.
            parts = [p for p in years.split(',') if p != '']
            if not parts or any(not _YEAR_RE.match(p) for p in parts):
                return Response({'error': 'invalid_year'}, status=status.HTTP_400_BAD_REQUEST)
            year_list = [int(p) for p in parts]
        elif year:
            # legacy одиночный ?year=2026
            if not _YEAR_RE.match(year):
                return Response({'error': 'invalid_year'}, status=status.HTTP_400_BAD_REQUEST)
            year_list = [int(year)]

        return Response(services.get_monthly_cached(years=year_list))
