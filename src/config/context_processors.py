from typing import Any

from django.conf import settings
from django.http import HttpRequest


def optional_authentication_features(_request: HttpRequest) -> dict[str, Any]:
    """Expose optional authentication feature flags to server-rendered templates."""
    return {"passkey_enabled": settings.PASSKEY_ENABLED}
