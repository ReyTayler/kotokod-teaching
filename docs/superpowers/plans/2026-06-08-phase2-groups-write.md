# Фаза 2 — запись групп (create/update/delete) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить в раздел `src/modules/groups/` операции записи (POST/PATCH/DELETE) на чистом NestJS с паритетом Express-роута, проверкой данных через nestjs-zod на существующих Zod-схемах и общим обработчиком ошибок БД.

**Architecture:** DTO создаются из существующих Zod-схем `shared/schemas.js` (один источник правил). SQL записи копируется дословно из `services/repo/groups.js`, транзакции — через `DbService.tx`. Глобальный exception-фильтр переводит ошибки валидации и БД в HTTP-коды как у Express (таблица `PG_ERRORS` выносится в общий `shared/pg-errors.js`). Пайп и фильтр регистрируются через `APP_PIPE`/`APP_FILTER` — прод и e2e получают идентичную конфигурацию.

**Tech Stack:** NestJS 11 + Fastify, `nestjs-zod` (+ существующий `zod` v4), `pg` (общий пул через `DbService`), `node --test` + `supertest`.

---

## ⚠️ Адаптация под отсутствие git

git не используется. **Шаг «Commit» в каждой задаче заменён на «Verification checkpoint»**: прогнать проверку, показать вывод, дождаться ревью перед следующей задачей. Не переходить дальше без зелёной проверки.

## Точные данные для паритета (прочитано из кода)

- **Формат ошибки валидации Express** (`routes/middleware/validate.js`): `{ error: 'Validation failed', details: zodError.flatten().fieldErrors }`, статус 400.
- **Таблица PG-ошибок** (`server.js`): `23505→[409,'Запись с такими данными уже существует']`, `23503→[409,'Связанная запись не найдена или используется']`, `23502→[400,'Не заполнено обязательное поле']`, `23514→[400,'Нарушено ограничение целостности данных']`, `22P02→[400,'Некорректный формат данных']`, `22001→[400,'Слишком длинное значение']`. Тело: `{ error: <сообщение> }`.
- **Zod-схемы** (`shared/schemas.js`): `createGroupSchema`, `updateGroupSchema` (экспортируются).
- **Write-SQL** (`services/repo/groups.js`): см. дословный перенос в Task 4.

## File Structure

```
src/modules/groups/
  dto/create-group.dto.ts     # createZodDto(createGroupSchema)
  dto/update-group.dto.ts     # createZodDto(updateGroupSchema)
  groups.repository.ts        # + createGroup/updateGroup/softDeleteGroup
  groups.service.ts           # + createGroup/updateGroup/deleteGroup
  groups.controller.ts        # + POST/PATCH/DELETE
src/common/filters/all-exceptions.filter.ts
shared/pg-errors.js
server.js                     # импорт shared/pg-errors.js
src/app.module.ts             # APP_PIPE (ZodValidationPipe) + APP_FILTER (AllExceptionsFilter)
```

---

### Task 1: Спайк nestjs-zod + DTO из существующих Zod-схем

**Files:**
- Modify: `package.json` (dep `nestjs-zod`)
- Create: `src/modules/groups/dto/create-group.dto.ts`
- Create: `src/modules/groups/dto/update-group.dto.ts`
- Test: `test/nest/groups-dto.test.js`

- [ ] **Step 1: Установить nestjs-zod**

Run: `npm install nestjs-zod`
Expected: установка без ERESOLVE. **Если конфликт peer-deps с `zod@4` — зафиксировать вывод, СТОП, показать пользователю** (фолбэк: тонкий собственный Zod-пайп вместо пакета).

- [ ] **Step 2: Написать падающий тест на DTO-схему**

`test/nest/groups-dto.test.js`:
```js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { CreateGroupDto } = require('../../dist/modules/groups/dto/create-group.dto.js');

test('CreateGroupDto несёт рабочую Zod-схему (валидное тело проходит)', () => {
  const schema = CreateGroupDto.schema; // nestjs-zod кладёт исходную схему в .schema
  const ok = schema.safeParse({
    name: 'Группа A',
    direction_id: 1,
    teacher_id: 1,
    is_individual: false,
    lesson_duration_minutes: 90,
    lessons_per_week: 2,
  });
  assert.equal(ok.success, true);
});

test('CreateGroupDto: пустой name отклоняется', () => {
  const schema = CreateGroupDto.schema;
  const bad = schema.safeParse({
    name: '',
    direction_id: 1,
    teacher_id: 1,
    is_individual: false,
    lesson_duration_minutes: 90,
    lessons_per_week: 2,
  });
  assert.equal(bad.success, false);
});
```

- [ ] **Step 3: Запустить — убедиться, что падает**

Run: `npm run nest:build && node --test test/nest/groups-dto.test.js`
Expected: FAIL — модуля DTO ещё нет. **Если сборка падает на несовместимости nestjs-zod ↔ zod v4 — СТОП, показать вывод (фолбэк ниже).**

- [ ] **Step 4: Реализовать DTO**

`src/modules/groups/dto/create-group.dto.ts`:
```ts
import { createZodDto } from 'nestjs-zod';
// Переиспользуем СУЩЕСТВУЮЩУЮ Zod-схему проекта (shared/schemas.js, zod v4) —
// единый источник правил валидации с Express. НЕ дублируем правила.
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { createGroupSchema } = require('../../../shared/schemas');

export class CreateGroupDto extends createZodDto(createGroupSchema) {}
```

`src/modules/groups/dto/update-group.dto.ts`:
```ts
import { createZodDto } from 'nestjs-zod';
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { updateGroupSchema } = require('../../../shared/schemas');

export class UpdateGroupDto extends createZodDto(updateGroupSchema) {}
```

> **Фолбэк (если nestjs-zod несовместим с zod v4 и Step 1/3 упали):** остановиться и сообщить.
> Тогда вместо `createZodDto` — тонкий пайп на схемах напрямую (отдельное решение с пользователем).
> НЕ продолжать молча.

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `npm run nest:build && node --test test/nest/groups-dto.test.js`
Expected: PASS (2 теста).

- [ ] **Step 6: Verification checkpoint**

Run: `npm run nest:test`
Expected: все nest-тесты зелёные. Показать вывод, дождаться ревью.

---

### Task 2: Вынести таблицу PG-ошибок в общий `shared/pg-errors.js`

**Files:**
- Create: `shared/pg-errors.js`
- Modify: `server.js` (импорт вместо локального объекта)
- Test: `test/nest/pg-errors.test.js`

- [ ] **Step 1: Написать падающий тест**

`test/nest/pg-errors.test.js`:
```js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { PG_ERRORS } = require('../../shared/pg-errors');

test('PG_ERRORS: маппинг кодов на [status, message]', () => {
  assert.deepEqual(PG_ERRORS['23505'], [409, 'Запись с такими данными уже существует']);
  assert.deepEqual(PG_ERRORS['23502'], [400, 'Не заполнено обязательное поле']);
  assert.deepEqual(PG_ERRORS['22P02'], [400, 'Некорректный формат данных']);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test test/nest/pg-errors.test.js`
Expected: FAIL — модуля нет.

- [ ] **Step 3: Создать `shared/pg-errors.js`**

```js
// Единый источник маппинга PG constraint-ошибок → [HTTP-статус, сообщение].
// Импортируется и Express (server.js), и Nest-фильтром (all-exceptions.filter.ts).
const PG_ERRORS = {
  '23505': [409, 'Запись с такими данными уже существует'],
  '23503': [409, 'Связанная запись не найдена или используется'],
  '23502': [400, 'Не заполнено обязательное поле'],
  '23514': [400, 'Нарушено ограничение целостности данных'],
  '22P02': [400, 'Некорректный формат данных'],
  '22001': [400, 'Слишком длинное значение'],
};

module.exports = { PG_ERRORS };
```

- [ ] **Step 4: Подключить в `server.js`**

Найти в `server.js` объявление `const PG_ERRORS = { ... }` (раздел «Centralized error handler») и **заменить** его на импорт. Вверху файла (рядом с прочими require) добавить:
```js
const { PG_ERRORS } = require('./shared/pg-errors');
```
и удалить локальный объект `const PG_ERRORS = {...}` (строки с картой). Логику обработчика (`app.use((err,...))`) не трогать — он продолжает использовать переменную `PG_ERRORS`.

- [ ] **Step 5: Запустить тест + регрессию Express**

Run: `node --test test/nest/pg-errors.test.js`
Expected: PASS.
Run: `npm test`
Expected: полный набор зелёный (Express-обработчик ошибок работает через вынесенную карту — существующие тесты это покрывают).

- [ ] **Step 6: Verification checkpoint**

Показать вывод `npm test`, дождаться ревью.

---

### Task 3: Глобальный AllExceptionsFilter (валидация / PG / HttpException / 500)

**Files:**
- Create: `src/common/filters/all-exceptions.filter.ts`
- Modify: `src/app.module.ts` (APP_FILTER + APP_PIPE)
- Test: повторный прогон `test/nest/groups.e2e.test.js` (read-only паритет не сломан)

- [ ] **Step 1: Реализовать фильтр**

`src/common/filters/all-exceptions.filter.ts`:
```ts
import {
  ExceptionFilter,
  Catch,
  ArgumentsHost,
  HttpException,
  Logger,
} from '@nestjs/common';
import type { FastifyReply } from 'fastify';
import { ZodValidationException } from 'nestjs-zod';
// Общая карта PG-ошибок (тот же источник, что у Express).
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { PG_ERRORS } = require('../../../shared/pg-errors');

/**
 * Глобальный обработчик ошибок. Порядок веток важен:
 * 1) ошибка валидации nestjs-zod → 400 { error:'Validation failed', details } (формат Express);
 * 2) ошибка БД (err.code в PG_ERRORS) → маппинг [статус,'сообщение'] → { error: сообщение };
 * 3) HttpException (404/401/403 и пр.) → проброс как есть (НЕ ломаем read-only поведение);
 * 4) прочее → 500 generic + полный лог на сервере.
 */
@Catch()
export class AllExceptionsFilter implements ExceptionFilter {
  private readonly logger = new Logger('AllExceptionsFilter');

  catch(exception: unknown, host: ArgumentsHost): void {
    const reply = host.switchToHttp().getResponse<FastifyReply>();

    // 1) Валидация (nestjs-zod)
    if (exception instanceof ZodValidationException) {
      const zerr = exception.getZodError();
      reply.status(400).send({
        error: 'Validation failed',
        details: zerr.flatten().fieldErrors,
      });
      return;
    }

    // 2) Ошибка БД по коду
    const code = (exception as { code?: string } | null)?.code;
    if (code && PG_ERRORS[code]) {
      const [status, message] = PG_ERRORS[code];
      this.logger.warn(`[PG] ${code} ${(exception as Error).message}`);
      reply.status(status).send({ error: message });
      return;
    }

    // 3) HttpException — сохранить текущее поведение (404 {error:'Not found'}, 401/403 от guard'ов)
    if (exception instanceof HttpException) {
      reply.status(exception.getStatus()).send(exception.getResponse());
      return;
    }

    // 4) Неизвестная ошибка — generic 500, детали только в лог
    this.logger.error(exception);
    reply.status(500).send({ error: 'Internal server error' });
  }
}
```

- [ ] **Step 2: Зарегистрировать фильтр и пайп в `src/app.module.ts`**

Добавить импорты и провайдеры. Итоговый `src/app.module.ts`:
```ts
import { Module } from '@nestjs/common';
import { APP_FILTER, APP_PIPE } from '@nestjs/core';
import { ConfigModule } from '@nestjs/config';
import { LoggerModule } from 'nestjs-pino';
import { ZodValidationPipe } from 'nestjs-zod';
import { HealthController } from './modules/health/health.controller';
import { DbModule } from './database/db.module';
import { SecurityModule } from './common/security.module';
import { validateEnv } from './config/env.validation';
import { GroupsModule } from './modules/groups/groups.module';
import { AllExceptionsFilter } from './common/filters/all-exceptions.filter';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      validate: (raw) => validateEnv(raw as Record<string, unknown>),
    }),
    LoggerModule.forRoot({
      pinoHttp: {
        transport:
          process.env.NODE_ENV !== 'production'
            ? { target: 'pino-pretty', options: { singleLine: true } }
            : undefined,
        redact: ['req.headers.cookie', 'req.headers.authorization'],
        autoLogging: true,
      },
    }),
    DbModule,
    SecurityModule,
    GroupsModule,
  ],
  controllers: [HealthController],
  providers: [
    // Глобальная Zod-валидация тел запросов (срабатывает на аргументах-ZodDto).
    { provide: APP_PIPE, useClass: ZodValidationPipe },
    // Глобальный обработчик ошибок (валидация/PG/HttpException/500).
    { provide: APP_FILTER, useClass: AllExceptionsFilter },
  ],
})
export class AppModule {}
```

- [ ] **Step 3: Verification — read-only паритет НЕ сломан**

Run: `npm run nest:build && node --test test/nest/groups.e2e.test.js`
Expected: PASS (5 тестов; 404 по-прежнему `{error:'Not found'}`, 401/403 на месте).
Run: `node --test test/nest/whoami.test.js`
Expected: PASS (401/403 от guard'ов не изменились).

- [ ] **Step 4: Verification checkpoint**

Run: `npm run nest:test`
Expected: все nest-тесты зелёные. Показать вывод, дождаться ревью.

---

### Task 4: Репозиторий и сервис — методы записи (SQL дословно)

**Files:**
- Modify: `src/modules/groups/groups.repository.ts`
- Modify: `src/modules/groups/groups.service.ts`
- Test: `test/nest/groups.repository.write.test.js`

- [ ] **Step 1: Написать падающий unit-тест репозитория (фейковый DbService с tx)**

`test/nest/groups.repository.write.test.js`:
```js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { GroupsRepository } = require('../../dist/modules/groups/groups.repository.js');

// Фейковый DbService: tx прокидывает client с query, записывает все вызовы.
function fakeDb() {
  const calls = [];
  const client = {
    query: async (sql, params) => {
      calls.push({ sql, params });
      if (/INSERT INTO groups/.test(sql)) return { rows: [{ id: 10, name: params[0] }] };
      if (/UPDATE groups SET/.test(sql) && /RETURNING/.test(sql)) return { rows: [{ id: params[0] }] };
      return { rows: [] };
    },
  };
  return {
    calls,
    query: client.query,
    tx: async (fn) => fn(client),
  };
}

test('createGroup: INSERT в groups + слоты, возвращает строку', async () => {
  const db = fakeDb();
  const repo = new GroupsRepository(db);
  const g = await repo.createGroup({
    name: 'X', direction_id: 1, teacher_id: 2, is_individual: false,
    lesson_duration_minutes: 90, lessons_per_week: 1,
    slots: [{ day_of_week: 1, start_time: '10:00' }],
  });
  assert.equal(g.id, 10);
  assert.ok(db.calls.some((c) => /INSERT INTO groups/.test(c.sql)));
  assert.ok(db.calls.some((c) => /INSERT INTO group_schedule_slots/.test(c.sql)));
});

test('updateGroup: нет строки → null', async () => {
  const db = {
    calls: [],
    query: async () => ({ rows: [] }),
    tx: async (fn) => fn({ query: async () => ({ rows: [] }) }),
  };
  const repo = new GroupsRepository(db);
  assert.equal(await repo.updateGroup(999, { name: 'Y' }), null);
});

test('softDeleteGroup: rowCount>0 → true', async () => {
  const db = {
    calls: [],
    query: async () => ({ rowCount: 1 }),
    tx: async (fn) => fn({ query: async () => ({ rowCount: 1 }) }),
  };
  const repo = new GroupsRepository(db);
  assert.equal(await repo.softDeleteGroup(5), true);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `npm run nest:build && node --test test/nest/groups.repository.write.test.js`
Expected: FAIL — методов записи ещё нет.

- [ ] **Step 3: Добавить методы записи в `src/modules/groups/groups.repository.ts`**

Дополнить класс `GroupsRepository` (НЕ трогая существующие `listGroups`/`getGroup`). SQL — дословно из `services/repo/groups.js`. Транзакция — через `this.db.tx`. Добавить в начало файла тип клиента:
```ts
type TxClient = { query: (text: string, params?: unknown[]) => Promise<{ rows: any[]; rowCount?: number }> };
```
Методы (вставить в тело класса `GroupsRepository`):
```ts
  createGroup(input: any) {
    return this.db.tx(async (client: TxClient) => {
      const { rows } = await client.query(
        `INSERT INTO groups
           (name, direction_id, teacher_id, is_individual,
            lesson_duration_minutes, lessons_per_week, group_start_date, vk_chat)
         VALUES ($1, $2, $3, $4, $5, $6, $7, NULLIF($8,''))
         RETURNING *`,
        [
          input.name,
          input.direction_id,
          input.teacher_id,
          !!input.is_individual,
          input.lesson_duration_minutes ?? 90,
          input.lessons_per_week ?? 1,
          input.group_start_date ?? null,
          input.vk_chat ?? null,
        ],
      );
      const group = rows[0];
      for (const s of input.slots || []) {
        await client.query(
          `INSERT INTO group_schedule_slots (group_id, day_of_week, start_time)
           VALUES ($1, $2, $3)`,
          [group.id, s.day_of_week, s.start_time],
        );
      }
      return group;
    });
  }

  updateGroup(id: number | string, input: any) {
    return this.db.tx(async (client: TxClient) => {
      const { rows } = await client.query(
        `UPDATE groups SET
           name                    = COALESCE($2, name),
           direction_id            = COALESCE($3, direction_id),
           teacher_id              = COALESCE($4, teacher_id),
           is_individual           = COALESCE($5, is_individual),
           lesson_duration_minutes = COALESCE($6, lesson_duration_minutes),
           lessons_per_week        = COALESCE($7, lessons_per_week),
           group_start_date        = COALESCE($8, group_start_date),
           vk_chat                 = COALESCE(NULLIF($9,''), vk_chat),
           active                  = COALESCE($10, active)
         WHERE id = $1 RETURNING *`,
        [
          id,
          input.name ?? null,
          input.direction_id ?? null,
          input.teacher_id ?? null,
          input.is_individual ?? null,
          input.lesson_duration_minutes ?? null,
          input.lessons_per_week ?? null,
          input.group_start_date ?? null,
          input.vk_chat ?? null,
          input.active ?? null,
        ],
      );
      if (!rows[0]) return null;
      if (Array.isArray(input.slots)) {
        await client.query('DELETE FROM group_schedule_slots WHERE group_id = $1', [id]);
        for (const s of input.slots) {
          await client.query(
            `INSERT INTO group_schedule_slots (group_id, day_of_week, start_time)
             VALUES ($1, $2, $3)`,
            [id, s.day_of_week, s.start_time],
          );
        }
      }
      return rows[0];
    });
  }

  async softDeleteGroup(id: number | string) {
    const { rowCount } = await this.db.query(
      'UPDATE groups SET active = false WHERE id = $1',
      [id],
    );
    return (rowCount ?? 0) > 0;
  }
```
> `softDeleteGroup` использует `this.db.query` (не tx) — как в оригинале (одиночный UPDATE).
> `DbService.query` уже возвращает результат pg с `rowCount`.

- [ ] **Step 4: Добавить методы в `src/modules/groups/groups.service.ts`**

Дополнить класс `GroupsService`:
```ts
  createGroup(input: any) {
    return this.groupsRepo.createGroup(input);
  }

  updateGroup(id: number | string, input: any) {
    return this.groupsRepo.updateGroup(id, input);
  }

  deleteGroup(id: number | string) {
    return this.groupsRepo.softDeleteGroup(id);
  }
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `npm run nest:build && node --test test/nest/groups.repository.write.test.js`
Expected: PASS (3 теста).

- [ ] **Step 6: Verification checkpoint**

Run: `npm run nest:test`
Expected: все nest-тесты зелёные. Показать вывод, дождаться ревью.

---

### Task 5: Контроллер POST/PATCH/DELETE + e2e

**Files:**
- Modify: `src/modules/groups/groups.controller.ts`
- Test: `test/nest/groups.write.e2e.test.js`

- [ ] **Step 1: Написать падающий e2e-тест**

`test/nest/groups.write.e2e.test.js`:
```js
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
require('dotenv').config();
const request = require('supertest');
const { Test } = require('@nestjs/testing');
const { createFastifyAdapter, registerPlugins } = require('../../dist/bootstrap.js');
const { AppModule } = require('../../dist/app.module.js');
const { sign, COOKIE_NAME } = require('../../services/auth');
const { pool } = require('../../services/db');

const SECRET = process.env.ADMIN_COOKIE_SECRET;
let app;
let dirId = null;
let teacherId = null;
const createdIds = [];

function cookieFor(role) {
  const payload = { account_id: 42, role, iat: Date.now(), exp: Date.now() + 60_000 };
  return `${COOKIE_NAME}=${sign(payload, SECRET)}`;
}

before(async () => {
  const moduleRef = await Test.createTestingModule({ imports: [AppModule] }).compile();
  app = moduleRef.createNestApplication(createFastifyAdapter());
  await registerPlugins(app);
  await app.init();
  await app.getHttpAdapter().getInstance().ready();
  // Реальные FK из БД (приложение рабочее — данные есть). Если пусто — happy-path пропустим.
  const d = await pool.query('SELECT id FROM directions LIMIT 1');
  const t = await pool.query('SELECT id FROM teachers LIMIT 1');
  dirId = d.rows[0]?.id ?? null;
  teacherId = t.rows[0]?.id ?? null;
});

after(async () => {
  // Чистим за собой созданные тестом группы (и их слоты).
  for (const id of createdIds) {
    await pool.query('DELETE FROM group_schedule_slots WHERE group_id = $1', [id]);
    await pool.query('DELETE FROM groups WHERE id = $1', [id]);
  }
  if (app) await app.close();
});

test('POST без cookie → 401', async () => {
  const res = await request(app.getHttpServer()).post('/api/admin/groups').send({});
  assert.equal(res.status, 401);
});

test('POST teacher-cookie → 403', async () => {
  const res = await request(app.getHttpServer())
    .post('/api/admin/groups').set('Cookie', cookieFor('teacher')).send({});
  assert.equal(res.status, 403);
});

test('POST кривое тело (пустой name) → 400 { error:"Validation failed", details }', async () => {
  const res = await request(app.getHttpServer())
    .post('/api/admin/groups').set('Cookie', cookieFor('admin'))
    .send({ name: '', direction_id: 1, teacher_id: 1, is_individual: false,
            lesson_duration_minutes: 90, lessons_per_week: 1 });
  assert.equal(res.status, 400);
  assert.equal(res.body.error, 'Validation failed');
  assert.ok(res.body.details && typeof res.body.details === 'object');
});

test('POST валидное тело → 201 + созданная группа; PATCH → 200; DELETE → 204', async (t) => {
  if (dirId == null || teacherId == null) {
    t.skip('нет directions/teachers в БД — happy-path пропущен');
    return;
  }
  // POST
  const created = await request(app.getHttpServer())
    .post('/api/admin/groups').set('Cookie', cookieFor('admin'))
    .send({ name: '__e2e_test_group__', direction_id: dirId, teacher_id: teacherId,
            is_individual: false, lesson_duration_minutes: 90, lessons_per_week: 1,
            slots: [{ day_of_week: 1, start_time: '10:00' }] });
  assert.equal(created.status, 201);
  assert.equal(created.body.name, '__e2e_test_group__');
  const id = created.body.id;
  createdIds.push(id);

  // PATCH
  const patched = await request(app.getHttpServer())
    .patch(`/api/admin/groups/${id}`).set('Cookie', cookieFor('admin'))
    .send({ name: '__e2e_test_group_renamed__' });
  assert.equal(patched.status, 200);
  assert.equal(patched.body.name, '__e2e_test_group_renamed__');

  // DELETE (мягкое)
  const del = await request(app.getHttpServer())
    .delete(`/api/admin/groups/${id}`).set('Cookie', cookieFor('admin'));
  assert.equal(del.status, 204);

  // После мягкого удаления группа существует с active=false
  const after = await request(app.getHttpServer())
    .get(`/api/admin/groups/${id}`).set('Cookie', cookieFor('admin'));
  assert.equal(after.status, 200);
  assert.equal(after.body.active, false);
});

test('PATCH несуществующей → 404 { error:"Not found" }', async () => {
  const res = await request(app.getHttpServer())
    .patch('/api/admin/groups/999999999').set('Cookie', cookieFor('admin'))
    .send({ name: 'x' });
  assert.equal(res.status, 404);
  assert.deepEqual(res.body, { error: 'Not found' });
});

test('DELETE несуществующей → 404', async () => {
  const res = await request(app.getHttpServer())
    .delete('/api/admin/groups/999999999').set('Cookie', cookieFor('admin'));
  assert.equal(res.status, 404);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `npm run nest:build && node --test test/nest/groups.write.e2e.test.js`
Expected: FAIL — POST/PATCH/DELETE ещё не существуют (404/405).

- [ ] **Step 3: Добавить методы записи в `src/modules/groups/groups.controller.ts`**

Дополнить импорты и класс (НЕ трогая существующие `list`/`getOne`):
```ts
import {
  Controller, Get, Post, Patch, Delete, Param, Query, Body,
  HttpCode, NotFoundException, UseGuards,
} from '@nestjs/common';
import { CreateGroupDto } from './dto/create-group.dto';
import { UpdateGroupDto } from './dto/update-group.dto';
```
Методы в тело контроллера:
```ts
  @Post()
  @HttpCode(201)
  create(@Body() dto: CreateGroupDto) {
    return this.groupsService.createGroup(dto);
  }

  @Patch(':id')
  async update(@Param('id') id: string, @Body() dto: UpdateGroupDto) {
    const updated = await this.groupsService.updateGroup(id, dto);
    if (!updated) {
      throw new NotFoundException({ error: 'Not found' });
    }
    return updated;
  }

  @Delete(':id')
  @HttpCode(204)
  async remove(@Param('id') id: string) {
    const ok = await this.groupsService.deleteGroup(id);
    if (!ok) {
      throw new NotFoundException({ error: 'Not found' });
    }
  }
```
> `@HttpCode(201)` на POST и `@HttpCode(204)` на DELETE — точные коды как у Express.
> Валидация тела идёт автоматически глобальным `ZodValidationPipe` (DTO — ZodDto), ошибка → 400 через фильтр.

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `npm run nest:build && node --test test/nest/groups.write.e2e.test.js`
Expected: PASS (happy-path выполняется при наличии directions/teachers, иначе `skip`).

- [ ] **Step 5: Verification checkpoint — сверка с Express**

Поднять оба процесса, создать группу через оба и сверить форму ответа (admin-cookie из Express-логина):
```bash
# POST одинаковым телом в Express и Nest, сравнить статус (201) и форму ответа.
```
Express-роут активен — обе записи реальны (потом удалить тестовую группу из БД). Показать сравнение, дождаться ревью.

---

### Task 6: Финальная регрессия + документация

**Files:**
- Modify: `CLAUDE.md` (раздел NestJS — отметить write-операции групп, nestjs-zod, общий фильтр ошибок)
- Modify: `docs/ROADMAP.md` (обновить статус Фазы 2)

- [ ] **Step 1: Полный прогон nest-тестов**

Run: `npm run nest:build && npm run nest:test`
Expected: зелёные (groups-dto, pg-errors, groups.repository.write, groups.write.e2e + все прежние).

- [ ] **Step 2: Регрессия**

Run: `npm test`
Expected: полный набор зелёный (Express не сломан вынесением PG_ERRORS).

- [ ] **Step 3: Обновить `CLAUDE.md`**

В разделе NestJS, в строке «Перенесено: modules/groups» дописать: теперь и **запись** (POST/PATCH/DELETE),
валидация через `nestjs-zod` (DTO из `shared/schemas.js` — один источник правил), общий `AllExceptionsFilter`
(`common/filters/`) переводит ошибки валидации и БД в HTTP-коды как Express; карта `PG_ERRORS` вынесена в
`shared/pg-errors.js` (общая Express+Nest). Удаление — мягкое (`active=false`).

- [ ] **Step 4: Обновить `docs/ROADMAP.md`**

В строке Фазы 2 заменить «(только чтение...)» на «(полный CRUD: чтение + запись через nestjs-zod, общий фильтр ошибок PG)».

- [ ] **Step 5: Verification checkpoint — финал**

Подтвердить: `npm run nest:test` зелено, `npm test` зелено, оба процесса поднимаются. Показать сводку.

---

## Self-Review (против спеки `2026-06-08-phase2-groups-write-design.md`)

| Требование спеки | Где в плане |
|---|---|
| POST/PATCH/DELETE, коды 201/200/204/404 | Task 5 (`@HttpCode`, 404 через NotFoundException) |
| Доступ manager/admin | контроллер уже под guard'ами (read-only Task), наследуется |
| Валидация через nestjs-zod на существующих схемах | Task 1 (createZodDto) + Task 3 (APP_PIPE) |
| Формат 400 `{error:'Validation failed', details}` | Task 3, ветка 1 фильтра |
| SQL записи дословно (+tx) | Task 4, Step 3 |
| Мягкое удаление | Task 4 (`softDeleteGroup`) + Task 5 e2e (active=false) |
| Общий фильтр PG→HTTP, не ломая 404/401/403 | Task 3 (ветки 2 и 3) + Step 3 проверка read-only |
| PG_ERRORS вынесена в shared (DRY) | Task 2 |
| Расхождение 23505 → русское сообщение | Task 2 (общая карта) + Task 3 (ветка 2 для всех кодов) |
| e2e с очисткой данных | Task 5, Step 1 (`after()` удаляет created) |
| Спайк совместимости nestjs-zod ↔ zod v4 | Task 1, Steps 1/3 (СТОП при несовместимости) |
| Регрессия read-only + Express | Task 3 Step 3, Task 6 |

**Placeholder-скан:** код полный в каждом шаге; «add validation/TODO» отсутствуют.

**Type-consistency:** `CreateGroupDto`/`UpdateGroupDto` (Task 1) используются в контроллере (Task 5); `AllExceptionsFilter` (Task 3) и `PG_ERRORS` (Task 2) согласованы; методы репозитория `createGroup`/`updateGroup`/`softDeleteGroup` (Task 4) зовутся сервисом `createGroup`/`updateGroup`/`deleteGroup` и контроллером (`create`/`update`/`remove`); `TxClient` определён в repository. `ZodValidationException`/`ZodValidationPipe`/`createZodDto` — из `nestjs-zod`.

**Осознанные риски:** nestjs-zod ↔ zod v4 (спайк Task 1 со СТОП-условием и фолбэком); happy-path e2e зависит от наличия directions/teachers (иначе `skip`, не падение).
