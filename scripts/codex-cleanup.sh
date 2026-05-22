#!/usr/bin/env bash
set -euo pipefail

rm -rf .pytest_cache .test-local-logs htmlcov playwright-report test-results tmp
find . -type d -name __pycache__ -prune -exec rm -rf {} +
find . -type f -name '*.pyc' -delete
