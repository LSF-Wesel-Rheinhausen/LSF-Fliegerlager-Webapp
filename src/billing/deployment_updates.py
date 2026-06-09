from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings


class UpdateAgentError(RuntimeError):
    """Raised when the isolated deployment agent cannot complete a request."""


def agent_request(path: str, *, method: str = "GET", timeout: int = 30) -> dict[str, Any]:
    if not settings.UPDATE_AGENT_URL or not settings.UPDATE_AGENT_TOKEN:
        raise UpdateAgentError("Der Update-Agent ist nicht konfiguriert.")

    request = urllib.request.Request(
        f"{settings.UPDATE_AGENT_URL}{path}",
        method=method,
        headers={
            "Authorization": f"Bearer {settings.UPDATE_AGENT_TOKEN}",
            "Accept": "application/json",
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
    return agent_request("/status")


def check_for_update() -> dict[str, Any]:
    return agent_request("/check", method="POST", timeout=120)


def install_update() -> dict[str, Any]:
    return agent_request("/install", method="POST")
