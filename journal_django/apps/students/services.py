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


def soft_delete_student(student_id: int) -> bool:
    """Мягкое удаление (enrollment_status='not_enrolled'). Возвращает False если не найден."""
    return repository.soft_delete_student(student_id)


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
    not_enrolled: как declined по членствам, но сделку не трогаем.

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

    if new_status == 'frozen':
        for m in memberships:
            if m['is_individual']:
                sched_repo.freeze_individual_group(
                    m['group_id'], frozen_from=frozen_from, resume_date=frozen_until)
            memberships_repo.remove_membership(m['id'])
        student.enrollment_status = 'frozen'
        student.frozen_from = frozen_from
        student.frozen_until = frozen_until
        student.save(update_fields=['enrollment_status', 'frozen_from', 'frozen_until'])
        engine.freeze_deal(student_id, author_id=_actor_id(actor))

    elif new_status in ('declined', 'not_enrolled'):
        for m in memberships:
            if m['is_individual']:
                sched_repo.cancel_future_planned(m['group_id'])
            memberships_repo.remove_membership(m['id'])
        student.enrollment_status = new_status
        student.frozen_from = None
        student.frozen_until = None
        student.save(update_fields=['enrollment_status', 'frozen_from', 'frozen_until'])
        if new_status == 'declined':
            engine.decline_deal(student_id, author_id=_actor_id(actor))

    else:  # enrolled — прямой возврат без каскада расписания (используйте resume_student)
        student.enrollment_status = 'enrolled'
        student.frozen_from = None
        student.frozen_until = None
        student.save(update_fields=['enrollment_status', 'frozen_from', 'frozen_until'])

    return True


@transaction.atomic
def resume_student(student_id: int, *, actual_resume_date, actor=None) -> bool:
    """Выход из заморозки (плановый/досрочный). Заново перекладывает индив-хвост от
    actual_resume_date, возвращает статус в enrolled, а сделку — на расчётную
    авто-стадию (engine.resume_from_freeze). False, если ученика нет / не заморожен.

    Реактивируется только то индив-членство, чей хвост реально переложился
    (resume_individual_group вернул >0) — так «давно завершённый курс» не
    воскресает. Известное ограничение: если у группы нет открытого слота
    (рассинхрон данных, не штатный путь), хвост не переложится и membership
    не реактивируется, даже если pending-уроки формально есть."""
    from apps.memberships import repository as memberships_repo
    from apps.memberships.models import GroupMembership
    from apps.renewals import engine
    from apps.scheduling import repository as sched_repo
    from apps.students.models import Student

    student = Student.objects.filter(id=student_id).first()
    if student is None or student.enrollment_status != 'frozen':
        return False
    frozen_from = student.frozen_from

    # Индив-членства были деактивированы при заморозке (change_student_status) —
    # берём все, где группа индивидуальная, перекладываем хвост от фактической
    # даты и реактивируем сами членства (это личный курс ученика, а не общий
    # класс, куда его пере-записывают вручную — групповые НЕ реактивируем, см.
    # спеку student-status-lifecycle).
    #
    # ВАЖНО: берём ТОЛЬКО неактивные (active=False) индив-членства. Заморозка
    # (change_student_status 'frozen') всегда деактивирует то, что реально трогает
    # (remove_membership для каждого выбранного членства), а wizard позволяет
    # заморозить лишь ПОДМНОЖЕСТВО членств (per-membership чекбоксы). Значит
    # членство, оставшееся active=True, в этой заморозке НЕ участвовало — его курс
    # идёт своим чередом, и разморозка не имеет права ни отменять его будущие extra
    # (шаг «а» freeze_individual_group), ни перекладывать его хвост (шаг «б»). Без
    # active=False resume_student испортил бы расписание постороннего, параллельно
    # активного индив-курса.
    #
    # Среди active=False групп ещё остаётся давно-завершённый курс (active=False по
    # окончанию, а не по этой заморозке). Его отсекает не фильтр, а условие relaid>0
    # ниже: у завершённого курса хвоста в окне нет (все done / нет строк) →
    # resume_individual_group вернёт 0 → членство не воскрешаем.
    indiv = list(GroupMembership.objects
                 .filter(student_id=student_id, group__is_individual=True, active=False)
                 .values('id', 'group_id'))
    to_reactivate = []
    for m in indiv:
        relaid = sched_repo.resume_individual_group(
            m['group_id'], actual_resume_date=actual_resume_date, frozen_from=frozen_from)
        if relaid:
            to_reactivate.append(m['id'])
    memberships_repo.reactivate_memberships(to_reactivate)

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
    {'lesson_on_frozen_from': bool, 'first_lesson_after_resume': date|None}."""
    from apps.memberships.models import GroupMembership
    from apps.scheduling import repository as sched_repo

    result = {}
    memberships = (GroupMembership.objects
                   .filter(id__in=membership_ids, group__is_individual=True, active=True)
                   .values('id', 'group_id'))
    for m in memberships:
        result[m['id']] = sched_repo.preview_freeze(
            m['group_id'], frozen_from=frozen_from, frozen_until=frozen_until)
    return result


def _actor_id(actor) -> Optional[int]:
    """Account.id из actor (request.user) или None."""
    return getattr(actor, 'id', None)
