"""
StudentsService — тонкий слой между views и repository.

Принцип: никакого SQL здесь — всё через repository.
"""
from __future__ import annotations

from typing import Optional

from django.db import transaction

from apps.payments import services as payments_services
from apps.students import repository


def list_students(
    page: int = 1,
    page_size: int = 50,
    sort_by: str = 'full_name',
    sort_dir: str = 'asc',
    filters: Optional[dict] = None,
) -> dict:
    """Делегирует список учеников в repository."""
    return repository.list_students(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        filters=filters,
    )


def get_student(student_id: int) -> Optional[dict]:
    """Возвращает ученика или None."""
    return repository.get_student(student_id)


def create_student(data: dict) -> dict:
    """Создаёт ученика."""
    return repository.create_student(data)


def update_student(student_id: int, data: dict) -> Optional[dict]:
    """Обновляет ученика. Возвращает None если не найден."""
    return repository.update_student(student_id, data)


def student_stats(student_id: int) -> dict:
    """Сводка посещаемости ученика."""
    return repository.student_stats(student_id)


def get_student_balance(student_id: int) -> dict:
    """Баланс ученика по направлениям (постоянный дом — apps/payments/)."""
    return payments_services.get_student_balance(student_id)


def add_comment(student_id: int, body: str, author_id: Optional[int]):
    """Создаёт комментарий к ученику."""
    return repository.add_comment(student_id, body, author_id)


def delete_comment(student_id: int, comment_id: int) -> bool:
    """Удаляет комментарий. False если не найден."""
    return repository.delete_comment(student_id, comment_id)


# ---------------------------------------------------------------------------
# Оркестрация смены статуса ученика (Task 9). Единая транзакция: членства,
# индив-расписание (хвост) и сделка продления двигаются согласованно. Права/
# валидация входных данных — на уровне view/serializer, здесь чистый каскад.
# ---------------------------------------------------------------------------

def _affected_memberships(student_id: int, membership_ids):
    """Активные членства ученика (id, group_id, is_individual), опц. по списку id."""
    from django.db.models import F
    from apps.memberships.models import GroupMembership
    qs = GroupMembership.objects.filter(student_id=student_id, active=True)
    if membership_ids is not None:
        qs = qs.filter(id__in=membership_ids)
    return list(qs.values('id', 'group_id', is_individual=F('group__is_individual')))


def _active_individual_group_ids(student_id: int):
    """group_id всех АКТИВНЫХ индивидуальных курсов ученика (не ограничено выбором
    в мастере). Заморозка двигает расписание ВСЕХ индив-курсов разом — ученик уходит
    на паузу целиком, поэтому выбор membership_ids к индивидуальным курсам не
    применяется (в отличие от групповых, где выбор решает, из каких групп убрать)."""
    from apps.memberships.models import GroupMembership
    return list(GroupMembership.objects
                .filter(student_id=student_id, active=True, group__is_individual=True)
                .values_list('group_id', flat=True))


@transaction.atomic
def change_student_status(
    student_id: int,
    new_status: str,
    *,
    frozen_from=None,
    frozen_until=None,
    membership_ids=None,
    actor=None,
) -> bool:
    """Единая смена статуса ученика с каскадом (одна транзакция). Возвращает False,
    если ученика нет. Права/валидация — на уровне view/serializer.

    frozen: индив-членства → сдвиг хвоста (frozen_from..frozen_until), групповые →
    active=False; статус+даты проставляются; сделка → 'frozen' (engine.freeze_deal).
    declined: все выбранные членства → active=False, будущие pending отменяются;
    статус; сделка → 'lost' (engine.decline_deal).

    Разморозка (frozen→enrolled) через эту функцию ЗАПРЕЩЕНА (ValueError): она не
    перекладывает хвост расписания и не реактивирует членства — для выхода из
    заморозки есть resume_student() с полным каскадом."""
    from apps.memberships import repository as memberships_repo
    from apps.renewals import engine
    from apps.scheduling import repository as sched_repo
    from apps.students.models import Student

    student = Student.objects.filter(id=student_id).first()
    if student is None:
        return False

    if student.enrollment_status == 'frozen' and new_status == 'enrolled':
        raise ValueError('use resume_student() to un-freeze a student')

    memberships = _affected_memberships(student_id, membership_ids)

    from apps.extra_lessons import services as extra_lessons_services

    if new_status == 'frozen':
        # Групповой формат: убираем из выбранных групп (членство active=False).
        # Снятие членства = гейт доп.уроков: блок при назначенных, авто-удаление
        # pending (заморозка тоже снимает членство и не реактивирует его на resume).
        for m in memberships:
            if not m['is_individual']:
                extra_lessons_services.enforce_membership_cancellation(student_id, m['group_id'])
                memberships_repo.remove_membership(m['id'])
        # Индивидуальный формат: ученик ОСТАЁТСЯ в группе (членство активно) —
        # двигаем только расписание. Замораживаем ВСЕ активные индив-курсы ученика
        # разом (не только выбранные): ученик уходит на паузу целиком, поэтому на
        # разморозке все его активные индив-курсы = замороженные, без неоднозначности.
        for gid in _active_individual_group_ids(student_id):
            sched_repo.freeze_individual_group(
                gid, frozen_from=frozen_from, resume_date=frozen_until)
        student.enrollment_status = 'frozen'
        student.frozen_from = frozen_from
        student.frozen_until = frozen_until
        student.save(update_fields=['enrollment_status', 'frozen_from', 'frozen_until'])
        engine.freeze_deal(student_id, author_id=_actor_id(actor))

    elif new_status == 'declined':
        # Уход снимает членство во всех выбранных группах → по каждой
        # гейт доп.уроков: блок при назначенных (makeup_scheduled), авто-удаление
        # pending. makeup_done/burned не трогаются (факт + payroll). Гейт ДО
        # remove_membership, чтобы блок откатил всю смену статуса (одна транзакция).
        for m in memberships:
            extra_lessons_services.enforce_membership_cancellation(student_id, m['group_id'])
            if m['is_individual']:
                sched_repo.cancel_future_planned(m['group_id'])
            memberships_repo.remove_membership(m['id'])
        student.enrollment_status = 'declined'
        student.frozen_from = None
        student.frozen_until = None
        student.save(update_fields=['enrollment_status', 'frozen_from', 'frozen_until'])
        engine.decline_deal(student_id, author_id=_actor_id(actor))

    elif new_status == 'enrolled':
        # Прямой возврат без каскада расписания (для выхода из заморозки — resume_student).
        student.enrollment_status = 'enrolled'
        student.frozen_from = None
        student.frozen_until = None
        student.save(update_fields=['enrollment_status', 'frozen_from', 'frozen_until'])

    else:
        # Раньше здесь был безусловный else → enrolled: неизвестный статус (и, до
        # миграции 0015, удалённый 'not_enrolled') молча зачислял ученика обратно.
        # На API это закрыто ChoiceField, но сервис зовут и напрямую — падаем явно.
        raise ValueError(f'unknown enrollment status: {new_status!r}')

    return True


@transaction.atomic
def resume_student(student_id: int, *, actual_resume_date, actor=None) -> bool:
    """Выход из заморозки (плановый/досрочный). Заново перекладывает хвост всех
    активных индив-курсов от actual_resume_date, возвращает статус в enrolled, а
    сделку — на расчётную авто-стадию (engine.resume_from_freeze). False, если
    ученика нет / не заморожен."""
    from apps.memberships.models import GroupMembership
    from apps.renewals import engine
    from apps.scheduling import repository as sched_repo
    from apps.students.models import Student

    # Нормализуем тип actual_resume_date
    if isinstance(actual_resume_date, str):
        from datetime import datetime
        actual_resume_date = datetime.strptime(actual_resume_date, '%Y-%m-%d').date()

    student = Student.objects.filter(id=student_id).first()
    if student is None or student.enrollment_status != 'frozen':
        return False
    frozen_from = student.frozen_from

    # Индив-членства при заморозке НЕ деактивируются — ученик остаётся в группе,
    # двигается только расписание (исходное требование: индивид остаётся в группе).
    # Заморозка сдвигает хвост ВСЕХ активных индив-курсов разом, поэтому здесь
    # перекладываем обратно ровно этот же набор — все активные индив-курсы. Флаг
    # active тут не сигнал «что заморожено» (индив всегда остаются active): все
    # активные индив-курсы замороженного ученика и есть замороженные. Реактивация
    # не нужна — членства не покидали группу.
    indiv = list(GroupMembership.objects
                 .filter(student_id=student_id, group__is_individual=True, active=True)
                 .values('group_id'))
    for m in indiv:
        sched_repo.resume_individual_group(
            m['group_id'], actual_resume_date=actual_resume_date, frozen_from=frozen_from)

    student.enrollment_status = 'enrolled'
    student.frozen_from = None
    student.frozen_until = None
    student.save(update_fields=['enrollment_status', 'frozen_from', 'frozen_until'])
    engine.resume_from_freeze(student_id, author_id=_actor_id(actor))
    return True


def preview_freeze_schedule(membership_ids: list[int], *, frozen_from, frozen_until) -> dict:
    """Для каждого индив-членства из membership_ids — дран-превью сдвига расписания
    (apps.scheduling.repository.preview_freeze). Групповые membership_ids игнорируются
    (превью только для индивидуальных — у групповых расписание не сдвигается).

    active=True — та же область, что и у реальной заморозки (_affected_memberships
    тоже берёт только активные): неактивное членство заморозка вообще не тронет,
    так что превью не должно предсказывать сдвиг для того, чего не произойдёт.

    Read-only: ничего не пишет в БД. Ключ результата — id членства; значение —
    {'lesson_on_frozen_from': bool, 'first_lesson_after_resume': date|None,
    'affected': list[dict]} — 'affected' (repository.preview_affected) — разовые
    операции (переносы/замены/отмены) внутри [frozen_from, frozen_until], которые
    freeze_individual_group сбросит при реальной заморозке (см. wipe_one_offs)."""
    from apps.memberships.models import GroupMembership
    from apps.scheduling import repository as sched_repo

    result = {}
    memberships = (GroupMembership.objects
                   .filter(id__in=membership_ids, group__is_individual=True, active=True)
                   .values('id', 'group_id'))
    for m in memberships:
        preview = sched_repo.preview_freeze(
            m['group_id'], frozen_from=frozen_from, frozen_until=frozen_until)
        preview['affected'] = sched_repo.preview_affected(
            m['group_id'], date_from=frozen_from, date_to=frozen_until)
        result[m['id']] = preview
    return result


def _actor_id(actor) -> Optional[int]:
    """Account.id из actor (request.user) или None."""
    return getattr(actor, 'id', None)


@transaction.atomic
def set_student_manager(student_id: int, manager_id: Optional[int], *, actor=None) -> Optional[dict]:
    """
    Сменить ответственного менеджера ученика и синхронно переписать assignee
    АКТИВНОЙ (открытой) сделки продления этого ученика — единый источник правды
    вместо независимого назначения на сделке. Закрытые (won/lost) сделки
    сохраняют своего исторического ответственного и не трогаются. Возвращает
    None, если ученика нет; ValueError, если manager_id указывает на
    неподходящую учётку (не manager/admin/superadmin или неактивна).

    actor принят для единообразия сигнатуры с change_student_status/resume_student
    и на будущее (например, если появится RenewalActivity для смены менеджера), но
    пока не используется — атрибуция pghistory для этого изменения уже берётся из
    контекста middleware запроса, не из этого параметра.
    """
    from apps.accounts.models import Account
    from apps.renewals.models import RenewalDeal
    from apps.students.models import Student

    student = Student.objects.filter(id=student_id).first()
    if student is None:
        return None

    if manager_id is not None:
        # Тот же критерий, что apps.renewals.services.list_assignees() —
        # кандидат в ответственные по сделкам продления.
        is_eligible = Account.objects.filter(
            id=manager_id, role__in=['manager', 'admin', 'superadmin'], is_active=True,
        ).exists()
        if not is_eligible:
            raise ValueError('manager account not found or not eligible')

    student.manager_id = manager_id
    student.save(update_fields=['manager'])
    RenewalDeal.objects.filter(
        student_id=student_id, outcome_at__isnull=True,
    ).update(assignee_id=manager_id)

    return repository.get_student(student_id)
