# Anwesenheiten im Positionsbericht effizient auswerten

## Zusammenfassung

- Der Positionsbericht verwendet für getrackte Teilnehmer die gültigen Anwesenheitstage.
- Eigene, anwesende Teilnehmerzeilen und die Lagerbeziehung werden in konstant vielen Datenbankabfragen vorgeladen.
- Nicht getrackte Teilnehmer behalten den bisherigen Ist-/Buchungsnächte-Fallback.

## Geänderte Bereiche

- Positionsbericht-Service
- Regressionstests für Anwesenheitsgrenzen, Familienzeilen, Legacy-Fallback und Query-Anzahl

## Tests

- Fokussierte und vollständige Positionsbericht-Pytest-Suite

## Offene Punkte

- Keine.
