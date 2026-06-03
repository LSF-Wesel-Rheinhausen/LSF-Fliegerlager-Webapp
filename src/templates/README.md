# `src/templates`

Servergerenderte Django-Templates.

- `base.html`: Gemeinsames Layout mit Topbar, Vereinslogo, Nachrichten und Inhaltsbereich.
- `registration/login.html`: Login-Seite mit deutschem Formular.
- `billing/setup.html`: Ersteinrichtung fuer den ersten Admin-Benutzer.
- `billing/user_list.html`: Nutzerverwaltung mit Rollen, Status, Bearbeitung und Passwort-Reset.
- `billing/camp_list.html`: Lageruebersicht.
- `billing/camp_detail.html`: Lagerdetail, Kennzahlen, Aktionen und Exporte.
- `billing/price_rules_manage.html`: Admin-Preisverwaltung mit Lagerpauschalen-Matrix, Mahlzeiten-Standardpreisen, Tagespreisen und nativen Dialogen fuer Preisregeln.
- `billing/price_rule_table.html`: Gemeinsame Tabelle fuer Preisregeluebersichten.
- `billing/participant_detail.html`: Teilnehmerdetail, Einzelabrechnung, Buchungen, PIN-Aktionen und Änderungsprotokoll fuer Buchungskorrekturen.
- `billing/form.html`: Generisches Formularlayout fuer CRUD-Aktionen.
- `billing/import_preview.html`: Importformular und Vorschautabelle.
- `billing/kiosk_base.html`, `billing/kiosk_login.html`, `billing/kiosk_pin_setup.html`, `billing/kiosk_home.html`: Kiosk-Layout mit sichtbarem Auto-Logout-Timer, PIN-Flows und mobiler Buchungsoberflaeche mit grossen Getraenke-Tasten.
