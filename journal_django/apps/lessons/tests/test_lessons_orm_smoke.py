"""
Smoke-тесты ORM-переноса LessonsRepository (раздел 09).

Сеют минимальные данные и проверяют критичные инварианты write-путей, которые
в пустой тестовой БД иначе пропускаются (no data):
  • half-lesson: duration 45 → шаг 0.5; иначе 1;
  • lessons_done корректируется в той же транзакции (create/delete/toggle);
  • get_lesson_full / list_lessons собирают joined-поля и attendance.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db.models.functions import Now

from apps.directions.models import Direction
from apps.groups.models import Group
from apps.lessons import repository
from apps.memberships.models import GroupMembership
from apps.students.models import Student
from apps.teachers.models import Teacher


def _seed(duration: int = 90):
    d = Direction.objects.create(name=f'ORM-DIR-{duration}', sheet_name='s', is_individual=False)
    t = Teacher.objects.create(name=f'ORM-T-{duration}', created_at=Now())
    g = Group.objects.create(
        name=f'ORM-G-{duration}', direction_id=d.id, teacher_id=t.id,
        is_individual=False, lesson_duration_minutes=duration, lessons_per_week=1,
        created_at=Now(),
    )
    s1 = Student.objects.create(full_name=f'ORM-S1-{duration}', created_at=Now())
    s2 = Student.objects.create(full_name=f'ORM-S2-{duration}', created_at=Now())
    GroupMembership.objects.create(group_id=g.id, student_id=s1.id, lessons_done=0)
    GroupMembership.objects.create(group_id=g.id, student_id=s2.id, lessons_done=0)
    return d, t, g, s1, s2


def _lessons_done(group_id, student_id) -> Decimal:
    return GroupMembership.objects.get(group_id=group_id, student_id=student_id).lessons_done


@pytest.mark.django_db
def test_create_lesson_full_increments_present_full_lesson():
    d, t, g, s1, s2 = _seed(duration=90)
    lid = repository.create_lesson_full({
        'lesson_date': '2026-01-10', 'teacher_id': t.id, 'group_id': g.id,
        'lesson_number': 1, 'lesson_duration_minutes': 90, 'lesson_type': 'regular',
        'attendance': [
            {'student_id': s1.id, 'present': True},
            {'student_id': s2.id, 'present': False},
        ],
        'payroll': {'total_students': 2, 'present_count': 1, 'payment': 500, 'penalty': 0},
    })
    assert isinstance(lid, int)
    # present → +1, absent → без изменений
    assert _lessons_done(g.id, s1.id) == Decimal('1.0')
    assert _lessons_done(g.id, s2.id) == Decimal('0.0')

    full = repository.get_lesson_full(lid)
    assert full['group_name'] == g.name
    assert full['teacher_name'] == t.name
    assert len(full['attendance']) == 2
    assert full['payroll']['present_count'] == 1


@pytest.mark.django_db
def test_create_lesson_full_half_lesson_step():
    d, t, g, s1, s2 = _seed(duration=45)
    repository.create_lesson_full({
        'lesson_date': '2026-01-11', 'teacher_id': t.id, 'group_id': g.id,
        'lesson_number': 1, 'lesson_duration_minutes': 45, 'lesson_type': 'regular',
        'attendance': [{'student_id': s1.id, 'present': True}],
    })
    # half-lesson: present → +0.5
    assert _lessons_done(g.id, s1.id) == Decimal('0.5')


@pytest.mark.django_db
def test_delete_lesson_full_rolls_back_lessons_done():
    d, t, g, s1, s2 = _seed(duration=90)
    lid = repository.create_lesson_full({
        'lesson_date': '2026-01-12', 'teacher_id': t.id, 'group_id': g.id,
        'lesson_number': 1, 'lesson_duration_minutes': 90,
        'attendance': [{'student_id': s1.id, 'present': True}],
    })
    assert _lessons_done(g.id, s1.id) == Decimal('1.0')
    assert repository.delete_lesson_full(lid) is True
    assert _lessons_done(g.id, s1.id) == Decimal('0.0')
    assert repository.get_lesson_full(lid) is None


@pytest.mark.django_db
def test_update_attendance_cell_toggles_delta():
    d, t, g, s1, s2 = _seed(duration=90)
    lid = repository.create_lesson_full({
        'lesson_date': '2026-01-13', 'teacher_id': t.id, 'group_id': g.id,
        'lesson_number': 1, 'lesson_duration_minutes': 90,
        'attendance': [{'student_id': s1.id, 'present': False}],
    })
    assert _lessons_done(g.id, s1.id) == Decimal('0.0')
    # false → true: +1
    assert repository.update_attendance_cell(lid, s1.id, True) is True
    assert _lessons_done(g.id, s1.id) == Decimal('1.0')
    # true → false: -1
    assert repository.update_attendance_cell(lid, s1.id, False) is True
    assert _lessons_done(g.id, s1.id) == Decimal('0.0')
    # GREATEST(...,0): повторный false не уводит в минус
    assert repository.update_attendance_cell(lid, s1.id, False) is True
    assert _lessons_done(g.id, s1.id) == Decimal('0.0')


@pytest.mark.django_db
def test_update_attendance_cell_missing_lesson_returns_false():
    assert repository.update_attendance_cell(999999, 1, True) is False
