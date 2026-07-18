"""record_lesson обычного урока авто-создаёт pending-резолюции по отсутствовавшим
(apps.extra_lessons.AbsenceResolution). extra/burned уроки — не порождают."""
from __future__ import annotations

import pytest
from django.db import connection

from apps.lessons import services
from apps.lessons.exceptions import LessonHasMakeupResolutions

pytestmark = pytest.mark.django_db


def _pending_students(missed_lesson_id):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT student_id FROM absence_resolutions "
            "WHERE missed_lesson_id=%s AND status='pending' ORDER BY student_id",
            [missed_lesson_id])
        return [r[0] for r in cur.fetchall()]


def _cleanup(lesson_id):
    with connection.cursor() as cur:
        cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id=%s', [lesson_id])
        cur.execute('DELETE FROM payroll WHERE lesson_id=%s', [lesson_id])
        cur.execute('DELETE FROM lesson_attendance WHERE lesson_id=%s', [lesson_id])
        cur.execute('DELETE FROM lessons WHERE id=%s', [lesson_id])


def test_regular_lesson_autocreates_pending_for_absent(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture,
):
    res = services.record_lesson(
        lesson_date='2026-05-01', teacher_id=teacher_id_fixture, group_id=group_fixture,
        original_teacher_id=None, lesson_number=1, lesson_duration_minutes=60,
        lesson_type='regular', record_url=None, submitted_by_token='t',
        submit_date='2026-05-01',
        attendance=[{'student_id': student_fixture, 'present': False}])
    lesson_id = res['lesson_id']
    try:
        assert _pending_students(lesson_id) == [student_fixture]
        # Идемпотентность: повторный autocreate по тому же уроку не дублирует.
        from apps.extra_lessons import services as el
        el.autocreate_pending_for_lesson(lesson_id, [student_fixture])
        assert _pending_students(lesson_id) == [student_fixture]
    finally:
        _cleanup(lesson_id)


def test_present_student_gets_no_pending(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture,
):
    res = services.record_lesson(
        lesson_date='2026-05-03', teacher_id=teacher_id_fixture, group_id=group_fixture,
        original_teacher_id=None, lesson_number=1, lesson_duration_minutes=60,
        lesson_type='regular', record_url=None, submitted_by_token='t',
        submit_date='2026-05-03',
        attendance=[{'student_id': student_fixture, 'present': True}])
    lesson_id = res['lesson_id']
    try:
        assert _pending_students(lesson_id) == []
    finally:
        _cleanup(lesson_id)


def test_delete_lesson_blocked_when_makeup_done(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture,
):
    """Обычный урок с проведённым доп.уроком по его пропуску (makeup_done) удалить
    нельзя (409/LessonHasMakeupResolutions) — иначе ON DELETE CASCADE осиротил бы
    факт доп.урока + payroll. pending — удалять каскадом можно."""
    res = services.record_lesson(
        lesson_date='2026-05-04', teacher_id=teacher_id_fixture, group_id=group_fixture,
        original_teacher_id=None, lesson_number=1, lesson_duration_minutes=60,
        lesson_type='regular', record_url=None, submitted_by_token='t',
        submit_date='2026-05-04',
        attendance=[{'student_id': student_fixture, 'present': False}])
    lesson_id = res['lesson_id']
    try:
        # Симулируем проведённый доп.урок: pending → makeup_done.
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE absence_resolutions SET status='makeup_done' "
                "WHERE missed_lesson_id=%s", [lesson_id])
        with pytest.raises(LessonHasMakeupResolutions):
            services.delete_lesson_full(lesson_id)

        # Вернём в pending — тогда удаление проходит (каскад снесёт резолюцию).
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE absence_resolutions SET status='pending' WHERE missed_lesson_id=%s",
                [lesson_id])
        assert services.delete_lesson_full(lesson_id) is True
        assert _pending_students(lesson_id) == []  # каскад снёс резолюцию
    finally:
        _cleanup(lesson_id)


def test_delete_lesson_blocked_when_burned(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture,
):
    """Обычный урок со сгоревшим пропуском (burned) удалить нельзя
    (409/LessonHasMakeupResolutions) — иначе ON DELETE CASCADE осиротил бы
    burned-факт + payroll. pending — удалять каскадом можно."""
    res = services.record_lesson(
        lesson_date='2026-05-05', teacher_id=teacher_id_fixture, group_id=group_fixture,
        original_teacher_id=None, lesson_number=1, lesson_duration_minutes=60,
        lesson_type='regular', record_url=None, submitted_by_token='t',
        submit_date='2026-05-05',
        attendance=[{'student_id': student_fixture, 'present': False}])
    lesson_id = res['lesson_id']
    try:
        # Симулируем сгорание: pending → burned.
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE absence_resolutions SET status='burned' "
                "WHERE missed_lesson_id=%s", [lesson_id])
        with pytest.raises(LessonHasMakeupResolutions):
            services.delete_lesson_full(lesson_id)

        # Вернём в pending — тогда удаление проходит (каскад снесёт резолюцию).
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE absence_resolutions SET status='pending' WHERE missed_lesson_id=%s",
                [lesson_id])
        assert services.delete_lesson_full(lesson_id) is True
        assert _pending_students(lesson_id) == []
    finally:
        _cleanup(lesson_id)


def test_extra_lesson_does_not_autocreate(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture,
):
    res = services.record_lesson(
        lesson_date='2026-05-02', teacher_id=teacher_id_fixture, group_id=group_fixture,
        original_teacher_id=None, lesson_number=1, lesson_duration_minutes=60,
        lesson_type='extra', record_url=None, submitted_by_token='t',
        submit_date='2026-05-02',
        attendance=[{'student_id': student_fixture, 'present': False}])
    lesson_id = res['lesson_id']
    try:
        assert _pending_students(lesson_id) == []  # extra не порождает pending
    finally:
        _cleanup(lesson_id)
