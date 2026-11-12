# Position report performance baseline

The opt-in harness in `tests/test_position_report_performance.py` compares the reference implementation copied from `faad22a18dd610c531752401402df4a4a59afc92` with the optimized implementation on the same disposable pytest database. It seeds 1,000 participants, 1,000 family members, 30 calendar days, 100 article descriptions, active and retracted meals, and tracked and untracked attendance. Setup and database writes are excluded from timing and memory measurements. It performs one warmup and five `perf_counter` measurements for each implementation at each charge volume. Each stage checks full `PositionReport` equality.

## SQLite run

Measured in the provided Linux workspace on Python 3.13.5, SQLite, x86_64 / AMD EPYC 9V74. The reference revision is the branch base above; the optimized implementation was measured from the working tree based on that revision. Results are medians in seconds; memory is peak Python allocation from a separate `tracemalloc` calculation run.

| Charges | Database size | Reference median | Optimized median | Reference peak | Optimized peak |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 | 3,756,032 B | 0.2951 s | 0.0631 s | 13.55 MB | 1.18 MB |
| 50,000 | 11,128,832 B | 1.1588 s | 0.3026 s | 69.12 MB | 1.18 MB |
| 100,000 | 20,496,384 B | 2.0877 s | 0.5090 s | 138.81 MB | 1.18 MB |

The 100,000-charge optimized result is below the 5 second median and 128 MiB optimized allocation budgets. The checked-in JSON artifact records each sample, base and reference commit, optimized source SHA256, and dirty-worktree status, backend metadata, database size, and both memory peaks. CI runs this harness in SQLite and PostgreSQL 16 matrix jobs and uploads JSON even after a failed benchmark step.
