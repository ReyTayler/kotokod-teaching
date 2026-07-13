> ⚠️ **УСТАРЕЛ (2026-07-13).** Описывает деплой старого Node/Express-бэкенда, который
> снесён 2026-06-11 (см. `CLAUDE.md`). Актуальный бэкенд — Django (`journal_django/`).
> Актуальная инструкция: [`docs/production-admin-guide.md`](production-admin-guide.md).
> Файл оставлен как историческая справка.

# Deploy runbook — journal-backend (Beget VPS, Ubuntu 22.04, без Docker)

Пошаговое разворачивание на чистый VPS: **2 ядра / 2 ГБ ОЗУ / 30 ГБ NVMe**.
Нагрузка: 50–100 преподавателей (teacher SPA), 10–15 управляющих (admin SPA).
Содержит готовые конфиги под пункты №3 (nginx/gzip) и №4 (PostgreSQL-тюнинг) из
`docs/superpowers/specs/2026-06-04-performance-load-audit.md`.

Конвенция проекта: **без Docker**. Архитектура: nginx (TLS + сжатие + статика) →
Node (только API + SPA-fallback) → PostgreSQL (локально на том же VPS).

```
Браузер ──HTTPS──▶ nginx ──┬─▶ /admin/assets/* ──▶ файлы с диска (immutable-кэш)
                           ├─▶ /api/*          ──▶ Node :3000
                           └─▶ остальное        ──▶ Node :3000 (SPA-fallback)
                                                      │
                                                      └─▶ PostgreSQL :5432 (localhost)
```

---

## 0. Предварительно (локально, до заливки)

- [ ] `npm test` — зелёный (97/97).
- [ ] Собрать **оба** SPA **локально** (⚠️ на VPS `vite build` НЕ запускать — 2 ГБ мало, риск swap/OOM):
      - Admin: `cd journal_django/frontend/admin-src && npm ci && npm run build` → `../admin-dist/`.
      - Teacher: `cd journal_django/frontend/teacher-src && npm ci && npm run build` → `../teacher-dist/`
        (base по умолчанию `/teacher/`; teacher-бандл переиспользует шрифты из `/admin/fonts/*`,
        поэтому `admin-dist` тоже должен быть залит). Оба каталога залить на VPS вместе с репо.
- [ ] Сгенерировать прод-секреты: `node scripts/admin-set-password.js <надёжный-пароль>`
      → получить `ADMIN_PASSWORD_HASH` + `ADMIN_COOKIE_SECRET`.
- [ ] Подготовить домен (A-запись на IP VPS).

---

## 1. Система и пользователь

```bash
sudo apt update && sudo apt upgrade -y
sudo adduser --system --group --home /opt/journal journal   # сервисный пользователь
sudo apt install -y curl ca-certificates ufw
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable
```

## 2. Node.js (LTS)

Версия — мажорная LTS ≥ 20 (локально использовалась 24.x; для прода ок 20/22 LTS).
Глобального Vite/dev-tooling на сервере не нужно — фронт собран локально.

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
node -v
```

## 3. PostgreSQL + тюнинг под 2 ГБ (пункт №4)

```bash
sudo apt install -y postgresql
sudo -u postgres psql -c "CREATE USER journal WITH PASSWORD 'СИЛЬНЫЙ_ПАРОЛЬ';"
sudo -u postgres psql -c "CREATE DATABASE journal OWNER journal;"
```

Тюнинг — `ALTER SYSTEM` (или правка `postgresql.conf`). Параметры разобраны в аудите;
PG из коробки настроен консервативно, на 2 ГБ ему надо разрешить больше памяти:

```bash
sudo -u postgres psql <<'SQL'
ALTER SYSTEM SET shared_buffers = '384MB';          -- личный кэш PG (~25% ОЗУ)
ALTER SYSTEM SET effective_cache_size = '1GB';      -- подсказка планировщику (~50-75% ОЗУ), не аллокация
ALTER SYSTEM SET work_mem = '12MB';                 -- на одну сортировку/хэш (× операции × соединения!)
ALTER SYSTEM SET maintenance_work_mem = '128MB';    -- построение индексов / VACUUM
-- max_connections = 100 (дефолт) не трогаем: пул приложения берёт максимум 20
SQL
sudo systemctl restart postgresql
```
> Тонко подобрать значения можно калькулятором **PGTune** (RAM/ядра/тип нагрузки → готовый блок).

## 4. Код приложения

```bash
# залить репозиторий в /opt/journal (git clone / rsync), ВКЛЮЧАЯ собранный public/admin-dist
sudo chown -R journal:journal /opt/journal
cd /opt/journal
sudo -u journal npm ci --omit=dev      # только runtime-зависимости
```

`.env` в `/opt/journal/.env` (права 600, владелец journal):
```dotenv
NODE_ENV=production                     # включает Secure-флаг на admin-cookie
PORT=3000
DATABASE_URL=postgresql://journal:СИЛЬНЫЙ_ПАРОЛЬ@localhost:5432/journal
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=<из admin-set-password.js>
ADMIN_COOKIE_SECRET=<из admin-set-password.js>
PG_POOL_MAX=20                          # потолок соединений пула (см. services/db.js)
# JOURNAL_SPREADSHEET_ID / STUDENTS_SPREADSHEET_ID — только если будет нужен backfill;
# service-account-key.json класть вне git, если потребуется Sheets (до Phase 5)
```

Применить миграции схемы. **Владелец схемы — Django** (`journal_django/`, `manage.py migrate`).

- **Свежая БД** (чистая установка) — схему создаёт Django:
  ```bash
  cd /opt/journal/journal_django && sudo -u journal .venv/bin/python manage.py migrate
  ```
- **Существующая БД** (наполненная по старому SQL-пути `db/migrations/`) — разовый переход
  владения на Django без выполнения DDL:
  ```bash
  cd /opt/journal/journal_django && sudo -u journal .venv/bin/python manage.py migrate --fake-initial
  ```

> Node-скрипт `npm run db:migrate` (`db/migrations/*.sql`) **устарел** для провижининга
> и оставлен как историческая справка / для обслуживания старых SQL-инсталляций.
> Новые изменения схемы вести только Django-миграциями (`manage.py makemigrations`).

## 5. systemd-сервис для Node

`/etc/systemd/system/journal.service`:
```ini
[Unit]
Description=journal-backend
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=journal
WorkingDirectory=/opt/journal
ExecStart=/usr/bin/node server.js
Restart=always
RestartSec=3
Environment=NODE_ENV=production
# Подстраховка по памяти на 2 ГБ:
MemoryMax=512M

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now journal
sudo systemctl status journal          # должно быть active (running)
curl -s localhost:3000/api/validateToken -X POST -H 'Content-Type: application/json' -d '{"token":"x"}'
# ожидаем {"valid":false,...} — Node живёт и ходит в БД
```

## 6. nginx + gzip + immutable-кэш (пункт №3)

```bash
sudo apt install -y nginx
```

`/etc/nginx/sites-available/journal` (заменить `journal.example.com` и путь):
```nginx
server {
    listen 80;
    server_name journal.example.com;
    # certbot (шаг 7) сам добавит редирект на 443 и TLS-строки

    # --- Сжатие текстовых ответов (бандл ~926 КБ сырыми → ~150 КБ) ---
    gzip on;
    gzip_proxied any;                       # жать и проксированные от Node ответы
    gzip_types text/css application/javascript application/json image/svg+xml;
    gzip_min_length 1024;

    # --- Хэшированные ассеты Vite: кэш навсегда (имена контент-хэшированы) ---
    location /admin/assets/ {
        alias /opt/journal/public/admin-dist/assets/;
        add_header Cache-Control "public, max-age=31536000, immutable";
        access_log off;
    }

    # --- Не отдавать source maps наружу ---
    location ~ \.map$ { deny all; }

    # --- Всё остальное (API + SPA-fallback + teacher SPA) → Node ---
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    client_max_body_size 2m;               # с запасом под JSON-тела
}
```
```bash
sudo ln -s /etc/nginx/sites-available/journal /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 7. TLS (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d journal.example.com   # сам пропишет ssl_certificate + редирект 80→443
sudo certbot renew --dry-run                   # проверка авто-продления
```

## 8. Бэкапы БД

`/etc/cron.daily/journal-pgdump` (chmod +x):
```bash
#!/bin/sh
set -e
DIR=/var/backups/journal; mkdir -p "$DIR"
sudo -u postgres pg_dump journal | gzip > "$DIR/journal-$(date +\%F).sql.gz"
find "$DIR" -name 'journal-*.sql.gz' -mtime +7 -delete   # хранить 7 дней
```

---

## 9. Smoke после деплоя

- [ ] `https://домен/admin` отдаёт SPA (200).
- [ ] Логин в admin SPA реальными кредами работает; неверные → отказ.
- [ ] `curl -I https://домен/admin/assets/index-*.js` → `Content-Encoding: gzip` + `Cache-Control: ...immutable`.
- [ ] Заполнение урока из teacher SPA проходит (по реальному токену).
- [ ] `sudo journalctl -u journal -n 50` — без ошибок.
- [ ] Дашборд открывается, цифры на месте.

## 10. Перед go-live — правки в КОДЕ (из backlog, не в этом runbook)

Это изменения репозитория, делаются отдельно (см. `docs/BACKLOG.md` → Production):
- [ ] CORS whitelist вместо открытого `cors()`.
- [ ] Rate-limit на `POST /api/admin/login` (anti-brute-force).
- [ ] (опц.) Zod-валидация `:id`-параметров (`/students/abc` сейчас → 500).
- [ ] При 2-м управляющем: роли + ограничение дашборда (см. аудит, п.4/5) + `GET /api/admin/me`.

---

## Заметки по эксплуатации

- **Сборка фронта только локально**, на VPS — никогда (память). Деплой нового фронта = `npm run admin:build` локально → залить `public/admin-dist/` → `sudo systemctl reload nginx` (ассеты с новыми хэшами подхватятся, старые кэши не конфликтуют).
- **Память:** Node ~80–150 МБ (лимит 512 МБ в unit), PG ~400–600 МБ кэша, ОС — остальное. На 2 ГБ комфортно.
- **Производительность:** обоснование значений (`PG_POOL_MAX`, индексы, gzip, кэш) и замеры — в `docs/superpowers/specs/2026-06-04-performance-load-audit.md`.
