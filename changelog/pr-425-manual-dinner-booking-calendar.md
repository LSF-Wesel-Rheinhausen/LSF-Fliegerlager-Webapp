# Manual dinner booking calendar

## Requirement and behavior

The meal overview now exposes a responsive dinner-only day-card calendar (`data-meal-calendar="dinner"`) for every camp day. Past days show **Vergangen**, manually closed days **Gesperrt**, sent catering orders **Bestellung versandt**, and available days **Offen**. Today and future days offer CSRF-protected POST controls to lock and unlock dinner booking; sent orders must first be marked as not ordered. Breakfast has no lock controls. Existing detail dialogs, tables, counts, and no-JavaScript operation remain available.

The configured `meal_booking_cutoff_time` remains unchanged internally and is presented as an unverbindliche **Richtzeit** for reminders. Dinner booking and retraction remain available on the current day until an administrator manually closes it or the caterer order is marked as sent. Sent status takes precedence over both manual OPEN and CLOSED overrides until `not_sent` restores the stored manual state. Breakfast remains available today and on future camp days. PWA cache version 35 was bumped to 36 (surfaces 36/37/36) because `app-v8.css` changed.

Desktop light theme:

![Dinner day-card calendar on desktop](../docs/images/manual-dinner-booking-calendar-desktop-light.png)

Mobile dark theme:

![Dinner day-card calendar on mobile](../docs/images/manual-dinner-booking-calendar-mobile-dark.png)

## Root cause, tests, and risks

The former state resolver automatically locked next-day meals at the configured cutoff. Its overview controls lived in dense detail tables and excluded today. TDD red evidence before implementation was 11 failed / 115 passed. A final review added two more RED regressions: seven per-day override queries instead of one preload, and a participant reminder created after manual closure. Both are GREEN now.

The resulting contract is covered at service, view, kiosk, notification, PWA, and browser levels, including same-day booking and retraction, dinner-only override validation, past-day rejection, reminder suppression, bounded override queries, and mobile overflow. The final Python suite passes with 1,148 passed and 8 PostgreSQL-only concurrency tests skipped locally; Mypy reports no issues in 116 source files. Chromium and Firefox validate the new calendar flow in light/dark and desktop/mobile layouts. Local WebKit execution requires the unavailable `libwoff2dec.so.1.0.2` host library and is left to the dependency-complete CI environment.

A review follow-up closes the transaction race between the initial kiosk availability check and a concurrent manual close. Booking now rechecks every submitted meal day after acquiring the shared camp row lock, while retraction rechecks the locked signup before changing its charge or status. Deterministic lock-boundary tests first reproduced both stale writes, and PostgreSQL concurrency tests now prove that a committed administrative close wins against a waiting booking or retraction without partial multi-day writes.

A second review follow-up restores sent catering orders as a higher-priority dinner lock. Sent/not-sent writes now use the same `Camp -> MealOrder` lock order as booking, retraction, and manual overrides; the raw Django admin is read-only so it cannot bypass this workflow. Bulk calendars preload both overrides and sent dates, while authoritative transaction checks reload after taking the camp lock. Participant reminders are suppressed for sent orders, the kiosk distinguishes a persisted `is_sent=False` row correctly, and the calendar can reverse sent status for the current or a future camp day without rewriting an already-unmarked audit record. Unknown states and malformed explicit dates are rejected.

The bounded changelog manifest now stops at the first entry that exceeds the remaining byte budget. It can no longer omit a newer, larger entry and then include older, smaller release notes, while UTF-8-aware truncation of an oversized newest entry remains intact.

The dynamic browser test also derives form values and visible labels from one explicit `Europe/Berlin` calendar date. Its fixed UTC-boundary regression first reproduced the former `2026-08-17` result at an instant Django treats as `2026-08-18`, then passed in Chromium, Firefox, and WebKit with the timezone-aware helper.

## Changed areas

- Booking-state service, kiosk/admin views, reminders, and server-rendered meal calendars.
- Focused service, view, notification, query-bound, transaction, and browser regression tests.
- Bounded changelog-manifest builder and its ordering regression test.
- Admin, participant, and project documentation for sent-order precedence and reversal.

## Verification and open points

Focused RED-to-GREEN runs cover sent-order precedence, booking/retraction rejection, `not_sent`, query bounds, lock order, reminders, UI state, and manifest ordering. The final full Pytest run is green (`1,148 passed, 8 skipped`), as are Ruff, Django checks, and Mypy. The complete local Playwright attempt reached 140 passes before reproducible browser-launch failures (`SIGKILL`/`EPERM`) and the missing WebKit library; the 10 affected meal, timezone, and retraction scenarios pass in an isolated one-worker Chromium/Firefox run. Dependency-complete CI remains the authority for the full three-browser matrix. No known product or migration follow-up remains.
