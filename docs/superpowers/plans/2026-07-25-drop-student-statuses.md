# Удаление статусов ученика: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Убрать `Student.enrollment_status` вместе с каскадами заморозки/отказа и показывать вместо статуса стадию последней сделки продления; «Заморожен» и «Ушёл» становятся обычными стадиями воронки.

**Architecture:** Стадия последней сделки (`renewal_deal` с максимальным `cycle_no`) становится единственным «статусом» ученика и аннотируется в `students.repository` коррелированными подзапросами. Заморозка теряет все побочные эффекты и хранит только месяц окончания в новом поле `RenewalDeal.frozen_until_month`; выход из неё — ручное действие, пересчитывающее авто-стадию движком. Каскадный код (смена статуса, сдвиг расписания, превью) удаляется целиком.

**Tech Stack:** Django 5 + DRF, PostgreSQL, pytest; admin SPA — React 19 + TanStack Query v5 + Vite (TypeScript).

**Спека:** [`docs/superpowers/specs/2026-07-25-drop-student-statuses-design.md`](../specs/2026-07-25-drop-student-statuses-design.md)

---

## Соглашения этого плана

- Все команды запускаются из `journal_django/` (там `manage.py` и `pytest.ini`), кроме фронтовых — те из `journal_django/frontend/admin-src/`.
- Тесты: `pytest` (настройки `config.settings.test`, изолированная `journal_test` — гард против боевой БД уже стоит). Отдельный тест: `pytest apps/<app>/tests/test_x.py::test_name -v`.
- **Коммиты:** по правилу проекта (`CLAUDE.md`) коммитим только по явному разрешению пользователя. Шаги «Commit» приведены с готовыми сообщениями — если разрешения нет, шаг пропускается, изменения остаются в рабочем дереве.
- **`npm run build` не запускать** — сборка `admin-dist` не входит в задачи (проверка типов делается `npm run typecheck`).
- После задач 3 и 12 (миграции) прогонять **полный** `pytest`, а не отдельные файлы: приложения по-разному инициализируют тестовую БД, и raw-SQL ломается только на полном прогоне.

## Структура файлов

**Бэкенд — создаём:**

| Файл | Ответственность |
|---|---|
| `apps/renewals/migrations/0012_frozen_manual_stage.py` | Стадия `frozen` → `is_auto=False` |
| `apps/renewals/migrations/0013_deal_frozen_until_month.py` | Поле + индекс + бэкфил месяца из `students.frozen_until` |
| `apps/renewals/migrations/_frozen_month_backfill.py` | SQL бэкфила отдельной функцией (переиспользуется тестом) |
| `apps/renewals/tests/test_frozen_stage.py` | Заморозка как ручная стадия: переходы, месяц, unfreeze |
| `apps/students/migrations/0016_drop_enrollment_status.py` | Удаление 3 констрейнтов и 3 колонок |
| `apps/students/tests/test_students_stage_annotation.py` | Аннотация стадии в списке/детали, фильтр и сортировка |

**Бэкенд — меняем:** `apps/renewals/{models,transitions,engine,repository,serializers,views,urls}.py`, `apps/students/{models,repository,serializers,services,views,urls}.py`, `apps/dashboard/registry_service.py`, `apps/sync/backfills/students.py`, `apps/changelog/{labels,summary}.py`.

**Бэкенд — удаляем:** `apps/students/tests/{test_status_service,test_status_api,test_freeze_preview_api,test_frozen_constraints,test_student_leave_cleanup}.py`, `apps/scheduling/tests/{test_freeze_scheduling,test_preview_freeze}.py`, `apps/renewals/tests/test_freeze_deal.py`.

**Фронт — создаём:** `src/components/StageBadge.tsx`, `src/pages/renewals/FreezeDealDialog.tsx`.

**Фронт — меняем:** `src/lib/{shared-types,labels,renewals,table-settings}.ts`, `src/hooks/useRenewals.ts`, `src/pages/students/{StudentsListPage,StudentDetailPage}.tsx`, `src/pages/groups/GroupMembersBlock.tsx`, `src/pages/payments/PaymentModal.tsx`, `src/pages/renewals/{RenewalBoard,RenewalCardView,RenewalDealDrawer}.tsx`, `src/styles/components.css`.

**Фронт — удаляем:** `src/components/StatusBadge.tsx`, `src/pages/students/StudentStatusModal.tsx`.

---

### Task 1: Стадия «Заморожен» становится ручной

**Files:**
- Create: `journal_django/apps/renewals/migrations/0012_frozen_manual_stage.py`
- Modify: `journal_django/apps/renewals/tests/test_seed.py:31-36`

- [ ] **Step 1: Развернуть существующий тест**

`test_seed.py` уже фиксирует старое поведение — `test_frozen_stage_is_auto` утверждает `frozen.is_auto is True`. Это и есть падающий тест задачи: переименовать в `test_frozen_stage_is_manual`, развернуть ассерт и объяснить причину в докстринге:

```python
@pytest.mark.django_db
def test_frozen_stage_is_manual():
    """Миграция 0012 отменила 0010: «Заморожен» снова обычная ручная стадия.

    0010 пометила её is_auto=True искусственно — только чтобы
    transitions.is_allowed запретил ручной вход, а двигал стадию каскад смены
    статуса ученика. Статусы удалены (спека 2026-07-25), заморозка — обычная
    decision-стадия, которую ставит менеджер.
    """
    pipe = RenewalPipeline.objects.get(is_default=True)
    frozen = RenewalStage.objects.get(pipeline=pipe, key='frozen')
    assert frozen.is_auto is False
    assert frozen.kind == 'decision'
```

Отдельный файл под это не создаём: состояние засидированной воронки — предмет `test_seed.py`, а `test_frozen_stage.py` (поведение заморозки) появится в задаче 4.

- [ ] **Step 2: Убедиться, что тест падает**

Run: `pytest apps/renewals/tests/test_frozen_stage.py -v`
Expected: FAIL — `assert True is False` (стадия пока `is_auto=True` после миграции 0010).

- [ ] **Step 3: Написать миграцию**

Создать `journal_django/apps/renewals/migrations/0012_frozen_manual_stage.py`:

```python
"""Стадия «Заморожен» снова становится РУЧНОЙ (is_auto=False) — откат 0010.

0010 сделала её авто-стадией только чтобы transitions.is_allowed блокировал
ручной вход/выход: войти можно было исключительно каскадом смены статуса
ученика (engine.freeze_deal). Статусы ученика удалены (спека 2026-07-25),
заморозка — обычная decision-стадия, которую менеджер ставит сам.
Идемпотентно; обратимо.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    RenewalStage = apps.get_model('renewals', 'RenewalStage')
    RenewalStage.objects.filter(
        pipeline__is_default=True, key='frozen').update(is_auto=False)


def backwards(apps, schema_editor):
    RenewalStage = apps.get_model('renewals', 'RenewalStage')
    RenewalStage.objects.filter(
        pipeline__is_default=True, key='frozen').update(is_auto=True)


class Migration(migrations.Migration):

    dependencies = [
        ('renewals', '0011_drop_next_touch_at'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
```

- [ ] **Step 4: Прогнать тест**

Run: `pytest apps/renewals/tests/test_frozen_stage.py -v`
Expected: PASS.

Если FAIL с «стадия is_auto=True» — тестовая БД не пересоздалась. Проверить, что миграция подхватилась: `python manage.py showmigrations renewals` (ожидается `[X] 0012_frozen_manual_stage`).

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals/migrations/0012_frozen_manual_stage.py journal_django/apps/renewals/tests/test_frozen_stage.py
git commit -m "refactor(renewals): стадия «Заморожен» снова ручная (откат авто-стадии)"
```

---

### Task 2: Переход в «Заморожен» разрешён посреди цикла

Заморозка почти всегда случается до конца цикла из 4 уроков, а `transitions.is_allowed` при незавершённом цикле пускает только `lost`. Раньше это не мешало: `engine.freeze_deal` обходил валидатор.

**Files:**
- Modify: `journal_django/apps/renewals/transitions.py`
- Modify: `journal_django/apps/renewals/engine.py:27` (переносим определение `FROZEN_KEY`)
- Test: `journal_django/apps/renewals/tests/test_transitions.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `journal_django/apps/renewals/tests/test_transitions.py`:

```python
def test_frozen_allowed_mid_cycle():
    """В «Заморожен» можно уйти, не докрутив цикл — как и в «Ушёл»."""
    assert is_allowed(from_kind='progress', to_kind='decision',
                      from_is_auto=True, to_is_auto=False,
                      from_key='lesson_2', to_key='frozen',
                      cycle_completed=False) is True


def test_other_decision_still_blocked_mid_cycle():
    """Послабление касается ТОЛЬКО заморозки: «Думает» посреди цикла по-прежнему нет."""
    assert is_allowed(from_kind='progress', to_kind='decision',
                      from_is_auto=True, to_is_auto=False,
                      from_key='lesson_2', to_key='thinking',
                      cycle_completed=False) is False


def test_frozen_to_lost_allowed():
    """Со «Заморожен» всегда можно закрыть сделку как «Ушёл»."""
    assert is_allowed(from_kind='decision', to_kind='lost',
                      from_is_auto=False, to_is_auto=False,
                      from_key='frozen', to_key='churned',
                      cycle_completed=False) is True
```

Проверить, что импорт `is_allowed` в файле уже есть; если нет — добавить `from apps.renewals.transitions import is_allowed`.

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest apps/renewals/tests/test_transitions.py -v`
Expected: FAIL — `TypeError: is_allowed() got an unexpected keyword argument 'to_key'`.

- [ ] **Step 3: Реализовать**

В `journal_django/apps/renewals/transitions.py` добавить константу рядом с `AWAITING_RENEWAL_KEY`:

```python
# Ключ стадии «Заморожен». Единственная decision-стадия, в которую можно уйти
# посреди цикла: заморозка не связана с созреванием продления. Определена здесь
# (а не в engine), потому что это правило переходов; engine её реэкспортирует.
FROZEN_KEY = 'frozen'
```

Заменить сигнатуру и блок незавершённого цикла:

```python
def is_allowed(*, from_kind: str, to_kind: str,
               from_is_auto: bool = False, to_is_auto: bool = False,
               from_key: str | None = None, to_key: str | None = None,
               cycle_completed: bool = True, balance: float = 1) -> bool:
```

```python
    if not cycle_completed:
        # Заморозка приравнена к «Ушёл»: и то, и другое случается посреди цикла
        # (решение пользователя 2026-07-25). Прочие decision-стадии — только
        # после отработанного цикла.
        return to_kind == 'lost' or to_key == FROZEN_KEY
```

Так же расширить `assert_allowed` — добавить `to_key: str | None = None` в сигнатуру и передать его в `is_allowed(...)`.

В `journal_django/apps/renewals/engine.py` заменить локальное определение `FROZEN_KEY` (строки 24-27) на реэкспорт, чтобы источник был один:

```python
from apps.renewals.transitions import FROZEN_KEY  # noqa: F401  (реэкспорт для вызывающих)
```

- [ ] **Step 4: Прогнать тесты**

Run: `pytest apps/renewals/tests/test_transitions.py apps/renewals/tests/test_engine.py -v`
Expected: PASS. Если падает импорт в `engine.py` (циклический) — проверить, что `transitions.py` ничего не импортирует из `apps.renewals`.

- [ ] **Step 5: Прокинуть `to_key` в вызов валидатора**

В `journal_django/apps/renewals/repository.py::move_deal` (строки 131-135) добавить аргумент:

```python
        assert_allowed(from_kind=from_stage.kind, to_kind=to_stage.kind,
                       from_is_auto=from_stage.is_auto, to_is_auto=to_stage.is_auto,
                       from_key=from_stage.key, to_key=to_stage.key,
                       cycle_completed=engine.cycle_completed(deal),
                       balance=float(balance_for_student(deal.student_id)))
```

- [ ] **Step 6: Прогнать тесты записи**

Run: `pytest apps/renewals -v`
Expected: PASS (падений быть не должно — `to_key` необязателен).

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/renewals/transitions.py journal_django/apps/renewals/engine.py journal_django/apps/renewals/repository.py journal_django/apps/renewals/tests/test_transitions.py
git commit -m "feat(renewals): переход в «Заморожен» разрешён посреди цикла"
```

---

### Task 3: Поле `frozen_until_month` на сделке + индекс + бэкфил

**Files:**
- Modify: `journal_django/apps/renewals/models.py:104-110`
- Create: `journal_django/apps/renewals/migrations/_frozen_month_backfill.py`
- Create: `journal_django/apps/renewals/migrations/0013_deal_frozen_until_month.py`
- Test: `journal_django/apps/renewals/tests/test_frozen_stage.py`

- [ ] **Step 1: Написать падающий тест бэкфила**

Добавить в `journal_django/apps/renewals/tests/test_frozen_stage.py`:

```python
from datetime import date

from django.db import connection

from apps.renewals.migrations._frozen_month_backfill import BACKFILL_SQL
from apps.renewals.models import RenewalDeal
from apps.students.models import Student


@pytest.mark.django_db
def test_backfill_sql_takes_month_from_student_frozen_until():
    """Бэкфил (миграция 0013) переносит месяц заморозки с ученика на его открытую
    сделку, стоящую на стадии 'frozen'. Тот же SQL гоняем повторно — он
    идемпотентен (WHERE frozen_until_month IS NULL)."""
    if 'frozen_until' not in {c.name for c in
                              connection.introspection.get_table_description(
                                  connection.cursor(), 'students')}:
        pytest.skip('колонка students.frozen_until уже удалена (задача 12)')

    student = Student.objects.create(
        full_name='__bf_frozen__', enrollment_status='frozen',
        frozen_from=date(2026, 7, 1), frozen_until=date(2026, 9, 20),
        created_at='2026-07-01T00:00:00Z')
    stage = RenewalStage.objects.get(pipeline__is_default=True, key='frozen')
    deal = RenewalDeal.objects.create(
        student=student, cycle_no=1, pipeline=stage.pipeline, stage=stage)

    with connection.cursor() as cur:
        cur.execute(BACKFILL_SQL)

    deal.refresh_from_db()
    assert deal.frozen_until_month == date(2026, 9, 1)
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `pytest apps/renewals/tests/test_frozen_stage.py::test_backfill_sql_takes_month_from_student_frozen_until -v`
Expected: FAIL — `ModuleNotFoundError: apps.renewals.migrations._frozen_month_backfill`.

- [ ] **Step 3: Добавить поле в модель**

В `journal_django/apps/renewals/models.py`, в `RenewalDeal` после `due_at` (строка 104):

```python
    # Месяц окончания заморозки («до какого месяца»), всегда 1-е число.
    # Заполнено ТОЛЬКО пока сделка на стадии key='frozen'; уход со стадии
    # обнуляет (repository.move_deal / engine.return_from_freeze). DB-CHECK нет:
    # ключ стадии живёт в другой таблице, условие по FK-джойну не выражается.
    frozen_until_month = models.DateField(null=True, blank=True)
```

В `Meta.indexes` того же класса добавить:

```python
            # Подзапрос «последняя сделка ученика» (аннотация стадии в
            # apps/students/repository.py): без -cycle_no это сортировка на
            # каждую строку списка учеников.
            models.Index(fields=['student', '-cycle_no'],
                         name='renewal_deal_student_cycle_idx'),
```

- [ ] **Step 4: Написать SQL бэкфила отдельным модулем**

Создать `journal_django/apps/renewals/migrations/_frozen_month_backfill.py`:

```python
"""SQL бэкфила месяца заморозки — отдельным модулем, чтобы тест мог прогнать
ровно то же выражение, что и миграция 0013 (тот же приём, что
apps/students/migrations/_frozen_backfill_util.py).

Читает students.frozen_until, которую удаляет students/0016 — поэтому 0016
объявляет зависимость от renewals/0013.
"""

BACKFILL_SQL = """
    UPDATE renewal_deal d
       SET frozen_until_month = date_trunc('month', s.frozen_until)::date
      FROM students s, renewal_stage st
     WHERE s.id = d.student_id
       AND st.id = d.stage_id
       AND st.key = 'frozen'
       AND d.outcome_at IS NULL
       AND d.frozen_until_month IS NULL
       AND s.frozen_until IS NOT NULL
"""
```

- [ ] **Step 5: Написать миграцию**

Создать `journal_django/apps/renewals/migrations/0013_deal_frozen_until_month.py`:

```python
"""Месяц окончания заморозки переезжает на сделку (спека 2026-07-25).

Раньше период заморозки жил на ученике (students.frozen_from/frozen_until) и
двигал расписание. Теперь заморозка — просто стадия воронки, и от периода
остаётся только «до какого месяца» — свойство сделки.

Бэкфил переносит месяц уже замороженных учеников, пока колонка
students.frozen_until ещё существует (её удаляет students/0016).
"""
from django.db import migrations, models

from apps.renewals.migrations._frozen_month_backfill import BACKFILL_SQL


def backfill(apps, schema_editor):
    schema_editor.execute(BACKFILL_SQL)


def noop(apps, schema_editor):
    """Откат не нужен: RemoveField ниже уносит колонку вместе с данными."""


class Migration(migrations.Migration):

    dependencies = [
        ('renewals', '0012_frozen_manual_stage'),
        ('students', '0015_drop_not_enrolled_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='renewaldeal',
            name='frozen_until_month',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name='renewaldeal',
            index=models.Index(fields=['student', '-cycle_no'],
                               name='renewal_deal_student_cycle_idx'),
        ),
        migrations.RunPython(backfill, noop),
    ]
```

- [ ] **Step 6: Проверить, что Django не хочет дополнительных миграций**

Run: `python manage.py makemigrations --check --dry-run`
Expected: «No changes detected». Если Django просит миграцию для `renewaldealevent` (pghistory-модель) — сгенерировать её (`python manage.py makemigrations renewals`) и включить в коммит: трекинг pghistory обязан знать новое поле.

- [ ] **Step 7: Прогнать полный pytest**

Run: `pytest`
Expected: все тесты проходят, включая новый тест бэкфила.

Полный прогон обязателен: приложения по-разному инициализируют тестовую БД, и новая колонка ломает raw-SQL-вставки только на общем прогоне.

- [ ] **Step 8: Commit**

```bash
git add journal_django/apps/renewals/models.py journal_django/apps/renewals/migrations/ journal_django/apps/renewals/tests/test_frozen_stage.py
git commit -m "feat(renewals): frozen_until_month на сделке + индекс (student, -cycle_no)"
```

---

### Task 4: `move_deal` принимает и обнуляет месяц заморозки

**Files:**
- Modify: `journal_django/apps/renewals/repository.py:113-158` (`move_deal`)
- Modify: `journal_django/apps/renewals/serializers.py:12-14` (`MoveSerializer`)
- Modify: `journal_django/apps/renewals/views.py:108-124` (`RenewalMoveView`)
- Create: `journal_django/apps/renewals/tests/test_frozen_stage.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `journal_django/apps/renewals/tests/test_frozen_stage.py` (поведение заморозки; состояние засидированной стадии живёт в `test_seed.py`) с шапкой `"""Заморозка как обычная стадия воронки (спека 2026-07-25)."""` и тестами:

```python
MOVE_URL = '/api/admin/renewals/{}/move'


@pytest.mark.django_db
def test_move_to_frozen_requires_month(admin_client, open_deal, frozen_stage):
    """Без месяца заморозки переход в «Заморожен» не проходит — 400."""
    resp = admin_client.post(MOVE_URL.format(open_deal.id),
                             {'to_stage_id': frozen_stage.id},
                             content_type='application/json')
    assert resp.status_code == 400
    assert 'frozen_until_month' in resp.json()


@pytest.mark.django_db
def test_move_to_frozen_normalizes_month(admin_client, open_deal, frozen_stage):
    """День из ввода отбрасывается: храним 1-е число месяца."""
    resp = admin_client.post(MOVE_URL.format(open_deal.id),
                             {'to_stage_id': frozen_stage.id,
                              'frozen_until_month': '2026-09-17'},
                             content_type='application/json')
    assert resp.status_code == 200
    open_deal.refresh_from_db()
    assert open_deal.frozen_until_month == date(2026, 9, 1)
    assert open_deal.stage_id == frozen_stage.id


@pytest.mark.django_db
def test_leaving_frozen_clears_month(admin_client, open_deal, frozen_stage,
                                     thinking_stage):
    """Уход со стадии «Заморожен» обнуляет месяц — иначе он «прилипает» мёртвым."""
    from apps.renewals import repository as repo
    repo.move_deal(open_deal.id, frozen_stage.id, None, None,
                   frozen_until_month=date(2026, 9, 1))
    repo.move_deal(open_deal.id, thinking_stage.id, None, None)
    open_deal.refresh_from_db()
    assert open_deal.frozen_until_month is None
    assert open_deal.stage_id == thinking_stage.id


@pytest.mark.django_db
def test_freeze_activity_mentions_month(open_deal, frozen_stage):
    """В таймлайне видно, до какого месяца заморозка."""
    from apps.renewals import repository as repo
    repo.move_deal(open_deal.id, frozen_stage.id, None, None,
                   frozen_until_month=date(2026, 9, 1))
    body = (open_deal.activities.filter(kind='stage_change')
            .order_by('-created_at').first().body)
    assert 'сентября 2026' in body
```

Фикстуры `admin_client` и `teacher_client` уже определены в корневом `journal_django/conftest.py` (строки 129 и 150) и доступны любому тесту без импорта. Локальные фикстуры добавить в тот же файл теста:

```python
@pytest.fixture
def frozen_stage():
    return RenewalStage.objects.get(pipeline__is_default=True, key='frozen')


@pytest.fixture
def thinking_stage():
    return RenewalStage.objects.get(pipeline__is_default=True, key='thinking')


@pytest.fixture
def open_deal(frozen_stage):
    """Открытая сделка на «Ждём продление» с отработанным циклом: ручные
    переходы в decision-стадии разрешены, ворота cycle_completed не мешают."""
    student = Student.objects.create(
        full_name='__frozen_stage_stud__', created_at='2026-07-01T00:00:00Z')
    awaiting = RenewalStage.objects.get(
        pipeline__is_default=True, key='awaiting_renewal')
    return RenewalDeal.objects.create(
        student=student, cycle_no=1, pipeline=frozen_stage.pipeline, stage=awaiting)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest apps/renewals/tests/test_frozen_stage.py -v`
Expected: FAIL — `move_deal() got an unexpected keyword argument 'frozen_until_month'` и 200 вместо 400 в первом тесте.

- [ ] **Step 3: Реализовать в `repository.move_deal`**

Заменить сигнатуру (строки 113-114) и добавить обработку месяца:

```python
def move_deal(deal_id: int, to_stage_id: int, reason_code: str | None,
              author_id: int | None, frozen_until_month=None) -> dict | None:
    """Переместить сделку в стадию, записать активность, синхронизировать outcome.

    frozen_until_month («до какого месяца заморозка») пишется только при
    переходе НА стадию key='frozen'; при переходе с неё — обнуляется, чтобы
    мёртвый месяц не «прилипал» к сделке. Обязательность поля проверяет
    MoveSerializer (у него есть to_stage_id, значит и ключ стадии).
    """
```

После `assert_allowed(...)` и перед `deal.stage = to_stage` добавить:

```python
        from apps.renewals.transitions import FROZEN_KEY
        to_frozen = to_stage.key == FROZEN_KEY
        deal.frozen_until_month = frozen_until_month if to_frozen else None
```

В `deal.save(update_fields=[...])` добавить `'frozen_until_month'`:

```python
        deal.save(update_fields=['stage', 'stage_entered_at', 'reason_code',
                                 'outcome_at', 'frozen_until_month', 'updated_at'])
```

Заменить создание активности так, чтобы у заморозки в тексте был месяц:

```python
        body = reason_code or ''
        if to_frozen and frozen_until_month is not None:
            body = f'Заморозка до {month_label(frozen_until_month)}'
        RenewalActivity.objects.create(
            deal=deal, kind='stage_change', from_stage=from_stage, to_stage=to_stage,
            author_id=author_id, body=body)
```

Добавить хелпер рядом с другими приватными функциями `repository.py` (модуль уже импортирует `connection`; новых зависимостей не нужно):

```python
_MONTHS_GENITIVE = (
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
)


def month_label(value) -> str:
    """date(2026, 9, 1) → «сентября 2026» — для текста активности таймлайна."""
    return f'{_MONTHS_GENITIVE[value.month - 1]} {value.year}'
```

- [ ] **Step 4: Реализовать валидацию в сериализаторе**

В `journal_django/apps/renewals/serializers.py` заменить `MoveSerializer`:

```python
class MoveSerializer(serializers.Serializer):
    to_stage_id = serializers.IntegerField()
    reason_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    # «До какого месяца заморозка». Обязателен при переходе в стадию 'frozen',
    # на других стадиях игнорируется. День из ввода отбрасывается — храним 1-е число.
    frozen_until_month = serializers.DateField(required=False, allow_null=True)

    def validate(self, data: dict) -> dict:
        from apps.renewals.models import RenewalStage
        from apps.renewals.transitions import FROZEN_KEY

        key = (RenewalStage.objects
               .filter(id=data['to_stage_id']).values_list('key', flat=True).first())
        month = data.get('frozen_until_month')
        if key == FROZEN_KEY:
            if month is None:
                raise serializers.ValidationError(
                    {'frozen_until_month': 'Укажите, до какого месяца заморозка'})
            data['frozen_until_month'] = month.replace(day=1)
        else:
            data['frozen_until_month'] = None
        return data
```

- [ ] **Step 5: Прокинуть поле во вьюхе**

В `journal_django/apps/renewals/views.py::RenewalMoveView.post` передать месяц в репозиторий — рядом с уже передаваемыми `to_stage_id` / `reason_code`:

```python
        deal = repository.move_deal(
            pk,
            ser.validated_data['to_stage_id'],
            ser.validated_data.get('reason_code'),
            getattr(request.user, 'id', None),
            frozen_until_month=ser.validated_data.get('frozen_until_month'),
        )
```

Сверить с фактическим телом метода: если аргументы там передаются позиционно/иначе — сохранить существующий стиль, добавив только `frozen_until_month=`.

- [ ] **Step 6: Прогнать тесты**

Run: `pytest apps/renewals -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/renewals/repository.py journal_django/apps/renewals/serializers.py journal_django/apps/renewals/views.py journal_django/apps/renewals/tests/test_frozen_stage.py
git commit -m "feat(renewals): месяц заморозки в move_deal (обязателен на входе, обнуляется на выходе)"
```

---

### Task 5: Ручной выход из заморозки — `return_from_freeze` + эндпоинт

`engine.resume_from_freeze(student_id)` пока остаётся: его зовёт `students.services.resume_student`, который удаляется в задаче 10. Новая функция работает по сделке — так её вызывает UI.

**Files:**
- Modify: `journal_django/apps/renewals/engine.py`
- Modify: `journal_django/apps/renewals/views.py`
- Modify: `journal_django/apps/renewals/urls.py`
- Test: `journal_django/apps/renewals/tests/test_frozen_stage.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в `journal_django/apps/renewals/tests/test_frozen_stage.py`:

```python
UNFREEZE_URL = '/api/admin/renewals/{}/unfreeze'


@pytest.mark.django_db
def test_unfreeze_returns_to_computed_auto_stage(admin_client, open_deal, frozen_stage):
    """«Вернуть в работу» ставит расчётную авто-стадию и гасит месяц."""
    from apps.renewals import repository as repo
    repo.move_deal(open_deal.id, frozen_stage.id, None, None,
                   frozen_until_month=date(2026, 9, 1))

    resp = admin_client.post(UNFREEZE_URL.format(open_deal.id))
    assert resp.status_code == 200

    open_deal.refresh_from_db()
    assert open_deal.stage.is_auto is True
    assert open_deal.stage_id != frozen_stage.id
    assert open_deal.frozen_until_month is None
    assert open_deal.activities.filter(kind='system').exists()


@pytest.mark.django_db
def test_unfreeze_is_noop_when_not_frozen(admin_client, open_deal):
    """Сделка не на «Заморожен» — 409, стадия не меняется."""
    before = open_deal.stage_id
    resp = admin_client.post(UNFREEZE_URL.format(open_deal.id))
    assert resp.status_code == 409
    open_deal.refresh_from_db()
    assert open_deal.stage_id == before


@pytest.mark.django_db
def test_unfreeze_forbidden_for_teacher(teacher_client, open_deal):
    """RBAC: учителю раздел продлений недоступен."""
    resp = teacher_client.post(UNFREEZE_URL.format(open_deal.id))
    assert resp.status_code in (401, 403)
```

`teacher_client` — фикстура из корневого `journal_django/conftest.py:150`, дополнительных объявлений не нужно.

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest apps/renewals/tests/test_frozen_stage.py -v -k unfreeze`
Expected: FAIL — 404 (маршрута нет).

- [ ] **Step 3: Реализовать функцию движка**

Добавить в `journal_django/apps/renewals/engine.py` рядом с `resume_from_freeze`:

```python
@transaction.atomic
def return_from_freeze(deal_id: int, author_id: Optional[int] = None) -> Optional[RenewalDeal]:
    """«Вернуть в работу»: сделка со стадии 'frozen' → расчётная авто-стадия.

    Единственный выход из заморозки (решение пользователя 2026-07-25: автовыхода
    по факту записанного урока нет — sync_lesson_stage не трогает ручные стадии).
    Валидатор переходов обходим осознанно, как reopen_deal: встать на авто-стадию
    руками правила воронки не дают, а это не ручной переход, а пересчёт.

    None, если сделки нет, она закрыта или стоит не на 'frozen'.
    """
    from apps.finances.repository import balance_for_student

    deal = (RenewalDeal.objects.select_for_update().select_related('stage', 'pipeline')
            .filter(id=deal_id, outcome_at__isnull=True).first())
    if deal is None or deal.stage.key != FROZEN_KEY:
        return None

    auto = _auto_stages(deal.pipeline)
    progress_stages = _progress_stages(deal.pipeline)
    attended = _attended_total(deal.student_id)
    balance = float(balance_for_student(deal.student_id))
    target, _matured = _target_auto_stage(deal, attended, balance, auto, progress_stages)
    if target is None:
        return deal

    from_stage = deal.stage
    deal.stage = target
    deal.stage_entered_at = timezone.now()
    deal.frozen_until_month = None
    deal.save(update_fields=['stage', 'stage_entered_at', 'frozen_until_month', 'updated_at'])
    RenewalActivity.objects.create(
        deal=deal, kind='system', from_stage=from_stage, to_stage=target,
        author_id=author_id, body='Возврат в работу из заморозки')
    return deal
```

- [ ] **Step 4: Добавить вьюху**

В `journal_django/apps/renewals/views.py` рядом с `RenewalReopenView`:

```python
class RenewalUnfreezeView(APIView):
    """«Вернуть в работу»: сделка со стадии «Заморожен» → расчётная авто-стадия."""
    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        deal = engine.return_from_freeze(pk, author_id=getattr(request.user, 'id', None))
        if deal is None:
            return Response(
                {'error': 'Сделка не найдена или не находится в заморозке'},
                status=status.HTTP_409_CONFLICT)
        return Response(repository.deal_computed(deal.id))
```

Проверить, что в файле уже импортированы `engine`, `repository`, `status`, `IsManagerOrAdmin`; при необходимости дополнить импорты.

- [ ] **Step 5: Добавить маршрут**

В `journal_django/apps/renewals/urls.py` — импорт `RenewalUnfreezeView` в список и строка после `/reopen`:

```python
    path('/<int:pk>/unfreeze', RenewalUnfreezeView.as_view(), name='renewals-unfreeze'),
```

- [ ] **Step 6: Прогнать тесты**

Run: `pytest apps/renewals -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/renewals/engine.py journal_django/apps/renewals/views.py journal_django/apps/renewals/urls.py journal_django/apps/renewals/tests/test_frozen_stage.py
git commit -m "feat(renewals): ручной выход из заморозки (POST .../unfreeze)"
```

---

### Task 6: Месяц заморозки в ответах API сделок

Три raw-SQL-выборки отдают карточку/деталь/строку списка — во все нужно добавить `d.frozen_until_month`.

**Files:**
- Modify: `journal_django/apps/renewals/repository.py` (`deal_computed` ~строка 72, `_column_cards` ~строка 267, `list_deals` ~строка 459)
- Test: `journal_django/apps/renewals/tests/test_frozen_stage.py`

- [ ] **Step 1: Написать падающий тест**

```python
@pytest.mark.django_db
def test_frozen_month_visible_in_api(admin_client, open_deal, frozen_stage):
    """Месяц заморозки видно в детали сделки, на карточке доски и в списке."""
    from apps.renewals import repository as repo
    repo.move_deal(open_deal.id, frozen_stage.id, None, None,
                   frozen_until_month=date(2026, 9, 1))

    detail = admin_client.get(f'/api/admin/renewals/{open_deal.id}').json()
    assert detail['frozen_until_month'] == '2026-09-01'

    board = admin_client.get('/api/admin/renewals?view=board').json()
    frozen_col = next(c for c in board['columns'] if c['key'] == 'frozen')
    assert frozen_col['cards'][0]['frozen_until_month'] == '2026-09-01'
```

Контракт доски: `GET /api/admin/renewals` с `?view=board` (это же значение по умолчанию, см. `apps/renewals/views.py:52`) — отдаёт `{columns: [...]}`, где у колонки есть `key` и `cards`.

- [ ] **Step 2: Убедиться, что тест падает**

Run: `pytest apps/renewals/tests/test_frozen_stage.py::test_frozen_month_visible_in_api -v`
Expected: FAIL — `KeyError: 'frozen_until_month'`.

- [ ] **Step 3: Добавить колонку в три выборки**

В `deal_computed` (после `d.due_at, d.stage_entered_at, d.outcome_at, d.created_at,`):

```sql
               d.frozen_until_month,
```

В `_column_cards` (после `d.due_at, a.full_name AS assignee_name,`):

```sql
                   d.frozen_until_month,
```

В `list_deals` (после `d.due_at, a.full_name AS assignee_name,`):

```sql
                   d.frozen_until_month,
```

- [ ] **Step 4: Прогнать тесты**

Run: `pytest apps/renewals -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals/repository.py journal_django/apps/renewals/tests/test_frozen_stage.py
git commit -m "feat(renewals): frozen_until_month в детали, карточке и списке сделок"
```

---

### Task 7: Стадия последней сделки в API учеников

**Files:**
- Modify: `journal_django/apps/students/repository.py:41-147`
- Modify: `journal_django/apps/students/serializers.py:24-47`
- Modify: `journal_django/apps/students/views.py:44` (whitelist сортировки)
- Create: `journal_django/apps/students/tests/test_students_stage_annotation.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `journal_django/apps/students/tests/test_students_stage_annotation.py`:

```python
"""Стадия последней сделки как «статус» ученика (спека 2026-07-25).

Открытая сделка → её стадия, stage_is_open=True. Все закрыты → стадия
последнего цикла, stage_is_open=False. Нет сделок → stage=None.
"""
from datetime import date

import pytest
from django.utils import timezone

from apps.renewals.models import RenewalDeal, RenewalStage
from apps.students import repository
from apps.students.models import Student


@pytest.fixture
def stages():
    pipe_filter = {'pipeline__is_default': True}
    return {
        'frozen': RenewalStage.objects.get(**pipe_filter, key='frozen'),
        'churned': RenewalStage.objects.get(**pipe_filter, key='churned'),
        'awaiting': RenewalStage.objects.get(**pipe_filter, key='awaiting_renewal'),
    }


def _student(name):
    return Student.objects.create(full_name=name, created_at=timezone.now())


@pytest.mark.django_db
def test_open_deal_stage_is_reported(stages):
    st = _student('__stage_open__')
    RenewalDeal.objects.create(student=st, cycle_no=1,
                               pipeline=stages['frozen'].pipeline,
                               stage=stages['frozen'],
                               frozen_until_month=date(2026, 9, 1))
    row = repository.get_student(st.id)
    assert row['stage']['key'] == 'frozen'
    assert row['stage']['label'] == 'Заморожен'
    assert row['stage_is_open'] is True
    assert row['stage_frozen_until_month'] == date(2026, 9, 1)


@pytest.mark.django_db
def test_closed_deal_stage_is_reported_as_not_open(stages):
    st = _student('__stage_closed__')
    RenewalDeal.objects.create(student=st, cycle_no=1,
                               pipeline=stages['churned'].pipeline,
                               stage=stages['churned'],
                               outcome_at=timezone.now())
    row = repository.get_student(st.id)
    assert row['stage']['key'] == 'churned'
    assert row['stage_is_open'] is False
    assert row['stage_frozen_until_month'] is None


@pytest.mark.django_db
def test_latest_cycle_wins(stages):
    """Показываем стадию последнего цикла, а не первого."""
    st = _student('__stage_latest__')
    RenewalDeal.objects.create(student=st, cycle_no=1,
                               pipeline=stages['churned'].pipeline,
                               stage=stages['churned'], outcome_at=timezone.now())
    RenewalDeal.objects.create(student=st, cycle_no=2,
                               pipeline=stages['awaiting'].pipeline,
                               stage=stages['awaiting'])
    row = repository.get_student(st.id)
    assert row['stage']['key'] == 'awaiting_renewal'
    assert row['stage_is_open'] is True


@pytest.mark.django_db
def test_student_without_deals_has_no_stage():
    st = _student('__stage_none__')
    row = repository.get_student(st.id)
    assert row['stage'] is None
    assert row['stage_is_open'] is False
    assert row['stage_frozen_until_month'] is None


@pytest.mark.django_db
def test_filter_by_stage_id(stages):
    st = _student('__stage_filter__')
    RenewalDeal.objects.create(student=st, cycle_no=1,
                               pipeline=stages['frozen'].pipeline,
                               stage=stages['frozen'],
                               frozen_until_month=date(2026, 9, 1))
    result = repository.list_students(
        page_size=500, filters={'stage_id': stages['frozen'].id})
    names = [r['full_name'] for r in result['rows']]
    assert '__stage_filter__' in names
    assert all(r['stage']['key'] == 'frozen' for r in result['rows'])


@pytest.mark.django_db
def test_sort_by_stage(stages):
    """sort_by='stage' сортирует по sort_order стадии, не по её id/подписи."""
    result = repository.list_students(page_size=500, sort_by='stage', sort_dir='asc')
    orders = [r['stage']['sort_order'] for r in result['rows'] if r['stage']]
    assert orders == sorted(orders)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest apps/students/tests/test_students_stage_annotation.py -v`
Expected: FAIL — `KeyError: 'stage'`.

- [ ] **Step 3: Реализовать аннотацию в репозитории**

В `journal_django/apps/students/repository.py` добавить импорты (`OuterRef`, `Subquery` к существующим из `django.db.models`) и блок рядом с `_apply_filters`:

```python
def _annotate_stage(qs):
    """Стадия ПОСЛЕДНЕЙ сделки ученика (max cycle_no) — «статус» ученика после
    удаления enrollment_status (спека 2026-07-25).

    Четыре коррелированных подзапроса вместо джойна: одна сделка на строку,
    индекс renewal_deal_student_cycle_idx делает каждый index-only lookup'ом.
    Подписи стадий подзапросом НЕ тянем — воронка это 7 строк, их отдаёт
    _stage_index() одним запросом (см. _attach_stage).
    """
    from apps.renewals.models import RenewalDeal
    latest = RenewalDeal.objects.filter(student_id=OuterRef('pk')).order_by('-cycle_no')
    return qs.annotate(
        stage_id=Subquery(latest.values('stage_id')[:1]),
        stage_sort_order=Subquery(latest.values('stage__sort_order')[:1]),
        stage_outcome_at=Subquery(latest.values('outcome_at')[:1]),
        stage_month=Subquery(latest.values('frozen_until_month')[:1]),
    )


def _stage_index() -> dict[int, dict]:
    """stage_id → {id, key, label, kind, sort_order}. Воронка мала, читаем целиком."""
    from apps.renewals.models import RenewalStage
    return {s['id']: s for s in RenewalStage.objects.values(
        'id', 'key', 'label', 'kind', 'sort_order')}


def _attach_stage(rows: list[dict]) -> list[dict]:
    """Разворачивает аннотации в контракт stage / stage_is_open /
    stage_frozen_until_month. Месяц показываем только на стадии 'frozen' —
    на других он либо мёртвый, либо ещё не обнулён историческими данными."""
    from apps.renewals.transitions import FROZEN_KEY
    index = _stage_index() if any(r.get('stage_id') for r in rows) else {}
    for r in rows:
        stage_id = r.pop('stage_id', None)
        outcome_at = r.pop('stage_outcome_at', None)
        month = r.pop('stage_month', None)
        r.pop('stage_sort_order', None)  # только для ORDER BY
        stage = index.get(stage_id)
        r['stage'] = dict(stage) if stage else None
        r['stage_is_open'] = stage is not None and outcome_at is None
        r['stage_frozen_until_month'] = (
            month if stage is not None and stage['key'] == FROZEN_KEY else None)
    return rows
```

В `_SORTABLE` добавить строку:

```python
    'stage':               'stage_sort_order',
```

В `_apply_filters` добавить фильтр (аннотация применяется до фильтров, см. ниже):

```python
    stage_id = filters.get('stage_id')
    if stage_id not in (None, ''):
        try:
            stage_id = int(stage_id)
        except (TypeError, ValueError):
            pass  # невалидное значение — фильтр молча игнорируется (как manager_id)
        else:
            qs = qs.filter(stage_id=stage_id)
```

Переписать `list_students` так, чтобы `count()` не тащил подзапросы без нужды:

```python
    sort_field = _SORTABLE.get(sort_by) or _SORTABLE[_DEFAULT_SORT_BY]
    order_prefix = '' if sort_dir == 'asc' else '-'

    # Аннотация стадии нужна для COUNT только если по ней фильтруют или сортируют:
    # иначе считаем по «чистому» queryset, не платя за 4 подзапроса на строку.
    needs_stage_in_count = (filters.get('stage_id') not in (None, '')
                            or sort_field == 'stage_sort_order')
    base = Student.objects.all()
    if needs_stage_in_count:
        base = _annotate_stage(base)
    base = _apply_filters(base, filters)

    total = base.count()

    page_qs = base if needs_stage_in_count else _annotate_stage(base)
    offset = max(0, (page - 1) * page_size)
    ordered = page_qs.order_by(f'{order_prefix}{sort_field}', '-id')
    rows = dictrows(ordered[offset:offset + page_size].values(
        *_STUDENT_VALUES_FIELDS, *_STAGE_VALUES_FIELDS,
        manager_name=F('manager__full_name'),
    ))

    return {
        'rows': _attach_stage(rows),
        'total': total,
        'page': page,
        'page_size': page_size,
    }
```

Рядом с `_STUDENT_VALUES_FIELDS` добавить:

```python
# Аннотации стадии: в .values() их нужно перечислять явно.
_STAGE_VALUES_FIELDS = ('stage_id', 'stage_sort_order', 'stage_outcome_at', 'stage_month')
```

Обновить `get_student`:

```python
def get_student(student_id: int) -> Optional[dict]:
    """Возвращает одного ученика по id или None."""
    rows = _attach_stage(dictrows(
        _annotate_stage(Student.objects.filter(id=student_id)).values(
            *_STUDENT_VALUES_FIELDS, *_STAGE_VALUES_FIELDS,
            manager_name=F('manager__full_name'),
        )))
    return rows[0] if rows else None
```

`create_student` и `update_student` возвращают ученика тем же путём — заменить в них финальный `dictrow(...)` на `get_student(obj.pk)` / `get_student(student_id)`, чтобы контракт ответа был единым и не пришлось дублировать аннотацию.

- [ ] **Step 4: Добавить поля в сериализатор чтения**

В `journal_django/apps/students/serializers.py::StudentReadSerializer` после `manager_name`:

```python
    # Стадия последней сделки продления — заменила enrollment_status.
    # dict или None; поля совпадают с renewal_stage (id/key/label/kind/sort_order).
    stage = serializers.DictField(allow_null=True)
    stage_is_open = serializers.BooleanField()
    stage_frozen_until_month = DateStringField(allow_null=True)
```

- [ ] **Step 5: Разрешить сортировку по стадии в вьюхе**

В `journal_django/apps/students/views.py` (строка 44) добавить `'stage'` в whitelist `sort_by` рядом с `'enrollment_status'` (сам `enrollment_status` уходит в задаче 12).

- [ ] **Step 6: Прогнать тесты**

Run: `pytest apps/students -v`
Expected: PASS, включая новый файл. Если падает `test_students_api.py` на проверке набора полей — добавить в её список ожидаемых полей `stage`, `stage_is_open`, `stage_frozen_until_month`.

- [ ] **Step 7: Проверить план запроса на dev-БД**

Run:
```bash
python manage.py dbshell -- -c "EXPLAIN ANALYZE SELECT s.id, (SELECT d.stage_id FROM renewal_deal d WHERE d.student_id = s.id ORDER BY d.cycle_no DESC LIMIT 1) FROM students s LIMIT 2000;"
```
Expected: в плане `Index Scan using renewal_deal_student_cycle_idx`, общее время — десятки миллисекунд. Если видно `Seq Scan` по `renewal_deal` — индекс из задачи 3 не применился, проверить `\d renewal_deal`.

- [ ] **Step 8: Commit**

```bash
git add journal_django/apps/students/repository.py journal_django/apps/students/serializers.py journal_django/apps/students/views.py journal_django/apps/students/tests/test_students_stage_annotation.py
git commit -m "feat(students): стадия последней сделки в API вместо статуса"
```

---

### Task 8: `StageBadge` вместо `StatusBadge` на фронте

**Files:**
- Create: `journal_django/frontend/admin-src/src/components/StageBadge.tsx`
- Delete: `journal_django/frontend/admin-src/src/components/StatusBadge.tsx`
- Modify: `src/lib/shared-types.ts:81,97-99`, `src/lib/labels.ts:5-15`, `src/lib/table-settings.ts:43`
- Modify: `src/pages/students/StudentsListPage.tsx:13,110-117`, `src/pages/students/StudentDetailPage.tsx:224,290,297`
- Modify: `src/pages/groups/GroupMembersBlock.tsx:3,32`, `src/pages/payments/PaymentModal.tsx:16,167-169`
- Modify: `src/styles/components.css:421+`

- [ ] **Step 1: Обновить типы**

В `src/lib/shared-types.ts` удалить `export type EnrollmentStatus = ...` (строка 81) и поля `enrollment_status`, `frozen_from`, `frozen_until` у `Student`; добавить туда же:

```ts
/** Стадия воронки продлений — «статус» ученика после удаления enrollment_status. */
export interface StudentStage {
  id: number;
  key: string;
  label: string;
  kind: 'progress' | 'decision' | 'won' | 'lost';
  sort_order: number;
}
```

и в интерфейс `Student`:

```ts
  /** Стадия ПОСЛЕДНЕЙ сделки; null — сделок ещё не было. */
  stage: StudentStage | null;
  /** false — последняя сделка закрыта (won/lost): бейдж рисуется приглушённым. */
  stage_is_open: boolean;
  /** «До какого месяца заморозка», непусто только на стадии frozen. */
  stage_frozen_until_month: string | null;
```

- [ ] **Step 2: Создать компонент**

Создать `journal_django/frontend/admin-src/src/components/StageBadge.tsx`:

```tsx
import type { Student, StudentStage } from '../lib/types';

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

// Тон — по виду стадии, а не по её color из БД: цвет стадии принадлежит
// колонкам доски, а в таблицах и героях цвет несёт семантику из токенов.
// frozen выделен отдельно: это не «плохо» и не «хорошо», а пауза.
function toneOf(stage: StudentStage): 'positive' | 'negative' | 'info' | 'neutral' {
  if (stage.key === 'frozen') return 'neutral';
  if (stage.kind === 'won') return 'positive';
  if (stage.kind === 'lost') return 'negative';
  return 'info';
}

function monthLabel(iso: string): string {
  // iso = 'YYYY-MM-01' (DateStringField).
  const [y, m] = iso.split('-').map(Number);
  return `до ${MONTHS[m - 1]} ${y}`;
}

type StageLike = Pick<Student, 'stage' | 'stage_is_open' | 'stage_frozen_until_month'>;

export function StageBadge({ row }: { row: StageLike }) {
  const { stage } = row;
  if (!stage) return <span className="text-muted">—</span>;

  const tone = toneOf(stage);
  const label = row.stage_frozen_until_month
    ? `${stage.label} · ${monthLabel(row.stage_frozen_until_month)}`
    : stage.label;

  return (
    <span
      className={`status-badge status-badge--${tone}${row.stage_is_open ? '' : ' status-badge--muted'}`}
      title={row.stage_is_open ? undefined : 'Сделка закрыта'}
    >
      {label}
    </span>
  );
}
```

- [ ] **Step 3: Добавить приглушённый и нейтральный варианты в CSS**

В `src/styles/components.css`, в секции `/* ===== StatusBadge ... */` (строка 421) переименовать комментарий в `StageBadge` и добавить модификаторы, опираясь на уже существующие в файле токены (взять названия переменных из соседних правил `.status-badge--info` — не вводить новых hex):

```css
/* Закрытая сделка: та же семантика, меньше веса — бейдж не спорит с открытыми. */
.status-badge--muted { opacity: .6; }

/* Заморозка — пауза, а не оценка: нейтральный тон. */
.status-badge--neutral {
  background: var(--surface-subtle);
  color: var(--text-secondary);
}
```

Перед коммитом проверить, что `--surface-subtle` и `--text-secondary` существуют в `src/styles/tokens.css`; если названия другие — использовать фактические (иначе `var()` схлопнется молча).

- [ ] **Step 4: Переключить три места использования**

`src/pages/students/StudentsListPage.tsx` — заменить импорт `StatusBadge` на `StageBadge`, убрать импорт `ENROLLMENT_STATUS_OPTIONS`, добавить `import { useRenewalStages } from '../../hooks/useRenewalStages';` и `const { data: stages } = useRenewalStages();` рядом с прочими хуками страницы, затем заменить колонку:

```tsx
    {
      key: 'stage',
      label: 'Стадия',
      sortable: true,
      searchable: true,
      searchOptions: (stages || []).map((s) => ({ value: String(s.id), label: s.label })),
      cell: (r) => <StageBadge row={r} />,
    },
```

`src/pages/students/StudentDetailPage.tsx` — `badge={<StageBadge row={student} />}` (строка 224); удалить строку поля `enrollment_status` из массива полей (строка 290) и убрать `'enrollment_status'` из списка ключей на строке 297: бейдж в герое эту строку дублирует.

`src/pages/groups/GroupMembersBlock.tsx` — заменить `<StatusBadge row={s} />` на `<StageBadge row={s} />`.

`src/pages/payments/PaymentModal.tsx` — убрать импорт `ENROLLMENT_STATUS_LABELS` и упростить подпись:

```tsx
        label: s.full_name,
```

- [ ] **Step 5: Почистить labels и настройки колонок**

В `src/lib/labels.ts` удалить `ENROLLMENT_STATUS_LABELS`, `ENROLLMENT_STATUS_OPTIONS` и импорт типа `EnrollmentStatus`.
В `src/lib/table-settings.ts` (строка 43) заменить `{ key: 'enrollment_status', label: 'Статус' }` на `{ key: 'stage', label: 'Стадия' }`.
Удалить файл `src/components/StatusBadge.tsx`.

- [ ] **Step 6: Проверить типы**

Run (из `journal_django/frontend/admin-src/`): `npm run typecheck`
Expected: без ошибок. Ожидаемые падения на этом шаге — только в `StudentStatusModal.tsx` и `RenewalBoard.tsx` (они удаляются/переписываются в задаче 9). Если так — выполнить задачу 9 и вернуться к `typecheck`; сборку (`npm run build`) не запускать.

- [ ] **Step 7: Commit**

```bash
git add journal_django/frontend/admin-src/src
git commit -m "feat(admin-ui): StageBadge вместо StatusBadge (стадия сделки как статус)"
```

---

### Task 9: Доска продлений и страница ученика без модалки статуса

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/renewals/FreezeDealDialog.tsx`
- Delete: `journal_django/frontend/admin-src/src/pages/students/StudentStatusModal.tsx`
- Modify: `src/pages/renewals/RenewalBoard.tsx`, `src/pages/renewals/RenewalCardView.tsx`, `src/pages/renewals/RenewalDealDrawer.tsx`
- Modify: `src/pages/students/StudentDetailPage.tsx:36-83,209-217,356-362`
- Modify: `src/hooks/useRenewals.ts:114-145`, `src/lib/renewals.ts`

- [ ] **Step 1: Расширить типы и мутации сделок**

В `src/lib/renewals.ts` добавить `frozen_until_month: string | null;` в интерфейсы `RenewalCard`, `RenewalListRow` и `RenewalDealDetail`.

В `src/hooks/useRenewals.ts::useRenewalMutations` заменить `move` и добавить `unfreeze`:

```ts
    move: useMutation({
      mutationFn: ({ id, to_stage_id, reason_code, frozen_until_month }:
        { id: number; to_stage_id: number; reason_code?: string; frozen_until_month?: string }) =>
        api<RenewalDealDetail>('POST', `/api/admin/renewals/${id}/move`,
          { to_stage_id, reason_code, frozen_until_month }),
      onSuccess: invalidate,
    }),
    unfreeze: useMutation({
      mutationFn: ({ id }: { id: number }) =>
        api<RenewalDealDetail>('POST', `/api/admin/renewals/${id}/unfreeze`),
      // Стадия ученика показывается бейджем в списке учеников и в составе
      // группы — их кэш тоже нужно освежить.
      onSuccess: () => {
        invalidate();
        qc.invalidateQueries({ queryKey: ['students'] });
      },
    }),
```

- [ ] **Step 2: Создать диалог заморозки**

Создать `journal_django/frontend/admin-src/src/pages/renewals/FreezeDealDialog.tsx`:

```tsx
import { useState } from 'react';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { SelectInput } from '../../components/form/SelectInput';

const MONTHS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];

// 12 месяцев вперёд от текущего: заморозка «до» дальше года — не рабочий сценарий,
// а свободный ввод даты порождал бы вопрос «а день зачем?».
function monthOptions(): { value: string; label: string }[] {
  const now = new Date();
  return Array.from({ length: 12 }, (_, i) => {
    const d = new Date(now.getFullYear(), now.getMonth() + i, 1);
    const month = String(d.getMonth() + 1).padStart(2, '0');
    return {
      value: `${d.getFullYear()}-${month}-01`,
      label: `${MONTHS[d.getMonth()]} ${d.getFullYear()}`,
    };
  });
}

interface Props {
  studentName: string;
  pending: boolean;
  onClose: () => void;
  onConfirm: (frozenUntilMonth: string) => void;
}

export function FreezeDealDialog({ studentName, pending, onClose, onConfirm }: Props) {
  const options = monthOptions();
  const [month, setMonth] = useState(options[0].value);

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title="Заморозить сделку">
      <div className="status-form">
        <Field label="Заморозка до месяца">
          <SelectInput
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            options={options}
          />
        </Field>
        <div className="status-form__hint">
          {studentName}: сделка переедет в «Заморожен». Членство в группах и
          расписание не меняются — снимите их вручную, если нужно.
        </div>
        <div className="status-form__footer">
          <button type="button" className="btn-cancel" onClick={onClose}>Отмена</button>
          <button
            type="button"
            className="btn-save"
            onClick={() => onConfirm(month)}
            disabled={pending}
          >
            Заморозить
          </button>
        </div>
      </div>
    </Dialog>
  );
}
```

- [ ] **Step 3: Переписать обработку drop в `RenewalBoard`**

В `src/pages/renewals/RenewalBoard.tsx`:

1. Удалить импорты `StudentStatusModal`, `EnrollmentStatus`, состояние `statusModalStudent`, `statusMemberships`/`statusMembershipsReady` и блок рендера `<StudentStatusModal .../>` (строки 263-271).
2. Добавить `import { FreezeDealDialog } from './FreezeDealDialog';` и состояние:

```tsx
  const [freezeTarget, setFreezeTarget] = useState<
    { dealId: number; studentName: string; stageId: number } | null
  >(null);
```

3. Зону «Ушёл» перевести на обычный диалог закрытия (заменить блок `if (over.id === 'close-lost')`, строки 119-123):

```tsx
    // «Ушёл» — терминальная стадия 'churned' (kind='lost'); колонкой на доске
    // она не показана, drop в зону — единственный путь. Каскадов по членствам
    // больше нет: это обычное закрытие сделки с причиной.
    if (over.id === 'close-lost') {
      const card = dragCard(event);
      if (card) {
        setCloseTarget({
          dealId,
          studentId: card.student_id,
          studentName: card.student_name,
          mode: 'lost',
        });
      }
      return;
    }
```

4. Заменить спец-обработку авто-стадий (строки 149-158) на:

```tsx
    // Авто-стадии двигает только движок (transitions.is_allowed блокирует ручной
    // вход): колонка «Урок 1–4» не droppable, «Ждём оплату»/«Ждём продление» —
    // технически да. «Заморожен» больше не авто-стадия: у неё свой диалог, потому
    // что move требует месяц окончания.
    const targetStage = (stages || []).find((s) => s.id === toStageId);
    if (targetStage?.is_auto) {
      toast('Эта стадия управляется системой', 'info');
      return;
    }
    if (targetStage?.key === 'frozen') {
      const card = dragCard(event);
      if (card) {
        setFreezeTarget({ dealId, studentName: card.student_name, stageId: toStageId });
      }
      return;
    }
```

5. Отрендерить диалог рядом с `RenewalCloseDialog`:

```tsx
      {freezeTarget && (
        <FreezeDealDialog
          studentName={freezeTarget.studentName}
          pending={move.isPending}
          onClose={() => setFreezeTarget(null)}
          onConfirm={(frozen_until_month) => {
            move.mutate(
              { id: freezeTarget.dealId, to_stage_id: freezeTarget.stageId, frozen_until_month },
              {
                onSuccess: () => setFreezeTarget(null),
                onError: (err) => {
                  setFreezeTarget(null);
                  showError(err, 'Не удалось заморозить сделку');
                },
              },
            );
          }}
        />
      )}
```

- [ ] **Step 4: Показать месяц и действие «Вернуть в работу»**

В `src/pages/renewals/RenewalCardView.tsx` — там, где рисуются метки карточки (`due_at`, `days_in_stage`), добавить:

```tsx
      {card.frozen_until_month && (
        <span className="renewal-card__chip">до {monthShort(card.frozen_until_month)}</span>
      )}
```

Хелпер `monthShort` положить рядом с существующими форматтерами карточки (или переиспользовать уже имеющийся в файле форматтер даты, если он умеет месяц — проверить перед добавлением, чтобы не дублировать).

В `src/pages/renewals/RenewalDealDrawer.tsx` (панель сделки) — кнопка, видимая только на стадии заморозки:

```tsx
      {deal.stage_key === 'frozen' && (
        <button
          type="button"
          className="btn-save"
          onClick={() => unfreeze.mutate({ id: deal.id })}
          disabled={unfreeze.isPending}
        >
          Вернуть в работу
        </button>
      )}
```

`unfreeze` взять из `useRenewalMutations()` там же, где берётся `move`/`comment`.

- [ ] **Step 5: Убрать смену статуса со страницы ученика**

В `src/pages/students/StudentDetailPage.tsx`:
- удалить компонент `StudentResumeDialog` (строки 36-83), состояния `changingStatus` и `resuming`, импорт `StudentStatusModal`, блок рендера `<StudentStatusModal .../>` (строки 356-362) и `<StudentResumeDialog .../>`;
- из `menuItems` (строки 209-217) убрать «Изменить статус» и «Разморозить», оставив «Сменить менеджера» под тем же условием `canWriteStudentManager`;
- удалить `statusMemberships` (строки 167-174) — единственный потребитель ушёл. Если после этого `useMemberships`/`useGroupsAll` не используются на странице, убрать и их импорты (проверить остальные обращения перед удалением: `activeMemberships` используется в `meta` героя).

Удалить файл `src/pages/students/StudentStatusModal.tsx`.

- [ ] **Step 6: Проверить типы**

Run (из `journal_django/frontend/admin-src/`): `npm run typecheck`
Expected: без ошибок.

- [ ] **Step 7: Ручная проверка в браузере**

Запустить dev-окружение (nginx :8080 + `python manage.py runserver`) и проверить:
1. Продления → доска: перетащить карточку в «Заморожен» → появился диалог с месяцем → после сохранения на карточке видно «до <месяц>».
2. Перетащить карточку в зону «✕ Ушёл» → диалог причины → сделка закрылась.
3. В панели замороженной сделки нажать «Вернуть в работу» → стадия стала «Урок N»/«Ждём …», месяц исчез.
4. Страница ученика: в меню «…» нет «Изменить статус» и «Разморозить», бейдж в герое показывает стадию.
5. Список учеников: колонка «Стадия», фильтр по стадии работает, у ушедшего ученика бейдж приглушён.

- [ ] **Step 8: Commit**

```bash
git add journal_django/frontend/admin-src/src
git commit -m "feat(admin-ui): заморозка и уход как обычные переходы сделки, модалка статуса удалена"
```

---

### Task 10: Удалить каскады смены статуса на бэкенде

**Files:**
- Modify: `journal_django/apps/students/services.py:68-260`
- Modify: `journal_django/apps/students/{views,urls,serializers}.py`
- Modify: `journal_django/apps/renewals/engine.py`
- Modify: `journal_django/apps/scheduling/repository.py:1128-1470`
- Delete: `apps/students/tests/{test_status_service,test_status_api,test_freeze_preview_api,test_student_leave_cleanup}.py`, `apps/scheduling/tests/{test_freeze_scheduling,test_preview_freeze}.py`, `apps/renewals/tests/test_freeze_deal.py`

- [ ] **Step 1: Удалить сервисы смены статуса**

В `journal_django/apps/students/services.py` удалить: комментарий-заголовок блока (строки 68-72), `_affected_memberships`, `_active_individual_group_ids`, `change_student_status`, `resume_student`, `preview_freeze_schedule`, `_actor_id`.

Оставить: `list_students`, `get_student`, `create_student`, `update_student`, `student_stats`, `get_student_balance`, `add_comment`, `delete_comment`, `set_student_manager`. В `set_student_manager` параметр `actor` остаётся (он документирован как задел и в подписи), но убедиться, что `_actor_id` в нём не вызывается.

- [ ] **Step 2: Удалить вьюхи, маршруты и сериализаторы**

`apps/students/views.py`: удалить классы `StudentStatusView`, `StudentResumeView`, `StudentFreezePreviewView` и их импорты сериализаторов.
`apps/students/urls.py`: удалить три строки маршрутов `/status/preview`, `/status`, `/resume` и соответствующие импорты вьюх.
`apps/students/serializers.py`: удалить сериализаторы смены статуса/разморозки/превью (те, что использовались только этими вьюхами — найти по `grep -n "class Student.*Status\|Resume\|Freeze" apps/students/serializers.py`).

- [ ] **Step 3: Удалить каскадные функции движка**

В `journal_django/apps/renewals/engine.py` удалить `freeze_deal`, `decline_deal`, `resume_from_freeze` (её заменила `return_from_freeze` из задачи 5). Убрать упоминание `FROZEN_KEY`-исключения из докстринга `sync_lesson_stage` и сам его код:

```python
    deal = _open_deal_for_update(student_id)
    if deal is None or not deal.stage.is_auto:
        return
```

Докстринг привести в соответствие: стадия «Заморожен» теперь не авто, движок пропускает её общим правилом.

- [ ] **Step 4: Удалить мёртвый код расписания**

В `journal_django/apps/scheduling/repository.py` удалить `cancel_future_planned` (строка 1128), `preview_freeze` (1295), `freeze_individual_group` (1355), `resume_individual_group` (1453). Перед удалением подтвердить отсутствие вызовов:

Run: `grep -rn "freeze_individual_group\|resume_individual_group\|preview_freeze\|cancel_future_planned" journal_django --include=*.py`
Expected: совпадения только внутри удаляемых блоков и удаляемых тестов.

- [ ] **Step 5: Удалить тесты мёртвого кода**

```bash
git rm journal_django/apps/students/tests/test_status_service.py \
       journal_django/apps/students/tests/test_status_api.py \
       journal_django/apps/students/tests/test_freeze_preview_api.py \
       journal_django/apps/students/tests/test_student_leave_cleanup.py \
       journal_django/apps/scheduling/tests/test_freeze_scheduling.py \
       journal_django/apps/scheduling/tests/test_preview_freeze.py \
       journal_django/apps/renewals/tests/test_freeze_deal.py
```

- [ ] **Step 6: Прогнать тесты**

Run: `pytest apps/students apps/scheduling apps/renewals -v`
Expected: PASS. Ожидаемые падения — тесты, ссылающиеся на удалённые функции (например, `apps/renewals/tests/test_engine.py` на `freeze_deal`): удалить из них соответствующие тест-функции, так как проверяемого поведения больше нет.

- [ ] **Step 7: Commit**

```bash
git add -A journal_django/apps
git commit -m "refactor: удалить каскады смены статуса ученика (заморозка/уход)"
```

---

### Task 11: Периферийные потребители статуса

**Files:**
- Modify: `journal_django/apps/dashboard/registry_service.py:177-202`
- Modify: `journal_django/apps/sync/backfills/students.py`
- Modify: `journal_django/apps/changelog/labels.py:35-36`
- Modify: `journal_django/apps/changelog/summary.py:215-216`

- [ ] **Step 1: Реестр — считать активность по членству**

В `journal_django/apps/dashboard/registry_service.py::base_students_qs` удалить `.filter(enrollment_status='enrolled')` и поправить докстринг:

```python
def base_students_qs(today: datetime.date) -> QuerySet:
    """
    Активные ученики (есть активный membership в активной группе), аннотированные
    вычисляемыми полями. База и для списка, и для сводки.

    Статуса ученика больше нет (спека 2026-07-25): «учится» = активное членство.
    Ушедший ученик покидает реестр, когда менеджер снимает членство, а не по
    стадии сделки — фильтр по последней сделке был бы лишним коррелированным
    подзапросом в тяжёлом кешируемом запросе дашборда.
    """
```

- [ ] **Step 2: Sheets-бэкфил — убрать маппинг статуса**

В `journal_django/apps/sync/backfills/students.py`:
- удалить `map_enrollment_from_sheets` и импорт `from apps.students.migrations._frozen_backfill_util import ...` (файл-утилита остаётся: его использует историческая миграция 0010);
- из словаря строки убрать `enrollment_status`/`frozen_from`/`frozen_until` (строки 80-82);
- из `INSERT ... ON CONFLICT` убрать три колонки в списке вставки, в `DO UPDATE SET`, в `WHERE ... IS DISTINCT FROM` и три параметра (`status`, `frozen_from`, `frozen_until`);
- если `msk_now` после этого не используется — убрать и его импорт.

- [ ] **Step 3: Журнал изменений — правила и подписи полей**

В `journal_django/apps/changelog/labels.py` удалить два правила (строки 35-36) и добавить рядом с прочими renewals-правилами:

```python
    ('POST', re.compile(r'^/api/admin/renewals/\d+/unfreeze$'), 'renewal.unfreeze'),
```

Проверить, что у метки есть человекочитаемая подпись там, где определяются подписи операций (искать по существующей метке `renewal.` в `labels.py`), и добавить «Возврат из заморозки», если такой словарь есть.

В `journal_django/apps/changelog/summary.py` (строки 215-216) удалить `enrollment_status`, `frozen_from`, `frozen_until` и добавить:

```python
    'frozen_until_month': 'заморозка до месяца',
```

- [ ] **Step 4: Прогнать тесты**

Run: `pytest apps/dashboard apps/sync apps/changelog -v`
Expected: PASS. Если тест реестра ожидал исключения `declined`-ученика — переписать его так, чтобы «неактивность» задавалась снятым членством, а не статусом.

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/dashboard journal_django/apps/sync journal_django/apps/changelog
git commit -m "refactor: реестр, Sheets-бэкфил и журнал изменений без статуса ученика"
```

---

### Task 12: Удалить колонки из БД

**Files:**
- Create: `journal_django/apps/students/migrations/0016_drop_enrollment_status.py`
- Modify: `journal_django/apps/students/models.py:41-74`
- Modify: `journal_django/apps/students/repository.py`, `journal_django/apps/students/serializers.py`
- Delete: `journal_django/apps/students/tests/test_frozen_constraints.py`

- [ ] **Step 1: Убрать поля из модели**

В `journal_django/apps/students/models.py` удалить поля `enrollment_status`, `frozen_from`, `frozen_until` и все три `CheckConstraint` из `Meta.constraints` (после удаления `constraints` останется пустым списком — убрать и его).

- [ ] **Step 2: Убрать поля из репозитория и сериализаторов**

`apps/students/repository.py`: убрать `'enrollment_status'` из `_SORTABLE`; убрать `'enrollment_status', 'frozen_from', 'frozen_until'` из `_STUDENT_VALUES_FIELDS`; удалить блок фильтра `enrollment_status` из `_apply_filters` и упоминание в её докстринге; убрать три поля из `create_student` и из `update_student` (включая ветку сброса дат).

`apps/students/serializers.py`: удалить константу `ENROLLMENT_STATUS_CHOICES`, поля `enrollment_status`/`frozen_from`/`frozen_until` из `StudentReadSerializer`, `StudentWriteSerializer`, `StudentUpdateSerializer`, а также метод `StudentWriteSerializer.validate` (он проверял только связку frozen ↔ даты).

`apps/students/views.py`: убрать `'enrollment_status'` из whitelist `sort_by` (строка 44) и упоминание в докстринге списка (строка 53).

- [ ] **Step 3: Сгенерировать миграцию**

Run: `python manage.py makemigrations students --name drop_enrollment_status`
Expected: создан `apps/students/migrations/0016_drop_enrollment_status.py` с `RemoveConstraint` ×3 и `RemoveField` ×3.

Открыть файл и дописать зависимость от renewals (бэкфил месяца должен успеть прочитать колонку) и докстринг:

```python
    dependencies = [
        ('students', '0015_drop_not_enrolled_status'),
        # Бэкфил месяца заморозки читает students.frozen_until — он обязан
        # выполниться ДО удаления колонки (спека 2026-07-25).
        ('renewals', '0013_deal_frozen_until_month'),
    ]
```

- [ ] **Step 4: Удалить тест констрейнтов**

```bash
git rm journal_django/apps/students/tests/test_frozen_constraints.py
```

- [ ] **Step 5: Починить raw-SQL в тестах**

Найти прямые вставки со статусом:

Run: `grep -rn "enrollment_status" journal_django/apps --include=*.py`
Expected после правок: ни одного совпадения.

В файлах `apps/students/tests/{test_manager_service,test_manager_api,test_comment_repository,test_comment_api,test_freeze_preview_api}.py` и любых других из вывода grep заменить

```sql
INSERT INTO students (full_name, enrollment_status, created_at) VALUES (%s, 'enrolled', now())
```

на

```sql
INSERT INTO students (full_name, created_at) VALUES (%s, now())
```

(и убрать соответствующий параметр, если статус передавался параметром). Аналогично в `apps/students/tests/test_students_repository.py` и `test_students_api.py` удалить тесты и ассерты про статус: `test_filter_enrollment_status`, `test_enrollment_status_default_enrolled`, `test_update_enrollment_status`, `test_not_enrolled_rejected`, проверки frozen-дат.

- [ ] **Step 6: Прогнать полный pytest**

Run: `pytest`
Expected: все тесты проходят.

Полный прогон обязателен: часть приложений использует общую `journal_test`, часть — свежую `test_journal_test`, и удаление колонки ломает raw-SQL только на общем прогоне. Если падают тесты с `column "enrollment_status" does not exist` — остался raw-SQL из шага 5; если `relation ... does not exist` — пересоздать тестовую схему (`scripts/recreate_test_db.ps1`, предупредив пользователя: скрипт затирает seed-данные общей БД).

- [ ] **Step 7: Commit**

```bash
git add -A journal_django/apps/students
git commit -m "refactor(students): удалить enrollment_status и даты заморозки из БД"
```

---

### Task 13: Финальная верификация

- [ ] **Step 1: Полный прогон тестов**

Run: `pytest`
Expected: 0 failed. Записать итоговое число прошедших тестов.

- [ ] **Step 2: Проверка типов фронта**

Run (из `journal_django/frontend/admin-src/`): `npm run typecheck`
Expected: без ошибок.

- [ ] **Step 3: Убедиться, что от статусов не осталось следов**

Run: `grep -rn "enrollment_status\|EnrollmentStatus\|frozen_from\|StatusBadge\|StudentStatusModal\|freeze_individual_group\|resume_individual_group\|decline_deal\|freeze_deal" journal_django --include=*.py --include=*.ts --include=*.tsx | grep -v "/migrations/" | grep -v "-dist/"`
Expected: пусто. Совпадения в `apps/*/migrations/` и в собранных бандлах `*-dist/` — норма (история миграций не переписывается, бандлы пересоберутся при следующей сборке).

- [ ] **Step 4: Проверка миграций**

Run: `python manage.py makemigrations --check --dry-run`
Expected: «No changes detected».

- [ ] **Step 5: Ручной прогон сценариев в браузере**

Проверить на dev-окружении:
1. Список учеников: колонка «Стадия», фильтр по стадии, сортировка по стадии; у ученика без сделок — прочерк.
2. Страница ученика: бейдж стадии в герое; в меню «…» только «Сменить менеджера»; вкладка «Обучение» работает.
3. Состав группы: у участников виден бейдж стадии.
4. Внести оплату: в списке учеников подписи без суффикса статуса.
5. Продления: заморозка через drag&drop с выбором месяца; «Вернуть в работу»; закрытие «Ушёл» с причиной; заморозка сделки посреди цикла (не докрутив 4 урока) проходит.
6. Дашборд → «Реестр» открывается и содержит учеников с активным членством.
7. Журнал изменений: запись про заморозку сделки и про возврат из заморозки читается осмысленно.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: финальная верификация удаления статусов ученика"
```
