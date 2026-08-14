# Mobile Touch Targets & Form Metadata (Closes #346, #349)

- Standardize interactive touch targets to 44px minimum height and width through the 1024px mobile/tablet boundary, covering portrait and landscape layouts.
- Cover theme/navigation controls, buttons, fields, dialog actions, standalone checkbox/radio inputs, their labels, and table row actions.
- Reserve safe-area space at the top and bottom of the mobile shell without hiding content behind browser chrome or the virtual keyboard.
- Enhance form input metadata with explicit `autocomplete`, `inputmode`, `spellcheck="false"`, and `autocapitalize="none"` across authentication, registration, participant, family member, and financial forms.
- Preserved credential autocompletion (`autocomplete="username"`, `autocomplete="current-password"`) without `autocomplete="off"`.
- Increment `PWA_CACHE_VERSION` to 36 and updated PWA cache version expectations.
- Add Python unit tests (`tests/test_mobile_touch_form_metadata.py`) and Playwright E2E tests (`tests/e2e/mobile_touch_form_metadata.spec.js`) for the complete scope.
