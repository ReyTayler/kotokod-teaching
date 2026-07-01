# Этап 10 — перенос фронтенда внутрь journal_django + раздача через Django

> **Назначение документа.** Инструкция для исполняющего агента (отдельная сессия).
> Описывает перенос всего фронтенда внутрь `journal_django/`, развязку внешних
> зависимостей и dev-раздачу статики самим Django, чтобы платформа запускалась одной
> командой `manage.py runserver` **без Node**. Документ самодостаточен — читать целиком
> до начала работы.

## Контекст и цель

Бэкенд уже полностью на Python (Django+DRF, `journal_django/`), все эндпоинты
портированы, ~615 тестов. Сейчас фронтенд лежит **вне** Django-проекта:
- статика — `public/{login,teacher,admin-dist,fonts}`;
- исходники admin SPA (React 19 + TanStack Query v5 + React Router v7 + Vite) — `web/admin/`;
- общие TS-типы — `shared/types.ts`.

Прод-раздача фронта настроена в `deploy/nginx/journal-kotokod.conf` (nginx отдаёт
статику + проксирует `/api/*` на gunicorn). Локально на Windows фронт открыть нечем —
Django ничего, кроме JSON, не отдаёт, а Vite dev-proxy смотрит на мёртвый Express `:3000`.

**Цель:** сделать `journal_django/` самодостаточным — весь фронтенд внутри, запуск
платформы = `manage.py runserver` (единый origin `http://localhost:8000`).

### Ключевой факт про Node (не путать runtime и build-time)
- Node как **сервер** не нужен — бэк на Python.
- `login/` и `teacher/` — чистый vanilla HTML/CSS/JS, сборки нет.
- `admin-dist/` — **уже скомпилированный** бандл, Django отдаёт как есть.
- Node (Vite) нужен **только** как разовый компилятор, когда правят React-исходники
  admin (`admin-src/`). Питон не компилирует React/TSX — это свойство стека, а не
  привязка бэка к Node. В запуске платформы Node не участвует.

### Почему «просто отдать папку» недостаточно
SPA ссылаются на активы по **абсолютным корневым** путям: `/login/...`,
`/admin/assets/...`, `/teacher/...`, `/fonts/...` — не по Django-шному `/static/...`.
Поэтому нужен маппинг URL-префиксов на папки (в проде это `alias` в nginx; в dev —
небольшой `urls_dev.py`). Единый origin `localhost:8000` также обязателен, иначе cookie
`session` с `SameSite=Strict` не будет ходить между страницами.

## Решения (зафиксированы с владельцем — не пересматривать без согласования)
- Переносим **и статику, и исходники admin** внутрь проекта.
- Раздаваемая статика → `journal_django/frontend/`.
- Исходники admin → `journal_django/frontend/admin-src/`.
- Admin **остаётся на React** — Django отдаёт собранный `admin-dist/`.
- Раздача статики в Django — **dev-only** (`if settings.DEBUG`); в проде её отдаёт nginx.
- API-пути и логику фронтенда **не трогаем** — фронт origin-agnostic
  (относительные `/api/...`, `credentials:'include'`).

### Внешние связи, которые надо развязать
- `web/admin/src/lib/types.ts:1` → `export * from '../../../../shared/types'`. После
  удаления Express/Nest каталог `shared/` содержит только `types.ts` (+`tsconfig.json`) и
  нужен лишь admin → **внести типы внутрь admin-исходников**, `shared/` удалить.
- Шрифты: admin грузит `/admin/fonts/...` (внутри `admin-dist/fonts`, см.
  `web/admin/src/styles/tokens.css`); teacher/login — `/fonts/...` из корня
  (`public/teacher/styles.css`). Корневые `/fonts/` нужно отдавать и в dev, и в проде.

## Итоговая структура

```
journal_django/
  apps/  config/  manage.py  ...
  frontend/
    login/         # ← public/login        (vanilla, активы /login/*)
    teacher/       # ← public/teacher       (vanilla SPA, активы /teacher/* + /fonts/*)
    admin-dist/    # ← public/admin-dist    (собранный бандл, активы /admin/*)
    fonts/         # ← public/fonts         (корневые шрифты teacher/login: /fonts/*)
    admin-src/     # ← web/admin            (React-исходники: src/, vite.config.ts,
                   #                          tsconfig.json, index.html, package.json)
```

## Шаги исполнения

> Делать **инкрементально, с проверкой после каждого шага** — git в репозитории нет,
> откатывать нечем, поэтому проверяем по ходу.

### Шаг 1. Перенос файлов
1. Переместить `public/login`, `public/teacher`, `public/admin-dist`, `public/fonts`
   → `journal_django/frontend/` (сохранив имена папок).
2. Переместить `web/admin/` → `journal_django/frontend/admin-src/` (вместе с `src/`,
   `vite.config.ts`, `tsconfig.json`, `index.html`).
3. Перенести `shared/types.ts` → `journal_django/frontend/admin-src/src/lib/shared-types.ts`.
   В `admin-src/src/lib/types.ts` заменить
   `export * from '../../../../shared/types'` → `export * from './shared-types'`.
   Удалить каталог `shared/` (после переноса в нём остаётся только `tsconfig.json`).
4. Проверить, что в `admin-src/src/**` не осталось импортов, выходящих за пределы
   `admin-src/` (поиск `../../../`, `shared/`). Ожидаемо — только что развязанный был
   единственным.

### Шаг 2. Конфиг admin под новое расположение
1. `frontend/admin-src/vite.config.ts`:
   - `build.outDir` → `path.resolve(__dirname, '../admin-dist')` (теперь соседняя папка
     в `frontend/`; было `../../public/admin-dist`).
   - `server.proxy['/api'].target` → `'http://localhost:8000'` (было `:3000`, мёртвый Express).
   - `base: '/admin/'`, `root: __dirname`, `resolve.alias['@']` → `src` — без изменений.
2. Создать **самодостаточный** `frontend/admin-src/package.json` (только admin-зависимости,
   взять версии из текущего корневого `package.json`):
   - **dependencies:** `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities`,
     `@radix-ui/react-dialog`, `@radix-ui/react-dropdown-menu`, `@radix-ui/react-select`,
     `@radix-ui/react-tabs`, `@radix-ui/react-toast`, `@radix-ui/react-tooltip`,
     `@tanstack/react-query`, `@tanstack/react-query-devtools`, `lucide-react`, `react`,
     `react-dom`, `react-router-dom`, `recharts`.
   - **devDependencies:** `@types/node`, `@types/react`, `@types/react-dom`,
     `@vitejs/plugin-react`, `typescript`, `vite`.
   - **scripts:** `"dev": "vite"`, `"build": "vite build"`, `"typecheck": "tsc --noEmit"`.
   - НЕ переносить `bcryptjs/googleapis/pg/dotenv` — это legacy backfill-тулинг, остаётся в корне.
3. `frontend/admin-src/tsconfig.json` переезжает как есть.

### Шаг 3. Корневой package.json (репозиторий)
- Удалить скрипты `admin:dev`, `admin:build`, `admin:typecheck`.
- Удалить admin-only зависимости (переехали в `admin-src/package.json`): все `@dnd-kit/*`,
  `@radix-ui/*`, `@tanstack/*`, `lucide-react`, `react`, `react-dom`, `react-router-dom`,
  `recharts`, `@types/react`, `@types/react-dom`, `@vitejs/plugin-react`, `vite`
  (а также `typescript`, `@types/node`, если они больше нигде в корне не нужны).
- Оставить backfill/db-тулинг (`backfill:*`, `db:*`, `account:create`, `payroll:rebuild`,
  `counters:rebuild`) и их зависимости (`pg`, `googleapis`, `bcryptjs`, `dotenv`).

### Шаг 4. Dev-раздача статики в Django (единственный новый Python-код)
1. Создать `journal_django/config/urls_dev.py`. Использовать штатный
   `django.views.static.serve`. База: `FRONTEND = BASE_DIR / 'frontend'`
   (`BASE_DIR` = каталог `journal_django/`, см. `config/settings/base.py:15`).
   Маршруты (зеркалят nginx; учесть `APPEND_SLASH=False` — пути без слеша задавать явно):
   - `^$` и `^login$` → отдать `frontend/login/index.html`
   - `^login/(?P<path>.*)$` → `serve(document_root=frontend/login)`
   - `^teacher$` → `frontend/teacher/index.html`
   - `^teacher/(?P<path>.*)$` → `serve` из `frontend/teacher`; на `Http404` → отдать
     `teacher/index.html` (SPA history-fallback)
   - `^admin$` → `frontend/admin-dist/index.html`
   - `^admin/(?P<path>.*)$` → `serve` из `frontend/admin-dist`; на `Http404` → отдать
     `admin-dist/index.html`
   - `^(?P<path>.+)$` (ПОСЛЕДНИМ) → `serve` из корня `frontend/` (покрывает `/fonts/*`)
   - SPA-fallback оформить маленьким helper-view: пробует `serve(...)`, ловит `Http404`,
     отдаёт нужный `index.html`.
   Экспортировать список как `dev_urlpatterns`.
2. В `journal_django/config/urls.py` — в самом конце файла:
   ```python
   from django.conf import settings
   if settings.DEBUG:
       from .urls_dev import dev_urlpatterns
       urlpatterns += dev_urlpatterns
   ```
   **Критично:** dev-паттерны добавляются строго последними. Django матчит по порядку —
   catch-all `^(?P<path>.+)$` не должен перехватить уже объявленные выше `/api/*` и
   `/health`. После правки убедиться, что `GET /health` и `GET /api/...` всё ещё отдают JSON.

### Шаг 5. Прод-конфиг (пути изменились — обязательно обновить)
1. `deploy/nginx/journal-kotokod.conf`:
   - `set $app_root` → путь к каталогу `journal_django/` на VPS (раньше указывал на
     корень репо, где лежал `public/`).
   - Во всех `location` заменить `public/login|teacher|admin-dist` →
     `frontend/login|teacher|admin-dist`.
   - Добавить раздачу корневых шрифтов `/fonts/` (например, `location /fonts/ { alias
     $app_root/frontend/fonts/; }`) — нужно для teacher/login.
2. `deploy/README.md`: обновить пути `public/*` → `frontend/*` и команду сборки admin
   (`cd journal_django/frontend/admin-src && npm install && npm run build`).

### Шаг 6. Документация
- `CLAUDE.md`: обновить раздел «Структура» (`public/*` → `frontend/*`, `web/admin` →
  `frontend/admin-src`) и команды запуска/сборки admin (`npm run admin:*` → запуск из
  `frontend/admin-src`). Прочие `docs/**` — исторические, не трогать.

## Замечания по auth (проверить, не менять без необходимости)
- Cookie `session` — `HttpOnly`, `SameSite=Strict`; флаг `Secure` выставляется только в
  `production.py`, поэтому по `http://localhost` cookie ставится корректно. Убедиться, что
  `config/settings/base.py` не форсит `Secure`.
- `frontend/login/login.js` после входа делает `window.location = j.redirect`. Проверить
  в `apps/auth_app` (login view), что значения `redirect` (`/teacher`, `/admin`) совпадают
  с dev-маршрутами из шага 4; при расхождении — выровнять раздачу под фактический redirect.

## Как запускать после переноса

**Платформа целиком (без Node):**
```
cd journal_django
.venv/Scripts/python.exe manage.py runserver        # :8000
```
`http://localhost:8000/` → login → после входа `/teacher` или `/admin` (Django отдаёт из
`frontend/`). Всё на одном порту — cookie работают.

**Пересборка admin (только при правке React-исходников):**
```
cd journal_django/frontend/admin-src
npm install        # один раз
npm run build      # → ../admin-dist
```
Опционально HMR-разработка: `npm run dev` (Vite :5173, proxy `/api` → :8000), открыть
`http://localhost:5173/admin/`. Это режим разработки admin, не запуск платформы.

## Верификация (критерии готовности)
1. `cd journal_django && .venv/Scripts/python.exe -m pytest -q` — бэкенд-тесты зелёные
   (раздача статики на API не влияет).
2. `cd journal_django/frontend/admin-src && npm install && npm run build` — бандл лёг в
   `frontend/admin-dist/` без ошибок; `npm run typecheck` чист (импорт `shared-types`
   разрешается).
3. `manage.py runserver`, в браузере:
   - `http://localhost:8000/` → страница входа; `/login/login.js`, `/login/styles.css`,
     `/fonts/*` → 200 (не 404).
   - вход teacher → `/teacher`, SPA грузится, шрифты `/fonts/*` ок, `GET /api/getData` отвечает.
   - вход admin/manager (2FA) → `/admin`, React-SPA грузится, `GET /api/auth/me` и
     `GET /api/admin/dashboard` → 200.
   - hard-refresh на `/admin/students` и `/teacher/...` → не 404 (SPA history-fallback).
   - `GET /api/...` и `/health` по-прежнему отдают JSON, а не HTML.
4. В `journal_django/frontend/admin-src/src/**` нет импортов за пределы `admin-src/`;
   каталоги `public/`, `web/`, `shared/` в корне репозитория удалены/пусты.

## Чего НЕ делать
- Не менять API-пути и логику фронтенда (он origin-agnostic).
- Не переписывать admin; Node — только разовый компилятор admin при правках `admin-src/`.
- Не включать раздачу статики Django в проде — там её отдаёт nginx (раздача строго
  `if settings.DEBUG`).
- Не трогать прод-стек `deploy/` сверх обновления путей (gunicorn/systemd без изменений).
```
