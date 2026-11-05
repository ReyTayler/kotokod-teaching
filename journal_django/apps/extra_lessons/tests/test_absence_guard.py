"""Второй рубеж против двойного учёта: burn()/record() makeup-заявки работают
только если на пропущенном уроке ученик ДЕЙСТВИТЕЛЬНО отсутствовал. Состояние
«заявка жива, а ученик отмечен был» воспроизводим прямым UPDATE ячейки — так
оно выглядело на проде до фикса отметки (ВДГ18, Ларина, №32, 2026-09-19)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection

from apps.extra_lessons import services
from apps.extra_lessons.exceptions import StudentNotAbsent
from apps.extra_lessons.models import (
    BURNED, MAKEUP_DONE, MAKEUP_SCHEDULED, PENDING, AbsenceResolution,
)
from apps.lessons.models import Lesson, LessonAttendance
from apps.lessons.services import create_lesson_full

pytestmark = pytest.mark.django_db


class _FakeRequest:
    META: dict = {}
    user = None


def _mark_present(lesson_id, student_id):
    with connection.cursor() as cur:
        cur.execute('UPDATE lesson_attendance SET present=true '
                    'WHERE lesson_id=%s AND student_id=%s', [lesson_id, student_id])


@pytest.fixture
def pending_resolution(missed_lesson_fixture, student_fixture):
    """pending-резолюция, авто-созданная missed_lesson_fixture. Teardown сносит
    возможный факт ДО teardown missed_lesson_fixture (DB-level FK) — общая
    journal_test не должна копить мусор, если тест упал на полпути."""
    res = AbsenceResolution.objects.get(
        missed_lesson_id=missed_lesson_fixture, student_id=student_fixture, status=PENDING)
    yield res
    tokens = [f'burn:{res.id}', f'makeup:{res.id}']
    with connection.cursor() as cur:
        cur.execute('UPDATE absence_resolutions SET fact_lesson_id=NULL WHERE id=%s', [res.id])
        cur.execute('SELECT id FROM lessons WHERE submitted_by_token = ANY(%s)', [tokens])
        fact_ids = [r[0] for r in cur.fetchall()]
        for fid in fact_ids:
            cur.execute('DELETE FROM payroll WHERE lesson_id=%s', [fid])
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id=%s', [fid])
            cur.execute('DELETE FROM lessons WHERE id=%s', [fid])


def test_burn_refused_when_student_was_present(pending_resolution):
    _mark_present(pending_resolution.missed_lesson_id, pending_resolution.student_id)
    with pytest.raises(StudentNotAbsent):
        services.burn(pending_resolution.id, request=_FakeRequest(), burn_date='2026-07-18')
    pending_resolution.refresh_from_db()
    assert pending_resolution.status == PENDING
    assert pending_resolution.fact_lesson_id is None
    assert not Lesson.objects.filter(
        submitted_by_token=f'burn:{pending_resolution.id}').exists()


def test_record_refused_when_student_was_present(pending_resolution, teacher_fixture):
    with connection.cursor() as cur:
        cur.execute(
            'UPDATE absence_resolutions SET status=%s, assigned_teacher_id=%s, '
            "scheduled_date='2026-04-05', duration_minutes=60 WHERE id=%s",
            [MAKEUP_SCHEDULED, teacher_fixture, pending_resolution.id])
    _mark_present(pending_resolution.missed_lesson_id, pending_resolution.student_id)
    with pytest.raises(StudentNotAbsent):
        services.record(
            pending_resolution.id, teacher_id=teacher_fixture, present=True,
            record_url=None, submitted_by_token='t', submit_date='2026-04-05',
            request=_FakeRequest())
    pending_resolution.refresh_from_db()
    assert pending_resolution.status == MAKEUP_SCHEDULED
    assert not Lesson.objects.filter(
        submitted_by_token=f'makeup:{pending_resolution.id}').exists()


def test_burn_still_works_for_real_absence(pending_resolution):
    """Контроль: реальный пропуск по-прежнему сжигается."""
    services.burn(pending_resolution.id, request=_FakeRequest(), burn_date='2026-07-18')
    pending_resolution.refresh_from_db()
    assert pending_resolution.status == BURNED
    services.delete_fact(pending_resolution.id, _FakeRequest())


@pytest.fixture
def lesson_before_joining(group_fixture, teacher_fixture):
    """Урок №16 группы, проведённый ДО вступления student_fixture: на него нет
    строки посещаемости — ни «был», ни «не был»."""
    with connection.cursor() as cur:
        cur.execute("INSERT INTO students (full_name) VALUES ('__el_classmate__') RETURNING id")
        classmate_id = cur.fetchone()[0]
        cur.execute(
            'INSERT INTO group_memberships (group_id, student_id, lessons_done, active) '
            'VALUES (%s, %s, 0, true)', [group_fixture, classmate_id])
    lesson_id = create_lesson_full({
        'lesson_date': '2026-04-16', 'group_id': group_fixture, 'teacher_id': teacher_fixture,
        'lesson_number': 16, 'lesson_duration_minutes': 60,
        'attendance': [{'student_id': classmate_id, 'present': False}],
    })['lesson_id']
    yield lesson_id
    with connection.cursor() as cur:
        cur.execute(
            'SELECT fact_lesson_id FROM absence_resolutions WHERE missed_lesson_id = %s '
            'AND fact_lesson_id IS NOT NULL', [lesson_id])
        fact_ids = [r[0] for r in cur.fetchall()]
        cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id = %s', [lesson_id])
        for lid in [*fact_ids, lesson_id]:
            cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [lid])
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lid])
            cur.execute('DELETE FROM lessons WHERE id = %s', [lid])
        cur.execute('DELETE FROM group_memberships WHERE student_id = %s', [classmate_id])
        cur.execute('DELETE FROM students WHERE id = %s', [classmate_id])


@pytest.fixture
def late_joiner_makeup(group_fixture, teacher_fixture, student_fixture, membership_fixture,
                       lesson_before_joining):
    """Ручное назначение доп.урока за урок, прошедший до вступления ученика в группу."""
    result = services.create_extra_assignment({
        'group_id': group_fixture, 'teacher_id': teacher_fixture,
        'student_ids': [student_fixture], 'scheduled_date': '2026-05-01',
        'scheduled_time': '16:00', 'duration_minutes': 60, 'lesson_number': Decimal('16'),
    }, _FakeRequest())
    assert result['kind'] == 'makeup'
    return AbsenceResolution.objects.get(id=result['resolution_ids'][0])


def test_record_allowed_for_lesson_before_joining(
    late_joiner_makeup, lesson_before_joining, group_fixture, teacher_fixture,
    student_fixture, lessons_done,
):
    """Ученика добавили в группу после урока №16 и назначили доп.урок за него.
    Двойного учёта нет: на исходном уроке ученик ничего не потребил, поэтому
    проведение не блокируется. Исходный урок при этом не получает строку посещения."""
    result = services.record(
        late_joiner_makeup.id, teacher_id=teacher_fixture, present=True,
        record_url=None, submitted_by_token='t', submit_date='2026-05-01',
        request=_FakeRequest())

    late_joiner_makeup.refresh_from_db()
    assert late_joiner_makeup.status == MAKEUP_DONE
    assert late_joiner_makeup.fact_lesson_id == result['lesson_id']
    assert lessons_done(group_fixture, student_fixture) == Decimal('1')
    assert not LessonAttendance.objects.filter(
        lesson_id=lesson_before_joining, student_id=student_fixture).exists()

    # Откат факта возвращает всё обратно — путь тот же, что у обычной отработки.
    services.delete_fact(late_joiner_makeup.id, _FakeRequest())
    late_joiner_makeup.refresh_from_db()
    assert late_joiner_makeup.status == PENDING
    assert lessons_done(group_fixture, student_fixture) == Decimal('0')


def test_burn_refused_for_lesson_before_joining(late_joiner_makeup):
    """Сжечь можно только реальный пропуск: ученика на том уроке не было в составе,
    и списать с него занятие без отработки нельзя."""
    services.cancel_assignment(late_joiner_makeup.id, _FakeRequest())
    with pytest.raises(StudentNotAbsent):
        services.burn(late_joiner_makeup.id, request=_FakeRequest(), burn_date='2026-05-02')
    late_joiner_makeup.refresh_from_db()
    assert late_joiner_makeup.status == PENDING
