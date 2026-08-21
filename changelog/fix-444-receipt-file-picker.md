# Receipt file picker

## Zusammenfassung

Entfernt den erzwungenen Kamera-Upload bei Rechnungsbelegen, damit Admins und
Kiosk-Teilnehmer vorhandene PDF- und Bilddateien auswählen können.

## Geänderte Dateien

- `src/billing/forms.py`: Entfernt `capture="environment"` aus beiden Beleg-Widgets.
- `tests/test_forms.py`: Sichert Widget-Attribute sowie gültige und manipulierte Uploads ab.

## Tests

- Fokussierte Formular-, Kiosk- und Admin-Belegtests

## Offene Punkte

- Keine.
