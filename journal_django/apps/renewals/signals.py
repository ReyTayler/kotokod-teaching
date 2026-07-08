"""
Сигналы renewals:
  • оплата (Payment) → закрыть сделку направления как «Продлён» + респавн цикла.

Оплаты в проде создаются через ORM (apps/payments/repository.create_payment →
Payment.objects.create), поэтому post_save отрабатывает штатно.
Идемпотентность обеспечивает engine (get_or_create / select_for_update):
close_deal_won без открытой сделки — безопасный no-op.
"""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.payments.models import Payment
from apps.renewals import engine


@receiver(post_save, sender=Payment, dispatch_uid='renewals_on_payment')
def on_payment_created(sender, instance: Payment, created: bool, **kwargs) -> None:
    if not created or instance.direction_id is None:
        return  # легаси-оплаты без направления пропускаем
    engine.close_deal_won(instance.student_id, instance.direction_id, payment_id=instance.id)
