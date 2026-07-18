# Унификация пропусков — Фаза 1c-2 («Сжечь» через запись-урок) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> ⚠️ **ДЕНЬГИ-КРИТИЧНО (новый payroll + новое потребление).** «Сжечь» создаёт реальный `burned`-Lesson (present=true, payroll 200₽) и списывает урок с баланса. Фаза завершается **сверкой lifecycle «сжечь → откат»** (balance/attended/renewals/payroll возвращаются точно) и **STOP-докладом пользователю** перед 1c-3.

**Goal:** Реализовать «Сжечь» (`pending → burned`) как симметрию доп.урока: создаётся отдельный `Lesson(lesson_type='burned')` present=true в дату сегодня с длительностью ИСХОДНОГО урока (вес потребления), флет-payroll 200₽ преподавателю пропущенного урока, penalty=0; откат (`burned → pending`) полностью реверсирует. Строится на новой модели потребления 1c-1 (present=true считается штатно по всем подтипам, `.exclude(extra)` уже снят).

**Architecture:** Эволюция на месте поверх 1c-1. Новый статус `burned` в `AbsenceResolution` (миграция 0009 = swap CHECK-констрейнта, как 0006). Сервис `burn()` — близнец `record()` (транзакция + row-lock + `insert_lesson`/`insert_attendance`/`insert_payroll`/`increment_lessons_done`/`sync_renewal_stage` on_commit). Откат — обобщённый `delete_fact()` (принимает `makeup_done` ИЛИ `burned`, тело идентично). Старый burn-WIP (`update_attendance_cell`/`burned_at`/`burn_surcharge`) НЕ трогается (удаление данных — Фаза 2); новый «Сжечь» идёт мимо него.

**Tech Stack:** Django 5 + DRF, pytest + pytest-django (реальная `journal_test`). Команды из `journal_django/`, интерпретатор `.venv/Scripts/python.exe`. Миграции — к ОБЕИМ БД (`journal` + `journal_test`); НЕ запускать `recreate_test_db.sh`.

---

## Ключевые решения 1c-2 (фикс, без двусмысленности)

1. **Получатель payroll за сгорание:** `missed_lesson.teacher_id` — преподаватель, проводивший пропущенный урок (владелец его Payroll; «исходный преподаватель группы» из спеки). **Fallback:** если этот преподаватель уволен (`Teacher.active=False`), надбавка уходит ТЕКУЩЕМУ преподавателю группы (`Group.teacher_id`) — нельзя платить уволенному (решение пользователя 2026-07-18). Флет 200₽ = `calculate_extra_lesson_payment(1)`, penalty=0 (`submit_date == lesson_date`, админское действие).
2. **Кто может «Сжечь»:** admin-раздел `/api/admin/extra-lessons/:id/burn` с `permission_classes=[IsManagerOrAdmin]` (симметрично cancel/list — «Сжечь» из раздела «Доп.уроки», не teacher-действие).
3. **Дата/вес/потребление:** burned-Lesson `lesson_date = сегодня (msk_today)`; `lesson_duration_minutes = missed_lesson.lesson_duration_minutes` (вес списания = вес пропуска, half-lesson 45→0.5); present=true → потребляется в свой месяц штатно (после 1c-1 `.exclude(extra)` снят, burned НЕ исключается нигде).
4. **`submitted_by_token = f'burn:{resolution_id}'`** — гарантирует уникальность `lessons_natural_key` (`lesson_date, group, lesson_number, submitted_by_token`): два студента, пропустившие ОДИН урок, сожжённые в ОДИН день, иначе схлопнулись бы по natural key → IntegrityError. Одна резолюция = один burned-факт, resolution_id уникален.
5. **Баланс-гард:** `assert_students_paid([student_id])` перед сжиганием — нельзя сжечь урок ученику без оплаченного остатка (нечего сжигать; 400 `UnpaidAttendanceBlocked`).
6. **Откат = обобщённый `delete_fact`:** статус-гейт расширяется до `status in (makeup_done, burned)`. Тело уже корректно для обоих (fact несёт длительность исходного → `_step` верен; удаление Lesson+Payroll+attendance снимает потребление; `back_to_pending`; `sync_renewal_stage`). Один DELETE-эндпоинт `/api/admin/extra-lessons/:id` = «Откат доп.урока» И «Откат сгорания».
7. **Расширить delete-lesson guard:** `apps/lessons/services.py::_assert_no_makeup_done_resolutions` должен блокировать удаление обычного урока и при `burned`-детях (иначе DB-CASCADE осиротит burned-факт+payroll) → фильтр `status__in=[MAKEUP_DONE, BURNED]`.
8. **Сверка:** lifecycle-тест «сжечь pending → откат»: balance −1→восстановлен, `attended_units_total`/`renewals._attended_total` +1→0, payroll 200 в месяц сжигания→удалён; исходный пропуск present=false ВСЁ ВРЕМЯ. STOP — доложить пользователю.

### Что НЕ входит в 1c-2 (→ 1c-3 / Фаза 2)

- Фронт (кнопка «Сжечь»/«Откат сгорания» в разделе, блок карточек в `LessonEditor`, статус-лейбл `burned`, teacher-календарь) — **Фаза 1c-3**.
- Физ. удаление `burned_at`/`burn_surcharge`/`update_attendance_cell`-burn-путь + миграция исторических `burned_at` в `burned`-Lesson — **Фаза 2**. В 1c-2 старый burn-WIP не трогаем: новый «Сжечь» просто идёт мимо него.

---

## Структура файлов (1c-2)

- `apps/extra_lessons/models.py` — `BURNED='burned'`, добавить в `STATUS_CHOICES`.
- `apps/extra_lessons/migrations/0009_add_burned_status.py` (new) — swap CHECK-констрейнта (remove old → add с `burned`), паттерн 0006.
- `apps/extra_lessons/repository.py` — `mark_burned(resolution_id, *, fact_lesson_id)`; расширить `has_active_resolution` (BURNED тоже активна — нельзя назначить доп.урок на сожжённый).
- `apps/extra_lessons/services.py` — `burn(resolution_id, *, request, burn_date)`; обобщить `delete_fact` до `makeup_done|burned`.
- `apps/extra_lessons/exceptions.py` — (переиспользуем существующие; новых нет).
- `apps/extra_lessons/views.py` — `ExtraLessonBurnView` (POST `/:id/burn`, IsManagerOrAdmin).
- `apps/extra_lessons/urls.py` — маршрут `/:id/burn`.
- `apps/lessons/services.py` — `_assert_no_makeup_done_resolutions` → фильтр `[MAKEUP_DONE, BURNED]`.
- `apps/changelog/labels.py` — правило `POST /api/admin/extra-lessons/\d+/burn → extra_lesson.burn`.
- Тесты: `apps/extra_lessons/tests/test_burn_services.py` (new), дополнить `test_extra_lessons_views.py`, `apps/lessons/tests/test_record_lesson_autocreate.py` (burned-guard), `apps/extra_lessons/tests/test_burn_reconciliation_1c2.py` (new lifecycle-сверка).

---

## Task 1: Статус `burned` в модели + миграция CHECK

**Files:**
- Modify: `apps/extra_lessons/models.py:18-21`
- Create: `apps/extra_lessons/migrations/0009_add_burned_status.py`
- Test: `apps/extra_lessons/tests/test_burn_services.py` (new, статус-константа)

- [ ] **Step 1: Добавить константу и включить в choices.**

В `apps/extra_lessons/models.py`:

```python
PENDING = 'pending'
MAKEUP_SCHEDULED = 'makeup_scheduled'
MAKEUP_DONE = 'makeup_done'
BURNED = 'burned'
STATUS_CHOICES = [PENDING, MAKEUP_SCHEDULED, MAKEUP_DONE, BURNED]
```

- [ ] **Step 2: Написать миграцию 0009** (swap CHECK-констрейнта — snapshot нового набора; паттерн 0006, но БЕЗ RunPython/uniq-правок — меняется только CHECK).

`apps/extra_lessons/migrations/0009_add_burned_status.py`:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('extra_lessons', '0008_revert_historical_makeups'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='absenceresolution',
            name='absence_resolutions_status_check',
        ),
        migrations.AddConstraint(
            model_name='absenceresolution',
            constraint=models.CheckConstraint(
                condition=models.Q(('status__in', ['pending', 'makeup_scheduled', 'makeup_done', 'burned'])),
                name='absence_resolutions_status_check',
            ),
        ),
    ]
```

- [ ] **Step 3: Применить к ОБЕИМ БД и проверить, что автодетектор чист.**

```bash
cd /c/Users/ilyap/TestKOTOKOD/journal_django
.venv/Scripts/python.exe manage.py migrate extra_lessons
DJANGO_SETTINGS_MODULE=config.settings.test .venv/Scripts/python.exe manage.py migrate extra_lessons
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
```
Expected: миграция применяется; последняя строка `No changes detected`.

- [ ] **Step 4: Тест — константа и CHECK пропускают `burned`.**

`apps/extra_lessons/tests/test_burn_services.py`:

```python
import pytest
from apps.extra_lessons.models import BURNED, STATUS_CHOICES


def test_burned_status_registered():
    assert BURNED == 'burned'
    assert BURNED in STATUS_CHOICES
```

Run: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/tests/test_burn_services.py::test_burned_status_registered -q`
Expected: PASS.

- [ ] **Step 5: Commit** (контроллер, после независимого прогона):

```bash
git add apps/extra_lessons/models.py apps/extra_lessons/migrations/0009_add_burned_status.py apps/extra_lessons/tests/test_burn_services.py
git commit -m "feat(absences): add burned status + CHECK migration (Phase 1c-2 Task 1)"
```

---

## Task 2: Repository — `mark_burned` + `has_active_resolution` учитывает burned

**Files:**
- Modify: `apps/extra_lessons/repository.py`
- Test: `apps/extra_lessons/tests/test_burn_services.py`

- [ ] **Step 1: Написать failing-тесты репозитория.**

Добавить в `test_burn_services.py` (использует существующие фикстуры `missed_lesson_fixture`/`student_fixture` — свериться с `conftest.py`, ниже — форма; при расхождении имён параметров подогнать под реальные фикстуры, НЕ выдумывать):

```python
from apps.extra_lessons import repository
from apps.extra_lessons.models import AbsenceResolution, BURNED, PENDING


@pytest.mark.django_db
def test_mark_burned_sets_status_and_fact(absence_pending):
    # absence_pending: фикстура pending-резолюции (см. Task 2 Step 2)
    repository.mark_burned(absence_pending.id, fact_lesson_id=absence_pending.missed_lesson_id)
    absence_pending.refresh_from_db()
    assert absence_pending.status == BURNED
    assert absence_pending.fact_lesson_id == absence_pending.missed_lesson_id


@pytest.mark.django_db
def test_has_active_resolution_true_for_burned(absence_pending):
    repository.mark_burned(absence_pending.id, fact_lesson_id=absence_pending.missed_lesson_id)
    assert repository.has_active_resolution(
        absence_pending.missed_lesson_id, absence_pending.student_id) is True
```

- [ ] **Step 2: Добавить фикстуру `absence_pending`** в `test_burn_services.py` (или переиспользовать существующую из `conftest.py`, если есть — проверить `apps/extra_lessons/tests/conftest.py`). Форма:

```python
@pytest.fixture
def absence_pending(missed_lesson_fixture, student_fixture):
    """pending-резолюция на реально отсутствовавшего ученика.
    ВНИМАНИЕ (готча): missed_lesson_fixture, записанный через create_lesson_full,
    УЖЕ авто-создаёт pending. Берём существующую, а не создаём вторую (UNIQUE)."""
    return AbsenceResolution.objects.get(
        missed_lesson_id=missed_lesson_fixture.id, student_id=student_fixture.id,
        status=PENDING)
```

(Если фикстуры `missed_lesson_fixture`/`student_fixture` в conftest дают другую форму — адаптировать. Ключевой инвариант: получить существующую pending-строку, НЕ создавать дубль.)

- [ ] **Step 3: Run — verify FAIL** (`mark_burned` не существует, `has_active_resolution` не знает burned).

Run: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/tests/test_burn_services.py -q`
Expected: FAIL (`AttributeError: mark_burned` / has_active False).

- [ ] **Step 4: Реализовать в `apps/extra_lessons/repository.py`.**

Импорт: добавить `BURNED` в import из `apps.extra_lessons.models`.

```python
def mark_burned(resolution_id, *, fact_lesson_id) -> None:
    AbsenceResolution.objects.filter(id=resolution_id).update(
        status=BURNED, fact_lesson_id=fact_lesson_id)
```

Расширить `has_active_resolution` (сожжённый пропуск закрыт — доп.урок на него назначать нельзя):

```python
def has_active_resolution(missed_lesson_id, student_id) -> bool:
    """Уже назначено/проведено/сожжено? (pending НЕ считается). Guard от
    повторного назначения/сжигания уже разрешённого пропуска."""
    return (AbsenceResolution.objects
            .filter(missed_lesson_id=missed_lesson_id, student_id=student_id,
                    status__in=[MAKEUP_SCHEDULED, MAKEUP_DONE, BURNED]).exists())
```

- [ ] **Step 5: Run — verify PASS.**

Run: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/tests/test_burn_services.py -q`
Expected: PASS.

- [ ] **Step 6: Commit:**

```bash
git add apps/extra_lessons/repository.py apps/extra_lessons/tests/test_burn_services.py
git commit -m "feat(absences): mark_burned + has_active covers burned (Phase 1c-2 Task 2)"
```

---

## Task 3: Сервис `burn()` — создать burned-факт из pending

**Files:**
- Modify: `apps/extra_lessons/services.py`
- Test: `apps/extra_lessons/tests/test_burn_services.py`

- [ ] **Step 1: Написать failing-тесты сервиса `burn`.**

```python
from decimal import Decimal

from apps.extra_lessons import services
from apps.extra_lessons.models import AbsenceResolution, BURNED, PENDING
from apps.lessons.models import Lesson, LessonAttendance
from apps.payroll.models import Payroll


@pytest.mark.django_db
def test_burn_creates_burned_fact(absence_pending, rf_admin):
    # rf_admin: request с админ-actor (см. существующие view-тесты для формы request)
    res = services.burn(absence_pending.id, request=rf_admin, burn_date='2026-07-18')
    absence_pending.refresh_from_db()
    assert absence_pending.status == BURNED
    fact = Lesson.objects.get(id=absence_pending.fact_lesson_id)
    assert fact.lesson_type == 'burned'
    assert fact.lesson_date.isoformat() == '2026-07-18'
    # вес = длительность ИСХОДНОГО урока
    missed = Lesson.objects.get(id=absence_pending.missed_lesson_id)
    assert fact.lesson_duration_minutes == missed.lesson_duration_minutes
    assert fact.teacher_id == missed.teacher_id
    # present=true на burned-факте, исходный пропуск ОСТАЁТСЯ present=false
    assert LessonAttendance.objects.get(
        lesson_id=fact.id, student_id=absence_pending.student_id).present is True
    assert LessonAttendance.objects.get(
        lesson_id=missed.id, student_id=absence_pending.student_id).present is False
    # payroll флет 200, penalty 0
    pr = Payroll.objects.get(lesson_id=fact.id)
    assert pr.payment == 200 and pr.penalty == 0 and pr.teacher_id == missed.teacher_id
    assert res['payment'] == 200


@pytest.mark.django_db
def test_burn_requires_pending(absence_pending, rf_admin):
    services.burn(absence_pending.id, request=rf_admin, burn_date='2026-07-18')
    with pytest.raises(ValueError):
        services.burn(absence_pending.id, request=rf_admin, burn_date='2026-07-18')


@pytest.mark.django_db
def test_burn_missing_returns_none(rf_admin):
    assert services.burn(999999, request=rf_admin, burn_date='2026-07-18') is None


@pytest.mark.django_db
def test_burn_pays_current_group_teacher_when_missed_teacher_fired(absence_pending, rf_admin):
    """Уволенному преподавателю пропущенного урока платить нельзя — надбавка
    уходит текущему преподавателю группы (Group.teacher_id)."""
    from apps.teachers.models import Teacher
    from apps.groups.models import Group
    missed = Lesson.objects.get(id=absence_pending.missed_lesson_id)
    # Уволить преподавателя пропущенного урока; текущий преп. группы — другой.
    Teacher.objects.filter(id=missed.teacher_id).update(active=False)
    current_teacher_id = Group.objects.get(id=missed.group_id).teacher_id

    services.burn(absence_pending.id, request=rf_admin, burn_date='2026-07-18')
    absence_pending.refresh_from_db()
    pr = Payroll.objects.get(lesson_id=absence_pending.fact_lesson_id)
    # Если фикстура даёт group.teacher == missed.teacher, тест выродится —
    # тогда переустановить Group.teacher_id на отдельного активного преподавателя
    # перед burn (создать/взять второго teacher-фикстурой), см. conftest.
    assert pr.teacher_id == current_teacher_id
```

(`rf_admin` — переиспользовать паттерн request-фикстуры из существующих extra_lessons view/service-тестов; если там `request` конструируется через `APIRequestFactory`+`force_authenticate` — повторить. НЕ выдумывать несуществующий helper.)

- [ ] **Step 2: Run — verify FAIL** (`services.burn` не существует).

Run: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/tests/test_burn_services.py -q`
Expected: FAIL (`AttributeError: burn`).

- [ ] **Step 3: Реализовать `burn()` в `apps/extra_lessons/services.py`.**

Импорты: добавить `BURNED` в import из `apps.extra_lessons.models`; `from apps.teachers.models import Teacher`.

Хелпер выбора получателя надбавки (уволенному не платим — уходит текущему преподавателю группы):

```python
def _burn_payment_teacher_id(missed_lesson) -> int:
    """Флет-надбавку за сгорание получает преподаватель пропущенного урока.
    Если он уволен (Teacher.active=False) — надбавка уходит ТЕКУЩЕМУ
    преподавателю группы (Group.teacher_id). Если и тот не найден — остаётся
    исходный (не допускаем NULL teacher_id в Payroll)."""
    row = Teacher.objects.filter(id=missed_lesson.teacher_id).values_list('active', flat=True).first()
    if row:  # active=True
        return missed_lesson.teacher_id
    current = Group.objects.filter(
        id=missed_lesson.group_id).values_list('teacher_id', flat=True).first()
    return current or missed_lesson.teacher_id
```

```python
def burn(resolution_id: int, *, request, burn_date: str) -> Optional[dict]:
    """
    «Сжечь» пропуск: pending → burned. Создаёт Lesson(lesson_type='burned')
    present=true для ученика, дата=burn_date (сегодня), длительность=ИСХОДНОГО
    урока (вес потребления), teacher=преподаватель пропущенного урока, флет
    payment=200 (calculate_extra_lesson_payment), penalty=0 (админское действие,
    submit_date==lesson_date). Списывает урок с баланса штатно (present=true на
    burned-факте); исходный пропуск остаётся present=false.

    None → резолюции нет (view → 404). ValueError → не pending (view → 409).
    UnpaidAttendanceBlocked → balance<=0 (view → 400): нечего сжигать.
    """
    full = repository.get_resolution_full(resolution_id)
    if full is None:
        return None
    if full['status'] != PENDING:
        raise ValueError('Сжечь можно только нерешённый (pending) пропуск.')

    # Нельзя сжечь урок ученику без оплаченного остатка (нечего сжигать).
    lessons_repository.assert_students_paid([full['student_id']])

    payment = calculate_extra_lesson_payment(1)
    penalty = 0  # админское действие, submit_date == lesson_date

    with transaction.atomic():
        # Авторитетная проверка статуса под блокировкой строки — гонка двух
        # параллельных burn() иначе создала бы два burned-факта/Payroll.
        locked = repository.lock_for_record(resolution_id)
        if locked is None:
            return None
        if locked['status'] != PENDING:
            raise ValueError('Сжечь можно только нерешённый (pending) пропуск.')

        missed_lesson = Lesson.objects.get(id=locked['missed_lesson_id'])
        payment_teacher_id = _burn_payment_teacher_id(missed_lesson)
        lesson_id = lessons_repository.insert_lesson({
            'lesson_date': burn_date,
            'teacher_id': payment_teacher_id,
            'group_id': locked['missed_lesson_group_id'],
            'original_teacher_id': None,
            'lesson_number': missed_lesson.lesson_number,
            # Вес списания = вес пропущенного занятия (half-lesson 45→0.5).
            'lesson_duration_minutes': missed_lesson.lesson_duration_minutes,
            'lesson_type': 'burned',
            'record_url': None,
            # Уникализирует lessons_natural_key: два студента, сожжённые за один
            # пропуск в один день, иначе схлопнулись бы по (date,group,number,token).
            'submitted_by_token': f'burn:{resolution_id}',
        })
        lessons_repository.insert_attendance(
            lesson_id, [{'student_id': locked['student_id'], 'present': True}],
        )
        lessons_repository.insert_payroll({
            'lesson_id': lesson_id,
            'teacher_id': payment_teacher_id,
            'total_students': 1,
            'present_count': 1,
            'payment': payment,
            'penalty': penalty,
        })
        step = _step(missed_lesson.lesson_duration_minutes)
        lessons_repository.increment_lessons_done(
            locked['missed_lesson_group_id'], [locked['student_id']], step,
        )
        direction_id = Group.objects.filter(
            id=locked['missed_lesson_group_id']).values_list('direction_id', flat=True).first()
        transaction.on_commit(
            lambda: lessons_repository.sync_renewal_stage(locked['student_id'], direction_id))
        repository.mark_burned(resolution_id, fact_lesson_id=lesson_id)

    log_event(
        'extra_lesson_burn', actor_email=_actor(request),
        target_id=resolution_id,
        meta={'lesson_id': lesson_id, 'payment': payment},
        request=request,
    )
    return {'lesson_id': lesson_id, 'payment': payment}
```

- [ ] **Step 4: Run — verify PASS.**

Run: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/tests/test_burn_services.py -q`
Expected: PASS (все burn-тесты).

- [ ] **Step 5: Commit:**

```bash
git add apps/extra_lessons/services.py apps/extra_lessons/tests/test_burn_services.py
git commit -m "feat(absences): burn() creates burned fact + flat 200 payroll (Phase 1c-2 Task 3)"
```

---

## Task 4: Обобщить `delete_fact` на откат сгорания

**Files:**
- Modify: `apps/extra_lessons/services.py:283-334`
- Test: `apps/extra_lessons/tests/test_burn_services.py`

- [ ] **Step 1: Написать failing-тест отката сгорания.**

```python
@pytest.mark.django_db
def test_unburn_reverses_everything(absence_pending, rf_admin):
    from apps.groups.models import GroupMembership
    student_id = absence_pending.student_id
    group_id = Lesson.objects.get(id=absence_pending.missed_lesson_id).group_id
    before = GroupMembership.objects.get(
        group_id=group_id, student_id=student_id).lessons_done

    services.burn(absence_pending.id, request=rf_admin, burn_date='2026-07-18')
    absence_pending.refresh_from_db()
    fact_id = absence_pending.fact_lesson_id

    ok = services.delete_fact(absence_pending.id, rf_admin)
    absence_pending.refresh_from_db()
    assert ok is True
    assert absence_pending.status == PENDING
    assert absence_pending.fact_lesson_id is None
    assert not Lesson.objects.filter(id=fact_id).exists()
    assert not Payroll.objects.filter(lesson_id=fact_id).exists()
    after = GroupMembership.objects.get(
        group_id=group_id, student_id=student_id).lessons_done
    assert after == before  # lessons_done восстановлен


@pytest.mark.django_db
def test_delete_fact_rejects_pending(absence_pending, rf_admin):
    with pytest.raises(ValueError):
        services.delete_fact(absence_pending.id, rf_admin)
```

- [ ] **Step 2: Run — verify FAIL** (`delete_fact` пока отвергает burned: `status != MAKEUP_DONE`).

Run: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/tests/test_burn_services.py -k "unburn or rejects_pending" -q`
Expected: FAIL (ValueError на burned в первом тесте).

- [ ] **Step 3: Обобщить статус-гейт в `delete_fact`.**

Импорт: добавить `BURNED` в import из `apps.extra_lessons.models`.

Заменить обе проверки статуса (неблокирующую ~строка 294 и под-локом ~строка 305):

```python
    if full['status'] not in (MAKEUP_DONE, BURNED):
        raise ValueError('Удалить факт можно только у проведённого доп.урока или сгорания.')
```

и под локом:

```python
        if locked['status'] not in (MAKEUP_DONE, BURNED):
            raise ValueError('Удалить факт можно только у проведённого доп.урока или сгорания.')
```

Обновить докстроку `delete_fact`: «Откатывает проведённый доп.урок ИЛИ сгорание: ...». Тело (fact/present_ids/`_step(fact.lesson_duration_minutes)`/decrement/delete/back_to_pending/sync) — БЕЗ изменений (корректно для обоих: burned-факт тоже несёт длительность исходного урока и present=true).

- [ ] **Step 4: Run — verify PASS** (весь файл, убедиться, что makeup delete_fact НЕ сломан).

Run: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/tests/test_burn_services.py apps/extra_lessons/tests/test_extra_lessons_services.py -q`
Expected: PASS.

- [ ] **Step 5: Commit:**

```bash
git add apps/extra_lessons/services.py apps/extra_lessons/tests/test_burn_services.py
git commit -m "feat(absences): delete_fact reverses burned too (Phase 1c-2 Task 4)"
```

---

## Task 5: API — эндпоинт «Сжечь» + label + delete-lesson guard на burned

**Files:**
- Modify: `apps/extra_lessons/views.py`, `apps/extra_lessons/urls.py`
- Modify: `apps/lessons/services.py:185-195`
- Modify: `apps/changelog/labels.py`
- Test: `apps/extra_lessons/tests/test_extra_lessons_views.py`, `apps/lessons/tests/test_record_lesson_autocreate.py`

- [ ] **Step 1: Написать failing-тесты вьюхи и guard.**

В `apps/extra_lessons/tests/test_extra_lessons_views.py` (повторить существующий admin-auth паттерн этого файла):

```python
@pytest.mark.django_db
def test_burn_endpoint_burns_pending(admin_client, absence_pending):
    resp = admin_client.post(f'/api/admin/extra-lessons/{absence_pending.id}/burn')
    assert resp.status_code == 200
    assert resp.json()['payment'] == 200
    absence_pending.refresh_from_db()
    assert absence_pending.status == 'burned'


@pytest.mark.django_db
def test_burn_endpoint_conflict_when_not_pending(admin_client, absence_pending):
    admin_client.post(f'/api/admin/extra-lessons/{absence_pending.id}/burn')
    resp = admin_client.post(f'/api/admin/extra-lessons/{absence_pending.id}/burn')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_burn_endpoint_requires_manager(teacher_client, absence_pending):
    resp = teacher_client.post(f'/api/admin/extra-lessons/{absence_pending.id}/burn')
    assert resp.status_code in (401, 403)
```

В `apps/lessons/tests/test_record_lesson_autocreate.py` — по образцу `test_delete_lesson_blocked_when_makeup_done`, но статус `burned`:

```python
@pytest.mark.django_db
def test_delete_lesson_blocked_when_burned(...):
    """Обычный урок с сожжённым пропуском (burned) удалить нельзя — иначе
    ON DELETE CASCADE осиротил бы burned-факт + payroll."""
    # ... UPDATE absence_resolutions SET status='burned' по пропуску урока ...
    with pytest.raises(LessonHasMakeupResolutions):
        lessons_services.delete_lesson_full(lesson_id)
```

(Скопировать тело/фикстуры из соседнего makeup_done-теста, заменив статус.)

- [ ] **Step 2: Run — verify FAIL** (нет маршрута /burn → 404; guard не ловит burned).

Run: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/tests/test_extra_lessons_views.py -k burn apps/lessons/tests/test_record_lesson_autocreate.py::test_delete_lesson_blocked_when_burned -q`
Expected: FAIL.

- [ ] **Step 3: Добавить `ExtraLessonBurnView`** в `apps/extra_lessons/views.py`:

Импорт: добавить `msk_today` уже импортирован; `services` уже импортирован.

```python
class ExtraLessonBurnView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        try:
            result = services.burn(pk, request=request, burn_date=msk_today())
        except UnpaidAttendanceBlocked as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        if result is None:
            raise NotFound({'error': 'Not found'})
        return Response(result)
```

- [ ] **Step 4: Маршрут** в `apps/extra_lessons/urls.py` (специфичнее detail — но `/<int:pk>/burn` не пересекается с `/<int:pk>`; добавить рядом с cancel):

```python
from apps.extra_lessons.views import (
    ExtraLessonBurnView, ExtraLessonCancelView, ExtraLessonDetailView, ExtraLessonListCreateView,
)
...
    path('/<int:pk>/burn', ExtraLessonBurnView.as_view(), name='extra-lessons-burn'),
```

- [ ] **Step 5: Label** в `apps/changelog/labels.py` (рядом с прочими extra_lesson, до generic — специфичный путь):

```python
    ('POST', re.compile(r'^/api/admin/extra-lessons/\d+/burn$'), 'extra_lesson.burn'),
```

- [ ] **Step 6: Расширить guard** в `apps/lessons/services.py`:

```python
def _assert_no_makeup_done_resolutions(lesson_id: int) -> None:
    """Бросает LessonHasMakeupResolutions, если по пропускам этого урока уже
    проведён доп.урок (makeup_done) ИЛИ пропуск сожжён (burned). Без гарда
    DB-level ON DELETE CASCADE (extra_lessons.0007) снёс бы резолюцию каскадом,
    осиротив факт (extra/burned) + Payroll. pending/makeup_scheduled — безопасно."""
    from apps.extra_lessons.models import BURNED, MAKEUP_DONE, AbsenceResolution
    if AbsenceResolution.objects.filter(
        missed_lesson_id=lesson_id, status__in=[MAKEUP_DONE, BURNED],
    ).exists():
        raise LessonHasMakeupResolutions()
```

- [ ] **Step 7: Run — verify PASS.**

Run: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/tests/test_extra_lessons_views.py apps/lessons/tests/test_record_lesson_autocreate.py -q`
Expected: PASS.

- [ ] **Step 8: Commit:**

```bash
git add apps/extra_lessons/views.py apps/extra_lessons/urls.py apps/changelog/labels.py apps/lessons/services.py apps/extra_lessons/tests/test_extra_lessons_views.py apps/lessons/tests/test_record_lesson_autocreate.py
git commit -m "feat(absences): burn API endpoint + label + delete-lesson burned guard (Phase 1c-2 Task 5)"
```

---

## Task 6: Сверка lifecycle + полный прогон (ГЕЙТ — STOP)

**Files:**
- Test: `apps/extra_lessons/tests/test_burn_reconciliation_1c2.py` (new)

- [ ] **Step 1: Lifecycle-сверка «сжечь → откат»** — balance/attended/renewals/payroll реверсируются точно, исходный пропуск present=false всё время.

```python
import pytest
from decimal import Decimal

from apps.extra_lessons import services
from apps.extra_lessons.models import BURNED, PENDING
from apps.finances import repository as fin_repo
from apps.lessons.models import Lesson, LessonAttendance
from apps.payroll.models import Payroll
from apps.renewals import engine as renewals_engine


@pytest.mark.django_db
def test_burn_lifecycle_reconciles(absence_pending, rf_admin):
    student_id = absence_pending.student_id
    missed = Lesson.objects.get(id=absence_pending.missed_lesson_id)

    bal0 = fin_repo.balances_for_students([student_id]).get(student_id)
    att0 = fin_repo.attended_units_total(...)   # подставить реальную сигнатуру (student/direction)

    services.burn(absence_pending.id, request=rf_admin, burn_date='2026-07-18')
    absence_pending.refresh_from_db()
    fact_id = absence_pending.fact_lesson_id

    # Списание на 1 (или 0.5) в месяц сжигания; payroll 200; исходный present=false.
    bal1 = fin_repo.balances_for_students([student_id]).get(student_id)
    assert bal1 == bal0 - 1  # или -0.5 для 45-мин исходного — подогнать под фикстуру
    assert Payroll.objects.get(lesson_id=fact_id).payment == 200
    assert LessonAttendance.objects.get(
        lesson_id=missed.id, student_id=student_id).present is False

    # Откат — числа возвращаются.
    services.delete_fact(absence_pending.id, rf_admin)
    absence_pending.refresh_from_db()
    assert absence_pending.status == PENDING
    bal2 = fin_repo.balances_for_students([student_id]).get(student_id)
    assert bal2 == bal0
    assert not Payroll.objects.filter(lesson_id=fact_id).exists()
```

(Сигнатуры `attended_units_total`/`balances_for_students`/renewals — сверить с реальным кодом `apps/finances/repository.py` и `apps/renewals/engine.py`; тест обязан читать РЕАЛЬНЫЕ значения, не хардкод входа. `bal0 - 1` уточнить под длительность фикстурного пропуска.)

- [ ] **Step 2: Проверка «burned не двойным путём»** — новый burned-факт имеет `attendance.burned_at IS NULL` (потребляется в свою дату, а не через старый `burned_at`-приоритет):

```python
@pytest.mark.django_db
def test_burned_fact_attendance_has_no_burned_at(absence_pending, rf_admin):
    services.burn(absence_pending.id, request=rf_admin, burn_date='2026-07-18')
    absence_pending.refresh_from_db()
    att = LessonAttendance.objects.get(lesson_id=absence_pending.fact_lesson_id)
    assert att.burned_at is None  # новый путь не использует старый burned_at
```

- [ ] **Step 3: Полный прогон** затронутых приложений:

Run:
```bash
.venv/Scripts/python.exe -m pytest apps/extra_lessons/ apps/lessons/ apps/finances/ apps/renewals/ apps/dashboard/ apps/changelog/ apps/scheduling/ apps/students/ apps/teacher_spa/ apps/payroll/ -q
```
Expected: PASS кроме 2 известных предсуществующих `test_fifo_inputs` (см. [[project_finances_test_fifo_inputs_bug]]). Любое ДРУГОЕ падение — регрессия, чинить до коммита.

- [ ] **Step 4: Ревью code-quality (opus)** по диапазону 1c-2 (`code-reviewer` агент), починить Important-находки.

- [ ] **Step 5: Commit сверки:**

```bash
git add apps/extra_lessons/tests/test_burn_reconciliation_1c2.py
git commit -m "test(absences): burn lifecycle reconciliation (Phase 1c-2 Task 6)"
```

- [ ] **Step 6: STOP — доложить пользователю:** сверка сошлась (баланс/зарплата/продления реверсируются, исходный пропуск present=false, burned считается штатно), 1c-2 готова, прежде чем переходить к 1c-3 (фронт).

---

## Self-Review (по спеке)

- **Спека «Зарплата» → сгорание 200₽ исходному преподавателю, penalty=0** → Task 3 (`missed_lesson.teacher_id`, `calculate_extra_lesson_payment(1)`, penalty=0). ✅
- **Решение пользователя: уволенному не платим → текущему преп. группы** → Task 3 (`_burn_payment_teacher_id`, fallback на `Group.teacher_id` при `Teacher.active=False`) + тест. ✅
- **Спека «Правило единиц» → burned несёт длительность исходного** → Task 3 (`lesson_duration_minutes = missed.lesson_duration_minutes`). ✅
- **Спека «Сгорание — тоже через ядро» → баланс-гард** → Task 3 (`assert_students_paid`). ✅
- **Спека «Состояния» → pending→burned, откат burned→pending** → Task 1 (статус), Task 3 (burn), Task 4 (откат). ✅
- **Спека «Гарды» → удаление исходного урока с burned-детьми = 409** → Task 5 Step 6. ✅
- **Спека «Гарды» → CRUD burned запрещён** → уже покрыто `SystemLessonProtected` (1a/1b), новых правок не требует; НЕ дублировать.
- **Спека «Единое правило потребления» → burned present=true считается** → 1c-1 снял `.exclude(extra)`, burned не исключается; Task 6 Step 1-2 проверяет сверкой. ✅
- **CLAUDE.md «новый мутирующий URL → правило labels.py»** → Task 5 Step 5. ✅
- **Готча #3 (delete-guard на burned)** → Task 5 Step 6. ✅
- **Готча #4 (вес = исходная длительность)** → Task 3. ✅
- **Готча natural-key collision** → Task 3 (`submitted_by_token=f'burn:{resolution_id}'`). ✅
- **Changelog registry** — модель не новая (AbsenceResolution уже трекается), правок registry.py НЕ требуется.
