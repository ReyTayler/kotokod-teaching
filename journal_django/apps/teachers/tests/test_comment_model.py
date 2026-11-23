"""Тесты модели TeacherComment (без БД — только объявление/метаданные)."""
from __future__ import annotations

from django.db import models

from apps.teachers.models import TeacherComment


def test_table_name():
    assert TeacherComment._meta.db_table == 'teacher_comment'


def test_fields():
    field_names = {f.name for f in TeacherComment._meta.get_fields()}
    assert {'id', 'teacher', 'body', 'author', 'created_at'} <= field_names


def test_author_on_delete_set_null():
    field = TeacherComment._meta.get_field('author')
    assert field.remote_field.on_delete is models.SET_NULL
    assert field.null is True


def test_teacher_on_delete_cascade():
    field = TeacherComment._meta.get_field('teacher')
    assert field.remote_field.on_delete is models.CASCADE
    assert field.remote_field.related_name == 'comments'


def test_index_teacher_created_at_desc():
    """Список читается «последние сверху» по одному преподавателю — индекс под этот предикат."""
    fields = [list(idx.fields) for idx in TeacherComment._meta.indexes]
    assert ['teacher', '-created_at'] in fields


def test_not_pghistory_tracked():
    """
    Осознанное исключение из правила CLAUDE.md, тот же прецедент, что у
    StudentComment (docs/superpowers/specs/2026-07-10-student-comments-design.md).
    """
    from apps.changelog.registry import TRACKED
    assert 'teachers.TeacherComment' not in TRACKED
