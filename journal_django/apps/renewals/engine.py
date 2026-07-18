"""
Движок сделок продления: идемпотентная генерация цикла, синхронизация
авто-стадии по посещаемости и балансу, переоткрытие закрытых сделок.

Движок НИКОГДА не закрывает сделку как «Продлён» сам — окончательное решение
о продлении принимает менеджер вручную (repository.move_deal). Все операции
здесь безопасны к повторному вызову. Стадии берём из дефолтной воронки;
авто-стадия прогресса — kind='progress'.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.renewals import cycle
from apps.renewals.models import RenewalActivity, RenewalDeal, RenewalPipeline, RenewalStage

logger = logging.getLogger(__name__)

# Ключ стадии «Заморожен» — is_auto=True только чтобы блокировать РУЧНОЙ вход/выход
# (Task 5), не чтобы sync_lesson_stage сам её пересчитывал. Единая точка правды
# для всех мест, где движок должен опознать именно эту стадию.
FROZEN_KEY = 'frozen'


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


def _attended_total(student_id: int) -> float:
    """
    Суммарно посещено уроков за ВСЮ историю ученика (half-lesson 45мин=0.5).
    Делегирует apps.finances.repository.attended_units_total — ЕДИНЫЙ источник
    «отработано», тот же, что и баланс/потребление finances (с исключением
    lesson_type='extra'). Раньше здесь был отдельный SQL БЕЗ исключения extra, из-за
    чего доп.урок задваивал прогресс сделки (регрессия 2026-07-18). Локальный импорт —
    чтобы не тянуть finances в граф импорта renewals на старте.
    """
    from apps.finances.repository import attended_units_total
    return float(attended_units_total(student_id))


def cycle_completed(deal: RenewalDeal) -> bool:
    """
    Отработаны ли все 4 урока ТЕКУЩЕГО цикла сделки — по факту посещаемости,
    независимо от того, на какой стадии она сейчас сидит (прогресс-стадия
    или «Ждём оплату» — обе бывают ДО завершения цикла, «Ждём оплату» просто
    когда деньги кончились раньше). Ворота для ручных переходов
    (repository.move_deal): пока цикл не завершён, вручную можно поставить
    только «Ушёл» — решение пользователя 2026-07-17.
    """
    attended = _attended_total(deal.student_id)
    into = attended - (deal.cycle_no - 1) * cycle.LESSONS_PER_CYCLE
    return into >= cycle.LESSONS_PER_CYCLE


@transaction.atomic
def ensure_deal(student_id: int, cycle_no: int,
                assignee_id: Optional[int] = None) -> RenewalDeal:
    """Создать (или вернуть существующую) сделку цикла ученика. Идемпотентно по UNIQUE."""
    pipeline = _default_pipeline()
    progress_stages = _progress_stages(pipeline)
    progress = progress_stages[0] if progress_stages else _stage(pipeline, kind='progress')
    deal, created = RenewalDeal.objects.get_or_create(
        student_id=student_id, cycle_no=cycle_no,
        defaults={'pipeline': pipeline, 'stage': progress, 'assignee_id': assignee_id},
    )
    if created:
        RenewalActivity.objects.create(
            deal=deal, kind='system', to_stage=progress, body='Сделка создана')
    return deal


def next_open_cycle_no(student_id: int, min_cycle_no: int) -> int:
    """
    Первый свободный номер цикла ученика (>= min_cycle_no), не занятый
    закрытой сделкой.

    ensure_deal с занятым номером вернул бы ЗАКРЫТУЮ сделку по
    UNIQUE(student, cycle_no) и не создал бы открытую — поэтому при спавне
    следующего цикла (ручное закрытие «Продлён», ручное создание сделки)
    такие номера нужно перешагивать: например, после переоткрытия/возврата,
    когда более поздний цикл уже закрыт «Ушёл».
    """
    taken = set(RenewalDeal.objects
                .filter(student_id=student_id, cycle_no__gte=min_cycle_no)
                .values_list('cycle_no', flat=True))
    cycle_no = min_cycle_no
    while cycle_no in taken:
        cycle_no += 1
    return cycle_no


def _auto_stages(pipeline: RenewalPipeline) -> dict[str, RenewalStage]:
    """Все авто-стадии воронки по key (Не было урока, Урок 1..3 + awaiting_payment + awaiting_renewal)."""
    return {s.key: s for s in RenewalStage.objects.filter(pipeline=pipeline, is_auto=True)}


def _target_auto_stage(deal: RenewalDeal, attended: float, balance: float,
                       auto: dict, progress_stages: list) -> tuple[Optional[RenewalStage], bool]:
    """
    Целевая авто-стадия сделки и флаг «цикл созрел» (для due_at).

    Прогресс считается от НОМЕРА ЦИКЛА сделки, а не attended % 4 —
    иначе после 4-го урока сделка «заворачивалась» обратно в «Урок 1».
    Приоритет при конфликте (цикл отработан И баланс ≤ 0): «Ждём продление» >
    «Ждём оплату» — более поздняя точка воронки; долг показывается бейджем.
    """
    into = attended - (deal.cycle_no - 1) * cycle.LESSONS_PER_CYCLE
    if into >= cycle.LESSONS_PER_CYCLE and 'awaiting_renewal' in auto:
        return auto['awaiting_renewal'], True
    if balance <= 0 and 'awaiting_payment' in auto:
        return auto['awaiting_payment'], False
    if not progress_stages:
        return None, False
    idx = min(max(int(into), 0), len(progress_stages) - 1)
    return progress_stages[idx], False


@transaction.atomic
def sync_lesson_stage(student_id: int) -> None:
    """
    Держит открытую сделку ученика на правильной авто-стадии по посещаемости
    и балансу (вызывается после записи/правки посещаемости урока и по оплатам).

    Двигает ТОЛЬКО между авто-стадиями (Не было урока, Урок 1–3, Ждём оплату, Ждём продление):
    если менеджер вручную увёл сделку в «Думает»/«Заморожен»/… или она закрыта —
    движок её не трогает.

    ИСКЛЮЧЕНИЕ: сделка на стадии 'frozen' тоже не трогается, хотя эта стадия
    is_auto=True (Task 5 сделала её авто исключительно чтобы заблокировать
    РУЧНОЙ вход/выход — не чтобы движок сам её пересчитывал по посещаемости/балансу).
    Разморозить может только явный вызов resume_from_freeze.
    """
    from apps.finances.repository import balance_for_student

    deal = _open_deal_for_update(student_id)
    if deal is None or not deal.stage.is_auto or deal.stage.key == FROZEN_KEY:
        return

    auto = _auto_stages(deal.pipeline)
    progress_stages = _progress_stages(deal.pipeline)
    attended = _attended_total(student_id)
    balance = float(balance_for_student(student_id))

    target, matured = _target_auto_stage(deal, attended, balance, auto, progress_stages)
    if target is None:
        return

    update_fields: list[str] = []
    if matured and deal.due_at is None:
        deal.due_at = timezone.now().date()
        update_fields.append('due_at')
    if target.id != deal.stage_id:
        from_stage = deal.stage
        deal.stage = target
        deal.stage_entered_at = timezone.now()
        update_fields += ['stage', 'stage_entered_at']
        RenewalActivity.objects.create(
            deal=deal, kind='system', from_stage=from_stage, to_stage=target,
            body=f'Автопереход: {target.label}')
    if update_fields:
        deal.save(update_fields=update_fields + ['updated_at'])


def sync_lesson_stage_safe(student_id: int, direction_id: Optional[int] = None) -> None:
    """
    Safe-обёртка над sync_lesson_stage для вызова из apps.lessons/apps.teacher_spa
    через transaction.on_commit — сбой синхронизации авто-стадии никогда не должен
    ронять сохранение урока/посещаемости (основной, учебный поток важнее CRM).

    direction_id сохранён в сигнатуре для совместимости вызовов, но сделка —
    сущность УЧЕНИКА (подписочная модель): направление игнорируется.
    """
    try:
        sync_lesson_stage(student_id)
    except Exception:
        logger.exception(
            'renewals: не удалось синхронизировать авто-стадию (student=%s)', student_id)


@transaction.atomic
def reopen_deal(deal_id: int, author_id: Optional[int] = None,
                note: str = 'Сделка переоткрыта') -> Optional[RenewalDeal]:
    """
    Переоткрыть закрытую сделку: outcome_at → NULL, стадия → вычисленная авто-стадия.

    Порождённая при закрытии сделка следующего цикла удаляется, если открыта и
    не тронута руками (только системная активность и авто-стадия); иначе остаётся
    с системной пометкой. Возвращает None, если сделка не найдена или не закрыта.
    """
    from apps.finances.repository import balance_for_student

    deal = (RenewalDeal.objects.select_for_update().select_related('stage', 'pipeline')
            .filter(id=deal_id, outcome_at__isnull=False).first())
    if deal is None:
        return None

    nxt = (RenewalDeal.objects.select_for_update().select_related('stage')
           .filter(student_id=deal.student_id,
                   cycle_no=deal.cycle_no + 1, outcome_at__isnull=True).first())
    if nxt is not None:
        touched = (not nxt.stage.is_auto
                   or nxt.activities.exclude(kind='system').exists())
        if touched:
            RenewalActivity.objects.create(
                deal=nxt, kind='system',
                body=f'Сделка цикла {deal.cycle_no} переоткрыта — проверьте актуальность')
        else:
            nxt.delete()  # activity уйдёт каскадом

    auto = _auto_stages(deal.pipeline)
    progress_stages = _progress_stages(deal.pipeline)
    attended = _attended_total(deal.student_id)
    balance = float(balance_for_student(deal.student_id))
    from_stage = deal.stage
    target, _matured = _target_auto_stage(deal, attended, balance, auto, progress_stages)
    deal.stage = target or from_stage
    deal.outcome_at = None
    deal.stage_entered_at = timezone.now()
    deal.save(update_fields=['stage', 'outcome_at', 'stage_entered_at', 'updated_at'])
    RenewalActivity.objects.create(
        deal=deal, kind='system', from_stage=from_stage, to_stage=deal.stage,
        author_id=author_id, body=note)
    return deal


def _open_deal_for_update(student_id: int) -> Optional[RenewalDeal]:
    """Открытая сделка ученика с блокировкой (самый поздний цикл). None если нет."""
    return (RenewalDeal.objects
            .select_for_update()
            .select_related('stage', 'pipeline')
            .filter(student_id=student_id, outcome_at__isnull=True)
            .order_by('-cycle_no').first())


@transaction.atomic
def freeze_deal(student_id: int, author_id: Optional[int] = None) -> Optional[RenewalDeal]:
    """Перевести открытую сделку ученика на авто-стадию 'frozen' напрямую (в обход
    move_deal/валидатора — как reopen_deal). No-op, если сделки нет или в воронке
    нет стадии 'frozen'. Идемпотентно (повторный вызов на 'frozen' ничего не пишет)."""
    deal = _open_deal_for_update(student_id)
    if deal is None:
        return None
    frozen = RenewalStage.objects.filter(pipeline=deal.pipeline, key=FROZEN_KEY).first()
    if frozen is None:
        return None
    if deal.stage_id == frozen.id:
        return deal  # уже заморожена — идемпотентно, ничего не пишем
    from_stage = deal.stage
    deal.stage = frozen
    deal.stage_entered_at = timezone.now()
    deal.save(update_fields=['stage', 'stage_entered_at', 'updated_at'])
    RenewalActivity.objects.create(
        deal=deal, kind='system', from_stage=from_stage, to_stage=frozen,
        author_id=author_id, body='Заморозка (смена статуса ученика)')
    return deal


@transaction.atomic
def decline_deal(student_id: int, author_id: Optional[int] = None) -> Optional[RenewalDeal]:
    """Закрыть открытую сделку ученика как терминальную 'lost' («Ушёл») напрямую,
    в обход валидатора. No-op, если открытой сделки нет или нет lost-стадии."""
    deal = _open_deal_for_update(student_id)
    if deal is None:
        return None
    lost = _stage(deal.pipeline, kind='lost')
    if lost is None:
        return None
    from_stage = deal.stage
    deal.stage = lost
    deal.stage_entered_at = timezone.now()
    deal.outcome_at = timezone.now()
    deal.save(update_fields=['stage', 'stage_entered_at', 'outcome_at', 'updated_at'])
    RenewalActivity.objects.create(
        deal=deal, kind='system', from_stage=from_stage, to_stage=lost,
        author_id=author_id, body='Отказ (смена статуса ученика)')
    return deal


@transaction.atomic
def resume_from_freeze(student_id: int, author_id: Optional[int] = None) -> Optional[RenewalDeal]:
    """Выход из заморозки: если открытая сделка ученика стоит на 'frozen', вернуть её
    на РАСЧЁТНУЮ авто-стадию (та же _target_auto_stage, что при создании/reopen) по
    attended/balance. No-op, если сделки нет или она не на 'frozen'."""
    from apps.finances.repository import balance_for_student

    deal = _open_deal_for_update(student_id)
    if deal is None or deal.stage.key != FROZEN_KEY:
        return None
    auto = _auto_stages(deal.pipeline)
    progress_stages = _progress_stages(deal.pipeline)
    attended = _attended_total(student_id)
    balance = float(balance_for_student(student_id))
    target, _matured = _target_auto_stage(deal, attended, balance, auto, progress_stages)
    if target is None:
        return deal
    from_stage = deal.stage
    deal.stage = target
    deal.stage_entered_at = timezone.now()
    deal.save(update_fields=['stage', 'stage_entered_at', 'updated_at'])
    RenewalActivity.objects.create(
        deal=deal, kind='system', from_stage=from_stage, to_stage=target,
        author_id=author_id, body='Автопереход после выхода из заморозки')
    return deal
