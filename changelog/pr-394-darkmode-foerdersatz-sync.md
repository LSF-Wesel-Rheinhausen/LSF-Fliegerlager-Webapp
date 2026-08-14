# Darkmode Contrast & Meal Charge Sync (Issues #371 & #379)

- Fixes #371 by giving deployment-update code blocks explicit dark-mode text,
  background, and border colors.
- Fixes #379 by synchronizing mutable future meal bookings after administrators
  create, edit, or archive meal price rules. Canonical target-role resolution
  applies companion and youth-group subsidy rules while guardian-owned charges
  remain attributed to the guardian payer.
- Protects historical, soft-deleted, and exactly settlement-snapshotted charges
  from resynchronization or kiosk retraction, including future and undated
  charges captured by immutable settlement snapshots.
- Adds regression tests for canonical server-side pricing, authorization, rule
  lifecycle changes, companion ownership and subsidies, exact snapshot
  membership, rollback behavior, idempotency, and the dark-mode CSS contract.
