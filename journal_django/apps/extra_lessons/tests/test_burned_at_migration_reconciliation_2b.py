"""Сверка миграции историч. burned_at (Фаза 2b): конвертация «сгоревшей задним
числом» правки (LessonAttendance.burned_at + Payroll.burn_surcharge_*) в штатный
burned-Lesson + AbsenceResolution НЕ двигает числа — balance/attended/зарплата
преподавателя за месяц те же; исходный урок возвращается в present=false, надбавка
переезжает в payment нового burned-урока (без двойного счёта)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection

from apps.extra_lessons._migration_helpers import convert_historical_burned_at
from apps.finances import repository as fin
from apps.lessons.models import Lesson, LessonAttendance
from apps.payroll.models import Payroll
from apps.renewals import engine as ren

pytestmark = pytest.mark.django_db


def _teacher_month_pay(teacher_id):
    """Вся зарплата преподавателя = SUM(payment) + SUM(burn_surcharge_amount)."""
    with connection.cursor() as cur:
        cur.execute(
            'SELECT COALESCE(SUM(payment),0)+COALESCE(SUM(burn_surcharge_amount),0) '
            'FROM payroll WHERE teacher_id=%s', [teacher_id])
        return cur.fetchone()[0]


def test_convert_historical_burned_at_reconciles(
    group_fixture, teacher_fixture, student_fixture, missed_lesson_fixture,
):
    """missed_lesson_fixture: regular-урок (60мин), student отсутствовал. Симулируем
    старый burn-WIP: attendance present=true + burned_at, payroll base+surcharge 200,
    авто-pending убираем (историч. burned_at резолюций не имел). После хелпера числа
    те же, исходный present=false, есть burned-Lesson+resolution."""
    lesson_id = missed_lesson_fixture
    burn_date = '2026-07-17'
    with connection.cursor() as cur:
        # Старый burn-WIP: исходную строку флипаем present=true + burned_at,
        # payroll — base payment + surcharge 200 (как update_attendance_cell).
        cur.execute(
            'UPDATE lesson_attendance SET present=true, burned_at=%s '
            'WHERE lesson_id=%s AND student_id=%s', [burn_date, lesson_id, student_fixture])
        cur.execute(
            'UPDATE payroll SET present_count=1, payment=500, '
            'burn_surcharge_amount=200, burn_surcharge_at=%s WHERE lesson_id=%s',
            [burn_date, lesson_id])
        # Историч. burned_at не имел резолюции — снять авто-pending, созданный фикстурой.
        cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id=%s', [lesson_id])

    # Снимок «до».
    bal0 = fin.balance_for_student(student_fixture)
    att0 = fin.attended_units_total(student_fixture)
    ren0 = ren._attended_total(student_fixture)
    pay0 = _teacher_month_pay(teacher_fixture)

    try:
        convert_historical_burned_at(connection)

        # Числа не сдвинулись.
        assert fin.balance_for_student(student_fixture) == bal0
        assert fin.attended_units_total(student_fixture) == att0
        assert ren._attended_total(student_fixture) == ren0
        assert _teacher_month_pay(teacher_fixture) == pay0

        # Исходный урок — снова present=false, burned_at снят, надбавка обнулена.
        orig = LessonAttendance.objects.get(lesson_id=lesson_id, student_id=student_fixture)
        assert orig.present is False and orig.burned_at is None
        orig_pay = Payroll.objects.get(lesson_id=lesson_id)
        assert orig_pay.burn_surcharge_amount == Decimal('0')
        assert orig_pay.burn_surcharge_at is None
        assert orig_pay.payment == Decimal('500')  # base не тронут

        # Появился burned-Lesson в дату burned_at с present=true и payroll=surcharge.
        from apps.extra_lessons.models import AbsenceResolution
        res = AbsenceResolution.objects.get(
            missed_lesson_id=lesson_id, student_id=student_fixture)
        assert res.status == 'burned'
        burned = Lesson.objects.get(id=res.fact_lesson_id)
        assert burned.lesson_type == 'burned'
        assert burned.lesson_date.isoformat() == burn_date
        assert burned.lesson_duration_minutes == 60  # исходная длительность
        assert LessonAttendance.objects.get(
            lesson_id=burned.id, student_id=student_fixture).present is True
        assert Payroll.objects.get(lesson_id=burned.id).payment == Decimal('200')

        # Идемпотентность: повторный вызов ничего не меняет.
        n_burned_before = Lesson.objects.filter(lesson_type='burned').count()
        convert_historical_burned_at(connection)
        assert Lesson.objects.filter(lesson_type='burned').count() == n_burned_before
        assert fin.balance_for_student(student_fixture) == bal0
        assert _teacher_month_pay(teacher_fixture) == pay0
    finally:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT fact_lesson_id FROM absence_resolutions "
                "WHERE missed_lesson_id=%s AND fact_lesson_id IS NOT NULL", [lesson_id])
            fact_ids = [r[0] for r in cur.fetchall()]
            cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id=%s', [lesson_id])
            for fid in fact_ids:
                cur.execute('DELETE FROM payroll WHERE lesson_id=%s', [fid])
                cur.execute('DELETE FROM lesson_attendance WHERE lesson_id=%s', [fid])
                cur.execute('DELETE FROM lessons WHERE id=%s', [fid])


def test_convert_splits_surcharge_across_multiple_burned(
    group_fixture, teacher_fixture, student_fixture, missed_lesson_fixture,
):
    """Несколько сожжённых на одном уроке: надбавка делится поровну, нечётный
    остаток (копейки) — первому по student_id. Сумма долей == исходной надбавке."""
    lesson_id = missed_lesson_fixture
    with connection.cursor() as cur:
        # Второй ученик, отсутствовавший на том же уроке.
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status) "
            "VALUES ('__el_burn2_student__','enrolled') RETURNING id")
        student2 = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO group_memberships (group_id, student_id, lessons_done, active) "
            "VALUES (%s,%s,0,true)", [group_fixture, student2])
        cur.execute(
            "INSERT INTO lesson_attendance (lesson_id, student_id, present) "
            "VALUES (%s,%s,false)", [lesson_id, student2])
        # Оба сожжены задним числом; надбавка 2.01 (201 копейка) на двоих →
        # 1.01 первому по student_id (остаток копейки), 1.00 второму.
        cur.execute(
            "UPDATE lesson_attendance SET present=true, burned_at='2026-07-17' "
            "WHERE lesson_id=%s AND student_id IN (%s,%s)",
            [lesson_id, student_fixture, student2])
        cur.execute(
            "UPDATE payroll SET burn_surcharge_amount=2.01, burn_surcharge_at='2026-07-17' "
            "WHERE lesson_id=%s", [lesson_id])
        cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id=%s', [lesson_id])

    try:
        convert_historical_burned_at(connection)
        from apps.extra_lessons.models import AbsenceResolution
        shares = {}
        for sid in (student_fixture, student2):
            res = AbsenceResolution.objects.get(missed_lesson_id=lesson_id, student_id=sid)
            shares[sid] = Payroll.objects.get(lesson_id=res.fact_lesson_id).payment
        first, second = sorted((student_fixture, student2))
        assert shares[first] == Decimal('1.01')   # остаток первому по student_id
        assert shares[second] == Decimal('1.00')
        assert shares[first] + shares[second] == Decimal('2.01')  # == исходная надбавка
    finally:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT fact_lesson_id FROM absence_resolutions "
                "WHERE missed_lesson_id=%s AND fact_lesson_id IS NOT NULL", [lesson_id])
            fact_ids = [r[0] for r in cur.fetchall()]
            cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id=%s', [lesson_id])
            for fid in fact_ids:
                cur.execute('DELETE FROM payroll WHERE lesson_id=%s', [fid])
                cur.execute('DELETE FROM lesson_attendance WHERE lesson_id=%s', [fid])
                cur.execute('DELETE FROM lessons WHERE id=%s', [fid])
            cur.execute('DELETE FROM lesson_attendance WHERE student_id=%s', [student2])
            cur.execute('DELETE FROM group_memberships WHERE student_id=%s', [student2])
            cur.execute('DELETE FROM students WHERE id=%s', [student2])
