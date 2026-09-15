# Дашборд «Посещения учеников» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Экран в разделе «Отчёты» с двумя цифрами отработанных уроков (за всё время и за период), списком всех учеников с разбивкой по типам занятий и модалкой детализации по клику на строку.

**Architecture:** Два read-only эндпоинта: сводка (две цифры) и пагинированный список учеников — так сводка не пересчитывается при листании, а список сохраняет общий конверт `{rows, total, page, page_size}`. Считает один агрегирующий запрос с условными суммами (`Sum(..., filter=Q(...))`), без N+1. Вес занятия (45 мин = 0,5) берётся из общей функции, а не дублируется — этот инвариант в проекте уже терялся однажды. Модалка переиспользует таблицу уроков из карточки ученика, для чего существующий эндпоинт уроков получает необязательный период.

**Tech Stack:** Django 5 + DRF (`journal_django/`), PostgreSQL, pytest; React 19 + TanStack Query v5 + Vite (`journal_django/frontend/admin-src/`).

**Спека:** `docs/superpowers/specs/2026-09-15-attendance-dashboard-design.md`

---

## Структура файлов

| Файл | Ответственность |
|---|---|
| `journal_django/apps/lessons/weights.py` | **Создать.** Вес посещения (45 мин = 0,5) одной функцией на весь проект. |
| `journal_django/apps/finances/repository.py` | **Правка.** `_attended_units_case` делегирует в общую функцию — два определения веса разъедутся. |
| `journal_django/apps/reports/attendance_dashboard.py` | **Создать.** Сводка и агрегат по ученикам: фильтры типов, период, сортировка, поиск по имени. |
| `journal_django/apps/reports/dashboard_views.py` | **Создать.** Две тонкие вьюхи. Отдельный файл: `views.py` раздела — про фоновую генерацию Excel, живые агрегаты там не к месту. |
| `journal_django/apps/reports/urls.py` | **Правка.** Два маршрута. |
| `journal_django/apps/students/lesson_history.py` | **Правка.** Необязательный период в выборке уроков ученика. |
| `journal_django/apps/students/views.py` | **Правка.** Разбор `date_from` / `date_to`. |
| `journal_django/frontend/admin-src/src/components/lessons/StudentLessonsTable.tsx` | **Создать** (переезд из `pages/students/StudentLessonsBlock.tsx`). Таблица уроков ученика с необязательным периодом — общая для вкладки карточки и модалки. |
| `journal_django/frontend/admin-src/src/pages/students/StudentLessonsBlock.tsx` | **Удалить** — его содержимое переезжает в общий компонент. |
| `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx` | **Правка.** Вкладка использует общий компонент. |
| `journal_django/frontend/admin-src/src/lib/shared-types.ts` | **Правка.** Типы строк дашборда. |
| `journal_django/frontend/admin-src/src/hooks/useStudentLessons.ts` | **Правка.** Необязательный период. |
| `journal_django/frontend/admin-src/src/hooks/useAttendanceDashboard.ts` | **Создать.** Два хука: сводка и список. |
| `journal_django/frontend/admin-src/src/pages/reports/AttendanceDashboardPage.tsx` | **Создать.** Экран: период, плитки, фильтр, таблица, модалка. |
| `journal_django/frontend/admin-src/src/pages/reports/ReportsPage.tsx` | **Правка.** Вкладки «Отчёты» / «Дашборд». |
| `journal_django/frontend/admin-src/src/App.tsx` | **Правка.** Маршрут дашборда. |
| `journal_django/frontend/admin-src/src/styles/pages/reports.css` | **Правка.** Классы экрана (если файла нет — искать, где живут стили раздела). |

**Про тесты:** гонять только полный `pytest -q` из `journal_django/` — часть приложений no-op'ит `django_db_setup` (общая `journal_test`), часть пересоздаёт `test_journal_test`; прогон по приложениям даёт ложный результат. Внутри задачи можно гонять один файл, но перед завершением задачи — полный прогон.

**Команды:**
- pytest: `cd journal_django && ./.venv/Scripts/python.exe -m pytest <путь> -q`
- типы фронта: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
- сборка: только в последней задаче.

---

### Task 1: Общая функция веса занятия

**Files:**
- Create: `journal_django/apps/lessons/weights.py`
- Modify: `journal_django/apps/finances/repository.py` (функция `_attended_units_case`, ~строки 57-63)
- Test: `journal_django/apps/lessons/tests/test_weights.py`

Почему отдельная задача: вес «45 минут = 0,5 урока» — самый хрупкий инвариант проекта, он уже однажды потерялся (прогресс ученика считался сырым COUNT). Дашборд станет третьим потребителем, и второе определение рядом с первым — вопрос времени.

- [ ] **Step 1: Написать падающий тест**

Создать `journal_django/apps/lessons/tests/test_weights.py`:

```python
"""
Тесты общей функции веса посещения (half-lesson: 45 минут = 0.5 урока).

Вес — инвариант, от которого зависят балансы, финансы и отчёты. Функция одна на
проект именно поэтому: второе определение рядом разъедется молча.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection

from apps.lessons.models import LessonAttendance
from apps.lessons.weights import attended_units_case

pytestmark = pytest.mark.django_db


@pytest.fixture
def graph():
    created = {}
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name, total_lessons, active) "
                    "VALUES ('__w_dir__', 16, true) RETURNING id")
        created['direction_id'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name) VALUES ('__w_teacher__') RETURNING id")
        created['teacher_id'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active, lesson_number_offset) "
            "VALUES ('__w_group__', %s, %s, false, 60, true, 0) RETURNING id",
            [created['direction_id'], created['teacher_id']])
        created['group_id'] = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name) VALUES ('__w_student__') RETURNING id")
        created['student_id'] = cur.fetchone()[0]
    created['lessons'] = []
    yield created
    with connection.cursor() as cur:
        for lid in created['lessons']:
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lid])
            cur.execute('DELETE FROM lessons WHERE id = %s', [lid])
        cur.execute('DELETE FROM students WHERE id = %s', [created['student_id']])
        cur.execute('DELETE FROM groups WHERE id = %s', [created['group_id']])
        cur.execute('DELETE FROM teachers WHERE id = %s', [created['teacher_id']])
        cur.execute('DELETE FROM directions WHERE id = %s', [created['direction_id']])


def _add(graph, duration, number):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s, %s, '2026-02-10', %s, %s, 'regular', 't') RETURNING id",
            [graph['group_id'], graph['teacher_id'], number, duration])
        lid = cur.fetchone()[0]
        graph['lessons'].append(lid)
        cur.execute('INSERT INTO lesson_attendance (lesson_id, student_id, present) '
                    'VALUES (%s, %s, true)', [lid, graph['student_id']])
    return lid


def test_45_minutes_weighs_half(graph):
    lid = _add(graph, 45, 1)
    row = (LessonAttendance.objects.filter(lesson_id=lid)
           .annotate(units=attended_units_case()).values('units').first())
    assert row['units'] == Decimal('0.5')


def test_other_durations_weigh_one(graph):
    for duration, number in ((60, 1), (90, 2), (120, 3)):
        lid = _add(graph, duration, number)
        row = (LessonAttendance.objects.filter(lesson_id=lid)
               .annotate(units=attended_units_case()).values('units').first())
        assert row['units'] == Decimal('1'), duration


def test_finances_helper_delegates_to_shared_one(graph):
    """У финансов не должно остаться СВОЕГО определения веса."""
    from apps.finances.repository import _attended_units_case
    _add(graph, 45, 1)
    shared = (LessonAttendance.objects.filter(student_id=graph['student_id'])
              .annotate(u=attended_units_case()).values_list('u', flat=True).first())
    legacy = (LessonAttendance.objects.filter(student_id=graph['student_id'])
              .annotate(u=_attended_units_case()).values_list('u', flat=True).first())
    assert shared == legacy == Decimal('0.5')
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_weights.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.lessons.weights'`.

- [ ] **Step 3: Создать общую функцию**

Создать `journal_django/apps/lessons/weights.py`:

```python
"""
Вес посещения в уроках — единственное определение half-lesson на проект.

Занятие 45 минут весит 0.5 урока, любое другое — 1. От этого веса зависят
балансы учеников, FIFO-списание денег и отчёты; однажды он уже потерялся в
одном месте (прогресс ученика считался сырым COUNT занятий), поэтому второе
определение рядом заводить нельзя — только импорт этого.

Выражение рассчитано на queryset по lesson_attendance: путь до длительности
идёт через FK `lesson`. Для запросов от самой модели Lesson оно не годится.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Case, DecimalField, Value, When

_DEC = DecimalField(max_digits=12, decimal_places=2)


def attended_units_case() -> Case:
    """SUM(CASE WHEN duration=45 THEN 0.5 ELSE 1) как Decimal-выражение."""
    return Case(
        When(lesson__lesson_duration_minutes=45, then=Value(Decimal('0.5'))),
        default=Value(Decimal('1')),
        output_field=_DEC,
    )
```

- [ ] **Step 4: Переключить финансы на общую функцию**

В `journal_django/apps/finances/repository.py` заменить тело `_attended_units_case` на делегирование:

```python
def _attended_units_case():
    """
    half-lesson: SUM(CASE WHEN duration=45 THEN 0.5 ELSE 1) как Decimal-выражение.

    Своего определения здесь больше нет: вес — общий инвариант проекта и живёт в
    apps/lessons/weights.py. Имя оставлено, потому что на него завязаны вызовы
    внутри модуля.
    """
    from apps.lessons.weights import attended_units_case
    return attended_units_case()
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_weights.py apps/finances -q`
Expected: PASS — новые тесты зелёные, финансовые не сломаны.

- [ ] **Step 6: Полный прогон**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, падений нет.

---

### Task 2: Агрегат дашборда

**Files:**
- Create: `journal_django/apps/reports/attendance_dashboard.py`
- Test: `journal_django/apps/reports/tests/test_attendance_dashboard.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `journal_django/apps/reports/tests/test_attendance_dashboard.py`:

```python
"""
Тесты агрегата дашборда «Посещения учеников» (спека 2026-09-15).

Счётчик везде один: списанные уроки с весом (45 мин = 0.5), это обычные +
доп.уроки + сгорания; бесплатные идут отдельной колонкой и в «Итого» не входят.
Период определяется датой ЗАНЯТИЯ.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection

from apps.reports import attendance_dashboard as ad

pytestmark = pytest.mark.django_db

PERIOD = ('2026-02-01', '2026-02-28')


@pytest.fixture
def graph():
    created = {'lessons': [], 'students': []}
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name, total_lessons, active) "
                    "VALUES ('__ad_dir__', 16, true) RETURNING id")
        created['direction_id'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name) VALUES ('__ad_teacher__') RETURNING id")
        created['teacher_id'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active, lesson_number_offset) "
            "VALUES ('__ad_group__', %s, %s, false, 60, true, 0) RETURNING id",
            [created['direction_id'], created['teacher_id']])
        created['group_id'] = cur.fetchone()[0]
    yield created
    with connection.cursor() as cur:
        for lid in created['lessons']:
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lid])
            cur.execute('DELETE FROM lessons WHERE id = %s', [lid])
        for sid in created['students']:
            cur.execute('DELETE FROM students WHERE id = %s', [sid])
        cur.execute('DELETE FROM groups WHERE id = %s', [created['group_id']])
        cur.execute('DELETE FROM teachers WHERE id = %s', [created['teacher_id']])
        cur.execute('DELETE FROM directions WHERE id = %s', [created['direction_id']])


def _student(graph, name):
    with connection.cursor() as cur:
        cur.execute('INSERT INTO students (full_name) VALUES (%s) RETURNING id', [name])
        sid = cur.fetchone()[0]
    graph['students'].append(sid)
    return sid


def _lesson(graph, sid, *, date='2026-02-10', number=1, duration=60,
            lesson_type='regular', present=True, is_free=False):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s, %s, %s, %s, %s, %s, 't') RETURNING id",
            [graph['group_id'], graph['teacher_id'], date, number, duration, lesson_type])
        lid = cur.fetchone()[0]
        graph['lessons'].append(lid)
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present, is_free) '
            'VALUES (%s, %s, %s, %s)', [lid, sid, present, is_free])
    return lid


def _rows(date_from=PERIOD[0], date_to=PERIOD[1], **kw):
    """Строки API с числами, приведёнными обратно в Decimal — сравнивать удобнее."""
    qs = ad.student_rows_queryset(date_from, date_to, **kw)
    out = []
    for r in ad.serialize_rows(list(qs)):
        row = dict(r)
        for key in ('regular', 'extra', 'burned', 'free', 'billed'):
            row[key] = Decimal(row[key])
        out.append(row)
    return out


def _by_student(rows):
    return {r['student_id']: r for r in rows}


def test_columns_split_by_kind_with_weight(graph):
    """Четыре типа раскладываются по своим колонкам, 45 минут весит 0.5."""
    sid = _student(graph, '__ad_s1__')
    _lesson(graph, sid, number=1)                                  # обычный, 1
    _lesson(graph, sid, number=2, duration=45)                     # обычный, 0.5
    _lesson(graph, sid, number=3, lesson_type='extra')             # доп.урок, 1
    _lesson(graph, sid, number=4, lesson_type='burned')            # сгорание, 1
    _lesson(graph, sid, number=5, is_free=True)                    # бесплатный, 1

    row = _by_student(_rows())[sid]
    assert row['regular'] == Decimal('1.5')
    assert row['extra'] == Decimal('1')
    assert row['burned'] == Decimal('1')
    assert row['free'] == Decimal('1')
    # «Итого» — только списанные: бесплатное занятие с абонемента не снимается.
    assert row['billed'] == Decimal('3.5')


def test_absent_rows_are_ignored(graph):
    """Пропуск — не занятие: ни в одну колонку не идёт."""
    sid = _student(graph, '__ad_s2__')
    _lesson(graph, sid, number=1)
    _lesson(graph, sid, number=2, present=False)

    row = _by_student(_rows())[sid]
    assert row['billed'] == Decimal('1')


def test_period_is_by_lesson_date(graph):
    """Урок вне периода не считается, хотя ученик в списке остаётся."""
    sid = _student(graph, '__ad_s3__')
    _lesson(graph, sid, number=1, date='2026-01-15')
    _lesson(graph, sid, number=2, date='2026-02-10')

    row = _by_student(_rows())[sid]
    assert row['billed'] == Decimal('1')


def test_student_without_lessons_in_period_stays_with_zeros(graph):
    """Видно, кто перестал ходить, — иначе он просто исчезнет из отчёта."""
    sid = _student(graph, '__ad_s4__')
    _lesson(graph, sid, number=1, date='2025-12-01')

    row = _by_student(_rows())[sid]
    assert (row['regular'], row['extra'], row['burned'], row['free'], row['billed']) == (
        Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0'))


def test_extra_and_burned_belong_to_period_by_their_own_date(graph):
    """Доп.урок и сгорание относятся к месяцу СВОЕГО проведения, не пропуска."""
    sid = _student(graph, '__ad_s5__')
    _lesson(graph, sid, number=1, date='2026-01-20', lesson_type='extra')
    _lesson(graph, sid, number=2, date='2026-02-05', lesson_type='burned')

    row = _by_student(_rows())[sid]
    assert row['extra'] == Decimal('0')
    assert row['burned'] == Decimal('1')


def test_name_filter_is_substring_case_insensitive(graph):
    sid = _student(graph, '__ad_Иванов__')
    _student(graph, '__ad_Петров__')
    _lesson(graph, sid, number=1)

    rows = _rows(name_query='иванов')
    assert [r['student_id'] for r in rows] == [sid]


def test_sort_by_billed_desc_then_name(graph):
    many = _student(graph, '__ad_zz_many__')
    few = _student(graph, '__ad_aa_few__')
    _lesson(graph, many, number=1)
    _lesson(graph, many, number=2)
    _lesson(graph, few, number=3)

    rows = [r for r in _rows() if r['student_id'] in (many, few)]
    assert [r['student_id'] for r in rows] == [many, few]


def test_sort_by_full_name_asc(graph):
    b = _student(graph, '__ad_bbb__')
    a = _student(graph, '__ad_aaa__')
    _lesson(graph, b, number=1)
    _lesson(graph, a, number=2)

    rows = [r for r in _rows(sort_by='full_name', sort_dir='asc')
            if r['student_id'] in (a, b)]
    assert [r['student_id'] for r in rows] == [a, b]


def test_summary_counts_billed_lessons_only(graph):
    sid = _student(graph, '__ad_s6__')
    _lesson(graph, sid, number=1)                        # 1, в периоде
    _lesson(graph, sid, number=2, duration=45)           # 0.5, в периоде
    _lesson(graph, sid, number=3, is_free=True)          # бесплатный — мимо
    _lesson(graph, sid, number=4, date='2025-11-11')     # 1, вне периода

    summary = ad.summary(*PERIOD)
    rows = _rows()
    # Цифра за период сходится с суммой колонки «Итого» по всем строкам —
    # иначе плитка и таблица на одном экране показывают разное.
    assert Decimal(summary['period_lessons']) == sum(Decimal(r['billed']) for r in rows)
    assert Decimal(summary['period_lessons']) == Decimal('1.5')
    # За всё время больше на урок из ноября.
    assert Decimal(summary['all_time_lessons']) >= Decimal('2.5')
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/reports/tests/test_attendance_dashboard.py -q`
Expected: FAIL — `ImportError: cannot import name 'attendance_dashboard'`.

- [ ] **Step 3: Создать модуль агрегата**

Создать `journal_django/apps/reports/attendance_dashboard.py`:

```python
"""
Дашборд «Посещения учеников» (спека 2026-09-15): сводка и агрегат по ученикам.

Счётчик один на весь экран — СПИСАННЫЕ уроки с весом (45 мин = 0.5): обычные,
доп.уроки и сгорания. Бесплатные занятия идут отдельной колонкой и в «Итого» не
входят: с абонемента за них не снимается, и подмешать их значило бы разойтись с
балансами и с плиткой за период.

Типы строк — те же четыре, что во вкладке «Уроки» карточки ученика, и выводятся
по тому же правилу (apps/students/lesson_history.py::row_kind): тип урока
проверяется раньше флага «бесплатное», потому что сгорание и доп.урок
бесплатными не бывают. Две классификации одного факта завести нельзя — колонки
перестанут сходиться между экранами.

Период — по дате ЗАНЯТИЯ (lesson_date), как в финансах: доп.урок и сгорание
попадают в период по дате своего проведения, а не по дате закрытого пропуска.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce

from apps.lessons.models import SYSTEM_LESSON_TYPES, LessonAttendance
from apps.lessons.weights import attended_units_case

_DEC = DecimalField(max_digits=12, decimal_places=2)
_ZERO = Decimal('0')

# Разрешённые ключи сортировки: ключ запроса → поля ORM. Белый список, а не
# сырой sort_by в order_by. К ключу всегда добавляется ФИО и id: без этого
# строки с равным значением меняют порядок между запросами и страница 2
# повторит строку со страницы 1.
ORDERING_FIELDS = {
    'billed': 'billed',
    'full_name': 'student__full_name',
}
DEFAULT_SORT_BY = 'billed'
DEFAULT_SORT_DIR = 'desc'

_IS_SYSTEM = Q(lesson__lesson_type__in=SYSTEM_LESSON_TYPES)
_Q_EXTRA = Q(lesson__lesson_type='extra')
_Q_BURNED = Q(lesson__lesson_type='burned')
# «Бесплатный» и «обычный» — только среди НЕ системных уроков: у сгорания и
# доп.урока тип старше флага is_free.
_Q_FREE = ~_IS_SYSTEM & Q(is_free=True)
_Q_REGULAR = ~_IS_SYSTEM & Q(is_free=False)
# «Списано» = всё, кроме бесплатного: обычные + доп.уроки + сгорания.
_Q_BILLED = ~_Q_FREE


def _weighted(condition: Q) -> Coalesce:
    """SUM(вес) по строкам, удовлетворяющим condition; пусто → 0, не NULL."""
    return Coalesce(
        Sum(attended_units_case(), filter=condition),
        Decimal('0'),
        output_field=_DEC,
    )


def _in_period(date_from: str, date_to: str) -> Q:
    return Q(lesson__lesson_date__gte=date_from, lesson__lesson_date__lte=date_to)


def summary(date_from: str, date_to: str) -> dict:
    """
    Две цифры экрана: списанные уроки за всё время и внутри периода.

    Считается по всей школе и НЕ зависит от фильтра по имени: иначе цифра
    прыгала бы при наборе букв в поиске и читалась как ошибка.
    """
    base = LessonAttendance.objects.filter(Q(present=True) & _Q_BILLED)
    row = base.aggregate(
        all_time=_weighted(Q()),
        period=_weighted(_in_period(date_from, date_to)),
    )
    # Строками — по той же причине, что и строки таблицы (см. serialize_rows).
    return {
        'all_time_lessons': str(row['all_time'] or _ZERO),
        'period_lessons': str(row['period'] or _ZERO),
    }


def student_rows_queryset(
    date_from: str,
    date_to: str,
    sort_by: str = DEFAULT_SORT_BY,
    sort_dir: str = DEFAULT_SORT_DIR,
    name_query: str = '',
):
    """
    Строка на ученика: разбивка по типам внутри периода.

    В выборке ВСЕ ученики, у кого есть хоть какое-то посещение (present=true) —
    даже если в периоде у них пусто: тогда во всех колонках нули, и видно, кто
    перестал ходить. Поэтому фильтр периода живёт внутри условных сумм, а не в
    WHERE: иначе такой ученик пропал бы из отчёта совсем.

    Значение sort_by вне белого списка сюда не доходит (вьюха отдаёт 400), здесь
    второй рубеж — откат на умолчание вместо сырой строки в order_by.
    """
    qs = LessonAttendance.objects.filter(present=True)
    if name_query:
        qs = qs.filter(student__full_name__icontains=name_query)

    period = _in_period(date_from, date_to)
    qs = (
        qs.values('student_id', 'student__full_name')
        .annotate(
            regular=_weighted(period & _Q_REGULAR),
            extra=_weighted(period & _Q_EXTRA),
            burned=_weighted(period & _Q_BURNED),
            free=_weighted(period & _Q_FREE),
            billed=_weighted(period & _Q_BILLED),
        )
    )
    field = ORDERING_FIELDS.get(sort_by, ORDERING_FIELDS[DEFAULT_SORT_BY])
    prefix = '' if sort_dir == 'asc' else '-'
    return qs.order_by(f'{prefix}{field}', 'student__full_name', 'student_id')


def serialize_rows(rows) -> list[dict]:
    """Строки агрегата в форму ответа API."""
    return [
        {
            'student_id': r['student_id'],
            'full_name': r['student__full_name'],
            # Уроки отдаются строками ('1.50'), как деньги и номер урока во
            # вкладке «Уроки»: DRF кодирует Decimal во float, а половинки лучше
            # не гонять через двоичную дробь. Фронт приводит через Number().
            'regular': str(r['regular']),
            'extra': str(r['extra']),
            'burned': str(r['burned']),
            'free': str(r['free']),
            'billed': str(r['billed']),
        }
        for r in rows
    ]
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/reports/tests/test_attendance_dashboard.py -q`
Expected: PASS, 9 тестов.

---

### Task 3: Эндпоинты дашборда

**Files:**
- Create: `journal_django/apps/reports/dashboard_views.py`
- Modify: `journal_django/apps/reports/urls.py`
- Test: `journal_django/apps/reports/tests/test_attendance_dashboard_api.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `journal_django/apps/reports/tests/test_attendance_dashboard_api.py`:

```python
"""
E2E дашборда «Посещения учеников».

  GET /api/admin/reports/attendance-dashboard/summary
  GET /api/admin/reports/attendance-dashboard/students

RBAC: manager/admin/superadmin читают, преподаватель — нет.
"""
from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db

SUMMARY_URL = '/api/admin/reports/attendance-dashboard/summary'
STUDENTS_URL = '/api/admin/reports/attendance-dashboard/students'
PERIOD = 'date_from=2026-02-01&date_to=2026-02-28'


@pytest.fixture
def graph():
    created = {'lessons': [], 'students': []}
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name, total_lessons, active) "
                    "VALUES ('__adapi_dir__', 16, true) RETURNING id")
        created['direction_id'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name) VALUES ('__adapi_teacher__') RETURNING id")
        created['teacher_id'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active, lesson_number_offset) "
            "VALUES ('__adapi_group__', %s, %s, false, 60, true, 0) RETURNING id",
            [created['direction_id'], created['teacher_id']])
        created['group_id'] = cur.fetchone()[0]
    yield created
    with connection.cursor() as cur:
        for lid in created['lessons']:
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lid])
            cur.execute('DELETE FROM lessons WHERE id = %s', [lid])
        for sid in created['students']:
            cur.execute('DELETE FROM students WHERE id = %s', [sid])
        cur.execute('DELETE FROM groups WHERE id = %s', [created['group_id']])
        cur.execute('DELETE FROM teachers WHERE id = %s', [created['teacher_id']])
        cur.execute('DELETE FROM directions WHERE id = %s', [created['direction_id']])


def _student(graph, name):
    with connection.cursor() as cur:
        cur.execute('INSERT INTO students (full_name) VALUES (%s) RETURNING id', [name])
        sid = cur.fetchone()[0]
    graph['students'].append(sid)
    return sid


def _lesson(graph, sid, *, date='2026-02-10', number=1, duration=60,
            lesson_type='regular', is_free=False):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s, %s, %s, %s, %s, %s, 't') RETURNING id",
            [graph['group_id'], graph['teacher_id'], date, number, duration, lesson_type])
        lid = cur.fetchone()[0]
        graph['lessons'].append(lid)
        cur.execute('INSERT INTO lesson_attendance (lesson_id, student_id, present, is_free) '
                    'VALUES (%s, %s, true, %s)', [lid, sid, is_free])
    return lid


def test_summary_requires_auth(anon_client):
    assert anon_client.get(f'{SUMMARY_URL}?{PERIOD}').status_code == 401


def test_summary_forbidden_for_teacher(teacher_client):
    assert teacher_client.get(f'{SUMMARY_URL}?{PERIOD}').status_code == 403


def test_students_requires_auth(anon_client):
    assert anon_client.get(f'{STUDENTS_URL}?{PERIOD}').status_code == 401


def test_students_forbidden_for_teacher(teacher_client):
    assert teacher_client.get(f'{STUDENTS_URL}?{PERIOD}').status_code == 403


def test_manager_can_read_both(manager_client):
    assert manager_client.get(f'{SUMMARY_URL}?{PERIOD}').status_code == 200
    assert manager_client.get(f'{STUDENTS_URL}?{PERIOD}').status_code == 200


def test_summary_shape(admin_client, graph):
    sid = _student(graph, '__adapi_s1__')
    _lesson(graph, sid, number=1)

    data = admin_client.get(f'{SUMMARY_URL}?{PERIOD}').json()
    assert set(data) == {'all_time_lessons', 'period_lessons'}
    assert float(data['period_lessons']) >= 1


def test_students_row_shape_and_envelope(admin_client, graph):
    sid = _student(graph, '__adapi_s2__')
    _lesson(graph, sid, number=1, duration=45)
    _lesson(graph, sid, number=2, lesson_type='extra')
    _lesson(graph, sid, number=3, is_free=True)

    data = admin_client.get(f'{STUDENTS_URL}?{PERIOD}&filter[full_name]=__adapi_s2__').json()
    assert set(data) >= {'rows', 'total', 'page', 'page_size'}
    assert data['total'] == 1
    row = data['rows'][0]
    assert row['student_id'] == sid
    assert row['full_name'] == '__adapi_s2__'
    assert float(row['regular']) == 0.5
    assert float(row['extra']) == 1
    assert float(row['burned']) == 0
    assert float(row['free']) == 1
    assert float(row['billed']) == 1.5


def test_students_name_filter_narrows(admin_client, graph):
    a = _student(graph, '__adapi_Иванов__')
    _student(graph, '__adapi_Петров__')
    _lesson(graph, a, number=1)

    data = admin_client.get(f'{STUDENTS_URL}?{PERIOD}&filter[full_name]=иванов').json()
    assert [r['student_id'] for r in data['rows']] == [a]


def test_missing_period_returns_400(admin_client):
    assert admin_client.get(STUDENTS_URL).status_code == 400
    assert admin_client.get(SUMMARY_URL).status_code == 400


def test_invalid_period_returns_400(admin_client):
    assert admin_client.get(f'{SUMMARY_URL}?date_from=вчера&date_to=2026-02-28').status_code == 400


def test_reversed_period_returns_400(admin_client):
    """Конец раньше начала — почти наверняка опечатка, молчать о ней нельзя."""
    resp = admin_client.get(f'{SUMMARY_URL}?date_from=2026-02-28&date_to=2026-02-01')
    assert resp.status_code == 400


def test_invalid_sort_returns_400(admin_client):
    assert admin_client.get(f'{STUDENTS_URL}?{PERIOD}&sort_by=student__id').status_code == 400
    assert admin_client.get(f'{STUDENTS_URL}?{PERIOD}&sort_dir=sideways').status_code == 400


def test_pagination_slices(admin_client, graph):
    a = _student(graph, '__adapi_pag_a__')
    b = _student(graph, '__adapi_pag_b__')
    _lesson(graph, a, number=1)
    _lesson(graph, b, number=2)

    data = admin_client.get(
        f'{STUDENTS_URL}?{PERIOD}&filter[full_name]=__adapi_pag_&page_size=1').json()
    assert data['total'] == 2
    assert len(data['rows']) == 1
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/reports/tests/test_attendance_dashboard_api.py -q`
Expected: FAIL — 404 на всех запросах (маршрутов нет).

- [ ] **Step 3: Создать вьюхи**

Создать `journal_django/apps/reports/dashboard_views.py`:

```python
"""
Вьюхи дашборда «Посещения учеников» (спека 2026-09-15).

  GET /api/admin/reports/attendance-dashboard/summary   — две цифры
  GET /api/admin/reports/attendance-dashboard/students  — список учеников

Живут отдельно от views.py раздела: тот про фоновую генерацию Excel через
Celery, а здесь — обычное чтение агрегатов, общего у них только URL-префикс.

RBAC — IsManagerOrAdmin, как у всего раздела «Отчёты».
"""
from __future__ import annotations

from datetime import date

from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import StandardPagination
from apps.core.permissions import IsManagerOrAdmin
from apps.reports import attendance_dashboard as ad


def _parse_period(request: Request) -> tuple[str, str]:
    """
    Период из query-строки. Обязателен и валидируется здесь, а не в агрегате:
    невалидная дата в SQL — это 500 вместо внятного 400, а пустой период молча
    дал бы нули и читался как «за месяц ничего не было».
    """
    raw_from = request.query_params.get('date_from') or ''
    raw_to = request.query_params.get('date_to') or ''
    if not raw_from or not raw_to:
        raise ValidationError({'error': 'date_from and date_to are required'})
    try:
        parsed_from = date.fromisoformat(raw_from)
        parsed_to = date.fromisoformat(raw_to)
    except ValueError:
        raise ValidationError({'error': 'date_from/date_to must be YYYY-MM-DD'})
    if parsed_to < parsed_from:
        raise ValidationError({'error': 'date_to must not be earlier than date_from'})
    return parsed_from.isoformat(), parsed_to.isoformat()


class AttendanceDashboardSummaryView(APIView):
    """Две цифры: отработано за всё время и за период. По всей школе."""

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        date_from, date_to = _parse_period(request)
        return Response(ad.summary(date_from, date_to))


class AttendanceDashboardStudentsView(APIView):
    """
    Список учеников с разбивкой по типам занятий внутри периода.

    Сортировка: sort_by ∈ attendance_dashboard.ORDERING_FIELDS, sort_dir ∈
    asc|desc; мусор → 400, как в остальных списках. Фильтр по имени —
    filter[full_name], подстрока без учёта регистра.
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        date_from, date_to = _parse_period(request)
        qp = request.query_params
        sort_by = qp.get('sort_by') or ad.DEFAULT_SORT_BY
        sort_dir = qp.get('sort_dir') or ad.DEFAULT_SORT_DIR
        if sort_by not in ad.ORDERING_FIELDS:
            raise ValidationError(
                f"Invalid sort_by '{sort_by}'. Allowed: {sorted(ad.ORDERING_FIELDS)}"
            )
        if sort_dir not in ('asc', 'desc'):
            raise ValidationError(
                f"Invalid sort_dir '{sort_dir}'. Must be 'asc' or 'desc'."
            )

        qs = ad.student_rows_queryset(
            date_from, date_to, sort_by, sort_dir,
            name_query=qp.get('filter[full_name]') or '',
        )
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(ad.serialize_rows(page))
```

- [ ] **Step 4: Добавить маршруты**

В `journal_django/apps/reports/urls.py` заменить содержимое на:

```python
"""Маршруты раздела «Отчёты». APPEND_SLASH=False — без trailing slash."""
from django.urls import path

from apps.reports.dashboard_views import (
    AttendanceDashboardStudentsView,
    AttendanceDashboardSummaryView,
)
from apps.reports.views import (
    ReportDownloadView,
    ReportRunView,
    ReportStatusView,
)

urlpatterns = [
    # Литеральные /status|/download|/attendance-dashboard — до /<report_type>/run
    # (str-конвертер жадный).
    path('/status/<str:task_id>', ReportStatusView.as_view(), name='reports-status'),
    path('/download/<str:task_id>', ReportDownloadView.as_view(), name='reports-download'),
    path('/attendance-dashboard/summary', AttendanceDashboardSummaryView.as_view(),
         name='reports-attendance-dashboard-summary'),
    path('/attendance-dashboard/students', AttendanceDashboardStudentsView.as_view(),
         name='reports-attendance-dashboard-students'),
    path('/<str:report_type>/run', ReportRunView.as_view(), name='reports-run'),
]
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/reports/tests/test_attendance_dashboard_api.py -q`
Expected: PASS, 13 тестов.

- [ ] **Step 6: Полный прогон**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

---

### Task 4: Период в эндпоинте уроков ученика

**Files:**
- Modify: `journal_django/apps/students/lesson_history.py` (функция `lesson_rows_queryset`)
- Modify: `journal_django/apps/students/views.py` (класс `StudentLessonsView`)
- Test: `journal_django/apps/students/tests/test_lesson_history.py`, `journal_django/apps/students/tests/test_student_lessons_api.py`

Модалке дашборда нужна та же таблица уроков, что во вкладке карточки, но за период.

- [ ] **Step 1: Написать падающие тесты**

Дописать в конец `journal_django/apps/students/tests/test_lesson_history.py`:

```python

# ---------------------------------------------------------------------------
# Необязательный период (нужен модалке дашборда «Посещения учеников»)
# ---------------------------------------------------------------------------

def test_period_filters_by_lesson_date(graph):
    _add_lesson(graph, number=1, date='2026-01-15')
    inside = _add_lesson(graph, number=2, date='2026-02-10')
    _add_lesson(graph, number=3, date='2026-03-01')

    rows = _rows(graph, date_from='2026-02-01', date_to='2026-02-28')
    assert [r['lesson_id'] for r in rows] == [inside]


def test_period_bounds_are_inclusive(graph):
    first = _add_lesson(graph, number=1, date='2026-02-01')
    last = _add_lesson(graph, number=2, date='2026-02-28')

    rows = _rows(graph, date_from='2026-02-01', date_to='2026-02-28')
    assert {r['lesson_id'] for r in rows} == {first, last}


def test_without_period_whole_history_is_returned(graph):
    """Вкладка карточки период не передаёт — её поведение меняться не должно."""
    old = _add_lesson(graph, number=1, date='2020-01-01')
    new = _add_lesson(graph, number=2, date='2026-02-10')

    assert {r['lesson_id'] for r in _rows(graph)} == {old, new}
```

Дописать в конец `journal_django/apps/students/tests/test_student_lessons_api.py`:

```python

def test_period_params_filter_rows(admin_client, graph):
    _add_lesson(graph, number=1, date='2026-01-15')
    inside = _add_lesson(graph, number=2, date='2026-02-10')

    data = admin_client.get(
        _url(graph) + '?date_from=2026-02-01&date_to=2026-02-28').json()
    assert [r['lesson_id'] for r in data['rows']] == [inside]


def test_invalid_period_returns_400(admin_client, graph):
    assert admin_client.get(_url(graph) + '?date_from=вчера').status_code == 400


def test_reversed_period_returns_400(admin_client, graph):
    resp = admin_client.get(_url(graph) + '?date_from=2026-02-28&date_to=2026-02-01')
    assert resp.status_code == 400
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/students/tests/test_lesson_history.py apps/students/tests/test_student_lessons_api.py -q`
Expected: FAIL — `TypeError: lesson_rows_queryset() got an unexpected keyword argument 'date_from'` и 200 вместо 400 на невалидном периоде.

- [ ] **Step 3: Добавить период в выборку**

В `journal_django/apps/students/lesson_history.py` заменить сигнатуру и тело `lesson_rows_queryset`:

```python
def lesson_rows_queryset(
    student_id: int,
    sort_by: str = DEFAULT_SORT_BY,
    sort_dir: str = DEFAULT_SORT_DIR,
    date_from: str | None = None,
    date_to: str | None = None,
) -> QuerySet[LessonAttendance]:
    """
    Записи вкладки в заданном порядке. По умолчанию — убывание даты СОХРАНЕНИЯ
    урока (submitted_at): даты занятия и сохранения расходятся, урок могут
    заполнить спустя дни, и свежезаполненное должно быть сверху.

    Сортировать можно по обеим датам (ORDERING_FIELDS) в обе стороны. Значения
    вне белого списка сюда не доходят — их отбивает вьюха (400), а здесь стоит
    второй рубеж: неизвестное значение откатывается на умолчание, а не уезжает
    в order_by сырой строкой.

    date_from/date_to — необязательный период по дате ЗАНЯТИЯ, границы
    включительно. Нужен модалке дашборда «Посещения учеников»; вкладка карточки
    период не передаёт и показывает всю историю.

    К ключу сортировки ВСЕГДА добавляется lesson_id — иначе записи с одинаковой
    датой могут менять порядок между запросами, и страница 2 повторит строку со
    страницы 1. Направление тай-брейка совпадает с основным.

    select_related на группу, направление и преподавателя: строка показывает их
    все, без него был бы N+1 на каждую строку страницы.
    """
    field = ORDERING_FIELDS.get(sort_by, ORDERING_FIELDS[DEFAULT_SORT_BY])
    prefix = '' if sort_dir == 'asc' else '-'
    qs = LessonAttendance.objects.filter(student_id=student_id, present=True)
    if date_from:
        qs = qs.filter(lesson__lesson_date__gte=date_from)
    if date_to:
        qs = qs.filter(lesson__lesson_date__lte=date_to)
    return (
        qs
        .select_related('lesson', 'lesson__group', 'lesson__group__direction',
                        'lesson__teacher')
        .order_by(f'{prefix}{field}', f'{prefix}lesson_id')
    )
```

- [ ] **Step 4: Разобрать период во вьюхе**

В `journal_django/apps/students/views.py`, в `StudentLessonsView.get`, заменить блок построения страницы на:

```python
        qp = request.query_params
        sort_by = qp.get('sort_by') or lesson_history.DEFAULT_SORT_BY
        sort_dir = qp.get('sort_dir') or lesson_history.DEFAULT_SORT_DIR
        allowed = sorted(lesson_history.ORDERING_FIELDS)
        if sort_by not in lesson_history.ORDERING_FIELDS:
            raise ValidationError(f"Invalid sort_by '{sort_by}'. Allowed: {allowed}")
        if sort_dir not in ('asc', 'desc'):
            raise ValidationError(
                f"Invalid sort_dir '{sort_dir}'. Must be 'asc' or 'desc'."
            )
        date_from, date_to = _parse_optional_period(qp)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(
            lesson_history.lesson_rows_queryset(pk, sort_by, sort_dir, date_from, date_to),
            request, view=self,
        )
        return paginator.get_paginated_response(lesson_history.serialize_rows(page, pk))
```

И добавить хелпер в том же файле, перед классом `StudentLessonsView`:

```python
def _parse_optional_period(qp) -> tuple[str | None, str | None]:
    """
    Необязательный период вкладки «Уроки»: обе границы включительно.

    Пусто — период не задан (вся история). Невалидная дата — 400, а не тихий
    прогон в SQL: неразобранная строка там превращается в 500.
    """
    raw_from = qp.get('date_from') or ''
    raw_to = qp.get('date_to') or ''
    parsed: list[str | None] = []
    for raw in (raw_from, raw_to):
        if not raw:
            parsed.append(None)
            continue
        try:
            parsed.append(date.fromisoformat(raw).isoformat())
        except ValueError:
            raise ValidationError({'error': 'date_from/date_to must be YYYY-MM-DD'})
    if parsed[0] and parsed[1] and parsed[1] < parsed[0]:
        raise ValidationError({'error': 'date_to must not be earlier than date_from'})
    return parsed[0], parsed[1]
```

В импорты `journal_django/apps/students/views.py` добавить строкой после `from __future__ import annotations`:

```python

from datetime import date
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/students/tests -q`
Expected: PASS — новые тесты зелёные, старые (вкладка без периода) не сломаны.

- [ ] **Step 6: Полный прогон**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

---

### Task 5: Общая таблица уроков на фронте

**Files:**
- Create: `journal_django/frontend/admin-src/src/components/lessons/StudentLessonsTable.tsx`
- Delete: `journal_django/frontend/admin-src/src/pages/students/StudentLessonsBlock.tsx`
- Modify: `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx`
- Modify: `journal_django/frontend/admin-src/src/hooks/useStudentLessons.ts`

Вкладка карточки и модалка дашборда показывают одну и ту же таблицу — второй копии быть не должно.

- [ ] **Step 1: Добавить период в хук**

В `journal_django/frontend/admin-src/src/hooks/useStudentLessons.ts` заменить функцию `useStudentLessons` на:

```ts
export interface StudentLessonsPeriod {
  /** 'YYYY-MM-DD'; обе границы включительно. Без периода — вся история. */
  dateFrom?: string;
  dateTo?: string;
}

/**
 * GET /api/admin/students/:id/lessons — серверно-пагинированный список уроков
 * ученика. Сортировка — по дате занятия или по дате сохранения, в обе стороны;
 * по умолчанию свежезаполненное сверху. Период необязателен: вкладка карточки
 * показывает всю историю, модалка дашборда — выбранный диапазон.
 */
export function useStudentLessons(
  studentId: number,
  page: number,
  pageSize: number,
  sortBy: StudentLessonSort,
  sortDir: 'asc' | 'desc',
  period: StudentLessonsPeriod = {},
) {
  const qs = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    sort_by: sortBy,
    sort_dir: sortDir,
  });
  if (period.dateFrom) qs.set('date_from', period.dateFrom);
  if (period.dateTo) qs.set('date_to', period.dateTo);
  const query = qs.toString();

  return useQuery({
    queryKey: ['students', 'lessons', studentId, query],
    queryFn: () =>
      api<Paginated<StudentLessonRow>>(
        'GET', `/api/admin/students/${studentId}/lessons?${query}`,
      ),
    placeholderData: keepPreviousData,
  });
}
```

- [ ] **Step 2: Перенести таблицу в общий компонент**

Создать `journal_django/frontend/admin-src/src/components/lessons/StudentLessonsTable.tsx` — полное содержимое `pages/students/StudentLessonsBlock.tsx` с тремя изменениями: имя компонента, пропсы (добавились период и заголовок) и относительные пути импортов (компонент лежит на уровень выше прежнего места):

```tsx
import { useState } from 'react';
import { DataTable, type Column } from '../table/DataTable';
import { EntityLink } from '../EntityLink';
import { EmptyState } from '../ui/EmptyState';
import {
  useStudentLessons,
  type StudentLessonSort,
  type StudentLessonsPeriod,
} from '../../hooks/useStudentLessons';
import { fmtDate, fmtDateTime, fmtLessons, fmtRub } from '../../lib/format';
import { STUDENT_LESSON_KIND_LABELS } from '../../lib/labels';
import type { StudentLessonRow } from '../../lib/types';

interface Props {
  studentId: number;
  /** Без периода — вся история (вкладка карточки). С периодом — модалка дашборда. */
  period?: StudentLessonsPeriod;
  /** Подпись таблицы для ассистивных технологий. */
  title?: string;
}

/**
 * Таблица уроков ученика: все занятия, на которых он был, по убыванию даты
 * сохранения. Обе даты в таблице — занятия и сохранения: они часто расходятся,
 * и без первой порядок строк выглядел бы случайным.
 *
 * «Признано» — точный FIFO по уроку (сколько денег списала именно эта строка).
 * Ноль честный: у бесплатного занятия денег не берут вовсе, у урока сверх
 * оплаченного их ещё нет — такая строка помечена «в долг».
 *
 * Один компонент на два экрана: вкладка «Уроки» карточки ученика и модалка
 * дашборда «Посещения учеников». Копия разъехалась бы с оригиналом.
 */
export default function StudentLessonsTable({ studentId, period, title }: Props) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [sortBy, setSortBy] = useState<StudentLessonSort>('submitted_at');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const { data, isFetching, isError } = useStudentLessons(
    studentId, page, pageSize, sortBy, sortDir, period,
  );

  const columns: Column<StudentLessonRow>[] = [
    { key: 'lesson_id', label: 'ID', sortable: false, width: 70 },
    {
      key: 'lesson_number',
      label: 'Номер урока',
      sortable: false,
      // numeric(5,1) приходит как «12.0» — fmtLessons убирает пустой хвост.
      cell: (r) => fmtLessons(Number(r.lesson_number)),
    },
    {
      key: 'lesson_date',
      label: 'Дата занятия',
      cell: (r) => fmtDate(r.lesson_date),
    },
    {
      key: 'submitted_at',
      label: 'Сохранён',
      cell: (r) => fmtDateTime(r.submitted_at),
    },
    {
      key: 'kind',
      label: 'Тип',
      sortable: false,
      cell: (r) => STUDENT_LESSON_KIND_LABELS[r.kind] || r.kind,
    },
    {
      key: 'duration_minutes',
      label: 'Продолжительность',
      sortable: false,
      cell: (r) => `${r.duration_minutes} мин`,
    },
    {
      key: 'group_name',
      label: 'Группа',
      sortable: false,
      cell: (r) => <EntityLink section="groups" id={r.group_id} text={r.group_name} />,
    },
    {
      key: 'teacher_name',
      label: 'Преподаватель',
      sortable: false,
      cell: (r) => <EntityLink section="teachers" id={r.teacher_id} text={r.teacher_name} />,
    },
    {
      key: 'direction_name',
      label: 'Направление',
      sortable: false,
      cell: (r) => r.direction_name || '—',
    },
    {
      key: 'recognized_amount',
      label: 'Признано',
      sortable: false,
      // У частично оплаченного урока признанная сумма больше нуля И стоит флаг
      // долга одновременно — партий хватило на часть веса. Пометка это
      // различает: иначе «1 000 ₽ в долг» читалось бы как «вся сумма в долг».
      cell: (r) => (
        <span className="slessons__money">
          {fmtRub(r.recognized_amount)}
          {r.is_debt && (
            <span className="slessons__debt">
              {Number(r.recognized_amount) > 0 ? 'частично в долг' : 'в долг'}
            </span>
          )}
        </span>
      ),
    },
  ];

  // Упавший запрос нельзя показывать пустой таблицей: «ничего не найдено» на
  // денежной вкладке прочитается как «уроков нет и денег не признано».
  if (isError) {
    return (
      <EmptyState hint="Обновите страницу — если повторится, сообщите администратору.">
        Не удалось загрузить уроки ученика
      </EmptyState>
    );
  }

  return (
    <DataTable<StudentLessonRow>
      data={data?.rows || []}
      columns={columns}
      title={title || 'Уроки ученика'}
      isLoading={isFetching}
      serverPagination={{
        page,
        pageSize,
        total: data?.total || 0,
        sortBy,
        sortDir,
        // Фильтров у таблицы нет: ни одна колонка не searchable, поэтому
        // тулбар фильтров схлопывается в null, а обработчик — заглушка.
        filters: {},
        onPageChange: setPage,
        onPageSizeChange: (size) => { setPageSize(size); setPage(1); },
        // Сортировать можно только по двум датам (белый список на бэке, мусор
        // даёт 400) — остальные колонки помечены sortable: false и сюда не
        // приходят. Смена порядка возвращает на первую страницу: иначе третья
        // страница нового порядка — это уже не то, что человек смотрел.
        onSortChange: (col, dir) => {
          setSortBy(col as StudentLessonSort);
          setSortDir(dir);
          setPage(1);
        },
        onFiltersChange: () => {},
      }}
    />
  );
}
```

- [ ] **Step 3: Удалить старый компонент и переключить вкладку**

Удалить файл `journal_django/frontend/admin-src/src/pages/students/StudentLessonsBlock.tsx`.

В `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx` заменить импорт:

```tsx
import StudentLessonsTable from '../../components/lessons/StudentLessonsTable';
```

(вместо строки `import StudentLessonsBlock from './StudentLessonsBlock';`)

и содержимое вкладки:

```tsx
    {
      value: 'lessons',
      label: 'Уроки',
      content: <StudentLessonsTable studentId={student.id} />,
    },
```

- [ ] **Step 4: Проверить типы**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: без ошибок. Если tsc ругается на оставшийся импорт `StudentLessonsBlock` — значит файл где-то ещё используется; найти и переключить на общий компонент.

---

### Task 6: Типы и хуки дашборда

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/shared-types.ts`
- Create: `journal_django/frontend/admin-src/src/hooks/useAttendanceDashboard.ts`

- [ ] **Step 1: Добавить типы**

В конец `journal_django/frontend/admin-src/src/lib/shared-types.ts` добавить:

```ts
// ===== Дашборд «Посещения учеников» (спека 2026-09-15) =====

/** Две цифры экрана. Уроки с весом (45 мин = 0,5) строками — точный Decimal. */
export interface AttendanceDashboardSummary {
  all_time_lessons: string;
  period_lessons: string;
}

/** Строка ученика: разбивка занятий внутри выбранного периода, всё в уроках. */
export interface AttendanceDashboardRow {
  student_id: number;
  full_name: string;
  regular: string;
  extra: string;
  burned: string;
  free: string;
  /** Итого списано = обычные + доп.уроки + сгоревшие. Бесплатные не входят. */
  billed: string;
}
```

- [ ] **Step 2: Создать хуки**

Создать `journal_django/frontend/admin-src/src/hooks/useAttendanceDashboard.ts`:

```ts
import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type {
  AttendanceDashboardRow,
  AttendanceDashboardSummary,
  Paginated,
} from '../lib/types';

const BASE = '/api/admin/reports/attendance-dashboard';

/** Ключи сортировки списка (белый список на бэке; мусор даёт 400). */
export type AttendanceSort = 'billed' | 'full_name';

export interface AttendanceDashboardParams {
  dateFrom: string;
  dateTo: string;
}

/**
 * Две цифры экрана. Отдельный запрос от списка: так сводка не пересчитывается
 * при листании и не реагирует на фильтр по имени — она про всю школу.
 */
export function useAttendanceDashboardSummary(p: AttendanceDashboardParams) {
  return useQuery({
    queryKey: ['attendance-dashboard', 'summary', p.dateFrom, p.dateTo],
    queryFn: () =>
      api<AttendanceDashboardSummary>(
        'GET', `${BASE}/summary?date_from=${p.dateFrom}&date_to=${p.dateTo}`,
      ),
    placeholderData: keepPreviousData,
  });
}

export interface AttendanceStudentsParams extends AttendanceDashboardParams {
  page: number;
  pageSize: number;
  sortBy: AttendanceSort;
  sortDir: 'asc' | 'desc';
  nameQuery: string;
}

/** Серверно-пагинированный список учеников с разбивкой по типам занятий. */
export function useAttendanceDashboardStudents(p: AttendanceStudentsParams) {
  const qs = new URLSearchParams({
    date_from: p.dateFrom,
    date_to: p.dateTo,
    page: String(p.page),
    page_size: String(p.pageSize),
    sort_by: p.sortBy,
    sort_dir: p.sortDir,
  });
  if (p.nameQuery) qs.set('filter[full_name]', p.nameQuery);
  const query = qs.toString();

  return useQuery({
    queryKey: ['attendance-dashboard', 'students', query],
    queryFn: () => api<Paginated<AttendanceDashboardRow>>('GET', `${BASE}/students?${query}`),
    placeholderData: keepPreviousData,
  });
}
```

- [ ] **Step 3: Проверить типы**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: без ошибок.

---

### Task 7: Страница дашборда

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/reports/AttendanceDashboardPage.tsx`
- Modify: `journal_django/frontend/admin-src/src/App.tsx`
- Modify: `journal_django/frontend/admin-src/src/styles/pages/detail.css`

- [ ] **Step 1: Создать страницу**

Создать `journal_django/frontend/admin-src/src/pages/reports/AttendanceDashboardPage.tsx`:

```tsx
import { useState } from 'react';
import { PageHeader } from '../../components/shell/PageHeader';
import { StatTiles } from '../../components/detail/StatTiles';
import { DataTable, type Column } from '../../components/table/DataTable';
import { RowOpenButton } from '../../components/table/RowOpenButton';
import { Dialog } from '../../components/ui/Dialog';
import { EmptyState } from '../../components/ui/EmptyState';
import { Field } from '../../components/form/Field';
import { DateInput } from '../../components/form/DateInput';
import StudentLessonsTable from '../../components/lessons/StudentLessonsTable';
import {
  useAttendanceDashboardStudents,
  useAttendanceDashboardSummary,
  type AttendanceSort,
} from '../../hooks/useAttendanceDashboard';
import { fmtDate, fmtLessons, todayMSK } from '../../lib/format';
import type { AttendanceDashboardRow } from '../../lib/types';

/** Первое и последнее число текущего месяца по МСК — период по умолчанию. */
function currentMonth(): { from: string; to: string } {
  const today = todayMSK();              // 'YYYY-MM-DD'
  const [y, m] = today.split('-').map(Number);
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const mm = String(m).padStart(2, '0');
  return { from: `${y}-${mm}-01`, to: `${y}-${mm}-${String(last).padStart(2, '0')}` };
}

const lessons = (v: string | undefined) => fmtLessons(Number(v || 0));

/**
 * Дашборд «Посещения учеников»: сколько уроков отработано всего и за период,
 * и как это раскладывается по ученикам. Клик по строке открывает детализацию
 * занятий этого ученика за тот же период.
 *
 * Счётчик везде один — списанные уроки с весом (45 минут = 0,5): обычные,
 * доп.уроки и сгорания. Бесплатные видны отдельной колонкой, но в «Итого» не
 * входят: с абонемента за них не списывается, и подмешать их значило бы
 * разойтись с балансами.
 */
export default function AttendanceDashboardPage() {
  const month = currentMonth();
  const [dateFrom, setDateFrom] = useState(month.from);
  const [dateTo, setDateTo] = useState(month.to);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [sortBy, setSortBy] = useState<AttendanceSort>('billed');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [nameQuery, setNameQuery] = useState('');
  const [openStudent, setOpenStudent] = useState<AttendanceDashboardRow | null>(null);

  const summary = useAttendanceDashboardSummary({ dateFrom, dateTo });
  const students = useAttendanceDashboardStudents({
    dateFrom, dateTo, page, pageSize, sortBy, sortDir, nameQuery,
  });

  const columns: Column<AttendanceDashboardRow>[] = [
    { key: 'full_name', label: 'Ученик', searchable: true },
    { key: 'regular', label: 'Обычные', sortable: false, cell: (r) => lessons(r.regular) },
    { key: 'extra', label: 'Доп.уроки', sortable: false, cell: (r) => lessons(r.extra) },
    { key: 'burned', label: 'Сгоревшие', sortable: false, cell: (r) => lessons(r.burned) },
    { key: 'free', label: 'Бесплатные', sortable: false, cell: (r) => lessons(r.free) },
    { key: 'billed', label: 'Итого списано', cell: (r) => lessons(r.billed) },
  ];

  const periodLabel = `${fmtDate(dateFrom)} — ${fmtDate(dateTo)}`;

  return (
    <>
      <PageHeader
        title="Посещения учеников"
        sub="Отработанные уроки с учётом половинных занятий: 45 минут считаются за 0,5 урока."
      />

      <div className="page-toolbar">
        <Field label="Период с">
          <DateInput value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }} />
        </Field>
        <Field label="по">
          <DateInput value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1); }} />
        </Field>
      </div>

      <StatTiles
        items={[
          {
            label: 'Отработано за всё время',
            value: lessons(summary.data?.all_time_lessons),
            sub: 'по всем ученикам',
          },
          {
            label: 'Отработано за период',
            value: lessons(summary.data?.period_lessons),
            sub: periodLabel,
          },
        ]}
      />

      {students.isError ? (
        <EmptyState hint="Обновите страницу — если повторится, сообщите администратору.">
          Не удалось загрузить список учеников
        </EmptyState>
      ) : (
        <DataTable<AttendanceDashboardRow>
          data={students.data?.rows || []}
          columns={columns}
          title="Ученики за период"
          isLoading={students.isFetching}
          onRowClick={(row) => setOpenStudent(row)}
          rowAction={(row) => <RowOpenButton to={`/admin/students/${row.student_id}`} />}
          serverPagination={{
            page,
            pageSize,
            total: students.data?.total || 0,
            sortBy,
            sortDir,
            filters: nameQuery ? { full_name: nameQuery } : {},
            onPageChange: setPage,
            onPageSizeChange: (size) => { setPageSize(size); setPage(1); },
            onSortChange: (col, dir) => {
              setSortBy(col as AttendanceSort);
              setSortDir(dir);
              setPage(1);
            },
            onFiltersChange: (next) => { setNameQuery(next.full_name || ''); setPage(1); },
          }}
        />
      )}

      {openStudent && (
        <Dialog
          open
          onOpenChange={(o) => !o && setOpenStudent(null)}
          title={`${openStudent.full_name} · ${periodLabel}`}
          wide
        >
          <StudentLessonsTable
            studentId={openStudent.student_id}
            period={{ dateFrom, dateTo }}
            title={`Уроки ученика за период ${periodLabel}`}
          />
        </Dialog>
      )}
    </>
  );
}
```

Примечание к строке: ФИО показывается текстом, а ссылка на карточку живёт в кнопке «Открыть» справа (`RowOpenButton`, общий приём раздела). Ссылка внутри кликабельной строки конфликтовала бы с открытием модалки — два разных действия по одному клику.

- [ ] **Step 2: Добавить маршрут**

В `journal_django/frontend/admin-src/src/App.tsx` добавить импорт рядом с остальными страницами отчётов:

```tsx
import AttendanceDashboardPage from './pages/reports/AttendanceDashboardPage';
```

и маршрут ПЕРЕД строкой с `/admin/reports/:reportType` (сегментов больше, конфликта нет, но порядок читается лучше):

```tsx
            <Route path="/admin/reports/dashboard/attendance" element={<RequireRole roles={['manager','admin','superadmin']}><AttendanceDashboardPage /></RequireRole>} />
```

- [ ] **Step 3: Добавить стиль тулбара периода**

Класса `.page-toolbar` в стилях сейчас нет (проверено), токены `--space-3` и
`--space-4` объявлены в `styles/tokens.css`. Дописать в конец
`journal_django/frontend/admin-src/src/styles/pages/detail.css`:

```css
/* Ряд контролов над таблицей (период дашборда): поля в строку, перенос на узком. */
.page-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
```

Hardcoded отступы не заводить — только токены.

- [ ] **Step 4: Проверить типы**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: без ошибок.

---

### Task 8: Вкладки раздела «Отчёты»

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/reports/ReportsPage.tsx`

- [ ] **Step 1: Переписать страницу списка на вкладки**

Заменить содержимое `journal_django/frontend/admin-src/src/pages/reports/ReportsPage.tsx` на:

```tsx
import { useSearchParams } from 'react-router-dom';
import { DataTable, type Column } from '../../components/table/DataTable';
import { RowOpenButton } from '../../components/table/RowOpenButton';
import { PageHeader } from '../../components/shell/PageHeader';
import { Tabs, type TabItem } from '../../components/ui/Tabs';
import { REPORT_TYPES, type ReportTypeDef } from '../../lib/reports';

/**
 * Раздел «Отчёты»: две вкладки.
 *
 * «Отчёты» — фоновые выгрузки: строка отвечает на вопрос «какие отчёты есть»,
 * настройка и запуск живут на странице отчёта (тот же паттерн «список →
 * карточка», что у учеников, групп и преподавателей).
 *
 * «Дашборд» — живые экраны со сводками. Пока один; список сделан таблицей, а не
 * единственной ссылкой, чтобы второй лёг рядом строкой, а не переделкой раздела.
 */
const columns: Column<ReportTypeDef>[] = [
  { key: 'title', label: 'Отчёт', cell: (row) => <span className="report-list__name">{row.title}</span> },
];

interface DashboardDef {
  key: string;
  title: string;
  desc: string;
  path: string;
}

const DASHBOARDS: DashboardDef[] = [
  {
    key: 'attendance',
    title: 'Посещения учеников',
    desc: 'Отработанные уроки за всё время и за период, с разбивкой по ученикам',
    path: '/admin/reports/dashboard/attendance',
  },
];

const dashboardColumns: Column<DashboardDef>[] = [
  { key: 'title', label: 'Дашборд', cell: (row) => <span className="report-list__name">{row.title}</span> },
];

const TABS = ['reports', 'dashboard'] as const;
type ReportsTab = (typeof TABS)[number];
const DEFAULT_TAB: ReportsTab = 'reports';

function isTab(value: string | null): value is ReportsTab {
  return !!value && (TABS as readonly string[]).includes(value);
}

export default function ReportsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get('tab');
  const activeTab: ReportsTab = isTab(raw) ? raw : DEFAULT_TAB;

  const setActiveTab = (tab: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (tab === DEFAULT_TAB) next.delete('tab'); else next.set('tab', tab);
      return next;
    }, { replace: true });
  };

  const tabs: TabItem[] = [
    {
      value: 'reports',
      label: 'Отчёты',
      content: (
        <DataTable<ReportTypeDef>
          data={REPORT_TYPES}
          columns={columns}
          title="Список доступных отчётов"
          roomy
          rowAction={(row) => (
            <RowOpenButton to={`/admin/reports/${row.reportType}`} title={row.desc} />
          )}
        />
      ),
    },
    {
      value: 'dashboard',
      label: 'Дашборд',
      content: (
        <DataTable<DashboardDef>
          data={DASHBOARDS}
          columns={dashboardColumns}
          title="Список доступных дашбордов"
          roomy
          rowAction={(row) => <RowOpenButton to={row.path} title={row.desc} />}
        />
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Отчёты"
        sub="Выгрузки формируются в фоне: файл скачивается сразу по готовности и на платформе не хранится."
      />
      <Tabs items={tabs} value={activeTab} onChange={setActiveTab} />
    </>
  );
}
```

- [ ] **Step 2: Проверить типы**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: без ошибок.

---

### Task 9: Сборка и проверка

**Files:**
- Modify: `journal_django/frontend/admin-dist/**` (артефакты сборки)

- [ ] **Step 1: Полный прогон тестов**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, падений нет.

- [ ] **Step 2: Собрать admin SPA**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: сборка без ошибок.

- [ ] **Step 3: Проверить состав сборки**

Run: `git status --short journal_django/frontend/admin-dist`
Expected: изменены `index.html` и хешированные бандлы, ничего постороннего.

- [ ] **Step 4: Ручная проверка в браузере**

Открыть «Отчёты» → вкладка «Дашборд» → «Посещения учеников» и проверить:

1. Вкладка «Дашборд» переключается, адрес получает `?tab=dashboard`, строка «Посещения учеников» открывает экран.
2. Период по умолчанию — текущий месяц; смена дат меняет вторую плитку и таблицу, первая плитка («за всё время») не меняется.
3. Фильтр по имени сужает таблицу и НЕ меняет обе плитки.
4. Сортировка по «Итого списано» и по «Ученик» работает в обе стороны.
5. У ученика с 45-минутными занятиями числа дробные (0,5 / 1,5), а не округлённые.
6. Сумма колонки «Итого списано» по видимым строкам не больше плитки за период (на одной странице — часть школы).
7. Клик по строке открывает модалку с уроками ТОЛЬКО за выбранный период; кнопка «Открыть» справа ведёт в карточку ученика.
8. Вкладка «Уроки» в карточке ученика по-прежнему показывает всю историю.

Если пункт не сходится — чинить до завершения.

---

## Чего в этом плане нет

Сознательно за рамками (из спеки): графики и динамика по месяцам, выгрузка экрана в Excel, разрезы по преподавателю, группе и направлению, любые мутации.
