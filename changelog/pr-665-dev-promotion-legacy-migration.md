# Legacy Dev-Pointer-Migration

## Zusammenfassung

Ergänzt einen expliziten, begrenzten `workflow_dispatch`-Pfad zur Migration des
bekannten unannotierten GHCR-Dev-Pointer-Paars. Normale Dev-Promotionen bleiben
provenance-strikt und melden fehlende oder ungültige Workflow-Run-Annotationen
mit genauer Referenz.

## Geänderte Dateien

- `.github/workflows/docker.yml`
- `.github/workflows/README.md`
- `scripts/migrate-legacy-dev-pointers.sh`
- `tests/test_release_build.py`

## Tests

- Bestanden: `tests/test_dev_promotion_migration.py`, `tests/test_release_build.py`
  und `tests/test_workflow_action_pins.py` (87 Tests).
- Bestanden: 2.299 Python- und Migrationstests (19 übersprungen), Ruff, Formatierung, Django, Migrationsabgleich und mypy.
- Bestanden: `bash -n scripts/migrate-legacy-dev-pointers.sh`.

## Offene Punkte

- Die Migration wurde nicht ausgelöst; sie benötigt nach Review und Merge einen
  ausdrücklich gestarteten Dispatch auf `main` mit aktuellem erfolgreichem
  Tests-Run.
- GHCR bietet keinen atomaren Compare-and-swap für das App-/Updater-Paar.
  Derselbe Concurrency-Key serialisiert Repository-Workflows; externe
  Registry-Schreiber bleiben eine Betriebsannahme.

## Getrennte Workflow-Ausführung

Die manuelle Migration liegt in `dev-migration.yml`, getrennt von PR- und
`workflow_run`-Builds. Die Docker-Jobs nutzen keinen gespeicherten pip-Cache mehr,
um Cache-Poisoning über ausgeführten PR-Code zu verhindern. Die Prüfungen,
Berechtigungen, der Checkout von `main` und die gemeinsame Parallelitätssperre
der Migration bleiben erhalten. Regressionstests sichern die getrennten Trigger
und den Verzicht auf den pip-Cache ab.
