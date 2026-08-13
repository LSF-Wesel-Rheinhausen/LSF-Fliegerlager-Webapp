# Screen Reader Live Region Announcements (Issue #350)

- Added persistent screen reader live region elements (`#sr-announcer-polite`, `#sr-announcer-assertive`) to `base.html` and `kiosk_base.html`.
- Implemented `window.announceToScreenReader` JavaScript helper in `dialog-scroll-lock.js` to dispatch dynamic UI updates to screen readers without page reloads.
- Added Python template tests (`tests/test_screenreader_live_regions.py`) and Playwright E2E tests (`tests/e2e/screenreader_live_regions.spec.js`).
