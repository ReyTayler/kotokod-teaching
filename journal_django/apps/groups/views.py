"""
GroupsView — тонкий ViewSet для /api/admin/groups.

Зеркалит Express routes/admin/groups.js и Nest GroupsController:
  GET    /api/admin/groups        → list()    → 200 {rows, total, page, page_size}
  GET    /api/admin/groups/:id    → retrieve() → 200 | 404 {error: 'Not found'}
  POST   /api/admin/groups        → create()   → 201 | 409
  PATCH  /api/admin/groups/:id    → partial_update() → 200 | 404
  DELETE /api/admin/groups/:id    → destroy()  → 204 | 404

Права: только manager или admin (IsManagerOrAdmin).
Пагинация и сортировка: параметры sort_by / sort_dir / page / page_size / filter[*].
"""
from __future__ import annotations

from django.db import IntegrityError
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin
from apps.groups import services
from apps.groups.serializers import (
    GroupReadSerializer, GroupUpdateSerializer, GroupWriteSerializer,
    ScheduleChangeSerializer,
)


# Допустимые значения sort_by (whitelist)
ORDERING_FIELDS = [
    'id', 'name', 'direction_id', 'teacher_id',
    'lesson_duration_minutes', 'lessons_per_week', 'group_start_date', 'active',
]


def _parse_list_params(request: Request) -> dict:
    """
    Извлечь и нормализовать параметры пагинации из query string.

    Поддерживаемые параметры:
      page, page_size, sort_by, sort_dir, filter[name], filter[active], ...

    Зеркалит parsePaginationRequest() из services/pagination.js.
    Бросает ValidationError при невалидном sort_by или sort_dir.
    """
    qp = request.query_params

    page = max(1, int(qp.get('page', 1) or 1))
    page_size = min(500, max(1, int(qp.get('page_size', 50) or 50)))

    sort_by = qp.get('sort_by', 'name') or 'name'
    sort_dir = qp.get('sort_dir', 'asc') or 'asc'

    if sort_by not in ORDERING_FIELDS:
        raise ValidationError(
            f"Invalid sort_by '{sort_by}'. Allowed: {ORDERING_FIELDS}"
        )
    if sort_dir not in ('asc', 'desc'):
        raise ValidationError(
            f"Invalid sort_dir '{sort_dir}'. Must be 'asc' or 'desc'."
        )

    # Express передаёт фильтры как filter[key]=value
    # DRF QueryDict делает их доступными через filter[name] ключи напрямую
    filters: dict = {}
    for key, value in qp.items():
        if key.startswith('filter[') and key.endswith(']'):
            filter_key = key[7:-1]
            filters[filter_key] = value

    return {
        'page': page,
        'page_size': page_size,
        'sort_by': sort_by,
        'sort_dir': sort_dir,
        'filters': filters,
    }


class GroupListCreateView(APIView):
    """
    GET  /api/admin/groups  — список групп с пагинацией
    POST /api/admin/groups  — создать группу
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        params = _parse_list_params(request)
        result = services.list_groups(**params)
        return Response(result)

    def post(self, request: Request) -> Response:
        serializer = GroupWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            group = services.create_group(serializer.validated_data)
        except (IntegrityError, ValidationError) as exc:
            if _is_unique_violation(exc):
                return Response(
                    {'error': 'Already exists'},
                    status=status.HTTP_409_CONFLICT,
                )
            raise

        return Response(group, status=status.HTTP_201_CREATED)


class GroupDetailView(APIView):
    """
    GET    /api/admin/groups/:id  — получить группу
    PATCH  /api/admin/groups/:id  — обновить группу
    DELETE /api/admin/groups/:id  — мягкое удаление
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        group = services.get_group(pk)
        if group is None:
            raise NotFound({'error': 'Not found'})
        return Response(group)

    def patch(self, request: Request, pk: int) -> Response:
        serializer = GroupUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = services.update_group(pk, serializer.validated_data)
        if updated is None:
            raise NotFound({'error': 'Not found'})

        return Response(updated)

    def delete(self, request: Request, pk: int) -> Response:
        ok = services.soft_delete_group(pk)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(status=status.HTTP_204_NO_CONTENT)


class GroupScheduleView(APIView):
    """
    GET  /api/admin/groups/:id/schedule         — слоты (с датами действия) + исключения
    POST /api/admin/groups/:id/schedule-change  — постоянная смена расписания
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        sched = services.get_schedule(pk)
        if sched is None:
            raise NotFound({'error': 'Not found'})
        return Response(sched)


class GroupScheduleChangeView(APIView):
    """POST /api/admin/groups/:id/schedule-change — постоянная смена времени."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        serializer = ScheduleChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = services.apply_schedule_change(pk, serializer.validated_data)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                return Response({'error': 'Slot already exists'}, status=status.HTTP_409_CONFLICT)
            raise
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_unique_violation(exc: Exception) -> bool:
    """Проверить, является ли ошибка нарушением уникальности (pgcode 23505)."""
    pgcode = getattr(exc, 'pgcode', None)
    if pgcode == '23505':
        return True
    cause = getattr(exc, '__cause__', None)
    if cause and getattr(cause, 'pgcode', None) == '23505':
        return True
    return False
