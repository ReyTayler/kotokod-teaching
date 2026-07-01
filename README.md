# KOTOKOD — платформа учёта посещаемости и биллинга

Веб-платформа для детской образовательной школы **KOTOKOD**: учёт посещаемости,
управление учениками и группами, абонементы и оплаты с точным (FIFO) финансовым
учётом, расчёт зарплаты преподавателей, аналитический дашборд. Единая точка входа
с выбором роли и обязательной двухфакторной аутентификацией.

> **Бэкенд — Python / Django + DRF** (`journal_django/`). Исторический Node/Express
> удалён; в корне остались только dev-инструменты (backfill Google Sheets → PostgreSQL)
> и утилиты обслуживания БД. Источник истины по данным — **PostgreSQL**.

---

## Содержание

- [Возможности](#возможности)
- [Архитектура](#архитектура)
- [Доменная модель](#доменная-модель)
- [Бизнес-логика](#ключевая-бизнес-логика)
- [API](#api)
- [Безопасность](#безопасность)
- [Стек](#стек)
- [Структура репозитория](#структура-репозитория)
- [Быстрый старт](#быстрый-старт-локально-без-docker)
- [Тесты](#тесты)
- [Конфигурация](#конфигурация-env)
- [Развёртывание](#развёртывание)

---

## Возможности

### Вход и роли
- **Единый `/login`** с выбором роли (Преподаватель / Админ · Менеджер) и
  **обязательной 2FA** для всех: TOTP-приложение (QR) **или** одноразовый код на e-mail.
- **Invite-провижининг**: администратор создаёт аккаунт → пользователь по ссылке
  задаёт пароль и настраивает 2FA (`/login/set-password`); выдаются **recovery-коды**.
- Мгновенный отзыв доступа (`token_version`) при сбросе пароля/2FA.

### Кабинет преподавателя (`/teacher`)
- Личное **расписание** и **журнал**: отметка посещаемости, проведение урока
  (`submitLesson`), отчёты по своим группам. Доступ строго к своим данным.

### Админ-панель (`/admin`)
CRM и управление платформой (доступно ролям **admin** и **manager**):

| Раздел | Функции |
|--------|---------|
| **Ученики** | CRUD, статистика, баланс по направлениям, статусы (активен/заморожен/архив), согласия (152-ФЗ) |
| **Группы** | CRUD, слоты расписания, состав (memberships), заморозка участия |
| **Преподаватели** | CRUD, привязка к аккаунтам и направлениям |
| **Направления** | цвет-метка, цена абонемента, число уроков в абонементе |
| **Абонементы и оплаты** | приём оплат (**immutable**), скидки, FIFO-списание |
| **Уроки и посещаемость** | ведение уроков, отметки, полусчёт уроков (45 мин → 0.5) |
| **Зарплата** | расчёт и сводка выплат преподавателям (payroll) |
| **Дашборд** | FIFO read-model, финансовые метрики, графики (Recharts) |
| **Аккаунты / RBAC** | управление пользователями и ролями (только admin) |
| **Аудит** | журнал событий безопасности (только admin) |
| **Токены, Настройки** | инвайт-токены, пользовательские настройки |

---

## Архитектура

Классическая слоистая структура Django-приложения — **каждый доменный модуль**
(`apps/<domain>/`) устроен одинаково:

```
apps/students/
├── models.py        # ORM-модель (managed=False — схема ведётся SQL-миграциями)
├── repository.py    # доступ к данным: параметризованный SQL (%s), без ORM-магии
├── services.py      # бизнес-логика и инварианты
├── serializers.py   # валидация входа + сериализация ответа (DRF)
├── views.py         # APIView + permission_classes (RBAC)
└── urls.py          # маршруты модуля
```

Ключевые технические решения:

- **DRF поверх сырого SQL.** Модели `managed=False`; схема БД управляется
  **SQL-миграциями** (`db/migrations/*.sql`), а не `makemigrations`. Django-миграции
  используются только для служебных таблиц (auth/sessions). Запросы — строго
  **параметризованные** (защита от инъекций), с индексами под реальные предикаты.
- **Аутентификация — JWT в HttpOnly-cookie** (`djangorestframework-simplejwt`).
  Кастомный `CookieJWTAuthentication` читает токен из cookie, **проверяет CSRF** на
  мутирующих методах и сверяет claim **`token_version`** с БД (механизм мгновенного
  отзыва без blacklist). Access 60 мин, refresh 7 дней.
- **RBAC.** DRF default = `AllowAny` (health), каждая вьюха **явно** задаёт
  `permission_classes`: `IsTeacher` / `IsManager` / `IsAdmin` / `IsManagerOrAdmin`.
  Реальная граница доступа — на API; клиентские guard'ы — defense-in-depth.
- **Единый формат ответов.** `DateSafeJSONRenderer` (даты/время → ISO, без
  таймзонного дрейфа), кастомный exception handler, встроенная пагинация
  (`StandardPagination`, 50/страница).
- **Rate-limiting** в два слоя: `django-ratelimit` на auth-вьюхах + `limit_req` в nginx.
- **Раздача.** Статику фронта (login / teacher / admin) отдаёт **nginx**, он же
  проксирует `/api` на Django; на проде — **gunicorn** за nginx (без Docker).

### Фронтенд

- **Админ-панель** — SPA на **React 19 + Vite + TypeScript**, **TanStack Query v5**
  (server-state, `keepPreviousData` во всех серверно-пагинированных хуках),
  **React Router v7**. Единая дизайн-система на CSS-токенах (light/dark), собственные
  form-компоненты, графики на **Recharts**. Собирается в `frontend/admin-dist/`.
- **Кабинет преподавателя** и **страница входа** — **vanilla JS/CSS** (лёгкие,
  без сборки), с прогрессивным улучшением (сегментированный ввод OTP, темизация).
- **CSP-совместимость:** строгий `script-src 'self'` — весь JS вынесен во внешние
  файлы, никаких inline-скриптов и обработчиков.

---

## Доменная модель

Основные сущности (PostgreSQL):

| Таблица | Назначение |
|---------|-----------|
| `accounts`, `account_recovery_codes` | учётки, роли, 2FA, recovery-коды |
| `students` | ученики (+ статус зачисления, согласия) |
| `teachers` | преподаватели |
| `directions` | направления обучения (цвет, цена, число уроков) |
| `groups`, `group_schedule_slots`, `group_memberships` | группы, расписание, состав |
| `lessons`, `lesson_attendance` | уроки и отметки посещаемости |
| `payments` | оплаты абонементов (immutable) |
| `discounts` | скидки |
| `payroll` | расчёт зарплаты |
| `tokens` | инвайт/доступ-токены (PK — текст) |
| `security_audit_log` | журнал событий безопасности |
| `admin_user_settings`, `sync_failures` | настройки, диагностика синхронизации |

Особенности схемы: `lesson_number = numeric(5,1)` (полусчёт), soft-delete через
`active=false` / `enrollment_status`, `ON DELETE RESTRICT` на `payments→students/directions`,
даты как строки `YYYY-MM-DD` (без сдвига на MSK).

---

## Ключевая бизнес-логика

- **Оплаты immutable.** `payments` — только `POST`/`DELETE`, никакого `PATCH`.
  `total_amount = unit_price × subscriptions_count` — пересчитывается на сервере и
  защищён `CHECK` в БД.
- **Полусчёт уроков.** Урок 45 минут = **0.5** урока, иначе 1.
- **Баланс выводится, не хранится.** Баланс ученика = `оплачено − посещено` по
  каждому направлению.
- **FIFO-финансы.** Стоимость одного урока = `total_amount / (subscriptions_count × 4)`
  конкретной оплаты; списание — по принципу «первым оплачен — первым израсходован».
  Оплаты с `subscriptions_count = NULL/0` пропускаются. Подробно: `docs/finances.md`.
- **Скидки** учитываются при расчёте стоимости абонемента.

---

## API

Все endpoints под `/api`. Порядок монтирования: `/api/auth` → `/api/admin/*` → `/api`.

**Аутентификация** `/api/auth/*`
```
POST /login            POST /login/2fa        POST /logout       GET  /me
GET  /csrf             POST /refresh          GET  /invite       POST /invite/accept
POST /2fa/setup        POST /2fa/enable       POST /2fa/disable  POST /2fa/email/send
```

**Админ-панель** `/api/admin/*` (роли manager/admin; accounts и audit — только admin)
```
groups   teachers   directions   discounts   settings   audit-log   tokens
students   memberships   payments   lessons   payroll   dashboard   accounts
```

**Кабинет преподавателя** `/api/*`
```
GET  getData   getAllData        POST submitLesson
GET  report    schedule          POST report/refresh   schedule/refresh   refreshData
```

Полное описание — `docs/endpoints.md`.

---

## Безопасность

Периметр: JWT в HttpOnly-cookie + CSRF на мутациях + `token_version`-отзыв;
RBAC на каждом эндпоинте; обязательная 2FA; строгий CSP (`script-src 'self'`);
security-заголовки и rate-limit в nginx; параметризованный SQL; аудит чувствительных
действий; секреты только из окружения; соответствие 152-ФЗ по ПДн.

📌 **Обязательные правила для любой фичи/правки — [`docs/security-guidelines.md`](docs/security-guidelines.md)** (со сводом и PR-чеклистом).

---

## Стек

| Слой | Технологии |
|------|-----------|
| **Backend** | Python 3.11+, Django 5.1, Django REST Framework, PostgreSQL (psycopg2) |
| **Auth** | SimpleJWT (HttpOnly-cookie), 2FA — `pyotp` (TOTP) + e-mail OTP, `django-ratelimit`, bcrypt |
| **Admin SPA** | React 19, Vite, TypeScript, TanStack Query v5, React Router v7, Recharts |
| **Teacher / Login** | Vanilla JS/CSS |
| **Инфраструктура** | nginx (статика + прокси + TLS + CSP), gunicorn, systemd |
| **Dev-инструменты** | Node.js (backfill Sheets→PG, обслуживание БД) |

---

## Структура репозитория

```
.
├── journal_django/            # ★ бэкенд (Django + DRF)
│   ├── config/settings/       #   development | production | test
│   ├── apps/                  #   17 доменных модулей (students, payments, lessons, …)
│   ├── frontend/
│   │   ├── login/             #   страница входа (vanilla)
│   │   ├── teacher/           #   кабинет преподавателя (vanilla SPA)
│   │   ├── admin-src/         #   исходники админ-панели (React/Vite)
│   │   ├── admin-dist/        #   собранный бандл админки (раздаётся nginx)
│   │   └── fonts/             #   self-hosted шрифты
│   ├── manage.py  ·  requirements*.txt  ·  pytest.ini
├── db/migrations/             # SQL-схема доменных таблиц
├── scripts/, services/        # Node dev-инструменты (backfill, обслуживание)
├── deploy/                    # nginx / gunicorn / systemd + runbook
├── docs/                      # документация (auth, finances, security, CSP, 152-ФЗ, …)
├── .env.example               # шаблон конфигурации
└── CLAUDE.md                  # доменные инварианты и правила
```

---

## Быстрый старт (локально, без Docker)

**Требования:** Python 3.11+, PostgreSQL 14+, Node.js 18+, nginx.

### 1. Конфигурация
```bash
cp .env.example .env
# заполнить DATABASE_URL, ADMIN_COOKIE_SECRET (128-hex), SMTP_* для e-mail-OTP
python -c "import secrets; print(secrets.token_hex(64))"   # генерация секрета cookie
```

### 2. База данных
```bash
createdb journal
npm install            # dev-инструменты
npm run db:migrate     # применяет db/migrations/*.sql
```

### 3. Backend
```bash
cd journal_django
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python manage.py migrate            # служебные таблицы Django
python manage.py runserver 8000     # API на http://127.0.0.1:8000
python manage.py bootstrap_admin    # создать первого администратора
```

### 4. Админ-панель
```bash
cd journal_django/frontend/admin-src
npm install
npm run build      # → frontend/admin-dist (раздаётся nginx)
# разработка: npm run dev  (Vite :5173, проксирует /api на :8000)
```

### 5. nginx
Раздаёт `login/teacher/admin-dist/fonts` и проксирует `/api` на runserver.
Конфиг и скрипт запуска — `deploy/nginx/local/`. Открыть **http://localhost:8080**.
Подробности — `deploy/README.md`.

---

## Тесты
```bash
cd journal_django
pytest             # изолированная БД journal_test (config/settings/test.py)
```
> `pytest.ini` жёстко задаёт `DJANGO_SETTINGS_MODULE=config.settings.test` с
> fail-fast guard против боевой БД — не переключать на `development`.

Node dev-инструменты — `node --test`.

---

## Конфигурация (`.env`)

Полный список — `.env.example`. Ключевое:

| Переменная | Назначение |
|------------|-----------|
| `DATABASE_URL` | подключение к PostgreSQL |
| `SECRET_KEY` | подпись Django (в проде — отдельный, 128+ энтропии) |
| `ADMIN_COOKIE_SECRET` | 128-hex, подпись cookie (**обязателен**) |
| `SMTP_HOST/PORT/USER/PASS/FROM` | отправка e-mail-OTP |
| `ALLOWED_HOSTS`, `CORS_ORIGINS`, `CSRF_TRUSTED_ORIGINS_LIST` | прод-хосты/домены |
| `STUDENTS_SPREADSHEET_ID`, `JOURNAL_SPREADSHEET_ID` | только для backfill из Google Sheets |

Секреты (`.env`, `service-account-key.json`), дампы БД (`backups/`) и логи в
репозиторий **не коммитятся** (`.gitignore`). При развёртывании создайте `.env` из
шаблона.

---

## Развёртывание

Прод: **Beget VPS, Ubuntu 22.04, без Docker**. nginx (TLS + security-заголовки +
CSP + rate-limit) → gunicorn (systemd) → Django, единая PostgreSQL. Пошаговый
runbook и все конфиги — в **`deploy/`** (`README.md`, `nginx/`, `gunicorn.conf.py`,
`systemd/`).

---

## Документация

`docs/`: `auth.md` · `finances.md` · `db-schema.md` · `endpoints.md` ·
`security-guidelines.md` · `csp-explained.md` · `compliance-152fz-checklist.md` ·
`design-system.md` · `deploy-runbook.md` · `architecture_v2.md`.
