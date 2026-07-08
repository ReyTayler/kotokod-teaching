"""APIView для /api/admin/renewals. Права: IsManagerOrAdmin (manager/admin/superadmin)."""
from __future__ import annotations

from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin
from apps.renewals import services

SORT_FIELDS = ['next_touch_at', 'stage_entered_at', 'cycle_no', 'student_name']


class RenewalCollectionView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        qp = request.query_params
        view = qp.get('view', 'board')
        filters = {k[7:-1]: v for k, v in qp.items()
                   if k.startswith('filter[') and k.endswith(']')}
        if view == 'list':
            page = max(1, int(qp.get('page', 1) or 1))
            page_size = min(200, max(1, int(qp.get('page_size', 50) or 50)))
            sort_by = qp.get('sort_by', 'stage_entered_at')
            sort_dir = qp.get('sort_dir', 'asc')
            if sort_by not in SORT_FIELDS:
                raise ValidationError(f"Invalid sort_by. Allowed: {SORT_FIELDS}")
            if sort_dir not in ('asc', 'desc'):
                raise ValidationError("sort_dir must be 'asc' or 'desc'")
            return Response(services.list_deals(
                page=page, page_size=page_size, sort_by=sort_by,
                sort_dir=sort_dir, filters=filters))
        return Response(services.board(filters))


class RenewalDetailView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        deal = services.get_deal(pk)
        if deal is None:
            raise NotFound({'error': 'Not found'})
        return Response(deal)
