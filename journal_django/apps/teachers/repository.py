"""
TeachersRepository — единственное место доступа к данным раздела teachers.

ORM-порт services/repo/teachers.js (раздел 09). Контракт ответа списка —
plain list (не пагинированный), как в оригинале.
"""
from __future__ import annotations

from typing import Optional

from django.db.models.functions import Now

from apps.core.utils.orm import dictrow, dictrows

from .models import Teacher


# ---------------------------------------------------------------------------
# Repository functions (ORM-порт services/repo/teachers.js)
# ---------------------------------------------------------------------------

def list_teachers(include_inactive: bool = False) -> list[dict]:
    """SELECT * FROM teachers [WHERE active=true] ORDER BY name."""
    qs = Teacher.objects.all()
    if not include_inactive:
        qs = qs.filter(active=True)
    return dictrows(qs.order_by('name').values())


def get_teacher(teacher_id: int) -> Optional[dict]:
    """SELECT * FROM teachers WHERE id=%s."""
    return dictrow(Teacher.objects.filter(id=teacher_id).values())


def create_teacher(data: dict) -> dict:
    """
    Создаёт преподавателя (INSERT ... RETURNING *).

    NULLIF(email,''), NULLIF(phone,'') → пустая строка → None (паттерн 4.5).
    created_at: модель не объявляет default, поэтому передаём DB-функцию Now()
    (= now()), повторяя серверный DEFAULT исходного INSERT; значение возвращаем
    через refetch .values().
    """
    obj = Teacher.objects.create(
        name=data['name'],
        email=data.get('email') or None,
        phone=data.get('phone') or None,
        created_at=Now(),
    )
    return dictrow(Teacher.objects.filter(pk=obj.pk).values())


def update_teacher(teacher_id: int, data: dict) -> Optional[dict]:
    """
    Обновляет преподавателя (PATCH через COALESCE/NULLIF, дословно из teachers.js).

    - name:  COALESCE(%s, name)              → set если непусто.
    - email: COALESCE(NULLIF(%s,''), email)  → set если ключ есть и значение непусто.
    - phone: COALESCE(NULLIF(%s,''), phone)  → set если ключ есть и значение непусто.
    - active: COALESCE(%s, active)           → set если ключ есть и значение не None.
    """
    obj = Teacher.objects.filter(id=teacher_id).first()
    if obj is None:
        return None

    if data.get('name'):
        obj.name = data['name']
    if data.get('email'):              # NULLIF: пустая строка/None → не трогаем
        obj.email = data['email']
    if data.get('phone'):
        obj.phone = data['phone']
    if data.get('active') is not None and 'active' in data:
        obj.active = data['active']

    obj.save()
    return dictrow(Teacher.objects.filter(id=teacher_id).values())


def soft_delete_teacher(teacher_id: int) -> bool:
    """Мягкое удаление: active=false. True если строка найдена."""
    updated = Teacher.objects.filter(id=teacher_id).update(active=False)
    return updated > 0
