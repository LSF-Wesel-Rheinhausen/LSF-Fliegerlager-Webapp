# Manuelle Buchungen aus Preisregeln repariert

## Zusammenfassung

- Manuelle Buchungen im Teilnehmerdetail werden wieder ohne Serverfehler gespeichert.
- Preisregel, Menge und optionale Beschreibung werden serverseitig validiert.
- Preis und Fördersatz werden bei der Erstellung als Snapshot in die Buchung übernommen.
- Archivierte Teilnehmer können keine neuen manuellen Buchungen erhalten.

## Geänderte Dateien

- `src/billing/forms.py`
- `src/billing/services.py`
- `src/billing/views.py`
- `src/templates/billing/participant_detail.html`
- `tests/test_booking_audit.py`
- `tests/e2e/fliegerlager.spec.js`

## Tests

- Backend-Regressionen für erfolgreiche und ungültige manuelle Buchungen.
- Playwright-Regression für den vollständigen Dialog- und Buchungsablauf.
- Vollständige lokale Verifikation mit Ruff, Django, pytest, Playwright und Mypy.

## Offene Punkte

- Die weiteren Audit-Befunde aus Issue #233 bleiben außerhalb dieses PRs offen.
