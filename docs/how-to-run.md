# Как запускать проект (после переноса фронтенда в Django, раздел 10)

Платформа запускается **одной командой, без Node**. Node нужен только как разовый
компилятор admin SPA, когда правишь React-исходники.

Команды — для PowerShell (Windows). Все пути от корня репозитория
`C:\Users\ilyap\TestKOTOKOD`.

---

## 1. Повседневный запуск платформы

```powershell
cd journal_django
.venv\Scripts\python.exe manage.py runserver        # http://localhost:8000
```

Открыть в браузере **http://localhost:8000/** → страница входа.
После входа Django сам отдаёт нужный фронт на одном порту :8000:
- учитель → `/teacher` (vanilla SPA);
- менеджер/админ (с 2FA) → `/admin` (React SPA).

> Всё на одном origin `localhost:8000` — поэтому cookie `session`
> (`SameSite=Strict`) ходит между страницами. Другой порт ломает авторизацию.

Остановить: `Ctrl+C`.

---

## 2. Первый запуск на чистой машине (установка зависимостей)

Однократно, если ещё не сделано (сейчас уже всё установлено и собрано):

```powershell
# 2.1 venv + зависимости бэкенда
cd journal_django
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

# 2.2 сборка admin SPA (кладёт бандл в frontend/admin-dist/)
cd frontend\admin-src
npm install
npm run build
cd ..\..

# 2.3 запуск
.venv\Scripts\python.exe manage.py runserver
```

`.env` лежит в корне репозитория (общий) — он уже есть. Минимум переменных:
`DATABASE_URL`, `ADMIN_COOKIE_SECRET` (128-hex), SMTP-параметры для email-OTP.

---

## 3. Разработка admin SPA (только при правке React-исходников)

Исходники: `journal_django/frontend/admin-src/`.

**Вариант А — пересобрать бандл** (Django отдаёт собранное на :8000):
```powershell
cd journal_django\frontend\admin-src
npm run build            # → ../admin-dist/
```

**Вариант Б — HMR-разработка** (горячая перезагрузка, для вёрстки):
```powershell
# терминал 1 — бэкенд
cd journal_django
.venv\Scripts\python.exe manage.py runserver        # :8000

# терминал 2 — Vite dev-сервер
cd journal_django\frontend\admin-src
npm run dev                                          # :5173, proxy /api → :8000
```
Открыть **http://localhost:5173/admin/**.

> ⚠️ В HMR-режиме (:5173) авторизация за логином работать **не будет**: cookie
> `session` с `SameSite=Strict` ставится на :8000 и не уходит с :5173 (cross-site).
> HMR годится для вёрстки, не для работы с реальными данными. Для полноценной
> проверки — собрать бандл (вариант А) и открыть :8000.

Проверка типов без сборки:
```powershell
cd journal_django\frontend\admin-src
npm run typecheck
```

---

## 4. Тесты бэкенда

```powershell
cd journal_django
.venv\Scripts\python.exe -m pytest -q
```

> Известно: тесты `apps/accounts/tests/test_accounts_api.py` падают на состоянии
> общей БД (FK `security_audit_log`) — это отдельная проблема окружения, не
> связана с раздачей фронтенда.

---

## 5. Node dev-инструменты (backfill Sheets→PG, обслуживание БД) — из корня

```powershell
cd C:\Users\ilyap\TestKOTOKOD
npm run backfill:all          # Sheets → PG (порядок важен)
npm run account:create        # первый admin
npm run payroll:rebuild
```

---

## 6. Прод (Beget VPS, Ubuntu 22.04, без Docker)

В проде статику отдаёт **nginx** (не Django — раздача в Django строго `if DEBUG`),
`/api/*` проксируется на gunicorn. См. `deploy/README.md` и
`deploy/nginx/journal-kotokod.conf`. Сборка admin перед деплоем:
```bash
cd journal_django/frontend/admin-src && npm install && npm run build
```

---

## Что где лежит

```
journal_django/
  manage.py                  # точка входа Django
  .venv/                     # виртуальное окружение Python
  config/
    settings/{development,production}.py
    urls.py                  # API-маршруты (+ dev-раздача статики в конце)
    urls_dev.py              # dev-only раздача frontend/ (if DEBUG)
  apps/                      # Django-приложения (домены)
  frontend/                  # ← весь фронтенд
    login/  teacher/         # vanilla SPA
    admin-dist/              # собранный admin (React) — отдаётся как есть
    admin-src/               # исходники admin — здесь правишь и пересобираешь
    fonts/                   # корневые шрифты teacher/login
```
