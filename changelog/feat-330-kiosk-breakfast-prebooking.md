# Frühstück im Kiosk vorbestellen

## Zusammenfassung

Der Kiosk zeigt Frühstück als zusätzliche zukünftige Mahlzeit im bestehenden Essenskalender
und verwendet dafür denselben Buchungs-, Preis-, Frist-, Familien- und Rücknahmevertrag wie
das Abendessen.

## Geänderte Dateien

- `src/billing/views.py`
- `src/templates/billing/kiosk_home.html`
- `tests/test_kiosk.py`

## Tests

- Frühstücks-Regressionen für fehlende Preise, ungültige Tage, Duplikate, Familienmitglieder,
  Cutoff und unbekannte Ziele
- bestehende Kiosk- und Essenskalender-Regressionen

## Offene Punkte

- Keine; die Schnellbuchung bleibt die primäre Kiosk-Aktion.
