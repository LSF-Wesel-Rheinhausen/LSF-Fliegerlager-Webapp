# Buchungsnummern

## Zusammenfassung

- Buchungen zeigen eine menschenlesbare Nummer im Format `B#00001`.
- Die Nummer wird aus der stabilen Datenbank-ID der Buchung abgeleitet.
- Die Django-Admin-Übersicht zeigt die Buchungsnummer als eigene Spalte.
- Das Änderungsprotokoll speichert Buchungsnummern in neuen Snapshots.

## Geänderte Dateien

- `README.md`
- `src/billing/admin.py`
- `src/billing/models.py`
- `src/billing/services.py`
- `src/templates/README.md`
- `src/templates/billing/participant_detail.html`
- `tests/e2e/fliegerlager.spec.js`
- `tests/test_booking_audit.py`

## Tests

- Bestanden: `.venv/bin/python src/manage.py check`
- Bestanden: `.venv/bin/python src/manage.py makemigrations --check --dry-run`
- Bestanden: `.venv/bin/python -m pytest tests/test_booking_audit.py -q`
- Bestanden: `.venv/bin/python -m pytest tests/test_booking_audit.py tests/test_view_permissions.py`
- Bestanden: `.venv/bin/python -m pytest`
- Bestanden: `.venv/bin/ruff check .`
- Bestanden: `.venv/bin/ruff format --check .`
- Bestanden: `npm run test:e2e`
- Bestanden: `graphify update .`
