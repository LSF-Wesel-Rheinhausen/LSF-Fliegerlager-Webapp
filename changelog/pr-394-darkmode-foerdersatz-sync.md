# Darkmode Contrast & Meal Charge Sync (Issues #371 & #379)

- Fixes #371 by giving deployment-update code blocks explicit dark-mode text,
  background, and border colors.
- Fixes #379 by synchronizing only future, active meal signups that are not
  deleted or covered by a versioned settlement run. Archived meal rules are
  excluded, and the synchronization is atomic and idempotent.
- Adds regression tests for rule selection, historical/deleted/finalized
  records, rollback behavior, idempotency, and the dark-mode CSS contract.
