"""Доменные исключения раздела extra_lessons (см. apps/lessons/exceptions.py для паттерна)."""
from __future__ import annotations


class MissedLessonNotFound(Exception):
    """missed_lesson_id не ссылается на существующий проведённый урок."""


class DuplicateAssignment(Exception):
    """У студента уже есть активное (не отменённое) назначение за этот же пропуск."""

    def __init__(self, student_names: list[str]) -> None:
        self.student_names = student_names
        names = ', '.join(student_names)
        super().__init__(
            f'Уже есть активный доп.урок за этот пропуск у: {names}.'
        )


class NotTeachersAssignment(Exception):
    """Преподаватель пытается провести/посмотреть чужое назначение."""
