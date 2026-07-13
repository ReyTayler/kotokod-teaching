"""
TeacherSpaRepository — единственное место доступа к данным раздела teacher_spa.

ORM-порт services/teacher-repo.js (раздел 09):
  - read_all_students  — главный срез данных (data[teacher][group])
  - read_filled_lessons — заполненные уроки за неделю (для report)
  - resolve_ids / resolve_students — разрешение id перед записью урока
  - insert_lesson / insert_attendance / insert_payroll / increment_counters —
    запись урока (вызываются внутри transaction.atomic в services.py)

Half-lesson инвариант (step 0.5/1) приходит из services.py.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Optional

from django.db.models import F, Min
from django.db.models.functions import Now

from apps.finances.repository import balances_for_students
from apps.groups.models import Group
from apps.lessons.models import Lesson, LessonAttendance
from apps.memberships.models import GroupMembership
from apps.payroll.models import Payroll
from apps.scheduling.models import PlannedLesson
from apps.students.models import Student
from apps.teachers.models import Teacher


# ---------------------------------------------------------------------------
# Форматтеры (порт fmtDateRu / fmtFixedAt — чистый Python, без SQL)
# ---------------------------------------------------------------------------

def fmt_date_ru(d) -> str:
    """'YYYY-MM-DD' → 'DD.MM.YYYY'. Пустая строка если None/пустое (без timezone-сдвига)."""
    if not d:
        return ''
    if isinstance(d, str):
        import re
        m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', d)
        if m:
            return f'{m.group(3)}.{m.group(2)}.{m.group(1)}'
    if isinstance(d, (datetime.date, datetime.datetime)):
        return d.strftime('%d.%m.%Y')
    return str(d)


def fmt_fixed_at(d) -> str:
    """timestamptz → МСК (UTC+3, без DST) → 'DD.MM HH:MM'. Пустая строка если невалидно."""
    if not d:
        return ''
    if isinstance(d, str):
        try:
            d = datetime.datetime.fromisoformat(d.replace('Z', '+00:00'))
        except ValueError:
            return ''
    if not isinstance(d, datetime.datetime):
        return ''
    if d.tzinfo is not None:
        d = d.astimezone(datetime.timezone.utc)
    msk = d + datetime.timedelta(hours=3)
    dd = str(msk.day).zfill(2)
    mm = str(msk.month).zfill(2)
    hh = str(msk.hour).zfill(2)
    mi = str(msk.minute).zfill(2)
    return f'{dd}.{mm} {hh}:{mi}'


# ---------------------------------------------------------------------------
# Чтение данных
# ---------------------------------------------------------------------------

def read_all_students() -> dict:
    """
    Возвращает {'data': {teacher: {group: groupData}}, 'index': {...}}.

    Только активные membership/группы/преподаватели. ORDER te.name, g.name, s.full_name.
    remaining — вычисляемый общий баланс ученика (apps.finances), не хранимая колонка;
    считается одним батч-запросом на всех учеников выборки (без N+1).
    """
    rows = list(
        GroupMembership.objects
        .filter(active=True, group__active=True, group__teacher__active=True)
        .order_by('group__teacher__name', 'group__name', 'student__full_name')
        .values(
            'group_id', 'student_id', 'lessons_done', 'sheet_row',
            group_name=F('group__name'),
            is_individual=F('group__is_individual'),
            vk_chat=F('group__vk_chat'),
            group_start_date=F('group__group_start_date'),
            teacher_name=F('group__teacher__name'),
            student_name=F('student__full_name'),
            age=F('student__age'),
            pm=F('student__pm'),
            membership_id=F('id'),
        )
    )

    balances = balances_for_students({r['student_id'] for r in rows})

    data: dict = {}
    index: dict = {}

    for r in rows:
        teacher = r['teacher_name']
        group = r['group_name']
        # Legacy Google Sheets поле direction.sheet_name удалено (раздел 05).
        # sheetName/sheetRow — вестигиальные поля, фронт их больше не читает по
        # значению; сохраняем ключ и осмысленный маркер «Индивидуальные».
        sheet_name = 'Индивидуальные' if r['is_individual'] else ''

        if teacher not in data:
            data[teacher] = {}
        if group not in data[teacher]:
            data[teacher][group] = {
                'students': [],
                'lessonsDone': 0,
                'pm': r['pm'] or '',
                'vkChat': r['vk_chat'] or '',
                'startDate': fmt_date_ru(r['group_start_date']),
                'isGroup': not r['is_individual'],
            }

        grp = data[teacher][group]

        # lessons_done — Number(x)||0 (None → 0); Decimal → int/float
        raw_done = r['lessons_done']
        if raw_done is None:
            done = 0
        else:
            f = float(raw_done)
            done = int(f) if f == int(f) else f

        remaining = balances[r['student_id']]

        if done > grp['lessonsDone']:
            grp['lessonsDone'] = done

        grp['students'].append({
            'name': r['student_name'],
            'lessonsDone': done,
            'remaining': remaining,
            'age': str(r['age']) if r['age'] is not None else '',
            'sheetName': sheet_name,
            'sheetRow': r['sheet_row'] or 0,
        })

        if r['sheet_row']:
            index[r['student_name'] + '|||' + group] = {
                'sheetName': sheet_name,
                'sheetRow': r['sheet_row'],
            }

    return {'data': data, 'index': index}


def read_filled_lessons(week_start_str: str) -> dict:
    """
    Возвращает map {groupName+'|||'+weekStartStr: fmtFixedAt(first_at)}.

    Уроки в [week_start, week_start+6] (включительно), MIN(submitted_at) по группе.
    """
    week_start_date = datetime.date.fromisoformat(week_start_str)
    week_end_date = week_start_date + datetime.timedelta(days=6)
    week_end_str = week_end_date.isoformat()

    rows = (
        Lesson.objects
        .filter(lesson_date__gte=week_start_str, lesson_date__lte=week_end_str)
        .values(group_name=F('group__name'))
        .annotate(first_at=Min('submitted_at'))
    )

    result: dict = {}
    for r in rows:
        result[r['group_name'] + '|||' + week_start_str] = fmt_fixed_at(r['first_at'])
    return result


# ---------------------------------------------------------------------------
# Resolve IDs (внутри submit_lesson, вызывается из service ДО транзакции)
# ---------------------------------------------------------------------------

def resolve_ids(teacher_name: str, group_name: str) -> Optional[dict]:
    """
    submitter_teacher_id + метаданные группы. None если группа не найдена.

    submitter_teacher_id может быть None (преподаватель с таким именем не найден).
    """
    grp = (
        Group.objects.filter(name=group_name)
        .values('id', 'teacher_id', 'lesson_duration_minutes', 'direction_id')
        .first()
    )
    if grp is None:
        return None

    submitter_teacher_id = (
        Teacher.objects.filter(name=teacher_name).values_list('id', flat=True).first()
    )
    return {
        'submitter_teacher_id': submitter_teacher_id,
        'group_id': grp['id'],
        'group_owner_id': grp['teacher_id'],
        'lesson_duration_minutes': grp['lesson_duration_minutes'],
        'direction_id': grp['direction_id'],
    }


def resolve_group_meta(group_name: str) -> Optional[dict]:
    """{'id', 'teacher_id'} группы по имени, None если не найдена."""
    return (
        Group.objects.filter(name=group_name).values('id', 'teacher_id').first()
    )


def teacher_has_any_planned_lesson(group_id: int, teacher_id: int) -> bool:
    """
    Назначено ли преподавателю хотя бы одно НЕотменённое плановое занятие группы
    (любая дата) — доступ заменщика к странице группы в teacher SPA.
    """
    return (
        PlannedLesson.objects
        .filter(group_id=group_id, teacher_id=teacher_id)
        .exclude(status='cancelled')
        .exists()
    )


def planned_lesson_is_moved(group_id: int, lesson_date: str, teacher_id: int) -> bool:
    """
    Перенесено ли НА эту дату плановое занятие преподавателя (moved_from_date
    задан). Сервер выводит из этого lesson_type='reschedule' — клиентский
    выбор «Перенос» в submitLesson упразднён.
    """
    return (
        PlannedLesson.objects
        .filter(
            group_id=group_id,
            scheduled_date=lesson_date,
            teacher_id=teacher_id,
            moved_from_date__isnull=False,
        )
        .exclude(status='cancelled')
        .exists()
    )


def has_assigned_planned_lesson(group_id: int, lesson_date: str, teacher_id: int) -> bool:
    """
    Есть ли у преподавателя НЕотменённое плановое занятие этой группы на дату.

    Основание отметить урок ЧУЖОЙ группы: замена, назначенная админом через
    «Сменить преподавателя» (planned_lessons.teacher_id ≠ учитель группы).
    """
    return (
        PlannedLesson.objects
        .filter(group_id=group_id, scheduled_date=lesson_date, teacher_id=teacher_id)
        .exclude(status='cancelled')
        .exists()
    )


def resolve_students(group_id: int) -> list[dict]:
    """student_id, full_name, membership_id активных membership группы."""
    return list(
        GroupMembership.objects
        .filter(group_id=group_id, active=True)
        .values('student_id', membership_id=F('id'), full_name=F('student__full_name'))
    )


# ---------------------------------------------------------------------------
# Запись урока (вызываются изнутри transaction.atomic в services.py)
# ---------------------------------------------------------------------------

def insert_lesson(fields: dict) -> int:
    """
    INSERT урока. Возвращает id. submitted_at — DB DEFAULT now() через Now().
    """
    obj = Lesson.objects.create(
        lesson_date=fields['lesson_date'],
        teacher_id=fields['teacher_id'],
        group_id=fields['group_id'],
        original_teacher_id=fields.get('original_teacher_id'),
        lesson_number=fields['lesson_number'],
        lesson_duration_minutes=fields['lesson_duration_minutes'],
        lesson_type=fields['lesson_type'],
        record_url=fields.get('record_url'),
        submitted_by_token=fields['submitted_by_token'],
        submitted_at=Now(),
    )
    return obj.pk


def increment_counters(membership_ids: list, step) -> None:
    """UPDATE group_memberships SET lessons_done += step WHERE id IN ids. half-lesson step."""
    if not membership_ids:
        return
    step_dec = Decimal(str(step))   # numeric-арифметика без float-сюрпризов
    GroupMembership.objects.filter(id__in=membership_ids).update(
        lessons_done=F('lessons_done') + step_dec,
    )


def insert_attendance(lesson_id: int, attendance: list) -> None:
    """
    Вставка посещаемости только для существующих студентов (= JOIN students),
    ON CONFLICT (lesson_id, student_id) DO NOTHING. No-op если список пуст.
    """
    if not attendance:
        return
    sids = [a['student_id'] for a in attendance]
    valid = set(Student.objects.filter(id__in=sids).values_list('id', flat=True))
    LessonAttendance.objects.bulk_create(
        [
            LessonAttendance(
                lesson_id=lesson_id,
                student_id=a['student_id'],
                present=bool(a['present']),
            )
            for a in attendance if a['student_id'] in valid
        ],
        ignore_conflicts=True,
    )


def insert_payroll(fields: dict) -> None:
    """INSERT записи payroll."""
    Payroll.objects.create(
        lesson_id=fields['lesson_id'],
        teacher_id=fields['teacher_id'],
        total_students=fields['total_students'],
        present_count=fields['present_count'],
        payment=fields['payment'],
        penalty=fields['penalty'],
    )
