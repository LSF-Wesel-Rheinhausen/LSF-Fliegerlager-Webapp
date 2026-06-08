# Kiosk-Buchungen mit Legacy-Datenbanken reparieren

## Zusammenfassung

- Entfernt verwaiste Stornospalten aus einer früheren, konkurrierenden Migration.
- Überführt vorhandene Legacy-Stornierungen vor der Bereinigung in das aktuelle Soft-Delete-Modell.
- Verhindert `NOT NULL`-Fehler beim Anlegen neuer Getränke- und Essensbuchungen.

## Geänderte Dateien

- `src/billing/migrations/0013_remove_legacy_charge_cancellation_columns.py`
- `tests/test_migrations.py`

## Tests

- Migration einer Datenbank mit Legacy-Spalten und Stornodaten.
- Idempotenter Durchlauf auf einem aktuellen Schema.
- Kiosk- und vollständige Testsuite.

## Offene Punkte

- Keine.
