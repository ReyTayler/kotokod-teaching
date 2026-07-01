# Фаза 2 — запись групп (create/update/delete) на чистом NestJS — дизайн

> Утверждённый дизайн второго инкремента раздела «Группы»: операции записи.
> Продолжение: `2026-06-08-phase2-groups-module-design.md` (read-only) и
> `2026-06-08-phase2-groups-module.md` (план read-only). git нет → verification + ревью после шагов.

## Цель

Добавить в раздел `src/modules/groups/` операции записи с паритетом Express-роута `routes/admin/groups.js`.
Это первый write-раздел → здесь же впервые появляются: проверка входных данных (DTO) и общий
обработчик ошибок (PG-коды → HTTP), которые Фаза 2 откладывала до этого момента (решения #2 и #4 брифа).

## Контракт (паритет с Express)

| Действие | Маршрут | Успех | Ошибки |
|---|---|---|---|
| Создать | `POST /api/admin/groups` | 201 + созданная группа | 400 (валидация), 409 (дубликат/FK) |
| Изменить | `PATCH /api/admin/groups/:id` | 200 + группа | 400, 404 (нет группы), 409 |
| Удалить | `DELETE /api/admin/groups/:id` | 204 без тела | 404 (нет группы) |

- Доступ: роли `manager`/`admin` (контроллер уже под `@UseGuards(AuthGuard, RolesGuard)` + `@Roles`).
- Удаление — **мягкое** (`UPDATE groups SET active=false`), как в Express.
- SQL create/update (со слотами расписания в транзакции) и softDelete — **дословно** из `services/repo/groups.js`.

## Проверка входных данных (решение #2 — nestjs-zod)

- Ставим пакет `nestjs-zod`. DTO-классы создаём из **существующих** Zod-схем `shared/schemas.js`:
  - `CreateGroupDto = createZodDto(createGroupSchema)`
  - `UpdateGroupDto = createZodDto(updateGroupSchema)`
  Единый источник правил с Express — никакого второго свода.
- Формат ошибки 400 — **точно как у Express** (`routes/middleware/validate.js`):
  `{ error: 'Validation failed', details: <fieldErrors> }`, где `fieldErrors = zodError.flatten().fieldErrors`.
  Достигается в общем обработчике ошибок (ловит исключение валидации nestjs-zod и форматирует тело).

### Риск (спайк — первая задача плана)
`nestjs-zod` исторически под Zod 3, в проекте **Zod 4**. Первая задача — проверить связку
(сборка + один прогон валидации). Если несовместимо — фолбэк: тонкий собственный `ZodValidationPipe`
(~15 строк) на тех же схемах `shared/schemas.js`. Цель «один источник правил» достигается в обоих случаях.
Решение по фолбэку — показать пользователю.

## Обработчик ошибок (решение #4 — общий ExceptionFilter)

Глобальный фильтр `src/common/filters/all-exceptions.filter.ts`, по порядку:

1. **Ошибка валидации** (исключение nestjs-zod / `ZodError`) → 400 `{ error:'Validation failed', details }`.
2. **Ошибка БД** (`err.code` в таблице PG) → статус+сообщение из таблицы, тело `{ error: <сообщение> }`.
3. **HttpException** (404/401/403 и пр.) → проброс как есть (сохранить уже работающее: 404 `{error:'Not found'}`,
   401/403 от guard'ов). НЕ ломать read-only поведение.
4. **Прочее** → 500 generic + полный лог на сервере (без утечки деталей наружу).

**DRY таблицы PG-ошибок:** вынести `PG_ERRORS` из `server.js` в `shared/pg-errors.js`; импортировать
и в `server.js` (Express), и в Nest-фильтр. Один источник на оба приложения. Карта (без изменений):
`23505→409`, `23503→409`, `23502→400`, `23514→400`, `22P02→400`, `22001→400` — с текущими русскими сообщениями.

**Намеренное минимальное расхождение:** Express в POST-роуте имеет локальный catch `23505 → {error:'Already exists'}`
(англ.), перекрывающий общую карту. В Nest используем общую карту для всех (рус. «Запись с такими данными
уже существует») — единообразнее. Согласовано с пользователем.

## Состав файлов

```
src/modules/groups/
  dto/create-group.dto.ts     # createZodDto(createGroupSchema)
  dto/update-group.dto.ts     # createZodDto(updateGroupSchema)
  groups.repository.ts        # + createGroup / updateGroup / softDeleteGroup (SQL дословно, tx через DbService.tx)
  groups.service.ts           # + createGroup / updateGroup / deleteGroup
  groups.controller.ts        # + POST / PATCH / DELETE (+ ZodValidationPipe на теле)
src/common/filters/
  all-exceptions.filter.ts    # глобальный (валидация/PG/HttpException/500)
shared/pg-errors.js           # вынесенная карта PG_ERRORS (общая Express+Nest)
server.js                     # импортирует shared/pg-errors.js вместо локального объекта
src/app.module.ts             # APP_FILTER → AllExceptionsFilter; глобальный ZodValidationPipe
```

`DbService.tx` уже есть (обёртка над `services/db.js tx`) — транзакция для слотов идёт через неё.

## Тесты (e2e, паритет)

`test/nest/groups.write.e2e.test.js` (supertest, реальная БД):
- POST валидное тело → 201, в ответе созданная группа (id, name, слоты).
- POST кривое тело (например пустой `name`) → 400 `{ error:'Validation failed', details:{...} }`.
- PATCH существующей → 200, поля изменены.
- PATCH несуществующей (`/999999999`) → 404 `{ error:'Not found' }`.
- DELETE существующей → 204; повторный GET показывает `active=false` (мягкое удаление).
- DELETE несуществующей → 404.
- (если воспроизводимо) POST с дубликатом уникального поля → 409 `{ error:'Запись с такими данными уже существует' }`.
- 401 без cookie / 403 teacher на POST — гейтинг сохранён.

**Гигиена данных:** тест трекает id созданных групп и в `after()` жёстко удаляет их из БД
(`DELETE FROM groups ... ; DELETE FROM group_schedule_slots ...`) через общий пул, чтобы не копились.

**Регрессия read-only:** существующий `groups.e2e.test.js` (404/401/403/list/filter) остаётся зелёным —
доказывает, что новый глобальный фильтр не сломал прежнее поведение.

## Верификация

- `npm run nest:build` чисто, `npm run nest:test` зелено, `npm test` (полный) зелено.
- Express-роут групп **не трогаем** (кроме импорта общей карты ошибок) — cutover позже (nginx).

## Вне скоупа

- Перенос самого пула/`tx` из `services/db.js` в TS — после удаления Express.
- cutover на nginx; перенос остальных разделов (Students/Lessons/Finance/Auth).
