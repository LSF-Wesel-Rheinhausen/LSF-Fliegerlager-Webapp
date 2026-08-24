# `.github/workflows`

GitHub-Actions-Workflows.

## Playwright-Systemabhängigkeiten

Der Browser-Workflow cached die Playwright-Browser-Binaries in
`~/.cache/ms-playwright`. Die von `npx playwright install-deps` installierten
Systemabhängigkeiten werden dagegen absichtlich nicht gecacht: Sie verändern
die systemweite Runner-Installation über APT und sind an das konkrete
Ubuntu-Image, dessen Paketstände und dessen Architektur gebunden. Ein
gespeicherter APT- oder `/usr`-Cache wäre dadurch stale und nicht zuverlässig
wiederverwendbar. GitHub-hosted Runner werden ohnehin frisch bereitgestellt;
`install-deps` bleibt deshalb der wartbare und reproduzierbare Schritt pro
Browser-Lauf. Ein echtes OS-Image- oder Runner-Prebaking wäre eine separate
Infrastrukturentscheidung, keine zusätzliche Cache-Action.

Externe Actions sind aus Supply-Chain-Sicherheitsgründen auf vollständige, lowercase
40-stellige Commit-SHAs gepinnt. Der lesbare Release-Stand steht als Kommentar neben
dem SHA; lokale `./`-Actions sind davon ausgenommen. Änderungen an Workflow-Dateien
werden durch `tests/test_workflow_action_pins.py` rekursiv geprüft.

- `ci.yml`: Fuehrt jeden relevanten Pull Request und Push nach `main` aus. Der Job `Change scope` klassifiziert deterministisch reine Dokumentations-, Changelog- oder Graphify-Aenderungen; nur dann werden Quality-, Python-, PostgreSQL- und Browser-Pruefungen sicher uebersprungen. Der Diff wird mit Status und ohne Rename-Erkennung gelesen, damit technische Loeschungen und beide Seiten technischer-to-docs-Renames Full CI erzwingen; leere oder all-zero Base-SHAs erzwingen ebenfalls Full CI. Andere gemischte oder technische Aenderungen starten alle Pruefungen. Quality (Ruff, `mypy src`), Python (Django und vollstaendige Pytest-Suite) und die fehl-fast-unabhaengige Browser-Matrix fuer Chromium, Firefox und WebKit sind getrennt diagnostizierbar. Der aggregierte Job `CI gate` ist der stabile Branch-Protection-Check und akzeptiert Skips nur nach erfolgreicher docs-only-Klassifikation. Pip-Downloads, installierte Node-Abhaengigkeiten und Browser-Binaries werden anhand der jeweiligen Lock-/Versionsschluessel gecacht; Playwright-Reports und Testresultate werden nur bei Fehlern oder Abbruch und sieben Tage lang pro Browser und Run-ID archiviert. Veraltete PR-Laeufe werden abgebrochen.
- `docker.yml`: Baut und prueft App- sowie Update-Agent-Image fuer Pull Requests mit `contents: read`, ohne zu publizieren. Nach einem erfolgreichen `Tests`-Workflow auf dem vertrauenswürdigen `main`-Push läuft derselbe Docker-Testjob zuerst gegen exakt dessen SHA; erst danach publiziert der abhängige `workflow_run`-Job diesen SHA. Er bricht ab, wenn `refs/heads/main` inzwischen weitergelaufen ist. Nur dieser Job erhält zusätzlich `packages: write`; Fork-/PR-Pfade erfüllen die Read-only-Bedingung. App- und Update-Agent-BuildKit-Caches bleiben über getrennte Scopes isoliert.
- `security.yml`: Fuehrt Trivy im Repository-Modus bei Push, Pull Request und woechentlich aus; hohe und kritische Findings schlagen fehl.
- `dast.yml`: Trennt den unprivilegierten Pull-Request-Scan vom vertrauenswürdigen Push-/Schedule-Scan; nur letzterer darf Issues schreiben.
- `pr-title.yml`: Erzwingt Conventional-Commit-/Semantic-PR-Titel über `pull_request_target`; der Job checkt keinen Code aus und führt keinen Code aus.
- `changelog-check.yml`: Prueft bei Aenderungen unter `src/`, ob ein Changelog-Eintrag vorhanden ist.

Dependabot wird ueber `.github/dependabot.yml` konfiguriert und aktualisiert pip-, npm- und GitHub-Actions-Abhaengigkeiten.
