"""
LessonsService — тонкий слой между views и repository.

Никакого SQL здесь — всё через repository.
"""
from __future__ import annotations

from typing import Optional

from apps.lessons import repository


def list_lessons(
    page: int = 1,
    page_size: int = 50,
    sort_by: str = 'lesson_date',
    sort_dir: str = 'desc',
    filters: Optional[dict] = None,
) -> dict:
    return repository.list_lessons(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        filters=filters,
    )


def get_lesson_full(lesson_id: int) -> Optional[dict]:
    return repository.get_lesson_full(lesson_id)


def create_lesson_full(data: dict) -> int:
    return repository.create_lesson_full(data)


def update_lesson(lesson_id: int, fields: dict) -> Optional[dict]:
    return repository.update_lesson(lesson_id, fields)


def delete_lesson_full(lesson_id: int) -> bool:
    return repository.delete_lesson_full(lesson_id)


def update_attendance_cell(lesson_id: int, student_id: int, present: bool) -> bool:
    return repository.update_attendance_cell(lesson_id, student_id, present)
