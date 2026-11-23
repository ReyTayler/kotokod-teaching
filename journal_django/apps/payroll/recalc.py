"""
Пересчёт начислений «Мотивации» поверх БД (спека
docs/superpowers/specs/2026-11-18-motivation-individual-design.md, §3).

Правила — в apps/payroll/engine.py; здесь только сбор входов и запись результата:
версии, персональные ставки, уроки (присутствие одним агрегатом) и маркеры отмен
грузятся фиксированным числом запросов, запись — bulk_create/bulk_update только
реально изменившихся строк. Число запросов не зависит от числа уроков.

Охват «Мотивации» — индивидуальные и групповые занятия на даты с соответствующей
версией ставок. Уроки до первой версии пересчёт не трогает: их начисление пишет
прежний движок в местах записи урока. Урок,
который «Мотивация» считала, а теперь нет (удалена версия, начатая сегодня;
группе сменили формат), возвращается к сумме прежнего движка
(engine.legacy_lesson_pay).

Отмена платится только у индива и только с записью о причине: compensated=False —
0 «Без компенсации: …», compensated=True — сумма «Мотивации» с причиной. Маркер
без записи (отмены до фичи, групповые форматы) — без начисления, как раньше.
Запись идёт за начислением: к маркеру привязывается запись той же отмены, чьё
начисление-сирота привязалось к нему (cancellations.repository.bind_for_markers).

Порядок блокировок внутри пересчёта — «урок → план → записи отмен → деньги» (как
у scheduling.repository.cancel_lesson: сначала строки плана, затем зависимые):
уроки охвата по id, затем маркеры по id, затем записи об отменах
(cancellations.repository.lock_for_markers), затем Payroll по lesson_id и
CancellationPay по id. Два параллельных пересчёта поэтому не встают в дедлок
друг с другом; лок урока до чтения агрегата присутствия защищает от расчёта по
устаревшей посещаемости и от двойного bulk_create одного начисления. Удаление
урока (lessons.repository.delete_lesson_full, extra_lessons.services.delete_fact)
и правки посещаемости лочат урок раньше его Payroll — тот же порядок.

Операции расписания (scheduling.repository: отмена, замена, перенос, reset_plan,
wipe_one_offs) лочат строки плана ПЕРВЫМИ, поэтому полный recalculate из них
звать нельзя: он полез бы лочить уроки после плана, а параллельный пересчёт по
смене ставок лочит уроки до плана — дедлок. Им — recalculate_cancellations:
уроки он не лочит и не читает, только маркеры → деньги. Удаление маркеров
Django-коллектором обнуляет ссылку в payroll_cancellations (UPDATE … SET
planned_lesson_id = NULL) раньше DELETE плана, то есть «деньги → план»; поэтому
перед удалением маркеров scheduling лочит удаляемые строки плана сам.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import Coalesce

from apps.core.utils.dates import msk_now
from apps.payroll.engine import (
    LessonInput,
    MarkerInput,
    PersonalRateInput,
    RateCard,
    cancellation_pay,
    governs,
    legacy_lesson_pay,
    lesson_pay,
    rates_on,
)
from apps.payroll.group_engine import GroupRateCard, group_lesson_pay, group_snapshot

__all__ = ['load_rate_cards', 'recalculate', 'recalculate_cancellations', 'recalculate_lesson']

_CANCELLED = 'cancelled'
_BATCH = 500

_PAYROLL_FIELDS = ['teacher_id', 'total_students', 'present_count', 'payment', 'penalty',
                   'calc_payment', 'calc_penalty', 'rule_note', 'is_manual', 'group_rate_snapshot']
_CANCEL_FIELDS = ['planned_lesson_id', 'teacher_id', 'group_id', 'lesson_date',
                  'scheduled_time', 'payment', 'calc_payment', 'rule_note', 'is_manual']


def _keeps_manual(current, teacher_id: int) -> bool:
    """Сохраняется ли ручная правка начисления при пересчёте.

    Ручная сумма — договорённость с конкретным человеком. Сменился получатель
    (преподаватель урока поправлен PATCH-ем, на отменённое занятие поставили
    замену, сирота привязалась к маркеру другого преподавателя) — сумма прежнего
    к новому не переходит: правка снимается, начисление становится расчётным."""
    return current.is_manual and current.teacher_id == teacher_id


def load_rate_cards() -> list[RateCard]:
    """Все версии ставок со ставками направлений — два запроса на весь пересчёт."""
    from apps.payroll.models import PayRateVersion
    return [RateCard.from_version(v)
            for v in PayRateVersion.objects.prefetch_related('directions')]


def _load_personal(group_ids: set[int]) -> dict[int, list[PersonalRateInput]]:
    """Периоды персональных ставок групп пересчёта одним запросом, по группам.

    Все периоды, включая закрытые и периоды выключенных/удалённых ставок: какой
    действует на дату занятия, решает движок (PersonalRateInput.covers) — так
    прошлое считается по тем параметрам, что действовали тогда (поправка §8)."""
    from apps.payroll.models import PersonalRateTerm
    by_group: dict[int, list[PersonalRateInput]] = {}
    if not group_ids:
        return by_group
    for row in PersonalRateTerm.objects.filter(group_id__in=group_ids).values(
            'teacher_id', 'group_id', 'lesson_from', 'lesson_to', 'kind', 'value',
            'valid_from', 'valid_until'):
        by_group.setdefault(row['group_id'], []).append(PersonalRateInput(**row))
    return by_group


def _marker_qs():
    """Единственное определение «маркера отмены» для привязки начислений (и, через
    них, записей об отменах): строка плана seq IS NULL, status='cancelled', и есть
    кому платить — замена или преподаватель. Маркер без преподавателя не в счёт:
    он не привяжет сироту никогда (teacher у начисления NOT NULL)."""
    from apps.scheduling.models import PlannedLesson
    return PlannedLesson.objects.filter(
        Q(substitute_teacher_id__isnull=False) | Q(teacher_id__isnull=False),
        status=_CANCELLED, seq__isnull=True)


def _markers():
    """Маркеры отмен с эффективным преподавателем: замена, если поставлена (её
    ставят и на уже отменённое занятие), иначе teacher."""
    return _marker_qs().annotate(eff_teacher_id=Coalesce('substitute_teacher_id',
                                                         'teacher_id'))


def _scope(qs, *, group_ids, date_field, date_from, date_to):
    if group_ids is not None:
        qs = qs.filter(group_id__in=list(group_ids))
    if date_from is not None:
        qs = qs.filter(**{f'{date_field}__gte': date_from})
    if date_to is not None:
        qs = qs.filter(**{f'{date_field}__lte': date_to})
    return qs


def _diff(obj, values: dict) -> bool:
    """Записывает в obj отличающиеся значения; True — если что-то поменялось."""
    changed = False
    for name, value in values.items():
        if getattr(obj, name) != value:
            setattr(obj, name, value)
            changed = True
    return changed


def _lock_lessons(lesson_qs) -> list[int]:
    # Отдельным запросом: агрегат с GROUP BY под FOR UPDATE не лочится.
    # of=('self',): фильтр охвата (_motivation_lessons) джойнит группу и
    # начисление — лочим только строки уроков (и FOR UPDATE не ложится на
    # nullable-сторону LEFT JOIN).
    return list(lesson_qs.select_for_update(of=('self',)).order_by('id')
                .values_list('id', flat=True))


def _motivation_lessons(qs):
    """Индив, групповые уроки с первой групповой версии и уже посчитанные
    «Мотивацией» уроки для возможного возврата к прежнему расчёту."""
    from apps.payroll.models import GroupPayRateVersion
    first = GroupPayRateVersion.objects.order_by('effective_from').values('effective_from')[:1]
    return qs.filter(Q(group__is_individual=True) | (
        Q(group__is_individual=False, lesson_date__gte=first)) | (
        Q(payroll__isnull=False) & ~Q(payroll__rule_note='')))


def _lesson_rows(lesson_ids: list[int]) -> list[dict]:
    """Уроки с группой, источником и присутствием — один запрос с агрегатом.
    Читается ПОСЛЕ лока уроков: посещаемость уже не поменяется под нами."""
    from apps.lessons.models import Lesson
    if not lesson_ids:
        return []
    return list(
        Lesson.objects.filter(id__in=lesson_ids).values(
            'id', 'teacher_id', 'group_id', 'lesson_date', 'lesson_number', 'lesson_type',
            'lesson_duration_minutes', 'submitted_at', 'submitted_by_token',
            'group__is_individual', 'group__direction_id', 'group__direction__name',
        ).annotate(
            # Headcount (правило 2026-09-28): unpaid_skip — ученика на уроке как будто
            # нет (вне total и вне present); is_free оплачивается как присутствие.
            total=Count('attendance', filter=Q(attendance__unpaid_skip=False)),
            present=Count('attendance', filter=Q(attendance__unpaid_skip=False,
                                                 attendance__present=True)),
        ).order_by('id')
    )


def _lock_markers(marker_qs) -> list[dict]:
    # of=('self',): лочим только строки плана, не группы/направления из JOIN.
    return list(
        marker_qs.select_for_update(of=('self',)).order_by('id').values(
            'id', 'eff_teacher_id', 'group_id', 'scheduled_date', 'scheduled_time',
            'group__is_individual', 'group__direction_id', 'group__direction__name',
        )
    )


def _recalc_lessons(rows, cards, personal_by_group, group_cards=()) -> dict:
    from apps.payroll.models import Payroll

    # Лок существующих строк: ручная правка (PATCH) между чтением и записью
    # иначе была бы тихо затёрта расчётом.
    existing = {
        p.lesson_id: p
        for p in Payroll.objects.select_for_update()
        .filter(lesson_id__in=[r['id'] for r in rows]).order_by('lesson_id')
    }

    to_create, to_update = [], []
    for row in rows:
        lesson = LessonInput(
            teacher_id=row['teacher_id'], group_id=row['group_id'],
            lesson_date=row['lesson_date'], lesson_number=row['lesson_number'],
            is_individual=row['group__is_individual'],
            direction_id=row['group__direction_id'],
            direction_name=row['group__direction__name'],
            submitted_at=row['submitted_at'], submitted_by_token=row['submitted_by_token'],
            present_count=row['present'], total_students=row['total'],
            lesson_type=row['lesson_type'], duration_minutes=row['lesson_duration_minutes'],
        )
        current = existing.get(row['id'])
        card = rates_on(cards, lesson.lesson_date)
        group_card = rates_on(group_cards, lesson.lesson_date) if not lesson.is_individual else None
        snapshot = {}
        if governs(lesson.is_individual, card):
            res = lesson_pay(lesson, card, personal_by_group.get(lesson.group_id, ()))
        elif group_card is not None:
            res = group_lesson_pay(lesson, group_card)
            snapshot = group_snapshot(lesson, group_card)
        elif current is not None and current.rule_note:
            # Был под «Мотивацией», теперь нет — обратно к прежнему движку.
            # Ручная правка относилась к расчёту «Мотивации» и снимается.
            res = legacy_lesson_pay(lesson)
            if _diff(current, {
                'teacher_id': lesson.teacher_id,
                'total_students': row['total'], 'present_count': row['present'],
                'payment': res.payment, 'penalty': res.penalty,
                'calc_payment': res.payment, 'calc_penalty': res.penalty,
                'rule_note': '', 'is_manual': False, 'group_rate_snapshot': {},
            }):
                to_update.append(current)
            continue
        else:
            # Групповой формат или дата без версии: начисление прежнего движка
            # пишет место записи урока — пересчёт его не трогает.
            continue
        values = {
            'teacher_id': lesson.teacher_id,
            'total_students': row['total'], 'present_count': row['present'],
            'calc_payment': res.payment, 'calc_penalty': res.penalty,
            'rule_note': res.rule_note,
            'group_rate_snapshot': snapshot,
        }
        if current is None:
            to_create.append(Payroll(lesson_id=row['id'], payment=res.payment,
                                     penalty=res.penalty, is_manual=False, **values))
            continue
        # Ручная правка (§1.9) хранит свои payment/penalty; остальным — расчёт.
        # Проверка до записи teacher_id в current: сравниваем прежнего получателя.
        values['is_manual'] = _keeps_manual(current, lesson.teacher_id)
        if not values['is_manual']:
            values['payment'] = res.payment
            values['penalty'] = res.penalty
        if _diff(current, values):
            to_update.append(current)

    Payroll.objects.bulk_create(to_create, batch_size=_BATCH)
    Payroll.objects.bulk_update(to_update, _PAYROLL_FIELDS, batch_size=_BATCH)
    return {'created': len(to_create), 'updated': len(to_update)}


def _recalc_cancellations(marker_rows, orphan_scope, cards, personal_by_group,
                          today: datetime.date, records: list) -> dict:
    """Начисления маркеров охвата + сироты (маркер удалён) в orphan_scope.

    orphan_scope — queryset CancellationPay без маркера или None (сирот не трогаем).
    records — записи об отменах, уже залоченные (cancellations.repository.
    lock_for_markers); к маркерам они привязываются здесь, вслед за начислениями."""
    from apps.payroll.models import CancellationPay

    pays_filter = Q(planned_lesson_id__in=[r['id'] for r in marker_rows])
    if orphan_scope is not None:
        pays_filter |= Q(id__in=orphan_scope.values('id'))
    pays = list(
        CancellationPay.objects.select_for_update(of=('self',)).filter(pays_filter)
        .annotate(
            # Маркер с тем же ключом вне охвата пересчёта: сироту не удаляем — её
            # привяжет к нему пересчёт, который этот маркер затронет. Маркер без
            # преподавателя не в счёт: он не привяжет никогда, сирота жила бы вечно.
            has_marker=Exists(_marker_qs().filter(
                group_id=OuterRef('group_id'), scheduled_date=OuterRef('lesson_date'),
                scheduled_time=OuterRef('scheduled_time'))),
        ).order_by('id')
    )
    linked = {p.planned_lesson_id: p for p in pays if p.planned_lesson_id is not None}
    # Сироты по естественному ключу; при дублях ключа старшая строка первой.
    orphans: dict[tuple, list] = {}
    for p in pays:
        if p.planned_lesson_id is None:
            orphans.setdefault((p.group_id, p.lesson_date, p.scheduled_time), []).append(p)

    # Начисление каждого маркера: своё; иначе сирота с тем же ключом — привязка
    # сохраняет её ручную правку (§2): маркер пересоздан, а отмена та же. Если у
    # нового маркера другой преподаватель, правку снимет _keeps_manual.
    current_by_marker: dict[int, object] = {}
    unbound: list[dict] = []
    scope_keys = set()
    for row in marker_rows:
        key = (row['group_id'], row['scheduled_date'], row['scheduled_time'])
        scope_keys.add(key)
        current = linked.get(row['id'])
        if current is None:
            bucket = orphans.get(key)
            current = bucket.pop(0) if bucket else None
        if current is None:
            unbound.append(row)
        else:
            current_by_marker[row['id']] = current
    _bind_by_day(unbound, orphans, current_by_marker)

    # Решение об отмене — по записи, идущей за начислением: сирота-начисление,
    # привязавшаяся к маркеру, ведёт за собой запись со своим ИСХОДНЫМ ключом
    # (ключ читается до _diff, который перепишет его на ключ маркера).
    decisions: dict = {}
    if marker_rows:
        from apps.cancellations.repository import bind_for_markers
        follow = {mid: (p.group_id, p.lesson_date, p.scheduled_time)
                  for mid, p in current_by_marker.items() if p.planned_lesson_id != mid}
        decisions = bind_for_markers(marker_rows, records, follow)

    to_create, to_update, to_drop = [], [], []
    for row in marker_rows:
        marker = MarkerInput(
            teacher_id=row['eff_teacher_id'], group_id=row['group_id'],
            scheduled_date=row['scheduled_date'],
            is_individual=row['group__is_individual'],
            direction_id=row['group__direction_id'],
            direction_name=row['group__direction__name'],
            decision=decisions.get(row['id']),
        )
        current = current_by_marker.get(row['id'])
        card = rates_on(cards, marker.scheduled_date)
        if marker.decision is None or not governs(marker.is_individual, card):
            # Отмена без записи о причине, групповой формат или дата без версии —
            # прежний движок за отмену не платил. Начисление, оставшееся от
            # «Мотивации» (удалена версия, начатая сегодня), убираем, только если
            # отмена не в прошлом: выплаченный месяц не меняется.
            if current is not None and current.lesson_date >= today:
                to_drop.append(current.id)
            continue
        res = cancellation_pay(marker, card, personal_by_group.get(marker.group_id, ()))
        values = {
            'planned_lesson_id': row['id'],
            'teacher_id': marker.teacher_id, 'group_id': marker.group_id,
            'lesson_date': marker.scheduled_date, 'scheduled_time': row['scheduled_time'],
            'calc_payment': res.payment, 'rule_note': res.rule_note,
        }
        if current is None:
            to_create.append(CancellationPay(payment=res.payment, is_manual=False, **values))
            continue
        values['is_manual'] = _keeps_manual(current, marker.teacher_id)
        if not values['is_manual']:
            values['payment'] = res.payment
        if _diff(current, values):
            to_update.append(current)

    # Будущей отмены больше нет — начисление убираем; прошлую сироту не трогаем:
    # выплаченный месяц не должен меняться задним числом. Лишние сироты ключа,
    # чей маркер в охвате (уже привязан к одной из них), — тоже под удаление.
    stale = [
        p.id for key, bucket in orphans.items() for p in bucket
        if p.lesson_date >= today and (key in scope_keys or not p.has_marker)
    ] + to_drop
    deleted = 0
    if stale:
        deleted, _ = CancellationPay.objects.filter(id__in=stale).delete()

    CancellationPay.objects.bulk_create(to_create, batch_size=_BATCH)
    CancellationPay.objects.bulk_update(to_update, _CANCEL_FIELDS, batch_size=_BATCH)
    return {'created': len(to_create), 'updated': len(to_update), 'deleted': deleted}


def _bind_by_day(unbound: list[dict], orphans: dict[tuple, list], current_by_marker: dict) -> None:
    """Запасная привязка сироты к маркеру по (группа, дата), когда время отмены
    сменилось (мягкое обновление: в старой системе перенесли время отменённого
    занятия). Без неё прошлая сирота осталась бы рядом с новым начислением —
    двойная оплата одной отмены. Только однозначный случай: в группе на дату ровно
    один маркер отмены БЕЗ своего начисления и ровно одна свободная сирота. Маркеры
    считаются по всей БД, не по охвату: точечный пересчёт одного маркера иначе не
    увидел бы второго такого же в этом дне. Маркер со своим начислением (в БД или
    привязанным в этом проходе) — не конкурент: в дне с двумя слотами перенос одной
    отмены не должен оставлять её сироту без пары. Сирота, чей маркер с тем же
    ключом есть вне охвата (has_marker), не кандидат — её привяжет он."""
    from apps.payroll.models import CancellationPay
    markers_by_day: dict[tuple, list[dict]] = {}
    for row in unbound:
        markers_by_day.setdefault((row['group_id'], row['scheduled_date']), []).append(row)
    orphans_by_day: dict[tuple, list[tuple]] = {}
    for key, bucket in orphans.items():
        for p in bucket:
            orphans_by_day.setdefault(key[:2], []).append((key, p))
    days = [
        day_key for day_key, rows in markers_by_day.items()
        if len(rows) == 1 and len(orphans_by_day.get(day_key, [])) == 1
        and not orphans_by_day[day_key][0][1].has_marker
    ]
    if not days:
        return
    # Маркеры этих дней без своего начисления во всей БД — один запрос по
    # planned_lessons_group_date_idx; уже получившие начисление в этом проходе
    # (по FK или ключу) исключаются явно — в БД ссылка появится только при записи.
    per_day = {
        (g, d): n for g, d, n in _marker_qs()
        .filter(group_id__in={g for g, _ in days}, scheduled_date__in={d for _, d in days})
        .exclude(Exists(CancellationPay.objects.filter(planned_lesson_id=OuterRef('pk'))))
        .exclude(id__in=list(current_by_marker))
        .values('group_id', 'scheduled_date').annotate(n=Count('id'))
        .values_list('group_id', 'scheduled_date', 'n')
    }
    for day_key in days:
        if per_day.get(day_key) != 1:
            continue
        rows = markers_by_day[day_key]
        key, orphan = orphans_by_day[day_key][0]
        orphans[key].remove(orphan)
        current_by_marker[rows[0]['id']] = orphan


def recalculate(*, lesson_ids=None, marker_ids=None, group_ids=None,
                date_from: datetime.date | None = None,
                date_to: datetime.date | None = None,
                today: datetime.date | None = None) -> dict:
    """
    Пересчитать начисления за уроки и отмены. Фильтры комбинируются через AND;
    без фильтров — вся история.

    Охват:
      * только lesson_ids — пересчитываются эти уроки, начисления маркеров не трогаются;
      * только marker_ids — эти маркеры, уроки не трогаются;
      * group_ids / date_from / date_to сужают оба множества (даты: lesson_date
        урока, scheduled_date маркера, lesson_date начисления-сироты).
    Сироты отмен (маркер удалён) с датой ≥ сегодня (МСК) удаляются в группах
    охвата при любом пересчёте: group_ids, а при lesson_ids/marker_ids — группы
    этих строк; в пределах date_from/date_to. Прошлые сироты не трогаются.

    today — «сегодня» по МСК вызывающей операции (мутации ставок читают его один
    раз под своим локом): граница «прошлые / будущие сироты» тогда совпадает с
    границей самой операции и через полночь не расходится. None — msk_now().

    Возвращает {'lessons', 'cancellations', 'created', 'updated', 'deleted',
    'changed'}: lessons/cancellations — сколько уроков и маркеров рассмотрено;
    created/updated/deleted — строк Payroll + CancellationPay; changed — их сумма.
    """
    return _run(
        lesson_ids=lesson_ids, marker_ids=marker_ids, group_ids=group_ids,
        date_from=date_from, date_to=date_to, today=today,
        with_lessons=not (lesson_ids is None and marker_ids is not None),
        with_markers=not (marker_ids is None and lesson_ids is not None),
    )


def recalculate_cancellations(*, marker_ids=None, group_ids=None,
                              date_from: datetime.date | None = None,
                              date_to: datetime.date | None = None,
                              from_today: bool = False) -> dict:
    """
    Пересчитать только начисления за отмены — для операций расписания, которые
    уже держат строки плана (см. шапку модуля). Уроки не лочатся и не читаются.

    Охват и сироты — как у recalculate с теми же фильтрами без lesson_ids:
    marker_ids — эти маркеры (будущие сироты — в их группах); group_ids /
    date_from / date_to — маркеры и сироты групп за период. Будущие сироты
    охвата удаляются, прошлые остаются. Ответ — как у recalculate (lessons = 0).

    from_today=True — охват с сегодняшнего дня по МСК (вместо date_from): то же
    «сегодня», по которому пересчёт делит сирот на прошлые и будущие, — иначе на
    границе суток два вызова часов разошлись бы (после удаления маркеров).
    """
    return _run(lesson_ids=None, marker_ids=marker_ids, group_ids=group_ids,
                date_from=date_from, date_to=date_to, from_today=from_today,
                with_lessons=False, with_markers=True)


def recalculate_group_rates(*, date_from, date_to=None, today=None):
    """Изменение групповых ставок не затрагивает индив и начисления отмен."""
    return _run(lesson_ids=None, marker_ids=None, group_ids=None,
                date_from=date_from, date_to=date_to, today=today,
                with_lessons=True, with_markers=False, only_groups=True)


def _run(*, lesson_ids, marker_ids, group_ids, date_from, date_to,
         with_lessons: bool, with_markers: bool, from_today: bool = False,
         today: datetime.date | None = None, only_groups: bool = False) -> dict:
    from apps.lessons.models import Lesson
    from apps.payroll.models import CancellationPay

    by_ids = lesson_ids is not None or marker_ids is not None
    # Одно «сегодня» на весь пересчёт: иначе на границе суток выборка сирот и
    # их удаление разошлись бы.
    if today is None:
        today = msk_now().date()
    if from_today:
        date_from = today

    with transaction.atomic():
        # 1. Уроки охвата (лок по id), затем агрегат присутствия.
        lesson_rows: list[dict] = []
        if with_lessons:
            lesson_qs = _scope(_motivation_lessons(Lesson.objects.all()), group_ids=group_ids,
                               date_field='lesson_date', date_from=date_from, date_to=date_to)
            if only_groups:
                lesson_qs = lesson_qs.filter(group__is_individual=False)
            if lesson_ids is not None:
                lesson_qs = lesson_qs.filter(id__in=list(lesson_ids))
            lesson_rows = _lesson_rows(_lock_lessons(lesson_qs))

        # 2. Маркеры охвата (лок по id).
        marker_rows: list[dict] = []
        if with_markers:
            marker_qs = _scope(
                _markers(), group_ids=group_ids, date_field='scheduled_date',
                date_from=date_from, date_to=date_to)
            if marker_ids is not None:
                marker_qs = marker_qs.filter(id__in=list(marker_ids))
            marker_rows = _lock_markers(marker_qs)

        # 2a. Записи об отменах этих маркеров — лок после плана, до денег; привязка
        # к маркерам — позже, вслед за начислениями. Локальный импорт: cancellations
        # сам ссылается на scheduling.
        records: list = []
        if marker_rows:
            from apps.cancellations.repository import lock_for_markers
            records = lock_for_markers(marker_rows)

        # Сироты — в группах охвата. При точечном пересчёте это группы
        # затронутых строк: удаление маркера (reset_plan) иначе оставило бы
        # будущую сироту до ближайшего полного пересчёта.
        touched = {r['group_id'] for r in lesson_rows} | {r['group_id'] for r in marker_rows}
        # Начисления за отмену бывают только у индива: сирот групповых уроков
        # нет, и точечный пересчёт группового урока (запись, посещаемость,
        # PATCH) не лочит и не сканирует CancellationPay зря.
        orphan_touched = ({r['group_id'] for r in lesson_rows if r['group__is_individual']}
                          | {r['group_id'] for r in marker_rows})
        orphan_groups = orphan_touched if by_ids else group_ids
        orphan_scope = None
        if not only_groups and (not by_ids or orphan_touched):
            orphan_scope = _scope(CancellationPay.objects.filter(planned_lesson__isnull=True),
                                  group_ids=orphan_groups, date_field='lesson_date',
                                  date_from=date_from, date_to=date_to)
            if not marker_rows:
                # Привязывать не к чему — нужны лишь будущие (кандидаты на удаление).
                orphan_scope = orphan_scope.filter(lesson_date__gte=today)

        stats = {'lessons': len(lesson_rows), 'cancellations': len(marker_rows),
                 'created': 0, 'updated': 0, 'deleted': 0}
        if not lesson_rows and not marker_rows and orphan_scope is None:
            # Вне охвата версий: ставки не грузим.
            stats['changed'] = 0
            return stats

        cards = load_rate_cards()
        from apps.payroll.models import GroupPayRateVersion
        group_cards = [GroupRateCard.from_version(v) for v in GroupPayRateVersion.objects.all()]
        personal_by_group = _load_personal(touched)

        # 3. Деньги: Payroll, затем CancellationPay.
        if lesson_rows:
            res = _recalc_lessons(lesson_rows, cards, personal_by_group, group_cards)
            stats['created'] += res['created']
            stats['updated'] += res['updated']
        if marker_rows or orphan_scope is not None:
            res = _recalc_cancellations(marker_rows, orphan_scope, cards, personal_by_group,
                                        today, records)
            stats['created'] += res['created']
            stats['updated'] += res['updated']
            stats['deleted'] += res['deleted']

    stats['changed'] = stats['created'] + stats['updated'] + stats['deleted']
    return stats


def _as_number(value) -> int | float:
    """Сумма для ответа места записи урока: прежний контракт — число (int),
    копейки «Мотивации» — float."""
    value = Decimal(value)
    return int(value) if value == value.to_integral_value() else float(value)


def recalculate_lesson(lesson_id: int, payment, penalty) -> tuple:
    """Точечный пересчёт только что записанного/поправленного урока — в
    транзакции места записи (после insert_payroll/правки посещаемости, урок уже
    залочен вызывающим). Урок «Мотивации» получает её начисление; урок прежнего
    движка не меняется.

    payment/penalty — суммы прежнего движка, посчитанные местом записи; их и
    возвращаем, если урок не под «Мотивацией». Иначе — итог строки Payroll
    числами (контракт ответов записи урока)."""
    from apps.payroll.models import Payroll
    stats = recalculate(lesson_ids=[lesson_id])
    if not stats['lessons']:
        return payment, penalty
    row = Payroll.objects.filter(lesson_id=lesson_id).values('payment', 'penalty').first()
    if row is None:
        return payment, penalty
    return _as_number(row['payment']), _as_number(row['penalty'])
