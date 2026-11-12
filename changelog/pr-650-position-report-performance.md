# Position report aggregation performance

- Streams only the charge and person fields used by the position report, groups meal signups in the database, and counts daily attendance with interval deltas. Report arithmetic, sort order, attendance-night fallbacks, and rendered output remain compatible.
- Keeps query count bounded as camp size grows; adds a six-query ceiling to the existing position report query regression test.

- Adds isolated SQLite/PostgreSQL CI performance checks with JSON artifacts and hard limits of 5 seconds median and 128 MiB extra Python allocation at 100,000 bookings.
- Validation: 148 focused tests, 2,277 full Python tests passed (19 skipped), 365 browser tests passed (1 skipped), Ruff, mypy, Django and migration check passed. SQLite benchmark: 0.5090 seconds and 1,177,981 bytes peak. PostgreSQL performance validation remains pending in CI.
