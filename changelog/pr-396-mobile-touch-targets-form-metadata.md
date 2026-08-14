# Mobile Touch Targets & Form Metadata (Refs #346, #349)

- Standardized mobile interactive touch targets to 44px minimum height and width on mobile viewports (`@media (max-width: 768px)`).
- Updated `.theme-toggle`, standard buttons, input/select/textarea fields, dialog close controls, and checkbox/radio label touch targets.
- Enhanced form input metadata with explicit `autocomplete`, `inputmode`, `spellcheck="false"`, and `autocapitalize="none"` across authentication, registration, participant, family member, and financial forms.
- Preserved credential autocompletion (`autocomplete="username"`, `autocomplete="current-password"`) without `autocomplete="off"`.
- Increment `PWA_CACHE_VERSION` to 36 and updated PWA cache version expectations.
- Added Python unit tests (`tests/test_mobile_touch_form_metadata.py`) and Playwright E2E tests (`tests/e2e/mobile_touch_form_metadata.spec.js`).

## Scope

This PR provides the initial touch-target and form-metadata implementation for #346 and #349. The remaining acceptance criteria, including complete checkbox/radio coverage and landscape viewport coverage, are still tracked by those issues.
