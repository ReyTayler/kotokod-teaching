"""
Инвалидация кэша сводки «Реестра куратора» на мутациях баланса.

Дашборд (read-model) САМ подписывается на изменения Payment — payments про кэш
реестра ничего не знает (правильное направление зависимостей). Сброс откладывается
на transaction.on_commit: срабатывает ТОЛЬКО после успешного коммита, при откате
оплаты кэш не трогается. Покрывает любые оплаты (create/delete/refund) — где бы их
ни создавали, а не только 3 метода сервиса.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.dashboard.registry_service import invalidate_registry_cache
from apps.payments.models import Payment


@receiver(post_save, sender=Payment, dispatch_uid='registry_invalidate_on_payment_save')
@receiver(post_delete, sender=Payment, dispatch_uid='registry_invalidate_on_payment_delete')
def invalidate_registry_on_payment_change(sender, **kwargs) -> None:
    """Баланс ученика изменился → сбросить кэш сводки после коммита транзакции."""
    transaction.on_commit(invalidate_registry_cache)
