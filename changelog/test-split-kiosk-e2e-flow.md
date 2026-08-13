# WebKit-stabile Kiosk-E2E-Flows

## Zusammenfassung

Der bisher kombinierte Kiosk-E2E-Ablauf wird in fachlich abgegrenzte Tests mit
unabhängigem Setup und klaren Dialog-Postconditions aufgeteilt. Dadurch lassen
sich WebKit-Übergänge gezielt diagnostizieren und parallel nach Browserprojekt
ausführen, ohne fachliche Assertions zu verlieren.

## Tests

- Die bestehenden Kiosk-Assertions bleiben erhalten und werden auf getrennte
  Login-, Buchungs-, Kalender-, Dialog- und Nachlauf-Flows verteilt.
