# `src/templates`

Servergerenderte Django-Templates.

- `base.html`: Gemeinsames Layout mit Topbar, Vereinslogo, Nachrichten und Inhaltsbereich.
- `registration/login.html`: Login-Seite mit deutschem Formular.
- `billing/setup.html`: Ersteinrichtung fuer den ersten Admin-Benutzer.
- `billing/camp_list.html`: Lageruebersicht.
- `billing/camp_detail.html`: Lagerdetail, Kennzahlen, Aktionen und Exporte.
- `billing/price_rules_manage.html`: Admin-Preisverwaltung mit Uebernachtungskategorien, Lagerpauschalen pro Kategorie und Preisregeluebersichten.
- `billing/price_rule_table.html`: Gemeinsame Tabelle fuer Preisregeluebersichten.
- `billing/participant_detail.html`: Teilnehmerdetail und Einzelabrechnung.
- `billing/form.html`: Generisches Formularlayout fuer CRUD-Aktionen.
- `billing/import_preview.html`: Importformular und Vorschautabelle.
- `billing/kiosk_base.html`, `billing/kiosk_login.html`, `billing/kiosk_pin_setup.html`, `billing/kiosk_home.html`: Kiosk-Layout mit sichtbarem Auto-Logout-Timer, PIN-Flows, Aufenthaltsaenderungen, Zusatzpersonen und mobiler Buchungsoberflaeche mit grossen Getraenke-Tasten.
