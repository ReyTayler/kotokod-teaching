# Ansible — сервер журнала одной командой

Ansible описывает, каким должен быть сервер журнала, и приводит его к этому
описанию. Запускается **на самом сервере** (зашли по SSH → команда), ничего
ставить на свой компьютер не нужно.

Все команды — от root, из папки плейбука:

```bash
cd /opt/kotokod/journal-backend/deploy/ansible
```

## Что когда запускать

| Задача | Команда |
|---|---|
| Проверить, что сервер совпадает с описанием (ничего не меняет) | `/opt/ansible/bin/ansible-playbook site.yml --check --diff` |
| Привести сервер к описанию | `/opt/ansible/bin/ansible-playbook site.yml` |
| **Авария:** поднять журнал на новом сервере из копий | см. «Новый сервер» ниже, `-e restore=true` |
| Учения: то же на временном сервере, не задевая прод | `-e restore=true -e drill=true` |

Как читать результат (последняя строка `PLAY RECAP`):

- `ok` — уже было как описано;
- `changed` — Ansible это изменил (в `--check` — изменил бы);
- `skipping` — задача не нужна в этом режиме или менять нечего;
- `failed` — ошибка; Ansible остановился, текст ошибки — выше.

`--check` с `changed=0` — сервер совпадает с описанием. Ненулевой `changed` в
`--check` значит, что кто-то правил сервер руками: `--diff` покажет что.

## Новый сервер (авария или учения)

Нужно: чистая Ubuntu 22.04 (от 2 ГБ памяти), SSH root, менеджер паролей.

```bash
# 1. git и код (в коде — сам плейбук)
apt update && apt install -y git
git clone https://github.com/ReyTayler/kotokod-teaching.git /opt/kotokod/journal-backend

# 2. Ansible
bash /opt/kotokod/journal-backend/deploy/scripts/bootstrap-ansible.sh

# 3. Секреты — из менеджера паролей, НЕ новые:
#    .env — запись «KOTOKOD прод .env»:
nano /opt/kotokod/journal-backend/.env
#    ключи S3 и пароль шифрования копий — шаг «Секреты» из
#    deploy/offsite-backup.md; пароль шифрования ВВОДИТЬ сохранённый
#    (read -rsp), а не генерировать: с новым копии не расшифруются.

# 4. Всё остальное (~20–30 минут, из них ~15 — скачивание базы)
cd /opt/kotokod/journal-backend/deploy/ansible
/opt/ansible/bin/ansible-playbook site.yml -e restore=true                 # авария
/opt/ansible/bin/ansible-playbook site.yml -e restore=true -e drill=true   # учения
```

Восстановить на момент времени (например, до ошибочного удаления) — добавить
`-e restore_target="2026-10-12 14:30:00+03"`.

**Только для аварии (не учений), после шага 4.** Первый прогон при аварии
**ожидаемо останавливается** на задаче «Сертификат обязателен»: домен ещё
смотрит на старый сервер. К этому моменту база восстановлена, журнал запущен,
копии в S3 уже включены — не хватает только сайта снаружи.

1. Направить домен на IP нового сервера. DNS сейчас у Beget; если панель
   Beget недоступна — сменить NS-серверы у регистратора домена.
2. Когда домен смотрит на новый IP — выпустить сертификат и включить сайт:
   ```bash
   certbot certonly --nginx -d develop-kotokod.ru   # nginx и certbot уже поставлены
   /opt/ansible/bin/ansible-playbook site.yml
   ```

### Чем учения отличаются от аварии

Временный сервер получает секреты прода, поэтому `drill=true` выключает всё,
что задело бы прод:

- копии и архив WAL — иначе он писал бы в бакет прода;
- Celery beat — иначе рассылал бы Telegram-дайджесты настоящим преподавателям;
- nginx — сертификата боевого домена у него нет.

Проверка журнала на учениях — прямо на сервере, через gunicorn:

```bash
curl -s -H "Host: develop-kotokod.ru" -H "X-Forwarded-Proto: https" \
  --unix-socket /run/journal-django/gunicorn.sock http://localhost/health
```

После учений сервер удалить в панели провайдера.

## Защиты

- `-e restore=true` на сервере, где база журнала уже есть (прод), **ничего не
  делает** и останавливается с сообщением: восстановление затирает базу целиком.
- Повторный прогон после восстановления его не повторяет (метка
  `/var/lib/postgresql/.kotokod-restored`).
- Секреты (`.env`, ключи S3, пароль шифрования) плейбук не создаёт и не
  выводит — только проверяет, что они на месте.
- nginx: новый конфиг проверяется `nginx -t`; не прошёл — прежний
  возвращается, сайт работает дальше.

## Устройство

| Роль | Что описывает |
|---|---|
| `base` | пакеты, пользователь `kotokod`, journald, автообновления |
| `security` | межсетевой экран ufw, fail2ban. SSH не трогает: вход по паролю оставлен намеренно |
| `postgresql` | PostgreSQL 15 (PGDG), роль и база журнала (по `DATABASE_URL` из `.env`) |
| `redis` | Redis только на локальном адресе |
| `restore` | только `-e restore=true`: база и файлы Wiki из S3 |
| `app` | код, Python-окружение, зависимости, папка Wiki, миграции |
| `services` | gunicorn, Celery worker и beat |
| `nginx` | конфиг сайта (шаблон `deploy/nginx/journal-kotokod.conf`), SSL |
| `backup` | pgBackRest, rclone, ночной `pg_dump`, таймеры |

Конфиги роли берут из `deploy/` (systemd, nginx, pgbackrest, scripts) — копий
внутри ролей нет. Переменные — `group_vars/all.yml`. Версии Ansible и
коллекций закреплены: `scripts/bootstrap-ansible.sh`, `requirements.yml`.

Код роль `app` только клонирует на чистый сервер и **не обновляет** — выкатка
новой версии отдельная.
