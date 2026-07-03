"""
Тонкая вьюха календаря плановых занятий (role=teacher).

GET /api/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD
  → { occurrences, unscheduled, window }

Скоуп — ТОЛЬКО группы текущего преподавателя (request.user.teacher_id): кабинет
не показывает чужие расписания. Вся логика — в services.py.
"""
from __future__ import annotations

import datetime

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin, IsTeacher
from apps.scheduling import services

# Максимальная ширина окна (дней) — календарь просит неделю/месяц; ограничиваем,
# чтобы не генерировать occurrences на произвольно большой диапазон.
_MAX_WINDOW_DAYS = 92


class CalendarView(APIView):
    """GET /api/calendar — плановые занятия преподавателя за окно [from, to]."""

    permission_classes = [IsTeacher]

    def get(self, request: Request) -> Response:
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

        result = services.build_calendar(d_from, d_to, teacher_id=request.user.teacher_id)
        return Response(result)


# ---------------------------------------------------------------------------
# Admin-план (RBAC IsManagerOrAdmin) — заглушки. Бизнес-логика операций над
# planned_lessons (generate/reschedule/permanent-change/cancel/extra) добавляется
# в шагах 2 и 4 (planner.py + repository.py). Здесь — только маршруты и RBAC:
# доступ проверяется на API, а не только на фронте. Мутации требуют X-CSRFToken.
# ---------------------------------------------------------------------------

def _not_implemented() -> Response:
    """Единый ответ-заглушка admin-плана (реализация — шаги 2/4)."""
    return Response(
        {'error': 'Not implemented yet.'},
        status=status.HTTP_501_NOT_IMPLEMENTED,
    )


class GroupPlanView(APIView):
    """
    GET  /api/admin/groups/<pk>/plan          — список плановых занятий группы.
    POST /api/admin/groups/<pk>/plan/generate — сгенерировать план (идемпотентно).
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        return _not_implemented()


class GroupPlanGenerateView(APIView):
    """POST /api/admin/groups/<pk>/plan/generate — генерация плана."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        return _not_implemented()


class GroupPlanRescheduleView(APIView):
    """POST /api/admin/groups/<pk>/plan/<lid>/reschedule — разовый перенос (+опц. teacher)."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int, lid: int) -> Response:
        return _not_implemented()


class GroupPlanPermanentChangeView(APIView):
    """POST /api/admin/groups/<pk>/plan/permanent-change — перенос навсегда (с seq/даты)."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        return _not_implemented()


class GroupPlanCancelView(APIView):
    """POST /api/admin/groups/<pk>/plan/<lid>/cancel — отмена со сдвигом хвоста."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int, lid: int) -> Response:
        return _not_implemented()


class GroupPlanExtraView(APIView):
    """POST /api/admin/groups/<pk>/plan/extra — доп. занятие (вне курса)."""

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        return _not_implemented()
