"""Gunicorn configuration with the repository-owned chunk metadata guard."""

from config.gunicorn_parser_guard import configure

http_parser = "python"


def on_starting(server: object) -> None:
    """Validate Gunicorn and install the bounded parser before workers start."""
    configure(server.cfg)  # type: ignore[attr-defined]
