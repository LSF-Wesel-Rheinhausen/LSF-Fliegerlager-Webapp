#!/usr/bin/env sh
set -eu

python -m config.webpush_keys
python manage.py migrate --noinput
python manage.py bootstrap_roles
python manage.py collectstatic --noinput

if [ -n "${KIOSK_ACCESS_TRUSTED_PROXY_ADDRESSES:-}" ]; then
    export GUNICORN_CMD_ARGS="--forwarded-allow-ips=${KIOSK_ACCESS_TRUSTED_PROXY_ADDRESSES} ${GUNICORN_CMD_ARGS:-}"
fi

exec "$@"
