# «Мои уроки» — история по месяцам — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Раздел «Мои уроки» кабинета преподавателя показывает историю проведённых уроков по месяцам; строка раскрывается и показывает, кто из учеников был и кто не был.

**Architecture:** Существующий `GET /api/lessons` получает поле `students` (посещения одним `prefetch_related`). Фронт запрашивает месяц диапазоном `from`/`to` и рисует строки в стиле «Зарплаты». Общие куски «Зарплаты» (подписи типов, дата «дд.мм», переключатель месяцев) выносятся и переиспользуются.

**Tech Stack:** Django 5 + DRF, pytest; React 19 + TanStack Query v5 (`journal_django/frontend/teacher-src/`, общий код через алиас `@shared` → `admin-src/src`).

**Спека:** `docs/superpowers/specs/2026-09-16-teacher-my-lessons-history-design.md`

---

## Структура файлов

| Файл | Ответственность |
|---|---|
| `journal_django/apps/teacher_spa/serializers.py` | **Правка.** Поле `students` и правило статуса ученика. |
| `journal_django/apps/teacher_spa/views.py` | **Правка.** `prefetch_related` посещений в `MyLessonsView`. |
| `journal_django/apps/teacher_spa/tests/test_my_lessons_history.py` | **Создать.** Тесты статусов, скоупа, месяца, совпадения с зарплатой, числа запросов. |
| `journal_django/frontend/teacher-src/src/lib/types.ts` | **Правка.** `MyLessonStudent`, `students`, расширенный `lessonType`. |
| `journal_django/frontend/teacher-src/src/lib/lessonKinds.ts` | **Создать.** Подписи типов урока и статусов ученика — общие для «Зарплаты» и «Моих уроков». |
| `journal_django/frontend/teacher-src/src/lib/dates.ts` | **Правка.** `dayMonthOfIso` (переезд из `PayrollPage`). |
| `journal_django/frontend/teacher-src/src/components/ui/MonthNav.tsx` | **Создать.** Шапка-переключатель месяцев, общая для двух экранов. |
| `journal_django/frontend/teacher-src/src/hooks/useMyLessons.ts` | **Правка.** Параметр `pageSize`. |
| `journal_django/frontend/teacher-src/src/pages/payroll/PayrollPage.tsx` | **Правка.** Использует вынесенные подписи, дату и `MonthNav`. |
| `journal_django/frontend/teacher-src/src/pages/lessons/MyLessonsPage.tsx` | **Переписать.** История по месяцам. |
| `journal_django/frontend/teacher-src/src/styles/lessons.css` | **Правка.** Удалить `.ml-page`, `.ml-subtitle`; добавить классы истории. |

Команды:
- pytest: `cd journal_django && ./.venv/Scripts/python.exe -m pytest <путь> -q`; перед завершением — ПОЛНЫЙ `pytest -q` без путей.
- типы кабинета: `cd journal_django/frontend/teacher-src && npx tsc --noEmit`.
- сборка — только в последней задаче, координатором.

---

### Task 1: Поле `students` в `/api/lessons`

**Files:**
- Modify: `journal_django/apps/teacher_spa/serializers.py` (класс `MyLessonSerializer`)
- Modify: `journal_django/apps/teacher_spa/views.py` (класс `MyLessonsView`)
- Test: `journal_django/apps/teacher_spa/tests/test_my_lessons_history.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `journal_django/apps/teacher_spa/tests/test_my_lessons_history.py`:

```python
"""
История «Мои уроки» (GET /api/lessons) — поле students и совпадение с зарплатой.

Спека: docs/superpowers/specs/2026-09-16-teacher-my-lessons-history-design.md.
Фикстуры teacher_fixture/account_fixture — из conftest этого пакета.
"""
from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.teacher_spa.tests.conftest import _jwt_client

pytestmark = pytest.mark.django_db

MONTH = {'from': '2026-02-01', 'to': '2026-02-28', 'page_size': 500}


@pytest.fixture
def graph(teacher_fixture):
    """Направление, группа преподавателя, пять учеников; чистится в teardown."""
    teacher_id = teacher_fixture[0]
    created = {'teacher_id': teacher_id, 'lessons': [], 'students': [], 'teachers': []}
    with connection.cursor() as cur:
        cur.execute("INSERT INTO directions (name, total_lessons, active) "
                    "VALUES ('__mlh_dir__', 16, true) RETURNING id")
        created['direction_id'] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active, lesson_number_offset) "
            "VALUES ('__mlh_group__', %s, %s, false, 60, true, 0) RETURNING id",
            [created['direction_id'], teacher_id])
        created['group_id'] = cur.fetchone()[0]
        for name in ('__mlh_Дарья__', '__mlh_Анна__', '__mlh_Борис__', '__mlh_Вера__', '__mlh_Глеб__'):
            cur.execute('INSERT INTO students (full_name) VALUES (%s) RETURNING id', [name])
            created['students'].append(cur.fetchone()[0])
    yield created
    with connection.cursor() as cur:
        for lid in created['lessons']:
            cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [lid])
            cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lid])
            cur.execute('DELETE FROM lessons WHERE id = %s', [lid])
        for sid in created['students']:
            cur.execute('DELETE FROM students WHERE id = %s', [sid])
        cur.execute('DELETE FROM groups WHERE id = %s', [created['group_id']])
        for tid in created['teachers']:
            cur.execute('DELETE FROM teachers WHERE id = %s', [tid])
        cur.execute('DELETE FROM directions WHERE id = %s', [created['direction_id']])


def _lesson(graph, *, date='2026-02-10', number=1, lesson_type='regular',
            attendance=(), teacher_id=None, with_payroll=True):
    """
    Урок с посещениями. attendance — кортежи (student_id, present, is_free, unpaid_skip).
    with_payroll — строка зарплаты, как у всех уроков на проде (замер 2026-09-16).
    """
    tid = teacher_id or graph['teacher_id']
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s, %s, %s, %s, 60, %s, 't') RETURNING id",
            [graph['group_id'], tid, date, number, lesson_type])
        lid = cur.fetchone()[0]
        graph['lessons'].append(lid)
        for sid, present, is_free, skip in attendance:
            cur.execute(
                'INSERT INTO lesson_attendance (lesson_id, student_id, present, is_free, unpaid_skip) '
                'VALUES (%s, %s, %s, %s, %s)', [lid, sid, present, is_free, skip])
        if with_payroll:
            present_count = sum(1 for _, p, f, s in attendance if p and not f and not s)
            cur.execute(
                'INSERT INTO payroll (lesson_id, teacher_id, total_students, present_count, payment, penalty) '
                'VALUES (%s, %s, %s, %s, 0, 0)', [lid, tid, len(attendance), present_count])
    return lid


def _get(account_id, params):
    resp = _jwt_client(account_id).get('/api/lessons', params)
    assert resp.status_code == 200, resp.content
    return resp.json()


def _row(body, lesson_id):
    return next(r for r in body['rows'] if r['id'] == lesson_id)


def test_student_statuses_for_all_cases(graph, account_fixture):
    anna, boris, vera, gleb, darya = sorted(graph['students'])[:5]
    lid = _lesson(graph, attendance=[
        (anna, True, False, False),    # был
        (boris, True, True, False),    # был бесплатно
        (vera, False, False, False),   # не был
        (gleb, False, False, True),    # не посещает
    ])
    burned = _lesson(graph, number=2, lesson_type='burned', date='2026-02-11',
                     attendance=[(darya, True, False, False)])

    body = _get(account_fixture, MONTH)
    statuses = {s['id']: s['status'] for s in _row(body, lid)['students']}
    assert statuses == {anna: 'present', boris: 'free', vera: 'absent', gleb: 'skip'}
    # Сгорание: в базе present=true, но занятия не было — тип урока старше флагов.
    assert [s['status'] for s in _row(body, burned)['students']] == ['burned']


def test_students_sorted_by_name_and_none_lost(graph, account_fixture):
    """
    Все ученики урока на месте и по алфавиту. У lesson_attendance PK в ORM —
    lesson_id, поэтому prefetch мог бы схлопнуть учеников одного урока в одного.
    """
    ids = graph['students']
    lid = _lesson(graph, attendance=[(sid, True, False, False) for sid in ids])

    names = [s['name'] for s in _row(_get(account_fixture, MONTH), lid)['students']]
    assert len(names) == len(ids)
    assert names == sorted(names)


def test_foreign_teacher_lessons_are_hidden(graph, account_fixture):
    with connection.cursor() as cur:
        cur.execute("INSERT INTO teachers (name, active) VALUES ('__mlh_other__', true) RETURNING id")
        other = cur.fetchone()[0]
    graph['teachers'].append(other)
    mine = _lesson(graph, number=1)
    foreign = _lesson(graph, number=2, teacher_id=other)

    ids = {r['id'] for r in _get(account_fixture, MONTH)['rows']}
    assert mine in ids
    assert foreign not in ids


def test_month_range_and_order(graph, account_fixture):
    early = _lesson(graph, number=1, date='2026-02-03')
    late = _lesson(graph, number=2, date='2026-02-20')
    _lesson(graph, number=3, date='2026-03-02')   # вне месяца

    rows = [r['id'] for r in _get(account_fixture, MONTH)['rows'] if r['id'] in graph['lessons']]
    assert rows == [late, early]


def test_month_matches_payroll(graph, account_fixture):
    """Список уроков месяца совпадает со списком «Зарплаты» строка в строку."""
    from apps.payroll.services import my_payroll_month

    _lesson(graph, number=1, date='2026-02-03', attendance=[(graph['students'][0], True, False, False)])
    _lesson(graph, number=2, date='2026-02-20', lesson_type='burned',
            attendance=[(graph['students'][1], True, False, False)])
    _lesson(graph, number=3, date='2026-02-21', lesson_type='extra',
            attendance=[(graph['students'][2], True, False, False)])

    history = [r['id'] for r in _get(account_fixture, MONTH)['rows']]
    payroll = [r['lessonId'] for r in my_payroll_month(graph['teacher_id'], '2026-02')['rows']]
    assert history == payroll


def test_query_count_does_not_grow_with_lessons(graph, account_fixture):
    client = _jwt_client(account_fixture)
    _lesson(graph, number=1, attendance=[(graph['students'][0], True, False, False)])
    with CaptureQueriesContext(connection) as one:
        client.get('/api/lessons', MONTH)

    for n in (2, 3, 4):
        _lesson(graph, number=n, attendance=[(sid, True, False, False) for sid in graph['students']])
    with CaptureQueriesContext(connection) as many:
        client.get('/api/lessons', MONTH)

    assert len(many.captured_queries) == len(one.captured_queries)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_my_lessons_history.py -q`
Expected: FAIL — `KeyError: 'students'` в тестах про учеников; тесты скоупа, месяца и зарплаты могут уже проходить — это нормально, они страхуют поведение.

Если `_jwt_client` не импортируется из conftest или фикстуры `teacher_fixture`/`account_fixture` устроены иначе, чем предполагает тест, — подогнать под реальный conftest и отметить это в отчёте.

- [ ] **Step 3: Правило статуса и поле в сериализаторе**

В `journal_django/apps/teacher_spa/serializers.py` рядом с `MyLessonSerializer` (перед классом) добавить:

```python
def my_lesson_student_status(lesson_type: str, attendance) -> str:
    """
    Статус ученика в истории «Мои уроки».

    Тип урока проверяется РАНЬШЕ флагов посещения: у сгорания посещение в базе
    отмечено present=true, но занятия не было — показывать «был» было бы неправдой.
    """
    if lesson_type == 'burned':
        return 'burned'
    if attendance.present:
        return 'free' if attendance.is_free else 'present'
    return 'skip' if attendance.unpaid_skip else 'absent'
```

В `MyLessonSerializer` добавить поле рядом с остальными `SerializerMethodField`:

```python
    students = serializers.SerializerMethodField()
```

и метод:

```python
    def get_students(self, obj):
        # Посещения приходят из prefetch (MyLessonsView) уже по алфавиту —
        # без него здесь был бы запрос на каждый урок выдачи.
        return [
            {
                'id': att.student_id,
                'name': att.student.full_name,
                'status': my_lesson_student_status(obj.lesson_type, att),
            }
            for att in obj.attendance.all()
        ]
```

- [ ] **Step 4: Prefetch посещений во вьюхе**

В `journal_django/apps/teacher_spa/views.py`, в `MyLessonsView.get_queryset`, к цепочке после `.select_related(...)` добавить:

```python
            .prefetch_related(
                Prefetch(
                    'attendance',
                    queryset=LessonAttendance.objects
                    .select_related('student')
                    .order_by('student__full_name', 'student_id'),
                )
            )
```

Добавить в импорты файла `from django.db.models import Prefetch` и `LessonAttendance` из `apps.lessons.models` (проверить, что `Lesson` уже импортируется оттуда, и дописать в тот же импорт). Дописать в docstring вьюхи строку: `Каждый урок несёт students — ученики с статусом посещения (prefetch, без запроса на урок).`

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest apps/teacher_spa/tests/test_my_lessons_history.py apps/teacher_spa/tests/test_teacher_spa_api.py -q`
Expected: PASS — новые тесты и существующий `TestMyLessons`.

- [ ] **Step 6: Полный прогон**

Run: `cd journal_django && ./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

---

### Task 2: Фронт — история по месяцам

**Files:**
- Modify: `journal_django/frontend/teacher-src/src/lib/types.ts`
- Create: `journal_django/frontend/teacher-src/src/lib/lessonKinds.ts`
- Modify: `journal_django/frontend/teacher-src/src/lib/dates.ts`
- Create: `journal_django/frontend/teacher-src/src/components/ui/MonthNav.tsx`
- Modify: `journal_django/frontend/teacher-src/src/hooks/useMyLessons.ts`
- Modify: `journal_django/frontend/teacher-src/src/pages/payroll/PayrollPage.tsx`
- Rewrite: `journal_django/frontend/teacher-src/src/pages/lessons/MyLessonsPage.tsx`
- Modify: `journal_django/frontend/teacher-src/src/styles/lessons.css`

- [ ] **Step 1: Типы**

В `lib/types.ts` перед `export interface MyLesson` добавить:

```ts
/** Статус ученика в истории «Мои уроки» — выводит сервер
 *  (teacher_spa/serializers.py::my_lesson_student_status). */
export type MyLessonStudentStatus = 'present' | 'free' | 'absent' | 'skip' | 'burned';

export interface MyLessonStudent {
  id: number;
  name: string;
  status: MyLessonStudentStatus;
}
```

В `MyLesson` расширить `lessonType` до `'regular' | 'substitution' | 'reschedule' | 'extra' | 'burned'` (сервер отдаёт сырой `lesson_type`, и доп.уроки со сгораниями туда уже попадают) и добавить поле:

```ts
  /** Ученики урока по алфавиту с пометкой посещения. */
  students: MyLessonStudent[];
```

- [ ] **Step 2: Общие подписи**

Создать `lib/lessonKinds.ts`:

```ts
import type { MyLessonStudentStatus, PayrollLessonKind } from './types';

/**
 * Подпись типа урока. Обычный урок бейджа не получает — это шум.
 * Общая для «Зарплаты» и «Моих уроков»: списки двух экранов совпадают строка в
 * строку, и один и тот же урок обязан называться в них одинаково.
 */
export const LESSON_KIND_LABEL: Partial<Record<PayrollLessonKind, string>> = {
  substitution: 'Замена',
  reschedule: 'Перенос',
  extra: 'Доп. занятие',
  burned: 'Сгоревшее занятие',
};

/** Подпись статуса ученика в истории «Мои уроки». */
export const STUDENT_STATUS_LABEL: Record<MyLessonStudentStatus, string> = {
  present: 'был',
  free: 'был, бесплатно',
  absent: 'не был',
  skip: 'не посещает',
  burned: 'пропуск сгорел',
};
```

Если `PayrollLessonKind` в `types.ts` не покрывает `'regular'` — не страшно, `Partial` это допускает; если тип называется иначе — подогнать и отметить.

- [ ] **Step 3: Дата «дд.мм»**

В `lib/dates.ts` добавить:

```ts
/** «03.07» из 'YYYY-MM-DD' — год в списке за месяц избыточен. */
export function dayMonthOfIso(iso: string): string {
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
}
```

- [ ] **Step 4: Переключатель месяцев**

Создать `components/ui/MonthNav.tsx` — вынос шапки из `PayrollPage` без изменения разметки и классов:

```tsx
import { addMonths, monthLabel } from '../../lib/dates';

interface Props {
  title: string;
  month: Date;
  currentMonth: Date;
  onChange: (month: Date) => void;
  isFetching?: boolean;
}

/**
 * Шапка экрана с переключателем месяцев: стрелки, подпись месяца и возврат к
 * текущему. Вперёд дальше текущего месяца не пускает — будущих уроков и выплат
 * нет. Общая для «Зарплаты» и «Моих уроков».
 */
export function MonthNav({ title, month, currentMonth, onChange, isFetching }: Props) {
  const isCurrentMonth = month.getTime() >= currentMonth.getTime();
  return (
    <div className="cal-head">
      <div className="cal-title">{title}</div>
      <div className="cal-week-nav">
        <button
          type="button"
          className="cal-nav-btn"
          onClick={() => onChange(addMonths(month, -1))}
          aria-label="Предыдущий месяц"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6" /></svg>
        </button>
        <span className="cal-week-label">{monthLabel(month)}</span>
        <button
          type="button"
          className="cal-nav-btn"
          onClick={() => onChange(addMonths(month, 1))}
          disabled={isCurrentMonth}
          aria-label="Следующий месяц"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg>
        </button>
        {!isCurrentMonth && (
          <button type="button" className="cal-today-btn" onClick={() => onChange(currentMonth)}>
            Текущий месяц
          </button>
        )}
      </div>
      {isFetching && <span className="ml-updating">обновление…</span>}
    </div>
  );
}
```

- [ ] **Step 5: `PayrollPage` на общих кусках**

В `pages/payroll/PayrollPage.tsx`:
- удалить локальные `KIND_LABEL` и `dayMonthOfIso`; импортировать `LESSON_KIND_LABEL` из `../../lib/lessonKinds` и `dayMonthOfIso` из `../../lib/dates`; в `PayrollRow` заменить `KIND_LABEL[entry.kind]` на `LESSON_KIND_LABEL[entry.kind]`;
- заменить блок `<div className="cal-head">…</div>` на `<MonthNav title="Зарплата" month={month} currentMonth={currentMonth} onChange={setMonth} isFetching={isFetching} />` (импорт из `../../components/ui/MonthNav`);
- переменная `isCurrentMonth` и импорты `addMonths`, `monthLabel` станут неиспользуемыми — удалить.

Поведение экрана «Зарплата» меняться не должно.

- [ ] **Step 6: `pageSize` в хуке**

В `hooks/useMyLessons.ts` добавить в `MyLessonsParams` поле `pageSize?: number;` и в сборку строки запроса — `if (params.pageSize) qs.set('page_size', String(params.pageSize));`. Обновить docstring: хук используется «Моими уроками» для выборки месяца.

- [ ] **Step 7: Переписать страницу**

Заменить содержимое `pages/lessons/MyLessonsPage.tsx`:

```tsx
import { useMemo, useState, type CSSProperties } from 'react';
import { useMyLessons } from '../../hooks/useMyLessons';
import { MonthNav } from '../../components/ui/MonthNav';
import { addDays, addMonths, dayMonthOfIso, firstOfMonthMsk, isoDate, weekdayShortOfIso } from '../../lib/dates';
import { LESSON_KIND_LABEL, STUDENT_STATUS_LABEL } from '../../lib/lessonKinds';
import { resolveDirectionColor } from '../../lib/subjects';
import type { MyLesson } from '../../lib/types';

/** Уроков за месяц у преподавателя ~20–40; 500 — потолок пагинатора с запасом. */
const MONTH_PAGE_SIZE = 500;

/**
 * Строка посещаемости: считается по ученикам урока, а не по строке зарплаты —
 * это экран «кто был», а не расчёт оплаты. «Не посещает» (неоплачиваемый пропуск)
 * в знаменатель не входит: ученик этот урок и не должен был посещать.
 */
function attendanceLine(lesson: MyLesson): string {
  if (lesson.lessonType === 'burned') return 'пропуск сгорел';
  const came = lesson.students.filter((s) => s.status === 'present' || s.status === 'free').length;
  const expected = lesson.students.filter((s) => s.status !== 'skip').length;
  return `пришли ${came} из ${expected}`;
}

function LessonRow({ lesson }: { lesson: MyLesson }) {
  const [open, setOpen] = useState(false);
  const kindLabel = LESSON_KIND_LABEL[lesson.lessonType];
  const color = resolveDirectionColor(lesson.directionColor, lesson.direction ?? lesson.group);

  return (
    <div className={`mlh-row${open ? ' is-open' : ''}`} style={{ '--subject-color': color } as CSSProperties}>
      <button
        type="button"
        className="mlh-toggle"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <div className="pr-date">
          <span className="pr-date-day">{dayMonthOfIso(lesson.date)}</span>
          <span className="pr-date-dow">{weekdayShortOfIso(lesson.date)}</span>
        </div>
        <div className="pr-main">
          <div className="pr-title">
            <span className="pr-group">{lesson.group}</span>
            {kindLabel && <span className={`pr-badge pr-badge--${lesson.lessonType}`}>{kindLabel}</span>}
          </div>
          <div className="pr-formula">{attendanceLine(lesson)}</div>
        </div>
        <svg className="mlh-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {open && (
        lesson.students.length === 0 ? (
          <div className="mlh-students mlh-students--empty">Ученики урока не отмечены.</div>
        ) : (
          <ul className="mlh-students">
            {lesson.students.map((s) => (
              <li key={s.id} className="mlh-student">
                <span className="mlh-name">{s.name}</span>
                <span className={`mlh-mark mlh-mark--${s.status}`}>{STUDENT_STATUS_LABEL[s.status]}</span>
              </li>
            ))}
          </ul>
        )
      )}
    </div>
  );
}

/**
 * Мои уроки — история проведённых уроков текущего преподавателя по месяцам.
 *
 * Список за месяц совпадает со списком «Зарплаты» строка в строку (закреплено
 * тестом на бэке), но денег здесь нет: задача экрана — показать, кто был на
 * уроке. Записывать урок отсюда нельзя — вход в запись живёт в «Календаре».
 */
export default function MyLessonsPage() {
  const [month, setMonth] = useState<Date>(() => firstOfMonthMsk());
  const currentMonth = useMemo(() => firstOfMonthMsk(), []);

  const from = isoDate(month);
  const to = isoDate(addDays(addMonths(month, 1), -1));
  const { data, isLoading, isError, isFetching } = useMyLessons({
    page: 1, pageSize: MONTH_PAGE_SIZE, from, to,
  });

  const rows = data?.rows ?? [];
  const truncated = data ? data.total > rows.length : false;

  return (
    <div className="pr-page">
      <MonthNav title="Мои уроки" month={month} currentMonth={currentMonth} onChange={setMonth} isFetching={isFetching} />

      {isLoading ? (
        <div className="cal-skel" style={{ height: 320 }} />
      ) : isError ? (
        <div className="cal-error">Не удалось загрузить уроки.</div>
      ) : rows.length === 0 ? (
        <div className="cal-empty">В этом месяце проведённых уроков нет.</div>
      ) : (
        <>
          <div className="pr-list">
            {rows.map((lesson) => <LessonRow key={lesson.id} lesson={lesson} />)}
          </div>
          {truncated && (
            <div className="pr-note">Показаны не все уроки месяца: {rows.length} из {data!.total}.</div>
          )}
        </>
      )}
    </div>
  );
}
```

Перед записью проверить сигнатуры `addDays`, `addMonths`, `isoDate`, `firstOfMonthMsk`, `weekdayShortOfIso` в `lib/dates.ts` и `resolveDirectionColor` в `lib/subjects.ts` — если разошлись, подогнать и отметить.

- [ ] **Step 8: Стили**

В `styles/lessons.css` удалить правила `.ml-page` и `.ml-subtitle` (потребителей больше нет; `.ml-updating` оставить — его использует переключатель месяцев) и дописать:

```css
/* «Мои уроки» — история по месяцам. Строка в стиле «Зарплаты» (.pr-*), но
   кликабельная: раскрывает учеников урока. */
.mlh-row { border-left: 3px solid var(--subject-color, var(--accent)); }
.mlh-row + .mlh-row { border-top: 1px solid var(--border2); }

.mlh-toggle {
  display: grid;
  grid-template-columns: 60px 1fr auto;
  align-items: start;
  gap: var(--space-4);
  width: 100%;
  padding: var(--space-4);
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.mlh-toggle:hover { background: var(--bg3); }
.mlh-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }

.mlh-chevron { color: var(--text4); transition: transform .15s; margin-top: 2px; }
.mlh-row.is-open .mlh-chevron { transform: rotate(180deg); }

.mlh-students {
  list-style: none;
  margin: 0;
  padding: 0 var(--space-4) var(--space-4) calc(60px + var(--space-4) * 2);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.mlh-students--empty { font-size: var(--fs-xs); color: var(--text4); }

.mlh-student {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  font-size: var(--fs-sm);
}
.mlh-name { color: var(--text); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.mlh-mark { flex-shrink: 0; font-size: var(--fs-xs); font-weight: 600; }
.mlh-mark--present { color: var(--success); }
.mlh-mark--free    { color: var(--success); }
.mlh-mark--absent  { color: var(--danger); }
.mlh-mark--skip    { color: var(--text4); font-weight: 400; }
.mlh-mark--burned  { color: var(--warning); }

@media (max-width: 640px) {
  .mlh-students { padding-left: var(--space-4); }
}
```

Все токены (`--space-2/3/4`, `--fs-xs/sm`, `--text/--text4`, `--bg3`, `--border2`, `--accent`, `--success`, `--danger`, `--warning`) уже объявлены в `teacher-src/src/styles/tokens.css` — проверить `grep`, новых значений не заводить.

- [ ] **Step 9: Проверка типов**

Run: `cd journal_django/frontend/teacher-src && npx tsc --noEmit`
Expected: чисто. Отдельно проверить, что `MyLessonsPage` больше не импортирует `useCalendar`, `useGroupData`, `LessonForm`, `ExtraLessonRecordModal`, `Modal`, `LessonPopup`, `StatusPill` (они остаются нужны «Календарю» и «Отчёту» — сами файлы не удалять).

---

### Task 3: Сборка и проверка (координатор)

- [ ] полный `pytest -q`;
- [ ] `npx tsc --noEmit` в `teacher-src` и `admin-src`;
- [ ] `npm run build` в `teacher-src` (admin не затронут — проверить `git status` на `admin-dist`);
- [ ] смоук на dev-данных: для реального преподавателя список месяца из `/api/lessons` совпадает с `my_payroll_month`, у уроков есть ученики со статусами;
- [ ] ручная проверка в браузере (пользователь): листание месяцев, раскрытие строки, пометки, сгорание, «Зарплата» выглядит как прежде.
