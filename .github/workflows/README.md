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

- `ci.yml`: Fuehrt relevante Pull Requests und Pushes nach `main` mit getrennten Python- und Browser-Jobs aus. Python 3.13 prueft Django und die vollstaendige Pytest-Suite; der Browserjob laeuft als fehl-fast-unabhaengige Matrix fuer Chromium, Firefox und WebKit. Der aggregierte Job `Browser UI tests` bleibt als stabiler Branch-Protection-Check erhalten und schlaegt fehl, sobald ein Matrixjob fehlschlaegt. Pip-Downloads, installierte Node-Abhaengigkeiten und Browser-Binaries werden anhand der jeweiligen Lock-/Versionsschluessel gecacht; Reports und Testresultate werden pro Browser und Run-ID archiviert. Reine Dokumentations- und Changelog-Aenderungen starten diesen teuren Workflow nicht; veraltete PR-Laeufe werden abgebrochen.
- `docker.yml`: Baut und prueft App- sowie Update-Agent-Image mit `contents: read`; der getrennte Publish-Job wartet auf den Test-Job und erhält nur zusätzlich `packages: write`.
- `security.yml`: Fuehrt Trivy im Repository-Modus bei Push, Pull Request und woechentlich aus; hohe und kritische Findings schlagen fehl.
- `dast.yml`: Trennt den unprivilegierten Pull-Request-Scan vom vertrauenswürdigen Push-/Schedule-Scan; nur letzterer darf Issues schreiben.
- `pr-title.yml`: Erzwingt Conventional-Commit-/Semantic-PR-Titel über `pull_request_target`; der Job checkt keinen Code aus und führt keinen Code aus.
- `changelog-check.yml`: Prueft bei Aenderungen unter `src/`, ob ein Changelog-Eintrag vorhanden ist.

Dependabot wird ueber `.github/dependabot.yml` konfiguriert und aktualisiert pip-, npm- und GitHub-Actions-Abhaengigkeiten.
