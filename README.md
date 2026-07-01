# KOTOKOD — платформа учёта посещаемости

Сервер учёта посещаемости и биллинга для детской образовательной платформы **KOTOKOD**.
Единый вход с выбором роли и 2FA, кабинет преподавателя и админ-панель управления
(CRM, оплаты, зарплаты, отчёты, дашборд). Всё на PostgreSQL.

> Бэкенд — **Python / Django + DRF** (`journal_django/`). Исторический Node/Express
> удалён; в корне остались только dev-инструменты (backfill Google Sheets → PostgreSQL)
> и утилиты обслуживания БД.

---

## Стек

| Слой | Технологии |
|------|-----------|
| **Backend** | Django 5.1, Django REST Framework, PostgreSQL (psycopg2) |
| **Auth** | JWT в HttpOnly-cookie (SimpleJWT), 2FA — TOTP (`pyotp`) + e-mail OTP, rate-limit |
| **Admin SPA** | React 19, Vite, TanStack Query v5, React Router v7, TypeScript |
| **Teacher SPA** | Vanilla JS |
| **Страница входа** | Vanilla JS/CSS (`/login`, `/login/set-password`) |
| **Раздача** | nginx (статика + прокси `/api` на Django), gunicorn на проде |
| **Dev-инструменты** | Node.js (backfill Sheets→PG, миграции БД, обслуживающие скрипты) |

---

## Структура репозитория

```
.
├── journal_django/            # ★ основной бэкенд (Django + DRF)
│   ├── config/settings/       #   development | production | test
│   ├── apps/                  #   доменные приложения (auth, students, payments, …)
│   ├── frontend/
│   │   ├── login/             #   страница входа (vanilla)
│   │   ├── teacher/           #   кабинет преподавателя (vanilla SPA)
│   │   ├── admin-src/         #   исходники админ-панели (React/Vite)
│   │   ├── admin-dist/        #   собранный бандл админки (раздаётся nginx)
│   │   └── fonts/             #   self-hosted шрифты
│   ├── manage.py
│   └── requirements*.txt
├── db/migrations/             # SQL-схема доменных таблиц
├── scripts/, services/        # Node dev-инструменты (backfill, обслуживание)
├── deploy/                    # nginx / gunicorn / systemd + runbook
├── docs/                      # проектная документация
├── .env.example               # шаблон конфигурации
└── CLAUDE.md                  # доменные инварианты и соглашения
```

---

## Требования

- **Python** 3.11+
- **PostgreSQL** 14+
- **Node.js** 18+ (для сборки админ-SPA и dev-инструментов)
- **nginx** (локально и на проде — статику отдаёт nginx, не Django)

---

## Быстрый старт (локально, Windows/Linux, без Docker)

### 1. Конфигурация

```bash
cp .env.example .env
# заполнить: DATABASE_URL, ADMIN_COOKIE_SECRET (128-hex), SMTP_* для e-mail-OTP
```

Ключ для cookie можно сгенерировать так:

```bash
python -c "import secrets; print(secrets.token_hex(64))"
```

### 2. База данных

```bash
createdb journal                 # или через psql: CREATE DATABASE journal;
npm install                      # dev-инструменты (pg, googleapis, …)
npm run db:migrate               # применяет db/migrations/*.sql
```

### 3. Backend (Django)

```bash
cd journal_django
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python manage.py migrate         # служебные таблицы Django (auth/sessions)
python manage.py runserver 8000  # API на http://127.0.0.1:8000
```

Создать первого администратора:

```bash
python manage.py bootstrap_admin   # см. apps/accounts/management/commands
```

### 4. Админ-панель (React/Vite)

```bash
cd journal_django/frontend/admin-src
npm install
npm run build        # → frontend/admin-dist (то, что раздаёт nginx)
# либо для разработки: npm run dev  (Vite :5173, проксирует /api на :8000)
```

### 5. nginx (раздача фронта + прокси API)

Локально nginx раздаёт `login` / `teacher` / `admin-dist` / `fonts` и проксирует
`/api` и `/health` на `runserver`. Конфиг и скрипт запуска — в
`deploy/nginx/local/`. Открыть **http://localhost:8080**.

Подробности (dev/prod parity, gunicorn, systemd) — в **`deploy/README.md`**.

---

## Роли и вход

Единая точка входа `/login` с выбором роли и обязательной 2FA:

- **Преподаватель** → кабинет `/teacher`;
- **Админ / Менеджер** → панель управления `/admin`.

Доступ к данным закрыт на уровне API ролевыми пермишенами
(`IsManagerOrAdmin` / `IsAdmin`); admin-SPA дополнительно не пускает чужую роль
в оболочку (клиентский `AuthGate`). 2FA настраивается при первом входе:
приложение-аутентификатор (TOTP + QR) **или** код на e-mail.

---

## Тесты

```bash
cd journal_django
pytest                # изолированная БД journal_test (config/settings/test.py)
```

> `pytest.ini` жёстко указывает `DJANGO_SETTINGS_MODULE=config.settings.test` — в нём
> есть fail-fast guard против боевой БД. Не переключать на `development`.

Node dev-инструменты покрыты отдельно: `node --test`.

---

## Конфигурация (`.env`)

Полный список — в `.env.example`. Ключевое:

| Переменная | Назначение |
|------------|-----------|
| `DATABASE_URL` | строка подключения PostgreSQL |
| `ADMIN_COOKIE_SECRET` | 128-hex, подпись cookie (**обязателен**) |
| `SMTP_HOST/PORT/USER/PASS/FROM` | отправка e-mail-OTP |
| `STUDENTS_SPREADSHEET_ID`, `JOURNAL_SPREADSHEET_ID` | только для backfill из Google Sheets |

---

## Безопасность

Секреты в репозиторий **не коммитятся** (`.gitignore`): `.env`,
`service-account-key.json`, дампы БД (`backups/`), логи. При развёртывании создайте
`.env` из шаблона и положите ключ сервис-аккаунта Google рядом (нужен только
backfill-скриптам).

---

## Развёртывание

Прод: **Beget VPS, Ubuntu 22.04, без Docker**, nginx (TLS + rate-limit) → gunicorn.
Пошаговый runbook, конфиги nginx/gunicorn/systemd — в **`deploy/`**.
