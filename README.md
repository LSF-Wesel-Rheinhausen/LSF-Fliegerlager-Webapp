# Fliegerlager-Abrechnung

Web-App zur Verwaltung und Abrechnung eines Vereins-Fliegerlagers. Die Anwendung ist als Docker-basierte Django-App mit PostgreSQL vorbereitet und kann lokal auch mit SQLite laufen.

## Funktionen in V1

- Lager/Jahre mit Preisen und Abrechnungsregeln verwalten
- Vereinsnutzer mit E-Mail-/Passwort-Login und Rollen `Admin` und `Bearbeiter`
- Teilnehmer, Zahlungen, Kostenpositionen und vorgestreckte Beträge pflegen
- Server-seitige Abrechnung je Teilnehmer und Gesamtauswertung je Lager, inklusive Förderlogik über Lager-, Hilfs- und Berufssatz
- Übersichtliche Preisverwaltung mit Lagerpauschalen für 1/2 Wochen und Teilnehmer/Begleitpersonen sowie Preisregeln für Getränke und Essen
- Teilnehmer-Kiosk: PIN-Login, PIN-Ersteinrichtung, Essensanmeldungen und Getränkebuchungen mit Tablet-/Mobilbedienung
- CSV-/Excel-Import mit Vorschau und Validierung
- CSV-, Excel- und PDF-Export für Abrechnungen

## Lokale Entwicklung

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
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

Um die Tests automatisch vor jedem Commit auszuführen, aktiviere die Projekt-Hooks einmalig:

```bash
git config core.hooksPath .githooks
```

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

## Roadmap

- Installierbare Webapp/PWA: Web App Manifest, App-Icons, Theme-/Hintergrundfarben, Service Worker für Shell-/Asset-Caching und Installationshinweise für iOS, Android und Desktop.
- Teilnehmer-Kiosk: PWA-Ausbau, Offline-Hinweise und weitere Tablet-Optimierungen.
- Getränke-/Essens-Workflow: Tages-/Mahlzeitenübersichten, Storno-/Korrekturflüsse und optionale Schnellerfassung.
- Persistierte Abrechnungsläufe: berechnete Abrechnungen speichern, Verlauf/Versionierung und Nachvollziehbarkeit von Zeitpunkt und Bearbeiter.
- Mehr Tests: View-/Permission-Integrationstests, Exporttests für CSV/XLSX/PDF, Import-Edge-Cases und zusätzliche Settlement-Regressionsfälle.
- UI-Ausbau: Bearbeiten-/Löschen-Flows, bessere Leerzustände, Druck-/PDF-Ansichten und Dashboard-Auswertungen.
- Deployment und Betrieb: Produktionscheckliste, Backup-/Restore-Dokumentation, Monitoring/Healthcheck und sichere Env-Konfiguration.
