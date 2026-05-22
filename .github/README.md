# `.github`

GitHub-spezifische Projektdateien.

- `workflows/ci.yml`: CI-Workflow fuer Python-Setup, Node-Setup, Django-Check, Pytest und Playwright-E2E.

Der Workflow installiert Playwright-Browser in CI mit `npx playwright install --with-deps`, damit die benoetigten Linux-Bibliotheken vorhanden sind.
