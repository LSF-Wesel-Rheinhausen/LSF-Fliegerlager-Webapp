# High Contrast Theme & WCAG AA Color Ratios (Issues #352 & #353)

- Implemented dedicated `:root[data-theme="high-contrast"]`, `@media (prefers-contrast: more)`, and `@media (forced-colors: active)` CSS styling rules.
- Adjusted text, muted, line, and focus color CSS variables to satisfy WCAG AA contrast standards (minimum 4.5:1 text, 3:1 control borders).
- Enhanced focus indicator contrast with 3px solid outlines and ring offsets across interactive controls.
- Bumped `PWA_CACHE_VERSION` to 37 and updated PWA cache tests.
- Added Python unit tests (`tests/test_high_contrast_color_ratios.py`) and Playwright E2E tests (`tests/e2e/high_contrast_color_ratios.spec.js`).
