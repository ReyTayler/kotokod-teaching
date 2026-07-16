"""
Тонкие APIView для extra_lessons.

Admin (IsManagerOrAdmin, менеджер/админ/суперадмин — явное требование фичи,
не общий ReadStaffWriteAdmin раздела lessons):
  GET  /api/admin/extra-lessons             → список {rows,total,page,page_size}
  POST /api/admin/extra-lessons             → 201 (назначение)
  GET  /api/admin/extra-lessons/:id         → 200 | 404
  DELETE /api/admin/extra-lessons/:id       → 204 | 404 | 409 (не done)
  POST /api/admin/extra-lessons/:id/cancel  → 200 | 404 | 409 (не scheduled)

Teacher (IsTeacher, скоуп — своё назначение):
  GET  /api/extra-lessons/:id         → 200 | 404 (чужое = 404, не 403 — не
                                         раскрываем существование чужих назначений)
  POST /api/extra-lessons/:id/record  → 200 | 404 | 403 (чужое) | 409 (не scheduled)
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin, IsTeacher
from apps.core.utils.dates import msk_today
from apps.extra_lessons import repository, services
from apps.extra_lessons.exceptions import (
    DuplicateAssignment, MissedLessonNotFound, NotTeachersAssignment,
)
from apps.extra_lessons.serializers import (
    ExtraLessonCreateSerializer, ExtraLessonRecordSerializer,
)

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 500


def _parse_list_params(request: Request) -> dict:
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
    sort_by = qp.get('sort_by') or 'scheduled_date'
    sort_dir = qp.get('sort_dir')
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'desc'
    filters = {}
    if qp.get('status'):
        filters['status'] = qp['status']
    if qp.get('teacher_id'):
        filters['teacher_id'] = qp['teacher_id']
    return {'page': page, 'page_size': page_size, 'sort_by': sort_by, 'sort_dir': sort_dir, 'filters': filters}


class ExtraLessonListCreateView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        params = _parse_list_params(request)
        return Response(services.list_assignments(**params))

    def post(self, request: Request) -> Response:
        serializer = ExtraLessonCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = services.create_assignment(serializer.validated_data, request)
        except MissedLessonNotFound as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except DuplicateAssignment as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(result, status=status.HTTP_201_CREATED)


class ExtraLessonDetailView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        full = repository.get_assignment_full(pk)
        if full is None:
            raise NotFound({'error': 'Not found'})
        return Response(full)

    def delete(self, request: Request, pk: int) -> Response:
        try:
            ok = services.delete_fact(pk, request)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExtraLessonCancelView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        try:
            result = services.cancel_assignment(pk, request)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)


class TeacherExtraLessonDetailView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request: Request, pk: int) -> Response:
        result = services.get_assignment_for_teacher(pk, request.user.teacher_id)
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)


class TeacherExtraLessonRecordView(APIView):
    permission_classes = [IsTeacher]

    def post(self, request: Request, pk: int) -> Response:
        serializer = ExtraLessonRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        try:
            result = services.record(
                pk,
                teacher_id=request.user.teacher_id,
                attendance=v['attendance'],
                record_url=v.get('record_url') or None,
                submitted_by_token=f'acct:{request.user.id}',
                submit_date=msk_today(),
                request=request,
            )
        except NotTeachersAssignment as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)
