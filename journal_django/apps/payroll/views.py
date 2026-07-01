"""
Тонкие APIView для /api/admin/payroll.

Зеркалит Express routes/admin/payroll.js:
  GET   /api/admin/payroll          → список {rows,total,page,page_size}
  GET   /api/admin/payroll/summary  → сводка по учителю [...]
  PATCH /api/admin/payroll/:id      → 200 | 404 {error:'Not found'}

Права: только manager или admin (IsManagerOrAdmin).
Сортировка: тихий fallback на default (как Express paginate()), без 400.
"""
from __future__ import annotations

from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin
from apps.payroll import services
from apps.payroll.serializers import PayrollUpdateSerializer

_DEFAULT_SORT_BY = 'lesson_date'
_DEFAULT_SORT_DIR = 'desc'
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 500


def _parse_list_params(request: Request) -> dict:
    """
    Параметры пагинации/фильтров (parsePaginationRequest). Фильтры только из
    filter[*] — payroll-роут не мержит top-level (в отличие от lessons).
    sort_by/sort_dir НЕ валидируются (fallback в repository, как Express).
    """
    qp = request.query_params

    try:
        page = max(1, int(qp.get('page') or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        raw_page_size = int(qp.get('page_size') or 0)
    except (TypeError, ValueError):
        raw_page_size = 0
    page_size = min(_MAX_PAGE_SIZE, max(1, raw_page_size or _DEFAULT_PAGE_SIZE))

    sort_by = qp.get('sort_by') or _DEFAULT_SORT_BY
    sort_dir = qp.get('sort_dir')
    if sort_dir not in ('asc', 'desc'):
        sort_dir = _DEFAULT_SORT_DIR

    filters: dict = {}
    for key, value in qp.items():
        if key.startswith('filter[') and key.endswith(']'):
            filters[key[7:-1]] = value

    return {
        'page': page,
        'page_size': page_size,
        'sort_by': sort_by,
        'sort_dir': sort_dir,
        'filters': filters,
    }


class PayrollListView(APIView):
    """GET /api/admin/payroll — список расчётного листа."""

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        return Response(services.list_payroll(**_parse_list_params(request)))


class PayrollSummaryView(APIView):
    """GET /api/admin/payroll/summary — сводка по учителю (фильтры date_from/date_to/teacher_id)."""

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        qp = request.query_params
        teacher_id = int(qp['teacher_id']) if qp.get('teacher_id') else None
        date_from = qp.get('date_from') or None
        date_to = qp.get('date_to') or None
        return Response(services.payroll_summary(
            teacher_id=teacher_id, date_from=date_from, date_to=date_to,
        ))


class PayrollDetailView(APIView):
    """PATCH /api/admin/payroll/:id — частичное обновление."""

    permission_classes = [IsManagerOrAdmin]

    def patch(self, request: Request, pk: int) -> Response:
        serializer = PayrollUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = services.update_payroll(pk, serializer.validated_data)
        if updated is None:
            raise NotFound({'error': 'Not found'})
        return Response(updated)
