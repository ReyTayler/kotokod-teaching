# Раздел «Продления» (CRM-пайплайн, Вариант 2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить в admin SPA раздел «Продления» — CRM-воронку продлений учеников с настраиваемыми стадиями, канбан-доской + списочным видом, автогенерацией сделок по циклам обучения, таймлайном активности, напоминаниями и аналитикой конверсии.

**Architecture:** Новое Django-приложение `apps/renewals/` (managed=True модели поверх Django-миграций) с 4 таблицами: `renewal_pipeline`, `renewal_stage` (конфигурируемые стадии), `renewal_deal` (сделка = ученик × направление × номер цикла), `renewal_activity` (таймлайн). Движок (`engine.py`) идемпотентно порождает/закрывает сделки по событиям посещаемости и оплат (Django signals + ночная management-команда самозаживления). Фронт — React 19 + TanStack Query v5, канбан на `@dnd-kit` с оптимистичными переходами. Всё под pghistory + changelog + RBAC `IsManagerOrAdmin`.

**Tech Stack:** Python 3 / Django 5.1 / DRF / PostgreSQL / django-pghistory · React 19 / TanStack Query v5 / React Router v7 / @dnd-kit / Recharts 3 · pytest / node --test.

---

## Инварианты, которые НЕЛЬЗЯ нарушать (чек-лист на каждый PR)

- [ ] Каждая DRF-вьюха задаёт `permission_classes`. Раздел — `IsManagerOrAdmin`; конфиг стадий — `ReadStaffWriteSuperAdmin`.
- [ ] Новые модели: `@pghistory.track(InsertEvent(), UpdateEvent(), DeleteEvent())` + запись в `apps/changelog/registry.py` + миграция pghistory-событий (`makemigrations`).
- [ ] Новые мутирующие URL → правила в `apps/changelog/labels.py` (иначе журнал пометит операцию `other`).
- [ ] Баланс/прогресс — **вычисляемые**, не хранимые (`purchased − attended` через `apps/finances`; прогресс из `memberships.lessons_done`, half-lesson 45мин=0.5).
- [ ] `Payment` не мутируем (только POST/DELETE) — сделка лишь отражает оплату.
- [ ] Список — server-pagination; фронт-хуки с `placeholderData: keepPreviousData`.
- [ ] Sort-dir: `(val==='asc'||val==='desc') ? val : default` в обоих местах (parse + paginate).
- [ ] Идемпотентность автогенерации: `UNIQUE(student_id, direction_id, cycle_no)`.
- [ ] Фронт: design tokens (`styles/tokens.css`), form-компоненты (`SelectInput/DateInput/Combobox`), enum-подписи из `lib/labels.ts`, `ErrorBoundary key={location.pathname}`, `.data-table--loading` гасит `pointer-events` только на `tbody`.
- [ ] Производительность (VPS 2CPU/2GB): точечные UPDATE по индексам, батчи в командах, лимит карточек на колонку + «Показать ещё».
- [ ] Секреты/ПДн не в `meta` аудита. Мутации шлют `X-CSRFToken`, без `@csrf_exempt`.

## Команды проекта (справочник)

- Тесты бэка: `cd journal_django && pytest -q` (или конкретный файл: `pytest apps/renewals/tests/test_engine.py -q`).
- Миграции: `cd journal_django && python manage.py makemigrations renewals` → `python manage.py migrate`.
- Ночная команда: `python manage.py rebuild_renewal_deals`.
- Сборка фронта: `cd journal_django/frontend/admin-src && npm run build`.
- Тип-чек фронта: `cd journal_django/frontend/admin-src && npm run typecheck` (или `tsc --noEmit`).

## Карта файлов

**Бэкенд — новое приложение `journal_django/apps/renewals/`:**
- `__init__.py`, `apps.py` — регистрация приложения
- `models.py` — `RenewalPipeline`, `RenewalStage`, `RenewalDeal`, `RenewalActivity`
- `cycle.py` — вычисление `cycle_no`, окна продления из memberships/finances
- `engine.py` — идемпотентная (пере)генерация/закрытие сделок, авто-переходы
- `transitions.py` — валидатор допустимых переходов стадий
- `repository.py` — board/list/get/move/patch/comment/analytics (ORM/SQL)
- `services.py` — тонкий слой + оркестрация
- `serializers.py` — сериализаторы сделок/стадий/активности/move/patch
- `views.py` — APIView с `permission_classes`
- `urls.py` — маршруты `/api/admin/renewals*`
- `signals.py` — реакция на `Payment`/`LessonAttendance`
- `analytics.py` — воронка конверсии, KPI
- `management/commands/rebuild_renewal_deals.py` — самозаживление
- `management/commands/send_renewal_reminders.py` — дайджест касаний
- `migrations/` — сгенерированные
- `tests/` — `conftest.py`, `test_models.py`, `test_cycle.py`, `test_engine.py`, `test_transitions.py`, `test_api_read.py`, `test_api_write.py`, `test_stages_api.py`, `test_analytics.py`

**Бэкенд — правки существующих:**
- `journal_django/config/settings/base.py` — добавить `apps.renewals` в `INSTALLED_APPS`
- `journal_django/config/urls.py` — `path('api/admin/renewals', include('apps.renewals.urls'))`
- `journal_django/apps/changelog/registry.py` — 4 записи TRACKED
- `journal_django/apps/changelog/labels.py` — правила мутирующих URL
- `journal_django/apps/changelog/humanize.py` / `summary.py` — подписи сущностей (если требуется явное имя)

**Фронт — новое (`journal_django/frontend/admin-src/src/`):**
- `hooks/useRenewals.ts`, `hooks/useRenewalStages.ts`, `hooks/useRenewalAnalytics.ts`
- `pages/renewals/RenewalsPage.tsx`, `RenewalBoard.tsx`, `RenewalColumn.tsx`, `RenewalCardView.tsx`, `RenewalList.tsx`, `RenewalDrawer.tsx`, `RenewalStagesSettings.tsx`, `RenewalAnalyticsPage.tsx`
- `lib/renewals.ts` — типы

**Фронт — правки:**
- `lib/permissions.ts` — `canSeeRenewals`
- `lib/labels.ts` — подписи стадий/операций/причин
- `components/shell/Sidebar.tsx` — пункт навигации + иконка
- `App.tsx` — роуты
- `package.json` — `@dnd-kit/core`, `@dnd-kit/sortable`

---

## ФАЗА 0. Скелет приложения, модели, миграции, регистрация в журнале

Цель фазы: рабочие таблицы + модели под pghistory + дефолтная воронка в БД + зелёный `test_registry_covers_all_tracked_models`.

### Task 0.1: Скелет приложения `apps/renewals/`

**Files:**
- Create: `journal_django/apps/renewals/__init__.py` (пустой)
- Create: `journal_django/apps/renewals/apps.py`
- Create: `journal_django/apps/renewals/migrations/__init__.py` (пустой)
- Create: `journal_django/apps/renewals/tests/__init__.py` (пустой)
- Modify: `journal_django/config/settings/base.py` (список `INSTALLED_APPS`)

- [ ] **Step 1: Создать `apps.py`**

```python
"""AppConfig для раздела «Продления»."""
from django.apps import AppConfig


class RenewalsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.renewals'
    label = 'renewals'

    def ready(self) -> None:
        # Подключаем сигналы при старте приложения (Payment/Attendance).
        from apps.renewals import signals  # noqa: F401
```

- [ ] **Step 2: Создать пустой `signals.py`-заглушку** (чтобы `ready()` не падал до Фазы 1)

```python
"""Сигналы раздела renewals. Наполняется в Фазе 1."""
```

- [ ] **Step 3: Зарегистрировать приложение**

В `config/settings/base.py` найти список `INSTALLED_APPS` и добавить строку `'apps.renewals',` рядом с прочими `apps.*` (после `apps.payments`/`apps.lessons` — порядок не критичен, но держим доменные вместе).

- [ ] **Step 4: Проверить, что Django видит приложение**

Run: `cd journal_django && python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals journal_django/config/settings/base.py
git commit -m "feat(renewals): скелет приложения renewals + регистрация"
```

### Task 0.2: Модели пайплайна и стадий

**Files:**
- Create: `journal_django/apps/renewals/models.py`
- Test: `journal_django/apps/renewals/tests/test_models.py`

- [ ] **Step 1: Написать модели пайплайна/стадии** (`models.py`, часть 1)

```python
"""
Модели раздела «Продления» — управляемые Django (managed=True), новые таблицы.

renewal_pipeline — воронка (обычно одна, is_default).
renewal_stage    — КОНФИГУРИРУЕМЫЕ стадии воронки (kind: progress/decision/won/lost).
renewal_deal     — сделка продления: ученик × направление × номер цикла.
renewal_activity — таймлайн: смена стадии, комментарий, привязка оплаты, системное.

Прогресс/баланс НЕ хранятся — вычисляются на чтении (см. repository/serializers).
"""
from __future__ import annotations

import pghistory
from django.db import models


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class RenewalPipeline(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.TextField()
    is_default = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'renewal_pipeline'
        constraints = [
            models.UniqueConstraint(
                fields=['is_default'],
                condition=models.Q(is_default=True),
                name='renewal_pipeline_one_default',
            ),
        ]


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class RenewalStage(models.Model):
    class Kind(models.TextChoices):
        PROGRESS = 'progress', 'Прогресс'   # авто-стадии «урок 1–4»
        DECISION = 'decision', 'Решение'    # ручные промежуточные
        WON = 'won', 'Продлён'              # терминальная-успех
        LOST = 'lost', 'Ушёл'               # терминальная-провал

    id = models.BigAutoField(primary_key=True)
    pipeline = models.ForeignKey(
        RenewalPipeline, on_delete=models.CASCADE,
        db_column='pipeline_id', related_name='stages',
    )
    key = models.TextField()                # стабильный машинный ключ для авто-правил
    label = models.TextField()
    color = models.TextField(null=True, blank=True)
    sort_order = models.IntegerField()
    kind = models.CharField(max_length=10, choices=Kind.choices)
    is_auto = models.BooleanField(default=False)  # двигается движком vs руками

    class Meta:
        managed = True
        db_table = 'renewal_stage'
        constraints = [
            models.UniqueConstraint(fields=['pipeline', 'key'], name='renewal_stage_pipeline_key_uq'),
            models.CheckConstraint(
                name='renewal_stage_kind_check',
                condition=models.Q(kind__in=['progress', 'decision', 'won', 'lost']),
            ),
            models.CheckConstraint(
                name='renewal_stage_color_check',
                condition=models.Q(color__isnull=True) | models.Q(color__regex=r'^#[0-9a-fA-F]{6}$'),
            ),
        ]
        indexes = [models.Index(fields=['pipeline', 'sort_order'], name='renewal_stage_order_idx')]
```

- [ ] **Step 2: Дописать `RenewalDeal` и `RenewalActivity`** (`models.py`, часть 2 — добавить в тот же файл)

```python
@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class RenewalDeal(models.Model):
    id = models.BigAutoField(primary_key=True)
    # RESTRICT — защищаем историю продлений от хард-удаления ученика/направления.
    student = models.ForeignKey(
        'students.Student', on_delete=models.RESTRICT,
        db_column='student_id', related_name='renewal_deals',
    )
    direction = models.ForeignKey(
        'directions.Direction', on_delete=models.RESTRICT,
        db_column='direction_id', related_name='renewal_deals',
    )
    cycle_no = models.IntegerField()
    pipeline = models.ForeignKey(
        RenewalPipeline, on_delete=models.RESTRICT,
        db_column='pipeline_id', related_name='deals',
    )
    stage = models.ForeignKey(
        RenewalStage, on_delete=models.RESTRICT,
        db_column='stage_id', related_name='deals',
    )
    # Ответственный менеджер. SET NULL — учётку могут удалить, сделку теряем нельзя.
    assignee = models.ForeignKey(
        'accounts.Account', on_delete=models.SET_NULL,
        db_column='assignee_id', related_name='renewal_deals',
        null=True, blank=True,
    )
    expected_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    next_touch_at = models.DateField(null=True, blank=True)
    reason_code = models.TextField(null=True, blank=True)
    stage_entered_at = models.DateTimeField(auto_now_add=True)
    outcome_at = models.DateTimeField(null=True, blank=True)  # NOT NULL ⇒ сделка закрыта
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = 'renewal_deal'
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'direction', 'cycle_no'],
                name='renewal_deal_cycle_uq',
            ),
        ]
        indexes = [
            models.Index(fields=['stage'], condition=models.Q(outcome_at__isnull=True),
                         name='renewal_deal_open_stage_idx'),
            models.Index(fields=['assignee'], name='renewal_deal_assignee_idx'),
            models.Index(fields=['student'], name='renewal_deal_student_idx'),
        ]


@pghistory.track(pghistory.InsertEvent(), pghistory.DeleteEvent())  # activity — лог, update не трекаем
class RenewalActivity(models.Model):
    class Kind(models.TextChoices):
        STAGE_CHANGE = 'stage_change', 'Смена стадии'
        COMMENT = 'comment', 'Комментарий'
        PAYMENT_LINKED = 'payment_linked', 'Оплата'
        SYSTEM = 'system', 'Система'

    id = models.BigAutoField(primary_key=True)
    deal = models.ForeignKey(
        RenewalDeal, on_delete=models.CASCADE,
        db_column='deal_id', related_name='activities',
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    from_stage = models.ForeignKey(
        RenewalStage, on_delete=models.SET_NULL, null=True, blank=True,
        db_column='from_stage_id', related_name='+',
    )
    to_stage = models.ForeignKey(
        RenewalStage, on_delete=models.SET_NULL, null=True, blank=True,
        db_column='to_stage_id', related_name='+',
    )
    payment = models.ForeignKey(
        'payments.Payment', on_delete=models.SET_NULL, null=True, blank=True,
        db_column='payment_id', related_name='+',
    )
    body = models.TextField(null=True, blank=True)
    author = models.ForeignKey(
        'accounts.Account', on_delete=models.SET_NULL, null=True, blank=True,
        db_column='author_id', related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'renewal_activity'
        indexes = [
            models.Index(fields=['deal', '-created_at'], name='renewal_activity_deal_idx'),
        ]
```

- [ ] **Step 3: Написать падающий тест на конфигурацию моделей**

Test: `journal_django/apps/renewals/tests/test_models.py`

```python
"""Проверяем, что модели renewals объявлены и корректно связаны."""
from __future__ import annotations

from apps.renewals.models import RenewalActivity, RenewalDeal, RenewalPipeline, RenewalStage


def test_tables_named_as_expected():
    assert RenewalPipeline._meta.db_table == 'renewal_pipeline'
    assert RenewalStage._meta.db_table == 'renewal_stage'
    assert RenewalDeal._meta.db_table == 'renewal_deal'
    assert RenewalActivity._meta.db_table == 'renewal_activity'


def test_deal_has_cycle_unique_constraint():
    names = {c.name for c in RenewalDeal._meta.constraints}
    assert 'renewal_deal_cycle_uq' in names


def test_stage_kinds():
    assert set(RenewalStage.Kind.values) == {'progress', 'decision', 'won', 'lost'}
```

- [ ] **Step 4: Запустить тест**

Run: `cd journal_django && pytest apps/renewals/tests/test_models.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals/models.py journal_django/apps/renewals/tests/test_models.py
git commit -m "feat(renewals): модели pipeline/stage/deal/activity под pghistory"
```

### Task 0.3: Миграции (таблицы + pghistory-события)

**Files:**
- Create: `journal_django/apps/renewals/migrations/0001_initial.py` (генерируется)

- [ ] **Step 1: Сгенерировать миграции**

Run: `cd journal_django && python manage.py makemigrations renewals`
Expected: создаётся `0001_initial.py` с `CreateModel` для 4 моделей **и** pghistory-события (`RenewalDealEvent`, `RenewalStageEvent`, `RenewalPipelineEvent`, `RenewalActivityEvent`).

- [ ] **Step 2: Проверить, что pghistory-события попали в миграцию**

Run: `grep -c "Event" journal_django/apps/renewals/migrations/0001_initial.py`
Expected: число > 0 (события трекинга сгенерированы). Если 0 — проверить, что `@pghistory.track` стоит на моделях.

- [ ] **Step 3: Применить миграции на тестовой БД**

Run: `cd journal_django && python manage.py migrate renewals`
Expected: `Applying renewals.0001_initial... OK`.

- [ ] **Step 4: Прогнать `manage.py check` и модельные тесты повторно с БД**

Run: `cd journal_django && pytest apps/renewals/tests/test_models.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals/migrations/0001_initial.py
git commit -m "feat(renewals): миграции таблиц + pghistory-события"
```

### Task 0.4: Сид дефолтной воронки (data-миграция)

**Files:**
- Create: `journal_django/apps/renewals/migrations/0002_seed_default_pipeline.py`
- Test: `journal_django/apps/renewals/tests/test_seed.py`

- [ ] **Step 1: Написать data-миграцию с дефолтными стадиями**

```python
"""Сид: дефолтная воронка + стадии (см. docs/renewals-plan.md §2.1)."""
from django.db import migrations

STAGES = [
    # (key, label, color, kind, is_auto)
    ('lesson_progress', 'Урок 1–4',      '#6366F1', 'progress', True),
    ('awaiting_payment', 'Ждём оплату',  '#F59E0B', 'decision', False),
    ('thinking',        'Думает',         '#3B82F6', 'decision', False),
    ('frozen',          'Заморожен',      '#64748B', 'decision', False),
    ('ignoring',        'Игнорит',        '#EF4444', 'decision', False),
    ('renewed',         'Продлён',        '#22C55E', 'won',      False),
    ('churned',         'Ушёл',           '#9CA3AF', 'lost',     False),
]


def seed(apps, schema_editor):
    Pipeline = apps.get_model('renewals', 'RenewalPipeline')
    Stage = apps.get_model('renewals', 'RenewalStage')
    pipe, _ = Pipeline.objects.get_or_create(is_default=True, defaults={'name': 'Продления'})
    for i, (key, label, color, kind, is_auto) in enumerate(STAGES):
        Stage.objects.get_or_create(
            pipeline=pipe, key=key,
            defaults={'label': label, 'color': color, 'sort_order': i,
                      'kind': kind, 'is_auto': is_auto},
        )


def unseed(apps, schema_editor):
    Stage = apps.get_model('renewals', 'RenewalStage')
    Pipeline = apps.get_model('renewals', 'RenewalPipeline')
    Stage.objects.all().delete()
    Pipeline.objects.filter(is_default=True).delete()


class Migration(migrations.Migration):
    dependencies = [('renewals', '0001_initial')]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 2: Применить и написать проверочный тест**

Run: `cd journal_django && python manage.py migrate renewals`
Expected: `Applying renewals.0002_seed_default_pipeline... OK`.

Test: `journal_django/apps/renewals/tests/test_seed.py`

```python
import pytest
from apps.renewals.models import RenewalPipeline, RenewalStage


@pytest.mark.django_db
def test_default_pipeline_seeded():
    pipe = RenewalPipeline.objects.get(is_default=True)
    stages = list(RenewalStage.objects.filter(pipeline=pipe).order_by('sort_order'))
    assert [s.key for s in stages][0] == 'lesson_progress'
    assert {s.kind for s in stages} >= {'progress', 'decision', 'won', 'lost'}
    assert next(s for s in stages if s.key == 'lesson_progress').is_auto is True
```

- [ ] **Step 3: Запустить тест**

Run: `cd journal_django && pytest apps/renewals/tests/test_seed.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add journal_django/apps/renewals/migrations/0002_seed_default_pipeline.py journal_django/apps/renewals/tests/test_seed.py
git commit -m "feat(renewals): сид дефолтной воронки и стадий"
```

### Task 0.5: Регистрация в журнале изменений (registry + labels)

**Files:**
- Modify: `journal_django/apps/changelog/registry.py` (словарь `TRACKED`)
- Modify: `journal_django/apps/changelog/labels.py` (список `RULES`)

- [ ] **Step 1: Добавить сущности в `registry.py`**

В словарь `TRACKED` добавить (topo: справочники воронки → сделки → активность):

```python
    'renewals.RenewalPipeline':  TrackedModel('renewal_pipeline', True, 12),
    'renewals.RenewalStage':     TrackedModel('renewal_stage', True, 14),
    'renewals.RenewalDeal':      TrackedModel('renewal_deal', True, 35),
    'renewals.RenewalActivity':  TrackedModel('renewal_activity', False, 55),
```

- [ ] **Step 2: Добавить правила меток в `labels.py`**

В список `RULES` добавить (более специфичные пути выше generic):

```python
    # renewals (продления)
    ('POST',  re.compile(r'^/api/admin/renewals/\d+/move$'), 'renewal.move'),
    ('POST',  re.compile(r'^/api/admin/renewals/\d+/comment$'), 'renewal.comment'),
    ('PATCH', re.compile(r'^/api/admin/renewals/\d+$'), 'renewal.update'),
    ('POST',  re.compile(r'^/api/admin/renewals/rebuild$'), 'renewal.rebuild'),
    ('POST',  re.compile(r'^/api/admin/renewals/stages$'), 'renewal.stage_create'),
    ('PATCH', re.compile(r'^/api/admin/renewals/stages/\d+$'), 'renewal.stage_update'),
    ('DELETE', re.compile(r'^/api/admin/renewals/stages/\d+$'), 'renewal.stage_delete'),
    ('POST',  re.compile(r'^/api/admin/renewals/stages/reorder$'), 'renewal.stage_reorder'),
```

- [ ] **Step 3: Прогнать тест реестра (он падает, если модель забыли)**

Run: `cd journal_django && pytest apps/changelog -q -k registry`
Expected: PASS (`test_registry_covers_all_tracked_models`).

- [ ] **Step 4: Прогнать весь changelog-набор на регресс**

Run: `cd journal_django && pytest apps/changelog -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/changelog/registry.py journal_django/apps/changelog/labels.py
git commit -m "feat(renewals): регистрация моделей и меток операций в журнале изменений"
```

---

## ФАЗА 1. Движок циклов: вычисление, автогенерация, сигналы, переходы

Цель фазы: сделки корректно порождаются/закрываются/респавнятся по данным о посещаемости и оплатах; переходы валидируются.

### Task 1.1: Вычисление номера цикла и окна продления

**Files:**
- Create: `journal_django/apps/renewals/cycle.py`
- Test: `journal_django/apps/renewals/tests/test_cycle.py`

- [ ] **Step 1: Написать падающий тест**

```python
import pytest
from apps.renewals import cycle


@pytest.mark.django_db
def test_cycle_no_from_attended():
    # 0 отработанных уроков → цикл 1; 4 → цикл 2; 7 → цикл 2; 8 → цикл 3.
    assert cycle.cycle_no_from_attended(0) == 1
    assert cycle.cycle_no_from_attended(3.5) == 1
    assert cycle.cycle_no_from_attended(4) == 2
    assert cycle.cycle_no_from_attended(7.5) == 2
    assert cycle.cycle_no_from_attended(8) == 3


def test_in_renewal_window():
    # окно: remaining<=1 ИЛИ balance<=0
    assert cycle.in_renewal_window(remaining=1, balance=5) is True
    assert cycle.in_renewal_window(remaining=3, balance=0) is True
    assert cycle.in_renewal_window(remaining=3, balance=5) is False
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && pytest apps/renewals/tests/test_cycle.py -q`
Expected: FAIL (`module apps.renewals.cycle has no attribute ...`).

- [ ] **Step 3: Реализовать `cycle.py`**

```python
"""
Вычисление номера цикла продления и признака «окно продления».

Цикл = 1 оплаченный месяц = 4 урока (LESSONS_PER_CYCLE). Half-lesson (0.5)
уже учтён в attended (numeric), поэтому floor по 4 корректен.
"""
from __future__ import annotations

import math

LESSONS_PER_CYCLE = 4


def cycle_no_from_attended(attended: float) -> int:
    """attended отработанных уроков по направлению → номер текущего цикла (1-based)."""
    return math.floor(float(attended) / LESSONS_PER_CYCLE) + 1


def in_renewal_window(remaining: float, balance: float) -> bool:
    """Окно продления: остался ≤1 урок ИЛИ баланс отработан (≤0)."""
    return float(remaining) <= 1 or float(balance) <= 0
```

- [ ] **Step 4: Запустить тест**

Run: `cd journal_django && pytest apps/renewals/tests/test_cycle.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals/cycle.py journal_django/apps/renewals/tests/test_cycle.py
git commit -m "feat(renewals): вычисление номера цикла и окна продления"
```

### Task 1.2: Движок — идемпотентная генерация/закрытие сделок

**Files:**
- Create: `journal_django/apps/renewals/engine.py`
- Test: `journal_django/apps/renewals/tests/test_engine.py`
- Create: `journal_django/apps/renewals/tests/conftest.py`

- [ ] **Step 1: conftest для renewals-тестов** (фабрики ученика/направления)

```python
"""Фикстуры renewals: создаём реальные строки в journal_test, чистим в teardown."""
from __future__ import annotations

import pytest
from django.db import connection


@pytest.fixture(scope='session')
def django_db_setup():
    pass


@pytest.fixture
def make_student(db):
    ids = []

    def _make(full_name='__renew_test_student__'):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO students (full_name, enrollment_status, created_at) "
                "VALUES (%s, 'enrolled', now()) RETURNING id", [full_name])
            sid = cur.fetchone()[0]
        ids.append(sid)
        return sid

    yield _make
    with connection.cursor() as cur:
        for sid in ids:
            cur.execute('DELETE FROM renewal_deal WHERE student_id = %s', [sid])
            cur.execute('DELETE FROM students WHERE id = %s', [sid])


@pytest.fixture
def make_direction(db):
    ids = []

    def _make(name='__renew_test_dir__', price='4000.00'):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO directions (name, sheet_name, is_individual, active, subscription_price) "
                "VALUES (%s, %s, false, true, %s) RETURNING id", [name, name, price])
            did = cur.fetchone()[0]
        ids.append(did)
        return did

    yield _make
    with connection.cursor() as cur:
        for did in ids:
            cur.execute('DELETE FROM renewal_deal WHERE direction_id = %s', [did])
            cur.execute('DELETE FROM directions WHERE id = %s', [did])
```

- [ ] **Step 2: Написать падающий тест движка (идемпотентность + закрытие)**

```python
import pytest
from apps.renewals import engine
from apps.renewals.models import RenewalDeal, RenewalStage


@pytest.mark.django_db
def test_ensure_deal_is_idempotent(make_student, make_direction):
    sid, did = make_student(), make_direction()
    d1 = engine.ensure_deal(sid, did, cycle_no=1)
    d2 = engine.ensure_deal(sid, did, cycle_no=1)
    assert d1.id == d2.id
    assert RenewalDeal.objects.filter(student_id=sid, direction_id=did).count() == 1
    # новая сделка стартует в auto-стадии прогресса
    assert d1.stage.kind == 'progress'
    assert d1.outcome_at is None


@pytest.mark.django_db
def test_close_won_and_respawn(make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    engine.close_deal_won(sid, did)  # оплата пришла
    open_deals = RenewalDeal.objects.filter(student_id=sid, direction_id=did, outcome_at__isnull=True)
    closed = RenewalDeal.objects.filter(student_id=sid, direction_id=did, outcome_at__isnull=False)
    assert closed.count() == 1
    assert closed.first().stage.kind == 'won'
    # порождён следующий цикл
    assert open_deals.count() == 1
    assert open_deals.first().cycle_no == 2
```

- [ ] **Step 3: Запустить — убедиться, что падает**

Run: `cd journal_django && pytest apps/renewals/tests/test_engine.py -q`
Expected: FAIL.

- [ ] **Step 4: Реализовать `engine.py`**

```python
"""
Движок сделок продления: идемпотентная генерация, закрытие won/lost, респавн цикла.

Все операции безопасны к повторному вызову (для сигналов и ночной команды).
Стадии берём из дефолтной воронки; авто-стадия прогресса — kind='progress'.
"""
from __future__ import annotations

from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.renewals.models import RenewalActivity, RenewalDeal, RenewalPipeline, RenewalStage


def _default_pipeline() -> RenewalPipeline:
    return RenewalPipeline.objects.get(is_default=True)


def _stage(pipeline: RenewalPipeline, *, kind: str) -> RenewalStage:
    """Первая по порядку стадия заданного вида (progress/won/lost)."""
    return (RenewalStage.objects
            .filter(pipeline=pipeline, kind=kind)
            .order_by('sort_order').first())


@transaction.atomic
def ensure_deal(student_id: int, direction_id: int, cycle_no: int,
                assignee_id: Optional[int] = None) -> RenewalDeal:
    """Создать (или вернуть существующую) сделку цикла. Идемпотентно по UNIQUE."""
    pipeline = _default_pipeline()
    progress = _stage(pipeline, kind='progress')
    deal, created = RenewalDeal.objects.get_or_create(
        student_id=student_id, direction_id=direction_id, cycle_no=cycle_no,
        defaults={'pipeline': pipeline, 'stage': progress, 'assignee_id': assignee_id},
    )
    if created:
        RenewalActivity.objects.create(
            deal=deal, kind='system', to_stage=progress, body='Сделка создана')
    return deal


@transaction.atomic
def close_deal_won(student_id: int, direction_id: int,
                   payment_id: Optional[int] = None) -> Optional[RenewalDeal]:
    """Закрыть открытую сделку как «Продлён» и породить следующий цикл."""
    deal = (RenewalDeal.objects
            .select_for_update()
            .filter(student_id=student_id, direction_id=direction_id, outcome_at__isnull=True)
            .order_by('-cycle_no').first())
    if deal is None:
        return None
    won = _stage(deal.pipeline, kind='won')
    from_stage = deal.stage
    deal.stage = won
    deal.outcome_at = timezone.now()
    deal.stage_entered_at = timezone.now()
    deal.save(update_fields=['stage', 'outcome_at', 'stage_entered_at', 'updated_at'])
    RenewalActivity.objects.create(
        deal=deal, kind='payment_linked', from_stage=from_stage, to_stage=won,
        payment_id=payment_id, body='Продление подтверждено оплатой')
    # респавн: следующий цикл наследует ответственного
    ensure_deal(student_id, direction_id, deal.cycle_no + 1, assignee_id=deal.assignee_id)
    return deal
```

- [ ] **Step 5: Запустить тест**

Run: `cd journal_django && pytest apps/renewals/tests/test_engine.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/renewals/engine.py journal_django/apps/renewals/tests/test_engine.py journal_django/apps/renewals/tests/conftest.py
git commit -m "feat(renewals): движок idempotent-генерации и закрытия сделок"
```

### Task 1.3: Валидатор переходов стадий

**Files:**
- Create: `journal_django/apps/renewals/transitions.py`
- Test: `journal_django/apps/renewals/tests/test_transitions.py`

- [ ] **Step 1: Написать падающий тест**

```python
import pytest
from apps.renewals import transitions
from apps.renewals.transitions import InvalidTransition


def test_terminal_stages_are_frozen():
    # из won/lost переходов нет
    assert transitions.is_allowed(from_kind='won', to_kind='decision') is False
    assert transitions.is_allowed(from_kind='lost', to_kind='progress') is False


def test_open_to_terminal_allowed():
    assert transitions.is_allowed(from_kind='progress', to_kind='won') is True
    assert transitions.is_allowed(from_kind='decision', to_kind='lost') is True
    assert transitions.is_allowed(from_kind='decision', to_kind='decision') is True


def test_assert_raises():
    with pytest.raises(InvalidTransition):
        transitions.assert_allowed(from_kind='won', to_kind='decision')
```

- [ ] **Step 2: Запустить — падает**

Run: `cd journal_django && pytest apps/renewals/tests/test_transitions.py -q`
Expected: FAIL.

- [ ] **Step 3: Реализовать `transitions.py`**

```python
"""Валидатор переходов между стадиями по их виду (kind)."""
from __future__ import annotations


class InvalidTransition(Exception):
    """Недопустимый переход стадии."""


# Из терминальных (won/lost) переходов нет. Из открытых — в любую открытую/терминальную.
_TERMINAL = {'won', 'lost'}


def is_allowed(*, from_kind: str, to_kind: str) -> bool:
    if from_kind in _TERMINAL:
        return False
    return to_kind in {'progress', 'decision', 'won', 'lost'}


def assert_allowed(*, from_kind: str, to_kind: str) -> None:
    if not is_allowed(from_kind=from_kind, to_kind=to_kind):
        raise InvalidTransition(f'Переход {from_kind} → {to_kind} запрещён')
```

- [ ] **Step 4: Запустить тест**

Run: `cd journal_django && pytest apps/renewals/tests/test_transitions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals/transitions.py journal_django/apps/renewals/tests/test_transitions.py
git commit -m "feat(renewals): валидатор переходов стадий"
```

### Task 1.4: Сигналы — оплата закрывает сделку, посещаемость обновляет окно

**Files:**
- Modify: `journal_django/apps/renewals/signals.py`
- Test: `journal_django/apps/renewals/tests/test_signals.py`

- [ ] **Step 1: Написать падающий тест на сигнал оплаты**

```python
import pytest
from django.db import connection
from apps.renewals import engine
from apps.renewals.models import RenewalDeal


@pytest.mark.django_db(transaction=True)
def test_payment_closes_deal(make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    # создаём оплату напрямую в БД (immutable-инвариант: только INSERT)
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, "
            "unit_price, total_amount, paid_at, created_at) "
            "VALUES (%s,%s,1,4000,4000, now()::date, now()) RETURNING id", [sid, did])
        pid = cur.fetchone()[0]
    try:
        closed = RenewalDeal.objects.filter(
            student_id=sid, direction_id=did, outcome_at__isnull=False)
        assert closed.count() == 1
        assert RenewalDeal.objects.filter(
            student_id=sid, direction_id=did, outcome_at__isnull=True,
            cycle_no=2).exists()
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM renewal_activity WHERE payment_id = %s', [pid])
            cur.execute('DELETE FROM payments WHERE id = %s', [pid])
```

> Примечание: тест с `transaction=True`, т.к. сигнал `post_save` должен отработать в отдельной
> транзакции. Оплата вставляется через ORM в реализации? Нет — сигнал вешаем на модель `Payment`,
> а вставка через raw SQL сигнал Django НЕ вызовет. Поэтому в тесте создаём оплату через ORM-модель
> (см. Step 2 — тест переписываем на `Payment.objects.create`).

- [ ] **Step 2: Переписать тест через ORM (чтобы `post_save` сработал)**

```python
import pytest
from apps.payments.models import Payment
from apps.renewals import engine
from apps.renewals.models import RenewalDeal


@pytest.mark.django_db
def test_payment_orm_create_closes_deal(make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    pay = Payment.objects.create(
        student_id=sid, direction_id=did, subscriptions_count=1,
        unit_price=4000, total_amount=4000, paid_at='2026-07-08')
    try:
        assert RenewalDeal.objects.filter(
            student_id=sid, direction_id=did, outcome_at__isnull=False).count() == 1
        assert RenewalDeal.objects.filter(
            student_id=sid, direction_id=did, cycle_no=2, outcome_at__isnull=True).exists()
    finally:
        RenewalDeal.objects.filter(student_id=sid).delete()
        pay.delete()
```

- [ ] **Step 3: Запустить — падает** (сигнал ещё не подключён)

Run: `cd journal_django && pytest apps/renewals/tests/test_signals.py -q`
Expected: FAIL (сделка не закрыта).

- [ ] **Step 4: Реализовать `signals.py`**

```python
"""
Сигналы renewals:
  • оплата (Payment) → закрыть сделку направления как «Продлён» + респавн цикла;
  • посещаемость (LessonAttendance) → обновить stage_entered_at открытой сделки (для SLA).

Идемпотентность обеспечивает engine (get_or_create / select_for_update).
"""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.lessons.models import LessonAttendance
from apps.payments.models import Payment
from apps.renewals import engine


@receiver(post_save, sender=Payment, dispatch_uid='renewals_on_payment')
def on_payment_created(sender, instance: Payment, created: bool, **kwargs) -> None:
    if not created or instance.direction_id is None:
        return  # легаси-оплаты без направления пропускаем
    engine.close_deal_won(instance.student_id, instance.direction_id, payment_id=instance.id)
```

> `LessonAttendance` в проекте пишется преимущественно raw SQL (см. модель — «раздел работает через
> raw SQL»), поэтому вешать `post_save` на неё смысла мало: обновление окна делаем в API-слое на чтении
> (вычисляемые поля) и в ночной команде `rebuild_renewal_deals`. Оставляем только сигнал оплаты.

- [ ] **Step 5: Запустить тест**

Run: `cd journal_django && pytest apps/renewals/tests/test_signals.py -q`
Expected: PASS.

- [ ] **Step 6: Прогнать смежные наборы на регресс (payments)**

Run: `cd journal_django && pytest apps/payments -q`
Expected: PASS (сигнал не ломает создание оплат).

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/renewals/signals.py journal_django/apps/renewals/tests/test_signals.py
git commit -m "feat(renewals): сигнал оплаты закрывает сделку и порождает цикл"
```

### Task 1.5: Ночная команда самозаживления `rebuild_renewal_deals`

**Files:**
- Create: `journal_django/apps/renewals/management/__init__.py` (пустой)
- Create: `journal_django/apps/renewals/management/commands/__init__.py` (пустой)
- Create: `journal_django/apps/renewals/management/commands/rebuild_renewal_deals.py`
- Create: `journal_django/apps/renewals/repository.py` (первый метод — `active_cycles()`)
- Test: `journal_django/apps/renewals/tests/test_rebuild.py`

- [ ] **Step 1: Реализовать `repository.active_cycles()`**

```python
"""Repository renewals: чтение агрегатов из memberships/finances + операции над сделками."""
from __future__ import annotations

from django.db import connection

from apps.renewals import cycle


def active_cycles() -> list[dict]:
    """
    Для каждого активного (ученик × направление) — сколько уроков отработано,
    чтобы движок мог гарантировать сделку текущего цикла.

    Источник: активные membership + attended по направлению.
    group_memberships → groups.direction_id (направление группы).
    """
    sql = """
        SELECT m.student_id,
               g.direction_id,
               COALESCE(SUM(m.lessons_done), 0) AS attended
        FROM group_memberships m
        JOIN groups g ON g.id = m.group_id
        WHERE m.active = true AND g.direction_id IS NOT NULL
        GROUP BY m.student_id, g.direction_id
    """
    with connection.cursor() as cur:
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        r['cycle_no'] = cycle.cycle_no_from_attended(r['attended'])
    return rows
```

> ⚠️ Перед реализацией сверить имя колонки направления в `groups` (в проекте это `groups.direction_id`
> — подтвердить по `apps/groups/models.py`; если направление хранится иначе, поправить JOIN).

- [ ] **Step 2: Реализовать команду**

```python
"""Пересборка сделок продления — самозаживление на случай пропущенных сигналов."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.renewals import engine, repository


class Command(BaseCommand):
    help = 'Гарантирует сделку текущего цикла для каждого активного (ученик×направление).'

    def handle(self, *args, **options):
        created = 0
        for row in repository.active_cycles():
            deal = engine.ensure_deal(row['student_id'], row['direction_id'], row['cycle_no'])
            if deal._state.adding is False and deal.pk:
                created += 1
        self.stdout.write(self.style.SUCCESS(f'renewals: обработано {created} циклов'))
```

- [ ] **Step 3: Написать тест команды**

```python
import pytest
from django.core.management import call_command
from django.db import connection
from apps.renewals.models import RenewalDeal


@pytest.mark.django_db
def test_rebuild_creates_deal_for_active_membership(make_student, make_direction):
    sid, did = make_student(), make_direction()
    # создаём группу с направлением и активный membership
    with connection.cursor() as cur:
        # groups: is_individual и created_at — NOT NULL без дефолта, задаём явно.
        cur.execute("INSERT INTO groups (name, direction_id, is_individual, active, created_at) "
                    "VALUES ('__rg__', %s, false, true, now()) RETURNING id", [did])
        gid = cur.fetchone()[0]
        cur.execute("INSERT INTO group_memberships (group_id, student_id, lessons_done, remaining, active) "
                    "VALUES (%s,%s,0,4,true)", [gid, sid])
    try:
        call_command('rebuild_renewal_deals')
        assert RenewalDeal.objects.filter(student_id=sid, direction_id=did, cycle_no=1).exists()
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM renewal_deal WHERE student_id = %s', [sid])
            cur.execute('DELETE FROM group_memberships WHERE group_id = %s', [gid])
            cur.execute('DELETE FROM groups WHERE id = %s', [gid])
```

> Сверить набор колонок `groups` (name/direction_id/active) с `apps/groups/models.py` перед прогоном.

- [ ] **Step 4: Запустить тест**

Run: `cd journal_django && pytest apps/renewals/tests/test_rebuild.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals/management journal_django/apps/renewals/repository.py journal_django/apps/renewals/tests/test_rebuild.py
git commit -m "feat(renewals): команда rebuild_renewal_deals (самозаживление)"
```

---

## ФАЗА 2. Read API: доска, список, детальная карточка

Цель фазы: `GET /api/admin/renewals` (board|list) и `GET /api/admin/renewals/:id` с вычисляемыми полями, под RBAC.

### Task 2.1: Вычисляемые поля сделки + сериализатор

**Files:**
- Modify: `journal_django/apps/renewals/repository.py` (метод `deal_computed`)
- Create: `journal_django/apps/renewals/serializers.py`
- Test: `journal_django/apps/renewals/tests/test_serializers.py`

- [ ] **Step 1: Реализовать `repository.deal_computed(deal_id)`**

Добавить в `repository.py`:

```python
def deal_computed(deal_id: int) -> dict | None:
    """
    Сделка + вычисляемые поля: имя ученика, направление/цвет, прогресс n/4,
    remaining, balance, days_in_stage. Баланс — через apps.finances.
    """
    from apps.finances.repository import balance_for_direction

    sql = """
        SELECT d.id, d.student_id, d.direction_id, d.cycle_no, d.stage_id,
               d.assignee_id, d.expected_amount, d.next_touch_at, d.reason_code,
               d.stage_entered_at, d.outcome_at, d.created_at,
               s.full_name AS student_name,
               dir.name AS direction_name, dir.color AS direction_color,
               st.key AS stage_key, st.label AS stage_label, st.kind AS stage_kind,
               st.color AS stage_color,
               a.full_name AS assignee_name,
               EXTRACT(DAY FROM now() - d.stage_entered_at)::int AS days_in_stage,
               COALESCE((
                   SELECT SUM(m.lessons_done) FROM group_memberships m
                   JOIN groups g ON g.id = m.group_id
                   WHERE m.student_id = d.student_id AND g.direction_id = d.direction_id
                     AND m.active = true), 0) AS attended
        FROM renewal_deal d
        JOIN students s   ON s.id = d.student_id
        JOIN directions dir ON dir.id = d.direction_id
        JOIN renewal_stage st ON st.id = d.stage_id
        LEFT JOIN accounts a ON a.id = d.assignee_id
        WHERE d.id = %s
    """
    with connection.cursor() as cur:
        cur.execute(sql, [deal_id])
        row = cur.fetchone()
        if row is None:
            return None
        cols = [c[0] for c in cur.description]
        data = dict(zip(cols, row))
    attended = float(data.pop('attended') or 0)
    data['lesson_in_cycle'] = int(attended % cycle.LESSONS_PER_CYCLE) + 1  # 1..4
    data['balance'] = balance_for_direction(data['student_id'], data['direction_id'])
    return data
```

- [ ] **Step 2: Написать сериализаторы**

```python
"""Сериализаторы renewals. Read — из dict repository; write — валидация входа."""
from __future__ import annotations

from rest_framework import serializers


class MoveSerializer(serializers.Serializer):
    to_stage_id = serializers.IntegerField()
    reason_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class DealPatchSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField(required=False, allow_null=True)
    next_touch_at = serializers.DateField(required=False, allow_null=True)
    reason_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    expected_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True)


class CommentSerializer(serializers.Serializer):
    body = serializers.CharField()
```

- [ ] **Step 3: Тест сериализаторов**

```python
from apps.renewals.serializers import MoveSerializer, DealPatchSerializer


def test_move_requires_stage():
    assert MoveSerializer(data={}).is_valid() is False
    assert MoveSerializer(data={'to_stage_id': 5}).is_valid() is True


def test_patch_all_optional():
    assert DealPatchSerializer(data={}).is_valid() is True
```

- [ ] **Step 4: Запустить**

Run: `cd journal_django && pytest apps/renewals/tests/test_serializers.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals/repository.py journal_django/apps/renewals/serializers.py journal_django/apps/renewals/tests/test_serializers.py
git commit -m "feat(renewals): вычисляемые поля сделки + сериализаторы"
```

### Task 2.2: Repository board() и list()

**Files:**
- Modify: `journal_django/apps/renewals/repository.py`
- Test: `journal_django/apps/renewals/tests/test_repository.py`

- [ ] **Step 1: Реализовать `board()` и `list_deals()`**

```python
COLUMN_LIMIT = 50  # карточек на колонку по умолчанию (остальное — «Показать ещё»)


def board(filters: dict | None = None) -> dict:
    """
    Доска: открытые сделки, сгруппированные по стадиям дефолтной воронки.
    Возвращает колонки в порядке sort_order с count/sum_potential и первыми N карточками.
    """
    filters = filters or {}
    from apps.renewals.models import RenewalStage, RenewalPipeline
    pipeline = RenewalPipeline.objects.get(is_default=True)
    stages = list(RenewalStage.objects.filter(pipeline=pipeline).order_by('sort_order'))

    where = ['d.outcome_at IS NULL']
    params: list = []
    if filters.get('assignee_id'):
        where.append('d.assignee_id = %s'); params.append(int(filters['assignee_id']))
    if filters.get('direction_id'):
        where.append('d.direction_id = %s'); params.append(int(filters['direction_id']))
    if filters.get('overdue') == 'true':
        where.append("d.next_touch_at IS NOT NULL AND d.next_touch_at < now()::date")
    where_sql = ' AND '.join(where)

    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT d.stage_id, COUNT(*) AS cnt, COALESCE(SUM(d.expected_amount),0) AS sum_amt
            FROM renewal_deal d WHERE {where_sql} GROUP BY d.stage_id
        """, params)
        agg = {r[0]: {'count': r[1], 'sum_potential': float(r[2])} for r in cur.fetchall()}

    columns = []
    for st in stages:
        stat = agg.get(st.id, {'count': 0, 'sum_potential': 0.0})
        cards = _deals_in_stage(st.id, where_sql, params, COLUMN_LIMIT)
        columns.append({
            'stage_id': st.id, 'key': st.key, 'label': st.label, 'kind': st.kind,
            'color': st.color, 'count': stat['count'],
            'sum_potential': stat['sum_potential'], 'cards': cards,
        })
    return {'columns': columns}


def _deals_in_stage(stage_id: int, where_sql: str, base_params: list, limit: int) -> list[dict]:
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT d.id, s.full_name AS student_name, dir.name AS direction_name,
                   dir.color AS direction_color, d.cycle_no, d.expected_amount,
                   d.next_touch_at, a.full_name AS assignee_name,
                   EXTRACT(DAY FROM now() - d.stage_entered_at)::int AS days_in_stage
            FROM renewal_deal d
            JOIN students s ON s.id = d.student_id
            JOIN directions dir ON dir.id = d.direction_id
            LEFT JOIN accounts a ON a.id = d.assignee_id
            WHERE {where_sql} AND d.stage_id = %s
            ORDER BY d.next_touch_at NULLS LAST, d.stage_entered_at
            LIMIT %s
        """, base_params + [stage_id, limit])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def list_deals(page: int, page_size: int, sort_by: str, sort_dir: str, filters: dict) -> dict:
    """Списочный вид: server-pagination. sort_dir валидируется вызывающим (view)."""
    where = ['1=1']
    params: list = []
    if not filters.get('include_closed'):
        where.append('d.outcome_at IS NULL')
    if filters.get('assignee_id'):
        where.append('d.assignee_id = %s'); params.append(int(filters['assignee_id']))
    if filters.get('direction_id'):
        where.append('d.direction_id = %s'); params.append(int(filters['direction_id']))
    if filters.get('stage_id'):
        where.append('d.stage_id = %s'); params.append(int(filters['stage_id']))
    where_sql = ' AND '.join(where)

    sort_col = {
        'next_touch_at': 'd.next_touch_at', 'stage_entered_at': 'd.stage_entered_at',
        'cycle_no': 'd.cycle_no', 'student_name': 's.full_name',
    }.get(sort_by, 'd.stage_entered_at')
    direction = 'DESC' if sort_dir == 'desc' else 'ASC'

    with connection.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM renewal_deal d WHERE {where_sql}", params)
        total = cur.fetchone()[0]
        cur.execute(f"""
            SELECT d.id, s.full_name AS student_name, dir.name AS direction_name,
                   dir.color AS direction_color, d.cycle_no, st.label AS stage_label,
                   st.kind AS stage_kind, d.next_touch_at, a.full_name AS assignee_name,
                   EXTRACT(DAY FROM now() - d.stage_entered_at)::int AS days_in_stage
            FROM renewal_deal d
            JOIN students s ON s.id = d.student_id
            JOIN directions dir ON dir.id = d.direction_id
            JOIN renewal_stage st ON st.id = d.stage_id
            LEFT JOIN accounts a ON a.id = d.assignee_id
            WHERE {where_sql}
            ORDER BY {sort_col} {direction} NULLS LAST, d.id
            LIMIT %s OFFSET %s
        """, params + [page_size, (page - 1) * page_size])
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {'rows': rows, 'total': total, 'page': page, 'page_size': page_size}
```

- [ ] **Step 2: Тест repository (board + list)**

```python
import pytest
from apps.renewals import engine, repository


@pytest.mark.django_db
def test_board_groups_open_deals(make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    board = repository.board()
    progress_col = next(c for c in board['columns'] if c['kind'] == 'progress')
    assert progress_col['count'] >= 1
    assert any(card['student_name'] == '__renew_test_student__' for card in progress_col['cards'])


@pytest.mark.django_db
def test_list_paginates(make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    res = repository.list_deals(page=1, page_size=10, sort_by='cycle_no', sort_dir='asc', filters={})
    assert res['total'] >= 1
    assert res['page'] == 1
```

- [ ] **Step 3: Запустить**

Run: `cd journal_django && pytest apps/renewals/tests/test_repository.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add journal_django/apps/renewals/repository.py journal_django/apps/renewals/tests/test_repository.py
git commit -m "feat(renewals): repository board() и list_deals() с пагинацией"
```

### Task 2.3: Views + urls + wiring + RBAC

**Files:**
- Create: `journal_django/apps/renewals/services.py`
- Create: `journal_django/apps/renewals/views.py`
- Create: `journal_django/apps/renewals/urls.py`
- Modify: `journal_django/config/urls.py`
- Test: `journal_django/apps/renewals/tests/test_api_read.py`

- [ ] **Step 1: services.py (тонкий слой)**

```python
"""Services renewals — тонкий слой между views и repository/engine."""
from __future__ import annotations

from apps.renewals import repository


def board(filters: dict | None = None) -> dict:
    return repository.board(filters)


def list_deals(**kwargs) -> dict:
    return repository.list_deals(**kwargs)


def get_deal(deal_id: int) -> dict | None:
    return repository.deal_computed(deal_id)
```

- [ ] **Step 2: views.py (GET board|list + detail)**

```python
"""APIView для /api/admin/renewals. Права: IsManagerOrAdmin (manager/admin/superadmin)."""
from __future__ import annotations

from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin
from apps.renewals import services

SORT_FIELDS = ['next_touch_at', 'stage_entered_at', 'cycle_no', 'student_name']


class RenewalCollectionView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        qp = request.query_params
        view = qp.get('view', 'board')
        filters = {k[7:-1]: v for k, v in qp.items()
                   if k.startswith('filter[') and k.endswith(']')}
        if view == 'list':
            page = max(1, int(qp.get('page', 1) or 1))
            page_size = min(200, max(1, int(qp.get('page_size', 50) or 50)))
            sort_by = qp.get('sort_by', 'stage_entered_at')
            sort_dir = qp.get('sort_dir', 'asc')
            if sort_by not in SORT_FIELDS:
                raise ValidationError(f"Invalid sort_by. Allowed: {SORT_FIELDS}")
            if sort_dir not in ('asc', 'desc'):
                raise ValidationError("sort_dir must be 'asc' or 'desc'")
            return Response(services.list_deals(
                page=page, page_size=page_size, sort_by=sort_by,
                sort_dir=sort_dir, filters=filters))
        return Response(services.board(filters))


class RenewalDetailView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        deal = services.get_deal(pk)
        if deal is None:
            raise NotFound({'error': 'Not found'})
        return Response(deal)
```

- [ ] **Step 3: urls.py + wiring**

`journal_django/apps/renewals/urls.py`:

```python
"""Маршруты renewals. APPEND_SLASH=False — без trailing slash."""
from django.urls import path

from apps.renewals.views import RenewalCollectionView, RenewalDetailView

urlpatterns = [
    path('', RenewalCollectionView.as_view(), name='renewals-collection'),
    path('/<int:pk>', RenewalDetailView.as_view(), name='renewals-detail'),
]
```

В `config/urls.py` добавить рядом с другими admin-разделами (после `payments`/`lessons`):

```python
    path('api/admin/renewals', include('apps.renewals.urls')),
```

- [ ] **Step 4: Тест API чтения (RBAC + формы)**

```python
import pytest
from apps.renewals import engine

BASE = '/api/admin/renewals'


@pytest.mark.django_db
def test_no_cookie_401(anon_client):
    assert anon_client.get(BASE).status_code == 401


@pytest.mark.django_db
def test_teacher_403(teacher_client):
    assert teacher_client.get(BASE).status_code == 403


@pytest.mark.django_db
def test_manager_board_200(manager_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    resp = manager_client.get(f'{BASE}?view=board')
    assert resp.status_code == 200
    assert 'columns' in resp.json()


@pytest.mark.django_db
def test_manager_list_shape(manager_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    resp = manager_client.get(f'{BASE}?view=list&page=1&page_size=10')
    body = resp.json()
    assert set(body) >= {'rows', 'total', 'page', 'page_size'}


@pytest.mark.django_db
def test_invalid_sort_400(manager_client):
    assert manager_client.get(f'{BASE}?view=list&sort_by=hax').status_code == 400
```

- [ ] **Step 5: Запустить**

Run: `cd journal_django && pytest apps/renewals/tests/test_api_read.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/renewals/services.py journal_django/apps/renewals/views.py journal_django/apps/renewals/urls.py journal_django/config/urls.py journal_django/apps/renewals/tests/test_api_read.py
git commit -m "feat(renewals): read API (board/list/detail) под IsManagerOrAdmin"
```

---

## ФАЗА 3. Write API: перемещение стадии, patch, комментарии, активность

### Task 3.1: Перемещение сделки по стадиям (`POST /:id/move`)

**Files:**
- Modify: `journal_django/apps/renewals/repository.py`, `services.py`, `views.py`, `urls.py`
- Test: `journal_django/apps/renewals/tests/test_api_write.py`

- [ ] **Step 1: `repository.move_deal()` + `services.move_deal()`**

В `repository.py`:

```python
def move_deal(deal_id: int, to_stage_id: int, reason_code: str | None,
              author_id: int | None) -> dict | None:
    """Переместить сделку в стадию, записать активность, синхронизировать outcome/enrollment."""
    from django.db import transaction
    from django.utils import timezone
    from apps.renewals.models import RenewalActivity, RenewalDeal, RenewalStage
    from apps.renewals.transitions import assert_allowed, InvalidTransition

    with transaction.atomic():
        deal = RenewalDeal.objects.select_for_update().filter(id=deal_id).first()
        if deal is None:
            return None
        to_stage = RenewalStage.objects.filter(id=to_stage_id, pipeline=deal.pipeline).first()
        if to_stage is None:
            raise InvalidTransition('Стадия не принадлежит воронке сделки')
        from_stage = deal.stage
        assert_allowed(from_kind=from_stage.kind, to_kind=to_stage.kind)

        deal.stage = to_stage
        deal.stage_entered_at = timezone.now()
        if reason_code is not None:
            deal.reason_code = reason_code
        deal.outcome_at = timezone.now() if to_stage.kind in ('won', 'lost') else None
        deal.save(update_fields=['stage', 'stage_entered_at', 'reason_code',
                                 'outcome_at', 'updated_at'])
        RenewalActivity.objects.create(
            deal=deal, kind='stage_change', from_stage=from_stage, to_stage=to_stage,
            author_id=author_id, body=reason_code or '')
        # win-стадия по кнопке (без оплаты) тоже респавнит цикл
        if to_stage.kind == 'won':
            from apps.renewals import engine
            engine.ensure_deal(deal.student_id, deal.direction_id, deal.cycle_no + 1,
                               assignee_id=deal.assignee_id)
    return deal_computed(deal_id)
```

В `services.py`:

```python
def move_deal(deal_id: int, to_stage_id: int, reason_code, author_id) -> dict | None:
    return repository.move_deal(deal_id, to_stage_id, reason_code, author_id)
```

- [ ] **Step 2: View + маршрут**

В `views.py` добавить:

```python
from rest_framework import status
from apps.renewals.serializers import MoveSerializer
from apps.renewals.transitions import InvalidTransition


class RenewalMoveView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        ser = MoveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            result = services.move_deal(
                pk, ser.validated_data['to_stage_id'],
                ser.validated_data.get('reason_code'),
                author_id=getattr(request.user, 'id', None))
        except InvalidTransition as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)
```

В `urls.py` добавить: `path('/<int:pk>/move', RenewalMoveView.as_view(), name='renewals-move'),`

- [ ] **Step 3: Тест move (успех + запрещённый переход → 409)**

```python
import pytest
from apps.renewals import engine
from apps.renewals.models import RenewalStage

BASE = '/api/admin/renewals'


def _stage_id(key):
    return RenewalStage.objects.get(key=key).id


@pytest.mark.django_db
def test_move_to_decision(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('awaiting_payment')}, format='json')
    assert resp.status_code == 200
    assert resp.json()['stage_key'] == 'awaiting_payment'


@pytest.mark.django_db
def test_move_from_terminal_409(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    admin_client.post(f'{BASE}/{deal.id}/move', {'to_stage_id': _stage_id('churned')}, format='json')
    resp = admin_client.post(f'{BASE}/{deal.id}/move',
                             {'to_stage_id': _stage_id('thinking')}, format='json')
    assert resp.status_code == 409
```

- [ ] **Step 4: Запустить**

Run: `cd journal_django && pytest apps/renewals/tests/test_api_write.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals/repository.py journal_django/apps/renewals/services.py journal_django/apps/renewals/views.py journal_django/apps/renewals/urls.py journal_django/apps/renewals/tests/test_api_write.py
git commit -m "feat(renewals): POST /move с валидацией переходов (409 на запрещённый)"
```

### Task 3.2: PATCH сделки + POST /comment + GET /activity

**Files:**
- Modify: `journal_django/apps/renewals/repository.py`, `services.py`, `views.py`, `urls.py`
- Test: дополнить `test_api_write.py`

- [ ] **Step 1: repository — `patch_deal`, `add_comment`, `list_activity`**

```python
def patch_deal(deal_id: int, data: dict) -> dict | None:
    from apps.renewals.models import RenewalDeal
    fields = {}
    for k in ('assignee_id', 'next_touch_at', 'reason_code', 'expected_amount'):
        if k in data:
            fields[k] = data[k]
    if not fields:
        return deal_computed(deal_id)
    updated = RenewalDeal.objects.filter(id=deal_id).update(**fields)
    return deal_computed(deal_id) if updated else None


def add_comment(deal_id: int, body: str, author_id: int | None) -> dict | None:
    from apps.renewals.models import RenewalActivity, RenewalDeal
    if not RenewalDeal.objects.filter(id=deal_id).exists():
        return None
    act = RenewalActivity.objects.create(
        deal_id=deal_id, kind='comment', body=body, author_id=author_id)
    return {'id': act.id, 'created_at': act.created_at}


def list_activity(deal_id: int) -> list[dict]:
    with connection.cursor() as cur:
        cur.execute("""
            SELECT ra.id, ra.kind, ra.body, ra.created_at,
                   fs.label AS from_label, ts.label AS to_label,
                   a.full_name AS author_name, ra.payment_id
            FROM renewal_activity ra
            LEFT JOIN renewal_stage fs ON fs.id = ra.from_stage_id
            LEFT JOIN renewal_stage ts ON ts.id = ra.to_stage_id
            LEFT JOIN accounts a ON a.id = ra.author_id
            WHERE ra.deal_id = %s ORDER BY ra.created_at DESC
        """, [deal_id])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
```

- [ ] **Step 2: services + views + urls** (PATCH detail, POST comment, GET activity)

В `services.py`: тонкие обёртки `patch_deal / add_comment / list_activity`.

В `views.py` — добавить `patch` в `RenewalDetailView` и новые вьюхи:

```python
    def patch(self, request: Request, pk: int) -> Response:
        from apps.renewals.serializers import DealPatchSerializer
        ser = DealPatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = services.patch_deal(pk, ser.validated_data)
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)


class RenewalCommentView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        from apps.renewals.serializers import CommentSerializer
        ser = CommentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = services.add_comment(pk, ser.validated_data['body'],
                                      getattr(request.user, 'id', None))
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result, status=status.HTTP_201_CREATED)


class RenewalActivityView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        return Response(services.list_activity(pk))
```

В `urls.py`:

```python
    path('/<int:pk>/comment', RenewalCommentView.as_view(), name='renewals-comment'),
    path('/<int:pk>/activity', RenewalActivityView.as_view(), name='renewals-activity'),
```

- [ ] **Step 3: Тесты (patch assignee, comment создаёт активность)**

```python
@pytest.mark.django_db
def test_patch_next_touch(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    resp = admin_client.patch(f'{BASE}/{deal.id}',
                              {'next_touch_at': '2026-07-15'}, format='json')
    assert resp.status_code == 200
    assert resp.json()['next_touch_at'] == '2026-07-15'


@pytest.mark.django_db
def test_comment_then_activity(admin_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    admin_client.post(f'{BASE}/{deal.id}/comment', {'body': 'позвонил, думает'}, format='json')
    acts = admin_client.get(f'{BASE}/{deal.id}/activity').json()
    assert any(a['kind'] == 'comment' and a['body'] == 'позвонил, думает' for a in acts)
```

- [ ] **Step 4: Запустить**

Run: `cd journal_django && pytest apps/renewals/tests/test_api_write.py -q`
Expected: PASS.

- [ ] **Step 5: Прогнать changelog-набор (метки move/comment/update должны резолвиться)**

Run: `cd journal_django && pytest apps/changelog -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/renewals journal_django/apps/changelog
git commit -m "feat(renewals): PATCH сделки, комментарии, лента активности"
```

---

## ФАЗА 4. Конфигурация стадий (superadmin)

### Task 4.1: CRUD стадий + reorder

**Files:**
- Modify: `journal_django/apps/renewals/repository.py`, `services.py`, `serializers.py`, `views.py`, `urls.py`
- Test: `journal_django/apps/renewals/tests/test_stages_api.py`

- [ ] **Step 1: Сериализатор стадии**

В `serializers.py`:

```python
class StageWriteSerializer(serializers.Serializer):
    label = serializers.CharField()
    color = serializers.RegexField(r'^#[0-9a-fA-F]{6}$', required=False, allow_null=True)
    kind = serializers.ChoiceField(choices=['progress', 'decision', 'won', 'lost'])
    key = serializers.RegexField(r'^[a-z0-9_]+$', required=False)


class StageReorderSerializer(serializers.Serializer):
    order = serializers.ListField(child=serializers.IntegerField())  # stage_id в новом порядке
```

- [ ] **Step 2: repository — list/create/update/delete/reorder стадий**

```python
def list_stages() -> list[dict]:
    from apps.renewals.models import RenewalPipeline, RenewalStage
    pipe = RenewalPipeline.objects.get(is_default=True)
    return list(RenewalStage.objects.filter(pipeline=pipe).order_by('sort_order')
                .values('id', 'key', 'label', 'color', 'kind', 'is_auto', 'sort_order'))


def create_stage(data: dict) -> dict:
    from apps.renewals.models import RenewalPipeline, RenewalStage
    from django.db.models import Max
    pipe = RenewalPipeline.objects.get(is_default=True)
    next_order = (RenewalStage.objects.filter(pipeline=pipe)
                  .aggregate(m=Max('sort_order'))['m'] or 0) + 1
    key = data.get('key') or _slugify_key(data['label'])
    st = RenewalStage.objects.create(
        pipeline=pipe, key=key, label=data['label'], color=data.get('color'),
        kind=data['kind'], sort_order=next_order, is_auto=False)
    return _stage_dict(st)


def update_stage(stage_id: int, data: dict) -> dict | None:
    from apps.renewals.models import RenewalStage
    st = RenewalStage.objects.filter(id=stage_id).first()
    if st is None:
        return None
    for k in ('label', 'color', 'kind'):
        if k in data:
            setattr(st, k, data[k])
    st.save()
    return _stage_dict(st)


def delete_stage(stage_id: int) -> str:
    """Нельзя удалить стадию с открытыми сделками или единственную won/lost/progress."""
    from apps.renewals.models import RenewalDeal, RenewalStage
    st = RenewalStage.objects.filter(id=stage_id).first()
    if st is None:
        return 'not_found'
    if RenewalDeal.objects.filter(stage_id=stage_id, outcome_at__isnull=True).exists():
        return 'has_open_deals'
    if st.is_auto or RenewalStage.objects.filter(
            pipeline=st.pipeline, kind=st.kind).count() == 1 and st.kind in ('won', 'lost', 'progress'):
        return 'protected'
    st.delete()
    return 'ok'


def reorder_stages(order: list[int]) -> list[dict]:
    from apps.renewals.models import RenewalStage
    from django.db import transaction
    with transaction.atomic():
        for i, sid in enumerate(order):
            RenewalStage.objects.filter(id=sid).update(sort_order=i)
    return list_stages()


def _slugify_key(label: str) -> str:
    import re
    base = re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_') or 'stage'
    return base


def _stage_dict(st) -> dict:
    return {'id': st.id, 'key': st.key, 'label': st.label, 'color': st.color,
            'kind': st.kind, 'is_auto': st.is_auto, 'sort_order': st.sort_order}
```

- [ ] **Step 3: views — read staff, write superadmin (`ReadStaffWriteSuperAdmin`)**

```python
from apps.core.permissions import ReadStaffWriteSuperAdmin
from apps.renewals.serializers import StageReorderSerializer, StageWriteSerializer


class RenewalStageListView(APIView):
    permission_classes = [ReadStaffWriteSuperAdmin]

    def get(self, request):
        return Response(services.list_stages())

    def post(self, request):
        ser = StageWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(services.create_stage(ser.validated_data), status=status.HTTP_201_CREATED)


class RenewalStageDetailView(APIView):
    permission_classes = [ReadStaffWriteSuperAdmin]

    def patch(self, request, pk):
        ser = StageWriteSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        result = services.update_stage(pk, ser.validated_data)
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)

    def delete(self, request, pk):
        outcome = services.delete_stage(pk)
        if outcome == 'not_found':
            raise NotFound({'error': 'Not found'})
        if outcome in ('has_open_deals', 'protected'):
            return Response({'error': outcome}, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RenewalStageReorderView(APIView):
    permission_classes = [ReadStaffWriteSuperAdmin]

    def post(self, request):
        ser = StageReorderSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(services.reorder_stages(ser.validated_data['order']))
```

В `urls.py` (ПЕРЕД `/<int:pk>` detail, чтобы `stages` не парсился как id — но `stages` не число, конфликта нет; всё же держим специфичные выше):

```python
    path('/stages', RenewalStageListView.as_view(), name='renewals-stages'),
    path('/stages/reorder', RenewalStageReorderView.as_view(), name='renewals-stages-reorder'),
    path('/stages/<int:pk>', RenewalStageDetailView.as_view(), name='renewals-stage-detail'),
```

Плюс `services.py`-обёртки для всех stage-методов.

- [ ] **Step 4: Тесты (manager читает, менеджеру write запрещён, super создаёт)**

```python
import pytest

BASE = '/api/admin/renewals/stages'


@pytest.mark.django_db
def test_manager_reads_stages(manager_client):
    assert manager_client.get(BASE).status_code == 200


@pytest.mark.django_db
def test_manager_cannot_create(manager_client):
    resp = manager_client.post(BASE, {'label': 'X', 'kind': 'decision'}, format='json')
    assert resp.status_code == 403


@pytest.mark.django_db
def test_super_creates_and_deletes(superadmin_client):
    resp = superadmin_client.post(BASE, {'label': 'Перезвонить позже', 'kind': 'decision',
                                         'color': '#AABBCC'}, format='json')
    assert resp.status_code == 201
    sid = resp.json()['id']
    assert superadmin_client.delete(f'{BASE}/{sid}').status_code == 204
```

- [ ] **Step 5: Запустить**

Run: `cd journal_django && pytest apps/renewals/tests/test_stages_api.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/renewals
git commit -m "feat(renewals): CRUD и reorder стадий (read staff / write superadmin)"
```

### Task 4.2: Полный прогон бэка

- [ ] **Step 1: Прогнать весь набор тестов**

Run: `cd journal_django && pytest -q`
Expected: PASS (существующие + новые renewals). Ноль регрессов.

- [ ] **Step 2: Commit (если были правки)** — иначе перейти к фронту.

---

## ФАЗА 5. Фронт: навигация, список, канбан, drawer

### Task 5.1: Навигация, права, роуты

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/permissions.ts`
- Modify: `journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx`
- Modify: `journal_django/frontend/admin-src/src/App.tsx`

- [ ] **Step 1: Право видимости раздела**

В `lib/permissions.ts` добавить: `export const canSeeRenewals = isStaff;`

- [ ] **Step 2: Пункт навигации + иконка**

В `Sidebar.tsx` в объект `NAV_ICONS` добавить ключ `renewals` (иконка «повтор/цикл»):

```tsx
  renewals: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10"/>
      <polyline points="1 20 1 14 7 14"/>
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
    </svg>
  ),
```

В массив `SECTIONS` добавить (после `subscriptions`):

```tsx
  { key: 'renewals', label: 'Продления', path: '/admin/renewals' },
```

(`renewals` виден всем staff — доступ уже ограничен на API; дополнительной фильтрации в `visibleSections` не требуется, как у большинства разделов.)

- [ ] **Step 3: Роуты**

В `App.tsx` импортировать страницы и добавить роуты под `AppShell`:

```tsx
import RenewalsPage from './pages/renewals/RenewalsPage';
import RenewalAnalyticsPage from './pages/renewals/RenewalAnalyticsPage';
import RenewalStagesSettings from './pages/renewals/RenewalStagesSettings';
// ...
            <Route path="/admin/renewals" element={<RequireRole roles={['manager','admin','superadmin']}><RenewalsPage /></RequireRole>} />
            <Route path="/admin/renewals/analytics" element={<RequireRole roles={['manager','admin','superadmin']}><RenewalAnalyticsPage /></RequireRole>} />
            <Route path="/admin/renewals/stages" element={<RequireRole roles={['superadmin']}><RenewalStagesSettings /></RequireRole>} />
```

- [ ] **Step 4: Проверка сборки (упадёт — страниц ещё нет; это ожидаемо до 5.3)**

Отложить typecheck до создания страниц; сейчас только зафиксировать нав/права после создания страниц. Порядок: сначала 5.2–5.3 создают страницы, потом единый typecheck. **Пока не коммитить** App.tsx-роуты отдельно — коммит вместе с 5.3.

### Task 5.2: Типы и хуки TanStack Query

**Files:**
- Create: `journal_django/frontend/admin-src/src/lib/renewals.ts`
- Create: `journal_django/frontend/admin-src/src/hooks/useRenewals.ts`
- Create: `journal_django/frontend/admin-src/src/hooks/useRenewalStages.ts`

- [ ] **Step 1: Типы**

```ts
// lib/renewals.ts
export type StageKind = 'progress' | 'decision' | 'won' | 'lost';

export interface RenewalStage {
  id: number; key: string; label: string; color: string | null;
  kind: StageKind; is_auto: boolean; sort_order: number;
}

export interface RenewalCard {
  id: number; student_name: string; direction_name: string;
  direction_color: string | null; cycle_no: number;
  expected_amount: string | null; next_touch_at: string | null;
  assignee_name: string | null; days_in_stage: number;
}

export interface RenewalColumn {
  stage_id: number; key: string; label: string; kind: StageKind;
  color: string | null; count: number; sum_potential: number; cards: RenewalCard[];
}

export interface RenewalBoard { columns: RenewalColumn[]; }

export interface RenewalDealDetail extends RenewalCard {
  stage_id: number; stage_key: string; stage_label: string; stage_kind: StageKind;
  student_id: number; direction_id: number; balance: number;
  lesson_in_cycle: number; reason_code: string | null; outcome_at: string | null;
}

export interface RenewalActivityItem {
  id: number; kind: string; body: string | null; created_at: string;
  from_label: string | null; to_label: string | null;
  author_name: string | null; payment_id: number | null;
}

export interface RenewalFilters {
  assignee_id?: string; direction_id?: string; stage_id?: string; overdue?: string;
}
```

- [ ] **Step 2: Хуки досок/списка/мутаций** (оптимистичный move)

```ts
// hooks/useRenewals.ts
import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type {
  RenewalBoard, RenewalDealDetail, RenewalActivityItem, RenewalFilters,
} from '../lib/renewals';
import type { Paginated } from '../lib/types';

const KEY = ['renewals'] as const;

function filterQS(f: RenewalFilters): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v) qs.set(`filter[${k}]`, v);
  return qs.toString();
}

export function useRenewalBoard(filters: RenewalFilters) {
  return useQuery({
    queryKey: [...KEY, 'board', filters],
    queryFn: () => api<RenewalBoard>('GET', `/api/admin/renewals?view=board&${filterQS(filters)}`),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export interface RenewalListParams {
  page: number; page_size: number; sort_by: string; sort_dir: 'asc' | 'desc';
  filters: RenewalFilters;
}

export function useRenewalList(p: RenewalListParams) {
  const qs = new URLSearchParams({
    view: 'list', page: String(p.page), page_size: String(p.page_size),
    sort_by: p.sort_by, sort_dir: p.sort_dir,
  });
  for (const [k, v] of Object.entries(p.filters)) if (v) qs.set(`filter[${k}]`, v);
  return useQuery({
    queryKey: [...KEY, 'list', p],
    queryFn: () => api<Paginated<RenewalDealDetail>>('GET', `/api/admin/renewals?${qs}`),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useRenewalDeal(id: number | null) {
  return useQuery({
    queryKey: [...KEY, 'deal', id],
    queryFn: () => api<RenewalDealDetail>('GET', `/api/admin/renewals/${id}`),
    enabled: !!id,
  });
}

export function useRenewalActivity(id: number | null) {
  return useQuery({
    queryKey: [...KEY, 'activity', id],
    queryFn: () => api<RenewalActivityItem[]>('GET', `/api/admin/renewals/${id}/activity`),
    enabled: !!id,
  });
}

export function useRenewalMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ['renewals'] });
  return {
    move: useMutation({
      mutationFn: ({ id, to_stage_id, reason_code }:
        { id: number; to_stage_id: number; reason_code?: string }) =>
        api<RenewalDealDetail>('POST', `/api/admin/renewals/${id}/move`, { to_stage_id, reason_code }),
      onSuccess: invalidate,
    }),
    patch: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
        api<RenewalDealDetail>('PATCH', `/api/admin/renewals/${id}`, body),
      onSuccess: invalidate,
    }),
    comment: useMutation({
      mutationFn: ({ id, body }: { id: number; body: string }) =>
        api('POST', `/api/admin/renewals/${id}/comment`, { body }),
      onSuccess: (_r, v) => qc.invalidateQueries({ queryKey: ['renewals', 'activity', v.id] }),
    }),
  };
}
```

- [ ] **Step 3: Хук стадий**

```ts
// hooks/useRenewalStages.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { RenewalStage } from '../lib/renewals';

export function useRenewalStages() {
  return useQuery({
    queryKey: ['renewals', 'stages'],
    queryFn: () => api<RenewalStage[]>('GET', '/api/admin/renewals/stages'),
    staleTime: 60_000,
  });
}

export function useRenewalStageMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ['renewals'] });
  return {
    create: useMutation({
      mutationFn: (body: Partial<RenewalStage>) =>
        api<RenewalStage>('POST', '/api/admin/renewals/stages', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Partial<RenewalStage> }) =>
        api<RenewalStage>('PATCH', `/api/admin/renewals/stages/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<void>('DELETE', `/api/admin/renewals/stages/${id}`),
      onSuccess: invalidate,
    }),
    reorder: useMutation({
      mutationFn: (order: number[]) =>
        api<RenewalStage[]>('POST', '/api/admin/renewals/stages/reorder', { order }),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Step 4: Commit** (хуки/типы компилируются сами по себе; страницы — далее)

```bash
git add journal_django/frontend/admin-src/src/lib/renewals.ts journal_django/frontend/admin-src/src/hooks/useRenewals.ts journal_django/frontend/admin-src/src/hooks/useRenewalStages.ts
git commit -m "feat(renewals-fe): типы и TanStack-хуки раздела продлений"
```

### Task 5.3: Страница-оболочка + переключатель вида + фильтры

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/renewals/RenewalsPage.tsx`
- Modify: `lib/labels.ts` (подписи стадий/причин)

- [ ] **Step 1: Подписи в `lib/labels.ts`**

Добавить словари (использовать существующий стиль файла):

```ts
export const RENEWAL_STAGE_LABELS: Record<string, string> = {
  lesson_progress: 'Урок 1–4', awaiting_payment: 'Ждём оплату', thinking: 'Думает',
  frozen: 'Заморожен', ignoring: 'Игнорит', renewed: 'Продлён', churned: 'Ушёл',
};
export const RENEWAL_REASON_LABELS: Record<string, string> = {
  price: 'Дорого', schedule: 'Неудобное расписание', result: 'Нет результата',
  pause: 'Временная пауза', other: 'Другое',
};
```

- [ ] **Step 2: RenewalsPage (тумблер Канбан/Список, фильтры через useListSearchParams)**

```tsx
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { RenewalBoard } from './RenewalBoard';
import { RenewalList } from './RenewalList';
import { RenewalDrawer } from './RenewalDrawer';
import type { RenewalFilters } from '../../lib/renewals';

export default function RenewalsPage() {
  const [sp, setSp] = useSearchParams();
  const view = sp.get('view') === 'list' ? 'list' : 'board';
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const filters: RenewalFilters = {
    assignee_id: sp.get('assignee_id') ?? undefined,
    direction_id: sp.get('direction_id') ?? undefined,
    overdue: sp.get('overdue') ?? undefined,
  };
  const setView = (v: 'board' | 'list') => { sp.set('view', v); setSp(sp, { replace: true }); };

  return (
    <div className="page">
      <div className="page-header">
        <h1>Продления</h1>
        <div className="view-toggle" role="tablist">
          <button className={view === 'board' ? 'active' : ''} onClick={() => setView('board')}>Канбан</button>
          <button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}>Список</button>
        </div>
      </div>
      {/* TODO-фильтры: SelectInput менеджер/направление + чекбокс «просроченные» */}
      {view === 'board'
        ? <RenewalBoard filters={filters} onOpen={setSelectedId} />
        : <RenewalList filters={filters} onOpen={setSelectedId} />}
      {selectedId && <RenewalDrawer id={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  );
}
```

> Стили `.view-toggle`, `.page-header` — из существующих токенов/утилит проекта. Если классов нет —
> добавить в локальный css-модуль раздела, используя только переменные `tokens.css` (никаких hex).

- [ ] **Step 3: Заглушки дочерних компонентов** (чтобы собралось)

Создать минимальные `RenewalBoard.tsx`, `RenewalList.tsx`, `RenewalDrawer.tsx`, `RenewalAnalyticsPage.tsx`, `RenewalStagesSettings.tsx`, экспортирующие пустой компонент-заглушку (наполним в 5.4–5.6, 6.x). Пример заглушки:

```tsx
export function RenewalBoard(_: { filters: unknown; onOpen: (id: number) => void }) {
  return <div>Канбан скоро</div>;
}
```

- [ ] **Step 4: Тайпчек + сборка**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: сборка успешна (роуты из 5.1 теперь резолвятся).

- [ ] **Step 5: Commit** (нав + права + роуты + оболочка вместе)

```bash
git add journal_django/frontend/admin-src/src
git commit -m "feat(renewals-fe): навигация, роуты, оболочка страницы с переключателем вида"
```

### Task 5.4: Списочный вид (data-table)

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/renewals/RenewalList.tsx`

- [ ] **Step 1: Реализовать список** через существующие табличные компоненты (`components/table/`) и `StatusBadge`, server-pagination как в `StudentsListPage`.

```tsx
import { useState } from 'react';
import { useRenewalList } from '../../hooks/useRenewals';
import { StatusBadge } from '../../components/StatusBadge';
import { RENEWAL_STAGE_LABELS } from '../../lib/labels';
import type { RenewalFilters } from '../../lib/renewals';

export function RenewalList({ filters, onOpen }:
  { filters: RenewalFilters; onOpen: (id: number) => void }) {
  const [page, setPage] = useState(1);
  const { data, isFetching } = useRenewalList({
    page, page_size: 50, sort_by: 'stage_entered_at', sort_dir: 'desc', filters,
  });
  return (
    <div className={`data-table${isFetching ? ' data-table--loading' : ''}`}>
      <table>
        <thead><tr>
          <th>Ученик</th><th>Направление</th><th>Цикл</th><th>Стадия</th>
          <th>Дней в стадии</th><th>След. касание</th><th>Ответственный</th>
        </tr></thead>
        <tbody>
          {(data?.rows ?? []).map((r) => (
            <tr key={r.id} onClick={() => onOpen(r.id)} style={{ cursor: 'pointer' }}>
              <td>{r.student_name}</td>
              <td>{r.direction_name}</td>
              <td>Мес. {r.cycle_no}</td>
              <td><StatusBadge>{r.stage_label ?? RENEWAL_STAGE_LABELS[r.stage_key]}</StatusBadge></td>
              <td>{r.days_in_stage}</td>
              <td>{r.next_touch_at ?? '—'}</td>
              <td>{r.assignee_name ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {/* Пагинация: переиспользовать общий Pagination-компонент проекта */}
    </div>
  );
}
```

> Свериться с фактическим API `StatusBadge` и табличных компонентов (`components/table/`) — при
> расхождении сигнатуры адаптировать пропсы. `.data-table--loading` гасит pointer-events на `tbody`.

- [ ] **Step 2: Сборка**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: успех.

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/renewals/RenewalList.tsx
git commit -m "feat(renewals-fe): списочный вид продлений с пагинацией"
```

### Task 5.5: Канбан-доска на @dnd-kit

**Files:**
- Modify: `journal_django/frontend/admin-src/package.json` (+ `@dnd-kit/core`)
- Modify: `RenewalBoard.tsx`
- Create: `RenewalColumn.tsx`, `RenewalCardView.tsx`

- [ ] **Step 1: Установить зависимость**

Run: `cd journal_django/frontend/admin-src && npm install @dnd-kit/core`
Expected: пакет добавлен в `package.json`/lock.

- [ ] **Step 2: Карточка `RenewalCardView.tsx`** (draggable)

```tsx
import { useDraggable } from '@dnd-kit/core';
import type { RenewalCard } from '../../lib/renewals';

export function RenewalCardView({ card, onOpen }:
  { card: RenewalCard; onOpen: (id: number) => void }) {
  const { attributes, listeners, setNodeRef, transform } = useDraggable({ id: card.id });
  const style = transform
    ? { transform: `translate(${transform.x}px, ${transform.y}px)` } : undefined;
  const overdue = card.days_in_stage > 5; // SLA-подсветка (порог вынести в токен/константу)
  return (
    <div ref={setNodeRef} style={style} {...listeners} {...attributes}
         className={`renewal-card${overdue ? ' renewal-card--overdue' : ''}`}
         onClick={() => onOpen(card.id)}>
      <div className="renewal-card__name">{card.student_name}</div>
      <div className="renewal-card__dir" style={{ color: card.direction_color ?? undefined }}>
        {card.direction_name} · Мес. {card.cycle_no}
      </div>
      <div className="renewal-card__meta">
        {overdue && <span className="badge-warn">⚠ {card.days_in_stage} дн</span>}
        {card.assignee_name && <span>👤 {card.assignee_name}</span>}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Колонка `RenewalColumn.tsx`** (droppable)

```tsx
import { useDroppable } from '@dnd-kit/core';
import { RenewalCardView } from './RenewalCardView';
import type { RenewalColumn as Col } from '../../lib/renewals';

export function RenewalColumn({ col, onOpen }:
  { col: Col; onOpen: (id: number) => void }) {
  const { setNodeRef, isOver } = useDroppable({ id: col.stage_id });
  return (
    <div ref={setNodeRef} className={`renewal-col${isOver ? ' renewal-col--over' : ''}`}>
      <div className="renewal-col__head" style={{ borderColor: col.color ?? undefined }}>
        <span>{col.label}</span>
        <span className="renewal-col__count">
          {col.count}{col.sum_potential ? ` · ${col.sum_potential.toLocaleString('ru')}₽` : ''}
        </span>
      </div>
      <div className="renewal-col__body">
        {col.cards.map((c) => <RenewalCardView key={c.id} card={c} onOpen={onOpen} />)}
        {col.count > col.cards.length && (
          <button className="renewal-col__more">Показать ещё ({col.count - col.cards.length})</button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Доска `RenewalBoard.tsx`** (DnD-контекст + оптимистичный move + rollback)

```tsx
import { DndContext, DragEndEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { useQueryClient } from '@tanstack/react-query';
import { RenewalColumn } from './RenewalColumn';
import { useRenewalBoard, useRenewalMutations } from '../../hooks/useRenewals';
import type { RenewalBoard as Board, RenewalFilters } from '../../lib/renewals';

export function RenewalBoard({ filters, onOpen }:
  { filters: RenewalFilters; onOpen: (id: number) => void }) {
  const { data } = useRenewalBoard(filters);
  const { move } = useRenewalMutations();
  const qc = useQueryClient();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  function onDragEnd(e: DragEndEvent) {
    const dealId = Number(e.active.id);
    const toStageId = e.over ? Number(e.over.id) : null;
    if (!toStageId) return;
    const key = ['renewals', 'board', filters];
    const prev = qc.getQueryData<Board>(key);
    // оптимистично перемещаем карточку между колонками
    if (prev) {
      let moved: Board['columns'][number]['cards'][number] | undefined;
      const columns = prev.columns.map((c) => {
        const found = c.cards.find((x) => x.id === dealId);
        if (found) moved = found;
        return { ...c, cards: c.cards.filter((x) => x.id !== dealId) };
      });
      if (moved) {
        const target = columns.find((c) => c.stage_id === toStageId);
        if (target) target.cards = [moved, ...target.cards];
      }
      qc.setQueryData<Board>(key, { columns });
    }
    move.mutate({ id: dealId, to_stage_id: toStageId }, {
      onError: () => { if (prev) qc.setQueryData(key, prev); }, // rollback
    });
  }

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <div className="renewal-board">
        {(data?.columns ?? []).map((col) => (
          <RenewalColumn key={col.stage_id} col={col} onOpen={onOpen} />
        ))}
      </div>
    </DndContext>
  );
}
```

> Стили `.renewal-board/.renewal-col*/.renewal-card*` — новый css-модуль, значения только из `tokens.css`.
> `.renewal-board { display: flex; gap: var(--space-…); overflow-x: auto; }` — колонки скроллятся горизонтально.

- [ ] **Step 5: Сборка + ручной смоук**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: успех. Затем ручной прогон (`docs/admin-smoke-tests.md`): открыть `/admin/renewals`,
перетащить карточку между колонками, убедиться, что после reload стадия сохранилась; запрещённый
переход (из «Продлён») откатывается и показывает ошибку.

- [ ] **Step 6: Commit**

```bash
git add journal_django/frontend/admin-src/package.json journal_django/frontend/admin-src/package-lock.json journal_django/frontend/admin-src/src/pages/renewals
git commit -m "feat(renewals-fe): канбан-доска с DnD и оптимистичным перемещением"
```

### Task 5.6: Drawer карточки (детали, оплата, таймлайн, комментарий)

**Files:**
- Modify: `RenewalDrawer.tsx`

- [ ] **Step 1: Реализовать drawer**

```tsx
import { useState } from 'react';
import { useRenewalDeal, useRenewalActivity, useRenewalMutations } from '../../hooks/useRenewals';
import { usePaymentModal } from '../../providers/PaymentModalProvider';
import { EntityLink } from '../../components/EntityLink';

export function RenewalDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const { data: deal } = useRenewalDeal(id);
  const { data: activity } = useRenewalActivity(id);
  const { comment } = useRenewalMutations();
  const { open: openPayment } = usePaymentModal();
  const [text, setText] = useState('');
  if (!deal) return null;
  return (
    <aside className="drawer" role="dialog">
      <header className="drawer__head">
        <EntityLink kind="student" id={deal.student_id}>{deal.student_name}</EntityLink>
        <button onClick={onClose} aria-label="Закрыть">✕</button>
      </header>
      <section className="drawer__body">
        <div>{deal.direction_name} · Мес. {deal.cycle_no} · Урок {deal.lesson_in_cycle}/4</div>
        <div>Баланс: {deal.balance}</div>
        <button className="btn btn--primary"
                onClick={() => openPayment({ studentId: deal.student_id, directionId: deal.direction_id })}>
          Внести оплату
        </button>

        <h4>Комментарий</h4>
        <textarea value={text} onChange={(e) => setText(e.target.value)} />
        <button disabled={!text.trim()}
                onClick={() => comment.mutate({ id, body: text }, { onSuccess: () => setText('') })}>
          Добавить
        </button>

        <h4>История</h4>
        <ul className="timeline">
          {(activity ?? []).map((a) => (
            <li key={a.id}>
              <span className="timeline__when">{new Date(a.created_at).toLocaleString('ru')}</span>
              {a.kind === 'stage_change' && <span>{a.from_label} → {a.to_label}</span>}
              {a.kind === 'comment' && <span>💬 {a.body}</span>}
              {a.kind === 'payment_linked' && <span>💰 Оплата #{a.payment_id}</span>}
              {a.author_name && <span className="timeline__who"> · {a.author_name}</span>}
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}
```

> Сверить фактические сигнатуры `usePaymentModal().open(...)` и `EntityLink` (props `kind/id`) с
> реализацией в `providers/PaymentModalProvider` и `components/EntityLink.tsx`; адаптировать вызовы.

- [ ] **Step 2: Сборка + смоук**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: успех. Смоук: открыть карточку, добавить комментарий (появляется в истории),
нажать «Внести оплату» → открывается модалка с предзаполненным учеником/направлением.

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/renewals/RenewalDrawer.tsx
git commit -m "feat(renewals-fe): drawer сделки — таймлайн, комментарии, оплата из карточки"
```

---

## ФАЗА 6. Настройка воронки, напоминания, аналитика

### Task 6.1: Экран настройки стадий (superadmin)

**Files:**
- Modify: `RenewalStagesSettings.tsx`

- [ ] **Step 1: Реализовать CRUD-экран стадий** через `useRenewalStages` + `useRenewalStageMutations` (создать/переименовать/цвет/вид/удалить; порядок — кнопками ↑/↓, вызывающими `reorder`). Форма — только `SelectInput` для `kind`, `DateInput` не нужен; цвет — валидируемый текст `#RRGGBB`.

```tsx
import { useRenewalStages, useRenewalStageMutations } from '../../hooks/useRenewalStages';

export default function RenewalStagesSettings() {
  const { data: stages } = useRenewalStages();
  const m = useRenewalStageMutations();
  return (
    <div className="page">
      <h1>Стадии воронки продлений</h1>
      <ul>
        {(stages ?? []).map((s, i) => (
          <li key={s.id}>
            <span style={{ color: s.color ?? undefined }}>{s.label}</span> · {s.kind}
            <button disabled={i === 0}
                    onClick={() => m.reorder.mutate(reorderUp(stages!, i))}>↑</button>
            {!s.is_auto && <button onClick={() => m.remove.mutate(s.id)}>Удалить</button>}
          </li>
        ))}
      </ul>
      {/* Форма создания: label + SelectInput(kind) + color */}
    </div>
  );
}

function reorderUp(stages: { id: number }[], i: number): number[] {
  const ids = stages.map((s) => s.id);
  [ids[i - 1], ids[i]] = [ids[i], ids[i - 1]];
  return ids;
}
```

- [ ] **Step 2: Сборка + смоук** (доступ только superadmin; manager получает 403 на write).

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: успех.

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/renewals/RenewalStagesSettings.tsx
git commit -m "feat(renewals-fe): экран настройки стадий воронки (superadmin)"
```

### Task 6.2: Напоминания — дайджест касаний (SMTP)

**Files:**
- Create: `journal_django/apps/renewals/management/commands/send_renewal_reminders.py`
- Test: `journal_django/apps/renewals/tests/test_reminders.py`

- [ ] **Step 1: Реализовать команду**

```python
"""
Дайджест касаний: для каждого менеджера — открытые сделки с next_touch_at <= сегодня.
Шлёт письмо через настроенный Django email backend (Beget SMTP из .env).
"""
from __future__ import annotations

from collections import defaultdict

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Рассылает менеджерам напоминания о касаниях продлений на сегодня.'

    def handle(self, *args, **options):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT a.email, a.full_name, s.full_name AS student, dir.name AS direction,
                       st.label AS stage, d.next_touch_at
                FROM renewal_deal d
                JOIN accounts a ON a.id = d.assignee_id
                JOIN students s ON s.id = d.student_id
                JOIN directions dir ON dir.id = d.direction_id
                JOIN renewal_stage st ON st.id = d.stage_id
                WHERE d.outcome_at IS NULL AND d.next_touch_at IS NOT NULL
                  AND d.next_touch_at <= now()::date
                ORDER BY a.email, d.next_touch_at
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        by_email: dict[str, list] = defaultdict(list)
        for r in rows:
            by_email[r['email']].append(r)

        sent = 0
        for email, items in by_email.items():
            lines = [f"— {it['student']} · {it['direction']} · {it['stage']} "
                     f"(касание {it['next_touch_at']})" for it in items]
            send_mail(
                subject=f'Продления на сегодня: {len(items)}',
                message='Задачи по продлениям:\n' + '\n'.join(lines),
                from_email=None, recipient_list=[email], fail_silently=True)
            sent += 1
        self.stdout.write(self.style.SUCCESS(f'renewals: отправлено дайджестов: {sent}'))
```

- [ ] **Step 2: Тест (через `locmem` email backend)**

```python
import pytest
from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from apps.renewals import engine
from apps.renewals.models import RenewalDeal


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
def test_reminder_digest_sends(make_student, make_direction, admin_client):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    # назначаем ответственного и просроченное касание
    RenewalDeal.objects.filter(id=deal.id).update(
        assignee_id=_root_manager_id(), next_touch_at='2020-01-01')
    call_command('send_renewal_reminders')
    assert len(mail.outbox) >= 1
```

> `_root_manager_id()` — получить id аккаунта менеджера (создать через тот же helper, что в conftest,
> либо переиспользовать `manager_client` для порождения аккаунта; уточнить при реализации).

- [ ] **Step 3: Запустить**

Run: `cd journal_django && pytest apps/renewals/tests/test_reminders.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add journal_django/apps/renewals/management/commands/send_renewal_reminders.py journal_django/apps/renewals/tests/test_reminders.py
git commit -m "feat(renewals): дайджест напоминаний о касаниях (SMTP)"
```

### Task 6.3: Аналитика конверсии (API)

**Files:**
- Create: `journal_django/apps/renewals/analytics.py`
- Modify: `services.py`, `views.py`, `urls.py`
- Test: `journal_django/apps/renewals/tests/test_analytics.py`

- [ ] **Step 1: Реализовать `analytics.funnel()`**

```python
"""Аналитика продлений: воронка по стадиям + сводные KPI."""
from __future__ import annotations

from django.db import connection


def funnel(group_by: str | None = None) -> dict:
    """
    Распределение открытых сделок по стадиям + renewal rate за 30 дней
    (won / (won + lost) среди закрытых).
    """
    with connection.cursor() as cur:
        cur.execute("""
            SELECT st.key, st.label, st.kind, COUNT(*) AS cnt,
                   COALESCE(SUM(d.expected_amount),0) AS sum_amt
            FROM renewal_deal d JOIN renewal_stage st ON st.id = d.stage_id
            WHERE d.outcome_at IS NULL
            GROUP BY st.key, st.label, st.kind, st.sort_order
            ORDER BY st.sort_order
        """)
        cols = [c[0] for c in cur.description]
        stages = [dict(zip(cols, r)) for r in cur.fetchall()]

        cur.execute("""
            SELECT st.kind, COUNT(*) FROM renewal_deal d
            JOIN renewal_stage st ON st.id = d.stage_id
            WHERE d.outcome_at IS NOT NULL AND d.outcome_at >= now() - interval '30 days'
            GROUP BY st.kind
        """)
        closed = {r[0]: r[1] for r in cur.fetchall()}
    won, lost = closed.get('won', 0), closed.get('lost', 0)
    rate = round(won / (won + lost) * 100, 1) if (won + lost) else None
    return {'stages': stages, 'renewal_rate_30d': rate, 'won_30d': won, 'lost_30d': lost}
```

- [ ] **Step 2: View + маршрут** (`GET /api/admin/renewals/analytics`, `IsManagerOrAdmin`)

В `views.py`:

```python
class RenewalAnalyticsView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        from apps.renewals import analytics
        return Response(analytics.funnel(request.query_params.get('group_by')))
```

В `urls.py`: `path('/analytics', RenewalAnalyticsView.as_view(), name='renewals-analytics'),`
(разместить ПЕРЕД `/<int:pk>`, чтобы `analytics` не парсился как id — `analytics` не число, но держим специфичные выше для ясности).

- [ ] **Step 3: Тест**

```python
import pytest
from apps.renewals import engine


@pytest.mark.django_db
def test_analytics_shape(manager_client, make_student, make_direction):
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    body = manager_client.get('/api/admin/renewals/analytics').json()
    assert 'stages' in body and 'renewal_rate_30d' in body
```

- [ ] **Step 4: Запустить**

Run: `cd journal_django && pytest apps/renewals/tests/test_analytics.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals/analytics.py journal_django/apps/renewals/services.py journal_django/apps/renewals/views.py journal_django/apps/renewals/urls.py journal_django/apps/renewals/tests/test_analytics.py
git commit -m "feat(renewals): API аналитики воронки конверсии"
```

### Task 6.4: Экран аналитики (Recharts 3)

**Files:**
- Modify: `RenewalAnalyticsPage.tsx`
- Create: `hooks/useRenewalAnalytics.ts`

- [ ] **Step 1: Хук**

```ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';

export interface RenewalFunnel {
  stages: { key: string; label: string; kind: string; cnt: number; sum_amt: number }[];
  renewal_rate_30d: number | null; won_30d: number; lost_30d: number;
}
export function useRenewalAnalytics() {
  return useQuery({
    queryKey: ['renewals', 'analytics'],
    queryFn: () => api<RenewalFunnel>('GET', '/api/admin/renewals/analytics'),
    staleTime: 60_000,
  });
}
```

- [ ] **Step 2: Экран с KPI + баровой воронкой** (Recharts 3 — стек графиков проекта; палитра — из dataviz/tokens)

```tsx
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { useRenewalAnalytics } from '../../hooks/useRenewalAnalytics';

export default function RenewalAnalyticsPage() {
  const { data } = useRenewalAnalytics();
  if (!data) return null;
  return (
    <div className="page">
      <h1>Аналитика продлений</h1>
      <div className="kpi-row">
        <div className="kpi"><div className="kpi__val">{data.renewal_rate_30d ?? '—'}%</div>
          <div className="kpi__label">Renewal rate (30д)</div></div>
        <div className="kpi"><div className="kpi__val">{data.won_30d}</div>
          <div className="kpi__label">Продлили</div></div>
        <div className="kpi"><div className="kpi__val">{data.lost_30d}</div>
          <div className="kpi__label">Ушли</div></div>
      </div>
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={data.stages}>
          <XAxis dataKey="label" /><YAxis allowDecimals={false} /><Tooltip />
          <Bar dataKey="cnt" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
```

> Цвета баров/KPI — только из токенов/палитры dataviz (см. skill `dataviz`); никаких hardcoded hex.

- [ ] **Step 3: Сборка + смоук**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: успех. Смоук: `/admin/renewals/analytics` показывает KPI и распределение по стадиям.

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/renewals/RenewalAnalyticsPage.tsx journal_django/frontend/admin-src/src/hooks/useRenewalAnalytics.ts
git commit -m "feat(renewals-fe): экран аналитики воронки (Recharts)"
```

---

## Финальная приёмка (после всех фаз)

- [ ] **Бэк — полный прогон:** `cd journal_django && pytest -q` → всё зелёное, ноль регрессов.
- [ ] **Реестр журнала:** `pytest apps/changelog -q -k registry` → PASS (4 модели renewals покрыты).
- [ ] **Фронт — сборка:** `cd journal_django/frontend/admin-src && npm run build` → успех.
- [ ] **RBAC-матрица вручную:** teacher → 403 на всех `/api/admin/renewals*`; manager → доска/список/move/patch/comment 200, конфиг стадий read 200 / write 403; superadmin → всё 200.
- [ ] **Смоук-сценарий продления:** создать оплату ученику → его сделка ушла в «Продлён», появилась карточка следующего цикла; перетащить карточку в «Заморожен» → активность записана, стадия сохранилась после reload.
- [ ] **Журнал изменений:** операции `renewal.move/update/comment/stage_*` отображаются с русскими подписями, а не `other`; откат перемещения работает из строки журнала.
- [ ] **Ночные команды:** `rebuild_renewal_deals` идемпотентна (повторный запуск не плодит дубли); `send_renewal_reminders` шлёт дайджест только по просроченным касаниям.
- [ ] Обновить `docs/BACKLOG.md`/`docs/ROADMAP.md`: раздел «Продления» — сделано; отметить возможные доработки (несколько воронок, drag-сортировка стадий, экспорт списка).

---

## Замечания по исполнению (важно свериться при реализации)

1. **Имя колонки направления в `groups`** — ✅ подтверждено: `groups.direction_id` (`apps/groups/models.py`). JOIN `g.direction_id` корректны. При вставках в `groups` в тестах помнить: `is_individual` и `created_at` — NOT NULL без дефолта, задавать явно.
2. **`balance_for_direction`** — ✅ подтверждено: `apps/finances/repository.balance_for_direction(student_id, direction_id) -> int | float`. Импорт `from apps.finances.repository import balance_for_direction`.
3. **`Payment.objects.create`** триггерит сигнал — убедиться, что боевой код создания оплаты идёт через ORM (`apps/payments/repository.create_payment`), а не raw SQL; если raw — вызвать `engine.close_deal_won` явно из `payments.repository.create_payment` вместо/вдобавок к сигналу.
4. **`api<T>()`** — сверить сигнатуру (`api('GET', url)` vs `api({method,url})`) по `lib/api.ts`; в плане — `api('METHOD', url, body?)` как в `useStudents.ts`.
5. **Табличные/бейдж-компоненты** (`components/table/`, `StatusBadge`, `EntityLink`, `usePaymentModal`) — адаптировать пропсы под фактические сигнатуры.
6. **CSS-классы** раздела — новый css-модуль на переменных `tokens.css`; ни одного hardcoded цвета/отступа.
7. **Порядок mount в urls** — `/api/admin/renewals` держать среди admin-разделов (после auth, admin выше teacher-guard), как прочие.
```
