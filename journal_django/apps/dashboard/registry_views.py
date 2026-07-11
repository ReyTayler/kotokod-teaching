"""
Тонкие APIView для «Реестра куратора» — вторая вкладка дашборда.

  GET /api/admin/registry/summary   → { generated_at, kpis, today_stream, signals }
  GET /api/admin/registry/students  → пагинированный список активных учеников
        ?page= &page_size= &segment= &search= &sort_by= &sort_dir=

Права: manager или admin (IsManagerOrAdmin) — как основной дашборд.
Логика — в registry_service; здесь только валидация query-параметров, пагинация
готового списка (StandardPagination) и сериализация. Query-параметры sort_by/
sort_dir/segment валидируются по whitelist → ValidationError на кривом значении
(паттерн sort-dir: явная проверка, без тихого дефолта).
"""
from __future__ import annotations

from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import StandardPagination
from apps.core.permissions import IsManagerOrAdmin
from apps.dashboard import registry_service as svc


class RegistrySummaryView(APIView):
    """GET /api/admin/registry/summary — KPI, поток дня, сигналы (без списка)."""

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        return Response(svc.get_summary())


class RegistryStudentsView(APIView):
    """GET /api/admin/registry/students — серверно-пагинированный список учеников."""

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        qp = request.query_params

        segment = qp.get('segment', 'all')
        if segment not in svc.SEGMENTS:
            raise ValidationError(f"Invalid segment '{segment}'. Allowed: {list(svc.SEGMENTS)}")

        sort_by = qp.get('sort_by', 'urgency')
        if sort_by not in svc.SORTS:
            raise ValidationError(f"Invalid sort_by '{sort_by}'. Allowed: {list(svc.SORTS)}")

        sort_dir = qp.get('sort_dir', 'asc')
        if sort_dir not in svc.SORT_DIRS:
            raise ValidationError(f"Invalid sort_dir '{sort_dir}'. Must be 'asc' or 'desc'.")

        # Вариант B: пагинация НА УРОВНЕ БД — DRF режет queryset LIMIT/OFFSET,
        # сериализуем только строки страницы (догрузка кодов/преподов батчем).
        qs = svc.students_qs(
            segment=segment,
            search=qp.get('search', ''),
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(svc.serialize_rows(page))
