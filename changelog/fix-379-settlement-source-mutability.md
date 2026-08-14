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

- Wird nach der TDD-Implementierung ergänzt.

## Tests

- RED/GREEN für Snapshot-Stabilität und Quellen-Mutabilität.
- Settlement-, PDF-, Kiosk-, Python-, E2E- und PostgreSQL-Prüfungen.

## Offene Punkte

- Implementierung und vollständige Verifikation folgen im Draft-PR.

Closes #379
Refs #394
