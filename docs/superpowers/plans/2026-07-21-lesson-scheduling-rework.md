# Lesson Scheduling Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework группового плана занятий (`planned_lessons`) в единую непрерывную модель: отмена = перенос-в-конец + перенумерация; «Изменить расписание» / заморозка = чистая перегенерация хвоста от даты с превью-подтверждением; всё поверх общих примитивов `planner`.

**Architecture:** Чистые date-функции в `apps/scheduling/planner.py` (TDD в изоляции), запись в БД — `apps/scheduling/repository.py` (транзакции), оркестрация/превью — `apps/scheduling/services.py`, API — `views.py`/`serializers.py`. Фронт — `GroupPlanActions.tsx` (диалоги + модалка превью) и `StudentStatusModal.tsx`. Спека: `docs/superpowers/specs/2026-07-21-lesson-scheduling-rework-design.md`.

**Tech Stack:** Django 5 + DRF, PostgreSQL, pytest (`config.settings.test`, БД `journal_test`), React 19 + TanStack Query (admin SPA). Прогон бэка: `.venv\Scripts\python.exe -m pytest …`. Прогон фронта-типов: `frontend/admin-src` → `node_modules\.bin\tsc.cmd --noEmit`.

**Соглашения проекта (важно):** `day_of_week` Вс=0. 45мин → half-lesson `step=0.5` (2N занятий). Инвариант: `status='done'` НЕ трогаем. `UniqueConstraint(group, seq)` где `seq IS NOT NULL`. Коммитить только по ходу плана (ветка одна, `main`; НЕ пушить). Даты в тестах сравнивать через `str(...)` (DateField возвращает `datetime.date`).

---

## Файловая карта

| Файл | Ответственность | Действие |
|------|-----------------|----------|
| `apps/scheduling/planner.py` | чистые функции дат | Modify: `generate` (start_seq), новая `renumber_by_date` |
| `apps/scheduling/repository.py` | запись плана в БД | Modify: `wipe_one_offs`, `preview_affected`, переписать `cancel_lesson`, `permanent_change`, `freeze_individual_group`/`resume_individual_group` |
| `apps/scheduling/services.py` | оркестрация + превью | Modify: превью-функции, проброс `effective_from` в permanent-change |
| `apps/scheduling/serializers.py` | вход API | Modify: `effective_from`+`preview` для permanent-change |
| `apps/scheduling/views.py` | эндпоинты | Modify: превью-ветка permanent-change |
| `apps/students/services.py` + `views.py` | заморозка/превью | Modify: превью затрагиваемых разовых операций |
| `frontend/admin-src/src/pages/groups/GroupPlanActions.tsx` | UI операций плана | Modify: диалог «Изменить расписание» (дата) + модалка превью |
| `frontend/admin-src/src/pages/students/StudentStatusModal.tsx` | UI заморозки | Modify: модалка превью сбрасываемых операций |
| `docs/lesson-scheduling.md` | документация | Modify: новая семантика |

Порядок: чистые функции → репозиторий-примитивы → операции (отмена, изменить-расписание, заморозка) → API/превью → фронт → верификация «Задать расписание» → доки.

---

## Task 1: `planner.generate` — параметр стартовой позиции (чистая функция)

**Files:**
- Modify: `apps/scheduling/planner.py` (функция `generate`, ~строки 74-99)
- Test: `apps/scheduling/tests/test_planner.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `apps/scheduling/tests/test_planner.py`:

```python
import datetime
from decimal import Decimal
from apps.scheduling import planner
from apps.scheduling.occurrences import Slot, PENDING


def _slot(dow, hh=18, mm=0, eff='2026-01-01'):
    return Slot(day_of_week=dow, start_time=datetime.time(hh, mm),
                effective_from=datetime.date.fromisoformat(eff))


def test_generate_start_seq_offsets_numbering():
    # Хвост курса: 2 занятия по вторникам, нумерация с seq=5 (номер с 4.0).
    rows = planner.generate(
        start_date=datetime.date(2026, 7, 21),  # вторник
        slots=[_slot(2)],
        total_lessons=6,                          # 6 курсовых всего
        duration_minutes=60,
        default_teacher_id=9,
        start_seq=5,
        start_number=Decimal('4'),
    )
    assert [r.seq for r in rows] == [5, 6]
    assert [str(r.lesson_number) for r in rows] == ['5.0', '6.0']
    assert rows[0].scheduled_date == datetime.date(2026, 7, 21)
    assert rows[0].status == PENDING
    assert rows[0].teacher_id == 9


def test_generate_default_start_seq_is_one():
    rows = planner.generate(
        start_date=datetime.date(2026, 7, 21), slots=[_slot(2)],
        total_lessons=2, duration_minutes=60, default_teacher_id=1,
    )
    assert [r.seq for r in rows] == [1, 2]
    assert [str(r.lesson_number) for r in rows] == ['1.0', '2.0']
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_planner.py::test_generate_start_seq_offsets_numbering -v`
Expected: FAIL (`generate() got an unexpected keyword argument 'start_seq'`).

- [ ] **Step 3: Реализация**

В `apps/scheduling/planner.py` заменить сигнатуру/тело `generate`:

```python
def generate(
    *,
    start_date: datetime.date,
    slots: list[Slot],
    total_lessons: Optional[int],
    duration_minutes: int,
    default_teacher_id: Optional[int],
    start_seq: int = 1,
    start_number: Decimal = Decimal('0'),
) -> list[PlannedRow]:
    """Развернуть занятия курса от start_date по слотам. С start_seq=1 — полный
    план; с start_seq=k / start_number — регенерация хвоста (продолжение нумерации).
    Число занятий = (total_lessons - start_number) / step, привязка к слоту ≥ start_date.
    total_lessons обязателен и в единицах занятий; None/нет слотов → []."""
    if total_lessons is None or not slots:
        return []
    step = _step_for(duration_minutes)
    remaining = Decimal(total_lessons) - start_number
    if remaining <= 0:
        return []
    occ = _walk(start_date, slots, step, remaining, _far_future(start_date, int(remaining / step) + 2, step))
    return [
        PlannedRow(
            seq=start_seq - 1 + o.seq,
            lesson_number=start_number + o.lesson_number,
            scheduled_date=o.date,
            scheduled_time=o.time,
            teacher_id=default_teacher_id,
            status=PENDING,
        )
        for o in occ
    ]
```

Примечание: `_walk(..., total=remaining)` останавливается при `num > remaining`, поэтому выдаёт ровно `remaining/step` occurrences с локальными `seq` 1..M и `lesson_number` step..remaining. Сдвигаем на `start_seq-1` / `start_number`. `_far_future` уже принимает `total_lessons` как число — передаём `int(remaining/step)+2` недель (корректный горизонт).

- [ ] **Step 4: Прогнать — PASS**

Run: `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_planner.py -v -k generate`
Expected: PASS (новые + существующие generate-тесты).

- [ ] **Step 5: Коммит**

```bash
git add apps/scheduling/planner.py apps/scheduling/tests/test_planner.py
git commit -m "feat(scheduling): generate() accepts start_seq/start_number for tail regen"
```

---

## Task 2: `planner.renumber_by_date` — перенумерация по дате (чистая функция)

**Files:**
- Modify: `apps/scheduling/planner.py` (новая функция)
- Test: `apps/scheduling/tests/test_planner.py`

- [ ] **Step 1: Падающий тест**

```python
def test_renumber_by_date_contiguous_from_start():
    # Три pending-строки не по порядку дат → перенумеровать по дате с seq=3.
    from apps.scheduling.planner import PlannedRow
    rows = [
        PlannedRow(seq=5, lesson_number=Decimal('5'), scheduled_date=datetime.date(2026, 8, 4),
                   scheduled_time=datetime.time(18, 0)),
        PlannedRow(seq=3, lesson_number=Decimal('3'), scheduled_date=datetime.date(2026, 7, 21),
                   scheduled_time=datetime.time(18, 0)),
        PlannedRow(seq=4, lesson_number=Decimal('4'), scheduled_date=datetime.date(2026, 7, 28),
                   scheduled_time=datetime.time(18, 0)),
    ]
    out = planner.renumber_by_date(rows, start_seq=3, start_number=Decimal('2'), step=Decimal('1'))
    ordered = sorted(out, key=lambda r: r.scheduled_date)
    assert [r.seq for r in ordered] == [3, 4, 5]
    assert [str(r.lesson_number) for r in ordered] == ['3.0', '4.0', '5.0']
    # Дата 21.07 → seq 3 (наименьшая), 04.08 → seq 5 (наибольшая).
    assert ordered[0].scheduled_date == datetime.date(2026, 7, 21)
    assert ordered[-1].scheduled_date == datetime.date(2026, 8, 4)


def test_renumber_by_date_half_lesson_step():
    from apps.scheduling.planner import PlannedRow
    rows = [
        PlannedRow(seq=2, lesson_number=Decimal('1.0'), scheduled_date=datetime.date(2026, 7, 28),
                   scheduled_time=datetime.time(18, 0)),
        PlannedRow(seq=1, lesson_number=Decimal('0.5'), scheduled_date=datetime.date(2026, 7, 21),
                   scheduled_time=datetime.time(18, 0)),
    ]
    out = planner.renumber_by_date(rows, start_seq=1, start_number=Decimal('0'), step=Decimal('0.5'))
    ordered = sorted(out, key=lambda r: r.scheduled_date)
    assert [str(r.lesson_number) for r in ordered] == ['0.5', '1.0']
```

- [ ] **Step 2: Прогнать — FAIL**

Run: `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_planner.py -v -k renumber`
Expected: FAIL (`module 'planner' has no attribute 'renumber_by_date'`).

- [ ] **Step 3: Реализация**

Добавить в `apps/scheduling/planner.py`:

```python
def renumber_by_date(
    rows: list[PlannedRow],
    *,
    start_seq: int,
    start_number: Decimal,
    step: Decimal,
) -> list[PlannedRow]:
    """Присвоить курсовым строкам непрерывные seq/lesson_number по возрастанию
    (scheduled_date, scheduled_time), начиная с start_seq/start_number+step.
    seq/номер — по порядку дат; сами даты не трогаются. Вход не мутируется."""
    ordered = sorted(rows, key=lambda r: (r.scheduled_date, r.scheduled_time))
    out: list[PlannedRow] = []
    seq = start_seq
    num = start_number
    for r in ordered:
        num += step
        out.append(replace(r, seq=seq, lesson_number=num))
        seq += 1
    return out
```

- [ ] **Step 4: Прогнать — PASS**

Run: `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_planner.py -v -k renumber`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add apps/scheduling/planner.py apps/scheduling/tests/test_planner.py
git commit -m "feat(scheduling): renumber_by_date pure function"
```

---

## Task 3: `repository.wipe_one_offs` — сброс разовых операций в диапазоне

**Files:**
- Modify: `apps/scheduling/repository.py` (новая функция; рядом с `_relay_tail`, ~строка 899)
- Test: `apps/scheduling/tests/test_scheduling_repository.py` (создать, если нет — см. паттерн `apps/scheduling/tests/test_teacher_reassignment.py` для сетапа группы/плана)

- [ ] **Step 1: Падающий тест**

Использовать существующий сетап из `apps/scheduling/tests/test_plan_autogenerate.py` (фикстура `sched_setup`/`wiring` создаёт группу+слот+направление) как образец. Написать в новый `apps/scheduling/tests/test_wipe_one_offs.py`:

```python
import datetime
import pytest
from django.db import connection
from apps.scheduling.models import PlannedLesson

pytestmark = pytest.mark.django_db


@pytest.fixture
def group_with_group(db):
    # Минимальная группа (direction total_lessons=4, слот вторник) + 4 pending строки.
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name,is_individual,total_lessons,active) "
                    "VALUES ('__wipe_dir__',false,4,true) RETURNING id")
        did = cur.fetchone()[0]
        cur.execute("INSERT INTO teachers (name) VALUES ('__wipe_t__') RETURNING id")
        tid = cur.fetchone()[0]
        cur.execute("INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                    "lesson_duration_minutes,lessons_per_week,active) "
                    "VALUES ('__wipe_g__',%s,%s,false,60,1,true) RETURNING id", [did, tid])
        gid = cur.fetchone()[0]
    for i, d in enumerate(['2026-07-07', '2026-07-14', '2026-07-21', '2026-07-28'], start=1):
        PlannedLesson.objects.create(
            group_id=gid, seq=i, lesson_number=i, scheduled_date=d,
            scheduled_time=datetime.time(18, 0), teacher_id=tid, status='pending')
    yield gid, tid
    with connection.cursor() as cur:
        cur.execute("DELETE FROM planned_lessons WHERE group_id=%s", [gid])
        cur.execute("DELETE FROM groups WHERE id=%s", [gid])
        cur.execute("DELETE FROM teachers WHERE id=%s", [tid])
        cur.execute("DELETE FROM directions WHERE id=%s", [did])


def test_wipe_one_offs_clears_reschedule_sub_and_marker(group_with_group):
    from apps.scheduling import repository
    gid, tid = group_with_group
    # разовый перенос (moved_from_date) на seq=3
    PlannedLesson.objects.filter(group_id=gid, seq=3).update(
        moved_from_date='2026-07-20', substitute_teacher_id=tid)
    # маркер отмены в диапазоне
    PlannedLesson.objects.create(group_id=gid, seq=None, lesson_number=None,
        scheduled_date='2026-07-22', scheduled_time=datetime.time(18, 0),
        teacher_id=tid, status='cancelled')

    repository.wipe_one_offs(gid, date_from=datetime.date(2026, 7, 21))

    r3 = PlannedLesson.objects.get(group_id=gid, seq=3)
    assert r3.moved_from_date is None
    assert r3.substitute_teacher_id is None
    assert not PlannedLesson.objects.filter(group_id=gid, status='cancelled').exists()
    # голова (seq=1, дата 07.07) не тронута
    assert PlannedLesson.objects.filter(group_id=gid, seq=1).exists()
```

- [ ] **Step 2: FAIL**

Run: `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_wipe_one_offs.py -v`
Expected: FAIL (`repository has no attribute 'wipe_one_offs'`).

- [ ] **Step 3: Реализация**

Добавить в `apps/scheduling/repository.py` (рядом с `_relay_tail`):

```python
def wipe_one_offs(
    group_id: int,
    *,
    date_from: datetime.date,
    date_to: datetime.date | None = None,
    from_seq: int | None = None,
) -> None:
    """Сбросить разовые операции в диапазоне (для чистой перегенерации хвоста):
      - удалить маркеры отмен (seq IS NULL, status='cancelled');
      - обнулить moved_from_date (разовые переносы);
      - снять substitute_teacher (разовые замены).
    Диапазон — по дате [date_from, date_to] и/или по позиции seq>=from_seq у
    курсовых строк. done не трогаем. Вызывать внутри открытой транзакции."""
    now = msk_now()
    markers = PlannedLesson.objects.filter(
        group_id=group_id, seq__isnull=True, status=CANCELLED,
        scheduled_date__gte=date_from)
    if date_to is not None:
        markers = markers.filter(scheduled_date__lte=date_to)
    markers.delete()

    course = PlannedLesson.objects.filter(
        group_id=group_id, seq__isnull=False, status__in=_MUTABLE_STATUSES)
    if from_seq is not None:
        course = course.filter(seq__gte=from_seq)
    else:
        course = course.filter(scheduled_date__gte=date_from)
        if date_to is not None:
            course = course.filter(scheduled_date__lte=date_to)
    course.update(moved_from_date=None, substitute_teacher=None, updated_at=now)
```

Проверить, что в начале файла есть импорты `CANCELLED`, `_MUTABLE_STATUSES`, `msk_now`, `datetime` (уже используются — см. `_relay_tail`).

- [ ] **Step 4: PASS**

Run: `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_wipe_one_offs.py -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add apps/scheduling/repository.py apps/scheduling/tests/test_wipe_one_offs.py
git commit -m "feat(scheduling): wipe_one_offs repository primitive"
```

---

## Task 4: `repository.preview_affected` — список сбрасываемых разовых операций

**Files:**
- Modify: `apps/scheduling/repository.py` (новая функция)
- Test: `apps/scheduling/tests/test_wipe_one_offs.py`

- [ ] **Step 1: Падающий тест**

```python
def test_preview_affected_lists_ops(group_with_group):
    from apps.scheduling import repository
    gid, tid = group_with_group
    PlannedLesson.objects.filter(group_id=gid, seq=3).update(
        moved_from_date='2026-07-20', substitute_teacher_id=tid)
    PlannedLesson.objects.create(group_id=gid, seq=None, lesson_number=None,
        scheduled_date='2026-07-22', scheduled_time=datetime.time(18, 0),
        teacher_id=tid, status='cancelled')

    out = repository.preview_affected(gid, date_from=datetime.date(2026, 7, 21))
    kinds = sorted(o['kind'] for o in out)
    assert kinds == ['cancellation', 'reschedule', 'substitution']
    resc = next(o for o in out if o['kind'] == 'reschedule')
    assert str(resc['date']) == '2026-07-21'
```

- [ ] **Step 2: FAIL**

Run: `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_wipe_one_offs.py::test_preview_affected_lists_ops -v`
Expected: FAIL.

- [ ] **Step 3: Реализация**

```python
def preview_affected(
    group_id: int,
    *,
    date_from: datetime.date,
    date_to: datetime.date | None = None,
    from_seq: int | None = None,
) -> list[dict]:
    """Read-only: разовые операции, попадающие под перегенерацию (для превью-модалки).
    kind ∈ {reschedule, substitution, cancellation}. Ничего не пишет."""
    out: list[dict] = []
    markers = PlannedLesson.objects.filter(
        group_id=group_id, seq__isnull=True, status=CANCELLED, scheduled_date__gte=date_from)
    if date_to is not None:
        markers = markers.filter(scheduled_date__lte=date_to)
    for m in markers.values('scheduled_date', 'scheduled_time'):
        out.append({'kind': 'cancellation', 'date': m['scheduled_date'],
                    'time': m['scheduled_time']})

    course = PlannedLesson.objects.filter(
        group_id=group_id, seq__isnull=False, status__in=_MUTABLE_STATUSES)
    if from_seq is not None:
        course = course.filter(seq__gte=from_seq)
    else:
        course = course.filter(scheduled_date__gte=date_from)
        if date_to is not None:
            course = course.filter(scheduled_date__lte=date_to)
    for r in course.values('seq', 'scheduled_date', 'moved_from_date', 'substitute_teacher_id'):
        if r['moved_from_date'] is not None:
            out.append({'kind': 'reschedule', 'seq': r['seq'], 'date': r['scheduled_date'],
                        'from_date': r['moved_from_date']})
        if r['substitute_teacher_id'] is not None:
            out.append({'kind': 'substitution', 'seq': r['seq'], 'date': r['scheduled_date']})
    return out
```

- [ ] **Step 4: PASS**

Run: `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_wipe_one_offs.py -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add apps/scheduling/repository.py apps/scheduling/tests/test_wipe_one_offs.py
git commit -m "feat(scheduling): preview_affected read-only helper"
```

---

## Task 5: Переписать `cancel_lesson` — перенос-в-конец + перенумерация

**Files:**
- Modify: `apps/scheduling/repository.py` (функция `cancel_lesson`, ~строки 969-1002; добавить приватный `_place_after_last`)
- Test: `apps/scheduling/tests/test_cancel_lesson.py` (создать; образец сетапа — Task 3)

- [ ] **Step 1: Падающий тест**

```python
import datetime
import pytest
from django.db import connection
from apps.scheduling.models import PlannedLesson

pytestmark = pytest.mark.django_db

# (переиспользовать фикстуру group_with_group из Task 3 — вынести в conftest
#  apps/scheduling/tests/conftest.py, чтобы делить между файлами)


def test_cancel_moves_to_end_and_renumbers(group_with_group):
    from apps.scheduling import repository
    gid, tid = group_with_group  # 4 pending вт: 07,14,21,28 июля; слот вторник
    row3 = PlannedLesson.objects.get(group_id=gid, seq=3)  # 21.07
    repository.cancel_lesson(
        gid, from_date=datetime.date(2026, 7, 21),
        marker_time=datetime.time(18, 0), marker_teacher_id=tid, lesson_id=row3.id)

    # Маркер на 21.07
    assert PlannedLesson.objects.filter(
        group_id=gid, status='cancelled', scheduled_date='2026-07-21', seq__isnull=True).exists()
    # 4 курсовых строки, непрерывный seq 1..4 по дате
    course = list(PlannedLesson.objects.filter(group_id=gid, seq__isnull=False)
                  .order_by('scheduled_date'))
    assert [c.seq for c in course] == [1, 2, 3, 4]
    # отменённый (был 21.07) уехал в конец: последняя дата = 04.08 (следующий вт после 28.07)
    assert str(course[-1].scheduled_date) == '2026-08-04'
    # даты 07,14,28 сохранились, перенумерованы 1,2,3
    assert [str(c.scheduled_date) for c in course] == ['2026-07-07', '2026-07-14', '2026-07-28', '2026-08-04']


def test_cancel_clears_substitution_on_moved_row(group_with_group):
    from apps.scheduling import repository
    gid, tid = group_with_group
    row3 = PlannedLesson.objects.get(group_id=gid, seq=3)
    PlannedLesson.objects.filter(id=row3.id).update(substitute_teacher_id=tid)
    repository.cancel_lesson(gid, from_date=datetime.date(2026, 7, 21),
        marker_time=datetime.time(18, 0), marker_teacher_id=tid, lesson_id=row3.id)
    moved = PlannedLesson.objects.get(id=row3.id)
    assert moved.substitute_teacher_id is None
    assert str(moved.scheduled_date) == '2026-08-04'
```

- [ ] **Step 2: FAIL**

Run: `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_cancel_lesson.py -v`
Expected: FAIL (сигнатура `cancel_lesson` без `lesson_id`; поведение старое).

- [ ] **Step 3: Реализация**

Заменить `cancel_lesson` в `apps/scheduling/repository.py`. Добавить хелпер поиска «следующего слота после последнего» через `_walk` (1 occurrence, обход занятых дат) и двухфазную перенумерацию:

```python
def _next_slot_after(
    group_id: int, *, after_date: datetime.date, occupied: frozenset[datetime.date],
    duration_minutes: int, open_slots: list,
) -> datetime.date | None:
    """Ближайшая слот-дата СТРОГО после after_date, не входящая в occupied.
    Разворачиваем один шаг _walk от after_date+1. None — нет открытого слота."""
    if not open_slots:
        return None
    start = after_date + datetime.timedelta(days=1)
    horizon = start + datetime.timedelta(weeks=len(occupied) + 4)
    occ = _walk(start, open_slots, _step_for(duration_minutes), None, horizon,
                skip_dates=occupied)
    return occ[0].date if occ else None


def cancel_lesson(
    group_id: int,
    from_date: datetime.date,
    *,
    marker_time: datetime.time,
    marker_teacher_id: int | None,
    lesson_id: int,
) -> list[dict]:
    """Отмена: (1) маркер 'cancelled' (seq=NULL) на from_date; (2) отменённый урок
    (lesson_id) уезжает на следующий свободный слот после последнего курсового
    занятия, замена снимается; (3) все pending/overdue курсовые перенумеровываются
    по дате. Баланс не трогаем. done не трогаем. Возвращает новый план."""
    now = msk_now()
    with transaction.atomic():
        g = Group.objects.filter(id=group_id).values('lesson_duration_minutes').first()
        if g is None:
            return get_plan(group_id)
        step = _step_for(g['lesson_duration_minutes'])
        open_slots = [s for s in slots_by_group([group_id]).get(group_id, [])
                      if s.effective_to is None]

        target = (PlannedLesson.objects.select_for_update()
                  .filter(id=lesson_id, group_id=group_id, seq__isnull=False,
                          status__in=_MUTABLE_STATUSES).first())
        if target is None:
            raise ValueError('Отменить можно только активную курсовую строку.')

        # (1) маркер на исходной дате
        PlannedLesson.objects.create(
            group_id=group_id, seq=None, lesson_number=None,
            scheduled_date=from_date, scheduled_time=marker_time,
            teacher_id=marker_teacher_id, status=CANCELLED, created_at=now, updated_at=now)

        # (2) перенос отменённого в конец (следующий слот после последнего курсового)
        course_qs = PlannedLesson.objects.select_for_update().filter(
            group_id=group_id, seq__isnull=False)
        last_date = max(p.scheduled_date for p in course_qs)
        occupied = frozenset(PlannedLesson.objects.filter(group_id=group_id)
                             .values_list('scheduled_date', flat=True))
        new_date = _next_slot_after(
            group_id, after_date=last_date, occupied=occupied,
            duration_minutes=g['lesson_duration_minutes'], open_slots=open_slots)
        if new_date is not None:
            target.scheduled_date = new_date
            target.scheduled_time = open_slots[0].start_time
            target.substitute_teacher_id = None
            target.moved_from_date = None
            target.updated_at = now
            target.save(update_fields=['scheduled_date', 'scheduled_time',
                                       'substitute_teacher', 'moved_from_date', 'updated_at'])

        # (3) перенумерация pending/overdue по дате, продолжая от последнего done
        last_done = (PlannedLesson.objects.filter(group_id=group_id, status=DONE, seq__isnull=False)
                     .order_by('-seq').values('seq', 'lesson_number').first())
        start_seq = (last_done['seq'] + 1) if last_done else 1
        start_number = (last_done['lesson_number'] if last_done else Decimal('0'))
        pending = list(PlannedLesson.objects.select_for_update().filter(
            group_id=group_id, seq__isnull=False, status__in=_MUTABLE_STATUSES)
            .order_by('scheduled_date', 'scheduled_time'))
        _renumber_persist(pending, start_seq=start_seq, start_number=start_number,
                          step=step, now=now)

    return get_plan(group_id)


def _renumber_persist(pending, *, start_seq, start_number, step, now) -> None:
    """Двухфазная запись seq/lesson_number (обход UniqueConstraint(group, seq)):
    сначала временные отрицательные seq, потом финальные по порядку дат."""
    if not pending:
        return
    # фаза 1: увести в отрицательный диапазон, чтобы не столкнуться с целевыми seq
    for i, p in enumerate(pending, start=1):
        p.seq = -i
    PlannedLesson.objects.bulk_update(pending, ['seq'])
    # фаза 2: финальные значения по возрастанию даты
    ordered = sorted(pending, key=lambda p: (p.scheduled_date, p.scheduled_time))
    seq = start_seq
    num = start_number
    for p in ordered:
        num += step
        p.seq = seq
        p.lesson_number = num
        p.updated_at = now
        seq += 1
    PlannedLesson.objects.bulk_update(ordered, ['seq', 'lesson_number', 'updated_at'])
```

Проверить импорты в начале файла: `Decimal` (из decimal), `DONE`, `_step_for`, `_walk`, `slots_by_group`, `Group`, `transaction`, `msk_now`, `CANCELLED`, `_MUTABLE_STATUSES` — все уже используются в модуле.

- [ ] **Step 4: Обновить вызывающий код `cancel`**

Во `apps/scheduling/services.py` функция `cancel(...)` вызывает `repository.cancel_lesson` — добавить проброс `lesson_id`. Найти (grep `cancel_lesson(`):

```python
# было: repository.cancel_lesson(group_id, from_date, marker_time=..., marker_teacher_id=...)
# стало: добавить lesson_id=lesson_id (id якорной строки уже известен в services.cancel)
```

Показать точную правку после чтения `services.py` (функция `cancel(group_id, lesson_id, request)` уже принимает `lesson_id`).

- [ ] **Step 5: PASS**

Run: `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_cancel_lesson.py -v`
Expected: PASS. Затем прогнать существующие тесты отмены: `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/ -v -k cancel` — старые тесты старой семантики (relay всего хвоста) **обновить** под новую модель (перенос-в-конец) или удалить устаревшие ассерты; НЕ оставлять сломанными.

- [ ] **Step 6: Коммит**

```bash
git add apps/scheduling/repository.py apps/scheduling/services.py apps/scheduling/tests/
git commit -m "feat(scheduling): cancel = move-to-end + renumber (new model)"
```

---

## Task 6: Переписать `permanent_change` — чистая перегенерация хвоста от даты

**Files:**
- Modify: `apps/scheduling/repository.py` (функция `permanent_change`, ~строки 750-895 — заменить оба пути на единый)
- Modify: `apps/scheduling/serializers.py` (добавить `effective_from`)
- Test: `apps/scheduling/tests/test_permanent_change.py` (создать; или дополнить существующий, если есть)

- [ ] **Step 1: Падающий тест**

```python
def test_permanent_change_regenerates_tail_from_new_date_clean(group_with_group):
    from apps.scheduling import repository
    gid, tid = group_with_group  # 4 pending вт: 07,14,21,28
    # разовый перенос + замена на seq=4, маркер отмены в хвосте
    PlannedLesson.objects.filter(group_id=gid, seq=4).update(
        moved_from_date='2026-07-27', substitute_teacher_id=tid)
    # меняем расписание с урока 3: новая дата 2026-08-03 (понедельник), слот понедельник
    repository.permanent_change(
        gid, from_seq=3, effective_from=datetime.date(2026, 8, 3),
        new_slots=[{'day_of_week': 1, 'start_time': '17:00'}])

    course = list(PlannedLesson.objects.filter(group_id=gid, seq__isnull=False)
                  .order_by('seq'))
    assert [c.seq for c in course] == [1, 2, 3, 4]
    # голова (seq 1,2) не тронута: 07.07, 14.07
    assert [str(c.scheduled_date) for c in course[:2]] == ['2026-07-07', '2026-07-14']
    # хвост (seq 3,4) регенерирован по понедельникам с 03.08
    assert [str(c.scheduled_date) for c in course[2:]] == ['2026-08-03', '2026-08-10']
    # чистый лист: разовые сброшены
    assert course[3].moved_from_date is None
    assert course[3].substitute_teacher_id is None
```

- [ ] **Step 2: FAIL**

Run: `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_permanent_change.py -v`
Expected: FAIL (сигнатура без `effective_from`).

- [ ] **Step 3: Реализация — единый путь**

Заменить тело `permanent_change` в `apps/scheduling/repository.py` (убрать одно/мультислотовое ветвление) на:

```python
def permanent_change(
    group_id: int,
    *,
    from_seq: int,
    effective_from: datetime.date,
    new_slots: list[dict],
    new_teacher_id: int | None = None,
) -> list[dict] | None:
    """«Изменить расписание» с урока from_seq: чистая перегенерация хвоста от
    effective_from по new_slots. Сбрасывает разовые операции хвоста (wipe_one_offs),
    версионирует слоты (apply_schedule_change), разворачивает остаток курса
    (planner.generate со start_seq). done/голова не тронуты. None → группы нет."""
    from apps.groups import repository as groups_repo
    if not Group.objects.filter(id=group_id).exists():
        return None
    now = msk_now()
    with transaction.atomic():
        head_done = (PlannedLesson.objects
                     .filter(group_id=group_id, seq__isnull=False, seq__lt=from_seq)
                     .order_by('-seq').values('seq', 'lesson_number').first())
        start_seq = from_seq
        start_number = head_done['lesson_number'] if head_done else Decimal('0')
        # (если head_done['seq'] != from_seq-1 из-за дыр — доверяем seq контенту:
        #  start_number = (from_seq-1)*step; вычисляем ниже через direction/step)

        g = Group.objects.filter(id=group_id).values(
            'lesson_duration_minutes', 'teacher_id',
            total_lessons=F('direction__total_lessons')).first()
        step = _step_for(g['lesson_duration_minutes'])
        start_number = (Decimal(from_seq) - 1) * step

        # чистый лист хвоста
        wipe_one_offs(group_id, date_from=effective_from, from_seq=from_seq)

        # версионируем набор слотов от новой даты
        target = [{'day_of_week': s['day_of_week'],
                   'start_time': _parse_hhmm(s['start_time']).strftime('%H:%M')}
                  for s in new_slots]
        groups_repo.apply_schedule_change(group_id, effective_from, target)

        # генерируем хвост (остаток курса) от новой даты по новым слотам
        open_slots = [s for s in slots_by_group([group_id]).get(group_id, [])
                      if s.effective_to is None]
        teacher_for_tail = new_teacher_id if new_teacher_id is not None else g['teacher_id']
        rows = planner.generate(
            start_date=effective_from, slots=open_slots,
            total_lessons=g['total_lessons'], duration_minutes=g['lesson_duration_minutes'],
            default_teacher_id=teacher_for_tail, start_seq=start_seq, start_number=start_number)

        tail = list(PlannedLesson.objects.select_for_update().filter(
            group_id=group_id, seq__isnull=False, seq__gte=from_seq,
            status__in=_MUTABLE_STATUSES).order_by('seq'))
        by_seq = {p.seq: p for p in tail}
        to_update = []
        for r in rows:
            p = by_seq.get(r.seq)
            if p is None:
                continue
            p.scheduled_date = r.scheduled_date
            p.scheduled_time = r.scheduled_time
            p.teacher_id = teacher_for_tail
            p.moved_from_date = None
            p.substitute_teacher_id = None
            p.updated_at = now
            to_update.append(p)
        PlannedLesson.objects.bulk_update(to_update, [
            'scheduled_date', 'scheduled_time', 'teacher', 'moved_from_date',
            'substitute_teacher', 'updated_at'])
        if new_teacher_id is not None:
            Group.objects.filter(id=group_id).update(teacher_id=new_teacher_id)
    return get_plan(group_id)
```

Примечание: `lessons_per_week` синхронизируется внутри `apply_schedule_change` (сервис) — эффект уже есть после недавней правки. Если `apply_schedule_change` вызывается на уровне repository (минуя сервис) — добавить `Group.objects.filter(id=group_id).update(lessons_per_week=len(target))`.

- [ ] **Step 4: Сериализатор — `effective_from`**

В `apps/scheduling/serializers.py` в permanent-change сериализаторе добавить обязательное поле даты:

```python
effective_from = DateStringField()   # дата, с которой действует новое расписание
```

(импорт `from apps.core.fields import DateStringField` — проверить.)

- [ ] **Step 5: PASS + обновить старые тесты**

Run: `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/ -v -k permanent`
Expected: PASS. Старые тесты `permanent_change` (сдвиг по дню недели/мультислот) переписать под новую единую семантику (перегенерация от даты).

- [ ] **Step 6: Коммит**

```bash
git add apps/scheduling/repository.py apps/scheduling/serializers.py apps/scheduling/tests/
git commit -m "feat(scheduling): permanent-change = clean tail regen from date"
```

---

## Task 7: Заморозка (индив) — wipe окна + перегенерация от разморозки

**Files:**
- Modify: `apps/scheduling/repository.py` (`freeze_individual_group` ~1223, `resume_individual_group` ~1309 — добавить `wipe_one_offs` окна перед relay)
- Test: `apps/scheduling/tests/test_freeze_scheduling.py` (дополнить)

- [ ] **Step 1: Падающий тест**

Дополнить существующий `apps/scheduling/tests/test_freeze_scheduling.py`: заморозка с разовым переносом/заменой в окне → после заморозки они сброшены, хвост перегенерирован от даты разморозки. (Сетап — по образцу существующих тестов файла.)

```python
def test_freeze_wipes_one_offs_in_window(indiv_group_with_plan):
    from apps.scheduling import repository
    gid, tid = indiv_group_with_plan
    # разовая замена на урок в окне заморозки
    PlannedLesson.objects.filter(group_id=gid, seq=2).update(substitute_teacher_id=tid)
    repository.freeze_individual_group(
        gid, frozen_from=datetime.date(2026, 7, 14), resume_date=datetime.date(2026, 7, 28))
    # замена снята (урок сдвинут за окно и разовое сброшено)
    assert not PlannedLesson.objects.filter(
        group_id=gid, seq__isnull=False, substitute_teacher_id__isnull=False).exists()
```

- [ ] **Step 2: FAIL** — Run соответствующий `-k freeze_wipes`; Expected FAIL.

- [ ] **Step 3: Реализация**

В `freeze_individual_group` перед перекладкой хвоста добавить:

```python
wipe_one_offs(group_id, date_from=frozen_from, date_to=resume_date)
```

(внутри уже открытой транзакции, до `_relay_tail`/relay от resume_date). Аналогично в `resume_individual_group`, если он сбрасывает окно. Существующий relay/generate от `resume_date` переиспользуется.

- [ ] **Step 4: PASS** — `.venv\Scripts\python.exe -m pytest apps/scheduling/tests/test_freeze_scheduling.py -v`. Обновить старые ассерты при необходимости.

- [ ] **Step 5: Коммит**

```bash
git add apps/scheduling/repository.py apps/scheduling/tests/test_freeze_scheduling.py
git commit -m "feat(scheduling): freeze wipes one-off ops in window before relay"
```

---

## Task 8: Превью-эндпоинты (Изменить расписание + Заморозка)

**Files:**
- Modify: `apps/scheduling/views.py` (permanent-change: ветка `preview`)
- Modify: `apps/scheduling/serializers.py` (флаг `preview`)
- Modify: `apps/students/views.py` (`StudentFreezePreviewView` — добавить `affected_ops` в ответ)
- Test: `apps/scheduling/tests/test_plan_api.py`, `apps/students/tests/test_freeze_preview_api.py`

- [ ] **Step 1: Падающий тест (API превью permanent-change)**

В `apps/scheduling/tests/test_plan_api.py` добавить тест: `POST …/plan/permanent-change` с `{"preview": true, "from_seq": 3, "effective_from": "...", "new_slots": [...]}` → 200 с полем `affected` (список), при этом план в БД НЕ изменился.

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Реализация**

В permanent-change view: если `serializer.validated_data.get('preview')` → вернуть `Response({'affected': services.preview_permanent_change(pk, from_seq, effective_from)})` без записи; иначе — боевой путь. В `services.py`:

```python
def preview_permanent_change(group_id, from_seq, effective_from):
    return repository.preview_affected(group_id, date_from=effective_from, from_seq=from_seq)
```

Для заморозки: в `apps/students/services.py` `preview_freeze_schedule` (уже есть) — добавить в результат по каждой индив-группе `affected: repository.preview_affected(gid, date_from=frozen_from, date_to=frozen_until)`.

- [ ] **Step 4: PASS** — прогнать оба тестовых файла.

- [ ] **Step 5: Коммит**

```bash
git add apps/scheduling/ apps/students/
git commit -m "feat(scheduling): preview endpoints for schedule-change and freeze"
```

---

## Task 9: Фронт — «Изменить расписание» (дата + превью-модалка)

**Files:**
- Modify: `frontend/admin-src/src/pages/groups/GroupPlanActions.tsx`
- Modify: `frontend/admin-src/src/hooks/useGroupPlan.ts` (`usePermanentChange` — тело + превью)

- [ ] **Step 1: Хук — поле `effective_from` + превью**

В `usePermanentChange` тело мутации: `{ from_seq, effective_from, new_slots }`. Добавить `usePermanentChangePreview` (POST c `preview: true`) → возвращает `{ affected: [...] }`.

- [ ] **Step 2: Диалог**

В диалоге «Изменить расписание» ([GroupPlanActions.tsx](../../journal_django/frontend/admin-src/src/pages/groups/GroupPlanActions.tsx)) добавить `DateInput` «Дата, с которой действует новое расписание» (`effective_from`, дефолт — дата выбранного урока `from_seq`). Кнопка «Применить» → сначала превью → модалка со списком `affected` (переносы/замены/отмены) → подтверждение → боевой вызов.

- [ ] **Step 3: Модалка превью**

Компонент со списком: «Будут сброшены: разовый перенос (Урок N, дата), замена (Урок N), отмена (дата)…». Кнопки «Отмена» / «Применить и сбросить».

- [ ] **Step 4: Проверка типов**

Run: `frontend/admin-src` → `node_modules\.bin\tsc.cmd --noEmit -p tsconfig.json`
Expected: EXIT 0. Прогнать вручную (`/run` или dev-сборка) — фронтовых юнит-тестов нет.

- [ ] **Step 5: Коммит**

```bash
git add frontend/admin-src/src/pages/groups/GroupPlanActions.tsx frontend/admin-src/src/hooks/useGroupPlan.ts
git commit -m "feat(admin): schedule-change dialog with date + reset preview"
```

---

## Task 10: Фронт — Заморозка (превью-модалка сбрасываемых операций)

**Files:**
- Modify: `frontend/admin-src/src/pages/students/StudentStatusModal.tsx`

- [ ] **Step 1: Показ `affected` из превью**

Существующий `previewQuery` (freeze preview) уже дергается; расширить рендер: если по индив-группам есть `affected` — показать блок «При заморозке будут сброшены разовые операции: …».

- [ ] **Step 2: Подтверждение**

Перед сохранением заморозки — если `affected` непустой, показать модалку-подтверждение (можно переиспользовать существующий паттерн `showCoincidenceConfirm`).

- [ ] **Step 3: tsc** — EXIT 0.

- [ ] **Step 4: Коммит**

```bash
git add frontend/admin-src/src/pages/students/StudentStatusModal.tsx
git commit -m "feat(admin): freeze shows/reset preview of one-off ops"
```

---

## Task 11: Верификация «Задать расписание» (уже реализовано)

**Files:**
- Test: `apps/scheduling/tests/test_plan_autogenerate.py` (дополнить)

- [ ] **Step 1: Тест ×2 на 45мин + старт по слоту**

```python
def test_45min_generates_double_and_snaps_to_slot(wiring):
    from apps.groups import services as groups_services
    s, created = wiring
    data = self._base(s, '__ag_45__'); data['lesson_duration_minutes'] = 45
    data['group_start_date'] = None; data['slots'] = []
    group = groups_services.create_group(data)
    gid = group['id']; created.append(gid)
    # старт 20.07 (Пн), слот Пятница(5) → первое занятие 24.07; ×2 от total_lessons
    groups_services.apply_schedule_change(gid, {
        'effective_from': '2026-07-20', 'slots': [{'day_of_week': 5, 'start_time': '17:00'}]})
    from apps.scheduling.models import PlannedLesson
    rows = list(PlannedLesson.objects.filter(group_id=gid, seq__isnull=False).order_by('seq'))
    assert len(rows) == 2 * s_total_lessons  # подставить total_lessons направления фикстуры
    assert str(rows[0].scheduled_date) == '2026-07-24'  # первый слот-день ≥ старта
```

(Подставить `total_lessons` направления из фикстуры `sched_setup`.)

- [ ] **Step 2: Прогнать — PASS** (если FAIL — чинить `generate`/`apply_schedule_change`, но по анализу должно проходить).

- [ ] **Step 3: Коммит**

```bash
git add apps/scheduling/tests/test_plan_autogenerate.py
git commit -m "test(scheduling): verify 45min x2 and slot-snap for set-schedule"
```

---

## Task 12: Обновить документацию

**Files:**
- Modify: `docs/lesson-scheduling.md`

- [ ] **Step 1: Правки**

Раздел «5. Отмена»: заменить описание relay-всего-хвоста на новую модель (маркер + перенос-в-конец на следующий слот + перенумерация `renumber_by_date` + снятие замены). Раздел «4. Перенос навсегда» → «Изменить расписание»: единый путь — чистая перегенерация хвоста от `effective_from` по слотам (`wipe_one_offs` + `generate(start_seq)`), превью-подтверждение. Добавить примитивы `renumber_by_date` / `wipe_one_offs` / `preview_affected` и параметр `start_seq` у `generate`. Заморозка: сброс окна + перегенерация от разморозки.

- [ ] **Step 2: Коммит**

```bash
git add docs/lesson-scheduling.md
git commit -m "docs: update lesson-scheduling for new cancel/schedule-change model"
```

---

## Финальная проверка

- [ ] Полный бэкенд-suite: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` — все зелёные (обновить/переписать старые тесты старой семантики отмены/permanent-change).
- [ ] `frontend/admin-src` → `tsc --noEmit` — EXIT 0.
- [ ] Ручной прогон в admin SPA: Задать/Изменить расписание, отмена (урок в конце + маркер + перенумерация), заморозка индив (превью сброса).

## Замечания для реализующей сессии

- Инвариант «`done` не трогаем» — проверять в каждом тесте, где есть проведённые.
- Перенумерация — только двухфазная (`_renumber_persist`), иначе `UniqueConstraint(group, seq)` упадёт.
- Старые тесты старой семантики (relay-всего-хвоста при отмене; двухпутёвый permanent_change) НЕ игнорировать — переписать под новую модель или удалить устаревшие ассерты, не оставлять красными.
- Коммитить по задачам; ветка `main`, НЕ пушить (только по явной просьбе владельца).
- В рабочем дереве есть незакоммиченный WIP предыдущих правок («Задать расписание», форма группы) — не откатывать; план на них опирается.
