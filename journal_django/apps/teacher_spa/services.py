"""
TeacherSpaService — бизнес-логика teacher SPA.

Слой: View → Service (здесь) → Repository (ORM).
Никакого SQL здесь. Транзакция submit_lesson управляется через
transaction.atomic; репозиторий выполняет ORM-операции.

Порт routes/teacher.js + services/teacher-repo.js.
"""
from __future__ import annotations

import warnings
from typing import Optional

from django.db import transaction

from apps.accounts.repository import get_by_id_with_teacher
from apps.teacher_spa import repository
from apps.teacher_spa.calculator import (
    calculate_payment,
    calculate_penalty,
    format_msk_date,
)


def _sync_renewal_stage(student_id: int, direction_id: int | None) -> None:
    """Пост-коммит-хук: подвинуть авто-стадию «Урок N» раздела «Продления»."""
    from apps.renewals import engine
    engine.sync_lesson_stage_safe(student_id, direction_id)


def get_current_teacher(account_id: int) -> Optional[str]:
    """
    Порт currentTeacher() из routes/teacher.js.

    Возвращает teacher_name или None если аккаунт не привязан к преподавателю.
    """
    acc = get_by_id_with_teacher(account_id)
    return acc['teacher_name'] if acc else None


def get_data(account_id: int) -> dict:
    """
    Порт POST /api/getData из routes/teacher.js.

    Возвращает {'teacher': str, 'data': groupDict} или {'_error': str, '_status': int}.
    """
    teacher = get_current_teacher(account_id)
    if not teacher:  # порт JS if(!teacher): None и пустая строка → не привязан
        return {'_error': 'Аккаунт не привязан к преподавателю', '_status': 403}

    unified = repository.read_all_students()
    teacher_data = unified['data'].get(teacher, {})
    return {'teacher': teacher, 'data': teacher_data}


def get_all_data(account_id: int) -> dict:
    """
    Порт POST /api/getAllData из routes/teacher.js.

    Возвращает {'teacher': str, 'data': все данные} или {'_error': ..., '_status': 403}.
    """
    teacher = get_current_teacher(account_id)
    if not teacher:  # порт JS if(!teacher): None и пустая строка → не привязан
        return {'_error': 'Аккаунт не привязан к преподавателю', '_status': 403}

    unified = repository.read_all_students()
    return {'teacher': teacher, 'data': unified['data']}


def submit_lesson(account_id: int, validated: dict) -> dict:
    """
    Порт POST /api/submitLesson из routes/teacher.js (lines 38-139).

    Атомарная транзакция: lesson + attendance + payroll + инкремент счётчиков.
    Возвращает:
      {'success': True, 'payment': int, 'penalty': int, 'lessonNumber': float|int}
      {'success': False, 'error': str}   — ошибки без статуса 4xx (как Express)
      {'_error': str, '_status': 403}    — аккаунт не привязан к преподу
    """
    group = validated['group']
    date = validated['date']
    record_url = validated.get('recordUrl') or None
    lesson_type = validated.get('lessonType')
    is_substitution = bool(validated.get('isSubstitution', False))
    original_teacher = validated.get('originalTeacher')
    students = validated['students']

    # 1. Auth — препод из сессии
    teacher = get_current_teacher(account_id)
    if not teacher:  # порт JS if(!teacher): None и пустая строка → не привязан
        return {'_error': 'Аккаунт не привязан к преподавателю', '_status': 403}

    # 2. Актуальное состояние (readAllStudents)
    unified = repository.read_all_students()
    teacher_for_group = original_teacher if (is_substitution and original_teacher) else teacher
    teacher_data = unified['data'].get(teacher_for_group)
    if not teacher_data or group not in teacher_data:
        return {'success': False, 'error': 'Группа не найдена'}

    group_data = teacher_data[group]

    # 3. Resolve IDs (submitter + группа + продолжительность). Делаем ДО расчётов:
    #    half-lesson теперь определяется СТРУКТУРНО (lesson_duration_minutes == 45),
    #    а не regex '/45\s*минут/' по имени группы (Ф4 — вывод regex из hot-path).
    ids = repository.resolve_ids(teacher, group)
    if not ids or not ids.get('submitter_teacher_id'):
        return {'success': False, 'error': 'Группа/преподаватель не найдены в БД'}

    lesson_teacher_id = ids['submitter_teacher_id']
    original_teacher_id = ids['group_owner_id'] if is_substitution else None

    # 4. Расчёты — half-lesson, lesson_number, payment, penalty
    is_half = ids['lesson_duration_minutes'] == 45
    step = 0.5 if is_half else 1

    total_students = len(students)
    present_count = sum(1 for s in students if s['present'])

    # done = max(lessonsDone) по студентам группы, или 0 если группа пуста
    group_students = group_data.get('students', [])
    done = max((s.get('lessonsDone') or 0 for s in group_students), default=0)

    # lessonNum = Math.round((done + step) * 10) / 10
    # (done + step) * 10 всегда целое (step кратен 0.5), поэтому round — no-op.
    raw = (done + step) * 10
    lesson_num = round(raw) / 10

    payment = calculate_payment(total_students, present_count, is_half)
    penalty = calculate_penalty(date, format_msk_date())

    # 5. Mapping student_name → {student_id, membership_id}
    stud_rows = repository.resolve_students(ids['group_id'])
    by_name = {r['full_name']: r for r in stud_rows}

    present_membership_ids: list[int] = []
    present_student_ids: list[int] = []
    attendance: list[dict] = []
    for s in students:
        meta = by_name.get(s['name'])
        if meta is None:
            warnings.warn(
                f'submitLesson: студент "{s["name"]}" не найден в group_memberships '
                f'для group_id={ids["group_id"]}',
                stacklevel=2,
            )
            continue
        attendance.append({'student_id': meta['student_id'], 'present': bool(s['present'])})
        if s['present']:
            present_membership_ids.append(meta['membership_id'])
            present_student_ids.append(meta['student_id'])

    # 6. subLabel — тип урока
    if is_substitution:
        sub_label = 'substitution'
    elif lesson_type == 'reschedule':
        sub_label = 'reschedule'
    else:
        sub_label = 'regular'

    # 7. Атомарная транзакция (репозиторий — ORM, транзакция управляется здесь)
    with transaction.atomic():
        lesson_id = repository.insert_lesson({
            'lesson_date': date,
            'teacher_id': lesson_teacher_id,
            'group_id': ids['group_id'],
            'original_teacher_id': original_teacher_id,
            'lesson_number': lesson_num,
            'lesson_duration_minutes': ids['lesson_duration_minutes'],
            'lesson_type': sub_label,
            'record_url': record_url,
            'submitted_by_token': f'acct:{account_id}',
        })
        repository.increment_counters(present_membership_ids, step)
        repository.insert_attendance(lesson_id, attendance)
        repository.insert_payroll({
            'lesson_id': lesson_id,
            'teacher_id': lesson_teacher_id,
            'total_students': total_students,
            'present_count': present_count,
            'payment': payment,
            'penalty': penalty,
        })

        # Подвинуть авто-стадию «Урок N» раздела «Продления» по факту посещаемости
        # (после коммита — сбой этой вторичной CRM-фичи не должен уронить submitLesson).
        direction_id = ids['direction_id']
        for sid in present_student_ids:
            transaction.on_commit(lambda sid=sid: _sync_renewal_stage(sid, direction_id))

    # lessonNumber: если целое → int, иначе float (JS-совместимость)
    lesson_number_out = int(lesson_num) if lesson_num == int(lesson_num) else lesson_num

    return {
        'success': True,
        'payment': payment,
        'penalty': penalty,
        'lessonNumber': lesson_number_out,
    }
