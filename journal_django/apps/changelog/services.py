"""ChangelogService — тонкий слой между views и repository (+ откат)."""
from __future__ import annotations

from typing import Optional

from rest_framework.request import Request

from apps.audit.services import log_event
from apps.changelog import repository
from apps.changelog import revert as revert_module


def list_operations(page: int = 1, page_size: int = 50, filters: dict | None = None) -> dict:
    return repository.list_operations(
        page=page, page_size=page_size, filters=filters or {},
    )


def get_operation(context_id) -> dict | None:
    return repository.get_operation(context_id)


def revert_operation(context_id, request: Optional[Request] = None) -> dict:
    """Откатить операцию + записать событие безопасности changelog_revert."""
    summary = revert_module.revert_context(context_id)
    user = getattr(request, 'user', None) if request is not None else None
    log_event(
        'changelog_revert',
        account_id=getattr(user, 'id', None),
        actor_email=getattr(user, 'email', None),
        meta={'context_id': str(context_id), **summary},
        request=request,
    )
    return summary
