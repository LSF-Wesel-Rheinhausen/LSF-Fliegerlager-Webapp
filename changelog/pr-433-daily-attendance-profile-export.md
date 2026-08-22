# Daily attendance, profiles and export

- Added administrator-only attendance overview and workbook routes.
- Integrated attendance calendars, optimistic locking, safe audit trails and the setup/departure window into kiosk check-in.
- Added profile navigation, contact and birth-date administration, plus attendance detail and export coverage.
- Hardened exact attendance target scoping, stay-date reconciliation, profile validation and settlement query bounds.
- Rejects stale companion profile sessions and excludes incomplete stays from attendance-backed billing and shift targets.
- Applies family-specific stay dates only as a complete pair, preventing hybrid attendance billing from partial overrides.
- Prefetches participant and family attendance during cost-center evaluation to keep query counts constant.
- Renders age zero for participants and family members while reserving `-` for missing ages.
- Validates profile birth dates against Django's configured local date at timezone boundaries.
- Normalizes profile-form imports in the kiosk profile tests for consistent code-quality analysis.

Changed areas/files:

- `src/billing/models.py`, `src/billing/migrations/0063_attendance_profiles.py`: daily attendance records, profile fields and derived age/attendance billing.
- `src/billing/attendance.py`, `src/billing/attendance_export.py`, `src/billing/attendance_views.py`, `src/billing/services.py`: attendance validation, admin overview and one-person-per-row Excel export.
- `src/billing/profile_forms.py`, `src/billing/profile_views.py`, `src/billing/urls.py`, `src/billing/admin.py`: kiosk self-service, admin visibility and authorization boundaries.
- `src/templates/billing/camp_attendance_overview.html`, `kiosk_home.html`, `kiosk_profile.html`, `participant_detail.html`, `camp_detail.html`, plus `src/static/billing/app-v8.css`: UI, accessibility and mobile matrix scrolling.
- `src/billing/views.py`, `src/billing/forms.py`, `src/billing/pwa_views.py`: kiosk integration, profile form support and PWA cache versioning.
- `tests/test_attendance_*.py`, `tests/test_kiosk_profile_*.py`, `tests/test_issue_417_ui.py`, relevant billing/kiosk/security/shift/PWA regressions and `tests/e2e/fliegerlager.spec.js`.

Tests: 1,258 Python tests passed with 8 skipped; 242 Playwright tests passed with 1 skipped. Mypy, Django checks, migration checks, Ruff, formatting and diff checks passed.

Open points:

- None.

## Shared local test data

- Added the idempotent `seed_local_test_db` management command with synthetic users, camps, participants, kiosk credentials, attendance, meals, expenses, charges, payments and settlement snapshots.
- Kept pytest, CI and parallel Playwright database isolation; `start-e2e.sh` invokes the command only when `SEED_LOCAL_TEST_DB=1`.
- Refactored GIF database setup to consume the same command.
- Foreign collisions with deterministic seed usernames now fail closed without overwriting or partially applying seed data.
