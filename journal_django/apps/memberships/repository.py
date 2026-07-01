"""
MembershipsRepository — единственное место доступа к данным раздела memberships.

ORM-порт services/repo/memberships.js (раздел 09).

GET список — без пагинации, просто список.
POST — UPSERT: повторный вызов с той же парой (group_id, student_id) реактивирует
(ON CONFLICT DO UPDATE SET active=true, остальные поля не трогаются).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from django.db import transaction
from django.db.models import F

from apps.core.utils.orm import dictrow, dictrows

from .models import GroupMembership


# Поля строки membership (gm.* / RETURNING *), в порядке схемы.
_MEMBERSHIP_FIELDS = (
    'id', 'group_id', 'student_id', 'lessons_done', 'remaining',
    'start_date', 'sheet_row', 'active',
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_dates(row: Optional[dict]) -> Optional[dict]:
    """
    start_date: datetime.date → 'YYYY-MM-DD' in-place (аналог setTypeParser(1082)).
    Защита от timezone drift — дословно повторяет поведение исходного репозитория.
    """
    if row is None:
        return None
    val = row.get('start_date')
    if isinstance(val, _dt.date) and not isinstance(val, _dt.datetime):
        row['start_date'] = val.strftime('%Y-%m-%d')
    return row


def _membership_row(membership_id: int) -> Optional[dict]:
    """Строка membership (gm.* / RETURNING *) с нормализованной датой."""
    return _normalize_dates(
        dictrow(GroupMembership.objects.filter(id=membership_id).values(*_MEMBERSHIP_FIELDS))
    )


# ---------------------------------------------------------------------------
# Repository functions (ORM-порт services/repo/memberships.js)
# ---------------------------------------------------------------------------

def list_memberships(
    group_id: Optional[int] = None,
    student_id: Optional[int] = None,
    include_inactive: bool = False,
) -> list[dict]:
    """
    Возвращает список membership без пагинации.

    Фильтры: group_id, student_id, include_inactive (по умолчанию только active=true).
    Порядок: g.name, s.full_name.
    """
    qs = GroupMembership.objects.all()
    if not include_inactive:
        qs = qs.filter(active=True)
    if group_id is not None:
        qs = qs.filter(group_id=group_id)
    if student_id is not None:
        qs = qs.filter(student_id=student_id)

    rows = dictrows(
        qs.order_by('group__name', 'student__full_name').values(
            *_MEMBERSHIP_FIELDS,
            group_name=F('group__name'),
            student_name=F('student__full_name'),
        )
    )
    for row in rows:
        _normalize_dates(row)
    return rows


def add_membership(data: dict) -> dict:
    """
    UPSERT membership (ON CONFLICT (group_id, student_id) DO UPDATE SET active=true).

    На вставке: lessons_done/remaining дефолтятся в 0 (COALESCE(%s,0)).
    На конфликте: только active=true, остальные поля сохраняются (паттерн 4.9).
    """
    group_id = data['group_id']
    student_id = data['student_id']
    lessons_done = data.get('lessons_done')
    remaining = data.get('remaining')

    obj = GroupMembership(
        group_id=group_id,
        student_id=student_id,
        lessons_done=lessons_done if lessons_done is not None else 0,
        remaining=remaining if remaining is not None else 0,
        start_date=data.get('start_date') or None,
        sheet_row=data.get('sheet_row') or None,
        active=True,
    )
    with transaction.atomic():
        GroupMembership.objects.bulk_create(
            [obj],
            update_conflicts=True,
            unique_fields=['group', 'student'],
            update_fields=['active'],   # ON CONFLICT DO UPDATE SET active=true
        )
    # RETURNING * — перечитываем строку по уникальной паре (id мог не вернуться при конфликте).
    return _normalize_dates(
        dictrow(
            GroupMembership.objects
            .filter(group_id=group_id, student_id=student_id)
            .values(*_MEMBERSHIP_FIELDS)
        )
    )


def update_membership(membership_id: int, data: dict) -> Optional[dict]:
    """
    Обновляет membership (PATCH через COALESCE, дословно из memberships.js).

    - lessons_done/remaining: COALESCE(%s, col) → set если значение не None (вкл. 0/0.5).
    - start_date/sheet_row:   COALESCE(%s, col) → set если значение непусто.
    - active:                 COALESCE(%s, col) → set если ключ есть и значение не None.
    """
    obj = GroupMembership.objects.filter(id=membership_id).first()
    if obj is None:
        return None

    if data.get('lessons_done') is not None:
        obj.lessons_done = data['lessons_done']
    if data.get('remaining') is not None:
        obj.remaining = data['remaining']
    if data.get('start_date'):
        obj.start_date = data['start_date']
    if data.get('sheet_row'):
        obj.sheet_row = data['sheet_row']
    if data.get('active') is not None and 'active' in data:
        obj.active = data['active']

    obj.save()
    return _membership_row(membership_id)


def remove_membership(membership_id: int) -> bool:
    """Мягкое удаление: active=false. True если строка найдена."""
    updated = GroupMembership.objects.filter(id=membership_id).update(active=False)
    return updated > 0
