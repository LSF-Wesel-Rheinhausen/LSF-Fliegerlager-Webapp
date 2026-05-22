# Fliegerlager-Abrechnung

Web-App zur Verwaltung und Abrechnung eines Vereins-Fliegerlagers. Die Anwendung ist als Docker-basierte Django-App mit PostgreSQL vorbereitet und kann lokal auch mit SQLite laufen.

## Funktionen in V1

- Lager/Jahre mit Preisen und Abrechnungsregeln verwalten
- Vereinsnutzer mit E-Mail-/Passwort-Login und Rollen `Admin` und `Bearbeiter`
- Teilnehmer, Zahlungen, Kostenpositionen und vorgestreckte Beträge pflegen
- Server-seitige Abrechnung je Teilnehmer und Gesamtauswertung je Lager, inklusive Förderlogik über Lager-, Hilfs- und Berufssatz
- Gespeicherte Abrechnungsläufe mit Snapshot pro Lauf, Detailansicht und CSV-Export für nachvollziehbare Stände
- Übersichtliche Preisverwaltung mit Uebernachtungskategorien pro Lager, kategoriespezifischen Lagerpauschalen und Overlay-Formularen fuer Getraenke, Essen, Uebernachtungen und sonstige Preise
- Teilnehmer-Kiosk: PIN-Login, PIN-Ersteinrichtung, sichtbarer Auto-Logout-Timer, grosse Getraenketasten, Aufenthaltsanpassung per An-/Abreise und das Anlegen von Begleitern oder Kindern als eigene Eintraege
- Lager koennen mit separater Bestaetigungsseite vollstaendig geloescht werden
- CSV-/Excel-Import mit Vorschau und Validierung
- CSV-, Excel- und PDF-Export für Abrechnungen

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

Die Python-Toolchain nutzt Ruff für Linting/Formatierung, mypy für statische Typprüfung und pre-commit für lokale Qualitäts- und Secret-Checks. `.env`-Dateien dürfen nicht committed werden; `.env.example` enthält nur sichere Platzhalter.

Um zusätzlich den älteren Projekt-Hook zu aktivieren:

```bash
git config core.hooksPath .githooks
```

## Git-Workflow

Für jedes neue Arbeitspaket gilt derselbe Ablauf:

1. GitHub-Authentifizierung mit `gh auth status` prüfen und bei Bedarf mit `gh auth login -h github.com` reparieren.
2. Von `master` einen frischen Feature-Branch anlegen.
3. Vor Beginn der eigentlichen Umsetzung `Push 1` ausführen: `git push -u origin <feature-branch>`.
4. Umsetzung, Tests, Review-Fixes und Coverage-Arbeit ausschließlich auf diesem Branch erledigen.
5. Nach Abschluss `Push 2` ausführen: final committen, validieren und denselben Branch erneut nach `origin` pushen.

Direktes Arbeiten oder Pushen auf `master` ist nicht der Standardprozess.

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
- Getränke-/Essens-Workflow: Tages-/Mahlzeitenübersichten, Storno-/Korrekturflüsse und optionale Schnellerfassung.
- Persistierte Abrechnungsläufe: Vergleich mehrerer gespeicherter Läufe, gezielte Lösch-/Archivierungsregeln und klarere Verlaufsnavigation.
- Mehr Tests: zusätzliche View-/Permission-Integrationstests, weitere Exporttests für XLSX/PDF, Import-Edge-Cases und zusätzliche Settlement-Regressionsfälle.
- UI-Ausbau: Bearbeiten-/Löschen-Flows, bessere Leerzustände, Druck-/PDF-Ansichten und Dashboard-Auswertungen.
- Deployment und Betrieb: Produktionscheckliste, Backup-/Restore-Dokumentation, Monitoring/Healthcheck und sichere Env-Konfiguration.
