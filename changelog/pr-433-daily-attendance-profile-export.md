# Daily attendance, profiles and export

- Added administrator-only attendance overview and workbook routes.
- Integrated attendance calendars, optimistic locking, safe audit trails and the setup/departure window into kiosk check-in.
- Added profile navigation, contact and birth-date administration, plus attendance detail and export coverage.

Changed areas/files:

- `src/billing/models.py`, `src/billing/migrations/0063_attendance_profiles.py`: daily attendance records, profile fields and derived age/attendance billing.
- `src/billing/attendance.py`, `src/billing/attendance_export.py`, `src/billing/attendance_views.py`, `src/billing/services.py`: attendance validation, admin overview and one-person-per-row Excel export.
- `src/billing/profile_forms.py`, `src/billing/profile_views.py`, `src/billing/urls.py`, `src/billing/admin.py`: kiosk self-service, admin visibility and authorization boundaries.
- `src/templates/billing/camp_attendance_overview.html`, `kiosk_home.html`, `kiosk_profile.html`, `participant_detail.html`, `camp_detail.html`, plus `src/static/billing/app-v8.css`: UI, accessibility and mobile matrix scrolling.
- `src/billing/views.py`, `src/billing/forms.py`, `src/billing/pwa_views.py`: kiosk integration, profile form support and PWA cache versioning.
- `tests/test_attendance_*.py`, `tests/test_kiosk_profile_*.py`, `tests/test_issue_417_ui.py`, relevant billing/kiosk/security/shift/PWA regressions and `tests/e2e/fliegerlager.spec.js`.

Tests: focused attendance, profile, kiosk, forms, exporters, permissions, billing, shifts and UI checks reported green. The independent full verification is still running; no final full-suite green status is claimed here.

Open points:

- Complete and review the independent full verification, including the end-to-end suite, before declaring release readiness.
