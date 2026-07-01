"""
PayrollRepository — единственное место доступа к данным раздела payroll.

ORM-порт services/repo/payroll.js (раздел 09).

Паритет с node-pg:
  • payment/penalty/sum_* (numeric) → Decimal → строка с масштабом (renderer).
  • lessons_count = COUNT(*) → строка (node-pg bigint = строка; в оригинале ::text).
  • list — порт paginate(): whitelist sort с тихим fallback, secondarySort p.id DESC,
    контракт { rows, total, page, page_size }.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from django.db.models import Count, DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce

from apps.core.utils.orm import dictrow, dictrows

from .models import Payroll


# Поля строки payroll (p.* / RETURNING *), в порядке схемы.
_PAYROLL_FIELDS = (
    'id', 'lesson_id', 'teacher_id', 'total_students', 'present_count',
    'payment', 'penalty',
)

# Whitelist sort_by → ORM-поле. p.id DESC — вторичная сортировка.
_SORTABLE: dict[str, str] = {
    'lesson_date':   'lesson__lesson_date',
    'lesson_number': 'lesson__lesson_number',
    'group_name':    'lesson__group__name',
    'teacher_name':  'teacher__name',
    'payment':       'payment',
    'penalty':       'penalty',
}

_DEFAULT_SORT_BY = 'lesson_date'
_DEFAULT_SORT_DIR = 'desc'

_ZERO = Value(Decimal('0'), output_field=DecimalField(max_digits=20, decimal_places=2))


def _apply_filters(qs, filters: dict[str, Any]):
    """
    Фильтры (дословно из PAYROLL_PAGINATION.filters): teacher_id, group_id,
    date_from/date_to и алиасы lesson_date_from/to (l.lesson_date),
    group_name/teacher_name (LIKE).
    """
    teacher_id = filters.get('teacher_id')
    if teacher_id not in (None, ''):
        qs = qs.filter(teacher_id=int(teacher_id))

    group_id = filters.get('group_id')
    if group_id not in (None, ''):
        qs = qs.filter(lesson__group_id=int(group_id))

    for key in ('date_from', 'lesson_date_from'):
        val = filters.get(key)
        if val not in (None, ''):
            qs = qs.filter(lesson__lesson_date__gte=val)

    for key in ('date_to', 'lesson_date_to'):
        val = filters.get(key)
        if val not in (None, ''):
            qs = qs.filter(lesson__lesson_date__lte=val)

    group_name = filters.get('group_name')
    if group_name not in (None, ''):
        qs = qs.filter(lesson__group__name__icontains=str(group_name))

    teacher_name = filters.get('teacher_name')
    if teacher_name not in (None, ''):
        qs = qs.filter(teacher__name__icontains=str(teacher_name))

    return qs


# ---------------------------------------------------------------------------
# Repository functions
# ---------------------------------------------------------------------------

def list_payroll(
    page: int = 1,
    page_size: int = 50,
    sort_by: str = _DEFAULT_SORT_BY,
    sort_dir: str = _DEFAULT_SORT_DIR,
    filters: Optional[dict] = None,
) -> dict:
    """Пагинированный список payroll с joined-полями. Контракт {rows,total,page,page_size}."""
    if filters is None:
        filters = {}

    sort_field = _SORTABLE.get(sort_by) or _SORTABLE[_DEFAULT_SORT_BY]
    order_prefix = '' if sort_dir == 'asc' else '-'

    qs = _apply_filters(Payroll.objects.all(), filters)

    total = qs.count()

    offset = max(0, (page - 1) * page_size)
    ordered = qs.order_by(f'{order_prefix}{sort_field}', '-id')
    rows = dictrows(
        ordered[offset:offset + page_size].values(
            *_PAYROLL_FIELDS,
            lesson_date=F('lesson__lesson_date'),
            lesson_number=F('lesson__lesson_number'),
            group_id=F('lesson__group_id'),
            group_name=F('lesson__group__name'),
            teacher_name=F('teacher__name'),
        )
    )

    return {
        'rows': rows,
        'total': total,
        'page': page,
        'page_size': page_size,
    }


def payroll_summary(
    teacher_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    """
    Сводка по учителю: COUNT уроков, SUM(payment), SUM(penalty). ORDER BY te.name.

    lessons_count → строка (node-pg bigint = строка). sum_* → Decimal (renderer → строка).
    """
    qs = Payroll.objects.all()
    if teacher_id:
        qs = qs.filter(teacher_id=teacher_id)
    if date_from:
        qs = qs.filter(lesson__lesson_date__gte=date_from)
    if date_to:
        qs = qs.filter(lesson__lesson_date__lte=date_to)

    rows = (
        qs.values('teacher_id', teacher_name=F('teacher__name'))
        .annotate(
            lessons_count=Count('id'),
            sum_payment=Coalesce(Sum('payment'), _ZERO),
            sum_penalty=Coalesce(Sum('penalty'), _ZERO),
        )
        .order_by('teacher__name')
    )

    result: list[dict] = []
    for r in rows:
        result.append({
            'teacher_id': r['teacher_id'],
            'teacher_name': r['teacher_name'],
            'lessons_count': str(r['lessons_count']),   # ::text — bigint строкой
            'sum_payment': r['sum_payment'],
            'sum_penalty': r['sum_penalty'],
        })
    return result


def update_payroll(payroll_id: int, fields: dict) -> Optional[dict]:
    """
    Частичное обновление payroll (COALESCE-семантика). Возвращает RETURNING * или None.

    total_students/present_count/payment/penalty — set если значение не None.
    """
    obj = Payroll.objects.filter(id=payroll_id).first()
    if obj is None:
        return None

    if fields.get('total_students') is not None:
        obj.total_students = fields['total_students']
    if fields.get('present_count') is not None:
        obj.present_count = fields['present_count']
    if fields.get('payment') is not None:
        obj.payment = fields['payment']
    if fields.get('penalty') is not None:
        obj.penalty = fields['penalty']

    obj.save()
    return dictrow(Payroll.objects.filter(id=payroll_id).values(*_PAYROLL_FIELDS))
