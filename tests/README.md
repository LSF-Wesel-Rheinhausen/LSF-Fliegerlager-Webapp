# `tests`

Automatisierte Tests.

- `test_auth.py`: Login per E-Mail-Adresse oder Benutzername.
- `test_permissions.py`: Rollenlogik fuer Admin und Bearbeiter.
- `test_view_permissions.py`: Zugriffsschutz fuer GET- und POST-Routen.
- `test_user_management.py`: Nutzerverwaltung, Rollenwechsel, Passwort-Reset und Schutz des letzten Admins.
- `test_importers.py`: Teilnehmerimport, Validierung und Upsert.
- `test_exporters.py`: CSV-, Excel- und PDF-Exports sowie Export-Berechtigungen.
- `test_settlements.py`: Abrechnungslogik, Foerderung, Lagerpauschalen-Auswahl und Ueberzahlung.
- `test_kiosk.py`: Kiosk-PIN-Flow, Kiosk-Layout und Buchungen fuer Getraenke/Essen.
- `test_price_rules.py`: Admin-Preisverwaltung und Lagerpauschalen-Matrix.
- `test_booking_audit.py`: Admin-Bearbeitung von Buchungen und Audit-Protokoll.
- `test_setup_flow.py`: First-Launch-Websetup und Static-Finder.
- `factories.py`: Wiederverwendbare Testdaten mit `factory_boy`.
- `e2e/fliegerlager.spec.js`: Playwright-Browsertests fuer Setup, Login, Lageranlage, Buchungs-Audit, Preisregel-Dialoge, deutsche Aktionen, Exporte und responsive Overflow-Pruefungen.

Standardbefehle:

```bash
.venv/bin/python src/manage.py check
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy src
npm run test:e2e
```

Der lokale Sammellauf ist `npm run test:local`; die Logs werden unter `.test-local-logs/<timestamp>/` abgelegt.
