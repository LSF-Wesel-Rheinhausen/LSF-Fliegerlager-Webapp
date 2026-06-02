# Dateiuebersicht

Diese Datei gibt spaeteren Chats einen schnellen Einstieg in die Projektstruktur.

- `README.md`: Projektbeschreibung, Setup, Tests, Rollen und Roadmap.
- `CONTRIBUTING.md`: Beitragsregeln, Tooling, Security-, ORM- und Agentenrichtlinien.
- `AGENTS.md`: Arbeitsregeln fuer Agenten im Repository.
- `docs/`: zentrale Projektdokumentation als Markdown und statische HTML-Seiten inklusive Architektur, Betrieb und Entwicklung.
- `.pre-commit-config.yaml`: pre-commit-Konfiguration fuer Basischecks, Ruff und gitleaks.
- `pyproject.toml`: Ruff- und mypy-Konfiguration.
- `.env.example`: Beispielkonfiguration fuer Docker/Deployment.
- `.gitignore`: Ausgeschlossene lokale Dateien, Caches, Node-Module und Testartefakte.
- `.githooks/pre-commit`: Git-Hook zum Ausfuehren der Tests vor Commits.
- `Dockerfile`: Produktionsnahes Python-Image fuer die Django-App.
- `docker-compose.yml`: App plus PostgreSQL fuer Containerbetrieb.
- `package.json`: Playwright-/E2E-Scripts und Node-Entwicklungsabhaengigkeiten.
- `playwright.config.js`: Playwright-Konfiguration mit Django-Testserver und Browserprojekten.
- `pytest.ini`: Pytest-/pytest-django-Konfiguration.
- `requirements.txt`: Python-Laufzeitabhaengigkeiten.
- `requirements-dev.txt`: Python-Testabhaengigkeiten.
- `scripts/`: Lokale Hilfsskripte fuer Setup, Start, Cleanup, E2E-Server und Sammeltests.
- `.github/workflows/ci.yml`: GitHub-Actions-Workflow fuer Python- und Browsertests.
- `src/manage.py`: Django-CLI-Einstieg.
- `src/config/`: Django-Projektkonfiguration, URL-Routing, ASGI/WSGI.
- `src/billing/`: Domain-App fuer Lager, Teilnehmer, Abrechnung, Importe, Exporte und Rollen.
- `src/static/billing/`: Stylesheet und Vereinslogo.
- `src/templates/`: Servergerenderte Django-Templates inklusive Kiosk und Preisverwaltung.
- `tests/`: Pytest-Tests und Playwright-E2E-Tests.
