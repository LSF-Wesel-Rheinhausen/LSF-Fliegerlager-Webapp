# Kein Inaktivitäts-Timer im öffentlichen Kiosk-Login

## Zusammenfassung

- Der öffentliche Login des zentralen Kiosks zeigt keinen Abmelde-Countdown mehr.
- Das clientseitige Auto-Logout-Skript startet erst auf authentifizierten zentralen Kiosk-Seiten.
- Der serverseitige 120-Sekunden-Session-Timeout und private Kiosk-Abläufe bleiben unverändert.

## Geänderte Dateien

- `src/billing/views.py`
- `tests/test_pwa.py`
- `tests/e2e/pwa.spec.js`

## Tests

- Backend-Regressionen für GET und ungültigen POST auf dem zentralen Login.
- Positive Gegenprobe für den Timer nach erfolgreicher zentraler Anmeldung.
- Playwright-Regression für die öffentliche zentrale Login-Seite.

## Offene Punkte

- Keine.
