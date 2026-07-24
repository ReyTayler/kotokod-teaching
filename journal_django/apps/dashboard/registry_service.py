"""
RegistryService — «Реестр куратора»: список активных учеников для вкладки дашборда.

Строка реестра = УЧЕНИК (баланс пулится по student_id — единый пул по всем
направлениям, см. docs/superpowers/specs/2026-07-08-student-balance-pooling-design.md).

МАСШТАБ (вариант B, 2026-07-11): список пагинируется НА УРОВНЕ БД. `students_qs`
строит аннотированный queryset (balance/attended/planned/last/next — коррелированные
Subquery, без fan-out), фильтр сегмента и поиск — WHERE, сортировка — ORDER BY,
срез — LIMIT/OFFSET штатным DRF-пагинатором. Так реестр держит тысячи учеников,
не вычитывая весь список в память на каждый запрос.

Реестр использует ПРОСТОЙ пул-баланс purchased − attended (SQL-арифметика), НЕ
FIFO-движок (он нужен только финансовой вкладке). Половинки: урок 45 мин = 0.5.

Сводка (get_summary) — агрегаты по всей активной популяции (это тотал, считать
всех неизбежно), поэтому кэшируется (Redis) и прогревается Celery-beat. Список —
per-request дешёвая индексированная выборка страницы, не кэшируется.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.core.cache import cache
from django.db.models import (
    Case, Count, DecimalField, Exists, ExpressionWrapper, F, FloatField,
    IntegerField, OuterRef, QuerySet, Subquery, Sum, Value, When,
)
from django.db.models.functions import Coalesce

from apps.core.utils.dates import msk_month_range_triple, msk_now
from apps.core.utils.decimal import js_number, to_decimal
from apps.lessons.models import LessonAttendance
from apps.memberships.models import GroupMembership
from apps.scheduling import repository as sched_repo
from apps.scheduling.occurrences import OVERDUE, PENDING
from apps.scheduling.models import PlannedLesson
from apps.payments.models import Payment
from apps.students.models import Student

# Порог «простоя» (дней без проведённого урока).
IDLE_DAYS = 14

# Единый источник приоритета статусов (срочность по убыванию). Отсюда — и
# статус-бейдж (classify), и urgency_rank для сортировки в SQL (_URGENCY_CASE).
# При правке порядка синхронизировать оба места (тест это подстрахует).
STATUS_PRIORITY = ('closed', 'ending', 'idle', 'no_plan', 'ok')
STATUS_RANK = {s: i for i, s in enumerate(STATUS_PRIORITY)}

# Публичные whitelist'ы (валидируются во view).
SEGMENTS = ('all', 'ending', 'closed', 'idle', 'no_plan')
SORTS = ('urgency', 'name', 'balance', 'progress', 'last_lesson')
SORT_DIRS = ('asc', 'desc')

# Кэш сводки: короткий TTL (базовая свежесть для всех мутаций); оплаты
# инвалидируют явно; в проде Celery-beat держит тёплым. Список НЕ кэшируется.
SUMMARY_CACHE_KEY = 'registry:summary'
SUMMARY_TTL = 120  # секунд

_DEC = DecimalField(max_digits=20, decimal_places=2)
_ZERO_DEC = Value(Decimal('0'), output_field=_DEC)


def _today() -> datetime.date:
    return msk_now().date()


def _idle_cutoff(today: datetime.date) -> datetime.date:
    return today - datetime.timedelta(days=IDLE_DAYS)


# ---------------------------------------------------------------------------
# Классификация (чистая) — статус-бейдж + флаги сигналов. Без БД.
# ---------------------------------------------------------------------------

def classify(balance, last_date, next_date, today: datetime.date) -> dict:
    """
    Балансы/даты → флаги сигналов (пересекающиеся) + статус-бейдж (самый срочный).
    closed > ending > idle > no_plan > ok. Точечно тестируемо на границах.
    """
    cutoff = _idle_cutoff(today)
    flags = {
        'closed': balance <= 0,
        'ending': 0 < balance <= 2,
        'idle': last_date is not None and last_date < cutoff,
        'no_plan': next_date is None,
    }
    status = next((s for s in STATUS_PRIORITY if flags.get(s)), 'ok')
    return {**flags, 'status': status}


# ---------------------------------------------------------------------------
# Аннотированный queryset активных учеников (вариант B). Все агрегаты —
# коррелированные Subquery по student_id → без fan-out от JOIN'ов.
# ---------------------------------------------------------------------------

def _attended_units_subquery():
    """
    Σ отработанных уроков (half-lesson: 45→0.5) по посещениям ученика.

    Факт доп.урока (lesson_type='extra') учитывается: в новой модели компенсации
    исходный пропуск остаётся present=false, а потребление идёт от самого факта
    доп.урока (его вес = длительность исходного урока), поэтому один пропуск
    списывается ровно один раз (см. apps/finances/repository.py, тот же инвариант).
    """
    return Subquery(
        LessonAttendance.objects
        .filter(student_id=OuterRef('pk'), present=True)
        .values('student_id')
        .annotate(u=Coalesce(Sum(Case(
            When(lesson__lesson_duration_minutes=45, then=Value(Decimal('0.5'))),
            default=Value(Decimal('1')),
            output_field=_DEC,
        )), _ZERO_DEC))
        .values('u')[:1],
        output_field=_DEC,
    )


def _purchased_subquery():
    """Σ купленных уроков (net, с учётом возвратов как отрицательных строк)."""
    return Subquery(
        Payment.objects
        .filter(student_id=OuterRef('pk'))
        .values('student_id')
        .annotate(s=Coalesce(Sum('lessons_count', output_field=_DEC), _ZERO_DEC))
        .values('s')[:1],
        output_field=_DEC,
    )


def _membership_sum_subquery(field: str):
    """Σ поля по активным membership ученика (в активных группах)."""
    return Subquery(
        GroupMembership.objects
        .filter(student_id=OuterRef('pk'), active=True, group__active=True)
        .values('student_id')
        .annotate(s=Coalesce(Sum(field, output_field=_DEC), _ZERO_DEC))
        .values('s')[:1],
        output_field=_DEC,
    )


def _last_lesson_subquery():
    """
    Дата последнего посещённого занятия (для idle-флага).

    Намеренно БЕЗ exclude(lesson_type='extra'), в отличие от
    _attended_units_subquery: доп.урок — реальное присутствие ученика, его
    дата корректно двигает «последнее занятие» вперёд. Исключается из баланса
    (там задвоение), но не из активности/engagement-сигнала.
    """
    return Subquery(
        LessonAttendance.objects
        .filter(student_id=OuterRef('pk'), present=True)
        .order_by('-lesson__lesson_date')
        .values('lesson__lesson_date')[:1],
    )


def _next_lesson_subquery(today: datetime.date):
    return Subquery(
        PlannedLesson.objects
        .filter(
            group__active=True,
            group__memberships__active=True,
            group__memberships__student_id=OuterRef('pk'),
            scheduled_date__gte=today,
            status__in=(PENDING, OVERDUE),
        )
        .order_by('scheduled_date')
        .values('scheduled_date')[:1],
    )


def base_students_qs(today: datetime.date) -> QuerySet:
    """
    Активные ученики (enrolled + есть активный membership в активной группе),
    аннотированные вычисляемыми полями. База и для списка, и для сводки.
    """
    active_membership = GroupMembership.objects.filter(
        student_id=OuterRef('pk'), active=True, group__active=True,
    )
    qs = (
        Student.objects
        .filter(enrollment_status='enrolled')
        .filter(Exists(active_membership))
        .annotate(
            balance=ExpressionWrapper(
                Coalesce(_purchased_subquery(), _ZERO_DEC)
                - Coalesce(_attended_units_subquery(), _ZERO_DEC),
                output_field=_DEC,
            ),
            attended=Coalesce(_membership_sum_subquery('lessons_done'), _ZERO_DEC),
            planned=Coalesce(
                _membership_sum_subquery('group__direction__total_lessons'), _ZERO_DEC,
            ),
            last_lesson=_last_lesson_subquery(),
            next_lesson=_next_lesson_subquery(today),
        )
    )
    # Второй проход: поля, зависящие от balance/дат (urgency_rank, progress_ratio).
    cutoff = _idle_cutoff(today)
    return qs.annotate(
        urgency_rank=Case(
            When(balance__lte=0, then=Value(0)),                 # closed
            When(balance__lte=2, then=Value(1)),                 # ending (0<bal≤2)
            When(last_lesson__lt=cutoff, then=Value(2)),         # idle
            When(next_lesson__isnull=True, then=Value(3)),       # no_plan
            default=Value(4),
            output_field=IntegerField(),
        ),
        progress_ratio=Case(
            When(planned__gt=0, then=ExpressionWrapper(
                F('attended') * Value(1.0) / F('planned'), output_field=FloatField(),
            )),
            default=Value(None),
            output_field=FloatField(),
        ),
    )


# ---------------------------------------------------------------------------
# Список: фильтр сегмента + поиск + сортировка (view пагинирует queryset).
# ---------------------------------------------------------------------------

def _apply_segment(qs: QuerySet, segment: str, today: datetime.date) -> QuerySet:
    """Фильтр по сигналу (пересекающиеся условия — не эксклюзивный статус)."""
    cutoff = _idle_cutoff(today)
    if segment == 'ending':
        return qs.filter(balance__gt=0, balance__lte=2)
    if segment == 'closed':
        return qs.filter(balance__lte=0)
    if segment == 'idle':
        return qs.filter(last_lesson__lt=cutoff)
    if segment == 'no_plan':
        return qs.filter(next_lesson__isnull=True)
    return qs  # 'all'


def _apply_search(qs: QuerySet, search: str) -> QuerySet:
    """Поиск по имени ИЛИ коду группы (Exists — без задваивания строк)."""
    q = (search or '').strip()
    if not q:
        return qs
    code_match = GroupMembership.objects.filter(
        student_id=OuterRef('pk'), active=True, group__active=True,
        group__name__icontains=q,
    )
    from django.db.models import Q
    return qs.filter(Q(full_name__icontains=q) | Exists(code_match))


_ORDER_FIELDS = {
    'urgency': ('urgency_rank', 'balance', 'full_name'),
    'name': ('full_name',),
    'balance': ('balance',),
    'progress': ('progress_ratio',),
    'last_lesson': ('last_lesson',),
}


def _apply_order(qs: QuerySet, sort_by: str, sort_dir: str) -> QuerySet:
    fields = _ORDER_FIELDS.get(sort_by, _ORDER_FIELDS['urgency'])
    desc = sort_dir == 'desc'
    order = []
    for i, name in enumerate(fields):
        f = F(name)
        # Первичный ключ — по направлению; вторичные (тай-брейки urgency) — asc.
        expr = (f.desc(nulls_last=True) if (desc and i == 0) else f.asc(nulls_last=True))
        order.append(expr)
    return qs.order_by(*order)


def students_qs(*, segment='all', search='', sort_by='urgency', sort_dir='asc') -> QuerySet:
    """Аннотированный, отфильтрованный и отсортированный queryset (view пагинирует)."""
    today = _today()
    qs = base_students_qs(today)
    qs = _apply_segment(qs, segment, today)
    qs = _apply_search(qs, search)
    return _apply_order(qs, sort_by, sort_dir)


def serialize_rows(students: list) -> list[dict]:
    """Строки ответа из Student-объектов страницы: догрузка кодов/преподов
    (батч по id страницы, без N+1) + статус через classify."""
    today = _today()
    ids = [s.pk for s in students]
    codes: dict[int, list[str]] = {}
    teachers: dict[int, list[str]] = {}
    if ids:
        rows = (
            GroupMembership.objects
            .filter(student_id__in=ids, active=True, group__active=True)
            .order_by('group__name')
            .values('student_id', group_name=F('group__name'), teacher_name=F('group__teacher__name'))
        )
        for r in rows:
            codes.setdefault(r['student_id'], []).append(r['group_name'])
            t = r['teacher_name']
            lst = teachers.setdefault(r['student_id'], [])
            if t and t not in lst:
                lst.append(t)

    out: list[dict] = []
    for s in students:
        balance = js_number(to_decimal(s.balance or 0))
        attended = to_decimal(s.attended or 0)
        planned = int(s.planned or 0)
        progress_pct = round(float(attended) / planned * 100) if planned > 0 else None
        status = classify(balance, s.last_lesson, s.next_lesson, today)['status']
        out.append({
            'student_id': s.pk,
            'student_name': s.full_name,
            'codes': codes.get(s.pk, []),
            'teacher_names': teachers.get(s.pk, []),
            'balance': balance,
            'attended': js_number(attended),
            'planned': planned,
            'progress_pct': progress_pct,
            'last_lesson_date': s.last_lesson.isoformat() if s.last_lesson else None,
            'next_lesson_date': s.next_lesson.isoformat() if s.next_lesson else None,
            'status': status,
        })
    return out


# ---------------------------------------------------------------------------
# Сводка: агрегаты по всей активной популяции + поток дня. Кэшируется.
# ---------------------------------------------------------------------------

def build_summary() -> dict:
    """KPI + счётчики сигналов + поток дня. Один лёгкий проход по активным
    ученикам (тотал — считать всех неизбежно); результат кэшируется."""
    today = _today()
    _, month_start, month_end = msk_month_range_triple()

    rows = base_students_qs(today).values('balance', 'last_lesson', 'next_lesson', 'attended', 'planned')

    active = 0
    signals = {'ending': 0, 'closed': 0, 'idle': 0, 'no_plan': 0}
    lessons_ahead = Decimal('0')
    progress_sum = 0
    progress_n = 0
    for r in rows:
        active += 1
        balance = js_number(to_decimal(r['balance'] or 0))
        flags = classify(balance, r['last_lesson'], r['next_lesson'], today)
        for k in signals:
            if flags[k]:
                signals[k] += 1
        if balance > 0:
            lessons_ahead += to_decimal(balance)
        planned = int(r['planned'] or 0)
        if planned > 0:
            progress_sum += round(float(to_decimal(r['attended'] or 0)) / planned * 100)
            progress_n += 1

    kpis = {
        'active_students': active,
        'renewal_upsell': signals['ending'] + signals['closed'],
        'idle': signals['idle'],
        'avg_progress': round(progress_sum / progress_n) if progress_n else 0,
        'lessons_ahead': js_number(lessons_ahead),
        'cancellations': sched_repo.cancellations_count(month_start, month_end),
    }
    return {
        'generated_at': msk_now().isoformat(),
        'kpis': kpis,
        'today_stream': _build_today_stream(today),
        'signals': {k: {'count': v} for k, v in signals.items()},
    }


def _build_today_stream(today: datetime.date) -> list[dict]:
    """«Поток дня»: плановые занятия всех активных групп на сегодня."""
    occ = sched_repo.occurrences_on_date(today)
    if not occ:
        return []
    tnames = sched_repo.teacher_names()
    group_ids = sorted({o['group_pk'] for o in occ})
    students_by_group = sched_repo.student_names_by_group(group_ids)
    stream: list[dict] = []
    for o in occ:
        t = o['scheduled_time']
        stream.append({
            'time': t.strftime('%H:%M') if t else None,
            'group_id': o['group_pk'],
            'group_code': o['group_name'],
            'teacher_name': tnames.get(o['teacher_id']),
            'student_names': students_by_group.get(o['group_pk'], []),
            'status': o['status'],
        })
    return stream


def get_summary() -> dict:
    """Сводка из кэша; при промахе/ошибке — свежий расчёт (и запись в кэш).
    Cache — оптимизация, не источник правды."""
    try:
        cached = cache.get(SUMMARY_CACHE_KEY)
    except Exception:
        return build_summary()
    if cached is not None:
        return cached
    summary = build_summary()
    try:
        cache.set(SUMMARY_CACHE_KEY, summary, SUMMARY_TTL)
    except Exception:
        pass
    return summary


def refresh_summary() -> str:
    """Пересчитать сводку и положить в кэш (точка входа Celery-прогрева).
    Возвращает generated_at."""
    summary = build_summary()
    try:
        cache.set(SUMMARY_CACHE_KEY, summary, SUMMARY_TTL)
    except Exception:
        pass
    return summary['generated_at']


def invalidate_registry_cache() -> None:
    """Сбросить кэш сводки (после мутаций баланса — вызывается из payments)."""
    try:
        cache.delete(SUMMARY_CACHE_KEY)
    except Exception:
        pass
