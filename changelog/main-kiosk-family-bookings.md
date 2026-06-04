# Kiosk-Familienbuchungen

## Zusammenfassung

- Getränke werden im Kiosk per Mengenpopup mit Schnellwahl und eigener Menge gebucht.
- Kiosk-Teilnehmer können Familienmitglieder anlegen und für diese Essen mitbuchen.
- Bestehende Teilnehmer können sich per Kiosk-Einladung beidseitig für Mitbuchungen verknüpfen.
- Familienmitglieder werden beim eingeloggten Teilnehmer abgerechnet; verknüpfte Teilnehmer behalten ihre eigene Abrechnung.
- Die neuen Kiosk-Dialoge und Listen wurden mit mehr Abstand, größeren Touch-Zielen und besserer mobiler Stapelung überarbeitet.

## Geänderte Dateien

- `src/billing/models.py`
- `src/billing/migrations/0010_participantbookinglink_participantfamilymember_and_more.py`
- `src/billing/forms.py`
- `src/billing/views.py`
- `src/billing/admin.py`
- `src/templates/billing/kiosk_home.html`
- `src/static/billing/app.css`
- `tests/test_kiosk.py`

## Tests

- Bestanden: `.venv/bin/python src/manage.py check`
- Bestanden: `.venv/bin/python src/manage.py makemigrations --check --dry-run`
- Bestanden: `.venv/bin/python -m pytest tests/test_kiosk.py tests/test_forms.py`
- Bestanden: `.venv/bin/python -m pytest tests/test_kiosk.py`
- Bestanden: `.venv/bin/python -m pytest`
- Bestanden: `.venv/bin/ruff check src/billing/models.py src/billing/forms.py src/billing/views.py src/billing/admin.py tests/test_kiosk.py`

## Offene Punkte

- Kein visueller Browserlauf gegen `src/db.sqlite3`, weil dafür eine lokale Migration der tracked SQLite-Datei nötig wäre.
