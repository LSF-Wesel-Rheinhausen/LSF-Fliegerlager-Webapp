# `src/templates`

Servergerenderte Django-Templates.

- `base.html`: Gemeinsames Layout mit Topbar, Vereinslogo, Nachrichten und Inhaltsbereich.
- `registration/login.html`: Login-Seite mit deutschem Formular.
- `billing/setup.html`: Ersteinrichtung fuer den ersten Admin-Benutzer.
- `billing/user_list.html`: Nutzerverwaltung mit Rollen, Status, Bearbeitung und Passwort-Reset.
- `billing/camp_list.html`: Lageruebersicht.
- `billing/camp_detail.html`: Lagerdetail, Kennzahlen, Aktionen und Exporte.
- `billing/camp_meal_overview.html`: Tagesweise Essensübersicht, Bestellstatus und Storno-/Wiederherstellungsaktionen.
- `billing/price_rules_manage.html`: Admin-Preisverwaltung mit Lagerpauschalen-Matrix, Mahlzeiten-Standardpreisen, Tagespreisen und nativen Dialogen fuer Preisregeln.
- `billing/price_rule_table.html`: Gemeinsame Tabelle fuer Preisregeluebersichten.
- `billing/participant_detail.html`: Teilnehmerdetail, Einzelabrechnung, Buchungen mit Buchungsnummern, PIN-Aktionen und Änderungsprotokoll fuer Buchungskorrekturen.
- `billing/form.html`: Generisches Formularlayout fuer CRUD-Aktionen.
- `billing/import_preview.html`: Importformular und Vorschautabelle.
- `billing/shift_manage.html`, `billing/shift_report.html`, `billing/shift_templates_manage.html`: Dienstverwaltung, Soll-/Ist-Auswertung und tägliche Vorlagen.
- `billing/kiosk_base.html`, `billing/kiosk_login.html`, `billing/kiosk_pin_setup.html`, `billing/kiosk_home.html`, `billing/kiosk_shifts.html`: Kiosk-Layout mit Auto-Logout-Timer, PIN-Flows, Buchungsoberflaeche und Dienstwahl/Tausch.
