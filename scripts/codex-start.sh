#!/usr/bin/env bash
set -euo pipefail

.venv/bin/python src/manage.py migrate
.venv/bin/python src/manage.py runserver 0.0.0.0:8000
