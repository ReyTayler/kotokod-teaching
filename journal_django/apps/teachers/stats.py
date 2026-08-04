"""
Агрегаты карточки преподавателя — источник данных для
GET /api/admin/teachers/<id>/stats.

Отдельный модуль, а не `repository.py`: тот отвечает за CRUD преподавателя,
здесь — только читающие агрегации по урокам и группам.

Что считается нагрузкой: ТОЛЬКО курсовые уроки
(`lesson_type IN COURSE_LESSON_TYPES`). Доп.уроки (`extra`) и сгорания
(`burned`) — не занятия курса и в нагрузку не входят.

Единицы: «занятий» — штуки (COUNT), «минут» — сумма фактической
`lessons.lesson_duration_minutes`. Вес half-lesson (45 мин = 0.5 урока) здесь
НЕ применяется: это мера программы курса, а не труда преподавателя. Слово
«уроков» в этом модуле относится только к прогрессу курса группы
(`group_progress`), где вес как раз применяется.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.db.models import (
    Case, Count, DecimalField, F, Max, OuterRef, Q, Subquery, Sum, Value, When,
)
from django.db.models.functions import Coalesce, TruncMonth

from apps.groups.course_length import effective_total_lessons_expr
from apps.groups.models import Group
from apps.lessons.models import COURSE_LESSON_TYPES, Lesson


def month_bounds(month: str) -> tuple[str, str]:
    """'YYYY-MM' → ('YYYY-MM-01', 'YYYY-MM-<последний день>'), обе границы включительно."""
    year, mon = int(month[:4]), int(month[5:7])
    first = datetime.date(year, mon, 1)
    next_first = datetime.date(year + (1 if mon == 12 else 0), (mon % 12) + 1, 1)
    return first.isoformat(), (next_first - datetime.timedelta(days=1)).isoformat()


def month_breakdown(teacher_id: int, month: str) -> dict:
    """
    Итог месяца + разбивки по направлениям и длительностям.

    Один запрос с GROUP BY (направление, длительность), свёртка в Python:
    строк — десятки (направлений у преподавателя единицы, длительностей три),
    отдельные запросы под каждую разбивку не окупаются.
    """
    date_from, date_to = month_bounds(month)

    rows = (
        Lesson.objects
        .filter(
            teacher_id=teacher_id,
            lesson_type__in=COURSE_LESSON_TYPES,
            lesson_date__gte=date_from,
            lesson_date__lte=date_to,
        )
        .values(
            'lesson_duration_minutes',
            direction_id=F('group__direction_id'),
            direction_name=F('group__direction__name'),
            direction_color=F('group__direction__color'),
        )
        .annotate(
            lessons=Count('id'),
            substitutions=Count('id', filter=Q(original_teacher__isnull=False)),
        )
    )

    by_direction: dict[int, dict] = {}
    by_duration: dict[int, int] = {}
    total_lessons = total_minutes = total_subs = 0

    for row in rows:
        count = row['lessons']
        duration = row['lesson_duration_minutes']
        minutes = count * duration

        total_lessons += count
        total_minutes += minutes
        total_subs += row['substitutions']

        bucket = by_direction.setdefault(row['direction_id'], {
            'direction_id': row['direction_id'],
            'name': row['direction_name'],
            'color': row['direction_color'],
            'lessons': 0,
            'minutes': 0,
        })
        bucket['lessons'] += count
        bucket['minutes'] += minutes

        by_duration[duration] = by_duration.get(duration, 0) + count

    return {
        'total': {
            'lessons': total_lessons,
            'minutes': total_minutes,
            'substitutions': total_subs,
        },
        # Сортировка по убыванию: первым идёт направление, где он работает больше
        # всего — это ответ на вопрос «кто он по профилю».
        'by_direction': sorted(by_direction.values(), key=lambda r: -r['lessons']),
        'by_duration': sorted(
            [{'minutes': m, 'lessons': c} for m, c in by_duration.items()],
            key=lambda r: -r['minutes'],
        ),
    }


# Глубина спарклайна. Год — минимум, на котором видна сезонность учебного года
# (спад летом, набор в сентябре); меньше — график ни о чём не говорит.
MONTHS_BACK = 12


def _month_keys(month: str, count: int) -> list[str]:
    """['YYYY-MM', …] длиной `count`, заканчивая на `month` включительно."""
    year, mon = int(month[:4]), int(month[5:7])
    keys: list[str] = []
    for _ in range(count):
        keys.append(f'{year}-{mon:02d}')
        mon -= 1
        if mon == 0:
            mon, year = 12, year - 1
    keys.reverse()
    return keys


def monthly_series(teacher_id: int, month: str) -> list[dict]:
    """
    Занятий по месяцам за последние MONTHS_BACK месяцев, включая выбранный.

    Месяцы без занятий возвращаются с нулём: пропуск точки заставил бы
    спарклайн соединить соседние месяцы прямой и показать рост, которого не было.
    """
    keys = _month_keys(month, MONTHS_BACK)
    date_from = f'{keys[0]}-01'
    _, date_to = month_bounds(keys[-1])

    rows = (
        Lesson.objects
        .filter(
            teacher_id=teacher_id,
            lesson_type__in=COURSE_LESSON_TYPES,
            lesson_date__gte=date_from,
            lesson_date__lte=date_to,
        )
        .annotate(bucket=TruncMonth('lesson_date'))
        .values('bucket')
        .annotate(lessons=Count('id'))
    )
    counts = {row['bucket'].strftime('%Y-%m'): row['lessons'] for row in rows}

    return [{'month': key, 'lessons': counts.get(key, 0)} for key in keys]


def last_lesson_date(teacher_id: int) -> str | None:
    """
    Дата последнего проведённого занятия — БЕЗ ограничения месяцем.

    Отвечает на вопрос «преподаватель ещё работает», а не «сколько провёл
    в июле», поэтому выбранный период здесь не при чём.
    """
    value = (
        Lesson.objects
        .filter(teacher_id=teacher_id, lesson_type__in=COURSE_LESSON_TYPES)
        .aggregate(last=Max('lesson_date'))['last']
    )
    return value.isoformat() if value else None


# Вес занятия в уроках курса: 45 мин = 0.5, иначе 1. Та же формула, что в
# apps.lessons.services._step и apps.scheduling.occurrences._step_for, но
# выраженная как SQL-выражение — суммировать надо на стороне БД.
_LESSON_WEIGHT = Case(
    When(lesson_duration_minutes=45, then=Value(Decimal('0.5'))),
    default=Value(Decimal('1')),
    output_field=DecimalField(max_digits=6, decimal_places=1),
)

_PROGRESS_FIELD = DecimalField(max_digits=6, decimal_places=1)


def group_progress(teacher_id: int) -> list[dict]:
    """
    Пройдено курса по каждой группе преподавателя, в УРОКАХ (45 мин = 0.5 урока).

    Считается по группе целиком, а не по этому преподавателю: прогресс курса —
    свойство группы, замена коллеги его не обнуляет и не удваивает.

    Архивные группы включены: карточка показывает их отдельной секцией.

    `lessons_done` — скалярный подзапрос, а НЕ второй Count в общем annotate.
    `groups` уже соединяется с `directions` ради длины курса; агрегат по второй
    связи в том же запросе перемножился бы на строки первой (классическая
    ловушка Django ORM — см. тест test_group_progress_not_inflated_by_members).
    """
    done = Subquery(
        Lesson.objects
        .filter(group=OuterRef('pk'), lesson_type__in=COURSE_LESSON_TYPES)
        .values('group')
        .annotate(done=Sum(_LESSON_WEIGHT))
        .values('done')[:1],
        output_field=_PROGRESS_FIELD,
    )

    rows = (
        Group.objects
        .filter(teacher_id=teacher_id)
        .annotate(
            lessons_done=Coalesce(done, Value(Decimal('0')), output_field=_PROGRESS_FIELD),
            course_total=effective_total_lessons_expr(),
        )
        .values('id', 'lessons_done', 'course_total')
        .order_by('name')
    )

    return [
        {
            'group_id': row['id'],
            'lessons_done': row['lessons_done'],
            'lessons_total': row['course_total'],
        }
        for row in rows
    ]
