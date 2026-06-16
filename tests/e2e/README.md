# `tests/e2e`

Playwright-End-to-End-Tests.

`fliegerlager.spec.js` folgt dem Stil von `windenbuch.spec.js`: kleine Hilfsfunktionen, role-/label-basierte Selektoren und echte Browserablaeufe.

Die Tests pruefen:

- Ersteinrichtung mit erstem Admin.
- Login und Logout.
- Lageranlage.
- Deutsche Aktionslabels und Exportlinks.
- Admin-Bearbeitung einer Buchung inklusive sichtbarem Änderungsprotokoll.
- Native Dialoge fuer das Anlegen und Bearbeiten von Preisregeln.
- Dienstvorlagen, Dienstgenerierung sowie Uebernahme und Tausch im Teilnehmer-Kiosk.
- Kiosk-Buchungen fuer Getraenke und Mahlzeiten inklusive PIN-Ersteinrichtung.
- Sichtbares Vereinslogo und geladenes CSS.
- Desktop- und iPhone-Viewports ohne unerwarteten horizontalen Overflow.

Vor lokalen E2E-Laeufen muessen die Playwright-Systemabhaengigkeiten installiert sein:

```bash
npx playwright install-deps
npx playwright install
npm run test:e2e
```

Playwright startet standardmaessig einen isolierten Django-Testserver ueber `scripts/start-e2e.sh` und nutzt `tmp/e2e.sqlite3`. Die Suite laeuft voll parallel in Chromium, Firefox und WebKit; in CI werden zwei Worker und ein Retry verwendet. Das Startskript entfernt veraltete Server-/Datenbankreste, damit keine Zombie-Prozesse Folgelaeufe blockieren. Mit `PLAYWRIGHT_USE_EXTERNAL_SERVER=1` kann stattdessen ein bereits laufender Server gegen `PLAYWRIGHT_BASE_URL` verwendet werden.

In GitHub Actions werden die Browser-Binaries in `~/.cache/ms-playwright` mit einem Cache-Key aus `package-lock.json` wiederverwendet. Bei Cache-Hit installiert CI nur die Systemabhaengigkeiten; bei Cache-Miss laedt Playwright die Browser neu.
