#!/bin/bash
# Хранилище файлов Wiki → Selectel S3 (тот же бакет, что у pgBackRest, префикс media/).
#
# База восстанавливается на любую минуту (pgBackRest + WAL), а картинки —
# на момент последней синхронизации. Поэтому синхронизация ежечасная: файлы
# адресуются хешем и только добавляются, rclone докачивает лишь новые, так
# что частый запуск почти ничего не стоит.
#
# sync, а не copy: удалённое локально удаляется и в бакете. От ошибки или
# взлома это не страшно — в бакете включены версионирование и Object Lock,
# старая версия файла остаётся и восстанавливается.
#
# Ключи — в /etc/kotokod/s3-backup.env (root, 600), см. deploy/offsite-backup.md.
#
# Установка:
#   sudo apt install rclone
#   sudo cp deploy/scripts/backup-media-s3.sh /opt/kotokod/backup-media-s3.sh
#   sudo chmod +x /opt/kotokod/backup-media-s3.sh

set -euo pipefail

# Должно совпадать с KNOWLEDGE_MEDIA_ROOT в .env.
MEDIA_ROOT="/var/www/journal-media"
BUCKET="kotokod-backoffice-reserve"

# rclone настраивается переменными окружения: удалённое хранилище «selectel».
export RCLONE_CONFIG_SELECTEL_TYPE=s3
export RCLONE_CONFIG_SELECTEL_PROVIDER=Other
export RCLONE_CONFIG_SELECTEL_ENDPOINT=https://s3.ru-6.storage.selcloud.ru
export RCLONE_CONFIG_SELECTEL_REGION=ru-6
export RCLONE_CONFIG_SELECTEL_FORCE_PATH_STYLE=true
# RCLONE_CONFIG_SELECTEL_ACCESS_KEY_ID / _SECRET_ACCESS_KEY — из EnvironmentFile юнита.

if [ ! -d "$MEDIA_ROOT" ]; then
    echo "Каталог $MEDIA_ROOT не найден — медиа не синхронизируется (Wiki не развёрнута?)"
    exit 0
fi

rclone sync "$MEDIA_ROOT" "selectel:$BUCKET/media" --checksum --stats-one-line -v
