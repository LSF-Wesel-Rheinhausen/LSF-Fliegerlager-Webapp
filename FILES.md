# Dateiuebersicht

Diese Datei gibt spaeteren Chats einen schnellen Einstieg in die Projektstruktur.

- `README.md`: Projektbeschreibung, Setup, Tests, Rollen und Roadmap.
- `CONTRIBUTING.md`: Beitragsregeln, Tooling, Security-, ORM- und Agentenrichtlinien.
- `AGENTS.md`: Arbeitsregeln fuer Agenten im Repository.
- `docs/`: zentrale Projektdokumentation als Markdown und statische HTML-Seiten inklusive Architektur, Betrieb, Import/Export, Dienstplanung, Konfiguration und Entwicklung.
- `docs/images/`: Screenshots der Admin-Lagerübersicht und der Dienstplanung im Teilnehmer-Kiosk.
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
- `.github/workflows/ci.yml`: GitHub-Actions-Workflow fuer lokale Python- und Browsertests.
- `.github/workflows/docker.yml`: GitHub-Actions-Workflow fuer den Docker-Build und Push zur Container Registry.
- `.github/workflows/security.yml`: Trivy Vulnerability Scanner fuer Code und Dependencies.
- `.github/workflows/pr-title.yml`: Enforcer fuer Semantic Pull Request Titel.
- `.github/workflows/changelog-check.yml`: Ueberpruefung auf zwingende Changelog-Eintraege.
- `.github/dependabot.yml`: Automatisierte Updates fuer npm, pip und GitHub Actions.
- `src/manage.py`: Django-CLI-Einstieg.
- `src/config/`: Django-Projektkonfiguration, URL-Routing, ASGI/WSGI.
- `src/billing/`: Domain-App fuer Lager, Nutzerprofile, Teilnehmer, Mahlzeiten, Dienstplaene, Abrechnung, Importe, Exporte und Rollen.
- `src/static/billing/`: Stylesheet und Vereinslogo.
- `src/templates/`: Servergerenderte Django-Templates inklusive Kiosk und Preisverwaltung.
- `tests/`: Pytest-Tests, `factory_boy`-Factories und Playwright-E2E-Tests fuer Auth, Rollen, Nutzerverwaltung, Migrationen, Import/Export, Abrechnung, Kiosk, Preisverwaltung, Mahlzeiten, Dienstplaene, Buchungs-Audit und View-Berechtigungen.
- `graphify-out/`: generierter Wissensgraph, HTML-Visualisierung, Wiki und Architekturbericht fuer Agentenabfragen.
