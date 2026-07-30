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
  sperrt zuerst nur die Essensanmeldung und lädt danach eine vorhandene Charge
  separat unter Lock neu. Dadurch bleiben nullable Relationen unter
  PostgreSQL zulässig und eine zwischenzeitlich geänderte Charge kann weder
  die Tokenprüfung noch den Audit-Snapshot umgehen.
  Jede erfolgreiche Rücknahme erhöht zusätzlich eine persistente Version,
  sodass ihr Bestätigungstoken auch nach einer identischen Neubuchung nicht
  erneut verwendet werden kann. Buchungs-Batches sperren alle betroffenen
  Essensanmeldungen in stabiler Reihenfolge, bevor sie Partner-Vollmachten
  sperren, damit parallele Gegenoperationen keinen Lock-Zyklus bilden.
- Sperrt bei allen Partner-Schreibvorgängen zuerst das betroffene Lager und
  danach alle referenzierten Teilnehmer- und Familienzeilen jeweils in
  stabiler Datenbankreihenfolge. Dabei werden alle eingereichten Snapshots
  derselben Identität geprüft, statt bei doppelten Zielen stillschweigend nur
  den letzten zu behalten. Anschließend werden sämtliche Preisregeln des
  Lagers gesperrt und die effektive Regel aus den gesperrten Zielrollen neu
  aufgelöst. Essensvorgänge sperren beziehungsweise erzeugen erst danach alle
  MealSignup-Zeilen und sperren zuletzt die benötigten Vollmachten;
  Schnellstornierungen sperren nach den Identitäten die Charge und danach die
  Vollmacht. Diese gesperrten Zeilen werden für den gesamten Schreibvorgang
  wiederverwendet, sodass parallele Abrechnungen, Widerrufe und Buchungen
  keinen Fremdschlüssel-/Vollmachts-Lockzyklus bilden. Nach dem Lock werden
  Lageraktivität, Teilnehmer-Lagerzuordnung, Archivstatus, Kind-/Begleitrolle
  sowie Hauptkonto und Rolle von Familienmitgliedern erneut geprüft; eine
  parallele Lagerdeaktivierung kann dadurch keinen Kiosk-Write mehr
  durchlassen.
- Hält das konkrete Familienziel auch bei Eigenhaushalts-Schnellbuchungen im
  Audit fest, damit ein später verknüpfter Partner bei einer Stornierung
  weiterhin die tatsächlich betroffene Person protokolliert.
- Schützt Familienmitglieder mit vorhandener Audit-Historie vor dem Löschen
  und speichert unveränderliche Akteurs- und Zielnamen aus den nach dem Lock
  frisch geladenen Identitäten im Audit. Spätere Namens- oder
  Hauptkontowechsel schreiben die dargestellte Historie dadurch nicht
  rückwirkend um; fachliches Entfernen erfolgt weiterhin über die
  Deaktivierung.
- Erstellt auch Schnellbuchungs-Charges, Rechnungsbeschreibungen und
  Benachrichtigungen aus den frisch gesperrten Ziel- und Akteursobjekten,
  damit ein Name, der unmittelbar vor dem Lock geändert wurde, überall
  konsistent erscheint. Der Namens-Snapshot wird an den Commit-Callback
  übergeben und dort nicht aus einer später erneut geladenen Identität
  rekonstruiert. Handelt eine Begleitperson, nennt die Benachrichtigung diese
  tatsächliche Person statt des Hauptkontos. Auch Einladungs-, Annahme-,
  Ablehnungs- und Widerrufsbenachrichtigungen verwenden den unter Lock
  erfassten Namen.
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
- Race-Regressionen für doppelte Identitätssnapshots, Lagerdeaktivierung,
  archivierte oder geänderte Quick-/Essenspreisregeln und Namensänderungen vor
  beziehungsweise nach den Identitätslocks.
