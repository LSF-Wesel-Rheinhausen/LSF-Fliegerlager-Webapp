"""Gunicorn access logging that redacts credential-recovery capabilities."""

from __future__ import annotations

import re
from typing import Any

from gunicorn.glogging import Logger

_RECOVERY_SECRET_PATTERN = re.compile(r"(?P<prefix>/account/recovery/confirm/)[^/?#]+")
_SENSITIVE_ENVIRONMENT_KEYS = ("RAW_URI", "PATH_INFO", "HTTP_REFERER")


def redact_recovery_secrets(value: str) -> str:
    """Replace a recovery capability embedded in a URL while preserving its route."""
    return _RECOVERY_SECRET_PATTERN.sub(r"\g<prefix>[REDACTED]", value)


class RecoverySecretFilter:
    """Remove recovery capabilities from Django request log records."""

    def filter(self, record: Any) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_recovery_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: redact_recovery_secrets(value) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            else:
                record.args = tuple(
                    redact_recovery_secrets(value) if isinstance(value, str) else value for value in record.args
                )
        return True


class RecoverySafeLogger(Logger):
    """Build Gunicorn access-log atoms without raw account-recovery tokens."""

    def atoms(self, resp: Any, req: Any, environ: dict[str, Any], request_time: Any) -> dict[str, Any]:
        safe_environ = environ.copy()
        for key in _SENSITIVE_ENVIRONMENT_KEYS:
            value = safe_environ.get(key)
            if isinstance(value, str):
                safe_environ[key] = redact_recovery_secrets(value)
        atoms = super().atoms(resp, req, safe_environ, request_time)
        return {
            key: redact_recovery_secrets(value) if isinstance(value, str) else value for key, value in atoms.items()
        }
