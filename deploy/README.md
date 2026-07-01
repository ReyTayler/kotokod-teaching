# Cutover на Django + снос Express (раздел 08)

Runbook перевода продакшена с Node/Express на Django за nginx. Цель — переключить
трафик `/api/*` на Django без простоя и с возможностью мгновенного отката, затем
(отдельным, явно подтверждённым шагом) удалить Express.

> **Контекст:** Beget VPS, Ubuntu 22.04, 2 CPU / 2 ГБ RAM, **без Docker**.
> Django и Express делят одну PostgreSQL и один корневой `.env`.
> SPA-статика (`journal_django/frontend/{login,teacher,admin-dist,fonts}`) раздаётся nginx.

Артефакты в этой папке:
- `nginx/journal-kotokod.conf` — прод site-config (TLS + security + rate-limit + `include` сниппета)
- `nginx/snippets/journal-static.conf` — **общие** location-блоки раздачи фронта (источник истины dev+прод)
- `nginx/local/nginx.conf` + `nginx/local/start-local-nginx.ps1` — локальный запуск через nginx (Windows)
- `gunicorn.conf.py` — WSGI app-server (unix-сокет)
- `systemd/journal-django.service` — автозапуск gunicorn

---

## Локальный запуск через nginx (Windows, без Docker)

Локально nginx раздаёт статику фронта и проксирует `/api` + `/health` на
`manage.py runserver`. Это dev/prod parity: те же location-блоки статики, что в
проде (`nginx/snippets/journal-static.conf`). Django сам статику больше не отдаёт
(`config/urls_dev.py` удалён).

1. **Установить nginx:** `scoop install nginx` | `choco install nginx` | zip с nginx.org.
2. **Указать путь к коду:** в `nginx/local/nginx.conf` проверить `set $app_root …;`
   (путь к `journal_django/`, форвард-слеши) и абсолютный путь в `include …/snippets/journal-static.conf;`.
3. **Поднять Django:**
   ```
   cd journal_django
   .venv/Scripts/python.exe manage.py runserver 8000
   ```
4. **Поднять nginx:**
   ```
   ./deploy/nginx/local/start-local-nginx.ps1            # проверит конфиг и запустит
   ./deploy/nginx/local/start-local-nginx.ps1 -Reload    # перечитать после правки сниппета
   ./deploy/nginx/local/start-local-nginx.ps1 -Stop      # остановить
   ```
5. Открыть **http://localhost:8080/** → вход → `/teacher` или `/admin`. Один origin —
   cookie `session` ходит между страницами (`Secure` в dev не ставится).

Пересборка admin SPA (только при правке React-исходников) — как в проде:
`cd journal_django/frontend/admin-src && npm install && npm run build`.

---

## 0. Инвариант, который нельзя нарушить

- **Часовой пояс.** И Node, и Django запускать в `TZ=Europe/Moscow`. Teacher `/report`
  считает статус урока по локальному времени сервера — другой TZ уводит статус на день.
  В юните это `Environment=TZ=Europe/Moscow`; у Express — переменная окружения процесса.
- **Порядок маршрутов** `/api/auth` → `/api/admin` → `/api` (teacher). В Express это был
  порядок `app.use(...)`; в Django он зашит в `config/urls.py` (admin ВЫШЕ teacher-guard).
  nginx выбирает location по длиннейшему префиксу, поэтому в конфиге порядок блоков не важен.
- **Cookie `session`** общий: HMAC-формат byte-identical у обоих бэкендов (подтверждено
  `scripts/diff_auth.py`). Поэтому во время сосуществования трафик можно дробить между
  серверами — сессия читается обоими.

## 1. Подготовка Django на VPS

```bash
cd /opt/kotokod/journal-backend            # путь к репозиторию (подставить свой)
python3.11 -m venv journal_django/.venv
journal_django/.venv/bin/pip install -r journal_django/requirements.txt

# Прогон тестов и проверок конфигурации
cd journal_django
.venv/bin/python -m pytest -q
DJANGO_SETTINGS_MODULE=config.settings.production .venv/bin/python manage.py check --deploy
```

Сборка admin SPA (если ещё не собрана) — кладёт билд в `journal_django/frontend/admin-dist/`.
Node нужен только как разовый компилятор admin; в запуске платформы не участвует:
```bash
cd /opt/kotokod/journal-backend/journal_django/frontend/admin-src && npm install && npm run build
```

`.env` (общий с Express) должен содержать минимум:
```
DATABASE_URL=postgresql://journal:...@localhost:5432/journal
ADMIN_COOKIE_SECRET=<128-hex>
ALLOWED_HOSTS=example.kotokod.ru
CORS_ORIGINS=                       # пусто = same-origin only (SPA с того же домена)
SMTP_HOST=... SMTP_PORT=465 SMTP_USER=... SMTP_PASS=... SMTP_FROM=...
NODE_ENV=production                 # Express: Secure-cookie + строгий CORS
```
`.env` несёт секреты (DB-пароль, `ADMIN_COOKIE_SECRET`, `SMTP_PASS`) — закрыть права:
```bash
chmod 600 .env && chown kotokod:kotokod .env      # systemd читает от root до сброса прав
```

> **Ожидаемые предупреждения `manage.py check --deploy`** (не ошибки):
> `security.W002` (X-Frame-Options) — ставится на nginx-слое; `security.W003` (CSRF) —
> намеренно, защита = `SameSite=Strict` cookie (как в Express); `fields.W342`
> (Lesson FK unique) — модель `managed=False`, зеркало реальной схемы. `W020`
> (ALLOWED_HOSTS) исчезает, когда переменная задана в `.env`.

## 2. Поднять gunicorn + nginx

```bash
sudo cp deploy/systemd/journal-django.service /etc/systemd/system/
# отредактировать User/WorkingDirectory/EnvironmentFile/пути под VPS
sudo systemctl daemon-reload && sudo systemctl enable --now journal-django
sudo systemctl status journal-django               # active (running), сокет создан

sudo cp deploy/nginx/journal-kotokod.conf /etc/nginx/sites-available/journal-kotokod
sudo ln -s /etc/nginx/sites-available/journal-kotokod /etc/nginx/sites-enabled/
# Общий сниппет статики (его include'ит site-config; путь относительно /etc/nginx/):
sudo mkdir -p /etc/nginx/snippets
sudo cp deploy/nginx/snippets/journal-static.conf /etc/nginx/snippets/journal-static.conf
# заменить server_name / $app_root / ssl_certificate*
sudo nginx -t && sudo systemctl reload nginx
```

## 3. Верификация ПЕРЕД переключением (Express ещё обслуживает прод)

Поднять Django рядом (порт/сокет), Express оставить активным, сверить ответы один-в-один:
```bash
cd journal_django
.venv/bin/python scripts/diff_express.py     # все админ/teacher разделы → 0 расхождений
.venv/bin/python scripts/diff_auth.py         # /api/auth/* + cross-compat cookie → 8/8
```
> `diff_*` дают ложные 429 при повторных прогонах (rate-limit 10/15мин на login) —
> сверять на свежих инстансах обоих серверов.

Чек-лист: полный прогон фронта против Django (страница логина + вход с 2FA, teacher SPA
отправка урока + report, admin SPA — список/создание/правка по каждому разделу).

> **Про rate-limit на login.** Настоящий барьер против brute-force — **lockout аккаунта
> в БД** (5 неудач → `locked_until` +15 мин; общий между воркерами и серверами, переживает
> рестарт). nginx `api_login` — коарс анти-DoS поверх. App-лимитер в `auth_app/views.py`
> in-memory **per-воркер**: при N gunicorn-воркерах эффективный потолок ~N×10/15мин и
> сбрасывается на рестарт воркера — это best-effort, не точные 10/15мин. Точную защиту
> даёт БД-lockout. Для строгого IP-лимита через все воркеры — Redis-store (BACKLOG).

## 4. Бэкап БД (обязательно до переключения)

```bash
pg_dump "$DATABASE_URL" -Fc -f /var/backups/journal-pre-cutover-$(date +%F-%H%M).dump
```

## 5. Переключение трафика

Cutover в этом конфиге **полный** (`location /api/ → Django`). Применяется reload'ом nginx
(п. 2). Если нужен поэтапный перевод — временно в nginx направить часть префиксов на Express
(`upstream journal_express { server 127.0.0.1:3000; }` + отдельные `location`), переключая
`/api/admin`, затем `/api` (teacher), и **последним** `/api/auth`.

После reload:
```bash
curl -sS https://example.kotokod.ru/api/auth/me        # 401 без cookie — Django отвечает
# войти в браузере, прокликать ключевые сценарии admin/teacher
sudo journalctl -u journal-django -f                    # следить за ошибками
```

## 6. Откат (если что-то не так)

```bash
# 1. Вернуть трафик на Express: в nginx сменить proxy_pass /api/ на 127.0.0.1:3000
#    (или восстановить прежний site-config) и reload:
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl start journal-express        # если Express был остановлен
# 2. Данные откатывать НЕ требуется (общая БД, схема не менялась). Восстановление
#    из дампа — только если повреждены данные:
#    pg_restore -d "$DATABASE_URL" --clean /var/backups/journal-pre-cutover-*.dump
```
Откат безопасен: Django ничего в схеме не мигрировал (`managed=False`), cookie общий.

## 7. Снос Express — ФИНАЛЬНЫЙ шаг (по явному решению, после стабильной работы)

Выполнять только после нескольких дней зелёной работы Django в проде. **Необратимо**
(в проекте нет git) — сделать архив перед удалением.

Удалить:
- `server.js`, `routes/`, `services/` (КРОМЕ `services/sheets.js`), `shared/` (если не нужен
  Node-скриптам), `test/`, Nest-каркас `src/` + `test/nest/`, `nest-cli.json`, `tsconfig*.nest*`
- backend-зависимости из `package.json` + `node_modules` (оставить то, что нужно admin SPA-сборке)

**НЕ удалять** (до перехода компании с Google Sheets на веб-приложение, отдельным решением):
- `scripts/backfill-*.js` — подтягивание данных из Sheets в БД (dev-инструмент)
- `services/sheets.js` — нужен backfill-скриптам

После сноса убрать из nginx все ссылки на `journal_express`, отключить юнит Express.
