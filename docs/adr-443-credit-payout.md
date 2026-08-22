# ADR: Credit payouts (#443)

## Decision

Add an immutable, append-only `CreditPayout` ledger owned by a participant. A
payout is a positive `Decimal` amount and may be full or partial. It records
the actor, creation time, payout method, an idempotency UUID, and optional
external reference/note. It never creates a negative `Payment` and never
stores bank-account, card, PayPal, or other raw payment coordinates.

The current available credit is derived from the current settlement: charges
and approved reimbursable expenses, minus active payments, plus existing
payouts. Historical `Settlement` snapshots remain unchanged. Payout creation
is an admin-only POST operation inside `transaction.atomic()`, locking the
participant row with `select_for_update()` before recalculating credit and
writing the ledger row. A unique idempotency UUID makes retries a no-op.

The participant UI and exports distinguish received payments from payouts.
The payout action is shown only when current available credit is positive.
The admin exposes the ledger read-only; no edit, delete, or admin action is
registered.

## Threat note

Assets are participant credit and its audit trail. Threats are overpayment,
replay, concurrent double payout, privilege escalation, and ledger tampering.

Controls:

- `Decimal` validation, positive amounts, and an upper bound of current
  available credit prevent overpayment.
- A unique UUID idempotency key makes duplicate submissions return the
  existing payout without a second ledger row.
- A participant row lock plus an atomic transaction serializes concurrent
  credit checks and writes.
- Admin-only authorization and POST-only routing reject editor, anonymous,
  and GET attempts without mutation.
- The model has no update/delete workflow; the admin is read-only and the
  actor/timestamp/method/reference/note are append-only audit fields.
- Form validation rejects account-number-like or oversized sensitive-looking
  raw payment coordinates; payment details are never persisted.
