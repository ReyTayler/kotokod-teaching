"""Тесты сериализаторов комментариев к преподавателю (без БД)."""
from __future__ import annotations

from types import SimpleNamespace

from apps.teachers.serializers import TeacherCommentSerializer, TeacherCommentWriteSerializer


def test_rejects_blank_body():
    ser = TeacherCommentWriteSerializer(data={'body': '   '})
    assert not ser.is_valid()
    assert 'body' in ser.errors


def test_rejects_missing_body():
    ser = TeacherCommentWriteSerializer(data={})
    assert not ser.is_valid()
    assert 'body' in ser.errors


def test_strips_body():
    ser = TeacherCommentWriteSerializer(data={'body': '  Привет  '})
    assert ser.is_valid(), ser.errors
    assert ser.validated_data['body'] == 'Привет'


def test_rejects_too_long_body():
    ser = TeacherCommentWriteSerializer(data={'body': 'x' * 5001})
    assert not ser.is_valid()
    assert 'body' in ser.errors


def test_accepts_max_length_body():
    ser = TeacherCommentWriteSerializer(data={'body': 'x' * 5000})
    assert ser.is_valid(), ser.errors


def test_read_serializer_shape_with_author():
    obj = SimpleNamespace(
        id=7, body='Текст', created_at=None, author_id=3,
        author=SimpleNamespace(full_name='Анна Петрова'),
    )
    data = TeacherCommentSerializer(obj).data
    assert set(data) == {'id', 'body', 'created_at', 'author_id', 'author_name'}
    assert data['author_id'] == 3
    assert data['author_name'] == 'Анна Петрова'


def test_read_serializer_author_deleted():
    """Автор удалён (SET_NULL) — имя None, а не падение на None.full_name."""
    obj = SimpleNamespace(id=7, body='Текст', created_at=None, author_id=None, author=None)
    data = TeacherCommentSerializer(obj).data
    assert data['author_id'] is None
    assert data['author_name'] is None
