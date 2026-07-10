"""
Движок сделок продления: идемпотентная генерация, закрытие won/lost, респавн цикла.

Все операции безопасны к повторному вызову (для сигналов и ночной команды).
Стадии берём из дефолтной воронки; авто-стадия прогресса — kind='progress'.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.db import connection, transaction
from django.utils import timezone

from apps.renewals import cycle
from apps.renewals.models import RenewalActivity, RenewalDeal, RenewalPipeline, RenewalStage

logger = logging.getLogger(__name__)


def _default_pipeline() -> RenewalPipeline:
    return RenewalPipeline.objects.get(is_default=True)


def _stage(pipeline: RenewalPipeline, *, kind: str) -> RenewalStage:
    """Первая по порядку стадия заданного вида (progress/won/lost)."""
    return (RenewalStage.objects
            .filter(pipeline=pipeline, kind=kind)
            .order_by('sort_order').first())


def _progress_stages(pipeline: RenewalPipeline) -> list[RenewalStage]:
    """
    Авто-стадии прогресса «Урок N» воронки, по порядку (sort_order).

    Специально фильтруем is_auto=True, а не просто kind='progress' — superadmin
    может через настройку стадий завести свою decision-подобную стадию с
    kind='progress' (это разрешено сериализатором), и она не должна путать
    нумерацию «Урок 1..N», завязанную только на движковые авто-стадии.
    """
    return list(RenewalStage.objects
                .filter(pipeline=pipeline, kind='progress', is_auto=True)
                .order_by('sort_order'))


def _attended_lessons(student_id: int, direction_id: int) -> float:
    with connection.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(SUM(m.lessons_done), 0)
            FROM group_memberships m
            JOIN groups g ON g.id = m.group_id
            WHERE m.student_id = %s AND g.direction_id = %s AND m.active = true
        """, [student_id, direction_id])
        return float(cur.fetchone()[0] or 0)


@transaction.atomic
def ensure_deal(student_id: int, direction_id: int, cycle_no: int,
                assignee_id: Optional[int] = None) -> RenewalDeal:
    """Создать (или вернуть существующую) сделку цикла. Идемпотентно по UNIQUE."""
    pipeline = _default_pipeline()
    progress_stages = _progress_stages(pipeline)
    progress = progress_stages[0] if progress_stages else _stage(pipeline, kind='progress')
    deal, created = RenewalDeal.objects.get_or_create(
        student_id=student_id, direction_id=direction_id, cycle_no=cycle_no,
        defaults={'pipeline': pipeline, 'stage': progress, 'assignee_id': assignee_id},
    )
    if created:
        RenewalActivity.objects.create(
            deal=deal, kind='system', to_stage=progress, body='Сделка создана')
    return deal


@transaction.atomic
def sync_lesson_stage(student_id: int, direction_id: int) -> None:
    """
    Держит открытую сделку на правильной авто-стадии «Урок N» по факту
    посещаемости (вызывается после записи/правки посещаемости урока).

    Идемпотентно и безопасно: если сделки нет, либо её уже увели в
    decision/won/lost (менеджер сам решил её судьбу) — не трогаем. Авто-прогресс
    работает только пока сделка находится в исходной progress-фазе.
    """
    deal = (RenewalDeal.objects
            .select_for_update()
            .select_related('stage', 'pipeline')
            .filter(student_id=student_id, direction_id=direction_id, outcome_at__isnull=True)
            .order_by('-cycle_no').first())
    if deal is None or deal.stage.kind != 'progress':
        return

    stages = _progress_stages(deal.pipeline)
    if not stages:
        return

    attended = _attended_lessons(student_id, direction_id)
    idx = min(int(attended % cycle.LESSONS_PER_CYCLE), len(stages) - 1)
    target = stages[idx]
    if target.id == deal.stage_id:
        return

    from_stage = deal.stage
    deal.stage = target
    deal.stage_entered_at = timezone.now()
    deal.save(update_fields=['stage', 'stage_entered_at', 'updated_at'])
    RenewalActivity.objects.create(
        deal=deal, kind='system', from_stage=from_stage, to_stage=target,
        body=f'Автопрогресс по посещаемости: {target.label}')


def sync_lesson_stage_safe(student_id: int, direction_id: Optional[int]) -> None:
    """
    Safe-обёртка над sync_lesson_stage для вызова из apps.lessons/apps.teacher_spa
    через transaction.on_commit — сбой синхронизации авто-стадии никогда не должен
    ронять сохранение урока/посещаемости (основной, учебный поток важнее CRM).
    """
    if direction_id is None:
        return
    try:
        sync_lesson_stage(student_id, direction_id)
    except Exception:
        logger.exception(
            'renewals: не удалось синхронизировать авто-стадию (student=%s, direction=%s)',
            student_id, direction_id)


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
