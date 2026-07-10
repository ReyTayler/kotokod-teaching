"""
PaymentsView — тонкие APIView для /api/admin/payments.

Зеркалит Express routes/admin/payments.js:
  GET    /api/admin/payments      → список с фильтрами → 200 [...]
  GET    /api/admin/payments/:id  → одна запись → 200 | 404
  POST   /api/admin/payments      → создать → 201 | 400 | 404
  DELETE /api/admin/payments/:id  → хард-удалить → 200 | 404

Права: только manager или admin (IsManagerOrAdmin).
POST коды ошибок (дословно payments.js:30-43):
  direction_not_found → 404 {error: 'Direction not found'}
  no_capacity         → 400 {error: 'no_capacity', message: '...'}
  cap_exceeded        → 400 {error: 'cap_exceeded', already, cap_subscriptions}
DELETE: 200 {deleted: true, new_balance} + warning: 'balance_negative' если < 0.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin
from apps.payments import services
from apps.payments.serializers import PaymentCreateSerializer


class PaymentListCreateView(APIView):
    """
    GET  /api/admin/payments  — список оплат с фильтрами
    POST /api/admin/payments  — создать оплату
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        qp = request.query_params
        student_id = int(qp['student_id']) if qp.get('student_id') else None
        direction_id = int(qp['direction_id']) if qp.get('direction_id') else None
        from_ = qp.get('from') or None
        to = qp.get('to') or None

        rows = services.list_payments(
            student_id=student_id,
            direction_id=direction_id,
            from_=from_,
            to=to,
        )
        return Response(rows)

    def post(self, request: Request) -> Response:
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = dict(serializer.validated_data)
        user = request.user
        data['created_by'] = (getattr(user, 'full_name', None) or getattr(user, 'email', None)) if user else None

        result = services.create_payment(data)

        if result.get('error') == 'direction_not_found':
            return Response(
                {'error': 'Direction not found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if result.get('error') == 'no_capacity':
            return Response(
                {'error': 'no_capacity', 'message': 'У направления не задан total_lessons'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if result.get('error') == 'cap_exceeded':
            return Response(
                {
                    'error': 'cap_exceeded',
                    'already': result['already'],
                    'cap_subscriptions': result['cap_subscriptions'],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(result['payment'], status=status.HTTP_201_CREATED)


class PaymentDetailView(APIView):
    """
    GET    /api/admin/payments/:id  — получить оплату
    DELETE /api/admin/payments/:id  — хард-удалить оплату
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        payment = services.get_payment(pk)
        if payment is None:
            raise NotFound({'error': 'Not found'})
        return Response(payment)

    def delete(self, request: Request, pk: int) -> Response:
        result = services.delete_payment(pk)
        if not result['deleted']:
            raise NotFound({'error': 'Not found'})

        body: dict = {'deleted': True, 'new_balance': result['new_balance']}
        if result['new_balance'] < 0:
            body['warning'] = 'balance_negative'

        return Response(body)
