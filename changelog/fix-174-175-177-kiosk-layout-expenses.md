# Kiosk-Layout und Gemeinschaftsausgaben

## Zusammenfassung

- Ordnet die Kiosk-Karten in einem responsiven, progressiv verbesserten Masonry-Grid an.
- Zeigt eigene Gemeinschaftsausgaben als mobile Karten mit priorisierter Statussortierung.
- Stellt Ablehnungsgründe ohne Dialog über ein natives, aufklappbares Detail dar.

## Geänderte Dateien

- `src/billing/views.py`
- `src/static/billing/app.css`
- `src/templates/base.html`
- `src/templates/billing/kiosk_base.html`
- `src/templates/billing/kiosk_home.html`
- `tests/test_kiosk.py`
- `tests/e2e/fliegerlager.spec.js`

## Tests

- Fokussierte Pytest-Regressionstests für Sortierung, Karteninhalte, Belege, Ablehnungsgrund und Leerzustand.
- Playwright-Regressionstest für Desktop/Mobil, Light/Dark, Reflow, Fokusreihenfolge, Overflow und Überlappungen.

## Offene Punkte

- Keine.
