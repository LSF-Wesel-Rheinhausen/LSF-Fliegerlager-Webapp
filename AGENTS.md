# Agent Instructions

## Scope And Precedence

- These rules apply to the entire repository. A closer nested `AGENTS.md` may add or override rules for its subtree.
- Read `TODO.md` before starting. The current user request remains the task; `TODO.md` supplies relevant context, not unrelated work. Update only entries directly completed by the task.
- Inspect only the files needed for the task. Preserve all pre-existing working-tree changes and never stage, rewrite, or remove unrelated work.
- Follow `CONTRIBUTING.md` for human-facing setup and pull-request conventions.

## Workflow

1. **Explore:** inspect the relevant tree, contracts, tests, and history. For codebase questions, query Graphify first as described below.
2. **Plan:** before editing, present a concrete plan and wait for explicit implementation approval unless the user already granted it.
3. **Implement:** make the smallest coherent change. Add or update tests before or with behavioral code.
4. **Verify:** run focused checks first, then every required full check. Review the diff and observable behavior.
5. **Commit:** publish one coherent task after verification using the Git workflow below.

- Resolve risky ambiguity by asking the user directly; never write clarification questions into tracked files.
- Troubleshoot from a stated hypothesis and interpret each result. Do not repeat the same failed approach; after three equivalent blockers, report the evidence and required external action.
- Never weaken, skip, or delete tests to obtain a passing result. Distinguish regressions from documented pre-existing or environmental failures.

## Project Map

- `src/config/`: Django settings, middleware, and root routing.
- `src/billing/`: domain app. Keep views thin; put shared calculations and workflows in services.
- `src/billing/importers.py` and `exporters.py`: validated file boundaries and generated reports.
- `src/templates/` and `src/static/`: server-rendered UI and assets.
- `tests/`: pytest tests, factories, and Playwright E2E coverage.
- `scripts/`: canonical local setup, test, and operational helpers.

## Commands

Run commands from the repository root. Use the existing `.venv` and `package-lock.json`; do not migrate package managers unless requested.

| Purpose | Command |
| --- | --- |
| Django check | `.venv/bin/python src/manage.py check` |
| Focused Python test | `.venv/bin/python -m pytest tests/test_<area>.py` |
| Python suite | `.venv/bin/python -m pytest` |
| Lint and format check | `.venv/bin/python -m ruff check .` and `.venv/bin/python -m ruff format --check .` |
| Type check | `.venv/bin/python -m mypy src` |
| Browser suite | `npm run test:e2e` |
| Full local verification | `npm run test:local` followed by `.venv/bin/python -m mypy src` |

- Playwright needs access to browser binaries outside the workspace sandbox; request the required sandbox escalation for `npm run test:e2e`.
- Tests must not use external networks, real APIs, or real email delivery. Mock only I/O boundaries and time; test domain logic directly.
- Use `tests/factories.py` for reusable data and assert exact results and side effects, including a relevant failure or edge case.

## Engineering Rules

- Prefer KISS, explicit names, typed contracts, guard clauses, and focused patches. Add abstractions only when they remove current complexity or duplication.
- Refactor legacy code only when necessary to make the requested change safe; keep that refactor scoped and covered by characterization tests.
- Document public APIs and non-obvious contracts with standard docstrings, including parameters, return values, and raised exceptions where applicable. Comments explain rationale, not syntax.
- Make optional values explicit in type contracts. Management commands and data migrations must be idempotent.
- Keep calculations as pure as practical and isolate file, email, API, and storage effects behind dedicated helpers.
- Prevent N+1 queries with `select_related()` or `prefetch_related()` when iterating relations. Use `transaction.atomic()` for financial and settlement-altering writes.
- Use the Django ORM and parameterized operations. Raw SQL requires explicit justification and focused tests.

## Security And Privacy

- Validate untrusted input at the form, importer, or API boundary for type, length, format, and allowed values.
- Never commit or log secrets, passwords, PINs, payment details, imported personal data, or other PII. Do not use `print()` for diagnostics; use structured logging only where operationally useful, with correlation IDs on critical request paths.
- Use environment variables or a secret manager for secrets and `secrets`, not `random`, for security-sensitive values.
- Validate uploaded file content as well as extensions, sanitize filenames, and use Django storage or secure temporary directories to prevent traversal.
- Verify a dependency's exact package name and current repository compatibility before proposing it. Ask before adding any undeclared third-party dependency.
- Catch specific exceptions. A broad boundary exception must log safe diagnostic context and preserve the stack trace; never use `except Exception: pass`.

## Frontend

- Use semantic, accessible, mobile-first HTML. Every control needs an associated label or accessible name; actions use `<button>` rather than scripted placeholder links.
- Keep templates presentational, reuse includes, avoid inline styles and jQuery, and prefer existing vanilla JavaScript, Flexbox, and Grid patterns.
- Prefer native `<dialog>` workflows for in-context create/edit actions, with progressive enhancement. Confirm destructive or settlement-altering actions and report outcomes through Django messages.
- Format currency and dates consistently with the configured locale.
- Before automating UI assertions, exercise the smallest runnable change against real application state with a Playwright-controlled browser at representative desktop and mobile viewports; include light and dark themes when affected.
- Check keyboard operation, disabled and error states, overflow or overlap, browser console errors, and failed requests. Then encode the verified behavior and discovered edge cases in deterministic Playwright or pytest regression tests.

## Git And Pull Requests

- After one completed user task with repository changes, automatically create a Conventional Commit, push the task branch, and create or update one pull request without asking again.
- Stage only files changed for the current task. Never include pre-existing staged or unstaged changes. Do not push directly to `main`.
- Before committing changes under `src/` or `tests/`, run `.venv/bin/python -m pytest` and `npm run test:e2e` plus all other relevant checks. Never commit known failing checks.
- Any change under `src/` requires a `changelog/` entry. Use `<branch-name>.md` until a PR number exists, then rename it to `pr-<number>-<short-title>.md`.
- If authentication, permissions, or remote state blocks publishing, keep the verified local commit intact and report the exact blocker; never bypass security controls.

## Graphify

- When the user types `/graphify`, invoke the Graphify skill before doing anything else.
- When `graphify-out/graph.json` exists, begin codebase questions with `graphify query "<question>"`; use `graphify path` or `graphify explain` for focused relationships.
- Use `graphify-out/wiki/index.md` for broad navigation. Read `GRAPH_REPORT.md` only when focused queries are insufficient.
- Dirty generated graph files are expected and do not invalidate queries. After modifying source code, run `graphify update .`; do not stage unrelated generated output.
