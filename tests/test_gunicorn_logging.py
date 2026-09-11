import logging
import os
import socket
import subprocess
import sys
import time
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace

import pytest
from django.test import Client
from gunicorn.config import Config

from config import gunicorn_config, settings
from config.gunicorn_logging import RecoverySafeLogger, RecoverySecretFilter, redact_recovery_secrets


@pytest.mark.parametrize(
    "recovery_route",
    ("/account/recovery/confirm/", "/central/kiosk/pin/recovery/confirm/"),
)
def test_recovery_secret_is_redacted_from_request_targets_and_referrers(recovery_route: str) -> None:
    raw_token = "secret-token_123"
    recovery_path = f"{recovery_route}{raw_token}/"
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
    redacted_path = f"{recovery_route}[REDACTED]/"
    assert atoms["r"] == f"GET {redacted_path}?next=%2Fkiosk%2F HTTP/1.1"
    assert atoms["U"] == redacted_path
    assert atoms["f"] == f"https://example.test{redacted_path}"


def test_redaction_preserves_non_recovery_urls() -> None:
    url = "/kiosk/?next=%2Fbilling%2F"

    assert redact_recovery_secrets(url) == url


def test_gunicorn_uses_the_recovery_safe_access_logger() -> None:
    assert gunicorn_config.logger_class == "config.gunicorn_logging.RecoverySafeLogger"


def test_gunicorn_error_log_redacts_recovery_secret() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    logger = RecoverySafeLogger(Config())
    logger.error_log.addHandler(handler)
    logger.error_log.setLevel(logging.ERROR)
    raw_token = "gunicorn-error-recovery-secret"
    try:
        logger.error("Invalid HTTP request: %s", f"GET /account/recovery/confirm/{raw_token}/ HTTP/1.1")
    finally:
        logger.error_log.removeHandler(handler)
        handler.close()

    rendered = stream.getvalue()
    assert raw_token not in rendered
    assert "/account/recovery/confirm/[REDACTED]/" in rendered


def test_django_server_logger_uses_recovery_filter() -> None:
    logger_config = settings.LOGGING["loggers"]["django.server"]
    assert logger_config == {
        "handlers": ["console"],
        "propagate": False,
    }
    logger = logging.getLogger("django.server")
    console_handler = next(handler for handler in logger.handlers if handler.name == "console")
    assert any(isinstance(log_filter, RecoverySecretFilter) for log_filter in console_handler.filters)


def test_django_server_logs_redact_recovery_secret_for_get_post_and_status() -> None:
    stream = StringIO()
    logger = logging.getLogger("django.server")
    handler = next(handler for handler in logger.handlers if handler.name == "console")
    original_stream = handler.stream
    handler.setStream(stream)
    raw_token = "django-server-recovery-secret"
    try:
        for method, status in (("GET", 404), ("POST", 403)):
            logger.info(
                '"%s %s HTTP/1.1" %s 123',
                method,
                f"/account/recovery/confirm/{raw_token}/",
                status,
            )
    finally:
        handler.setStream(original_stream)

    rendered = stream.getvalue()
    assert raw_token not in rendered
    assert rendered.count("/account/recovery/confirm/[REDACTED]/") == 2
    assert '"GET /account/recovery/confirm/[REDACTED]/ HTTP/1.1" 404' in rendered
    assert '"POST /account/recovery/confirm/[REDACTED]/ HTTP/1.1" 403' in rendered


def test_real_gunicorn_wsgi_error_log_does_not_contain_recovery_secret() -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]

    raw_token = "raw-wsgi-recovery-secret_123"
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
    assert "Traceback (most recent call last)" in logs
    assert raw_token not in logs
    assert "[REDACTED]" in logs


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


def test_django_request_handler_redacts_recovery_secret() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RecoverySecretFilter())
    logger = logging.getLogger("django.request.test")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    try:
        logger.error("Internal Server Error: %s", "/account/recovery/confirm/raw-secret/")
    finally:
        logger.removeHandler(handler)
        handler.close()

    rendered = stream.getvalue()
    assert "raw-secret" not in rendered
    assert "/account/recovery/confirm/[REDACTED]/" in rendered


def test_csrf_rejection_log_redacts_recovery_secret() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("django.security.csrf")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    client = Client(enforce_csrf_checks=True)
    raw_token = "csrf-raw-recovery-secret"
    try:
        response = client.post(f"/account/recovery/confirm/{raw_token}/", {"pin": "1234"})
    finally:
        logger.removeHandler(handler)
        handler.close()

    assert response.status_code == 403
    rendered = stream.getvalue()
    assert raw_token not in rendered
    assert "/account/recovery/confirm/[REDACTED]/" in rendered
