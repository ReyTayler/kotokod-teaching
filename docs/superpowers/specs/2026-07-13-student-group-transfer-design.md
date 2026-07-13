# Перевод ученика между группами одного направления — Design

**Date:** 2026-07-13
**Status:** Approved by user in брейнсторме
**Scope:** Backend (`journal_django/apps/memberships`, `apps/changelog`), Frontend (`journal_django/frontend/admin-src`, компонент `MembershipsBlock` и страница ученика).

## Проблема

Ученик может уйти из одной группы направления в другую группу того же направления, успев отзаниматься в прежней группе некоторое количество уроков (например 32). Технически перевод уже возможен вручную двумя отдельными операциями (`DELETE` старой membership + `POST` новой), но:

- это не одна атомарная операция (нет транзакционной гарантии, легко забыть один из двух шагов);
- на карточке новой группы у ученика нет никакого следа, что он уже занимался этим направлением раньше — новая membership стартует с `lessons_done=0` без каких-либо пояснений, из-за чего создаётся ощущение, что прогресс «потерялся».

## Что НЕ является проблемой (проверено по коду)

Вопреки исходной гипотезе задачи, следующее **уже не завязано на группу/направление** и переводом не ломается:

- **Баланс ученика** (`apps/finances/balance.py`) — единый пул `purchased − attended` по всему ученику, без разбивки по направлению (с 2026-07-08).
- **Прогресс продления** (`apps/renewals/models.py`, `RenewalDeal`) — сущность ученика, `cycle_no` считается от суммарной посещаемости по всем направлениям сразу, ни `group_id`, ни `direction_id` в модели нет.
- **Историческая посещаемость** (`Lesson`/`LessonAttendance`) — физически и корректно остаётся привязанной к старой группе через `lesson.group_id`; трогать её не нужно.

Единственное, что реально привязано к конкретной группе и требует переноса/отображения — счётчик `GroupMembership.lessons_done` (инкрементируется в `apps/lessons/repository.py` в той же транзакции, что и отметка посещаемости — это честное «отработано именно в этой группе», используется в том числе в учительской статистике/payroll).

## Решение

Перевод — это **атомарная операция** (деактивировать старую membership + создать/реактивировать новую), не переносящая `lessons_done` в счётчик новой группы (счётчик остаётся честным), но помечающая новую membership ссылкой на старую, чтобы на UI можно было явно показать «переведён из группы X, там отработано N уроков».

## Модель данных

`apps/memberships/models.py`, `GroupMembership`:

```python
transferred_from = models.ForeignKey(
    'self',
    null=True, blank=True,
    on_delete=models.SET_NULL,
    related_name='transferred_to',
    help_text='Membership, из которой ученик был переведён (если применимо).',
)
```

Заполняется только сервисом перевода. Обычный `add_membership` (ручное добавление в группу) его не трогает — значение остаётся `NULL`. Требуется миграция (`makemigrations memberships`); pghistory-триггер модели подхватит новую колонку автоматически (аналогично прошлым миграциям в проекте).

## Backend

### `apps/memberships/repository.py` + `services.py`

Новая функция:

```python
def transfer_membership(membership_id: int, to_group_id: int) -> dict
```

В одной `transaction.atomic()`:

1. Найти активное membership по `membership_id` (`active=True`) — иначе `NotFound` (404).
2. Найти целевую группу `to_group_id` — должна быть `active=True`, иначе `ValidationError` (400).
3. Проверить `to_group.direction_id == old.group.direction_id` — иначе `ValidationError` (400, «перевод разрешён только внутри направления»).
4. Проверить `to_group_id != old.group_id` — иначе `ValidationError` (400, «нельзя перевести в ту же группу»).
5. Проверить вместимость индивидуальной группы (переиспользовать существующую `_assert_individual_capacity(to_group_id, exclude_student_id=old.student_id)`) — при конфликте `IndividualGroupFull` → 409 (как в `add_membership`/`update_membership`).
6. Деактивировать старую membership: `active=False` (реальный `lessons_done` остаётся как есть — это честная история).
7. UPSERT новой membership в целевой группе тем же `bulk_create(..., update_conflicts=True, unique_fields=['group', 'student'], update_fields=['active', 'transferred_from', 'start_date'])` паттерном, что и в `add_membership` — покрывает и случай «ученик впервые в этой группе», и случай «ученик туда уже когда-то возвращается» (была неактивная membership). `lessons_done` не проставляется (остаётся 0 на вставке / сохраняется прежнее значение при реактивации — как в текущем `add_membership`). `start_date` = дата перевода (`timezone.localdate()`). `transferred_from_id` = id старой membership.
8. Вернуть строку новой membership (переиспользовать существующий `_membership_row`/сериализацию с добавленными полями `transferred_from_group_name`, `transferred_from_lessons_done`).

`services.transfer_membership()` — тонкая делегирующая обёртка, как остальные функции сервиса.

### API

`POST /api/admin/memberships/{id}/transfer`

- Тело: `{"to_group_id": <int>}`.
- Права: `ReadStaffWriteSuperAdmin` (тот же класс, что у остальных мутирующих методов `MembershipDetailView`).
- Ответы: `200` с новой membership; `400` при валидационных ошибках (не то направление / та же группа / невалидный `to_group_id`); `404` если исходная membership не найдена/неактивна; `409` при переполненной индивидуальной группе.
- Новый сериализатор `MembershipTransferSerializer` с единственным полем `to_group_id` (`IntegerField(required=True)`).
- Отдельный класс `MembershipTransferView(APIView)` (по образцу `MembershipListCreateView`/`MembershipDetailView` — один класс на один URL-паттерн), метод `post`. Роут `memberships/<int:pk>/transfer/` регистрируется в `apps/memberships/urls.py` рядом с существующими.

### Changelog

`apps/changelog/labels.py`: добавить правило `('POST', re.compile(r'^/api/admin/memberships/\d+/transfer$'), 'membership.transfer')` **до** более общего правила `POST /api/admin/memberships$` (порядок важен для regex-матчинга — сверить с существующим списком).

`apps/changelog/summary.py`: добавить ветку для `operation == 'membership.transfer'` с человекочитаемым описанием (по образцу соседних `membership.create`/`membership.delete`), упоминающим старую и новую группу.

### Сериализатор чтения

`apps/memberships/serializers.py`, `MembershipReadSerializer` (или эквивалент, собирающий словарь строки в repository) — добавить read-only:

- `transferred_from_group_name: str | None`
- `transferred_from_lessons_done: str | None` (numeric как строка, как остальные Decimal-поля в проекте)

Достаются через `select_related('transferred_from__group')` в `list_memberships`/`_membership_row`. Поля добавляются на уровне API для всех membership (не только для admin/byStudent-режима) — это дёшево и не ограничивает будущее использование (например teacher SPA), даже если UI сейчас строится только под один сценарий.

## Frontend (admin SPA)

### `MembershipsBlock.tsx`

- На каждой карточке (`mode: 'byStudent'`) рядом с существующей кнопкой «×» (Убрать) — новая кнопка **«⇄ Перевести»**. Кнопка на конкретной карточке, а не одна общая кнопка на странице — однозначно понятно, какую membership переводим, даже если у ученика несколько активных групп по разным направлениям.
- Клик открывает модалку `TransferMembershipModal(membership, groups, directions)`:
  - Список целевых групп: активные группы (`active=true`) того же `direction_id`, что и `membership.group_id`, исключая саму текущую группу.
  - `SelectInput` (не нативный `<select>`, по конвенции проекта) + кнопка «Перевести».
  - На confirm → `POST /api/admin/memberships/{id}/transfer`, `onSuccess` → invalidate `['memberships']`, `['students']`, `['groups']`, тост «Переведён».
- В `renderCard` на `StudentDetailPage.tsx` — если у membership есть `transferred_from_group_name`, добавить в `meta` (или отдельной строкой в `membership-card__stats`) плашку: *«Переведён из «{transferred_from_group_name}» — там отработано {transferred_from_lessons_done} ур.»*.

### `shared-types.ts`

Добавить в тип `GroupMembership`:

```typescript
transferred_from_group_name?: string | null;
transferred_from_lessons_done?: string | null;
```

### Границы фичи (явно НЕ делаем)

- Не переносим `lessons_done` в счётчик новой группы — счётчик остаётся честным (реальные уроки именно в этой группе), используется в учительской статистике/payroll.
- Не строим отдельный блок «История групп» на странице ученика — только плашка на карточке активной (целевой) группы.
- Не разрешаем перевод между разными направлениями — только внутри одного направления (валидация на бэкенде, фильтр списка групп на фронте).
- Не трогаем `byGroup`-режим `MembershipsBlock` (карточка ученика на странице самой группы) — кнопка перевода есть только в `byStudent`-режиме на странице ученика.
- Не трогаем teacher SPA.
- Не добавляем `end_date` в `GroupMembership` — момент перевода при необходимости восстановим из pghistory-журнала (уже готовая инфраструктура changelog), отдельное поле не нужно.

## Тестирование

- `apps/memberships/tests/test_memberships_repository.py`: `transfer_membership` — успешный перевод (старая деактивирована с сохранённым `lessons_done`, новая создана/реактивирована с `transferred_from` и `start_date`), 400 на разное направление, 400 на ту же группу, 404 на несуществующую/неактивную исходную membership, 409 на переполненную индивидуальную группу (переиспользовать существующие фикстуры `test_individual_group_limit.py`), кейс реактивации ранее существовавшей (неактивной) membership в целевой группе.
- `apps/memberships/tests/test_memberships_api.py`: RBAC (403 без прав), 200 успешный путь, коды ошибок из списка выше.
- Сериализатор: `transferred_from_group_name`/`transferred_from_lessons_done` корректно подтягиваются при чтении.
- `apps/changelog/tests/test_summary.py`: описание для `membership.transfer`.

## Что явно не делаем (сводно)

- Перенос `lessons_done` между группами.
- Общий список истории групп на странице ученика.
- Кросс-направленческие переводы.
- Изменения в teacher SPA и в `byGroup`-режиме компонента.
- Поле `end_date` у `GroupMembership`.
