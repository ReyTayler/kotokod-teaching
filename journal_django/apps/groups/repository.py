"""
GroupsRepository — единственное место доступа к данным раздела groups.

ORM-порт services/repo/groups.js (раздел 09).

Слоты расписания (json_agg в оригинале) собираются в Python из ORM (паттерн
4.6.1): отдельный запрос по group_id + сборка списка словарей в порядке
day_of_week, start_time. start_time форматируется как 'HH:MM:SS' (= start_time::text).

Контракт ответа пагинатора: { rows, total, page, page_size } — совпадает с
services/pagination.js (для admin SPA). create/update возвращают строку группы
БЕЗ slots/joined-полей (RETURNING * у оригинала); get/list — со slots.
"""
from __future__ import annotations

import datetime
from typing import Any, Optional

from django.db import transaction
from django.db.models import F
from django.db.models.functions import Now

from apps.core.utils.orm import dictrow, dictrows

from .exceptions import ImmutableGroupFormat
from .models import Group, GroupScheduleSlot


# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

# Поля строки группы (соответствуют g.* / RETURNING *), в порядке схемы.
_GROUP_FIELDS = (
    'id', 'name', 'direction_id', 'teacher_id', 'is_individual',
    'lesson_duration_minutes', 'lessons_per_week', 'group_start_date',
    'vk_chat', 'active', 'created_at',
)

# Whitelist sort_by → ORM-поле. g.id DESC — вторичная сортировка.
_SORTABLE: dict[str, str] = {
    'id':                      'id',
    'name':                    'name',
    'direction_id':            'direction_id',
    'teacher_id':              'teacher_id',
    'lesson_duration_minutes': 'lesson_duration_minutes',
    'lessons_per_week':        'lessons_per_week',
    'group_start_date':        'group_start_date',
    'active':                  'active',
}

_DEFAULT_SORT_BY = 'name'
_DEFAULT_SORT_DIR = 'asc'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_time(t) -> str:
    """datetime.time → 'HH:MM:SS' (повторяет start_time::text у PostgreSQL)."""
    return t.strftime('%H:%M:%S')


def _slots_by_group(group_ids: list[int]) -> dict[int, list[dict]]:
    """
    Собирает слоты расписания по группам (порядок day_of_week, start_time).

    Возвращает {group_id: [{'day_of_week': int, 'start_time': 'HH:MM:SS'}, ...]}.
    Эквивалент json_agg(... ORDER BY day_of_week, start_time) FILTER (WHERE ...)
    с COALESCE до '[]' (группы без слотов получают пустой список).
    """
    result: dict[int, list[dict]] = {gid: [] for gid in group_ids}
    if not group_ids:
        return result
    slots = (
        GroupScheduleSlot.objects
        .filter(group_id__in=group_ids)
        .order_by('day_of_week', 'start_time')
        .values('group_id', 'day_of_week', 'start_time')
    )
    for s in slots:
        result[s['group_id']].append({
            'day_of_week': s['day_of_week'],
            'start_time': _fmt_time(s['start_time']),
        })
    return result


def _apply_filters(qs, filters: dict[str, Any]):
    """
    Применяет фильтры (мимикрирует F.*-билдеры services/pagination.js):
      name (LIKE, регистронезависимо), direction_id, teacher_id,
      is_individual (bool), active (bool).
    """
    name = filters.get('name')
    if name not in (None, ''):
        qs = qs.filter(name__icontains=str(name))

    direction_id = filters.get('direction_id')
    if direction_id not in (None, ''):
        qs = qs.filter(direction_id=int(direction_id))

    teacher_id = filters.get('teacher_id')
    if teacher_id not in (None, ''):
        qs = qs.filter(teacher_id=int(teacher_id))

    is_individual = filters.get('is_individual')
    if is_individual not in (None, ''):
        val = is_individual is True or str(is_individual).lower() == 'true'
        qs = qs.filter(is_individual=val)

    active = filters.get('active')
    if active not in (None, ''):
        val = active is True or str(active).lower() == 'true'
        qs = qs.filter(active=val)

    return qs


def _group_row(group_id: int) -> Optional[dict]:
    """Строка группы (g.* / RETURNING *) без slots и joined-полей."""
    return dictrow(Group.objects.filter(id=group_id).values(*_GROUP_FIELDS))


# ---------------------------------------------------------------------------
# Repository functions
# ---------------------------------------------------------------------------

def list_groups(
    page: int = 1,
    page_size: int = 50,
    sort_by: str = _DEFAULT_SORT_BY,
    sort_dir: str = _DEFAULT_SORT_DIR,
    filters: Optional[dict] = None,
) -> dict:
    """
    Возвращает пагинированный список групп со слотами и именами справочников.

    Контракт ответа: { rows, total, page, page_size }.
    """
    if filters is None:
        filters = {}

    sort_field = _SORTABLE.get(sort_by) or _SORTABLE[_DEFAULT_SORT_BY]
    order_prefix = '' if sort_dir == 'asc' else '-'

    qs = _apply_filters(Group.objects.all(), filters)

    total = qs.count()  # COUNT(*) без JOIN/агрегатов — как _GROUPS_COUNT_FROM

    offset = max(0, (page - 1) * page_size)
    ordered = qs.order_by(f'{order_prefix}{sort_field}', '-id')
    rows = dictrows(
        ordered[offset:offset + page_size].values(
            *_GROUP_FIELDS,
            direction_name=F('direction__name'),
            direction_color=F('direction__color'),
            teacher_name=F('teacher__name'),
        )
    )

    slots_map = _slots_by_group([r['id'] for r in rows])
    for r in rows:
        r['slots'] = slots_map[r['id']]

    return {
        'rows': rows,
        'total': total,
        'page': page,
        'page_size': page_size,
    }


def get_group(group_id: int) -> Optional[dict]:
    """Возвращает одну группу со слотами расписания, либо None."""
    group = _group_row(group_id)
    if group is None:
        return None
    group['slots'] = _slots_by_group([group_id])[group_id]
    return group


def create_group(data: dict) -> dict:
    """
    Создаёт группу + слоты в одной транзакции.

    Возвращает строку группы (g.* / RETURNING *) БЕЗ slots — как оригинал.
    created_at — DB DEFAULT now() через Now(). NULLIF(vk_chat,'') → пустая → None.
    """
    with transaction.atomic():
        obj = Group.objects.create(
            name=data['name'],
            direction_id=data['direction_id'],
            teacher_id=data['teacher_id'],
            is_individual=bool(data.get('is_individual', False)),
            lesson_duration_minutes=data.get('lesson_duration_minutes', 90),
            lessons_per_week=data.get('lessons_per_week', 1),
            group_start_date=data.get('group_start_date') or None,
            vk_chat=data.get('vk_chat') or None,
            created_at=Now(),
        )
        slots = data.get('slots') or []
        if slots:
            GroupScheduleSlot.objects.bulk_create([
                GroupScheduleSlot(
                    group_id=obj.pk,
                    day_of_week=s['day_of_week'],
                    start_time=s['start_time'],
                )
                for s in slots
            ])

    return _group_row(obj.pk)


def update_group(group_id: int, data: dict) -> Optional[dict]:
    """
    Обновляет группу (PATCH через COALESCE) + опционально перезаписывает слоты.

    Если строки нет — возвращает None.
    Если data содержит 'slots' (list) — старые слоты удаляются, вставляются новые.
    is_individual/active могут быть False (sentinel "ключ присутствует").
    Возвращает строку группы (g.*) БЕЗ slots — как RETURNING * оригинала.
    """
    with transaction.atomic():
        obj = Group.objects.filter(id=group_id).first()
        if obj is None:
            return None

        # Формат группы неизменен: смена is_individual на существующей группе
        # запрещена (влияет на инвариант «≤1 активный membership»). Совпадающее
        # значение или отсутствие ключа — no-op (идемпотентный round-trip).
        if (
            'is_individual' in data
            and data['is_individual'] is not None
            and data['is_individual'] != obj.is_individual
        ):
            raise ImmutableGroupFormat()

        if data.get('name'):
            obj.name = data['name']
        if data.get('direction_id'):
            obj.direction_id = data['direction_id']
        if data.get('teacher_id'):
            obj.teacher_id = data['teacher_id']
        if data.get('is_individual') is not None and 'is_individual' in data:
            obj.is_individual = data['is_individual']
        if data.get('lesson_duration_minutes'):
            obj.lesson_duration_minutes = data['lesson_duration_minutes']
        if data.get('lessons_per_week'):
            obj.lessons_per_week = data['lessons_per_week']
        if data.get('group_start_date'):
            obj.group_start_date = data['group_start_date']
        if data.get('vk_chat'):                       # NULLIF: пустая строка → не трогаем
            obj.vk_chat = data['vk_chat']
        if data.get('active') is not None and 'active' in data:
            obj.active = data['active']

        obj.save()

        # Перезаписываем слоты если переданы
        if 'slots' in data and isinstance(data['slots'], list):
            GroupScheduleSlot.objects.filter(group_id=group_id).delete()
            if data['slots']:
                GroupScheduleSlot.objects.bulk_create([
                    GroupScheduleSlot(
                        group_id=group_id,
                        day_of_week=s['day_of_week'],
                        start_time=s['start_time'],
                    )
                    for s in data['slots']
                ])

    return _group_row(group_id)


def soft_delete_group(group_id: int) -> bool:
    """Мягкое удаление группы: active=false. True если строка найдена."""
    updated = Group.objects.filter(id=group_id).update(active=False)
    return updated > 0


# ---------------------------------------------------------------------------
# Расписание: версионные слоты (Ф3)
# ---------------------------------------------------------------------------

def _fmt_time_hm(t) -> Optional[str]:
    return t.strftime('%H:%M') if t else None


def _iso(d) -> Optional[str]:
    return d.isoformat() if d else None


def get_schedule(group_id: int) -> Optional[dict]:
    """
    Расписание группы для редактирования: версионные слоты (с датами действия).
    None если группы нет.
    """
    if not Group.objects.filter(id=group_id).exists():
        return None
    slots = (
        GroupScheduleSlot.objects
        .filter(group_id=group_id)
        .order_by('effective_from', 'day_of_week', 'start_time')
        .values('id', 'day_of_week', 'start_time', 'effective_from', 'effective_to')
    )
    return {
        'slots': [{
            'id': s['id'],
            'day_of_week': s['day_of_week'],
            'start_time': _fmt_time_hm(s['start_time']),
            'effective_from': _iso(s['effective_from']),
            'effective_to': _iso(s['effective_to']),
        } for s in slots],
    }


def apply_schedule_change(group_id: int, effective_from, slots: list[dict]) -> Optional[dict]:
    """
    Постоянная смена расписания с даты effective_from (атомарно):
      - закрыть текущие ОТКРЫТЫЕ слоты (effective_to = effective_from - 1);
        если слот начинался бы позже даты закрытия (нулевой/отрицательный
        интервал) — удалить (он не успел стать активным);
      - вставить новые слоты (effective_from = дата, effective_to = NULL).
    Возвращает обновлённое расписание (get_schedule) или None если группы нет.
    """
    if not Group.objects.filter(id=group_id).exists():
        return None
    eff = (
        effective_from if isinstance(effective_from, datetime.date)
        else datetime.date.fromisoformat(effective_from)
    )
    prev_to = eff - datetime.timedelta(days=1)

    with transaction.atomic():
        for s in GroupScheduleSlot.objects.filter(group_id=group_id, effective_to__isnull=True):
            if s.effective_from <= prev_to:
                s.effective_to = prev_to
                s.save(update_fields=['effective_to'])
            else:
                s.delete()
        GroupScheduleSlot.objects.bulk_create([
            GroupScheduleSlot(
                group_id=group_id,
                day_of_week=s['day_of_week'],
                start_time=s['start_time'],
                effective_from=eff,
            )
            for s in slots
        ])

    return get_schedule(group_id)


# ---------------------------------------------------------------------------
# Прогресс группы: матрица посещаемости «ученик × урок» (вкладка «Прогресс»)
# ---------------------------------------------------------------------------

def get_group_progress(group_id: int) -> Optional[dict]:
    """
    Обзорная матрица посещаемости группы: слоты уроков (столбцы) × ученики (строки).

    Ровно 3 запроса (участники + уроки + посещаемость) без N+1 — считаем на VPS.
    None если группы нет.

    Слот = ceil(lesson_number) (как LessonGrid: half-lesson 0.5 схлопывается в слот,
    первый урок на слот выигрывает). Число слотов = max(последний слот с уроком,
    direction.total_lessons) — так плановые, ещё не проведённые уроки видны пунктиром.

    ОГРАНИЧЕНИЕ коллапса: если на один слот попадает >1 урока (дробные lesson_number
    у 45-мин групп ИЛИ дубль номера на другую дату), берётся только первый — посещаемость
    остальных в % не попадает. В боевых данных lesson_number целочисленный и уникален на
    группу (проверено SELECT'ом), поэтому на практике коллапс безопасен; зеркалит LessonGrid.

    Ячейка ученика по слоту:
      True  — был (есть запись посещаемости present=true),
      False — не был (запись present=false),
      None  — урок не проведён (плановый слот) ИЛИ ученик не входил в состав на тот
              урок (нет записи посещаемости) — не учитывается в held/present/pct.

    transferred_lessons / transferred_from_group_name — если у ученика есть
    GroupMembership.transferred_from (перевод из другой группы, apps.memberships),
    transferred_lessons = min(floor(lessons_done в старой группе), slot_count) —
    столько ведущих пустых ячеек фронт красит статусом «Перевод» (cells не
    переписываются, разметка — чисто presentational). Направление старой группы
    не проверяется здесь — инвариант «только внутри направления» гарантирует
    apps.memberships.repository.transfer_membership на момент перевода. Если
    transferred_lessons == 0 (в т.ч. floor дал 0), transferred_from_group_name = None.

    ВАЖНО: transferred_lessons не гарантирует ровно N закрашенных ячеек — фронт
    расходует его только на cell === None (никогда не перекрывает реальную
    посещаемость), поэтому число закрашенных ячеек может быть меньше (если
    в первых слотах уже есть реальные True/False у этого ученика) — это
    осознанный компромисс, не баг. Плашка на карточке membership
    (MembershipsBlock) при этом показывает сырое число из старой группы без
    капа/floor — небольшой рассинхром с матрицей ожидаем и допустим.
    """
    import math

    from apps.lessons.models import Lesson, LessonAttendance
    from apps.memberships.models import GroupMembership

    grp = (
        Group.objects
        .filter(id=group_id)
        .values('id', total_lessons=F('direction__total_lessons'))
        .first()
    )
    if grp is None:
        return None

    # Ученики группы — строки матрицы, стабильный порядок по имени.
    # Только активные (active=True): membership удаляется мягко (active=false),
    # как и в list_memberships — выбывшие не должны появляться в «Прогрессе».
    members = list(
        GroupMembership.objects
        .filter(group_id=group_id, active=True)
        .order_by('student__full_name')
        .values(
            'student_id', 'transferred_from_id', name=F('student__full_name'),
            transferred_from_lessons_done=F('transferred_from__lessons_done'),
            transferred_from_group_name=F('transferred_from__group__name'),
        )
    )

    # Реальные (проведённые) уроки: слот = ceil(lesson_number), первый на слот.
    lessons = list(
        Lesson.objects
        .filter(group_id=group_id)
        .order_by('lesson_number', 'id')
        .values('id', 'lesson_number', 'lesson_date')
    )

    lesson_by_slot: dict[int, dict] = {}
    max_slot = 0
    for lesson in lessons:
        slot = max(1, math.ceil(float(lesson['lesson_number'])))
        if slot not in lesson_by_slot:
            lesson_by_slot[slot] = lesson
        if slot > max_slot:
            max_slot = slot

    total_lessons = grp['total_lessons'] or 0
    slot_count = max(max_slot, total_lessons)

    # Посещаемость всех уроков группы разом: (lesson_id, student_id) → present.
    lesson_ids = [lesson['id'] for lesson in lesson_by_slot.values()]
    att_map: dict[tuple[int, int], bool] = {}
    if lesson_ids:
        for lid, sid, present in (
            LessonAttendance.objects
            .filter(lesson_id__in=lesson_ids)
            .values_list('lesson_id', 'student_id', 'present')
        ):
            att_map[(lid, sid)] = present

    # Столбцы (слоты). held=True — урок проведён (есть запись), иначе плановый.
    slots = []
    held_slots = 0
    for slot in range(1, slot_count + 1):
        lesson = lesson_by_slot.get(slot)
        if lesson is not None:
            held_slots += 1
        slots.append({
            'slot': slot,
            'lesson_id': lesson['id'] if lesson else None,
            'date': lesson['lesson_date'] if lesson else None,
            'held': lesson is not None,
        })

    # Строки учеников: cells выровнены по slots (None — не проведён / не в составе).
    students = []
    for member in members:
        sid = member['student_id']
        cells: list[Optional[bool]] = []
        present = 0
        held = 0
        for col in slots:
            if not col['held']:
                cells.append(None)
                continue
            key = (col['lesson_id'], sid)
            if key not in att_map:      # ученик не входил в состав на тот урок
                cells.append(None)
                continue
            is_present = bool(att_map[key])
            held += 1
            if is_present:
                present += 1
            cells.append(is_present)
        transferred_lessons = 0
        transferred_from_group_name = None
        if member['transferred_from_id']:
            transferred_lessons = min(
                math.floor(float(member['transferred_from_lessons_done'] or 0)),
                slot_count,
            )
            if transferred_lessons > 0:
                transferred_from_group_name = member['transferred_from_group_name']

        students.append({
            'student_id': sid,
            'name': member['name'],
            'present': present,
            'held': held,
            'pct': round(present / held * 100) if held else 0,
            'cells': cells,
            'transferred_lessons': transferred_lessons,
            'transferred_from_group_name': transferred_from_group_name,
        })

    return {
        'group_id': group_id,
        'total_slots': slot_count,
        'held_slots': held_slots,
        'slots': slots,
        'students': students,
    }
