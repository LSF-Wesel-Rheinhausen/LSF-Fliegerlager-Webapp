# Fliegerlager-Abrechnung

[![Tests](https://github.com/LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp/actions/workflows/ci.yml/badge.svg)](https://github.com/LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp/actions/workflows/ci.yml)
[![Docker](https://github.com/LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp/actions/workflows/docker.yml/badge.svg)](https://github.com/LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp/actions/workflows/docker.yml)
[![Security Scan](https://github.com/LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp/actions/workflows/security.yml/badge.svg)](https://github.com/LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp/actions/workflows/security.yml)
[![PR Title Check](https://github.com/LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp/actions/workflows/pr-title.yml/badge.svg)](https://github.com/LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp/actions/workflows/pr-title.yml)


Web-App zur Verwaltung und Abrechnung eines Vereins-Fliegerlagers. Die Anwendung ist als Docker-basierte Django-App mit PostgreSQL vorbereitet und kann lokal auch mit SQLite laufen.

## Funktionen in V1

- Lager/Jahre mit Preisen und Abrechnungsregeln verwalten
- Vereinsnutzer mit E-Mail-/Passwort-Login, Nutzerverwaltung, Passwort-Reset durch Admins und Rollen `Admin` und `Bearbeiter`
- Teilnehmer, Zahlungen, Kostenpositionen und vorgestreckte Beträge pflegen
- Server-seitige Abrechnung je Teilnehmer und Gesamtauswertung je Lager, inklusive Förderlogik über Lager-, Hilfs- und Berufssatz
- Übersichtliche Preisverwaltung mit Lagerpauschalen für 1/2 Wochen und Teilnehmer/Begleitpersonen, Getränke, Standardpreise für Mahlzeiten und abweichende Tagespreise
- Native Dialoge für Preisregelanlage und -bearbeitung, damit Admins im Kontext der Preisübersicht bleiben
- Teilnehmer-Kiosk: PIN-Login, PIN-Ersteinrichtung, sichtbarer Auto-Logout-Timer, große Getränketasten (Ein-Tap-Buchung) und Essensanmeldungen mit Tablet-/Mobilbedienung
- Admin-Mahlzeitenübersicht pro Tag mit Varianten-Zählung, reversiblem Soft-Storno, Storno-Bemerkung und Audit-Protokoll
- Admin-Bearbeitung von Buchungen mit Audit-Protokoll der geänderten abrechnungsrelevanten Felder
- CSV-/Excel-Import mit Vorschau und Validierung
- CSV-, Excel- und PDF-Export für Lager- und Einzelabrechnungen sowie Getränkeauswertungen

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
.venv/bin/python -m pytest
.venv/bin/python src/manage.py check
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy src
```

Playwright-End-to-End-Tests:

```bash
npx playwright install-deps
npx playwright install
npm run test:e2e
```

Interaktive E2E-Prüfung:

```bash
npm run test:e2e:headed
npm run test:e2e:ui
```

Lokaler Sammellauf:

```bash
npm run test:local
```

Die Python-Toolchain nutzt Ruff für Linting/Formatierung, mypy für statische Typprüfung, `factory_boy` für wiederverwendbare Testdaten und pre-commit für lokale Qualitäts- und Secret-Checks. `.env`-Dateien dürfen nicht committed werden; `.env.example` enthält nur sichere Platzhalter.

Um zusätzlich den älteren Projekt-Hook zu aktivieren:

```bash
git config core.hooksPath .githooks
```

## CI/CD & Automatisierung

Das Repository nutzt GitHub Actions für verschiedene Automatisierungen:
- **Tests (`ci.yml`)**: Führt bei jedem Push und PR die lokalen Python- und Playwright-Tests aus.
- **Docker (`docker.yml`)**: Baut das Container-Image, testet es intern und pusht es beim Merge in den `main`-Branch in die GitHub Container Registry (`ghcr.io`).
- **Security (`security.yml`)**: Scannt den Code und die Abhängigkeiten mit Trivy auf bekannte Schwachstellen.
- **PR Title & Changelog (`pr-title.yml`, `changelog-check.yml`)**: Erzwingen *Semantic Pull Requests* und fordern Changelog-Einträge bei Änderungen im Code.
- **Dependabot**: Hält `pip`-, `npm`- und `github-actions`-Abhängigkeiten automatisch aktuell.

## Konfiguration

Die wichtigsten Umgebungsvariablen stehen mit sicheren Platzhaltern in [`.env.example`](.env.example):

- `DJANGO_SECRET_KEY`: produktiver Secret Key, lokal nur Platzhalter verwenden.
- `DJANGO_DEBUG`: `1` für lokale Entwicklung, `0` für Docker/Deployment.
- `DJANGO_ALLOWED_HOSTS`: kommaseparierte Hostnamen.
- `CSRF_TRUSTED_ORIGINS`: kommaseparierte vertrauenswürdige Origins mit Schema.
- `DATABASE_URL`: Datenbank-URL; lokal kann SQLite genutzt werden, Docker nutzt PostgreSQL.

## Rollen

Die Rollen werden über Django-Gruppen abgebildet:

- `Admin`: Nutzer, Lager, Preise, Kategorien und Teilnehmer-PINs verwalten
- `Bearbeiter`: Teilnehmer, Zahlungen, Kosten und Abrechnungen bearbeiten

Superuser haben automatisch vollen Zugriff.

## Dokumentation

Die zentrale Projektdokumentation liegt in [`docs/README.md`](docs/README.md). Zusätzlich gibt es statische HTML-Seiten, die direkt im Browser geöffnet werden können:

- [`docs/index.html`](docs/index.html): Gesamtübersicht
- [`docs/architecture.html`](docs/architecture.html): Architektur, Datenfluss und Abrechnungslogik
- [`docs/operations.html`](docs/operations.html): Setup, Betrieb, Tests und typische Admin-Abläufe
- [`docs/development.html`](docs/development.html): Entwicklung, Qualität, Security und UI-Konventionen

Beitrags- und Agentenregeln stehen in [`CONTRIBUTING.md`](CONTRIBUTING.md) und [`AGENTS.md`](AGENTS.md).

## Roadmap

- Installierbare Webapp/PWA: Web App Manifest, App-Icons, Theme-/Hintergrundfarben, Service Worker für Shell-/Asset-Caching und Installationshinweise für iOS, Android und Desktop.
- Teilnehmer-Kiosk: PWA-Ausbau, Offline-Hinweise und weitere Tablet-Optimierungen.
- Getränke-/Essens-Workflow: Getränke-Tagesübersichten, optionale Schnellerfassung und weitere Storno-Flüsse außerhalb der Admin-Mahlzeitenübersicht.
- Persistierte Abrechnungsläufe: den vorhandenen `Settlement`-Speicher als produktiven Bedienworkflow ausbauen, inklusive Verlauf/Versionierung und Nachvollziehbarkeit von Zeitpunkt und Bearbeiter.
- Mehr Tests: View-/Permission-Integrationstests, Exporttests für CSV/XLSX/PDF, Import-Edge-Cases und zusätzliche Settlement-Regressionsfälle.
- UI-Ausbau: Bearbeiten-/Löschen-Flows, bessere Leerzustände, Druck-/PDF-Ansichten und Dashboard-Auswertungen.
- Deployment und Betrieb: Produktionscheckliste, Backup-/Restore-Dokumentation, Monitoring/Healthcheck und sichere Env-Konfiguration.
- KI-Auslese: Automatisierte KI-Auslese für Rechnungen aus Auslagen implementieren.
- Dienstpläne, Einstellen der Dienstpläne für den Admin und eintragen für einen Dienst als Teilnehmer, inklusive der Anhzahl noch zu erledigenden Dienste
