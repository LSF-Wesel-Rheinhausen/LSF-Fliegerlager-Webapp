# TODO: Testabdeckung ausbauen

Analyse vom 2026-06-02:

- Django-Test-Suite: 123 Tests bestanden.
- Playwright-E2E-Suite: 27 Tests bestanden in Chromium, Firefox und WebKit.
- Offizieller Coverage-Wert fehlt, weil `coverage.py` / `pytest-cov` nicht installiert oder konfiguriert ist.
- Ersatzmessung mit Python `trace` zeigt fuer ausgewertete Billing-Helper 100% Line-Coverage:
  - `billing.services`: 151/151 Zeilen
  - `billing.importers`: 57/57 Zeilen
  - `billing.exporters`: 126/126 Zeilen
  - `billing.auth`, `billing.permissions`, `billing.roles`, Template-Filter: ebenfalls voll getroffen
- Einschraenkung: `trace` liefert keinen belastbaren vollstaendigen App-Coverage-Wert fuer `views.py`, `forms.py` und `models.py`.
- E2E ist aktuell eher Smoke-/Layout-Abdeckung. Mehrere zentrale Browser-Flows fehlen.

## Plan

### 1. Offizielle Coverage-Messung einfuehren

- [x] `pytest-cov` als Dev-Dependency in `requirements-dev.txt` aufnehmen.
- [x] Coverage-Konfiguration fuer `src/billing` im Projekt hinterlegen.
- [x] Zielkommando dokumentieren: `.venv/bin/python -m pytest --cov=src/billing --cov-report=term-missing`.
- Optional spaeter Mindestschwelle einfuehren, sobald der echte Ausgangswert bekannt ist.

Akzeptanzkriterien:

- [x] Coverage-Report laeuft lokal reproduzierbar.
- [x] Report zeigt fehlende Zeilen fuer Views, Forms, Models, Services, Importer und Exporter.
- [x] Normale Test-Suite bleibt gruen.

### 2. Fehlende E2E-Kernflows ergaenzen

- Kiosk-Flow:
  - Teilnehmer mit fehlender PIN landet im PIN-Setup.
  - PIN setzen fuehrt zum Kiosk-Home.
  - Getraenk buchen erzeugt sichtbare Kosten/Summary.
  - Essensanmeldung erzeugt bzw. aktualisiert die Buchung.
- Import-Flow:
  - CSV hochladen.
  - Preview pruefen.
  - Import bestaetigen.
  - Teilnehmer erscheint im Lager.
- Preisverwaltung:
  - Lagerpauschalen speichern.
  - Standardpreise fuer Verpflegung speichern.
  - Preisregel anlegen oder bearbeiten.
- Finanz-Flow:
  - Zahlung erfassen.
  - Auslage erfassen.
  - Abrechnungssummen auf Camp- oder Teilnehmerseite pruefen.
- Export-Flow:
  - CSV-/XLSX-/PDF-Download im Browser ausloesen.
  - Mindestens Dateiname und Content-Type pruefen.
- Rollen-Flow:
  - Editor darf operative Seiten nutzen.
  - Editor darf Admin-Seiten nicht nutzen.
  - Admin darf User-Management nutzen.

Akzeptanzkriterien:

- Neue E2E-Tests laufen stabil mit `npm run test:e2e`.
- Selektoren bleiben role-/label-basiert.
- Keine Testdaten-Abhaengigkeit zwischen einzelnen Browser-Tests.

### 3. Backend-Testluecken aus Coverage-Report schliessen

- Nach echtem Coverage-Report gezielt fehlende Branches in `forms.py`, `views.py` und `models.py` abdecken.
- Formvalidierung fuer relevante Fehlerfaelle testen:
  - PIN-Wiederholung passt nicht.
  - Preisregel ohne erforderliche Lagerpauschalen-Auswahl.
  - Kiosk-Mahlzeit ohne hinterlegte Preisregel.
  - Importdaten mit ungueltiger Signatur.
- Keine Tests skippen oder abschwaechen.

Akzeptanzkriterien:

- Neue Tests pruefen konkrete Rueckgabewerte, Redirects, Messages oder Datenbankeffekte.
- Kritische Business-Flows haben Happy Path und mindestens einen Fehlerfall.
- `.venv/bin/python -m pytest` bleibt gruen.
