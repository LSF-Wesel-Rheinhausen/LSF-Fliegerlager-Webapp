# Kiosk-Autorisierungsgrenzen

## Zusammenfassung

- Ordnet historische Abrechnungen ausschließlich dem exakt angemeldeten
  Teilnehmerdatensatz zu.
- Verweigert PDF-Zugriffe, die bisher nur über gleiche Namen, E-Mail-Adressen
  oder Begleitpersonennamen autorisiert wurden.
- Schließt verknüpfte Buchungsteilnehmer aus dem Check-in aus, damit ein Kiosk
  deren Anreise- und Abreisedaten nicht verändern kann.

## Geänderte Dateien

- `src/billing/views.py`
- `src/templates/billing/kiosk_home.html`
- `tests/test_kiosk.py`
- `tests/test_kiosk_camp_phases.py`

## Tests

- Regressionstests für Abrechnungszugriffe über Namens-, E-Mail- und
  Begleitpersonenkollisionen.
- Regressionstests für Anzeige und manipulierte Übermittlung verknüpfter
  Check-in-Teilnehmer.
- Vollständiger lokaler Prüfablauf einschließlich Pytest, Playwright, Ruff,
  Django-Systemcheck und mypy.

## Offene Punkte

- Eine spätere explizite, unveränderliche Personenidentität kann berechtigte
  lagerübergreifende Abrechnungshistorien wieder ermöglichen, ohne auf
  veränderliche Attribute zurückzugreifen.
