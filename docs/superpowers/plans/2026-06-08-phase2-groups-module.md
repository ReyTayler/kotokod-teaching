# Фаза 2 — раздел «Группы» на чистом NestJS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перенести раздел «Группы» (только чтение) с Express на чистый NestJS по каноничным паттернам, заложив структуру (`common/`, `modules/`), которую повторят все следующие разделы.

**Architecture:** Каждый раздел = папка в `src/modules/<name>/` с одинаковым набором: `*.controller.ts` (приём HTTP), `*.service.ts` (правила), `*.repository.ts` (единственное место с SQL), `dto/`. Сквозные вещи (guard'ы, декораторы, пагинация) — в `src/common/`. SQL-запросы переносятся из старых `services/repo/*.js` **дословно**; e2e-тесты сверяют ответ со старым Express один-в-один. Пул БД (`services/db.js`) остаётся общим для Express и Nest на время миграции (два пула к одной базе держать нельзя) — это единственный санкционированный мост к данным, его перенос в TS — отдельная уборка после удаления Express.

**Tech Stack:** NestJS 11 + Fastify 5, TS 6, `pg` (общий пул через `DbService`), `qs` (парсер query для паритета фильтров), `node --test` + `supertest`.

---

## ⚠️ Адаптация под отсутствие git

Проект не под version control. Поэтому **шаг «Commit» в каждой задаче заменён на «Verification checkpoint»**: прогнать проверку, показать вывод, дождаться ревью пользователя перед следующей задачей. Не переходить дальше без зелёной проверки.

## File Structure (цель после плана)

```
src/
├── main.ts                      # bootstrap (правка: общий FastifyAdapter-фабрикой)
├── bootstrap.ts                 # registerPlugins + createFastifyAdapter (правка)
├── app.module.ts                # + GroupsModule, импорты после реорга (правка)
├── common/
│   ├── guards/
│   │   ├── auth.guard.ts         # ← перенос из src/auth/auth.guard.ts
│   │   └── roles.guard.ts        # ← перенос из src/auth/roles.guard.ts
│   ├── decorators/
│   │   └── roles.decorator.ts    # ← перенос из src/auth/roles.decorator.ts
│   ├── security.module.ts        # ← замена src/auth/auth.module.ts (провайдит/экспортит guard'ы)
│   └── pagination/
│       └── pagination.ts         # ← порт services/pagination.js в TS
├── config/
│   ├── env.validation.ts         # без изменений
│   └── security.ts               # без изменений
├── database/
│   ├── db.service.ts             # ← перенос из src/db/db.service.ts
│   └── db.module.ts              # ← перенос из src/db/db.module.ts
└── modules/
    ├── health/
    │   └── health.controller.ts  # ← перенос из src/health/health.controller.ts
    └── groups/
        ├── groups.module.ts
        ├── groups.controller.ts
        ├── groups.service.ts
        ├── groups.repository.ts
        └── dto/
            └── list-groups-query.dto.ts
```

---

### Task 1: Общий FastifyAdapter с `qs`-парсером query (паритет фильтров)

**Files:**
- Modify: `package.json` (deps: `qs`, `@types/qs`)
- Modify: `src/bootstrap.ts` (добавить `createFastifyAdapter`)
- Modify: `src/main.ts` (использовать фабрику)
- Modify: `test/nest/health.test.js`, `test/nest/whoami.test.js` (использовать фабрику)

- [ ] **Step 1: Установить `qs`**

Run: `npm install qs && npm install -D @types/qs`
Expected: установка без ERESOLVE.

- [ ] **Step 2: Добавить фабрику адаптера в `src/bootstrap.ts`**

В начало файла (после существующих импортов) добавить:
```ts
import { FastifyAdapter } from '@nestjs/platform-fastify';
import qs from 'qs';

/**
 * Единая фабрика FastifyAdapter. querystringParser на qs — чтобы вложенные
 * параметры фильтров `?filter[name]=x&filter[active]=true` парсились в объект
 * `{ filter: { name, active } }`, как это делает Express (qs). Без этого
 * пагинаторные фильтры в Nest молча не работали бы. Используется и в main.ts,
 * и в e2e — прод и тесты поднимают идентичный парсер (как registerPlugins).
 */
export function createFastifyAdapter(): FastifyAdapter {
  return new FastifyAdapter({
    querystringParser: (str) => qs.parse(str) as Record<string, unknown>,
  });
}
```

- [ ] **Step 3: Использовать фабрику в `src/main.ts`**

Заменить импорт `FastifyAdapter` и его использование:
```ts
import { NestFastifyApplication } from '@nestjs/platform-fastify';
import { registerPlugins, createFastifyAdapter } from './bootstrap';
```
```ts
  const app = await NestFactory.create<NestFastifyApplication>(
    AppModule,
    createFastifyAdapter(),
    { bufferLogs: true },
  );
```

- [ ] **Step 4: Использовать фабрику в существующих e2e**

В `test/nest/health.test.js` и `test/nest/whoami.test.js` заменить:
```js
const { FastifyAdapter } = require('@nestjs/platform-fastify');
```
```js
const { createFastifyAdapter } = require('../../dist/bootstrap.js');
```
и `new FastifyAdapter()` → `createFastifyAdapter()`.

- [ ] **Step 5: Verification checkpoint**

Run: `npm run nest:build && npm run nest:test`
Expected: все существующие nest-тесты (env.validation, security, health, whoami) зелёные. Показать вывод, дождаться ревью.

---

### Task 2: Привести каркас к каноничной структуре (организационный шаг, поведение не меняется)

**Files:**
- Move: `src/auth/auth.guard.ts` → `src/common/guards/auth.guard.ts`
- Move: `src/auth/roles.guard.ts` → `src/common/guards/roles.guard.ts`
- Move: `src/auth/roles.decorator.ts` → `src/common/decorators/roles.decorator.ts`
- Replace: `src/auth/auth.module.ts` → `src/common/security.module.ts`
- Move: `src/db/db.service.ts` → `src/database/db.service.ts`
- Move: `src/db/db.module.ts` → `src/database/db.module.ts`
- Move: `src/health/health.controller.ts` → `src/modules/health/health.controller.ts`
- Modify: `src/app.module.ts` (импорты)
- Delete: пустые папки `src/auth/`, `src/db/`, `src/health/`

- [ ] **Step 1: Перенести guard'ы в `src/common/guards/`**

Создать `src/common/guards/auth.guard.ts` — содержимое прежнего `src/auth/auth.guard.ts` БЕЗ изменений (путь `require('../../services/auth')` остаётся корректным: `src/common/guards/` → на 2 уровня вверх до `src/`, дальше нужно `../../../services/auth`).
⚠️ Глубина изменилась: было `src/auth/` (2 вверх до корня), стало `src/common/guards/` (3 вверх). Исправить require на:
```ts
const { verify, COOKIE_NAME } = require('../../../services/auth');
```
Остальное — как в оригинале (`export interface SessionAccount`, класс `AuthGuard`).

- [ ] **Step 2: Перенести RolesGuard**

Создать `src/common/guards/roles.guard.ts` — как оригинал, поправить относительные импорты:
```ts
import { ROLES_KEY } from '../decorators/roles.decorator';
import type { SessionAccount } from './auth.guard';
```

- [ ] **Step 3: Перенести декоратор**

Создать `src/common/decorators/roles.decorator.ts` — содержимое прежнего `src/auth/roles.decorator.ts` БЕЗ изменений (импортов из проекта нет).

- [ ] **Step 4: Заменить auth.module на security.module**

Создать `src/common/security.module.ts`:
```ts
import { Module } from '@nestjs/common';
import { AuthGuard } from './guards/auth.guard';
import { RolesGuard } from './guards/roles.guard';

/**
 * Сквозной модуль безопасности: провайдит и экспортит guard'ы, чтобы их можно
 * было применять (@UseGuards) в любом feature-модуле. Реальной auth-фичи
 * (логин/2FA) тут пока нет — она остаётся в Express до её переноса.
 */
@Module({
  providers: [AuthGuard, RolesGuard],
  exports: [AuthGuard, RolesGuard],
})
export class SecurityModule {}
```

- [ ] **Step 5: Перенести БД в `src/database/`**

Создать `src/database/db.service.ts` — содержимое прежнего `src/db/db.service.ts`, поправить require (было `src/db/` → 2 вверх; стало `src/database/` → тоже 2 вверх до корня, путь не меняется):
```ts
const { pool, tx } = require('../../services/db');
```
(глубина та же — `src/database/db.service.ts` и `src/db/db.service.ts` обе на 2 уровня от корня; require остаётся `../../services/db`).

Создать `src/database/db.module.ts` — как оригинал, импорт `./db.service` без изменений.

- [ ] **Step 6: Перенести health-контроллер в `src/modules/health/`**

Создать `src/modules/health/health.controller.ts` — как оригинал, поправить импорты на новые пути:
```ts
import { DbService } from '../../database/db.service';
import { AuthGuard } from '../../common/guards/auth.guard';
import { RolesGuard } from '../../common/guards/roles.guard';
import { Roles } from '../../common/decorators/roles.decorator';
```
Тело (`health()`, `whoami()`) — без изменений.

- [ ] **Step 7: Обновить `src/app.module.ts`**

```ts
import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { LoggerModule } from 'nestjs-pino';
import { HealthController } from './modules/health/health.controller';
import { DbModule } from './database/db.module';
import { SecurityModule } from './common/security.module';
import { validateEnv } from './config/env.validation';

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
  ],
  controllers: [HealthController],
})
export class AppModule {}
```

- [ ] **Step 8: Удалить старые файлы/папки**

Удалить `src/auth/auth.guard.ts`, `src/auth/roles.guard.ts`, `src/auth/roles.decorator.ts`, `src/auth/auth.module.ts`, `src/db/db.service.ts`, `src/db/db.module.ts`, `src/health/health.controller.ts` и опустевшие папки `src/auth/`, `src/db/`, `src/health/`.

- [ ] **Step 9: Verification checkpoint**

Run: `npm run nest:build && npm run nest:test`
Expected: сборка чистая, все nest-тесты зелёные (поведение не изменилось — только размещение файлов). Показать вывод, дождаться ревью.

---

### Task 3: Порт пагинации в `src/common/pagination/pagination.ts` (TS)

**Files:**
- Create: `src/common/pagination/pagination.ts`
- Test: `test/nest/pagination.test.js`

- [ ] **Step 1: Написать падающий тест**

`test/nest/pagination.test.js`:
```js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const {
  paginate,
  parsePaginationRequest,
  F,
} = require('../../dist/common/pagination/pagination.js');

test('parsePaginationRequest: дефолты и коэрсинг', () => {
  const r = parsePaginationRequest({}, { sortBy: 'name', sortDir: 'asc' });
  assert.equal(r.page, 1);
  assert.equal(r.page_size, 50);
  assert.equal(r.sort_by, 'name');
  assert.equal(r.sort_dir, 'asc');
  assert.deepEqual(r.filters, {});
});

test('parsePaginationRequest: невалидный sort_dir → дефолт', () => {
  const r = parsePaginationRequest({ sort_dir: 'sideways' }, { sortBy: 'id' });
  assert.equal(r.sort_dir, 'desc');
});

test('paginate: whitelist sort_by (неизвестный → defaultSortBy), форма ответа', async () => {
  const captured = [];
  const fakeQuery = async (sql, params) => {
    captured.push({ sql, params });
    if (/COUNT\(\*\)/.test(sql)) return { rows: [{ total: 7 }] };
    return { rows: [{ id: 1 }, { id: 2 }] };
  };
  const config = {
    sortable: { name: 't.name', id: 't.id' },
    defaultSortBy: 'name',
    defaultSortDir: 'asc',
    from: 'FROM t',
    selectColumns: 't.*',
    secondarySort: 't.id DESC',
    filters: { active: F.bool('t.active') },
  };
  const out = await paginate(
    config,
    { page: 1, page_size: 50, sort_by: 'HACK; DROP', sort_dir: 'asc', filters: { active: 'true' } },
    fakeQuery,
  );
  assert.equal(out.total, 7);
  assert.equal(out.page, 1);
  assert.equal(out.page_size, 50);
  assert.deepEqual(out.rows, [{ id: 1 }, { id: 2 }]);
  const rowsSql = captured.find((c) => !/COUNT/.test(c.sql)).sql;
  // неизвестный sort_by НЕ попал в SQL — взят whitelisted defaultSortBy:
  assert.ok(rowsSql.includes('t.name'));
  assert.ok(!rowsSql.includes('HACK'));
  // фильтр active собрался в WHERE:
  assert.ok(/WHERE/.test(rowsSql));
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `npm run nest:build && node --test test/nest/pagination.test.js`
Expected: FAIL — `Cannot find module '../../dist/common/pagination/pagination.js'`.

- [ ] **Step 3: Реализовать `src/common/pagination/pagination.ts`**

Дословный порт `services/pagination.js` в TS. Отличие: вместо `require('./db')` пула функция `paginate` принимает `query`-функцию (через неё пройдёт `DbService`) — так репозиторий остаётся единственным владельцем подключения.

```ts
// Порт services/pagination.js в TypeScript. Логика сборки SQL не меняется
// (whitelist sort_by, параметризованные фильтры) — меняется только источник
// подключения: query-функция передаётся снаружи (DbService), а не берётся
// из глобального пула.

export type QueryFn = (
  text: string,
  params?: unknown[],
) => Promise<{ rows: any[] }>;

export type FilterBuilder = (value: unknown, addParam: (v: unknown) => string) => string;

export interface PaginateConfig {
  sortable: Record<string, string>;
  defaultSortBy: string;
  defaultSortDir?: 'asc' | 'desc';
  filters?: Record<string, FilterBuilder>;
  from: string;
  countFrom?: string;
  selectColumns: string;
  groupBy?: string;
  secondarySort?: string;
}

export interface PaginationRequest {
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: 'asc' | 'desc';
  filters: Record<string, unknown>;
}

export interface PaginatedResult {
  rows: any[];
  total: number;
  page: number;
  page_size: number;
}

/** Готовые билдеры WHERE-условий (дословно из services/pagination.js). */
export const F = {
  like: (col: string): FilterBuilder => (v, p) =>
    `LOWER(${col}) LIKE ${p('%' + String(v).toLowerCase() + '%')}`,
  likeNullable: (col: string): FilterBuilder => (v, p) =>
    `LOWER(COALESCE(${col}, '')) LIKE ${p('%' + String(v).toLowerCase() + '%')}`,
  exact: (col: string): FilterBuilder => (v, p) => `${col} = ${p(v)}`,
  num: (col: string): FilterBuilder => (v, p) => `${col} = ${p(Number(v))}`,
  bool: (col: string): FilterBuilder => (v, p) =>
    `${col} = ${p(v === 'true' || v === true)}`,
  gte: (col: string): FilterBuilder => (v, p) => `${col} >= ${p(v)}`,
  lte: (col: string): FilterBuilder => (v, p) => `${col} <= ${p(v)}`,
};

/** Парсит HTTP query → нормализованный pagination request. */
export function parsePaginationRequest(
  query: Record<string, any> = {},
  defaults: {
    sortBy?: string;
    sortDir?: 'asc' | 'desc';
    pageSize?: number;
    maxPageSize?: number;
  } = {},
): PaginationRequest {
  const pageSize = Math.min(
    defaults.maxPageSize || 500,
    Math.max(1, Number(query.page_size) || defaults.pageSize || 50),
  );
  const filters =
    query.filter && typeof query.filter === 'object' ? { ...query.filter } : {};
  return {
    page: Math.max(1, Number(query.page) || 1),
    page_size: pageSize,
    sort_by: typeof query.sort_by === 'string' ? query.sort_by : defaults.sortBy || 'id',
    sort_dir:
      query.sort_dir === 'asc' || query.sort_dir === 'desc'
        ? query.sort_dir
        : defaults.sortDir || 'desc',
    filters,
  };
}

/** Выполняет paginated-запрос через переданную query-функцию. */
export async function paginate(
  config: PaginateConfig,
  request: Partial<PaginationRequest>,
  query: QueryFn,
): Promise<PaginatedResult> {
  const page = Math.max(1, Number(request.page) || 1);
  const page_size = Math.max(1, Number(request.page_size) || 50);
  const sort_by = request.sort_by || config.defaultSortBy;
  const sort_dir =
    request.sort_dir === 'asc' || request.sort_dir === 'desc'
      ? request.sort_dir
      : config.defaultSortDir || 'desc';
  const filters = request.filters || {};

  const sortCol = config.sortable[sort_by] || config.sortable[config.defaultSortBy];
  if (!sortCol) {
    throw new Error(
      `paginate: defaultSortBy '${config.defaultSortBy}' missing in sortable map`,
    );
  }
  const sortOrder = sort_dir === 'asc' ? 'ASC' : 'DESC';

  const params: unknown[] = [];
  const addParam = (val: unknown) => {
    params.push(val);
    return `$${params.length}`;
  };
  const conds: string[] = [];
  for (const [key, builder] of Object.entries(config.filters || {})) {
    const val = (filters as Record<string, unknown>)[key];
    if (val === undefined || val === null || val === '') continue;
    const sql = builder(val, addParam);
    if (sql) conds.push(sql);
  }
  const where = conds.length ? `WHERE ${conds.join(' AND ')}` : '';
  const groupBy = config.groupBy ? `GROUP BY ${config.groupBy}` : '';
  const tieBreaker = config.secondarySort || 'id DESC';

  const countFrom = config.countFrom || config.from;
  const countSql = `SELECT COUNT(*)::int AS total ${countFrom} ${where}`;
  const countParams = params.slice();

  const offset = Math.max(0, (page - 1) * page_size);
  const limitPh = addParam(page_size);
  const offsetPh = addParam(offset);

  const rowsSql = `
    SELECT ${config.selectColumns}
    ${config.from}
    ${where}
    ${groupBy}
    ORDER BY ${sortCol} ${sortOrder}, ${tieBreaker}
    LIMIT ${limitPh} OFFSET ${offsetPh}
  `;

  const [countRes, rowsRes] = await Promise.all([
    query(countSql, countParams),
    query(rowsSql, params),
  ]);

  return {
    rows: rowsRes.rows,
    total: countRes.rows[0].total,
    page,
    page_size,
  };
}
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `npm run nest:build && node --test test/nest/pagination.test.js`
Expected: PASS (3 теста).

- [ ] **Step 5: Verification checkpoint**

Run: `npm run nest:test`
Expected: все nest-тесты зелёные. Показать вывод, дождаться ревью.

---

### Task 4: Репозиторий и сервис «Группы»

**Files:**
- Create: `src/modules/groups/groups.repository.ts`
- Create: `src/modules/groups/groups.service.ts`
- Test: `test/nest/groups.repository.test.js`

- [ ] **Step 1: Написать падающий тест репозитория (с фейковым DbService)**

`test/nest/groups.repository.test.js`:
```js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { GroupsRepository } = require('../../dist/modules/groups/groups.repository.js');

function fakeDb(rowsByMatcher) {
  const calls = [];
  return {
    calls,
    query: async (sql, params) => {
      calls.push({ sql, params });
      for (const [re, rows] of rowsByMatcher) {
        if (re.test(sql)) return { rows };
      }
      return { rows: [] };
    },
  };
}

test('getGroup: запрос по id, возвращает первую строку или null', async () => {
  const db = fakeDb([[/FROM groups g/, [{ id: 5, name: 'A', slots: [] }]]]);
  const repo = new GroupsRepository(db);
  const g = await repo.getGroup(5);
  assert.equal(g.id, 5);
  assert.equal(db.calls[0].params[0], 5);
  assert.ok(/WHERE g\.id = \$1/.test(db.calls[0].sql));
});

test('getGroup: пусто → null', async () => {
  const db = fakeDb([]);
  const repo = new GroupsRepository(db);
  assert.equal(await repo.getGroup(999), null);
});

test('listGroups: возвращает форму { rows, total, page, page_size }', async () => {
  const db = fakeDb([
    [/COUNT\(\*\)/, [{ total: 3 }]],
    [/FROM\s+groups g/, [{ id: 1 }, { id: 2 }]],
  ]);
  const repo = new GroupsRepository(db);
  const out = await repo.listGroups({
    page: 1, page_size: 50, sort_by: 'name', sort_dir: 'asc', filters: {},
  });
  assert.equal(out.total, 3);
  assert.deepEqual(out.rows, [{ id: 1 }, { id: 2 }]);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `npm run nest:build && node --test test/nest/groups.repository.test.js`
Expected: FAIL — `Cannot find module '.../groups.repository.js'`.

- [ ] **Step 3: Реализовать `src/modules/groups/groups.repository.ts`**

SQL перенесён ДОСЛОВНО из `services/repo/groups.js` (read-only часть: `GROUP_SELECT_WITH_SLOTS`, `GROUPS_PAGINATION`, `listGroups`, `getGroup`). Запросы идут через `DbService`.

```ts
import { Injectable } from '@nestjs/common';
import { DbService } from '../../database/db.service';
import {
  paginate,
  F,
  type PaginateConfig,
  type PaginationRequest,
} from '../../common/pagination/pagination';

// Дословно из services/repo/groups.js — текст SQL не менялся.
const GROUP_SELECT_WITH_SLOTS = `
  SELECT g.*,
    COALESCE(
      json_agg(
        json_build_object('day_of_week', s.day_of_week, 'start_time', s.start_time::text)
        ORDER BY s.day_of_week, s.start_time
      ) FILTER (WHERE s.id IS NOT NULL),
      '[]'
    ) AS slots
  FROM groups g
  LEFT JOIN group_schedule_slots s ON s.group_id = g.id
`;

const GROUPS_PAGINATION: PaginateConfig = {
  sortable: {
    id: 'g.id',
    name: 'g.name',
    direction_id: 'g.direction_id',
    teacher_id: 'g.teacher_id',
    lesson_duration_minutes: 'g.lesson_duration_minutes',
    lessons_per_week: 'g.lessons_per_week',
    group_start_date: 'g.group_start_date',
    active: 'g.active',
  },
  defaultSortBy: 'name',
  defaultSortDir: 'asc',
  from: `
    FROM groups g
    LEFT JOIN group_schedule_slots s ON s.group_id = g.id
    LEFT JOIN directions d           ON d.id = g.direction_id
    LEFT JOIN teachers   te          ON te.id = g.teacher_id
  `,
  countFrom: 'FROM groups g',
  selectColumns: `
    g.*,
    d.name  AS direction_name,
    d.color AS direction_color,
    te.name AS teacher_name,
    COALESCE(
      json_agg(
        json_build_object('day_of_week', s.day_of_week, 'start_time', s.start_time::text)
        ORDER BY s.day_of_week, s.start_time
      ) FILTER (WHERE s.id IS NOT NULL),
      '[]'
    ) AS slots
  `,
  groupBy: 'g.id, d.id, te.id',
  secondarySort: 'g.id DESC',
  filters: {
    name: F.like('g.name'),
    direction_id: F.num('g.direction_id'),
    teacher_id: F.num('g.teacher_id'),
    is_individual: F.bool('g.is_individual'),
    active: F.bool('g.active'),
  },
};

@Injectable()
export class GroupsRepository {
  constructor(private readonly db: DbService) {}

  listGroups(request: Partial<PaginationRequest>) {
    return paginate(GROUPS_PAGINATION, request, (text, params) =>
      this.db.query(text, params),
    );
  }

  async getGroup(id: number | string) {
    const { rows } = await this.db.query(
      `${GROUP_SELECT_WITH_SLOTS} WHERE g.id = $1 GROUP BY g.id`,
      [id],
    );
    return rows[0] || null;
  }
}
```

- [ ] **Step 4: Реализовать `src/modules/groups/groups.service.ts`**

Тонкий сервис: для чтения бизнес-правил нет, делегирует репозиторию. Слой существует ради единообразия (во всех разделах контроллер зовёт сервис, не репозиторий напрямую).

```ts
import { Injectable } from '@nestjs/common';
import { GroupsRepository } from './groups.repository';
import type { PaginationRequest } from '../../common/pagination/pagination';

@Injectable()
export class GroupsService {
  constructor(private readonly groupsRepo: GroupsRepository) {}

  listGroups(request: Partial<PaginationRequest>) {
    return this.groupsRepo.listGroups(request);
  }

  getGroup(id: number | string) {
    return this.groupsRepo.getGroup(id);
  }
}
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `npm run nest:build && node --test test/nest/groups.repository.test.js`
Expected: PASS (3 теста).

- [ ] **Step 6: Verification checkpoint**

Run: `npm run nest:test`
Expected: все nest-тесты зелёные. Показать вывод, дождаться ревью.

---

### Task 5: Контроллер, DTO, модуль «Группы» + e2e-паритет

**Files:**
- Create: `src/modules/groups/dto/list-groups-query.dto.ts`
- Create: `src/modules/groups/groups.controller.ts`
- Create: `src/modules/groups/groups.module.ts`
- Modify: `src/app.module.ts` (добавить `GroupsModule`)
- Test: `test/nest/groups.e2e.test.js`

- [ ] **Step 1: Написать падающий e2e-тест (supertest, реальная БД)**

`test/nest/groups.e2e.test.js`:
```js
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const request = require('supertest');
const { Test } = require('@nestjs/testing');
const { createFastifyAdapter } = require('../../dist/bootstrap.js');
const { AppModule } = require('../../dist/app.module.js');
const { sign, COOKIE_NAME } = require('../../services/auth');

const SECRET = process.env.ADMIN_COOKIE_SECRET;
let app;

function cookieFor(role) {
  const payload = { account_id: 42, role, iat: Date.now(), exp: Date.now() + 60_000 };
  return `${COOKIE_NAME}=${sign(payload, SECRET)}`;
}

before(async () => {
  const moduleRef = await Test.createTestingModule({ imports: [AppModule] }).compile();
  app = moduleRef.createNestApplication(createFastifyAdapter());
  await app.init();
  await app.getHttpAdapter().getInstance().ready();
});
after(async () => { if (app) await app.close(); });

test('GET /api/admin/groups без cookie → 401', async () => {
  const res = await request(app.getHttpServer()).get('/api/admin/groups');
  assert.equal(res.status, 401);
});

test('GET /api/admin/groups с teacher-cookie → 403', async () => {
  const res = await request(app.getHttpServer())
    .get('/api/admin/groups')
    .set('Cookie', cookieFor('teacher'));
  assert.equal(res.status, 403);
});

test('GET /api/admin/groups (admin) → 200 и форма { rows, total, page, page_size }', async () => {
  const res = await request(app.getHttpServer())
    .get('/api/admin/groups')
    .set('Cookie', cookieFor('admin'));
  assert.equal(res.status, 200);
  assert.ok(Array.isArray(res.body.rows));
  assert.equal(typeof res.body.total, 'number');
  assert.equal(res.body.page, 1);
  assert.equal(typeof res.body.page_size, 'number');
});

test('GET /api/admin/groups с фильтром active=true → 200 (qs-парсер работает)', async () => {
  const res = await request(app.getHttpServer())
    .get('/api/admin/groups?filter[active]=true&sort_by=name&sort_dir=asc')
    .set('Cookie', cookieFor('manager'));
  assert.equal(res.status, 200);
  assert.ok(Array.isArray(res.body.rows));
});

test('GET /api/admin/groups/:id несуществующий → 404 { error: "Not found" }', async () => {
  const res = await request(app.getHttpServer())
    .get('/api/admin/groups/999999999')
    .set('Cookie', cookieFor('admin'));
  assert.equal(res.status, 404);
  assert.deepEqual(res.body, { error: 'Not found' });
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `npm run nest:build && node --test test/nest/groups.e2e.test.js`
Expected: FAIL — маршрут `/api/admin/groups` не существует (404 вместо 401/200).

- [ ] **Step 3: Реализовать DTO query-параметров**

`src/modules/groups/dto/list-groups-query.dto.ts` — типобезопасная форма известных скалярных параметров. Фильтры (`filter[...]`) — динамический объект, его нормализует и валидирует whitelist в `paginate` (защита от SQL-инъекции там), поэтому агрессивную валидацию query здесь не навешиваем.

```ts
/**
 * Параметры списка групп. Скаляры пагинации/сортировки + динамический filter.
 * Жёсткой валидации тут нет намеренно: безопасность сортировки обеспечивает
 * whitelist в paginate(), а тело запроса у read-only отсутствует. Полноценные
 * class-validator DTO появятся на первом write-разделе (вместе с ValidationPipe).
 */
export interface ListGroupsQueryDto {
  page?: string;
  page_size?: string;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
  filter?: Record<string, string>;
}
```

- [ ] **Step 4: Реализовать контроллер**

`src/modules/groups/groups.controller.ts`:
```ts
import {
  Controller,
  Get,
  Param,
  Query,
  Req,
  NotFoundException,
  UseGuards,
} from '@nestjs/common';
import { GroupsService } from './groups.service';
import { AuthGuard } from '../../common/guards/auth.guard';
import { RolesGuard } from '../../common/guards/roles.guard';
import { Roles } from '../../common/decorators/roles.decorator';
import { parsePaginationRequest } from '../../common/pagination/pagination';
import type { ListGroupsQueryDto } from './dto/list-groups-query.dto';

// Зеркало Express: /api/admin/groups за requireAuth + requireRole(manager|admin).
@Controller('api/admin/groups')
@UseGuards(AuthGuard, RolesGuard)
@Roles('manager', 'admin')
export class GroupsController {
  constructor(private readonly groupsService: GroupsService) {}

  @Get()
  list(@Query() query: ListGroupsQueryDto) {
    const params = parsePaginationRequest(query as Record<string, any>, {
      sortBy: 'name',
      sortDir: 'asc',
    });
    return this.groupsService.listGroups(params);
  }

  @Get(':id')
  async getOne(@Param('id') id: string) {
    const group = await this.groupsService.getGroup(id);
    if (!group) {
      // Точный паритет с Express: res.status(404).json({ error: 'Not found' }).
      throw new NotFoundException({ error: 'Not found' });
    }
    return group;
  }
}
```

> Паритет 404: `NotFoundException({ error: 'Not found' })` отдаёт тело `{ "error": "Not found" }` (как Express). По умолчанию Nest обернул бы в `{statusCode, message}` — поэтому передаём объект явно.

- [ ] **Step 5: Реализовать модуль**

`src/modules/groups/groups.module.ts`:
```ts
import { Module } from '@nestjs/common';
import { SecurityModule } from '../../common/security.module';
import { GroupsController } from './groups.controller';
import { GroupsService } from './groups.service';
import { GroupsRepository } from './groups.repository';

@Module({
  imports: [SecurityModule], // guard'ы для @UseGuards
  controllers: [GroupsController],
  providers: [GroupsService, GroupsRepository],
})
export class GroupsModule {}
```

- [ ] **Step 6: Подключить `GroupsModule` в `src/app.module.ts`**

Добавить импорт и в `imports`:
```ts
import { GroupsModule } from './modules/groups/groups.module';
```
```ts
    DbModule,
    SecurityModule,
    GroupsModule,
```

- [ ] **Step 7: Запустить — убедиться, что проходит**

Run: `npm run nest:build && node --test test/nest/groups.e2e.test.js`
Expected: PASS (5 тестов; требуется доступная PG из `.env`).

- [ ] **Step 8: Verification checkpoint — сверка ответа со старым Express**

Поднять оба процесса и сверить список один-в-один (нужна валидная admin-cookie из Express-логина, см. рецепт в `whoami`-проверке Фазы 1):
```bash
npm start                 # Express :3000 (фон)
npm run nest:build && npm run nest:start   # Nest :3001 (фон)
# C — значение cookie session из Express-логина
curl -s "http://localhost:3000/api/admin/groups?sort_by=name&sort_dir=asc" -H "Cookie: session=$C" > express.json
curl -s "http://localhost:3001/api/admin/groups?sort_by=name&sort_dir=asc" -H "Cookie: session=$C" > nest.json
```
Expected: `express.json` и `nest.json` идентичны (порядок, поля, слоты). Показать diff пользователю, дождаться ревью.

---

### Task 6: Финальная регрессия + документация

**Files:**
- Modify: `CLAUDE.md` (обновить раздел NestJS — структура `modules/`/`common/`, перенесён Groups-read)
- Modify: `docs/ROADMAP.md` (отметить старт Фазы 2)

- [ ] **Step 1: Полный прогон nest-тестов**

Run: `npm run nest:build && npm run nest:test`
Expected: зелёные — env.validation, security, health, whoami, pagination, groups.repository, groups.e2e.

- [ ] **Step 2: Регрессия Express-набора**

Run: `npm test`
Expected: 122+ зелёных (старый набор не сломан переносом).

- [ ] **Step 3: Обновить `CLAUDE.md`**

В разделе «NestJS» заменить описание структуры на каноничную: `src/modules/<feature>/` (controller/service/repository/dto), `src/common/` (guards/decorators/pagination/security.module), `src/database/`, `src/config/`. Отметить: первый перенесённый раздел — **Groups (read-only)**, SQL портирован дословно, e2e сверены с Express, Express-роут групп ещё активен до cutover (nginx).

- [ ] **Step 4: Отметить в `docs/ROADMAP.md`**

Добавить строку:
```markdown
- ⏳ **Платформа Фаза 2 — перенос ядра Express → NestJS.** Первый раздел: Groups (read-only) на каноничной структуре modules/common. SQL портирован дословно, e2e-паритет с Express. *План: docs/superpowers/plans/2026-06-08-phase2-groups-module.md.*
```

- [ ] **Step 5: Verification checkpoint — финал**

Подтвердить: `npm run nest:build` чисто, `npm run nest:test` зелено, `npm test` 122+ зелено, оба процесса поднимаются. Показать сводку пользователю.

---

## Self-Review (проверено против спеки `2026-06-08-phase2-groups-module-design.md`)

| Требование спеки | Где в плане |
|---|---|
| Каноничная структура `modules/`/`common/` | Task 2 |
| Общая пагинация в `common/`, портирована в TS | Task 3 |
| `groups.repository.ts` — SQL дословно | Task 4, Step 3 |
| Тонкий `groups.service.ts` | Task 4, Step 4 |
| `groups.controller.ts` — пути/роли паритетны | Task 5, Step 4 |
| Доступ manager/admin | Task 5 (`@Roles('manager','admin')`) |
| 404 `{error:'Not found'}` паритет | Task 5, Step 4 |
| Фильтры `filter[...]` (qs-парсер) | Task 1 + Task 5 e2e |
| e2e-кейсы (401/403/200 list/200 filter/404) | Task 5, Step 1 |
| Верификация nest:test + npm test 122 | Task 6 |
| Express-роут не трогаем до паритета | Task 5, Step 8 (только сверка) |
| #2 nestjs-zod отложен | Task 5, Step 3 (DTO без жёсткой валидации, обоснованно) |
| #4 ExceptionFilter отложен | вне плана (read-only), общий фильтр — на write-разделе |

**Placeholder-скан:** код приведён полностью в каждом шаге; «TODO/добавить обработку» отсутствуют.

**Type-consistency:** `QueryFn`/`PaginateConfig`/`PaginationRequest`/`PaginatedResult`/`F` определены в `pagination.ts` и используются в `groups.repository.ts`/`groups.service.ts`; `DbService` из `database/db.service`; guard'ы/декоратор из `common/`; `sign`/`COOKIE_NAME`/`verify` — из существующего `services/auth.js`; форма ответа `{rows,total,page,page_size}` едина в порту, репозитории и e2e.

**Сознательно вне плана:** перенос самого пула/`tx`/type-parser из `services/db.js` в TS (нужен общий пул, пока жив Express) — уборка после удаления Express; write-разделы Groups (create/update/delete) — следующий план (там же ValidationPipe + ExceptionFilter); cutover на nginx — прод-конфиг.
```
