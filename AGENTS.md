# Repository Guidelines

## Project Structure & Module Organization

Application code lives in `src/`. The Django project is in `src/config/`, and the domain app is in `src/billing/`.

- `src/billing/models.py` contains the camp, participant, pricing, payment, expense, kiosk-preparation, and settlement models.
- `src/billing/services.py` contains server-side settlement and kiosk-summary logic shared by UI and exports.
- `src/billing/importers.py` and `src/billing/exporters.py` contain CSV/XLSX/PDF import and export helpers.
- `src/templates/` contains server-rendered templates.
- `src/static/` contains static assets.
- `tests/` contains pytest-based automated tests.

Keep new modules small and domain-focused. Add root-level files only for global configuration, documentation, or build/deployment manifests.

## Build, Test, and Development Commands

Local setup:

- `python -m venv .venv`
- `. .venv/bin/activate`
- `pip install -r requirements-dev.txt`
- `python src/manage.py migrate`
- `python src/manage.py bootstrap_roles`
- `python src/manage.py createsuperuser`
- `python src/manage.py runserver`

Docker setup:

- `cp .env.example .env`
- `docker compose up --build`

Tests:

- `pytest`

Keep commands runnable from the repository root and document required environment variables in `.env.example`.

## Coding Style & Naming Conventions

Follow Django conventions and keep Python formatted with 4-space indentation. Use descriptive `snake_case` for Python modules, functions, fields, and variables. Use `PascalCase` for classes.

For HTML and CSS, use 2-space indentation. Keep templates presentation-focused; put business logic in services or model methods.

## Testing Guidelines

Use `pytest` and `pytest-django`. Place tests in `tests/` and name them after the behavior under test, for example `test_settlements.py` or `test_importers.py`.

Every new feature should include tests for expected behavior and a relevant edge case. At minimum, protect changes to settlement math, imports, permissions, and exports.

## Commit & Pull Request Guidelines

Git history is not available in this workspace, so no existing commit convention can be inferred. Use concise, imperative commit messages, for example `Add invoice total calculation` or `Fix participant import validation`.

Pull requests should include a summary, rationale, test results, and linked issues when available. Include screenshots or sample output for visible UI, report, or generated-file changes.

## Agent-Specific Instructions

Before editing, inspect the current tree. Keep changes narrowly scoped, avoid unrelated restructuring, and update this guide when build tools, tests, or conventions change.
Always start with the TODO.md file before doing anythin else. clear it after it is implemented. Treat it as user input.
