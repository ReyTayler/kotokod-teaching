# Унификация пропусков — Фаза 0 (безопасные починки) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть две денежные дыры, найденные аудитом, БЕЗ изменения модели данных: защитить факты доп.урока (`lesson_type='extra'`) от общего CRUD `/api/admin/lessons`, и починить двойной учёт доп.урока в «Продлениях» через единый источник «отработано».

**Architecture:** Новое доменное исключение `SystemLessonProtected` в `apps.lessons.exceptions` бросается в сервис-слое `apps.lessons.services` (при попытке удалить/патчить/тоггла-посещаемости системного урока) и маппится во view в 409. Единый источник «отработано» — новая функция `apps.finances.repository.attended_units_total(student_id)` с тем же исключением `lesson_type='extra'`, что и баланс; движок продлений `apps.renewals.engine._attended_total` делегирует ей (сейчас он считает `present=true` без исключения → доп.урок задваивает прогресс).

**Tech Stack:** Django 5 + DRF, pytest + pytest-django (реальная БД `journal_test`, `managed=False`). Все команды `pytest` — из каталога `journal_django/`, интерпретатор `.venv/Scripts/python.exe`.

**Спека:** `docs/superpowers/specs/2026-07-18-unify-absences-makeup-burn-design.md` (Фаза 0).

**Замечание про `'burned'`:** подтип `lesson_type='burned'` появится только в Фазе 2, но мы уже сейчас включаем его в whitelist системных типов (`_SYSTEM_LESSON_TYPES`) — это безопасно (таких строк ещё нет) и избавляет от правки в Фазе 2.

---

## Task 1: Исключение `SystemLessonProtected` + гард на общий DELETE extra-урока

**Files:**
- Modify: `journal_django/apps/lessons/exceptions.py`
- Modify: `journal_django/apps/lessons/services.py:157-158` (`delete_lesson_full`)
- Modify: `journal_django/apps/lessons/views.py` (`LessonDetailView.delete`, импорт)
- Test: `journal_django/apps/lessons/tests/test_lessons_api.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `journal_django/apps/lessons/tests/test_lessons_api.py` (файл уже
импортирует `connection`, `_client`, `BASE_URL`):

```python
def _make_extra_lesson() -> tuple[int, int, int, int]:
    """teacher+direction+group + Lesson(lesson_type='extra'). → (lesson_id, group_id, teacher_id, direction_id)."""
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name) VALUES ('__les_extra_t__') RETURNING id")
        tid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO directions (name, is_individual, active) "
            "VALUES ('__les_extra_d__', false, true) RETURNING id")
        did = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active) "
            "VALUES ('__les_extra_g__', %s, %s, false, 60, true) RETURNING id", [did, tid])
        gid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s,%s,'2026-04-01',1,60,'extra','__les_extra__') RETURNING id", [gid, tid])
        lid = cur.fetchone()[0]
    return lid, gid, tid, did


def _cleanup_extra(lid: int, gid: int, tid: int, did: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lid])
        cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [lid])
        cur.execute('DELETE FROM lessons WHERE id = %s', [lid])
        cur.execute('DELETE FROM groups WHERE id = %s', [gid])
        cur.execute('DELETE FROM directions WHERE id = %s', [did])
        cur.execute('DELETE FROM teachers WHERE id = %s', [tid])


def test_delete_extra_lesson_blocked_409():
    """Факт доп.урока (lesson_type='extra') нельзя удалить через общий CRUD → 409, урок цел."""
    lid, gid, tid, did = _make_extra_lesson()
    try:
        resp = _client('admin').delete(f'{BASE_URL}/{lid}')
        assert resp.status_code == 409
        assert 'error' in resp.json()
        with connection.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM lessons WHERE id = %s', [lid])
            assert cur.fetchone()[0] == 1
    finally:
        _cleanup_extra(lid, gid, tid, did)
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_lessons_api.py -k test_delete_extra_lesson_blocked_409 -v`
Expected: FAIL — сейчас DELETE удаляет extra-урок (204), а не 409.

- [ ] **Step 3: Добавить исключение**

В `journal_django/apps/lessons/exceptions.py`, после класса `UnpaidAttendanceBlocked`:

```python


class SystemLessonProtected(Exception):
    """
    Попытка изменить/удалить системный урок (lesson_type='extra'/'burned') через
    общий CRUD /api/admin/lessons. Такие уроки — факты доп.урока/сгорания,
    ими владеет раздел «Доп.уроки» (apps.extra_lessons); менять/удалять их можно
    только откатом оттуда, не общим списком уроков.
    """

    def __init__(self, lesson_type: str) -> None:
        self.lesson_type = lesson_type
        label = 'сгоревший урок' if lesson_type == 'burned' else 'доп.урок'
        super().__init__(
            f'Это системный {label} — изменить или удалить его можно только '
            f'через раздел «Доп.уроки», не через общий список уроков.'
        )
```

- [ ] **Step 4: Добавить гард-хелпер и защитить `delete_lesson_full` в сервисе**

В `journal_django/apps/lessons/services.py` — добавить импорты вверху файла (рядом
с существующими `from apps.lessons import repository`):

```python
from apps.lessons.exceptions import SystemLessonProtected
from apps.lessons.models import Lesson
```

Там же, после импортов, добавить константу и хелпер:

```python
# Подтипы уроков, которыми владеет apps.extra_lessons (факты доп.урока/сгорания).
# Общий CRUD /api/admin/lessons их не трогает — только откат из раздела «Доп.уроки».
# 'burned' появится в Фазе 2; включён заранее (таких строк ещё нет — безвредно).
_SYSTEM_LESSON_TYPES = ('extra', 'burned')


def _assert_not_system_lesson(lesson_id: int) -> None:
    """Бросает SystemLessonProtected, если урок — системный (extra/burned).
    No-op для несуществующего урока (тип None) — тогда работает обычный путь 404."""
    lesson_type = (
        Lesson.objects.filter(id=lesson_id).values_list('lesson_type', flat=True).first()
    )
    if lesson_type in _SYSTEM_LESSON_TYPES:
        raise SystemLessonProtected(lesson_type)
```

Заменить `delete_lesson_full` (строки 157-158):

```python
def delete_lesson_full(lesson_id: int) -> bool:
    _assert_not_system_lesson(lesson_id)
    return repository.delete_lesson_full(lesson_id)
```

- [ ] **Step 5: Поймать исключение во view (`LessonDetailView.delete`)**

В `journal_django/apps/lessons/views.py` изменить импорт исключений (строка 32):

```python
from apps.lessons.exceptions import SystemLessonProtected, UnpaidAttendanceBlocked
```

Заменить метод `delete` в `LessonDetailView`:

```python
    def delete(self, request: Request, pk: int) -> Response:
        try:
            ok = services.delete_lesson_full(pk)
        except SystemLessonProtected as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(status=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 6: Запустить тесты, убедиться что проходят**

Run: `.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_lessons_api.py -v`
Expected: PASS (весь файл, включая новый тест и все существующие delete/patch-тесты).

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/lessons/exceptions.py journal_django/apps/lessons/services.py journal_django/apps/lessons/views.py journal_django/apps/lessons/tests/test_lessons_api.py
git commit -m "feat(lessons): block generic DELETE of extra lessons (system-owned)"
```

---

## Task 2: Гард на общий PATCH (мета + смена типа) и тоггл посещаемости extra-урока

**Files:**
- Modify: `journal_django/apps/lessons/services.py:153-154,161-162` (`update_lesson`, `update_attendance_cell`)
- Modify: `journal_django/apps/lessons/views.py` (`LessonDetailView.patch`, `AttendanceCellView.patch`)
- Test: `journal_django/apps/lessons/tests/test_lessons_api.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в `journal_django/apps/lessons/tests/test_lessons_api.py` (переиспользуют
`_make_extra_lesson`/`_cleanup_extra` из Task 1):

```python
def test_patch_extra_lesson_blocked_409():
    """PATCH мета факта доп.урока через общий CRUD → 409."""
    lid, gid, tid, did = _make_extra_lesson()
    try:
        resp = _client('admin').patch(f'{BASE_URL}/{lid}', {'record_url': 'https://x.test'}, format='json')
        assert resp.status_code == 409
        assert 'error' in resp.json()
    finally:
        _cleanup_extra(lid, gid, tid, did)


def test_patch_lesson_type_change_blocked_409():
    """Смену lesson_type у обычного урока через общий PATCH запрещаем (нельзя
    «превратить» regular в extra в обход раздела «Доп.уроки»)."""
    lid, gid, tid, did = _make_extra_lesson()
    # сделаем урок обычным, чтобы проверить именно блок смены типа (а не блок системного урока)
    with connection.cursor() as cur:
        cur.execute("UPDATE lessons SET lesson_type = 'regular' WHERE id = %s", [lid])
    try:
        resp = _client('admin').patch(f'{BASE_URL}/{lid}', {'lesson_type': 'extra'}, format='json')
        assert resp.status_code == 409
    finally:
        _cleanup_extra(lid, gid, tid, did)


def test_attendance_toggle_on_extra_lesson_blocked_409():
    """Тоггл ячейки посещаемости на факте доп.урока через общий CRUD → 409."""
    lid, gid, tid, did = _make_extra_lesson()
    with connection.cursor() as cur:
        cur.execute("INSERT INTO students (full_name, enrollment_status) "
                    "VALUES ('__les_extra_s__', 'enrolled') RETURNING id")
        sid = cur.fetchone()[0]
    try:
        resp = _client('admin').patch(f'{BASE_URL}/{lid}/attendance/{sid}', {'present': True}, format='json')
        assert resp.status_code == 409
    finally:
        with connection.cursor() as cur:
            cur.execute('DELETE FROM lesson_attendance WHERE student_id = %s', [sid])
            cur.execute('DELETE FROM students WHERE id = %s', [sid])
        _cleanup_extra(lid, gid, tid, did)
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_lessons_api.py -k "patch_extra_lesson or lesson_type_change or attendance_toggle_on_extra" -v`
Expected: FAIL — сейчас PATCH/тоггл на extra-уроке проходят (200), а не 409.

- [ ] **Step 3: Защитить `update_lesson` и `update_attendance_cell` в сервисе**

В `journal_django/apps/lessons/services.py` заменить `update_lesson` (строки 153-154):

```python
def update_lesson(lesson_id: int, fields: dict) -> Optional[dict]:
    lesson_type = (
        Lesson.objects.filter(id=lesson_id).values_list('lesson_type', flat=True).first()
    )
    if lesson_type is None:
        return None  # несуществующий урок → обычный 404 во view
    if lesson_type in _SYSTEM_LESSON_TYPES:
        raise SystemLessonProtected(lesson_type)
    if fields.get('lesson_type') is not None:
        raise SystemLessonProtected(fields['lesson_type'])
    return repository.update_lesson(lesson_id, fields)
```

Заменить `update_attendance_cell` (строки 161-162):

```python
def update_attendance_cell(lesson_id: int, student_id: int, present: bool) -> bool:
    _assert_not_system_lesson(lesson_id)
    return repository.update_attendance_cell(lesson_id, student_id, present)
```

- [ ] **Step 4: Поймать исключение во view (`patch` и `AttendanceCellView`)**

В `journal_django/apps/lessons/views.py` заменить метод `patch` в `LessonDetailView`:

```python
    def patch(self, request: Request, pk: int) -> Response:
        serializer = LessonUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            updated = services.update_lesson(pk, serializer.validated_data)
        except SystemLessonProtected as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        if updated is None:
            raise NotFound({'error': 'Not found'})
        return Response(updated)
```

Заменить метод `patch` в `AttendanceCellView`:

```python
    def patch(self, request: Request, lesson_id: int, student_id: int) -> Response:
        serializer = AttendanceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            ok = services.update_attendance_cell(
                lesson_id, student_id, serializer.validated_data['present']
            )
        except UnpaidAttendanceBlocked as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except SystemLessonProtected as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response({'ok': True})
```

- [ ] **Step 5: Запустить тесты, убедиться что проходят**

Run: `.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_lessons_api.py -v`
Expected: PASS (весь файл).

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/lessons/services.py journal_django/apps/lessons/views.py journal_django/apps/lessons/tests/test_lessons_api.py
git commit -m "feat(lessons): block generic PATCH and attendance toggle on extra lessons"
```

---

## Task 3: Единый источник «отработано» + починка двойного учёта в продлениях

**Files:**
- Modify: `journal_django/apps/finances/repository.py` (новая `attended_units_total`)
- Modify: `journal_django/apps/renewals/engine.py:54-69` (`_attended_total` делегирует)
- Test: `journal_django/apps/renewals/tests/test_lesson_progress.py`

- [ ] **Step 1: Написать падающий тест (регрессия двойного учёта)**

Добавить в `journal_django/apps/renewals/tests/test_lesson_progress.py` (файл уже
импортирует `connection`, `engine`, и содержит хелперы `_make_group_with_membership`
/ `_cleanup_group`):

```python
@pytest.mark.django_db
def test_attended_total_excludes_extra_lessons(make_student, make_direction, make_teacher, make_attendance):
    """
    Регрессия 2026-07-18: доп.урок (lesson_type='extra') НЕ должен задваивать
    прогресс сделки. _attended_total обязан считать его 0 (потребление идёт от
    исходного урока, extra исключён — как в финансах), значит при 1 обычном
    посещённом уроке + 1 extra итог = 1.0, а не 2.0.
    """
    sid, did, tid = make_student(), make_direction(), make_teacher()
    gid = _make_group_with_membership(did, tid, sid, name='__extra_dc_group__')
    try:
        make_attendance(sid, gid, tid, count=1)  # 1 обычный урок, present=true
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
                "lesson_duration_minutes, lesson_type, submitted_by_token) "
                "VALUES (%s,%s,'2026-06-05',1,60,'extra','__dc_test__') RETURNING id", [gid, tid])
            extra_lid = cur.fetchone()[0]
            cur.execute(
                'INSERT INTO lesson_attendance (lesson_id, student_id, present) '
                'VALUES (%s,%s,true)', [extra_lid, sid])
        try:
            assert engine._attended_total(sid) == 1.0
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [extra_lid])
                cur.execute('DELETE FROM lessons WHERE id = %s', [extra_lid])
    finally:
        _cleanup_group(gid, sid)
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `.venv/Scripts/python.exe -m pytest apps/renewals/tests/test_lesson_progress.py -k test_attended_total_excludes_extra_lessons -v`
Expected: FAIL — сейчас `_attended_total` считает и обычный, и extra → возвращает `2.0`, ассерт `== 1.0` падает.

- [ ] **Step 3: Добавить единый источник `attended_units_total` в финансы**

В `journal_django/apps/finances/repository.py`, сразу после функции
`balances_for_students` (она заканчивается на `return {sid: _js_number(v) for ...}`),
добавить:

```python
def attended_units_total(student_id: int) -> Decimal:
    """
    Суммарно «отработано» уроков учеником за всю историю (present=true), в тех же
    единицах (half-lesson 45мин=0.5) и с тем же исключением lesson_type='extra',
    что и потребление баланса (fifo_inputs/balances_for_students): компенсируемый
    пропуск уже учтён через ретроактивную отметку исходного урока, а сам extra —
    нет, иначе один пропуск считался бы дважды.

    ЕДИНЫЙ источник правды «отработано» — вызывается и балансом finances, и движком
    продлений (apps.renewals.engine._attended_total), чтобы «отработано» в отчёте и
    прогресс сделки в «Продлениях» никогда не разошлись (до этого продления считали
    present=true БЕЗ исключения extra → доп.урок задваивал прогресс).
    """
    row = (
        LessonAttendance.objects
        .filter(student_id=student_id, present=True)
        .exclude(lesson__lesson_type='extra')
        .aggregate(s=Coalesce(Sum(_attended_units_case()), _ZERO))
    )
    return row['s']
```

(`Decimal`, `LessonAttendance`, `Sum`, `Coalesce`, `_attended_units_case`, `_ZERO`
уже импортированы/определены в этом файле — используются в `balances_for_students`
выше; новых импортов не нужно.)

- [ ] **Step 4: Делегировать из движка продлений**

В `journal_django/apps/renewals/engine.py` заменить функцию `_attended_total`
(строки 54-69) целиком:

```python
def _attended_total(student_id: int) -> float:
    """
    Суммарно посещено уроков за ВСЮ историю ученика (half-lesson 45мин=0.5).
    Делегирует apps.finances.repository.attended_units_total — ЕДИНЫЙ источник
    «отработано», тот же, что и баланс/потребление finances (с исключением
    lesson_type='extra'). Раньше здесь был отдельный SQL БЕЗ исключения extra, из-за
    чего доп.урок задваивал прогресс сделки (регрессия 2026-07-18). Локальный импорт —
    во избежание циклического импорта renewals ↔ finances при загрузке модулей.
    """
    from apps.finances.repository import attended_units_total
    return float(attended_units_total(student_id))
```

После этой замены `connection` в `engine.py` больше нигде не используется (проверено:
единственное использование было на строке 61 внутри старого `_attended_total`).
Поэтому изменить импорт в шапке файла (строка 15) с

```python
from django.db import connection, transaction
```

на

```python
from django.db import transaction
```

- [ ] **Step 5: Запустить тест, убедиться что проходит**

Run: `.venv/Scripts/python.exe -m pytest apps/renewals/tests/test_lesson_progress.py -v`
Expected: PASS (весь файл, включая новый тест).

- [ ] **Step 6: Регрессия — прогнать финансы и продления целиком**

Run: `.venv/Scripts/python.exe -m pytest apps/finances/ apps/renewals/ -v`
Expected: PASS. ИСКЛЮЧЕНИЕ: `apps/renewals/tests/test_renewals_stage_sync.py::test_create_lesson_full_advances_renewal_stage` и `::test_update_attendance_cell_advances_renewal_stage` могут падать — это ПРЕДСУЩЕСТВУЮЩИЕ падения от несвязанного незакоммиченного WIP (проверено 2026-07-17, не относятся к этой правке). Если падают только эти два и с тем же сообщением (`assert 'lesson_1' == 'no_lesson_yet'`) — игнорировать. Любое ДРУГОЕ падение — разобрать.

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/finances/repository.py journal_django/apps/renewals/engine.py journal_django/apps/renewals/tests/test_lesson_progress.py
git commit -m "fix(renewals): count worked-off lessons via single finances source (no extra double-count)"
```

---

## Итоговая проверка (после всех задач)

- [ ] **Прогон затронутых наборов**

Run (из `journal_django/`):
`.venv/Scripts/python.exe -m pytest apps/lessons/ apps/finances/ apps/renewals/ apps/extra_lessons/ -q`
Expected: PASS, кроме двух предсуществующих падений в `test_renewals_stage_sync.py`
(см. Task 3, Step 6). Раздел `apps/extra_lessons/` включён, чтобы убедиться, что
внутренние откаты доп.урока (`delete_fact` — прямой ORM `Lesson.objects...delete()`,
в обход сервис-гарда) по-прежнему работают.

## Вне охвата Фазы 0 (будет в Фазах 1-2, отдельные планы)

- Сущность `AbsenceResolution`, авто-создание пропусков, единый раздел с
  «Сжечь»/«Доп.урок», блокировка карточек в `LessonEditor`.
- Перенос сгорания на `burned`-урок, схлопывание групповой модели, миграция данных.
- Удаление мёртвой спец-механики (`burned_at`, `burn_surcharge`,
  `_makeup_completion_dates`, `apply/revert_makeup_attendance`) — только после того,
  как модель переедет (иначе сломается текущее потребление).
- FK `missed_lesson` PROTECT→CASCADE и гард на удаление исходного урока с решёнными
  пропусками — в Фазе 1 (вместе с моделью).
