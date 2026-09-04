"""Bound Gunicorn's Python parser for HTTP chunk metadata lines."""

from __future__ import annotations

import gunicorn
from gunicorn.http.body import ChunkedReader
from gunicorn.http.errors import (
    InvalidChunkExtension,
    InvalidChunkSize,
    LimitRequestLine,
    NoMoreData,
)

SUPPORTED_GUNICORN_VERSION = "26.2.0"
MAX_CHUNK_METADATA_SIZE = 8192


class ChunkMetadataTooLarge(LimitRequestLine):
    """HTTP 400 parser error for a chunk metadata line exceeding the limit."""

    code = 400


def _parse_chunk_size(self: ChunkedReader, unreader: object, data: bytes | None = None) -> tuple[int, bytes | None]:
    buffer = bytearray(data or b"")

    while True:
        line_end = buffer.find(b"\r\n")
        if line_end >= 0:
            break

        incoming = unreader.read()  # type: ignore[attr-defined]
        if not incoming:
            if len(buffer) >= MAX_CHUNK_METADATA_SIZE:
                raise ChunkMetadataTooLarge(len(buffer), MAX_CHUNK_METADATA_SIZE)
            raise NoMoreData(bytes(buffer))

        if buffer.endswith(b"\r") and incoming.startswith(b"\n"):
            line = bytes(buffer[:-1])
            rest_chunk = incoming[1:]
            break

        incoming_line_end = incoming.find(b"\r\n")
        if incoming_line_end >= 0:
            line_end = len(buffer) + incoming_line_end
            if line_end > MAX_CHUNK_METADATA_SIZE:
                raise ChunkMetadataTooLarge(line_end, MAX_CHUNK_METADATA_SIZE)
            line = bytes(buffer) + incoming[:incoming_line_end]
            rest_chunk = incoming[incoming_line_end + 2 :]
            break

        if len(buffer) + len(incoming) > MAX_CHUNK_METADATA_SIZE:
            raise ChunkMetadataTooLarge(len(buffer) + len(incoming), MAX_CHUNK_METADATA_SIZE)
        buffer.extend(incoming)

    if line_end >= 0 and "line" not in locals():
        line = bytes(buffer[:line_end])
        rest_chunk = bytes(buffer[line_end + 2 :])

    chunk_size, *chunk_ext = line.split(b";", 1)
    if chunk_ext:
        if b"\r" in chunk_ext[0]:
            raise InvalidChunkExtension("bare CR not allowed")
        chunk_size = chunk_size.rstrip(b" \t")
    if any(char not in b"0123456789abcdefABCDEF" for char in chunk_size):
        raise InvalidChunkSize(chunk_size)
    if not chunk_size:
        raise InvalidChunkSize(chunk_size)

    parsed_size = int(chunk_size, 16)
    if parsed_size == 0:
        try:
            self.parse_trailers(unreader, rest_chunk)
        except NoMoreData:
            # Gunicorn accepts EOF after the terminal zero-size chunk.
            pass
        return 0, None
    return parsed_size, rest_chunk


def install() -> None:
    """Install the guard for the exact supported Gunicorn release.

    Raises:
        RuntimeError: if the installed Gunicorn version is unsupported.
    """
    if gunicorn.__version__ != SUPPORTED_GUNICORN_VERSION:
        raise RuntimeError(
            f"Unsupported Gunicorn version: {gunicorn.__version__}; expected {SUPPORTED_GUNICORN_VERSION}"
        )
    ChunkedReader.parse_chunk_size = _parse_chunk_size


def configure(config: object) -> object:
    """Install the guard for Gunicorn's statically configured Python parser."""
    install()
    return config
