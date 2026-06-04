# Kiosk-Getränkekarten ausrichten

## Zusammenfassung

- Name, Preis und Mengenhinweis in den Kiosk-Getränkekarten werden zentriert ausgerichtet.
- Lange Getränkenamen brechen innerhalb des Buttons um.

## Geänderte Dateien

- `src/static/billing/app.css`

## Tests

- Bestanden: `.venv/bin/python -m pytest tests/test_kiosk.py`
- Bestanden: `npx playwright test tests/e2e/fliegerlager.spec.js -g "Kiosk flow"`

## Offene Punkte

- Keine.
