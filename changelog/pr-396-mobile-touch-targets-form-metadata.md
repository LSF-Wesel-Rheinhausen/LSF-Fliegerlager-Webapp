# Mobile Touch Targets & Form Metadata (Closes #346, #349, #557, #558, #559, #560, #561, #562, #566)

- Standardized mobile interactive touch targets to 44px minimum height and width in portrait and narrow landscape viewports (`@media (max-width: 768px), (max-width: 900px) and (orientation: landscape)`).
- Updated `.theme-toggle`, standard buttons, input/select/textarea fields, dialog close controls, and checkbox/radio label touch targets.
- Enhanced form input metadata with explicit `autocomplete`, `inputmode`, `spellcheck="false"`, and `autocapitalize="none"` across authentication, registration, participant, family member, and financial forms.
- Preserved credential autocompletion (`autocomplete="username"`, `autocomplete="current-password"`) without `autocomplete="off"`.
- Increment `PWA_CACHE_VERSION` from the current base value 39 to 40 and updated PWA cache version expectations.
- Added Python unit tests (`tests/test_mobile_touch_form_metadata.py`) and Playwright E2E tests (`tests/e2e/mobile_touch_form_metadata.spec.js`).
- Restored the strict 280px mobile admin header regression assertion and retained the two-column layout without reordering navigation items.
- Covered visible checkbox and radio inputs with associated labels at 44px touch targets in portrait and narrow landscape viewports.
- Added an explicit metadata inventory for login, kiosk registration, participant, family-member, QuickBooking, and MealBooking forms, including exact field names, labels, credential autocomplete, and meaningful text/number metadata.
- Synchronized the final kiosk login before navigating to the authenticated meal calendar, preventing WebKit from cancelling the login POST during the subsequent navigation.
- Kept kiosk self-registration interaction behind the observable modal/focus-ready contract and asserted both entered names before advancing the wizard, preventing Firefox from validating a partially initialized Step 1.
- Synchronized the kiosk donation dialog before entering the amount and asserted the exact value, preventing native required validation from blocking the donation POST in Firefox.

## Scope

This recovery fully verifies and closes the #346 touch-target contract and the #349 form-metadata contract, including the #557, #558, #559, #560, #561, and #562 regressions. The verified contract covers accessible theme and dialog names, portrait and narrow-landscape layouts, keyboard focus, overflow, theme variants, the existing safe-area behavior, synchronized kiosk authentication before authenticated navigation, and ready-state synchronization for self-registration and donation input.
