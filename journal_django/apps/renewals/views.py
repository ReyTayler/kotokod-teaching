"""APIView для /api/admin/renewals. Права: IsManagerOrAdmin (manager/admin/superadmin)."""
from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin, ReadStaffWriteSuperAdmin
from apps.renewals import services
from apps.renewals.serializers import (
    MoveSerializer,
    StageReorderSerializer,
    StageWriteSerializer,
)
from apps.renewals.transitions import InvalidTransition

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

    def patch(self, request: Request, pk: int) -> Response:
        from apps.renewals.serializers import DealPatchSerializer
        ser = DealPatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = services.patch_deal(pk, ser.validated_data)
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)


class RenewalMoveView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        ser = MoveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            result = services.move_deal(
                pk, ser.validated_data['to_stage_id'],
                ser.validated_data.get('reason_code'),
                author_id=getattr(request.user, 'id', None))
        except InvalidTransition as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)


class RenewalCommentView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        from apps.renewals.serializers import CommentSerializer
        ser = CommentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = services.add_comment(pk, ser.validated_data['body'],
                                       getattr(request.user, 'id', None))
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result, status=status.HTTP_201_CREATED)


class RenewalActivityView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        return Response(services.list_activity(pk))


class RenewalStageListView(APIView):
    permission_classes = [ReadStaffWriteSuperAdmin]

    def get(self, request: Request) -> Response:
        return Response(services.list_stages())

    def post(self, request: Request) -> Response:
        ser = StageWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(services.create_stage(ser.validated_data),
                        status=status.HTTP_201_CREATED)


class RenewalStageDetailView(APIView):
    permission_classes = [ReadStaffWriteSuperAdmin]

    def patch(self, request: Request, pk: int) -> Response:
        ser = StageWriteSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        result = services.update_stage(pk, ser.validated_data)
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)

    def delete(self, request: Request, pk: int) -> Response:
        outcome = services.delete_stage(pk)
        if outcome == 'not_found':
            raise NotFound({'error': 'Not found'})
        if outcome in ('has_open_deals', 'protected'):
            return Response({'error': outcome}, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RenewalStageReorderView(APIView):
    permission_classes = [ReadStaffWriteSuperAdmin]

    def post(self, request: Request) -> Response:
        ser = StageReorderSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(services.reorder_stages(ser.validated_data['order']))
