"""
StudentsView — тонкие APIView для /api/admin/students.

Зеркалит Express routes/admin/students.js:
  GET    /api/admin/students           → список + пагинация → 200
  GET    /api/admin/students/:id       → один ученик → 200 | 404
  GET    /api/admin/students/:id/stats → посещаемость → 200 | 404
  GET    /api/admin/students/:id/balance → баланс → 200
  POST   /api/admin/students           → создать → 201
  PATCH  /api/admin/students/:id       → обновить → 200 | 404
  DELETE /api/admin/students/:id       → soft-delete → 204 | 404

Права: только manager или admin (IsManagerOrAdmin).
"""
from __future__ import annotations

from rest_framework import generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import StandardPagination
from apps.core.permissions import IsAdminOrSuperAdmin, IsManagerOrAdmin, ReadStaffWriteAdmin
from apps.payments import services as payment_services
from apps.students import services
from apps.students.models import StudentComment
from apps.students.serializers import (
    StudentCommentSerializer,
    StudentCommentWriteSerializer,
)
from apps.students.serializers import (
    StudentFreezePreviewSerializer,
    StudentResumeSerializer,
    StudentStatusSerializer,
    StudentUpdateSerializer,
    StudentWriteSerializer,
)

# Допустимые значения sort_by (whitelist)
ORDERING_FIELDS = [
    'id', 'full_name', 'age',
    'enrollment_status', 'first_purchase_date', 'created_at',
]


def _parse_list_params(request: Request) -> dict:
    """
    Извлечь и нормализовать параметры пагинации из query string.

    Поддерживаемые параметры:
      page, page_size, sort_by, sort_dir, filter[name], filter[enrollment_status], ...

    Зеркалит parsePaginationRequest() из services/pagination.js.
    Бросает ValidationError при невалидном sort_by или sort_dir.
    """
    qp = request.query_params

    page = max(1, int(qp.get('page', 1) or 1))
    page_size = min(500, max(1, int(qp.get('page_size', 50) or 50)))

    sort_by = qp.get('sort_by', 'full_name') or 'full_name'
    sort_dir = qp.get('sort_dir', 'asc') or 'asc'

    if sort_by not in ORDERING_FIELDS:
        raise ValidationError(
            f"Invalid sort_by '{sort_by}'. Allowed: {ORDERING_FIELDS}"
        )
    if sort_dir not in ('asc', 'desc'):
        raise ValidationError(
            f"Invalid sort_dir '{sort_dir}'. Must be 'asc' or 'desc'."
        )

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


class StudentListCreateView(APIView):
    """
    GET  /api/admin/students  — список учеников с пагинацией
    POST /api/admin/students  — создать ученика
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        params = _parse_list_params(request)
        result = services.list_students(**params)
        return Response(result)

    def post(self, request: Request) -> Response:
        serializer = StudentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        student = services.create_student(serializer.validated_data)
        return Response(student, status=status.HTTP_201_CREATED)


class StudentDetailView(APIView):
    """
    GET    /api/admin/students/:id  — получить ученика
    PATCH  /api/admin/students/:id  — обновить ученика
    DELETE /api/admin/students/:id  — мягкое удаление
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        student = services.get_student(pk)
        if student is None:
            raise NotFound({'error': 'Not found'})
        return Response(student)

    def patch(self, request: Request, pk: int) -> Response:
        serializer = StudentUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = services.update_student(pk, serializer.validated_data)
        if updated is None:
            raise NotFound({'error': 'Not found'})

        return Response(updated)

    def delete(self, request: Request, pk: int) -> Response:
        ok = services.soft_delete_student(pk)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudentStatsView(APIView):
    """
    GET /api/admin/students/:id/stats — посещаемость ученика.

    404 если ученик не найден (в отличие от balance — там проверки нет).
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        # Проверяем существование ученика
        student = services.get_student(pk)
        if student is None:
            raise NotFound({'error': 'Not found'})

        stats = services.student_stats(pk)
        return Response(stats)


class StudentBalanceView(APIView):
    """
    GET /api/admin/students/:id/balance — баланс ученика по направлениям.

    Express не проверяет существование ученика — просто возвращает данные.
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        balance = services.get_student_balance(pk)
        return Response(balance)


class StudentCommentListView(generics.ListAPIView):
    """
    GET  /api/admin/students/:id/comments — список комментариев, пагинация
    POST /api/admin/students/:id/comments — добавить комментарий → 201

    404 если ученик не найден (единообразно с StudentStatsView).
    """

    permission_classes = [IsManagerOrAdmin]
    pagination_class = StandardPagination
    serializer_class = StudentCommentSerializer

    def get_queryset(self):
        return (
            StudentComment.objects
            .filter(student_id=self.kwargs['pk'])
            .select_related('author')
            .order_by('-created_at')
        )

    def get(self, request: Request, pk: int) -> Response:
        if services.get_student(pk) is None:
            raise NotFound({'error': 'Not found'})
        return super().get(request, pk)

    def post(self, request: Request, pk: int) -> Response:
        if services.get_student(pk) is None:
            raise NotFound({'error': 'Not found'})
        ser = StudentCommentWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        comment = services.add_comment(
            pk, ser.validated_data['body'], getattr(request.user, 'id', None))
        return Response(StudentCommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class StudentCommentDetailView(APIView):
    """DELETE /api/admin/students/:id/comments/:comment_id — только admin/superadmin."""

    permission_classes = [ReadStaffWriteAdmin]

    def delete(self, request: Request, pk: int, comment_id: int) -> Response:
        ok = services.delete_comment(pk, comment_id)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudentRefundView(APIView):
    """POST /api/admin/students/{id}/refund — возврат неотработанного остатка (admin/superadmin)."""

    permission_classes = [IsAdminOrSuperAdmin]

    def post(self, request: Request, pk: int) -> Response:
        user = request.user
        author = (getattr(user, 'full_name', None) or getattr(user, 'email', None)) if user else None
        result = payment_services.refund_student(pk, created_by=author)
        if result.get('error') == 'student_not_found':
            raise NotFound({'error': 'Not found'})
        if result.get('error') == 'nothing_to_refund':
            return Response({'error': 'nothing_to_refund'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_201_CREATED)


class StudentStatusView(APIView):
    """POST /api/admin/students/:id/status — смена статуса с каскадом. 404 если нет.

    400 при frozen→enrolled напрямую (services.change_student_status бросает
    ValueError — используйте /resume для выхода из заморозки)."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        ser = StudentStatusSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            ok = services.change_student_status(
                pk, data['status'],
                frozen_from=data.get('frozen_from'),
                frozen_until=data.get('frozen_until'),
                membership_ids=data.get('membership_ids'),
                actor=request.user,
            )
        except ValueError as exc:
            raise ValidationError({'error': str(exc)})
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(services.get_student(pk))


class StudentFreezePreviewView(APIView):
    """POST /api/admin/students/:id/status/preview — дран-превью заморозки (read-only).

    Для каждого ИНДИВ-членства из membership_ids считает без записи в БД:
    lesson_on_frozen_from (на дату frozen_from стоит урок?) и
    first_lesson_after_resume (первая дата хвоста после перекладки от frozen_until).
    Групповые membership_ids молча исключаются (у групп расписание не сдвигается).

    Возвращает плоский словарь {membership_id: {...}} (ключи станут строками в JSON —
    фронт ищет по id). Существование ученика НЕ проверяем: это stateless-вычисление,
    скоуп задаётся самими membership_ids, а не статусом/наличием ученика; путь под
    /students/:id — лишь для единообразия с /status и /resume."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        ser = StudentFreezePreviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        result = services.preview_freeze_schedule(
            data['membership_ids'],
            frozen_from=data['frozen_from'],
            frozen_until=data['frozen_until'],
        )
        return Response(result)


class StudentResumeView(APIView):
    """POST /api/admin/students/:id/resume — выход из заморозки. 404 если нет/не заморожен."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        ser = StudentResumeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ok = services.resume_student(
            pk, actual_resume_date=ser.validated_data['actual_resume_date'],
            actor=request.user)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(services.get_student(pk))
