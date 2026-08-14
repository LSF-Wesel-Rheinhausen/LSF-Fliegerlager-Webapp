# Settlement-Snapshots von veränderbaren Quelldaten trennen

## Zusammenfassung

- Korrigiert die in #394 eingeführte globale Schreibsperre für Charges, die in
  einem früheren SettlementRun-Snapshot vorkommen.
- Bewahrt SettlementRun-, Settlement- und SettlementLine-Snapshots unverändert,
  während spätere zulässige Änderungen an Charge-, MealSignup- und
  Buchungsquelldaten möglich bleiben.
- Stellt sicher, dass spätere SettlementRuns den dann aktuellen Quellenstand
  versioniert abbilden.

## Geänderte Dateien

- `src/billing/services.py`: Entfernt die globale Snapshot-Mitgliedschaftssperre
  aus dem Essenspreis-Resync; bestehende Zeit-, Archiv- und Soft-Delete-Regeln
  bleiben erhalten.
- `src/billing/views.py`: Entfernt dieselbe fachlich falsche Sperre aus
  Schnellstorno und Essensrücknahme.
- `tests/test_foerdersatz_update_sync.py`: Prüft Admin-Resync, unveränderte
  Run-/Settlement-/Line-Daten und PDF-Bytes sowie eine spätere Abrechnungsversion.
- `tests/test_kiosk.py`: Prüft mutable Quellen nach früherem Snapshot und die
  weiterhin wirksamen Catering-, Zeit- und Berechtigungsregeln.

## Tests

- RED: Drei gezielte Regressionstests scheiterten an Resync-, Storno- und
  Rücknahmeblockaden.
- GREEN: 283 Settlement-, PDF-, Fördersatz-, Kiosk- und Partnerfälle bestehen.
- Vollständige Python-Suite: 1.075 bestanden, 3 PostgreSQL-only lokal
  übersprungen.
- Vollständige E2E-Suite: 227 bestanden, 1 übersprungen; Ruff, Format,
  Django check und mypy bestehen.
- Der echte PostgreSQL-Concurrency-Lauf folgt im dedizierten CI-Job.

## Offene Punkte

- Remote-CI und Review-Kommentare werden nach dem finalen Push überwacht.

Closes #379
Refs #394
