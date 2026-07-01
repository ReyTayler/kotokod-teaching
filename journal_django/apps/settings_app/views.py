"""
SettingsView — ViewSet для /api/admin/settings.

Зеркалит Express routes/admin/settings.js:
  GET /api/admin/settings  → get()  → 200 { settings: {...} }
  PUT /api/admin/settings  → put()  → 200 { settings: {...} }

Ключ настроек — account_id из сессии (request.user.account_id).
Права: только manager или admin (IsManagerOrAdmin).

adminSettingsSchema = z.object({}).passthrough() — любой JSON-объект.
Валидация типа напрямую во view (DRF Serializer не поддерживает passthrough без полей).
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin
from apps.settings_app import services


class AdminSettingsView(APIView):
    """
    GET /api/admin/settings  — получить настройки текущего аккаунта
    PUT /api/admin/settings  — сохранить настройки текущего аккаунта
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        account_id = request.user.id
        settings_data = services.get_settings(account_id)
        return Response({'settings': settings_data})

    def put(self, request: Request) -> Response:
        # adminSettingsSchema = z.object({}).passthrough() — любой объект
        body = request.data
        if not isinstance(body, dict):
            return Response(
                {'error': 'Settings must be a JSON object.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        account_id = request.user.id
        saved = services.upsert_settings(account_id, body)
        return Response({'settings': saved})
