# Унификация пропусков — Фаза 1 (ядро) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Превратить доп.уроки и сгорание в единый пер-ученик механизм `AbsenceResolution` с очередью «ждёт решения», кнопками «Сжечь»/«Назначить доп.урок»/«Откат», блокировкой карточек и единым правилом потребления — сохраняя денежные числа бит-в-бит на каждом шаге.

**Architecture:** Эволюция на месте: `apps.extra_lessons.ExtraLessonAssignment`+`ExtraLessonParticipant` (групповая) перестраивается в **1:1 пер-ученик** `AbsenceResolution`; данные мигрируются. Затем авто-создание `pending`, действия через `apps.lessons.services.record_lesson`, единый раздел, блок карточек. Спека: `docs/superpowers/specs/2026-07-18-unify-absences-makeup-burn-design.md`. Уточнения 2026-07-18: **эволюция на месте + миграция сейчас**, **полная картина в Фазе 1**, **фронт входит в 1a, модель 1:1 насквозь (без адаптера/слотов)**.

**Tech Stack:** Django 5 + DRF (managed=True для доменных таблиц), pytest + pytest-django (реальная `journal_test`), React 19 + TanStack Query v5 (admin), React + @shared (teacher). Команды из `journal_django/`, интерпретатор `.venv/Scripts/python.exe`.

---

## Декомпозиция Фазы 1 на под-планы (порядок обязателен)

Фаза 1 слишком велика/деньги-критична для одного плана. Три самодостаточных
под-плана; каждый оставляет систему рабочей и с неизменными денежными числами.
Этот документ ДЕТАЛИЗИРУЕТ **1a**; 1b/1c получат свой проход writing-plans позже.

- **Фаза 1a — 1:1 пер-ученик `AbsenceResolution` + миграция, НАСКВОЗЬ (бэк+фронт), поведение денег сохранено.** Данный документ.
- **Фаза 1b — Авто-создание `pending` + переименование статусов + очередь + авто-очистка при уходе ученика.** Отдельный план.
- **Фаза 1c — Сгорание через раздел (`burned`-урок через `record_lesson`) + переключение модели потребления (present=true по всем подтипам, исходный остаётся false) + блок карточек + синхронизация продлений.** Отдельный план.
- **Фаза 2 (после 1)** — удаление мёртвой спец-механики + миграция исторических `burned_at` + решение про исключение `'burned'` из потребления. Отдельный план.

---

## Фаза 1a — детально

**Goal (1a):** Заменить групповую модель на 1:1 пер-ученик `AbsenceResolution`,
мигрировать данные, переписать бэк (repo/services/serializers/views) и оба фронта
(admin-список, teacher-модалка записи) на пер-ученик — сохранив денежные ТОТАЛЫ,
потребление и продления НЕИЗМЕННЫМИ.

### Ключевые решения 1a (фикс, без двусмысленности)

1. **Грануляция 1:1:** одна `AbsenceResolution` на (missed_lesson × student).
   `UNIQUE(missed_lesson, student)`. Admin `create` с multi-select → N независимых
   резолюций. Teacher `record` таргетит ОДНУ резолюцию → свой `Lesson`-факт + Payroll.
2. **`fact_lesson` — `ForeignKey` (не OneToOne), nullable, `SET_NULL`.** Историческая
   группа (один `Lesson` на N участников) → N резолюций на один `fact_lesson`. Для
   новых — 1:1 обеспечивает сервис.
3. **Статусы в 1a НЕ переименовываем** — `scheduled`/`done`/`cancelled` (как сейчас;
   `pending`/`makeup_*` — 1b). 1a = чистая смена грануляции без семантики.
4. **«Поведение сохранено» = деньги+потребление неизменны**, хотя строк больше
   (N фактов×200₽ вместо 1 факта 200₽×N; тотал тот же). Сверка — Task 8.

### Структура файлов (1a)

- `apps/extra_lessons/models.py` — `AbsenceResolution` заменяет старые 2 модели.
- `apps/extra_lessons/migrations/0002_*`, `0003_*` — создать таблицу; перелить+удалить старые.
- `apps/extra_lessons/repository.py`, `services.py`, `serializers.py`, `views.py`, `urls.py`, `teacher_urls.py` — на пер-ученик.
- `apps/finances/repository.py::_makeup_completion_dates` — читать `AbsenceResolution`.
- `apps/changelog/registry.py` — заменить трек-модель.
- `frontend/admin-src/.../useExtraLessons.ts`, `pages/extra-lessons/ExtraLessonsListPage.tsx`, `components/lessons/AssignExtraLessonModal.tsx`, `lib/shared-types.ts` — пер-ученик.
- `frontend/teacher-src/.../useExtraLesson.ts`, `components/lessons/ExtraLessonRecordModal.tsx`, `lib/types.ts` — пер-резолюция.
- Тесты: адаптировать `apps/extra_lessons/tests/*`; новые `test_extra_lessons_models.py`, `test_migration_1a.py`, `test_reconciliation_1a.py`.

---

## Task 1: Модель `AbsenceResolution` (рядом со старой)

**Files:** Modify `apps/extra_lessons/models.py`; Test `apps/extra_lessons/tests/test_extra_lessons_models.py` (new).

- [ ] **Step 1: Тест на UNIQUE(missed_lesson, student)** — create файл:

```python
"""Smoke новой пер-ученик модели AbsenceResolution."""
from __future__ import annotations
import pytest
from django.db import connection, IntegrityError, transaction
from apps.extra_lessons.models import AbsenceResolution, SCHEDULED

pytestmark = pytest.mark.django_db


def test_unique_missed_lesson_student(teacher_fixture, missed_lesson_fixture, student_fixture):
    AbsenceResolution.objects.create(
        missed_lesson_id=missed_lesson_fixture, student_id=student_fixture,
        assigned_teacher_id=teacher_fixture, status=SCHEDULED,
        scheduled_date='2026-04-05', scheduled_time='15:00', duration_minutes=45)
    try:
        with transaction.atomic(), pytest.raises(IntegrityError):
            AbsenceResolution.objects.create(
                missed_lesson_id=missed_lesson_fixture, student_id=student_fixture,
                assigned_teacher_id=teacher_fixture, status=SCHEDULED,
                scheduled_date='2026-04-06', scheduled_time='16:00', duration_minutes=45)
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id = %s', [missed_lesson_fixture])
```

- [ ] **Step 2: Запустить → ImportError** (`AbsenceResolution` нет).
Run: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/tests/test_extra_lessons_models.py -v`

- [ ] **Step 3: Добавить модель** в `apps/extra_lessons/models.py` (старые классы пока НЕ трогаем — удаление в Task 3):

```python
@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class AbsenceResolution(models.Model):
    """
    Пер-ученик (1:1) «пропуск, требующий решения» — заменяет групповую пару
    ExtraLessonAssignment+ExtraLessonParticipant. Одна строка на (пропущенный
    урок × ученик). Статусы в 1a прежние (scheduled/done/cancelled). См.
    docs/superpowers/specs/2026-07-18-unify-absences-makeup-burn-design.md.
    """
    id = models.AutoField(primary_key=True)
    missed_lesson = models.ForeignKey('lessons.Lesson', on_delete=models.CASCADE,
                                      related_name='absence_resolutions')
    student = models.ForeignKey('students.Student', on_delete=models.PROTECT,
                                related_name='absence_resolutions')
    assigned_teacher = models.ForeignKey('teachers.Teacher', on_delete=models.PROTECT,
                                         null=True, blank=True, related_name='absence_resolutions')
    scheduled_date = models.DateField(null=True, blank=True)
    scheduled_time = models.TimeField(null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, default=SCHEDULED)
    # FK (не OneToOne): историческая группа = один Lesson на N учеников → N резолюций
    # на один fact_lesson. Новые доп.уроки 1:1 обеспечивает сервис.
    fact_lesson = models.ForeignKey('lessons.Lesson', on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='absence_resolution_facts')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'absence_resolutions'
        indexes = [
            models.Index(fields=['status'], name='ar_status_idx'),
            models.Index(fields=['missed_lesson'], name='ar_missed_lesson_idx'),
            models.Index(fields=['assigned_teacher', 'scheduled_date'], name='ar_teacher_date_idx'),
            models.Index(fields=['student'], name='ar_student_idx'),
        ]
        constraints = [
            models.UniqueConstraint(fields=['missed_lesson', 'student'],
                                    name='absence_resolutions_missed_student_key'),
            models.CheckConstraint(name='absence_resolutions_status_check',
                                   condition=models.Q(status__in=STATUS_CHOICES)),
        ]
```

- [ ] **Step 4: makemigrations** только на создание таблицы:
`.venv/Scripts/python.exe manage.py makemigrations extra_lessons` (получится `0002_absenceresolution` + pghistory-таблицы). Переливку/удаление старых таблиц — отдельной миграцией в Task 2.

- [ ] **Step 5: migrate + тест** (dev-БД и `journal_test`; НЕ recreate_test_db.sh — рушит seed, см. [[feedback_shared_test_db_across_worktrees]]):
`.venv/Scripts/python.exe manage.py migrate extra_lessons` → `pytest ...test_extra_lessons_models.py -v` → PASS.

- [ ] **Step 6: Commit** `feat(absences): add per-student AbsenceResolution model alongside old`.

---

## Task 2: Миграция данных → пер-ученик, затем удаление старых таблиц

**Files:** Create `apps/extra_lessons/_migration_helpers.py`; Create `apps/extra_lessons/migrations/0003_migrate_and_drop_old.py`; Test `apps/extra_lessons/tests/test_migration_1a.py` (new).

Логику переливки кладём в отдельный модуль-хелпер (не в модуль-миграцию с ведущей
цифрой в имени — его не импортнуть в тест), тестируем напрямую.

- [ ] **Step 1: Тест переливки** — create `test_migration_1a.py`:

```python
"""Переливка групповых назначений в пер-ученик резолюции (1:1, общий fact_lesson через FK)."""
from __future__ import annotations
import pytest
from django.db import connection
from apps.extra_lessons._migration_helpers import migrate_assignments_to_resolutions

pytestmark = pytest.mark.django_db


def test_group_assignment_becomes_per_student(teacher_fixture, missed_lesson_fixture, student_fixture):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO students (full_name, enrollment_status) VALUES ('__mig_s2__','enrolled') RETURNING id")
        sid2 = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO extra_lesson_assignments (teacher_id, missed_lesson_id, scheduled_date, "
            "scheduled_time, duration_minutes, status, fact_lesson_id, created_at) "
            "VALUES (%s,%s,'2026-04-05','15:00',45,'done',%s, now()) RETURNING id",
            [teacher_fixture, missed_lesson_fixture, missed_lesson_fixture])
        aid = cur.fetchone()[0]
        for sid in (student_fixture, sid2):
            cur.execute("INSERT INTO extra_lesson_participants (assignment_id, student_id) VALUES (%s,%s)", [aid, sid])
    try:
        migrate_assignments_to_resolutions(connection)
        with connection.cursor() as cur:
            cur.execute("SELECT student_id, status, fact_lesson_id, assigned_teacher_id "
                        "FROM absence_resolutions WHERE missed_lesson_id = %s ORDER BY student_id", [missed_lesson_fixture])
            rows = cur.fetchall()
        assert {r[0] for r in rows} == {student_fixture, sid2}
        assert all(r[1] == 'done' and r[2] == missed_lesson_fixture and r[3] == teacher_fixture for r in rows)
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM absence_resolutions WHERE missed_lesson_id = %s', [missed_lesson_fixture])
            cur.execute('DELETE FROM extra_lesson_participants WHERE assignment_id = %s', [aid])
            cur.execute('DELETE FROM extra_lesson_assignments WHERE id = %s', [aid])
            cur.execute('DELETE FROM students WHERE id = %s', [sid2])
```

- [ ] **Step 2: Запустить → ImportError.**

- [ ] **Step 3: Хелпер + миграция.** Create `apps/extra_lessons/_migration_helpers.py`:

```python
"""Чистая переливка старых групповых назначений в пер-ученик AbsenceResolution."""
from __future__ import annotations


def migrate_assignments_to_resolutions(connection) -> None:
    with connection.cursor() as cur:
        cur.execute("""
            INSERT INTO absence_resolutions
                (missed_lesson_id, student_id, assigned_teacher_id, scheduled_date,
                 scheduled_time, duration_minutes, status, fact_lesson_id, created_at)
            SELECT a.missed_lesson_id, p.student_id, a.teacher_id, a.scheduled_date,
                   a.scheduled_time, a.duration_minutes, a.status, a.fact_lesson_id, a.created_at
            FROM extra_lesson_assignments a
            JOIN extra_lesson_participants p ON p.assignment_id = a.id
            ON CONFLICT (missed_lesson_id, student_id) DO NOTHING
        """)
```

Create `apps/extra_lessons/migrations/0003_migrate_and_drop_old.py`:

```python
from django.db import migrations
from apps.extra_lessons._migration_helpers import migrate_assignments_to_resolutions


def _forward(apps, schema_editor):
    migrate_assignments_to_resolutions(schema_editor.connection)


class Migration(migrations.Migration):
    dependencies = [('extra_lessons', '0002_absenceresolution')]
    operations = [
        migrations.RunPython(_forward, migrations.RunPython.noop),
        # Старые модели удаляются из models.py в Task 3; здесь — DDL, ТОЛЬКО после переливки.
        # pghistory-таблицы старых моделей тоже снести (см. как это делают миграции changelog).
        migrations.RunSQL("DROP TABLE IF EXISTS extra_lesson_participants CASCADE;", reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL("DROP TABLE IF EXISTS extra_lesson_assignments CASCADE;", reverse_sql=migrations.RunSQL.noop),
    ]
```

- [ ] **Step 4: Тест переливки → PASS.** (Миграцию НЕ применять к БД, пока Task 3 не убрал старые модели из кода — иначе Django увидит рассинхрон state/DB.)

- [ ] **Step 5: Commit** `feat(absences): migrate group assignments to per-student + drop old tables`.

---

## Task 3: Репозиторий на 1:1 пер-ученик

**Files:** Modify `apps/extra_lessons/repository.py`; Modify `apps/extra_lessons/models.py` (удалить старые классы); Test `apps/extra_lessons/tests/test_extra_lessons_repository.py`.

Переписать репозиторий целиком на `AbsenceResolution`. Публичные функции (per-student):

```python
"""ExtraLessonsRepository — единственное место ORM-доступа раздела (пер-ученик)."""
from __future__ import annotations
import datetime
from typing import Optional
from django.db import transaction
from django.db.models import F
from apps.extra_lessons.models import CANCELLED, DONE, SCHEDULED, AbsenceResolution
from apps.lessons.models import LessonAttendance


def create_resolutions(*, missed_lesson_id, assigned_teacher_id, student_ids,
                       scheduled_date, scheduled_time, duration_minutes) -> list[int]:
    """N независимых резолюций (по одной на ученика), status=scheduled. Возвращает их id."""
    objs = [AbsenceResolution(
        missed_lesson_id=missed_lesson_id, student_id=sid, assigned_teacher_id=assigned_teacher_id,
        scheduled_date=scheduled_date, scheduled_time=scheduled_time,
        duration_minutes=duration_minutes, status=SCHEDULED,
    ) for sid in student_ids]
    AbsenceResolution.objects.bulk_create(objs)
    return [o.id for o in objs]


def _full_values(qs):
    return qs.values(
        'id', 'missed_lesson_id', 'student_id', 'assigned_teacher_id', 'scheduled_date',
        'scheduled_time', 'duration_minutes', 'status', 'fact_lesson_id',
        student_name=F('student__full_name'),
        teacher_name=F('assigned_teacher__name'),
        missed_lesson_group_id=F('missed_lesson__group_id'),
        missed_lesson_group_name=F('missed_lesson__group__name'),
        missed_lesson_date=F('missed_lesson__lesson_date'))


def get_resolution_full(resolution_id) -> Optional[dict]:
    return _full_values(AbsenceResolution.objects.filter(id=resolution_id)).first()


def lock_for_record(resolution_id) -> Optional[dict]:
    """SELECT ... FOR UPDATE внутри atomic() — авторитетная проверка статуса перед записью."""
    return (AbsenceResolution.objects.select_for_update().filter(id=resolution_id)
            .values('id', 'status', 'assigned_teacher_id', 'missed_lesson_id', 'student_id',
                    'scheduled_date', 'duration_minutes',
                    missed_lesson_group_id=F('missed_lesson__group_id')).first())


def lock_for_delete(resolution_id) -> Optional[dict]:
    return (AbsenceResolution.objects.select_for_update().filter(id=resolution_id)
            .values('id', 'status', 'missed_lesson_id', 'student_id', 'fact_lesson_id').first())


def has_active_resolution(missed_lesson_id, student_id) -> bool:
    return (AbsenceResolution.objects.filter(missed_lesson_id=missed_lesson_id, student_id=student_id)
            .exclude(status=CANCELLED).exists())


def students_not_absent(missed_lesson_id, student_ids) -> list[int]:
    absent = set(LessonAttendance.objects.filter(
        lesson_id=missed_lesson_id, student_id__in=student_ids, present=False
    ).values_list('student_id', flat=True))
    return [sid for sid in student_ids if sid not in absent]


def cancel(resolution_id) -> None:
    with transaction.atomic():
        obj = AbsenceResolution.objects.select_for_update().filter(id=resolution_id).first()
        if obj is None:
            return
        if obj.status != SCHEDULED:
            raise ValueError('Отменить можно только ещё не проведённый доп.урок.')
        obj.status = CANCELLED
        obj.save(update_fields=['status'])


def mark_done(resolution_id, *, fact_lesson_id) -> None:
    AbsenceResolution.objects.filter(id=resolution_id).update(status=DONE, fact_lesson_id=fact_lesson_id)


def reset_to_scheduled(resolution_id) -> None:
    AbsenceResolution.objects.filter(id=resolution_id).update(status=SCHEDULED, fact_lesson_id=None)


def list_resolutions(page=1, page_size=50, sort_by='scheduled_date', sort_dir='desc', filters=None) -> dict:
    filters = filters or {}
    sortable = {'scheduled_date': 'scheduled_date', 'status': 'status',
                'teacher_name': 'assigned_teacher__name', 'student_name': 'student__full_name'}
    order = ('' if sort_dir == 'asc' else '-') + sortable.get(sort_by, 'scheduled_date')
    qs = AbsenceResolution.objects.all()
    if filters.get('status'):
        qs = qs.filter(status=filters['status'])
    if filters.get('teacher_id'):
        qs = qs.filter(assigned_teacher_id=int(filters['teacher_id']))
    total = qs.count()
    offset = max(0, (page - 1) * page_size)
    rows = list(_full_values(qs.order_by(order, '-id')[offset:offset + page_size]))
    return {'rows': rows, 'total': total, 'page': page, 'page_size': page_size}
```

- [ ] **TDD:** адаптировать существующий `test_extra_lessons_repository.py` под новые имена/грануляцию (create_resolutions вместо create_assignment; get_resolution_full; has_active_resolution; cancel/mark_done/reset per resolution). Сохранить СМЫСЛ проверок (create/cancel/done-roundtrip/has_active true/false/after-cancel). Прогонять пошагово: адаптировал тест → упал → реализовал → зелёный.
- [ ] **Финал:** удалить `ExtraLessonAssignment`/`ExtraLessonParticipant` из `models.py`; применить миграции `0002`+`0003` к dev-БД и `journal_test`; `pytest apps/extra_lessons/tests/test_extra_lessons_repository.py -v` → PASS. Commit `refactor(absences): per-student repository, drop group models`.

---

## Task 4: Сервисы на 1:1 пер-ученик + finances._makeup_completion_dates

**Files:** Modify `apps/extra_lessons/services.py`; Modify `apps/finances/repository.py::_makeup_completion_dates`; Test `apps/extra_lessons/tests/test_extra_lessons_services.py`.

Сервис сохраняет исключения и деньги. `record` таргетит ОДНУ резолюцию, создаёт СВОЙ
факт (200₽ если ученик пришёл). Ключевые тела:

```python
def create_assignment(data: dict, request) -> dict:
    """create с multi-select → N резолюций. Валидация: урок существует; каждый ученик
    реально present=false на нём (StudentNotAbsent); нет активной резолюции за этот
    пропуск (DuplicateAssignment); balance>0 (UnpaidAttendanceBlocked)."""
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
    ids = repository.create_resolutions(
        missed_lesson_id=missed_lesson_id, assigned_teacher_id=data['teacher_id'],
        student_ids=student_ids, scheduled_date=_to_date(data['scheduled_date']),
        scheduled_time=_to_time(data['scheduled_time']), duration_minutes=data['duration_minutes'])
    log_event('extra_lesson_create', actor_email=_actor(request), target_id=ids[0],
              meta={'missed_lesson_id': missed_lesson_id, 'student_ids': student_ids,
                    'resolution_ids': ids}, request=request)
    return {'created': len(ids), 'resolution_ids': ids}


def record(resolution_id, *, teacher_id, present, record_url, submitted_by_token, submit_date, request):
    """Провести доп.урок ОДНОГО ученика. present=пришёл ли он. None→404, NotTeachers→403, ValueError→409, Unpaid→400."""
    full = repository.get_resolution_full(resolution_id)
    if full is None:
        return None
    if full['assigned_teacher_id'] != teacher_id:
        raise NotTeachersAssignment('Это назначение принадлежит другому преподавателю.')
    if full['status'] != SCHEDULED:
        raise ValueError('Доп.урок уже проведён или отменён.')
    if present:
        lessons_repository.assert_students_paid([full['student_id']])
    present_count = 1 if present else 0
    payment = calculate_extra_lesson_payment(present_count)
    penalty = calculate_penalty(full['scheduled_date'].isoformat(), submit_date, present_count)
    with transaction.atomic():
        locked = repository.lock_for_record(resolution_id)
        if locked is None:
            return None
        if locked['assigned_teacher_id'] != teacher_id:
            raise NotTeachersAssignment('Это назначение принадлежит другому преподавателю.')
        if locked['status'] != SCHEDULED:
            raise ValueError('Доп.урок уже проведён или отменён.')
        lesson_id = lessons_repository.insert_lesson({
            'lesson_date': locked['scheduled_date'].isoformat(), 'teacher_id': teacher_id,
            'group_id': locked['missed_lesson_group_id'], 'original_teacher_id': None,
            'lesson_number': Lesson.objects.get(id=locked['missed_lesson_id']).lesson_number,
            'lesson_duration_minutes': locked['duration_minutes'], 'lesson_type': 'extra',
            'record_url': record_url, 'submitted_by_token': submitted_by_token})
        lessons_repository.insert_attendance(lesson_id, [{'student_id': locked['student_id'], 'present': present}])
        lessons_repository.insert_payroll({'lesson_id': lesson_id, 'teacher_id': teacher_id,
            'total_students': 1, 'present_count': present_count, 'payment': payment, 'penalty': penalty})
        if present:
            lessons_repository.apply_makeup_attendance(locked['missed_lesson_id'], locked['student_id'])
        repository.mark_done(resolution_id, fact_lesson_id=lesson_id)
    log_event('extra_lesson_record', actor_email=_actor(request), target_id=resolution_id,
              meta={'lesson_id': lesson_id, 'payment': payment, 'penalty': penalty}, request=request)
    return {'lesson_id': lesson_id, 'payment': payment, 'penalty': penalty}
```

`cancel_assignment(resolution_id, request)`, `get_assignment_for_teacher(resolution_id, teacher_id)`,
`delete_fact(resolution_id, request)` — по образцу текущих, но per-resolution и через
`repository.lock_for_delete` (в `delete_fact` — `revert_makeup_attendance` если факт
был present=true, затем удалить Payroll+Lesson, `reset_to_scheduled`).

`apps/finances/repository.py::_makeup_completion_dates` — переписать на новую модель:

```python
def _makeup_completion_dates(student_ids=None):
    from apps.extra_lessons.models import AbsenceResolution
    qs = AbsenceResolution.objects.filter(status='done')
    if student_ids is not None:
        qs = qs.filter(student_id__in=list(student_ids))
    rows = qs.values('student_id', 'missed_lesson_id', completion_date=F('fact_lesson__lesson_date'))
    return {(r['missed_lesson_id'], r['student_id']): r['completion_date']
            for r in rows if r['completion_date'] is not None}
```

- [ ] **TDD:** адаптировать `test_extra_lessons_services.py` (happy/duplicate/not-absent/unpaid/record/
  delete/second-call-race) под per-resolution `record(resolution_id, present=True)`; убедиться падает → реализовать → зелёный. Прогнать `apps/finances/` (не сломан ли `_makeup_completion_dates`). Commit.

---

## Task 5: Сериализаторы/вьюхи/урлы + changelog (per-resolution)

**Files:** Modify `apps/extra_lessons/serializers.py`, `views.py`, `urls.py`, `teacher_urls.py`, `apps/changelog/registry.py`; Test `apps/extra_lessons/tests/test_extra_lessons_api.py`.

- [ ] `ExtraLessonRecordSerializer` → `{present: bool, record_url?}` (вместо `attendance:[...]`).
  `ExtraLessonCreateSerializer` — без изменений (принимает `student_ids`).
- [ ] Вьюхи: teacher `record` берёт `v['present']`; admin list зовёт `services.list_assignments`
  (→ `repository.list_resolutions`, per-student rows). Detail/cancel/delete — по `resolution_id`.
  Коды/сообщения (400/403/404/409) — прежние.
- [ ] Урлы `:id` теперь = `resolution_id` (пути не меняются).
- [ ] `changelog/registry.py`: заменить старые 2 модели на `AbsenceResolution`
  (тест `test_registry_covers_all_tracked_models` упадёт, если забыть).
- [ ] Адаптировать `test_extra_lessons_api.py` (RBAC/list-contract/detail/cancel/delete/record/scope)
  под per-resolution (record body `{present: true}`; list rows содержат `student_name`, не `participants`). Прогнать `apps/extra_lessons/ apps/changelog/` → PASS. Commit.

---

## Task 6: Admin-фронт на пер-ученик строки

**Files:** Modify `frontend/admin-src/src/lib/shared-types.ts`, `hooks/useExtraLessons.ts`, `pages/extra-lessons/ExtraLessonsListPage.tsx`, `components/lessons/AssignExtraLessonModal.tsx`.

- [ ] `shared-types.ts`: заменить `ExtraLessonAssignment` (с `participants`) на
  `AbsenceResolution` (плоский: `id, student_id, student_name, missed_lesson_group_name,
  missed_lesson_date, teacher_name, scheduled_date, status, fact_lesson_id`).
- [ ] `useExtraLessons.ts`: типы `Paginated<AbsenceResolution>`; `create` возвращает
  `{created, resolution_ids}` (мутация только инвалидирует — тип ослабить). `cancel(id)`/
  `remove(id)` — по `resolution_id`.
- [ ] `ExtraLessonsListPage.tsx`: колонки → Дата / Группа (пропуск) / Ученик
  (`student_name`) / Преподаватель / Статус / действия. Убрать колонку `participants`.
  Действия (cancel scheduled / delete done с подтверждением) — по строке (resolution_id).
- [ ] `AssignExtraLessonModal.tsx`: без изменений контракта (multi-select учеников →
  `student_ids`), но onSuccess-текст «Доп.уроки назначены» (мн. ч.). `create` теперь
  возвращает `{created}` — тост может показать число.
- [ ] `npx tsc --noEmit` в `admin-src/` → 0 новых ошибок. Ручная проверка списка. Commit.

---

## Task 7: Teacher-фронт на пер-резолюцию

**Files:** Modify `frontend/teacher-src/src/lib/types.ts`, `hooks/useExtraLesson.ts`, `components/lessons/ExtraLessonRecordModal.tsx`, `pages/calendar/OccurrenceMenu.tsx` (если рендерит участников).

- [ ] `types.ts`: тип детали доп.урока → плоский per-resolution (`student_name` вместо `participants[]`).
- [ ] `useExtraLesson.ts`: `record` шлёт `{present: boolean, record_url?}` для одной резолюции.
- [ ] `ExtraLessonRecordModal.tsx`: показывает ОДНОГО ученика (`data.student_name`) с одним
  тумблером «Пришёл/Не пришёл» вместо списка участников; сабмит `{present}`.
- [ ] `npx tsc --noEmit` в `teacher-src/` → 0 новых ошибок. Ручная проверка записи. Commit.

---

## Task 8: Сверка «деньги/продления до == после» + полный прогон

**Files:** Test `apps/extra_lessons/tests/test_reconciliation_1a.py` (new).

- [ ] Тест-сверка: сценарий (ученик, оплата, пропуск, назначенный+проведённый доп.урок
  на новой модели). Проверить, что `finances.balance_for_student`,
  `finances.attended_units_total`, `renewals.engine._attended_total`, срез
  `finances.reports.collect_monthly_report` и SUM(payroll.payment) по преподавателю —
  дают ТЕ ЖЕ числа, что давал старый групповой путь на тех же входных данных
  (эталон — зафиксировать значениями из ручного расчёта в докстроке теста).
- [ ] Полный прогон: `.venv/Scripts/python.exe -m pytest apps/extra_lessons/ apps/lessons/ apps/finances/ apps/renewals/ apps/changelog/ -q`. PASS, кроме известных 2 предсуществующих падений в `test_fifo_inputs.py` ([[project_finances_test_fifo_inputs_bug]]).
- [ ] `npx tsc --noEmit` в обоих фронтах → 0 ошибок. Commit.

## Вне охвата Фазы 1a

- Авто-создание `pending`, переименование статусов, единый раздел-очередь, авто-очистка при уходе — Фаза 1b.
- Сгорание-как-`burned`-урок, переключение модели потребления, блок карточек, синхронизация продлений на сгорании — Фаза 1c.
- Удаление `apply/revert_makeup_attendance`, `burned_at`, `burn_surcharge`, `_makeup_completion_dates` — Фаза 2.
