# Платформа Фаза 2 — kickoff-бриф (перенос ядра Express → NestJS)

> **Назначение:** точка входа для НОВОЙ сессии, чтобы начать Фазу 2 без перечитывания всего контекста.
> Это бриф, а не task-by-task план — детальный план первого модуля пишется через `superpowers:writing-plans`
> ПОСЛЕ выбора модуля и короткого `brainstorming` (см. «Открытые решения» ниже).

## Где мы (контекст за 30 секунд)

- Проект — `journal-backend` (Express + PostgreSQL, admin SPA React 19). См. `CLAUDE.md`.
- **Фаза 0** (хардненинг прода) — фактически сделана раньше (helmet/CORS-whitelist/rate-limit/fail-fast env уже в `server.js`/`services/env.js`). git — **отложен пользователем** (проект НЕ под version control → верификация+ревью после каждого шага вместо коммитов).
- **Фаза 1 — каркас Nest ✅ ЗАВЕРШЕНА** (`docs/superpowers/plans/2026-06-08-phase1-nest-scaffold.md`). Пустой Nest (Fastify) на `:3001` рядом с Express (`:3000`), делят PG-пул и HMAC-session-cookie. 12 Nest e2e зелёные, регресс `npm test` 122/122.
- **Стек-решение** (одобрено 2026-06-08): остаёмся на TS, Express → NestJS (модульный монолит, Fastify), strangler-fig, без Docker, raw-SQL (без ORM). Полный роадмап: `C:\Users\ilyap\.claude\plans\golden-dancing-mango.md`. Память: `project_platform_roadmap`.

## Что уже есть в каркасе (переиспользовать, не дублировать)

```
src/
  main.ts                  # bootstrap: dotenv/config ПЕРВЫМ → Fastify → registerPlugins → listen NEST_PORT
  bootstrap.ts             # registerPlugins(app): cookie→helmet→cors→rate-limit (общий для прода и тестов)
  app.module.ts            # ConfigModule(Zod-env) + LoggerModule(pino) + DbModule + AuthModule
  config/env.validation.ts # validateEnv: переиспользует services/env.js schema + NEST_PORT
  config/security.ts       # corsOptions / rateLimitOptions (зеркало server.js)
  db/db.service.ts         # DbService.query/tx/ping поверх services/db.js pool (Global DbModule)
  auth/auth.guard.ts       # AuthGuard: verify(cookie, ADMIN_COOKIE_SECRET) из services/auth.js → req.account
  auth/roles.guard.ts      # RolesGuard: @Roles(...) через Reflector
  auth/roles.decorator.ts  # @Roles, ROLES_KEY
  health/health.controller.ts # GET /nest/health (db-ping), GET /nest/whoami (@Roles admin,manager)
test/nest/*.test.js        # node --test + supertest (НЕ Jest)
```

**Доступные DI-строительные блоки для Фазы 2:** `DbService` (инъектируется куда угодно, Global), `AuthGuard`, `RolesGuard`, `@Roles`. Доменная логика уже написана в `services/repo/*` и `services/{fifo,calculator,teacher-repo}.js` — Nest-провайдеры оборачивают их как `DbService` оборачивает `db.js`.

## Цель Фазы 2

Перенести **ядро** из Express-роутов в Nest-модули по одному, с e2e-паритетом. Порядок из роадмапа:
**Auth/Rbac/Audit → Attendance → Finance → Students/Groups/Teachers.** Каждый перенесённый путь в проде nginx перекидывает на Nest; старый Express-роут удаляется только когда Nest-аналог покрыт e2e и сверен со старым поведением.

## Рецепт переноса одного модуля (повторяемый)

1. **Брифинг модуля:** перечитать соответствующий Express-роут (`routes/admin/<entity>.js` или `routes/auth.js`/`routes/teacher.js`) и его репозиторий (`services/repo/<entity>.js`). Зафиксировать контракт (пути, методы, Zod-схема из `shared/schemas.js`, гейтинг ролей, формат ответа).
2. **Провайдер:** `src/<module>/<entity>.service.ts` — тонкая обёртка над существующим `services/repo/<entity>.js` (как `DbService`). НЕ переписывать SQL/FIFO/расчёты.
3. **Валидация:** DTO через Zod — переиспользовать `shared/schemas.js` (рассмотреть `nestjs-zod` ZodValidationPipe, чтобы `z.infer` = тип + рантайм одним источником). На каркасе `nestjs-zod` ещё НЕ установлен — поставить на первом модуле с DTO.
4. **Контроллер:** `src/<module>/<entity>.controller.ts` — те же пути/методы/коды, `@UseGuards(AuthGuard, RolesGuard)` + `@Roles(...)` зеркалят Express-гейтинг.
5. **Маппинг ошибок:** PG-коды → 4xx как в централизованном хендлере `server.js` (`PG_ERRORS`: 23505→409, 23503→409, 23502→400, 23514→400, 22P02→400, 22001→400, любая 5xx → generic). Сделать Nest `ExceptionFilter`, чтобы детали схемы не утекали.
6. **e2e-паритет:** `test/nest/<entity>.test.js` (supertest) — те же кейсы, что у Express; где есть старый тест — сверить ответ один-в-один. Минтить cookie через `sign()` из `services/auth.js` (рецепт в `test/nest/whoami.test.js`).
7. **Верификация:** `npm run nest:test` зелено + `npm test` 122+ зелено. Показать пользователю, ревью (git нет).
8. **Cutover:** в прод-nginx добавить `location`-правило на путь → Nest. Локально (без nginx) — оба процесса + тесты бьют Nest напрямую. Express-роут НЕ удалять до подтверждённого паритета.

## Грабли каркаса (НЕ переоткрывать — уже решены в Фазе 1)

- Версии: `@nestjs/config`=**v4**, `nestjs-pino`=**v4** (НЕ v11); core/platform/cli=11, fastify=5. Node 24, TS 6 — собирается.
- `tsconfig.nest.json`: TS6 требует `ignoreDeprecations:"6.0"` + явный `rootDir`; **`incremental` отключён** (конфликт с `deleteOutDir` — иначе пропадают «неизменённые» файлы из dist).
- `.env` грузить ПЕРВЫМ (`import 'dotenv/config'` в main.ts; `require('dotenv').config()` до `require dist` в тестах) — пул `services/db.js` создаётся на require.
- Fastify-плагины — только через общий `registerPlugins()` (иначе guard на `@fastify/cookie` ломается в тестах).
- `node --test` хочет glob `"test/nest/**/*.test.js"`, не каталог. `npm test` собирает Nest перед прогоном.
- **mount-order инвариант (из RBAC):** при переносе следить, чтобы teacher-гейтинг не перехватывал admin-пути (в Express баг был: `/api` с requireRole('teacher') выше `/api/admin`). В Nest это решается явными `@Roles` на контроллерах.

## Открытые решения (развязать в начале сессии Фазы 2 через brainstorming)

1. **Какой модуль первым?** Роадмап говорит Auth. НО Auth — security-critical и stateful (2FA, challenge-токены, recovery, email-OTP) → рискованный первый шаг. **Рекомендация:** начать с **read-only справочника** (Teachers ИЛИ Groups list/get) — докажет рецепт переноса end-to-end на низком риске, затем браться за Auth/Finance. Решение за пользователем.
2. **`nestjs-zod` vs ручной ZodValidationPipe** — ставить ли пакет или обойтись тонким pipe поверх существующих `shared/schemas.js`.
3. **Локальная маршрутизация без nginx** — как переключать трафик на Nest в dev (вариант: dev-прокси в Express на `/nest-migrated/*`, или просто гонять e2e против Nest и держать cutover чисто прод-nginx-конфигом). 
4. **ExceptionFilter** — общий маппинг PG-ошибок: вынести `PG_ERRORS` из `server.js` в shared-модуль, переиспользовать в Nest-фильтре (DRY).

## Первые конкретные шаги новой сессии

1. Прочитать этот бриф + `CLAUDE.md` раздел «NestJS» + память `project_platform_roadmap`.
2. `npm test` — убедиться, что база зелёная (122/122), каркас не сгнил.
3. Короткий `brainstorming` по «Открытым решениям» п.1–4 (особенно: первый модуль).
4. `writing-plans` → детальный task-by-task план первого модуля по «Рецепту переноса» выше.
5. Исполнять inline (executing-plans) с verification-чекпойнтами (git нет).
