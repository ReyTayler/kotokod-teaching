# journal-backend

Сервер учёта посещаемости для школы KOTOKOD. Единый вход `/login` с выбором роли + 2FA; teacher SPA `/teacher` и admin SPA `/admin` (React 19 + TanStack Query v5 + React Router v7). Всё на PostgreSQL.

> **Бэкенд — Python Django+DRF (`journal_django/`).** Express, Nest-каркас (2026-06-11) и Node-инструменты (2026-08-02) удалены; упоминания `server.js`, `services/*.js`, `computeFifo` и т.п. в комментариях кода — историческая справка о происхождении порта. Backfill Sheets→PG — `journal_django/apps/sync/` (`sheets_client.py`, `backfills/`), создание учётки — `manage.py bootstrap_admin`. В корне: документация, `db/` (историческая SQL-схема эпохи Express), `deploy/` (сервер, Ansible, копии).

## 🔒 Безопасность — ОБЯЗАТЕЛЬНО

**Полный свод правил: [`docs/security-guidelines.md`](docs/security-guidelines.md)** — читать перед добавлением ЛЮБОЙ фичи/правки; там же чеклист для PR.

Самое критичное (нарушение = блокер):

- **RBAC**: DRF default = `AllowAny`. КАЖДАЯ новая вьюха ОБЯЗАНА задать `permission_classes` (`IsAdmin`/`IsManagerOrAdmin`/`IsTeacher`). Забыл → эндпоинт открыт всем. Доступ проверяется на API, не только на фронте (фронт-guard = UX/defense-in-depth).
- **Auth**: JWT только в HttpOnly-cookie (не в JS/localStorage); токены — через `issue_tokens_for`/`set_auth_cookies`. Отзыв — инкремент `token_version` (при смене/сбросе пароля и 2FA). Свою аутентификацию не изобретать.
- **CSP `script-src 'self'`**: НИКАКИХ inline-`<script>`, `onclick=`, `eval`. Весь JS — внешним файлом same-origin. Внешний origin (CDN/API/шрифты) — только с обновлением CSP.
- **CSRF**: мутирующие методы шлют `X-CSRFToken`; не ставить `@csrf_exempt`.
- **Rate-limit** (Django + nginx) на всех auth/OTP/reset-эндпоинтах.
- **SQL** только параметризованный (`%s`); идентификаторы — из whitelist.
- **Секреты** только из окружения; не коммитить (`.env`, ключи, дампы `backups/`, ПДн). Аудит чувствительных действий — `log_event`, без секретов в `meta`.

## Критичные соглашения

**Git**: репозиторий активен, remote — `origin` (GitHub `ReyTayler/kotokod-teaching`), основная ветка `main`. Репозиторий **публичный** (решение владельца) — секреты, ПДн и дампы в него не попадают ни при каких условиях. Коммитить/пушить только по явной просьбе. Разработка ведётся локально (dev-БД, runserver), CI нет; сервер — см. «Инфраструктура».

**Docker не использовать** — ни локально, ни на проде (Beget VPS, Ubuntu 22.04). Решение владельца; плюсы и минусы обсуждены 2026-10-12, вернуться — при втором разработчике или отдельных сервисах платформы.

**Эталонная структура проекта**: так как в основе проекта лежит Python Django+DRF, необходимо строго соблюдать структуру для проекта, которая считается эталонной для такого фреймворка из документации и best practice.

**Не придумывать "велосипед"**: использовать максимум возможностей фреймворков, которые указаны в проекте, не писать всё с нуля, если это уже было придумано в самом фреймворке (пример - не использовать свою систему аутентификации и авторизации, когда есть встроенные механизмы от Django).

**Всегда опираться на документации и существующие паттерны**: не выдумывать что-то своё, использовать всегда знания, в первую очередь, из официальных документаций к используемым в проекте инструментам.

**Быть строгим senior-разработчиком**.

**Порядок маршрутов** (`config/urls.py`): `/api/auth` → `/api/admin/*` → `/api/integrations/*` → общий `/api` (teacher). Общий `/api` — последним, иначе перехватит более узкие префиксы.

**Часовой пояс**: `TIME_ZONE='Europe/Moscow'`, `USE_TZ=True`; сервисы (gunicorn, Celery) запускаются с `TZ=Europe/Moscow` (юниты `deploy/systemd`). Teacher-отчёт считает статус урока по локальному времени — другой TZ уводит статус на день.

**`payments` immutable**: только POST/DELETE, никакого PATCH. `total_amount = unit_price × subscriptions_count` — CHECK в БД + пересчёт на сервере. `unit_price` округляется до копеек ДО умножения.

**Half-lesson**: `duration=45min → 0.5 урока`, иначе 1. Канон веса — `apps/lessons/weights.py`.

**Балансы выводятся, не хранятся**: `get_student_balance()` (`apps/finances/balance.py` — единственный дом расчёта; одноимённые функции в `students`/`payments` лишь делегируют сюда) = куплено − пройдено **общим пулом по всем направлениям** (с 2026-07-08; `payments.direction_id` — информационная метка, разбивки по направлениям только справочные).

**FIFO-финансы**: `compute_fifo` (`apps/finances/fifo.py`, точный `Decimal`, округление до копеек один раз на выходе). Партии строит **только** `build_lots` (`apps/finances/lots.py`): цена урока = `total_amount / lessons_count` оплаты; с доплатами (`kind='surcharge'`) оплата дробится на блоки по 4 урока; возвраты — синтетические списания, не партии. Guard: оплаты с `lessons_count=NULL/0` пропускаются (деление на ноль ломает суммы). Подробнее: `docs/finances.md`.

**Журнал изменений (pghistory)**: новые доменные модели ОБЯЗАНЫ получать `@pghistory.track(InsertEvent(), UpdateEvent(), DeleteEvent())` + запись в `apps/changelog/registry.py` (тест `test_registry_covers_all_tracked_models` упадёт, если забыть) + миграцию. Метки операций — `apps/changelog/labels.py` (новый мутирующий URL → новое правило). Секретные поля — в `exclude` декоратора.

**Paginator**: пагинация используется встроенная от фреймворка (`apps/core/pagination.StandardPagination`, 50 на страницу), никаких постоянных пагинаций от SELECT.

**Направление сортировки** из запроса — только из whitelist: `sort_dir not in ('asc', 'desc')` → значение по умолчанию или 400 (как в `apps/accounts/views.py`, `apps/audit/views.py`). Сырое значение в `ORDER BY` не подставлять.

**ErrorBoundary key**: `key={location.pathname}`, NOT `key={location.key}` (последнее ремоунтит на каждый setSearchParams → потеря фокуса инпутов).

**`.data-table--loading`**: гасить `pointer-events` только на `tbody`, не на всей таблице.

**`placeholderData: keepPreviousData`** обязателен во всех server-paginated хуках.

**Native form-элементы запрещены** в admin SPA: использовать `SelectInput`, `DateInput`, `Checkbox`, `Combobox` из `components/form/`. Enum-labels — только из `lib/labels.ts`.

**Design tokens** — единственный источник: `journal_django/frontend/admin-src/src/styles/tokens.css`. Никаких hardcoded цветов/радиусов/отступов. Подробнее: `docs/design-system.md`.

**`AuthProvider`**: поле `me`, не `user`. `GET /api/auth/me` возвращает **плоский** объект (`{ account_id, email, role, teacher_id, name, twofa_enabled }`) — БЕЗ обёртки `{ me: {...} }`; `api<Me>()` отдаёт его как есть.

## Конфигурация (.env)

Файл — в корне репозитория; образец с пояснениями — `.env.example`. Прод-режим включает `DJANGO_SETTINGS_MODULE=config.settings.production` (задан в юнитах systemd, не в `.env`).

```
DATABASE_URL=postgresql://journal:...@localhost:5432/journal
SECRET_KEY=                   # 128-hex, в проде обязателен
ADMIN_COOKIE_SECRET=          # 128-hex; запасной источник ключа для dev
ALLOWED_HOSTS=                # домен; в проде пусто = не пустит никого
CSRF_TRUSTED_ORIGINS_LIST=    # https://<домен> — SPA и API на одном origin
CORS_ORIGINS=                 # пусто = кросс-ориджин запрещён (так и нужно)
REDIS_URL=                    # без него — синхронно, LocMemCache, без Celery-задач
SMTP_HOST/PORT/USER/PASS/FROM # Beget SMTP для email-OTP
# Telegram-уведомления:
TELEGRAM_BOT_TOKEN=           # токен того же бота, что крутится в kotocode-bot
TELEGRAM_GENERAL_CHAT_ID=     # общий чат сотрудников (-100...); пусто → дубли в чат не идут
BOT_SERVICE_TOKEN=            # общий секрет журнал ↔ бот для /api/integrations/telegram
NOTIFICATIONS_HISTORY_LIMIT=200  # сколько ЗАВЕРШЁННЫХ записей очереди хранить
KNOWLEDGE_MEDIA_ROOT=          # корень хранилища картинок базы знаний; прод — /var/www/journal-media
KNOWLEDGE_X_ACCEL_PREFIX=      # префикс internal-локации nginx; пусто → Django отдаёт файлы сам (локально)
# Legacy (Phase 5):
STUDENTS_SPREADSHEET_ID=
JOURNAL_SPREADSHEET_ID=       # нужен для backfill-payments
```

**Telegram-уведомления** — `apps/notifications/`, единственное место в журнале, знающее про Telegram. Очередь исходящих (`notification_messages`) лежит в PostgreSQL: доменные сервисы (`scheduling`, `extra_lessons`) вызывают `notifications.services.notify_teacher()` **внутри своей транзакции** (transactional outbox — либо операция и сообщение, либо ничего), а Celery-beat раз в минуту разгребает очередь и шлёт через Telegram Bot API. Бот в доставке не участвует. Идемпотентность — уникальный `dedup_key` на уровне БД. Дайджесты: расписание 8:00, незаполненные отчёты 21:00 (оба только в личку); точечные уведомления об изменениях — личка + дубль в общий чат. Импорт `apps.notifications` из доменных приложений — **только локальный, внутри функции**. Спека: `docs/superpowers/specs/2026-08-03-telegram-notifications-design.md`.

## Тесты

`pytest` из `journal_django/` (~2900 тестов).

⚠️ Гонять **полный** `pytest -q`, а не по приложениям: часть приложений no-op'ит `django_db_setup` (общая `journal_test`), часть пересоздаёт `test_journal_test`. Прогон по частям даёт ложный результат.

## Статус фаз

Всё до Phase R2 + Payments/Discounts + Design system + RBAC + teacher SPA на React (`frontend/teacher-src`) — **✅**. Прод развёрнут (с 2026-07-13). Phase 5 (удалить Sheets) — ⏳ частично.

## Производительность (учитывать при любой правке)

VPS 4 CPU / 6 ГБ под 50–100 учителей и 10–15 admin; на той же машине — бот `kotocode-bot`. Не читать «всё» там, где нужна часть. Индексы под реальные предикаты (PG не индексирует FK). Пагинация везде.

Каждую новую добавляемую или изменяемую фичу проверяй на производительность и способы оптимизации. В проекте уже используется Celery и Redis если что.


## Инфраструктура

Прод: `develop-kotokod.ru`, Beget VPS (Санкт-Петербург), Ubuntu 22.04, без Docker. Код — `/opt/kotokod/journal-backend` (git-клон `main`), пользователь `kotokod`.

**Сервер описан в Ansible** — `deploy/ansible/` (шпаргалка для владельца — его `README.md`). Запускается **на самом сервере** (`connection: local`), ansible-core 2.17.14 в `/opt/ansible`. Роли: base, security, postgresql, redis, restore, app, services, backup, nginx.
- Правки сервера — **только через роли** и `deploy/`, не руками: иначе следующий прогон их откатит или покажет расхождением. Роли берут конфиги прямо из `deploy/` (systemd, nginx, pgbackrest, scripts) — копий внутри ролей нет.
- Перед применением на проде — `ansible-playbook site.yml --check --diff`, показать владельцу, применять с его согласия.
- `deploy/nginx/journal-kotokod.conf` — **шаблон Jinja** (`{{ nginx_domain }}`, `{{ django_dir }}`), вручную не копировать.
- Роль `app` код только клонирует и **не обновляет**; выкатка новой версии сейчас — `git pull` + перезапуск сервисов (плейбук выкатки не написан).
- Секреты (`.env`, `/etc/pgbackrest/conf.d/secrets.conf`, `/etc/kotokod/s3-backup.env`) плейбук не создаёт и не выводит — только проверяет наличие.

**Резервные копии** (`deploy/offsite-backup.md`): pgBackRest → Selectel S3, бакет `kotokod-backoffice-reserve`, пул ru-6 (Москва) — полная вс, разностная пн–сб, архив WAL с `archive_timeout=60` (потеря ≤ 1 мин); файлы Wiki — rclone ежечасно; плюс ночной `pg_dump` на самом сервере. Копии шифруются; пароль шифрования — только у владельца.

**Восстановление**: `site.yml -e restore=true` на чистом сервере (на сервере с базой журнала роль отказывается работать). Учения — `-e restore=true -e drill=true`: без копий/архива (не писать в бакет прода), без Celery beat (не слать рассылки), без nginx. Полный путь на чистом сервере ещё **не проверен учениями**.

**Решения владельца** (не «чинить» без его слова): вход root по SSH с паролем оставлен намеренно; репозиторий публичный; Docker не используется.

**Известное**: на проде Python 3.11.0rc1 (предрелизный пакет Ubuntu 22.04); PostgreSQL на заводских настройках памяти (`shared_buffers` 128 МБ); мониторинга и оповещений нет; DNS домена — у Beget.

## Backlog

Soft-delete payments и прочее — `docs/BACKLOG.md`.
