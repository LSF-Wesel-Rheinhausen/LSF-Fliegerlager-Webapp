# Hotfix #426: Linked meal calendar status

## Zusammenfassung

Partner-Essensanmeldungen bleiben in autorisierten Tagesdetails sichtbar, beeinflussen aber nicht mehr den Kalenderstatus des aktuell angemeldeten Teilnehmerkontos.

## Geänderte Dateien

- `src/billing/views.py`: Kalenderstatus auf das aktuelle Participant-Konto begrenzt.
- `tests/test_kiosk.py`: Regressionen für aktive/zurückgenommene Partner-Signups sowie Breakfast/Dinner ergänzt.
- `tests/e2e/fliegerlager.spec.js`: Partnerstatus und weiterhin autorisierte Rücknahme im Browser abgesichert.

## Tests

1. Vollständige pytest-Suite, Ruff/Format und Django-Check via `npm run test:local`
2. Fokussierter Partner-Playwright-Test in Chromium, Firefox und WebKit
3. `mypy src`

## Offene Punkte

Der vollständige Playwright-Lauf endete mit 237 bestanden / 1 übersprungen. Unter paralleler Last traten zwei WebKit-Timeouts auf; der Issue-#426-Test war nach `test.slow` browserübergreifend grün, und der unveränderte Masonry-Kontrolltest lief isoliert unter WebKit grün.
