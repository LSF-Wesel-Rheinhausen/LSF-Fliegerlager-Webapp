# Fliegerlager-Abrechnung

Web-App zur Verwaltung und Abrechnung eines Vereins-Fliegerlagers. Die Anwendung ist als Docker-basierte Django-App mit PostgreSQL vorbereitet und kann lokal auch mit SQLite laufen.

## Funktionen in V1

- Lager/Jahre mit Preisen und Abrechnungsregeln verwalten
- Vereinsnutzer mit E-Mail-/Passwort-Login und Rollen `Admin` und `Bearbeiter`
- Teilnehmer, Zahlungen, Kostenpositionen und vorgestreckte Beträge pflegen
- Server-seitige Abrechnung je Teilnehmer und Gesamtauswertung je Lager
- Vorbereitung für Teilnehmer-Kiosk: PINs, Essensanmeldungen und Getränkebuchungen im Datenmodell und in Services
- CSV-/Excel-Import mit Vorschau und Validierung
- CSV-, Excel- und PDF-Export für Abrechnungen

## Lokale Entwicklung

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
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
pytest
```

To run the test suite automatically before each commit, enable the project Git hooks once:

```bash
git config core.hooksPath .githooks
```

## Rollen

Die Rollen werden über Django-Gruppen abgebildet:

- `Admin`: Nutzer, Lager, Preise, Kategorien und Teilnehmer-PINs verwalten
- `Bearbeiter`: Teilnehmer, Zahlungen, Kosten und Abrechnungen bearbeiten

Superuser haben automatisch vollen Zugriff.
