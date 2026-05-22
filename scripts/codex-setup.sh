#!/usr/bin/env bash
set -euo pipefail

python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
npm install
