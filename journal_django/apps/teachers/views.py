"""
TeachersView — тонкий ViewSet для /api/admin/teachers.

Зеркалит Express routes/admin/teachers.js:
  GET    /api/admin/teachers        → list()           → 200 [...]
  GET    /api/admin/teachers/:id    → retrieve()       → 200 | 404
  POST   /api/admin/teachers        → create()         → 201 | 409
  PATCH  /api/admin/teachers/:id    → partial_update() → 200 | 404
  DELETE /api/admin/teachers/:id    → destroy()        → 204 | 404

Параметры: ?include_inactive=1 (GET список).
Права: чтение — manager/admin/superadmin; запись — только superadmin (ReadStaffWriteSuperAdmin).
"""
from __future__ import annotations

from django.db import IntegrityError
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ReadStaffWriteSuperAdmin
from apps.teachers import services
from apps.teachers.serializers import TeacherUpdateSerializer, TeacherWriteSerializer


class TeacherListCreateView(APIView):
    """
    GET  /api/admin/teachers  — список преподавателей
    POST /api/admin/teachers  — создать преподавателя
    """

    permission_classes = [ReadStaffWriteSuperAdmin]

    def get(self, request: Request) -> Response:
        include_inactive = request.query_params.get('include_inactive') == '1'
        rows = services.list_teachers(include_inactive=include_inactive)
        return Response(rows)

    def post(self, request: Request) -> Response:
        serializer = TeacherWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            teacher = services.create_teacher(serializer.validated_data)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                return Response(
                    {'error': 'Already exists'},
                    status=status.HTTP_409_CONFLICT,
                )
            raise

        return Response(teacher, status=status.HTTP_201_CREATED)


class TeacherDetailView(APIView):
    """
    GET    /api/admin/teachers/:id  — получить преподавателя
    PATCH  /api/admin/teachers/:id  — обновить преподавателя
    DELETE /api/admin/teachers/:id  — мягкое удаление
    """

    permission_classes = [ReadStaffWriteSuperAdmin]

    def get(self, request: Request, pk: int) -> Response:
        teacher = services.get_teacher(pk)
        if teacher is None:
            raise NotFound({'error': 'Not found'})
        return Response(teacher)

    def patch(self, request: Request, pk: int) -> Response:
        serializer = TeacherUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = services.update_teacher(pk, serializer.validated_data)
        if updated is None:
            raise NotFound({'error': 'Not found'})

        return Response(updated)

    def delete(self, request: Request, pk: int) -> Response:
        ok = services.soft_delete_teacher(pk)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_unique_violation(exc: Exception) -> bool:
    pgcode = getattr(exc, 'pgcode', None)
    if pgcode == '23505':
        return True
    cause = getattr(exc, '__cause__', None)
    if cause and getattr(cause, 'pgcode', None) == '23505':
        return True
    return False
