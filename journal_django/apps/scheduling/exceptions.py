"""
Доменные исключения планировщика.

Не зависят от DRF/HTTP — бросаются в repository, маппятся в HTTP-ответ во view.
"""
from __future__ import annotations


class PlanHasRecordedLessons(Exception):
    """
    Попытка задать группе длину курса короче, чем в ней уже проведено занятий.

    Урезать план можно только по непроведённым (pending/overdue) строкам:
    удаление проведённого (done) или перенесённого (moved) занятия — потеря
    фактических данных. View отдаёт 409 Conflict.
    """

    def __init__(self, recorded_lessons: int) -> None:
        self.recorded_lessons = recorded_lessons
        super().__init__(
            f'В группе уже проведено занятий: {recorded_lessons}. '
            f'Задать меньшее число уроков нельзя.'
        )
