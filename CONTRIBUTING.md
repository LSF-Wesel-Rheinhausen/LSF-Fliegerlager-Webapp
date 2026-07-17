# Contributing

## Setup

Use Python 3.13, the checked-in pip requirement files, and npm's lock file.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
npm ci
python src/manage.py migrate
python src/manage.py bootstrap_roles
python src/manage.py createsuperuser
```

Start Django with `.venv/bin/python src/manage.py runserver`. For containers, copy `.env.example` to an untracked `.env` and run `docker compose up --build`.

## Development Workflow

1. Create a focused branch from `main`.
2. Keep changes scoped and follow the architecture described in `docs/README.md` and `src/billing/README.md`.
3. Add tests for new behavior and relevant failure cases.
4. Run the verification commands below.
5. Submit a Conventional Commit and a pull request with rationale and verification evidence.

Do not commit `.env`, credentials, participant data, payment details, PINs, generated test artifacts, or local databases.

## Verification

Run focused tests during development. Before requesting review, run:

```bash
npm run test:local
.venv/bin/python -m mypy src
```

`npm run test:local` runs Ruff lint and format checks, Django checks, pytest, and Playwright. See `tests/README.md` for focused commands and test ownership.

## Commits And Pull Requests

- Use Conventional Commit types accepted by `.github/workflows/pr-title.yml`, for example `feat:`, `fix:`, `docs:`, `refactor:`, or `test:`.
- Keep one logical change per commit and do not include unrelated working-tree changes.
- Explain the problem, rationale, affected areas, tests, and remaining risks in the pull request.
- Include screenshots or sample output for UI changes and modified exports.
- CI must pass before review or merge.

Every change under `src/` requires a changelog file. Follow `changelog/README.md`: use `<branch-name>.md` before the PR exists, then rename it to `pr-<number>-<short-title>.md`.

## Engineering And Security Standards

The canonical agent-facing requirements are in `AGENTS.md`. The same standards apply to human contributions, especially:

- keep Django views thin and business logic in cohesive services;
- use type hints, focused tests, Ruff, and mypy;
- validate imports and user input at their boundaries;
- use ORM queries and transactions for financial writes;
- avoid logging secrets, PII, payment information, and PINs;
- preserve accessible, mobile-first server-rendered UI behavior.

Report suspected vulnerabilities privately to the repository maintainers rather than opening a public issue with exploit or participant data.

## Agent Configuration

`AGENTS.md` is the repository source of truth. `CLAUDE.md` and `.agents/rules/repository-guidelines.md` import it for Claude Code and Google Antigravity; do not duplicate project rules in those adapters.
