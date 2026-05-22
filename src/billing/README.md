# `src/billing`

Domain-App fuer die Fliegerlager-Abrechnung.

- `models.py`: Datenmodell fuer Lager, Teilnehmer, Uebernachtungskategorien, Preisregeln, Kosten, Zahlungen, Auslagen, Kiosk-Vorbereitung und Abrechnungen.
- `services.py`: Rechenlogik fuer Teilnehmer- und Lagerabrechnungen, Foerderung, kategoriebasierte Lagerpauschalen und Kiosk-Zusammenfassung.
- `forms.py`: Django-Formulare mit deutschen Labels fuer Weboberflaeche, Preisverwaltung, Kiosk, Aufenthaltsaenderungen, Zusatzpersonen und Ersteinrichtung.
- `views.py`: Servergerenderte Views fuer Setup, Login-Weiterleitung, Lager, Preisverwaltung, Kiosk, Teilnehmer, Kategorien, Imports, Exports und Lager-Loeschung.
- `urls.py`: URL-Routing der Billing-App.
- `permissions.py`: Rollenpruefung fuer `Admin` und `Bearbeiter`.
- `roles.py`: Gemeinsame Rollenanlage fuer Websetup und Management-Command.
- `importers.py`: CSV-/XLSX-Importvorschau und Teilnehmer-Upsert.
- `exporters.py`: CSV-, Excel- und PDF-Exports.
- `auth.py`: Login per E-Mail-Adresse oder Benutzername.
- `signals.py`: Automatische Teilnehmer-PIN-Anlage.
- `admin.py`: Django-Admin-Registrierungen.
- `management/commands/bootstrap_roles.py`: CLI-Command zum Anlegen/Aktualisieren der Rollen.
