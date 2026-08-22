# Issue #486: Zielbuchungen im Positionsbericht kanonisieren

- Der Positionsbericht fasst direkte Buchungen und für Familienmitglieder oder Partner erfasste Buchungen unter derselben Artikelbeschreibung zusammen, ohne Ledger-Beschreibungen zu verändern.
- Maschinell erzeugte Quick- und Meal-Buchungen speichern ihre kanonische Berichtsbezeichnung dauerhaft; der Bericht verwendet sie und fällt bei Altbestand auf `description` zurück.
- Natürliche und manuelle Beschreibungen mit `für` bleiben erhalten; die Query-Anzahl bleibt bei wachsender Lagergröße konstant.
- RED: Direkte, Familien- und Partnerbuchungen wurden vor dem Fix als drei Artikelzeilen ausgewiesen.
- GREEN: Aggregation, Summen, Nichtmutation, Sicherheitsfall und Query-Bound sind durch fokussierte Regressionstests abgedeckt.
- Closes #493: Manuelle Familien-Charges ohne maschinell gespeicherte Berichtsbezeichnung behalten Texte wie `Spende für <Familienname>` unverändert.
- Closes #492: Die persistierte Basis bleibt bei späteren Umbenennungen der Zielperson stabil. Basisartikel mit eigenem ` für ` sowie leere oder malformed finale Trennsegmente bleiben korrekt erhalten.
- Closes #494: Die String-Heuristik im Positionsbericht wurde durch das optionale Feld `position_report_description` ersetzt.
- Explizite Admin-Änderungen an `description` verwerfen eine zuvor gespeicherte kanonische Bezeichnung. Partner-Mahlzeiten mit natürlichem `für` behalten ihre vollständige fachliche Beschreibung.
- Eine idempotente Datenmigration übernimmt nur durch Kiosk-Provenienz, Zielrelation und eindeutige aktuelle oder auditierte Zielnamen belegte historische Basen; mehrdeutige Fälle bleiben `NULL`.
- Restrisiko: Bei Altbestand, dessen Kiosk-Provenienz oder Zielrelation bereits vor der Migration durch `SET_NULL` verloren ging, bleibt das Feld bewusst `NULL` und der Bericht verwendet die unveränderte Ledger-Beschreibung.
- Closes #495: Zielnamen mit eigenem ` für `, etwa `Hans für Müller`, bleiben vollständig in der Ledgerbeschreibung, während Quick-/Family-Buchungen ausschließlich unter ihrer explizit gespeicherten Basis aggregieren.
- Beim Backfill haben passende unveränderliche Audit-Namenssnapshots Vorrang vor späteren aktuellen Namen; mehrere passende Snapshots bleiben als mehrdeutige Evidenz bewusst `NULL`.
- Closes #496: Historische eigene Familien-Mahlzeiten ohne Kiosk-Audit werden nur bei genau einer verknüpften `MealSignup` mit exakt übereinstimmender Teilnehmer- und Familienrelation kanonisiert.
- Fehlende, widersprüchliche oder mehrfache MealSignup-Zuordnungen sowie umbenannte Ziele ohne historischen Namenssnapshot bleiben beim Backfill bewusst `NULL`.
- Closes #497: Ändert ein Superuser die Charge-Beschreibung über den Django-Admin, wird eine alte kanonische Berichtsbezeichnung vor dem Speichern verworfen; Änderungen anderer Felder erhalten sie.
- Closes #498: Migration 0068 verarbeitet eligible Charges per PK-Keyset in festen Batches und lädt Audit-/MealSignup-Provenienz nur für die Charge-IDs des aktuellen Batches.
