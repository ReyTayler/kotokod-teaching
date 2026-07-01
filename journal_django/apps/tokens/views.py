"""
TokensView — ViewSet для /api/admin/tokens.

Зеркалит Express routes/admin/tokens.js:
  GET  /api/admin/tokens           → list()     → 200 [...]
  POST /api/admin/tokens/generate  → generate() → 200 { token: '...' }
  POST /api/admin/tokens           → create()   → 201 | 409
  PATCH /api/admin/tokens/:token   → update()   → 200 | 404
  DELETE /api/admin/tokens/:token  → destroy()  → 204 | 404

Параметры: ?include_inactive=1 (GET список).
PK — token (строка), не числовой id.
Права: только manager или admin (IsManagerOrAdmin).

ВАЖНО: /generate должен быть смонтирован ПЕРЕД /:token, иначе DRF
поймает 'generate' как значение параметра token.
"""
from __future__ import annotations

from django.db import IntegrityError
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin
from apps.tokens import services
from apps.tokens.serializers import TokenUpdateSerializer, TokenWriteSerializer


class TokenListCreateView(APIView):
    """
    GET  /api/admin/tokens  — список токенов
    POST /api/admin/tokens  — создать токен
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        include_inactive = request.query_params.get('include_inactive') == '1'
        rows = services.list_tokens(include_inactive=include_inactive)
        return Response(rows)

    def post(self, request: Request) -> Response:
        serializer = TokenWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            token = services.create_token(serializer.validated_data)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                return Response(
                    {'error': 'Already exists'},
                    status=status.HTTP_409_CONFLICT,
                )
            raise

        return Response(token, status=status.HTTP_201_CREATED)


class TokenGenerateView(APIView):
    """
    POST /api/admin/tokens/generate — сгенерировать случайный токен.

    Возвращает { token: 'XXX-XXX-XXX' } без сохранения в БД.
    """

    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request) -> Response:
        return Response({'token': services.generate_random_token()})


class TokenDetailView(APIView):
    """
    PATCH  /api/admin/tokens/:token  — обновить токен
    DELETE /api/admin/tokens/:token  — отозвать токен (active=false)
    """

    permission_classes = [IsManagerOrAdmin]

    def patch(self, request: Request, token: str) -> Response:
        serializer = TokenUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = services.update_token(token, serializer.validated_data)
        if updated is None:
            raise NotFound({'error': 'Not found'})

        return Response(updated)

    def delete(self, request: Request, token: str) -> Response:
        ok = services.revoke_token(token)
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
