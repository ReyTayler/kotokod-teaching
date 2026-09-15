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

from django.db.models import F, Min, Q

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


def fmt_lesson_number(value) -> str:
    """
    Номер урока → строка-ключ: 3 → '3', 3.5 → '3.5' (half-lesson).

    Формат обязан совпадать с тем, что даёт JS `String(number)` на фронте: по этому
    ключу LessonForm ищет маркеры «неоплачиваемый пропуск» для заполняемого урока.
    """
    f = float(value)
    return str(int(f)) if f == int(f) else str(f)


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

    Для страниц (расписание, отчёт) полная выборка по смыслу. На пути ЗАПИСИ урока
    её быть не должно — там read_group_students (см. ниже).
    """
    return _build_from_rows(_membership_rows())


def read_group_students(group_name: str) -> dict:
    """
    То же самое, но только по ОДНОЙ группе (по имени). Формат ответа идентичен
    read_all_students — вызывающий не различает, откуда пришли данные.

    Зачем: read_all_students стояла на пути записи урока (submit_lesson) и тянула
    все активные membership всей школы плюс баланс по каждому ученику. На странице
    это терпимо, но запись урока — самое критичное действие, а sync-воркеров на всю
    школу единицы: три одновременные отправки занимали сервер целиком (инцидент
    ПГ215).

    Имя, а не id: группу teacher SPA знает по имени (клиент присылает его), и
    разрешение имени в id — отдельный шаг ниже по submit_lesson. Если имя носят
    группы двух преподавателей, вернутся обе ветки — ровно как в полной выборке,
    и вызывающий выбирает владельца той же логикой.
    """
    return _build_from_rows(_membership_rows(group_name=group_name))


def _membership_rows(group_name: str | None = None) -> list[dict]:
    """
    Строки активных membership. Единственное место, где живёт этот запрос:
    полная выборка и выборка по группе отличаются ТОЛЬКО фильтром, чтобы набор
    полей и порядок не могли разъехаться.
    """
    qs = (
        GroupMembership.objects
        .filter(active=True, group__active=True, group__teacher__active=True)
    )
    if group_name is not None:
        qs = qs.filter(group__name=group_name)
    return list(
        qs
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


def _build_from_rows(rows: list[dict]) -> dict:
    """
    Сборка ответа из уже выбранных строк membership.

    Вынесено из read_all_students, чтобы выборка по одной группе давала БАЙТ В
    БАЙТ тот же формат: две параллельные сборки неизбежно разъехались бы, а на
    этом формате стоит вся запись урока — владелец группы, признак замены,
    прогресс учеников, маркеры «неоплачиваемый пропуск».

    Блокировки ученика в форме записи (перевод, неоплачиваемый пропуск) зависят от
    НОМЕРА заполняемого урока, а его знает только форма (номер из плана занятия, по
    которому кликнули). Поэтому отсюда уходят ФАКТЫ, а не готовые флаги:
    `lockedThrough` у ученика и `skips` {номер урока: [имена]} у группы.
    """
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
    # батч-запрос. Отдаём ВСЕ номера уроков группы, а не «тот, который следующий»:
    # форма записи заполняет урок с номером ИЗ ПЛАНА (planned_lessons.lesson_number),
    # а он не обязан совпадать с номером, выведенным из прогресса учеников
    # (max(lessons_done)+шаг). Расходятся они штатно — переведённый ученик тянет
    # max вверх, сожжённый пропуск даёт +1 без занятия, перенос двигает план. Выбери
    # мы номер здесь, подсказка для формы отвечала бы про ДРУГОЙ урок, чем тот, что
    # запишется: помеченный ученик выглядел бы обычным, преподаватель ставил бы ему
    # «Пришёл», а record_lesson всё равно форсил бы unpaid_skip — молча и с другой
    # суммой в превью зарплаты. Номер-ключ выбирает фронт — ровно тот, что показывает.
    from apps.lessons.models import LessonSkip
    skips: dict = {}
    for sr in LessonSkip.objects.filter(
        group_id__in={r['group_id'] for r in rows},
    ).values('group_id', 'student_id', 'lesson_number'):
        (skips.setdefault(sr['group_id'], {})
              .setdefault(fmt_lesson_number(sr['lesson_number']), set())
              .add(sr['student_id']))

    for teacher_groups in data.values():
        for grp in teacher_groups.values():
            gid = grp.pop('_group_id')
            # Имена, а не id: ученик в этом ответе живёт под именем (present, index,
            # submitLesson — всё по имени), id наружу не отдаём.
            names_by_id = {s.pop('_student_id'): s['name'] for s in grp['students']}
            group_skips = skips.get(gid, {})
            # locked здесь НЕ считаем по той же причине: блокировка переведённого —
            # это «номер урока <= lockedThrough», и номер опять же знает только форма.
            # Отдаём факт (lockedThrough), решение принимает фронт.
            grp['skips'] = {
                num: sorted(names_by_id[sid] for sid in sids if sid in names_by_id)
                for num, sids in sorted(group_skips.items(), key=lambda kv: float(kv[0]))
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

    Основание отметить урок ЧУЖОЙ группы — назначение админом, в двух видах:
      • «Сменить преподавателя» → planned_lessons.teacher_id (препод контента);
      • разовая замена на дату → planned_lessons.substitute_teacher_id.

    Скоуп ОБЯЗАН совпадать с календарём (scheduling.repository.
    planned_lessons_in_window): эффективный преподаватель занятия — замена, если
    она задана, иначе препод контента. Пока здесь смотрели только teacher_id,
    замещающий видел занятие в своём календаре, но получал 403 при сохранении
    урока — фронт показывал это как «Сессия истекла» (баг 2026-07-30).
    """
    return (
        PlannedLesson.objects
        .filter(group_id=group_id, scheduled_date=lesson_date)
        .filter(
            Q(substitute_teacher_id=teacher_id)
            | Q(substitute_teacher_id__isnull=True, teacher_id=teacher_id)
        )
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
