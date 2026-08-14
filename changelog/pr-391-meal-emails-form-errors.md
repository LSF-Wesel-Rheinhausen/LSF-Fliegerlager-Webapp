# Meal Booking Emails & Form Error Accessibility

- Enhanced HTML email template structure in `email_delivery.py` with `<html lang="de">`, viewport metadata, max-width, responsive typography, and high-contrast color formatting.
- Added `AccessibleFormMixin` in `forms.py` to automatically decorate invalid fields with `aria-invalid="true"` and `aria-describedby="id_{field}_error"` upon validation failures.
- Added automatic focus placement on invalid form fields upon submission.
- Added Python unit tests (`tests/test_meal_emails_form_errors.py`) and Playwright E2E tests (`tests/e2e/meal_emails_form_errors.spec.js`).

## Scope

This PR covers meal-email markup and form-error metadata only. It does not implement reduced-motion support from #348 or the subsidy-rate display requested in #363.
