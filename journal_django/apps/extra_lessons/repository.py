"""ExtraLessonsRepository — единственное место ORM-доступа раздела (пер-ученик AbsenceResolution)."""
from __future__ import annotations

from typing import Optional

from django.db.models import F
from django.db.models.functions import Coalesce

from apps.extra_lessons.models import (
    BURNED, EXTRA, MAKEUP_DONE, MAKEUP_SCHEDULED, PENDING, AbsenceResolution,
)
from apps.lessons.models import Lesson, LessonAttendance


def autocreate_pending(missed_lesson_id, student_ids) -> int:
    """Идемпотентно создать pending-резолюции по списку отсутствовавших.
    bulk_create(ignore_conflicts=True) → INSERT ... ON CONFLICT DO NOTHING по
    UNIQUE(missed_lesson, student). Возвращает len(student_ids) (верхняя оценка;
    тесты проверяют факт создания выборкой). Пустой список — no-op (return 0).

    Через ORM, а не raw executemany: последний несовместим с инъекцией
    pghistory-контекста под HTTP-запросом (не все аргументы форматируются)."""
    if not student_ids:
        return 0
    AbsenceResolution.objects.bulk_create(
        [AbsenceResolution(missed_lesson_id=missed_lesson_id, student_id=sid, status=PENDING)
         for sid in student_ids],
        ignore_conflicts=True,
    )
    return len(student_ids)


def _full_values(qs):
    return qs.values(
        'id', 'missed_lesson_id', 'student_id', 'assigned_teacher_id', 'scheduled_date',
        'scheduled_time', 'duration_minutes', 'status', 'fact_lesson_id',
        'kind', 'group_id', 'target_lesson_number',
        student_name=F('student__full_name'),
        teacher_name=F('assigned_teacher__name'),
        missed_lesson_group_id=F('missed_lesson__group_id'),
        missed_lesson_group_name=F('missed_lesson__group__name'),
        missed_lesson_date=F('missed_lesson__lesson_date'),
        missed_lesson_number=F('missed_lesson__lesson_number'),
        # Унифицированное имя группы для отображения: makeup → группа пропуска,
        # extra → собственная группа резолюции.
        resolution_group_name=Coalesce(F('group__name'), F('missed_lesson__group__name')))


def get_resolution_full(resolution_id) -> Optional[dict]:
    return _full_values(AbsenceResolution.objects.filter(id=resolution_id)).first()


def lock_for_record(resolution_id) -> Optional[dict]:
    """SELECT ... FOR UPDATE внутри atomic() — авторитетная проверка статуса перед записью.

    of=('self',): missed_lesson теперь nullable (kind='extra' → NULL), из-за чего
    обращение к missed_lesson__group_id даёт LEFT OUTER JOIN, а FOR UPDATE по
    nullable-стороне outer join Postgres запрещает. Лочим только строку резолюции
    (не joined-таблицу lessons) — этого достаточно (сериализуем правки самой резолюции)."""
    return (AbsenceResolution.objects.select_for_update(of=('self',)).filter(id=resolution_id)
            .values('id', 'status', 'assigned_teacher_id', 'missed_lesson_id', 'student_id',
                    'scheduled_date', 'duration_minutes', 'kind', 'group_id',
                    'target_lesson_number',
                    missed_lesson_group_id=F('missed_lesson__group_id')).first())


def lock_for_delete(resolution_id) -> Optional[dict]:
    return (AbsenceResolution.objects.select_for_update().filter(id=resolution_id)
            .values('id', 'status', 'missed_lesson_id', 'student_id', 'fact_lesson_id').first())


def lock_for_assign(missed_lesson_id, student_id) -> Optional[dict]:
    """SELECT ... FOR UPDATE резолюции перед переводом в makeup_scheduled.
    None → строки нет (сервис создаст напрямую create_scheduled_direct)."""
    return (AbsenceResolution.objects.select_for_update()
            .filter(missed_lesson_id=missed_lesson_id, student_id=student_id)
            .values('id', 'status').first())


def find_group_regular_lesson(group_id, lesson_number):
    """id проведённого ОБЫЧНОГО урока группы на слоте lesson_number (не extra/burned)
    — для роутинга ручного доп.урока: если реальный урок №N есть, ручное назначение
    идёт как makeup, привязанный к нему. None → такого урока нет (→ extra сверх курса)."""
    from decimal import Decimal
    return (Lesson.objects
            .filter(group_id=group_id, lesson_number=Decimal(str(lesson_number)))
            .exclude(lesson_type__in=('extra', 'burned'))
            .values_list('id', flat=True).first())


def students_present_on(lesson_id, student_ids) -> set[int]:
    """student_id, отмеченные ПРИСУТСТВОВАВШИМИ (present=true) на уроке — гард
    ручного доп.урока: за посещённый урок доп.урок ставить нельзя."""
    return set(
        LessonAttendance.objects
        .filter(lesson_id=lesson_id, student_id__in=student_ids, present=True)
        .values_list('student_id', flat=True)
    )


def students_not_absent(missed_lesson_id, student_ids) -> list[int]:
    absent = set(LessonAttendance.objects.filter(
        lesson_id=missed_lesson_id, student_id__in=student_ids, present=False
    ).values_list('student_id', flat=True))
    return [sid for sid in student_ids if sid not in absent]


def assign_pending(resolution_id, *, assigned_teacher_id, scheduled_date, scheduled_time,
                   duration_minutes) -> None:
    """pending → makeup_scheduled с параметрами доп.урока."""
    AbsenceResolution.objects.filter(id=resolution_id).update(
        status=MAKEUP_SCHEDULED, assigned_teacher_id=assigned_teacher_id,
        scheduled_date=scheduled_date, scheduled_time=scheduled_time,
        duration_minutes=duration_minutes)


def create_scheduled_direct(*, missed_lesson_id, student_id, assigned_teacher_id,
                            scheduled_date, scheduled_time, duration_minutes) -> int:
    """Edge: pending-строки нет (пропуск до релиза) → создать сразу makeup_scheduled."""
    obj = AbsenceResolution.objects.create(
        missed_lesson_id=missed_lesson_id, student_id=student_id,
        assigned_teacher_id=assigned_teacher_id, status=MAKEUP_SCHEDULED,
        scheduled_date=scheduled_date, scheduled_time=scheduled_time,
        duration_minutes=duration_minutes)
    return obj.id


def create_extra_direct(*, group_id, student_id, assigned_teacher_id, scheduled_date,
                        scheduled_time, duration_minutes, target_lesson_number) -> int:
    """Назначить доп.урок СВЕРХ курса (kind='extra', без пропуска): создаётся сразу
    makeup_scheduled. Группа — из group_id (не из пропуска), «за какой урок» —
    target_lesson_number (может быть None → record() возьмёт следующую позицию)."""
    obj = AbsenceResolution.objects.create(
        kind=EXTRA, missed_lesson_id=None, group_id=group_id, student_id=student_id,
        assigned_teacher_id=assigned_teacher_id, status=MAKEUP_SCHEDULED,
        scheduled_date=scheduled_date, scheduled_time=scheduled_time,
        duration_minutes=duration_minutes, target_lesson_number=target_lesson_number)
    return obj.id


def delete_resolution(resolution_id) -> None:
    """Полностью удалить резолюцию — для extra (доп.урок сверх курса) отмена/откат
    означают отмену самого назначения (в отличие от makeup, где есть pending-пропуск,
    к которому возвращаемся)."""
    AbsenceResolution.objects.filter(id=resolution_id).delete()


def back_to_pending(resolution_id) -> None:
    """Отмена назначения / откат факта → pending. Сбрасывает параметры и факт."""
    AbsenceResolution.objects.filter(id=resolution_id).update(
        status=PENDING, assigned_teacher_id=None, scheduled_date=None,
        scheduled_time=None, duration_minutes=None, fact_lesson_id=None)


def mark_makeup_done(resolution_id, *, fact_lesson_id) -> None:
    AbsenceResolution.objects.filter(id=resolution_id).update(
        status=MAKEUP_DONE, fact_lesson_id=fact_lesson_id)


def mark_burned(resolution_id, *, fact_lesson_id) -> None:
    """pending → burned с привязкой к созданному burned-факту (Lesson)."""
    AbsenceResolution.objects.filter(id=resolution_id).update(
        status=BURNED, fact_lesson_id=fact_lesson_id)


def pending_count() -> int:
    """Число необработанных пропусков (status=pending) — для бейджа в сайдбаре."""
    return AbsenceResolution.objects.filter(status=PENDING).count()


def has_active_resolution(missed_lesson_id, student_id) -> bool:
    """Уже назначено / проведено / сожжено? (pending НЕ считается — его как раз
    разрешают). Guard от повторного назначения или сжигания уже закрытого пропуска."""
    return (AbsenceResolution.objects
            .filter(missed_lesson_id=missed_lesson_id, student_id=student_id,
                    status__in=[MAKEUP_SCHEDULED, MAKEUP_DONE, BURNED]).exists())


def has_scheduled_for_student_in_group(student_id, group_id) -> bool:
    """Есть ли у ученика НАЗНАЧЕННЫЙ (не проведённый) доп.урок в этой группе? Гейт
    снятия членства: makeup_scheduled нельзя удалять молча (за ним преподаватель +
    дата) — операция снятия членства блокируется до его разбора. Покрывает и makeup
    (группа пропуска), и extra сверх курса (собственная группа резолюции)."""
    from django.db.models import Q
    return (AbsenceResolution.objects
            .filter(Q(missed_lesson__group_id=group_id) | Q(group_id=group_id),
                    student_id=student_id, status=MAKEUP_SCHEDULED)
            .exists())


def delete_pending_for_student_in_group(student_id, group_id) -> int:
    """Снятие членства в группе: удалить pending («Ждёт решения») резолюции ученика
    по пропускам ИМЕННО этой группы. makeup_scheduled/makeup_done/burned не трогаем
    (первый блокирует снятие раньше, у остальных есть факт/деньги). Возвращает число."""
    qs = AbsenceResolution.objects.filter(
        student_id=student_id, missed_lesson__group_id=group_id, status=PENDING)
    n = qs.count()
    qs.delete()
    return n


def list_resolutions(page=1, page_size=50, sort_by='scheduled_date', sort_dir='desc', filters=None) -> dict:
    filters = filters or {}
    sortable = {'scheduled_date': 'scheduled_date', 'status': 'status',
                'teacher_name': 'assigned_teacher__name', 'student_name': 'student__full_name'}
    order = ('' if sort_dir == 'asc' else '-') + sortable.get(sort_by, 'scheduled_date')
    qs = AbsenceResolution.objects.all()
    if filters.get('status'):
        qs = qs.filter(status=filters['status'])
    if filters.get('teacher_id'):
        qs = qs.filter(assigned_teacher_id=int(filters['teacher_id']))
    if filters.get('student_name'):
        qs = qs.filter(student__full_name__icontains=filters['student_name'])
    if filters.get('missed_lesson_group_name'):
        qs = qs.filter(missed_lesson__group__name__icontains=filters['missed_lesson_group_name'])
    total = qs.count()
    offset = max(0, (page - 1) * page_size)
    rows = list(_full_values(qs.order_by(order, '-id')[offset:offset + page_size]))
    return {'rows': rows, 'total': total, 'page': page, 'page_size': page_size}


def unfilled_extra_lessons(today, teacher_id=None) -> list[dict]:
    """Незаполненные доп.уроки (отработки) по школе с датой <= today — источник
    вкладки «Заполнить». makeup_scheduled без факта; pending имеет scheduled_date
    NULL и не попадает, makeup_done имеет проставленный fact_lesson. Overdue-порог
    по времени досчитывает вызывающий (fill_service). group_id/group_name — группа
    пропущенного урока (для перехода). Опц. скоуп по назначенному преподавателю."""
    qs = AbsenceResolution.objects.filter(
        status=MAKEUP_SCHEDULED,
        fact_lesson__isnull=True,
        scheduled_date__lte=today,
    )
    if teacher_id is not None:
        qs = qs.filter(assigned_teacher_id=teacher_id)
    # Группа резолюции: для makeup — группа пропущенного урока; для extra (сверх
    # курса, missed_lesson=NULL) — из поля `group`. Coalesce покрывает оба.
    # Алиасы _grp_* (не group_id/group_name) — иначе конфликт с полем group_id.
    rows = list(
        qs.order_by('scheduled_date', 'scheduled_time').values(
            'id', 'scheduled_date', 'scheduled_time', 'assigned_teacher_id',
            _grp_id=Coalesce(F('group'), F('missed_lesson__group_id')),
            _grp_name=Coalesce(F('group__name'), F('missed_lesson__group__name')),
        )
    )
    for r in rows:
        r['group_id'] = r.pop('_grp_id')
        r['group_name'] = r.pop('_grp_name')
    return rows


def assignments_in_window(teacher_id, window_from, window_to) -> list[dict]:
    """Резолюции за окно — источник календаря доп.уроков. teacher_id=None → ВСЕ
    преподаватели (admin-календарь без фильтра); иначе — один. Каждая резолюция =
    одна карточка (пер-ученик), поэтому student_names — список из одного имени
    (форму сохраняем для совместимости с scheduling-консьюмером). Имя группы —
    Coalesce(group, missed_lesson.group): makeup берёт группу пропуска, extra —
    свою группу."""
    qs = AbsenceResolution.objects.filter(
        scheduled_date__gte=window_from, scheduled_date__lte=window_to)
    if teacher_id is not None:
        qs = qs.filter(assigned_teacher_id=teacher_id)
    rows = list(
        qs.values('id', 'scheduled_date', 'scheduled_time', 'duration_minutes', 'status',
                  teacher_name=F('assigned_teacher__name'),
                  missed_lesson_group_name=Coalesce(
                      F('group__name'), F('missed_lesson__group__name')),
                  _student_name=F('student__full_name')))
    for r in rows:
        name = r.pop('_student_name')
        r['student_names'] = [name] if name else []
    return rows
