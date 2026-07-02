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

from .models import Group, GroupScheduleSlot, LessonScheduleException


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
# Расписание: версионные слоты + разовые исключения (Ф3)
# ---------------------------------------------------------------------------

def _fmt_time_hm(t) -> Optional[str]:
    return t.strftime('%H:%M') if t else None


def _iso(d) -> Optional[str]:
    return d.isoformat() if d else None


def get_schedule(group_id: int) -> Optional[dict]:
    """
    Полное расписание группы для редактирования: версионные слоты (с датами
    действия) + все исключения. None если группы нет.
    """
    if not Group.objects.filter(id=group_id).exists():
        return None
    slots = (
        GroupScheduleSlot.objects
        .filter(group_id=group_id)
        .order_by('effective_from', 'day_of_week', 'start_time')
        .values('id', 'day_of_week', 'start_time', 'effective_from', 'effective_to')
    )
    exceptions = (
        LessonScheduleException.objects
        .filter(group_id=group_id)
        .order_by('-created_at', '-id')
        .values('id', 'kind', 'original_date', 'original_time', 'new_date',
                'new_start_time', 'new_teacher_id', 'note', 'created_at')
    )
    return {
        'slots': [{
            'id': s['id'],
            'day_of_week': s['day_of_week'],
            'start_time': _fmt_time_hm(s['start_time']),
            'effective_from': _iso(s['effective_from']),
            'effective_to': _iso(s['effective_to']),
        } for s in slots],
        'exceptions': [{
            'id': e['id'],
            'kind': e['kind'],
            'original_date': _iso(e['original_date']),
            'original_time': _fmt_time_hm(e['original_time']),
            'new_date': _iso(e['new_date']),
            'new_start_time': _fmt_time_hm(e['new_start_time']),
            'new_teacher_id': e['new_teacher_id'],
            'note': e['note'],
            'created_at': e['created_at'].isoformat() if e['created_at'] else None,
        } for e in exceptions],
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


def create_exception(group_id: int, data: dict) -> Optional[dict]:
    """Создать разовое исключение (перенос/отмена/доп.). None если группы нет."""
    if not Group.objects.filter(id=group_id).exists():
        return None
    obj = LessonScheduleException.objects.create(
        group_id=group_id,
        kind=data['kind'],
        original_date=data.get('original_date') or None,
        original_time=data.get('original_time') or None,
        new_date=data.get('new_date') or None,
        new_start_time=data.get('new_start_time') or None,
        new_teacher_id=data.get('new_teacher_id') or None,
        note=data.get('note') or None,
        created_at=Now(),
        created_by=data.get('created_by') or None,
    )
    row = dictrow(
        LessonScheduleException.objects.filter(pk=obj.pk).values(
            'id', 'kind', 'original_date', 'original_time', 'new_date',
            'new_start_time', 'new_teacher_id', 'note', 'created_at',
        )
    )
    return {
        'id': row['id'],
        'kind': row['kind'],
        'original_date': _iso(row['original_date']),
        'original_time': _fmt_time_hm(row['original_time']),
        'new_date': _iso(row['new_date']),
        'new_start_time': _fmt_time_hm(row['new_start_time']),
        'new_teacher_id': row['new_teacher_id'],
        'note': row['note'],
        'created_at': row['created_at'].isoformat() if row['created_at'] else None,
    }


def delete_exception(group_id: int, exception_id: int) -> bool:
    """Удалить исключение по id в рамках группы. True если удалено."""
    deleted, _ = LessonScheduleException.objects.filter(
        id=exception_id, group_id=group_id,
    ).delete()
    return deleted > 0
