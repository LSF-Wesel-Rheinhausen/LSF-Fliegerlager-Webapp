# Fix: Gunicorn 26.2 compatibility

- Pin Gunicorn to 26.2.0 and update the exact-version Python parser guard.
- Preserve fail-closed startup checks for unsupported versions and non-Python parsers,
  including the 8 KiB fragmented chunk metadata limit.
