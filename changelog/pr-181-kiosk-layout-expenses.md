# Kiosk-Layout und Gemeinschaftsausgaben

## Zusammenfassung

- Ordnet die Kiosk-Karten in einem responsiven, progressiv verbesserten Masonry-Grid an.
- Zeigt eigene Gemeinschaftsausgaben als mobile Karten mit priorisierter Statussortierung.
- Stellt Ablehnungsgründe ohne Dialog über ein natives, aufklappbares Detail dar.
- Entfernt die redundante Buchungsliste unter dem Essenskalender; Tagesdetails bleiben im Kalender erreichbar.

## Geänderte Dateien

- `src/billing/views.py`
- `src/static/billing/app.css`
- `src/templates/base.html`
- `src/templates/billing/kiosk_base.html`
- `src/templates/billing/kiosk_home.html`
- `tests/test_kiosk.py`
- `tests/e2e/fliegerlager.spec.js`

## Tests

- Fokussierte Pytest-Regressionstests für Sortierung, Karteninhalte, Belege, Ablehnungsgrund, Leerzustand und die entfallene redundante Buchungsliste.
- Playwright-Regressionstest für Desktop/Mobil, Light/Dark, Reflow, Fokusreihenfolge, Overflow und Überlappungen.

## Offene Punkte

- Keine.
