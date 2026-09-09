import os
import socket
import subprocess
import sys
import time
from datetime import timedelta
from types import SimpleNamespace

from gunicorn.config import Config

from config import gunicorn_config
from config.gunicorn_logging import RecoverySafeLogger, redact_recovery_secrets


def test_recovery_secret_is_redacted_from_request_targets_and_referrers() -> None:
    raw_token = "secret-token_123"
    recovery_path = f"/account/recovery/confirm/{raw_token}/"
    logger = RecoverySafeLogger(Config())

    atoms = logger.atoms(
        SimpleNamespace(status="200 OK", sent=42, headers=[]),
        {"Referer": f"https://example.test{recovery_path}"},
        {
            "REMOTE_ADDR": "127.0.0.1",
            "REQUEST_METHOD": "GET",
            "RAW_URI": f"{recovery_path}?next=%2Fkiosk%2F",
            "PATH_INFO": recovery_path,
            "QUERY_STRING": "next=%2Fkiosk%2F",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "HTTP_REFERER": f"https://example.test{recovery_path}",
        },
        timedelta(milliseconds=12),
    )

    rendered_atoms = " ".join(str(value) for value in atoms.values())
    assert raw_token not in rendered_atoms
    assert atoms["r"] == "GET /account/recovery/confirm/[REDACTED]/?next=%2Fkiosk%2F HTTP/1.1"
    assert atoms["U"] == "/account/recovery/confirm/[REDACTED]/"
    assert atoms["f"] == "https://example.test/account/recovery/confirm/[REDACTED]/"


def test_redaction_preserves_non_recovery_urls() -> None:
    url = "/kiosk/?next=%2Fbilling%2F"

    assert redact_recovery_secrets(url) == url


def test_gunicorn_uses_the_recovery_safe_access_logger() -> None:
    assert gunicorn_config.logger_class == "config.gunicorn_logging.RecoverySafeLogger"


def test_real_gunicorn_access_log_does_not_contain_recovery_secret() -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]

    raw_token = "raw-recovery-secret_123"
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
        "--access-logfile",
        "-",
        "--error-logfile",
        "-",
    ]
    environment = os.environ | {"PYTHONPATH": "src", "DJANGO_DEBUG": "1", "DJANGO_SETTINGS_MODULE": "config.settings"}
    process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2) as client:
                    client.sendall(
                        f"GET /account/recovery/confirm/{raw_token}/ HTTP/1.1\r\n"
                        "Host: localhost\r\nConnection: close\r\n\r\n".encode()
                    )
                    client.recv(4096)
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("Gunicorn did not become ready")
    finally:
        process.terminate()
        stdout, stderr = process.communicate(timeout=10)

    logs = (stdout + stderr).decode(errors="replace")
    access_line = next(line for line in logs.splitlines() if "/account/recovery/confirm/[REDACTED]/" in line)
    assert raw_token not in access_line
