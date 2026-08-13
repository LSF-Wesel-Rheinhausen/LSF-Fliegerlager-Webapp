# Frühstück im Kiosk vorbestellen

## Zusammenfassung

Der Kiosk zeigt Frühstück als zusätzliche Schnellbuchung. Über den sekundären Vorbestell-CTA
öffnet sich ein eigener Frühstückskalender mit getrennten Preisen, Beschreibungen, Statuswerten
und ARIA-Beschriftungen; der bestehende Abendessenkalender bleibt unverändert.

## Geänderte Dateien

- `src/billing/views.py`
- `src/templates/billing/kiosk_base.html`
- `src/templates/billing/includes/kiosk_quick_targets.html`
- `src/templates/billing/kiosk_home.html`
- `tests/test_kiosk.py`
- `tests/e2e/fliegerlager.spec.js`

## Tests

- Frühstücks-Regressionen für fehlende Preise, ungültige Tage, Duplikate, Familienmitglieder,
  Cutoff und unbekannte Ziele
- bestehende Kiosk- und Essenskalender-Regressionen
- Playwright-Flow für primäre Frühstücks-Schnellbuchung, Zielvalidierung, Vorbestellung,
  Zielzusammenfassung und Rückkehr über „Ändern“
- deterministischer Legacy-Deep-Link `#meal-calendar` und zustandsbasierte native
  Dialogübergaben mit genau einem offenen Dialog
- unterbrechungsfreier Hintergrund-Scroll-Lock bei serialisierten Dialogübergaben sowie
  Aktualisierung des PWA-Caches auf Version 34
- stabilisierte Rückwechsel zwischen Frühstücks-Zielauswahl und Frühstückskalender ohne
  stale Rücksprungdialoge oder dauerhaft gehaltenen Scroll-Lock
- zustandsbasierte native Dialogübergaben warten auf WebKits vollständigen Top-Layer-Abbau,
  bevor der Folgedialog geöffnet und aktionsfähig wird

## Offene Punkte

- Keine; die Schnellbuchung bleibt die primäre Kiosk-Aktion.
