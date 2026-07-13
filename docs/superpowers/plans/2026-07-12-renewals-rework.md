# Переработка раздела «Продления» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **ВАЖНО (правило проекта):** коммиты/пуши — ТОЛЬКО по явной просьбе пользователя. Вместо commit-шагов в этом плане — шаги верификации. Субагентам git запрещён.

**Goal:** Привести раздел «Продления» в рабочее состояние: честная автоматика стадий (без зацикливания «Урок 4 → Урок 1»), новая обязательная авто-стадия «Ждём продление», диалоги с объяснением операций, переоткрытие сделок, синхронизация с удалением оплат, живые CRM-поля в карточке, панель фильтров, когортная аналитика по месяцам.

**Architecture:** Бэкенд — доработка `apps/renewals/` (engine, signals, repository, views) + миграции 0004 (поле `due_at`) и 0005 (стадия `awaiting_renewal`, is_auto для `awaiting_payment`, backfill `due_at`). Фронт — доработка страниц `pages/renewals/*`: зоны закрытия при drag, диалоги закрытия (Radix `Dialog`), редактируемые поля в drawer, фильтры, вид «По месяцам» в аналитике.

**Tech Stack:** Django 5.1 / DRF / PostgreSQL / pghistory · React 19 / TanStack Query v5 / @dnd-kit / Radix Dialog · pytest.

**Spec:** `docs/superpowers/specs/2026-07-12-renewals-rework-design.md`

**Команды:**
- Тесты: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/renewals -q`
- Миграции: `./.venv/Scripts/python.exe manage.py makemigrations renewals && ./.venv/Scripts/python.exe manage.py migrate`
- Фронт: `cd journal_django/frontend/admin-src && npm run typecheck && npm run build`

---

## ФАЗА A. Бэкенд-движок

### Task 1: Миграции — поле `due_at` + стадия «Ждём продление»

**Files:**
- Modify: `journal_django/apps/renewals/models.py` (RenewalDeal: поле `due_at`)
- Create: `journal_django/apps/renewals/migrations/0004_renewaldeal_due_at.py` (makemigrations)
- Create: `journal_django/apps/renewals/migrations/0005_seed_awaiting_renewal.py` (руками)

- [ ] **Step 1: Добавить поле в модель** (после `next_touch_at`):

```python
    # Дата «созревания» продления: 4-й урок цикла отработан (ставит движок).
    # Основа когортной аналитики по месяцам. NULL — цикл ещё не отработан.
    due_at = models.DateField(null=True, blank=True)
```

- [ ] **Step 2: Сгенерировать и применить схемную миграцию**

Run: `./.venv/Scripts/python.exe manage.py makemigrations renewals` → `0004_...due_at`, затем `migrate`.

- [ ] **Step 3: Написать data-миграцию 0005**

```python
"""
Стадия «Ждём продление» (awaiting_renewal, авто) после «Ждём оплату»;
awaiting_payment становится авто-стадией; backfill due_at закрытым сделкам.
Открытые сделки разводит по новым правилам НЕ миграция, а
`manage.py rebuild_renewal_deals` (балансовая логика живёт в apps.finances).
"""
from django.db import migrations


def forward(apps, schema_editor):
    RenewalPipeline = apps.get_model('renewals', 'RenewalPipeline')
    RenewalStage = apps.get_model('renewals', 'RenewalStage')
    RenewalDeal = apps.get_model('renewals', 'RenewalDeal')

    pipe = RenewalPipeline.objects.get(is_default=True)
    ap = RenewalStage.objects.filter(pipeline=pipe, key='awaiting_payment').first()
    if ap is not None and not ap.is_auto:
        ap.is_auto = True
        ap.save(update_fields=['is_auto'])

    if not RenewalStage.objects.filter(pipeline=pipe, key='awaiting_renewal').exists():
        anchor = ap.sort_order if ap is not None else 4
        for st in RenewalStage.objects.filter(pipeline=pipe, sort_order__gt=anchor):
            st.sort_order += 1
            st.save(update_fields=['sort_order'])
        RenewalStage.objects.create(
            pipeline=pipe, key='awaiting_renewal', label='Ждём продление',
            color='#F97316', kind='decision', is_auto=True, sort_order=anchor + 1)

    # закрытым сделкам месяц когорты = месяц закрытия
    for deal in RenewalDeal.objects.filter(outcome_at__isnull=False, due_at__isnull=True):
        deal.due_at = deal.outcome_at.date()
        deal.save(update_fields=['due_at'])


def backward(apps, schema_editor):
    RenewalPipeline = apps.get_model('renewals', 'RenewalPipeline')
    RenewalStage = apps.get_model('renewals', 'RenewalStage')
    pipe = RenewalPipeline.objects.get(is_default=True)
    st = RenewalStage.objects.filter(pipeline=pipe, key='awaiting_renewal').first()
    if st is not None and not st.deals.exists():
        st.delete()


class Migration(migrations.Migration):
    dependencies = [('renewals', '0004_renewaldeal_due_at')]
    operations = [migrations.RunPython(forward, backward)]
```

- [ ] **Step 4: Применить, обновить тест сида** — в `tests/test_seed.py` добавить:

```python
@pytest.mark.django_db
def test_awaiting_renewal_stage_seeded():
    pipe = RenewalPipeline.objects.get(is_default=True)
    ar = RenewalStage.objects.get(pipeline=pipe, key='awaiting_renewal')
    ap = RenewalStage.objects.get(pipeline=pipe, key='awaiting_payment')
    assert ar.is_auto and ap.is_auto and ar.kind == 'decision'
    assert ar.sort_order == ap.sort_order + 1
```

- [ ] **Step 5: Verify** — `pytest apps/renewals/tests/test_seed.py -q` → PASS.

### Task 2: Engine — новая логика авто-стадий (фикс зацикливания, баланс, due_at)

**Files:**
- Modify: `journal_django/apps/renewals/engine.py`
- Test: `journal_django/apps/renewals/tests/test_lesson_progress.py` (обновить/дописать)

- [ ] **Step 1: Написать падающие тесты** (используют фикстуры conftest; membership с `lessons_done`, баланс без оплат отрицательный):

```python
@pytest.mark.django_db
def test_cycle_complete_moves_to_awaiting_renewal(make_student, make_direction, make_membership):
    sid, did = make_student(), make_direction()
    make_membership(sid, did, lessons_done=4)
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    engine.sync_lesson_stage(sid, did)
    deal.refresh_from_db()
    assert deal.stage.key == 'awaiting_renewal'
    assert deal.due_at is not None  # дата созревания зафиксирована


@pytest.mark.django_db
def test_no_wraparound_to_lesson_1(make_student, make_direction, make_membership):
    """Раньше attended=4 давало «Урок 1» (attended % 4 == 0) — теперь «Ждём продление»."""
    sid, did = make_student(), make_direction()
    make_membership(sid, did, lessons_done=4)
    engine.ensure_deal(sid, did, cycle_no=1)
    engine.sync_lesson_stage(sid, did)
    deal = RenewalDeal.objects.get(student_id=sid, direction_id=did)
    assert deal.stage.key != 'lesson_1'


@pytest.mark.django_db
def test_balance_zero_mid_cycle_moves_to_awaiting_payment(make_student, make_direction, make_membership):
    """2 урока отработано (цикл не отработан), оплат нет → баланс ≤ 0 → «Ждём оплату»."""
    sid, did = make_student(), make_direction()
    make_membership(sid, did, lessons_done=2)
    engine.ensure_deal(sid, did, cycle_no=1)
    engine.sync_lesson_stage(sid, did)
    deal = RenewalDeal.objects.get(student_id=sid, direction_id=did)
    assert deal.stage.key == 'awaiting_payment'


@pytest.mark.django_db
def test_prepaid_cycle2_deal_stays_on_lesson_1(make_student, make_direction, make_membership):
    """Сделка цикла 2 при attended=2 (ещё цикл 1) не двигается дальше «Урок 1»."""
    sid, did = make_student(), make_direction()
    make_membership(sid, did, lessons_done=2)
    make_payment(sid, did, lessons=8)   # хелпер: оплата на 8 уроков → баланс > 0
    engine.ensure_deal(sid, did, cycle_no=2)
    engine.sync_lesson_stage(sid, did)
    deal = RenewalDeal.objects.get(student_id=sid, direction_id=did, cycle_no=2)
    assert deal.stage.key == 'lesson_1'


@pytest.mark.django_db
def test_manual_stage_not_touched(make_student, make_direction, make_membership):
    """Сделку в ручной стадии («Думает») движок не трогает."""
    ...  # перенести в thinking через move, затем sync — стадия не меняется
```

(`make_membership`/`make_payment` — добавить в `tests/conftest.py` по образцу существующих фикстур: INSERT в `group_memberships`+`groups` и `Payment.objects.create` соответственно.)

- [ ] **Step 2: Verify FAIL** — `pytest apps/renewals/tests/test_lesson_progress.py -q`.

- [ ] **Step 3: Переписать `sync_lesson_stage`** в `engine.py`:

```python
def _auto_stages(pipeline) -> dict[str, RenewalStage]:
    """Все авто-стадии воронки по key (Урок 1..4 + awaiting_payment + awaiting_renewal)."""
    return {s.key: s for s in RenewalStage.objects.filter(pipeline=pipeline, is_auto=True)}


def _target_auto_stage(deal, attended: float, balance: float,
                       auto: dict, progress_stages: list) -> tuple[RenewalStage | None, bool]:
    """
    Целевая авто-стадия сделки и флаг «цикл созрел» (для due_at).
    Прогресс считается от НОМЕРА ЦИКЛА сделки, а не attended % 4 —
    иначе после 4-го урока сделка «заворачивалась» обратно в «Урок 1».
    Приоритет при конфликте: «Ждём продление» > «Ждём оплату» (более
    поздняя точка воронки; долг показывается бейджем, не стадией).
    """
    into = attended - (deal.cycle_no - 1) * cycle.LESSONS_PER_CYCLE
    if into >= cycle.LESSONS_PER_CYCLE and 'awaiting_renewal' in auto:
        return auto['awaiting_renewal'], True
    if balance <= 0 and 'awaiting_payment' in auto:
        return auto['awaiting_payment'], False
    if not progress_stages:
        return None, False
    idx = min(max(int(into), 0), len(progress_stages) - 1)
    return progress_stages[idx], False


@transaction.atomic
def sync_lesson_stage(student_id: int, direction_id: int) -> None:
    """
    Держит открытую сделку на правильной авто-стадии по посещаемости и балансу.
    Двигает ТОЛЬКО между авто-стадиями: если менеджер вручную увёл сделку в
    «Думает»/«Заморожен»/… — движок её не трогает.
    """
    from apps.finances.repository import balance_for_student

    deal = (RenewalDeal.objects
            .select_for_update()
            .select_related('stage', 'pipeline')
            .filter(student_id=student_id, direction_id=direction_id, outcome_at__isnull=True)
            .order_by('-cycle_no').first())
    if deal is None or not deal.stage.is_auto:
        return

    auto = _auto_stages(deal.pipeline)
    progress_stages = _progress_stages(deal.pipeline)
    attended = _attended_lessons(student_id, direction_id)
    balance = float(balance_for_student(student_id))

    target, matured = _target_auto_stage(deal, attended, balance, auto, progress_stages)
    if target is None:
        return

    update_fields = []
    if matured and deal.due_at is None:
        deal.due_at = timezone.now().date()
        update_fields.append('due_at')
    if target.id != deal.stage_id:
        from_stage = deal.stage
        deal.stage = target
        deal.stage_entered_at = timezone.now()
        update_fields += ['stage', 'stage_entered_at']
        RenewalActivity.objects.create(
            deal=deal, kind='system', from_stage=from_stage, to_stage=target,
            body=f'Автопереход: {target.label}')
    if update_fields:
        deal.save(update_fields=update_fields + ['updated_at'])
```

- [ ] **Step 4: Verify PASS** — `pytest apps/renewals/tests/test_lesson_progress.py apps/renewals/tests/test_engine.py -q`. Обновить старые тесты, завязанные на `attended % 4` (если ассертят «Урок 1» при attended=4 — теперь awaiting_renewal).

- [ ] **Step 5: Регресс смежных** — `pytest apps/lessons/tests/test_renewals_stage_sync.py apps/teacher_spa -q`.

### Task 3: Engine — переоткрытие сделки (`reopen_deal`)

**Files:**
- Modify: `journal_django/apps/renewals/engine.py`
- Test: `journal_django/apps/renewals/tests/test_engine.py`

- [ ] **Step 1: Падающие тесты:**

```python
@pytest.mark.django_db
def test_reopen_deletes_untouched_next_cycle(make_student, make_direction, make_membership):
    sid, did = make_student(), make_direction()
    make_membership(sid, did, lessons_done=0)
    engine.ensure_deal(sid, did, cycle_no=1)
    closed = engine.close_deal_won(sid, did)
    assert RenewalDeal.objects.filter(student_id=sid, cycle_no=2).exists()
    reopened = engine.reopen_deal(closed.id)
    assert reopened.outcome_at is None and reopened.stage.is_auto
    # порождённая нетронутая сделка цикла 2 удалена
    assert not RenewalDeal.objects.filter(student_id=sid, cycle_no=2).exists()


@pytest.mark.django_db
def test_reopen_keeps_touched_next_cycle(make_student, make_direction, make_membership):
    sid, did = make_student(), make_direction()
    make_membership(sid, did, lessons_done=0)
    engine.ensure_deal(sid, did, cycle_no=1)
    closed = engine.close_deal_won(sid, did)
    nxt = RenewalDeal.objects.get(student_id=sid, cycle_no=2)
    RenewalActivity.objects.create(deal=nxt, kind='comment', body='тронуто')
    engine.reopen_deal(closed.id)
    assert RenewalDeal.objects.filter(id=nxt.id).exists()  # осталась


@pytest.mark.django_db
def test_reopen_open_deal_is_noop(make_student, make_direction):
    sid, did = make_student(), make_direction()
    deal = engine.ensure_deal(sid, did, cycle_no=1)
    assert engine.reopen_deal(deal.id) is None
```

- [ ] **Step 2: Verify FAIL.**

- [ ] **Step 3: Реализация в `engine.py`:**

```python
@transaction.atomic
def reopen_deal(deal_id: int, author_id: Optional[int] = None,
                note: str = 'Сделка переоткрыта') -> Optional[RenewalDeal]:
    """
    Переоткрыть закрытую сделку: outcome_at → NULL, стадия → вычисленная авто-стадия.
    Порождённая при закрытии сделка следующего цикла удаляется, если открыта и не
    тронута руками (только системная активность и авто-стадия); иначе остаётся
    с системной пометкой. Возвращает None, если сделка не найдена или открыта.
    """
    from apps.finances.repository import balance_for_student

    deal = (RenewalDeal.objects.select_for_update().select_related('stage', 'pipeline')
            .filter(id=deal_id, outcome_at__isnull=False).first())
    if deal is None:
        return None

    nxt = (RenewalDeal.objects.select_for_update().select_related('stage')
           .filter(student_id=deal.student_id, direction_id=deal.direction_id,
                   cycle_no=deal.cycle_no + 1, outcome_at__isnull=True).first())
    if nxt is not None:
        touched = (not nxt.stage.is_auto
                   or nxt.activities.exclude(kind='system').exists())
        if touched:
            RenewalActivity.objects.create(
                deal=nxt, kind='system',
                body=f'Сделка месяца {deal.cycle_no} переоткрыта — проверьте актуальность')
        else:
            nxt.delete()  # activity уйдёт каскадом

    auto = _auto_stages(deal.pipeline)
    progress_stages = _progress_stages(deal.pipeline)
    attended = _attended_lessons(deal.student_id, deal.direction_id)
    balance = float(balance_for_student(deal.student_id))
    from_stage = deal.stage
    target, _ = _target_auto_stage(deal, attended, balance, auto, progress_stages)
    deal.stage = target or from_stage
    deal.outcome_at = None
    deal.stage_entered_at = timezone.now()
    deal.save(update_fields=['stage', 'outcome_at', 'stage_entered_at', 'updated_at'])
    RenewalActivity.objects.create(
        deal=deal, kind='system', from_stage=from_stage, to_stage=deal.stage,
        author_id=author_id, body=note)
    return deal
```

- [ ] **Step 4: Verify PASS** — `pytest apps/renewals/tests/test_engine.py -q`.

### Task 4: Сигналы оплат — фильтр kind + удаление оплаты переоткрывает сделку

**Files:**
- Modify: `journal_django/apps/renewals/signals.py`
- Test: `journal_django/apps/renewals/tests/test_signals.py`

- [ ] **Step 1: Падающие тесты:**

```python
@pytest.mark.django_db
def test_refund_does_not_close_deal(make_student, make_direction):
    """kind='refund' (и любой не-purchase) не должен закрывать сделку."""
    sid, did = make_student(), make_direction()
    engine.ensure_deal(sid, did, cycle_no=1)
    pay = Payment.objects.create(
        student_id=sid, direction_id=did, subscriptions_count=None,
        lessons_count=-4, kind='refund', unit_price=0, total_amount=-4000,
        paid_at='2026-07-12')
    try:
        assert not RenewalDeal.objects.filter(
            student_id=sid, outcome_at__isnull=False).exists()
    finally:
        RenewalDeal.objects.filter(student_id=sid).delete()
        pay.delete()


@pytest.mark.django_db
def test_payment_delete_reopens_deal(make_student, make_direction, make_membership):
    sid, did = make_student(), make_direction()
    make_membership(sid, did, lessons_done=0)
    engine.ensure_deal(sid, did, cycle_no=1)
    pay = Payment.objects.create(
        student_id=sid, direction_id=did, subscriptions_count=1,
        unit_price=4000, total_amount=4000, paid_at='2026-07-12')
    closed = RenewalDeal.objects.get(student_id=sid, cycle_no=1)
    assert closed.outcome_at is not None
    pay.delete()
    closed.refresh_from_db()
    assert closed.outcome_at is None          # переоткрыта
    assert not RenewalDeal.objects.filter(    # порождённый цикл 2 удалён
        student_id=sid, cycle_no=2).exists()
```

- [ ] **Step 2: Verify FAIL.**

- [ ] **Step 3: Реализация.** В `on_payment_created` добавить фильтр:

```python
    if not created or instance.direction_id is None or instance.kind != 'purchase':
        return
```

Добавить pre_delete-приёмник (ссылка activity.payment_id обнуляется SET_NULL во время
удаления, поэтому deal_id ловим ДО, а выполняем ПОСЛЕ коммита):

```python
from django.db.models.signals import post_save, pre_delete

@receiver(pre_delete, sender=Payment, dispatch_uid='renewals_on_payment_delete')
def on_payment_deleted(sender, instance: Payment, **kwargs) -> None:
    """Удаление оплаты переоткрывает сделку, которую эта оплата закрыла."""
    if instance.direction_id is None or instance.kind != 'purchase':
        return
    from apps.renewals.models import RenewalActivity
    deal_ids = list(
        RenewalActivity.objects
        .filter(payment_id=instance.id, kind='payment_linked',
                deal__outcome_at__isnull=False)
        .values_list('deal_id', flat=True))
    if not deal_ids:
        return
    payment_id = instance.id

    def _reopen() -> None:
        for deal_id in deal_ids:
            try:
                engine.reopen_deal(
                    deal_id, note=f'Оплата #{payment_id} удалена — сделка переоткрыта')
            except Exception:
                logger.exception(
                    'renewals: не удалось переоткрыть сделку %s после удаления оплаты %s',
                    deal_id, payment_id)

    transaction.on_commit(_reopen)
```

- [ ] **Step 4: Verify PASS** — `pytest apps/renewals/tests/test_signals.py apps/payments -q`.

### Task 5: `rebuild_renewal_deals` — без дублей + полная синхронизация стадий

**Files:**
- Modify: `journal_django/apps/renewals/management/commands/rebuild_renewal_deals.py`
- Test: `journal_django/apps/renewals/tests/test_rebuild.py`

- [ ] **Step 1: Падающие тесты:**

```python
@pytest.mark.django_db
def test_rebuild_skips_pair_with_open_deal_other_cycle(make_student, make_direction, make_membership):
    """Открытая сделка цикла 2 (предоплата) — rebuild НЕ создаёт вторую открытую (цикл 1)."""
    sid, did = make_student(), make_direction()
    make_membership(sid, did, lessons_done=0)   # attended=0 → расчётный цикл 1
    engine.ensure_deal(sid, did, cycle_no=2)
    call_command('rebuild_renewal_deals')
    assert RenewalDeal.objects.filter(
        student_id=sid, direction_id=did, outcome_at__isnull=True).count() == 1


@pytest.mark.django_db
def test_rebuild_syncs_stages(make_student, make_direction, make_membership):
    """rebuild приводит стадии к новым правилам (нужно после миграции 0005)."""
    sid, did = make_student(), make_direction()
    make_membership(sid, did, lessons_done=4)
    engine.ensure_deal(sid, did, cycle_no=1)
    call_command('rebuild_renewal_deals')
    deal = RenewalDeal.objects.get(student_id=sid, direction_id=did)
    assert deal.stage.key == 'awaiting_renewal'
```

- [ ] **Step 2: Verify FAIL.**

- [ ] **Step 3: Реализация** (`handle`):

```python
    def handle(self, *args, **options):
        from apps.renewals.models import RenewalDeal

        open_pairs = set(RenewalDeal.objects.filter(outcome_at__isnull=True)
                         .values_list('student_id', 'direction_id'))
        ensured = synced = 0
        for row in repository.active_cycles():
            pair = (row['student_id'], row['direction_id'])
            if pair not in open_pairs:
                engine.ensure_deal(row['student_id'], row['direction_id'], row['cycle_no'])
                ensured += 1
            engine.sync_lesson_stage_safe(row['student_id'], row['direction_id'])
            synced += 1
        self.stdout.write(self.style.SUCCESS(
            f'renewals: создано {ensured}, синхронизировано {synced}'))
```

- [ ] **Step 4: Verify PASS** — `pytest apps/renewals/tests/test_rebuild.py -q`.
- [ ] **Step 5: Прогнать команду на dev-БД** — `./.venv/Scripts/python.exe manage.py rebuild_renewal_deals` (разведёт существующие 240 сделок по новым стадиям). Проверить распределение SQL-запросом из анализа.

## ФАЗА B. Бэкенд-API

### Task 6: Endpoint переоткрытия + список ответственных + labels

**Files:**
- Modify: `journal_django/apps/renewals/views.py`, `urls.py`, `services.py`
- Modify: `journal_django/apps/changelog/labels.py`
- Test: `journal_django/apps/renewals/tests/test_api_write.py`

- [ ] **Step 1: Падающие тесты** (по образцу существующих в test_api_write; клиент менеджера уже есть в conftest тестов API):

```python
def test_reopen_closed_deal(manager_client, closed_deal):
    r = manager_client.post(f'/api/admin/renewals/{closed_deal.id}/reopen')
    assert r.status_code == 200 and r.json()['outcome_at'] is None

def test_reopen_open_deal_409(manager_client, open_deal):
    r = manager_client.post(f'/api/admin/renewals/{open_deal.id}/reopen')
    assert r.status_code == 409

def test_assignees_list(manager_client):
    r = manager_client.get('/api/admin/renewals/assignees')
    assert r.status_code == 200
    assert all({'id', 'full_name'} <= set(x) for x in r.json())
```

- [ ] **Step 2: Verify FAIL.**

- [ ] **Step 3: Реализация.** `services.py`:

```python
def reopen_deal(deal_id: int, author_id: int | None) -> dict | None | str:
    from apps.renewals import engine
    from apps.renewals.models import RenewalDeal
    if not RenewalDeal.objects.filter(id=deal_id).exists():
        return None
    deal = engine.reopen_deal(deal_id, author_id=author_id)
    if deal is None:
        return 'not_closed'
    return repository.deal_computed(deal_id)


def list_assignees() -> list[dict]:
    from apps.accounts.models import Account
    return list(Account.objects
                .filter(role__in=['manager', 'admin', 'superadmin'], is_active=True)
                .order_by('full_name').values('id', 'full_name'))
```

(Проверить фактические имена полей `role`/`is_active`/`full_name` в `apps/accounts/models.py` и поправить при расхождении.)

`views.py`:

```python
class RenewalReopenView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        result = services.reopen_deal(pk, author_id=getattr(request.user, 'id', None))
        if result is None:
            raise NotFound({'error': 'Not found'})
        if result == 'not_closed':
            return Response({'error': 'Сделка не закрыта — переоткрывать нечего'},
                            status=status.HTTP_409_CONFLICT)
        return Response(result)


class RenewalAssigneesView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        return Response(services.list_assignees())
```

`urls.py` — добавить ДО `<int:pk>`-маршрутов:

```python
    path('/assignees', RenewalAssigneesView.as_view(), name='renewals-assignees'),
    path('/<int:pk>/reopen', RenewalReopenView.as_view(), name='renewals-reopen'),
```

`apps/changelog/labels.py` — рядом с renewal-правилами:

```python
    ('POST', re.compile(r'^/api/admin/renewals/\d+/reopen$'), 'renewal.reopen'),
```

- [ ] **Step 4: Verify PASS** — `pytest apps/renewals/tests/test_api_write.py apps/changelog -q`.

### Task 7: board/list/deal_computed — терминальные колонки, ids и долг на карточке, прогресс от цикла

**Files:**
- Modify: `journal_django/apps/renewals/repository.py`
- Test: `journal_django/apps/renewals/tests/test_api_read.py`, `tests/test_repository.py`

- [ ] **Step 1: Падающие тесты:**

```python
def test_board_excludes_terminal_columns(manager_client):
    r = manager_client.get('/api/admin/renewals?view=board')
    kinds = {c['kind'] for c in r.json()['columns']}
    assert 'won' not in kinds and 'lost' not in kinds

def test_board_card_has_ids_and_debt(manager_client, open_deal):
    r = manager_client.get('/api/admin/renewals?view=board')
    card = next(c for col in r.json()['columns'] for c in col['cards'])
    assert {'student_id', 'direction_id', 'debt'} <= set(card)

def test_deal_computed_lesson_from_cycle(open_deal_with_4_attended):
    """attended=4, cycle_no=1 → lesson_in_cycle=4 (раньше было 1 из-за %4)."""
    data = repository.deal_computed(open_deal_with_4_attended.id)
    assert data['lesson_in_cycle'] == 4
```

- [ ] **Step 2: Verify FAIL.**

- [ ] **Step 3: Реализация.**
  - `board()`: `stages = ...exclude(kind__in=('won', 'lost'))` (колонки-мишени уходят с доски; закрытые смотрят списком).
  - `_deals_in_stage`: добавить в SELECT `d.student_id, d.direction_id, d.due_at`; после выборки — батч-долг:

```python
def _annotate_debt(cards: list[dict]) -> list[dict]:
    """Бейдж долга: balance < 0. Батч через apps.finances (одним запросом на страницу)."""
    from apps.finances.repository import balances_for_students
    ids = list({c['student_id'] for c in cards})
    if not ids:
        return cards
    balances = balances_for_students(ids)
    for c in cards:
        c['debt'] = float(balances.get(c['student_id'], 0)) < 0
    return cards
```

    (проверить сигнатуру `balances_for_students` в `apps/finances/repository.py`; вызывать `_annotate_debt` в конце `_deals_in_stage`).
  - `deal_computed`: `lesson_in_cycle` от цикла сделки + новые поля:

```python
    attended = float(data.pop('attended') or 0)
    into = attended - (data['cycle_no'] - 1) * cycle.LESSONS_PER_CYCLE
    data['lesson_in_cycle'] = min(max(int(into), 0), cycle.LESSONS_PER_CYCLE - 1) + 1  # 1..4
    data['cycle_completed'] = into >= cycle.LESSONS_PER_CYCLE
    data['balance'] = balance_for_student(data['student_id'])
    data['debt'] = float(data['balance']) < 0
```

    и добавить `d.due_at` в SELECT.
  - `list_deals`: в SELECT добавить `d.due_at`, `st.color AS stage_color` (для бейджей закрытых).

- [ ] **Step 4: Verify PASS** — `pytest apps/renewals/tests/test_api_read.py apps/renewals/tests/test_repository.py -q`.

### Task 8: Аналитика «По месяцам»

**Files:**
- Modify: `journal_django/apps/renewals/analytics.py`
- Test: `journal_django/apps/renewals/tests/test_analytics.py`

- [ ] **Step 1: Падающий тест:**

```python
@pytest.mark.django_db
def test_funnel_group_by_month(make_student, make_direction, make_membership):
    sid, did = make_student(), make_direction()
    make_membership(sid, did, lessons_done=4)
    engine.ensure_deal(sid, did, cycle_no=1)
    engine.sync_lesson_stage(sid, did)          # созревание → due_at сегодня
    data = analytics.funnel(group_by='month')
    row = data['months'][0]
    assert row['matured'] >= 1
    assert {'month', 'matured', 'won', 'lost', 'in_progress', 'conversion'} <= set(row)
```

- [ ] **Step 2: Verify FAIL.**

- [ ] **Step 3: Реализация** — в `funnel()` при `group_by == 'month'` добавить в ответ ключ `months`:

```python
        cur.execute("""
            SELECT to_char(COALESCE(date_trunc('month', d.due_at::timestamp),
                                    date_trunc('month', d.outcome_at)), 'YYYY-MM') AS month,
                   COUNT(*) AS matured,
                   COUNT(*) FILTER (WHERE st.kind = 'won') AS won,
                   COUNT(*) FILTER (WHERE st.kind = 'lost') AS lost,
                   COUNT(*) FILTER (WHERE d.outcome_at IS NULL) AS in_progress
            FROM renewal_deal d JOIN renewal_stage st ON st.id = d.stage_id
            WHERE d.due_at IS NOT NULL OR d.outcome_at IS NOT NULL
            GROUP BY 1 ORDER BY 1 DESC LIMIT 24
        """)
        months = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
        for m in months:
            done = m['won'] + m['lost']
            m['conversion'] = round(m['won'] / done * 100, 1) if done else None
```

Смысл когорты: месяц = когда цикл отработан (`due_at`); оплатившие заранее — месяц закрытия.

- [ ] **Step 4: Verify PASS** — `pytest apps/renewals/tests/test_analytics.py -q`, затем весь бэкенд-набор `pytest apps/renewals -q`.

## ФАЗА C. Фронтенд

### Task 9: Типы, labels, хуки (reopen, assignees, invalidate оплат)

**Files:**
- Modify: `frontend/admin-src/src/lib/renewals.ts`, `lib/labels.ts`
- Modify: `frontend/admin-src/src/hooks/useRenewals.ts`, `hooks/usePayments.ts`

- [ ] **Step 1: Типы** (`lib/renewals.ts`): в `RenewalCard` добавить `student_id: number; direction_id: number; due_at: string | null; debt: boolean;` в `RenewalDealDetail` — `due_at: string | null; debt: boolean; cycle_completed: boolean;` в `RenewalFilters` — `include_closed?: string;` Новый тип:

```ts
export interface RenewalAssignee { id: number; full_name: string }
export type RenewalLostReason = 'price' | 'schedule' | 'lost_interest' | 'relocation' | 'other';
```

- [ ] **Step 2: Labels** (`lib/labels.ts`): в `RENEWAL_STAGE_LABELS` добавить `awaiting_renewal: 'Ждём продление',`; новый словарь:

```ts
export const RENEWAL_LOST_REASON_LABELS: Record<string, string> = {
  price: 'Не устроила цена', schedule: 'Не подошло расписание',
  lost_interest: 'Потерял интерес', relocation: 'Переезд', other: 'Другое',
};
```

- [ ] **Step 3: Хуки** (`useRenewals.ts`): в `useRenewalMutations` добавить

```ts
    reopen: useMutation({
      mutationFn: ({ id }: { id: number }) =>
        api<RenewalDealDetail>('POST', `/api/admin/renewals/${id}/reopen`),
      onSuccess: invalidate,
    }),
```

и новый хук:

```ts
export function useRenewalAssignees() {
  return useQuery({
    queryKey: [...KEY, 'assignees'],
    queryFn: () => api<RenewalAssignee[]>('GET', '/api/admin/renewals/assignees'),
    staleTime: 5 * 60_000,
  });
}
```

- [ ] **Step 4: `usePayments.ts`** — в общий invalidate добавить `qc.invalidateQueries({ queryKey: ['renewals'] });` (создание/удаление оплаты меняет сделки — доска должна обновиться сразу).

- [ ] **Step 5: Verify** — `npm run typecheck` (упадёт на местах, которые чинятся в задачах 10–12 — допустимо чинить по ходу; к концу задачи 12 typecheck обязан быть зелёным).

### Task 10: Диалог закрытия сделки (`RenewalCloseDialog`)

**Files:**
- Create: `frontend/admin-src/src/pages/renewals/RenewalCloseDialog.tsx`

- [ ] **Step 1: Компонент** на базе `components/ui/Dialog` (Radix), формы — только `SelectInput`/`Textarea` из `components/form/`:

```tsx
import { useState } from 'react';
import { Dialog } from '../../components/ui/Dialog';
import { SelectInput } from '../../components/form/SelectInput';
import { Textarea } from '../../components/form/Textarea';
import { usePaymentModal } from '../../providers/PaymentModalProvider';
import { RENEWAL_LOST_REASON_LABELS } from '../../lib/labels';
import type { RenewalLostReason } from '../../lib/renewals';

export interface CloseDialogTarget {
  dealId: number;
  studentId: number;
  directionId: number;
  studentName: string;
  mode: 'won' | 'lost';
}

interface Props {
  target: CloseDialogTarget;
  onClose: () => void;
  /** Выполнить перенос: reason_code уходит в move, comment — отдельным комментарием. */
  onConfirm: (opts: { reason_code?: string; comment?: string }) => void;
  pending: boolean;
}

export function RenewalCloseDialog({ target, onClose, onConfirm, pending }: Props) {
  const { open: openPayment } = usePaymentModal();
  const [reason, setReason] = useState<RenewalLostReason | ''>('');
  const [comment, setComment] = useState('');

  const lost = target.mode === 'lost';
  return (
    <Dialog
      open
      onOpenChange={(o) => { if (!o) onClose(); }}
      title={lost ? `Закрыть сделку: ${target.studentName} уходит` : `Продление: ${target.studentName}`}
      footer={
        lost ? (
          <>
            <button type="button" className="btn-secondary" onClick={onClose}>Отмена</button>
            <button
              type="button" className="btn-danger" disabled={!reason || pending}
              onClick={() => onConfirm({ reason_code: reason, comment: comment.trim() || undefined })}
            >
              Закрыть сделку
            </button>
          </>
        ) : (
          <>
            <button type="button" className="btn-secondary" onClick={onClose}>Отмена</button>
            <button
              type="button" className="btn-secondary" disabled={pending}
              onClick={() => onConfirm({ reason_code: 'manual_no_payment', comment: comment.trim() || undefined })}
            >
              Закрыть без оплаты
            </button>
            <button
              type="button" className="btn-primary"
              onClick={() => { onClose(); openPayment({ studentId: target.studentId, directionId: target.directionId }); }}
            >
              Внести оплату
            </button>
          </>
        )
      }
    >
      {lost ? (
        <>
          <p className="modal-text">
            Сделка уйдёт в архив и исчезнет с доски. Ученик останется в системе.
            Вернуть можно кнопкой «Переоткрыть» в карточке сделки.
          </p>
          <SelectInput
            label="Причина ухода" value={reason} required
            onChange={(v) => setReason(v as RenewalLostReason)}
            options={Object.entries(RENEWAL_LOST_REASON_LABELS)
              .map(([value, label]) => ({ value, label }))}
          />
          <Textarea value={comment} onChange={(e) => setComment(e.target.value)}
            placeholder="Комментарий (необязательно)…" rows={2} />
        </>
      ) : (
        <>
          <p className="modal-text">
            <b>«Внести оплату»</b> — откроется форма оплаты; после сохранения сделка
            закроется как «Продлён» автоматически и появится сделка следующего месяца.
          </p>
          <p className="modal-text">
            <b>«Закрыть без оплаты»</b> — только если деньги прошли мимо системы:
            сделка закроется с пометкой «без оплаты», следующий месяц тоже будет создан.
          </p>
          <Textarea value={comment} onChange={(e) => setComment(e.target.value)}
            placeholder="Комментарий (необязательно)…" rows={2} />
        </>
      )}
    </Dialog>
  );
}
```

(Точные пропсы `SelectInput`/`Textarea` сверить с `components/form/` и `btn-*`-классы с существующими модалками, например `RevertConfirmDialog.tsx`; `modal-text` — проверить в `styles/modal.css`, при отсутствии добавить скромный стиль через токены.)

- [ ] **Step 2: Verify** — `npm run typecheck` по файлу (ошибки других задач допустимы).

### Task 11: Доска — зоны закрытия при drag + подключение диалога + бейдж долга

**Files:**
- Modify: `frontend/admin-src/src/pages/renewals/RenewalBoard.tsx`
- Modify: `frontend/admin-src/src/pages/renewals/RenewalCardView.tsx`
- Modify: `frontend/admin-src/src/styles/pages/renewals.css`

- [ ] **Step 1: Зоны закрытия.** В `RenewalBoard`: получить стадии `useRenewalStages()`; найти `wonStage = stages.find(s => s.kind === 'won')`, `lostStage = ... 'lost'`. Новый локальный компонент:

```tsx
function CloseZone({ id, label, tone }: { id: string; label: string; tone: 'won' | 'lost' }) {
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <div ref={setNodeRef}
      className={`renewal-close-zone renewal-close-zone--${tone}${isOver ? ' renewal-close-zone--over' : ''}`}>
      {label}
    </div>
  );
}
```

Рендер внизу доски только пока тащат карточку (`activeCard != null`):

```tsx
{activeCard && (
  <div className="renewal-close-zones">
    <CloseZone id="close-won" label="✓ Продлён" tone="won" />
    <CloseZone id="close-lost" label="✕ Ушёл" tone="lost" />
  </div>
)}
```

- [ ] **Step 2: handleDragEnd.** Если `over.id === 'close-won' | 'close-lost'` — НЕ мутировать сразу, а открыть диалог:

```tsx
const [closeTarget, setCloseTarget] = useState<CloseDialogTarget | null>(null);
// в handleDragEnd, до оптимистичной логики колонок:
if (over.id === 'close-won' || over.id === 'close-lost') {
  const card = dragCard(event);
  if (card) setCloseTarget({
    dealId: Number(active.id), studentId: card.student_id, directionId: card.direction_id,
    studentName: card.student_name, mode: over.id === 'close-won' ? 'won' : 'lost',
  });
  return;
}
```

Подтверждение диалога выполняет move в терминальную стадию (+ комментарий отдельной мутацией):

```tsx
const { move, comment } = useRenewalMutations();
const handleCloseConfirm = ({ reason_code, comment: text }: { reason_code?: string; comment?: string }) => {
  if (!closeTarget) return;
  const stage = closeTarget.mode === 'won' ? wonStage : lostStage;
  if (!stage) return;
  move.mutate(
    { id: closeTarget.dealId, to_stage_id: stage.id, reason_code },
    {
      onSuccess: () => {
        if (text) comment.mutate({ id: closeTarget.dealId, body: text });
        setCloseTarget(null);
      },
      onError: (err) => { setCloseTarget(null); showError(err, 'Не удалось закрыть сделку'); },
    },
  );
};
// рендер: {closeTarget && <RenewalCloseDialog target={closeTarget} pending={move.isPending}
//   onClose={() => setCloseTarget(null)} onConfirm={handleCloseConfirm} />}
```

- [ ] **Step 3: Бейдж долга на карточке** (`RenewalCardContent`, рядом с бейджем дней):

```tsx
{card.debt && (
  <span className="status-badge status-badge--negative" title="Баланс ученика отрицательный">
    Долг
  </span>
)}
```

- [ ] **Step 4: Стили** (`styles/pages/renewals.css`, только токены):

```css
.renewal-close-zones {
  position: sticky; bottom: 0; display: flex; gap: var(--space-3);
  padding: var(--space-3); justify-content: center;
}
.renewal-close-zone {
  flex: 0 1 240px; padding: var(--space-4); text-align: center;
  border: 2px dashed var(--color-border); border-radius: var(--radius-md);
  background: var(--color-surface); font-weight: 600;
}
.renewal-close-zone--won.renewal-close-zone--over { border-color: var(--color-success); background: var(--color-success-bg); }
.renewal-close-zone--lost.renewal-close-zone--over { border-color: var(--color-danger); background: var(--color-danger-bg); }
```

(Имена токенов сверить с `styles/tokens.css` — использовать фактические.)

- [ ] **Step 5: Verify** — `npm run typecheck`; вручную: доска без колонок «Продлён»/«Ушёл», при drag появляются зоны, бросок открывает диалог, отмена диалога ничего не меняет.

### Task 12: Drawer — рабочая карточка сделки (поля, стадия, прогресс, переоткрытие)

**Files:**
- Modify: `frontend/admin-src/src/pages/renewals/RenewalDrawer.tsx`
- Modify: `frontend/admin-src/src/styles/pages/renewals.css` (по необходимости)

- [ ] **Step 1: Секция прогресса и долга** (после subhead):

```tsx
<div className="renewal-drawer__section renewal-drawer__progress">
  {deal.outcome_at == null && (
    deal.cycle_completed
      ? <span className="status-badge status-badge--warning">Цикл отработан — пора продлевать</span>
      : <span>Урок {deal.lesson_in_cycle} из 4</span>
  )}
  {deal.debt && <span className="status-badge status-badge--negative">Долг</span>}
</div>
```

- [ ] **Step 2: Редактируемые CRM-поля** (только для открытых сделок; `patch` из `useRenewalMutations`, `useRenewalAssignees`, `SelectInput`/`DateInput` из `components/form/`):

```tsx
const { patch, move, comment, reopen } = useRenewalMutations();
const { data: assignees } = useRenewalAssignees();
const save = (body: Record<string, unknown>) => patch.mutate({ id, body });
...
<div className="renewal-drawer__section renewal-drawer__fields">
  <SelectInput
    label="Ответственный"
    value={deal.assignee_id != null ? String(deal.assignee_id) : ''}
    onChange={(v) => save({ assignee_id: v ? Number(v) : null })}
    options={[{ value: '', label: '—' },
      ...(assignees || []).map((a) => ({ value: String(a.id), label: a.full_name }))]}
  />
  <DateInput
    label="Следующее касание"
    value={deal.next_touch_at ?? ''}
    onChange={(v) => save({ next_touch_at: v || null })}
  />
  <TextInput
    label="Ожидаемая сумма, ₽"
    inputMode="decimal"
    defaultValue={deal.expected_amount != null ? String(deal.expected_amount) : ''}
    onBlur={(e) => {
      const raw = e.target.value.trim().replace(',', '.');
      save({ expected_amount: raw === '' ? null : raw });
    }}
  />
</div>
```

(Пропсы `DateInput`/`SelectInput`/`TextInput` сверить с фактическими компонентами `components/form/` — подстроить под их API.)

- [ ] **Step 3: Смена стадии из карточки.** `SelectInput` со стадиями из `useRenewalStages()`: открытые kinds (progress/decision) — прямой `move.mutate`; выбор won/lost — открыть тот же `RenewalCloseDialog` (state `closeTarget`, как на доске; у drawer'а есть `deal.student_id`/`direction_id`/`student_name`). При 409 — `showError` (текст приходит с бэка).

- [ ] **Step 4: Переоткрытие закрытой сделки.** Для `deal.outcome_at != null` вместо полей — плашка и кнопка:

```tsx
<div className="renewal-drawer__section">
  <span className="status-badge">{deal.stage_kind === 'won' ? 'Продлена' : 'Закрыта'} {fmtDateTime(deal.outcome_at)}</span>
  <button type="button" className="btn-secondary" disabled={reopen.isPending}
    onClick={() => setConfirmReopen(true)}>
    Переоткрыть
  </button>
</div>
{confirmReopen && (
  <Dialog open onOpenChange={(o) => !o && setConfirmReopen(false)} title="Переоткрыть сделку?"
    footer={<>
      <button type="button" className="btn-secondary" onClick={() => setConfirmReopen(false)}>Отмена</button>
      <button type="button" className="btn-primary"
        onClick={() => reopen.mutate({ id }, { onSuccess: () => setConfirmReopen(false) })}>
        Переоткрыть
      </button>
    </>}>
    <p className="modal-text">
      Сделка вернётся на доску в актуальную стадию по посещаемости и балансу.
      Если при закрытии была создана нетронутая сделка следующего месяца — она будет удалена.
    </p>
  </Dialog>
)}
```

- [ ] **Step 5: Кнопку «Внести оплату»** оставить для открытых сделок; таймлайн и комментарии без изменений.

- [ ] **Step 6: Verify** — `npm run typecheck`; вручную: правка ответственного/даты/суммы сохраняется и видна на карточке доски; смена стадии работает; закрытая сделка переоткрывается.

### Task 13: Фильтры страницы + «Показать закрытые» в списке

**Files:**
- Modify: `frontend/admin-src/src/pages/renewals/RenewalsPage.tsx`
- Modify: `frontend/admin-src/src/pages/renewals/RenewalList.tsx`

- [ ] **Step 1: Панель фильтров** в `RenewalsPage` (значения — в searchParams, как уже читается):

```tsx
const { data: assignees } = useRenewalAssignees();
const { data: directions } = useDirections();
const setFilter = (key: string, value: string) => {
  const next = new URLSearchParams(sp);
  if (value) next.set(key, value); else next.delete(key);
  setSp(next, { replace: true });
};
...
<div className="renewals-page__filters">
  <SelectInput label="Ответственный" value={sp.get('assignee_id') ?? ''}
    onChange={(v) => setFilter('assignee_id', v)}
    options={[{ value: '', label: 'Все' },
      ...(assignees || []).map((a) => ({ value: String(a.id), label: a.full_name }))]} />
  <SelectInput label="Направление" value={sp.get('direction_id') ?? ''}
    onChange={(v) => setFilter('direction_id', v)}
    options={[{ value: '', label: 'Все' },
      ...(directions || []).map((d) => ({ value: String(d.id), label: d.name }))]} />
  <Checkbox label="Просроченное касание" checked={sp.get('overdue') === 'true'}
    onChange={(checked) => setFilter('overdue', checked ? 'true' : '')} />
</div>
```

(API `useDirections`/`Checkbox` сверить с фактическим; удалить устаревший комментарий «фильтры добавятся в следующей фазе».)

- [ ] **Step 2: «Показать закрытые»** — в режиме `list` дополнительный `Checkbox` (`include_closed`), значение уходит в `filters.include_closed` → бэкенд уже поддерживает. В `RenewalList` колонка «Стадия» для закрытых показывает won/lost-бейдж (уже работает через `StageBadge`).

- [ ] **Step 3: Verify** — `npm run typecheck`; вручную: фильтры меняют доску и список, URL шарится.

### Task 14: Аналитика «По месяцам» + финальная верификация

**Files:**
- Modify: `frontend/admin-src/src/hooks/useRenewalAnalytics.ts`
- Modify: `frontend/admin-src/src/pages/renewals/RenewalAnalyticsPage.tsx`

- [ ] **Step 1: Хук** — параметр `group_by=month` (отдельный `useQuery` c ключом `[...KEY,'analytics','months']` → `/api/admin/renewals/analytics?group_by=month`), тип:

```ts
export interface RenewalMonthRow {
  month: string;        // 'YYYY-MM'
  matured: number;      // циклов созрело в месяце
  won: number; lost: number; in_progress: number;
  conversion: number | null;  // % won/(won+lost)
}
```

- [ ] **Step 2: Секция на странице** — таблица «Продления по месяцам»: Месяц | Созрело | Продлено | Ушло | В работе | Конверсия. Месяц форматировать `Intl.DateTimeFormat('ru', { month: 'long', year: 'numeric' })`; конверсия `—`, если null. Использовать существующие табличные стили страницы аналитики.

- [ ] **Step 3: Финальная верификация всего:**
- `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/renewals apps/lessons apps/payments apps/changelog -q` → все PASS;
- `cd frontend/admin-src && npm run typecheck && npm run build` → без ошибок;
- смоук в браузере (runserver + nginx :8080): доска → drag в зону «Ушёл» → диалог с причиной → сделка в архиве → список «Показать закрытые» → переоткрытие → сделка вернулась; оплата из drawer закрывает сделку; удаление этой оплаты возвращает её; аналитика показывает месяцы.

---

## Self-review checklist (пройден при написании)

- Spec coverage: автоматика (Task 2, 5), диалоги (10–12), переоткрытие (3, 6, 12), удаление оплаты (4), доска/зоны/фильтры (11, 13), аналитика по месяцам (1, 8, 14), гигиена rebuild (5), миграции (1).
- Типы согласованы: `RenewalCard.student_id/direction_id/debt` (Task 7 SELECT ↔ Task 9 типы ↔ Task 11 использование); `reopen` мутация (Task 9 ↔ 12); `CloseDialogTarget` (Task 10 ↔ 11 ↔ 12).
- Нет commit-шагов — по правилу проекта (коммиты только по явной просьбе).
