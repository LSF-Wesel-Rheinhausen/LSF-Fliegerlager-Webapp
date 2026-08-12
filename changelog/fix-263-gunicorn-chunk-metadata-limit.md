# Security: Bound Gunicorn chunk metadata

- Pin Gunicorn to 26.0.0 and enforce an 8 KiB limit on fragmented HTTP chunk metadata.
- Reject oversized chunk metadata with HTTP 400 while keeping the worker available for
  subsequent health checks.
- Fail closed during startup when `GUNICORN_CMD_ARGS` selects a non-Python HTTP parser.
