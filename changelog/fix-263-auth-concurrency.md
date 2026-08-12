# PR 2: F-02/F-06 Authentifizierungs-Concurrency

## Zusammenfassung

- Serialisiere die First-Admin-Ersteinrichtung über einen migrationsgesicherten PostgreSQL-kompatiblen Lock-Datensatz
  und prüfe die Benutzertabelle innerhalb derselben Transaktion erneut.
- Stelle den Bootstrap-Lock nach einem Daten-Reset mit erhaltener Migrationshistorie atomar wieder her.
- Aktualisiere Teilnehmer- und Familien-PIN-Fehlversuchszähler unter `select_for_update()` atomar.
- Ergänze deterministische Regressionstests sowie einen PostgreSQL-16-CI-Job mit getrennten Verbindungen.

## Tests

- RED/GREEN-Regressionstests für den First-Admin-Race und stale PIN-Instanzen.
- Lokale Auth-/Kiosk-/Concurrency-Suite: erfolgreich; PostgreSQL-Concurrency-Tests werden ohne lokale PostgreSQL-Instanz übersprungen.
- Der Remote-PostgreSQL-Job führt die echten Zwei-Verbindungen-Szenarien aus.
