# PR #323 Review-Follow-up

- Invalidiere den `node_modules`-Cache auch bei Änderungen an `package.json`.
- Zeige Hübers in der Essensübersicht einen sichtbaren Einstieg zum Versand von Benachrichtigungen.
- Leite Hübers nach erfolgreichem Benachrichtigungsversand auf die zugängliche Essensübersicht zurück.

## Kiosk-Dienstbuchung

- Offene Dienste können im Kiosk nach Datum und Dienstname gefiltert werden.
- Eine eigene Dienstbuchung kann innerhalb von 15 Minuten zurückgezogen werden.
- Der PWA-Cache wurde für das aktualisierte Kiosk-Stylesheet versioniert.

## Tests

- `tests/test_kiosk_shifts.py`
- `tests/test_pwa.py`
- `tests/test_email_delivery.py`
