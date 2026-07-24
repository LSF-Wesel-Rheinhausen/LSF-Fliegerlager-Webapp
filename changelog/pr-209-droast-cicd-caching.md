# CI/CD Performance- und Caching-Optimierung

- Die GitHub Actions Workflows (Tests, DAST Scan, Security Scan) überspringen nun automatisch reine Dokumentations- und Graphify-Änderungen (`graphify-out/**`, `*.md`, `docs/**`), um CI-Zeiten drastisch zu verkürzen.
- Die Installation von Playwright-Systemabhängigkeiten in der CI wird nun bei bestehendem Browser-Cache übersprungen.
