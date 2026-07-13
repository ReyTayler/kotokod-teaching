# Инструкция администратора — journal-backend в проде

> Актуально с 2026-07-13 (первый реальный деплой на Beget VPS, домен `develop-kotokod.ru`).
> **Секретов (IP, пароли, ключи) в этом файле нет намеренно** — файл лежит в git и виден
> всей истории репозитория. Реквизиты доступа — в твоём менеджере паролей / там, где их
> сохранил себе после деплоя. Если потерял — спроси у ассистента в новой сессии, он найдёт
> их в `.env` на сервере (сам файл секретов не публикует).

## 1. Архитектура одной картинкой

```
Браузер ──HTTPS──▶ nginx (TLS, статика, security-заголовки, rate-limit)
                     │
                     ├─▶ /admin/*, /teacher/*, /login/* ──▶ файлы с диска (SPA)
                     │
                     └─▶ /api/*, /health ──▶ gunicorn (unix-сокет) ──▶ Django
                                                                          │
                                                                          ├─▶ PostgreSQL (localhost:5432)
                                                                          └─▶ Redis (кэш + очередь Celery)
                                                                                │
                                                                     Celery worker/beat (фон: OTP-письма, прогрев кэша)
```

На этом же VPS отдельно живёт **Telegram-бот** (`kotocode-bot.service`, свой пользователь
`kotocode`, свой venv) — не пересекается с journal-backend, трогать не нужно.

## 2. Где что лежит на сервере

| Что | Где |
|---|---|
| Код (git-репозиторий) | `/opt/kotokod/journal-backend` |
| Секреты (`.env`) | `/opt/kotokod/journal-backend/.env` (chmod 600, владелец `kotokod`) |
| venv | `/opt/kotokod/journal-backend/journal_django/.venv` |
| Бэкапы БД | `/opt/kotokod/backups/postgres/` (хранятся 14 дней) |
| SSL-сертификат | `/etc/letsencrypt/live/develop-kotokod.ru/` (авто-продление certbot) |
| nginx site-config | `/etc/nginx/sites-available/journal-kotokod` |
| Сервисный пользователь приложения | `kotokod` (группа `www-data`) |

systemd-юниты (источник истины — `deploy/systemd/*` в репозитории, на сервере лежат копии
в `/etc/systemd/system/`):

| Юнит | Что делает |
|---|---|
| `journal-django.service` | gunicorn (веб-приложение) |
| `journal-celery-worker.service` | фоновые задачи (OTP-письма, прогрев кэша) |
| `journal-celery-beat.service` | планировщик — раз в 60с ставит задачи прогрева кэша |
| `journal-db-backup.service` + `.timer` | ежедневный бэкап БД в 03:00 МСК |

## 3. Доступ к серверу

- SSH по ключу (пароль отключать не пришлось — root/sudo-доступ по паролю остаётся
  запасным, но ключ настроен для повседневной работы). Реквизиты — в своём менеджере
  паролей.
- Доступ к БД для просмотра/правки данных (pgAdmin) — через SSH-туннель, БД наружу не
  торчит (порт 5432 закрыт в `ufw`, `pg_hba.conf` разрешает только `localhost`). Инструкция
  по настройке pgAdmin — см. историю переписки с ассистентом (или спроси заново, это
  стандартная процедура: SSH-туннель `-L <локальный-порт>:localhost:5432` + подключение
  pgAdmin к `localhost:<порт>`).

## 4. Повседневные операции

### 4.1. Проверить, что всё живо

```bash
systemctl status journal-django nginx postgresql redis-server journal-celery-worker journal-celery-beat
curl -s https://develop-kotokod.ru/health   # ожидаем {"status":"ok","db":"ok"}
```

### 4.2. Посмотреть логи

```bash
journalctl -u journal-django -f              # веб-приложение (сюда же трейсбэки 500-ошибок)
journalctl -u journal-celery-worker -f       # фоновые задачи (OTP-письма и т.п.)
journalctl -u journal-celery-beat -f         # планировщик (раз в 60с должны быть тики)
tail -f /var/log/nginx/error.log
tail -f /var/log/nginx/access.log
```

### 4.3. Задеплоить новую версию кода

```bash
cd /opt/kotokod/journal-backend
sudo -u kotokod git pull --ff-only origin main

# если менялся requirements.txt:
sudo -u kotokod journal_django/.venv/bin/pip install -r journal_django/requirements.txt

# если появились новые Django-миграции:
cd journal_django
sudo -u kotokod env DJANGO_SETTINGS_MODULE=config.settings.production TZ=Europe/Moscow \
  .venv/bin/python manage.py migrate

# перезапустить веб-приложение (подхватывает новый код):
sudo systemctl restart journal-django

# если менялся код celery-задач:
sudo systemctl restart journal-celery-worker journal-celery-beat

# если менялся nginx-конфиг (deploy/nginx/journal-kotokod.conf или snippets/journal-static.conf):
sudo cp /opt/kotokod/journal-backend/deploy/nginx/journal-kotokod.conf /etc/nginx/sites-available/journal-kotokod
# в скопированном файле server_name уже develop-kotokod.ru — если в репо остались
# плейсхолдеры example.kotokod.ru, заменить их перед копированием
sudo cp /opt/kotokod/journal-backend/deploy/nginx/snippets/journal-static.conf /etc/nginx/snippets/journal-static.conf
sudo nginx -t && sudo systemctl reload nginx

# если менялся фронт (admin-src/teacher-src) — собрать ЛОКАЛЬНО (не на VPS, мало памяти для vite),
# закоммитить собранные admin-dist/teacher-dist, затем на сервере просто git pull (без rebuild).
```

⚠️ **Никогда не редактировать конфиги (`/etc/nginx/...`, `/etc/systemd/system/...`)
напрямую на сервере без переноса той же правки в `deploy/` в репозитории** — иначе при
следующем деплое (`cp` из репо) правка молча потеряется.

### 4.4. Резервные копии БД

- Работают автоматически: каждый день в 03:00 МСК → `/opt/kotokod/backups/postgres/`,
  хранятся 14 дней (старые удаляются автоматически).
- Проверить, что таймер жив:
  ```bash
  systemctl list-timers journal-db-backup.timer
  ls -la /opt/kotokod/backups/postgres/
  ```
- Запустить бэкап вручную (например, перед рискованной операцией):
  ```bash
  sudo systemctl start journal-db-backup.service
  journalctl -u journal-db-backup -n 10
  ```
- Скачать дамп к себе на машину:
  ```bash
  scp kotokod-vps:/opt/kotokod/backups/postgres/journal-ДАТА.dump ./
  ```
- **Восстановить из дампа** (⚠️ затирает текущие данные в таблицах — сначала свежий
  бэкап-подстраховка, см. выше):
  ```bash
  sudo -u postgres pg_restore -d journal --clean --if-exists /opt/kotokod/backups/postgres/journal-ДАТА.dump
  ```

### 4.5. Просмотр/правка данных в БД

Через pgAdmin (или любой другой GUI-клиент/psql) по SSH-туннелю — БД в интернет не
выставлена намеренно (там ПДн учеников). См. раздел 3.

⚠️ Подключение идёт под тем же пользователем `journal`, под которым работает само
приложение — полные права на запись. Случайный `UPDATE`/`DELETE` в GUI-клиенте уйдёт
прямо в боевые данные. Если нужна read-only роль для безопасного просмотра — попроси
завести отдельно.

### 4.6. SSL-сертификат

Продлевается автоматически (`certbot.timer`, сертификат Let's Encrypt живёт 90 дней,
certbot продлевает заранее). Проверить:

```bash
systemctl list-timers | grep certbot
sudo certbot renew --dry-run     # тестовый прогон без реальной замены сертификата
sudo certbot certificates        # срок действия текущего сертификата
```

## 5. Мониторинг ресурсов

```bash
free -h                          # память
df -h /                          # диск
systemctl status journal-django journal-celery-worker journal-celery-beat  # CPU/Memory в выводе
redis-cli info memory | grep used_memory_human
journalctl --disk-usage          # сколько места съели логи systemd
```

Если логи systemd разрослись — `sudo journalctl --vacuum-time=30d` (оставит только
последние 30 дней).

## 6. Типичные проблемы

**Сайт не открывается / 502 Bad Gateway**
```bash
systemctl status journal-django          # жив ли gunicorn
journalctl -u journal-django -n 50       # трейсбэк ошибки
sudo nginx -t                            # валиден ли nginx-конфиг
ls -la /run/journal-django/gunicorn.sock # существует ли unix-сокет
```

**500-ошибка при логине / любом API-запросе**
```bash
journalctl -u journal-django -n 80 --no-pager | grep -A 30 Traceback
```
Частые причины: не хватает переменной в `.env`, не накатана свежая миграция, Redis
недоступен (не должно валить приложение — есть graceful fallback, но стоит проверить
`systemctl status redis-server`).

**Не приходит письмо с кодом (2FA / вход)**
Отправка письма теперь идёт через Celery (очередь `interactive`), не синхронно из
запроса — смотреть в логах воркера, не веб-приложения:
```bash
journalctl -u journal-celery-worker -f
```
Проверить SMTP-настройки в `.env` (`SMTP_HOST/PORT/USER/PASS`).

**Диск заполняется**
```bash
df -h /
du -sh /opt/kotokod/backups/postgres/*   # бэкапы (ротация 14 дней должна ограничивать)
journalctl --disk-usage                  # логи
```

## 7. Чего НЕ делать

- Не коммитить `.env`, дампы БД, ключи, пароли — `.gitignore` уже это перекрывает,
  но при `git add -A` всё равно смотреть, что попадает в коммит.
- Не открывать порт PostgreSQL (5432) наружу через `ufw` — доступ только через
  SSH-туннель.
- Не запускать `npm run build` (vite) прямо на VPS — фронт собирается локально,
  готовые `admin-dist`/`teacher-dist` коммитятся в репозиторий.
- Не редактировать `/etc/nginx/...` и `/etc/systemd/system/...` напрямую без переноса
  правки в `deploy/` (см. раздел 4.3).
- Не запускать деструктивные SQL-команды (`TRUNCATE`, `DROP`, массовый `DELETE`) без
  свежего бэкапа под рукой (раздел 4.4).

## 8. Дальнейшее чтение

- `deploy/README.md` — исходный runbook перехода Express→Django (историческая часть,
  но описывает Redis/Celery-опции и общую структуру `deploy/`).
- `CLAUDE.md` — общие правила и инварианты проекта.
- `docs/security-guidelines.md` — чеклист безопасности перед добавлением новых фич.
- `docs/deploy-runbook.md` — **УСТАРЕЛ**, описывает деплой старого Node/Express-бэкенда
  (снесён 2026-06-11). Не использовать, оставлен как историческая справка.
