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

На проводе (JSON-ответ API) это разделение проведено явно: `sessions` —
занятия, штуки, без веса (нагрузка преподавателя); `lessons_*` —
уроки курса, с весом half-lesson (программа курса). Не смешивать: это два
разных числа для одних и тех же занятий, и одинаковое английское слово для
обоих уже приводило к путанице на проде.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.db.models import (
    Case, Count, DecimalField, F, Max, OuterRef, Q, Subquery, Sum, Value, When,
)
from django.db.models.functions import Cast, Coalesce, TruncMonth

from apps.groups.course_length import effective_total_lessons_expr
from apps.groups.models import Group
from apps.lessons.models import COURSE_LESSON_TYPES, Lesson


def month_bounds(month: str) -> tuple[str, str]:
    """'YYYY-MM' → ('YYYY-MM-01', 'YYYY-MM-<последний день>'), обе границы включительно.

    Формат `month` здесь НЕ валидируется — вызывающий обязан проверить его
    заранее. Сейчас единственный вызывающий — вьюха (`_MONTH_RE`), которая
    отдаёт 400 на плохой ввод; но `stats.py` — публичный модуль, и следующий
    вызывающий (Celery-таска, management-команда) может забыть про этот
    контракт. Невалидный `month` роняет `ValueError` из `int()`/`datetime.date`,
    а это 500, а не 400.
    """
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
            sessions=Count('id'),
            substitutions=Count('id', filter=Q(original_teacher__isnull=False)),
        )
    )

    by_direction: dict[int, dict] = {}
    by_duration: dict[int, int] = {}
    total_sessions = total_minutes = total_subs = 0

    for row in rows:
        count = row['sessions']
        duration = row['lesson_duration_minutes']
        minutes = count * duration

        total_sessions += count
        total_minutes += minutes
        total_subs += row['substitutions']

        bucket = by_direction.setdefault(row['direction_id'], {
            'direction_id': row['direction_id'],
            'name': row['direction_name'],
            'color': row['direction_color'],
            'sessions': 0,
            'minutes': 0,
        })
        bucket['sessions'] += count
        bucket['minutes'] += minutes

        by_duration[duration] = by_duration.get(duration, 0) + count

    return {
        'total': {
            'sessions': total_sessions,
            'minutes': total_minutes,
            'substitutions': total_subs,
        },
        # Сортировка по убыванию: первым идёт направление, где он работает больше
        # всего — это ответ на вопрос «кто он по профилю». Вторичный ключ по
        # `name` — БД не гарантирует порядок строк без ORDER BY, и при равном
        # числе занятий два направления могли бы менять места между
        # одинаковыми запросами (стабильная сортировка Python здесь не спасает:
        # сама последовательность на входе не детерминирована).
        'by_direction': sorted(by_direction.values(), key=lambda r: (-r['sessions'], r['name'])),
        'by_duration': sorted(
            [{'minutes': m, 'sessions': c} for m, c in by_duration.items()],
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
        .annotate(sessions=Count('id'))
    )
    counts = {row['bucket'].strftime('%Y-%m'): row['sessions'] for row in rows}

    return [{'month': key, 'sessions': counts.get(key, 0)} for key in keys]


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


# Вес занятия в уроках курса: 45 мин = 0.5, иначе 1.
#
# Эта формула продублирована по всему проекту, а не только здесь — это
# известный долг, не тайна этого модуля. Python-копии: apps.lessons.services
# ._step, apps.lessons.repository._step, apps.extra_lessons.services._step,
# apps.scheduling.occurrences._step_for (и ещё несколько мест, где условие
# `duration_minutes == 45` инлайнится без функции — apps.teacher_spa.services/
# .repository, apps.scheduling.services, apps.groups.repository). SQL-копии
# как CASE-выражение ORM: apps.finances.repository._attended_units_case,
# apps.dashboard.registry_service (два инлайн-Case). SQL-копии как сырой CASE
# в RunSQL/raw-запросах: apps.students.repository, apps.renewals.rebuild,
# apps.renewals.management.commands.backfill_renewal_history,
# apps.sync.backfills.rebuild_counters/rebuild_payroll.
#
# Консолидация в одно место — отдельная задача, сюда не входит: она заденет
# как минимум finances и dashboard, а те лежат по разные стороны разбиения
# django_db_setup между приложениями (часть no-op'ит и работает на общей
# journal_test, часть пересоздаёт свежую test_journal_test) — после такой
# правки обязателен полный `pytest -q`, а не прогон по отдельным apps.
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

    `lessons_total` в ответе — `None` (длина курса не задана нигде: ни в группе,
    ни в направлении) ИЛИ `0` (`directions.total_lessons` явно выставлен в 0 —
    CHECK на этом поле допускает `>= 0`, в отличие от `groups.lessons_total`,
    где CHECK `> 0`). Оба случая долетают до потребителя как есть и оба
    означают одно и то же: «длины курса нет». Наивное `done / total` на клиенте
    без проверки на этих значениях даст `NaN` (0/0) или `Infinity` (N/0).
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
            # Cast — не косметика: DecimalField как output_field только
            # ПОДПИСЫВАЕТ Python-значение, конвертер scale навешивается лишь
            # для sqlite/mysql/oracle. На PostgreSQL без явного ::numeric(6,1)
            # SQL отдаёт scale операндов «как есть» — 2 занятия по 90 минут
            # дают Decimal('2') ("2" на проводе), а не Decimal('2.0') ("2.0"),
            # хотя оба идут через один и тот же output_field. Cast заставляет
            # компилятор ORM реально добавить ::numeric(6,1) в SQL и
            # зафиксировать scale, а не только тип Python-объекта.
            lessons_done=Cast(
                Coalesce(done, Value(Decimal('0')), output_field=_PROGRESS_FIELD),
                output_field=_PROGRESS_FIELD,
            ),
            # Алиас, а не `lessons_total=...`: `lessons_total` уже занято
            # ПОЛЕМ модели Group (ручной override длины курса). Django не
            # даёт annotate() перекрыть имя существующего поля — упадёт
            # ValueError при попытке. Аннотация хранит ЭФФЕКТИВНУЮ длину курса
            # (override группы ИЛИ длина направления), поле — только сырой
            # override; это разные вещи, и не стоит "упрощать" до одного имени.
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
