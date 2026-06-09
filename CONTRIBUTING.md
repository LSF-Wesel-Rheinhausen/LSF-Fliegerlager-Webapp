# Repository Guidelines & Best Practices

## 1. Project Structure & Module Organization

Application code resides in `src/`. The core Django project configuration is located in `src/config/`, and the main domain application is in `src/billing/`.

- `src/billing/models.py`: contains models for camps, user profiles, participants, pricing, payments, expenses, meals, kiosk access, shifts, and settlements.
- `src/billing/services.py`: encapsulates core business logic, including server-side settlement and kiosk-summary logic. Keep views thin and share complex calculations through services.
- `src/billing/importers.py` and `src/billing/exporters.py`: CSV/XLSX/PDF import and export helpers.
- `src/templates/`: server-rendered HTML templates.
- `src/static/`: static assets.
- `tests/`: pytest-based automated test suite.

Golden rule: keep new modules small, cohesive, and domain-focused. Root-level files are reserved for global configuration, documentation, or build/deployment manifests.

## 2. Build, Test, and Development Commands

### Local Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
npm install
python src/manage.py migrate
python src/manage.py bootstrap_roles
python src/manage.py createsuperuser
python src/manage.py runserver
```

The project currently uses `requirements.txt` and `requirements-dev.txt`. Prefer migrating to `uv` or Poetry with a deterministic lock file before adding larger dependency sets.

### Docker Setup

```bash
cp .env.example .env
docker compose up --build
```

Never commit `.env` files or real secrets. Keep only safe placeholders in `.env.example`. Secret scanning is configured through pre-commit and should also run in CI.

### Tests and Linting

```bash
.venv/bin/python src/manage.py check
.venv/bin/python -m pytest
ruff check .
ruff format --check .
mypy src
npm run test:e2e
```

Keep commands runnable from the repository root. All required environment variables must be documented with safe placeholder values in `.env.example`.

## 3. Coding Style & Naming Conventions

Python formatting and linting are enforced by Ruff. Code should pass pre-commit checks before pushing.

Use Python type hints for all new functions and methods, especially services, import/export helpers, and settlement code.

Naming:

- `snake_case` for modules, functions, variables, and database fields.
- `PascalCase` for classes.
- `UPPER_SNAKE_CASE` for constants.

Templates and CSS use 2-space indentation. Keep templates presentation-focused; business logic belongs in services or model properties.

## 4. Testing Guidelines

Use `pytest` and `pytest-django`. Place tests in `tests/` and name them after the behavior under test.

Every new feature must include tests covering the happy path and at least one edge or failure case.

Critical paths require strong coverage:

- settlement math and financial calculations
- data imports and parsing validation
- permission checks
- data exports
- kiosk booking flows
- meal ordering and shift assignment flows

## 5. Commit & Pull Request Guidelines

Use Conventional Commits:

- `feat: add invoice total calculation`
- `fix(import): resolve participant CSV validation error`
- `docs: update kiosk setup guide`
- `chore: add pre-commit configuration`

Pull requests should include a clear summary, rationale, test results, and linked issues when available. Include screenshots or sample output for visible UI changes, generated reports, or modified exports. CI must pass before review. **For features, major refactorings, and relevant bugfixes, a changelog entry MUST be created in the `changelog/` directory following the format `pr-<number>-<short-title>.md`.**

## 6. AI & Agent-Specific Instructions

Always read and process `TODO.md` before initiating work. Treat it as primary user input and clear implemented items once completed.

Before editing, inspect the current project tree. Keep changes narrowly scoped to the requested task. Do not perform unrelated restructuring.

Update this document whenever build tools, testing frameworks, or conventions change.

## 7. Django ORM & Performance Guidelines

AI agents must prioritize database performance and efficient ORM usage.

- Prevent N+1 queries: use `select_related()` for `ForeignKey` and `OneToOneField` relationships when queried data will be iterated in business logic or templates.
- Use `prefetch_related()` for `ManyToManyField` and reverse `ForeignKey` relationships when iterating related collections.
- Wrap critical financial operations, such as payments, settlements, kiosk bookings, and settlement persistence, in `transaction.atomic()` to preserve data integrity.
- Avoid raw SQL. Use the Django ORM natively. Only use `.raw()` or `connection.cursor()` if explicitly requested and heavily documented.

## 8. Security & Data Privacy

Billing data is sensitive. Treat participant details, payment details, and imported files accordingly.

- Never log personally identifiable information, payment details, raw passwords, PINs, or secrets.
- Do not use `print()` for diagnostics. Use Python's standard `logging` module.
- Do not use `except Exception: pass`. Catch specific exceptions such as `ValidationError` or `ObjectDoesNotExist`. If a broad top-level exception is unavoidable, log the stack trace immediately.
- Never trust user input or imported CSV/XLSX contents. Validate incoming data at the form, importer, or service layer before model instantiation.

## 9. Strict AI Behavior Constraints

- No hallucinated dependencies: do not import or use third-party libraries that are not already present in `requirements.txt`, `requirements-dev.txt`, or `pyproject.toml` without explicitly asking for permission first.
- Idempotency: Django management commands and data migration scripts must be safe to run multiple times without duplicating data or crashing.
- Ambiguity resolution: if a requirement in `TODO.md` is ambiguous, incomplete, or conflicts with the existing architecture, write a clarifying question as a comment at the top of `TODO.md` and stop execution.
- Refactoring boundaries: only modify files directly related to the current task. Do not perform drive-by refactorings of unrelated modules unless explicitly instructed.

## 10. Side Effects & Pure Functions

- Keep business logic in `services.py` as pure as practical. Isolate side effects, such as sending emails, calling external APIs, generating PDFs, or writing files, into dedicated helper functions or adapters.
- For CSV/PDF/XLSX exports, use robust temporary directories through `tempfile` or Django's `default_storage` API. Do not write generated files to hardcoded relative paths.

## 11. Advanced Testing & Mocking

- Automated tests must never hit external network resources, real APIs, or send real emails.
- Use `unittest.mock` or `pytest-mock` to patch external services, file system operations, and time-sensitive behavior.
- When generating larger reusable test data, prefer `factory_boy` factories over scattered ORM `.create()` calls. If `factory_boy` is not yet installed, ask before adding it.

## 12. Security: Cryptography & File Handling

- Never use Python's standard `random` module for tokens, passwords, payment references, PINs, or any security-sensitive strings. Use `secrets`.
- For CSV/XLSX imports through a web interface, do not trust file extensions. Validate file content and type before processing. If MIME validation requires a new package such as `python-magic`, ask before adding the dependency.
- Protect file handling against directory traversal by using `os.path.basename()`, Django's upload sanitization, or storage APIs.

## 13. Context & Code Documentation

- Explain why, not what. Comments should document business rationale, edge cases, or workarounds rather than narrating obvious code.
- Use `Optional[...]` or `| None` whenever a function can accept or return `None`. Strict typing should make `None` edge cases explicit.

## 14. UI/UX Design & Frontend Best Practices

AI agents must follow modern web standards for server-rendered Django templates.

- Use semantic HTML and accessibility-friendly structure. Prefer elements such as `nav`, `main`, `section`, `article`, and `dialog` over generic `div` or `span` where semantics exist.
- Use `<button type="button">` or `<button type="submit">` for actions. Do not use `<a href="#">` with JavaScript handlers.
- Ensure every form input has an associated `label`.
- Follow a mobile-first approach. Tables, grids, and forms must remain functional on small screens.
- Use CSS Flexbox and CSS Grid for layout. Avoid inline styles; use CSS classes.
- Do not use jQuery. Use modern vanilla JavaScript, `fetch()`, and native DOM APIs.
- If dynamic behavior is needed, prefer lightweight declarative tools suitable for Django, such as HTMX or Alpine.js, over heavy SPA frameworks unless explicitly requested.
- Keep templates DRY with inheritance and includes. Reuse UI fragments for repeated form fields, tables, buttons, and panels.
- Keep templates presentation-focused. Move complex formatting logic to services, model properties, or custom template filters.
- Destructive or settlement-altering actions must include a clear confirmation step.
- Use Django's `messages` framework for success, error, and warning feedback after form submissions.
- Format currency and dates consistently according to the project's locale conventions.
- Popups/Modals Preference: For workflows that require creating/editing data within an overview or management page (e.g. managing prices), prioritize using native HTML5 `<dialog>` elements (popups) with clean progressive enhancement fallbacks instead of redirecting the user away. Keep the user in the context of the page they are working on.
