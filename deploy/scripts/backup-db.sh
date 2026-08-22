#!/bin/bash
# Ежедневный бэкап прода: PostgreSQL (journal) + хранилище файлов Wiki.
#
# Медиа бэкапится ВМЕСТЕ с базой и тем же запуском намеренно: картинки и
# вложения лежат на диске, а ссылки на них — в базе. Разъедься эти две
# резервные копии во времени, восстановление дало бы документы со ссылками на
# файлы, которых ещё (или уже) нет.
#
# Установка (Beget VPS, Ubuntu 22.04):
#   sudo cp deploy/scripts/backup-db.sh /opt/kotokod/backup-db.sh
#   sudo chmod +x /opt/kotokod/backup-db.sh
#   sudo cp deploy/systemd/journal-db-backup.service /etc/systemd/system/
#   sudo cp deploy/systemd/journal-db-backup.timer /etc/systemd/system/
#   sudo systemctl daemon-reload
#   sudo systemctl enable --now journal-db-backup.timer
#
# Разовый запуск вручную: sudo systemctl start journal-db-backup.service
# Проверка: journalctl -u journal-db-backup -n 50

set -euo pipefail

BACKUP_DIR="/opt/kotokod/backups/postgres"
MEDIA_BACKUP_DIR="/opt/kotokod/backups/media"
# Должно совпадать с KNOWLEDGE_MEDIA_ROOT в .env.
MEDIA_ROOT="/var/www/journal-media"
DB_NAME="journal"
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"
# Скрипт запускается от root (systemd), а pg_dump — от postgres (sudo -u).
# Каталог должен быть доступен postgres на запись.
chown postgres:postgres "$BACKUP_DIR"

STAMP="$(date +%F-%H%M)"
DUMP_FILE="$BACKUP_DIR/journal-$STAMP.dump"

sudo -u postgres pg_dump -Fc -d "$DB_NAME" -f "$DUMP_FILE"
chmod 600 "$DUMP_FILE"

echo "Бэкап создан: $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"

# ---------------------------------------------------------------------------
# Хранилище файлов Wiki (apps/knowledge): картинки и вложения документов.
# ---------------------------------------------------------------------------
# Каталога может не быть — на сервере, где Wiki ещё не поднимали. Это не повод
# ронять бэкап базы, поэтому просто пропускаем.
if [ -d "$MEDIA_ROOT" ]; then
    mkdir -p "$MEDIA_BACKUP_DIR"
    MEDIA_FILE="$MEDIA_BACKUP_DIR/media-$STAMP.tar.gz"
    # Полный архив каждый раз, а не инкрементальный: содержимое адресуется
    # хешем (имя файла = sha256), поэтому файлы не меняются — только
    # добавляются и удаляются. Инкрементальность имела бы смысл от десятков
    # гигабайт, до тех пор она лишь усложняет восстановление.
    #
    # gzip, а не zstd: внутри лежат WebP, JPEG и PDF — уже сжатое, выигрыш от
    # сильного алгоритма единицы процентов, а zstd пришлось бы доставлять на
    # сервер отдельным пакетом.
    tar -C "$(dirname "$MEDIA_ROOT")" -czf "$MEDIA_FILE" "$(basename "$MEDIA_ROOT")"
    chmod 600 "$MEDIA_FILE"
    echo "Бэкап медиа создан: $MEDIA_FILE ($(du -h "$MEDIA_FILE" | cut -f1))"
    find "$MEDIA_BACKUP_DIR" -name 'media-*.tar.gz' -mtime "+$KEEP_DAYS" -print -delete
else
    echo "Каталог $MEDIA_ROOT не найден — медиа не бэкапится (Wiki не развёрнута?)"
fi

# Ротация: удалить дампы старше KEEP_DAYS дней.
find "$BACKUP_DIR" -name 'journal-*.dump' -mtime "+$KEEP_DAYS" -print -delete

echo "Бэкапов в наличии: $(find "$BACKUP_DIR" -name 'journal-*.dump' | wc -l)"
