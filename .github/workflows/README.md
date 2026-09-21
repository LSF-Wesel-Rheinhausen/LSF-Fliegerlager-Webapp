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
- `docker.yml`: Baut und prueft alle PRs direkt unter `pull_request` ohne Schreibrechte oder Publikation, auch wenn die neue `workflow_run`-Definition noch nicht auf `main` liegt. Same-Repository-PRs und `main` starten nach erfolgreichen `Tests`-Laeufen zusaetzlich als `workflow_run`; der lesende Testjob baut exakt dessen Head-SHA mit dem deterministischen Commit-Zeitstempel als OCI-Builddatum. Bei Same-Repository-PRs uebergibt er die getesteten Images als kurzlebiges Artefakt; nur der getrennte Publish-Job mit `packages: write` laedt, validiert und publiziert sie, ohne PR-Code auszufuehren. Der bewegliche Dev-Tag wird nach der vertrauenswuerdigen Test-Workflow-Run-ID geordnet und ignoriert damit vom PR kontrollierte OCI-Zeitstempel. Fuer `main` prueft der Publish-Job den aktuellen Branch-Head vor beweglichen Tags. App- und Update-Agent-BuildKit-Caches bleiben ueber getrennte Scopes isoliert.
- `security.yml`: Fuehrt Trivy im Repository-Modus bei Push, Pull Request und woechentlich aus; hohe und kritische Findings schlagen fehl.
- `dast.yml`: Trennt den unprivilegierten Pull-Request-Scan vom vertrauenswürdigen Push-/Schedule-Scan; nur letzterer darf Issues schreiben. Beide Jobs bauen die Anwendung, starten sie über `scripts/dast-lifecycle.sh`, pollen `/healthz/` mit einer 60-Sekunden-Grenze und räumen den Container mit `always()` auf. ZAP-Funde bleiben report-only; Start-, Healthcheck-, Timeout- und Cleanup-Fehler schlagen als Infrastrukturfehler fehl.
- `pr-title.yml`: Erzwingt Conventional-Commit-/Semantic-PR-Titel über `pull_request_target`; der Job checkt keinen Code aus und führt keinen Code aus.
- `changelog-check.yml`: Prueft bei Aenderungen unter `src/`, ob ein Changelog-Eintrag vorhanden ist.

Dependabot wird ueber `.github/dependabot.yml` konfiguriert und aktualisiert pip-, npm- und GitHub-Actions-Abhaengigkeiten.
