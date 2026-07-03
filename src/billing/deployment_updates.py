from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings


class UpdateAgentError(RuntimeError):
    """Raised when the isolated deployment agent cannot complete a request."""


def agent_request(
    path: str,
    *,
    method: str = "GET",
    timeout: int = 30,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the isolated deployment agent and return its JSON response."""
    if not settings.UPDATE_AGENT_URL or not settings.UPDATE_AGENT_TOKEN:
        raise UpdateAgentError("Der Update-Agent ist nicht konfiguriert.")

    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{settings.UPDATE_AGENT_URL}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {settings.UPDATE_AGENT_TOKEN}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.load(error).get("error", "Unbekannter Agent-Fehler")
        except (json.JSONDecodeError, AttributeError):
            detail = f"HTTP {error.code}"
        raise UpdateAgentError(f"Update-Agent: {detail}") from error
    except (OSError, TimeoutError, json.JSONDecodeError) as error:
        raise UpdateAgentError("Der Update-Agent ist nicht erreichbar.") from error

    if not isinstance(payload, dict):
        raise UpdateAgentError("Der Update-Agent hat eine ungültige Antwort geliefert.")
    return payload


def deployment_status() -> dict[str, Any]:
    """Return the deployment agent status for the update page."""
    return agent_request("/status")


def check_for_update() -> dict[str, Any]:
    """Ask the agent to compare latest OCI metadata with this Django build."""
    return agent_request(
        "/check",
        method="POST",
        timeout=120,
        payload={
            "current": {
                "version": settings.APP_VERSION,
                "revision": settings.APP_REVISION,
                "build_date": settings.APP_BUILD_DATE,
                "change": settings.APP_CHANGE,
            }
        },
    )


def install_update() -> dict[str, Any]:
    """Ask the agent to install the configured application image."""
    return agent_request("/install", method="POST")
