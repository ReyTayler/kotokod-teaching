"""
Тонкая вьюха календаря плановых занятий (role=teacher).

GET /api/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD
  → { occurrences, unscheduled, window }

Скоуп — ТОЛЬКО группы текущего преподавателя (request.user.teacher_id): кабинет
не показывает чужие расписания. Вся логика — в services.py.
"""
from __future__ import annotations

import datetime

from django.db import IntegrityError
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin, IsTeacher
from apps.scheduling import services
from apps.scheduling.serializers import (
    PlanChangeTeacherPermanentSerializer, PlanChangeTeacherSerializer,
    PlanExtraSerializer, PlanPermanentChangeSerializer, PlanRescheduleSerializer,
)

# Максимальная ширина окна (дней) — календарь просит неделю/месяц; ограничиваем,
# чтобы не генерировать occurrences на произвольно большой диапазон.
_MAX_WINDOW_DAYS = 92


def _parse_window(request: Request) -> tuple[datetime.date, datetime.date] | Response:
    """
    Валидирует ?from=&to= (YYYY-MM-DD, to>=from, ширина ≤ _MAX_WINDOW_DAYS).
    Возвращает (d_from, d_to), либо готовый Response с 400 при ошибке —
    вызывающая сторона проверяет `isinstance(result, Response)`. Общий код
    для CalendarView (teacher) и AdminCalendarView (manager/admin/superadmin).
    """
    raw_from = request.query_params.get('from')
    raw_to = request.query_params.get('to')
    if not raw_from or not raw_to:
        return Response(
            {'error': 'Обязательны параметры from и to (YYYY-MM-DD).'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        d_from = datetime.date.fromisoformat(raw_from)
        d_to = datetime.date.fromisoformat(raw_to)
    except ValueError:
        return Response(
            {'error': 'from/to должны быть датами YYYY-MM-DD.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if d_to < d_from:
        return Response(
            {'error': 'to не может быть раньше from.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if (d_to - d_from).days > _MAX_WINDOW_DAYS:
        return Response(
            {'error': f'Слишком широкое окно (максимум {_MAX_WINDOW_DAYS} дней).'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return d_from, d_to


class CalendarView(APIView):
    """GET /api/calendar — плановые занятия преподавателя за окно [from, to]."""

    permission_classes = [IsTeacher]

    def get(self, request: Request) -> Response:
        window = _parse_window(request)
        if isinstance(window, Response):
            return window
        d_from, d_to = window

        result = services.build_calendar(d_from, d_to, teacher_id=request.user.teacher_id)
        return Response(result)


# ---------------------------------------------------------------------------
# Admin-план (RBAC IsManagerOrAdmin). Операции над planned_lessons
# (generate/reschedule/permanent-change/cancel/extra). Смонтированы под
# /api/admin/groups (ДО teacher-guard /api) → доступ проверяется на API, а не
# только на фронте. Мутации проходят DRF SessionAuthentication/CookieJWT →
# требуют X-CSRFToken (@csrf_exempt не ставим). Аудит — log_event в services.
# ---------------------------------------------------------------------------

def _is_unique_violation(exc: Exception) -> bool:
    """Нарушение уникальности PostgreSQL (pgcode 23505) — прямое или в __cause__."""
    if getattr(exc, 'pgcode', None) == '23505':
        return True
    cause = getattr(exc, '__cause__', None)
    return bool(cause and getattr(cause, 'pgcode', None) == '23505')


class GroupPlanView(APIView):
    """GET /api/admin/groups/<pk>/plan — список плановых занятий группы."""

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        plan = services.get_plan(pk)
        if plan is None:
            raise NotFound({'error': 'Not found'})
        return Response(plan)


class GroupPlanGenerateView(APIView):
    """POST /api/admin/groups/<pk>/plan/generate — генерация плана (идемпотентно)."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        try:
            plan = services.generate_plan(pk, request)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                return Response({'error': 'Conflict'}, status=status.HTTP_409_CONFLICT)
            raise
        if plan is None:
            raise NotFound({'error': 'Not found'})
        return Response(plan)


class GroupPlanRescheduleView(APIView):
    """POST /api/admin/groups/<pk>/plan/<lid>/reschedule — разовый перенос (+опц. teacher)."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int, lid: int) -> Response:
        serializer = PlanRescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = services.reschedule(pk, lid, serializer.validated_data, request)
        except ValueError as exc:
            # Перенос проведённого (status='done') — бизнес-конфликт, не 500.
            return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                return Response({'error': 'Conflict'}, status=status.HTTP_409_CONFLICT)
            raise
        if row is None:
            raise NotFound({'error': 'Not found'})
        return Response(row)


class GroupPlanPermanentChangeView(APIView):
    """POST /api/admin/groups/<pk>/plan/permanent-change — перенос навсегда (с seq/даты)."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        serializer = PlanPermanentChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            plan = services.permanent_change(pk, serializer.validated_data, request)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                return Response({'error': 'Slot already exists'}, status=status.HTTP_409_CONFLICT)
            raise
        if plan is None:
            raise NotFound({'error': 'Not found'})
        return Response(plan)


class GroupPlanCancelView(APIView):
    """POST /api/admin/groups/<pk>/plan/<lid>/cancel — отмена со сдвигом хвоста."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int, lid: int) -> Response:
        try:
            plan = services.cancel(pk, lid, request)
        except ValueError as exc:
            # Якорь не курсовой/активный (extra/cancelled/moved/done) — бизнес-ошибка.
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if plan is None:
            raise NotFound({'error': 'Not found'})
        return Response(plan)


class GroupPlanChangeTeacherView(APIView):
    """POST /api/admin/groups/<pk>/plan/<lid>/change-teacher — разовая смена препода."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int, lid: int) -> Response:
        serializer = PlanChangeTeacherSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = services.change_teacher(pk, lid, serializer.validated_data, request)
        except ValueError as exc:
            # Смена препода проведённого (status='done') — бизнес-конфликт, не 500.
            return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
        if row is None:
            raise NotFound({'error': 'Not found'})
        return Response(row)


class GroupPlanChangeTeacherPermanentView(APIView):
    """POST /api/admin/groups/<pk>/plan/change-teacher-permanent — смена препода хвоста."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        serializer = PlanChangeTeacherPermanentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            plan = services.change_teacher_permanent(pk, serializer.validated_data, request)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if plan is None:
            raise NotFound({'error': 'Not found'})
        return Response(plan)


class GroupPlanExtraView(APIView):
    """POST /api/admin/groups/<pk>/plan/extra — доп. занятие (вне курса)."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        serializer = PlanExtraSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = services.add_extra(pk, serializer.validated_data, request)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                return Response({'error': 'Conflict'}, status=status.HTTP_409_CONFLICT)
            raise
        if row is None:
            raise NotFound({'error': 'Not found'})
        return Response(row, status=status.HTTP_201_CREATED)
