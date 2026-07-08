"""
Сигналы renewals:
  • оплата (Payment) → закрыть сделку направления как «Продлён» + респавн цикла.

Оплаты в проде создаются через ORM (apps/payments/repository.create_payment →
Payment.objects.create), поэтому post_save отрабатывает штатно.
Идемпотентность обеспечивает engine (get_or_create / select_for_update):
close_deal_won без открытой сделки — безопасный no-op.

ВАЖНО: Payment — денежный immutable-инвариант. Закрытие сделки — вторичная
CRM-фича и НЕ должно влиять на транзакцию оплаты. Поэтому:
  • вызов отложен на transaction.on_commit — выполнится ТОЛЬКО после успешного
    коммита оплаты (сбой CRM не откатит деньги);
  • любое исключение внутри проглатывается с логированием (logger.exception),
    чтобы не всплыть наружу и не сломать поток;
  • backstop — ночная команда rebuild_renewal_deals досоздаст сделки.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.payments.models import Payment
from apps.renewals import engine

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Payment, dispatch_uid='renewals_on_payment')
def on_payment_created(sender, instance: Payment, created: bool, **kwargs) -> None:
    if not created or instance.direction_id is None:
        return  # легаси-оплаты без направления пропускаем

    student_id = instance.student_id
    direction_id = instance.direction_id
    payment_id = instance.id

    def _close() -> None:
        try:
            engine.close_deal_won(student_id, direction_id, payment_id=payment_id)
        except Exception:
            logger.exception(
                'renewals: не удалось закрыть сделку по оплате id=%s', payment_id)

    transaction.on_commit(_close)
