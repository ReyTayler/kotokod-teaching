# Вкладка «Уроки» в карточке ученика — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** В карточке ученика (Admin SPA) появляется вкладка «Уроки» со всеми его уроками: ID, даты, тип, продолжительность, группа, преподаватель, направление и сколько денег этим уроком отработано.

**Architecture:** «Признано» считается новым разрезом внутри общей FIFO-функции (`compute_fifo`), а не отдельным проходом — одна очередь FIFO на весь проект, поэтому вкладка сходится с отчётом по поступлениям и дашбордом. Бэкенд: новый read-only эндпоинт `GET /api/admin/students/<id>/lessons` (`IsManagerOrAdmin`, `StandardPagination`), строки берутся из `lesson_attendance` с `present=true`, деньги — картой `lesson_id → сумма`, построенной по всей истории ученика. Фронт: новая вкладка с таблицей на `DataTable` в server-режиме.

**Tech Stack:** Django 5 + DRF (`journal_django/`), PostgreSQL, pytest; React 19 + TanStack Query v5 + Vite (`journal_django/frontend/admin-src/`).

**Спека:** `docs/superpowers/specs/2026-09-14-student-lessons-tab-design.md`

---

## Структура файлов

| Файл | Ответственность |
|---|---|
| `journal_django/apps/finances/fifo.py` | **Правка.** Два новых разреза: признано по уроку и перерасход по уроку. |
| `journal_django/apps/finances/repository.py` | **Правка.** Общий хелпер «партии + потребления одного ученика» (выносится из `student_fifo_remaining`) и новая функция `student_lesson_recognition`. |
| `journal_django/apps/students/lesson_history.py` | **Создать.** Строки вкладки: запрос посещаемости, выводимый тип, склейка с деньгами. Отдельный модуль — `students/repository.py` и так 560+ строк, а у вкладки своя замкнутая ответственность (прецедент: `finances/student_month.py`, `lessons/attendance_report.py`). |
| `journal_django/apps/students/views.py` | **Правка.** `StudentLessonsView` — тонкая вьюха. |
| `journal_django/apps/students/urls.py` | **Правка.** Маршрут `/<int:pk>/lessons`. |
| `journal_django/apps/finances/tests/test_fifo.py` | **Правка.** Тесты чистой функции на новые разрезы. |
| `journal_django/apps/finances/tests/test_lesson_recognition.py` | **Создать.** Тесты карты «урок → деньги» на реальной БД. |
| `journal_django/apps/students/tests/test_student_lessons_api.py` | **Создать.** E2E: состав строк, порядок, типы, RBAC. |
| `journal_django/frontend/admin-src/src/lib/shared-types.ts` | **Правка.** `StudentLessonKind`, `StudentLessonRow`. Здесь лежат все типы админки; `lib/types.ts` — однострочный barrel `export * from './shared-types'`, править его не нужно. |
| `journal_django/frontend/admin-src/src/lib/labels.ts` | **Правка.** `STUDENT_LESSON_KIND_LABELS`. |
| `journal_django/frontend/admin-src/src/hooks/useStudentLessons.ts` | **Создать.** Хук серверной пагинации. |
| `journal_django/frontend/admin-src/src/pages/students/StudentLessonsBlock.tsx` | **Создать.** Таблица вкладки. |
| `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx` | **Правка.** Регистрация вкладки. |

**Важно про тесты:** гонять только полный `pytest -q` из `journal_django/` — часть приложений no-op'ит `django_db_setup` (общая `journal_test`), часть пересоздаёт `test_journal_test`; прогон по приложениям даёт ложный результат. Внутри задачи допустимо запускать один файл для скорости, но перед коммитом задачи — полный прогон.

---

### Task 1: Разрез FIFO по уроку

**Files:**
- Modify: `journal_django/apps/finances/fifo.py`
- Test: `journal_django/apps/finances/tests/test_fifo.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `journal_django/apps/finances/tests/test_fifo.py`:

```python
# ---------------------------------------------------------------------------
# Разрез по уроку — вкладка «Уроки» в карточке ученика (спека 2026-09-14)
# ---------------------------------------------------------------------------

def test_by_lesson_single_lesson():
    lots = [{'lessons': 4, 'price_per_lesson': _D(500)}]
    cons = [{'units': 1, 'date': '2026-06-10', 'lesson_id': 11}]
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_lesson'] == {11: _D('500')}
    assert r['over_consumed_by_lesson'] == {}


def test_by_lesson_half_lesson_costs_half():
    """45 минут = 0.5 урока → списывается полцены партии."""
    lots = [{'lessons': 4, 'price_per_lesson': _D(500)}]
    cons = [{'units': 0.5, 'date': '2026-06-10', 'lesson_id': 12}]
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_lesson'] == {12: _D('250.0')}


def test_by_lesson_spanning_two_lots_sums_both_parts():
    """Урок на стыке абонементов гасится двумя партиями — в разрезе сумма обеих."""
    lots = [
        {'lessons': _D('0.5'), 'price_per_lesson': _D(500)},
        {'lessons': 4, 'price_per_lesson': _D(400)},
    ]
    cons = [{'units': 1, 'date': '2026-06-10', 'lesson_id': 13}]
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_lesson'] == {13: _D('450.0')}


def test_by_lesson_debt_lesson_has_no_money_and_is_over_consumed():
    """Урок сверх оплаченного: денег не признано, урок попал в перерасход."""
    lots = [{'lessons': 1, 'price_per_lesson': _D(500)}]
    cons = [
        {'units': 1, 'date': '2026-06-10', 'lesson_id': 21},
        {'units': 1, 'date': '2026-06-11', 'lesson_id': 22},
    ]
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_lesson'] == {21: _D('500')}
    assert r['over_consumed_by_lesson'] == {22: _D('1')}


def test_by_lesson_partially_paid_lesson_is_both_recognized_and_debt():
    """Партий хватило на половину урока: полцены признано, полурока — долг."""
    lots = [{'lessons': _D('0.5'), 'price_per_lesson': _D(500)}]
    cons = [{'units': 1, 'date': '2026-06-10', 'lesson_id': 31}]
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_lesson'] == {31: _D('250.0')}
    assert r['over_consumed_by_lesson'] == {31: _D('0.5')}


def test_by_lesson_sum_equals_worked_off_total():
    """Разрез не расходится с итогом — иначе колонка врёт относительно отчётов."""
    lots = [
        {'lessons': 4, 'price_per_lesson': _D(500)},
        {'lessons': 4, 'price_per_lesson': _D(450)},
    ]
    cons = [
        {'units': 1, 'date': '2026-05-10', 'lesson_id': 41},
        {'units': 0.5, 'date': '2026-06-10', 'lesson_id': 42},
        {'units': 1, 'date': '2026-06-11', 'lesson_id': 43},
        {'units': 1, 'date': '2026-06-12', 'lesson_id': 44},
        {'units': 1, 'date': '2026-06-13', 'lesson_id': 45},
    ]
    r = compute_fifo(lots, cons, MS, ME)
    assert sum(r['worked_off_by_lesson'].values()) == r['worked_off_total']


def test_by_lesson_ignores_consumptions_without_lesson_id():
    """Синтетический возврат урока не имеет — в разрезе его быть не должно."""
    lots = [{'lessons': 4, 'price_per_lesson': _D(500)}]
    cons = [
        {'units': 1, 'date': '2026-06-10', 'lesson_id': 51},
        {'units': 3, 'date': '2026-06-20', 'direction_id': None, 'refund': True},
    ]
    r = compute_fifo(lots, cons, MS, ME)
    assert r['worked_off_by_lesson'] == {51: _D('500')}
    assert r['over_consumed_by_lesson'] == {}
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd journal_django && pytest apps/finances/tests/test_fifo.py -k by_lesson -q`
Expected: FAIL — `KeyError: 'worked_off_by_lesson'` во всех семи тестах.

- [ ] **Step 3: Добавить накопители в `compute_fifo`**

В `journal_django/apps/finances/fifo.py` после строки `unit_qtys_month: list[Decimal] = []  # уроков (units, half-lesson=0.5) на каждую цену` добавить:

```python
    # Разрез ПО УРОКУ (вкладка «Уроки» карточки ученика, спека 2026-09-14):
    # сколько денег списала конкретная запись потребления и сколько её уроков
    # прошло сверх оплаченного остатка. Ключ — lesson_id записи; потребления без
    # него (синтетические возвраты) в разрезы не попадают. Значения — ТОЧНЫЕ
    # Decimal без округления, как у разрезов по платежу: округляет потребитель,
    # один раз на строку.
    by_lesson: dict = {}
    over_consumed_by_lesson: dict = {}
```

- [ ] **Step 4: Копить разрезы внутри цикла**

В том же файле, в цикле `for c in consumptions:` после строки `is_refund = bool(c.get('refund'))` добавить:

```python
        lesson_id = c.get('lesson_id')
```

Внутри `if not is_refund:` — сразу после строки `worked_off_total += value` добавить:

```python
                if lesson_id is not None:
                    by_lesson[lesson_id] = by_lesson.get(lesson_id, _ZERO) + value
```

Блок перерасхода в конце цикла привести к виду:

```python
        if need > 0 and not is_refund:
            over_consumed_lessons += need
            if lesson_id is not None:
                over_consumed_by_lesson[lesson_id] = (
                    over_consumed_by_lesson.get(lesson_id, _ZERO) + need
                )
            if in_month:
                over_consumed_month += need
```

- [ ] **Step 5: Вернуть новые ключи**

В `return {...}` той же функции, перед строкой `# Перерасход внутри [month_start, month_end):` добавить:

```python
        # { lesson_id: Decimal } — признанные деньги в разрезе конкретного урока
        # и { lesson_id: Decimal } — сколько уроков этой записи прошло сверх
        # оплаченного. Точные Decimal без округления (потребитель —
        # apps/finances/repository.py::student_lesson_recognition).
        'worked_off_by_lesson': dict(by_lesson),
        'over_consumed_by_lesson': dict(over_consumed_by_lesson),
```

- [ ] **Step 6: Дописать docstring модуля**

В docstring `journal_django/apps/finances/fifo.py` строку описания `consumptions` привести к виду:

```
consumptions: [{ 'units': 1|0.5, 'date': 'YYYY-MM-DD', 'direction_id': int|None,
              'lesson_id': int|None }] — в порядке даты урока.
              direction_id — направление УРОКА (не оплаты), опционально.
              lesson_id — урок записи; нужен разрезу worked_off_by_lesson
              (вкладка «Уроки» карточки ученика), опционален.
```

- [ ] **Step 7: Убедиться, что тесты проходят**

Run: `cd journal_django && pytest apps/finances/tests/test_fifo.py -q`
Expected: PASS, все тесты файла (старые golden-кейсы не должны сломаться — новые ключи только добавляются).

- [ ] **Step 8: Полный прогон**

Run: `cd journal_django && pytest -q`
Expected: PASS. Падений быть не должно — существующие ключи возврата не менялись.

- [ ] **Step 9: Commit**

```bash
git add journal_django/apps/finances/fifo.py journal_django/apps/finances/tests/test_fifo.py
git commit -m "feat(finances): разрез FIFO по уроку — worked_off_by_lesson

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Карта «урок → признанные деньги» для ученика

**Files:**
- Modify: `journal_django/apps/finances/repository.py` (функция `student_fifo_remaining`, ~строки 286-362)
- Test: `journal_django/apps/finances/tests/test_lesson_recognition.py` (создать)

- [ ] **Step 1: Написать падающие тесты**

Создать `journal_django/apps/finances/tests/test_lesson_recognition.py`:

```python
"""
Тесты student_lesson_recognition — сколько денег списал каждый урок ученика.

Источник колонки «Признано» во вкладке «Уроки» карточки ученика
(спека 2026-09-14). Считается точным FIFO по всей истории ученика.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection

from apps.finances.repository import student_lesson_recognition

pytestmark = pytest.mark.django_db


def _add_payment(sid, did, lessons, total, graph_cleanup, kind='purchase', subs=1,
                 paid_at='2026-01-01'):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, "
            "lessons_count, kind, unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'t') RETURNING id",
            [sid, did, subs, lessons, kind, 0, total, paid_at])
        pid = cur.fetchone()[0]
    graph_cleanup['payments'].append(pid)
    return pid


def _add_lesson(gid, tid, sid, graph_cleanup, *, date='2026-02-10', number=1,
                duration=60, lesson_type='regular', present=True, is_free=False):
    """Урок + запись посещаемости ученика. Возвращает lesson_id."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s, %s, %s, %s, %s, %s, 't') RETURNING id",
            [gid, tid, date, number, duration, lesson_type])
        lid = cur.fetchone()[0]
        graph_cleanup['lessons'].append(lid)
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present, is_free) '
            'VALUES (%s, %s, %s, %s)', [lid, sid, present, is_free])
    return lid


def test_regular_lesson_recognizes_lot_price(
        student_fixture, direction_fixture, group_fixture, teacher_id_fixture, graph_cleanup):
    _add_payment(student_fixture, direction_fixture, 4, 4000, graph_cleanup)
    lid = _add_lesson(group_fixture, teacher_id_fixture, student_fixture, graph_cleanup)

    rec = student_lesson_recognition(student_fixture)
    assert rec[lid] == {'recognized': Decimal('1000.00'), 'is_debt': False}


def test_half_lesson_recognizes_half_price(
        student_fixture, direction_fixture, group_fixture, teacher_id_fixture, graph_cleanup):
    """45 минут = 0.5 урока — половина цены партии."""
    _add_payment(student_fixture, direction_fixture, 4, 4000, graph_cleanup)
    lid = _add_lesson(group_fixture, teacher_id_fixture, student_fixture, graph_cleanup,
                      duration=45)

    rec = student_lesson_recognition(student_fixture)
    assert rec[lid] == {'recognized': Decimal('500.00'), 'is_debt': False}


def test_free_lesson_recognizes_nothing(
        student_fixture, direction_fixture, group_fixture, teacher_id_fixture, graph_cleanup):
    """За бесплатное занятие деньги не берутся — его в карте нет вовсе."""
    _add_payment(student_fixture, direction_fixture, 4, 4000, graph_cleanup)
    lid = _add_lesson(group_fixture, teacher_id_fixture, student_fixture, graph_cleanup,
                      is_free=True)

    rec = student_lesson_recognition(student_fixture)
    assert lid not in rec


def test_extra_and_burned_lessons_consume_money(
        student_fixture, direction_fixture, group_fixture, teacher_id_fixture, graph_cleanup):
    """Доп.урок и сгорание — такие же списания с партий, как обычный урок."""
    _add_payment(student_fixture, direction_fixture, 4, 4000, graph_cleanup)
    extra = _add_lesson(group_fixture, teacher_id_fixture, student_fixture, graph_cleanup,
                        date='2026-02-11', number=2, lesson_type='extra')
    burned = _add_lesson(group_fixture, teacher_id_fixture, student_fixture, graph_cleanup,
                         date='2026-02-12', number=3, lesson_type='burned')

    rec = student_lesson_recognition(student_fixture)
    assert rec[extra] == {'recognized': Decimal('1000.00'), 'is_debt': False}
    assert rec[burned] == {'recognized': Decimal('1000.00'), 'is_debt': False}


def test_lesson_beyond_paid_balance_is_debt(
        student_fixture, direction_fixture, group_fixture, teacher_id_fixture, graph_cleanup):
    """Оплачен 1 урок, проведено 2 — второй в долг: 0 ₽ и флаг."""
    _add_payment(student_fixture, direction_fixture, 1, 1000, graph_cleanup)
    first = _add_lesson(group_fixture, teacher_id_fixture, student_fixture, graph_cleanup,
                        date='2026-02-10', number=1)
    second = _add_lesson(group_fixture, teacher_id_fixture, student_fixture, graph_cleanup,
                         date='2026-02-11', number=2)

    rec = student_lesson_recognition(student_fixture)
    assert rec[first] == {'recognized': Decimal('1000.00'), 'is_debt': False}
    assert rec[second] == {'recognized': Decimal('0.00'), 'is_debt': True}


def test_lesson_spanning_two_payments_sums_both_prices(
        student_fixture, direction_fixture, group_fixture, teacher_id_fixture, graph_cleanup):
    """Половинный урок на стыке абонементов гасит обе партии — сумма долей."""
    _add_payment(student_fixture, direction_fixture, 1, 1000, graph_cleanup,
                 paid_at='2026-01-01')
    _add_payment(student_fixture, direction_fixture, 4, 2000, graph_cleanup,
                 paid_at='2026-01-15')
    first = _add_lesson(group_fixture, teacher_id_fixture, student_fixture, graph_cleanup,
                        date='2026-02-10', number=1, duration=45)
    second = _add_lesson(group_fixture, teacher_id_fixture, student_fixture, graph_cleanup,
                         date='2026-02-11', number=2, duration=60)

    rec = student_lesson_recognition(student_fixture)
    # Первая партия: 1 урок по 1000. Половинный урок съел 0.5 → 500.
    assert rec[first] == {'recognized': Decimal('500.00'), 'is_debt': False}
    # Второй урок: остаток первой партии 0.5 × 1000 + 0.5 × 500 = 750.
    assert rec[second] == {'recognized': Decimal('750.00'), 'is_debt': False}


def test_lesson_after_refund_becomes_debt(
        student_fixture, direction_fixture, group_fixture, teacher_id_fixture, graph_cleanup):
    """Возврат гасит остаток — урок после него проведён в долг."""
    _add_payment(student_fixture, direction_fixture, 4, 4000, graph_cleanup,
                 paid_at='2026-01-01')
    _add_payment(student_fixture, None, -4, -4000, graph_cleanup, kind='refund',
                 subs=None, paid_at='2026-01-05')
    lid = _add_lesson(group_fixture, teacher_id_fixture, student_fixture, graph_cleanup,
                      date='2026-02-10', number=1)

    rec = student_lesson_recognition(student_fixture)
    assert rec[lid] == {'recognized': Decimal('0.00'), 'is_debt': True}


def test_no_payments_no_lessons_gives_empty_map(student_fixture):
    assert student_lesson_recognition(student_fixture) == {}
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd journal_django && pytest apps/finances/tests/test_lesson_recognition.py -q`
Expected: FAIL — `ImportError: cannot import name 'student_lesson_recognition'`.

- [ ] **Step 3: Добавить `round_kopecks` в импорты**

В `journal_django/apps/finances/repository.py` заменить строку:

```python
from apps.core.utils.decimal import to_decimal
```

на:

```python
from apps.core.utils.decimal import round_kopecks, to_decimal
```

- [ ] **Step 4: Вынести построение партий и потреблений в общий хелпер**

В `journal_django/apps/finances/repository.py` заменить тело `student_fifo_remaining` (весь блок от `from apps.finances.fifo import compute_fifo` до `return {...}` включительно) на:

```python
    from apps.finances.fifo import compute_fifo

    remaining_lessons = balance_for_student(student_id)
    lots, cons = _student_fifo_args(student_id)
    fifo = compute_fifo(lots, cons, '0001-01-01', '9999-12-31')
    return {
        'remaining_lessons': remaining_lessons,
        'remaining_value': fifo['remaining_value'],
        'remaining_by_direction': fifo['remaining_by_direction'],
    }


def _student_fifo_args(student_id: int) -> tuple[list, list]:
    """
    Партии и потребления ОДНОГО ученика — общий вход всех per-student расчётов
    FIFO (остаток к возврату, признание по урокам). Одно построение на модуль:
    два независимых обхода оплат разъехались бы при первой же правке правил
    (доплаты, возвраты, бесплатные занятия).

    Каждое потребление несёт lesson_id — по нему compute_fifo строит разрез
    worked_off_by_lesson (вкладка «Уроки» карточки ученика). Синтетические
    списания-возвраты урока не имеют и в разрез не попадают.
    """
    payment_rows = (
        Payment.objects.filter(student_id=student_id)
        .exclude(kind='surcharge')          # доплаты партий не образуют
        .order_by('paid_at', 'id')
        .values('id', 'total_amount', 'lessons_count', 'kind', 'paid_at', 'direction_id')
    )
    purchase_rows = []
    refund_cons = []
    for r in payment_rows:
        if r['kind'] == 'refund':
            raw = r['lessons_count']
            refund_cons.append({
                'units': -to_decimal(raw) if raw is not None else Decimal('0'),
                'date': _date_str(r['paid_at']),
                'direction_id': None,
                'refund': True,
            })
            continue
        lessons = int(r['lessons_count']) if r['lessons_count'] is not None else 0
        if lessons > 0:
            purchase_rows.append(r)

    lots = build_lots(purchase_rows, surcharges_by_parent(student_id))

    cons_rows = (
        # is_free=False — как в fifo_inputs и balances_for_students: за бесплатное
        # занятие деньги не берутся, партии оно не гасит. Иначе остаток к возврату
        # оказался бы меньше баланса и клиент недополучил бы деньги.
        LessonAttendance.objects.filter(student_id=student_id, present=True, is_free=False)
        # доп.урок (lesson_type='extra') учитывается в потреблении: исходный
        # пропуск остаётся present=false, потребление идёт от факта доп.урока.
        # Один пропуск списывается ровно один раз (новая модель компенсации).
        .annotate(units=_attended_units_case())
        .order_by('lesson__lesson_date', 'lesson_id')
        .values('units', 'lesson_id', lesson_date=F('lesson__lesson_date'))
    )
    cons = [
        {
            'units': to_decimal(r['units']),
            # Месяц денег = lesson_date записи (extra/burned — своя дата проведения).
            'date': _date_str(r['lesson_date']),
            'direction_id': None,
            'lesson_id': r['lesson_id'],
        }
        for r in cons_rows
    ]
    cons.extend(refund_cons)
    cons.sort(key=lambda c: (c['date'], 1 if c.get('refund') else 0))
    return lots, cons


def student_lesson_recognition(student_id: int) -> dict[int, dict]:
    """
    { lesson_id: {'recognized': Decimal (копейки), 'is_debt': bool} } — сколько
    денег списал каждый урок ученика. Источник колонки «Признано» во вкладке
    «Уроки» карточки ученика (спека 2026-09-14).

    Считается по ВСЕЙ истории ученика: чтобы знать, какие абонементы к моменту
    урока уже погашены, частичной выборки не хватает.

    is_debt=True — урок (целиком или частично) прошёл сверх оплаченного остатка.
    Оценку долга деньгами не даём: колонка показывает признанную выручку, и её
    сумма обязана сходиться с отчётами. Бесплатное занятие в потребление не
    входит вовсе, поэтому в карте его нет — потребитель показывает 0 ₽.
    """
    from apps.finances.fifo import compute_fifo

    lots, cons = _student_fifo_args(student_id)
    fifo = compute_fifo(lots, cons, '0001-01-01', '9999-12-31')
    debt = fifo['over_consumed_by_lesson']

    out: dict[int, dict] = {}
    for lesson_id, value in fifo['worked_off_by_lesson'].items():
        out[lesson_id] = {
            'recognized': round_kopecks(value),
            'is_debt': lesson_id in debt,
        }
    for lesson_id in debt:
        out.setdefault(lesson_id, {'recognized': Decimal('0.00'), 'is_debt': True})
    return out
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd journal_django && pytest apps/finances/tests/test_lesson_recognition.py apps/finances/tests/test_refund_remaining.py -q`
Expected: PASS — новые тесты зелёные, старые тесты остатка не сломаны (`student_fifo_remaining` работает через тот же хелпер).

- [ ] **Step 6: Полный прогон**

Run: `cd journal_django && pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/finances/repository.py journal_django/apps/finances/tests/test_lesson_recognition.py
git commit -m "feat(finances): student_lesson_recognition — признанные деньги по урокам ученика

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Строки вкладки — запрос и выводимый тип

**Files:**
- Create: `journal_django/apps/students/lesson_history.py`
- Test: `journal_django/apps/students/tests/test_lesson_history.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `journal_django/apps/students/tests/test_lesson_history.py`:

```python
"""
Тесты строк вкладки «Уроки» карточки ученика (спека 2026-09-14).

Проверяют состав строк (пропуски не попадают), порядок (по убыванию даты
сохранения урока), выводимый тип и склейку с деньгами.
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.students import lesson_history

pytestmark = pytest.mark.django_db


@pytest.fixture
def graph():
    """Направление → группа → преподаватель → ученик; чистится в teardown."""
    created = {}
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO directions (name, total_lessons, active) "
            "VALUES ('__lh_dir__', 16, true) RETURNING id")
        created['direction_id'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name) VALUES ('__lh_teacher__') RETURNING id")
        created['teacher_id'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active, lesson_number_offset) "
            "VALUES ('__lh_group__', %s, %s, false, 60, true, 0) RETURNING id",
            [created['direction_id'], created['teacher_id']])
        created['group_id'] = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name) VALUES ('__lh_student__') RETURNING id")
        created['student_id'] = cur.fetchone()[0]
    created['lessons'] = []
    created['payments'] = []
    yield created
    with connection.cursor() as cur:
        for lid in created['lessons']:
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lid])
            cur.execute('DELETE FROM lessons WHERE id = %s', [lid])
        for pid in created['payments']:
            cur.execute('DELETE FROM payments WHERE id = %s', [pid])
        cur.execute('DELETE FROM students WHERE id = %s', [created['student_id']])
        cur.execute('DELETE FROM groups WHERE id = %s', [created['group_id']])
        cur.execute('DELETE FROM teachers WHERE id = %s', [created['teacher_id']])
        cur.execute('DELETE FROM directions WHERE id = %s', [created['direction_id']])


def _add_lesson(graph, *, date='2026-02-10', number=1, duration=60,
                lesson_type='regular', present=True, is_free=False,
                unpaid_skip=False, submitted_at='2026-02-10 18:00:00+03'):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token, submitted_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, 't', %s) RETURNING id",
            [graph['group_id'], graph['teacher_id'], date, number, duration,
             lesson_type, submitted_at])
        lid = cur.fetchone()[0]
        graph['lessons'].append(lid)
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present, is_free, '
            'unpaid_skip) VALUES (%s, %s, %s, %s, %s)',
            [lid, graph['student_id'], present, is_free, unpaid_skip])
    return lid


def _add_payment(graph, lessons, total):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, "
            "lessons_count, kind, unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s,%s,1,%s,'purchase',0,%s,'2026-01-01','t') RETURNING id",
            [graph['student_id'], graph['direction_id'], lessons, total])
        graph['payments'].append(cur.fetchone()[0])


def _rows(graph):
    qs = lesson_history.lesson_rows_queryset(graph['student_id'])
    return lesson_history.serialize_rows(list(qs), graph['student_id'])


def test_absent_rows_are_excluded(graph):
    """Пропуски (present=false) во вкладку не попадают — ни обычные, ни неоплачиваемые."""
    kept = _add_lesson(graph, number=1)
    _add_lesson(graph, number=2, present=False)
    _add_lesson(graph, number=3, present=False, unpaid_skip=True)

    assert [r['lesson_id'] for r in _rows(graph)] == [kept]


def test_rows_ordered_by_submitted_at_desc(graph):
    """Порядок — по убыванию даты СОХРАНЕНИЯ, а не даты занятия."""
    early_submit = _add_lesson(graph, number=1, date='2026-02-20',
                               submitted_at='2026-02-20 18:00:00+03')
    late_submit = _add_lesson(graph, number=2, date='2026-02-10',
                              submitted_at='2026-03-01 12:00:00+03')

    assert [r['lesson_id'] for r in _rows(graph)] == [late_submit, early_submit]


def test_kind_is_derived_for_all_four_cases(graph):
    regular = _add_lesson(graph, number=1)
    free = _add_lesson(graph, number=2, is_free=True)
    extra = _add_lesson(graph, number=3, lesson_type='extra')
    burned = _add_lesson(graph, number=4, lesson_type='burned')

    kinds = {r['lesson_id']: r['kind'] for r in _rows(graph)}
    assert kinds == {regular: 'regular', free: 'free', extra: 'extra', burned: 'burned'}


def test_lesson_type_wins_over_free_flag(graph):
    """Сгорание и доп.урок бесплатными не бывают — флаг is_free на них не смотрим."""
    burned = _add_lesson(graph, number=1, lesson_type='burned', is_free=True)

    assert {r['lesson_id']: r['kind'] for r in _rows(graph)} == {burned: 'burned'}


def test_row_carries_group_teacher_direction_and_duration(graph):
    lid = _add_lesson(graph, number=1, duration=45)

    row = _rows(graph)[0]
    assert row['lesson_id'] == lid
    assert row['duration_minutes'] == 45
    assert row['group_id'] == graph['group_id']
    assert row['group_name'] == '__lh_group__'
    assert row['teacher_id'] == graph['teacher_id']
    assert row['teacher_name'] == '__lh_teacher__'
    assert row['direction_id'] == graph['direction_id']
    assert row['direction_name'] == '__lh_dir__'
    assert row['lesson_date'] == '2026-02-10'


def test_recognized_amount_and_debt_flag(graph):
    """Оплачен 1 урок, проведено 2: первый признан, второй — в долг."""
    _add_payment(graph, 1, 1000)
    first = _add_lesson(graph, number=1, date='2026-02-10',
                        submitted_at='2026-02-10 18:00:00+03')
    second = _add_lesson(graph, number=2, date='2026-02-11',
                         submitted_at='2026-02-11 18:00:00+03')

    by_id = {r['lesson_id']: r for r in _rows(graph)}
    assert by_id[first]['recognized_amount'] == '1000.00'
    assert by_id[first]['is_debt'] is False
    assert by_id[second]['recognized_amount'] == '0.00'
    assert by_id[second]['is_debt'] is True


def test_free_lesson_recognizes_zero(graph):
    _add_payment(graph, 4, 4000)
    lid = _add_lesson(graph, number=1, is_free=True)

    row = _rows(graph)[0]
    assert row['lesson_id'] == lid
    assert row['recognized_amount'] == '0.00'
    assert row['is_debt'] is False
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd journal_django && pytest apps/students/tests/test_lesson_history.py -q`
Expected: FAIL — `ImportError: cannot import name 'lesson_history'`.

- [ ] **Step 3: Создать модуль**

Создать `journal_django/apps/students/lesson_history.py`:

```python
"""
Строки вкладки «Уроки» в карточке ученика (спека 2026-09-14).

Строка = запись посещаемости, где ученик реально был (present=true). Это ровно
четыре типа: обычный, бесплатный, доп.урок, сгоревший. Пропуски (present=false —
и ждущие решения, и неоплачиваемые) во вкладку не идут: их место в очереди
резолюций и во вкладке «Обучение».

Деньги строки — точный FIFO по уроку
(apps/finances/repository.py::student_lesson_recognition).
"""
from __future__ import annotations

from decimal import Decimal

from apps.finances.repository import student_lesson_recognition
from apps.lessons.models import LessonAttendance

_ZERO = Decimal('0.00')

# Типы строки, выводимые из lesson_type + is_free. НЕ путать с сырым
# lessons.lesson_type: 'substitution'/'reschedule' — тоже обычные занятия, а
# «бесплатный» и вовсе не тип урока, а исход посещаемости.
KIND_BURNED = 'burned'
KIND_EXTRA = 'extra'
KIND_FREE = 'free'
KIND_REGULAR = 'regular'


def lesson_rows_queryset(student_id: int):
    """
    Записи вкладки в порядке убывания даты СОХРАНЕНИЯ урока (submitted_at).
    Даты занятия и сохранения расходятся — урок могут заполнить спустя дни.

    select_related на группу, направление и преподавателя: строка показывает их
    все, без него был бы N+1 на каждую строку страницы.
    """
    return (
        LessonAttendance.objects
        .filter(student_id=student_id, present=True)
        .select_related('lesson', 'lesson__group', 'lesson__group__direction',
                        'lesson__teacher')
        .order_by('-lesson__submitted_at', '-lesson_id')
    )


def row_kind(attendance: LessonAttendance) -> str:
    """
    Выводимый тип строки.

    lesson_type проверяется РАНЬШЕ is_free: сгорание и доп.урок бесплатными не
    бывают, и флаг is_free на них ничего не значит.
    """
    lesson_type = attendance.lesson.lesson_type
    if lesson_type == 'burned':
        return KIND_BURNED
    if lesson_type == 'extra':
        return KIND_EXTRA
    if attendance.is_free:
        return KIND_FREE
    return KIND_REGULAR


def serialize_rows(attendance_rows, student_id: int) -> list[dict]:
    """
    Строки вкладки для отданной страницы посещаемости.

    Карта денег строится по ВСЕЙ истории ученика (иначе неизвестно, какие
    абонементы к моменту урока погашены), а склеивается только со строками
    страницы. У ученика это десятки записей — расчёт дешёвый.

    recognized_amount отдаётся строкой: деньги через float терять нельзя, а
    фронтовый fmtRub принимает и строку.
    """
    recognition = student_lesson_recognition(student_id)
    rows: list[dict] = []
    for att in attendance_rows:
        lesson = att.lesson
        group = lesson.group
        # direction_id проверяем отдельно: у легаси-групп он бывает NULL, и
        # обращение к .direction тогда уронило бы строку.
        direction = group.direction if (group and group.direction_id) else None
        money = recognition.get(att.lesson_id) or {'recognized': _ZERO, 'is_debt': False}
        rows.append({
            'lesson_id': att.lesson_id,
            'lesson_date': lesson.lesson_date.isoformat(),
            'submitted_at': lesson.submitted_at.isoformat(),
            'kind': row_kind(att),
            'duration_minutes': lesson.lesson_duration_minutes,
            'group_id': group.id if group else None,
            'group_name': group.name if group else None,
            'teacher_id': lesson.teacher_id,
            'teacher_name': lesson.teacher.name if lesson.teacher_id else None,
            'direction_id': direction.id if direction else None,
            'direction_name': direction.name if direction else None,
            'recognized_amount': str(money['recognized']),
            'is_debt': money['is_debt'],
        })
    return rows
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd journal_django && pytest apps/students/tests/test_lesson_history.py -q`
Expected: PASS, 8 тестов.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/students/lesson_history.py journal_django/apps/students/tests/test_lesson_history.py
git commit -m "feat(students): строки вкладки «Уроки» карточки ученика

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Эндпоинт `GET /api/admin/students/:id/lessons`

**Files:**
- Modify: `journal_django/apps/students/views.py`
- Modify: `journal_django/apps/students/urls.py`
- Test: `journal_django/apps/students/tests/test_student_lessons_api.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `journal_django/apps/students/tests/test_student_lessons_api.py`:

```python
"""
E2E для GET /api/admin/students/:id/lessons — вкладка «Уроки» карточки ученика.

RBAC: читают все роли админки (manager/admin/superadmin), преподаватель — нет.
"""
from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db


@pytest.fixture
def graph():
    created = {}
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO directions (name, total_lessons, active) "
            "VALUES ('__sl_dir__', 16, true) RETURNING id")
        created['direction_id'] = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name) VALUES ('__sl_teacher__') RETURNING id")
        created['teacher_id'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active, lesson_number_offset) "
            "VALUES ('__sl_group__', %s, %s, false, 60, true, 0) RETURNING id",
            [created['direction_id'], created['teacher_id']])
        created['group_id'] = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name) VALUES ('__sl_student__') RETURNING id")
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


def _add_lesson(graph, *, number=1, date='2026-02-10', present=True,
                submitted_at='2026-02-10 18:00:00+03'):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token, submitted_at) "
            "VALUES (%s, %s, %s, %s, 60, 'regular', 't', %s) RETURNING id",
            [graph['group_id'], graph['teacher_id'], date, number, submitted_at])
        lid = cur.fetchone()[0]
        graph['lessons'].append(lid)
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present) '
            'VALUES (%s, %s, %s)', [lid, graph['student_id'], present])
    return lid


def _url(graph) -> str:
    return f"/api/admin/students/{graph['student_id']}/lessons"


def test_no_cookie_returns_401(anon_client, graph):
    assert anon_client.get(_url(graph)).status_code == 401


def test_teacher_cookie_returns_403(teacher_client, graph):
    assert teacher_client.get(_url(graph)).status_code == 403


def test_manager_cookie_returns_200(manager_client, graph):
    assert manager_client.get(_url(graph)).status_code == 200


def test_admin_cookie_returns_200(admin_client, graph):
    assert admin_client.get(_url(graph)).status_code == 200


def test_unknown_student_returns_404(admin_client):
    resp = admin_client.get('/api/admin/students/999999999/lessons')
    assert resp.status_code == 404


def test_response_shape_and_row_fields(admin_client, graph):
    lid = _add_lesson(graph)

    data = admin_client.get(_url(graph)).json()
    assert set(data) >= {'rows', 'total', 'page', 'page_size'}
    assert data['total'] == 1
    row = data['rows'][0]
    assert row['lesson_id'] == lid
    assert row['kind'] == 'regular'
    assert row['duration_minutes'] == 60
    assert row['group_name'] == '__sl_group__'
    assert row['teacher_name'] == '__sl_teacher__'
    assert row['direction_name'] == '__sl_dir__'
    assert row['recognized_amount'] == '0.00'
    assert row['is_debt'] is True


def test_absences_are_not_listed(admin_client, graph):
    kept = _add_lesson(graph, number=1)
    _add_lesson(graph, number=2, present=False)

    data = admin_client.get(_url(graph)).json()
    assert [r['lesson_id'] for r in data['rows']] == [kept]


def test_pagination_slices_rows(admin_client, graph):
    _add_lesson(graph, number=1, submitted_at='2026-02-10 18:00:00+03')
    newest = _add_lesson(graph, number=2, submitted_at='2026-02-11 18:00:00+03')

    data = admin_client.get(_url(graph) + '?page=1&page_size=1').json()
    assert data['total'] == 2
    assert data['page_size'] == 1
    assert [r['lesson_id'] for r in data['rows']] == [newest]
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd journal_django && pytest apps/students/tests/test_student_lessons_api.py -q`
Expected: FAIL — 404 на всех запросах (маршрута нет).

- [ ] **Step 3: Добавить вьюху**

В `journal_django/apps/students/views.py` добавить импорт модуля рядом с `from apps.students import services`:

```python
from apps.students import lesson_history, services
```

(заменив существующую строку `from apps.students import services`)

И добавить класс сразу после `StudentBalanceView`:

```python
class StudentLessonsView(APIView):
    """
    GET /api/admin/students/:id/lessons — уроки ученика (вкладка «Уроки»).

    Строки — записи посещаемости с present=true: обычный / бесплатный /
    доп.урок / сгоревший. Пропуски не показываются (спека 2026-09-14).
    Порядок — по убыванию даты сохранения урока.

    «Признано» считается точным FIFO по ВСЕЙ истории ученика независимо от
    запрошенной страницы: иначе неизвестно, какие абонементы к моменту урока
    уже погашены.

    404 если ученик не найден — единообразно со StudentStatsView.
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        if not services.student_exists(pk):
            raise NotFound({'error': 'Not found'})

        paginator = StandardPagination()
        page = paginator.paginate_queryset(
            lesson_history.lesson_rows_queryset(pk), request, view=self,
        )
        return paginator.get_paginated_response(lesson_history.serialize_rows(page, pk))
```

Дописать строку в docstring модуля `views.py` (список маршрутов), после строки про `/balance`:

```
  GET    /api/admin/students/:id/lessons → уроки ученика → 200 | 404
```

- [ ] **Step 4: Добавить маршрут**

В `journal_django/apps/students/urls.py` добавить `StudentLessonsView` в импорт (по алфавиту — между `StudentDetailView` и `StudentListCreateView`):

```python
from apps.students.views import (
    StudentBalanceView,
    StudentCommentDetailView,
    StudentCommentListView,
    StudentDetailView,
    StudentLessonsView,
    StudentListCreateView,
    StudentManagerView,
    StudentRefundView,
    StudentStatsView,
)
```

И маршрут после строки с `/balance`:

```python
    path('/<int:pk>/lessons', StudentLessonsView.as_view(), name='students-lessons'),
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd journal_django && pytest apps/students/tests/test_student_lessons_api.py -q`
Expected: PASS, 9 тестов.

- [ ] **Step 6: Полный прогон**

Run: `cd journal_django && pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/students/views.py journal_django/apps/students/urls.py journal_django/apps/students/tests/test_student_lessons_api.py
git commit -m "feat(students): эндпоинт GET /api/admin/students/:id/lessons

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Фронт — типы, подписи, хук

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/shared-types.ts`
- Modify: `journal_django/frontend/admin-src/src/lib/labels.ts`
- Create: `journal_django/frontend/admin-src/src/hooks/useStudentLessons.ts`

- [ ] **Step 1: Добавить типы строки**

В конец `journal_django/frontend/admin-src/src/lib/shared-types.ts` добавить (импорт в других файлах идёт через barrel `lib/types`, его править не нужно):

```ts
// ===== Вкладка «Уроки» карточки ученика (спека 2026-09-14) =====

/** Выводимый тип строки. Считает бэкенд из lesson_type + is_free
 *  (apps/students/lesson_history.py) — это НЕ сырой lessons.lesson_type. */
export type StudentLessonKind = 'regular' | 'free' | 'extra' | 'burned';

export interface StudentLessonRow {
  lesson_id: number;
  lesson_date: string;
  submitted_at: string;
  kind: StudentLessonKind;
  duration_minutes: number;
  group_id: number | null;
  group_name: string | null;
  teacher_id: number | null;
  teacher_name: string | null;
  direction_id: number | null;
  direction_name: string | null;
  /** Признанные деньги строкой — точный Decimal с бэка, fmtRub принимает строку. */
  recognized_amount: string;
  /** Урок (целиком или частично) прошёл сверх оплаченного остатка. */
  is_debt: boolean;
}
```

- [ ] **Step 2: Добавить подписи типов**

В `journal_django/frontend/admin-src/src/lib/labels.ts` заменить первую строку импорта:

```ts
import type { LessonType, RegistryStatus, Role, StudentLessonKind } from './types';
```

И добавить после блока `LESSON_TYPE_OPTIONS` (перед комментарием `// ===== Changelog:`):

```ts
// ===== Тип строки во вкладке «Уроки» карточки ученика =====
// Отдельный набор, а не LESSON_TYPE_LABELS: тот описывает сырой lessons.lesson_type
// и не знает ни «сгоревшего», ни «бесплатного» (последний — вовсе не тип урока,
// а исход посещаемости). Коды выводит бэкенд (apps/students/lesson_history.py).

export const STUDENT_LESSON_KIND_LABELS: Record<StudentLessonKind, string> = {
  regular: 'Обычный',
  free:    'Бесплатный',
  extra:   'Доп.урок',
  burned:  'Сгоревший',
};
```

- [ ] **Step 3: Создать хук**

Создать `journal_django/frontend/admin-src/src/hooks/useStudentLessons.ts`:

```ts
import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Paginated, StudentLessonRow } from '../lib/types';

/**
 * GET /api/admin/students/:id/lessons — серверно-пагинированный список уроков
 * ученика для вкладки «Уроки». Порядок задаёт бэкенд (по убыванию даты
 * сохранения урока), параметров сортировки у эндпоинта нет.
 */
export function useStudentLessons(studentId: number, page: number, pageSize: number) {
  return useQuery({
    queryKey: ['students', 'lessons', studentId, page, pageSize],
    queryFn: () =>
      api<Paginated<StudentLessonRow>>(
        'GET',
        `/api/admin/students/${studentId}/lessons?page=${page}&page_size=${pageSize}`,
      ),
    placeholderData: keepPreviousData,
  });
}
```

- [ ] **Step 4: Проверить типы**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: без ошибок. `Paginated` приходит из `lib/types` через barrel — так же импортирует `hooks/useUnfilledLessons.ts`.

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/lib/shared-types.ts journal_django/frontend/admin-src/src/lib/labels.ts journal_django/frontend/admin-src/src/hooks/useStudentLessons.ts
git commit -m "feat(admin-ui): типы, подписи и хук вкладки «Уроки» ученика

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Фронт — таблица вкладки и её подключение

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/students/StudentLessonsBlock.tsx`
- Modify: `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx`

- [ ] **Step 1: Создать компонент вкладки**

Создать `journal_django/frontend/admin-src/src/pages/students/StudentLessonsBlock.tsx`:

```tsx
import { useState } from 'react';
import { DataTable, type Column } from '../../components/table/DataTable';
import { EntityLink } from '../../components/EntityLink';
import { useStudentLessons } from '../../hooks/useStudentLessons';
import { fmtDate, fmtDateTime, fmtRub } from '../../lib/format';
import { STUDENT_LESSON_KIND_LABELS } from '../../lib/labels';
import type { StudentLessonRow } from '../../lib/types';

interface Props {
  studentId: number;
}

/**
 * Вкладка «Уроки» карточки ученика: все занятия, на которых он был, по убыванию
 * даты сохранения урока. Обе даты в таблице — занятия и сохранения: они часто
 * расходятся, и без первой порядок строк выглядел бы случайным.
 *
 * «Признано» — точный FIFO по уроку (сколько денег списала именно эта строка).
 * Ноль честный: у бесплатного занятия денег не берут вовсе, у урока сверх
 * оплаченного их ещё нет — такая строка помечена «в долг».
 */
export default function StudentLessonsBlock({ studentId }: Props) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const { data, isFetching } = useStudentLessons(studentId, page, pageSize);

  const columns: Column<StudentLessonRow>[] = [
    { key: 'lesson_id', label: 'ID', sortable: false, width: 70 },
    {
      key: 'lesson_date',
      label: 'Дата занятия',
      sortable: false,
      cell: (r) => fmtDate(r.lesson_date),
    },
    {
      key: 'submitted_at',
      label: 'Сохранён',
      sortable: false,
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
      cell: (r) => (
        <span className="slessons__money">
          {fmtRub(r.recognized_amount)}
          {r.is_debt && <span className="slessons__debt">в долг</span>}
        </span>
      ),
    },
  ];

  return (
    <DataTable<StudentLessonRow>
      data={data?.rows || []}
      columns={columns}
      title="Уроки ученика"
      isLoading={isFetching}
      serverPagination={{
        page,
        pageSize,
        total: data?.total || 0,
        // Сортировка и фильтры вкладке не нужны: порядок фиксирован бэкендом,
        // поэтому колонки не sortable, а обработчики — заглушки.
        sortBy: 'submitted_at',
        sortDir: 'desc',
        filters: {},
        onPageChange: setPage,
        onPageSizeChange: (size) => { setPageSize(size); setPage(1); },
        onSortChange: () => {},
        onFiltersChange: () => {},
      }}
    />
  );
}
```

- [ ] **Step 2: Добавить два класса в стили**

Дописать в конец `journal_django/frontend/admin-src/src/styles/pages/detail.css` (там же живут стили остальных блоков карточки):

```css
/* Вкладка «Уроки» карточки ученика: сумма и пометка долга в одной ячейке. */
.slessons__money {
  display: inline-flex;
  align-items: baseline;
  gap: var(--space-2);
}

.slessons__debt {
  color: var(--text3);
  font-size: var(--fs-xs);
}
```

Все три токена (`--space-2`, `--text3`, `--fs-xs`) уже объявлены в `styles/tokens.css` — новых значений заводить не нужно, hardcoded цветов и отступов не добавлять.

- [ ] **Step 3: Подключить вкладку**

В `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx`:

добавить импорт рядом с остальными блоками карточки:

```tsx
import StudentLessonsBlock from './StudentLessonsBlock';
```

заменить список вкладок:

```tsx
const STUDENT_TABS = ['learning', 'lessons', 'finance', 'tasks', 'comments', 'history'] as const;
```

и добавить элемент в массив `tabs` сразу после вкладки `learning`:

```tsx
    {
      value: 'lessons',
      label: 'Уроки',
      content: <StudentLessonsBlock studentId={student.id} />,
    },
```

- [ ] **Step 4: Проверить типы и сборку**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: без ошибок.

- [ ] **Step 5: Commit (без `admin-dist`)**

```bash
git add journal_django/frontend/admin-src/src
git commit -m "feat(admin-ui): вкладка «Уроки» в карточке ученика

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Сборка и ручная проверка

**Files:**
- Modify: `journal_django/frontend/admin-dist/**` (артефакты сборки)

- [ ] **Step 1: Полный прогон тестов**

Run: `cd journal_django && pytest -q`
Expected: PASS, падений нет.

- [ ] **Step 2: Собрать admin SPA**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: сборка без ошибок, обновлённые файлы в `journal_django/frontend/admin-dist/`.

- [ ] **Step 3: Проверить, что в сборке только ожидаемое**

Run: `git status --short journal_django/frontend/admin-dist`
Expected: изменены `index.html` и хешированные бандлы. Ничего постороннего в коммит не попадает.

- [ ] **Step 4: Ручная проверка в браузере**

Запустить локальный стенд (`runserver` + nginx на :8080) и открыть карточку ученика с историей уроков и оплат.

Проверить:
1. Вкладка «Уроки» видна и открывается; `?tab=lessons` в адресе.
2. Строки идут сверху вниз по убыванию колонки «Сохранён».
3. Пропусков в списке нет.
4. У 45-минутного урока в «Продолжительность» стоит `45 мин`, а сумма вдвое меньше, чем у 90-минутного того же абонемента.
5. Сумма колонки «Признано» у ученика без долгов сходится с «отработано» в его вкладке «Финансы».
6. У ученика с долгом последние строки помечены «в долг» и показывают `0 ₽`.
7. Переключение страниц не теряет фокус и не мигает пустой таблицей (`keepPreviousData`).
8. Ссылки на группу и преподавателя ведут в их карточки.

Если пункт не сходится — чинить до коммита.

- [ ] **Step 5: Commit сборки**

```bash
git add journal_django/frontend/admin-dist
git commit -m "build(admin): пересборка admin-dist

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Чего в этом плане нет

Сознательно за рамками (из спеки): пропуски во вкладке, фильтры и сортировка по колонкам, выгрузка в Excel, любые мутации. Вкладка только читает.
