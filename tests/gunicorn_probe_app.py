"""WSGI probe used to force Gunicorn to consume a request body in integration tests."""

from collections.abc import Callable
from typing import Any

from config.wsgi import application as django_application


def application(environ: dict[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
    """Read the probe body or delegate normal requests to Django."""
    if environ.get("PATH_INFO") != "/chunk-probe":
        return django_application(environ, start_response)

    environ["wsgi.input"].read()
    start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", "2")])
    return [b"ok"]
