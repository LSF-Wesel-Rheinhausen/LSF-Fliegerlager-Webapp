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
- `test_kiosk_shifts.py`: Dienstuebernahme, Rueckgabe, Tausch und Fortschrittsanzeige im Kiosk.
- `test_shifts.py`: Dienstmodelle, Soll-Dienst-Berechnung, Admin-Verwaltung und Auswertung.
- `test_shift_templates.py`: Taegliche Dienstvorlagen und idempotente Generierung fuer den Lagerzeitraum.
- `test_meal_overview.py`: Tagesuebersicht, Bestellstatus und reversible Essensstornos.
- `test_migrations.py`: Datenuebernahmen und Kompatibilitaet kritischer Schema-Migrationen.
- `test_price_rules.py`: Admin-Preisverwaltung und Lagerpauschalen-Matrix.
- `test_booking_audit.py`: Admin-Bearbeitung, Löschung und Wiederherstellung von Buchungen im Änderungsprotokoll.
- `test_setup_flow.py`: First-Launch-Websetup und Static-Finder.
- `test_persistence_migration.py`: sichere und idempotente Übernahme bisheriger Docker-Volumes.
- `test_webpush_keys.py`: Erzeugung, Wiederverwendung und Validierung persistenter VAPID-Schlüssel.
- `test_email_delivery.py`: verschlüsselte SMTP-Konfiguration, manuelle Auswahl, Vorschau, Rechnungs-PDFs und Worker-Retries.
- `factories.py`: Wiederverwendbare Testdaten mit `factory_boy`.
- `e2e/fliegerlager.spec.js`: Playwright-Browsertests fuer Setup, Login, Lageranlage, Buchungs-Audit, Preisregel-Dialoge, Kiosk, Dienstplanung, Exporte und responsive Overflow-Pruefungen.

Standardbefehle:

```bash
.venv/bin/python src/manage.py check
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy src
npm run test:e2e
```

Die gemeinsame lokale Beispieldatenbank wird mit der festgelegten SQLite-URL und diesen Befehlen erzeugt:

```bash
export DATABASE_URL=sqlite:////Users/jansellerbeck/git/LSF-Fliegerlager-Webapp/src/db.sqlite3
.venv/bin/python src/manage.py migrate --noinput
.venv/bin/python src/manage.py seed_local_test_db
```

Der Seed ist idempotent, lokal-only und nicht für Produktion bestimmt. Die deterministischen lokalen Logins sind:

- `local-admin` / `LocalAdmin-417-Only!` (aktiv, Admin)
- `local-editor` / `LocalEditor-417-Only!` (aktiv, Editor)
- `local-huebers` / `LocalHuebers-417-Only!` (aktiv, Huebers)
- `local-inactive` / `LocalInactive-417-Only!` (deaktiviert; Anmeldung wird abgelehnt)
- Lager-Kiosk-PIN: `864208`
- `AdultComplete Synthetic` / persönliche PIN `2468`
- `ChildPartial Synthetic` / persönliche PIN `8642` (gesperrt)
- `FamilyCompanion Synthetic` / persönliche PIN `9753`

pytest, CI und parallele Playwright-Worker verwenden weiterhin isolierte Datenbanken; nur ein serieller lokaler E2E-/Review-Lauf darf bewusst gegen dieselbe lokale Seed-Datenbank zeigen.

Der lokale Sammellauf ist `npm run test:local`; die Logs werden unter `.test-local-logs/<timestamp>/` abgelegt.
