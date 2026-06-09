#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
filename="fliegerlager-${timestamp}.sql.gz"

mkdir -p "$BACKUP_DIR"
docker compose exec -T db sh -c \
  'pg_dump --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | gzip >"$BACKUP_DIR/$filename"

test -s "$BACKUP_DIR/$filename"
printf 'Backup created: %s\n' "$BACKUP_DIR/$filename"
