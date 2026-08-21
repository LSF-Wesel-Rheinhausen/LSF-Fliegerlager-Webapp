# Auditable participant credit payouts

- Adds an immutable, idempotent `CreditPayout` ledger for full or partial participant-credit payouts.
- Restricts payout creation to administrators and prevents account/card coordinates from being recorded.
- Includes settlement, export, admin-read-only, and concurrency safeguards without changing historical snapshots.
