"""
MembershipsView — тонкие APIView для /api/admin/memberships.

Зеркалит Express routes/admin/memberships.js:
  GET    /api/admin/memberships     → список (без пагинации!) → 200 []
  POST   /api/admin/memberships     → upsert → 201
  PATCH  /api/admin/memberships/:id → обновить → 200 | 404
  DELETE /api/admin/memberships/:id → soft-delete (active=false) → 204 | 404

Права: только manager или admin (IsManagerOrAdmin).
Фильтры: group_id, student_id (числа), include_inactive ('1' → True).
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin
from apps.memberships import services
from apps.memberships.serializers import MembershipUpdateSerializer, MembershipWriteSerializer


def _parse_int_param(qp, key: str):
    val = qp.get(key)
    if not val:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        raise ValidationError({key: 'Must be an integer.'})


class MembershipListCreateView(APIView):
    """
    GET  /api/admin/memberships  — список без пагинации
    POST /api/admin/memberships  — UPSERT membership
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        qp = request.query_params

        group_id = _parse_int_param(qp, 'group_id')
        student_id = _parse_int_param(qp, 'student_id')
        include_inactive = qp.get('include_inactive') == '1'

        result = services.list_memberships(
            group_id=group_id,
            student_id=student_id,
            include_inactive=include_inactive,
        )
        return Response(result)

    def post(self, request: Request) -> Response:
        serializer = MembershipWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        membership = services.add_membership(serializer.validated_data)
        return Response(membership, status=status.HTTP_201_CREATED)


class MembershipDetailView(APIView):
    """
    PATCH  /api/admin/memberships/:id  — обновить membership
    DELETE /api/admin/memberships/:id  — мягкое удаление
    """

    permission_classes = [IsManagerOrAdmin]

    def patch(self, request: Request, pk: int) -> Response:
        serializer = MembershipUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = services.update_membership(pk, serializer.validated_data)
        if updated is None:
            raise NotFound({'error': 'Not found'})

        return Response(updated)

    def delete(self, request: Request, pk: int) -> Response:
        ok = services.remove_membership(pk)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(status=status.HTTP_204_NO_CONTENT)
