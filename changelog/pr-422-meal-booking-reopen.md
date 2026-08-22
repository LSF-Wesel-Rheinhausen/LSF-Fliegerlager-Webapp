# Essensbuchung nach Stichzeitpunkt wieder öffnen

## Zusammenfassung

Meal Manager können den Buchungsstatus je Lager, Tag und Mahlzeit dauerhaft öffnen
oder schließen. Eine manuelle Öffnung überstimmt den automatischen Stichzeitpunkt;
gesendete Caterer-Bestellungen bleiben davon getrennt und können reversibel als
nicht bestellt markiert werden.

## Geänderte Bereiche

- Persistenter, auditierbarer Status für Mahlzeit-Slots und reversibler Bestellmarker.
- Zentrale Statusauflösung für Kiosk, Übersicht und Benachrichtigungen.
- Server-seitige, CSRF-geschützte Meal-Manager-Steuerung ohne JavaScript.

## Tests

- Cutoff-Grenzen, manuelle Öffnung/Schließung, Isolation, CSRF, ungültige Daten und
  wiederholte POSTs.
- Bestehende Kiosk-, Preorder-, Übersichts- und Berechtigungstests.
