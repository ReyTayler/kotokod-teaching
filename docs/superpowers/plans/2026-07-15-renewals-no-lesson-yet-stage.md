# Продления: стадия «Не было урока» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** переименовать первую авто-стадию прогресса цикла продления (0 уроков в цикле) из «Урок 1» в «Не было урока», сдвинув «Урок 2/3/4» → «Урок 1/2/3», закрыв тем самым П-7 из `docs/renewals-tech-spec.md`.

**Architecture:** одна идемпотентная/обратимая data-миграция переименовывает 4 строки `renewal_stage` (key+label вместе); `engine.py` адресует прогресс-стадии позиционно (`sort_order`), поэтому код движка не меняется. Правки — тесты (ключи в assert'ах), doc-комментарий в `repository.py`, 2 фронтенд-файла (текст), 2 md-документа.

**Tech Stack:** Django (data migration, `apps.get_model`), pytest-django, React 19 / TypeScript (admin-src).

Спека: `docs/superpowers/specs/2026-07-15-renewals-no-lesson-yet-stage-design.md`.

Рабочая директория для всех Django/pytest команд — `journal_django/`. Рабочая директория для фронтенд-команд — `journal_django/frontend/admin-src/`.

⚠️ Footgun (см. память проекта): `pytest apps/lessons/...` **падает standalone** — conftest lessons переопределяет `django_db_setup=pass` и уходит в сталую БД без renewal-таблиц. Всегда гонять **полный** `pytest`, либо ставить renewals-тест **первым** позиционным аргументом.

---

### Task 1: Data-миграция переименования стадий

**Files:**
- Create: `journal_django/apps/renewals/migrations/0009_rename_lesson_progress_stages.py`

- [ ] **Step 1: Написать миграцию**

```python
"""
Переименование первой авто-стадии прогресса цикла (0 уроков этого цикла) из
«Урок 1» в «Не было урока» — закрывает П-7 из docs/renewals-tech-spec.md:
клампленный в «Урок 1» прогресс путал «только начал цикл» с «предоплаченный
следующий цикл, предыдущий ещё не отработан» (см. test_prepaid_cycle2_deal_
stays_on_no_lesson_yet). «Урок 2/3/4» сдвигаются на «Урок 1/2/3» — «Урок 4»
не сохраняется: into=4 перехватывается раньше правилом «Ждём продление»,
эта стадия физически никогда не занимает сделку.

engine.py адресует прогресс-стадии позиционно (sort_order), не по key/label —
код движка эта миграция не трогает.
"""
from django.db import migrations

# (старый key, новый key, новый label) — порядок важен, см. forward()/backward().
RENAMES = [
    ('lesson_1', 'no_lesson_yet', 'Не было урока'),
    ('lesson_2', 'lesson_1', 'Урок 1'),
    ('lesson_3', 'lesson_2', 'Урок 2'),
    ('lesson_4', 'lesson_3', 'Урок 3'),
]

OLD_LABELS = {'lesson_1': 'Урок 1', 'lesson_2': 'Урок 2',
              'lesson_3': 'Урок 3', 'lesson_4': 'Урок 4'}


def forward(apps, schema_editor):
    RenewalPipeline = apps.get_model('renewals', 'RenewalPipeline')
    RenewalStage = apps.get_model('renewals', 'RenewalStage')
    pipe = RenewalPipeline.objects.filter(is_default=True).first()
    if pipe is None:
        return
    # По возрастанию старого индекса: каждый шаг освобождает key, который
    # использует следующий шаг (UNIQUE(pipeline, key) иначе конфликтует).
    for old_key, new_key, new_label in RENAMES:
        st = RenewalStage.objects.filter(pipeline=pipe, key=old_key).first()
        if st is not None:
            st.key = new_key
            st.label = new_label
            st.save(update_fields=['key', 'label'])


def backward(apps, schema_editor):
    RenewalPipeline = apps.get_model('renewals', 'RenewalPipeline')
    RenewalStage = apps.get_model('renewals', 'RenewalStage')
    pipe = RenewalPipeline.objects.filter(is_default=True).first()
    if pipe is None:
        return
    # В обратном порядке (по убыванию нового индекса) — та же логика освобождения key.
    for old_key, new_key, _ in reversed(RENAMES):
        st = RenewalStage.objects.filter(pipeline=pipe, key=new_key).first()
        if st is not None:
            st.key = old_key
            st.label = OLD_LABELS[old_key]
            st.save(update_fields=['key', 'label'])


class Migration(migrations.Migration):
    dependencies = [('renewals', '0008_remove_renewaldeal_insert_insert_and_more')]
    operations = [migrations.RunPython(forward, backward)]
```

- [ ] **Step 2: Применить миграцию на dev-БД**

Run (из `journal_django/`): `python manage.py migrate renewals`
Expected: `Applying renewals.0009_rename_lesson_progress_stages... OK`

- [ ] **Step 3: Проверить руками через shell, что переименование прошло**

Run: `python manage.py shell -c "from apps.renewals.models import RenewalStage; print(list(RenewalStage.objects.filter(pipeline__is_default=True, kind='progress').order_by('sort_order').values_list('key','label')))"`
Expected: `[('no_lesson_yet', 'Не было урока'), ('lesson_1', 'Урок 1'), ('lesson_2', 'Урок 2'), ('lesson_3', 'Урок 3')]`

- [ ] **Step 4: Commit**

```bash
git add journal_django/apps/renewals/migrations/0009_rename_lesson_progress_stages.py
git commit -m "feat(renewals): rename lesson_1..4 stages, add no_lesson_yet"
```

---

### Task 2: Обновить `test_seed.py`

**Files:**
- Modify: `journal_django/apps/renewals/tests/test_seed.py:15,17`

- [ ] **Step 1: Запустить тесты, убедиться что они красные (ключ уже переименован миграцией)**

Run (из `journal_django/`): `pytest apps/renewals/tests/test_seed.py -v`
Expected: FAIL — `assert [s.key for s in stages][0] == 'lesson_1'` не проходит, т.к. первый key теперь `no_lesson_yet`.

- [ ] **Step 2: Поправить assert'ы**

В `test_default_pipeline_seeded` заменить:

```python
    # Первая по sort_order — «Урок 1» (миграция 0003 разбила lesson_progress на 4 стадии,
    # см. apps/renewals/tests/test_lesson_progress.py::test_default_pipeline_has_four_lesson_stages).
    assert [s.key for s in stages][0] == 'lesson_1'
    assert {s.kind for s in stages} >= {'progress', 'decision', 'won', 'lost'}
    assert next(s for s in stages if s.key == 'lesson_1').is_auto is True
```

на:

```python
    # Первая по sort_order — «Не было урока» (миграция 0003 разбила
    # lesson_progress на 4 стадии, 0009 переименовала первую из них — см.
    # apps/renewals/tests/test_lesson_progress.py::test_default_pipeline_has_four_lesson_stages).
    assert [s.key for s in stages][0] == 'no_lesson_yet'
    assert {s.kind for s in stages} >= {'progress', 'decision', 'won', 'lost'}
    assert next(s for s in stages if s.key == 'no_lesson_yet').is_auto is True
```

- [ ] **Step 3: Прогнать тест, убедиться что зелёный**

Run: `pytest apps/renewals/tests/test_seed.py -v`
Expected: PASS (2 passed)

- [ ] **Step 4: Commit**

```bash
git add journal_django/apps/renewals/tests/test_seed.py
git commit -m "test(renewals): update seed test for no_lesson_yet key"
```

---

### Task 3: Обновить `test_stages_api.py`

**Files:**
- Modify: `journal_django/apps/renewals/tests/test_stages_api.py:28-34`

- [ ] **Step 1: Прогнать тест, убедиться что красный**

Run: `pytest apps/renewals/tests/test_stages_api.py -v`
Expected: FAIL в `test_cannot_delete_protected_auto_stage` — `next(...)` кидает `StopIteration`, т.к. `key == 'lesson_1'` больше не первая авто-стадия.

- [ ] **Step 2: Поправить**

Заменить:

```python
@pytest.mark.django_db
def test_cannot_delete_protected_auto_stage(superadmin_client):
    """Авто-стадию «Урок N» (is_auto) удалить нельзя → 409."""
    stages = superadmin_client.get(BASE).json()
    auto = next(s for s in stages if s['key'] == 'lesson_1')
    resp = superadmin_client.delete(f"{BASE}/{auto['id']}")
    assert resp.status_code == 409
    assert resp.json()['error'] == 'protected'
```

на:

```python
@pytest.mark.django_db
def test_cannot_delete_protected_auto_stage(superadmin_client):
    """Авто-стадию «Не было урока»/«Урок N» (is_auto) удалить нельзя → 409."""
    stages = superadmin_client.get(BASE).json()
    auto = next(s for s in stages if s['key'] == 'no_lesson_yet')
    resp = superadmin_client.delete(f"{BASE}/{auto['id']}")
    assert resp.status_code == 409
    assert resp.json()['error'] == 'protected'
```

- [ ] **Step 3: Прогнать тесты файла, убедиться что зелёные**

Run: `pytest apps/renewals/tests/test_stages_api.py -v`
Expected: PASS (8 passed)

- [ ] **Step 4: Commit**

```bash
git add journal_django/apps/renewals/tests/test_stages_api.py
git commit -m "test(renewals): update stages API test for no_lesson_yet key"
```

---

### Task 4: Обновить `test_signals.py`

**Files:**
- Modify: `journal_django/apps/renewals/tests/test_signals.py:33,46,73`

- [ ] **Step 1: Прогнать тесты файла, убедиться что есть красные**

Run: `pytest apps/renewals/tests/test_signals.py -v`
Expected: `test_payment_orm_create_syncs_stage_without_closing` и `test_refund_does_not_touch_deal` FAIL (сравнение с устаревшими key).

- [ ] **Step 2: Поправить `test_payment_orm_create_syncs_stage_without_closing`**

Строка 33 (`deal.stage.key == 'awaiting_payment'`) не трогать — комментарий и ключ не меняются. Строка 46 заменить:

```python
            assert deal.stage.key == 'lesson_2'  # баланс положительный → «Урок 2»
```

на:

```python
            assert deal.stage.key == 'lesson_1'  # баланс положительный → «Урок 1» (1 урок отработан)
```

- [ ] **Step 3: Поправить `test_refund_does_not_touch_deal`**

Строка 73 заменить:

```python
        assert deal.stage.key == 'lesson_1'  # не сдвинулась
```

на:

```python
        assert deal.stage.key == 'no_lesson_yet'  # не сдвинулась
```

- [ ] **Step 4: Прогнать тесты файла, убедиться что зелёные**

Run: `pytest apps/renewals/tests/test_signals.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/renewals/tests/test_signals.py
git commit -m "test(renewals): update signals tests for renamed progress stages"
```

---

### Task 5: Обновить `test_lesson_progress.py`

**Files:**
- Modify: `journal_django/apps/renewals/tests/test_lesson_progress.py` (все упоминания `lesson_1..lesson_4`)

- [ ] **Step 1: Прогнать тесты файла, убедиться что есть красные**

Run: `pytest apps/renewals/tests/test_lesson_progress.py -v`
Expected: несколько FAIL (ключи/labels устарели).

- [ ] **Step 2: Поправить `test_default_pipeline_has_four_lesson_stages`**

Заменить (строки 41-47):

```python
@pytest.mark.django_db
def test_default_pipeline_has_four_lesson_stages():
    pipe = RenewalPipeline.objects.get(is_default=True)
    stages = list(RenewalStage.objects.filter(
        pipeline=pipe, kind='progress', is_auto=True).order_by('sort_order'))
    assert [s.key for s in stages] == ['lesson_1', 'lesson_2', 'lesson_3', 'lesson_4']
    assert [s.label for s in stages] == ['Урок 1', 'Урок 2', 'Урок 3', 'Урок 4']
    assert not RenewalStage.objects.filter(pipeline=pipe, key='lesson_progress').exists()
```

на:

```python
@pytest.mark.django_db
def test_default_pipeline_has_four_lesson_stages():
    pipe = RenewalPipeline.objects.get(is_default=True)
    stages = list(RenewalStage.objects.filter(
        pipeline=pipe, kind='progress', is_auto=True).order_by('sort_order'))
    assert [s.key for s in stages] == ['no_lesson_yet', 'lesson_1', 'lesson_2', 'lesson_3']
    assert [s.label for s in stages] == ['Не было урока', 'Урок 1', 'Урок 2', 'Урок 3']
    assert not RenewalStage.objects.filter(pipeline=pipe, key='lesson_progress').exists()
```

- [ ] **Step 3: Поправить `test_ensure_deal_starts_on_lesson_1`**

Заменить (строки 50-54):

```python
@pytest.mark.django_db
def test_ensure_deal_starts_on_lesson_1(make_student):
    sid = make_student()
    deal = engine.ensure_deal(sid, cycle_no=1)
    assert deal.stage.key == 'lesson_1'
```

на:

```python
@pytest.mark.django_db
def test_ensure_deal_starts_on_no_lesson_yet(make_student):
    sid = make_student()
    deal = engine.ensure_deal(sid, cycle_no=1)
    assert deal.stage.key == 'no_lesson_yet'
```

- [ ] **Step 4: Поправить `test_sync_lesson_stage_advances_with_attendance`**

Заменить (строки 57-78):

```python
@pytest.mark.django_db
def test_sync_lesson_stage_advances_with_attendance(make_student, make_direction,
                                                    make_teacher, make_payment,
                                                    make_attendance):
    sid, did, tid = make_student(), make_direction(), make_teacher()
    make_payment(sid, did, lessons=8)  # баланс > 0 — иначе уедет в «Ждём оплату»
    gid = _make_group_with_membership(did, tid, sid)
    try:
        deal = engine.ensure_deal(sid, cycle_no=1)
        assert deal.stage.key == 'lesson_1'

        make_attendance(sid, gid, tid, count=1)
        engine.sync_lesson_stage(sid)
        deal.refresh_from_db()
        assert deal.stage.key == 'lesson_2'

        make_attendance(sid, gid, tid, count=2, start='2026-06-10')
        engine.sync_lesson_stage(sid)
        deal.refresh_from_db()
        assert deal.stage.key == 'lesson_4'
    finally:
        _cleanup_group(gid, sid)
```

на:

```python
@pytest.mark.django_db
def test_sync_lesson_stage_advances_with_attendance(make_student, make_direction,
                                                    make_teacher, make_payment,
                                                    make_attendance):
    sid, did, tid = make_student(), make_direction(), make_teacher()
    make_payment(sid, did, lessons=8)  # баланс > 0 — иначе уедет в «Ждём оплату»
    gid = _make_group_with_membership(did, tid, sid)
    try:
        deal = engine.ensure_deal(sid, cycle_no=1)
        assert deal.stage.key == 'no_lesson_yet'

        make_attendance(sid, gid, tid, count=1)
        engine.sync_lesson_stage(sid)
        deal.refresh_from_db()
        assert deal.stage.key == 'lesson_1'

        make_attendance(sid, gid, tid, count=2, start='2026-06-10')
        engine.sync_lesson_stage(sid)
        deal.refresh_from_db()
        assert deal.stage.key == 'lesson_3'
    finally:
        _cleanup_group(gid, sid)
```

(3 урока суммарно из 4: `into=3` → `lesson_3` — последняя прогресс-стадия перед «Ждём продление», раньше называлась `lesson_4`.)

- [ ] **Step 5: Поправить `test_cycle_complete_moves_to_awaiting_renewal`**

Заменить (строка 118):

```python
        assert deal.stage.key != 'lesson_1'  # фикс зацикливания attended % 4
```

на:

```python
        assert deal.stage.key != 'no_lesson_yet'  # фикс зацикливания attended % 4
```

- [ ] **Step 6: Поправить `test_prepaid_cycle2_deal_stays_on_lesson_1`**

Заменить (строки 181-196):

```python
@pytest.mark.django_db
def test_prepaid_cycle2_deal_stays_on_lesson_1(make_student, make_direction,
                                               make_teacher, make_payment,
                                               make_attendance):
    """Сделка цикла 2 при attended=2 (ещё идёт цикл 1) стоит на «Урок 1»."""
    sid, did, tid = make_student(), make_direction(), make_teacher()
    make_payment(sid, did, lessons=8)
    gid = _make_group_with_membership(did, tid, sid)
    try:
        make_attendance(sid, gid, tid, count=2)
        engine.ensure_deal(sid, cycle_no=2)
        engine.sync_lesson_stage(sid)
        deal = RenewalDeal.objects.get(student_id=sid, cycle_no=2)
        assert deal.stage.key == 'lesson_1'
    finally:
        _cleanup_group(gid, sid)
```

на:

```python
@pytest.mark.django_db
def test_prepaid_cycle2_deal_stays_on_no_lesson_yet(make_student, make_direction,
                                                     make_teacher, make_payment,
                                                     make_attendance):
    """Сделка цикла 2 при attended=2 (ещё идёт цикл 1) стоит на «Не было урока»
    — это и есть П-7: предоплаченный цикл ещё не начался, а не «отработан 1 урок»."""
    sid, did, tid = make_student(), make_direction(), make_teacher()
    make_payment(sid, did, lessons=8)
    gid = _make_group_with_membership(did, tid, sid)
    try:
        make_attendance(sid, gid, tid, count=2)
        engine.ensure_deal(sid, cycle_no=2)
        engine.sync_lesson_stage(sid)
        deal = RenewalDeal.objects.get(student_id=sid, cycle_no=2)
        assert deal.stage.key == 'no_lesson_yet'
    finally:
        _cleanup_group(gid, sid)
```

- [ ] **Step 7: Прогнать все тесты файла, убедиться что зелёные**

Run: `pytest apps/renewals/tests/test_lesson_progress.py -v`
Expected: PASS (8 passed)

- [ ] **Step 8: Commit**

```bash
git add journal_django/apps/renewals/tests/test_lesson_progress.py
git commit -m "test(renewals): update lesson-progress tests for no_lesson_yet stage"
```

---

### Task 6: Обновить `apps/lessons/tests/test_renewals_stage_sync.py`

**Files:**
- Modify: `journal_django/apps/lessons/tests/test_renewals_stage_sync.py:49,62,89,94`

- [ ] **Step 1: Прогнать renewals-тесты и этот файл вместе (renewals — первым аргументом, см. footgun выше)**

Run (из `journal_django/`): `pytest apps/renewals apps/lessons/tests/test_renewals_stage_sync.py -v`
Expected: FAIL в `test_create_lesson_full_advances_renewal_stage` и `test_update_attendance_cell_advances_renewal_stage` (устаревшие key).

- [ ] **Step 2: Поправить `test_create_lesson_full_advances_renewal_stage`**

Строка 49 заменить:

```python
    assert deal.stage.key == 'lesson_1'
```

на:

```python
    assert deal.stage.key == 'no_lesson_yet'
```

Строка 62 заменить:

```python
        assert deal.stage.key == 'lesson_2'
```

на:

```python
        assert deal.stage.key == 'lesson_1'
```

- [ ] **Step 3: Поправить `test_update_attendance_cell_advances_renewal_stage`**

Строка 89 заменить:

```python
    assert deal.stage.key == 'lesson_1'  # не отмечен присутствующим — прогресса нет
```

на:

```python
    assert deal.stage.key == 'no_lesson_yet'  # не отмечен присутствующим — прогресса нет
```

Строка 94 заменить:

```python
        assert deal.stage.key == 'lesson_2'
```

на:

```python
        assert deal.stage.key == 'lesson_1'
```

- [ ] **Step 4: Прогнать снова, убедиться что зелёные**

Run: `pytest apps/renewals apps/lessons/tests/test_renewals_stage_sync.py -v`
Expected: PASS (все тесты обоих файлов)

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/lessons/tests/test_renewals_stage_sync.py
git commit -m "test(lessons): update renewal stage sync integration tests"
```

---

### Task 7: Полный прогон бэкенд-тестов

**Files:** нет изменений — только проверка.

- [ ] **Step 1: Полный pytest**

Run (из `journal_django/`): `pytest`
Expected: все тесты PASS, 0 failed (в частности `apps/renewals`, `apps/lessons`, `apps/changelog` — новая миграция не добавляет модель, changelog registry не трогаем).

- [ ] **Step 2: Если что-то красное — искать по тексту ошибки оставшиеся упоминания старых ключей**

Run: `grep -rn "lesson_2'\|lesson_3'\|lesson_4'" journal_django/apps --include=*.py`
Expected: пусто (все обновлено в Task 2-6). Если есть совпадения — поправить по аналогии с предыдущими шагами.

---

### Task 8: Doc-комментарий `lesson_in_cycle` в `repository.py`

**Files:**
- Modify: `journal_django/apps/renewals/repository.py:100-105`

- [ ] **Step 1: Поправить комментарий (вычисление не меняется)**

Заменить:

```python
    attended = float(data.pop('attended') or 0)
    # Прогресс от номера цикла сделки (не attended % 4): у сделки цикла N свои
    # уроки (N−1)×4+1 .. N×4, иначе после 4-го урока прогресс «заворачивался».
    into = attended - (data['cycle_no'] - 1) * cycle.LESSONS_PER_CYCLE
    data['lesson_in_cycle'] = min(max(int(into), 0), cycle.LESSONS_PER_CYCLE - 1) + 1  # 1..4
    data['cycle_completed'] = into >= cycle.LESSONS_PER_CYCLE
```

на:

```python
    attended = float(data.pop('attended') or 0)
    # Прогресс от номера цикла сделки (не attended % 4): у сделки цикла N свои
    # уроки (N−1)×4+1 .. N×4, иначе после 4-го урока прогресс «заворачивался».
    into = attended - (data['cycle_no'] - 1) * cycle.LESSONS_PER_CYCLE
    # 1..4, где 1 = «Не было урока цикла» (into<=0), 2..4 = «Урок 1..3» отработаны
    # (into=1..3). Текст на фронте (RenewalDrawer) разворачивает это в -1 при выводе.
    data['lesson_in_cycle'] = min(max(int(into), 0), cycle.LESSONS_PER_CYCLE - 1) + 1
    data['cycle_completed'] = into >= cycle.LESSONS_PER_CYCLE
```

- [ ] **Step 2: Прогнать тесты сериализатора/API, убедиться что не сломалось (значение поля не менялось)**

Run: `pytest apps/renewals/tests/test_serializers.py apps/renewals/tests/test_api_read.py -v`
Expected: PASS (без изменений — значение `lesson_in_cycle` не менялось, только комментарий)

- [ ] **Step 3: Commit**

```bash
git add journal_django/apps/renewals/repository.py
git commit -m "docs(renewals): clarify lesson_in_cycle comment after stage rename"
```

---

### Task 9: Фронтенд — `lib/labels.ts`

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/labels.ts:123-127`

- [ ] **Step 1: Обновить `RENEWAL_STAGE_LABELS`**

Заменить:

```typescript
export const RENEWAL_STAGE_LABELS: Record<string, string> = {
  lesson_1: 'Урок 1', lesson_2: 'Урок 2', lesson_3: 'Урок 3', lesson_4: 'Урок 4',
  awaiting_payment: 'Ждём оплату', awaiting_renewal: 'Ждём продление', thinking: 'Думает',
  frozen: 'Заморожен', ignoring: 'Игнорит', renewed: 'Продлён', churned: 'Ушёл',
};
```

на:

```typescript
export const RENEWAL_STAGE_LABELS: Record<string, string> = {
  no_lesson_yet: 'Не было урока', lesson_1: 'Урок 1', lesson_2: 'Урок 2', lesson_3: 'Урок 3',
  awaiting_payment: 'Ждём оплату', awaiting_renewal: 'Ждём продление', thinking: 'Думает',
  frozen: 'Заморожен', ignoring: 'Игнорит', renewed: 'Продлён', churned: 'Ушёл',
};
```

- [ ] **Step 2: Commit**

```bash
git add journal_django/frontend/admin-src/src/lib/labels.ts
git commit -m "feat(admin): rename lesson_1..4 fallback labels for renewals"
```

---

### Task 10: Фронтенд — `RenewalDrawer.tsx`

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/renewals/RenewalDrawer.tsx:175-190`

- [ ] **Step 1: Поправить текст прогресса**

Заменить:

```tsx
            <div className="renewal-drawer__section renewal-drawer__progress">
              {!isClosed && (
                deal.cycle_completed
                  ? (
                    <span className="status-badge status-badge--info">
                      Цикл отработан{deal.due_at ? ` ${fmtDate(deal.due_at)}` : ''} — пора продлевать
                    </span>
                  )
                  : <span>Урок {deal.lesson_in_cycle} из 4</span>
              )}
```

на:

```tsx
            <div className="renewal-drawer__section renewal-drawer__progress">
              {!isClosed && (
                deal.cycle_completed
                  ? (
                    <span className="status-badge status-badge--info">
                      Цикл отработан{deal.due_at ? ` ${fmtDate(deal.due_at)}` : ''} — пора продлевать
                    </span>
                  )
                  : deal.lesson_in_cycle === 1
                    ? <span>Не было уроков цикла</span>
                    : <span>Отработано {deal.lesson_in_cycle - 1} из 4</span>
              )}
```

- [ ] **Step 2: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/renewals/RenewalDrawer.tsx
git commit -m "feat(admin): show 'Не было уроков цикла' for zero-progress deals"
```

---

### Task 11: Фронтенд — `RenewalCloseDialog.tsx`

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/renewals/RenewalCloseDialog.tsx:29-34,113-117`

- [ ] **Step 1: Поправить комментарий у компонента**

Заменить:

```tsx
/**
 * Диалог закрытия сделки продления. «Ушёл» требует причину. «Продлён» —
 * всегда окончательное ручное решение менеджера: оплата сама по себе сделку
 * не закрывает (только двигает по стадиям Урок 1–4 / Ждём продление), поэтому
 * тут одна кнопка подтверждения плюс необязательный ярлык на форму оплаты.
 */
```

на:

```tsx
/**
 * Диалог закрытия сделки продления. «Ушёл» требует причину. «Продлён» —
 * всегда окончательное ручное решение менеджера: оплата сама по себе сделку
 * не закрывает (только двигает по стадиям Не было урока/Урок 1–3 / Ждём
 * продление), поэтому тут одна кнопка подтверждения плюс необязательный
 * ярлык на форму оплаты.
 */
```

- [ ] **Step 2: Поправить текст в диалоге**

Заменить:

```tsx
          <p className="renewal-close-dialog__text">
            Оплата сама по себе сделку не закрывает — она только двигает
            стадию (Урок 1–4 / Ждём продление) вместе с балансом. Продление
            подтверждает менеджер отдельным явным действием.
          </p>
```

на:

```tsx
          <p className="renewal-close-dialog__text">
            Оплата сама по себе сделку не закрывает — она только двигает
            стадию (Не было урока / Урок 1–3 / Ждём продление) вместе с
            балансом. Продление подтверждает менеджер отдельным явным действием.
          </p>
```

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/renewals/RenewalCloseDialog.tsx
git commit -m "docs(admin): update renewal close dialog copy for renamed stages"
```

---

### Task 12: Фронтенд — typecheck и сборка

**Files:** нет изменений — только проверка.

- [ ] **Step 1: Typecheck**

Run (из `journal_django/frontend/admin-src/`): `npm run typecheck` (или `tsc --noEmit`, смотреть `package.json` за точным скриптом)
Expected: без ошибок.

- [ ] **Step 2: Сборка**

Run: `npm run build`
Expected: сборка проходит, новые файлы появляются в `journal_django/frontend/admin-dist/assets/`.

- [ ] **Step 3: Смоук в браузере**

Открыть раздел «Продления» на dev-сервере, открыть карточку сделки, у которой 0 уроков в текущем цикле (либо создать тестовую) — убедиться, что колонка доски называется «Не было урока», а в drawer — «Не было уроков цикла» вместо «Урок 1 из 4».

- [ ] **Step 4: Commit (если сборка попадает в git, как остальной `admin-dist`)**

```bash
git add journal_django/frontend/admin-dist/
git commit -m "chore(admin): rebuild frontend after renewal stage rename"
```

---

### Task 13: Документация — `docs/renewals-tech-spec.md`

**Files:**
- Modify: `docs/renewals-tech-spec.md` (§2 таблица стадий сида, §10 список ограничений)

- [ ] **Step 1: Обновить строку сида стадий в §2**

Заменить:

```markdown
Стадии сида (0002 → 0003 → 0005): `lesson_1..lesson_4` (progress, auto) →
`awaiting_payment` (decision, auto) → `awaiting_renewal` (decision, auto) →
`thinking`, `frozen`, `ignoring` (decision, ручные) → `renewed` (won) →
`churned` (lost). Авто-принадлежность = флаг `is_auto`, НЕ `kind`.
```

на:

```markdown
Стадии сида (0002 → 0003 → 0005 → 0009): `no_lesson_yet, lesson_1..lesson_3`
(progress, auto; 0009 переименовала `lesson_1..4` — П-7) →
`awaiting_payment` (decision, auto) → `awaiting_renewal` (decision, auto) →
`thinking`, `frozen`, `ignoring` (decision, ручные) → `renewed` (won) →
`churned` (lost). Авто-принадлежность = флаг `is_auto`, НЕ `kind`.
```

- [ ] **Step 2: Перенести П-7 из «🟢 Мелкие» в «✅ Закрыто 2026-07-13»**

Переименовать заголовок секции (добавить дату) и убрать П-7 из списка мелких:

Заменить:

```markdown
### ✅ Закрыто 2026-07-13
```

на:

```markdown
### ✅ Закрыто
```

Заменить (в конце блока «✅ Закрыто», после П-13):

```markdown
**Поле `expected_amount` («Ожидаемая сумма») удалено полностью** — по решению
пользователя признано бесполезным (никто не заполнял, значимой аналитики не
несло). Убрано из модели (миграция 0008), API (`PATCH`, `board`, `analytics`),
доски (карточка, шапка колонки — `sum_potential` тоже удалён), drawer'а и
аналитической воронки (тултип `sum_amt`). Прогноз выручки при желании стоит
считать иначе — например, от направления/тарифа ученика, а не ручным полем.
```

на:

```markdown
**Поле `expected_amount` («Ожидаемая сумма») удалено полностью** — по решению
пользователя признано бесполезным (никто не заполнял, значимой аналитики не
несло). Убрано из модели (миграция 0008), API (`PATCH`, `board`, `analytics`),
доски (карточка, шапка колонки — `sum_potential` тоже удалён), drawer'а и
аналитической воронки (тултип `sum_amt`). Прогноз выручки при желании стоит
считать иначе — например, от направления/тарифа ученика, а не ручным полем.

**П-7 (было: предоплаченный цикл показывает «Урок 1»).** Закрыто 2026-07-15
(миграция 0009): первая прогресс-стадия переименована в «Не было урока» —
она честно описывает состояние `into ≤ 0` (0 уроков этого цикла, включая
предоплаченный следующий цикл, пока предыдущий не отработан). `lesson_2/3/4`
сдвинуты на `lesson_1/2/3`; `lesson_4` не сохранился — `into=4` перехватывается
раньше правилом «Ждём продление», эта стадия физически не занимает сделку.
Код движка не менялся — адресация позиционная (`sort_order`).
```

- [ ] **Step 3: Удалить П-7 из секции «🟢 Мелкие»**

Заменить:

```markdown
**П-6а. Дрейф стадий без самозаживления.** После удаления rebuild стадии
выравниваются только по событиям (посещаемость/оплаты/ручное создание). Если
данные меняли в обход этих точек (прямой SQL, откат из журнала изменений) —
стадия сделки догонит реальность при следующем событии по ученику, не раньше.

**П-7. Предоплаченный цикл показывает «Урок 1».**
Для сделки цикла N при `attended < (N−1)×4` прогресс отрицательный и клампится
в «Урок 1 из 4» — хотя фактически ученик дорабатывает предыдущий оплаченный
месяц. Косметика, денег не касается.

**П-8. Аномалия данных: 5 посещений уроков с будущими датами** (dev-БД) —
```

на:

```markdown
**П-6а. Дрейф стадий без самозаживления.** После удаления rebuild стадии
выравниваются только по событиям (посещаемость/оплаты/ручное создание). Если
данные меняли в обход этих точек (прямой SQL, откат из журнала изменений) —
стадия сделки догонит реальность при следующем событии по ученику, не раньше.

**П-8. Аномалия данных: 5 посещений уроков с будущими датами** (dev-БД) —
```

- [ ] **Step 4: Commit**

```bash
git add docs/renewals-tech-spec.md
git commit -m "docs(renewals): close P-7 (no_lesson_yet stage rename)"
```

---

### Task 14: Документация — `docs/renewals-user-guide.md`

**Files:**
- Modify: `docs/renewals-user-guide.md` (строки ~34, 67, 69, 131, 182, 190 — см. точный контент ниже)

- [ ] **Step 1: Обновить таблицу авто-стадий**

Заменить:

```markdown
| **Урок 1 … Урок 4** | По ходу цикла: сколько уроков текущего абонемента уже отработано |
```

на:

```markdown
| **Не было урока / Урок 1 … Урок 3** | По ходу цикла: сколько уроков текущего абонемента уже отработано (0 — цикл ещё не начался) |
```

- [ ] **Step 2: Обновить строку про пересчёт по посещаемости**

Заменить:

```markdown
| Преподаватель отметил посещаемость | Пересчитывает стадию сделки: двигает по «Урок 1–4», при 4-м уроке цикла — в «Ждём продление», при нулевом балансе — в «Ждём оплату» |
```

на:

```markdown
| Преподаватель отметил посещаемость | Пересчитывает стадию сделки: двигает по «Не было урока / Урок 1–3», при 4-м уроке цикла — в «Ждём продление», при нулевом балансе — в «Ждём оплату» |
```

- [ ] **Step 3: Обновить строку про оплату**

Заменить:

```markdown
| **Внесена оплата** (любая покупка) | Баланс вырос — сделка **пересчитывает стадию** точно так же, как от посещаемости: может сдвинуться по «Урок 1–4» или выйти из «Ждём оплату». **Сделку это не закрывает и не продлевает** |
```

на:

```markdown
| **Внесена оплата** (любая покупка) | Баланс вырос — сделка **пересчитывает стадию** точно так же, как от посещаемости: может сдвинуться по «Не было урока / Урок 1–3» или выйти из «Ждём оплату». **Сделку это не закрывает и не продлевает** |
```

- [ ] **Step 4: Обновить строку прогресса в drawer**

Заменить:

```markdown
- прогресс «Урок X из 4» или плашка «Цикл отработан — пора продлевать»;
```

на:

```markdown
- прогресс «Не было уроков цикла» / «Отработано X из 4» или плашка «Цикл отработан — пора продлевать»;
```

- [ ] **Step 5: Обновить раздел «Настройка стадий»**

Заменить:

```markdown
Кнопка «Настройка стадий»: можно добавлять свои ручные стадии (название, цвет,
вид), переименовывать, менять порядок. Нельзя удалить: автоматические стадии
(Урок 1–4, Ждём оплату, Ждём продление), единственную стадию закрытия и любую
стадию, в которой есть сделки.
```

на:

```markdown
Кнопка «Настройка стадий»: можно добавлять свои ручные стадии (название, цвет,
вид), переименовывать, менять порядок. Нельзя удалить: автоматические стадии
(Не было урока, Урок 1–3, Ждём оплату, Ждём продление), единственную стадию
закрытия и любую стадию, в которой есть сделки.
```

- [ ] **Step 6: Обновить FAQ про оплату**

Заменить:

```markdown
**Ученик оплатил, но сделка не закрылась сама — это баг?** Нет, так и задумано:
оплата только двигает стадию по балансу (может сдвинуть по «Урок 1–4» или
вывести из «Ждём оплату»), закрыть сделку как «Продлён» нужно отдельно —
```

на:

```markdown
**Ученик оплатил, но сделка не закрылась сама — это баг?** Нет, так и задумано:
оплата только двигает стадию по балансу (может сдвинуть по «Не было урока /
Урок 1–3» или вывести из «Ждём оплату»), закрыть сделку как «Продлён» нужно отдельно —
```

- [ ] **Step 7: Commit**

```bash
git add docs/renewals-user-guide.md
git commit -m "docs(renewals): update user guide for no_lesson_yet stage"
```

---

### Task 15: Финальная проверка

**Files:** нет изменений — только проверка.

- [ ] **Step 1: Полный backend-прогон**

Run (из `journal_django/`): `pytest`
Expected: все PASS.

- [ ] **Step 2: Финальный grep на мёртвые упоминания**

Run: `grep -rn "'lesson_1'\|'lesson_2'\|'lesson_3'\|'lesson_4'\|Урок 4" journal_django/apps journal_django/frontend/admin-src docs --include=*.py --include=*.ts --include=*.tsx --include=*.md`
Expected: только законные упоминания `lesson_1`/`lesson_2`/`lesson_3` (новые ключи/labels после рефакторинга) — никаких `lesson_4` или голого «Урок 4» не осталось.

- [ ] **Step 3: Обновить память проекта (для будущих сессий)**

Отметить в памяти `project_renewals_rework.md` (или новой записью), что П-7 закрыт 2026-07-15 переименованием стадии в `no_lesson_yet` — на случай, если следующая сессия будет читать старую версию tech-spec из памяти.
