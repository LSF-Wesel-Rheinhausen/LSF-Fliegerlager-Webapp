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
- Serialisiert parallele Einladungen für dasselbe Teilnehmerpaar und räumt
  verbliebene offene oder angenommene Duplikate bei Annahme und Widerruf auf,
  sodass ein alter Link die Vollmacht nicht später wiederherstellen kann.
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
  Rücknahmen aus einem fremden Partnerhaushalt erfordern zuvor einen
  expliziten Dialog mit einem signierten, zustandsgebundenen
  Bestätigungstoken. Status und signierter Zustand werden nach dem Datenbank-
  Lock erneut geprüft, damit parallele Requests weder doppelte Stornierungen
  noch doppelte Audit- oder Benachrichtigungseinträge erzeugen. Der Lock
  beschränkt sich auf die Essensanmeldung selbst, sodass PostgreSQL nullable
  vorgeladene Charge- und Familienrelationen nicht unzulässig mitsperrt.
  Jede erfolgreiche Rücknahme erhöht zusätzlich eine persistente Version,
  sodass ihr Bestätigungstoken auch nach einer identischen Neubuchung nicht
  erneut verwendet werden kann. Buchungs-Batches sperren alle betroffenen
  Essensanmeldungen in stabiler Reihenfolge, bevor sie Partner-Vollmachten
  sperren, damit parallele Gegenoperationen keinen Lock-Zyklus bilden.
- Sperrt bei Essens-, Schnellbuchungs- und Check-in-Sammeländerungen für
  mehrere Partnerkonten sämtliche benötigten Vollmachten einmalig in stabiler
  Datenbankreihenfolge und verwendet diese gesperrten Zeilen für den gesamten
  Schreibvorgang.
- Bindet jede Check-in-Zeile an ihren signierten Ausgangszustand, schreibt nur
  tatsächlich geänderte Zeilen und weist konkurrierend veränderte Daten ohne
  Teilaktualisierung zurück.
- Zeigt bei Schnellbuchungen für mehrere Konten vor dem Schreiben eine
  verbindliche Übersicht über Personen, Mengen, Einzelpreise und Gesamtsumme
  und verlangt eine ausdrückliche kostenpflichtige Bestätigung. Ein
  zeitlich begrenzter signierter Token bindet diese Bestätigung an den exakt
  gezeigten Buchungssatz; geänderte Ziele oder Preise erzwingen eine neue
  Übersicht. Ein eindeutiger, atomar mit der ersten Charge gespeicherter
  Nonce verhindert doppelte Buchungen durch Doppelklicks oder Replay.
- Bietet Schnellbuchungsartikel für alle tatsächlich verfügbaren
  Zielgruppen an und prüft ihre Anwendbarkeit weiterhin für jede ausgewählte
  Person separat.
- Schließt Charges regulärer Kalender-Essensanmeldungen aus der
  Schnellstornierung aus, damit Anmeldung und Abrechnung nicht auseinander
  laufen.
- Lässt PIN-, Sicherheits-, Identitäts- und Administrationsfunktionen
  ausdrücklich außerhalb der Partner-Vollmacht.
- Zeigt den vollständigen Umfang und die Ausschlüsse der Partner-Vollmacht
  unmittelbar vor jeder Annahme, auch auf der Kiosk-Startseite. Dazu gehört
  ausdrücklich, dass aktive Begleitpersonen beider Hauptkonten die Vollmacht
  mit eigener PIN ausüben können und als tatsächliche Akteure protokolliert
  werden.

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
