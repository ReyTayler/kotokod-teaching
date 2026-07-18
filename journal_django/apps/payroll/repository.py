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

from django.db.models import BooleanField, Count, DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce

from apps.core.utils.orm import dictrow, dictrows

from .models import Payroll


# Поля строки payroll (p.* / RETURNING *), в порядке схемы.
_PAYROLL_FIELDS = (
    'id', 'lesson_id', 'teacher_id', 'total_students', 'present_count',
    'payment', 'penalty',
)

# Whitelist sort_by → ORM-поле (алиасы entry_* — см. _base_entries/_surcharge_entries,
# union требует одинаковых имён колонок с обеих сторон). p.id DESC — вторичная сортировка.
_SORTABLE: dict[str, str] = {
    'lesson_date':   'entry_date',
    'lesson_number': 'lesson_number',
    'group_name':    'group_name',
    'teacher_name':  'teacher_name',
    'payment':       'entry_payment',
    'penalty':       'entry_penalty',
}

_DEFAULT_SORT_BY = 'lesson_date'
_DEFAULT_SORT_DIR = 'desc'

_ZERO = Value(Decimal('0'), output_field=DecimalField(max_digits=20, decimal_places=2))
_ZERO_MONEY = Value(Decimal('0'), output_field=DecimalField(max_digits=10, decimal_places=2))

# Колонки итоговой (union'утой) выборки — порядок и типы должны совпадать в
# _base_entries/_surcharge_entries, иначе Django откажется строить UNION.
_ENTRY_VALUES = (
    'id', 'lesson_id', 'teacher_id', 'total_students', 'present_count',
    'entry_payment', 'entry_penalty', 'entry_date', 'is_surcharge',
    'lesson_number', 'group_id', 'group_name', 'teacher_name',
)


def _apply_common_filters(qs, filters: dict[str, Any]):
    """teacher_id/group_id/group_name/teacher_name — общие для базовой и надбавочной
    выборки (диапазон дат — отдельно, см. _apply_date_range, у надбавки своя дата)."""
    teacher_id = filters.get('teacher_id')
    if teacher_id not in (None, ''):
        qs = qs.filter(teacher_id=int(teacher_id))

    group_id = filters.get('group_id')
    if group_id not in (None, ''):
        qs = qs.filter(lesson__group_id=int(group_id))

    group_name = filters.get('group_name')
    if group_name not in (None, ''):
        qs = qs.filter(lesson__group__name__icontains=str(group_name))

    teacher_name = filters.get('teacher_name')
    if teacher_name not in (None, ''):
        qs = qs.filter(teacher__name__icontains=str(teacher_name))

    return qs


def _apply_date_range(qs, filters: dict[str, Any], date_field: str):
    """date_from/date_to (+ алиасы lesson_date_from/to) — против ПЕРЕДАННОГО поля
    даты: у базовой строки это lesson__lesson_date, у надбавки — burn_surcharge_at."""
    for key in ('date_from', 'lesson_date_from'):
        val = filters.get(key)
        if val not in (None, ''):
            qs = qs.filter(**{f'{date_field}__gte': val})

    for key in ('date_to', 'lesson_date_to'):
        val = filters.get(key)
        if val not in (None, ''):
            qs = qs.filter(**{f'{date_field}__lte': val})

    return qs


def _base_entries(filters: dict[str, Any]):
    """Базовая (как отчитан урок изначально) строка на каждый payroll — дата
    фильтруется/сортируется по lesson_date, сумма — payment (без надбавок)."""
    qs = _apply_common_filters(Payroll.objects.all(), filters)
    qs = _apply_date_range(qs, filters, 'lesson__lesson_date')
    return qs.annotate(
        entry_date=F('lesson__lesson_date'),
        entry_payment=F('payment'),
        entry_penalty=F('penalty'),
        is_surcharge=Value(False, output_field=BooleanField()),
        lesson_number=F('lesson__lesson_number'),
        group_id=F('lesson__group_id'),
        group_name=F('lesson__group__name'),
        teacher_name=F('teacher__name'),
    ).values(*_ENTRY_VALUES)


def _surcharge_entries(filters: dict[str, Any]):
    """Надбавка за «сгоревшие» задним числом уроки (см. LessonAttendance.burned_at,
    apps.lessons.repository.update_attendance_cell) — отдельная строка, дата/сумма
    из burn_surcharge_at/burn_surcharge_amount, а не из самого урока. Только уроки,
    где надбавка реально есть (> 0) — иначе засорим список нулевыми строками."""
    qs = Payroll.objects.filter(burn_surcharge_amount__gt=0)
    qs = _apply_common_filters(qs, filters)
    qs = _apply_date_range(qs, filters, 'burn_surcharge_at')
    return qs.annotate(
        entry_date=F('burn_surcharge_at'),
        entry_payment=F('burn_surcharge_amount'),
        entry_penalty=_ZERO_MONEY,
        is_surcharge=Value(True, output_field=BooleanField()),
        lesson_number=F('lesson__lesson_number'),
        group_id=F('lesson__group_id'),
        group_name=F('lesson__group__name'),
        teacher_name=F('teacher__name'),
    ).values(*_ENTRY_VALUES)


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
    """
    Пагинированный список payroll с joined-полями. Контракт {rows,total,page,page_size}.

    UNION ALL двух выборок с одного и того же payroll (см. _base_entries/
    _surcharge_entries) — базовая оплата за урок остаётся в месяце самого урока,
    надбавка за «сгоревшие» правки — отдельной строкой в месяце самой правки.
    rows[i]['is_surcharge'] отличает вторую строку от первой на фронте.
    """
    if filters is None:
        filters = {}

    sort_field = _SORTABLE.get(sort_by) or _SORTABLE[_DEFAULT_SORT_BY]
    order_prefix = '' if sort_dir == 'asc' else '-'

    combined = _base_entries(filters).union(_surcharge_entries(filters), all=True)

    total = combined.count()

    offset = max(0, (page - 1) * page_size)
    ordered = combined.order_by(f'{order_prefix}{sort_field}', '-id')
    rows = dictrows(ordered[offset:offset + page_size])
    for r in rows:
        r['payment'] = r.pop('entry_payment')
        r['penalty'] = r.pop('entry_penalty')
        r['lesson_date'] = r.pop('entry_date')

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

    sum_payment = SUM(payment) за уроки в диапазоне (по lesson_date) + SUM(надбавок
    за «сгоревшие» правки), попавших в диапазон по ДАТЕ ПРАВКИ (burn_surcharge_at),
    а не по дате урока — см. list_payroll/_surcharge_entries. lessons_count считает
    только реальные уроки (базовую строку), надбавка новым уроком не считается.
    lessons_count → строка (node-pg bigint = строка). sum_* → Decimal (renderer → строка).
    """
    base_qs = Payroll.objects.all()
    if teacher_id:
        base_qs = base_qs.filter(teacher_id=teacher_id)
    if date_from:
        base_qs = base_qs.filter(lesson__lesson_date__gte=date_from)
    if date_to:
        base_qs = base_qs.filter(lesson__lesson_date__lte=date_to)

    base_rows = (
        base_qs.values('teacher_id', teacher_name=F('teacher__name'))
        .annotate(
            lessons_count=Count('id'),
            sum_payment=Coalesce(Sum('payment'), _ZERO),
            sum_penalty=Coalesce(Sum('penalty'), _ZERO),
        )
    )

    surcharge_qs = Payroll.objects.filter(burn_surcharge_amount__gt=0)
    if teacher_id:
        surcharge_qs = surcharge_qs.filter(teacher_id=teacher_id)
    if date_from:
        surcharge_qs = surcharge_qs.filter(burn_surcharge_at__gte=date_from)
    if date_to:
        surcharge_qs = surcharge_qs.filter(burn_surcharge_at__lte=date_to)

    surcharge_rows = (
        surcharge_qs.values('teacher_id', teacher_name=F('teacher__name'))
        .annotate(sum_surcharge=Coalesce(Sum('burn_surcharge_amount'), _ZERO))
    )
    surcharge_by_teacher = {r['teacher_id']: r for r in surcharge_rows}

    result_by_teacher: dict[int, dict] = {}
    for r in base_rows:
        surcharge = surcharge_by_teacher.pop(r['teacher_id'], None)
        result_by_teacher[r['teacher_id']] = {
            'teacher_id': r['teacher_id'],
            'teacher_name': r['teacher_name'],
            'lessons_count': str(r['lessons_count']),   # ::text — bigint строкой
            'sum_payment': r['sum_payment'] + (surcharge['sum_surcharge'] if surcharge else Decimal('0')),
            'sum_penalty': r['sum_penalty'],
        }

    # Учителя, у которых в диапазоне ЕСТЬ надбавка, но нет ни одного урока
    # (базовая строка вне диапазона/у другого учителя) — не должны пропасть из сводки.
    for tid, r in surcharge_by_teacher.items():
        result_by_teacher[tid] = {
            'teacher_id': tid,
            'teacher_name': r['teacher_name'],
            'lessons_count': '0',
            'sum_payment': r['sum_surcharge'],
            'sum_penalty': Decimal('0'),
        }

    return sorted(result_by_teacher.values(), key=lambda r: r['teacher_name'] or '')


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
