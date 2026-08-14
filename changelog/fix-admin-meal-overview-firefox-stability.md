## Stabilisierung des Firefox-Admin-Meal-Overview-E2E-Tests

Der Test verwendet für Admin und Kiosk getrennte Browser-Kontexte. Dialogwechsel
werden über die vorhandenen Close-Controls und explizite native Dialogzustände
abgeschlossen; unnötige Logout-/Login-Navigation entfällt.

### Root Cause

Nach dem Speichern der Abendessenbuchung schließt der native Dialog zunächst und
öffnet den Kalender erst nach dem Modal-Teardown wieder. Zwei unmittelbar
aufeinanderfolgende Escape-Tasten konnten daher den noch geschlossenen Zustand
treffen und den Kalender offen lassen. Der anschließende Logout wurde vom offenen
Kalender abgefangen. Der spätere Admin-Login konnte zusätzlich einen abgebrochenen
`passkeys.js`-GET als Requestfehler melden.

### Tests

- Firefox fokussiert, 10 Wiederholungen: grün.
- Chromium/WebKit fokussiert: grün.
- Requestfehler bleiben streng; kein neuer Filter und keine Force-Klicks oder Sleeps.
