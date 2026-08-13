# Accessibility Navigation & Focus Management (Issues #345 & #347)

- Added accessible `.skip-link` to `base.html`, `kiosk_base.html`, and `offline.html` jumping directly to `#main-content` (`tabindex="-1"`).
- Added `aria-current="page"` and `is-active` class to active main navigation and kiosk mobile bottom navigation links.
- Corrected countdown heading hierarchy on pre-camp kiosk login page to maintain single `<h1>` page structure.
- Enhanced kiosk self-registration dialog with initial element focus management and screen-reader polite step announcements (`#wizard-step-announcer`).
- Updated seed data in `scripts/start-e2e.sh` to populate active camp dates for deterministic E2E test runs.
- Added Python unit tests (`tests/test_accessibility_navigation_focus.py`) and Playwright E2E tests (`tests/e2e/accessibility_navigation_focus.spec.js`).
