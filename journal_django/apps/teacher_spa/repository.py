"""
TeacherSpaRepository — единственное место доступа к данным раздела teacher_spa.

ORM-порт services/teacher-repo.js (раздел 09):
  - read_all_students  — главный срез данных (data[teacher][group])
  - read_filled_lessons — заполненные уроки за неделю (для report)
  - resolve_ids / resolve_students — разрешение id перед записью урока

Запись самого урока (insert_lesson/insert_attendance/insert_payroll/
increment_counters) вынесена в apps.lessons.repository — вызывается через
apps.lessons.services.record_lesson (единое ядро, см.
docs/superpowers/specs/2026-07-14-unify-lesson-recording-design.md).

Half-lesson инвариант (step 0.5/1) приходит из services.py.
"""
from __future__ import annotations

import datetime
from typing import Optional

from django.db.models import F, Min

from apps.finances.repository import balances_for_students
from apps.groups.models import Group
from apps.lessons.models import Lesson
from apps.memberships.models import GroupMembership
from apps.scheduling.models import PlannedLesson
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
            'group_id', 'student_id', 'lessons_done', 'sheet_row', 'transferred_from_id',
            group_name=F('group__name'),
            is_individual=F('group__is_individual'),
            vk_chat=F('group__vk_chat'),
            group_start_date=F('group__group_start_date'),
            teacher_name=F('group__teacher__name'),
            student_name=F('student__full_name'),
            birth_date=F('student__birth_date'),
            pm=F('student__manager__full_name'),
            membership_id=F('id'),
            duration_minutes=F('group__lesson_duration_minutes'),
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
                'durationMinutes': r['duration_minutes'],
                '_group_id': r['group_id'],
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

        locked_through = None
        if r['transferred_from_id']:
            from apps.memberships.repository import cumulative_transferred_lessons
            locked_through = cumulative_transferred_lessons(r['transferred_from_id'])

        grp['students'].append({
            'name': r['student_name'],
            'lessonsDone': done,
            'remaining': remaining,
            # Возраст считает teacher-фронт из birth_date (поле age удалено).
            'birthDate': r['birth_date'].isoformat() if r['birth_date'] else '',
            'sheetName': sheet_name,
            'sheetRow': r['sheet_row'] or 0,
            'lockedThrough': float(locked_through) if locked_through is not None else None,
            '_student_id': r['student_id'],
        })

        if r['sheet_row']:
            index[r['student_name'] + '|||' + group] = {
                'sheetName': sheet_name,
                'sheetRow': r['sheet_row'],
            }

    # Маркеры «неоплачиваемый пропуск» (LessonSkip) по всем группам выборки — один
    # батч-запрос. skips[(group_id, lesson_number)] = {student_id}. Нужно, чтобы
    # преподаватель НЕ мог отметить помеченного ученика и превью зарплаты его не
    # считало (record_lesson всё равно исключит на бэке, но форма должна совпадать).
    from apps.lessons.models import LessonSkip
    skips: dict = {}
    for sr in LessonSkip.objects.filter(
        group_id__in={r['group_id'] for r in rows},
    ).values('group_id', 'student_id', 'lesson_number'):
        skips.setdefault((sr['group_id'], float(sr['lesson_number'])), set()).add(sr['student_id'])

    for teacher_groups in data.values():
        for grp in teacher_groups.values():
            step = 0.5 if grp['durationMinutes'] == 45 else 1
            next_number = float(grp['lessonsDone'] + step)
            gid = grp.pop('_group_id')
            skip_ids = skips.get((gid, next_number), set())
            for s in grp['students']:
                s['locked'] = s['lockedThrough'] is not None and next_number <= s['lockedThrough']
                # skip — «неоплачиваемый пропуск» на СЛЕДУЮЩИЙ урок группы.
                s['skip'] = s.pop('_student_id') in skip_ids

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
