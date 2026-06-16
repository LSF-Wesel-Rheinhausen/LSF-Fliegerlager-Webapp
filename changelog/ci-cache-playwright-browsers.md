# Playwright-CI-Cache

## Zusammenfassung

- GitHub Actions cached Playwright-Browser-Binaries anhand von `package-lock.json`.
- CI installiert Systemabhaengigkeiten weiter in jedem Lauf, laedt Browser aber nur bei Cache-Miss.

## Geänderte Bereiche

- Test-Workflow und E2E-Dokumentation

## Tests

- Workflow statisch geprüft
