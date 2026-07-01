# Phase 1 — Каркас NestJS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Поднять пустой NestJS-апп (Fastify-адаптер) рядом с действующим Express, который делит с ним один PostgreSQL и один формат HMAC-session-cookie — фундамент strangler-fig миграции.

**Architecture:** Nest живёт в `src/`, компилируется в CommonJS (`dist/`) и поэтому **переиспословит** существующие JS-сервисы напрямую (`services/auth.js` `verify`, `services/db.js` `pool`, `services/env.js` `schema`) — ничего из HMAC/пула/env не переписываем. Nest слушает отдельный порт (`NEST_PORT`, default 3001); Express остаётся главным приложением на `PORT` (3000). Реального трафика Nest пока не обслуживает — есть только диагностические маршруты `/nest/health` и `/nest/whoami`, доказывающие, что (а) Nest видит ту же БД и (б) валидирует ту же session-cookie, что выписывает Express. Это keystone strangler-fig: на Фазе 2 nginx начнёт перекидывать пути на Nest без перелогина пользователей.

**Tech Stack:** NestJS 11 + `@nestjs/platform-fastify` (fastify v5), `@nestjs/config` + Zod-валидация ENV, `nestjs-pino` (структурные логи), `@fastify/helmet` / `@fastify/cors` / `@fastify/rate-limit` / `@fastify/cookie`, существующий `pg`-пул. Тесты — `node --test` + `supertest` (НЕ Jest: сохраняем единый раннер репозитория, 97+ тестов).

---

## ⚠️ Адаптация под отсутствие git

Проект **не под version control** (`git init` отложен пользователем — см. ROADMAP 🟣). Поэтому **во всех задачах шаг «Commit» заменён на «Verification checkpoint»**: прогнать указанную проверку, показать вывод, остановиться на ревью пользователя перед следующей задачей (инвариант памяти *careful incremental refactor*: верификация + ревью после каждого изменения, поскольку отката через git нет). Не переходить к следующей задаче без зелёной проверки.

## Решения, заземлённые в коде (прочитано перед планом)

- **CommonJS везде** (`package.json` без `"type":"module"`) → скомпилированный Nest (`module: commonjs`) делает `require('../../services/auth')` без ESM-боли.
- **`services/auth.js`** экспортирует `verify(token, secret)` и `COOKIE_NAME='session'`; payload `{account_id, role, iat, exp}`, секрет `ADMIN_COOKIE_SECRET`. AuthGuard переиспользует `verify` — **не дублировать HMAC**.
- **`services/db.js`** экспортирует `{ pool, tx, shutdown }`. DbModule оборачивает этот же `pool` (один пул на процесс Nest).
- **`services/env.js`** экспортирует `schema` (zod v4) + `loadEnv`. ConfigModule переиспользует `schema`, расширяя его `NEST_PORT` — **не дублировать список ENV**.
- **`zod` v4** уже в deps. `helmet`/`cors`/`express-rate-limit` — это Express-версии (остаются у Express); для Fastify ставим `@fastify/*`-аналоги.
- **TS-риск:** в `devDependencies` `typescript ^6.0.3`. Nest 11 официально гоняется на TS 5.x. Поэтому **Задача 0 — спайк**: первым делом доказать, что Nest вообще собирается и стартует в этом окружении. Если `nest build` падает на TS6 — зафиксировать вывод и остановиться (fallback: локальный `typescript@5` только для Nest-tsconfig, решаем с пользователем).

## File Structure

| Файл | Ответственность |
|---|---|
| `nest-cli.json` | конфиг Nest CLI (sourceRoot `src`, output `dist`) |
| `tsconfig.nest.json` | tsconfig для бэкенд-Nest (decorators, commonjs, target es2022); отдельный от `web/admin/tsconfig.json` |
| `src/main.ts` | bootstrap: FastifyAdapter, регистрация плагинов (cookie/helmet/cors/rate-limit), pino-logger, listen `NEST_PORT` |
| `src/app.module.ts` | корневой модуль: импортирует Config/Logger/Db/Rbac/Health |
| `src/config/env.validation.ts` | Zod-`validate` для `@nestjs/config` (переиспользует `services/env.js` schema + `NEST_PORT`) |
| `src/config/security.ts` | чистая функция построения опций cors/rate-limit из ConfigService (тестируемо) |
| `src/db/db.module.ts` + `src/db/db.service.ts` | провайдер `DbService` поверх существующего `pool` (`query`, `ping`) |
| `src/auth/auth.guard.ts` | читает cookie `session`, валидирует через `services/auth.js` `verify`, кладёт `request.account` |
| `src/auth/roles.decorator.ts` + `src/auth/roles.guard.ts` | `@Roles(...)` + проверка роли |
| `src/auth/auth.module.ts` | экспортирует guard'ы для DI |
| `src/health/health.controller.ts` | `GET /nest/health` (db-ping), `GET /nest/whoami` (защищён AuthGuard) |
| `test/nest/*.test.js` | e2e на `node --test` + supertest |

---

### Task 0: Спайк — Nest собирается и стартует пустым

**Files:**
- Modify: `package.json` (deps + scripts)
- Create: `nest-cli.json`
- Create: `tsconfig.nest.json`
- Create: `src/app.module.ts`
- Create: `src/main.ts`
- Create: `src/health/health.controller.ts`

- [ ] **Step 1: Проверить версию Node (Nest 11 требует ≥ 20)**

Run: `node -v`
Expected: `v20.x` или новее. Если ниже — остановиться, сообщить пользователю.

- [ ] **Step 2: Установить рантайм-зависимости Nest + Fastify**

```bash
npm install @nestjs/common@^11 @nestjs/core@^11 @nestjs/platform-fastify@^11 @nestjs/config@^11 reflect-metadata rxjs fastify @fastify/cookie @fastify/helmet @fastify/cors @fastify/rate-limit nestjs-pino pino-http pino-pretty
```

Expected: установка без ERESOLVE. Если конфликт peer-deps с `typescript@6` — зафиксировать вывод, остановиться (см. TS-риск выше).

- [ ] **Step 3: Установить dev-зависимости Nest**

```bash
npm install -D @nestjs/cli@^11 @nestjs/schematics@^11 @nestjs/testing@^11 supertest @types/supertest ts-node tsconfig-paths
```

Expected: установка успешна.

- [ ] **Step 4: Создать `nest-cli.json`**

```json
{
  "$schema": "https://json.schemastore.org/nest-cli",
  "collection": "@nestjs/schematics",
  "sourceRoot": "src",
  "compilerOptions": {
    "tsConfigPath": "tsconfig.nest.json",
    "deleteOutDir": true
  }
}
```

- [ ] **Step 5: Создать `tsconfig.nest.json`**

Отдельный tsconfig: бэкенд-Nest (decorators, commonjs), НЕ трогает `web/admin`.

```json
{
  "compilerOptions": {
    "module": "commonjs",
    "target": "es2022",
    "lib": ["es2022"],
    "moduleResolution": "node",
    "declaration": false,
    "removeComments": true,
    "emitDecoratorMetadata": true,
    "experimentalDecorators": true,
    "allowSyntheticDefaultImports": true,
    "esModuleInterop": true,
    "sourceMap": true,
    "outDir": "./dist",
    "baseUrl": "./",
    "incremental": true,
    "skipLibCheck": true,
    "strictNullChecks": true,
    "forceConsistentCasingInFileNames": true,
    "noImplicitAny": false,
    "strictBindCallApply": false,
    "noFallthroughCasesInSwitch": false,
    "resolveJsonModule": true,
    "allowJs": true
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist", "web", "public"]
}
```

> `allowJs: true` + `esModuleInterop` — чтобы `import` из существующих `.js`-сервисов работал. `noImplicitAny:false` — JS-сервисы не типизированы, не воюем с этим на Фазе 1.

- [ ] **Step 6: Создать минимальный `src/health/health.controller.ts` (пока без БД)**

```ts
import { Controller, Get } from '@nestjs/common';

@Controller('nest')
export class HealthController {
  @Get('health')
  health() {
    return { status: 'ok', app: 'nest' };
  }
}
```

- [ ] **Step 7: Создать `src/app.module.ts` (минимальный)**

```ts
import { Module } from '@nestjs/common';
import { HealthController } from './health/health.controller';

@Module({
  controllers: [HealthController],
})
export class AppModule {}
```

- [ ] **Step 8: Создать `src/main.ts` (минимальный bootstrap на Fastify)**

```ts
import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import {
  FastifyAdapter,
  NestFastifyApplication,
} from '@nestjs/platform-fastify';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create<NestFastifyApplication>(
    AppModule,
    new FastifyAdapter(),
  );
  const port = Number(process.env.NEST_PORT) || 3001;
  await app.listen(port, '0.0.0.0');
  // eslint-disable-next-line no-console
  console.log(`🐈 Nest (Fastify) на порту ${port}`);
}
bootstrap();
```

- [ ] **Step 9: Добавить scripts в `package.json`**

Вставить в `"scripts"` (рядом с существующими; `start`/`dev` Express не трогаем):

```json
    "nest:build": "nest build -p tsconfig.nest.json",
    "nest:start": "node dist/main.js",
    "nest:dev": "nest start --watch -p tsconfig.nest.json",
    "nest:test": "node --test test/nest/"
```

- [ ] **Step 10: Verification checkpoint — Nest собирается и отвечает**

```bash
npm run nest:build
```
Expected: сборка без ошибок, появляется `dist/main.js`. **Если падает на TS6 — стоп, показать вывод.**

Затем запустить и проверить health (PowerShell, в фоне):
```bash
npm run nest:start   # в отдельном терминале/фоне
curl -s http://localhost:3001/nest/health
```
Expected: `{"status":"ok","app":"nest"}`. Остановить процесс. **Показать вывод пользователю, дождаться ревью.**

---

### Task 1: ConfigModule + Zod-валидация ENV (fail-fast)

**Files:**
- Create: `src/config/env.validation.ts`
- Modify: `src/app.module.ts`
- Test: `test/nest/env.validation.test.js`

- [ ] **Step 1: Написать падающий тест**

`test/nest/env.validation.test.js`:
```js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { validateEnv } = require('../../dist/config/env.validation.js');

const GOOD_SECRET = 'a'.repeat(128);

test('validateEnv: пропускает корректный конфиг и применяет дефолты', () => {
  const out = validateEnv({
    ADMIN_COOKIE_SECRET: GOOD_SECRET,
    DATABASE_URL: 'postgresql://x',
  });
  assert.equal(out.NEST_PORT, 3001); // дефолт
  assert.equal(out.NODE_ENV, 'development');
});

test('validateEnv: падает на коротком секрете', () => {
  assert.throws(
    () => validateEnv({ ADMIN_COOKIE_SECRET: 'short', DATABASE_URL: 'x' }),
    /ADMIN_COOKIE_SECRET/,
  );
});

test('validateEnv: NEST_PORT коэрсится из строки', () => {
  const out = validateEnv({
    ADMIN_COOKIE_SECRET: GOOD_SECRET,
    DATABASE_URL: 'postgresql://x',
    NEST_PORT: '3005',
  });
  assert.equal(out.NEST_PORT, 3005);
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `npm run nest:build && node --test test/nest/env.validation.test.js`
Expected: FAIL — `Cannot find module '../../dist/config/env.validation.js'`.

- [ ] **Step 3: Реализовать `src/config/env.validation.ts`**

Переиспользуем существующую zod-`schema` из `services/env.js`, расширяя `NEST_PORT`. Не дублируем список ENV.

```ts
import { z } from 'zod';
// Существующая схема ENV проекта (services/env.js, zod v4). Переиспользуем,
// чтобы единственным источником истины по ENV оставался один файл.
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { schema: baseSchema } = require('../../services/env');

const nestSchema = (baseSchema as z.ZodObject<any>).extend({
  // Порт Nest-процесса. Default 3001, чтобы не конфликтовать с Express (PORT=3000).
  NEST_PORT: z.coerce.number().int().positive().default(3001),
});

export type NestEnv = z.infer<typeof nestSchema>;

/**
 * validate-функция для @nestjs/config. Бросает (а не process.exit) — Nest
 * сам валит bootstrap с понятным сообщением. Возвращает распарсенный конфиг
 * с применёнными дефолтами/коэрсингом.
 */
export function validateEnv(raw: Record<string, unknown>): NestEnv {
  const parsed = nestSchema.safeParse(raw);
  if (!parsed.success) {
    const lines = parsed.error.issues
      .map((i) => `  • ${i.path.join('.')}: ${i.message}`)
      .join('\n');
    throw new Error(`Некорректная конфигурация окружения (Nest):\n${lines}`);
  }
  return parsed.data;
}
```

- [ ] **Step 4: Подключить ConfigModule в `src/app.module.ts`**

```ts
import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { HealthController } from './health/health.controller';
import { validateEnv } from './config/env.validation';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      validate: (raw) => validateEnv(raw as Record<string, unknown>),
    }),
  ],
  controllers: [HealthController],
})
export class AppModule {}
```

- [ ] **Step 5: Запустить тест — убедиться, что проходит**

Run: `npm run nest:build && node --test test/nest/env.validation.test.js`
Expected: PASS (3 теста).

- [ ] **Step 6: Verification checkpoint — fail-fast на старте**

Запустить Nest с заведомо битым секретом:
```bash
# PowerShell
$env:ADMIN_COOKIE_SECRET='short'; npm run nest:start
```
Expected: процесс падает с сообщением, содержащим `ADMIN_COOKIE_SECRET`. Вернуть корректный `.env`. **Показать вывод, дождаться ревью.**

---

### Task 2: Структурное логирование (nestjs-pino)

**Files:**
- Modify: `src/app.module.ts`
- Modify: `src/main.ts`

- [ ] **Step 1: Подключить LoggerModule в `src/app.module.ts`**

Добавить в `imports` (после ConfigModule):
```ts
import { LoggerModule } from 'nestjs-pino';
```
```ts
    LoggerModule.forRoot({
      pinoHttp: {
        // В dev — человекочитаемо; в prod — JSON-строки (для journald/nginx).
        transport:
          process.env.NODE_ENV !== 'production'
            ? { target: 'pino-pretty', options: { singleLine: true } }
            : undefined,
        // Не логируем тело запросов (ПДн/пароли). Только метод/путь/статус.
        redact: ['req.headers.cookie', 'req.headers.authorization'],
        autoLogging: true,
      },
    }),
```

- [ ] **Step 2: Включить pino как логгер приложения в `src/main.ts`**

```ts
import { Logger } from 'nestjs-pino';
```
В `bootstrap()` заменить создание app на буферизованное и подключить логгер:
```ts
  const app = await NestFactory.create<NestFastifyApplication>(
    AppModule,
    new FastifyAdapter(),
    { bufferLogs: true },
  );
  app.useLogger(app.get(Logger));
```
Убрать `console.log` про порт — заменить на:
```ts
  app.get(Logger).log(`🐈 Nest (Fastify) на порту ${port}`);
```

- [ ] **Step 3: Verification checkpoint — структурные логи**

```bash
npm run nest:build && npm run nest:start
curl -s http://localhost:3001/nest/health > $null
```
Expected: в логах появляется строка запроса с `req.method`, `res.statusCode`, `responseTime`; cookie/authorization-заголовки **не** видны в логе (redact). **Показать вывод, дождаться ревью.**

---

### Task 3: Security-плагины Fastify (helmet / cors / rate-limit / cookie)

**Files:**
- Create: `src/config/security.ts`
- Modify: `src/main.ts`
- Test: `test/nest/security.test.js`

- [ ] **Step 1: Написать падающий тест на построение опций**

`test/nest/security.test.js`:
```js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { corsOptions } = require('../../dist/config/security.js');

test('corsOptions: разрешённый origin принимается', (t, done) => {
  const opts = corsOptions('https://kotokod.ru,https://app.kotokod.ru', 'production');
  opts.origin('https://kotokod.ru', (err, allow) => {
    assert.equal(err, null);
    assert.equal(allow, true);
    done();
  });
});

test('corsOptions: чужой origin отклоняется (allow=false, без throw)', (t, done) => {
  const opts = corsOptions('https://kotokod.ru', 'production');
  opts.origin('https://evil.example', (err, allow) => {
    assert.equal(err, null);
    assert.equal(allow, false);
    done();
  });
});

test('corsOptions: same-origin/curl (no origin) разрешён', (t, done) => {
  const opts = corsOptions('', 'production');
  opts.origin(undefined, (err, allow) => {
    assert.equal(err, null);
    assert.equal(allow, true);
    done();
  });
});

test('corsOptions: dev пропускает localhost:5173', (t, done) => {
  const opts = corsOptions('', 'development');
  opts.origin('http://localhost:5173', (err, allow) => {
    assert.equal(allow, true);
    done();
  });
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `npm run nest:build && node --test test/nest/security.test.js`
Expected: FAIL — `Cannot find module '../../dist/config/security.js'`.

- [ ] **Step 3: Реализовать `src/config/security.ts`**

Зеркалит CORS-политику Express (`server.js`): whitelist из ENV, same-origin/no-origin разрешён, dev пропускает Vite. Без throw — просто `allow=false`.

```ts
import type { FastifyCorsOptions } from '@fastify/cors';

/** Построить CORS-опции из строки CORS_ORIGINS (через запятую) и NODE_ENV. */
export function corsOptions(
  corsOriginsRaw: string,
  nodeEnv: string,
): FastifyCorsOptions {
  const allowed = (corsOriginsRaw || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);

  return {
    credentials: true,
    origin(origin, cb) {
      if (!origin) return cb(null, true); // same-origin, curl, server-to-server
      if (allowed.includes(origin)) return cb(null, true);
      if (
        nodeEnv !== 'production' &&
        /^http:\/\/localhost:(5173|3000|3001)$/.test(origin)
      ) {
        return cb(null, true);
      }
      return cb(null, false); // запрещённый origin: без CORS-заголовков, без 500
    },
  };
}

/** Опции глобального rate-limit (зеркалит общий лимитер Express: 300/мин). */
export function rateLimitOptions() {
  return {
    max: 300,
    timeWindow: '1 minute',
  };
}
```

- [ ] **Step 4: Зарегистрировать плагины в `src/main.ts`**

В `bootstrap()`, ПОСЛЕ создания `app` и ДО `app.listen`. Порядок: cookie → helmet → cors → rate-limit.

```ts
import fastifyCookie from '@fastify/cookie';
import fastifyHelmet from '@fastify/helmet';
import fastifyCors from '@fastify/cors';
import fastifyRateLimit from '@fastify/rate-limit';
import { corsOptions, rateLimitOptions } from './config/security';
```
```ts
  await app.register(fastifyCookie as any);
  // CSP отключён (как в Express): дефолтная политика ломает inline-скрипты SPA.
  await app.register(fastifyHelmet as any, { contentSecurityPolicy: false });
  await app.register(
    fastifyCors as any,
    corsOptions(process.env.CORS_ORIGINS ?? '', process.env.NODE_ENV ?? 'development'),
  );
  await app.register(fastifyRateLimit as any, rateLimitOptions());
```

- [ ] **Step 5: Запустить тест — убедиться, что проходит**

Run: `npm run nest:build && node --test test/nest/security.test.js`
Expected: PASS (4 теста).

- [ ] **Step 6: Verification checkpoint — заголовки и origin вживую**

```bash
npm run nest:build && npm run nest:start
curl -sI http://localhost:3001/nest/health
```
Expected: присутствуют helmet-заголовки (`x-frame-options`, `x-content-type-options: nosniff`, и т.п.). **Показать вывод, дождаться ревью.**

---

### Task 4: DbModule — общий пул + health с db-ping

**Files:**
- Create: `src/db/db.service.ts`
- Create: `src/db/db.module.ts`
- Modify: `src/health/health.controller.ts`
- Modify: `src/app.module.ts`
- Test: `test/nest/health.test.js`

- [ ] **Step 1: Написать падающий e2e-тест health с БД**

`test/nest/health.test.js` (поднимает Nest через @nestjs/testing, бьёт supertest'ом):
```js
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const request = require('supertest');
const { Test } = require('@nestjs/testing');
const {
  FastifyAdapter,
} = require('@nestjs/platform-fastify');
const { AppModule } = require('../../dist/app.module.js');

let app;

before(async () => {
  const moduleRef = await Test.createTestingModule({
    imports: [AppModule],
  }).compile();
  app = moduleRef.createNestApplication(new FastifyAdapter());
  await app.init();
  await app.getHttpAdapter().getInstance().ready();
});

after(async () => {
  if (app) await app.close();
});

test('GET /nest/health → 200 и db:ok', async () => {
  const res = await request(app.getHttpServer()).get('/nest/health');
  assert.equal(res.status, 200);
  assert.equal(res.body.status, 'ok');
  assert.equal(res.body.db, 'ok');
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `npm run nest:build && node --test test/nest/health.test.js`
Expected: FAIL — `res.body.db` undefined (health пока без БД).

- [ ] **Step 3: Реализовать `src/db/db.service.ts`**

Оборачивает СУЩЕСТВУЮЩИЙ пул из `services/db.js` (один пул на процесс, type-parser 1082 уже применён там).

```ts
import { Injectable } from '@nestjs/common';
// Существующая инфраструктура пула (services/db.js): pool, tx, shutdown.
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { pool, tx } = require('../../services/db');

@Injectable()
export class DbService {
  /** Параметризованный запрос через общий пул. */
  query(text: string, params?: unknown[]) {
    return pool.query(text, params);
  }

  /** Транзакция (переиспользует services/db.js tx). */
  tx<T>(fn: (client: unknown) => Promise<T>): Promise<T> {
    return tx(fn);
  }

  /** Лёгкий ping для health-чека. true, если БД отвечает. */
  async ping(): Promise<boolean> {
    try {
      await pool.query('SELECT 1');
      return true;
    } catch {
      return false;
    }
  }
}
```

- [ ] **Step 4: Реализовать `src/db/db.module.ts` (Global — пул нужен всем)**

```ts
import { Global, Module } from '@nestjs/common';
import { DbService } from './db.service';

@Global()
@Module({
  providers: [DbService],
  exports: [DbService],
})
export class DbModule {}
```

- [ ] **Step 5: Обновить `src/health/health.controller.ts` — db-ping**

```ts
import { Controller, Get } from '@nestjs/common';
import { DbService } from '../db/db.service';

@Controller('nest')
export class HealthController {
  constructor(private readonly db: DbService) {}

  @Get('health')
  async health() {
    const dbOk = await this.db.ping();
    return { status: 'ok', app: 'nest', db: dbOk ? 'ok' : 'down' };
  }
}
```

- [ ] **Step 6: Импортировать DbModule в `src/app.module.ts`**

Добавить `DbModule` в `imports`:
```ts
import { DbModule } from './db/db.module';
```
```ts
    DbModule,
```

- [ ] **Step 7: Запустить — убедиться, что проходит**

Run: `npm run nest:build && node --test test/nest/health.test.js`
Expected: PASS (требуется доступная PG из `.env`).

- [ ] **Step 8: Verification checkpoint — health видит ту же БД, что Express**

```bash
npm run nest:build && npm run nest:start
curl -s http://localhost:3001/nest/health
```
Expected: `{"status":"ok","app":"nest","db":"ok"}`. **Показать вывод, дождаться ревью.**

---

### Task 5: AuthGuard + RolesGuard — общая HMAC-session (keystone strangler-fig)

**Files:**
- Create: `src/auth/auth.guard.ts`
- Create: `src/auth/roles.decorator.ts`
- Create: `src/auth/roles.guard.ts`
- Create: `src/auth/auth.module.ts`
- Modify: `src/health/health.controller.ts` (добавить `/nest/whoami`)
- Modify: `src/app.module.ts`
- Test: `test/nest/whoami.test.js`

- [ ] **Step 1: Написать падающий e2e-тест на общую cookie**

Тест минтит валидную session-cookie тем же `sign()`, что использует Express → доказывает, что Nest принимает «чужую» (Express-выписанную) сессию. `test/nest/whoami.test.js`:
```js
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const request = require('supertest');
const { Test } = require('@nestjs/testing');
const { FastifyAdapter } = require('@nestjs/platform-fastify');
const { AppModule } = require('../../dist/app.module.js');
const { sign, COOKIE_NAME } = require('../../services/auth');

const SECRET = process.env.ADMIN_COOKIE_SECRET;
let app;

function cookieFor(role) {
  const payload = {
    account_id: 42,
    role,
    iat: Date.now(),
    exp: Date.now() + 60_000,
  };
  return `${COOKIE_NAME}=${sign(payload, SECRET)}`;
}

before(async () => {
  const moduleRef = await Test.createTestingModule({ imports: [AppModule] }).compile();
  app = moduleRef.createNestApplication(new FastifyAdapter());
  await app.init();
  await app.getHttpAdapter().getInstance().ready();
});
after(async () => { if (app) await app.close(); });

test('GET /nest/whoami без cookie → 401', async () => {
  const res = await request(app.getHttpServer()).get('/nest/whoami');
  assert.equal(res.status, 401);
});

test('GET /nest/whoami с валидной admin-cookie → 200 + role', async () => {
  const res = await request(app.getHttpServer())
    .get('/nest/whoami')
    .set('Cookie', cookieFor('admin'));
  assert.equal(res.status, 200);
  assert.equal(res.body.role, 'admin');
  assert.equal(res.body.account_id, 42);
});

test('GET /nest/whoami с teacher-cookie → 403 (нужен admin/manager)', async () => {
  const res = await request(app.getHttpServer())
    .get('/nest/whoami')
    .set('Cookie', cookieFor('teacher'));
  assert.equal(res.status, 403);
});

test('GET /nest/whoami с подделанной подписью → 401', async () => {
  const res = await request(app.getHttpServer())
    .get('/nest/whoami')
    .set('Cookie', `${COOKIE_NAME}=garbage.deadbeef`);
  assert.equal(res.status, 401);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `npm run nest:build && node --test test/nest/whoami.test.js`
Expected: FAIL — маршрут `/nest/whoami` ещё не существует (404, не 401/200).

- [ ] **Step 3: Реализовать `src/auth/auth.guard.ts`**

Переиспользует `verify` из `services/auth.js` — НЕ дублирует HMAC.

```ts
import {
  CanActivate,
  ExecutionContext,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import type { FastifyRequest } from 'fastify';
// Существующее auth-ядро (services/auth.js): verify(token, secret), COOKIE_NAME.
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { verify, COOKIE_NAME } = require('../../services/auth');

export interface SessionAccount {
  account_id: number;
  role: string;
}

@Injectable()
export class AuthGuard implements CanActivate {
  canActivate(context: ExecutionContext): boolean {
    const req = context
      .switchToHttp()
      .getRequest<FastifyRequest & { cookies?: Record<string, string>; account?: SessionAccount }>();
    const token = req.cookies?.[COOKIE_NAME];
    const payload = verify(token, process.env.ADMIN_COOKIE_SECRET);
    if (!payload) {
      throw new UnauthorizedException('Unauthorized');
    }
    req.account = { account_id: payload.account_id, role: payload.role };
    return true;
  }
}
```

- [ ] **Step 4: Реализовать `src/auth/roles.decorator.ts`**

```ts
import { SetMetadata } from '@nestjs/common';

export const ROLES_KEY = 'roles';
/** Ограничить маршрут перечисленными ролями. Пусто → любая аутентифицированная. */
export const Roles = (...roles: string[]) => SetMetadata(ROLES_KEY, roles);
```

- [ ] **Step 5: Реализовать `src/auth/roles.guard.ts`**

```ts
import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
} from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { ROLES_KEY } from './roles.decorator';
import type { SessionAccount } from './auth.guard';

@Injectable()
export class RolesGuard implements CanActivate {
  constructor(private readonly reflector: Reflector) {}

  canActivate(context: ExecutionContext): boolean {
    const roles = this.reflector.getAllAndOverride<string[]>(ROLES_KEY, [
      context.getHandler(),
      context.getClass(),
    ]);
    if (!roles || roles.length === 0) return true; // нет @Roles → достаточно AuthGuard
    const req = context
      .switchToHttp()
      .getRequest<{ account?: SessionAccount }>();
    if (!req.account || !roles.includes(req.account.role)) {
      throw new ForbiddenException('Forbidden');
    }
    return true;
  }
}
```

- [ ] **Step 6: Реализовать `src/auth/auth.module.ts`**

```ts
import { Module } from '@nestjs/common';
import { AuthGuard } from './auth.guard';
import { RolesGuard } from './roles.guard';

@Module({
  providers: [AuthGuard, RolesGuard],
  exports: [AuthGuard, RolesGuard],
})
export class AuthModule {}
```

- [ ] **Step 7: Добавить `/nest/whoami` в `src/health/health.controller.ts`**

```ts
import { Controller, Get, Req, UseGuards } from '@nestjs/common';
import { DbService } from '../db/db.service';
import { AuthGuard } from '../auth/auth.guard';
import { RolesGuard } from '../auth/roles.guard';
import { Roles } from '../auth/roles.decorator';

@Controller('nest')
export class HealthController {
  constructor(private readonly db: DbService) {}

  @Get('health')
  async health() {
    const dbOk = await this.db.ping();
    return { status: 'ok', app: 'nest', db: dbOk ? 'ok' : 'down' };
  }

  // Диагностика общей сессии: доказывает, что Nest валидирует ту же
  // HMAC-cookie, что выписывает Express. Защищён ролями admin/manager.
  @Get('whoami')
  @UseGuards(AuthGuard, RolesGuard)
  @Roles('admin', 'manager')
  whoami(@Req() req: { account?: { account_id: number; role: string } }) {
    return { account_id: req.account?.account_id, role: req.account?.role };
  }
}
```

> Порядок в `@UseGuards(AuthGuard, RolesGuard)` важен: AuthGuard кладёт `req.account` ДО того, как RolesGuard его прочитает.

- [ ] **Step 8: Импортировать AuthModule в `src/app.module.ts`**

```ts
import { AuthModule } from './auth/auth.module';
```
Добавить `AuthModule` в `imports`.

- [ ] **Step 9: Запустить — убедиться, что проходит**

Run: `npm run nest:build && node --test test/nest/whoami.test.js`
Expected: PASS (4 теста).

- [ ] **Step 10: Verification checkpoint — реальная Express-cookie работает в Nest**

Доказательство keystone живьём (оба процесса подняты):
```bash
# 1. Залогиниться в Express и сохранить cookie (подставить реальные креды admin@kotokod.ru + 2FA;
#    либо использовать существующий smoke-скрипт логина).
#    Сохранить значение cookie `session` из ответа Express в переменную $C.
# 2. Дёрнуть Nest той же cookie:
curl -s http://localhost:3001/nest/whoami -H "Cookie: session=$C"
```
Expected: `{"account_id":<id>,"role":"admin"}` — Nest принял Express-сессию **без перелогина**. **Показать вывод, дождаться ревью.**

---

### Task 6: Финальная регрессия + краткая документация

**Files:**
- Modify: `package.json` (`nest:test` уже добавлен в Task 0; здесь проверяем агрегат)
- Modify: `CLAUDE.md` (короткий раздел про Nest-каркас)
- Modify: `docs/ROADMAP.md` (отметить Фазу 1 как ⏳/✅)

- [ ] **Step 1: Полный прогон Nest-тестов**

Run: `npm run nest:build && npm run nest:test`
Expected: все тесты `test/nest/` зелёные (env.validation, security, health, whoami).

- [ ] **Step 2: Регрессия — старый набор не сломан**

Run: `npm test`
Expected: существующие 97+ тестов зелёные (Nest-файлы лежат в `test/nest/`, старый `npm test` их не подхватывает, если таргетит иные пути; если `node --test` берёт всё — убедиться, что Nest-тесты тоже зелёные и не конфликтуют по порту/пулу).

> Если `npm test` (`node --test`) начнёт подхватывать `test/nest/*` и потребуется собранный `dist/` — задокументировать в CLAUDE.md, что перед `npm test` нужен `npm run nest:build`, ИЛИ сузить glob `test` до старого каталога. Решение по globs — на ревью.

- [ ] **Step 3: Дописать раздел в `CLAUDE.md`**

Добавить после таблицы фаз короткий блок:
```markdown
## NestJS (strangler-fig, Фаза 1 — каркас)

Параллельно Express поднят пустой Nest (Fastify) на `NEST_PORT` (default 3001), `src/` → `dist/`.
Делит с Express один PG-пул (`services/db.js`) и один формат session-cookie (`services/auth.js`).
Диагностика: `GET /nest/health` (db-ping), `GET /nest/whoami` (защищён, проверяет общую сессию).
Сборка/запуск: `npm run nest:build` / `npm run nest:start` / `npm run nest:dev`. Тесты: `npm run nest:test`.
Перенос модулей — по одному (Фаза 2), nginx маршрутизирует по путям. План: docs/superpowers/plans/2026-06-08-phase1-nest-scaffold.md.
```

- [ ] **Step 4: Отметить статус в `docs/ROADMAP.md`**

Добавить в раздел «🟢 Фазы миграции» (или новый «Платформа») строку:
```markdown
- ⏳ **Платформа Фаза 1 — каркас NestJS** (Fastify, ConfigModule+Zod-env, pino, helmet/cors/rate-limit, DbModule, AuthGuard на общей HMAC-cookie). Nest поднят пустым рядом с Express. *План: docs/superpowers/plans/2026-06-08-phase1-nest-scaffold.md.*
```

- [ ] **Step 5: Verification checkpoint — финал Фазы 1**

Подтвердить: `npm run nest:build` чисто, `npm run nest:test` зелено, `npm test` зелено, оба процесса (Express :3000, Nest :3001) поднимаются. **Показать сводку пользователю.**

---

## Self-Review (проверено против роадмапа `golden-dancing-mango.md`, раздел «Фаза 1»)

Требования Фазы 1 из роадмапа → задачи плана:

| Требование роадмапа | Где реализовано |
|---|---|
| инициализировать NestJS (Fastify-адаптер) | Task 0 |
| ConfigModule + Zod-env | Task 1 |
| nestjs-pino | Task 2 |
| helmet / cors / rate-limit | Task 3 |
| общий DbModule (обёртка пула) | Task 4 |
| AuthGuard читающий существующую HMAC-cookie | Task 5 |
| Nest поднят пустым, Express обслуживает трафик | вся структура: Nest на отдельном порту, только `/nest/*` диагностика |

**Placeholder-скан:** код приведён полностью в каждом шаге; «add error handling»/«TBD» отсутствуют.

**Type-consistency:** `SessionAccount` определён в `auth.guard.ts`, импортируется в `roles.guard.ts`; `validateEnv`/`NestEnv` из `env.validation.ts`; `corsOptions`/`rateLimitOptions` из `security.ts`; `DbService.ping/query/tx` используются единообразно. `COOKIE_NAME`/`sign`/`verify` берутся из существующего `services/auth.js` (имена сверены с прочитанным файлом).

**Сознательно вне Фазы 1 (по роадмапу — позже):** nginx-маршрутизация на Nest и перенос реальных модулей — Фаза 2; Redis/WS/BBB/BullMQ — Фаза 3; `git init`, Biome, lefthook — Фаза 0 (git отложен пользователем; Biome/lefthook опциональны и git-зависимы). Эти пункты намеренно НЕ включены.
