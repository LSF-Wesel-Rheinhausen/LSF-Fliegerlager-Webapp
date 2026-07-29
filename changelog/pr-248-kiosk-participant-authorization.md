# Auditierte Partner-Vollmachten im Kiosk

## Zusammenfassung

- Ersetzt implizite Teilnehmerzuordnungen über Namen, E-Mail-Adressen oder
  Familienmitglieder durch eine ausdrücklich angenommene Partner-Vollmacht für
  das aktuelle Lager.
- Erlaubt Partnern gegenseitig aktuelle und abgeschlossene Rechnungen,
  Buchungen sowie Anreise- und Abreisedaten des gesamten Haushalts zu
  verwalten.
- Ergänzt die Kiosk-Seite „Partner & Aktivitäten“ mit Vollmachtsverwaltung,
  Partnerabrechnungen und einem unveränderlichen Aktivitätsprotokoll.
- Protokolliert den tatsächlichen Akteur und die betroffene Person, informiert
  das betroffene Partnerkonto und entzieht alle Partnerrechte unmittelbar nach
  einem Widerruf.
- Lässt PIN-, Sicherheits-, Identitäts- und Administrationsfunktionen
  ausdrücklich außerhalb der Partner-Vollmacht.

## Geänderte Dateien

- Kiosk-Autorisierung, Buchungs- und Check-in-Abläufe
- Partner- und Aktivitätsseite samt Menüführung
- Audit-Modell, Migration, Admin-Leseansicht und Benachrichtigungen
- Benutzerhilfe und automatisierte Regressionstests

## Tests

- Regressionstests für Partnerrechnungen, PDF-Autorisierung, Haushalt-
  Buchungen, Check-in, Widerruf, Benachrichtigungen und append-only Audit.
- Negativtests für ausstehende, widerrufene und lagerfremde Verknüpfungen sowie
  unzulässige Vollmachtsverwaltung durch Begleitpersonen.
