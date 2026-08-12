from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from gunicorn.config import Config
from gunicorn.http.body import ChunkedReader
from gunicorn.http.errors import LimitRequestLine

from config import gunicorn_config, gunicorn_parser_guard


class FragmentedUnreader:
    def __init__(self, fragments: list[bytes]) -> None:
        self.fragments = iter(fragments)
        self.read_count = 0

    def read(self) -> bytes:
        self.read_count += 1
        return next(self.fragments, b"")

    def unread(self, data: bytes) -> None:
        raise AssertionError(f"unexpected unread: {data!r}")


def parse_chunk_size(fragments: list[bytes], data: bytes | None = None) -> tuple[int, bytes | None, int]:
    unreader = FragmentedUnreader(fragments)
    reader = object.__new__(ChunkedReader)
    size, rest = reader.parse_chunk_size(unreader, data=data)
    return size, rest, unreader.read_count


@pytest.fixture(autouse=True)
def install_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gunicorn_parser_guard, "SUPPORTED_GUNICORN_VERSION", "26.0.0")
    gunicorn_parser_guard.install()


def test_chunk_metadata_line_without_crlf_at_8192_bytes_is_rejected() -> None:
    with pytest.raises(LimitRequestLine) as raised:
        parse_chunk_size([b"a" * 8192])

    assert raised.value.code == 400
    assert raised.value.max_size == gunicorn_parser_guard.MAX_CHUNK_METADATA_SIZE


def test_chunk_metadata_line_without_crlf_at_8193_bytes_is_rejected() -> None:
    unreader = FragmentedUnreader([b"a" * 8192, b"a"])
    reader = object.__new__(ChunkedReader)

    with pytest.raises(LimitRequestLine) as raised:
        reader.parse_chunk_size(unreader)

    assert raised.value.code == 400
    assert unreader.read_count == 2


def test_large_fragmented_metadata_is_rejected_before_full_line_is_buffered() -> None:
    unreader = FragmentedUnreader([b"a" * 8192] * 32)
    reader = object.__new__(ChunkedReader)

    with pytest.raises(LimitRequestLine):
        reader.parse_chunk_size(unreader)

    assert unreader.read_count == 2


def test_crlf_at_8192_bytes_is_valid() -> None:
    size, rest, read_count = parse_chunk_size([b"1;" + b"x" * 8190 + b"\r\nBODY"])

    assert size == 1
    assert rest == b"BODY"
    assert read_count == 1


def test_chunk_metadata_and_body_in_one_read_preserve_body() -> None:
    size, rest, _ = parse_chunk_size([b"4\r\ndata\r\n"])

    assert size == 4
    assert rest == b"data\r\n"


def test_chunk_metadata_crlf_split_across_reads_is_valid() -> None:
    size, rest, read_count = parse_chunk_size([b"4", b"\r", b"\ndata"])

    assert size == 4
    assert rest == b"data"
    assert read_count == 3


def test_install_fails_closed_for_unsupported_gunicorn_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gunicorn_parser_guard, "SUPPORTED_GUNICORN_VERSION", "26.0.0")
    monkeypatch.setattr(gunicorn_parser_guard.gunicorn, "__version__", "26.0.1")

    with pytest.raises(RuntimeError, match="26.0.0"):
        gunicorn_parser_guard.install()


def test_guard_configuration_uses_python_parser_and_installs_guard() -> None:
    config = Config()
    assert config.http_parser == "auto"
    assert gunicorn_config.http_parser == "python"

    assert gunicorn_parser_guard.configure(config) is config
    assert config.http_parser == "auto"


@pytest.mark.parametrize("parser", ["auto", "fast", "rust"])
def test_on_starting_fails_closed_for_non_python_parser(parser: str) -> None:
    server = SimpleNamespace(cfg=SimpleNamespace(http_parser=parser))

    with pytest.raises(RuntimeError, match="(?i)parser.*python"):
        gunicorn_config.on_starting(server)


@pytest.mark.parametrize(
    ("parser", "expected_error"),
    [
        ("auto", "Unsafe Gunicorn HTTP parser"),
        ("fast", "Unsafe Gunicorn HTTP parser"),
        ("rust", "http_parser must be one of"),
    ],
)
def test_real_gunicorn_start_fails_closed_for_cmd_args_parser_override(parser: str, expected_error: str) -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]

    command = [
        sys.executable,
        "-m",
        "gunicorn",
        "tests.gunicorn_probe_app:application",
        "--config",
        "python:config.gunicorn_config",
        "--bind",
        f"127.0.0.1:{port}",
        "--workers",
        "1",
        "--worker-class",
        "sync",
        "--timeout",
        "2",
        "--log-level",
        "error",
    ]
    environment = os.environ | {
        "GUNICORN_CMD_ARGS": f"--http-parser={parser}",
        "PYTHONPATH": "src",
        "DJANGO_DEBUG": "1",
        "DJANGO_SETTINGS_MODULE": "config.settings",
    }
    process = subprocess.Popen(
        command,
        cwd=".",
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(timeout=10)

    assert process.returncode != 0
    assert expected_error.encode() in stderr
    assert b"Starting gunicorn" not in stdout + stderr


@pytest.mark.parametrize("worker_class", ["sync", "gthread"])
def test_real_worker_rejects_oversized_chunk_and_keeps_healthcheck_alive(worker_class: str) -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]

    command = [
        sys.executable,
        "-m",
        "gunicorn",
        "tests.gunicorn_probe_app:application",
        "--config",
        "python:config.gunicorn_config",
        "--bind",
        f"127.0.0.1:{port}",
        "--workers",
        "1",
        "--worker-class",
        worker_class,
        "--threads",
        "2",
        "--timeout",
        "10",
        "--log-level",
        "error",
    ]
    environment = os.environ | {
        "PYTHONPATH": "src",
        "DJANGO_DEBUG": "1",
        "DJANGO_SETTINGS_MODULE": "config.settings",
    }
    process = subprocess.Popen(command, cwd=".", env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2) as probe:
                    probe.sendall(b"GET /healthz/ HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                    if b" 200 " in probe.recv(4096):
                        break
            except OSError:
                time.sleep(0.05)
        else:
            process.terminate()
            _stdout, stderr = process.communicate(timeout=10)
            raise AssertionError(f"Gunicorn did not become ready: {stderr.decode(errors='replace')}")

        with socket.create_connection(("127.0.0.1", port), timeout=3) as attack:
            attack.sendall(b"POST /chunk-probe HTTP/1.1\r\nHost: localhost\r\nTransfer-Encoding: chunked\r\n\r\n")
            attack.sendall(b"a" * 8193 + b"\r\n")
            response = attack.recv(4096)
        assert b" 400 " in response

        with socket.create_connection(("127.0.0.1", port), timeout=3) as health:
            health.sendall(b"GET /healthz/ HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
            response = health.recv(4096)
        assert b" 200 " in response
    finally:
        process.terminate()
        process.wait(timeout=10)
