# PR #555: Bounded DAST lifecycle

- Replace fixed DAST startup sleep with bounded `/healthz/` polling.
- Fail visibly on application startup, healthcheck, timeout, or cleanup errors.
- Clean up the DAST container on successful and failed scans while preserving report-only ZAP findings.
- Detect containers that stop during startup immediately instead of waiting for the health timeout.

Closes #522
Closes #556
