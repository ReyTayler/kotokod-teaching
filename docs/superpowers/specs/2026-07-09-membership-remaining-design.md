# `remaining` у membership — вычисляемый общий баланс ученика — Design

**Date:** 2026-07-09
**Status:** Approved by user in брейнсторме
**Scope:** Backend (`journal_django/apps/finances`, `memberships`, `teacher_spa`, `students`, `groups/importers`), без изменений в admin-фронте.

## Проблема

`group_memberships.remaining` — сырая колонка, которую можно было вручную выставить через `PATCH /api/admin/memberships/:id`. Ничто в приложении не пересчитывает её при отметке посещаемости (в отличие от `lessons_done`, который инкрементируется в `apps/lessons/repository.py` на каждом уроке). В результате поле рассинхронизируется с реальностью и может уйти в минус без какой-либо валидации на уровне БД (у Поповой Юлии было найдено `remaining = -1` при `lessons_done = 29`).

Расследование (см. переписку) показало: полноценного «оплачено за конкретную группу» в системе не существует — `payments` привязаны к ученику + `direction_id` только как информационный тег, а с 2026-07-08 общий баланс ученика — единый пул по всем направлениям сразу (`apps/finances/balance.py`). Значит «остаток» на карточке группы физически не может быть привязан к этой группе — он может быть только общим балансом ученика.

## Решение

`remaining` перестаёт быть хранимым полем и становится вычисляемым — тем же числом, что и общий баланс ученика (`purchased − attended`, единый пул), продублированным на каждую membership-строку этого ученика. Хранимая колонка удаляется, ручная запись через API убирается.

## Компоненты

### 1. `apps/finances/repository.py` — батч-вычислитель (новое)

```python
def balances_for_students(student_ids: Iterable[int]) -> dict[int, int | float]
```

- Один агрегат по `Payment` (`.values('student_id').annotate(Sum(subscriptions_count*4))`), один по `LessonAttendance` (`present=True`, та же группировка по `student_id`, тот же `_attended_units_case()` что и в `balance_for_student`).
- Разница `purchased − attended` на каждый id, `_js_number` на выходе. Функция сама дефолтит каждый запрошенный `student_id` до `0`, если по нему нет ни оплат, ни посещений — итоговый словарь всегда содержит ключ на каждый переданный id, вызывающему коду не нужно самому думать про `.get(id, 0)`.
- `balance_for_student(student_id)` — существующая сигнатура сохраняется, но переиспользует `balances_for_students([student_id])` внутри, чтобы формула баланса жила в одном месте.
- Без изменений: `paid_by_direction_rows`, `attended_by_direction_rows` — они информационные разбивки, не трогаем.

**Почему батч, а не N+1:** `teacher_spa.read_all_students()` тянет вообще все активные membership по всей школе разом (все учителя, все группы) — на 2 CPU/2 ГБ VPS вызывать `balance_for_student` в питоновском цикле по каждой строке недопустимо. Один батч-запрос на все distinct `student_id`, встреченные в выдаче.

### 2. Точки чтения — переключить на вычисленное значение

- **`apps/memberships/repository.py`**: `list_memberships`, `add_membership`, `update_membership` — после сборки строк собрать distinct `student_id` из результата, вызвать `balances_for_students`, подставить вместо чтения сырой колонки `remaining`. Форма ответа (ключ `remaining` в словаре/сериализаторе) не меняется.
- **`apps/teacher_spa/repository.py`**: `read_all_students()` — то же самое: собрать distinct `student_id` по всем строкам среза школы, один батч-вызов, раздать по студентам при построении `grp['students']`.
- **`apps/students/repository.py`**: `student_stats()` — убрать `gm.remaining` из raw SQL (и `SELECT`, и `GROUP BY`), после получения `groups_raw` вызвать `balance_for_student(student_id)` один раз (запрос уже скоуплен на одного ученика — не батч), подставить это число в `remaining` каждой строки `group_stats` (один и тот же общий баланс на все группы одного ученика).

### 3. Убрать ручную запись и хранимую колонку

- `apps/memberships/serializers.py`: убрать поле `remaining` из `MembershipWriteSerializer` и `MembershipUpdateSerializer` (POST/PATCH больше не принимают `remaining`). `MembershipReadSerializer.remaining` остаётся (только вывод, значение теперь вычисляемое).
- `apps/memberships/models.py`: убрать поле `remaining` из `GroupMembership`.
- Миграция (`makemigrations memberships`): дропает колонку `remaining` в `group_memberships`; pghistory сам подхватит изменение в событийной модели/триггере при генерации миграции (аналогично прошлым миграциям pghistory в проекте — паттерн уже используется).
- `apps/groups/importers/direction_history.py`: убрать мёртвую запись `'remaining': 0` при создании архивной membership (строка ~290, ключ `remaining` в `defaults`).

### 4. Admin-фронт

Без изменений сверх уже сделанного в этой сессии — «Осталось» с карточек групп в admin убрано и обратно не возвращается. API и teacher SPA получают верное число, тип `GroupMembership.remaining` в `shared-types.ts` не меняется (значение всё так же приходит числом/строкой numeric).

## Тестирование

- Новый unit-тест на `balances_for_students`: несколько студентов разом, студент без оплат (0), студент с отрицательным балансом (посещений больше оплаченного), студент вне переданного списка не должен ломать остальных.
- Обновить фикстуры/ассерты, которые пишут или проверяют сырую колонку `remaining`:
  - `apps/memberships/tests/test_memberships_repository.py`, `test_individual_group_limit.py`
  - `apps/teacher_spa/tests/test_teacher_spa_repository.py`, `test_teacher_spa_api.py`
  - `apps/students/tests/test_students_repository.py`
  - `apps/renewals/tests/test_rebuild.py`, `test_lesson_progress.py` (raw `INSERT INTO group_memberships (..., remaining, ...)`)
  - `apps/groups/tests/test_direction_history_importer.py`
  - `apps/lessons/tests/conftest.py`
- Прогнать полный набор тестов после миграции (модели/фикстуры, ссылающиеся на несуществующую колонку, должны быть найдены и исправлены до зелёного прогона).
- Ручная проверка: у Поповой Юлии (student_id=202) `remaining` на всех её membership-карточках (через API/`teacher_spa`) должен совпасть с её реальным общим балансом (`purchased − attended` по всем направлениям), а не с произвольным числом на конкретной группе.

## Что явно не делаем

- Не привязываем оплаты к конкретной группе (архитектурно это отдельная, гораздо более крупная фича — сейчас payments скоуплены на ученика).
- Не возвращаем «Осталось» в admin-карточки групп.
- Не трогаем `paid_by_direction_rows` / `attended_by_direction_rows` — они остаются информационными разбивками по направлению, не по группе.
