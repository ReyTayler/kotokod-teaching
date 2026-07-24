# Продления: разблокировка «Ждём продление» + пересбор сделок — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Разблокировать ручной перевод сделок со стадии «Ждём продление» и добавить в раздел «Синхро» действие полного пересбора всех сделок продления из истории посещаемости.

**Architecture:** Два независимых изменения. (1) Точечная правка валидатора переходов `transitions.py`. (2) Доменный модуль `apps/renewals/rebuild.py` (чистая раскладка `plan_for_student` + оркестратор `rebuild_all`), подключённый действием `rebuild-renewals` в существующий каркас `apps/sync` (Celery-задача + `ACTIONS` + карточка `SYNC_ACTIONS` во фронте).

**Tech Stack:** Django 5 + DRF, pytest, Celery (в тестах eager), PostgreSQL, React 19 admin SPA (только правка `lib/sync.ts`).

**Спека:** [docs/superpowers/specs/2026-07-19-renewals-rebuild-and-awaiting-fix-design.md](../specs/2026-07-19-renewals-rebuild-and-awaiting-fix-design.md)

---

## ⚠️ Важные ограничения этого репозитория (читать до старта)

- **Git:** рабочее дерево полно постороннего WIP. **НЕ запускать `git add/commit/push`** во время исполнения (в т.ч. субагентам). Каждая задача завершается прогоном тестов как чекпойнтом; коммит — отдельно, вручную, только по явной просьбе пользователя в конце.
- **Фронтенд:** править ТОЛЬКО исходники в `frontend/admin-src/`. **НЕ запускать `npm run build`** — собранный `admin-dist/` не трогаем (пересборка засоряет дерево чужими ассетами).
- **Тесты:** запускать дефолтным pytest из каталога `journal_django/`, интерпретатор `.venv/Scripts/python.exe`. Тест-БД `journal_test` поднимается автоматически. НЕ запускать `recreate_test_db`.
- **Рабочий каталог для всех команд:** `c:\Users\ilyap\TestKOTOKOD\journal_django`.

---

## Файловая структура

**Изменение 1 (правило переходов):**
- Modify: `apps/renewals/transitions.py` — параметр `from_key`, константа `AWAITING_RENEWAL_KEY`, послабление для `awaiting_renewal`.
- Modify: `apps/renewals/repository.py` — `move_deal` передаёт `from_key=from_stage.key`.
- Modify: `apps/renewals/tests/test_transitions.py` — новые кейсы.
- Modify: `apps/renewals/tests/test_api_write.py` — end-to-end кейс «Ждём продление → Продлён».

**Изменение 2 (пересбор):**
- Create: `apps/renewals/rebuild.py` — вся доменная логика пересбора.
- Create: `apps/renewals/tests/test_rebuild.py` — юнит на раскладку + интеграция оркестратора.
- Create: `apps/sync/backfills/rebuild_renewals.py` — тонкая обёртка.
- Modify: `apps/sync/tasks.py` — Celery-задача.
- Modify: `apps/sync/views.py` — регистрация в `ACTIONS`.
- Modify: `apps/sync/tests/test_views.py` — reachability действия.
- Modify: `frontend/admin-src/src/lib/sync.ts` — запись действия в UI.

---

## Task 1: Разблокировать уход со стадии «Ждём продление»

**Files:**
- Modify: `apps/renewals/transitions.py`
- Modify: `apps/renewals/repository.py:113-151` (`move_deal`)
- Test: `apps/renewals/tests/test_transitions.py`, `apps/renewals/tests/test_api_write.py`

- [ ] **Step 1: Обновить тесты валидатора (failing)**

В `apps/renewals/tests/test_transitions.py` добавить в конец файла:

```python
def test_can_move_off_awaiting_renewal_to_won_when_cycle_completed():
    # «Ждём продление» (авто, decision) — ЕДИНСТВЕННАЯ авто-стадия, с которой
    # менеджер может уйти руками: подтвердить продление при отработанном цикле.
    assert is_allowed(from_kind='decision', from_is_auto=True,
                      from_key='awaiting_renewal', to_kind='won',
                      cycle_completed=True)


def test_can_move_off_awaiting_renewal_to_manual_decision_when_completed():
    assert is_allowed(from_kind='decision', from_is_auto=True,
                      from_key='awaiting_renewal', to_kind='decision',
                      cycle_completed=True)


def test_awaiting_renewal_to_lost_allowed_even_before_cycle_completed():
    assert is_allowed(from_kind='decision', from_is_auto=True,
                      from_key='awaiting_renewal', to_kind='lost',
                      cycle_completed=False)


def test_awaiting_renewal_to_won_still_gated_by_cycle():
    # Даже с «Ждём продление» продлить нельзя, пока цикл не отработан.
    assert not is_allowed(from_kind='decision', from_is_auto=True,
                          from_key='awaiting_renewal', to_kind='won',
                          cycle_completed=False)


def test_other_auto_stages_still_locked_off():
    # «Ждём оплату» (авто, decision, но НЕ awaiting_renewal) — уходить руками нельзя.
    assert not is_allowed(from_kind='decision', from_is_auto=True,
                          from_key='awaiting_payment', to_kind='won',
                          cycle_completed=True)
    # progress-авто — тоже нельзя.
    assert not is_allowed(from_kind='progress', from_is_auto=True,
                          from_key='lesson_1', to_kind='lost', cycle_completed=True)
```

- [ ] **Step 2: Прогнать — убедиться, что падают**

Run: `.venv/Scripts/python.exe -m pytest apps/renewals/tests/test_transitions.py -v`
Expected: 5 новых тестов FAIL (`is_allowed() got an unexpected keyword argument 'from_key'`).

- [ ] **Step 3: Реализовать правку `transitions.py`**

Полностью заменить тело `apps/renewals/transitions.py` на:

```python
"""Валидатор переходов между стадиями по их виду (kind), признаку is_auto и ключу."""
from __future__ import annotations


class InvalidTransition(Exception):
    """Недопустимый переход стадии."""


_TERMINAL = {'won', 'lost'}

# «Ждём продление» — единственная авто-стадия, с которой менеджер уходит РУКАМИ
# (подтверждение/отклонение продления). Прочие авто-стадии двигает только движок.
AWAITING_RENEWAL_KEY = 'awaiting_renewal'


def is_allowed(*, from_kind: str, to_kind: str,
               from_is_auto: bool = False, to_is_auto: bool = False,
               from_key: str | None = None,
               cycle_completed: bool = True) -> bool:
    """
    Авто-стадии (is_auto) двигает движок по событиям. Руками:
    - на авто-стадию встать нельзя (to_is_auto) — прогресс, «Ждём оплату»,
      «Ждём продление», «Заморожен»;
    - с авто-стадии уйти нельзя (from_is_auto) — КРОМЕ «Ждём продление»
      (from_key == AWAITING_RENEWAL_KEY): это точка ручного решения о продлении.
    С «Ждём продление» (kind='decision') работают обычные ворота decision-стадий:
    в другую ручную decision / «Продлён» — при завершённом цикле; «Ушёл» — всегда.

    Решение пользователя 2026-07-19 (послабляет прежний тотальный from_is_auto→False
    от 2026-07-17: без выхода со стадии «Ждём продление» сделку нельзя было закрыть
    как «Продлён»).
    """
    if from_kind in _TERMINAL:
        return False
    if from_is_auto and from_key != AWAITING_RENEWAL_KEY:
        return False
    if to_is_auto:
        return False
    if to_kind == 'progress':
        return False
    if not cycle_completed:
        return to_kind == 'lost'
    return to_kind in {'decision', 'won', 'lost'}


def assert_allowed(*, from_kind: str, to_kind: str,
                   from_is_auto: bool = False, to_is_auto: bool = False,
                   from_key: str | None = None,
                   cycle_completed: bool = True) -> None:
    if not is_allowed(from_kind=from_kind, to_kind=to_kind,
                      from_is_auto=from_is_auto, to_is_auto=to_is_auto,
                      from_key=from_key, cycle_completed=cycle_completed):
        raise InvalidTransition(f'Переход {from_kind} → {to_kind} запрещён')
```

- [ ] **Step 4: Передать `from_key` из `move_deal`**

В `apps/renewals/repository.py` в функции `move_deal` заменить вызов `assert_allowed` (сейчас строки ~130-132) на:

```python
        assert_allowed(from_kind=from_stage.kind, to_kind=to_stage.kind,
                       from_is_auto=from_stage.is_auto, to_is_auto=to_stage.is_auto,
                       from_key=from_stage.key,
                       cycle_completed=engine.cycle_completed(deal))
```

- [ ] **Step 5: Добавить end-to-end кейс в `test_api_write.py`**

В `apps/renewals/tests/test_api_write.py` добавить после `test_move_to_won_respawns_next_cycle`:

```python
@pytest.mark.django_db
def test_move_from_awaiting_renewal_to_won(admin_client, make_student, make_direction):
    """Со стадии «Ждём продление» продление подтверждается вручную (drag→won) —
    ключевой сценарий, ранее заблокированный тотальным from_is_auto (fix 2026-07-19).
    Ставим сделку на awaiting_renewal напрямую (движок ставит её сам по факту
    отработки цикла), cycle_completed мокаем — реальную посещаемость тут не строим."""
    from unittest.mock import patch
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, cycle_no=1)
    deal.stage = RenewalStage.objects.get(key='awaiting_renewal', pipeline=deal.pipeline)
    deal.save(update_fields=['stage'])
    with patch('apps.renewals.engine.cycle_completed', return_value=True):
        resp = admin_client.post(f'{BASE}/{deal.id}/move',
                                 {'to_stage_id': _stage_id('renewed')}, format='json')
    assert resp.status_code == 200
    assert resp.json()['stage_key'] == 'renewed'
    assert resp.json()['outcome_at'] is not None
```

- [ ] **Step 6: Прогнать оба тест-файла — всё зелёное**

Run: `.venv/Scripts/python.exe -m pytest apps/renewals/tests/test_transitions.py apps/renewals/tests/test_api_write.py -v`
Expected: PASS (включая ранее существовавшие — они не полагались на `from_key` и остаются валидны, т.к. по умолчанию `from_key=None`).

---

## Task 2: Чистая раскладка `plan_for_student`

**Files:**
- Create: `apps/renewals/rebuild.py`
- Test: `apps/renewals/tests/test_rebuild.py`

- [ ] **Step 1: Написать юнит-тесты раскладки (failing)**

Создать `apps/renewals/tests/test_rebuild.py`:

```python
"""Юнит на чистую раскладку plan_for_student — без БД."""
from datetime import date

from apps.renewals.rebuild import plan_for_student, target_open_stage_key

PROGRESS = ['no_lesson_yet', 'lesson_1', 'lesson_2', 'lesson_3']


def _visits(units_by_day):
    """[(day_offset, units)] → [(date, units)] на базовой дате."""
    return [(date(2026, 1, 1 + off), u) for off, u in units_by_day]


def test_target_stage_key_rules():
    assert target_open_stage_key(0, False, PROGRESS) == 'no_lesson_yet'
    assert target_open_stage_key(1, False, PROGRESS) == 'lesson_1'
    assert target_open_stage_key(3, False, PROGRESS) == 'lesson_3'
    assert target_open_stage_key(4, False, PROGRESS) == 'awaiting_renewal'
    assert target_open_stage_key(2, True, PROGRESS) == 'awaiting_payment'
    # цикл отработан + долг → продление приоритетнее оплаты
    assert target_open_stage_key(4, True, PROGRESS) == 'awaiting_renewal'


def test_active_no_lessons_opens_cycle_1_no_lesson_yet():
    plan = plan_for_student([], is_active=True, balance=10, progress_keys=PROGRESS)
    assert plan.closed == []
    assert plan.open.cycle_no == 1
    assert plan.open.stage_key == 'no_lesson_yet'


def test_active_mid_cycle_opens_progress_stage():
    # 6 уроков: цикл 1 отработан (won), 2 урока во 2-й цикл → lesson_2
    plan = plan_for_student(_visits([(0, 4), (1, 2)]), is_active=True,
                            balance=5, progress_keys=PROGRESS)
    assert [c.cycle_no for c in plan.closed] == [1]
    assert plan.closed[0].kind == 'renewed'
    assert plan.open.cycle_no == 2
    assert plan.open.stage_key == 'lesson_2'


def test_active_exactly_on_boundary_opens_awaiting_renewal():
    # ровно 16 уроков: циклы 1-3 won, цикл 4 открыт на «Ждём продление»
    plan = plan_for_student(_visits([(i, 4) for i in range(4)]), is_active=True,
                            balance=5, progress_keys=PROGRESS)
    assert [c.cycle_no for c in plan.closed] == [1, 2, 3]
    assert plan.open.cycle_no == 4
    assert plan.open.stage_key == 'awaiting_renewal'
    assert plan.open.due_date == date(2026, 1, 4)  # день 4-го урока цикла 4


def test_active_over_boundary_wons_prior_and_opens_new():
    # 18 уроков (4×4 + 2): циклы 1-4 won, цикл 5 открыт на lesson_2
    plan = plan_for_student(_visits([(i, 4) for i in range(4)] + [(4, 2)]),
                            is_active=True, balance=5, progress_keys=PROGRESS)
    assert [c.cycle_no for c in plan.closed] == [1, 2, 3, 4]
    assert all(c.kind == 'renewed' for c in plan.closed)
    assert plan.open.cycle_no == 5
    assert plan.open.stage_key == 'lesson_2'


def test_active_debt_mid_cycle_opens_awaiting_payment():
    plan = plan_for_student(_visits([(0, 4), (1, 1)]), is_active=True,
                            balance=-2, progress_keys=PROGRESS)
    assert plan.open.stage_key == 'awaiting_payment'


def test_churned_partial_last_cycle_is_lost():
    # ушёл: 5 уроков (цикл 1 won, цикл 2 неполный) → цикл 2 «Ушёл»
    plan = plan_for_student(_visits([(0, 4), (1, 1)]), is_active=False,
                            balance=0, progress_keys=PROGRESS)
    assert plan.open is None
    kinds = {c.cycle_no: c.kind for c in plan.closed}
    assert kinds == {1: 'renewed', 2: 'churned'}


def test_churned_exactly_on_boundary_all_renewed_no_lost():
    plan = plan_for_student(_visits([(0, 4), (1, 4)]), is_active=False,
                            balance=0, progress_keys=PROGRESS)
    assert plan.open is None
    assert [c.kind for c in plan.closed] == ['renewed', 'renewed']
```

- [ ] **Step 2: Прогнать — убедиться, что падают**

Run: `.venv/Scripts/python.exe -m pytest apps/renewals/tests/test_rebuild.py -v`
Expected: FAIL (`ModuleNotFoundError: apps.renewals.rebuild`).

- [ ] **Step 3: Реализовать `rebuild.py` (только чистая часть)**

Создать `apps/renewals/rebuild.py`:

```python
"""
Пересбор сделок продления из истории посещаемости («правда из данных»).

Чистая раскладка (plan_for_student / target_open_stage_key) отделена от записи в
БД (rebuild_all ниже) — раскладку покрываем юнит-тестами без БД.

Модель: цикл = 4 суммарных урока (LESSONS_PER_CYCLE), half-lesson уже в units.
Каждый пройденный рубеж i×4 → закрытая «Продлён»; хвост — одна открытая сделка
(или «Ушёл» для покинувшего). Посещение сверх рубежа = продление по факту
продолжения занятий (решение 2026-07-19). Ровно на рубеже (активный) → последний
цикл открыт на «Ждём продление».
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from apps.renewals.cycle import LESSONS_PER_CYCLE


@dataclass
class ClosedCycle:
    cycle_no: int
    kind: str            # 'renewed' | 'churned'
    date: date


@dataclass
class OpenCycle:
    cycle_no: int
    stage_key: str       # awaiting_renewal | awaiting_payment | no_lesson_yet | lesson_N
    due_date: date | None  # день 4-го урока для awaiting_renewal, иначе None


@dataclass
class StudentPlan:
    closed: list[ClosedCycle]
    open: OpenCycle | None


def target_open_stage_key(into: float, debt: bool, progress_keys: list[str]) -> str:
    """Ключ авто-стадии открытой сделки — по правилу engine._target_auto_stage:
    цикл отработан (into>=4) → awaiting_renewal (приоритетнее оплаты); долг →
    awaiting_payment; иначе прогресс-стадия по числу отработанных уроков цикла."""
    if into >= LESSONS_PER_CYCLE:
        return 'awaiting_renewal'
    if debt:
        return 'awaiting_payment'
    idx = min(max(int(into), 0), len(progress_keys) - 1)
    return progress_keys[idx]


def plan_for_student(visits: list[tuple[date, float]], *, is_active: bool,
                     balance: float, progress_keys: list[str]) -> StudentPlan:
    """visits — посещения (present=true) в хронологии [(date, units)]."""
    total = 0.0
    boundary = float(LESSONS_PER_CYCLE)
    cycle_i = 1
    closed: list[ClosedCycle] = []
    for day, units in visits:
        total += float(units)
        while total >= boundary:
            closed.append(ClosedCycle(cycle_no=cycle_i, kind='renewed', date=day))
            cycle_i += 1
            boundary += LESSONS_PER_CYCLE
    completed_full = cycle_i - 1
    rem = total - completed_full * LESSONS_PER_CYCLE
    debt = balance <= 0

    if is_active:
        if rem == 0 and completed_full >= 1:
            # цикл завершён ровно — это не «Продлён», а «Ждём продление»:
            # откатываем последний won, делаем его открытой сделкой-решением.
            last = closed.pop()
            open_cycle = OpenCycle(cycle_no=last.cycle_no,
                                   stage_key='awaiting_renewal', due_date=last.date)
        else:
            key = target_open_stage_key(rem, debt, progress_keys)
            open_cycle = OpenCycle(cycle_no=completed_full + 1, stage_key=key,
                                   due_date=None)
        return StudentPlan(closed=closed, open=open_cycle)

    # покинувший: неполный последний цикл → «Ушёл»; ровно на рубеже — все won.
    if rem > 0 and visits:
        closed.append(ClosedCycle(cycle_no=completed_full + 1, kind='churned',
                                  date=visits[-1][0]))
    return StudentPlan(closed=closed, open=None)
```

- [ ] **Step 4: Прогнать — зелёное**

Run: `.venv/Scripts/python.exe -m pytest apps/renewals/tests/test_rebuild.py -v`
Expected: PASS (все юнит-кейсы раскладки).

---

## Task 3: Оркестратор `rebuild_all` (запись в БД)

**Files:**
- Modify: `apps/renewals/rebuild.py` (дописать оркестратор)
- Test: `apps/renewals/tests/test_rebuild.py` (дописать интеграцию)

- [ ] **Step 1: Написать интеграционные тесты оркестратора (failing)**

Дописать в конец `apps/renewals/tests/test_rebuild.py`:

```python
import pytest
from datetime import date

from apps.renewals.models import RenewalDeal


def _patch_loaders(monkeypatch, attendance, active, balances):
    monkeypatch.setattr('apps.renewals.rebuild._load_attendance', lambda: attendance)
    monkeypatch.setattr('apps.renewals.rebuild._active_students', lambda: active)
    monkeypatch.setattr('apps.renewals.rebuild.balances_for_students',
                        lambda ids: {i: balances.get(i, 0) for i in ids})


@pytest.mark.django_db
def test_rebuild_dry_run_writes_nothing(monkeypatch, make_student):
    from apps.renewals import rebuild
    sid = make_student()
    _patch_loaders(monkeypatch,
                   attendance={sid: [(date(2026, 1, 1), 4.0), (date(2026, 1, 2), 2.0)]},
                   active={sid}, balances={sid: 5})
    before = RenewalDeal.objects.count()
    res = rebuild.rebuild_all(dry_run=True)
    assert res['dry_run'] is True
    assert res['created_won'] == 1
    assert res['created_open'] == 1
    assert RenewalDeal.objects.count() == before  # ничего не записано


@pytest.mark.django_db
def test_rebuild_apply_writes_expected_deals(monkeypatch, make_student):
    from apps.renewals import rebuild
    sid = make_student()
    _patch_loaders(monkeypatch,
                   attendance={sid: [(date(2026, 1, i + 1), 4.0) for i in range(4)] +
                                    [(date(2026, 1, 5), 2.0)]},  # 18 уроков
                   active={sid}, balances={sid: 5})
    rebuild.rebuild_all(dry_run=False)
    deals = RenewalDeal.objects.filter(student_id=sid).order_by('cycle_no')
    assert [d.cycle_no for d in deals] == [1, 2, 3, 4, 5]
    assert [d.outcome_at is None for d in deals] == [False, False, False, False, True]
    assert deals.get(cycle_no=5).stage.key == 'lesson_2'


@pytest.mark.django_db
def test_rebuild_is_idempotent(monkeypatch, make_student):
    from apps.renewals import rebuild
    sid = make_student()
    _patch_loaders(monkeypatch,
                   attendance={sid: [(date(2026, 1, i + 1), 4.0) for i in range(4)]},
                   active={sid}, balances={sid: 5})
    rebuild.rebuild_all(dry_run=False)
    first = list(RenewalDeal.objects.filter(student_id=sid)
                 .order_by('cycle_no').values_list('cycle_no', 'stage__key'))
    rebuild.rebuild_all(dry_run=False)
    second = list(RenewalDeal.objects.filter(student_id=sid)
                  .order_by('cycle_no').values_list('cycle_no', 'stage__key'))
    assert first == second
    # ровно на рубеже: цикл 4 открыт на awaiting_renewal
    assert second[-1] == (4, 'awaiting_renewal')
```

- [ ] **Step 2: Прогнать — падают**

Run: `.venv/Scripts/python.exe -m pytest apps/renewals/tests/test_rebuild.py -k rebuild_ -v`
Expected: FAIL (`AttributeError: module 'apps.renewals.rebuild' has no attribute 'rebuild_all'`).

- [ ] **Step 3: Дописать оркестратор в `rebuild.py`**

Добавить в конец `apps/renewals/rebuild.py`:

```python
from datetime import datetime, time

from django.db import connection, transaction
from django.utils import timezone as tz

from apps.finances.repository import balances_for_students
from apps.renewals.models import (
    RenewalActivity, RenewalDeal, RenewalPipeline, RenewalStage)


def _dt(day: date):
    """date → aware datetime (полдень; важен день, не время)."""
    return tz.make_aware(datetime.combine(day, time(12, 0)))


def _load_attendance() -> dict[int, list[tuple[date, float]]]:
    """Вся посещаемость present=true в хронологии, сгруппированная по ученику."""
    by_student: dict[int, list] = {}
    with connection.cursor() as cur:
        cur.execute("""
            SELECT la.student_id, l.lesson_date,
                   CASE WHEN l.lesson_duration_minutes = 45 THEN 0.5 ELSE 1 END AS units
            FROM lesson_attendance la
            JOIN lessons l ON l.id = la.lesson_id
            WHERE la.present = true
            ORDER BY la.student_id, l.lesson_date, l.id
        """)
        for sid, day, units in cur.fetchall():
            by_student.setdefault(sid, []).append((day, float(units)))
    return by_student


def _active_students() -> set[int]:
    with connection.cursor() as cur:
        cur.execute("SELECT DISTINCT student_id FROM group_memberships WHERE active = true")
        return {r[0] for r in cur.fetchall()}


def _stage_context(pipe) -> tuple[dict, list[str]]:
    stages = {s.key: s for s in RenewalStage.objects.filter(pipeline=pipe)}
    progress_keys = [s.key for s in RenewalStage.objects
                     .filter(pipeline=pipe, kind='progress', is_auto=True)
                     .order_by('sort_order')]
    return stages, progress_keys


def _current_open_labels() -> dict[int, tuple[str, str]]:
    """student_id → (имя, текущая стадия открытой сделки) для превью в dry-run."""
    out: dict[int, tuple[str, str]] = {}
    with connection.cursor() as cur:
        cur.execute("""
            SELECT d.student_id, s.full_name, st.label
            FROM renewal_deal d
            JOIN students s ON s.id = d.student_id
            JOIN renewal_stage st ON st.id = d.stage_id
            WHERE d.outcome_at IS NULL
        """)
        for sid, name, label in cur.fetchall():
            out[sid] = (name, label)
    return out


def _write_plan(sid: int, plan: StudentPlan, pipe, stages: dict) -> None:
    for c in plan.closed:
        stage = stages['renewed'] if c.kind == 'renewed' else stages['churned']
        deal = RenewalDeal.objects.create(
            student_id=sid, cycle_no=c.cycle_no, pipeline=pipe, stage=stage,
            due_at=(c.date if c.kind == 'renewed' else None),
            outcome_at=_dt(c.date),
            reason_code=('unknown' if c.kind == 'churned' else None))
        RenewalDeal.objects.filter(id=deal.id).update(
            stage_entered_at=_dt(c.date), created_at=_dt(c.date))
        RenewalActivity.objects.create(
            deal=deal, kind='system', to_stage=stage,
            body=('Пересобрано из истории посещений' if c.kind == 'renewed'
                  else 'Пересобрано из истории: ученик прекратил занятия'))
    if plan.open is not None:
        stage = stages[plan.open.stage_key]
        deal = RenewalDeal.objects.create(
            student_id=sid, cycle_no=plan.open.cycle_no, pipeline=pipe, stage=stage,
            due_at=plan.open.due_date)
        RenewalActivity.objects.create(
            deal=deal, kind='system', to_stage=stage, body='Сделка пересобрана')


def rebuild_all(dry_run: bool = False) -> dict:
    """Пересобрать сделки всех учеников из истории посещаемости. dry_run — только
    план (ничего не пишет). apply — атомарно снести все сделки и записать заново."""
    pipe = RenewalPipeline.objects.get(is_default=True)
    stages, progress_keys = _stage_context(pipe)
    by_student = _load_attendance()
    active = _active_students()
    student_ids = set(by_student) | active
    balances = balances_for_students(list(student_ids))

    plans: dict[int, StudentPlan] = {}
    created_won = created_lost = created_open = 0
    for sid in student_ids:
        plan = plan_for_student(by_student.get(sid, []), is_active=sid in active,
                                balance=float(balances.get(sid, 0)),
                                progress_keys=progress_keys)
        plans[sid] = plan
        created_won += sum(1 for c in plan.closed if c.kind == 'renewed')
        created_lost += sum(1 for c in plan.closed if c.kind == 'churned')
        created_open += 1 if plan.open is not None else 0

    deals_deleted = RenewalDeal.objects.count()

    # Превью: до 10 учеников с открытой сделкой — текущая стадия → планируемая.
    current = _current_open_labels()
    samples = []
    for sid, plan in plans.items():
        if plan.open is None or sid not in current:
            continue
        name, cur_label = current[sid]
        samples.append({'student': name, 'from': cur_label,
                        'to': stages[plan.open.stage_key].label})
        if len(samples) >= 10:
            break

    if not dry_run:
        with transaction.atomic():
            RenewalDeal.objects.all().delete()  # каскадит renewal_activity, аудит в pghistory
            for sid, plan in plans.items():
                _write_plan(sid, plan, pipe, stages)

    return {
        'entity': 'renewals-rebuild', 'dry_run': dry_run,
        'deals_deleted': deals_deleted,
        'created_won': created_won, 'created_lost': created_lost,
        'created_open': created_open, 'students': len(student_ids),
        'samples': samples,
    }
```

- [ ] **Step 4: Прогнать весь файл — зелёное**

Run: `.venv/Scripts/python.exe -m pytest apps/renewals/tests/test_rebuild.py -v`
Expected: PASS (юнит раскладки + 3 интеграционных).

---

## Task 4: Подключить действие `rebuild-renewals` в «Синхро»

**Files:**
- Create: `apps/sync/backfills/rebuild_renewals.py`
- Modify: `apps/sync/tasks.py`
- Modify: `apps/sync/views.py`
- Test: `apps/sync/tests/test_views.py`

- [ ] **Step 1: Написать reachability-тест (failing)**

Добавить в `apps/sync/tests/test_views.py`:

```python
@pytest.mark.django_db
def test_run_rebuild_renewals_action_reachable(superadmin_client, monkeypatch):
    """rebuild-renewals подключён end-to-end через URL (destructive-действие)."""
    monkeypatch.setattr(
        'apps.sync.backfills.rebuild_renewals.run',
        lambda dry_run=False: {'entity': 'renewals-rebuild', 'dry_run': dry_run},
    )
    run_resp = superadmin_client.post(
        '/api/admin/sync/rebuild-renewals/run', {'dry_run': True}, format='json',
    )
    assert run_resp.status_code == 202
    assert run_resp.data['task_id']
```

- [ ] **Step 2: Прогнать — падает**

Run: `.venv/Scripts/python.exe -m pytest apps/sync/tests/test_views.py::test_run_rebuild_renewals_action_reachable -v`
Expected: FAIL (404 Unknown sync action — действия ещё нет в ACTIONS).

- [ ] **Step 3: Создать обёртку backfill**

Создать `apps/sync/backfills/rebuild_renewals.py`:

```python
# journal_django/apps/sync/backfills/rebuild_renewals.py
"""Полный пересбор всех сделок продления из истории посещаемости.

Тонкая обёртка над apps.renewals.rebuild.rebuild_all. dry_run=true — только план
(счётчики + примеры), ничего не пишет. apply — атомарно сносит все сделки и
записывает заново (см. apps/renewals/rebuild.py и спеку 2026-07-19)."""
from __future__ import annotations

from apps.renewals import rebuild


def run(dry_run: bool = False) -> dict:
    return rebuild.rebuild_all(dry_run=dry_run)
```

- [ ] **Step 4: Зарегистрировать Celery-задачу**

В `apps/sync/tasks.py` в блоке импорта `from apps.sync.backfills import (...)` добавить `rebuild_renewals` в список, и добавить задачу (рядом с `rebuild_absence_resolutions_task`):

```python
@shared_task(name='apps.sync.tasks.rebuild_renewals_task', time_limit=300)
def rebuild_renewals_task(dry_run: bool = False) -> dict:
    return rebuild_renewals.run(dry_run=dry_run)
```

- [ ] **Step 5: Зарегистрировать в `ACTIONS`**

В `apps/sync/views.py` в словарь `ACTIONS` добавить строку (после `'rebuild-absence-resolutions'`):

```python
    'rebuild-renewals': tasks.rebuild_renewals_task,
```

- [ ] **Step 6: Прогнать — зелёное**

Run: `.venv/Scripts/python.exe -m pytest apps/sync/tests/test_views.py -v`
Expected: PASS (включая новый reachability-тест; прежние тесты не затронуты).

---

## Task 5: Карточка действия в admin SPA (Синхро)

**Files:**
- Modify: `frontend/admin-src/src/lib/sync.ts`

> ⚠️ Только исходник. **НЕ запускать `npm run build`.**

- [ ] **Step 1: Добавить действие в тип и список**

В `frontend/admin-src/src/lib/sync.ts`:

1. В union `SyncAction` добавить `| 'rebuild-renewals'` (например, рядом с `'rebuild-absence-resolutions'`):

```typescript
export type SyncAction =
  | 'teachers' | 'groups' | 'students' | 'lessons' | 'payments' | 'payroll'
  | 'rebuild-payroll' | 'rebuild-counters' | 'rebuild-planned-lessons'
  | 'rebuild-absence-resolutions' | 'rebuild-renewals' | 'run-all';
```

2. В массив `SYNC_ACTIONS` добавить запись (в группе `'rebuild'`, последней):

```typescript
  {
    action: 'rebuild-renewals',
    label: '⚠️ Продления — ПОЛНЫЙ пересбор всех сделок из посещаемости (стирает ответственных, комментарии, напоминания)',
    group: 'rebuild',
  },
```

- [ ] **Step 2: Проверка типов (без сборки)**

Run (из `frontend/admin-src`): `npx tsc --noEmit`
Expected: без ошибок типов. (Если `tsc` недоступен/медленный — визуально убедиться, что `action` соответствует union `SyncAction`; карточка рендерится в `SyncPage.tsx` автоматически из `SYNC_ACTIONS`.)

---

## Task 6: Финальная проверка (связывает оба изменения)

**Files:** нет новых — прогон и ручная сверка.

- [ ] **Step 1: Прогнать все затронутые тест-наборы**

Run: `.venv/Scripts/python.exe -m pytest apps/renewals apps/sync -v`
Expected: PASS во всех.

- [ ] **Step 2: Полный прогон renewals + смежных на регрессии**

Run: `.venv/Scripts/python.exe -m pytest apps/renewals apps/sync apps/lessons apps/finances -q`
Expected: PASS (правка `transitions.py` затрагивает только renewals; убеждаемся, что смежные домены не сломаны).

- [ ] **Step 3: Ручная сверка dry-run на dev-БД (реальные данные)**

Run: `.venv/Scripts/python.exe manage.py shell -c "from apps.renewals import rebuild; import json; print(json.dumps(rebuild.rebuild_all(dry_run=True), ensure_ascii=False, default=str, indent=2))"`
Expected: печатается план (`deals_deleted`, `created_won/lost/open`, `students`, `samples`). Убедиться, что `samples` содержит осмысленные переходы (напр. Антонов `Ждём продление → Урок 2`), и что `RenewalDeal` в БД НЕ изменились (dry_run ничего не пишет).

- [ ] **Step 4: Отчитаться пользователю**

Сообщить итог: оба изменения реализованы, все тесты зелёные, dry-run на реальных данных показывает корректный план. НЕ применять apply и НЕ коммитить без явной просьбы пользователя.

---

## Self-review заметки

- **Покрытие спеки:** Изменение 1 → Task 1; чистая раскладка → Task 2; оркестратор/wipe/dry-run/идемпотентность → Task 3; sync-обвязка (backfill+task+ACTIONS) → Task 4; фронт → Task 5; тесты и E2E-связка → распределены по Task 1/3/4/6.
- **Крайние случаи спеки:** «ушедший ровно на рубеже» → `test_churned_exactly_on_boundary_all_renewed_no_lost` (Task 2); «долг → awaiting_payment» → `test_active_debt_mid_cycle_opens_awaiting_payment` (Task 2); «ровно на рубеже → awaiting_renewal» → Task 2 + Task 3 идемпотентность.
- **Согласованность имён:** `plan_for_student`, `target_open_stage_key`, `rebuild_all`, `StudentPlan/ClosedCycle/OpenCycle`, стадии-ключи `renewed/churned/awaiting_renewal/awaiting_payment/no_lesson_yet/lesson_N`, action-slug `rebuild-renewals`, task `rebuild_renewals_task` — используются одинаково во всех задачах.
- **Прогресс-ключи** (`no_lesson_yet/lesson_1..3`) берутся из БД по `kind='progress', is_auto=True order by sort_order` (Task 3 `_stage_context`), в юнит-тестах передаются явным списком `PROGRESS`.
