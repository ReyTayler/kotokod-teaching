"""
Движок сделок продления: идемпотентная генерация, закрытие won/lost, респавн цикла.

Все операции безопасны к повторному вызову (для сигналов и ночной команды).
Стадии берём из дефолтной воронки; авто-стадия прогресса — kind='progress'.
"""
from __future__ import annotations

from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.renewals.models import RenewalActivity, RenewalDeal, RenewalPipeline, RenewalStage


def _default_pipeline() -> RenewalPipeline:
    return RenewalPipeline.objects.get(is_default=True)


def _stage(pipeline: RenewalPipeline, *, kind: str) -> RenewalStage:
    """Первая по порядку стадия заданного вида (progress/won/lost)."""
    return (RenewalStage.objects
            .filter(pipeline=pipeline, kind=kind)
            .order_by('sort_order').first())


@transaction.atomic
def ensure_deal(student_id: int, direction_id: int, cycle_no: int,
                assignee_id: Optional[int] = None) -> RenewalDeal:
    """Создать (или вернуть существующую) сделку цикла. Идемпотентно по UNIQUE."""
    pipeline = _default_pipeline()
    progress = _stage(pipeline, kind='progress')
    deal, created = RenewalDeal.objects.get_or_create(
        student_id=student_id, direction_id=direction_id, cycle_no=cycle_no,
        defaults={'pipeline': pipeline, 'stage': progress, 'assignee_id': assignee_id},
    )
    if created:
        RenewalActivity.objects.create(
            deal=deal, kind='system', to_stage=progress, body='Сделка создана')
    return deal


@transaction.atomic
def close_deal_won(student_id: int, direction_id: int,
                   payment_id: Optional[int] = None) -> Optional[RenewalDeal]:
    """Закрыть открытую сделку как «Продлён» и породить следующий цикл."""
    deal = (RenewalDeal.objects
            .select_for_update()
            .filter(student_id=student_id, direction_id=direction_id, outcome_at__isnull=True)
            .order_by('-cycle_no').first())
    if deal is None:
        return None
    won = _stage(deal.pipeline, kind='won')
    from_stage = deal.stage
    deal.stage = won
    deal.outcome_at = timezone.now()
    deal.stage_entered_at = timezone.now()
    deal.save(update_fields=['stage', 'outcome_at', 'stage_entered_at', 'updated_at'])
    RenewalActivity.objects.create(
        deal=deal, kind='payment_linked', from_stage=from_stage, to_stage=won,
        payment_id=payment_id, body='Продление подтверждено оплатой')
    ensure_deal(student_id, direction_id, deal.cycle_no + 1, assignee_id=deal.assignee_id)
    return deal
