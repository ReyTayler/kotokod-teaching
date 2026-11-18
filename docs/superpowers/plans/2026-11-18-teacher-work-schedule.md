# График работы преподавателя — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.
>
> **Правила этого репозитория для исполнителей (перекрывают шаблон скилла):**
> - **НИКАКИХ git-команд** (add/commit/stash/checkout/reset). Коммиты делает координатор после ревью — в дереве лежит чужой WIP.
> - Не пересоздавать тестовую БД (`recreate_test_db`), не запускать `npm run build` (dist не трогаем).
> - Не трогать файлы вне списка задачи. Существующие файлы с чужим WIP правим **точечно** (append/вставка), не переписываем целиком.
> - После каждой задачи — ревью `review-agent` (обязательно), затем коммит координатором.

**Цель:** преподаватель и сотрудники задают недельный шаблон рабочих окон + исключения на даты; окна видны белым/серым в редакторе «График работы» и фоном в календарях (teacher и admin при одном преподавателе). Блокера постановки уроков нет.

**Архитектура:** новое Django-приложение `apps/availability` (модели интервалов с CHECK, сервис итоговых окон, DRF-вьюхи teacher/admin поверх общих базовых классов). Фон календаря — поле `availability` в ответах `/api/calendar` и `/api/admin/calendar`. Фронт — один общий редактор `shared/availability/ScheduleEditor` (admin-src/src/shared, teacher подключает через `@shared`), параметризованный базовым URL; `WeekGrid` получает необязательный проп `availability`.

**Стек:** Django 5 + DRF, pghistory, PostgreSQL, pytest; React 19, TanStack Query v5, React Router v7, TypeScript.

**Спека:** `docs/superpowers/specs/2026-11-18-teacher-work-schedule-design.md`.

---

## Карта файлов

Создать:
- `journal_django/apps/availability/__init__.py`, `apps.py`, `models.py`, `services.py`, `serializers.py`, `views.py`, `urls.py`, `admin_urls.py`, `migrations/__init__.py`, `migrations/0001_initial.py` (makemigrations)
- `journal_django/apps/availability/tests/__init__.py`, `conftest.py`, `test_models.py`, `test_services.py`, `test_api.py`, `test_calendar_availability.py`
- `journal_django/frontend/admin-src/src/shared/availability/types.ts`, `grid.ts`, `useSchedule.ts`, `ScheduleEditor.tsx`, `schedule.css`
- `journal_django/frontend/teacher-src/src/pages/schedule/SchedulePage.tsx`
- `journal_django/frontend/admin-src/src/pages/teachers/TeacherScheduleTab.tsx`

Изменить (точечно):
- `journal_django/config/settings/base.py` — `INSTALLED_APPS += 'apps.availability'`
- `journal_django/config/urls.py` — два include
- `journal_django/apps/changelog/registry.py`, `summary.py`, `labels.py`
- `journal_django/apps/scheduling/views.py` — `CalendarView`, `AdminCalendarView`
- `journal_django/frontend/admin-src/src/lib/labels.ts` — операции и сущности журнала
- `journal_django/frontend/admin-src/src/shared/calendar/types.ts`, `WeekGrid.tsx`, `CalendarView.tsx`, `calendar.css`
- `journal_django/frontend/teacher-src/src/lib/types.ts`, `App.tsx`, `components/shell/TeacherShell.tsx`, `pages/calendar/CalendarPage.tsx`
- `journal_django/frontend/admin-src/src/pages/calendar/AdminCalendarPage.tsx`, `pages/teachers/TeacherDetailPage.tsx`, `lib/permissions.ts`

---

### Task 1: Приложение `availability` — модели, миграция, журнал изменений

**Агент:** backend-django

**Files:**
- Create: `journal_django/apps/availability/{__init__,apps,models}.py`, `migrations/__init__.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_models.py`
- Modify: `journal_django/config/settings/base.py` (INSTALLED_APPS, после `'apps.scheduling'`), `apps/changelog/registry.py`, `apps/changelog/summary.py` (`_ENTITY_RU`), `frontend/admin-src/src/lib/labels.ts` (карта сущностей журнала, рядом с `cancellation_reason: 'Причина отмены'`)

- [ ] **Step 1: apps.py и __init__**

```python
# apps/availability/apps.py
from django.apps import AppConfig


class AvailabilityConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.availability'
    label = 'availability'
```

`__init__.py`, `migrations/__init__.py`, `tests/__init__.py` — пустые. Добавить `'apps.availability',` в `INSTALLED_APPS` после `'apps.scheduling',`.

- [ ] **Step 2: models.py**

```python
"""
График работы преподавателя (спека 2026-11-18-teacher-work-schedule-design.md).

Недельный шаблон (AvailabilityRule) + исключения на даты (AvailabilityOverride).
Если на дату есть хоть одна строка исключения — она ЦЕЛИКОМ заменяет шаблон дня;
строка с start_time/end_time = NULL означает «день закрыт».

Окна — подсказка для планирования, НЕ блокер постановки уроков (решение владельца).
Сетка: шаг 30 минут, 08:00–22:00; инварианты продублированы CHECK-ами в БД.
"""
from __future__ import annotations

import datetime

import pghistory
from django.db import models
from django.db.models import Q

GRID_START = datetime.time(8, 0)
GRID_END = datetime.time(22, 0)

_HALF_HOUR_START = Q(start_time__minute__in=[0, 30]) & Q(start_time__second=0)
_HALF_HOUR_END = Q(end_time__minute__in=[0, 30]) & Q(end_time__second=0)
_IN_GRID = Q(start_time__gte=GRID_START) & Q(end_time__lte=GRID_END)
_ORDERED = Q(start_time__lt=models.F('end_time'))


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class AvailabilityRule(models.Model):
    """Окно недельного шаблона: day_of_week — конвенция Вс=0 (как group_schedule_slots)."""

    id = models.BigAutoField(primary_key=True)
    teacher = models.ForeignKey('teachers.Teacher', on_delete=models.CASCADE,
                                related_name='availability_rules')
    day_of_week = models.SmallIntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        managed = True
        db_table = 'teacher_availability_rules'
        indexes = [models.Index(fields=['teacher', 'day_of_week'], name='avail_rule_teacher_dow_idx')]
        constraints = [
            models.CheckConstraint(name='avail_rule_dow_check',
                                   condition=Q(day_of_week__gte=0) & Q(day_of_week__lte=6)),
            models.CheckConstraint(name='avail_rule_ordered', condition=_ORDERED),
            models.CheckConstraint(name='avail_rule_in_grid', condition=_IN_GRID),
            models.CheckConstraint(name='avail_rule_half_hour',
                                   condition=_HALF_HOUR_START & _HALF_HOUR_END),
        ]

    def __str__(self) -> str:
        return f'AvailabilityRule#{self.pk} t={self.teacher_id} d={self.day_of_week} {self.start_time}-{self.end_time}'


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class AvailabilityOverride(models.Model):
    """Исключение на дату. start_time/end_time = NULL → день закрыт целиком."""

    id = models.BigAutoField(primary_key=True)
    teacher = models.ForeignKey('teachers.Teacher', on_delete=models.CASCADE,
                                related_name='availability_overrides')
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = 'teacher_availability_overrides'
        indexes = [models.Index(fields=['teacher', 'date'], name='avail_override_teacher_date_idx')]
        constraints = [
            models.CheckConstraint(
                name='avail_override_both_or_none',
                condition=(Q(start_time__isnull=True) & Q(end_time__isnull=True))
                | (Q(start_time__isnull=False) & Q(end_time__isnull=False)),
            ),
            models.CheckConstraint(name='avail_override_ordered',
                                   condition=Q(start_time__isnull=True) | _ORDERED),
            models.CheckConstraint(name='avail_override_in_grid',
                                   condition=Q(start_time__isnull=True) | _IN_GRID),
            models.CheckConstraint(name='avail_override_half_hour',
                                   condition=Q(start_time__isnull=True)
                                   | (_HALF_HOUR_START & _HALF_HOUR_END)),
            # Не больше одной строки «день закрыт» на дату.
            models.UniqueConstraint(fields=['teacher', 'date'],
                                    condition=Q(start_time__isnull=True),
                                    name='avail_override_one_closed_per_date'),
        ]

    def __str__(self) -> str:
        return f'AvailabilityOverride#{self.pk} t={self.teacher_id} {self.date} {self.start_time}-{self.end_time}'
```

- [ ] **Step 3: Журнал изменений**

`apps/changelog/registry.py`, в `TRACKED` после строк `cancellations.*`:

```python
    # График работы преподавателя: шаблон и исключения перезаписываются целиком
    # по дню — построчный откат собрал бы несогласованный день, поэтому только след.
    'availability.AvailabilityRule':     TrackedModel('availability_rule', False, 20),
    'availability.AvailabilityOverride': TrackedModel('availability_override', False, 20),
```

`apps/changelog/summary.py`, в `_ENTITY_RU` добавить:
```python
    'availability_rule': 'Окно графика', 'availability_override': 'Исключение графика',
```
`frontend/admin-src/src/lib/labels.ts` — в карту сущностей (где `cancellation_reason: 'Причина отмены'`) добавить:
```ts
  availability_rule: 'Окно графика',
  availability_override: 'Исключение графика',
```

- [ ] **Step 4: Миграция и применение к journal_test**

Run (из `journal_django/`):
```
python manage.py makemigrations availability
python manage.py migrate availability
python manage.py migrate availability --settings=config.settings.test
```
Expected: создан `apps/availability/migrations/0001_initial.py` (модели + Event-модели + pgtrigger), миграции применены к dev-БД и к `journal_test`. Если `--settings=config.settings.test` не подходит по проекту — посмотреть `config/settings/test.py`/`scripts/` и применить штатным способом; БД НЕ пересоздавать.

- [ ] **Step 5: conftest тестов**

```python
# apps/availability/tests/conftest.py
"""Фикстуры availability. Работаем в общей journal_test (как большинство apps) —
no-op django_db_setup; каждый тест в транзакции pytest-django (откат)."""
from __future__ import annotations

import pytest
from django.utils import timezone

from apps.teachers.models import Teacher
from conftest import _create_account, _delete_account, _jwt_client_for_id


@pytest.fixture(scope='session')
def django_db_setup():
    pass


@pytest.fixture
def teacher(db):
    return Teacher.objects.create(name='__avail_teacher__', active=True, created_at=timezone.now())


@pytest.fixture
def other_teacher(db):
    return Teacher.objects.create(name='__avail_other__', active=True, created_at=timezone.now())


@pytest.fixture
def own_teacher_client(teacher):
    """JWT-клиент учётки role=teacher, привязанной к фикстуре teacher."""
    acc_id, _ = _create_account('__avail_t__@test.local', 'teacher', teacher_id=teacher.id)
    yield _jwt_client_for_id(acc_id)
    _delete_account(acc_id)
```

- [ ] **Step 6: Тесты CHECK-ограничений (test_models.py)**

```python
import datetime as dt

import pytest
from django.db import IntegrityError, transaction

from apps.availability.models import AvailabilityOverride, AvailabilityRule

pytestmark = pytest.mark.django_db
T = dt.time


@pytest.mark.parametrize('start,end', [
    (T(10, 0), T(9, 0)),     # start >= end
    (T(7, 30), T(9, 0)),     # раньше 08:00
    (T(21, 0), T(22, 30)),   # позже 22:00
    (T(10, 15), T(11, 0)),   # не кратно 30
])
def test_rule_rejects_bad_interval(teacher, start, end):
    with pytest.raises(IntegrityError), transaction.atomic():
        AvailabilityRule.objects.create(teacher=teacher, day_of_week=1, start_time=start, end_time=end)


def test_rule_rejects_bad_weekday(teacher):
    with pytest.raises(IntegrityError), transaction.atomic():
        AvailabilityRule.objects.create(teacher=teacher, day_of_week=7, start_time=T(10), end_time=T(11))


def test_rule_accepts_grid_bounds(teacher):
    AvailabilityRule.objects.create(teacher=teacher, day_of_week=0, start_time=T(8), end_time=T(22))


def test_override_half_null_rejected(teacher):
    with pytest.raises(IntegrityError), transaction.atomic():
        AvailabilityOverride.objects.create(teacher=teacher, date=dt.date(2030, 1, 7), start_time=T(10))


def test_override_closed_unique_per_date(teacher):
    d = dt.date(2030, 1, 7)
    AvailabilityOverride.objects.create(teacher=teacher, date=d)
    with pytest.raises(IntegrityError), transaction.atomic():
        AvailabilityOverride.objects.create(teacher=teacher, date=d)
```

- [ ] **Step 7: Прогон**

Run: `pytest apps/availability apps/changelog/tests/test_registry.py -q` (из `journal_django/`)
Expected: всё PASS (включая `test_registry_covers_all_tracked_models`).

---

### Task 2: Сервис итоговых окон и сохранения

**Агент:** backend-django

**Files:**
- Create: `journal_django/apps/availability/services.py`, `tests/test_services.py`

- [ ] **Step 1: Падающие тесты (test_services.py)**

```python
import datetime as dt

import pytest

from apps.availability import services
from apps.availability.models import AvailabilityOverride, AvailabilityRule

pytestmark = pytest.mark.django_db
T = dt.time
MON = dt.date(2030, 1, 7)          # понедельник (JS day 1)
SUN = dt.date(2030, 1, 13)         # воскресенье (JS day 0)


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    monkeypatch.setattr(services, '_today', lambda: dt.date(2030, 1, 1))


def test_normalize_merges_overlapping_and_adjacent():
    got = services.normalize([(T(12), T(13)), (T(10), T(11)), (T(11), T(12)), (T(15), T(16)), (T(15, 30), T(17))])
    assert got == [(T(10), T(13)), (T(15), T(17))]


def test_effective_windows_template_only(teacher):
    AvailabilityRule.objects.create(teacher=teacher, day_of_week=1, start_time=T(10), end_time=T(14))
    w = services.get_effective_windows(teacher.id, MON, SUN)
    assert w[MON] == [(T(10), T(14))]
    assert w[SUN] == []
    assert len(w) == 7


def test_override_replaces_day_and_closed_day(teacher):
    AvailabilityRule.objects.create(teacher=teacher, day_of_week=1, start_time=T(10), end_time=T(14))
    AvailabilityRule.objects.create(teacher=teacher, day_of_week=2, start_time=T(10), end_time=T(14))
    AvailabilityOverride.objects.create(teacher=teacher, date=MON, start_time=T(16), end_time=T(18))
    AvailabilityOverride.objects.create(teacher=teacher, date=MON + dt.timedelta(days=1))  # Вт закрыт
    w = services.get_effective_windows(teacher.id, MON, SUN)
    assert w[MON] == [(T(16), T(18))]
    assert w[MON + dt.timedelta(days=1)] == []


def test_has_schedule(teacher):
    assert services.has_schedule(teacher.id) is False
    AvailabilityOverride.objects.create(teacher=teacher, date=MON)
    assert services.has_schedule(teacher.id) is True


def test_replace_template_normalizes_and_skips_unchanged_days(teacher):
    services.replace_template(teacher.id, {1: [(T(10), T(11)), (T(11), T(12))], 3: [(T(15), T(16))]})
    assert services.get_template(teacher.id) == {1: [(T(10), T(12))], 3: [(T(15), T(16))]}
    wed_id = AvailabilityRule.objects.get(teacher=teacher, day_of_week=3).id
    services.replace_template(teacher.id, {1: [], 3: [(T(15), T(16))]})
    assert services.get_template(teacher.id) == {3: [(T(15), T(16))]}
    # Неизменённый день не переписывался (нет лишних событий журнала).
    assert AvailabilityRule.objects.get(teacher=teacher, day_of_week=3).id == wed_id


def test_replace_week_writes_only_diff_from_template(teacher):
    services.replace_template(teacher.id, {1: [(T(10), T(14))], 2: [(T(10), T(14))]})
    services.replace_week(teacher.id, MON, {
        MON: [(T(10), T(14))],                          # = шаблон → исключения нет
        MON + dt.timedelta(days=1): [],                 # закрыт
        MON + dt.timedelta(days=2): [(T(9), T(10))],    # открыт сверх шаблона
    })
    rows = list(AvailabilityOverride.objects.filter(teacher=teacher).order_by('date')
                .values_list('date', 'start_time', 'end_time'))
    assert rows == [
        (MON + dt.timedelta(days=1), None, None),
        (MON + dt.timedelta(days=2), T(9), T(10)),
    ]


def test_replace_week_resets_day_back_to_template(teacher):
    services.replace_template(teacher.id, {1: [(T(10), T(14))]})
    AvailabilityOverride.objects.create(teacher=teacher, date=MON)
    services.replace_week(teacher.id, MON, {MON: [(T(10), T(14))]})
    assert not AvailabilityOverride.objects.filter(teacher=teacher).exists()


def test_replace_week_rejects_past_dates(teacher, monkeypatch):
    monkeypatch.setattr(services, '_today', lambda: dt.date(2030, 1, 9))
    with pytest.raises(services.ScheduleError):
        services.replace_week(teacher.id, MON, {MON: []})


def test_replace_week_rejects_date_outside_week(teacher):
    with pytest.raises(services.ScheduleError):
        services.replace_week(teacher.id, MON, {SUN + dt.timedelta(days=1): []})


def test_replace_week_rejects_non_monday(teacher):
    with pytest.raises(services.ScheduleError):
        services.replace_week(teacher.id, MON + dt.timedelta(days=1), {})


def test_clear_override(teacher):
    AvailabilityOverride.objects.create(teacher=teacher, date=MON)
    services.clear_override(teacher.id, MON)
    assert not AvailabilityOverride.objects.exists()


def test_clear_override_past_rejected(teacher, monkeypatch):
    monkeypatch.setattr(services, '_today', lambda: dt.date(2030, 2, 1))
    with pytest.raises(services.ScheduleError):
        services.clear_override(teacher.id, MON)


def test_archived_teacher_cannot_be_edited(teacher):
    teacher.active = False
    teacher.save(update_fields=['active'])
    with pytest.raises(services.ScheduleError):
        services.replace_template(teacher.id, {})


def test_upcoming_overrides(teacher):
    AvailabilityOverride.objects.create(teacher=teacher, date=dt.date(2029, 12, 1))  # прошлое
    AvailabilityOverride.objects.create(teacher=teacher, date=MON)
    AvailabilityOverride.objects.create(teacher=teacher, date=SUN, start_time=T(10), end_time=T(11))
    assert services.upcoming_overrides(teacher.id) == [
        {'date': MON, 'intervals': []},
        {'date': SUN, 'intervals': [(T(10), T(11))]},
    ]


def test_windows_payload_none_without_schedule(teacher):
    assert services.windows_payload(teacher.id, MON, SUN) is None
    AvailabilityRule.objects.create(teacher=teacher, day_of_week=1, start_time=T(10), end_time=T(14))
    payload = services.windows_payload(teacher.id, MON, SUN)
    assert payload['2030-01-07'] == [['10:00', '14:00']]
    assert payload['2030-01-13'] == []
```

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest apps/availability/tests/test_services.py -q` → FAIL (`ImportError`/`AttributeError`).

- [ ] **Step 3: services.py**

```python
"""
Доменный сервис графика работы преподавателя.

Итоговые окна = недельный шаблон, поверх которого применены исключения на даты
(исключение целиком заменяет день). Сохранения меняют только реально
изменившиеся дни — журнал изменений (pghistory) не засоряется. Параллельные
сохранения одного преподавателя сериализуются SELECT … FOR UPDATE его строки.

След мутаций — «Журнал изменений» (pghistory), НЕ log_event: журнал ИБ — для
событий безопасности (конвенция apps.scheduling).
"""
from __future__ import annotations

import datetime
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from apps.availability.models import AvailabilityOverride, AvailabilityRule
from apps.teachers.models import Teacher

Interval = tuple[datetime.time, datetime.time]


class ScheduleError(Exception):
    """Нарушение правила графика — вьюха отдаёт 400 с текстом."""


def _today() -> datetime.date:
    # Локальная дата по TIME_ZONE (Europe/Moscow). Отдельная функция — подмена в тестах.
    return timezone.localdate()


def js_weekday(d: datetime.date) -> int:
    """Python Пн=0 → конвенция проекта Вс=0 (JS getDay)."""
    return (d.weekday() + 1) % 7


def normalize(intervals: list[Interval]) -> list[Interval]:
    """Сортировка + склейка пересекающихся и соприкасающихся интервалов."""
    merged: list[list[datetime.time]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def fmt(t: datetime.time) -> str:
    return t.strftime('%H:%M')


def has_schedule(teacher_id: int) -> bool:
    return (AvailabilityRule.objects.filter(teacher_id=teacher_id).exists()
            or AvailabilityOverride.objects.filter(teacher_id=teacher_id).exists())


def get_template(teacher_id: int) -> dict[int, list[Interval]]:
    """Шаблон {day_of_week: [интервалы]}; дни без окон в словарь не попадают."""
    out: dict[int, list[Interval]] = defaultdict(list)
    rows = (AvailabilityRule.objects.filter(teacher_id=teacher_id)
            .order_by('day_of_week', 'start_time')
            .values_list('day_of_week', 'start_time', 'end_time'))
    for dow, s, e in rows:
        out[dow].append((s, e))
    return dict(out)


def _overrides_by_date(teacher_id: int, d_from: datetime.date,
                       d_to: datetime.date | None) -> dict[datetime.date, list[Interval]]:
    """{дата: интервалы} для дат с исключением; [] = день закрыт."""
    qs = AvailabilityOverride.objects.filter(teacher_id=teacher_id, date__gte=d_from)
    if d_to is not None:
        qs = qs.filter(date__lte=d_to)
    out: dict[datetime.date, list[Interval]] = {}
    for d, s, e in qs.order_by('date', 'start_time').values_list('date', 'start_time', 'end_time'):
        day = out.setdefault(d, [])
        if s is not None:
            day.append((s, e))
    return out


def get_effective_windows(teacher_id: int, d_from: datetime.date,
                          d_to: datetime.date) -> dict[datetime.date, list[Interval]]:
    """Итоговые окна на каждую дату [d_from, d_to]. Два запроса, без N+1."""
    template = get_template(teacher_id)
    overrides = _overrides_by_date(teacher_id, d_from, d_to)
    result: dict[datetime.date, list[Interval]] = {}
    d = d_from
    while d <= d_to:
        result[d] = overrides[d] if d in overrides else list(template.get(js_weekday(d), []))
        d += datetime.timedelta(days=1)
    return result


def override_dates(teacher_id: int, d_from: datetime.date, d_to: datetime.date) -> list[datetime.date]:
    return sorted(_overrides_by_date(teacher_id, d_from, d_to).keys())


def upcoming_overrides(teacher_id: int) -> list[dict]:
    """Исключения с сегодняшнего дня — для сводки в редакторе."""
    by_date = _overrides_by_date(teacher_id, _today(), None)
    return [{'date': d, 'intervals': ivs} for d, ivs in sorted(by_date.items())]


def windows_payload(teacher_id: int, d_from: datetime.date, d_to: datetime.date) -> dict | None:
    """JSON-форма итоговых окон для календаря; None — графика нет (фон не рисуем)."""
    if not has_schedule(teacher_id):
        return None
    return {
        d.isoformat(): [[fmt(s), fmt(e)] for s, e in ivs]
        for d, ivs in get_effective_windows(teacher_id, d_from, d_to).items()
    }


def _lock_active_teacher(teacher_id: int) -> Teacher:
    """Блокирует строку преподавателя до конца транзакции. DoesNotExist пробрасывается (→404)."""
    teacher = Teacher.objects.select_for_update().get(pk=teacher_id)
    if not teacher.active:
        raise ScheduleError('Преподаватель в архиве — график только для просмотра.')
    return teacher


@transaction.atomic
def replace_template(teacher_id: int, by_day: dict[int, list[Interval]]) -> None:
    """Заменить шаблон целиком. Отсутствующий день = закрыт. Переписываются только изменившиеся дни."""
    _lock_active_teacher(teacher_id)
    current = get_template(teacher_id)
    for dow in range(7):
        wanted = normalize(by_day.get(dow, []))
        if wanted == current.get(dow, []):
            continue
        AvailabilityRule.objects.filter(teacher_id=teacher_id, day_of_week=dow).delete()
        AvailabilityRule.objects.bulk_create([
            AvailabilityRule(teacher_id=teacher_id, day_of_week=dow, start_time=s, end_time=e)
            for s, e in wanted
        ])


@transaction.atomic
def replace_week(teacher_id: int, monday: datetime.date,
                 days: dict[datetime.date, list[Interval]]) -> None:
    """
    Сохранить конкретную неделю: день, совпавший с шаблоном, — без исключения;
    отличающийся — исключение (пустой → «закрыт»). Прошлые даты — отказ.
    """
    if monday.weekday() != 0:
        raise ScheduleError('monday должен быть понедельником.')
    week_end = monday + datetime.timedelta(days=6)
    today = _today()
    for d in days:
        if not (monday <= d <= week_end):
            raise ScheduleError(f'Дата {d.isoformat()} вне недели {monday.isoformat()}.')
        if d < today:
            raise ScheduleError(f'Дата {d.isoformat()} уже прошла — её нельзя менять.')
    _lock_active_teacher(teacher_id)
    template = get_template(teacher_id)
    existing = _overrides_by_date(teacher_id, monday, week_end)
    for d, raw in days.items():
        wanted = normalize(raw)
        follows_template = wanted == template.get(js_weekday(d), [])
        if follows_template and d not in existing:
            continue
        if not follows_template and existing.get(d) == wanted:
            continue
        AvailabilityOverride.objects.filter(teacher_id=teacher_id, date=d).delete()
        if follows_template:
            continue
        if not wanted:
            AvailabilityOverride.objects.create(teacher_id=teacher_id, date=d)
        else:
            AvailabilityOverride.objects.bulk_create([
                AvailabilityOverride(teacher_id=teacher_id, date=d, start_time=s, end_time=e)
                for s, e in wanted
            ])


@transaction.atomic
def clear_override(teacher_id: int, d: datetime.date) -> None:
    """Сбросить дату к шаблону."""
    if d < _today():
        raise ScheduleError(f'Дата {d.isoformat()} уже прошла — её нельзя менять.')
    _lock_active_teacher(teacher_id)
    AvailabilityOverride.objects.filter(teacher_id=teacher_id, date=d).delete()
```

- [ ] **Step 4: Прогон**

Run: `pytest apps/availability -q` → PASS.

---

### Task 3: API (teacher + admin), маршруты, метки журнала

**Агент:** backend-django

**Files:**
- Create: `journal_django/apps/availability/{serializers,views,urls,admin_urls}.py`, `tests/test_api.py`
- Modify: `journal_django/config/urls.py`, `apps/changelog/labels.py`, `frontend/admin-src/src/lib/labels.ts` (карта операций, рядом с `'cancellation_reason.create'`)

- [ ] **Step 1: Падающие API-тесты (test_api.py)**

```python
import datetime as dt

import pytest

from apps.availability import services
from apps.availability.models import AvailabilityOverride, AvailabilityRule

pytestmark = pytest.mark.django_db
T = dt.time
FULL_WEEK = {str(i): [] for i in range(7)}


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    monkeypatch.setattr(services, '_today', lambda: dt.date(2030, 1, 1))


def _admin_base(teacher_id):
    return f'/api/admin/teachers/{teacher_id}/schedule'


class TestAuth:
    def test_anon_401(self, anon_client):
        assert anon_client.get('/api/schedule/template').status_code == 401

    def test_manager_cannot_use_teacher_endpoint(self, manager_client):
        assert manager_client.get('/api/schedule/template').status_code == 403

    def test_teacher_cannot_use_admin_endpoint(self, own_teacher_client, teacher):
        assert own_teacher_client.get(_admin_base(teacher.id) + '/template').status_code == 403

    @pytest.mark.parametrize('fixture', ['manager_client', 'admin_client', 'superadmin_client'])
    def test_staff_can_edit(self, request, fixture, teacher):
        client = request.getfixturevalue(fixture)
        r = client.put(_admin_base(teacher.id) + '/template',
                       {'days': {**FULL_WEEK, '1': [['10:00', '14:00']]}}, format='json')
        assert r.status_code == 200, r.content
        assert AvailabilityRule.objects.filter(teacher=teacher).count() == 1


def test_teacher_edits_only_own_schedule(own_teacher_client, teacher, other_teacher):
    r = own_teacher_client.put('/api/schedule/template',
                               {'days': {**FULL_WEEK, '3': [['15:00', '20:00']]}}, format='json')
    assert r.status_code == 200
    assert AvailabilityRule.objects.filter(teacher=teacher, day_of_week=3).exists()
    assert not AvailabilityRule.objects.filter(teacher=other_teacher).exists()


def test_template_get_shape(own_teacher_client, teacher):
    AvailabilityRule.objects.create(teacher=teacher, day_of_week=1, start_time=T(10), end_time=T(14))
    AvailabilityOverride.objects.create(teacher=teacher, date=dt.date(2030, 1, 7))
    body = own_teacher_client.get('/api/schedule/template').json()
    assert body['days']['1'] == [['10:00', '14:00']]
    assert body['days']['0'] == []
    assert set(body['days']) == {str(i) for i in range(7)}
    assert body['upcoming_overrides'] == [{'date': '2030-01-07', 'intervals': []}]


@pytest.mark.parametrize('bad', [
    [['10:15', '11:00']], [['07:30', '09:00']], [['21:00', '22:30']], [['12:00', '11:00']], [['10:00']],
])
def test_template_validation(own_teacher_client, bad):
    r = own_teacher_client.put('/api/schedule/template', {'days': {**FULL_WEEK, '1': bad}}, format='json')
    assert r.status_code == 400


def test_template_bad_day_key(own_teacher_client):
    r = own_teacher_client.put('/api/schedule/template', {'days': {'7': []}}, format='json')
    assert r.status_code == 400


def test_range_get(own_teacher_client, teacher):
    AvailabilityRule.objects.create(teacher=teacher, day_of_week=1, start_time=T(10), end_time=T(14))
    AvailabilityOverride.objects.create(teacher=teacher, date=dt.date(2030, 1, 8))
    body = own_teacher_client.get('/api/schedule?from=2030-01-07&to=2030-01-13').json()
    assert body['has_schedule'] is True
    assert body['windows']['2030-01-07'] == [['10:00', '14:00']]
    assert body['windows']['2030-01-08'] == []
    assert body['override_dates'] == ['2030-01-08']


def test_range_requires_params(own_teacher_client):
    assert own_teacher_client.get('/api/schedule').status_code == 400


def test_week_put_and_override_delete(own_teacher_client, teacher):
    r = own_teacher_client.put('/api/schedule/week', {
        'monday': '2030-01-07', 'days': {'2030-01-07': [['16:00', '18:00']]},
    }, format='json')
    assert r.status_code == 200, r.content
    assert AvailabilityOverride.objects.filter(teacher=teacher, date=dt.date(2030, 1, 7)).count() == 1
    r = own_teacher_client.delete('/api/schedule/overrides/2030-01-07')
    assert r.status_code == 204
    assert not AvailabilityOverride.objects.filter(teacher=teacher).exists()


def test_week_past_date_400(own_teacher_client, monkeypatch):
    monkeypatch.setattr(services, '_today', lambda: dt.date(2030, 1, 9))
    r = own_teacher_client.put('/api/schedule/week',
                               {'monday': '2030-01-07', 'days': {'2030-01-07': []}}, format='json')
    assert r.status_code == 400
    assert 'прошла' in r.json()['error']


def test_override_delete_bad_date_400(own_teacher_client):
    assert own_teacher_client.delete('/api/schedule/overrides/not-a-date').status_code == 400


def test_admin_unknown_teacher_404(admin_client):
    assert admin_client.get(_admin_base(2_000_000_000) + '/template').status_code == 404


def test_archived_teacher_read_only(admin_client, teacher):
    teacher.active = False
    teacher.save(update_fields=['active'])
    assert admin_client.get(_admin_base(teacher.id) + '/template').status_code == 200
    r = admin_client.put(_admin_base(teacher.id) + '/template', {'days': FULL_WEEK}, format='json')
    assert r.status_code == 400
```

Run: `pytest apps/availability/tests/test_api.py -q` → FAIL (404 на маршрутах).

- [ ] **Step 2: serializers.py**

```python
"""Валидация входа графика работы: 'HH:MM', шаг 30 мин, 08:00–22:00, start < end."""
from __future__ import annotations

import datetime
import re

from rest_framework import serializers

from apps.availability.models import GRID_END, GRID_START

_HHMM = re.compile(r'^([01]\d|2[0-3]):(00|30)$')


def _parse_hhmm(value: str) -> datetime.time:
    if not isinstance(value, str) or not _HHMM.match(value):
        raise serializers.ValidationError(f'Время «{value}» — формат HH:MM с шагом 30 минут.')
    h, m = value.split(':')
    return datetime.time(int(h), int(m))


class IntervalListField(serializers.Field):
    """[['10:00','14:00'], …] → [(time, time), …]."""

    def to_internal_value(self, data):
        if not isinstance(data, list):
            raise serializers.ValidationError('Ожидается список интервалов.')
        out = []
        for item in data:
            if not isinstance(item, list) or len(item) != 2:
                raise serializers.ValidationError('Интервал — пара [начало, конец].')
            start, end = _parse_hhmm(item[0]), _parse_hhmm(item[1])
            if start < GRID_START or end > GRID_END:
                raise serializers.ValidationError('Окна — в пределах 08:00–22:00.')
            if start >= end:
                raise serializers.ValidationError('Начало окна должно быть раньше конца.')
            out.append((start, end))
        return out

    def to_representation(self, value):  # pragma: no cover — только вход
        return value


class TemplateSerializer(serializers.Serializer):
    days = serializers.DictField(child=IntervalListField())

    def validate_days(self, value):
        out = {}
        for key, intervals in value.items():
            if key not in {str(i) for i in range(7)}:
                raise serializers.ValidationError(f'День недели «{key}» — ожидается 0–6 (Вс=0).')
            out[int(key)] = intervals
        return out


class WeekSerializer(serializers.Serializer):
    monday = serializers.DateField()
    days = serializers.DictField(child=IntervalListField())

    def validate_days(self, value):
        out = {}
        for key, intervals in value.items():
            try:
                out[datetime.date.fromisoformat(key)] = intervals
            except ValueError:
                raise serializers.ValidationError(f'Дата «{key}» — ожидается YYYY-MM-DD.')
        return out
```

- [ ] **Step 3: views.py**

```python
"""
API графика работы. Общие базовые классы + два скоупа:
- teacher (/api/schedule/…, IsTeacher) — преподаватель ТОЛЬКО из учётки;
- admin (/api/admin/teachers/<id>/schedule/…, IsManagerOrAdmin).
Мутации требуют X-CSRFToken (cookie-JWT), @csrf_exempt не ставим.
"""
from __future__ import annotations

import datetime

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.availability import services
from apps.availability.serializers import TemplateSerializer, WeekSerializer
from apps.core.permissions import IsManagerOrAdmin, IsTeacher
from apps.scheduling.views import _parse_window
from apps.teachers.models import Teacher


def _ivs(intervals):
    return [[services.fmt(s), services.fmt(e)] for s, e in intervals]


def _error(exc: Exception) -> Response:
    return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class _TeacherScope:
    permission_classes = [IsTeacher]

    def teacher_id(self, request: Request, kwargs) -> int:
        return request.user.teacher_id


class _AdminScope:
    permission_classes = [IsManagerOrAdmin]

    def teacher_id(self, request: Request, kwargs) -> int:
        teacher_id = kwargs['teacher_id']
        if not Teacher.objects.filter(pk=teacher_id).exists():
            raise NotFound('Преподаватель не найден.')
        return teacher_id


class _TemplateView(APIView):
    def get(self, request: Request, **kwargs) -> Response:
        tid = self.teacher_id(request, kwargs)
        template = services.get_template(tid)
        return Response({
            'days': {str(d): _ivs(template.get(d, [])) for d in range(7)},
            'upcoming_overrides': [
                {'date': o['date'].isoformat(), 'intervals': _ivs(o['intervals'])}
                for o in services.upcoming_overrides(tid)
            ],
        })

    def put(self, request: Request, **kwargs) -> Response:
        tid = self.teacher_id(request, kwargs)
        ser = TemplateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            services.replace_template(tid, ser.validated_data['days'])
        except services.ScheduleError as exc:
            return _error(exc)
        return self.get(request, **kwargs)


class _RangeView(APIView):
    def get(self, request: Request, **kwargs) -> Response:
        tid = self.teacher_id(request, kwargs)
        window = _parse_window(request)
        if isinstance(window, Response):
            return window
        d_from, d_to = window
        windows = services.get_effective_windows(tid, d_from, d_to)
        return Response({
            'has_schedule': services.has_schedule(tid),
            'windows': {d.isoformat(): _ivs(ivs) for d, ivs in windows.items()},
            'override_dates': [d.isoformat() for d in services.override_dates(tid, d_from, d_to)],
        })


class _WeekView(APIView):
    def put(self, request: Request, **kwargs) -> Response:
        tid = self.teacher_id(request, kwargs)
        ser = WeekSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            services.replace_week(tid, ser.validated_data['monday'], ser.validated_data['days'])
        except services.ScheduleError as exc:
            return _error(exc)
        return Response({'ok': True})


class _OverrideView(APIView):
    def delete(self, request: Request, date: str, **kwargs) -> Response:
        tid = self.teacher_id(request, kwargs)
        try:
            d = datetime.date.fromisoformat(date)
        except ValueError:
            return Response({'error': 'Дата — YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            services.clear_override(tid, d)
        except services.ScheduleError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TeacherTemplateView(_TeacherScope, _TemplateView):
    permission_classes = [IsTeacher]


class TeacherRangeView(_TeacherScope, _RangeView):
    permission_classes = [IsTeacher]


class TeacherWeekView(_TeacherScope, _WeekView):
    permission_classes = [IsTeacher]


class TeacherOverrideView(_TeacherScope, _OverrideView):
    permission_classes = [IsTeacher]


class AdminTemplateView(_AdminScope, _TemplateView):
    permission_classes = [IsManagerOrAdmin]


class AdminRangeView(_AdminScope, _RangeView):
    permission_classes = [IsManagerOrAdmin]


class AdminWeekView(_AdminScope, _WeekView):
    permission_classes = [IsManagerOrAdmin]


class AdminOverrideView(_AdminScope, _OverrideView):
    permission_classes = [IsManagerOrAdmin]
```

(`permission_classes` продублирован на конкретных классах намеренно — правило проекта «каждая вьюха явно задаёт пермишены».)

- [ ] **Step 4: urls.py / admin_urls.py**

```python
# apps/availability/urls.py — монтируется на 'api/schedule'
from django.urls import path

from apps.availability import views

urlpatterns = [
    path('', views.TeacherRangeView.as_view(), name='schedule-range'),
    path('/template', views.TeacherTemplateView.as_view(), name='schedule-template'),
    path('/week', views.TeacherWeekView.as_view(), name='schedule-week'),
    path('/overrides/<str:date>', views.TeacherOverrideView.as_view(), name='schedule-override'),
]
```

```python
# apps/availability/admin_urls.py — монтируется на 'api/admin/teachers/<int:teacher_id>/schedule'
from django.urls import path

from apps.availability import views

urlpatterns = [
    path('', views.AdminRangeView.as_view(), name='admin-schedule-range'),
    path('/template', views.AdminTemplateView.as_view(), name='admin-schedule-template'),
    path('/week', views.AdminWeekView.as_view(), name='admin-schedule-week'),
    path('/overrides/<str:date>', views.AdminOverrideView.as_view(), name='admin-schedule-override'),
]
```

`config/urls.py`:
- непосредственно **перед** `path('api/admin/teachers', include('apps.teachers.urls')),`:
```python
    # График работы преподавателя (admin, manager/admin/superadmin) — до общего teachers-include
    path('api/admin/teachers/<int:teacher_id>/schedule', include('apps.availability.admin_urls')),
```
- непосредственно **перед** `path('api', include('apps.teacher_spa.urls')),`:
```python
    # График работы — кабинет преподавателя (/api/schedule, role=teacher); до общего /api
    path('api/schedule', include('apps.availability.urls')),
```

- [ ] **Step 5: Метки журнала**

`apps/changelog/labels.py` — в `RULES`, перед блоком `# справочники`:
```python
    # График работы преподавателя (admin и кабинет преподавателя)
    ('PUT', re.compile(r'^/api/admin/teachers/\d+/schedule/template$'), 'schedule.template'),
    ('PUT', re.compile(r'^/api/admin/teachers/\d+/schedule/week$'), 'schedule.week'),
    ('DELETE', re.compile(r'^/api/admin/teachers/\d+/schedule/overrides/[^/]+$'), 'schedule.override_clear'),
    ('PUT', re.compile(r'^/api/schedule/template$'), 'schedule.template'),
    ('PUT', re.compile(r'^/api/schedule/week$'), 'schedule.week'),
    ('DELETE', re.compile(r'^/api/schedule/overrides/[^/]+$'), 'schedule.override_clear'),
```
`frontend/admin-src/src/lib/labels.ts` — в карту операций рядом с `'cancellation_reason.create'`:
```ts
  'schedule.template':        'График работы: шаблон недели',
  'schedule.week':            'График работы: изменения недели',
  'schedule.override_clear':  'График работы: сброс дня к шаблону',
```

- [ ] **Step 6: Прогон**

Run: `pytest apps/availability apps/changelog -q` → PASS.

---

### Task 4: Поле `availability` в календарных эндпоинтах

**Агент:** backend-django

**Files:**
- Modify: `journal_django/apps/scheduling/views.py` (`CalendarView.get`, `AdminCalendarView.get`)
- Create: `journal_django/apps/availability/tests/test_calendar_availability.py`

- [ ] **Step 1: Падающие тесты**

```python
import datetime as dt

import pytest

from apps.availability.models import AvailabilityRule

pytestmark = pytest.mark.django_db
WIN = '?from=2030-01-07&to=2030-01-13'


def test_teacher_calendar_has_availability(own_teacher_client, teacher):
    assert own_teacher_client.get('/api/calendar' + WIN).json()['availability'] is None
    AvailabilityRule.objects.create(teacher=teacher, day_of_week=1,
                                    start_time=dt.time(10), end_time=dt.time(14))
    body = own_teacher_client.get('/api/calendar' + WIN).json()
    assert body['availability']['2030-01-07'] == [['10:00', '14:00']]


def test_admin_calendar_availability_only_for_one_teacher(admin_client, teacher):
    AvailabilityRule.objects.create(teacher=teacher, day_of_week=1,
                                    start_time=dt.time(10), end_time=dt.time(14))
    assert admin_client.get('/api/admin/calendar' + WIN).json()['availability'] is None
    body = admin_client.get(f'/api/admin/calendar{WIN}&teacher_id={teacher.id}').json()
    assert body['availability']['2030-01-07'] == [['10:00', '14:00']]
```

Run: `pytest apps/availability/tests/test_calendar_availability.py -q` → FAIL (`KeyError: 'availability'`).

- [ ] **Step 2: Реализация**

В `apps/scheduling/views.py`, добавить импорт `from apps.availability import services as availability_services` и:
- в `CalendarView.get` перед `return Response(result)`:
```python
        # Фон «график работы» (белое/серое); None — графика нет.
        result['availability'] = availability_services.windows_payload(
            request.user.teacher_id, d_from, d_to)
```
- в `AdminCalendarView.get` перед `return Response(result)`:
```python
        # Фон графика — только для одного преподавателя: окна разных людей не накладываются.
        result['availability'] = (
            availability_services.windows_payload(teacher_id, d_from, d_to)
            if teacher_id is not None else None
        )
```
Обновить docstring модуля: в контракте ответа `{ occurrences, unscheduled, window, availability }`.

- [ ] **Step 3: Прогон**

Run: `pytest apps/availability apps/scheduling -q` → PASS.

---

### Task 5: Общие типы, сеточная математика и хуки (frontend)

**Агент:** frontend-design

**Files:**
- Create: `frontend/admin-src/src/shared/availability/types.ts`, `grid.ts`, `useSchedule.ts`
- Modify: `frontend/admin-src/src/shared/calendar/types.ts` (`CalendarResponse`), `frontend/teacher-src/src/lib/types.ts` (тот же интерфейс, если он там свой)

- [ ] **Step 1: types.ts**

```ts
/** Интервал окна графика: ['HH:MM', 'HH:MM'], шаг 30 мин, 08:00–22:00. */
export type Interval = [string, string];

/** GET …/schedule/template */
export interface ScheduleTemplate {
  /** Ключи '0'…'6', конвенция Вс=0 (JS getDay). */
  days: Record<string, Interval[]>;
  /** Исключения с сегодняшнего дня; intervals: [] — день закрыт. */
  upcoming_overrides: { date: string; intervals: Interval[] }[];
}

/** GET …/schedule?from=&to= */
export interface ScheduleRange {
  has_schedule: boolean;
  windows: Record<string, Interval[]>;   // 'YYYY-MM-DD' → окна
  override_dates: string[];
}

/** Поле availability ответа календаря: null — графика нет / не один преподаватель. */
export type AvailabilityWindows = Record<string, Interval[]> | null;
```

В `shared/calendar/types.ts` в `CalendarResponse` добавить `availability?: AvailabilityWindows;` (импорт типа из `../availability/types`); то же поле — в teacher `lib/types.ts`, если `CalendarResponse` объявлен там отдельно.

- [ ] **Step 2: grid.ts (чистые функции)**

```ts
import type { Interval } from './types';

export const GRID_START_MIN = 8 * 60;
export const SLOT_MIN = 30;
export const SLOT_COUNT = 28;                    // 08:00–22:00
/** Порядок колонок сетки Пн…Вс → day_of_week (Вс=0). */
export const WEEK_DOW = [1, 2, 3, 4, 5, 6, 0] as const;
export const DOW_SHORT: Record<number, string> = { 0: 'Вс', 1: 'Пн', 2: 'Вт', 3: 'Ср', 4: 'Чт', 5: 'Пт', 6: 'Сб' };

export function slotLabel(i: number): string {
  const m = GRID_START_MIN + i * SLOT_MIN;
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
}

function toMin(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 60 + m;
}

/** Интервалы → маска 28 слотов. */
export function intervalsToSlots(ivs: Interval[]): boolean[] {
  const slots = Array<boolean>(SLOT_COUNT).fill(false);
  for (const [s, e] of ivs) {
    const from = Math.max(0, (toMin(s) - GRID_START_MIN) / SLOT_MIN);
    const to = Math.min(SLOT_COUNT, (toMin(e) - GRID_START_MIN) / SLOT_MIN);
    for (let i = from; i < to; i++) slots[i] = true;
  }
  return slots;
}

/** Маска → склеенные интервалы. */
export function slotsToIntervals(slots: boolean[]): Interval[] {
  const out: Interval[] = [];
  let start = -1;
  for (let i = 0; i <= SLOT_COUNT; i++) {
    const on = i < SLOT_COUNT && slots[i];
    if (on && start < 0) start = i;
    if (!on && start >= 0) { out.push([slotLabel(start), slotLabel(i)]); start = -1; }
  }
  return out;
}

export function sameSlots(a: boolean[], b: boolean[]): boolean {
  return a.every((v, i) => v === b[i]);
}

export function formatIntervals(ivs: Interval[]): string {
  return ivs.length ? ivs.map(([s, e]) => `${s}–${e}`).join(', ') : 'выходной';
}

/** Сумма часов по маскам (для «Итого N ч/нед»). */
export function totalHours(masks: boolean[][]): number {
  return masks.reduce((acc, m) => acc + m.filter(Boolean).length, 0) * SLOT_MIN / 60;
}
```

- [ ] **Step 3: useSchedule.ts**

`basePath` — `'/api/schedule'` (teacher) или `` `/api/admin/teachers/${id}/schedule` `` (admin). `api` импортировать так же, как `shared/calendar` его получает (`'../../lib/api'` в admin-src — teacher подтягивает его через alias).

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../lib/api';
import type { Interval, ScheduleRange, ScheduleTemplate } from './types';

const key = (basePath: string) => ['schedule', basePath] as const;

export function useScheduleTemplate(basePath: string) {
  return useQuery<ScheduleTemplate>({
    queryKey: [...key(basePath), 'template'],
    queryFn: () => api<ScheduleTemplate>('GET', `${basePath}/template`),
  });
}

export function useScheduleRange(basePath: string, from: string, to: string, enabled: boolean) {
  return useQuery<ScheduleRange>({
    queryKey: [...key(basePath), 'range', from, to],
    queryFn: () => api<ScheduleRange>('GET', `${basePath}?from=${from}&to=${to}`),
    placeholderData: (prev) => prev,
    enabled,
  });
}

export function useScheduleMutations(basePath: string) {
  const qc = useQueryClient();
  const invalidate = () => Promise.all([
    qc.invalidateQueries({ queryKey: key(basePath) }),
    qc.invalidateQueries({ queryKey: ['calendar'] }),
    qc.invalidateQueries({ queryKey: ['admin-calendar'] }),
  ]);
  return {
    saveTemplate: useMutation({
      mutationFn: (days: Record<string, Interval[]>) => api('PUT', `${basePath}/template`, { days }),
      onSuccess: invalidate,
    }),
    saveWeek: useMutation({
      mutationFn: (p: { monday: string; days: Record<string, Interval[]> }) => api('PUT', `${basePath}/week`, p),
      onSuccess: invalidate,
    }),
    clearOverride: useMutation({
      mutationFn: (date: string) => api('DELETE', `${basePath}/overrides/${date}`),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Step 4: Проверка**

Run: `npm run typecheck` в `frontend/admin-src` и в `frontend/teacher-src` → 0 ошибок.

---

### Task 6: Компонент `ScheduleEditor` (сетка + сводка)

**Агент:** frontend-design

**Files:**
- Create: `frontend/admin-src/src/shared/availability/ScheduleEditor.tsx`, `schedule.css`

Контракт компонента (реализация — агент, по описанию ниже; без native form-элементов, только `<button>` и div-ячейки; все цвета/отступы/радиусы — токены; **каждый использованный токен должен существовать в обоих** `admin-src/src/styles/tokens.css` и `teacher-src/src/styles/tokens.css`, иначе добавить в оба):

```ts
export interface ScheduleEditorProps {
  /** '/api/schedule' | `/api/admin/teachers/${id}/schedule` */
  basePath: string;
  /** URL календаря для подсказки-уроков недели: (from, to) => string. */
  calendarUrl: (from: string, to: string) => string;
  /** Архивный преподаватель — только просмотр. */
  readOnly?: boolean;
}
export function ScheduleEditor(props: ScheduleEditorProps): JSX.Element;
```

- [ ] **Step 1: Состояние и данные**
- `mode: 'template' | 'week'`, `monday: Date` (по умолчанию текущий понедельник МСК — `currentMondayMsk()` из `shared/calendar/lib`), `draft: Record<colIndex 0..6, boolean[]> | null` (null = нет правок).
- База для сравнения: в режиме `template` — маски из `useScheduleTemplate(basePath).data.days[WEEK_DOW[c]]`; в режиме `week` — маски из `useScheduleRange(basePath, from, to, mode==='week').data.windows[дата колонки c]`.
- `dirty = draft != null && какая-либо колонка !sameSlots(draft[c], base[c])`.
- Уроки недели для подсказки (только `week`): `useQuery(['schedule-lessons', calendarUrl(from,to)], () => api<CalendarResponse>('GET', calendarUrl(from, to)))`, берём `occurrences` с `time`.

- [ ] **Step 2: Сетка**
- 8 колонок (`56px repeat(7, 1fr)`): гаттер с метками часов (`slotLabel(i)` на чётных i) + 7 дней Пн…Вс; заголовок колонки: день (`DOW_SHORT[WEEK_DOW[c]]`), в режиме `week` — ещё дата `dd.mm`, точка-маркер, если дата в `override_dates`, и кнопка «↺» (title «Вернуть к шаблону») для будущих дат с исключением → `clearOverride.mutate(date)`.
- 28 строк-ячеек на колонку: класс `sched-cell is-open` / `sched-cell`; ячейки прошлых дат в режиме `week` и всё при `readOnly` — класс `is-locked`, не реагируют.
- Закраска: `onPointerDown` на ячейке: если `e.pointerType === 'touch'` — переключить одну ячейку и выйти; иначе `paintValue = !current`, применить к ячейке, `setPointerCapture` не использовать (нужен `pointerenter` соседних ячеек), флаг `painting=true`. `onPointerEnter` при `painting` — применить `paintValue`. `pointerup`/`pointercancel` на `window` — `painting=false`. CSS сетки: `touch-action: pan-y; user-select: none`.
- В режиме `week` уроки рисуются поверх колонок абсолютными полупрозрачными блоками (`top = (минуты начала − 480) / 30 * ROW`, высота по `durationMinutes ?? 60`), `pointer-events: none` — не мешают закраске.

- [ ] **Step 3: Панель управления**
- Сегмент-переключатель «Шаблон недели | Конкретная неделя» (две `<button>` с `aria-pressed`), в режиме `week` — «‹ dd.mm–dd.mm ›».
- Смена режима/недели при `dirty` → подтверждение через `shared/calendar/Modal` («Есть несохранённые изменения. Сбросить их?» — «Сбросить» / «Остаться»).
- `useEffect` с `beforeunload` при `dirty` (снимать при `!dirty`/unmount).
- Кнопки «Сохранить» / «Отменить» видны только при `dirty`. Сохранить:
  - `template`: `saveTemplate.mutate(Object.fromEntries(WEEK_DOW.map((dow, c) => [String(dow), slotsToIntervals(draft[c])])))`;
  - `week`: `saveWeek.mutate({ monday: iso(monday), days })`, где `days` — только колонки с датой ≥ сегодня (МСК) — прошлые не отправлять (сервер ответит 400).
  - После успеха `draft = null`. Ошибка — текст `error` из ответа под кнопками.

- [ ] **Step 4: Сводка справа**
- Заголовок «Сводка»; строки по дням Пн…Вс: `DOW_SHORT — formatIntervals(...)` для текущего вида (черновик, если есть, иначе база).
- «Итого N ч/нед» — `totalHours`.
- Блок «Исключения»: `upcoming_overrides` из шаблона — `dd.mm (день) — formatIntervals(intervals)` (пустые → «выходной»), кнопка ✕ (`aria-label="Удалить исключение"`) → `clearOverride.mutate(date)`; при `readOnly` кнопок нет. Пусто → «Нет».
- Узкая ширина (< 900px): сводка уходит под сетку.

- [ ] **Step 5: Состояния**
- Загрузка — скелет высоты сетки; ошибка загрузки — «Не удалось загрузить график. Обновите страницу.»; `readOnly` — плашка «Преподаватель в архиве — график только для просмотра».

- [ ] **Step 6: Проверка**

Run: `npm run typecheck` в обоих SPA → 0 ошибок.

---

### Task 7: Страница «График работы» в teacher SPA

**Агент:** frontend-design

**Files:**
- Create: `frontend/teacher-src/src/pages/schedule/SchedulePage.tsx`
- Modify: `frontend/teacher-src/src/App.tsx`, `frontend/teacher-src/src/components/shell/TeacherShell.tsx`

- [ ] **Step 1: Страница**

```tsx
import { ScheduleEditor } from '@shared/shared/availability/ScheduleEditor';

/** «График работы» — окна, в которые преподавателю можно ставить уроки (белое/серое). */
export default function SchedulePage() {
  return (
    <div className="page">
      <h1 className="page-title">График работы</h1>
      <p className="page-sub">Отметьте время, когда вам можно ставить уроки. Шаблон повторяется каждую неделю; конкретную неделю можно поправить отдельно.</p>
      <ScheduleEditor
        basePath="/api/schedule"
        calendarUrl={(from, to) => `/api/calendar?from=${from}&to=${to}`}
      />
    </div>
  );
}
```
(Классы заголовка — взять те, что используют соседние страницы teacher SPA, например `PayrollPage`; не выдумывать новые.)

- [ ] **Step 2: Маршрут и меню**
- `App.tsx`: `const SchedulePage = lazy(() => import('./pages/schedule/SchedulePage'));` и `<Route path="/schedule" element={<SchedulePage />} />` после `/calendar`.
- `TeacherShell.tsx`: в `SECTIONS` после `calendar` — `{ key: 'schedule', label: 'График работы', path: '/schedule' }`; в `NAV_ICONS` добавить `schedule` — SVG 16×16 в стиле соседних (часы: `circle cx=12 cy=12 r=9.5` + стрелки `M12 7v5l3 2`).

- [ ] **Step 3: Проверка**

Run: `npm run typecheck` в `frontend/teacher-src` → 0 ошибок.

---

### Task 8: Вкладка «График работы» в карточке преподавателя (admin)

**Агент:** frontend-design

**Files:**
- Create: `frontend/admin-src/src/pages/teachers/TeacherScheduleTab.tsx`
- Modify: `frontend/admin-src/src/pages/teachers/TeacherDetailPage.tsx`, `frontend/admin-src/src/lib/permissions.ts`

- [ ] **Step 1: Право**

`lib/permissions.ts`, в блок «Операции над сущностями»:
```ts
// График работы преподавателя — manager/admin/superadmin (бэк: IsManagerOrAdmin).
export const canEditTeacherSchedule = (r?: Role | null) => r === 'manager' || isAdminUp(r);
```

- [ ] **Step 2: Вкладка**

```tsx
import { ScheduleEditor } from '../../shared/availability/ScheduleEditor';
import '../../shared/availability/schedule.css';
import type { Teacher } from '../../lib/types';

export default function TeacherScheduleTab({ teacher, canEdit }: { teacher: Teacher; canEdit: boolean }) {
  return (
    <ScheduleEditor
      basePath={`/api/admin/teachers/${teacher.id}/schedule`}
      calendarUrl={(from, to) => `/api/admin/calendar?teacher_id=${teacher.id}&from=${from}&to=${to}`}
      readOnly={!teacher.active || !canEdit}
    />
  );
}
```
(Если `schedule.css` уже импортируется внутри `ScheduleEditor.tsx` — импорт здесь убрать.)

- [ ] **Step 3: TeacherDetailPage**
- `TEACHER_TABS = ['overview', 'groups', 'schedule', 'data', 'history'] as const;`
- в `tabs` после `groups`:
```tsx
    {
      value: 'schedule',
      label: 'График работы',
      content: <TeacherScheduleTab teacher={teacher} canEdit={canEditTeacherSchedule(me?.role as Role)} />,
    },
```
- импорты `TeacherScheduleTab` и `canEditTeacherSchedule`.

- [ ] **Step 4: Проверка**

Run: `npm run typecheck` в `frontend/admin-src` → 0 ошибок.

---

### Task 9: Фон графика в календарях

**Агент:** frontend-design

**Files:**
- Modify: `frontend/admin-src/src/shared/calendar/WeekGrid.tsx`, `CalendarView.tsx`, `calendar.css`, `frontend/teacher-src/src/pages/calendar/CalendarPage.tsx`, `frontend/admin-src/src/pages/calendar/AdminCalendarPage.tsx`

- [ ] **Step 1: WeekGrid**
- Новый необязательный проп `availability?: AvailabilityWindows` (тип из `../availability/types`).
- Если `availability` не null/undefined: колонке дня добавить класс `has-availability` (фон — «закрыто»), внутри колонки **до** блоков уроков отрисовать `availability[isoDate(date)] ?? []` как `<div className="cal-avail" style={{ top: topPx(s), height: topPx(e) - topPx(s) }} aria-hidden />`. Для `e = '22:00'` `topPx` зажимает час до 21 — посчитать конец отдельно: `((toMin(e) - HOUR_START*60) / 60) * ROW_H`, без зажима.
- Без пропа — разметка и стили как сейчас (никаких регрессий).

- [ ] **Step 2: calendar.css**
```css
/* График работы: колонка с заданным графиком — «закрыто», окна — «открыто». */
.cal-col.has-availability { background: var(--bg4); }
.cal-avail { position: absolute; left: 0; right: 0; background: var(--bg2); pointer-events: none; }
```
(Проверить, что линии часов и `.cal-col.today` остаются видимыми поверх; токены — в обоих `tokens.css`.)

- [ ] **Step 3: CalendarView**
- Проп `availability?: AvailabilityWindows` → передать в `WeekGrid`.
- Пустое состояние: в недельном виде при `availability` (не null) и отсутствии уроков показывать `WeekGrid` (с фоном), а не «На этой неделе занятий нет.»

- [ ] **Step 4: Страницы календаря**
- teacher `CalendarPage.tsx`: `availability={data?.availability ?? null}`.
- admin `AdminCalendarPage.tsx`: `availability={data?.availability ?? null}` (бэк сам отдаёт null при «Все преподаватели»).

- [ ] **Step 5: Проверка**

Run: `npm run typecheck` в обоих SPA → 0 ошибок.

---

### Task 10: Финальная проверка

**Агенты:** координатор + review-agent + systems-analyst

- [ ] **Step 1:** `pytest -q` из `journal_django/` — **полный** прогон (не по приложениям). Падения сверить с базовой линией до фичи (инфраструктурные флаки — см. память о `test_journal_test`).
- [ ] **Step 2:** `npm run typecheck` в `frontend/admin-src` и `frontend/teacher-src`.
- [ ] **Step 3:** Ручная проверка в браузере (локальный nginx :8080): закраска мышью, тап на узкой ширине, сохранение шаблона, неделя с исключением, «↺», ✕ в сводке, фон в обоих календарях, архивный преподаватель read-only, manager видит вкладку и может править.
- [ ] **Step 4:** `systems-analyst` — сверка со спекой; `review-agent` — итоговое ревью всей фичи.
- [ ] **Step 5:** Обновить `CLAUDE.md` не требуется (новых инвариантов уровня проекта нет); память — статус фичи.

---

## Порядок коммитов (координатор)

После ревью каждой задачи — отдельный коммит только своих строк (surgical split для файлов с чужим WIP: `config/settings/base.py`, `config/urls.py`, `apps/changelog/*`, `apps/scheduling/views.py`, `lib/labels.ts` и др.). `admin-dist`/`teacher-dist` не коммитим. Пуш — только по просьбе владельца.
