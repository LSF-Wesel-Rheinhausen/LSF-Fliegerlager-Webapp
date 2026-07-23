# Projektdokumentation

Diese Dokumentation fasst die Fliegerlager-Webapp zusammen und verweist auf die Detaildokumente im Repository.

## Überblick

Die Anwendung ist eine Django-Webapp zur Verwaltung und Abrechnung eines Vereins-Fliegerlagers. Sie unterstützt Lager, Nutzer und Teilnehmer, Preisregeln, Förderlogik, Zahlungen, Auslagen, Import/Export, Dienstplanung und einen Kiosk-Modus für Teilnehmer.

Der typische Ablauf:

1. Ein Admin legt ein Lager an und pflegt Preise mit individuellen Fördersätzen.
2. Teilnehmer werden manuell angelegt oder per CSV/XLSX importiert.
3. Preisregeln werden im Adminbereich gepflegt, inklusive Lagerpauschalen für 1/2 Wochen und Teilnehmer/Begleitpersonen.
4. Admins erzeugen Dienste aus täglichen Vorlagen oder pflegen einzelne Dienste; Teilnehmer übernehmen oder tauschen Dienste im Kiosk.
5. Teilnehmer buchen im Kiosk Getränke und Essen per PIN.
6. Die Abrechnung berechnet Brutto, Förderung, Soll, Zahlungen, vorgestreckte Beträge und offenen Saldo.
7. Ergebnisse können als CSV, Excel-Arbeitsmappe oder PDF exportiert werden.

## Wichtige Funktionen

- Rollen: `Admin` und `Bearbeiter` über Django-Gruppen.
- Ersteinrichtung: Beim ersten Start kann der erste Admin im Browser angelegt werden; danach verwalten Admins Nutzer, Rollen und Passwörter in der Anwendung.
- Anmeldung: Verwaltungsnutzer können neben Passwort und optionalem Authelia-SSO eigene Passkeys registrieren und benutzernamenlos verwenden.
- Preisverwaltung: eigene Admin-Route für Lagerpauschalen, Getränke, Standard-Mahlzeitenpreise, abweichende Tagespreise und sonstige Preisregeln.
- Förderlogik: Jugendgruppenmitglieder erhalten je Position Förderung über `Element-Fördersatz * Hilfssatz * Berufssatz`.
- Kiosk: privater PIN-Login mit Browser-Session unter `/kiosk/` und zentraler Gemeinschaftsmodus mit automatischer Abmeldung unter `/central/kiosk/`.
- PWA und Push: getrennte Installationen für Verwaltung, private Geräte und zentrale Kiosks; Push ist nur auf privaten Geräten verfügbar und wird über eine Datenbank-Outbox zugestellt.
- E-Mail: Admins konfigurieren SMTP im Webinterface und bestätigen Informations- oder Rechnungsversand erst nach einer exakten Empfängervorschau.
- Dienstplanung: tägliche Vorlagen, automatische Generierung über den Lagerzeitraum, manuelle Dienste, Soll-Dienste anhand gebuchter Nächte, Fortschrittsanzeige, Besetzungsauswertung und Tauschangebote.
- Buchungsbearbeitung: Admins können Kostenpositionen stornieren, wiederherstellen und korrigieren; abrechnungsrelevante Änderungen werden im Audit-Protokoll gespeichert.
- Teilnehmerverwaltung: Bearbeiten, verlustfreies Archivieren und Wiederherstellen; archivierte Teilnehmer bleiben historisch nachvollziehbar, sind aber nicht im Kiosk oder in neuen Abrechnungsläufen sichtbar.
- Abrechnung: Live-Berechnung in `src/billing/services.py` sowie unveränderliche, versionierte Lagerläufe mit Bearbeiter, Zeitpunkt und historischen Exporten.
- Import/Export: Teilnehmerimport per CSV/XLSX, Abrechnungsexporte als Lager-CSV, Getränke-CSV, Excel-Arbeitsmappe und Einzelabrechnung als PDF-Vorschau im Browser.

## Projektstruktur

- [`../README.md`](../README.md): Einstieg, Setup, Tests, Rollen und Roadmap.
- [`../FILES.md`](../FILES.md): schnelle Dateiübersicht.
- [`../src/billing/README.md`](../src/billing/README.md): Domain-App mit Modellen, Services, Views, Import/Export und Rollen.
- [`../src/config/README.md`](../src/config/README.md): Django-Projektkonfiguration.
- [`../src/templates/README.md`](../src/templates/README.md): servergerenderte Templates.
- [`../src/static/billing/README.md`](../src/static/billing/README.md): CSS und statische Assets.
- [`../scripts/README.md`](../scripts/README.md): lokale Hilfsskripte.
- [`../tests/README.md`](../tests/README.md): Teststruktur und Testbefehle.
- [`../tests/e2e/README.md`](../tests/e2e/README.md): Playwright-End-to-End-Tests.
- [`passkeys.md`](passkeys.md): Passkey-Betrieb, Sicherheitsgrenzen und Recovery.
- [`pwa-push.md`](pwa-push.md): PWA-Gerätemodi, Offline-Grenzen, VAPID-Konfiguration und Push-Worker.
- [`email-delivery.md`](email-delivery.md): manuelle Empfängerauswahl, verschlüsselte SMTP-Konfiguration und E-Mail-Outbox.

## Zentrale Codebereiche

`src/billing/models.py` enthält das Datenmodell für Lager, Nutzerprofile, Teilnehmer, Preisregeln, Kosten, Zahlungen, Auslagen, Kiosk-PINs, Mahlzeiten, Dienstpläne und Abrechnungsläufe.

`src/billing/services.py` enthält die Abrechnungslogik und Audit-Helfer. Hier werden Lagerpauschalen automatisch ausgewählt, Förderung berechnet, Kiosk-Zusammenfassungen erzeugt und Buchungsänderungen vergleichbar protokolliert.

`src/billing/forms.py` enthält die Formulare für Admin, Bearbeiter und Kiosk. Die Preisverwaltung nutzt eine eigene Matrix für die vier Lagerpauschalen und ein separates Formular für Standardpreise von Frühstück und Abendessen.

`src/billing/views.py` enthält die servergerenderten Seiten für Setup, Nutzerverwaltung, Lager, Teilnehmer, Preisverwaltung, Mahlzeiten, Dienstplanung, Import/Export und Kiosk.

## Screenshots

- [Admin-Lagerübersicht](images/admin-camp-overview.png)
- [Dienstplanung im Kiosk](images/kiosk-shift-planning.png)

## Importformat

Teilnehmer können per CSV oder XLSX importiert werden. Pflichtspalten sind `first_name` und `last_name`. Weitere unterstützte Spalten sind `email`, `phone`, `status`, `is_child`, `is_youth_group`, `is_companion`, `hilfssatz`, `berufssatz`, `booked_nights`, `actual_nights` und `notes`.

Boolesche Werte akzeptieren unter anderem `1`, `true`, `ja`, `yes` und `x`. Dezimalwerte dürfen Komma oder Punkt verwenden. XLSX-Dateien werden anhand ihres Inhalts geprüft; eine Excel-Datei mit falscher Endung wird abgewiesen.

## Exporte

- Lagerabrechnung als CSV: Nachname, Vorname, Brutto, Förderung, Soll, Gezahlt, Vorgestreckt und Offen.
- Getränke als CSV: historische `DrinkEntry`-Daten und aktuelle Kiosk-Getränkebuchungen aus `Charge`.
- Excel-Arbeitsmappe: Blatt `Abrechnung` plus Blatt `Teilnehmer`.
- Einzelabrechnung als PDF: Positionen und Summen für einen Teilnehmer, als Browser-Vorschau mit Downloadmöglichkeit im PDF-Viewer.
- Gespeicherte Lagerläufe: versionsgebundene CSV- und Excel-Dateien sowie PDF-Snapshots je Teilnehmer als Browser-Vorschau.

## Lokaler Start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
npm install
python src/manage.py migrate
python src/manage.py runserver
```

Danach läuft die Anwendung lokal unter `http://localhost:8000`.

## Tests

```bash
.venv/bin/python src/manage.py check
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy src
```

Für Browsertests:

```bash
npm run test:e2e
```

Der lokale Sammellauf ist:

```bash
npm run test:local
```

## CI/CD & Automatisierung

Alle automatisierten GitHub-Actions-Workflows liegen in `.github/workflows/`:
- **Tests** (`ci.yml`): Lokale Tests und Playwright.
- **Docker** (`docker.yml`): Image Build, Test & Push zur Container Registry.
- **Sicherheit** (`security.yml`): Trivy Vulnerability Scans.
- **Compliance** (`pr-title.yml`, `changelog-check.yml`): Erzwingt Semantic PR Titles und zwingende Changelog-Einträge bei Code-Änderungen.
Dependabot hält die Abhängigkeiten aktuell.

## Qualitäts- und Sicherheitsregeln

Die Beitragsregeln stehen in [`../CONTRIBUTING.md`](../CONTRIBUTING.md), die Agentenregeln in [`../AGENTS.md`](../AGENTS.md).

- Ruff ist das Standardwerkzeug für Linting und Formatierung.
- pre-commit führt lokale Qualitäts- und Secret-Checks aus.
- Neue Python-Funktionen sollen Type Hints nutzen.
- Django-ORM-Code soll N+1-Abfragen vermeiden und kritische Finanzoperationen transaktional ausführen.
- `.env`-Dateien, personenbezogene Daten, Zahlungsdetails, PINs und Secrets dürfen nicht committed oder geloggt werden.
- Servergerenderte Templates sollen semantisches HTML, mobile-first Layouts, barrierearme Formulare und modernes Vanilla JavaScript verwenden.

## HTML-Dokumentation

Die wichtigsten Übersichten liegen zusätzlich als HTML vor:

- [`index.html`](index.html): Gesamtübersicht.
- [`user_guide.html`](user_guide.html): Benutzerhandbuch für Teilnehmer, Abrechner, Bearbeiter und Admins.
- [`architecture.html`](architecture.html): Architektur, Datenfluss und Abrechnungslogik.
- [`operations.html`](operations.html): Setup, Betrieb, Tests und typische Admin-Abläufe.
- [`development.html`](development.html): Beitragsregeln, Tooling, Security, ORM, Tests und UI-Konventionen.
