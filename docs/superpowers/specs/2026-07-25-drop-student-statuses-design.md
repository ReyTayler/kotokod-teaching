# Удаление статусов ученика: стадия сделки как единственный статус

**Дата:** 2026-07-25
**Статус:** утверждено пользователем, план реализации не написан

## Проблема

У ученика есть `enrollment_status` (`enrolled` / `frozen` / `declined`) — параллельный
жизненный цикл рядом с воронкой «Продлений». Он не даёт менеджеру ничего, чего не
даёт стадия сделки, но тянет за собой тяжёлый каскад:

- `students.services.change_student_status()` в одной транзакции снимает членства,
  сдвигает хвост индивидуального расписания (`freeze_individual_group`), отменяет
  будущие плановые уроки, проверяет гейт доп.уроков и двигает сделку
  (`engine.freeze_deal` / `decline_deal`);
- `StudentStatusModal` — 470 строк: выбор членств чекбоксами, дран-превью сдвига
  расписания, два диалога подтверждения (урок в день заморозки, сброс разовых операций);
- стадия `frozen` искусственно помечена `is_auto=True`, чтобы её нельзя было двигать
  руками — вход только через смену статуса; доска перехватывает drop в «Заморожен» и в
  зону «Ушёл» и открывает вместо переноса модалку статуса.

Итог: два источника правды о состоянии ученика и оверинжиниринг вокруг заморозки.
Реальные решения всё равно принимает менеджер вручную.

## Решение

Статусы ученика удаляются целиком. Состояние ученика = **стадия последней сделки
продления**. «Заморожен» и «Ушёл» становятся обычными стадиями воронки без побочных
эффектов на членства и расписание — остальное менеджер делает сам.

### Принятые решения (пользователь, 2026-07-25)

1. Колонки `enrollment_status` / `frozen_from` / `frozen_until` **удаляются из БД**.
2. Выход из стадии «Заморожен» — **только ручным действием** «Вернуть в работу»
   (автовозврата по факту записанного урока нет).
3. Месяц окончания заморозки хранится **на сделке**: `RenewalDeal.frozen_until_month`.
4. Бейдж ученика показывает стадию открытой сделки; если открытой нет — стадию
   последнего цикла приглушённым тоном (ушедший ученик остаётся визуально ушедшим).
5. Побочный эффект принят осознанно: заморозка больше не останавливает расписание
   индивидуалов — плановые уроки продолжают генерироваться и попадать в «Заполнить»,
   пока менеджер сам их не отменит.

## Модель данных

### `students` — удалить

- колонки `enrollment_status`, `frozen_from`, `frozen_until`;
- констрейнты `students_enrollment_status_check`,
  `students_frozen_dates_presence_check`, `students_frozen_dates_order_check`.

### `renewal_deal` — добавить

```
frozen_until_month  DateField(null=True, blank=True)
```

Всегда 1-е число месяца («до какого месяца заморозка»). Заполнено **только** пока
сделка стоит на стадии с `key='frozen'`; при уходе со стадии обнуляется.

DB-CHECK не ставим: ключ стадии лежит в другой таблице, а условный констрейнт по
FK-джойну в Postgres не выражается. Инвариант держится в двух точках записи —
`repository.move_deal` и `engine.return_from_freeze`; они же покрываются тестами.

### Индекс

```
Index(fields=['student', '-cycle_no'], name='renewal_deal_student_cycle_idx')
```

Существующий `renewal_deal_student_idx` — только по `student_id`; подзапрос «последняя
сделка ученика» без составного индекса делает сортировку на каждую строку.

## Домен «Продления»

### Стадия «Заморожен»

- `is_auto=False` (откат миграции `0010_frozen_autostage`) — обычная ручная
  decision-стадия.
- `transitions.is_allowed` получает новый аргумент `to_key`. Переход **в** `frozen`
  разрешён и при незавершённом цикле — так же, как переход в `lost`:

  ```python
  if not cycle_completed:
      return to_kind == 'lost' or to_key == FROZEN_KEY
  ```

  Причина: замораживаются почти всегда посреди цикла. Раньше это работало только
  потому, что `engine.freeze_deal` обходил валидатор.
- Остальные ворота не меняются: выход `frozen → decision` требует завершённого цикла,
  `frozen → lost` разрешён всегда, `frozen → won` требует завершённого цикла и
  положительного баланса.

### `move_deal`

Принимает `frozen_until_month`:

- переход **в** `frozen` — месяц обязателен (валидация в сериализаторе, см. API);
- переход **из** `frozen` в любую стадию — `frozen_until_month = None`;
- в `RenewalActivity` пишем человекочитаемое «Заморозка до сентября 2026».

### Выход из заморозки

Новая функция `engine.return_from_freeze(deal_id, author_id=None)` — переработка
существующей `resume_from_freeze` (сейчас принимает `student_id` и вызывается из
`students.services.resume_student`):

- работает по `deal_id`, а не по ученику (UI знает сделку);
- no-op, если сделка не найдена или стоит не на `frozen`;
- ставит стадию, посчитанную `_target_auto_stage` (та же логика, что при создании и
  `reopen_deal`), сбрасывает `frozen_until_month`, пишет системную активность;
- валидатор переходов обходит осознанно — как `reopen_deal` (возврат на авто-стадию
  руками невозможен по правилам воронки, это не ручной переход, а пересчёт).

### Что удаляется из движка

- `engine.freeze_deal` — существовала только для каскада статуса;
- `engine.decline_deal` — то же; «Ушёл» теперь обычное закрытие через `move_deal`;
- спец-исключение по `FROZEN_KEY` в `sync_lesson_stage`: стадия больше не `is_auto`,
  движок пропустит её общим правилом `not deal.stage.is_auto`. Константа `FROZEN_KEY`
  остаётся — её используют `transitions`, `move_deal` и `return_from_freeze`.

## API

### Ученики

`GET /api/admin/students` и `GET /api/admin/students/<id>` вместо
`enrollment_status` / `frozen_from` / `frozen_until` отдают:

```json
{
  "stage": { "id": 4, "key": "frozen", "label": "Заморожен",
             "kind": "decision", "sort_order": 3 },
  "stage_is_open": true,
  "stage_frozen_until_month": "2026-09-01"
}
```

- стадия берётся у сделки с максимальным `cycle_no`: открыта — её стадия,
  все закрыты — стадия последнего цикла и `stage_is_open: false`;
- у ученика без сделок `stage: null`, `stage_is_open: false`,
  `stage_frozen_until_month: null`;
- `stage_frozen_until_month` непустой только когда `stage.key == 'frozen'`.

Фильтр `filter[stage_id]=<id>` (exact) и сортировка `sort_by=stage` (по `sort_order`
стадии) заменяют фильтр и сортировку по `enrollment_status`.

**Удаляются эндпоинты:** `POST /api/admin/students/<id>/status`,
`POST /api/admin/students/<id>/status/preview`, `POST /api/admin/students/<id>/resume`.

### Продления

Новый: `POST /api/admin/renewals/<id>/unfreeze` → `engine.return_from_freeze`,
ответ — `deal_computed(id)`, как у `move` / `reopen`. `permission_classes = [IsManagerOrAdmin]`
— тот же класс, что у `RenewalMoveView` и `RenewalReopenView`. Маршрут добавляется
рядом с `/<int:pk>/reopen` в `apps/renewals/urls.py`.

`POST /api/admin/renewals/<id>/move` — тело получает необязательное
`frozen_until_month` (`YYYY-MM-01`). Валидация в `MoveDealSerializer.validate()`:
поле обязательно, если `to_stage_id` указывает на стадию с `key='frozen'`; при
переходе на любую другую стадию поле игнорируется. Нормализация к 1-му числу месяца —
там же (день из ввода отбрасывается).

Сериализаторы сделки (`deal_computed`, карточка доски, список) отдают
`frozen_until_month`.

## UI

### `StageBadge` (замена `StatusBadge`)

- подпись — `stage.label`; у стадии `frozen` дописывается «· до сентября 2026»
  (тот же приём, что сейчас у `Заморожен · до 12 августа 2026`);
- тон по `kind`: `progress`/`decision` → `info`, `won` → `positive`,
  `lost` → `negative`, отдельно `frozen` → `neutral`;
- `stage_is_open: false` → приглушённый вариант (модификатор класса, токены
  дизайн-системы);
- `stage: null` → прочерк, без бейджа;
- цвет стадии из БД (`stage.color`) **не** используется: он остаётся достоянием
  колонок доски, а в таблицах/героях цвет несёт семантику из токенов.

Места применения — те же три, где сейчас `StatusBadge`: список учеников, герой
страницы ученика, состав группы (`GroupMembersBlock`).

### Страница ученика

- из `ActionMenu` уходят «Изменить статус» и «Разморозить»;
- строка «Статус» в карточке полей удаляется — бейдж в герое её дублирует;
- `StudentStatusModal.tsx` и `StudentResumeDialog` удаляются.

### Список учеников

Колонка `enrollment_status` → `stage`: подпись «Стадия», `sortable`, `searchable`
с `searchOptions` из `useRenewalStages()`. Ключ колонки в `table-settings.ts`
переименовывается (`enrollment_status` → `stage`).

### Доска продлений

- drop в колонку «Заморожен» → диалог `FreezeDealDialog` с одним полем «Заморозка до
  месяца» (`SelectInput` месяц + год; native-элементы запрещены) → `move` с
  `frozen_until_month`. Спец-обработка `is_auto` для `frozen` из `handleDragEnd`
  уходит — стадия стала обычной;
- drop в зону «✕ Ушёл» → существующий `RenewalCloseDialog` с `mode: 'lost'`
  (причина + комментарий), обычный `move` в `lost`. Вызов `StudentStatusModal`
  из `RenewalBoard` удаляется целиком;
- на карточке и в панели сделки на стадии «Заморожен» — действие «Вернуть в работу»
  (`POST .../unfreeze`), инвалидирует `['renewals']` и `['students']`;
- у карточки на «Заморожен» видно «до сентября 2026».

### Прочее

`PaymentModal`: подпись ученика — только `full_name`, суффикс статуса уходит вместе
с `ENROLLMENT_STATUS_LABELS`.

Из `lib/labels.ts` удаляются `ENROLLMENT_STATUS_LABELS` и `ENROLLMENT_STATUS_OPTIONS`,
из `lib/shared-types.ts` — тип `EnrollmentStatus` и поля
`enrollment_status` / `frozen_from` / `frozen_until` у `Student`; добавляются
`stage` / `stage_is_open` / `stage_frozen_until_month`.

## Мёртвый код к удалению

`apps/students/services.py`: `change_student_status`, `resume_student`,
`preview_freeze_schedule`, `_affected_memberships`, `_active_individual_group_ids`,
`_actor_id` (после удаления первых двух не остаётся вызовов — `set_student_manager`
принимает `actor`, но не использует его).

`apps/students/views.py` + `urls.py` + `serializers.py`: `StudentStatusView`,
`StudentResumeView`, `StudentFreezePreviewView` и их сериализаторы; поле
`enrollment_status` из сериализаторов ученика; `enrollment_status` из whitelist
сортировки.

`apps/students/repository.py`: `enrollment_status` из `_SORTABLE`, `_FIELDS`,
фильтров, `create_student`, `update_student`; вместо него — аннотация стадии.

`apps/scheduling/repository.py`: `freeze_individual_group`, `resume_individual_group`,
`preview_freeze`, `cancel_future_planned` — вызываются **только** из смены статуса
(проверено grep'ом по всему `journal_django`).

`apps/dashboard/registry_service.py::base_students_qs`: фильтр
`enrollment_status='enrolled'` снимается, остаётся `Exists(active_membership)`.
Следствие: ушедший ученик уходит из реестра тогда, когда менеджер снимает членство,
а не по стадии сделки. Альтернатива «исключать учеников, чья последняя сделка в
`lost`» отклонена: лишний коррелированный подзапрос в тяжёлом кешируемом запросе
дашборда, при том что «учится» и так определяется активным членством.

`apps/sync/backfills/students.py`: `map_enrollment_from_sheets` и запись
`enrollment_status` / `frozen_from` / `frozen_until` в `INSERT ... ON CONFLICT`
вырезаются; остальные поля синхронизируются как раньше.
`apps/students/migrations/_frozen_backfill_util.py` остаётся — его использует
историческая миграция `0010`.

`apps/changelog/labels.py`: правила `student.status` и `student.resume` удаляются,
добавляется правило для `POST /api/admin/renewals/\d+/unfreeze` → `renewal.unfreeze`.
`apps/changelog/summary.py`: имена полей `enrollment_status`, `frozen_from`,
`frozen_until` удаляются, добавляется `frozen_until_month` → «заморозка до месяца».

Фронт: `StudentStatusModal.tsx`, `StudentResumeDialog`, `StatusBadge.tsx`
(переписывается в `StageBadge.tsx`), `ENROLLMENT_STATUS_*`, тип `EnrollmentStatus`.

## Миграции

Порядок обязателен — бэкфил месяца читает колонку, которую следующая миграция удаляет.

1. `renewals/0012_frozen_manual_stage` — `is_auto=False` у стадии `key='frozen'`
   дефолтной воронки. Идемпотентно, обратимо (`is_auto=True`).
2. `renewals/0013_deal_frozen_until_month` — `AddField frozen_until_month`
   (`null=True`) + `AddIndex renewal_deal_student_cycle_idx` + data-миграция:
   для открытых сделок на стадии `frozen` заполнить
   `date_trunc('month', students.frozen_until)::date` по её ученику.
3. `students/0016_drop_enrollment_status` — удалить три констрейнта и три колонки.
   Объявляет `dependencies` на `renewals/0013`, чтобы бэкфил успел прочитать
   `students.frozen_until` до её удаления (зависимость, а не `run_before`:
   `run_before` на ещё не существующую миграцию Django не разрешит).

Ловушки, которые учитываем:

- часть приложений no-op'ят `django_db_setup` (общая `journal_test`), часть создают
  свежую `test_journal_test` — после этих миграций гонять **полный** `pytest`, не по
  частям (см. `project_test_db_django_db_setup_split`);
- `AlterField` на FK в этом наборе нет, поэтому db-level `ON DELETE` из прежних
  `RunSQL`-миграций не затирается;
- новое поле nullable и с DB-default `NULL`, поэтому raw-SQL-вставки в тестах не
  ломаются.

## Производительность

Аннотация стадии в `list_students` — коррелированные подзапросы к `renewal_deal`
по `(student_id, cycle_no DESC)` для `stage_id`, `sort_order`, `outcome_at`,
`frozen_until_month`. С составным индексом каждый — index-only lookup.

Подписи и виды стадий (`label`, `kind`) не тянутся подзапросом: воронка — семь строк,
`repository` берёт их одним запросом и мапит `stage_id → dict` в питоне.

Самая тяжёлая точка — `useStudentsAll()` (`page_size=2000` для `PaymentModal` и
состава группы): 2000 строк × 4 index-lookup'а. Проверить `EXPLAIN ANALYZE` на dev-БД
при реализации; если не устроит — фолбэк на один `DISTINCT ON (student_id)`-запрос по
списку id и склейку в питоне (фильтр/сортировка по стадии в этом варианте недоступны,
поэтому это именно фолбэк).

## Тесты

Удаляются: `students/tests/test_status_service.py`, `test_status_api.py`,
`test_freeze_preview_api.py`, `test_frozen_constraints.py`,
`test_student_leave_cleanup.py`; `scheduling/tests/test_freeze_scheduling.py`,
`test_preview_freeze.py`; `renewals/tests/test_freeze_deal.py`.

Правятся: `students/tests/test_students_repository.py`, `test_students_api.py`
(поля/фильтры/сортировка), `test_manager_*` и `test_comment_*` (raw-INSERT со
`enrollment_status`), `renewals/tests/test_transitions.py`, `test_api_write.py`,
`test_engine.py`, changelog-тесты (набор правил и имён полей),
dashboard-тесты реестра.

Добавляются:

- переход в `frozen` разрешён при незавершённом цикле; в другие decision-стадии — нет;
- `move` в `frozen` без `frozen_until_month` → 400; месяц нормализуется к 1-му числу;
- уход со стадии `frozen` обнуляет `frozen_until_month`;
- `unfreeze` ставит расчётную авто-стадию, сбрасывает месяц, пишет активность;
  no-op на сделке не на `frozen`;
- RBAC: `unfreeze` недоступен учителю;
- аннотация стадии: открытая сделка → её стадия `stage_is_open=true`; все закрыты →
  последний цикл, `stage_is_open=false`; нет сделок → `null`;
- фильтр `filter[stage_id]` и сортировка `sort_by=stage`;
- data-миграция бэкфила месяца (месяц берётся у замороженного ученика).

## Что осознанно не делаем

- Не трогаем механику членств, переносов, relay и доп.уроков — она остаётся ручным
  инструментом менеджера.
- Не автоматизируем выход из заморозки по факту записанного урока (решение
  пользователя: только ручное действие).
- Не заводим отдельную сущность «период заморозки» и не храним историю периодов:
  таймлайн сделки уже фиксирует вход в стадию и месяц в тексте активности.
- Не добавляем soft-delete/архив ученику вместо статуса `declined`.
