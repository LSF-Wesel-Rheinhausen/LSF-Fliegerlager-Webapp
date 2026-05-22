# `tests`

Automatisierte Tests.

- `test_auth.py`: Login per E-Mail-Adresse oder Benutzername.
- `test_permissions.py`: Rollenlogik fuer Admin und Bearbeiter.
- `test_importers.py`: Teilnehmerimport, Validierung und Upsert.
- `test_settlements.py`: Abrechnungslogik, Foerderung, Uebernachtungskategorien, datumsbasierte Naechte, Ueberzahlung sowie gespeicherte Abrechnungslauf-Snapshots und CSV-Export.
- `test_kiosk.py`: Kiosk-PIN-Flow, Kiosk-Layout, Aufenthaltsaenderungen, Zusatzpersonen und Buchungen fuer Getraenke/Essen.
- `test_price_rules.py`: Admin-Preisverwaltung fuer Uebernachtungskategorien, Lagerpauschalen und kategoriespezifische Overlay-Formulare fuer Preisregeln.
- `test_camps.py`: Loeschbestaetigung fuer Lager und kaskadierendes Entfernen abhaengiger Daten.
- `test_setup_flow.py`: First-Launch-Websetup und Static-Finder.
- `e2e/fliegerlager.spec.js`: Playwright-Browsertests fuer Setup, Login, Lageranlage, deutsche Aktionen und responsive Overflow-Pruefungen.

Standardbefehle:

```bash
.venv/bin/python -m pytest
npm run test:e2e
```
