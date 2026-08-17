"""record_lesson обычного урока авто-создаёт pending-резолюции по отсутствовавшим
(apps.extra_lessons.AbsenceResolution). extra/burned уроки — не порождают."""
from __future__ import annotations

import pytest
from django.db import connection

from apps.lessons import services
from apps.lessons.exceptions import AttendanceCompensatedElsewhere, LessonHasMakeupResolutions

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


@pytest.mark.parametrize('status', ['makeup_done', 'burned'])
def test_attendance_toggle_to_present_blocked_when_compensated(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, status,
):
    """Critical-гард: нельзя вручную флипнуть исходную ячейку пропуска в present=true,
    если пропуск уже компенсирован (makeup_done) или сожжён (burned) — иначе урок
    спишется дважды. Снятие present (в absent) — разрешено."""
    res = services.record_lesson(
        lesson_date='2026-05-06', teacher_id=teacher_id_fixture, group_id=group_fixture,
        original_teacher_id=None, lesson_number=1, lesson_duration_minutes=60,
        lesson_type='regular', record_url=None, submitted_by_token='t',
        submit_date='2026-05-06',
        attendance=[{'student_id': student_fixture, 'present': False}])
    lesson_id = res['lesson_id']
    try:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE absence_resolutions SET status=%s WHERE missed_lesson_id=%s",
                [status, lesson_id])
        # Флип в present — заблокирован.
        with pytest.raises(AttendanceCompensatedElsewhere):
            services.update_attendance_cell(lesson_id, student_fixture, True)
        # Ячейка не изменилась.
        with connection.cursor() as cur:
            cur.execute(
                'SELECT present FROM lesson_attendance WHERE lesson_id=%s AND student_id=%s',
                [lesson_id, student_fixture])
            assert cur.fetchone()[0] is False
        # Снятие present (в absent) — не гейтится (не создаёт двойного учёта).
        assert services.update_attendance_cell(lesson_id, student_fixture, False) is True
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


@pytest.mark.parametrize('lesson_type', ['substitution', 'reschedule'])
def test_course_lesson_types_autocreate_pending(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lesson_type,
):
    """Замена и перенос — такие же занятия курса, как regular: пропуск на них
    обязан вставать в очередь «ждёт решения».

    Регрессия: гейт был `lesson_type == 'regular'`, из-за чего на всех замещённых
    и перенесённых занятиях заявки не создавались вовсе. Тип выводит сервер
    (apps.teacher_spa.services), преподаватель его не выбирает, поэтому потеря
    была не видна ни в кабинете, ни в логах."""
    res = services.record_lesson(
        lesson_date='2026-05-07', teacher_id=teacher_id_fixture, group_id=group_fixture,
        original_teacher_id=None, lesson_number=1, lesson_duration_minutes=60,
        lesson_type=lesson_type, record_url=None, submitted_by_token='t',
        submit_date='2026-05-07',
        attendance=[{'student_id': student_fixture, 'present': False}])
    lesson_id = res['lesson_id']
    try:
        assert _pending_students(lesson_id) == [student_fixture]
    finally:
        _cleanup(lesson_id)


@pytest.mark.parametrize('lesson_type', ['regular', 'substitution', 'reschedule'])
def test_unpaid_skip_never_autocreates_on_any_course_type(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture, lesson_type,
):
    """«Неоплачиваемый пропуск» — терминальный прощённый исход (перевод / начал не
    с 1-го урока): отработка не требуется, заявка НЕ создаётся. Расширение гейта на
    substitution/reschedule не должно этого менять — проверяем на всех трёх типах.

    Пометка ставится слот-маркером (LessonSkip, «Вариант A») — это единственный
    путь, которым unpaid_skip попадает в record_lesson: AttendanceItemSerializer
    такого поля не имеет, клиент его прислать не может. record_lesson форсит
    помеченного ученика в present=false/unpaid_skip=true, что бы ни пришло с фронта."""
    services.set_lesson_skip(group_fixture, student_fixture, 1, True)
    res = services.record_lesson(
        lesson_date='2026-05-08', teacher_id=teacher_id_fixture, group_id=group_fixture,
        original_teacher_id=None, lesson_number=1, lesson_duration_minutes=60,
        lesson_type=lesson_type, record_url=None, submitted_by_token='t',
        submit_date='2026-05-08',
        # Приходит «пришёл» — маркер обязан переписать исход в неоплачиваемый пропуск.
        attendance=[{'student_id': student_fixture, 'present': True}])
    lesson_id = res['lesson_id']
    try:
        with connection.cursor() as cur:
            cur.execute(
                'SELECT present, unpaid_skip FROM lesson_attendance '
                'WHERE lesson_id=%s AND student_id=%s', [lesson_id, student_fixture])
            assert cur.fetchone() == (False, True)
        assert _pending_students(lesson_id) == []
    finally:
        services.set_lesson_skip(group_fixture, student_fixture, 1, False)
        _cleanup(lesson_id)


def test_flip_to_absent_autocreates_pending(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture,
):
    """Ретроактивное снятие present (админ правит ячейку задним числом) ставит
    пропуск в очередь. Прежде pending создавался ТОЛЬКО в момент записи урока,
    поэтому пропуск, проставленный позже, не попадал в «Доп.уроки» никогда."""
    res = services.record_lesson(
        lesson_date='2026-05-09', teacher_id=teacher_id_fixture, group_id=group_fixture,
        original_teacher_id=None, lesson_number=1, lesson_duration_minutes=60,
        lesson_type='regular', record_url=None, submitted_by_token='t',
        submit_date='2026-05-09',
        attendance=[{'student_id': student_fixture, 'present': True}])
    lesson_id = res['lesson_id']
    try:
        assert _pending_students(lesson_id) == []          # пришёл — заявки нет
        services.update_attendance_cell(lesson_id, student_fixture, False)
        assert _pending_students(lesson_id) == [student_fixture]
        # Идемпотентность: повторное снятие не плодит дублей.
        services.update_attendance_cell(lesson_id, student_fixture, False)
        assert _pending_students(lesson_id) == [student_fixture]
    finally:
        _cleanup(lesson_id)


def test_flip_to_absent_does_not_autocreate_for_unpaid_skip_cell(
    group_fixture, teacher_id_fixture, student_fixture, membership_fixture,
):
    """Ячейка, помеченная «неоплачиваемым пропуском», заявку не порождает и при
    ретро-правке: исход терминальный, отработка не требуется."""
    res = services.record_lesson(
        lesson_date='2026-05-10', teacher_id=teacher_id_fixture, group_id=group_fixture,
        original_teacher_id=None, lesson_number=1, lesson_duration_minutes=60,
        lesson_type='regular', record_url=None, submitted_by_token='t',
        submit_date='2026-05-10',
        attendance=[{'student_id': student_fixture, 'present': True}])
    lesson_id = res['lesson_id']
    try:
        services.set_unpaid_skip(lesson_id, student_fixture, True)
        assert _pending_students(lesson_id) == []
        # Явное снятие present поверх пометки — заявки по-прежнему быть не должно.
        services.update_attendance_cell(lesson_id, student_fixture, False)
        assert _pending_students(lesson_id) == []
    finally:
        _cleanup(lesson_id)
