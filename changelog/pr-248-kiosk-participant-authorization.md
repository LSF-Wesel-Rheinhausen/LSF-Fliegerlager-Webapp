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
- Prüft Schnellbuchungs-Preisregeln für jede ausgewählte Person separat und
  verwendet bei Snacks den passenden Kinder-, Begleit- oder Erwachsenenpreis.
- Hält Audittexte frei von Personennamen und verhindert das Löschen eines
  Lagers, solange dessen Partner-Auditverlauf besteht.
- Lädt Partnerhaushalte einmalig für Buchungs- und Check-in-Ziele und weist
  offene Einladungen archivierter Teilnehmer ab.
- Widerruft bereits vor dieser Änderung offene oder angenommene
  Mitbuchungslinks, damit
  beide Seiten dem erweiterten Vollmachtsumfang durch neue Einladung und
  Annahme zustimmen, und lädt mehrere Partnerabrechnungen mit einer festen
  statt kontenabhängigen Query-Anzahl.
- Verhindert Schnellbuchungen ohne ausgewählte Zielperson, statt sie
  stillschweigend dem angemeldeten Konto zuzuordnen.
- Protokolliert und meldet auch Partner-Rücknahmen alter Essensanmeldungen
  ohne Kostenposition und erlaubt die Stornierung aktueller
  Partner-Eigenbuchungen innerhalb des bestehenden Zeitfensters.
- Zeigt bei Schnellbuchungen für mehrere Konten vor dem Schreiben eine
  verbindliche Übersicht über Personen, Mengen, Einzelpreise und Gesamtsumme
  und verlangt eine ausdrückliche kostenpflichtige Bestätigung. Ein
  zeitlich begrenzter signierter Token bindet diese Bestätigung an den exakt
  gezeigten Buchungssatz; geänderte Ziele oder Preise erzwingen eine neue
  Übersicht.
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
