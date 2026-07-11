from unittest.mock import patch

import pytest
from django.db.models.functions import Now

from apps.payments.models import Payment
from apps.renewals import engine
from apps.renewals.models import RenewalDeal


@pytest.mark.django_db
def test_payment_orm_create_closes_deal(django_capture_on_commit_callbacks,
                                        make_student, make_direction):
    # Закрытие сделки теперь отложено на transaction.on_commit (см. signals).
    # django_capture_on_commit_callbacks(execute=True) выполняет эти колбэки,
    # сохраняя обычный django_db (сид дефолтной воронки не флашится).
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    pay = None
    try:
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            # created_at без model-default (как в проде create_payment) → задаём явно.
            pay = Payment.objects.create(
                student_id=sid, direction_id=did, subscriptions_count=1,
                unit_price=4000, total_amount=4000, paid_at='2026-07-08', created_at=Now())
        # >= 1: на Payment.post_save подписаны и renewals (закрытие сделки), и
        # dashboard (сброс кэша реестра) — проверяем СВОЙ эффект ниже, не число слушателей.
        assert len(callbacks) >= 1
        assert RenewalDeal.objects.filter(
            student_id=sid, direction_id=did, outcome_at__isnull=False).count() == 1
        assert RenewalDeal.objects.filter(
            student_id=sid, direction_id=did, cycle_no=2, outcome_at__isnull=True).exists()
    finally:
        # payments ссылается на direction (RESTRICT) — чистим до teardown фикстур.
        if pay is not None:
            pay.delete()


@pytest.mark.django_db
def test_payment_create_survives_crm_failure(django_capture_on_commit_callbacks,
                                             make_student, make_direction):
    """Сбой во вторичной CRM-логике НЕ должен ронять создание денежной оплаты."""
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    pay = None
    try:
        with patch('apps.renewals.engine.close_deal_won', side_effect=RuntimeError('boom')):
            # колбэк выполнится на выходе из with — исключение проглатывается в сигнале,
            # наружу не всплывает и оплату не откатывает.
            with django_capture_on_commit_callbacks(execute=True):
                pay = Payment.objects.create(
                    student_id=sid, direction_id=did, subscriptions_count=1,
                    unit_price=4000, total_amount=4000, paid_at='2026-07-08', created_at=Now())
        # оплата фактически создана
        assert Payment.objects.filter(id=pay.id).exists()
        # сделка осталась открытой — CRM-закрытие не выполнилось из-за сбоя
        assert RenewalDeal.objects.filter(
            student_id=sid, direction_id=did, outcome_at__isnull=True).exists()
    finally:
        if pay is not None:
            pay.delete()
