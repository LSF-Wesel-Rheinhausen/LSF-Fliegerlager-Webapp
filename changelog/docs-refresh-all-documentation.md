# Dokumentation, Screenshots und Tooling aktualisiert

## Zusammenfassung

- Gesamte Projektdokumentation mit Dienstplanung, Kiosk-PIN-Sperre, Nutzerprofilen, aktuellen Tests und CI-Abläufen abgeglichen.
- Root-README um Test-/Technologie-Badges sowie Screenshots der Admin-Lagerübersicht und der Kiosk-Dienstplanung ergänzt.
- Codex CLI, Graphify und die eingecheckte Graphify-Agentenintegration aktualisiert.

## Tests

- Django-Systemcheck: erfolgreich.
- Pytest: 208 Tests erfolgreich, 88 % Branch-Coverage in `src/billing`.
- Playwright: 48 Tests erfolgreich in Chromium, Firefox und WebKit.
- mypy sowie HTML-/Linkprüfung: erfolgreich.
- Ruff-Gesamtlauf: bestehende Formatierungsabweichungen in den bereits gemergten Dienstplan-Dateien; der Dokumentationspatch enthält keinen Python-Code.

## Offene Punkte

- Keine.
