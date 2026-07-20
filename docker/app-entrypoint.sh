#!/usr/bin/env sh
set -eu

python -m config.webpush_keys
python manage.py migrate --noinput
python manage.py bootstrap_roles
python manage.py collectstatic --noinput

exec "$@"
