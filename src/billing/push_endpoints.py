from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings

PUSH_ENDPOINT_MAX_LENGTH = 2048
PUSH_ENDPOINT_ERROR = "Ungültiger Push-Endpoint."


def _canonical_origin(value: object, *, require_origin: bool) -> str | None:
    """Return a safe HTTPS origin or ``None`` for an invalid URL value."""
    if not isinstance(value, str) or not value or len(value) > PUSH_ENDPOINT_MAX_LENGTH:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() != "https":
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        hostname = parsed.hostname
        if not hostname or "*" in hostname:
            return None
        hostname = hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith(".localhost"):
            return None
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            return None
        if parsed.port not in (None, 443):
            return None
        if require_origin and (parsed.path or parsed.query or parsed.fragment):
            return None
        hostname = hostname.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return None
    return f"https://{hostname}"


@dataclass(frozen=True)
class PushEndpointPolicy:
    """Allow push delivery only to explicitly configured HTTPS origins."""

    allowed_origins: frozenset[str]

    @classmethod
    def from_origins(cls, origins: Iterable[object] | None) -> PushEndpointPolicy:
        """Build a policy, ignoring malformed origins so configuration fails closed."""
        if isinstance(origins, str):
            origins = (origins,)
        canonical_origins = {
            canonical
            for origin in origins or ()
            if (canonical := _canonical_origin(origin, require_origin=True)) is not None
        }
        return cls(allowed_origins=frozenset(canonical_origins))

    def allows(self, endpoint: object) -> bool:
        """Return whether an endpoint has an exact configured and safe origin."""
        canonical = _canonical_origin(endpoint, require_origin=False)
        return canonical is not None and canonical in self.allowed_origins


def configured_push_endpoint_policy() -> PushEndpointPolicy:
    """Return the current fail-closed Web Push endpoint policy."""
    return PushEndpointPolicy.from_origins(getattr(settings, "WEB_PUSH_ALLOWED_ORIGINS", ()))


def is_allowed_push_endpoint(endpoint: object) -> bool:
    """Return whether the endpoint is currently allowed for Web Push delivery."""
    return configured_push_endpoint_policy().allows(endpoint)
