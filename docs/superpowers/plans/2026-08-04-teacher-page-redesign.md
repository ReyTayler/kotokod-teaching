# Переработка карточки преподавателя — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Привести `/admin/teachers/:id` к общему виду карточек сущностей (`EntityHero` + плитки + вкладки), починить выпадающий список Telegram, разделить группы на активные/архивные и дать статистику нагрузки преподавателя по месяцам с расшифровкой по направлениям.

**Architecture:** Один новый read-only эндпоинт `GET /api/admin/teachers/<id>/stats` с агрегатами по `lessons` (месяц, направления, длительности, 12-месячный ряд, прогресс курса по группам). Сами группы преподавателя берутся из **существующего** `GET /api/admin/groups?filter[teacher_id]=…&include_inactive=1` — новый эндпоинт для них не нужен. Фронт: страница переписывается на `EntityHero` + `StatTiles` + `Tabs`, `Combobox` получает двухстрочный пункт.

**Tech Stack:** Django 5 + DRF (`apps/teachers`), PostgreSQL, pytest. React 19 + TanStack Query v5 + React Router v7, Recharts 3, CSS-токены (`styles/tokens.css`).

**Спека:** `docs/superpowers/specs/2026-08-04-teacher-page-redesign-design.md`

---

## ⚠️ Контракт переименован после ревью Tasks 1-4

`total.lessons`, `by_direction[].lessons`, `by_duration[].lessons` и
`monthly[].lessons` стали **`sessions`**. Причина: в одном ответе жили две
разные единицы под одним словом — `sessions` это ЗАНЯТИЯ (штуки, 45-мин = 1,
нагрузка преподавателя), а `lessons_done`/`lessons_total` в `group_progress` —
УРОКИ курса (с весом, 45-мин = 0.5). Ровно на этом смешении уже подрывалась
статистика ученика. Теперь слово «lessons» в ответе означает только
взвешенные уроки курса.

Заодно `lessons_done` обёрнут в `Cast(..., numeric(6,1))`: без него
`SUM(CASE 0.5/1)` наследует масштаб операндов и формат прыгает между `"2"` и
`"1.5"`. И задокументировано, что `lessons_total` бывает не только `null`, но
и `0` (CHECK у направления допускает `>= 0`) — оба означают «длины курса нет».

**Код Tasks 1-8 ниже приведён в исходной редакции, до переименования** — он
уже реализован и закоммичен в исправленном виде. Task 9 и далее используют
`sessions`.

## Уточнения относительно первой редакции спеки

Всё перечисленное найдено при написании плана и **уже внесено в спеку** —
здесь повторяется, чтобы исполнитель не искал причину в истории файла.

1. **Эндпоинта `/teachers/<id>/groups` нет.** `GET /api/admin/groups` уже принимает `filter[teacher_id]` и `include_inactive=1` и уже отдаёт `members_count`, `direction_name`, `direction_color`, `slots` (см. `apps/groups/repository.py:178-197`). Дублировать это вторым эндпоинтом — мёртвый код. Не хватало только прогресса курса, он уехал в `/stats` полем `group_progress`.
2. **`Option.disabled` → `Option.muted`.** Занятый чужим преподавателем Telegram-аккаунт остаётся выбираемым (перепривязка при смене преподавателя легитимна, конфликт разрешает бэкенд), но визуально приглушён и сортируется в конец. `disabled` заблокировал бы законный сценарий и потребовал бы обхода disabled-пунктов в клавиатурной навигации.
3. **`nameColor` живёт в существующем `lib/direction-color.ts`,** а не в новом `lib/entity-color.ts`: хеш-функция `hueFromName` там уже есть, просто не экспортирована. Новый файл создал бы третью копию той же формулы.

## Структура файлов

### Бэкенд

| Файл | Ответственность |
|---|---|
| `apps/teachers/stats.py` | **новый.** Только читающие агрегации: месячная разбивка, 12-месячный ряд, дата последнего занятия, прогресс курса по группам. `repository.py` не трогаем — он про CRUD преподавателя |
| `apps/teachers/services.py` | +`get_teacher_stats()` — склейка четырёх агрегатов в один контракт |
| `apps/teachers/views.py` | +`TeacherStatsView` (`IsManagerOrAdmin`, валидация `month`) |
| `apps/teachers/urls.py` | +маршрут `/<int:pk>/stats` |
| `apps/teachers/tests/conftest.py` | +фикстуры направления / группы / уроков (сейчас там только no-op `django_db_setup`) |
| `apps/teachers/tests/test_teacher_stats.py` | **новый.** Все тесты статистики |

### Фронтенд

| Файл | Ответственность |
|---|---|
| `components/ui/icons.tsx` | **новый.** Inline-SVG иконки, первая — `TelegramIcon` |
| `lib/direction-color.ts` | +экспорт `hueOfName()` и `nameColor()` |
| `components/Avatar.tsx` | берёт `hueOfName` вместо своей копии формулы |
| `components/form/Combobox.tsx` | `Option.hint`, `Option.muted`, проп `itemHeight` |
| `styles/forms.css` | починка `.combobox__item` (`height` → `min-height`) |
| `hooks/useTeacherStats.ts` | **новый.** `useTeacherStats(id, month)`, `useTeacherGroups(id)` |
| `pages/teachers/TeacherStatsRow.tsx` | **новый.** Плитки месяца + переключатель ◀ ▶ |
| `pages/teachers/TeacherDirectionsBreakdown.tsx` | **новый.** Полосы по направлениям + спарклайн 12 мес |
| `pages/teachers/TeacherGroupsBlock.tsx` | **новый.** Секции «Активные» / «Архив», строка группы |
| `pages/teachers/TeacherTelegramBlock.tsx` | Компактный вид для `aside` шапки + иконка |
| `pages/teachers/TeacherDetailPage.tsx` | Переписывается на `EntityHero` + `Tabs` |
| `styles/pages/detail.css` | Стили `.tdir-*`, `.tgroup-*`, `.tg-telegram-*`, `.month-nav` |

## Правила, которые ломать нельзя

- **RBAC:** каждая новая вьюха ОБЯЗАНА объявить `permission_classes`. Забыл → эндпоинт открыт всем.
- **Дизайн-токены:** ни одного hardcoded цвета/радиуса/отступа. Только `var(--…)` из `styles/tokens.css`.
- **Native form-элементы запрещены** в admin SPA — только `SelectInput`, `DateInput`, `Checkbox`, `Combobox` из `components/form/`.
- **`npm run build` НЕ запускать.** Собранный `admin-dist/` не должен попасть в коммит.
- **pytest гонять полностью,** а не по приложениям: часть приложений no-op'ит `django_db_setup` (общая `journal_test`), часть пересоздаёт `test_journal_test`. Прогон по частям даёт ложный результат.
- **Коммитить можно, пушить — нет** (в проекте пуш только по явной просьбе пользователя).

---

## Task 1: Месячная разбивка нагрузки

**Files:**
- Create: `journal_django/apps/teachers/stats.py`
- Modify: `journal_django/apps/teachers/tests/conftest.py`
- Test: `journal_django/apps/teachers/tests/test_teacher_stats.py`

- [ ] **Step 1: Добавить фикстуры в conftest**

Сейчас в `apps/teachers/tests/conftest.py` только no-op `django_db_setup`. Дописать в конец файла:

```python
@pytest.fixture
def stats_teacher():
    """Преподаватель под тесты статистики. Чистится DELETE — journal_test общая."""
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__stats_teacher__') RETURNING id")
        teacher_id = cur.fetchone()[0]
    yield teacher_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM lessons WHERE teacher_id = %s', [teacher_id])
        cur.execute('DELETE FROM groups WHERE teacher_id = %s', [teacher_id])
        cur.execute('DELETE FROM teachers WHERE id = %s', [teacher_id])


@pytest.fixture
def stats_direction():
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO directions (name, total_lessons, color, active) "
            "VALUES ('__stats_dir__', 36, '#f0b429', true) RETURNING id"
        )
        direction_id = cur.fetchone()[0]
    yield direction_id
    with connection.cursor() as cur:
        cur.execute('DELETE FROM directions WHERE id = %s', [direction_id])


@pytest.fixture
def make_group(stats_teacher, stats_direction):
    """Фабрика групп преподавателя. Удаление — в teardown stats_teacher."""
    from django.db import connection
    created = []

    def _make(name: str, duration: int = 90, active: bool = True,
              lessons_total=None, direction_id: int | None = None):
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO groups (name, direction_id, teacher_id, is_individual, '
                'lesson_duration_minutes, active, lesson_number_offset, lessons_total) '
                'VALUES (%s, %s, %s, false, %s, %s, 0, %s) RETURNING id',
                [name, direction_id or stats_direction, stats_teacher,
                 duration, active, lessons_total],
            )
            group_id = cur.fetchone()[0]
        created.append(group_id)
        return group_id

    yield _make
    with connection.cursor() as cur:
        for group_id in created:
            cur.execute('DELETE FROM lessons WHERE group_id = %s', [group_id])
            cur.execute('DELETE FROM groups WHERE id = %s', [group_id])


@pytest.fixture
def make_lesson(stats_teacher):
    """Фабрика уроков. `teacher_id` по умолчанию — stats_teacher."""
    from django.db import connection
    counter = {'n': 0}

    def _make(group_id: int, date: str, duration: int = 90,
              lesson_type: str = 'regular', original_teacher_id=None,
              teacher_id: int | None = None):
        counter['n'] += 1
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO lessons (group_id, teacher_id, original_teacher_id, '
                'lesson_date, lesson_number, lesson_duration_minutes, lesson_type, '
                'submitted_at, submitted_by_token) '
                "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s) RETURNING id",
                [group_id, teacher_id or stats_teacher, original_teacher_id,
                 date, counter['n'], duration, lesson_type,
                 f'__stats_tok_{counter["n"]}__'],
            )
            return cur.fetchone()[0]

    return _make
```

- [ ] **Step 2: Написать падающий тест**

Создать `journal_django/apps/teachers/tests/test_teacher_stats.py`:

```python
"""
Тесты агрегатов карточки преподавателя (apps.teachers.stats).

journal_test общая для всех worktree — каждая фикстура чистит за собой DELETE.
"""
from __future__ import annotations

import pytest

from apps.teachers import stats


@pytest.mark.django_db
def test_month_totals_count_lessons_and_minutes(stats_teacher, make_group, make_lesson):
    group = make_group('__stats_g90__', duration=90)
    make_lesson(group, '2026-07-06')
    make_lesson(group, '2026-07-13')

    result = stats.month_breakdown(stats_teacher, '2026-07')

    assert result['total']['lessons'] == 2
    assert result['total']['minutes'] == 180


@pytest.mark.django_db
def test_extra_and_burned_lessons_excluded(stats_teacher, make_group, make_lesson):
    """Доп.урок и сгорание — не нагрузка курса, в счёт не идут."""
    group = make_group('__stats_g_sys__')
    make_lesson(group, '2026-07-06', lesson_type='regular')
    make_lesson(group, '2026-07-07', lesson_type='extra')
    make_lesson(group, '2026-07-08', lesson_type='burned')

    result = stats.month_breakdown(stats_teacher, '2026-07')

    assert result['total']['lessons'] == 1


@pytest.mark.django_db
def test_substitution_counted_and_flagged(stats_teacher, make_group, make_lesson):
    """Замена идёт в общую нагрузку И попадает в счётчик substitutions."""
    group = make_group('__stats_g_sub__')
    make_lesson(group, '2026-07-06')
    make_lesson(group, '2026-07-07', lesson_type='substitution',
                original_teacher_id=stats_teacher)

    result = stats.month_breakdown(stats_teacher, '2026-07')

    assert result['total']['lessons'] == 2
    assert result['total']['substitutions'] == 1


@pytest.mark.django_db
def test_minutes_use_lesson_duration_not_group(stats_teacher, make_group, make_lesson):
    """Длительность берётся с УРОКА: у 90-мин группы бывает 45-мин занятие."""
    group = make_group('__stats_g_mixed__', duration=90)
    make_lesson(group, '2026-07-06', duration=90)
    make_lesson(group, '2026-07-07', duration=45)

    result = stats.month_breakdown(stats_teacher, '2026-07')

    assert result['total']['minutes'] == 135
    by_duration = {r['minutes']: r['lessons'] for r in result['by_duration']}
    assert by_duration == {90: 1, 45: 1}


@pytest.mark.django_db
def test_other_months_not_counted(stats_teacher, make_group, make_lesson):
    group = make_group('__stats_g_bounds__')
    make_lesson(group, '2026-06-30')
    make_lesson(group, '2026-07-01')
    make_lesson(group, '2026-07-31')
    make_lesson(group, '2026-08-01')

    result = stats.month_breakdown(stats_teacher, '2026-07')

    assert result['total']['lessons'] == 2


@pytest.mark.django_db
def test_breakdown_by_direction(stats_teacher, stats_direction, make_group, make_lesson):
    group = make_group('__stats_g_dir__')
    make_lesson(group, '2026-07-06')
    make_lesson(group, '2026-07-13')

    result = stats.month_breakdown(stats_teacher, '2026-07')

    assert len(result['by_direction']) == 1
    row = result['by_direction'][0]
    assert row['direction_id'] == stats_direction
    assert row['name'] == '__stats_dir__'
    assert row['color'] == '#f0b429'
    assert row['lessons'] == 2
    assert row['minutes'] == 180


@pytest.mark.django_db
def test_other_teacher_lessons_not_counted(stats_teacher, make_group, make_lesson):
    """Урок, который в этой же группе провёл кто-то другой, в счёт не идёт."""
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__stats_other__') RETURNING id")
        other_id = cur.fetchone()[0]
    group = make_group('__stats_g_other__')
    make_lesson(group, '2026-07-06')
    make_lesson(group, '2026-07-07', teacher_id=other_id)
    try:
        result = stats.month_breakdown(stats_teacher, '2026-07')
        assert result['total']['lessons'] == 1
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM lessons WHERE teacher_id = %s', [other_id])
            cur.execute('DELETE FROM teachers WHERE id = %s', [other_id])


@pytest.mark.django_db
def test_empty_month_returns_zeros(stats_teacher):
    result = stats.month_breakdown(stats_teacher, '2026-07')

    assert result['total'] == {'lessons': 0, 'minutes': 0, 'substitutions': 0}
    assert result['by_direction'] == []
    assert result['by_duration'] == []
```

- [ ] **Step 3: Запустить тест — убедиться, что падает**

```
cd journal_django && pytest apps/teachers/tests/test_teacher_stats.py -v
```

Ожидается: `ModuleNotFoundError: No module named 'apps.teachers.stats'` на всех тестах.

- [ ] **Step 4: Написать минимальную реализацию**

Создать `journal_django/apps/teachers/stats.py`:

```python
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
```

- [ ] **Step 5: Запустить тест — убедиться, что проходит**

```
cd journal_django && pytest apps/teachers/tests/test_teacher_stats.py -v
```

Ожидается: 8 passed.

- [ ] **Step 6: Коммит**

```bash
git add journal_django/apps/teachers/stats.py journal_django/apps/teachers/tests/
git commit -m "feat(teachers): месячная разбивка нагрузки преподавателя"
```

---

## Task 2: 12-месячный ряд и дата последнего занятия

**Files:**
- Modify: `journal_django/apps/teachers/stats.py`
- Test: `journal_django/apps/teachers/tests/test_teacher_stats.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в конец `test_teacher_stats.py`:

```python
# ---------------------------------------------------------------------------
# monthly_series / last_lesson_date
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_monthly_series_has_exactly_12_points(stats_teacher):
    """Пустые месяцы присутствуют нулями: без них спарклайн склеит соседние
    месяцы и покажет несуществующий рост."""
    series = stats.monthly_series(stats_teacher, '2026-07')

    assert len(series) == 12
    assert series[0]['month'] == '2025-08'
    assert series[-1]['month'] == '2026-07'
    assert all(point['lessons'] == 0 for point in series)


@pytest.mark.django_db
def test_monthly_series_counts_per_month(stats_teacher, make_group, make_lesson):
    group = make_group('__stats_g_series__')
    make_lesson(group, '2026-06-10')
    make_lesson(group, '2026-07-10')
    make_lesson(group, '2026-07-17')

    series = {p['month']: p['lessons'] for p in stats.monthly_series(stats_teacher, '2026-07')}

    assert series['2026-06'] == 1
    assert series['2026-07'] == 2
    assert series['2026-05'] == 0


@pytest.mark.django_db
def test_monthly_series_excludes_system_lessons(stats_teacher, make_group, make_lesson):
    group = make_group('__stats_g_series_sys__')
    make_lesson(group, '2026-07-10', lesson_type='regular')
    make_lesson(group, '2026-07-11', lesson_type='extra')

    series = {p['month']: p['lessons'] for p in stats.monthly_series(stats_teacher, '2026-07')}

    assert series['2026-07'] == 1


@pytest.mark.django_db
def test_last_lesson_date_ignores_selected_month(stats_teacher, make_group, make_lesson):
    """Отвечает на вопрос «преподаватель ещё работает», поэтому месяцем не ограничен."""
    group = make_group('__stats_g_last__')
    make_lesson(group, '2026-07-10')
    make_lesson(group, '2026-08-02')

    assert stats.last_lesson_date(stats_teacher) == '2026-08-02'


@pytest.mark.django_db
def test_last_lesson_date_none_when_never_taught(stats_teacher):
    assert stats.last_lesson_date(stats_teacher) is None
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

```
cd journal_django && pytest apps/teachers/tests/test_teacher_stats.py -k "monthly_series or last_lesson" -v
```

Ожидается: `AttributeError: module 'apps.teachers.stats' has no attribute 'monthly_series'`.

- [ ] **Step 3: Написать реализацию**

В `apps/teachers/stats.py` заменить блок импортов на:

```python
from django.db.models import Count, F, Max, Q
from django.db.models.functions import TruncMonth
```

и дописать в конец файла:

```python
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
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

```
cd journal_django && pytest apps/teachers/tests/test_teacher_stats.py -v
```

Ожидается: 13 passed.

- [ ] **Step 5: Коммит**

```bash
git add journal_django/apps/teachers/stats.py journal_django/apps/teachers/tests/test_teacher_stats.py
git commit -m "feat(teachers): 12-месячный ряд занятий и дата последнего занятия"
```

---

## Task 3: Прогресс курса по группам преподавателя

**Files:**
- Modify: `journal_django/apps/teachers/stats.py`
- Test: `journal_django/apps/teachers/tests/test_teacher_stats.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в конец `test_teacher_stats.py`:

```python
# ---------------------------------------------------------------------------
# group_progress
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_group_progress_counts_course_lessons(stats_teacher, make_group, make_lesson):
    group = make_group('__stats_g_prog__', duration=90)
    make_lesson(group, '2026-07-06')
    make_lesson(group, '2026-07-13')
    make_lesson(group, '2026-07-20', lesson_type='extra')  # сверх курса

    rows = {r['group_id']: r for r in stats.group_progress(stats_teacher)}

    assert float(rows[group]['lessons_done']) == 2.0
    assert rows[group]['lessons_total'] == 36  # из направления


@pytest.mark.django_db
def test_group_progress_applies_half_lesson_weight(stats_teacher, make_group, make_lesson):
    """Прогресс курса меряется в УРОКАХ: 45-мин занятие = 0.5 урока."""
    group = make_group('__stats_g_half__', duration=45)
    make_lesson(group, '2026-07-06', duration=45)
    make_lesson(group, '2026-07-08', duration=45)
    make_lesson(group, '2026-07-10', duration=45)

    rows = {r['group_id']: r for r in stats.group_progress(stats_teacher)}

    assert float(rows[group]['lessons_done']) == 1.5


@pytest.mark.django_db
def test_group_progress_prefers_manual_lessons_total(stats_teacher, make_group):
    """groups.lessons_total перекрывает directions.total_lessons."""
    manual = make_group('__stats_g_manual__', lessons_total=12)
    inherited = make_group('__stats_g_inherit__')

    rows = {r['group_id']: r for r in stats.group_progress(stats_teacher)}

    assert rows[manual]['lessons_total'] == 12
    assert rows[inherited]['lessons_total'] == 36


@pytest.mark.django_db
def test_group_progress_zero_for_group_without_lessons(stats_teacher, make_group):
    group = make_group('__stats_g_empty__')

    rows = {r['group_id']: r for r in stats.group_progress(stats_teacher)}

    assert float(rows[group]['lessons_done']) == 0.0


@pytest.mark.django_db
def test_group_progress_includes_archived_groups(stats_teacher, make_group):
    archived = make_group('__stats_g_arch__', active=False)

    rows = {r['group_id']: r for r in stats.group_progress(stats_teacher)}

    assert archived in rows


@pytest.mark.django_db
def test_group_progress_not_inflated_by_members(stats_teacher, stats_direction,
                                                make_group, make_lesson):
    """
    Регрессия на классическую ловушку Django ORM: два Count по разным связям
    в одном annotate дают декартово произведение. Группа с 3 учениками и
    2 уроками обязана отдать 2 урока, а не 6.
    """
    from django.db import connection
    group = make_group('__stats_g_cartesian__')
    make_lesson(group, '2026-07-06')
    make_lesson(group, '2026-07-13')

    student_ids = []
    with connection.cursor() as cur:
        for i in range(3):
            cur.execute(
                "INSERT INTO students (full_name) VALUES (%s) RETURNING id",
                [f'__stats_student_{i}__'],
            )
            student_id = cur.fetchone()[0]
            student_ids.append(student_id)
            cur.execute(
                'INSERT INTO group_memberships (group_id, student_id, lessons_done, active) '
                'VALUES (%s, %s, 0, true)',
                [group, student_id],
            )
    try:
        rows = {r['group_id']: r for r in stats.group_progress(stats_teacher)}
        assert float(rows[group]['lessons_done']) == 2.0
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [group])
            for student_id in student_ids:
                cur.execute('DELETE FROM students WHERE id = %s', [student_id])
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

```
cd journal_django && pytest apps/teachers/tests/test_teacher_stats.py -k group_progress -v
```

Ожидается: `AttributeError: module 'apps.teachers.stats' has no attribute 'group_progress'`.

- [ ] **Step 3: Написать реализацию**

В `apps/teachers/stats.py` расширить импорты:

```python
from decimal import Decimal

from django.db.models import (
    Case, Count, DecimalField, F, Max, OuterRef, Q, Subquery, Sum, Value, When,
)
from django.db.models.functions import Coalesce, TruncMonth

from apps.groups.course_length import effective_total_lessons_expr
from apps.groups.models import Group
from apps.lessons.models import COURSE_LESSON_TYPES, Lesson
```

и дописать в конец файла:

```python
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
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

```
cd journal_django && pytest apps/teachers/tests/test_teacher_stats.py -v
```

Ожидается: 19 passed.

- [ ] **Step 5: Коммит**

```bash
git add journal_django/apps/teachers/stats.py journal_django/apps/teachers/tests/test_teacher_stats.py
git commit -m "feat(teachers): прогресс курса по группам преподавателя"
```

---

## Task 4: Эндпоинт `/api/admin/teachers/<id>/stats`

**Files:**
- Modify: `journal_django/apps/teachers/services.py`
- Modify: `journal_django/apps/teachers/views.py`
- Modify: `journal_django/apps/teachers/urls.py`
- Test: `journal_django/apps/teachers/tests/test_teacher_stats_api.py`

- [ ] **Step 1: Написать падающий тест**

Создать `journal_django/apps/teachers/tests/test_teacher_stats_api.py`:

```python
"""
E2E тесты для GET /api/admin/teachers/<id>/stats.

RBAC: read-only, доступ у manager/admin/superadmin; teacher и аноним — мимо.
"""
from __future__ import annotations

import pytest

BASE_URL = '/api/admin/teachers'


def _url(teacher_id: int, month: str | None = None) -> str:
    suffix = f'?month={month}' if month else ''
    return f'{BASE_URL}/{teacher_id}/stats{suffix}'


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_anonymous_returns_401(anon_client, stats_teacher):
    assert anon_client.get(_url(stats_teacher)).status_code == 401


@pytest.mark.django_db
def test_teacher_role_returns_403(teacher_client, stats_teacher):
    assert teacher_client.get(_url(stats_teacher)).status_code == 403


@pytest.mark.django_db
def test_manager_returns_200(manager_client, stats_teacher):
    assert manager_client.get(_url(stats_teacher)).status_code == 200


@pytest.mark.django_db
def test_admin_returns_200(admin_client, stats_teacher):
    assert admin_client.get(_url(stats_teacher)).status_code == 200


# ---------------------------------------------------------------------------
# Контракт
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_response_shape(admin_client, stats_teacher, make_group, make_lesson):
    group = make_group('__api_stats_group__')
    make_lesson(group, '2026-07-06')

    body = admin_client.get(_url(stats_teacher, '2026-07')).json()

    assert body['month'] == '2026-07'
    assert body['total'] == {'lessons': 1, 'minutes': 90, 'substitutions': 0}
    assert body['last_lesson_date'] == '2026-07-06'
    assert len(body['monthly']) == 12
    assert len(body['by_direction']) == 1
    assert len(body['by_duration']) == 1
    assert any(r['group_id'] == group for r in body['group_progress'])


@pytest.mark.django_db
def test_month_defaults_to_current(admin_client, stats_teacher):
    from apps.core.utils.dates import msk_now

    body = admin_client.get(_url(stats_teacher)).json()

    assert body['month'] == msk_now().strftime('%Y-%m')


@pytest.mark.django_db
@pytest.mark.parametrize('bad', ['2026-13', '2026', 'июль', '2026-7', '2026-00'])
def test_invalid_month_returns_400(admin_client, stats_teacher, bad):
    resp = admin_client.get(_url(stats_teacher, bad))

    assert resp.status_code == 400
    assert 'error' in resp.json()


@pytest.mark.django_db
def test_unknown_teacher_returns_404(admin_client):
    resp = admin_client.get(_url(999999999))

    assert resp.status_code == 404
    assert resp.json() == {'error': 'Not found'}
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

```
cd journal_django && pytest apps/teachers/tests/test_teacher_stats_api.py -v
```

Ожидается: 404 вместо 200/400 на всех тестах — маршрута ещё нет.

- [ ] **Step 3: Добавить сервис**

В конец `journal_django/apps/teachers/services.py` дописать (и добавить импорт `from apps.teachers import repository, stats` вместо текущего одиночного):

```python
def get_teacher_stats(teacher_id: int, month: str) -> dict:
    """
    Полный набор чисел карточки преподавателя за месяц.

    Четыре агрегата (месяц, ряд по месяцам, дата последнего занятия, прогресс
    групп) склеиваются здесь, а не на фронте: иначе карточка делала бы четыре
    запроса вместо одного, а VPS у нас 2 CPU.
    """
    breakdown = stats.month_breakdown(teacher_id, month)
    return {
        'month': month,
        'last_lesson_date': stats.last_lesson_date(teacher_id),
        'total': breakdown['total'],
        'by_direction': breakdown['by_direction'],
        'by_duration': breakdown['by_duration'],
        'monthly': stats.monthly_series(teacher_id, month),
        'group_progress': stats.group_progress(teacher_id),
    }
```

- [ ] **Step 4: Добавить вьюху**

В `journal_django/apps/teachers/views.py` дописать импорты:

```python
import re

from apps.core.permissions import IsManagerOrAdmin, ReadStaffWriteSuperAdmin
from apps.core.utils.dates import msk_now
```

и класс в конец файла (перед секцией `# Helpers`):

```python
# Строгий формат месяца. Год без ограничений (архив уходит вглубь), месяц 01–12:
# '2026-7' и '2026-13' обязаны отваливаться на входе, а не превращаться в пустой
# период молча.
_MONTH_RE = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')


class TeacherStatsView(APIView):
    """
    GET /api/admin/teachers/:id/stats?month=YYYY-MM — показатели преподавателя.

    Read-only, поэтому IsManagerOrAdmin, а не ReadStaffWriteSuperAdmin:
    менеджеру статистика нужна, а писать здесь нечего.
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        if services.get_teacher(pk) is None:
            raise NotFound({'error': 'Not found'})

        month = request.query_params.get('month') or msk_now().strftime('%Y-%m')
        if not _MONTH_RE.match(month):
            return Response(
                {'error': f"Invalid month '{month}', expected YYYY-MM"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(services.get_teacher_stats(pk, month))
```

- [ ] **Step 5: Добавить тест на число запросов**

Дописать в конец `journal_django/apps/teachers/tests/test_teacher_stats.py`:

```python
# ---------------------------------------------------------------------------
# Производительность
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_stats_uses_fixed_number_of_queries(django_assert_num_queries, stats_teacher,
                                            make_group, make_lesson):
    """
    Четыре агрегата — четыре запроса, независимо от числа групп и уроков.

    Проверяется на СЕРВИСЕ, а не через API: в замер вьюхи попали бы ещё запросы
    аутентификации, и тест ломался бы от любой правки в auth. Здесь же любой
    N+1 (например, дозапрос направления на каждую группу) виден сразу.
    """
    from apps.teachers import services

    for i in range(3):
        group = make_group(f'__stats_g_nplus1_{i}__')
        make_lesson(group, '2026-07-06')
        make_lesson(group, '2026-07-13')

    with django_assert_num_queries(4):
        services.get_teacher_stats(stats_teacher, '2026-07')
```

Если фактическое число окажется другим — **не подгонять константу вслепую**:
посмотреть `django_assert_num_queries` в выводе, убедиться, что лишние запросы
не растут с числом групп, и только тогда поправить ожидание с комментарием.

- [ ] **Step 6: Добавить маршрут**

В `journal_django/apps/teachers/urls.py` заменить импорт и `urlpatterns`:

```python
from apps.teachers.views import TeacherDetailView, TeacherListCreateView, TeacherStatsView

urlpatterns = [
    path('', TeacherListCreateView.as_view(), name='teachers-list-create'),
    path('/<int:pk>', TeacherDetailView.as_view(), name='teachers-detail'),
    path('/<int:pk>/stats', TeacherStatsView.as_view(), name='teachers-stats'),
    path('/<int:teacher_id>/telegram', TeacherTelegramView.as_view(),
         name='teacher-telegram'),
]
```

- [ ] **Step 7: Запустить тест — убедиться, что проходит**

```
cd journal_django && pytest apps/teachers/ -v
```

Ожидается: все тесты teachers зелёные (20 из stats + 12 новых API + существующие).

- [ ] **Step 8: Полный прогон pytest**

```
cd journal_django && pytest -q
```

Ожидается: столько же passed, сколько до начала работы, плюс новые. Ни одного failed.
Прогон **обязательно полный**: частичный даёт ложный результат из-за разного
`django_db_setup` в разных приложениях.

- [ ] **Step 9: Коммит**

```bash
git add journal_django/apps/teachers/
git commit -m "feat(teachers): эндпоинт статистики преподавателя"
```

---

## Task 5: Починка Combobox + иконка Telegram

**Files:**
- Create: `journal_django/frontend/admin-src/src/components/ui/icons.tsx`
- Modify: `journal_django/frontend/admin-src/src/components/form/Combobox.tsx`
- Modify: `journal_django/frontend/admin-src/src/styles/forms.css:120-141`

Фронтенд-тестов в проекте нет — проверка ручная, в браузере.

- [ ] **Step 1: Создать модуль иконок**

Создать `journal_django/frontend/admin-src/src/components/ui/icons.tsx`:

```tsx
/**
 * Inline-SVG иконки. Внешних спрайтов и CDN нет — CSP `script-src 'self'`
 * и `img-src 'self'` не пропустят ни то, ни другое.
 *
 * Цвет — всегда `currentColor`: иконка наследует цвет текста и работает
 * в обеих темах без отдельных правил.
 */
interface IconProps {
  size?: number;
  className?: string;
}

export function TelegramIcon({ size = 16, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <path d="M21.9 4.3 18.7 20c-.2 1-.9 1.3-1.8.8l-5-3.7-2.4 2.3c-.3.3-.5.5-1 .5l.4-5.1L18.2 6c.4-.4-.1-.6-.6-.2L6.2 12.9l-5-1.6c-1-.3-1-1 .2-1.5l19.4-7.5c.8-.3 1.5.2 1.2 2z" />
    </svg>
  );
}
```

- [ ] **Step 2: Расширить Combobox**

В `journal_django/frontend/admin-src/src/components/form/Combobox.tsx` заменить
`interface Option`, `interface Props`, константу `ITEM_HEIGHT`, сигнатуру компонента,
`filtered` и рендер пункта списка.

Заменить блок с 4-й по 20-ю строку (от `interface Option` до строки с `export function Combobox(...)`):

```tsx
export interface Option {
  value: string;
  label: string;
  /**
   * Вторая строка пункта: ник, пометка «занят такой-то». Участвует в поиске —
   * ник человек помнит чаще, чем полное имя из профиля Telegram.
   */
  hint?: string;
  /**
   * Пункт приглушён, но выбираем. Именно приглушён, а не disabled: занятый
   * аккаунт законно перепривязать (человек сменил преподавателя), конфликт
   * разрешает бэкенд, а не форма.
   */
  muted?: boolean;
}

interface Props {
  value: string;
  onChange: (value: string) => void;
  options: Option[];
  placeholder?: string;
  /** Сколько строк помещается в выпадашке. Остальное прокручивается. По умолчанию 10. */
  maxVisible?: number;
  /**
   * Высота строки в пикселях — из неё считается maxHeight выпадашки.
   * Двухстрочные пункты (с `hint`) выше: передавать 52, иначе список
   * обрезается на середине пункта.
   */
  itemHeight?: number;
}

export function Combobox({
  value, onChange, options, placeholder, maxVisible = 10, itemHeight = 36,
}: Props) {
```

Заменить `filtered` (поиск идёт и по `hint`):

```tsx
  const filtered = useMemo(() => {
    if (!open || !query.trim()) return options;
    const q = query.toLowerCase();
    return options.filter(
      (o) => o.label.toLowerCase().includes(q) || (o.hint || '').toLowerCase().includes(q),
    );
  }, [options, query, open]);
```

Заменить `maxHeight` в `<Floating>`:

```tsx
        maxHeight={maxVisible * itemHeight + 8}
```

Заменить содержимое `<li>` (пункт списка):

```tsx
              <li
                key={opt.value}
                role="option"
                aria-selected={opt.value === value}
                className={
                  `combobox__item${i === highlight ? ' is-highlighted' : ''}` +
                  `${opt.value === value ? ' is-selected' : ''}` +
                  `${opt.muted ? ' is-muted' : ''}`
                }
                onMouseEnter={() => setHighlight(i)}
                onMouseDown={(e) => { e.preventDefault(); choose(opt); }}
              >
                <span className="combobox__item-label">{opt.label}</span>
                {opt.hint && <span className="combobox__item-hint">{opt.hint}</span>}
              </li>
```

- [ ] **Step 3: Починить CSS пункта**

В `journal_django/frontend/admin-src/src/styles/forms.css` заменить блок
`.combobox__item` (строки 120–141) на:

```css
/* height → min-height: жёсткая высота резала подписи, которые не влезали в одну
   строку, — текст переносился и налезал на соседний пункт (список привязки
   Telegram). Пункт теперь растёт под содержимое. */
.combobox__item {
  padding: 7px 10px;
  cursor: pointer;
  font-size: 14px;
  min-height: 34px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  box-sizing: border-box;
  border-radius: var(--r-xs, 4px);
  color: var(--text2);
  transition: background var(--t-fast) var(--ease);
}
.combobox__item-label {
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.combobox__item-hint {
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.3;
  color: var(--text4);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.combobox__item.is-muted .combobox__item-label { color: var(--text3); }
.combobox__item.is-highlighted {
  background: var(--bg3);
  color: var(--text);
}
.combobox__item.is-selected {
  font-weight: 500;
  color: var(--accent);
}
.combobox__item.is-selected.is-highlighted {
  background: var(--accent-soft);
}
```

- [ ] **Step 4: Проверить, что токен `--r-xs` существует**

```
cd journal_django/frontend/admin-src/src/styles && grep -n "r-xs\|--r-sm" tokens.css
```

Если `--r-xs` в `tokens.css` нет — заменить `var(--r-xs, 4px)` на `var(--r-sm)`.
Хардкод `4px` в проекте недопустим, fallback в `var()` оставлять нельзя.

- [ ] **Step 5: Проверить типы**

```
cd journal_django/frontend/admin-src && npx tsc --noEmit
```

Ожидается: без ошибок. **`npm run build` не запускать** — собранный `admin-dist/`
не должен попасть в коммит.

- [ ] **Step 6: Коммит**

```bash
git add journal_django/frontend/admin-src/src/components/ui/icons.tsx \
        journal_django/frontend/admin-src/src/components/form/Combobox.tsx \
        journal_django/frontend/admin-src/src/styles/forms.css
git commit -m "fix(admin): пункт combobox больше не режет длинные подписи"
```

---

## Task 6: Общий цвет сущности из имени

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/direction-color.ts`
- Modify: `journal_django/frontend/admin-src/src/components/Avatar.tsx`

- [ ] **Step 1: Экспортировать хеш-функцию**

Заменить `journal_django/frontend/admin-src/src/lib/direction-color.ts` целиком:

```ts
import type { Direction } from './types';

const FALLBACK = '#0d9488';

export function directionColor(input: Direction | string | null | undefined): string {
  if (!input) return FALLBACK;
  if (typeof input === 'object') {
    if (input.color && /^#[0-9a-fA-F]{6}$/.test(input.color)) return input.color;
    return nameColor(input.name || '');
  }
  if (/^#[0-9a-fA-F]{6}$/.test(input)) return input;
  return nameColor(input);
}

/**
 * Тон из имени — детерминированный, без хранения цвета в БД.
 *
 * Экспортируется отдельно от nameColor, потому что Avatar строит из одного тона
 * три цвета (подложка, рамка, текст) с разной светлотой. Вторая копия формулы
 * дала бы разный цвет у аватара и монограммы одного и того же человека.
 */
export function hueOfName(name: string): number {
  return [...String(name || '')].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
}

/** Насыщенный цвет сущности, у которой нет своего поля цвета (преподаватель). */
export function nameColor(name: string): string {
  return `hsl(${hueOfName(name)}, 55%, 42%)`;
}
```

- [ ] **Step 2: Перевести Avatar на общую формулу**

Заменить `journal_django/frontend/admin-src/src/components/Avatar.tsx` целиком:

```tsx
import { hueOfName } from '../lib/direction-color';

interface Props { name: string; size?: number; }

export function Avatar({ name, size = 32 }: Props) {
  const parts = name.trim().split(/\s+/);
  const initials = (parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2)).toUpperCase();
  const hue = hueOfName(name);
  return (
    <div
      className="avatar"
      style={{
        width: size,
        height: size,
        fontSize: Math.round(size * 0.38),
        background: `hsl(${hue},55%,92%)`,
        border: `2px solid hsl(${hue},50%,80%)`,
        color: `hsl(${hue},55%,35%)`,
      }}
    >
      {initials}
    </div>
  );
}
```

- [ ] **Step 3: Проверить типы**

```
cd journal_django/frontend/admin-src && npx tsc --noEmit
```

Ожидается: без ошибок.

- [ ] **Step 4: Коммит**

```bash
git add journal_django/frontend/admin-src/src/lib/direction-color.ts \
        journal_django/frontend/admin-src/src/components/Avatar.tsx
git commit -m "refactor(admin): единая формула цвета сущности по имени"
```

---

## Task 7: Хуки статистики и групп преподавателя

**Files:**
- Create: `journal_django/frontend/admin-src/src/hooks/useTeacherStats.ts`

- [ ] **Step 1: Создать хуки**

Создать `journal_django/frontend/admin-src/src/hooks/useTeacherStats.ts`:

```ts
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api, fetchAllPages } from '../lib/api';
import type { Group } from '../lib/types';

export interface TeacherDirectionStat {
  direction_id: number;
  name: string;
  color: string | null;
  lessons: number;
  minutes: number;
}

export interface TeacherGroupProgress {
  group_id: number;
  /** numeric(6,1) из PG приходит СТРОКОЙ — приводить Number() на месте использования. */
  lessons_done: string | number;
  lessons_total: number | null;
}

export interface TeacherStats {
  month: string;
  last_lesson_date: string | null;
  total: { lessons: number; minutes: number; substitutions: number };
  by_direction: TeacherDirectionStat[];
  by_duration: { minutes: number; lessons: number }[];
  monthly: { month: string; lessons: number }[];
  group_progress: TeacherGroupProgress[];
}

/**
 * Показатели преподавателя за месяц.
 *
 * keepPreviousData обязателен: без него переключение месяца ◀ ▶ схлопывает
 * плитки в скелет на каждый клик (правило всех server-paginated хуков проекта).
 */
export function useTeacherStats(teacherId: number, month: string) {
  return useQuery({
    queryKey: ['teacher-stats', teacherId, month],
    queryFn: () =>
      api<TeacherStats>('GET', `/api/admin/teachers/${teacherId}/stats?month=${month}`),
    enabled: Number.isFinite(teacherId) && teacherId > 0,
    placeholderData: keepPreviousData,
  });
}

/**
 * Группы одного преподавателя, включая архивные.
 *
 * Отдельного эндпоинта нет и не нужно: список групп уже принимает
 * filter[teacher_id] и отдаёт members_count, направление и слоты. Раньше
 * страница тянула useGroupsAll(true) — ВСЕ группы школы — и фильтровала
 * на клиенте.
 */
export function useTeacherGroups(teacherId: number) {
  return useQuery({
    queryKey: ['teacher-groups', teacherId],
    queryFn: () => {
      const qs = new URLSearchParams({
        sort_by: 'name',
        sort_dir: 'asc',
        include_inactive: '1',
      });
      qs.set('filter[teacher_id]', String(teacherId));
      return fetchAllPages<Group>('/api/admin/groups', qs);
    },
    enabled: Number.isFinite(teacherId) && teacherId > 0,
    staleTime: 60_000,
  });
}
```

- [ ] **Step 2: Проверить типы**

```
cd journal_django/frontend/admin-src && npx tsc --noEmit
```

Ожидается: без ошибок.

- [ ] **Step 3: Коммит**

```bash
git add journal_django/frontend/admin-src/src/hooks/useTeacherStats.ts
git commit -m "feat(admin): хуки статистики и групп преподавателя"
```

---

## Task 8: Плитки показателей за месяц

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/teachers/TeacherStatsRow.tsx`
- Modify: `journal_django/frontend/admin-src/src/styles/pages/detail.css`

- [ ] **Step 1: Создать компонент**

Создать `journal_django/frontend/admin-src/src/pages/teachers/TeacherStatsRow.tsx`:

```tsx
import { StatTiles, type StatTile } from '../../components/detail/StatTiles';
import { MONTHS_RU } from '../../lib/slots';
import type { Group } from '../../lib/types';
import type { TeacherStats } from '../../hooks/useTeacherStats';

interface Props {
  month: string;
  onMonthChange: (month: string) => void;
  stats: TeacherStats | undefined;
  groups: Group[];
}

/** 'YYYY-MM' + сдвиг в месяцах → 'YYYY-MM'. */
export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number);
  const zero = y * 12 + (m - 1) + delta;
  return `${Math.floor(zero / 12)}-${String((zero % 12) + 1).padStart(2, '0')}`;
}

/** 'YYYY-MM' → 'Июль 2026'. */
function monthLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  return `${MONTHS_RU[m - 1]} ${y}`;
}

/** 3750 → '62,5'. Часы астрономические: 45/60/90 мин не делятся на академчас ровно. */
function hours(minutes: number): string {
  return (minutes / 60).toFixed(1).replace('.', ',');
}

/** [{minutes:90,lessons:34}, …] → '90 мин ×34 · 45 мин ×8'. */
function durationsLabel(rows: TeacherStats['by_duration']): string {
  if (rows.length === 0) return 'занятий не было';
  return rows.map((r) => `${r.minutes} мин ×${r.lessons}`).join(' · ');
}

/**
 * Ключевые числа преподавателя.
 *
 * Месяцем управляются ТОЛЬКО «Занятий» и «Часов» — «Учеников» и «Группы» это
 * текущий срез, и подписи это проговаривают: иначе рядом стоят четыре числа,
 * из которых два за период, а два нет, и разницу никто не заметит.
 */
export default function TeacherStatsRow({ month, onMonthChange, stats, groups }: Props) {
  const active = groups.filter((g) => g.active);
  const archived = groups.length - active.length;
  const students = active.reduce((sum, g) => sum + (g.members_count ?? 0), 0);
  const avgSize = active.length ? (students / active.length).toFixed(1).replace('.', ',') : '0';

  const total = stats?.total;

  const tiles: StatTile[] = [
    {
      label: 'Занятий',
      value: total?.lessons ?? '—',
      sub: total && total.substitutions > 0
        ? `из них ${total.substitutions} замен`
        : 'курсовых, без доп.уроков',
    },
    {
      label: 'Часов',
      value: total ? hours(total.minutes) : '—',
      sub: stats ? durationsLabel(stats.by_duration) : '',
    },
    {
      label: 'Учеников',
      value: students,
      sub: active.length ? `в среднем ${avgSize} на группу` : 'активных групп нет',
    },
    {
      label: 'Групп',
      value: `${active.length}${archived ? ` / ${archived}` : ''}`,
      sub: archived ? 'активных / в архиве' : 'активных',
    },
  ];

  return (
    <div className="tstats">
      <div className="month-nav">
        <button
          type="button"
          className="month-nav__btn"
          onClick={() => onMonthChange(shiftMonth(month, -1))}
          aria-label="Предыдущий месяц"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
        <span className="month-nav__label">{monthLabel(month)}</span>
        <button
          type="button"
          className="month-nav__btn"
          onClick={() => onMonthChange(shiftMonth(month, 1))}
          aria-label="Следующий месяц"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      </div>
      <StatTiles items={tiles} />
    </div>
  );
}
```

- [ ] **Step 2: Добавить стили переключателя месяца**

Дописать в конец `journal_django/frontend/admin-src/src/styles/pages/detail.css`:

```css
/* ============================================================
   Карточка преподавателя
   ============================================================ */

.tstats { display: flex; flex-direction: column; gap: var(--space-3); }

.month-nav { display: flex; align-items: center; gap: var(--space-2); }
.month-nav__btn {
  width: 28px; height: 28px;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  color: var(--text3);
  cursor: pointer;
  transition: background var(--t-fast) var(--ease), color var(--t-fast) var(--ease);
}
.month-nav__btn:hover { background: var(--bg3); color: var(--text); }
.month-nav__btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.month-nav__label {
  font-size: 13px; font-weight: 600; color: var(--text2);
  min-width: 130px;
}
```

- [ ] **Step 3: Проверить, что все использованные токены существуют**

```
cd journal_django/frontend/admin-src/src/styles && grep -n -- "--space-2\|--space-3\|--r-sm\|--t-fast\|--ease\|--bg2\|--bg3\|--border\b\|--text2\|--text3\|--accent\b" tokens.css | head -20
```

Ожидается: каждый токен найден. Отсутствующий `var()` схлопывается молча —
цвет просто не применится, и это заметно не сразу.

- [ ] **Step 4: Проверить типы**

```
cd journal_django/frontend/admin-src && npx tsc --noEmit
```

Ожидается: без ошибок (компонент пока никем не используется — это нормально,
`noUnusedLocals` на экспортируемый default не срабатывает).

- [ ] **Step 5: Коммит**

```bash
git add journal_django/frontend/admin-src/src/pages/teachers/TeacherStatsRow.tsx \
        journal_django/frontend/admin-src/src/styles/pages/detail.css
git commit -m "feat(admin): плитки показателей преподавателя за месяц"
```

---

## Task 9: Расшифровка по направлениям и спарклайн

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/teachers/TeacherDirectionsBreakdown.tsx`
- Modify: `journal_django/frontend/admin-src/src/styles/pages/detail.css`

- [ ] **Step 1: Создать компонент**

Создать `journal_django/frontend/admin-src/src/pages/teachers/TeacherDirectionsBreakdown.tsx`:

```tsx
import type { CSSProperties } from 'react';
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis } from 'recharts';
import { EmptyState } from '../../components/ui/EmptyState';
import { directionColor } from '../../lib/direction-color';
import { MONTHS_RU } from '../../lib/slots';
import type { TeacherStats } from '../../hooks/useTeacherStats';

interface Props {
  stats: TeacherStats | undefined;
}

/** 'YYYY-MM' → 'июл'. */
function shortMonth(month: string): string {
  const m = Number(month.split('-')[1]);
  return MONTHS_RU[m - 1].slice(0, 3).toLowerCase();
}

/**
 * Вкладка «Обзор»: чем именно преподаватель занят и как менялась его нагрузка.
 *
 * Полоса красится цветом направления — тем же, что в DirTag и на карточке
 * группы: направление обязано выглядеть одинаково во всех разделах.
 */
export default function TeacherDirectionsBreakdown({ stats }: Props) {
  const rows = stats?.by_direction ?? [];
  const max = rows.reduce((acc, r) => Math.max(acc, r.lessons), 0);
  const series = (stats?.monthly ?? []).map((p) => ({ ...p, label: shortMonth(p.month) }));

  return (
    <div className="tbreak">
      <section className="tbreak__col">
        <h3 className="sub-header">Направления за месяц</h3>
        {rows.length === 0 ? (
          <EmptyState hint="Выберите другой месяц стрелками над плитками.">
            Занятий за этот месяц нет
          </EmptyState>
        ) : (
          <div className="tdir-list">
            {rows.map((r) => (
              <div
                key={r.direction_id}
                className="tdir"
                style={{ '--entity-c': directionColor(r.color || r.name) } as CSSProperties}
              >
                <div className="tdir__name">{r.name}</div>
                <div className="tdir__bar">
                  <div
                    className="tdir__fill"
                    style={{ width: max ? `${(r.lessons / max) * 100}%` : '0%' }}
                  />
                </div>
                <div className="tdir__count">{r.lessons}</div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="tbreak__col">
        <h3 className="sub-header">Занятий по месяцам</h3>
        <div className="tspark">
          <ResponsiveContainer width="100%" height={140}>
            <AreaChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
              <defs>
                <linearGradient id="teacher-load" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                interval="preserveStartEnd"
                tick={{ fontSize: 11, fill: 'var(--text4)' }}
              />
              <Tooltip
                cursor={{ stroke: 'var(--border)' }}
                contentStyle={{
                  background: 'var(--bg2)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--r-sm)',
                  fontSize: 12,
                }}
                labelFormatter={(label) => String(label)}
                formatter={(value: number) => [value, 'занятий']}
              />
              <Area
                type="monotone"
                dataKey="lessons"
                stroke="var(--accent)"
                strokeWidth={2}
                fill="url(#teacher-load)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Проверить API Recharts, установленного в проекте**

```
cd journal_django/frontend/admin-src && node -e "console.log(require('./package.json').dependencies.recharts)"
```

Ожидается: версия `^3.x`. Если major другой — сверить сигнатуры `Tooltip`/`Area`
с `journal_django/frontend/admin-src/src/pages/dashboard/MonthlyAreaChart.tsx`,
который уже работает, и привести к нему.

- [ ] **Step 3: Добавить стили**

Дописать в конец `journal_django/frontend/admin-src/src/styles/pages/detail.css`:

```css
.tbreak {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--space-6);
}
.tbreak__col { min-width: 0; }

.tdir-list { display: flex; flex-direction: column; gap: var(--space-2); }
.tdir {
  display: grid;
  grid-template-columns: minmax(0, 140px) minmax(0, 1fr) 40px;
  align-items: center;
  gap: var(--space-3);
}
.tdir__name {
  font-size: 13px; color: var(--text2);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.tdir__bar {
  height: 8px; border-radius: 999px;
  background: var(--bg4); overflow: hidden;
}
.tdir__fill {
  height: 100%; border-radius: 999px;
  background: var(--entity-c);
  transition: width .4s var(--ease);
}
.tdir__count {
  font-family: var(--font-mono); font-variant-numeric: tabular-nums;
  font-size: 14px; font-weight: 600; color: var(--text); text-align: right;
}

.tspark { width: 100%; }

@media (max-width: 900px) {
  .tbreak { grid-template-columns: minmax(0, 1fr); }
}
```

- [ ] **Step 4: Проверить типы**

```
cd journal_django/frontend/admin-src && npx tsc --noEmit
```

Ожидается: без ошибок.

- [ ] **Step 5: Коммит**

```bash
git add journal_django/frontend/admin-src/src/pages/teachers/TeacherDirectionsBreakdown.tsx \
        journal_django/frontend/admin-src/src/styles/pages/detail.css
git commit -m "feat(admin): расшифровка нагрузки преподавателя по направлениям"
```

---

## Task 10: Группы преподавателя — активные и архивные

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/teachers/TeacherGroupsBlock.tsx`
- Modify: `journal_django/frontend/admin-src/src/styles/pages/detail.css`

- [ ] **Step 1: Создать компонент**

Создать `journal_django/frontend/admin-src/src/pages/teachers/TeacherGroupsBlock.tsx`:

```tsx
import { useMemo, useState, type CSSProperties } from 'react';
import { useNavigate } from 'react-router-dom';
import { EmptyState } from '../../components/ui/EmptyState';
import { TextInput } from '../../components/form/TextInput';
import { directionColor } from '../../lib/direction-color';
import { formatSlot } from '../../lib/slots';
import type { Group } from '../../lib/types';
import type { TeacherGroupProgress } from '../../hooks/useTeacherStats';

interface Props {
  groups: Group[];
  progress: TeacherGroupProgress[];
}

interface Row {
  group: Group;
  done: number;
  total: number | null;
  pct: number | null;
}

function buildRows(groups: Group[], progress: TeacherGroupProgress[]): Row[] {
  const byId = new Map(progress.map((p) => [p.group_id, p]));
  return groups.map((group) => {
    const p = byId.get(group.id);
    const done = Number(p?.lessons_done ?? 0);
    const total = p?.lessons_total ?? null;
    return {
      group,
      done,
      total,
      // Прогресс зажат на 100 %: доп.уроки сверх плана давали 37/36 = 102,8 %.
      pct: total ? Math.min(100, Math.round((done / total) * 100)) : null,
    };
  });
}

/** Одна строка группы: имя, направление, формат, расписание, состав, прогресс. */
function GroupRow({ row }: { row: Row }) {
  const navigate = useNavigate();
  const { group, done, total, pct } = row;
  const open = () => navigate(`/admin/groups/${group.id}`);
  const slots = (group.slots || []).map(formatSlot).join(' · ');

  return (
    <div
      className={`tgroup${group.active ? '' : ' is-archived'}`}
      role="button"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      }}
      style={{ '--entity-c': directionColor(group.direction_color || group.direction_name || '') } as CSSProperties}
    >
      <div className="tgroup__head">
        <span className="tgroup__name">{group.name}</span>
        <span className="tgroup__dir">{group.direction_name || '—'}</span>
        <span className="tgroup__id">#{group.id}</span>
      </div>
      <div className="tgroup__meta">
        <span>{group.is_individual ? 'индивидуальная' : 'групповая'}</span>
        <span className="tgroup__mono">{group.lesson_duration_minutes} мин</span>
        {slots && <span className="tgroup__mono">{slots}</span>}
      </div>
      <div className="tgroup__stats">
        <span className="tgroup__students">
          <b>{group.members_count ?? 0}</b> {group.is_individual ? 'ученик' : 'учеников'}
        </span>
        {pct == null ? (
          <span className="tgroup__nocourse">длина курса не задана</span>
        ) : (
          <>
            <span className="tgroup__mono">курс {done} / {total}</span>
            <span className="tgroup__bar">
              <span className="tgroup__fill" style={{ width: `${pct}%` }} />
            </span>
            <span className="tgroup__pct">{pct}%</span>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * Группы преподавателя: активные отдельно, архив отдельно и свёрнут.
 *
 * До этого 18 групп шли одним плоским списком карточек по 90 px, каждая из
 * которых несла два факта. Строка вместо карточки даёт расписание, состав и
 * прогресс курса, не увеличивая высоту.
 */
export default function TeacherGroupsBlock({ groups, progress }: Props) {
  const [query, setQuery] = useState('');
  const [archiveOpen, setArchiveOpen] = useState(false);

  const { active, archived } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = buildRows(groups, progress).filter((r) =>
      !q
      || r.group.name.toLowerCase().includes(q)
      || (r.group.direction_name || '').toLowerCase().includes(q),
    );
    return {
      active: rows.filter((r) => r.group.active),
      archived: rows.filter((r) => !r.group.active),
    };
  }, [groups, progress, query]);

  if (groups.length === 0) {
    return (
      <EmptyState hint="Группа привязывается к преподавателю в её карточке.">
        У преподавателя нет групп
      </EmptyState>
    );
  }

  return (
    <div className="tgroups">
      <div className="tgroups__head">
        <h3 className="sub-header">
          Активные <span className="count-badge">{active.length}</span>
        </h3>
        <div className="tgroups__search">
          <TextInput
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Группа или направление"
            aria-label="Поиск по группам преподавателя"
          />
        </div>
      </div>

      {active.length === 0 ? (
        <EmptyState hint="Проверьте поиск или разверните архив ниже.">
          Активных групп нет
        </EmptyState>
      ) : (
        <div className="tgroups__list">
          {active.map((row) => <GroupRow key={row.group.id} row={row} />)}
        </div>
      )}

      {archived.length > 0 && (
        <>
          <button
            type="button"
            className="tgroups__toggle"
            onClick={() => setArchiveOpen((v) => !v)}
            aria-expanded={archiveOpen}
          >
            <svg
              width="12" height="12" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"
              strokeLinejoin="round" aria-hidden="true"
              className={archiveOpen ? 'is-open' : ''}
            >
              <polyline points="9 18 15 12 9 6" />
            </svg>
            Архив <span className="count-badge">{archived.length}</span>
          </button>
          {archiveOpen && (
            <div className="tgroups__list">
              {archived.map((row) => <GroupRow key={row.group.id} row={row} />)}
            </div>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Убедиться, что TextInput принимает событие, а не строку**

```
cd journal_django/frontend/admin-src/src/components/form && sed -n '1,10p' TextInput.tsx
```

Ожидается `TextInput(props: InputHTMLAttributes<HTMLInputElement>)` — то есть
`onChange` получает событие (`(e) => setQuery(e.target.value)`), как в
`pages/groups/GroupFormModal.tsx:121`. В коде выше вызов уже такой; шаг —
страховка на случай, если компонент успели поменять. Native `<input>` вместо
`TextInput` не использовать.

- [ ] **Step 3: Добавить стили**

Дописать в конец `journal_django/frontend/admin-src/src/styles/pages/detail.css`:

```css
.tgroups { display: flex; flex-direction: column; gap: var(--space-3); }
.tgroups__head {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-3); flex-wrap: wrap;
}
.tgroups__head .sub-header { margin-bottom: 0; }
.tgroups__search { min-width: 220px; }
.tgroups__list { display: flex; flex-direction: column; }

.tgroup {
  display: flex; flex-direction: column; gap: 4px;
  padding: var(--space-3) 0;
  border-top: 1px solid var(--border2);
  cursor: pointer;
  transition: background var(--t-fast) var(--ease);
}
.tgroup:hover { background: var(--bg2); }
.tgroup:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.tgroup.is-archived { opacity: .62; }

.tgroup__head { display: flex; align-items: baseline; gap: var(--space-2); flex-wrap: wrap; }
.tgroup__name { font-size: 14px; font-weight: 600; color: var(--text); }
.tgroup__dir {
  font-size: 12px; color: var(--entity-c);
  padding: 1px 7px; border-radius: 999px;
  background: color-mix(in oklab, var(--entity-c) 12%, transparent);
}
.tgroup__id {
  margin-left: auto;
  font-family: var(--font-mono); font-size: 12px; color: var(--text4);
}

.tgroup__meta {
  display: flex; gap: var(--space-3); flex-wrap: wrap;
  font-size: 12px; color: var(--text3);
}
.tgroup__mono {
  font-family: var(--font-mono); font-variant-numeric: tabular-nums;
  font-size: 12px; color: var(--text3); white-space: nowrap;
}

.tgroup__stats {
  display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap;
  font-size: 12px; color: var(--text3);
}
.tgroup__students b { font-size: 14px; font-weight: 600; color: var(--text2); }
.tgroup__nocourse { color: var(--text4); }
.tgroup__bar {
  flex: 1; min-width: 80px; max-width: 200px; height: 6px;
  border-radius: 999px; background: var(--bg4); overflow: hidden;
}
.tgroup__fill {
  display: block; height: 100%; border-radius: 999px;
  background: var(--entity-c); transition: width .4s var(--ease);
}
.tgroup__pct {
  font-family: var(--font-mono); font-variant-numeric: tabular-nums;
  font-size: 13px; font-weight: 600; color: var(--text2);
}

.tgroups__toggle {
  display: inline-flex; align-items: center; gap: var(--space-2);
  align-self: flex-start;
  padding: 6px 0;
  background: none; border: none; cursor: pointer;
  font-size: 14px; font-weight: 600; color: var(--text2);
}
.tgroups__toggle:hover { color: var(--text); }
.tgroups__toggle svg { transition: transform var(--t-fast) var(--ease); }
.tgroups__toggle svg.is-open { transform: rotate(90deg); }
```

- [ ] **Step 4: Проверить типы**

```
cd journal_django/frontend/admin-src && npx tsc --noEmit
```

Ожидается: без ошибок.

- [ ] **Step 5: Коммит**

```bash
git add journal_django/frontend/admin-src/src/pages/teachers/TeacherGroupsBlock.tsx \
        journal_django/frontend/admin-src/src/styles/pages/detail.css
git commit -m "feat(admin): группы преподавателя разделены на активные и архивные"
```

---

## Task 11: Компактный Telegram-блок для шапки

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/teachers/TeacherTelegramBlock.tsx`
- Modify: `journal_django/frontend/admin-src/src/styles/pages/notifications.css:167-200`

- [ ] **Step 1: Переписать компонент**

Заменить `journal_django/frontend/admin-src/src/pages/teachers/TeacherTelegramBlock.tsx` целиком:

```tsx
import { useMemo, useState } from 'react';
import { Combobox, type Option } from '../../components/form/Combobox';
import { TelegramIcon } from '../../components/ui/icons';
import { useToast } from '../../components/ui/Toast';
import { useApiError } from '../../hooks/useApiError';
import { useAuth } from '../../hooks/useAuth';
import { useTeacherTelegramMutations, useTelegramAccounts } from '../../hooks/useNotifications';
import { canWriteTeacherTelegram, type Role } from '../../lib/permissions';
import type { Teacher } from '../../lib/types';

/**
 * Вторая строка пункта: ник и — если аккаунт занят — чей он.
 * Раньше всё это склеивалось в label одной строкой, из-за чего подпись
 * не влезала и налезала на соседний пункт.
 */
function optionHint(username: string | null, boundTo: string | null): string | undefined {
  const parts: string[] = [];
  if (username) parts.push(`@${username}`);
  if (boundTo) parts.push(`занят: ${boundTo}`);
  return parts.length ? parts.join(' · ') : undefined;
}

/** Текущее состояние привязки словами — то, ради чего человек сюда смотрит. */
function TelegramStatus({ telegram }: { telegram: Teacher['telegram'] }) {
  if (!telegram) {
    return <span className="tg-card__status">не привязан</span>;
  }
  if (!telegram.is_active) {
    return (
      <span className="tg-card__status tg-card__status--error">
        заблокировал бота{telegram.blocked_reason ? `: ${telegram.blocked_reason}` : ''}
      </span>
    );
  }
  return <span className="tg-card__status tg-card__status--ok">привязан</span>;
}

/**
 * Блок «Telegram» в шапке карточки преподавателя.
 *
 * Выбор из списка аккаунтов, а не ввод ника: Bot API умеет писать только по
 * числовому chat_id, которого человек не видит, а набор руками даёт опечатки.
 * Список — те, кто уже написал боту /start (иначе привязывать нечего).
 *
 * Менеджеру блок показывается только на чтение: право на POST/DELETE у бэка
 * admin-only (ReadStaffWriteAdmin), кнопка с гарантированным 403 бесполезна.
 */
export function TeacherTelegramBlock({ teacher }: { teacher: Teacher }) {
  const { me } = useAuth();
  const canWrite = canWriteTeacherTelegram(me?.role as Role);
  const { data, isLoading } = useTelegramAccounts();
  const muts = useTeacherTelegramMutations(teacher.id);
  const { toast } = useToast();
  const showError = useApiError();

  const current = teacher.telegram?.chat_id != null ? String(teacher.telegram.chat_id) : '';
  const [selected, setSelected] = useState(current);

  // Свободные аккаунты — наверх: занятый выбирают редко, а листать до своего
  // через полтора десятка чужих привязок приходилось каждый раз.
  const options: Option[] = useMemo(() => {
    const rows = (data?.rows ?? []).map((a) => {
      // Свою же привязку «занятой» не считаем: это не конфликт.
      const boundTo = a.bound_to === teacher.name ? null : a.bound_to;
      return {
        value: String(a.chat_id),
        label: a.full_name,
        hint: optionHint(a.username, boundTo),
        muted: Boolean(boundTo),
      };
    });
    return [...rows.filter((o) => !o.muted), ...rows.filter((o) => o.muted)];
  }, [data, teacher.name]);

  const dirty = selected !== current;
  const busy = muts.link.isPending || muts.unlink.isPending;

  const handleSave = async () => {
    try {
      await muts.link.mutateAsync(Number(selected));
      toast('Telegram привязан', 'ok');
    } catch (err) { showError(err, 'Не удалось привязать Telegram'); }
  };

  const handleUnlink = async () => {
    try {
      await muts.unlink.mutateAsync();
      setSelected('');
      toast('Telegram отвязан', 'ok');
    } catch (err) { showError(err, 'Не удалось отвязать Telegram'); }
  };

  return (
    <div className="tg-card">
      <div className="tg-card__head">
        <span className="tg-card__title">
          <TelegramIcon size={14} />
          Telegram
        </span>
        <TelegramStatus telegram={teacher.telegram} />
      </div>

      {teacher.telegram && (
        <div className="tg-card__account">
          {teacher.telegram.username
            ? `@${teacher.telegram.username}`
            : teacher.telegram.full_name}
        </div>
      )}

      {canWrite && (
        <>
          <Combobox
            value={selected}
            onChange={setSelected}
            options={options}
            placeholder={isLoading ? 'Загрузка…' : 'Выберите аккаунт'}
            itemHeight={52}
          />
          <div className="tg-card__actions">
            <button
              type="button"
              className="btn-save"
              onClick={() => { void handleSave(); }}
              disabled={busy || !selected || !dirty}
            >
              {teacher.telegram ? 'Сменить' : 'Привязать'}
            </button>
            {teacher.telegram && (
              <button
                type="button"
                className="btn-cancel"
                onClick={() => { void handleUnlink(); }}
                disabled={busy}
              >
                Отвязать
              </button>
            )}
          </div>
          {!isLoading && options.length === 0 && (
            <div className="tg-card__hint">
              Боту ещё никто не писал: аккаунт появится в списке после команды /start.
            </div>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Заменить стили**

В `journal_django/frontend/admin-src/src/styles/pages/notifications.css` заменить
блок `.teacher-telegram*` (строки 167–200) на:

```css
/* Карточка привязки Telegram в шапке преподавателя. Раньше это было голое поле
   формы между карточкой данных и списком групп — без контейнера и с кнопками
   разной высоты. */
.tg-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
}
.tg-card__head {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-2);
}
.tg-card__title {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; font-weight: 600; letter-spacing: .04em;
  text-transform: uppercase; color: var(--text3);
}
.tg-card__status { font-size: 12px; color: var(--text3); }
.tg-card__status--ok { color: var(--success); }
.tg-card__status--error { color: var(--danger); }
.tg-card__account {
  font-family: var(--font-mono); font-size: 13px; color: var(--text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.tg-card__actions { display: flex; gap: var(--space-2); }
.tg-card__actions button { flex: 1; }
.tg-card__hint { font-size: 11px; color: var(--text4); }
```

- [ ] **Step 3: Убедиться, что старые классы больше нигде не используются**

```
cd journal_django/frontend/admin-src/src && grep -rn "teacher-telegram" .
```

Ожидается: ни одного совпадения. Если что-то осталось — доправить.

- [ ] **Step 4: Проверить типы**

```
cd journal_django/frontend/admin-src && npx tsc --noEmit
```

Ожидается: без ошибок.

- [ ] **Step 5: Коммит**

```bash
git add journal_django/frontend/admin-src/src/pages/teachers/TeacherTelegramBlock.tsx \
        journal_django/frontend/admin-src/src/styles/pages/notifications.css
git commit -m "feat(admin): Telegram-привязка преподавателя оформлена карточкой"
```

---

## Task 12: Сборка страницы преподавателя

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/teachers/TeacherDetailPage.tsx`

- [ ] **Step 1: Переписать страницу**

Заменить `journal_django/frontend/admin-src/src/pages/teachers/TeacherDetailPage.tsx` целиком:

```tsx
import { useState } from 'react';
import { useParams, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { useTeacher, useTeacherMutations } from '../../hooks/useTeachers';
import { useTeacherGroups, useTeacherStats } from '../../hooks/useTeacherStats';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { DetailShell, EntityCard, type DetailField } from '../../components/detail/DetailShell';
import { EntityHero, HeroChip, monogramOf } from '../../components/detail/EntityHero';
import { ActionMenu } from '../../components/ui/ActionMenu';
import { PageLoading } from '../../components/ui/Skeleton';
import { Tabs, type TabItem } from '../../components/ui/Tabs';
import { EntityChangelogPanel } from '../../components/changelog/EntityChangelogPanel';
import { nameColor } from '../../lib/direction-color';
import { fmtDate, todayMSK } from '../../lib/format';
import type { Teacher } from '../../lib/types';
import TeacherFormModal from './TeacherFormModal';
import { TeacherTelegramBlock } from './TeacherTelegramBlock';
import TeacherStatsRow from './TeacherStatsRow';
import TeacherDirectionsBreakdown from './TeacherDirectionsBreakdown';
import TeacherGroupsBlock from './TeacherGroupsBlock';
import { useAuth } from '../../hooks/useAuth';
import { canSeeChangelog, canWriteTeachers, type Role } from '../../lib/permissions';

const TEACHER_TABS = ['overview', 'groups', 'data', 'history'] as const;
type TeacherTab = (typeof TEACHER_TABS)[number];
const DEFAULT_TAB: TeacherTab = 'overview';

function isTeacherTab(value: string | null): value is TeacherTab {
  return !!value && (TEACHER_TABS as readonly string[]).includes(value);
}

export default function TeacherDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const navigate = useNavigate();
  const { data: teacher, isLoading } = useTeacher(id);
  const [searchParams, setSearchParams] = useSearchParams();
  const [month, setMonth] = useState(() => todayMSK().slice(0, 7));
  const { data: groups = [] } = useTeacherGroups(id);
  const { data: stats } = useTeacherStats(id, month);
  const muts = useTeacherMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [editing, setEditing] = useState(false);
  const { me } = useAuth();
  const canWrite = canWriteTeachers(me?.role as Role);

  const activeTab: TeacherTab = isTeacherTab(searchParams.get('tab'))
    ? (searchParams.get('tab') as TeacherTab)
    : DEFAULT_TAB;
  const setActiveTab = (tab: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (tab === DEFAULT_TAB) next.delete('tab'); else next.set('tab', tab);
      return next;
    }, { replace: true });
  };

  if (isLoading) return <PageLoading />;
  if (!teacher) return <Navigate to="/admin/teachers" replace />;

  const fields: DetailField<Teacher>[] = [
    { key: 'id', label: 'ID' },
    { key: 'email', label: 'Email' },
    { key: 'phone', label: 'Телефон' },
    { key: 'active', label: 'Статус', cell: (r) => r.active ? 'Активен' : 'Архив' },
    { key: 'created_at', label: 'Добавлен', cell: (r) => fmtDate(r.created_at) },
  ];

  const handleDelete = async () => {
    try {
      await muts.remove.mutateAsync(teacher.id);
      toast('Архивировано', 'ok');
      navigate('/admin/teachers');
    } catch (err) { showError(err); }
  };

  const handleRestore = async () => {
    try {
      await muts.update.mutateAsync({ id: teacher.id, body: { active: true } });
      toast('Разархивировано', 'ok');
    } catch (err) { showError(err); }
  };

  const activeGroups = groups.filter((g) => g.active);
  const directionsCount = new Set(
    activeGroups.map((g) => g.direction_id),
  ).size;
  const contacts = [teacher.email, teacher.phone].filter(Boolean).join(' · ');

  // У преподавателя нет направления, откуда EntityHero берёт цвет у группы, —
  // берём детерминированный тон из имени (та же формула, что у Avatar).
  const customHero = (
    <EntityHero
      monogram={monogramOf(teacher.name)}
      color={nameColor(teacher.name)}
      title={teacher.name}
      badge={
        teacher.active
          ? <span className="status-badge status-badge--positive">Активен</span>
          : <span className="status-badge status-badge--muted">Архив</span>
      }
      meta={
        <>
          <HeroChip mono>#{teacher.id}</HeroChip>
          {directionsCount > 0 && <HeroChip>{directionsCount} напр.</HeroChip>}
          <HeroChip mono>{activeGroups.length} групп</HeroChip>
          {contacts && <HeroChip>{contacts}</HeroChip>}
        </>
      }
      actions={
        canWrite ? (
          <>
            <button type="button" className="edit-btn" onClick={() => setEditing(true)}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
              Редактировать
            </button>
            <ActionMenu
              items={teacher.active
                ? [{ label: 'Архивировать преподавателя', onSelect: () => { void handleDelete(); }, danger: true }]
                : [{ label: 'Разархивировать преподавателя', onSelect: () => { void handleRestore(); } }]}
            />
          </>
        ) : undefined
      }
      facts={[
        { label: 'В школе с', value: fmtDate(teacher.created_at) },
        {
          label: 'Последнее занятие',
          value: stats?.last_lesson_date ? fmtDate(stats.last_lesson_date) : '—',
        },
      ]}
      aside={<TeacherTelegramBlock teacher={teacher} />}
    />
  );

  const tabs: TabItem[] = [
    {
      value: 'overview',
      label: 'Обзор',
      content: <TeacherDirectionsBreakdown stats={stats} />,
    },
    {
      value: 'groups',
      label: 'Группы',
      content: (
        <TeacherGroupsBlock groups={groups} progress={stats?.group_progress ?? []} />
      ),
    },
    {
      value: 'data',
      label: 'Данные',
      content: <EntityCard title="Данные преподавателя" row={teacher} fields={fields} />,
    },
  ];

  if (canSeeChangelog(me?.role as Role)) {
    tabs.push({
      value: 'history',
      label: 'История',
      content: <EntityChangelogPanel entity="teacher" entityId={teacher.id} />,
    });
  }

  return (
    <>
      <DetailShell<Teacher>
        title={teacher.name}
        row={teacher}
        fields={fields}
        cardTitle="Данные преподавателя"
        customHero={customHero}
        backTo="/admin/teachers"
        parentLabel="Преподаватели"
        hideCard
      >
        <TeacherStatsRow
          month={month}
          onMonthChange={setMonth}
          stats={stats}
          groups={groups}
        />
        <Tabs items={tabs} value={activeTab} onChange={setActiveTab} />
      </DetailShell>
      {editing && (
        <TeacherFormModal initial={teacher} onClose={() => setEditing(false)} />
      )}
    </>
  );
}
```

- [ ] **Step 2: Проверить, что `EntityChangelogPanel` знает сущность `teacher`**

```
cd journal_django && grep -n "teacher" apps/changelog/registry.py | head
cd frontend/admin-src/src && grep -n "entity" components/changelog/EntityChangelogPanel.tsx | head
```

Если `teacher` в реестре журнала изменений отсутствует или проп называется иначе —
убрать вкладку «История» из этой задачи и завести отдельную. Модель `Teacher`
уже трекается (`apps/teachers/migrations/0002_teacherevent_…`), так что запись
там должна быть.

- [ ] **Step 3: Проверить, что `ActionMenu` принимает `items` в этом виде**

```
cd journal_django/frontend/admin-src/src/components/ui && sed -n '1,40p' ActionMenu.tsx
```

Сверить с использованием в `pages/groups/GroupDetailPage.tsx:166-173` — там тот же
вызов. Если сигнатура другая, привести к фактической.

- [ ] **Step 4: Проверить типы**

```
cd journal_django/frontend/admin-src && npx tsc --noEmit
```

Ожидается: без ошибок. Если `useGroupsAll` / `useDirections` остались
неиспользованными импортами где-то ещё — это чужие файлы, не трогать.

- [ ] **Step 5: Коммит**

```bash
git add journal_django/frontend/admin-src/src/pages/teachers/TeacherDetailPage.tsx
git commit -m "feat(admin): карточка преподавателя на EntityHero и вкладках"
```

---

## Task 13: Ручная проверка в браузере

**Files:** нет изменений — только проверка.

- [ ] **Step 1: Поднять окружение**

```
cd journal_django && python manage.py runserver
```

Отдельным терминалом:

```
cd journal_django/frontend/admin-src && npm run dev
```

Фронт локально ходит через nginx (`:8080` → runserver), см. `reference_local_nginx`.

- [ ] **Step 2: Пройти чек-лист на карточке преподавателя с 18 группами**

Открыть `/admin/teachers/<id>` (взять преподавателя с большим числом групп).
Проверить и зафиксировать результат по каждому пункту:

1. Шапка: монограмма, статус-бейдж, чипы (#id, направления, группы, контакты), кнопки.
2. Правая колонка шапки: два факта + карточка Telegram с иконкой.
3. Выпадашка Telegram: **ни один пункт не налезает на соседний**, ник — второй строкой, занятые аккаунты приглушены и внизу списка, поиск находит по нику.
4. Плитки: переключатель ◀ ▶ меняет «Занятий» и «Часов», плитки НЕ схлопываются в скелет при переключении.
5. Месяц без занятий: «Занятий 0», «Часов 0,0», подпись «занятий не было», вкладка «Обзор» показывает пустое состояние вместо пустых полос.
6. Вкладка «Группы»: активные списком, «Архив N» свёрнут, разворачивается; поиск фильтрует; клик по строке ведёт на группу; Enter/Space с клавиатуры тоже.
7. Прогресс курса: у группы без заданной длины курса вместо полосы текст «длина курса не задана», деления на ноль нет.
8. Вкладки переживают перезагрузку страницы (`?tab=groups` в адресе).

- [ ] **Step 3: Проверить обе темы и узкий экран**

Переключить тёмную тему (кнопка в сайдбаре). Проверить, что:
- полосы направлений и прогресса видны на тёмном фоне;
- карточка Telegram и её рамка не сливаются с фоном;
- спарклайн читается.

Сузить окно до 700 px: `.tbreak` схлопывается в одну колонку, строка группы не
уезжает за край, горизонтального скролла у `body` нет.

- [ ] **Step 4: Проверить менеджера**

Зайти под ролью manager. Ожидается: страница открывается, статистика видна,
блок Telegram — только статус без контролов, кнопок «Редактировать»/«Архивировать» нет.

- [ ] **Step 5: Проверить преподавателя без групп и без Telegram**

Ожидается: пустые состояния вместо полос и списков, никаких `NaN` и `—/—`.

- [ ] **Step 6: Убедиться, что admin-dist не изменился**

```bash
git status --porcelain journal_django/frontend/admin-dist
```

Ожидается: пустой вывод. Если `admin-dist/` изменён — значит где-то запустили
`npm run build`; откатить: `git checkout -- journal_django/frontend/admin-dist`.

- [ ] **Step 7: Финальный полный прогон pytest**

```
cd journal_django && pytest -q
```

Ожидается: 0 failed.

- [ ] **Step 8: Коммит (только если что-то правили по итогам проверки)**

```bash
git add -u journal_django/frontend/admin-src
git commit -m "fix(admin): правки карточки преподавателя по итогам ручной проверки"
```

---

## Что сознательно не делается

Вынесено в отдельный заход (раздел «Вне области» спеки): пунктуальность отчётов,
счётчик незаполненных занятий, доля продлившихся учеников, посещаемость на его
уроках, отработано/сгорело, нагрузка по дням недели, зарплата за месяц.
