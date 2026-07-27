# Abstands- und Phasenlayout bereinigt

## Zusammenfassung

- reduziert die Kiosk-Anmeldung und Startseite vor Lagerbeginn auf Name, Countdown und vorbereitende Menüpunkte
- sperrt operative Kiosk-Buchungen sowie direkte Dienst- und Auslagenrouten vor Lagerbeginn serverseitig
- hält empfangene Mitbuchungs-Einladungen im vorbereitenden Menü annehmbar oder ablehnbar
- stabilisiert Kopfzeile, Benachrichtigungseinstellungen und Teilnehmerabrechnung bei unterschiedlichen Viewport-Größen
- entfernt den doppelten Einstieg zur Dienstverwaltung aus der Lagerübersicht

## Geänderte Dateien

- `src/billing/views.py`, `src/billing/pwa_views.py`
- `src/templates/billing/camp_detail.html`, `src/templates/billing/kiosk_home.html`, `src/templates/billing/kiosk_login.html`
- `src/static/billing/app-v8.css`
- zugehörige Pytest-, PWA- und Playwright-Regressionstests

## Tests

- gezielte Pytest-Regressionstests
- gezielte Playwright-Regressionstests für Admin-, Pre-Camp- und Kiosk-Layouts
- vollständige lokale Prüfung vor Veröffentlichung

## Offene Punkte

- keine
