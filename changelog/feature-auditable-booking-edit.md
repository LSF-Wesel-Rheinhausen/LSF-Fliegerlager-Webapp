# PR-Zusammenfassung: feature/auditable-booking-edit

Stand: 2026-06-02

## Zusammenfassung

- Testabdeckung analysiert, mit Fokus auf Django-Tests und Playwright-E2E-Flows.
- Bestehende Test-Suites ausgefuehrt und Ergebnisse dokumentiert.
- Fehlende E2E-Kernflows identifiziert.
- `TODO.md` von "Keine offenen TODOs." auf einen konkreten Umsetzungsplan fuer Testabdeckung erweitert.
- Changelog-Ordner fuer kuenftige PR-Zusammenfassungen angelegt.

## Geaenderte Dateien

- `TODO.md`: Analyseergebnisse, Coverage-Einschraenkung, E2E-Gaps und Umsetzungsplan.
- `changelog/README.md`: Konvention fuer PR-Changelog-Eintraege.
- `changelog/feature-auditable-booking-edit.md`: Zusammenfassung dieses Arbeitsstands.

## Verifikation

- `.venv/bin/python -m pytest`: 123 Tests bestanden.
- `npm run test:e2e`: 27 Playwright-Tests bestanden.
- Offizieller Coverage-Report noch nicht moeglich, weil `coverage.py` / `pytest-cov` nicht installiert ist.

## Offene Punkte

- `pytest-cov` als Dev-Dependency ergaenzen und echten Coverage-Report fuer `src/billing` erzeugen.
- Fehlende E2E-Flows fuer Kiosk, Import, Preisverwaltung, Finanzen, Exporte und Rollen umsetzen.
- Backend-Testluecken nach echtem Coverage-Report gezielt schliessen.
