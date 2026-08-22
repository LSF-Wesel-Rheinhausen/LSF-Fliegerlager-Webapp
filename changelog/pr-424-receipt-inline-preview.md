# Belegvorschau im Browser

## Zusammenfassung

Unterstützte PDF- und Bildbelege werden im geschützten Beleg-Endpoint inline mit
explizitem MIME-Typ ausgeliefert. Unbekannte Dateiendungen bleiben als sichere
Downloads mit `application/octet-stream` geschützt.

## Geänderte Dateien

- `src/billing/views.py`
- `tests/test_view_permissions.py`

## Tests

Die vollständigen lokalen Prüfungen werden vor dem Commit ausgeführt.

## Offene Punkte

Keine.
