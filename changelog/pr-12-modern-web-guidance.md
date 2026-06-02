# PR 12: Modern Web Guidance UI Refactoring

## Zusammenfassung
Umfangreiches Refactoring der UI nach modernen Web-Standards (Modern Web Guidance). Native `<dialog>` Elemente für Popups, semantische Definitionslisten (`<dl>`) für Metriken und verbesserte Formular-Zugänglichkeit (Labels, Autofill-Tokens).

## Geänderte Dateien
- `src/templates/billing/price_rules_manage.html` (Native Dialogs)
- `src/billing/forms.py` (Autofill, Inputmode)
- `src/templates/billing/camp_detail.html` & `kiosk_home.html` (Semantische Listen)
- `src/static/billing/app.css` (Styles)
- `tests/e2e/fliegerlager.spec.js` (E2E Tests)

## Tests
- 123 Pytest Backend-Tests passed
- 30 Playwright E2E-Tests passed (inkl. neuester Dialog-Test)

## Offene Punkte
- Keine.
