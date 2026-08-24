# PR #552: Stable CI gate

- Splits CI into separately diagnosable quality, Python, PostgreSQL, and E2E jobs.
- Adds a deterministic change-scope classifier and one aggregate `CI gate` for branch protection.
- Bounds job runtimes and keeps Playwright failure artifacts browser-specific with seven-day retention.

Closes #521
Closes #546
Closes #547
Closes #548
Closes #549
Closes #550
Closes #551
