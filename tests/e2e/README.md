# `tests/e2e`

Playwright-End-to-End-Tests.

`fliegerlager.spec.js` folgt dem Stil von `windenbuch.spec.js`: kleine Hilfsfunktionen, role-/label-basierte Selektoren und echte Browserablaeufe.

Die Tests pruefen:

- Ersteinrichtung mit erstem Admin.
- Login und Logout.
- Lageranlage.
- Deutsche Aktionslabels und Exportlinks.
- Sichtbares Vereinslogo und geladenes CSS.
- Desktop- und iPhone-Viewports ohne unerwarteten horizontalen Overflow.

Vor lokalen E2E-Laeufen muessen die Playwright-Systemabhaengigkeiten installiert sein:

```bash
npx playwright install-deps
```
