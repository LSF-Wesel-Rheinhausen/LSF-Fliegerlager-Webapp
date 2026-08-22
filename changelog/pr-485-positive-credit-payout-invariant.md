# Strictly positive credit payouts

## Summary

- Enforces the positive two-decimal `CreditPayout` range in model validation and at the database boundary.
- Prevents non-positive, over-precision, and over-range payouts through ORM bypasses such as `bulk_create()` and `QuerySet.update()`.
- Aborts migration before schema changes when historical payout rows violate the new contract, without modifying ledger data.
- Covers backend storage semantics explicitly: SQLite rejects over-precision bypasses, while PostgreSQL stores `0.011` as the canonical `0.01` numeric value without settlement drift.

## Changed files

- `src/billing/models.py`
- `src/billing/migrations/0067_positive_credit_payout_amount.py`
- `tests/test_credit_payout.py`

## Tests

- Model validation for invalid amounts and the valid minimum/maximum boundaries.
- Database constraint coverage for `bulk_create()` and `QuerySet.update()`.
- Migration preflight coverage for valid, non-positive, and SQLite subcent historical rows.
- PostgreSQL CI coverage for numeric coercion, minimum enforcement, overflow rejection, and settlement consistency.
- Existing settlement and ledger payout regressions.

## Open points

- None.
