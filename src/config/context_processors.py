from typing import Any

from django.conf import settings
from django.http import HttpRequest

from billing.pwa_views import pwa_template_context


def optional_authentication_features(_request: HttpRequest) -> dict[str, Any]:
    """Expose optional authentication feature flags to server-rendered templates."""
    return {
        "passkey_enabled": settings.PASSKEY_ENABLED,
        "web_push_enabled": settings.WEB_PUSH_ENABLED,
        **pwa_template_context("admin"),
    }
