#!/usr/bin/env bash
set -euo pipefail

port="${PLAYWRIGHT_PORT:-3101}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///tmp/e2e.sqlite3}"
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-127.0.0.1,localhost}"
export DJANGO_DEBUG="${DJANGO_DEBUG:-1}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-test_sk_playwright_local_only}"
export PASSKEY_ENABLED="${PASSKEY_ENABLED:-1}"
export PASSKEY_RP_ID="${PASSKEY_RP_ID:-127.0.0.1}"
export PASSKEY_RP_NAME="${PASSKEY_RP_NAME:-Fliegerlager E2E}"
export PASSKEY_ORIGIN="${PASSKEY_ORIGIN:-http://127.0.0.1:${port}}"

existing_pids="$(lsof -ti "tcp:${port}" || true)"
if [ -n "$existing_pids" ]; then
  kill $existing_pids || true
  sleep 1
  remaining_pids="$(lsof -ti "tcp:${port}" || true)"
  if [ -n "$remaining_pids" ]; then
    kill -9 $remaining_pids || true
  fi
fi

db_path="${DATABASE_URL#sqlite:///}"
mkdir -p "$(dirname "$db_path")"
rm -f "$db_path"

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python"
fi

$PYTHON src/manage.py migrate --noinput
exec $PYTHON src/manage.py runserver "127.0.0.1:${port}" --noreload > "/tmp/django-e2e-${port}.log" 2>&1
