# `.github/workflows`

GitHub-Actions-Workflows.

- `ci.yml`: Fuehrt auf Pull Requests und Pushes nach `main` mit Python 3.13 und Node 22 den Django-Systemcheck, die vollstaendige Pytest-Suite sowie Playwright in Chromium, Firefox und WebKit aus.
- `docker.yml`: Baut das Docker-Image, prueft es mit `python manage.py check` und pusht bei Merge nach `main` Tags nach `ghcr.io`.
- `security.yml`: Fuehrt Trivy im Repository-Modus bei Push, Pull Request und woechentlich aus; hohe und kritische Findings schlagen fehl.
- `pr-title.yml`: Erzwingt Conventional-Commit-/Semantic-PR-Titel.
- `changelog-check.yml`: Prueft bei Aenderungen unter `src/`, ob ein Changelog-Eintrag vorhanden ist.

Dependabot wird ueber `.github/dependabot.yml` konfiguriert und aktualisiert pip-, npm- und GitHub-Actions-Abhaengigkeiten.
