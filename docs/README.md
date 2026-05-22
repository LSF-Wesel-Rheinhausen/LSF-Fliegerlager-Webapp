# Projektdokumentation

Diese Dokumentation fasst die Fliegerlager-Webapp zusammen und verweist auf die Detaildokumente im Repository.

## Überblick

Die Anwendung ist eine Django-Webapp zur Verwaltung und Abrechnung eines Vereins-Fliegerlagers. Sie unterstützt Lager, Teilnehmer, Preisregeln, Förderlogik, Zahlungen, Auslagen, Import/Export und einen Kiosk-Modus für Teilnehmer.

Der typische Ablauf:

1. Ein Admin legt ein Lager an und pflegt den Lager-Fördersatz.
2. Teilnehmer werden manuell angelegt oder per CSV/XLSX importiert.
3. Preisregeln werden im Adminbereich gepflegt, inklusive Lagerpauschalen für 1/2 Wochen und Teilnehmer/Begleitpersonen.
4. Teilnehmer buchen im Kiosk Getränke und Essen per PIN.
5. Die Abrechnung berechnet Brutto, Förderung, Soll, Zahlungen, vorgestreckte Beträge und offenen Saldo.
6. Ergebnisse können als CSV, Excel-Arbeitsmappe oder PDF exportiert werden.

## Wichtige Funktionen

- Rollen: `Admin` und `Bearbeiter` über Django-Gruppen.
- Ersteinrichtung: Beim ersten Start kann der erste Admin im Browser angelegt werden.
- Preisverwaltung: eigene Admin-Route für Lagerpauschalen, Getränke, Essen und sonstige Preisregeln.
- Förderlogik: Jugendgruppenmitglieder erhalten Förderung über `Lager-Fördersatz * Hilfssatz * Berufssatz`.
- Kiosk: separater PIN-Login, PIN-Ersteinrichtung, Tablet-/Mobiloberfläche, automatische Abmeldung nach Inaktivität.
- Abrechnung: serverseitig in `src/billing/services.py`, damit UI, Export und Kiosk dieselbe Logik nutzen.
- Import/Export: Teilnehmerimport per CSV/XLSX, Abrechnungsexporte als CSV/XLSX/PDF.

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

## Zentrale Codebereiche

`src/billing/models.py` enthält das Datenmodell für Lager, Teilnehmer, Preisregeln, Kosten, Zahlungen, Auslagen, Kiosk-PINs und Abrechnungsläufe.

`src/billing/services.py` enthält die Abrechnungslogik. Hier werden Lagerpauschalen automatisch ausgewählt, Förderung berechnet und Teilnehmer-/Lagerzusammenfassungen erzeugt.

`src/billing/forms.py` enthält die Formulare für Admin, Bearbeiter und Kiosk. Die Preisverwaltung nutzt eine eigene Matrix für die vier Lagerpauschalen.

`src/billing/views.py` enthält die servergerenderten Seiten für Setup, Lager, Teilnehmer, Preisverwaltung, Import/Export und Kiosk.

## Lokaler Start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
npm install
python src/manage.py migrate
python src/manage.py runserver
```

Danach läuft die Anwendung lokal unter `http://localhost:8000`.

## Tests

```bash
.venv/bin/python src/manage.py check
.venv/bin/python -m pytest
```

Für Browsertests:

```bash
npm run test:e2e
```

Der lokale Sammellauf ist:

```bash
npm run test:local
```

## HTML-Dokumentation

Die wichtigsten Übersichten liegen zusätzlich als HTML vor:

- [`index.html`](index.html): Gesamtübersicht.
- [`architecture.html`](architecture.html): Architektur, Datenfluss und Abrechnungslogik.
- [`operations.html`](operations.html): Setup, Betrieb, Tests und typische Admin-Abläufe.
