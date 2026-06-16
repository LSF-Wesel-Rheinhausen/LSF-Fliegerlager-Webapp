# Deployment-Update-Diagnose

## Zusammenfassung

- Fehlgeschlagene automatische Updates zeigen den betroffenen Schritt, Exit-Code, stdout und stderr des Compose-Aufrufs.
- Rollback-Fehler werden separat vom ursprünglichen Update-Fehler gespeichert.
- Der Deployment-Status nennt konkrete Recovery-Hinweise mit Logs-Befehl, altem Image und Backup-Datei.

## Geänderte Bereiche

- Deployment-Agent und Update-Statusseite
- Tests für Compose-Fehler, Rollback-Diagnose und Recovery-Ausgabe

## Tests

- `.venv/bin/python -m pytest tests/test_deployment_agent.py tests/test_deployment_updates.py -q`
- `.venv/bin/python src/manage.py check`
- `.venv/bin/python -m ruff check deployment_agent.py tests/test_deployment_agent.py`
- `.venv/bin/python -m mypy deployment_agent.py`
