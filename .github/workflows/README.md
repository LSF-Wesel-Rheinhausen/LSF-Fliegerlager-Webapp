# `.github/workflows`

Die GitHub-Actions-Pipeline ist nach Verantwortung gegliedert. Längere Pull-Request-Workflows
brechen überholte Läufe automatisch ab; Main- und Zeitplanläufe bleiben davon unberührt. Jeder Job
hat ein festes Zeitlimit.

## CI und Container

- `ci.yml`: Führt bei jedem Push nach `main` sowie bei Pull Requests fünf klar getrennte
  Prüfgruppen aus:
  - `Detect relevant changes`: lässt bei reinen Dokumentations- oder Graphify-Änderungen die teuren
    Prüfungen aus, sorgt aber weiterhin für einen abschließenden Gate-Check
  - `Quality`: Ruff-Lint, Ruff-Formatprüfung, Django-Systemcheck und Mypy mit Python 3.13
  - `Python tests`: vollständige Pytest-Suite
  - `E2E`: parallele Matrix für Chromium, Firefox und WebKit im zur npm-Version passenden,
    digest-gepinnten Playwright-Container
  - `CI / Gate`: stabiler Sammelcheck für alle erforderlichen CI-Jobs
  Bei Browserfehlern werden Report, Traces, Screenshots und Django-Log sieben Tage lang als
  browserbezogenes Artefakt gespeichert.
- `docker.yml`: Baut und prüft App- sowie Update-Agent-Image und validiert das Deployment-Beispiel
  bei relevanten Pull Requests. Nach `main` werden `latest` und der Commit-SHA erst veröffentlicht,
  wenn der zugehörige `CI`-Lauf erfolgreich war und der getestete SHA weiterhin dem aktuellen
  Main-Stand entspricht. App und Updater verwenden getrennte BuildKit-Caches.

## Security

- `security.yml`: Führt Trivy im Repository-Modus bei Push, Pull Request und wöchentlich aus; hohe
  und kritische Findings schlagen fehl.
- `dast.yml`: Baut die Anwendung, wartet begrenzt auf `/healthz/` und führt anschließend den
  OWASP-ZAP-Baseline-Scan aus. Der Scan ist bewusst report-only, erstellt keine Issues und speichert
  seinen Bericht als Artefakt. Infrastruktur- oder Action-Fehler bleiben weiterhin sichtbar rot.

## Pull-Request-Richtlinien

- `pr-title.yml`: Erzwingt Conventional-Commit-/Semantic-PR-Titel beim Öffnen, Bearbeiten und
  Wiedereröffnen eines Pull Requests.
- `changelog-check.yml`: Prüft bei Änderungen unter `src/`, ob ein Changelog-Eintrag vorhanden ist.

Dependabot wird über `.github/dependabot.yml` konfiguriert und aktualisiert pip-, npm- und
GitHub-Actions-Abhängigkeiten. Die beiden dynamischen CodeQL-Läufe für Security und Code Quality
werden über die GitHub-Repository-Einstellungen verwaltet.
