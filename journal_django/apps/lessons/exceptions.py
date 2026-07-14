"""
Доменные исключения раздела lessons.

Не зависят от DRF/HTTP — бросаются в repository/services, маппятся в HTTP-ответ
во view (см. apps/groups/exceptions.py::ImmutableGroupFormat для того же паттерна).
"""
from __future__ import annotations


class UnpaidAttendanceBlocked(Exception):
    """
    Попытка отметить присутствие ученику, у которого не осталось оплаченных
    уроков (remaining <= 0, apps.finances.repository.balances_for_students).

    Действует одинаково для teacher SPA (submitLesson) и admin SPA (создание
    урока, переключение ячейки посещаемости) — единая проверка в
    apps.lessons.repository.assert_students_paid.
    """

    def __init__(self, blocked_names: list[str]) -> None:
        self.blocked_names = blocked_names
        names = ', '.join(blocked_names)
        super().__init__(
            f'У учеников без оплаченных уроков нельзя отметить посещение: {names}.'
        )
