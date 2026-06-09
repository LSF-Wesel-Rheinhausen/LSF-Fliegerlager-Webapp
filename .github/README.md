# LSF Fliegerlager Webapp

Web-App zur Verwaltung und Abrechnung des Vereins-Fliegerlagers der Luftsportfreunde Wesel-Rheinhausen e.V.

Die Anwendung ist eine Django-App mit Nutzer- und Teilnehmerverwaltung, Preisregeln, Förderlogik, Mahlzeiten- und Dienstplanung, Kiosk-Modus, Import/Export und Abrechnungsauswertung.

## Funktionen

- Lager/Jahre mit Preisen und Abrechnungsregeln verwalten
- Rollen für `Admin` und `Bearbeiter`
- Teilnehmer, Zahlungen, Kostenpositionen und vorgestreckte Beträge pflegen
- Preisverwaltung für Lagerpauschalen, Getränke, Essen und sonstige Regeln
- Lagerpauschalen automatisch nach 1/2 Wochen und Teilnehmer/Begleitperson berechnen
- Förderung über Lager-Fördersatz, Hilfssatz und Berufssatz berücksichtigen
- Kiosk mit PIN-Login, PIN-Ersteinrichtung, Getränke- und Essensbuchung
- Dienstvorlagen und einzelne Dienste im Adminbereich sowie Dienstübernahme und -tausch im Kiosk
- temporäre Kiosk-Sperre nach wiederholten falschen PIN-Eingaben
- automatische Kiosk-Abmeldung nach Inaktivität
- CSV-/XLSX-Import mit Vorschau und Validierung
- CSV-, Excel- und PDF-Export für Abrechnungen

## Dokumentation

- [`README.md`](../README.md): Setup, Tests, Rollen und Roadmap
- [`docs/README.md`](../docs/README.md): zentrale Projektdokumentation
- [`docs/index.html`](../docs/index.html): HTML-Gesamtübersicht
- [`docs/architecture.html`](../docs/architecture.html): Architektur, Datenfluss und Abrechnungslogik
- [`docs/operations.html`](../docs/operations.html): Setup, Betrieb, Tests und typische Admin-Abläufe
- [`docs/development.html`](../docs/development.html): Entwicklung, Qualität, Security und UI-Konventionen
- [`FILES.md`](../FILES.md): schnelle Dateiübersicht
- [`src/billing/README.md`](../src/billing/README.md): Domain-App und zentrale Module
- [`tests/README.md`](../tests/README.md): Teststruktur

## Lokale Entwicklung

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
npm install
python src/manage.py migrate
python src/manage.py runserver
```

Beim ersten Aufruf der Weboberfläche führt die App durch die Ersteinrichtung und legt den ersten Admin-Benutzer an.

## Docker

```bash
cp .env.example .env
docker compose up --build
```

Danach läuft die App unter `http://localhost:8000`.

## Tests

```bash
.venv/bin/python src/manage.py check
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy src
```

End-to-End-Tests:

```bash
npm run test:e2e
```

Lokaler Sammellauf:

```bash
npm run test:local
```

## CI/CD Workflows

Die GitHub-Actions-Workflows liegen in [`workflows/`](workflows/):
- `ci.yml`: Führt lokales Python-Setup, Node-Setup, Django-Check, Pytest und Playwright-E2E aus.
- `docker.yml`: Baut das Docker-Image, testet es intern und pusht es bei Merge auf `main` in die GitHub Container Registry (`ghcr.io`).
- `security.yml`: Führt einen Trivy-Security-Scan über die Abhängigkeiten aus (wöchentlich und bei Push).
- `pr-title.yml`: Erzwingt Semantic PR Titles (z.B. `feat:`, `fix:`).
- `changelog-check.yml`: Prüft, ob bei Code-Änderungen in `src/` zwingend ein Changelog-Eintrag erstellt wurde.

Zudem sorgt Dependabot (`dependabot.yml`) für automatisierte Updates von `pip`, `npm` und GitHub Actions.

## Contribution Rules

Beitrags- und Agentenregeln stehen in [`CONTRIBUTING.md`](../CONTRIBUTING.md) und [`AGENTS.md`](../AGENTS.md). Neue Python-Funktionen sollen Type Hints nutzen; ORM-Code muss N+1-Abfragen vermeiden; sensible Daten und `.env`-Dateien dürfen nicht committed oder geloggt werden. Templates sollen semantisches HTML, mobile-first CSS und barrierearme Formulare nutzen.
