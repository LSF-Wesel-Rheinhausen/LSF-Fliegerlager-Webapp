# Mobile Layout-Fixes

## Zusammenfassung

- Mobile Admin- und Kiosk-Texte brechen nicht mehr mitten im Wort um.
- Kiosk-Essen- und Getränkebereiche werden auf iPhone-Hochformat gegen unerwarteten Overflow geprüft.

## Geänderte Bereiche

- Globale CSS-Wrapping-Regeln für Tabellen, Navigation, Kiosk-Karten und Essensbuchungen
- Playwright-Regressionstest für mobile Kiosk-Ansichten

## Tests

- `npx playwright test tests/e2e/fliegerlager.spec.js -g "Kiosk meal and drink layout has no mobile overflow" --project=chromium`
