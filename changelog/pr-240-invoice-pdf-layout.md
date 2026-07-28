# Abrechnungs-PDFs mit klarer Seitenstruktur

## Zusammenfassung

- Nummeriert jede Seite der aktuellen und historischen Einzelabrechnungen.
- Stellt Datum und Buchungsnummern wie in der Kiosk-Detailansicht als dezente Metazeilen dar.
- Positioniert Trennlinien zwischen den Abrechnungspositionen, ohne den folgenden Text zu überlagern.

## Geänderte Dateien

- `src/billing/exporters.py`
- `tests/test_exporters.py`

## Tests

- Regressionstests für Seitenzahlen, Metadaten und kollisionsfreie Trennlinien beider PDF-Varianten.
- Visuelle Kontrolle einer dreiseitigen Beispielabrechnung als gerenderte PNG-Seiten.

## Offene Punkte

- Keine.
