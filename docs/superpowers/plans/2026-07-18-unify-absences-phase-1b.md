# Унификация пропусков — Фаза 1b (очередь + авто-создание + статусы) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Превратить `AbsenceResolution` из «доп.урок, назначенный вручную» в полноценную очередь «пропусков, требующих решения»: авто-создание `pending` по каждому отсутствовавшему при записи обычного урока, переименование статусов в `pending / makeup_scheduled / makeup_done` (без терминального `cancelled`), и авто-очистка висящих записей при уходе ученика — **сохраняя денежное поведение неизменным**.

**Architecture:** Эволюция на месте поверх Фазы 1a (пер-ученик `AbsenceResolution`). Авто-создание встраивается в единое ядро `apps/lessons/services.py::record_lesson` (ленивый вызов в extra_lessons, чтобы не завести import-cycle). Статусы переименовываются миграцией данных. Отмена назначения и откат факта теперь возвращают запись в `pending` (не в терминальный `cancelled`), поэтому на пару `(missed_lesson, student)` всегда РОВНО ОДНА строка — частичный uniq-constraint из ревью Фазы 1a откатывается обратно в полный `UNIQUE(missed_lesson, student)`. Спека: `docs/superpowers/specs/2026-07-18-unify-absences-makeup-burn-design.md`.

**Tech Stack:** Django 5 + DRF (managed=True), pytest + pytest-django (реальная `journal_test`), React 19 + TanStack Query v5 (admin), React + @shared (teacher). Команды из `journal_django/`, интерпретатор `.venv/Scripts/python.exe`. Тесты: `.venv/Scripts/python.exe -m pytest <path> -v` (config.settings.test, БД `journal_test`). Миграции — к ОБЕИМ БД (dev `journal` + `journal_test`); НЕ запускать `recreate_test_db.sh`.

---

## Границы Фазы 1b (что ВХОДИТ и что НЕТ)

**Входит:** авто-создание `pending`; переименование статусов (`scheduled→makeup_scheduled`, `done→makeup_done`, убрать `cancelled`, добавить `pending`); отмена назначения → `pending`; откат факта → `pending`; авто-очистка `pending`+`makeup_scheduled` при уходе ученика; раздел показывает pending-очередь с кнопкой «Назначить доп.урок»; полный `UNIQUE(missed_lesson, student)` вместо частичного.

**НЕ входит (Фаза 1c):** «Сжечь» (`burned`-урок); переключение модели потребления (сейчас `record` по-прежнему делает `apply_makeup_attendance` на исходном уроке — как в 1a); блокировка карточек в `LessonEditor`; удаление burn-тоггла из грида; синхронизация продлений на сгорании. **НЕ входит (Фаза 2):** удаление `burned_at`/`burn_surcharge`/`_makeup_completion_dates`.

**Ключевое решение о совместимости API:** admin-эндпоинт `POST /api/admin/extra-lessons` СОХРАНЯЕТ прежний контракт тела (`{missed_lesson_id, teacher_id, student_ids, scheduled_date, scheduled_time, duration_minutes}`), но меняет семантику: для каждого ученика он **upsert-ит** — находит его `pending`-резолюцию (созданную авто-создателем) и переводит её в `makeup_scheduled`; если резолюции нет (edge — напр. пропуск до релиза, без авто-создания), создаёт её сразу в `makeup_scheduled`. Так и раздел (кнопка на pending-строке), и существующая grid-модалка `AssignExtraLessonModal` шлют один и тот же запрос без конфликта с авто-создателем. Идемпотентность: назначить уже назначенную/проведённую резолюцию → 409.

**Решение об уходе ученика:** авто-очистка срабатывает на переходах `enrollment_status` в `declined` / `not_enrolled` (постоянный уход/архивация), НЕ на `frozen` (временная заморозка — ученик вернётся, пропуски должны сохраниться). Удаляются `pending` и `makeup_scheduled` (у обоих нет факта/денег); `makeup_done` не трогаем (есть факт-урок + payroll).

---

## Статусы: старое → новое

| 1a (сейчас) | 1b | смысл |
|---|---|---|
| — | `pending` | авто-создан по пропуску, ждёт решения (нет факта, нет денег) |
| `scheduled` | `makeup_scheduled` | доп.урок назначен (преподаватель/время), ещё не проведён |
| `done` | `makeup_done` | доп.урок проведён (есть extra-факт + payroll) |
| `cancelled` | *(удаляется как строка)* | отмена больше не терминальна — назначение отменяют в `pending` |

Переходы: `pending —assign→ makeup_scheduled —record→ makeup_done`; `makeup_scheduled —cancel→ pending`; `makeup_done —rollback(delete_fact)→ pending`.

---

## Структура файлов (1b)

**Бэк:**
- `apps/extra_lessons/models.py` — новые константы статусов + `STATUS_CHOICES`, `default=PENDING`, полный `UNIQUE(missed_lesson, student)` (убрать `condition=~Q(...)`).
- `apps/extra_lessons/migrations/0006_*` — данные: `scheduled→makeup_scheduled`, `done→makeup_done`, удалить `cancelled`-строки; + `AlterConstraint` (полный uniq) + новый CHECK.
- `apps/extra_lessons/repository.py` — `autocreate_pending`, `assign_makeup` (upsert), `back_to_pending`, `delete_open_for_student`; переименовать статус-константы в вызовах.
- `apps/extra_lessons/services.py` — `create_assignment`→ семантика assign; `record`→ `makeup_done`; `cancel_assignment`→ `pending`; `delete_fact`→ `pending`; `autocreate_pending_for_lesson`; `cleanup_on_student_leave`.
- `apps/lessons/services.py::record_lesson` — авто-создание pending (ленивый вызов).
- `apps/students/services.py::change_student_status` — вызвать очистку в ветке ухода.
- `apps/extra_lessons/serializers.py`, `views.py`, `urls.py` — статусы; эндпоинт assign сохраняет контракт.
- `apps/finances/repository.py::_makeup_completion_dates` — `status='makeup_done'`.
- `apps/changelog/labels.py` — метки мутаций (assign/cancel back-to-pending) если пути меняются (пути НЕ меняются → скорее всего правки не нужны, проверить).

**Фронт admin:** `lib/shared-types.ts` (union статусов), `pages/extra-lessons/ExtraLessonsListPage.tsx` (лейблы статусов + кнопка «Назначить» на pending-строке + текст отмены/отката), `components/lessons/AssignExtraLessonModal.tsx` (без изменения контракта). **Фронт teacher:** `hooks/useExtraLesson.ts` (union статусов).

**Тесты:** `apps/extra_lessons/tests/test_extra_lessons_autocreate.py` (new), `test_extra_lessons_cleanup.py` (new), адаптировать `test_extra_lessons_{repository,services,api}.py`, `test_reconciliation_1a.py`; `apps/lessons/tests/` (авто-создание из record_lesson), `apps/students/tests/` (очистка при уходе).

---

## Task 1: Переименование статусов в модели + миграция

**Files:** Modify `apps/extra_lessons/models.py`; Create `apps/extra_lessons/migrations/0006_rename_statuses.py`; Test `apps/extra_lessons/tests/test_status_migration_1b.py` (new).

- [ ] **Step 1: Обновить константы и constraints в `models.py`.** Заменить блок констант и Meta.constraints:

```python
PENDING = 'pending'
MAKEUP_SCHEDULED = 'makeup_scheduled'
MAKEUP_DONE = 'makeup_done'
STATUS_CHOICES = [PENDING, MAKEUP_SCHEDULED, MAKEUP_DONE]
```

В самой модели `AbsenceResolution`: `status = models.CharField(max_length=16, default=PENDING)`. В `Meta.constraints` заменить частичный uniq на полный (терминального cancelled больше нет → на пару всегда одна строка):

```python
        constraints = [
            models.UniqueConstraint(fields=['missed_lesson', 'student'],
                                    name='absence_resolutions_missed_student_key'),
            models.CheckConstraint(name='absence_resolutions_status_check',
                                   condition=models.Q(status__in=STATUS_CHOICES)),
        ]
```

Удалить старые константы `SCHEDULED='scheduled'`, `DONE='done'`, `CANCELLED='cancelled'`. Оставить `VALID_DURATIONS`.

**КРИТИЧНО (иначе migrate/makemigrations в Step 6-7 упадут ImportError):** `repository.py` и `services.py` импортируют старые константы на ВЕРХНЕМ уровне модуля. Приложение обязано ИМПОРТИРОВАТЬСЯ чисто, чтобы system checks при `migrate` прошли. Поэтому НА ЭТОМ ЖЕ шаге поправить ТОЛЬКО строки `import` в этих двух файлах на новые имена:
- `repository.py`: `from apps.extra_lessons.models import (MAKEUP_DONE, MAKEUP_SCHEDULED, PENDING, AbsenceResolution)`.
- `services.py`: `from apps.extra_lessons.models import MAKEUP_DONE, MAKEUP_SCHEDULED, PENDING`.

ТЕЛА функций (сравнения `== SCHEDULED` и т.п.) на этом шаге ещё ссылаются на старые имена → рантайм-NameError; их чинят Task 2 (repository) и Task 3 (services). Это осознанный транзиентный red: тесты repository/services/api временно падают, но приложение импортируется, `makemigrations --check` чист, миграция применяется. Контроллер на Task 1 проверяет ТОЛЬКО `test_status_migration_1b.py` + чистоту графа; полный зелёный — к Task 6. (Тот же паттерн принятого промежуточного red, что в Фазе 1a.)

- [ ] **Step 2: Написать падающий тест миграции статусов** — create `test_status_migration_1b.py`:

```python
"""Миграция данных: scheduled→makeup_scheduled, done→makeup_done, cancelled удаляются."""
from __future__ import annotations
import pytest
from django.db import connection
from apps.extra_lessons._migration_helpers import remap_statuses_1b

pytestmark = pytest.mark.django_db


def test_remap_statuses(teacher_fixture, missed_lesson_fixture, student_fixture):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO students (full_name, enrollment_status) VALUES ('__st_s2__','enrolled') RETURNING id")
        sid2 = cur.fetchone()[0]
        cur.execute("INSERT INTO students (full_name, enrollment_status) VALUES ('__st_s3__','enrolled') RETURNING id")
        sid3 = cur.fetchone()[0]
        # Три строки с legacy-статусами на разных учениках (uniq по missed+student).
        for sid, st in ((student_fixture, 'scheduled'), (sid2, 'done'), (sid3, 'cancelled')):
            cur.execute(
                "INSERT INTO absence_resolutions (missed_lesson_id, student_id, status, created_at) "
                "VALUES (%s,%s,%s, now())", [missed_lesson_fixture, sid, st])
    try:
        remap_statuses_1b(connection)
        with connection.cursor() as cur:
            cur.execute("SELECT student_id, status FROM absence_resolutions WHERE missed_lesson_id=%s ORDER BY student_id",
                        [missed_lesson_fixture])
            rows = dict(cur.fetchall())
        assert rows.get(student_fixture) == 'makeup_scheduled'
        assert rows.get(sid2) == 'makeup_done'
        assert sid3 not in rows  # cancelled удалён
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id=%s', [missed_lesson_fixture])
            cur.execute('DELETE FROM students WHERE id IN (%s,%s)', [sid2, sid3])
```

- [ ] **Step 3: Запустить → ImportError** (`remap_statuses_1b` нет).
Run: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/tests/test_status_migration_1b.py -v`

- [ ] **Step 4: Добавить хелпер** в `apps/extra_lessons/_migration_helpers.py` (рядом с существующим `migrate_assignments_to_resolutions`):

```python
def remap_statuses_1b(connection) -> None:
    """1b: cancelled-строки удалить (терминального статуса больше нет), затем
    переименовать scheduled→makeup_scheduled и done→makeup_done. Порядок важен:
    сначала DELETE cancelled, потом UPDATE (чтобы CHECK старого набора не мешал —
    UPDATE применяется до смены CHECK в миграции schema-части)."""
    with connection.cursor() as cur:
        cur.execute("DELETE FROM absence_resolutions WHERE status = 'cancelled'")
        cur.execute("UPDATE absence_resolutions SET status = 'makeup_scheduled' WHERE status = 'scheduled'")
        cur.execute("UPDATE absence_resolutions SET status = 'makeup_done' WHERE status = 'done'")
```

- [ ] **Step 5: Запустить тест → PASS.**

- [ ] **Step 6: Сгенерировать schema-миграцию + вставить data-шаг.**
Run: `.venv/Scripts/python.exe manage.py makemigrations extra_lessons --name rename_statuses`
Django сгенерит `0006_...` с `AlterConstraint`/`AlterField` (новый CHECK, новый uniq, default). ОТКРЫТЬ файл и вставить `RunPython(remap)` ПЕРВОЙ операцией (до смены CHECK — старые значения `scheduled/done` должны переехать до того, как новый CHECK запретит их; а `cancelled` удаляется). Добавить в начало файла:

```python
from apps.extra_lessons._migration_helpers import remap_statuses_1b


def _forward(apps, schema_editor):
    remap_statuses_1b(schema_editor.connection)
```

И первой операцией в `operations = [ migrations.RunPython(_forward, migrations.RunPython.noop), ... <сгенерированные схема-операции> ]`. ВАЖНО: если сгенерированная схема-операция меняет CHECK-constraint РАНЬШЕ RunPython, порядок сломает данные — убедиться, что RunPython стоит ПЕРВЫМ. Если Django-порядок иначе, разнести на две миграции: `0006_remap_statuses_data` (только RunPython) и `0007_rename_statuses_schema` (схема).

- [ ] **Step 7: Применить к обеим БД + проверить чистоту графа.**
Run: `.venv/Scripts/python.exe manage.py migrate extra_lessons`
Run: `DJANGO_SETTINGS_MODULE=config.settings.test .venv/Scripts/python.exe manage.py migrate extra_lessons`
Run: `.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` → `No changes detected`.

- [ ] **Step 8: Commit** (контроллер): `feat(absences): rename statuses to pending/makeup_scheduled/makeup_done (Phase 1b Task 1)`.

---

## Task 2: Репозиторий — авто-создание, assign-upsert, back-to-pending, cleanup

**Files:** Modify `apps/extra_lessons/repository.py`; Test `apps/extra_lessons/tests/test_extra_lessons_repository.py`.

- [ ] **Step 1: Обновить импорт статусов** в `repository.py`:

```python
from apps.extra_lessons.models import (
    MAKEUP_DONE, MAKEUP_SCHEDULED, PENDING, AbsenceResolution,
)
```

- [ ] **Step 2: Добавить/переписать функции.** Полные тела:

```python
def autocreate_pending(missed_lesson_id, student_ids) -> int:
    """Идемпотентно создать pending-резолюции по списку отсутствовавших.
    ON CONFLICT DO NOTHING по UNIQUE(missed_lesson, student). Возвращает число
    реально созданных (для лога/тестов). Пустой список — no-op."""
    if not student_ids:
        return 0
    from django.db import connection
    with connection.cursor() as cur:
        cur.executemany(
            "INSERT INTO absence_resolutions (missed_lesson_id, student_id, status, created_at) "
            "VALUES (%s, %s, 'pending', now()) "
            "ON CONFLICT (missed_lesson_id, student_id) DO NOTHING",
            [(missed_lesson_id, sid) for sid in student_ids],
        )
        # rowcount у executemany ненадёжен по драйверам — считаем отдельным запросом не нужно;
        # вернём len как верхнюю оценку (тесты проверяют факт создания через выборку).
    return len(student_ids)


def lock_for_assign(missed_lesson_id, student_id) -> Optional[dict]:
    """Блокировка строки резолюции (SELECT ... FOR UPDATE) перед переводом в
    makeup_scheduled. None → строки нет (тогда сервис создаст напрямую)."""
    return (AbsenceResolution.objects.select_for_update()
            .filter(missed_lesson_id=missed_lesson_id, student_id=student_id)
            .values('id', 'status').first())


def assign_pending(resolution_id, *, assigned_teacher_id, scheduled_date, scheduled_time, duration_minutes) -> None:
    """pending → makeup_scheduled с параметрами доп.урока."""
    AbsenceResolution.objects.filter(id=resolution_id).update(
        status=MAKEUP_SCHEDULED, assigned_teacher_id=assigned_teacher_id,
        scheduled_date=scheduled_date, scheduled_time=scheduled_time,
        duration_minutes=duration_minutes)


def create_scheduled_direct(*, missed_lesson_id, student_id, assigned_teacher_id,
                            scheduled_date, scheduled_time, duration_minutes) -> int:
    """Edge: pending-строки нет (пропуск до релиза) → создать сразу makeup_scheduled."""
    obj = AbsenceResolution.objects.create(
        missed_lesson_id=missed_lesson_id, student_id=student_id,
        assigned_teacher_id=assigned_teacher_id, status=MAKEUP_SCHEDULED,
        scheduled_date=scheduled_date, scheduled_time=scheduled_time,
        duration_minutes=duration_minutes)
    return obj.id


def back_to_pending(resolution_id) -> None:
    """Отмена назначения / откат факта → pending. Сбрасывает параметры доп.урока и факт."""
    AbsenceResolution.objects.filter(id=resolution_id).update(
        status=PENDING, assigned_teacher_id=None, scheduled_date=None,
        scheduled_time=None, duration_minutes=None, fact_lesson_id=None)


def mark_makeup_done(resolution_id, *, fact_lesson_id) -> None:
    AbsenceResolution.objects.filter(id=resolution_id).update(
        status=MAKEUP_DONE, fact_lesson_id=fact_lesson_id)


def delete_open_for_student(student_id) -> int:
    """Уход ученика: удалить его pending + makeup_scheduled (нет факта/денег).
    makeup_done не трогаем. Возвращает число удалённых."""
    qs = AbsenceResolution.objects.filter(
        student_id=student_id, status__in=[PENDING, MAKEUP_SCHEDULED])
    n = qs.count()
    qs.delete()
    return n
```

Также в `repository.py`: **удалить** старые `create_resolutions`, `mark_done`, `reset_to_scheduled`, `cancel`, `has_active_resolution` в их 1a-виде и заменить/переименовать под новую семантику:
- `has_active_resolution(missed_lesson_id, student_id)` → теперь «есть ли ЛЮБАЯ резолюция» (uniq полный, cancelled нет), используется как «уже назначено/проведено?»: вернуть `exists()` для status в (makeup_scheduled, makeup_done).
- `lock_for_record`/`lock_for_delete` — оставить, но статус-проверки в сервисе поменять на новые значения.
- `list_resolutions` — оставить (сортировка/фильтры те же, добавить возможность фильтра `status='pending'`).
- `get_resolution_full` — оставить как есть.

- [ ] **Step 3: TDD — адаптировать `test_extra_lessons_repository.py`** под новые имена/статусы. Сохранить смысл: autocreate создаёт pending; повторный autocreate идемпотентен (не дублирует); assign_pending переводит pending→makeup_scheduled; back_to_pending сбрасывает; mark_makeup_done ставит makeup_done+fact; delete_open_for_student удаляет pending+makeup_scheduled, но НЕ makeup_done. Прогонять: тест падает → реализовать → зелёный. Не забыть cleanup absence_resolutions (см. `resolution_cleanup` fixture-паттерн).

- [ ] **Step 4:** `.venv/Scripts/python.exe -m pytest apps/extra_lessons/tests/test_extra_lessons_repository.py -v` → PASS.
- [ ] **Step 5: Commit** `refactor(absences): per-status repository ops (autocreate/assign/back-to-pending/cleanup) (Phase 1b Task 2)`.

---

## Task 3: Сервисы — assign-семантика, record→makeup_done, cancel/rollback→pending, cleanup

**Files:** Modify `apps/extra_lessons/services.py`; Modify `apps/finances/repository.py::_makeup_completion_dates`; Test `apps/extra_lessons/tests/test_extra_lessons_services.py`.

- [ ] **Step 1: `create_assignment(data, request)` → assign-семантика.** Полное тело (сохраняет прежний контракт тела и валидации 1a; вместо вставки — upsert pending→makeup_scheduled):

```python
def create_assignment(data: dict, request) -> dict:
    """Назначить доп.урок (assign) по multi-select. Для каждого ученика:
    находит его pending-резолюцию (авто-создана при записи урока) и переводит в
    makeup_scheduled; если pending нет (пропуск до релиза) — создаёт сразу
    makeup_scheduled. Валидации 1a сохранены (урок есть; ученик реально
    present=false; balance>0). Дубль (уже makeup_scheduled/makeup_done) → 409."""
    missed_lesson_id = data['missed_lesson_id']
    if not Lesson.objects.filter(id=missed_lesson_id).exists():
        raise MissedLessonNotFound(f'Урок #{missed_lesson_id} не найден.')
    student_ids = data['student_ids']
    not_absent = repository.students_not_absent(missed_lesson_id, student_ids)
    if not_absent:
        raise StudentNotAbsent(list(Student.objects.filter(id__in=not_absent).values_list('full_name', flat=True)))
    dup = [sid for sid in student_ids if repository.has_active_resolution(missed_lesson_id, sid)]
    if dup:
        raise DuplicateAssignment(list(Student.objects.filter(id__in=dup).values_list('full_name', flat=True)))
    lessons_repository.assert_students_paid(student_ids)

    resolution_ids = []
    with transaction.atomic():
        for sid in student_ids:
            locked = repository.lock_for_assign(missed_lesson_id, sid)
            if locked is None:
                rid = repository.create_scheduled_direct(
                    missed_lesson_id=missed_lesson_id, student_id=sid,
                    assigned_teacher_id=data['teacher_id'],
                    scheduled_date=_to_date(data['scheduled_date']),
                    scheduled_time=_to_time(data['scheduled_time']),
                    duration_minutes=data['duration_minutes'])
            else:
                if locked['status'] != PENDING:
                    raise DuplicateAssignment([str(sid)])  # гонка: уже назначено
                repository.assign_pending(
                    locked['id'], assigned_teacher_id=data['teacher_id'],
                    scheduled_date=_to_date(data['scheduled_date']),
                    scheduled_time=_to_time(data['scheduled_time']),
                    duration_minutes=data['duration_minutes'])
                rid = locked['id']
            resolution_ids.append(rid)
    log_event('extra_lesson_assign', actor_email=_actor(request), target_id=resolution_ids[0],
              meta={'missed_lesson_id': missed_lesson_id, 'student_ids': student_ids,
                    'resolution_ids': resolution_ids}, request=request)
    return {'created': len(resolution_ids), 'resolution_ids': resolution_ids}
```

Импорты в services.py: `from apps.extra_lessons.models import MAKEUP_DONE, MAKEUP_SCHEDULED, PENDING`.

- [ ] **Step 2: `record(...)` → makeup_done.** Тело как в 1a, но: проверка статуса `!= MAKEUP_SCHEDULED` (вместо `SCHEDULED`), финальный вызов `repository.mark_makeup_done(resolution_id, fact_lesson_id=lesson_id)` (вместо `mark_done`). Всё остальное (insert_lesson lesson_type='extra', insert_attendance, insert_payroll 200, `apply_makeup_attendance` — В 1b СОХРАНЯЕТСЯ, переключение модели потребления это 1c) — без изменений.

- [ ] **Step 3: `cancel_assignment(resolution_id, request)` → pending.** Тело:

```python
def cancel_assignment(resolution_id, request):
    """Отмена назначенного доп.урока: makeup_scheduled → pending (пропуск снова
    ждёт решения). None → нет резолюции (404). ValueError → не makeup_scheduled (409)."""
    full = repository.get_resolution_full(resolution_id)
    if full is None:
        return None
    if full['status'] != MAKEUP_SCHEDULED:
        raise ValueError('Отменить можно только назначенный (ещё не проведённый) доп.урок.')
    repository.back_to_pending(resolution_id)
    log_event('extra_lesson_cancel', actor_email=_actor(request), target_id=resolution_id, meta={}, request=request)
    return repository.get_resolution_full(resolution_id)
```

(Убрать `repository.cancel` — его больше нет. Проверка статуса теперь в сервисе; гонку закрывает `back_to_pending` идемпотентно, но для строгости можно добавить `lock` — оставляем на усмотрение, тест на «повторная отмена → 409» проверяет.)

- [ ] **Step 4: `delete_fact(resolution_id, request)` → pending.** Тело как в 1a, но: проверка `!= MAKEUP_DONE` (вместо `DONE`) и финал `repository.back_to_pending(resolution_id)` (вместо `reset_to_scheduled`). `revert_makeup_attendance` СОХРАНЯЕТСЯ (1a-модель потребления).

- [ ] **Step 5: Добавить `autocreate_pending_for_lesson` и `cleanup_on_student_leave`.** Тела:

```python
def autocreate_pending_for_lesson(missed_lesson_id, absent_student_ids) -> int:
    """Вызывается из record_lesson (та же транзакция) для обычных уроков.
    Создаёт pending по отсутствовавшим. Идемпотентно."""
    return repository.autocreate_pending(missed_lesson_id, absent_student_ids)


def cleanup_on_student_leave(student_id) -> int:
    """Уход/архивация ученика: удалить его pending + makeup_scheduled резолюции
    (нет факта/денег). makeup_done не трогаем. Вызывается из
    apps.students.services.change_student_status."""
    return repository.delete_open_for_student(student_id)
```

- [ ] **Step 6: `finances/repository.py::_makeup_completion_dates`** — заменить `status='done'` на `status='makeup_done'` (тело в остальном без изменений).

- [ ] **Step 7: TDD — адаптировать `test_extra_lessons_services.py`.** Сохранить/переименовать: happy assign (создаёт makeup_scheduled из pending; проверить, что предварительно созданный pending переходит, а не дублируется); missed-not-found; not-absent; duplicate (уже makeup_scheduled → 409); unpaid; record→makeup_done (payment 200); cancel→pending; delete_fact→pending; second-record→409; second-delete→409. Плюс НОВЫЕ: `test_autocreate_pending_for_lesson_idempotent`; `test_cleanup_on_student_leave_deletes_open_keeps_done`. Прогонять пошагово.

- [ ] **Step 8:** `.venv/Scripts/python.exe -m pytest apps/extra_lessons/tests/test_extra_lessons_services.py apps/finances/ -q` → PASS (кроме 2 предсуществующих `test_fifo_inputs`).
- [ ] **Step 9: Commit** `refactor(absences): assign/record/cancel/rollback over pending lifecycle (Phase 1b Task 3)`.

---

## Task 4: Авто-создание pending в record_lesson

**Files:** Modify `apps/lessons/services.py::record_lesson`; Test `apps/lessons/tests/test_record_lesson_autocreate.py` (new).

- [ ] **Step 1: Написать падающий тест** — create `test_record_lesson_autocreate.py`:

```python
"""record_lesson обычного урока авто-создаёт pending-резолюции по отсутствовавшим."""
from __future__ import annotations
import pytest
from django.db import connection
from apps.lessons import services

pytestmark = pytest.mark.django_db


def _pending_students(missed_lesson_id):
    with connection.cursor() as cur:
        cur.execute("SELECT student_id FROM absence_resolutions WHERE missed_lesson_id=%s AND status='pending' ORDER BY student_id",
                    [missed_lesson_id])
        return [r[0] for r in cur.fetchall()]


def test_regular_lesson_autocreates_pending_for_absent(
    group_fixture, teacher_fixture, student_fixture, membership_fixture,
):
    res = services.record_lesson(
        lesson_date='2026-05-01', teacher_id=teacher_fixture, group_id=group_fixture,
        original_teacher_id=None, lesson_number=1, lesson_duration_minutes=60,
        lesson_type='regular', record_url=None, submitted_by_token='t',
        submit_date='2026-05-01',
        attendance=[{'student_id': student_fixture, 'present': False}])
    lesson_id = res['lesson_id']
    try:
        assert _pending_students(lesson_id) == [student_fixture]
        # Идемпотентность: attendance повторно (update_attendance_cell не создаёт дублей —
        # но здесь проверяем, что второй record другого урока не влияет; повтор autocreate
        # через прямой вызов не должен дублировать):
        from apps.extra_lessons import services as el
        el.autocreate_pending_for_lesson(lesson_id, [student_fixture])
        assert _pending_students(lesson_id) == [student_fixture]
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id=%s', [lesson_id])
            cur.execute('DELETE FROM payroll WHERE lesson_id=%s', [lesson_id])
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id=%s', [lesson_id])
            cur.execute('DELETE FROM lessons WHERE id=%s', [lesson_id])


def test_extra_lesson_does_not_autocreate(
    group_fixture, teacher_fixture, student_fixture, membership_fixture,
):
    res = services.record_lesson(
        lesson_date='2026-05-02', teacher_id=teacher_fixture, group_id=group_fixture,
        original_teacher_id=None, lesson_number=1, lesson_duration_minutes=60,
        lesson_type='extra', record_url=None, submitted_by_token='t',
        submit_date='2026-05-02',
        attendance=[{'student_id': student_fixture, 'present': False}])
    lesson_id = res['lesson_id']
    try:
        assert _pending_students(lesson_id) == []  # extra не порождает pending
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id=%s', [lesson_id])
            cur.execute('DELETE FROM payroll WHERE lesson_id=%s', [lesson_id])
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id=%s', [lesson_id])
            cur.execute('DELETE FROM lessons WHERE id=%s', [lesson_id])
```

Примечание: `test_extra_lesson_does_not_autocreate` использует group_fixture (extra-урок на группе) — фикстуры extra_lessons/conftest доступны и в apps/lessons/tests? НЕТ — они в extra_lessons/tests/conftest.py. Использовать фикстуры apps/lessons/tests/conftest.py (проверить имена: group/teacher/student/membership). Если их нет — создать локальные в тестовом файле по образцу. (Исполнителю: прочитать `apps/lessons/tests/conftest.py` и взять реальные имена фикстур.)

- [ ] **Step 2: Запустить → FAIL** (pending не создаётся).

- [ ] **Step 3: Встроить авто-создание в `record_lesson`.** В `apps/lessons/services.py::record_lesson`, ВНУТРИ `with transaction.atomic()`, ПОСЛЕ `repository.insert_attendance(lesson_id, attendance)` и до/после payroll (порядок с payroll неважен, главное в той же транзакции), добавить:

```python
        # Авто-создание «пропусков, требующих решения» — только для обычных уроков
        # (extra/burned сами являются РЕЗУЛЬТАТОМ решения, пропусков не порождают).
        # Ленивый импорт: apps.extra_lessons.repository импортит apps.lessons.models,
        # прямой top-level импорт здесь завёл бы цикл.
        if lesson_type == 'regular':
            absent_student_ids = [a['student_id'] for a in attendance if not a['present']]
            if absent_student_ids:
                from apps.extra_lessons import services as extra_lessons_services
                extra_lessons_services.autocreate_pending_for_lesson(lesson_id, absent_student_ids)
```

- [ ] **Step 4: Запустить тест → PASS.**
Run: `.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_record_lesson_autocreate.py -v`

- [ ] **Step 5: Регресс — весь lessons + teacher_spa** (submit_lesson тоже идёт через record_lesson):
Run: `.venv/Scripts/python.exe -m pytest apps/lessons/ apps/teacher_spa/ -q` → PASS (кроме известных).
- [ ] **Step 6: Commit** `feat(absences): auto-create pending resolutions on regular lesson record (Phase 1b Task 4)`.

---

## Task 5: Авто-очистка при уходе ученика

**Files:** Modify `apps/students/services.py::change_student_status`; Test `apps/students/tests/test_student_leave_cleanup.py` (new).

- [ ] **Step 1: Написать падающий тест** — create `test_student_leave_cleanup.py`. (Исполнителю: прочитать `apps/students/tests/conftest.py` и `test_status_service.py` для реальных имён фикстур и способа создать ученика с группой/членством; ниже — форма проверки.)

```python
"""Уход ученика (declined/not_enrolled) удаляет его pending+makeup_scheduled,
но не makeup_done."""
from __future__ import annotations
import pytest
from django.db import connection
from apps.students import services

pytestmark = pytest.mark.django_db


def _statuses(student_id):
    with connection.cursor() as cur:
        cur.execute("SELECT status FROM absence_resolutions WHERE student_id=%s ORDER BY status", [student_id])
        return [r[0] for r in cur.fetchall()]


def test_leaving_deletes_open_keeps_done(student_with_group_fixture, missed_lesson_fixture):
    sid = student_with_group_fixture  # адаптировать под реальную фикстуру
    with connection.cursor() as cur:
        for st in ('pending', 'makeup_scheduled', 'makeup_done'):
            cur.execute("INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, lesson_duration_minutes, lesson_type, submitted_by_token) "
                        "SELECT group_id, teacher_id, lesson_date, lesson_number, 60, 'regular', 't' FROM lessons WHERE id=%s RETURNING id", [missed_lesson_fixture])
            ml = cur.fetchone()[0]
            cur.execute("INSERT INTO absence_resolutions (missed_lesson_id, student_id, status, created_at) VALUES (%s,%s,%s, now())", [ml, sid, st])
    try:
        services.change_student_status(sid, 'declined', actor=None)
        assert _statuses(sid) == ['makeup_done']  # pending+makeup_scheduled удалены
    finally:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM absence_resolutions WHERE student_id=%s", [sid])
```

(Исполнителю: точная фикстура ученика с группой/членством и корректный вызов `change_student_status` — по образцу `apps/students/tests/test_status_service.py`. Ключевая проверка: после ухода остаётся только makeup_done.)

- [ ] **Step 2: Запустить → FAIL.**

- [ ] **Step 3: Вызвать очистку в `change_student_status`.** В ветке ухода (где `new_status in ('declined', 'not_enrolled')` — та, что делает `cancel_future_planned`/`remove_membership`/`decline_deal`, см. текущие строки ~138-147), ПОСЛЕ снятия членств добавить:

```python
        # Уход/архивация: снять «пропуски, требующие решения» (pending +
        # назначенные, но не проведённые доп.уроки — денег/факта нет).
        # makeup_done не трогаем (есть факт-урок + payroll).
        from apps.extra_lessons import services as extra_lessons_services
        extra_lessons_services.cleanup_on_student_leave(student_id)
```

(Ленивый импорт — избегаем import-cycle students↔extra_lessons. Только в ветке declined/not_enrolled; НЕ в ветке frozen.)

- [ ] **Step 4: Запустить тест → PASS.**
- [ ] **Step 5: Регресс** `.venv/Scripts/python.exe -m pytest apps/students/ -q` → PASS.
- [ ] **Step 6: Commit** `feat(absences): cleanup open resolutions when student leaves (Phase 1b Task 5)`.

---

## Task 6: Сериализаторы / вьюхи / урлы + API-тесты

**Files:** Modify `apps/extra_lessons/serializers.py`, `views.py`, `urls.py`; Modify `apps/changelog/labels.py` (если нужны новые метки); Test `apps/extra_lessons/tests/test_extra_lessons_api.py`.

- [ ] **Step 1: Вьюхи/статусы.** Контракты HTTP не меняются (пути те же). Проверить и поправить:
  - `ExtraLessonListCreateView.post` — по-прежнему принимает `ExtraLessonCreateSerializer` (тот же), вызывает `services.create_assignment` (теперь assign-семантика). Коды: 201 при успехе, 400 (MissedLessonNotFound/StudentNotAbsent/Unpaid), 409 (DuplicateAssignment), 409 при IntegrityError (оставить из ревью 1a — теперь редко, uniq полный). Ничего не менять по коду, только смысл.
  - `ExtraLessonCancelView.post` — теперь возвращает резолюцию в `pending`; ValueError→409 (не makeup_scheduled). Код без изменений.
  - `ExtraLessonDetailView.delete` (delete_fact) — makeup_done→pending; ValueError→409. Без изменений.
  - Фильтр списка: разрешить `?status=pending|makeup_scheduled|makeup_done` (в `_parse_list_params` уже прокидывается `status` — проверить, что не хардкодит старые значения).

- [ ] **Step 2: `apps/changelog/labels.py`** — если метка операции завязана на URL+метод и текст ссылается на «доп.урок» — обновить формулировки (assign/отмена→pending). Пути не поменялись, так что структурно правок может не быть; ПРОВЕРИТЬ `labels.py` на строки про extra-lessons и актуализировать текст статусов. (Реестр `changelog/registry.py` НЕ трогаем — модель та же.)

- [ ] **Step 3: TDD — адаптировать `test_extra_lessons_api.py`.** Изменения смысла:
  - create (assign) happy: 201, `resp.data['created']==1`. Но теперь ПРЕДУСЛОВИЕ: для «чистого» assign нужна pending-строка ИЛИ путь create_scheduled_direct (когда pending нет). В тестах `missed_lesson_fixture` НЕ авто-создаёт pending (он создаётся только через record_lesson). Значит assign пойдёт по ветке `create_scheduled_direct` → makeup_scheduled. Проверить detail: `status=='makeup_scheduled'`.
  - Добавить тест: если pending уже существует (создать вручную INSERT pending), то assign переводит ЕГО (не плодит вторую строку) — проверить, что в `absence_resolutions` для (missed,student) ровно 1 строка со status='makeup_scheduled'.
  - cancel happy: 200, `status=='pending'` (было 'cancelled').
  - delete happy (после record): 204, затем detail `status=='pending'` (было 'scheduled'), fact_lesson_id null.
  - record happy: 200; тело `{present: true}`.
  - Дубль assign: сначала assign (→makeup_scheduled), второй assign тем же → 409.
  - Прочие RBAC/404/409 — сохранить.

- [ ] **Step 4:** `.venv/Scripts/python.exe -m pytest apps/extra_lessons/ apps/changelog/ -q` → PASS.
- [ ] **Step 5: Commit** `refactor(absences): API over pending lifecycle + status filter (Phase 1b Task 6)`.

---

## Task 7: Фронт — статусы, pending-очередь, кнопки

**Files:** Modify `frontend/admin-src/src/lib/shared-types.ts`, `pages/extra-lessons/ExtraLessonsListPage.tsx`; Modify `frontend/teacher-src/src/hooks/useExtraLesson.ts`.

- [ ] **Step 1: admin `shared-types.ts`** — `AbsenceResolution.status: 'pending' | 'makeup_scheduled' | 'makeup_done'`. `ExtraLessonDetail`/teacher union — аналогично.
- [ ] **Step 2: admin `ExtraLessonsListPage.tsx`** — `STATUS_LABELS = { pending: 'Ждёт решения', makeup_scheduled: 'Назначен', makeup_done: 'Проведён' }`. Действия по строке:
  - `pending` → кнопка «Назначить доп.урок» (открывает `AssignExtraLessonModal`, преднастроенный на `missed_lesson_id` + одного `student_id` этой строки; модалка уже шлёт нужное тело через `create` мутацию).
  - `makeup_scheduled` → кнопка «Отменить» (`cancel` мутация; тост «Назначение отменено, пропуск снова ждёт решения»).
  - `makeup_done` → кнопка «Откатить» с подтверждением (`remove` мутация; тост «Факт удалён, пропуск снова ждёт решения»).
  Колонки: Дата (scheduled_date может быть null для pending → показывать «—» через `fmtDate` guard), Группа, Ученик, Преподаватель (null для pending), Статус, действия. Добавить фильтр по статусу (SelectInput в тулбаре, значения pending/makeup_scheduled/makeup_done) — опционально, если DataTable уже даёт filters.
- [ ] **Step 3: `AssignExtraLessonModal.tsx`** — поддержать вызов с ОДНИМ преднастроенным учеником (из pending-строки): проп `candidates` из одного элемента + `missedLessonId` из строки. Контракт тела не меняется. (Модалка уже принимает эти пропы — переиспользуем.)
- [ ] **Step 4: teacher `useExtraLesson.ts`** — `ExtraLessonDetail.status: 'pending' | 'makeup_scheduled' | 'makeup_done'`. Модалка проведения работает для `makeup_scheduled` (гарды на бэке).
- [ ] **Step 5: Typecheck** обоих фронтов: `cd frontend/admin-src && npx tsc --noEmit` → 0; `cd frontend/teacher-src && npx tsc --noEmit` → 0. (НЕ запускать `npm run build` — не коммитить dist.)
- [ ] **Step 6: Commit** `refactor(absences): admin queue UI + status vocabulary (Phase 1b Task 7)`.

---

## Task 8: Сверка + полный прогон

**Files:** Modify `apps/extra_lessons/tests/test_reconciliation_1a.py` (адаптировать статусы) или создать `test_reconciliation_1b.py`.

- [ ] **Step 1: Адаптировать сверку** — существующий `test_reconciliation_1a.py` использует `services.create_assignment` + `record(present=True)`. Под 1b: create_assignment теперь assign (пойдёт через `create_scheduled_direct`, т.к. фикстурный missed-урок pending не имеет), record → makeup_done. Числа денег ДОЛЖНЫ остаться те же (balance 8→7, attended 1, renewals 1.0, payroll 200, апрель). Обновить только статус-ожидания, если тест их проверяет; денежные литералы НЕ трогать. Добавить проверку: до assign по этому пропуску pending нет (фикстура не через record_lesson) — а после полного цикла статус makeup_done.
- [ ] **Step 2: Новый мини-тест жизненного цикла** (можно в том же файле): record обычного урока с present=false → появился pending; assign → makeup_scheduled; record доп.урока → makeup_done; delete_fact → pending; деньги в конце (после delete_fact) вернулись к базе (balance назад к 8). Проверяет, что откат чист.
- [ ] **Step 3: Полный прогон:**
Run: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/ apps/lessons/ apps/finances/ apps/renewals/ apps/changelog/ apps/scheduling/ apps/students/ apps/teacher_spa/ -q`
Ожидание: PASS кроме известных 2 предсуществующих `test_fifo_inputs` ([[project_finances_test_fifo_inputs_bug]]).
- [ ] **Step 4: Typecheck обоих фронтов** → 0 ошибок.
- [ ] **Step 5: Commit** `test(absences): pending-lifecycle reconciliation + full run (Phase 1b Task 8)`.

---

## Вне охвата Фазы 1b (→ 1c / 2)

- «Сжечь» (`burned`-урок через record_lesson, флет 200₽) — Фаза 1c.
- Переключение модели потребления (present=true по всем подтипам, исходный остаётся false; удаление `apply/revert_makeup_attendance`) — Фаза 1c.
- Блокировка карточек в `LessonEditor`, удаление burn-тоггла/assign-триггера из грида — Фаза 1c.
- Удаление `burned_at`, `burn_surcharge`, `_makeup_completion_dates` — Фаза 2.
