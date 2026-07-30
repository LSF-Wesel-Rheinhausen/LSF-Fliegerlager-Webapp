# Schnellere und klarere Actions-Pipeline

## Zusammenfassung

Die GitHub-Actions-Pipeline wird in klar erkennbare Qualitäts-, Python-, Browser-, Container- und
Security-Prüfungen gegliedert. Veraltete Pull-Request-Läufe werden abgebrochen und Container erst
nach erfolgreicher CI auf dem aktuellen `main`-Commit veröffentlicht.

## Geänderte Dateien

- GitHub-Actions-Workflows für CI, Container, DAST, Security und Pull-Request-Richtlinien
- Workflow-Dokumentation und Regressionstests für die kritischen Orchestrierungsregeln

## Tests

- `.venv/bin/python -m pytest` (676 bestanden)
- `.venv/bin/python -m pytest tests/test_actions_workflows.py tests/test_zap_configuration.py tests/test_changelog_manifest.py` (12 bestanden)
- `.venv/bin/python -m ruff check .`
- `.venv/bin/python -m ruff format --check .`
- `.venv/bin/python src/manage.py check`
- `.venv/bin/python -m mypy src`
- Playwright: Chromium (32 bestanden), Firefox (31 bestanden, 1 erwarteter Skip) und WebKit im
  gepinnten CI-Container (32 bestanden)
- App- und Updater-Image gebaut und geprüft; Deployment-Konfiguration mit
  `docker compose config --quiet` validiert
- Pre-commit-Hooks für alle geänderten Dateien

## Offene Punkte

- Keine
