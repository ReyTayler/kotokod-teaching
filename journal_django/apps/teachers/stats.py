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

from django.db.models import Count, F, Q

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
