# PR #555: Bounded DAST lifecycle

- Replace fixed DAST startup sleep with bounded `/healthz/` polling.
- Fail visibly on application startup, healthcheck, timeout, or cleanup errors.
- Clean up the DAST container on successful and failed scans while preserving report-only ZAP findings.

Closes #522
