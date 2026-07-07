"""
Доменные исключения раздела memberships.

Не зависят от DRF/HTTP — бросаются в repository (слой доступа к данным),
маппятся в HTTP-ответ во view. Такое разделение позволяет держать бизнес-
правила в одном месте и не тащить web-слой в репозиторий.
"""
from __future__ import annotations

from typing import Optional


class IndividualGroupFull(Exception):
    """
    Индивидуальная группа уже занята другим активным учеником.

    В индивидуальной группе (`groups.is_individual = true`) допускается не более
    одного активного membership. Попытка добавить/реактивировать ДРУГОГО ученика
    при уже активном → это исключение (view отдаёт 409 Conflict).

    active_student_id — id уже активного ученика (для диагностики/UI), опционален.
    """

    default_message = 'В индивидуальной группе может быть только один активный ученик.'

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        active_student_id: Optional[int] = None,
    ) -> None:
        super().__init__(message or self.default_message)
        self.active_student_id = active_student_id
