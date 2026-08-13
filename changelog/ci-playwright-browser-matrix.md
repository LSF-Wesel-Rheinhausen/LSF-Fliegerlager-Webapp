# Browsermatrix für Playwright-CI

- Teilt Chromium-, Firefox- und WebKit-E2E-Läufe in eine fehl-fast-unabhängige Matrix auf.
- Bewahrt den bestehenden aggregierten Check `Browser UI tests` als Merge-Gate.
- Erzeugt browser- und run-spezifische Playwright-Reports und Testartefakte.

Offen: Die Branch Protection muss weiterhin den aggregierten Check `Browser UI tests`
verwenden; die drei Matrix-Jobs sind Diagnose-Checks.
