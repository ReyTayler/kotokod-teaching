# Разметка перевода в матрице посещаемости — Design

**Date:** 2026-07-13
**Status:** Approved by user in брейнсторме
**Scope:** Backend (`journal_django/apps/groups`), Frontend (`journal_django/frontend/admin-src/src/shared/progress`, общий для admin и teacher SPA).
**Дополняет:** [`2026-07-13-student-group-transfer-design.md`](2026-07-13-student-group-transfer-design.md) — этот документ фиксирует уточнение требования, полученное после первой реализации: перевод должен быть виден не только текстовой плашкой на карточке ученика, но и как визуальная разметка в матрице посещаемости группы (по аналогии со старыми таблицами, где переведённому ученику красили особым цветом уже пройденные уроки).

## Проблема

Уже реализованная плашка-текст на карточке membership («Переведён из «X» — там отработано N уроков») достаточна для контекста страницы ученика, но не решает исходный кейс: куратор/учитель смотрит матрицу посещаемости НОВОЙ группы (`GroupProgressView` — лента цветных плиток «ученик × урок урока», общая для admin SPA и teacher SPA) и видит у переведённого ученика пустые/плановые ячейки в начале ряда — выглядит так, будто прогресса нет, хотя реально N уроков уже отработано в другой группе.

## Решение

N ячеек ряда переведённого ученика (N = `min(отработано в старой группе, всего слотов группы)`) красятся отдельным статусом «Перевод». Разметка считается на лету по существующему полю `GroupMembership.transferred_from` — новых полей в БД не требуется.

**Важный нюанс механики.** Столбцы матрицы — это слоты уроков ГРУППЫ (общие для всех её учеников, привязаны к реальным датам занятий этой конкретной группы), а не личный счётчик переведённого ученика. Если у новой группы к моменту перевода уже есть проведённые уроки (для других участников) и реальная посещаемость этого студента в новой группе попадает на позицию ≤ N, слепая «перекраска первых N позиций подряд» спрятала бы настоящую отметку о посещении под статусом «Перевод». Поэтому красим не «первые N позиций», а **первые N ещё пустых (`cell === null`) ячеек** этого ученика — реальные `true`/`false` не трогаем никогда, они всегда показываются как есть. В типичном случае (у студента ещё нет реальных отметок в новой группе на момент перевода) результат неотличим от «первые N подряд, затем реальные»; в редком случае (студент попал в уже продвинутую группу) закрашенные позиции могут быть не строго подряд, но реальные данные о посещении никогда не скрываются.

Матрица (`apps.groups.repository.get_group_progress`) уже переиспользуется и admin SPA (`GET /api/admin/groups/:id/progress`), и teacher SPA (`GET /api/group-progress`, делегирует в тот же repository-метод) — правка в одном месте автоматически покрывает оба SPA. Presentational-компонент `GroupProgressView.tsx` физически один файл (`admin-src/src/shared/progress/`), teacher-src импортирует его через алиас — правка тоже одна.

## Backend

`apps/groups/repository.py::get_group_progress(group_id)`:

1. В запрос `members` (строки ~400-405) добавить join на `transferred_from`:
   ```python
   members = list(
       GroupMembership.objects
       .filter(group_id=group_id, active=True)
       .order_by('student__full_name')
       .values(
           'student_id', name=F('student__full_name'),
           transferred_from_id=F('transferred_from_id'),
           transferred_from_lessons_done=F('transferred_from__lessons_done'),
           transferred_from_group_name=F('transferred_from__group__name'),
       )
   )
   ```

2. В цикле построения строки ученика (строки ~452-479) посчитать:
   ```python
   transferred_lessons = 0
   transferred_from_group_name = None
   if member['transferred_from_id']:
       transferred_lessons = min(
           math.floor(float(member['transferred_from_lessons_done'] or 0)),
           slot_count,
       )
       if transferred_lessons > 0:
           transferred_from_group_name = member['transferred_from_group_name']
   ```
   Добавить оба поля (`transferred_lessons`, `transferred_from_group_name`) в возвращаемый dict ученика. Массив `cells` не меняется — статус «Перевод» для первых N ячеек накладывается на фронте по счётчику, backend только сообщает факт и число.

Ответ `get_group_progress` не проходит через сериализатор (`GroupProgressView` в `apps/groups/views.py` отдаёт dict напрямую через `Response(data)`) — сериализатор трогать не нужно.

## Frontend

`journal_django/frontend/admin-src/src/shared/progress/types.ts`:
- `ProgressStudent` получает `transferred_lessons: number;` и `transferred_from_group_name: string | null;`.

`journal_django/frontend/admin-src/src/shared/progress/GroupProgressView.tsx`:
- `type CellStatus = 'present' | 'absent' | 'planned' | 'transferred';`
- `STATUS_LABEL.transferred = 'Перевод'`.
- В легенде — новый чип `<span className="progress-chip is-transferred" />Перевод`.
- В рендере ленты (`s.cells.map((cell, i) => ...)`): статус ячейки вычисляется с учётом «бюджета» переведённых уроков, расходуемого слева направо ТОЛЬКО на `cell === null`:
  ```ts
  let transferredLeft = s.transferred_lessons;
  const cellStatuses = s.cells.map((cell) => {
    if (cell === null && transferredLeft > 0) { transferredLeft--; return 'transferred'; }
    return cellStatus(cell);
  });
  ```
  Реальные `true`/`false` (посещение уже отмечено в НОВОЙ группе) никогда не перекрываются статусом «Перевод» — бюджет просто продолжает искать следующую пустую ячейку. Вычисляется один раз на строку ученика (перед рендером `cells.map`), а не инлайн внутри JSX.
- Тултип: при статусе `transferred` вместо даты/«Не проведён» показывать «Перевод из «{transferred_from_group_name}»» — `TipState` получает опциональное поле `transferredFromGroupName`.

`journal_django/frontend/admin-src/src/shared/progress/progress.css`:
- По аналогии с `.is-present`/`.is-absent`/`.is-planned` добавить `.is-transferred` для `.progress-chip`, `.progress-sq`, `.progress-sq:hover`, `.progress-tip` — цвет на основе `var(--accent)`/`var(--accent-soft)` (тот же токен, что уже использует кнопка «⇄ Перевести» в `MembershipsBlock`), без хардкода цветов.

## Границы фичи

- Текстовая плашка на карточке membership (`MembershipsBlock.tsx`) остаётся как есть — обе разметки сосуществуют (плашка — контекст на странице ученика, матрица — визуальный обзор на странице/вкладке группы).
- Сырые `cells` (present/absent/None) не переписываются под перевод — источник правды не меняется, только отображение.
- Округление `lessons_done` (Decimal с шагом 0.5 для half-lesson) вниз (`floor`) — половина урока не даёт лишнюю закрашенную ячейку.
- Не создаём отдельный backend-эндпоинт — используем существующий `get_group_progress`, общий для обоих SPA.

## Тестирование

- `apps/groups/tests/` (репозиторий/API теста progress, найти существующий файл по `get_group_progress`) — новый тест: у ученика с `transferred_from` (`lessons_done=32` в старой группе) `transferred_lessons` в ответе равен `min(32, slot_count)`, у обычного участника — `0`.
- Тест на `floor` для half-lesson (`lessons_done=31.5` → `transferred_lessons=31`).
- Тест, что `transferred_lessons` не превышает `total_slots` (если в старой группе отработано больше, чем есть слотов в новой — направление то же самое, `total_lessons` общий, но проверить граничный случай на всякий случай).
- Frontend: без автотестов (проект не имеет фронтенд-тестового фреймворка) — typecheck + `npm run build` + ручная/curl-проверка по аналогии с предыдущей фичей.

## Дополнение: многократный перевод (A→Б→В→...)

**Проблема.** `GroupMembership.transferred_from` — self-FK на НЕПОСРЕДСТВЕННО предыдущую membership. Если ученика перевели дважды подряд (А→Б→В), оба потребителя (плашка на карточке membership и `transferred_lessons` в матрице) сейчас берут `lessons_done` только с одного хопа назад (из Б) — уроки, отработанные в А, теряются из виду и не попадают ни в число на плашке, ни в закрашенные ячейки матрицы в В.

**Решение — не новая модель, а обход существующей цепочки.** Схему менять не нужно: раз В.transferred_from = Б, а Б.transferred_from = А (была установлена при переводе А→Б), это уже связный список. Нужна только функция, которая идёт по нему назад и суммирует `lessons_done` на каждом шаге.

`apps/memberships/repository.py` — новая публичная функция (используется и `apps.memberships`, и `apps.groups`):

```python
_MAX_TRANSFER_CHAIN = 20  # защитный лимит — реальные цепочки в разы короче


def cumulative_transferred_lessons(transferred_from_id: Optional[int]) -> Decimal:
    """
    Сумма lessons_done по всей цепочке переводов, начиная с transferred_from_id
    (сама текущая membership НЕ включается — только предки).

    Ученика могут перевести несколько раз подряд (А→Б→В→...) — transferred_from
    каждой membership указывает на непосредственно предыдущую, образуя связный
    список; функция проходит его назад до конца.

    Защита от цикла: если ученика переводят обратно в группу, где он уже был
    раньше в этой же цепочке, add_membership-паттерн (ON CONFLICT DO UPDATE)
    РЕАКТИВИРУЕТ старую membership-строку той же группы и перезаписывает её
    transferred_from на текущую — из-за этого цепочка технически может
    зациклиться (А.transferred_from → В → Б → А). `seen`-множество и
    _MAX_TRANSFER_CHAIN останавливают обход, не давая ему повиснуть; результат
    в этом редком случае — best-effort сумма до точки повторного визита, не
    гарантированно полная, но и не бесконечный цикл.
    """
    total = Decimal('0')
    seen: set[int] = set()
    current_id = transferred_from_id
    while current_id is not None and current_id not in seen and len(seen) < _MAX_TRANSFER_CHAIN:
        seen.add(current_id)
        row = (
            GroupMembership.objects
            .filter(id=current_id)
            .values('lessons_done', 'transferred_from_id')
            .first()
        )
        if row is None:
            break
        total += row['lessons_done'] or Decimal('0')
        current_id = row['transferred_from_id']
    return total
```

**Что показываем.** Название группы-источника (`transferred_from_group_name`, и в плашке, и в матрице) — по-прежнему НЕПОСРЕДСТВЕННО предыдущая группа (одиночный хоп через существующий F()-джойн `transferred_from__group__name`) — это отвечает на вопрос «откуда только что пришёл», текст плашки/тултипа не меняется. А вот число уроков (`transferred_from_lessons_done` в плашке, `transferred_lessons` в матрице) теперь — СУММА по всей цепочке через `cumulative_transferred_lessons`, а не одиночный хоп.

**Где заменить:**
- `apps/memberships/repository.py::_membership_row` и `list_memberships` — убрать F()-джойн `transferred_from_lessons_done=F('transferred_from__lessons_done')`, вместо него после сборки строки(-ок) вызвать `cumulative_transferred_lessons(row['transferred_from_id'])` (только если `transferred_from_id` не `None`, иначе оставить `None` — как сейчас).
- `apps/groups/repository.py::get_group_progress` — убрать F()-джойн `transferred_from_lessons_done=F(...)` из запроса `members`, в цикле построения строки ученика заменить `member['transferred_from_lessons_done']` на `cumulative_transferred_lessons(member['transferred_from_id'])`.

**Производительность.** Обход цепочки — доп. запросы (по одному на хоп), но ТОЛЬКО для строк, где `transferred_from_id` не `None` — переводы редки, у подавляющего большинства строк это поле пустое и функция не вызывается вовсе. Не батчим намеренно (YAGNI) — при типичной цепочке в 1-2 хопа и малом числе переведённых учеников на школу это не влияет на бюджет VPS ощутимо; если в будущем переводы станут массовым сценарием, можно будет вернуться к батч-версии (одним рекурсивным SQL или предзагрузкой всех memberships направления в память).

**Тесты (добавить в уже существующие файлы):**
- `apps/memberships/tests/test_transfer_membership.py` — новый тест: перевод А→Б→В, у В `transferred_from_lessons_done` = `lessons_done(А) + lessons_done(Б)`, `transferred_from_group_name` = имя Б (не А).
- `apps/groups/tests/test_progress_api.py` (класс `TestTransferredLessons`) — аналогичный тест на `transferred_lessons` в матрице для двухходового перевода.
- Тест на цикл (перевод А→Б→В→А обратно в исходную группу через реактивацию) — `cumulative_transferred_lessons` не виснет, возвращает конечное число за ограниченное время.
