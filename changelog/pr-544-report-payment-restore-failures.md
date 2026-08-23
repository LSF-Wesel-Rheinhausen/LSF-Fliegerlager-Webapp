# PR #544: Teilfehler bei der Zahlungswiederherstellung melden

## Zusammenfassung

Die Admin-Wiederherstellung von Zahlungen meldet fehlgeschlagene Audit-Zeilen separat und protokolliert sichere Zahlungs- und Audit-IDs. Erfolgreiche Wiederherstellungen bleiben bei zeilenweisen Validierungsfehlern erhalten.

Closes #541, #542, #543

## Geänderte Dateien

- `src/billing/admin.py`
- `tests/test_payment_audit.py`

## Tests

- `.venv/bin/python -m pytest tests/test_payment_audit.py -q`
- `.venv/bin/python -m ruff check src/billing/admin.py tests/test_payment_audit.py`
- `.venv/bin/python -m ruff format --check src/billing/admin.py tests/test_payment_audit.py`

## Offene Punkte

Keine.
