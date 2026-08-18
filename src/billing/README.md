# `src/billing`

Domain-App fuer die Fliegerlager-Abrechnung.

- `models.py`: Datenmodell fuer Lager, Nutzerprofile, Teilnehmer, Preisregeln, Kosten, Zahlungen, Auslagen, Mahlzeiten, widerrufbare Lagerzugaenge, Kiosk-PINs, Dienstplaene und Abrechnungen.
- `services.py`: Rechenlogik fuer Teilnehmer- und Lagerabrechnungen, Foerderung, automatische Lagerpauschalen-Auswahl, Kiosk-Zusammenfassung und Buchungs-Audit-Snapshots.
- `forms.py`: Django-Formulare mit deutschen Labels fuer Weboberflaeche, Nutzerverwaltung, Preisverwaltung, Mahlzeiten, Dienstvorlagen, Dienste, Kiosk, Login und Ersteinrichtung.
- `email_credentials.py`: authentifizierte Verschluesselung des im Webinterface gepflegten SMTP-Passworts.
- `email_forms.py`, `email_views.py`: Admin-Konfiguration, manuelle Empfaengerauswahl, Vorschau und Versandstatus.
- `email_delivery.py`: manuelle E-Mail-Outbox, Snapshot-PDF-Anhaenge und begrenzte SMTP-Retries.
- `views.py`: Servergerenderte Views fuer Setup, Nutzerverwaltung, Lager, Preisverwaltung, Mahlzeiten, Dienstplanung, Kiosk, Teilnehmer, Imports und Exports.
- `kiosk_access.py`, `kiosk_access_views.py`: serverseitige Lager-PIN-Grenze, signiertes Geraete-Cookie, Session-Bereinigung sowie Admin-Konfiguration und zentraler Widerruf.
- `kiosk_security.py`: datensparsame Client-Schluessel sowie persistente Drosselung von Lagerzugang und Kiosk-Selbstregistrierung.
- `urls.py`: URL-Routing der Billing-App.
- `permissions.py`: Rollenpruefung fuer `Admin` und `Bearbeiter`.
- `roles.py`: Gemeinsame Rollenanlage fuer Websetup und Management-Command.
- `importers.py`: CSV-/XLSX-Importvorschau, Inhaltsvalidierung fuer XLSX-Dateien und Teilnehmer-Upsert.
- `exporters.py`: Lagerabrechnung als CSV, Getraenke-CSV, Excel-Arbeitsmappe und Teilnehmer-PDF.
- `auth.py`: Login per E-Mail-Adresse oder Benutzername.
- `signals.py`: Automatische Teilnehmer-PIN-Anlage.
- `templatetags/billing_format.py`: Template-Filter fuer Geldformatierung und rollenabhaengige Anzeige.
- `admin.py`: Django-Admin-Registrierungen.
- `management/commands/bootstrap_roles.py`: CLI-Command zum Anlegen/Aktualisieren der Rollen.
- `management/commands/run_email_worker.py`: verarbeitet ausschliesslich manuell bestaetigte E-Mail-Auftraege.

Wichtige Modelle:

- `Camp`, `Participant`, `PriceRule`, `Charge`, `Payment` und `Expense` bilden Lager, Personen, Preise, Kosten, Zahlungen und Auslagen ab.
- `UserProfile` ergänzt Nutzerkonten um bearbeitbare Anwendungsdaten wie Telefonnummern.
- `ParticipantPin` und `ParticipantFamilyMemberPin` speichern gehashte persönliche Kiosk-PINs, Fehlversuche und zeitlich begrenzte Sperren. PIN-Hash-Modelle werden nicht im generischen Django-Admin angeboten.
- `CampKioskAccess` speichert nur den Hash des gemeinsamen Lager-PINs und eine rotierbare Generation, mit der alle ausgestellten Geraete-Cookies gleichzeitig widerrufen werden.
- `CampKioskAccessAttempt` und `CampKioskRegistrationAttempt` begrenzen PIN-Fehlversuche beziehungsweise Selbstregistrierungen persistent pro Lagerzugang und gehashtem Client-Schluessel.
- `MealSignup` speichert Essensanmeldungen eindeutig pro Teilnehmer, Datum und Mahlzeit.
- `DrinkEntry` ist ein historisches Getraenke-Modell; aktuelle Kiosk-Getraenkebuchungen werden als `Charge` mit Art `DRINK` gespeichert.
- `BookingAuditLog` protokolliert Admin-Korrekturen an Buchungen.
- `Shift`, `DailyShiftTemplate`, `DailyShiftException` und `ShiftAssignment` bilden Dienste, tägliche Vorlagen, Tagesausnahmen, Besetzungen und Tauschangebote ab. Vorlagen und einzelne Dienste besitzen Beschreibungstexte für die Aufgabeninformation; die Generierung kopiert Vorlagentexte nur in neue Dienste und bewahrt individuelle Änderungen.
- `SettlementRun` versioniert unveränderliche Lagerabrechnungen; `Settlement` speichert darin den jeweiligen Teilnehmer-Snapshot mit Positionen und Summen.
- `EmailConfiguration`, `EmailTestLog`, `EmailBatch` und `EmailDelivery` speichern verschluesselte SMTP-Einstellungen,
  sichere Verbindungstests sowie die nachvollziehbare manuelle Versand-Outbox.

## Essenskalender

Die responsive Abendessen-Tagessteuerung trennt Status und manuelle Sperrung von den Detailtabellen. Die interne `meal_booking_cutoff_time` wird nur als unverbindliche Richtzeit für Erinnerungen verwendet. Für Abendessen entscheidet an heutigen und zukünftigen Lagertagen ausschließlich `MealBookingOverride`; Frühstück ist dort immer buch- und stornierbar. Vergangene Tage bleiben unveränderlich.
