# Screen Reader Live Region Announcements

- Added persistent screen reader live region elements (`#sr-announcer-polite`, `#sr-announcer-assertive`) to `base.html` and `kiosk_base.html`.
- Implemented `window.announceToScreenReader` JavaScript helper in `dialog-scroll-lock.js` to dispatch dynamic UI updates to screen readers without page reloads.
- Added Python template tests (`tests/test_screenreader_live_regions.py`) and Playwright E2E tests (`tests/e2e/screenreader_live_regions.spec.js`).

## Scope

This PR adds the live-region primitives and their focused checks. It does not implement the spacing, action hierarchy, design-token, or responsive-table work requested in #350.
