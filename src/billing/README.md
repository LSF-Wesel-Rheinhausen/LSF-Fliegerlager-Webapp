# `src/billing`

Domain-App fuer die Fliegerlager-Abrechnung.

- `models.py`: Datenmodell fuer Lager, Teilnehmer, Preisregeln, Lagerpauschalen, Kosten, Zahlungen, Auslagen, Kiosk-Vorbereitung und Abrechnungen.
- `services.py`: Rechenlogik fuer Teilnehmer- und Lagerabrechnungen, Foerderung, automatische Lagerpauschalen-Auswahl, Kiosk-Zusammenfassung und Buchungs-Audit-Snapshots.
- `forms.py`: Django-Formulare mit deutschen Labels fuer Weboberflaeche, Nutzerverwaltung, Preisverwaltung, Mahlzeiten-Standardpreise, Kiosk, Login und Ersteinrichtung.
- `views.py`: Servergerenderte Views fuer Setup, Login-Weiterleitung, Nutzerverwaltung, Lager, Preisverwaltung, Kiosk, Teilnehmer, Imports und Exports.
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

Wichtige Modelle:

- `Camp`, `Participant`, `PriceRule`, `Charge`, `Payment` und `Expense` bilden Lager, Personen, Preise, Kosten, Zahlungen und Auslagen ab.
- `ParticipantPin` speichert gehashte Kiosk-PINs und den Status der PIN-Ersteinrichtung.
- `MealSignup` speichert Essensanmeldungen eindeutig pro Teilnehmer, Datum und Mahlzeit.
- `DrinkEntry` ist ein historisches Getraenke-Modell; aktuelle Kiosk-Getraenkebuchungen werden als `Charge` mit Art `DRINK` gespeichert.
- `BookingAuditLog` protokolliert Admin-Korrekturen an Buchungen.
- `Settlement` ist modellseitig vorbereitet; die sichtbaren Abrechnungen werden derzeit on-demand in `services.py` berechnet.
