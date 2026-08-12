"""Gunicorn configuration with the repository-owned chunk metadata guard."""

from config.gunicorn_parser_guard import configure

http_parser = "python"


def on_starting(server: object) -> None:
    """Validate Gunicorn and install the bounded parser before workers start."""
    config = server.cfg  # type: ignore[attr-defined]
    if config.http_parser != http_parser:
        raise RuntimeError(
            f"Unsafe Gunicorn HTTP parser '{config.http_parser}'; the chunk metadata guard requires '{http_parser}'"
        )
    configure(config)
