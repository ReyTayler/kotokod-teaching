# Универсальный перевод/запись ученика в группу

**Дата:** 2026-07-21
**Статус:** утверждён, реализация

## Проблема

Сейчас перевод ученика жёстко привязан к существующей **активной** membership:
`POST /api/admin/memberships/:id/transfer` принимает `membership_id` источника.
Из-за этого:

- Вернувшегося после долгого перерыва ученика (нет активной membership в
  направлении) перевести нельзя — только «добавить» отдельной кнопкой, без
  сохранения истории.
- Перевод запускается маленькой кнопкой `⇄` на каждой карточке группы в блоке
  «Группы ученика» — нет единой масштабируемой точки входа.

## Цель

Одна универсальная, масштабируемая функция и одна точка входа в UI, покрывающая
три сценария: **перевод** (из активной группы), **повторная запись с историей**
(из неактивной группы того же направления), **запись с нуля** (без источника).

## Дизайн

### Бэкенд: `place_student_in_group`

Новая функция в `apps/memberships/repository.py`:

```
place_student_in_group(student_id, to_group_id, from_membership_id=None) -> dict | None
```

Вся логика — в одной `transaction.atomic()`:

1. Целевая группа активна? иначе `TargetGroupUnavailable` (400).
2. Если `from_membership_id` задан (перевод / запись-с-историей):
   - `SELECT ... FOR UPDATE OF self` строки-источника;
   - источник не найден или принадлежит другому ученику → `SourceMembershipInvalid` (400);
   - `from.group_id == to_group_id` → `SameGroupTransfer` (400);
   - направление источника ≠ направление цели → `DirectionMismatch` (400);
3. Ученик уже **активен** в целевой группе → `AlreadyActiveInGroup` (409).
   (Заодно закрывает находку №1 аудита: перезапись `transferred_from`/`start_date`
   у уже активной membership.)
4. Инвариант индивидуальной группы (`_assert_individual_capacity` на цели) → `IndividualGroupFull` (409).
5. Если источник **активен** — деактивируем (`active=false`, `lessons_done`
   сохраняется как честная история). Неактивный источник не трогаем.
6. UPSERT новой membership в цель: `active=true`, `start_date=msk_today()`,
   `lessons_done=0`, `transferred_from = from_membership_id` (или `NULL`).
7. Возврат строки через `_membership_row(new_id)`.

`from_membership_id = None` → чистая запись в любое направление (`transferred_from=NULL`).
Правило «то же направление» действует только когда источник задан (истинный перевод).

Существование ученика проверяется во view (`Student.objects.exists`) → 404.

### Обратная совместимость

`transfer_membership(membership_id, to_group_id)` переписывается как тонкая
обёртка: подтягивает `student_id` из membership и вызывает
`place_student_in_group(student_id, to_group_id, from_membership_id=membership_id)`.
Возврат `None`, если исходная membership не найдена/неактивна (сохраняет
контракт 404). Все 24 существующих теста остаются зелёными.

### Endpoint

```
POST /api/admin/memberships/place
body: { student_id: int, to_group_id: int, from_membership_id?: int }
```

- Права: `ReadStaffWriteSuperAdmin` (как у всех записей memberships).
- Маппинг ошибок: `IndividualGroupFull`/`AlreadyActiveInGroup` → 409;
  `TargetGroupUnavailable`/`DirectionMismatch`/`SameGroupTransfer`/`SourceMembershipInvalid` → 400;
  ученик не найден → 404; успех → 200 (строка новой membership).
- Changelog-label: `('POST', r'^/api/admin/memberships/place$', 'membership.place')`
  (выше правила `^/api/admin/memberships$`). Русский лейбл — в `lib/labels.ts`.
- Старый `/:id/transfer` остаётся (обёртка) для совместимости.

### UI

- Убрать `⇄` со всех карточек в `MembershipsBlock` (проп `onTransfer`
  используется только в профиле ученика).
- В блоке «Группы ученика» (StudentDetailPage) — одна кнопка сверху
  **«Перевести / записать в группу»**, видна всегда (в т.ч. когда активных групп нет).
- Пикер «+Добавить» на профиле ученика **убирается** (`showAddPicker={false}`):
  универсальная кнопка его полностью заменяет. На странице группы
  (`GroupMembersBlock`, `mode: 'byGroup'`) пикер остаётся — там это единственная
  запись со стороны группы. В модалке из списка «Куда» исключаются группы, где
  ученик уже активен (иначе был бы 409) — кнопка становится строгим надмножеством «+Добавить».
- Модалка `PlaceStudentModal`:
  1. **Куда** — активная группа (required).
  2. **Источник истории (откуда)** — со смарт-дефолтом от направления цели:
     активная membership в этом направлении → она; иначе последняя неактивная
     в этом направлении → она; иначе «Без истории (новая запись)».
     Список: активные + неактивные того же направления + «Без истории».
  3. Живая подпись: «Перевод из «A2» — 12 отработанных уроков перейдут в историю» /
     «Новая запись, без истории».
- Данные: `useMemberships` расширяется опцией `include_inactive`, чтобы получить
  историю ученика для списка источников. `groups`/`directions` уже загружены на странице.

## Тесты

Юнит `place_student_in_group`:
- перевод из активной (деактивация + `transferred_from` + история);
- запись-с-историей из неактивной того же направления (источник не деактивируется);
- чистая запись `from=None` в новое направление (`transferred_from=NULL`);
- отказ: already-active в цели (409), same-group, different-direction, source
  чужого ученика, individual-full;
- `transfer_membership`-обёртка по-прежнему работает.

API `/place`: RBAC (401 / teacher 403 / manager 403 / admin 403 / superadmin 200),
смарт-кейсы (перевод, запись-с-историей, чистая запись), 404 при несуществующем ученике.

## Вне рамок

- «Добавить ученика» на странице группы (`GroupMembersBlock`) остаётся на
  `add_membership` — это enrollment со стороны группы, не перевод.
- Пересборка сделок продлений/финансов не требуется: баланс и продления —
  на уровне ученика, перевод внутри направления их не двигает.
