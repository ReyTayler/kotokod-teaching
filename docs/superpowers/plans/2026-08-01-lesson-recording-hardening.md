# Запись урока: закрытие дублей, обратная связь, инфраструктура — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать повторную отправку урока безопасной на ВСЕХ путях записи, дать преподавателю честную обратную связь о судьбе отправки и убрать инфраструктурные условия, в которых ответы теряются.

**Architecture:** Три независимо выкатываемые фазы. Фаза 1 — корректность данных: включить уже написанную защиту на главном экране, достроить недостающие ветки и ввести серверный ключ отправки (`submission_key`) с частичным уникальным индексом, который делает дубль невозможным по построению на всех путях, включая админский. Фаза 2 — клиентский контракт: не терять ответ и не врать о результате. Фаза 3 — инфраструктура: убрать самый дорогой запрос с критического пути и настроить кеширование/таймауты.

**Tech Stack:** Django 5.2 + DRF, PostgreSQL, React 19 + TanStack Query v5 + Vite, nginx + gunicorn (Ubuntu 22.04, без Docker).

---

## Замечание о разбиении

План покрывает три разные подсистемы. Они намеренно оформлены фазами в одном документе, потому что вытекают из одного инцидента и их приоритеты связаны, но **каждая фаза самостоятельна и выкатывается отдельно**:

- Фаза 1 (задачи 1–9) — корректность денег и данных. Выкатывать первой.
- Фаза 2 (задачи 10–12) — обратная связь. Без неё Фаза 1 работает, но человек продолжает нажимать повторно.
- Фаза 3 (задачи 13–15) — производительность. Без неё всё работает, но медленно.

Если исполнителей несколько, фазы можно вести параллельно: они не пересекаются по файлам, кроме `apps/teacher_spa/services.py` (Задачи 2/5 и 15) — тогда Задачу 15 делать последней.

---

## Карта файлов

**Фаза 1**

| Файл | Ответственность | Действие |
|---|---|---|
| `journal_django/frontend/teacher-src/src/pages/lessons/MyLessonsPage.tsx` | Передать в форму признак занятия; ветка доп.урока | Изменить |
| `journal_django/apps/scheduling/repository.py` | Резолв позиции курса по дате: различать «нет» и «все заняты» | Изменить |
| `journal_django/apps/lessons/exceptions.py` | Новое исключение «позиция исчезла» | Изменить |
| `journal_django/apps/lessons/models.py` | Поле `submission_key` + частичный уникальный индекс | Изменить |
| `journal_django/apps/lessons/migrations/0009_lesson_submission_key.py` | Миграция поля и индекса | Создать |
| `journal_django/apps/lessons/submission_key.py` | Чистое вычисление ключа отправки | Создать |
| `journal_django/apps/lessons/services.py` | Номер из залоченной позиции; ключ отправки; конфликт → доменное исключение | Изменить |
| `journal_django/apps/lessons/repository.py` | `insert_lesson` пишет `submission_key` | Изменить |
| `journal_django/apps/teacher_spa/services.py` | Устаревший id → резолв по дате; 409 при занятых позициях | Изменить |
| `journal_django/apps/lessons/views.py` | Конфликт записи → 409 на админском пути | Изменить |
| `journal_django/apps/lessons/tests/test_submission_key.py` | Юнит-тесты ключа | Создать |
| `journal_django/apps/teacher_spa/tests/test_duplicate_submit.py` | Дубли на всех путях + гонка | Создать |

**Фаза 2**

| Файл | Ответственность | Действие |
|---|---|---|
| `journal_django/frontend/admin-src/src/shared/calendar/Modal.tsx` | Запрет закрытия во время отправки | Изменить |
| `journal_django/frontend/admin-src/src/lib/api.ts` | Таймаут запроса + доменная ошибка таймаута | Изменить |
| `journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx` | Честный текст при таймауте; блокировка закрытия | Изменить |
| `journal_django/frontend/teacher-src/src/components/lessons/ExtraLessonRecordModal.tsx` | Спокойная обработка «уже записано» | Изменить |
| `journal_django/apps/extra_lessons/views.py` | Код конфликта в 409 | Изменить |
| `journal_django/frontend/teacher-src/src/hooks/useExtraLesson.ts` | Инвалидация кэша при конфликте | Изменить |

**Фаза 3**

| Файл | Ответственность | Действие |
|---|---|---|
| `deploy/nginx/snippets/journal-static.conf` | Кеширование бандлов | Изменить |
| `deploy/nginx/journal-kotokod.conf` | TLS-сессии, таймауты прокси | Изменить |
| `deploy/gunicorn.conf.py` | Воркеры под реальное железо | Изменить |
| `journal_django/config/settings/base.py` | Переиспользование соединений с БД | Изменить |
| `journal_django/apps/teacher_spa/repository.py` | Чтение одной группы вместо всей школы | Изменить |

---

# ФАЗА 1 — Корректность: дубли уроков

### Task 1: «Мои уроки» передаёт в форму конкретное занятие

Экран по умолчанию для отметки урока выбрасывает `Occurrence.id`, поэтому вся дневная рутина идёт мимо защиты, добавленной в коммите 2485444. Плюс карточка доп.урока открывает форму обычного урока и создаёт лишний платный урок.

**Files:**
- Modify: `journal_django/frontend/teacher-src/src/pages/lessons/MyLessonsPage.tsx`

- [ ] **Step 1: Заменить тип выбора и обработчик клика**

Найти в файле объявление `type Selection` и заменить целиком на:

```tsx
type Selection =
  | { kind: 'form'; occ: Occurrence; data: GroupData }
  | { kind: 'extra'; assignmentId: number }
  | { kind: 'popup'; lesson: Occurrence };
```

- [ ] **Step 2: Переписать `handleSelect` — ветка доп.урока и сохранение всего занятия**

Заменить существующий `handleSelect` целиком на:

```tsx
  const handleSelect = useCallback((occ: Occurrence) => {
    // Доп.урок — своя сущность и свой путь отметки (/api/extra-lessons/:id/record).
    // Без этой ветки форма обычного урока создала бы лишний курсовой урок с деньгами,
    // а назначение доп.урока осталось бы невыполненным.
    if (occ.extraLessonId != null) {
      setSelection({ kind: 'extra', assignmentId: occ.extraLessonId });
      return;
    }
    const groupData = teacherData.data?.data?.[occ.group];
    // Занятие кладём целиком: серверу нужен его id (позиция курса) и реальная дата,
    // иначе он вынужден угадывать позицию по дате — на группах с двумя занятиями
    // в день это уводит запись на незащищённый путь.
    if (groupData) setSelection({ kind: 'form', occ, data: groupData });
    else setSelection({ kind: 'popup', lesson: occ });
  }, [teacherData.data]);
```

- [ ] **Step 3: Передать занятие в форму**

Заменить блок рендера модалок в конце компонента на:

```tsx
      {selection?.kind === 'form' && (
        <LessonForm
          group={selection.occ.group}
          groupData={selection.data}
          initialDate={selection.occ.date}
          plannedLessonId={selection.occ.id}
          plannedLessonNumber={selection.occ.lessonNumber}
          isSubstitution={!!selection.occ.teacherOverride}
          onClose={() => setSelection(null)}
        />
      )}
      {selection?.kind === 'extra' && (
        <ExtraLessonRecordModal
          assignmentId={selection.assignmentId}
          onClose={() => setSelection(null)}
        />
      )}
      {selection?.kind === 'popup' && (
        <LessonPopup lesson={selection.lesson} onClose={() => setSelection(null)} />
      )}
```

- [ ] **Step 4: Добавить импорт модалки доп.урока**

В блок импортов добавить:

```tsx
import { ExtraLessonRecordModal } from '../../components/lessons/ExtraLessonRecordModal';
```

- [ ] **Step 5: Проверить типы**

Run: `cd journal_django/frontend/teacher-src && npm run typecheck`
Expected: без ошибок. Если TypeScript ругается на импорт `ExtraLessonRecordModal` — открыть `src/components/lessons/ExtraLessonRecordModal.tsx` и посмотреть, экспорт именованный (`export function`) или дефолтный (`export default`), и поправить импорт под факт.

- [ ] **Step 6: Коммит**

```bash
git add journal_django/frontend/teacher-src/src/pages/lessons/MyLessonsPage.tsx
git commit -m "fix(teacher): «Мои уроки» называют серверу конкретное занятие

Экран по умолчанию для отметки урока выбрасывал Occurrence.id, поэтому
дневная рутина шла мимо захвата позиции курса, добавленного в 2485444:
сервер угадывал позицию по дате, а на группах с двумя занятиями в день
уходил на незащищённый путь.

Карточка доп.урока здесь открывала форму обычного урока — вместо отметки
доп.урока создавался лишний курсовой урок с зарплатой, а назначение
оставалось невыполненным. Теперь ветка как в календаре."
```

---

### Task 2: «Все позиции дня заняты» — это отказ, а не тихий откат

`find_course_position_by_date` схлопывает в `None` два разных случая: «позиций на дату нет» (законный фолбэк) и «все позиции заняты» (повторная отправка). Второй обязан давать 409.

**Files:**
- Modify: `journal_django/apps/scheduling/repository.py`
- Test: `journal_django/apps/teacher_spa/tests/test_duplicate_submit.py` (создаётся здесь)

- [ ] **Step 1: Написать падающий тест**

Создать `journal_django/apps/teacher_spa/tests/test_duplicate_submit.py`:

```python
"""
Повторная отправка урока не должна создавать второй платный урок ни на одном
из путей записи. Инцидент ПГ215 (31.07.2026): три отправки одного занятия с
интервалом 10 и 15 секунд дали три урока, три начисления зарплаты и три
списания с баланса учеников.
"""
from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db


def _positions_on(group_id: int, date: str) -> list[dict]:
    from apps.scheduling.repository import find_course_position_by_date
    return find_course_position_by_date(group_id, date)


def test_all_positions_taken_returns_position_not_none(group_with_two_slots):
    """
    Мультислот, обе позиции дня заняты фактами. Резолвер обязан вернуть позицию
    (вызывающий по ней отдаст 409), а не None — None увёл бы запись на расчёт
    номера из прогресса, то есть ровно в механику ПГ215.
    """
    group_id, date, positions = group_with_two_slots
    with connection.cursor() as cur:
        for pos_id in positions:
            cur.execute(
                'UPDATE planned_lessons SET fact_lesson_id = %s, status = %s '
                'WHERE id = %s',
                [_any_lesson_id(), 'done', pos_id],
            )

    from apps.scheduling.repository import find_course_position_by_date
    resolved = find_course_position_by_date(group_id, date)

    assert resolved is not None
    assert resolved['fact_lesson_id'] is not None


def _any_lesson_id() -> int:
    with connection.cursor() as cur:
        cur.execute('SELECT id FROM lessons ORDER BY id DESC LIMIT 1')
        row = cur.fetchone()
    if not row:
        pytest.skip('В БД нет ни одного урока для привязки факта')
    return row[0]
```

Фикстуру `group_with_two_slots` добавить в `journal_django/apps/teacher_spa/tests/conftest.py`:

```python
@pytest.fixture
def group_with_two_slots(group_fixture):
    """
    Группа с ДВУМЯ курсовыми позициями на одну дату (мультислот, «два занятия
    подряд»). Возвращает (group_id, date, [position_id, position_id]).
    """
    date = '2026-08-16'
    ids = []
    with connection.cursor() as cur:
        # scheduled_time — NOT NULL без умолчания в схеме, пропустить нельзя.
        for seq, number, at in ((31, 31, '14:00'), (32, 32, '15:30')):
            cur.execute(
                """
                INSERT INTO planned_lessons
                    (group_id, seq, lesson_number, scheduled_date, scheduled_time,
                     status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'pending', NOW(), NOW())
                RETURNING id
                """,
                [group_fixture, seq, number, date, at],
            )
            ids.append(cur.fetchone()[0])
    yield group_fixture, date, ids
    with connection.cursor() as cur:
        cur.execute('DELETE FROM planned_lessons WHERE id = ANY(%s)', [ids])
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_duplicate_submit.py -v`
Expected: FAIL — `assert resolved is not None` не проходит, потому что текущая реализация при нуле свободных позиций возвращает `None`.

Если тест падает на фикстуре с ошибкой про колонку `planned_lessons` — открыть `apps/scheduling/models.py`, свериться с реальным набором колонок и поправить INSERT в фикстуре.

- [ ] **Step 3: Починить резолвер**

В `journal_django/apps/scheduling/repository.py` найти конец функции `find_course_position_by_date` и заменить последние три строки (`if len(rows) == 1: ... return free[0] if len(free) == 1 else None`) на:

```python
    if len(rows) == 1:
        return rows[0]
    if not rows:
        return None
    free = [r for r in rows if r['fact_lesson_id'] is None]
    if len(free) == 1:
        return free[0]
    if not free:
        # Все позиции дня заняты — это повторная отправка, а не «плана нет».
        # Возвращаем занятую позицию, чтобы вызывающий отдал 409. Вернуть None
        # здесь означало бы уйти на расчёт номера из прогресса учеников —
        # ровно та механика, что дала три урока в инциденте ПГ215.
        return rows[-1]
    # 2+ свободных позиций в один день различимы только явным plannedLessonId.
    return None
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_duplicate_submit.py -v`
Expected: PASS

- [ ] **Step 5: Прогнать соседние тесты на регресс**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/scheduling apps/teacher_spa -q`
Expected: без падений.

- [ ] **Step 6: Коммит**

```bash
git add journal_django/apps/scheduling/repository.py journal_django/apps/teacher_spa/tests/
git commit -m "fix(scheduling): занятые позиции дня — отказ, а не откат к старому расчёту

find_course_position_by_date схлопывала в None два разных случая: «позиций
на эту дату нет» и «все позиции уже заняты фактами». Второй — это повторная
отправка, и она уходила на расчёт номера из прогресса учеников, то есть на
незащищённый путь. Теперь занятая позиция возвращается, и вызывающий отдаёт
409 «урок уже записан»."
```

---

### Task 3: Номер урока брать из залоченной позиции

Докстринг `record_lesson` утверждает, что позиция — источник правды по номеру. Фактически в БД пишется аргумент, посчитанный вызывающим по незалоченному чтению. Между предпроверкой и локом номер позиции мог измениться (перенумерация плана при отмене занятия).

**Files:**
- Modify: `journal_django/apps/lessons/services.py:187-197`

- [ ] **Step 1: Написать падающий тест**

Добавить в `journal_django/apps/teacher_spa/tests/test_duplicate_submit.py`:

```python
def test_lesson_number_comes_from_locked_position(group_with_two_slots):
    """
    Номер пишется из позиции, захваченной под блокировкой, а не из аргумента,
    посчитанного до открытия транзакции. Иначе перенумерация плана между
    предпроверкой и локом разводит номер факта и номер позиции.
    """
    from apps.lessons.services import record_lesson

    group_id, date, positions = group_with_two_slots
    with connection.cursor() as cur:
        cur.execute(
            'UPDATE planned_lessons SET lesson_number = 99 WHERE id = %s',
            [positions[0]],
        )
        cur.execute('SELECT id FROM teachers LIMIT 1')
        teacher_id = cur.fetchone()[0]

    result = record_lesson(
        group_id=group_id,
        teacher_id=teacher_id,
        original_teacher_id=None,
        lesson_date=date,
        lesson_number=31,          # устаревший аргумент
        lesson_duration_minutes=60,
        lesson_type='regular',
        record_url=None,
        submitted_by_token='test:number',
        submit_date=date,
        attendance=[],
        planned_lesson_id=positions[0],
    )

    with connection.cursor() as cur:
        cur.execute('SELECT lesson_number FROM lessons WHERE id = %s', [result['lesson_id']])
        written = cur.fetchone()[0]
    assert int(written) == 99, 'номер должен быть взят из позиции, а не из аргумента'
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_duplicate_submit.py::test_lesson_number_comes_from_locked_position -v`
Expected: FAIL — записан 31 вместо 99.

Если `record_lesson` вернёт словарь без ключа `lesson_id` — посмотреть его фактический контракт в `apps/lessons/services.py` (конец функции) и поправить обращение в тесте.

- [ ] **Step 3: Взять номер из позиции**

В `journal_django/apps/lessons/services.py` сразу после блока проверки `position['fact_lesson_id']` (перед `lesson_id = repository.insert_lesson({`) вставить:

```python
        # Номер — из позиции, захваченной ПОД БЛОКИРОВКОЙ, а не из аргумента:
        # аргумент посчитан вызывающим до транзакции по незалоченному чтению, и
        # между этими моментами план могли перенумеровать (отмена другого
        # занятия группы вызывает _renumber_persist). Разъехавшиеся номер факта
        # и номер позиции ломают последующий матчинг link_facts/relink_fact.
        if position is not None:
            lesson_number = position['lesson_number']
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_duplicate_submit.py -v`
Expected: PASS

- [ ] **Step 5: Поправить докстринг, который теперь стал правдой**

В докстринге `record_lesson` строка «lesson_number берётся ИЗ ПОЗИЦИИ, а не из переданного аргумента» уже есть — убедиться, что она на месте, и дописать под ней:

```
        (номер читается из позиции ПОСЛЕ select_for_update — см. тело функции);
```

- [ ] **Step 6: Прогнать полный pytest**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest -q`
Expected: без падений. Прогонять ЦЕЛИКОМ, не по приложениям: часть приложений использует общую тестовую БД `journal_test`, часть — свежую `test_journal_test`, и частичный прогон даёт ложную картину.

- [ ] **Step 7: Коммит**

```bash
git add journal_django/apps/lessons/services.py journal_django/apps/teacher_spa/tests/test_duplicate_submit.py
git commit -m "fix(lessons): номер урока из позиции, захваченной под блокировкой

Докстринг обещал, что источник правды по номеру — позиция курса, но в БД
уходил аргумент, посчитанный до открытия транзакции по незалоченному чтению.
Если между предпроверкой и локом план перенумеровали (отмена другого занятия
группы), факт садился на позицию с одним номером, а в БД писался другой."
```

---

### Task 4: Исчезнувшая позиция — явная ошибка, не тихий фолбэк

Если между предпроверкой и локом позицию отменили или удалили, `lock_course_position` вернёт `None`, и код молча продолжит запись по старому расчёту — то есть провалится в незащищённый режим.

**Files:**
- Modify: `journal_django/apps/lessons/exceptions.py`
- Modify: `journal_django/apps/lessons/services.py:178-186`
- Modify: `journal_django/apps/teacher_spa/views.py`

- [ ] **Step 1: Добавить доменное исключение**

В конец `journal_django/apps/lessons/exceptions.py`:

```python
class CoursePositionVanished(Exception):
    """
    Позиция курса, названная клиентом, исчезла между предварительной проверкой
    и захватом под блокировкой: занятие отменили, план пересобрали или изменили
    его длину.

    Продолжать запись нельзя: без позиции ядро уходит на расчёт номера из
    прогресса учеников — путь, на котором повторная отправка создаёт дубль
    (инцидент ПГ215). Клиенту говорим обновить календарь.
    """

    def __init__(self) -> None:
        super().__init__(
            'Это занятие изменилось, пока вы заполняли форму — обновите '
            'страницу и отметьте его заново.'
        )
```

- [ ] **Step 2: Написать падающий тест**

Добавить в `journal_django/apps/teacher_spa/tests/test_duplicate_submit.py`:

```python
def test_vanished_position_raises_instead_of_silent_fallback(group_with_two_slots):
    """
    Позицию отменили между предпроверкой и локом → явная ошибка. Молчаливое
    продолжение записи означало бы переход на незащищённый путь.
    """
    from apps.lessons.exceptions import CoursePositionVanished
    from apps.lessons.services import record_lesson

    group_id, date, positions = group_with_two_slots
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE planned_lessons SET status = 'cancelled' WHERE id = %s",
            [positions[0]],
        )
        cur.execute('SELECT id FROM teachers LIMIT 1')
        teacher_id = cur.fetchone()[0]

    with pytest.raises(CoursePositionVanished):
        record_lesson(
            group_id=group_id,
            teacher_id=teacher_id,
            original_teacher_id=None,
            lesson_date=date,
            lesson_number=31,
            lesson_duration_minutes=60,
            lesson_type='regular',
            record_url=None,
            submitted_by_token='test:vanished',
            submit_date=date,
            attendance=[],
            planned_lesson_id=positions[0],
        )
```

- [ ] **Step 3: Запустить — убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_duplicate_submit.py::test_vanished_position_raises_instead_of_silent_fallback -v`
Expected: FAIL — исключение не поднято, урок записан.

- [ ] **Step 4: Поднимать исключение**

В `journal_django/apps/lessons/services.py` заменить блок захвата позиции на:

```python
        position = None
        if planned_lesson_id is not None:
            position = lock_course_position(planned_lesson_id, group_id)
            if position is None:
                # Позицию отменили/удалили между предпроверкой и локом. Молча
                # продолжать нельзя: без позиции ядро уходит на расчёт номера из
                # прогресса — незащищённый путь, на котором повтор даёт дубль.
                raise CoursePositionVanished()
        if position is not None and position['fact_lesson_id'] is not None:
            raise LessonAlreadyRecorded(
                position['lesson_number'], position['scheduled_date'],
            )
```

Добавить `CoursePositionVanished` в импорт исключений в начале файла.

- [ ] **Step 5: Отдать 409 во вьюхе преподавателя**

В `journal_django/apps/teacher_spa/views.py` расширить обработку в `SubmitLessonView.post`:

```python
        try:
            result = services.submit_lesson(request.user.id, serializer.validated_data)
        except LessonAlreadyRecorded as e:
            return Response(
                {'error': str(e), 'code': LESSON_ALREADY_RECORDED},
                status=status.HTTP_409_CONFLICT,
            )
        except CoursePositionVanished as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
```

Добавить `CoursePositionVanished` в импорт из `apps.lessons.exceptions`.

- [ ] **Step 6: Запустить тесты**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa apps/lessons -q`
Expected: без падений.

- [ ] **Step 7: Коммит**

```bash
git add journal_django/apps/lessons/exceptions.py journal_django/apps/lessons/services.py journal_django/apps/teacher_spa/views.py journal_django/apps/teacher_spa/tests/test_duplicate_submit.py
git commit -m "fix(lessons): исчезнувшая позиция курса — явный отказ

lock_course_position могла вернуть None (занятие отменили между предпроверкой
и локом), и запись молча продолжалась по старому расчёту номера — то есть
проваливалась в незащищённый режим. Теперь 409 с просьбой обновить страницу."
```

---

### Task 5: Устаревший `plannedLessonId` с чужой датой не должен закрывать не то занятие

`get_course_position` проверяет принадлежность группе, но не сверяет дату позиции с датой урока. Вкладка, открытая со вчера, после «переноса навсегда» пришлёт id позиции, которая теперь стоит на другой дате.

**Files:**
- Modify: `journal_django/apps/teacher_spa/services.py` (функция `_resolve_course_position`)

- [ ] **Step 1: Написать падающий тест**

Добавить в `journal_django/apps/teacher_spa/tests/test_duplicate_submit.py`:

```python
def test_stale_position_id_with_other_date_is_ignored(group_with_two_slots):
    """
    Клиент прислал id позиции, которая стоит на другой дате (календарь во
    вкладке устарел). Использовать её нельзя — закроется не то занятие.
    Резолвер обязан уйти на поиск по фактической дате.
    """
    from apps.teacher_spa.services import _resolve_course_position

    group_id, date, positions = group_with_two_slots
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE planned_lessons SET scheduled_date = '2026-09-20' WHERE id = %s",
            [positions[0]],
        )

    resolved = _resolve_course_position(group_id, date, positions[0])

    assert resolved is None or resolved['id'] != positions[0]
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_duplicate_submit.py::test_stale_position_id_with_other_date_is_ignored -v`
Expected: FAIL — вернулась именно устаревшая позиция.

- [ ] **Step 3: Сверять дату позиции**

В `journal_django/apps/teacher_spa/services.py` в `_resolve_course_position` заменить блок работы с явным id на:

```python
    if planned_lesson_id is not None:
        position = scheduling_repository.get_course_position(planned_lesson_id, group_id)
        # Дату сверяем обязательно: принадлежность группе get_course_position
        # проверяет, а дату — нет. Вкладка, открытая вчера, пришлёт id позиции,
        # которую с тех пор перенесли; по ней закрылось бы не то занятие, а
        # настоящая позиция дня осталась бы «не проведена».
        if position is not None and str(position['scheduled_date']) == str(date):
            return position
        # id не подошёл (чужая группа / не курсовая строка / отменена / уехал на
        # другую дату) — не падаем, ищем позицию по фактической дате.
    return scheduling_repository.find_course_position_by_date(group_id, date)
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_duplicate_submit.py -v`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add journal_django/apps/teacher_spa/services.py journal_django/apps/teacher_spa/tests/test_duplicate_submit.py
git commit -m "fix(teacher): устаревший plannedLessonId с чужой датой игнорируется

get_course_position проверяла принадлежность группе, но не дату. Календарь,
открытый вчера, присылал id позиции, которую с тех пор перенесли — урок
закрывал не то занятие, а настоящая позиция дня оставалась не проведённой."
```

---

### Task 6: Поле `submission_key` и частичный уникальный индекс

Ключ отправки делает дубль невозможным на уровне БД — на всех путях сразу, включая админский и группы без плана. Вычисляется СЕРВЕРОМ (клиенту не доверяем и контракт API не меняем).

**Files:**
- Create: `journal_django/apps/lessons/submission_key.py`
- Create: `journal_django/apps/lessons/tests/test_submission_key.py`
- Modify: `journal_django/apps/lessons/models.py`
- Create: `journal_django/apps/lessons/migrations/0009_lesson_submission_key.py`

- [ ] **Step 1: Написать тесты ключа**

Создать `journal_django/apps/lessons/tests/test_submission_key.py`:

```python
"""
Ключ отправки — суррогат «это то же самое занятие». Чистая функция, без БД.

Смысл: у повторной отправки одного и того же занятия ключ обязан совпасть,
у двух разных занятий — различаться. Именно на этом держится защита от дублей
на путях, где позиции курса нет (группы без плана, дата вне плана).
"""
from __future__ import annotations

from apps.lessons.submission_key import build_submission_key


def test_position_based_key_is_stable_across_retries():
    first = build_submission_key(group_id=7, lesson_date='2026-08-16', planned_lesson_id=31)
    second = build_submission_key(group_id=7, lesson_date='2026-08-16', planned_lesson_id=31)
    assert first == second


def test_different_positions_get_different_keys():
    """Мультислот: два занятия одного дня — две разные позиции, два ключа."""
    a = build_submission_key(group_id=7, lesson_date='2026-08-16', planned_lesson_id=31)
    b = build_submission_key(group_id=7, lesson_date='2026-08-16', planned_lesson_id=32)
    assert a != b


def test_without_position_key_falls_back_to_group_and_date():
    """Группа без плана: одно курсовое занятие на группу в день."""
    key = build_submission_key(group_id=7, lesson_date='2026-08-16', planned_lesson_id=None)
    assert key == 'slot:7:2026-08-16'


def test_without_position_key_is_stable_across_retries():
    first = build_submission_key(group_id=7, lesson_date='2026-08-16', planned_lesson_id=None)
    second = build_submission_key(group_id=7, lesson_date='2026-08-16', planned_lesson_id=None)
    assert first == second


def test_different_dates_get_different_keys():
    a = build_submission_key(group_id=7, lesson_date='2026-08-16', planned_lesson_id=None)
    b = build_submission_key(group_id=7, lesson_date='2026-08-17', planned_lesson_id=None)
    assert a != b


def test_date_object_and_string_give_same_key():
    """Вызывающие передают дату то строкой, то date — ключ обязан совпасть."""
    import datetime
    a = build_submission_key(group_id=7, lesson_date='2026-08-16', planned_lesson_id=None)
    b = build_submission_key(
        group_id=7, lesson_date=datetime.date(2026, 8, 16), planned_lesson_id=None,
    )
    assert a == b
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_submission_key.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.lessons.submission_key'`

- [ ] **Step 3: Написать модуль**

Создать `journal_django/apps/lessons/submission_key.py`:

```python
"""
submission_key — суррогатный ключ «это та же самая отправка того же занятия».

Зачем: без него сервер не может отличить повторную отправку от осмысленной
второй записи. В инциденте ПГ215 три отправки одного занятия дали три урока
именно потому, что каждая получала новый номер и проходила мимо уникального
ключа lessons_natural_key.

Ключ вычисляет СЕРВЕР, а не клиент: клиентский ключ пришлось бы валидировать
и он ничего не гарантирует (браузер может прислать новый после переоткрытия
формы). Серверный ключ выводится из того, ЧТО записывают, поэтому у повтора
он совпадает по построению.

Две формы ключа:
  pos:<planned_lesson_id>   — есть позиция курса. Мультислот различается сам
                              собой: два занятия дня — две разные позиции.
  slot:<group_id>:<date>    — позиции нет (группа без плана, дата вне плана).
                              Инвариант «одно курсовое занятие группы в день».

⚠️ Компромисс второй формы: группа БЕЗ плана, у которой два занятия в один
день, получит отказ на втором. Это осознанно — отказ громкий и с внятным
текстом, тогда как прежнее поведение молча создавало дубль с деньгами.
Обходной путь для админа — management-команда record_lesson_override.
"""
from __future__ import annotations

import datetime
from typing import Optional, Union


def build_submission_key(
    *,
    group_id: int,
    lesson_date: Union[str, datetime.date],
    planned_lesson_id: Optional[int],
) -> str:
    """Ключ отправки. Одинаковый у повторов, разный у разных занятий."""
    if planned_lesson_id is not None:
        return f'pos:{planned_lesson_id}'
    return f'slot:{group_id}:{_iso(lesson_date)}'


def _iso(value: Union[str, datetime.date]) -> str:
    """Дата в 'YYYY-MM-DD' независимо от того, пришла она строкой или date."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.strftime('%Y-%m-%d')
    return str(value)[:10]
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/lessons/tests/test_submission_key.py -v`
Expected: PASS (6 тестов)

- [ ] **Step 5: Добавить поле в модель**

В `journal_django/apps/lessons/models.py` в класс `Lesson` после `submitted_by_token` добавить:

```python
    # Суррогат «это та же самая отправка того же занятия» — см.
    # apps.lessons.submission_key. NULL у исторических записей и у системных
    # уроков (доп.урок/сгорание: их создаёт apps.extra_lessons напрямую через
    # insert_lesson, у них своя защита — лок статуса резолюции).
    submission_key = models.TextField(null=True, blank=True)
```

В `Meta.constraints` того же класса добавить вторым элементом:

```python
            # Частичный уникальный индекс: одна курсовая запись на ключ отправки
            # в пределах группы. Условие isnull=False оставляет исторические
            # строки и системные уроки вне ограничения.
            models.UniqueConstraint(
                fields=['group', 'submission_key'],
                condition=models.Q(submission_key__isnull=False),
                name='lessons_submission_key_unique',
            ),
```

- [ ] **Step 6: Сгенерировать миграцию**

Run: `cd journal_django && ./.venv/Scripts/python.exe manage.py makemigrations lessons --name lesson_submission_key`
Expected: создан `apps/lessons/migrations/0009_lesson_submission_key.py` с `AddField` и `AddConstraint`.

Открыть файл и убедиться глазами, что там ровно две операции и никаких посторонних `AlterField` по другим полям. Посторонний `AlterField` на FK опасен: он тихо затирает db-level `ON DELETE`, заданный прежними RunSQL-миграциями. Если такие операции появились — удалить их из файла вручную.

- [ ] **Step 7: Применить миграцию на dev-БД**

Run: `cd journal_django && ./.venv/Scripts/python.exe manage.py migrate lessons`
Expected: `Applying lessons.0009_lesson_submission_key... OK`

- [ ] **Step 8: Прогнать ПОЛНЫЙ pytest**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest -q`
Expected: без падений. Полный прогон здесь обязателен: миграция добавляет колонку, а часть приложений работает с общей `journal_test`, часть — со свежей `test_journal_test`; частичный прогон не покажет расхождения.

- [ ] **Step 9: Коммит**

```bash
git add journal_django/apps/lessons/submission_key.py journal_django/apps/lessons/tests/test_submission_key.py journal_django/apps/lessons/models.py journal_django/apps/lessons/migrations/0009_lesson_submission_key.py
git commit -m "feat(lessons): ключ отправки урока и уникальный индекс под него

Суррогат «это та же самая отправка того же занятия»: pos:<id> при наличии
позиции курса, slot:<group>:<date> без неё. Вычисляет сервер — клиентский
ключ ничего не гарантирует (браузер пришлёт новый после переоткрытия формы).

Частичный уникальный индекс (group, submission_key) оставляет исторические
записи и системные уроки вне ограничения."
```

---

### Task 7: Запись ключа и превращение конфликта в доменное исключение

**Files:**
- Modify: `journal_django/apps/lessons/repository.py` (функция `insert_lesson`)
- Modify: `journal_django/apps/lessons/services.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `journal_django/apps/teacher_spa/tests/test_duplicate_submit.py`:

```python
def test_second_record_without_position_is_rejected(group_fixture):
    """
    Группа без плана: повторная запись того же занятия обязана отказать, а не
    создать второй платный урок. Это путь, на котором произошёл ПГ215.
    """
    from apps.lessons.exceptions import LessonAlreadyRecorded
    from apps.lessons.services import record_lesson

    with connection.cursor() as cur:
        cur.execute('SELECT id FROM teachers LIMIT 1')
        teacher_id = cur.fetchone()[0]

    common = dict(
        group_id=group_fixture,
        teacher_id=teacher_id,
        original_teacher_id=None,
        lesson_date='2026-08-20',
        lesson_duration_minutes=60,
        lesson_type='regular',
        record_url=None,
        submit_date='2026-08-20',
        attendance=[],
        planned_lesson_id=None,
    )

    record_lesson(**common, lesson_number=1, submitted_by_token='acct:1')

    # Повтор: номер другой (его считают из прогресса), токен тот же — старый
    # натуральный ключ такое не ловил.
    with pytest.raises(LessonAlreadyRecorded):
        record_lesson(**common, lesson_number=2, submitted_by_token='acct:1')


def test_duplicate_across_different_actors_is_rejected(group_fixture):
    """
    Препод записал урок, следом админ записывает то же занятие. Старый ключ
    включал submitted_by_token и такой дубль пропускал.
    """
    from apps.lessons.exceptions import LessonAlreadyRecorded
    from apps.lessons.services import record_lesson

    with connection.cursor() as cur:
        cur.execute('SELECT id FROM teachers LIMIT 1')
        teacher_id = cur.fetchone()[0]

    common = dict(
        group_id=group_fixture,
        teacher_id=teacher_id,
        original_teacher_id=None,
        lesson_date='2026-08-21',
        lesson_duration_minutes=60,
        lesson_type='regular',
        record_url=None,
        submit_date='2026-08-21',
        attendance=[],
        planned_lesson_id=None,
        lesson_number=5,
    )

    record_lesson(**common, submitted_by_token='acct:12')

    with pytest.raises(LessonAlreadyRecorded):
        record_lesson(**common, submitted_by_token='admin-imported')
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_duplicate_submit.py -k "without_position or different_actors" -v`
Expected: FAIL — второй урок создаётся, исключения нет.

- [ ] **Step 3: Научить `insert_lesson` писать ключ**

В `journal_django/apps/lessons/repository.py:103-117` заменить функцию целиком:

```python
def insert_lesson(fields: dict) -> int:
    """INSERT урока. Возвращает id. submitted_at — DB DEFAULT now() через Now()."""
    obj = Lesson.objects.create(
        lesson_date=fields['lesson_date'],
        teacher_id=fields['teacher_id'],
        group_id=fields['group_id'],
        original_teacher_id=fields.get('original_teacher_id'),
        lesson_number=fields['lesson_number'],
        lesson_duration_minutes=fields['lesson_duration_minutes'],
        lesson_type=fields.get('lesson_type') or 'regular',
        record_url=fields.get('record_url') or None,
        submitted_by_token=fields.get('submitted_by_token') or 'admin-imported',
        # Ключ отправки — только у курсовых уроков. Доп.урок и сгорание приходят
        # сюда из apps.extra_lessons напрямую, без ключа: у них своя защита от
        # повтора (лок статуса резолюции), и уникальный индекс их не касается.
        submission_key=fields.get('submission_key'),
        submitted_at=Now(),
    )
    return obj.pk
```

- [ ] **Step 4: Считать ключ и ловить конфликт в `record_lesson`**

В `journal_django/apps/lessons/services.py` внутри `transaction.atomic()` заменить вызов вставки на:

```python
        # Ключ отправки — последний рубеж от дубля. Работает и там, где позиции
        # курса нет вовсе (группа без плана, дата вне плана): именно на этом
        # пути повтор создавал второй платный урок (ПГ215).
        submission_key = build_submission_key(
            group_id=group_id,
            lesson_date=lesson_date,
            planned_lesson_id=position['id'] if position is not None else None,
        )
        try:
            with transaction.atomic():   # savepoint: конфликт не рвёт внешнюю транзакцию
                lesson_id = repository.insert_lesson({
                    'lesson_date': lesson_date,
                    'teacher_id': teacher_id,
                    'group_id': group_id,
                    'original_teacher_id': original_teacher_id,
                    'lesson_number': lesson_number,
                    'lesson_duration_minutes': lesson_duration_minutes,
                    'lesson_type': lesson_type,
                    'record_url': record_url,
                    'submitted_by_token': submitted_by_token,
                    'submission_key': submission_key,
                })
        except IntegrityError as exc:
            if 'lessons_submission_key_unique' not in str(exc) and \
               'lessons_natural_key' not in str(exc):
                raise
            # Урок за это занятие уже записан — почти всегда повторная отправка
            # после потерянного ответа. Доменное исключение → 409, а не 500.
            raise LessonAlreadyRecorded(lesson_number, lesson_date) from exc
```

Добавить импорты в начало файла:

```python
from django.db import IntegrityError, transaction

from apps.lessons.submission_key import build_submission_key
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_duplicate_submit.py -v`
Expected: PASS

- [ ] **Step 6: Прогнать ПОЛНЫЙ pytest**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest -q`
Expected: без падений.

Вероятное место поломки — тесты, которые записывают несколько уроков одной группе на одну дату без позиций плана. Такой тест теперь корректно получает `LessonAlreadyRecorded`. Разводить датами, а не отключать защиту.

- [ ] **Step 7: Коммит**

```bash
git add journal_django/apps/lessons/repository.py journal_django/apps/lessons/services.py journal_django/apps/teacher_spa/tests/test_duplicate_submit.py
git commit -m "fix(lessons): повтор записи урока отказывает на ВСЕХ путях

Ключ отправки пишется при вставке, конфликт уникального индекса превращается
в LessonAlreadyRecorded вместо 500. Закрывает три дыры разом: группы без плана,
дата вне плана и дубль между разными акторами (препод + админ) — последний
проходил, потому что старый натуральный ключ включал submitted_by_token."
```

---

### Task 8: Админский путь отвечает 409, а не 500

**Files:**
- Modify: `journal_django/apps/lessons/views.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `journal_django/apps/teacher_spa/tests/test_duplicate_submit.py`:

```python
def test_admin_duplicate_returns_409_not_500(admin_client, group_fixture):
    """Повторное создание урока админом — понятный 409, а не «сломался сервер»."""
    with connection.cursor() as cur:
        cur.execute('SELECT id FROM teachers LIMIT 1')
        teacher_id = cur.fetchone()[0]

    payload = {
        'group_id': group_fixture,
        'teacher_id': teacher_id,
        'lesson_date': '2026-08-22',
        'lesson_number': 3,
        'lesson_duration_minutes': 60,
        'lesson_type': 'regular',
        'attendance': [],
    }

    first = admin_client.post('/api/admin/lessons', payload, format='json')
    assert first.status_code in (200, 201), first.content

    second = admin_client.post('/api/admin/lessons', payload, format='json')
    assert second.status_code == 409, second.content
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_duplicate_submit.py::test_admin_duplicate_returns_409_not_500 -v`
Expected: FAIL — 500 вместо 409.

Если первый POST вернёт 400 — открыть `apps/lessons/serializers.py`, посмотреть обязательные поля создания урока и дополнить `payload` фактическими.

- [ ] **Step 3: Обработать конфликт во вьюхе**

В `journal_django/apps/lessons/views.py` в методе `post` обернуть вызов сервиса:

```python
        try:
            created = services.create_lesson_full(serializer.validated_data)
        except LessonAlreadyRecorded as e:
            # Тот же конфликт, что у преподавателя: занятие уже записано.
            # Без этой ветки конфликт уникального индекса уходил наверх как
            # необработанный IntegrityError → голый 500.
            return Response(
                {'error': str(e), 'code': LESSON_ALREADY_RECORDED},
                status=status.HTTP_409_CONFLICT,
            )
        except CoursePositionVanished as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
```

Добавить в начало файла:

```python
from apps.lessons.exceptions import CoursePositionVanished, LessonAlreadyRecorded

# Машиночитаемый код конфликта — тот же, что у teacher SPA.
LESSON_ALREADY_RECORDED = 'lesson_already_recorded'
```

Точное имя вызываемого сервиса и переменной результата свериться по факту в файле.

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_duplicate_submit.py -v`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add journal_django/apps/lessons/views.py journal_django/apps/teacher_spa/tests/test_duplicate_submit.py
git commit -m "fix(lessons): повтор создания урока админом даёт 409, а не 500

Конфликт уникального индекса уходил наверх необработанным IntegrityError,
и админ видел «сломался сервер» вместо «урок уже записан»."
```

---

### Task 9: Тест на гонку двух одновременных отправок

Корректность блокировки держится только на рассуждении: в проекте нет ни одного теста с параллельными транзакциями.

**Files:**
- Create: `journal_django/apps/teacher_spa/tests/test_concurrent_submit.py`

- [ ] **Step 1: Написать тест**

```python
"""
Гонка: две одновременные записи одного занятия. Должен пройти ровно один урок.

transaction=True обязателен: нужны реальные коммиты и отдельные соединения,
внутри обычной тестовой транзакции select_for_update ничего не сериализует.
"""
from __future__ import annotations

import threading

import pytest
from django.db import connection, connections

pytestmark = pytest.mark.django_db(transaction=True)


def test_two_simultaneous_submits_create_one_lesson(group_fixture):
    from apps.lessons.exceptions import LessonAlreadyRecorded
    from apps.lessons.services import record_lesson

    with connection.cursor() as cur:
        cur.execute('SELECT id FROM teachers LIMIT 1')
        teacher_id = cur.fetchone()[0]

    date = '2026-08-25'
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        try:
            barrier.wait(timeout=10)      # стартуем строго одновременно
            record_lesson(
                group_id=group_fixture,
                teacher_id=teacher_id,
                original_teacher_id=None,
                lesson_date=date,
                lesson_number=1,
                lesson_duration_minutes=60,
                lesson_type='regular',
                record_url=None,
                submitted_by_token='acct:race',
                submit_date=date,
                attendance=[],
                planned_lesson_id=None,
            )
            with lock:
                outcomes.append('ok')
        except LessonAlreadyRecorded:
            with lock:
                outcomes.append('conflict')
        except Exception as exc:            # noqa: BLE001 — важно увидеть тип
            with lock:
                outcomes.append(f'error:{type(exc).__name__}')
        finally:
            connections.close_all()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    with connection.cursor() as cur:
        cur.execute(
            'SELECT count(*) FROM lessons WHERE group_id = %s AND lesson_date = %s',
            [group_fixture, date],
        )
        created = cur.fetchone()[0]
        cur.execute(
            'DELETE FROM payroll WHERE lesson_id IN '
            '(SELECT id FROM lessons WHERE group_id = %s AND lesson_date = %s)',
            [group_fixture, date],
        )
        cur.execute(
            'DELETE FROM lessons WHERE group_id = %s AND lesson_date = %s',
            [group_fixture, date],
        )

    assert created == 1, f'создано уроков: {created}, исходы: {outcomes}'
    assert sorted(outcomes) == ['conflict', 'ok'], outcomes
```

- [ ] **Step 2: Запустить**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_concurrent_submit.py -v`
Expected: PASS. Если увидите `error:IntegrityError` в исходах — значит конфликт не превращается в доменное исключение, вернуться к Задаче 7 Step 4 и проверить совпадение имени индекса в строке ошибки.

- [ ] **Step 3: Коммит**

```bash
git add journal_django/apps/teacher_spa/tests/test_concurrent_submit.py
git commit -m "test(lessons): гонка двух одновременных записей одного занятия

В проекте не было ни одного теста с параллельными транзакциями — корректность
select_for_update и уникального индекса держалась на рассуждении."
```

---

# ФАЗА 2 — Обратная связь при отправке

### Task 10: Модалку нельзя закрыть, пока запрос в полёте

Esc, клик по фону, крестик и «Отмена» работают во время отправки. После закрытия формы пришедший ответ не показывается вообще — ни успех, ни ошибка. Это и есть «подтверждения он не увидел ни разу».

**Files:**
- Modify: `journal_django/frontend/admin-src/src/shared/calendar/Modal.tsx`
- Modify: `journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx`
- Modify: `journal_django/frontend/teacher-src/src/components/lessons/ExtraLessonRecordModal.tsx`

- [ ] **Step 1: Добавить в модалку запрет закрытия**

В `journal_django/frontend/admin-src/src/shared/calendar/Modal.tsx` добавить проп `busy` и учитывать его во всех трёх путях закрытия:

```tsx
export function Modal({
  title,
  subtitle,
  onClose,
  busy = false,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  /** Идёт запрос: закрывать нельзя. Закрытая во время отправки форма теряет
   *  ответ навсегда — локальные колбэки мутации после размонтирования не
   *  выполняются, и человек не узнаёт, записалось или нет. */
  busy?: boolean;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, busy]);
```

В разметке заменить обработчики:

```tsx
    <div className="t-modal-overlay" onClick={() => { if (!busy) onClose(); }}>
```

```tsx
          <button
            type="button"
            className="t-modal-close"
            onClick={onClose}
            disabled={busy}
            aria-label="Закрыть"
          >
```

- [ ] **Step 2: Передать `busy` из формы урока**

В `journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx` найти использование `<Modal` и добавить проп:

```tsx
      busy={submitLesson.isPending}
```

Там же задизейблить кнопку «Отмена» — найти её и добавить:

```tsx
        disabled={submitLesson.isPending}
```

- [ ] **Step 3: То же для доп.урока**

В `journal_django/frontend/teacher-src/src/components/lessons/ExtraLessonRecordModal.tsx` добавить `busy={record.isPending}` в `<Modal` и `disabled={record.isPending}` на кнопку «Отмена».

- [ ] **Step 4: Проверить типы и собрать**

Run: `cd journal_django/frontend/teacher-src && npm run typecheck`
Expected: без ошибок.

Run: `cd journal_django/frontend/admin-src && npm run typecheck`
Expected: без ошибок (Modal общий для обоих SPA).

- [ ] **Step 5: Коммит**

```bash
git add journal_django/frontend/admin-src/src/shared/calendar/Modal.tsx journal_django/frontend/teacher-src/src/components/lessons/
git commit -m "fix(teacher): форму урока нельзя закрыть во время отправки

Esc, клик по фону, крестик и «Отмена» работали, пока запрос в полёте. После
закрытия формы пришедший ответ не показывался вообще: локальные колбэки
мутации после размонтирования компонента не выполняются. Человек оставался
в неведении и жал «Сохранить» ещё раз — механика инцидента ПГ215."
```

---

### Task 11: Таймаут запроса и честный текст

У `fetch` нет ограничения по времени: «долго» и «уже никогда» для человека неразличимы. Важно: таймаут НЕ отменяет серверную запись, поэтому текст не должен утверждать, что урок не сохранился.

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/api.ts`
- Modify: `journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx`

- [ ] **Step 1: Добавить таймаут в api-клиент**

В `journal_django/frontend/admin-src/src/lib/api.ts` перед `rawFetch` добавить:

```ts
/** Потолок ожидания ответа. Меньше, чем timeout gunicorn (30 с): к этому моменту
 *  сервер уже либо ответил, либо его воркер снят по своему таймауту. */
const REQUEST_TIMEOUT_MS = 25_000;

/** Код ошибки «ответ не пришёл вовремя». ВАЖНО: это НЕ значит, что запрос не
 *  выполнился — сервер мог закоммитить и не успеть ответить. UI обязан
 *  формулировать это как неизвестность, а не как неудачу. */
export const REQUEST_TIMEOUT = 'request_timeout';
```

Переписать `rawFetch`:

```ts
async function rawFetch(method: string, path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (!SAFE_METHODS.has(method.toUpperCase())) {
    const token = await ensureCsrfToken();
    if (token) headers['X-CSRFToken'] = token;
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(path, {
      method,
      credentials: 'include',
      headers: Object.keys(headers).length ? headers : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(0, 'Сервер не ответил вовремя', undefined, REQUEST_TIMEOUT);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
```

- [ ] **Step 2: Честный текст в форме урока**

В `journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx` в обработчике ошибки отправки добавить ветку ПЕРЕД общей ошибкой:

```tsx
        if (err instanceof ApiError && err.code === REQUEST_TIMEOUT) {
          // Таймаут не отменяет серверную запись: урок мог закоммититься, а
          // ответ не дойти. Говорить «не удалось, попробуйте ещё раз» здесь —
          // прямое приглашение создать дубль.
          setSubmitError(
            'Сервер не ответил вовремя. Урок мог записаться — откройте «Мои уроки» '
            + 'и проверьте, прежде чем отправлять ещё раз.',
          );
          return;
        }
```

Добавить `REQUEST_TIMEOUT` в импорт из `@shared/lib/api`.

- [ ] **Step 3: Проверить типы**

Run: `cd journal_django/frontend/teacher-src && npm run typecheck`
Expected: без ошибок.

Run: `cd journal_django/frontend/admin-src && npm run typecheck`
Expected: без ошибок.

- [ ] **Step 4: Коммит**

```bash
git add journal_django/frontend/admin-src/src/lib/api.ts journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx
git commit -m "feat(api): таймаут запроса и честный текст вместо «попробуйте ещё раз»

У fetch не было ограничения по времени — «долго» и «уже никогда» выглядели
одинаково. Таймаут не отменяет серверную запись, поэтому текст говорит о
неизвестности и отправляет проверить «Мои уроки», а не приглашает повторить."
```

---

### Task 12: Повтор записи доп.урока — спокойное «уже записано»

Сервер защищён, но 409 приходит без машиночитаемого кода, и фронт показывает красную ошибку на месте фактического успеха, не обновляя экран.

**Files:**
- Modify: `journal_django/apps/extra_lessons/views.py`
- Modify: `journal_django/frontend/teacher-src/src/hooks/useExtraLesson.ts`
- Modify: `journal_django/frontend/teacher-src/src/components/lessons/ExtraLessonRecordModal.tsx`
- Modify: `journal_django/frontend/admin-src/src/lib/api.ts`

- [ ] **Step 1: Добавить код в ответ сервера**

В `journal_django/apps/extra_lessons/views.py` рядом с прочими константами добавить:

```python
# Машиночитаемый код конфликта: доп.урок за это назначение уже проведён.
# Без кода фронт не отличает повтор от настоящей ошибки и пугает красным
# сообщением там, где на самом деле всё сохранено.
EXTRA_LESSON_ALREADY_RECORDED = 'extra_lesson_already_recorded'
```

Заменить обработчик `ValueError`:

```python
        except ValueError as e:
            return Response(
                {'error': str(e), 'code': EXTRA_LESSON_ALREADY_RECORDED},
                status=status.HTTP_409_CONFLICT,
            )
```

- [ ] **Step 2: Экспортировать код на фронте**

В `journal_django/frontend/admin-src/src/lib/api.ts` рядом с `LESSON_ALREADY_RECORDED` добавить:

```ts
// Код конфликта доп.урока (apps.extra_lessons.views): занятие уже проведено.
export const EXTRA_LESSON_ALREADY_RECORDED = 'extra_lesson_already_recorded';
```

- [ ] **Step 3: Обновлять кэш при конфликте**

В `journal_django/frontend/teacher-src/src/hooks/useExtraLesson.ts` в `useRecordExtraLesson` вынести инвалидацию в функцию и вызывать её также при конфликте:

```ts
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['extra-lesson'] });
    qc.invalidateQueries({ queryKey: ['calendar'] });
  };
```

и добавить в объект мутации:

```ts
    onError: (err) => {
      // «Уже проведён» → данные на сервере есть, экран устарел. Обновляем так
      // же, как при успехе, иначе календарь продолжит показывать назначение
      // невыполненным и преподаватель нажмёт ещё раз.
      if (err instanceof ApiError && err.code === EXTRA_LESSON_ALREADY_RECORDED) {
        invalidate();
      }
    },
```

Существующий `onSuccess` заменить на `onSuccess: invalidate`. Добавить импорты `ApiError` и `EXTRA_LESSON_ALREADY_RECORDED` из `@shared/lib/api`. Сверить фактические ключи запросов в файле и использовать их, а не выдуманные.

- [ ] **Step 4: Спокойное сообщение в модалке**

В `journal_django/frontend/teacher-src/src/components/lessons/ExtraLessonRecordModal.tsx` в обработчике ошибки добавить ветку ПЕРЕД общей:

```tsx
      if (err instanceof ApiError && err.code === EXTRA_LESSON_ALREADY_RECORDED) {
        toast('Это занятие уже отмечено', 'ok');
        onClose();
        return;
      }
```

Свериться, как в этом файле вызывается тост (в `LessonForm` это `toast(err.message, 'ok')`), и использовать тот же способ.

- [ ] **Step 5: Проверить типы**

Run: `cd journal_django/frontend/teacher-src && npm run typecheck`
Expected: без ошибок.

- [ ] **Step 6: Прогнать тесты доп.уроков**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/extra_lessons -q`
Expected: без падений. Если тест проверял тело 409 на точное равенство `{'error': ...}` — дополнить ожидание полем `code`.

- [ ] **Step 7: Коммит**

```bash
git add journal_django/apps/extra_lessons/views.py journal_django/frontend/admin-src/src/lib/api.ts journal_django/frontend/teacher-src/src/hooks/useExtraLesson.ts journal_django/frontend/teacher-src/src/components/lessons/ExtraLessonRecordModal.tsx
git commit -m "fix(extra-lessons): повтор отметки — спокойное «уже записано»

Сервер конфликт ловил, но отдавал 409 без машиночитаемого кода: фронт не мог
отличить повтор от настоящей ошибки, показывал красное сообщение на месте
фактического успеха и не обновлял экран. Деньги при этом уже начислены."
```

---

# ФАЗА 3 — Инфраструктура

### Task 13: Кеширование статики, TLS-сессии и таймауты прокси

Замерено на живом проде: у собранных бандлов нет заголовка кеширования вообще, TLS-сессии не переиспользуются.

**Files:**
- Modify: `deploy/nginx/snippets/journal-static.conf`
- Modify: `deploy/nginx/journal-kotokod.conf`

- [ ] **Step 1: Кешировать хешированные бандлы**

В `deploy/nginx/snippets/journal-static.conf` перед блоками `/teacher/` и `/admin/` добавить:

```nginx
# --- Хешированные бандлы Vite: имя файла меняется при каждой сборке, поэтому
#     кешировать можно навсегда. Сейчас заголовка нет вовсе — браузер ходит
#     проверять свежесть на КАЖДОМ заходе, и на мобильном интернете это самая
#     заметная задержка старта. add_header внутри location гасит server-уровневые
#     security-заголовки, поэтому повторяем их здесь явно. ---
location ~ ^/(teacher|admin)/assets/ {
    root $app_root/frontend;
    rewrite ^/teacher/(.*)$ /teacher-dist/$1 break;
    rewrite ^/admin/(.*)$  /admin-dist/$1  break;
    expires 1y;
    add_header Cache-Control "public, max-age=31536000, immutable" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    try_files $uri =404;
}
```

- [ ] **Step 2: Включить переиспользование TLS-сессий и задать таймауты прокси**

В `deploy/nginx/journal-kotokod.conf` после строк `ssl_protocols`/`ssl_prefer_server_ciphers` добавить:

```nginx
    # Без кеша сессий каждое новое соединение платит полный TLS-handshake.
    # На мобильной сети с потерями это самая ощутимая часть задержки.
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets on;
```

В блок `location /api/` добавить:

```nginx
        # Согласовано с gunicorn timeout=30: ждать дольше, чем живёт воркер,
        # бессмысленно — клиент просто дольше видит «крутилку».
        proxy_connect_timeout 5s;
        proxy_send_timeout    30s;
        proxy_read_timeout    30s;
```

- [ ] **Step 3: Проверить синтаксис локально**

Run: `nginx -t -c <путь к локальному конфигу>` (на машине разработчика — через `deploy/nginx/local/start-local-nginx.ps1`), либо на сервере `sudo nginx -t`.
Expected: `syntax is ok` / `test is successful`.

- [ ] **Step 4: Коммит**

```bash
git add deploy/nginx/
git commit -m "perf(nginx): кеш хешированных бандлов, TLS-сессии, таймауты прокси

Замерено на проде: у бандлов не было заголовка кеширования вовсе (браузер
перепроверял свежесть на каждом заходе), TLS-сессии не переиспользовались
(полный handshake на каждое соединение). Таймауты прокси согласованы с
gunicorn: раньше nginx ждал 60 с, а воркер снимался на 30-й."
```

---

### Task 14: Воркеры под реальное железо и переиспользование соединений с БД

**Files:**
- Modify: `deploy/gunicorn.conf.py`
- Modify: `journal_django/config/settings/base.py:150`

- [ ] **Step 1: Уточнить реальные ресурсы сервера**

Run (на сервере): `nproc && free -m`
Записать фактические значения — они определяют число воркеров. Комментарий в текущем конфиге говорит про «2 CPU / 2 ГБ», и это надо либо подтвердить, либо опровергнуть ФАКТОМ, а не памятью.

- [ ] **Step 2: Поднять число воркеров**

В `deploy/gunicorn.conf.py` заменить блок воркеров, подставив реальное число ядер вместо `<N>`:

```python
# Формула для sync-воркеров: 2*CPU+1. Sync-воркер держит запрос целиком и не
# отдаёт управление на время ожидания БД, поэтому их число — это и есть потолок
# одновременных запросов на всю школу. При трёх воркерах три одновременные
# отправки урока занимали сервер полностью (инцидент ПГ215).
workers = <N>   # = 2 * nproc + 1, подставить по факту из Step 1
```

- [ ] **Step 3: Включить переиспользование соединений с БД**

В `journal_django/config/settings/base.py` заменить строки про `CONN_MAX_AGE`:

```python
# Переиспользуем соединение между запросами: открывать новое к PostgreSQL на
# каждый запрос — лишняя задержка и лишняя нагрузка на сервер БД.
# Прежний комментарий «пусть существующий pg-пул разруливает» относился к пулу
# Node-бэкенда (services/db.js), а тот удалён вместе с Express.
DATABASES['default']['CONN_MAX_AGE'] = 60
DATABASES['default']['CONN_HEALTH_CHECKS'] = True
```

- [ ] **Step 4: Прогнать ПОЛНЫЙ pytest**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest -q`
Expected: без падений. `CONN_MAX_AGE` влияет на жизненный цикл соединений, и тесты с `transaction=True` — первое, что это почувствует.

- [ ] **Step 5: Коммит**

```bash
git add deploy/gunicorn.conf.py journal_django/config/settings/base.py
git commit -m "perf: воркеры под реальное железо, переиспользование соединений с БД

Три sync-воркера — это потолок в три одновременных запроса на всю школу:
три отправки урока подряд занимали сервер целиком. CONN_MAX_AGE=0 остался от
пула Node-бэкенда, который удалён вместе с Express, — Django открывал новое
соединение к PostgreSQL на каждый запрос."
```

---

### Task 15: Убрать чтение всей школы из отправки урока

`submit_lesson` вызывает `read_all_students()` — все активные membership всех групп всех преподавателей с расчётом баланса по каждому ученику. Самый дорогой запрос стоит на самом критичном действии.

**Files:**
- Modify: `journal_django/apps/teacher_spa/repository.py`
- Modify: `journal_django/apps/teacher_spa/services.py`

- [ ] **Step 1: Написать тест на эквивалентность**

Создать `journal_django/apps/teacher_spa/tests/test_group_scoped_read.py`:

```python
"""
Выборка по одной группе обязана давать те же данные, что общая выборка по школе,
иначе оптимизация тихо изменит поведение записи урока.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_group_scoped_read_matches_full_read(group_fixture):
    from apps.teacher_spa.repository import read_all_students, read_group_students

    full = read_all_students()
    target = None
    owner = None
    for teacher, groups in full['data'].items():
        for name, data in groups.items():
            if data.get('students'):
                target, owner = name, teacher
                break
        if target:
            break
    if target is None:
        pytest.skip('В БД нет группы с учениками')

    scoped = read_group_students(target)

    assert scoped is not None
    assert scoped['owner'] == owner
    expected = full['data'][owner][target]
    assert [s['name'] for s in scoped['group']['students']] == \
           [s['name'] for s in expected['students']]
    assert [s['lessonsDone'] for s in scoped['group']['students']] == \
           [s['lessonsDone'] for s in expected['students']]
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_group_scoped_read.py -v`
Expected: FAIL — `ImportError: cannot import name 'read_group_students'`

- [ ] **Step 3: Написать выборку по одной группе**

В `journal_django/apps/teacher_spa/repository.py` добавить рядом с `read_all_students`:

```python
def read_group_students(group_name: str) -> Optional[dict]:
    """
    Данные ОДНОЙ группы по её имени: {'owner': <имя преподавателя>, 'group': {...}}.
    None — активной группы с таким именем нет.

    Зачем отдельно от read_all_students: та читает все активные membership всей
    школы и считает баланс по каждому ученику. На странице это терпимо, но она
    же стояла на пути записи урока — самом критичном действии, где важна каждая
    сотня миллисекунд (воркер занят целиком, а их всего несколько на всю школу).

    Формат ветки 'group' совпадает с элементом read_all_students()['data'][t][g] —
    вызывающий код не различает, откуда данные пришли.
    """
    rows = list(
        GroupMembership.objects
        .filter(
            active=True, group__active=True, group__teacher__active=True,
            group__name=group_name,
        )
        .order_by('student__full_name')
        .values(
            'group_id', 'student_id', 'lessons_done', 'sheet_row', 'transferred_from_id',
            group_name=F('group__name'),
            is_individual=F('group__is_individual'),
            vk_chat=F('group__vk_chat'),
            group_start_date=F('group__group_start_date'),
            teacher_name=F('group__teacher__name'),
            student_name=F('student__full_name'),
            birth_date=F('student__birth_date'),
            pm=F('student__manager__full_name'),
            membership_id=F('id'),
            duration_minutes=F('group__lesson_duration_minutes'),
        )
    )
    if not rows:
        return None

    built = _build_from_rows(rows)
    teacher_name = rows[0]['teacher_name']
    return {'owner': teacher_name, 'group': built['data'][teacher_name][group_name]}
```

Перед этим сделать механическое извлечение, НЕ переписывая логику сборки:

1. В `read_all_students` всё от строки `balances = balances_for_students({r['student_id'] for r in rows})` и до `return` включительно вырезать в новую функцию:

```python
def _build_from_rows(rows: list[dict]) -> dict:
    """
    Сборка ответа из уже выбранных строк membership. Вынесено из
    read_all_students, чтобы выборка по одной группе (read_group_students)
    давала БАЙТ В БАЙТ тот же формат: две параллельные сборки неизбежно
    разъехались бы, а на этом формате стоит запись урока.
    """
```

2. Тело перенести без единого изменения (включая построение `index` и блок маркеров «неоплачиваемый пропуск» в конце) — меняется только отступ и то, что `rows` теперь аргумент.

3. `read_all_students` после этого заканчивается так:

```python
    return _build_from_rows(rows)
```

Так формат гарантированно один, а не «почти один».

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_group_scoped_read.py -v`
Expected: PASS

- [ ] **Step 5: Использовать её в записи урока**

В `journal_django/apps/teacher_spa/services.py` в `submit_lesson` заменить блок чтения состояния:

```python
    # 2. Актуальное состояние ОДНОЙ группы. Общая выборка по школе
    #    (read_all_students) здесь стояла на критическом пути записи урока и
    #    тянула все membership всех преподавателей с балансом по каждому ученику.
    scoped = repository.read_group_students(group)
    if scoped is None:
        return {'success': False, 'error': 'Группа не найдена'}
    owner_name = scoped['owner']
    group_data = scoped['group']
```

Ниже по функции найти все обращения к `unified` и заменить их на уже полученные `owner_name`/`group_data`. Если останется место, которому действительно нужна вся школа, — оставить его, но убедиться, что оно не на каждом вызове.

- [ ] **Step 6: Прогнать ПОЛНЫЙ pytest**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest -q`
Expected: без падений. Особое внимание — тестам подмены: право отметить чужой урок выводится из принадлежности группы другому преподавателю, и эта ветка раньше опиралась на общую выборку.

- [ ] **Step 7: Коммит**

```bash
git add journal_django/apps/teacher_spa/repository.py journal_django/apps/teacher_spa/services.py journal_django/apps/teacher_spa/tests/test_group_scoped_read.py
git commit -m "perf(teacher): запись урока читает одну группу, а не всю школу

submit_lesson вызывал read_all_students — все активные membership всех групп
всех преподавателей с расчётом баланса по каждому ученику. Самый дорогой
запрос стоял на самом критичном действии, при том что воркеров на всю школу
единицы, и три одновременные отправки занимали сервер целиком."
```

---

## Финальная проверка перед выкаткой

- [ ] **Полный pytest**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest -q`
Expected: зелёный прогон, число тестов не меньше прежнего 1785 + новые.

- [ ] **Типы и сборка обоих SPA**

```bash
cd journal_django/frontend/teacher-src && npm run typecheck && npm run build
cd ../admin-src && npm run typecheck && npm run build
```

- [ ] **Проверить, что в коммит фронта не утёк лишний мусор**

Run: `git status --short`
Ожидается только пересборка `teacher-dist` / `admin-dist`. Если admin-бандл изменился лишь одним `.map` — откатить его, это шум.

- [ ] **Миграция на проде — до перезапуска приложения**

```bash
python manage.py migrate lessons
```

- [ ] **`resync_plan_facts` на группах с накопленным дрейфом**

Это условие уже стояло в коммите 2485444 и не выполнено: без него новые уроки пойдут по позициям плана, а старые останутся со съехавшими номерами.

---

## Известные компромиссы

**Группа без плана с двумя занятиями в один день** после Задачи 7 получит отказ на втором занятии: ключ `slot:<group>:<date>` совпадёт. Отказ громкий и с внятным текстом, обходной путь — management-команда `record_lesson_override`. Прежнее поведение молча создавало дубль с деньгами, поэтому обмен считаю выгодным. Если такие группы обнаружатся в бою — завести им план занятий, это правильное решение по существу.

**Ключ вычисляется сервером, а не приходит от клиента.** Это сознательно: клиентский ключ пришлось бы валидировать, и он всё равно не решает случай «форму закрыли и открыли заново» — браузер сгенерировал бы новый.

**Повтор получает 409, а не успех первой попытки.** Хранить соответствие «ключ → id урока» ради возврата успеха — отдельная инфраструктура; фронт уже показывает 409 спокойным сообщением и обновляет экран, чего достаточно.
