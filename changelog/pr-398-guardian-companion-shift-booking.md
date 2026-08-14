# Issue #388: Guardian and companion shift booking

## Summary

- Prevent Guardian and Companion identities from being conflated in the kiosk shift flow.
- Store a Companion booking against the Guardian account with its explicit family-member target.
- Keep booking, retraction, exchange offers, progress counts, and coworker display identity-specific.
- Restrict an authenticated Companion to their own meal/check-in target while retaining the
  same role and price-rule eligibility as a regular Companion.
- Persist quick-booked charges to the Guardian payer and Companion target, including the
  Companion actor in the audit record.
- Include active regular and guardian-owned Companions as separate identities in the
  shift ranking, with annotated identity-specific completion counts; exclude child identities
  from the ranking and give them no shift target.
- Show guardian-owned Companions in kiosk/login selectors by their own name; duplicate names
  receive deterministic neutral numeric disambiguation without exposing guardian names.
- Preserve server-side camp and active-family-member authorization checks.

## Changed files

- `src/billing/models.py`
- `src/billing/migrations/0060_shiftassignment_family_member.py`
- `src/billing/views.py`
- `src/templates/billing/kiosk_shifts.html`
- `tests/test_kiosk.py`
- `tests/test_kiosk_shifts.py`
- `tests/test_shifts.py`
- `tests/test_forms.py`

## Tests

- RED: the regression reproduced the bug with one Guardian assignment instead of two
  (`1 == 2`).
- GREEN: focused Shift/Kiosk tests pass, including duplicate-booking protection and
  Guardian progress isolation, Companion target isolation, payer attribution, and
  Companion role/subsidy behavior.
- RED/GREEN: shift-report coverage reproduces and fixes missing guardian-owned Companions,
  guardian attribution, and regular/family child ranking leakage.
- Full local verification is run before the PR is marked ready.

## Open points

- Companion shift progress uses the Guardian's configured shift target because family
  members do not currently have an independent stay quota.

Closes #388
