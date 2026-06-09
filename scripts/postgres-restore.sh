#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
filename="${1:-}"

if [[ -z "$filename" || "$filename" != "$(basename "$filename")" ]]; then
  printf 'Usage: RESTORE_CONFIRM=YES %s <backup-file.sql.gz>\n' "$0" >&2
  exit 2
fi

backup_path="$BACKUP_DIR/$filename"
if [[ ! -f "$backup_path" ]]; then
  printf 'Backup not found: %s\n' "$backup_path" >&2
  exit 2
fi

if [[ "${RESTORE_CONFIRM:-}" != "YES" ]]; then
  printf 'Restore refused. Set RESTORE_CONFIRM=YES after stopping the app container.\n' >&2
  exit 2
fi

gzip -dc "$backup_path" \
  | docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB"'

printf 'Restore completed from: %s\n' "$backup_path"
