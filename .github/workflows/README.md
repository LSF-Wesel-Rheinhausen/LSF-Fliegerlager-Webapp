# `.github/workflows`

GitHub-Actions-Workflows.

- `ci.yml`: Fuehrt relevante Pull Requests und Pushes nach `main` mit getrennten Python- und Browser-Jobs aus. Python 3.13 prueft Django und die vollstaendige Pytest-Suite; Node 22 fuehrt Playwright in Chromium, Firefox und WebKit aus. Pip-Downloads, installierte Node-Abhaengigkeiten und Browser-Binaries werden anhand der jeweiligen Lock-/Versionsschluessel gecacht. Reine Dokumentations- und Changelog-Aenderungen starten diesen teuren Workflow nicht; veraltete PR-Laeufe werden abgebrochen.
- `docker.yml`: Baut und prueft App- sowie Update-Agent-Image, validiert das Beispiel-Compose und pusht bei Merge nach `main` jeweils `latest` und den Commit-SHA nach `ghcr.io`.
- `security.yml`: Fuehrt Trivy im Repository-Modus bei Push, Pull Request und woechentlich aus; hohe und kritische Findings schlagen fehl.
- `pr-title.yml`: Erzwingt Conventional-Commit-/Semantic-PR-Titel.
- `changelog-check.yml`: Prueft bei Aenderungen unter `src/`, ob ein Changelog-Eintrag vorhanden ist.

Dependabot wird ueber `.github/dependabot.yml` konfiguriert und aktualisiert pip-, npm- und GitHub-Actions-Abhaengigkeiten.
