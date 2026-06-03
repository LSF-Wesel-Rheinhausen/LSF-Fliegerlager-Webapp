# Buchungen löschen

## Zusammenfassung

- Admins können Buchungen direkt aus der Teilnehmerdetailseite löschen.
- Löschungen werden mit Vorher-Snapshot im Änderungsprotokoll protokolliert.
- Änderungsprotokolleinträge bleiben auch nach gelöschten Buchungen erhalten.
- Das Protokoll heißt jetzt Änderungsprotokoll.
- Admins können gelöschte Buchungen aus dem Änderungsprotokoll wiederherstellen.

## Geänderte Dateien

- `README.md`
- `src/billing/admin.py`
- `src/billing/models.py`
- `src/billing/services.py`
- `src/billing/views.py`
- `src/billing/urls.py`
- `src/templates/billing/participant_detail.html`
- `src/templates/README.md`
- `src/static/billing/app.css`
- `src/billing/migrations/0008_preserve_deleted_booking_audit_logs.py`
- `tests/test_booking_audit.py`
- `tests/test_view_permissions.py`
- `tests/README.md`
- `tests/e2e/README.md`
- `tests/e2e/fliegerlager.spec.js`

## Tests

- Bestanden: `.venv/bin/python src/manage.py check`
- Bestanden: `.venv/bin/python -m pytest tests/test_booking_audit.py tests/test_view_permissions.py`
- Bestanden: `.venv/bin/python -m pytest`
- Bestanden: `.venv/bin/ruff check .`
- Bestanden: `.venv/bin/ruff format --check .`
- Bestanden: `.venv/bin/python src/manage.py makemigrations --check --dry-run`
- Bestanden: `npm run test:e2e`
- Bestanden: `graphify update .`
