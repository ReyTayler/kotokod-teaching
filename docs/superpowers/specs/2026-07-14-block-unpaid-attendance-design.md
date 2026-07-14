# Блокировка отметки посещения ученикам без оплаченных уроков

Дата: 2026-07-14

## Проблема

В форме отметки урока (`LessonForm`, teacher SPA) преподаватель может отметить
присутствие ЛЮБОГО ученика группы, включая тех, у кого баланс оплаченных уроков
уже исчерпан (`remaining <= 0`). Нужно запретить это: и на фронте (UX), и на
бэке (defense-in-depth — фронт можно обойти прямым запросом к API).

`remaining` — общий баланс ученика (purchased − attended, единый пул по всем
направлениям), уже вычисляется батчем в `apps.finances.repository.balances_for_students`
и уже приходит в `GET /api/getData`/`getAllData` как `TStudent.remaining`
(`journal_django/apps/teacher_spa/repository.py:136-144`,
`journal_django/frontend/teacher-src/src/lib/types.ts:36-43`). Новый источник
данных не нужен — используем этот же расчёт.

## Backend (`journal_django/apps/teacher_spa/`)

### `services.py::submit_lesson`

После построения `by_name`/`attendance`/`present_student_ids` (шаг 5, уже
резолвит `student_id` по имени) — новый шаг 5b, ДО открытия `transaction.atomic()`:

```python
if present_student_ids:
    balances = finances_repository.balances_for_students(present_student_ids)
    blocked_names = [
        s['name'] for s in students
        if s['present'] and by_name.get(s['name'])
        and balances.get(by_name[s['name']]['student_id'], 0) <= 0
    ]
    if blocked_names:
        return {
            'success': False,
            'error': f'У учеников без оплаченных уроков нельзя отметить посещение: {", ".join(blocked_names)}.',
        }
```

Импорт: `from apps.finances.repository import balances_for_students` — та же
функция и тот же стиль импорта, что уже использует `apps/teacher_spa/repository.py:22`
(и по аналогии с `from apps.scheduling.repository import link_facts`, добавленным
в этот же файл ранее). Один батч-запрос, без N+1 — тот же паттерн, что и
остальной `read_all_students`.

Формат ошибки — `{'success': False, 'error': ...}`, тот же паттерн, что «Группа
не найдена» и блокировка будущей даты в этой же функции (не `ValidationError`
сериализатора — см. обоснование в `docs/superpowers/specs/2026-07-13-block-future-lesson-marking-design.md`,
раздел Backend: `custom_exception_handler` иначе съедает текст ошибки).

Проверка — ДО транзакции: при нарушении урок не создаётся вообще (ни `lessons`,
ни `attendance`, ни `payroll`, ни инкремент счётчиков) — тот же принцип, что и
у остальных ранних валидаций (`403 Занятие не назначено`, `Группа не найдена`).

Баланс считается на СЕРВЕРЕ в момент отправки (не из клиентского payload) —
клиент не присылает remaining вообще, подделать нечем.

## Frontend (`components/lessons/LessonForm.tsx`)

- `isBlocked(s: TStudent) => s.remaining <= 0`.
- Начальное состояние `present`: `Object.fromEntries(groupData.students.map((s) => [s.name, !isBlocked(s)]))` —
  заблокированные стартуют невыбранными.
- Клик по такому ученику — no-op: кнопка получает `disabled` + не вызывает
  `setPresent`.
- «Отметить всех/Снять всех» (`toggleAll`) применяется только к незаблокированным:
  заблокированные всегда остаются `false`. Текст кнопки («Отметить всех» ↔
  «Снять всех») теперь считается по `allPresent`, где `allPresent` — все
  НЕзаблокированные отмечены (а не вообще все ученики).
- Визуально: кнопка ученика получает класс `is-blocked` (приглушённый, как
  `disabled`), текст состояния — «Нет оплаты» вместо «Пришёл»/«Не пришёл».
- **Заодно фикс соседнего бага**: текущий групповой баннер `debtWarning`
  (`journal_django/frontend/teacher-src/src/components/lessons/LessonForm.tsx:84-85`)
  считает остаток только по `groupData.students[0]` — неверно для группы из
  нескольких учеников с разными балансами. Раз мы уже вводим точный per-student
  расчёт (`isBlocked`), баннер переписывается на список реально заблокированных
  имён: `Нет оплаченных уроков: <имена>. Отметить их нельзя — сообщите менеджеру {pm}.`
  Рендерится, только если список непуст (иначе, как и сейчас, не показывается).

### Стили (`styles/groups.css`)

Рядом с существующим `.lf-student.is-present` (строки 165-170) — новый модификатор:
```css
.lf-student.is-blocked {
  opacity: .5;
  cursor: not-allowed;
}
.lf-student.is-blocked .lf-student-state { color: var(--danger); }
```
Используем уже существующие design-токены (`--danger` — есть в `tokens.css`),
никаких хардкод-цветов.

## Тесты

Backend (`apps/teacher_spa/tests/test_teacher_spa_api.py`):
1. Ученик с `remaining <= 0` (задать через прямую вставку в `payments`/`lesson_attendance`
   или напрямую замокать/выставить баланс — по образцу существующих фикстур)
   и `present: true` → `resp.json() == {'success': False, 'error': ...}`,
   `lessons`/`attendance`/`payroll` не созданы, `lessons_done` не инкрементирован.
2. Тот же ученик с `present: false` → урок создаётся нормально (200, `success: true`).
3. Существующие тесты (`test_submit_lesson_success` и т.п., где `remaining` у
   фикстур обычно положительный/не выставлен явно — то есть 0 по умолчанию,
   раз оплат нет) — нужно свериться: если тестовые фикстуры не создают
   `Payment`, `balances_for_students` вернёт 0 → и старые тесты на успешную
   отправку с `present: true` сломаются новой проверкой. Придётся добавить
   тестовым ученикам оплату (INSERT в `payments`) в затронутых фикстурах/тестах,
   либо завести отдельный фикстурный `student_fixture` с оплатой. Это выясняется
   и чинится на этапе реализации (TDD — сначала прогон существующего сьюта
   покажет, какие тесты просели).

Frontend: ручная проверка в браузере (в teacher-src нет раннера компонентных
тестов — не заводим ради одной фичи, как и в прошлой спеке).

## Вне охвата

- Изменение самого расчёта баланса (`balances_for_students`) — не трогаем,
  используем как есть.
- Admin SPA — там свой флоу учёта посещаемости, не затронут.
- Возможность ручного «разрешения в долг» (override для конкретного урока) —
  не запрошено, не делаем (YAGNI).
