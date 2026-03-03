#!/bin/bash

set -euo pipefail

PROJECT_DIR="${HOME}/sports-bot"
DB_PATH="${PROJECT_DIR}/sports_bot.db"
BACKUP_DIR="${PROJECT_DIR}/backups"
BACKUP_NAME="sports_bot_$(date +%F).db"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"

mkdir -p "${BACKUP_DIR}"

if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "sqlite3 не найден в PATH" >&2
    exit 1
fi

if [ ! -f "${DB_PATH}" ]; then
    echo "Файл БД не найден: ${DB_PATH}" >&2
    exit 1
fi

sqlite3 "${DB_PATH}" ".backup '${BACKUP_PATH}'"

mapfile -t old_backups < <(find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'sports_bot_*.db' | sort -r | tail -n +8)
for backup in "${old_backups[@]}"; do
    rm -f "${backup}"
done

echo "Backup создан: ${BACKUP_PATH}"
