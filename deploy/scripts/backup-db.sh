#!/bin/bash
# Ежедневный бэкап продовой PostgreSQL (journal).
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
DB_NAME="journal"
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"

STAMP="$(date +%F-%H%M)"
DUMP_FILE="$BACKUP_DIR/journal-$STAMP.dump"

sudo -u postgres pg_dump -Fc -d "$DB_NAME" -f "$DUMP_FILE"
chmod 600 "$DUMP_FILE"

echo "Бэкап создан: $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"

# Ротация: удалить дампы старше KEEP_DAYS дней.
find "$BACKUP_DIR" -name 'journal-*.dump' -mtime "+$KEEP_DAYS" -print -delete

echo "Бэкапов в наличии: $(find "$BACKUP_DIR" -name 'journal-*.dump' | wc -l)"
