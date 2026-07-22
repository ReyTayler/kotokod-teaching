"""
StudentsRepository — единственное место доступа к данным раздела students.

CRUD (list/get/create/update/soft_delete) — ORM-порт services/repo/students.js
(раздел 09). Контракт пагинатора: { rows, total, page, page_size }.

student_stats() оставлен на сыром SQL — см. # ORM-EXCEPTION у функции.
"""
from __future__ import annotations

from typing import Any, Optional

from django.db import connection
from django.db.models import F
from django.db.models.functions import Now

from apps.core.utils.orm import dictrow, dictrows
from apps.finances.repository import balance_for_student

from .models import Student


# ---------------------------------------------------------------------------
# Helpers (только для student_stats — # ORM-EXCEPTION)
# ---------------------------------------------------------------------------

def _dictfetchall(cursor) -> list[dict]:
    """Вернуть список dict из cursor (аналог Node pg rows)."""
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Пагинация / фильтры
# ---------------------------------------------------------------------------

# Whitelist sort_by → ORM-поле. id DESC — вторичная сортировка.
_SORTABLE: dict[str, str] = {
    'id':                  'id',
    'full_name':           'full_name',
    'age':                 'age',
    'enrollment_status':   'enrollment_status',
    'first_purchase_date': 'first_purchase_date',
    'created_at':          'created_at',
}

_DEFAULT_SORT_BY = 'full_name'
_DEFAULT_SORT_DIR = 'asc'

# Явный список колонок students для .values() — общий для list/get/create/update,
# чтобы новое поле модели требовалось добавить только в одном месте. manager_name
# везде добавляется отдельным kwarg-алиасом (F() несовместим с .values() без аргументов).
_STUDENT_VALUES_FIELDS = (
    'id', 'full_name', 'birth_date', 'platform_id', 'bitrix24_link',
    'parent1_name', 'parent1_phone', 'parent1_email',
    'parent2_name', 'parent2_phone', 'parent2_email',
    'first_purchase_date', 'age', 'manager_id',
    'enrollment_status', 'frozen_from', 'frozen_until', 'created_at',
)


def _apply_filters(qs, filters: dict[str, Any]):
    """
    Фильтры (мимикрируют F.*-билдеры services/pagination.js):
      full_name (LIKE), parent1_phone/parent1_name/platform_id (likeNullable),
      manager_id (exact), enrollment_status (exact), age (num).

    likeNullable (col IS NOT NULL AND LOWER(col) LIKE) выражается __icontains —
    NULL по col не матчится автоматически, поэтому IS NOT NULL избыточен.
    """
    full_name = filters.get('full_name')
    if full_name not in (None, ''):
        qs = qs.filter(full_name__icontains=str(full_name))

    parent1_phone = filters.get('parent1_phone')
    if parent1_phone not in (None, ''):
        qs = qs.filter(parent1_phone__icontains=str(parent1_phone))

    parent1_name = filters.get('parent1_name')
    if parent1_name not in (None, ''):
        qs = qs.filter(parent1_name__icontains=str(parent1_name))

    manager_id = filters.get('manager_id')
    if manager_id not in (None, ''):
        try:
            manager_id = int(manager_id)
        except (TypeError, ValueError):
            pass  # невалидное значение — фильтр молча игнорируется, как age ниже
        else:
            qs = qs.filter(manager_id=manager_id)

    platform_id = filters.get('platform_id')
    if platform_id not in (None, ''):
        qs = qs.filter(platform_id__icontains=str(platform_id))

    enrollment_status = filters.get('enrollment_status')
    if enrollment_status not in (None, ''):
        qs = qs.filter(enrollment_status=str(enrollment_status))

    age = filters.get('age')
    if age not in (None, ''):
        qs = qs.filter(age=int(age))

    return qs


# ---------------------------------------------------------------------------
# Repository functions — students CRUD (ORM)
# ---------------------------------------------------------------------------

def list_students(
    page: int = 1,
    page_size: int = 50,
    sort_by: str = _DEFAULT_SORT_BY,
    sort_dir: str = _DEFAULT_SORT_DIR,
    filters: Optional[dict] = None,
) -> dict:
    """Пагинированный список учеников. Контракт { rows, total, page, page_size }."""
    if filters is None:
        filters = {}

    sort_field = _SORTABLE.get(sort_by) or _SORTABLE[_DEFAULT_SORT_BY]
    order_prefix = '' if sort_dir == 'asc' else '-'

    qs = _apply_filters(Student.objects.all(), filters)

    total = qs.count()

    offset = max(0, (page - 1) * page_size)
    ordered = qs.order_by(f'{order_prefix}{sort_field}', '-id')
    rows = dictrows(ordered[offset:offset + page_size].values(
        *_STUDENT_VALUES_FIELDS, manager_name=F('manager__full_name'),
    ))

    return {
        'rows': rows,
        'total': total,
        'page': page,
        'page_size': page_size,
    }


def get_student(student_id: int) -> Optional[dict]:
    """Возвращает одного ученика по id или None."""
    return dictrow(Student.objects.filter(id=student_id).values(
        *_STUDENT_VALUES_FIELDS, manager_name=F('manager__full_name'),
    ))


def create_student(data: dict) -> dict:
    """
    Создаёт ученика (INSERT ... RETURNING *).

    NULLIF('', '') → пустая строка → None (platform_id/bitrix24_link/parent1_*/parent2_*).
    enrollment_status по умолчанию 'enrolled'. created_at — DB DEFAULT now() через Now().
    """
    obj = Student.objects.create(
        full_name=data['full_name'],
        birth_date=data.get('birth_date') or None,
        platform_id=data.get('platform_id') or None,
        bitrix24_link=data.get('bitrix24_link') or None,
        parent1_name=data.get('parent1_name') or None,
        parent1_phone=data.get('parent1_phone') or None,
        parent1_email=data.get('parent1_email') or None,
        parent2_name=data.get('parent2_name') or None,
        parent2_phone=data.get('parent2_phone') or None,
        parent2_email=data.get('parent2_email') or None,
        first_purchase_date=data.get('first_purchase_date') or None,
        age=data.get('age') if data.get('age') is not None else None,
        enrollment_status=data.get('enrollment_status') or 'enrolled',
        frozen_from=data.get('frozen_from') or None,
        frozen_until=data.get('frozen_until') or None,
        created_at=Now(),
    )
    return dictrow(Student.objects.filter(pk=obj.pk).values(
        *_STUDENT_VALUES_FIELDS, manager_name=F('manager__full_name'),
    ))


def update_student(student_id: int, data: dict) -> Optional[dict]:
    """
    Обновляет ученика (PATCH через COALESCE, дословно из students.js).

    frozen_from/frozen_until — НЕ COALESCE-поля: перезаписываются ВСЕГДА (включая
    NULL-сброс). Отсутствие ключа эквивалентно None, чтобы смена статуса на
    не-frozen гарантированно занулила даты.
    """
    obj = Student.objects.filter(id=student_id).first()
    if obj is None:
        return None

    if data.get('full_name'):
        obj.full_name = data['full_name']
    if data.get('birth_date'):
        obj.birth_date = data['birth_date']
    if data.get('platform_id'):
        obj.platform_id = data['platform_id']
    if data.get('bitrix24_link'):              # NULLIF: пустая строка → не трогаем
        obj.bitrix24_link = data['bitrix24_link']
    if data.get('parent1_name'):
        obj.parent1_name = data['parent1_name']
    if data.get('parent1_phone'):
        obj.parent1_phone = data['parent1_phone']
    if data.get('parent1_email'):
        obj.parent1_email = data['parent1_email']
    if data.get('parent2_name'):
        obj.parent2_name = data['parent2_name']
    if data.get('parent2_phone'):
        obj.parent2_phone = data['parent2_phone']
    if data.get('parent2_email'):
        obj.parent2_email = data['parent2_email']
    if data.get('first_purchase_date'):
        obj.first_purchase_date = data['first_purchase_date']
    if data.get('age') is not None:
        obj.age = data['age']
    if data.get('enrollment_status'):
        obj.enrollment_status = data['enrollment_status']
    # frozen_from/frozen_until — всегда перезаписываем (absent → None-сброс),
    # чтобы смена статуса на не-frozen гарантированно занулила даты.
    obj.frozen_from = data.get('frozen_from') or None
    obj.frozen_until = data.get('frozen_until') or None

    obj.save()
    return dictrow(Student.objects.filter(id=student_id).values(
        *_STUDENT_VALUES_FIELDS, manager_name=F('manager__full_name'),
    ))


def soft_delete_student(student_id: int) -> bool:
    """Мягкое удаление: enrollment_status='not_enrolled', frozen_from/until=NULL."""
    updated = Student.objects.filter(id=student_id).update(
        enrollment_status='not_enrolled', frozen_from=None, frozen_until=None,
    )
    return updated > 0


def student_stats(student_id: int) -> dict:
    """
    Сводка посещаемости ученика по группам и направлениям.

    CTE-запрос дословно из services/repo/students.js studentStats().
    Пост-обработка на Python имитирует JS Math.round(x*1000)/10.

    # ORM-EXCEPTION: CTE с MSK-таймзоной (now() AT TIME ZONE 'Europe/Moscow'),
    # FILTER-агрегатами (COUNT(...) FILTER (WHERE present AND month-range)),
    # COUNT(DISTINCT) и составным условием LEFT JOIN lesson_attendance
    # (la.student_id = gm.student_id в ON, не в WHERE). ORM-перевод (FilteredRelation +
    # Case/When + zoneinfo) резко повышает риск расхождения на неверифицируемом пути
    # (Express удалён, data-тесты часто пропускаются). Сохраняем SQL дословно.
    """
    with connection.cursor() as cur:
        cur.execute(
            """
            WITH msk_now AS (
               SELECT (now() AT TIME ZONE 'Europe/Moscow')::date AS today
             ),
             msk_month AS (
               SELECT date_trunc('month', today)::date            AS m_start,
                      (date_trunc('month', today) + interval '1 month')::date AS m_end
                 FROM msk_now
             )
             SELECT gm.id AS membership_id,
                    gm.group_id,
                    gm.lessons_done,
                    gm.active AS membership_active,
                    g.name   AS group_name,
                    g.is_individual,
                    g.lesson_duration_minutes,
                    d.id     AS direction_id,
                    d.name   AS direction_name,
                    d.color  AS direction_color,
                    d.total_lessons AS course_total_lessons,
                    te.name  AS teacher_name,
                    te.id    AS teacher_id,
                    COUNT(la.*) FILTER (WHERE la.present)::int                                  AS attended_count,
                    COUNT(DISTINCT l.id)::int                                                   AS lessons_recorded,
                    MIN(CASE WHEN la.present THEN l.lesson_date END)                            AS first_attended,
                    MAX(CASE WHEN la.present THEN l.lesson_date END)                            AS last_attended,
                    COUNT(DISTINCT l.id) FILTER (
                      WHERE l.lesson_date >= (SELECT m_start FROM msk_month)
                        AND l.lesson_date <  (SELECT m_end   FROM msk_month)
                    )::int                                                                       AS month_lessons,
                    COUNT(la.*) FILTER (
                      WHERE la.present
                        AND l.lesson_date >= (SELECT m_start FROM msk_month)
                        AND l.lesson_date <  (SELECT m_end   FROM msk_month)
                    )::int                                                                       AS month_attended
               FROM group_memberships gm
               JOIN groups g    ON g.id = gm.group_id
               JOIN directions d ON d.id = g.direction_id
               JOIN teachers te ON te.id = g.teacher_id
               LEFT JOIN lessons l ON l.group_id = gm.group_id
               LEFT JOIN lesson_attendance la ON la.lesson_id = l.id AND la.student_id = gm.student_id
              WHERE gm.student_id = %s
              GROUP BY gm.id, gm.group_id, gm.lessons_done, gm.active,
                       g.name, g.is_individual, g.lesson_duration_minutes,
                       d.id, d.name, d.color, d.total_lessons, te.name, te.id
              ORDER BY d.name, g.name
            """,
            [student_id],
        )
        groups_raw = _dictfetchall(cur)

    def _js_round(x: float) -> Optional[float]:
        """
        Имитирует JS Math.round(x * 1000) / 10.

        Python banker's rounding (round()) отличается от JS Math.round().
        Используем int(x * 1000 + 0.5) / 10 для точного совпадения.
        """
        if x is None:
            return None
        return int(x * 1000 + 0.5) / 10

    student_balance = balance_for_student(student_id)

    # Строим список статистики по группам (аналог JS groupStats.map())
    group_stats: list[dict] = []
    for r in groups_raw:
        recorded = int(r['lessons_recorded'] or 0)
        attended = int(r['attended_count'] or 0)
        plan = int(r['course_total_lessons']) if r['course_total_lessons'] is not None else None
        denom = plan if (plan is not None and plan > 0) else recorded
        pct = _js_round(attended / denom) if denom > 0 else None
        month_lessons = int(r['month_lessons'] or 0)
        month_attended = int(r['month_attended'] or 0)

        group_stats.append({
            'membership_id':           r['membership_id'],
            'group_id':                r['group_id'],
            'group_name':              r['group_name'],
            'direction_id':            r['direction_id'],
            'direction_name':          r['direction_name'],
            'direction_color':         r['direction_color'],
            'course_total_lessons':    plan,
            'teacher_id':              r['teacher_id'],
            'teacher_name':            r['teacher_name'],
            'is_individual':           r['is_individual'],
            'lesson_duration_minutes': r['lesson_duration_minutes'],
            'membership_active':       r['membership_active'],
            'lessons_done':            r['lessons_done'],
            'remaining':               student_balance,
            'lessons_recorded':        recorded,
            'attended_count':          attended,
            'missed_count':            max(recorded - attended, 0),
            'denominator':             denom,
            'attendance_pct':          pct,
            'first_attended':          r['first_attended'],
            'last_attended':           r['last_attended'],
            'this_month': {
                'lessons_recorded': month_lessons,
                'attended_count':   month_attended,
                'attendance_pct':   _js_round(month_attended / month_lessons) if month_lessons > 0 else None,
            },
        })

    # Агрегируем по направлению (аналог JS directionMap / Map())
    direction_map: dict[int, dict] = {}
    for g in group_stats:
        did = g['direction_id']
        if did not in direction_map:
            direction_map[did] = {
                'direction_id':         did,
                'direction_name':       g['direction_name'],
                'direction_color':      g['direction_color'],
                'course_total_lessons': g['course_total_lessons'],
                'attended_count':       0,
                'lessons_recorded':     0,
                'missed_count':         0,
                'first_attended':       None,
                'last_attended':        None,
                'this_month': {
                    'lessons_recorded': 0,
                    'attended_count':   0,
                },
                'groups': [],
            }
        d = direction_map[did]
        d['attended_count']   += g['attended_count']
        d['lessons_recorded'] += g['lessons_recorded']
        d['missed_count']     += g['missed_count']
        if g['first_attended'] and (
            d['first_attended'] is None or g['first_attended'] < d['first_attended']
        ):
            d['first_attended'] = g['first_attended']
        if g['last_attended'] and (
            d['last_attended'] is None or g['last_attended'] > d['last_attended']
        ):
            d['last_attended'] = g['last_attended']
        d['this_month']['lessons_recorded'] += g['this_month']['lessons_recorded']
        d['this_month']['attended_count']   += g['this_month']['attended_count']
        d['groups'].append(g)

    # Финализируем направления (добавляем denominator и attendance_pct)
    directions: list[dict] = []
    for d in direction_map.values():
        plan = d['course_total_lessons']
        denom = plan if (plan is not None and plan > 0) else d['lessons_recorded']
        month_lessons = d['this_month']['lessons_recorded']
        month_attended = d['this_month']['attended_count']
        directions.append({
            **d,
            'denominator':    denom,
            'attendance_pct': _js_round(d['attended_count'] / denom) if denom > 0 else None,
            'this_month': {
                **d['this_month'],
                'attendance_pct': _js_round(month_attended / month_lessons) if month_lessons > 0 else None,
            },
        })

    # Сортируем по direction_name (аналог JS localeCompare('ru'))
    directions.sort(key=lambda d: d['direction_name'] or '')

    # Итоговые totals (аналог JS groupStats.reduce())
    totals = {
        'lessons_recorded': 0,
        'attended_count':   0,
        'missed_count':     0,
        'denominator':      0,
        'month_lessons':    0,
        'month_attended':   0,
    }
    for g in group_stats:
        totals['lessons_recorded'] += g['lessons_recorded']
        totals['attended_count']   += g['attended_count']
        totals['missed_count']     += g['missed_count']
        totals['denominator']      += g['denominator']
        totals['month_lessons']    += g['this_month']['lessons_recorded']
        totals['month_attended']   += g['this_month']['attended_count']

    overall_pct = (
        _js_round(totals['attended_count'] / totals['denominator'])
        if totals['denominator'] > 0 else None
    )
    month_pct = (
        _js_round(totals['month_attended'] / totals['month_lessons'])
        if totals['month_lessons'] > 0 else None
    )

    return {
        'student_id': student_id,
        'directions': directions,
        'groups':     group_stats,
        'overall': {
            'lessons_recorded': totals['lessons_recorded'],
            'attended_count':   totals['attended_count'],
            'missed_count':     totals['missed_count'],
            'denominator':      totals['denominator'],
            'attendance_pct':   overall_pct,
            'this_month': {
                'lessons_recorded': totals['month_lessons'],
                'attended_count':   totals['month_attended'],
                'attendance_pct':   month_pct,
            },
        },
    }


# list_payments / get_student_balance переехали в apps/payments/repository.py


# ---------------------------------------------------------------------------
# Repository functions — student comments (ORM)
# ---------------------------------------------------------------------------

def add_comment(student_id: int, body: str, author_id: Optional[int]):
    """Создаёт комментарий (INSERT). Существование student_id проверяет вызывающий (view)."""
    from .models import StudentComment
    return StudentComment.objects.create(student_id=student_id, body=body, author_id=author_id)


def delete_comment(student_id: int, comment_id: int) -> bool:
    """Удаляет комментарий. False если не найден (или принадлежит другому ученику)."""
    from .models import StudentComment
    deleted, _ = StudentComment.objects.filter(id=comment_id, student_id=student_id).delete()
    return deleted > 0
