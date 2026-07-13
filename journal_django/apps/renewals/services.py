"""Services renewals — тонкий слой между views и repository/engine."""
from __future__ import annotations

from apps.renewals import repository


def board(filters: dict | None = None) -> dict:
    return repository.board(filters)


def column_cards(stage_id: int, offset: int, filters: dict | None = None) -> dict:
    return repository.column_cards(stage_id, offset, filters)


def list_deals(**kwargs) -> dict:
    return repository.list_deals(**kwargs)


def get_deal(deal_id: int) -> dict | None:
    return repository.deal_computed(deal_id)


def move_deal(deal_id, to_stage_id, reason_code, author_id):
    return repository.move_deal(deal_id, to_stage_id, reason_code, author_id)


def list_unassigned() -> list[dict]:
    """Сводка «Ученики без сделок» — активный membership без открытой сделки."""
    return repository.students_without_deal()


def create_deal(student_id: int, author_id: int | None) -> dict | str | None:
    """
    Ручное создание сделки учеником сводки: None — ученика нет; 'exists' —
    открытая сделка уже есть; dict — созданная сделка.

    Номер цикла — расчётный от общей истории; занятые (в т.ч. закрытые «Ушёл»
    у вернувшегося ученика) номера перешагиваем вперёд.
    """
    from apps.renewals import cycle, engine
    from apps.renewals.models import RenewalDeal
    from apps.students.models import Student

    if not Student.objects.filter(id=student_id).exists():
        return None
    if RenewalDeal.objects.filter(student_id=student_id, outcome_at__isnull=True).exists():
        return 'exists'

    min_cycle_no = cycle.cycle_no_from_attended(engine._attended_total(student_id))
    cycle_no = engine.next_open_cycle_no(student_id, min_cycle_no)

    deal = engine.ensure_deal(student_id, cycle_no)
    engine.sync_lesson_stage_safe(student_id)  # сразу в актуальную авто-стадию
    return repository.deal_computed(deal.id)


def reopen_deal(deal_id: int, author_id: int | None) -> dict | str | None:
    """None — сделки нет; 'not_closed' — она и так открыта; dict — переоткрыта."""
    from apps.renewals import engine
    from apps.renewals.models import RenewalDeal
    if not RenewalDeal.objects.filter(id=deal_id).exists():
        return None
    deal = engine.reopen_deal(deal_id, author_id=author_id)
    if deal is None:
        return 'not_closed'
    return repository.deal_computed(deal_id)


def list_assignees() -> list[dict]:
    """Кандидаты в ответственные по сделкам: активные manager/admin/superadmin."""
    from apps.accounts.models import Account
    return list(Account.objects
                .filter(role__in=['manager', 'admin', 'superadmin'], is_active=True)
                .order_by('full_name').values('id', 'full_name'))


def patch_deal(deal_id, data):
    return repository.patch_deal(deal_id, data)


def add_comment(deal_id, body, author_id):
    return repository.add_comment(deal_id, body, author_id)


def list_activity(deal_id):
    return repository.list_activity(deal_id)


def list_stages() -> list[dict]:
    return repository.list_stages()


def create_stage(data: dict) -> dict:
    return repository.create_stage(data)


def update_stage(stage_id: int, data: dict) -> dict | None:
    return repository.update_stage(stage_id, data)


def delete_stage(stage_id: int) -> str:
    return repository.delete_stage(stage_id)


def reorder_stages(order: list) -> list[dict]:
    return repository.reorder_stages(order)


def analytics_funnel(group_by: str | None = None) -> dict:
    from apps.renewals import analytics
    return analytics.funnel(group_by)
