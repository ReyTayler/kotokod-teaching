# Журнал изменений на страницах группы и ученика

Дата: 2026-07-21

## Проблема

Раздел «Журнал изменений» (`/admin/changelog`, `journal_django/apps/changelog/`) показывает общую ленту всех изменений в системе с фильтрами. Чтобы посмотреть историю конкретной группы или ученика, нужно вручную перейти в общий журнал и подставить фильтр по сущности. Нужна встроенная вкладка «История» прямо на странице группы/ученика.

## Решение

### Backend

Изменений не требуется. `GET /api/admin/changelog?filter[entity]=<entity>&filter[entity_id]=<id>` уже фильтрует ленту по конкретной сущности — `_apply_filters` в `journal_django/apps/changelog/repository.py:90-101` резолвит `entity`/`entity_id` через `registry.model_label_for_entity` и строит `EXISTS`-подзапрос по Event-таблице. Ключи сущностей `group`/`student` уже есть в `registry.py:30-56` и во фронтовых константах `CHANGELOG_ENTITY_LABELS`/`ENTITY_ROUTES`.

### Frontend

**1. Вынести общие рендереры колонок.**
Логика отрисовки строки ленты (иконка действия `actionIcon`, короткая роль `ROLE_SHORT`, ячейка времени, ячейка актора) сейчас захардкожена внутри `pages/changelog/ChangelogListPage.tsx:20-58`. Выносим в `components/changelog/columnRenderers.tsx` (чистые функции/рендер-хелперы, без сайд-эффектов). `ChangelogListPage.tsx` переключается на импорт оттуда — поведение общего журнала не меняется.

**2. Новый компонент `components/changelog/EntityChangelogPanel.tsx`.**
```tsx
<EntityChangelogPanel entity="group" entityId={group.id} />
<EntityChangelogPanel entity="student" entityId={student.id} />
```
- Пагинация — локальный `useState<number>` (страница сбрасывается при размонтировании таба), без синхронизации с URL: виджет компактный, без фильтров/сортировки, не должен засорять `?tab=...` query страницы-хозяина. `pageSize` фиксирован (15). Сортировка фиксирована на бэке (`occurred_at DESC`).
- Запрос: `useChangelogList` с query `?page=&page_size=15&filter[entity]=<entity>&filter[entity_id]=<entityId>`.
- `DataTable` в server-mode с 4 колонками: Время / Действие / Описание / Кто. Без колонки «Статус» и без кнопки отката — сознательно компактный, только-просмотр виджет.
- Клик по строке → `ChangelogDetailModal` с новым пропом `readOnly={true}`.
- Пустое состояние обрабатывает сам `DataTable` (как в остальных списках).

**3. `ChangelogDetailModal` — новый проп `readOnly?: boolean` (default `false`).**
Когда `true`, кнопка «Откатить операцию» в футере не рендерится независимо от роли/`revertable`. `onRevert` становится опциональным (`onRevert?: (op) => void`). Использование в `ChangelogListPage.tsx` (общий журнал) не меняется — там `readOnly` не передаётся, откат работает как раньше.

**4. Встраивание вкладки — гейт по правам как у общего журнала.**
- `GroupDetailPage.tsx`: `GROUP_TABS` пополняется `'history'`. Вкладка «История» добавляется в массив `tabs` только если `canSeeChangelog(me?.role as Role)` (тот же `isStaff`-гейт: manager/admin/superadmin), размещается последней, после «Расписание».
- `StudentDetailPage.tsx`: `STUDENT_TABS` пополняется `'history'`. Вкладка добавляется только при том же гейте, последней, после «Комментарии».
- Гейт — defense-in-depth (бэкенд и так форсирует `IsManagerOrAdmin` на эндпоинте журнала); соответствует конвенции проекта «доступ проверяется на API, фронт-гейт — только UX».

### Сознательно не делаем

- Кнопку отката прямо из вкладки — только просмотр, для отката пользователь идёт через существующий общий журнал напрямую.
- Ссылку/переход «Смотреть в общем журнале →» из вкладки.
- Фильтры по дате/типу операции внутри вкладки.

## Затронутые файлы

- `journal_django/frontend/admin-src/src/pages/changelog/ChangelogListPage.tsx` — рефакторинг: рендереры выносятся в новый модуль.
- `journal_django/frontend/admin-src/src/pages/changelog/ChangelogDetailModal.tsx` — добавление пропа `readOnly`.
- `journal_django/frontend/admin-src/src/components/changelog/columnRenderers.tsx` — новый файл.
- `journal_django/frontend/admin-src/src/components/changelog/EntityChangelogPanel.tsx` — новый файл.
- `journal_django/frontend/admin-src/src/pages/groups/GroupDetailPage.tsx` — новая вкладка.
- `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx` — новая вкладка.

Backend не затрагивается.

## Тестирование

- Frontend: TypeScript typecheck/build admin-src без ошибок.
- Ручная проверка в браузере: вкладка «История» на странице группы и ученика показывает записи именно этой сущности (сверка с общим журналом через тот же фильтр), пагинация работает, клик по строке открывает модалку с диффами без кнопки отката, вкладка скрыта/показана согласно роли.
- Регрессия: общий журнал (`/admin/changelog`) — фильтры, модалка, откат — работает как прежде.
