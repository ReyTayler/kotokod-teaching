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

from apps.core.permissions import IsTeacher
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
