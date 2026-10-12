# Резервные копии вне Beget (Selectel S3)

Зачем: ночной `pg_dump` (`deploy/scripts/backup-db.sh`) лежит на том же VPS и
погибнет вместе с ним. Здесь — копии в другом городе.

| Что | Куда | Как часто | Сколько потеряем при гибели VPS |
|---|---|---|---|
| PostgreSQL | `s3://kotokod-backoffice-reserve/pgbackrest/` | полная — вс, разностная — пн–сб, WAL — непрерывно | ≤ 1 минута (`archive_timeout`) |
| Файлы Wiki | `s3://kotokod-backoffice-reserve/media/` | ежечасно | ≤ 1 час |

Хранилище: Selectel S3, пул **ru-6** (Москва, мультизональный), endpoint
`s3.ru-6.storage.selcloud.ru`. VPS — Beget, Санкт-Петербург. В бакете включены
версионирование и Object Lock: ключи с сервера удалить старые версии не могут.

Копии зашифрованы pgBackRest (AES-256) **до отправки**. Без пароля шифрования
(`repo1-cipher-pass`) их не расшифровать никому — он хранится в менеджере
паролей владельца, запись «Ключ шифрования бэкапов».

Ночной `pg_dump` остаётся как вторая, независимая копия на сервере.

## Установка (один раз)

### 1. Пакеты

```bash
sudo apt update
sudo apt install pgbackrest rclone   # pgbackrest — из репозитория PGDG, ≥ 2.54
```

### 2. Секреты (вводит владелец, не через чат)

S3-ключи — от сервисного пользователя Selectel `kotokod-backup` (роль
`s3.bucket.user`, доступ к бакету — политикой бакета). Ключи вводятся скрытно и
не попадают в историю shell. Пароль шифрования генерируется на месте и
печатается ОДИН раз — сразу в менеджер паролей.

```bash
sudo install -d -m 750 -o root -g postgres /etc/pgbackrest/conf.d
sudo install -d -m 700 -o root -g root /etc/kotokod
read -rp 'Access Key ID: ' AK; read -rsp 'Secret Access Key: ' SK; echo
CP="$(openssl rand -base64 48 | tr -d '\n')"
printf '[global]\nrepo1-s3-key=%s\nrepo1-s3-key-secret=%s\nrepo1-cipher-pass=%s\n' "$AK" "$SK" "$CP" \
  | sudo tee /etc/pgbackrest/conf.d/secrets.conf >/dev/null
sudo chown root:postgres /etc/pgbackrest/conf.d/secrets.conf
sudo chmod 640 /etc/pgbackrest/conf.d/secrets.conf
printf 'RCLONE_CONFIG_SELECTEL_ACCESS_KEY_ID=%s\nRCLONE_CONFIG_SELECTEL_SECRET_ACCESS_KEY=%s\n' "$AK" "$SK" \
  | sudo tee /etc/kotokod/s3-backup.env >/dev/null
sudo chmod 600 /etc/kotokod/s3-backup.env
echo; echo "ПАРОЛЬ ШИФРОВАНИЯ — сохранить в менеджер паролей:"; echo "$CP"; echo
unset AK SK CP
```

### 3. Конфиги и юниты

```bash
cd /opt/kotokod/journal-backend
sudo cp deploy/pgbackrest/pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
sudo cp deploy/pgbackrest/postgresql-archive.conf /etc/postgresql/15/main/conf.d/pgbackrest.conf
sudo cp deploy/scripts/backup-media-s3.sh /opt/kotokod/backup-media-s3.sh
sudo chmod +x /opt/kotokod/backup-media-s3.sh
sudo cp deploy/systemd/journal-pgbackrest@.service \
        deploy/systemd/journal-pgbackrest-full.timer \
        deploy/systemd/journal-pgbackrest-diff.timer \
        deploy/systemd/journal-media-s3.service \
        deploy/systemd/journal-media-s3.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

### 4. Включить архив WAL — РЕСТАРТ PostgreSQL

`archive_mode` меняется только рестартом: журнал недоступен несколько секунд.
Делать вне занятий.

```bash
sudo -u postgres pgbackrest --stanza=journal stanza-create
sudo systemctl restart postgresql
sudo -u postgres pgbackrest --stanza=journal check     # WAL реально уходит в S3
```

### 5. Первая полная копия и таймеры

```bash
sudo systemctl start journal-pgbackrest@full.service
sudo systemctl start journal-media-s3.service
sudo -u postgres pgbackrest --stanza=journal info
sudo systemctl enable --now journal-pgbackrest-full.timer journal-pgbackrest-diff.timer journal-media-s3.timer
```

## Проверка, что всё живо

```bash
sudo -u postgres pgbackrest --stanza=journal info     # список копий и диапазон WAL
sudo -u postgres psql -c "select last_archived_time, last_failed_time from pg_stat_archiver"
systemctl list-timers 'journal-*'
journalctl -u 'journal-pgbackrest@*' -u journal-media-s3 -n 50
```

`last_failed_time` новее `last_archived_time` — WAL не уходит. Это опасно не
только для копий: неотправленный WAL копится в `pg_wal` и может заполнить диск.

## Восстановление на НОВОМ сервере (Beget пропал)

**Основной путь — Ansible:** `deploy/ansible/README.md`, раздел «Новый
сервер» (`site.yml -e restore=true`) — те же шаги ниже, но одной командой и с
защитой от восстановления поверх живой базы. Ручной путь — запасной, если
Ansible почему-то не поднимается:

1. Чистая Ubuntu 22.04. PostgreSQL 15 и pgBackRest — из репозитория PGDG
   (apt.postgresql.org), тот же мажор 15.
2. Шаги 1–3 установки выше. В шаге 2 пароль шифрования **не генерировать**,
   а вписать сохранённый из менеджера паролей (вместо `CP="$(openssl ...)"` —
   `read -rsp 'Пароль шифрования: ' CP`). Сгенерируете новый — старые копии
   не расшифруются.
3. Восстановить базу:

   ```bash
   sudo systemctl stop postgresql
   sudo -u postgres pgbackrest --stanza=journal --delta restore
   # На конкретный момент (например, до ошибочного удаления):
   #   ... --delta --type=time --target="2026-10-12 14:30:00+03" --target-action=promote restore
   sudo systemctl start postgresql
   ```

4. Файлы Wiki:

   ```bash
   sudo mkdir -p /var/www/journal-media
   sudo env $(sudo cat /etc/kotokod/s3-backup.env | xargs) \
     RCLONE_CONFIG_SELECTEL_TYPE=s3 RCLONE_CONFIG_SELECTEL_PROVIDER=Other \
     RCLONE_CONFIG_SELECTEL_ENDPOINT=https://s3.ru-6.storage.selcloud.ru \
     RCLONE_CONFIG_SELECTEL_REGION=ru-6 RCLONE_CONFIG_SELECTEL_FORCE_PATH_STYLE=true \
     rclone sync selectel:kotokod-backoffice-reserve/media /var/www/journal-media
   ```

5. Остальное (код, `.env` из менеджера паролей, nginx, systemd, SSL) — по
   `deploy/README.md`. Домен перевести на новый IP. DNS сейчас у Beget: если
   панель Beget недоступна, менять NS-серверы у регистратора домена.

## Учения

Раз в квартал: восстановить последнюю копию на чистой машине и засечь время.
Копия, из которой ни разу не восстанавливались, ничего не гарантирует.
