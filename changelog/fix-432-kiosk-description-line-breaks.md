# Zeilenumbrüche in Dienstbeschreibungen

## Zusammenfassung

Mehrzeilige Dienstbeschreibungen behalten ihre sichtbaren Zeilenumbrüche im Kiosk-Info-Dialog. Lange ununterbrochene Inhalte werden innerhalb des Dialogs umgebrochen und verursachen auch auf mobilen Ansichten keinen horizontalen Overflow.

## Geänderte Bereiche

- Der Kiosk-Hilfetext stellt vorhandene Zeilenumbrüche mit `white-space: pre-wrap` dar.
- `overflow-wrap: anywhere` hält lange ununterbrochene Inhalte innerhalb des Dialogs.
- Die PWA-Cache-Version wurde erhöht, damit das geänderte Stylesheet ausgeliefert wird.
- Der bestehende Browser-Test deckt mehrzeilige Beschreibungen und mobilen Overflow ab; Fallback und Escaping bleiben unverändert.
- Zwei bestehende lange WebKit-Szenarien erhalten testlokal ausreichend Zeit, ohne ihre Assertions zu verändern.

## Tests

- TDD: Der erweiterte Chromium-Test schlug vor der CSS-Änderung mit `white-space: normal` statt `pre-wrap` fehl.
- Fokussierte Pytest- und Playwright-Prüfungen sowie die vollständige lokale Verifikation laufen grün.

## Offene Punkte

Keine.
