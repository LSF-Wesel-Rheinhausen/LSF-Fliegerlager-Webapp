# Sichere Seitenumbrüche für Rechnungs-PDFs

## Zusammenfassung

- Mehrseitige Rechnungen reservieren Platz für Summenblock und Zahlungsinformationen.
- Positionszeilen, Summen und Zahlungsboxen bleiben oberhalb der Fußzeile.
- Aktuelle und archivierte Rechnungs-PDFs verwenden dieselbe Seitenumbruchlogik.

## Geänderte Dateien

- `src/billing/exporters.py`
- `tests/test_exporters.py`

## Tests

- Regressionstest für lange aktuelle Rechnungen.
- Regressionstest für lange archivierte Rechnungen aus Settlement-Snapshots.

## Offene Punkte

- Keine.
