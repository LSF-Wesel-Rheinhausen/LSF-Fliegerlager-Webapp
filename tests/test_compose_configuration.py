from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_NON_UPDATER_ENVIRONMENT_KEYS = {
    "PORTAINER_URL",
    "PORTAINER_API_KEY",
    "PORTAINER_ENDPOINT_ID",
    "PORTAINER_STACK_ID",
    "GHCR_TOKEN",
}

EXPECTED_SERVICE_ENVIRONMENT_KEYS = {
    "app": {
        "AUTHELIA_SSO_EMAIL_HEADER",
        "AUTHELIA_SSO_ENABLED",
        "BACKUP_DIR",
        "CSRF_TRUSTED_ORIGINS",
        "DATABASE_URL",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_DEBUG",
        "DJANGO_HSTS_INCLUDE_SUBDOMAINS",
        "DJANGO_HSTS_PRELOAD",
        "DJANGO_HSTS_SECONDS",
        "DJANGO_HTTPS",
        "DJANGO_SECRET_KEY",
        "DJANGO_TRUST_PROXY_SSL_HEADER",
        "GUNICORN_CMD_ARGS",
        "KIOSK_ACCESS_TRUSTED_PROXY_ADDRESSES",
        "PASSKEY_ENABLED",
        "PASSKEY_ORIGIN",
        "PASSKEY_RP_ID",
        "PASSKEY_RP_NAME",
        "UPDATE_AGENT_TOKEN",
        "UPDATE_AGENT_URL",
        "WEB_PUSH_ALLOWED_ORIGINS",
        "WEB_PUSH_ENABLED",
        "WEB_PUSH_KEY_DIR",
        "WEB_PUSH_VAPID_PRIVATE_KEY",
        "WEB_PUSH_VAPID_PUBLIC_KEY",
        "WEB_PUSH_VAPID_SUBJECT",
    },
    "daily-settlement-backup": {
        "BACKUP_DIR",
        "DATABASE_URL",
        "DAILY_SETTLEMENT_BACKUP_INTERVAL_SECONDS",
        "DJANGO_DEBUG",
        "DJANGO_SECRET_KEY",
    },
    "push-worker": {
        "DATABASE_URL",
        "DJANGO_DEBUG",
        "DJANGO_SECRET_KEY",
        "WEB_PUSH_ALLOWED_ORIGINS",
        "WEB_PUSH_ENABLED",
        "WEB_PUSH_KEY_DIR",
        "WEB_PUSH_VAPID_PRIVATE_KEY",
        "WEB_PUSH_VAPID_PUBLIC_KEY",
        "WEB_PUSH_VAPID_SUBJECT",
        "WEB_PUSH_WORKER_INTERVAL_SECONDS",
    },
    "email-worker": {
        "DATABASE_URL",
        "DJANGO_DEBUG",
        "DJANGO_SECRET_KEY",
    },
}


def test_app_container_defaults_to_production_mode() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "    DJANGO_DEBUG=0 \\\n" in dockerfile
    assert "DJANGO_SECRET_KEY=" not in dockerfile


@pytest.mark.parametrize("compose_path", ["docker-compose.yml", "deploy/docker-compose.example.yml"])
def test_background_workers_disable_inherited_http_healthcheck(compose_path: str) -> None:
    configuration = yaml.safe_load((PROJECT_ROOT / compose_path).read_text(encoding="utf-8"))

    for service_name in ("daily-settlement-backup", "push-worker", "email-worker"):
        assert configuration["services"][service_name]["healthcheck"] == {"disable": True}


@pytest.mark.parametrize("compose_path", ["docker-compose.yml", "deploy/docker-compose.example.yml"])
def test_email_worker_does_not_receive_webpush_keys(compose_path: str) -> None:
    configuration = yaml.safe_load((PROJECT_ROOT / compose_path).read_text(encoding="utf-8"))
    email_worker = configuration["services"]["email-worker"]

    assert "WEB_PUSH_KEY_DIR" not in email_worker["environment"]
    assert not any("/secrets/webpush" in volume for volume in email_worker.get("volumes", []))


@pytest.mark.parametrize("compose_path", ["docker-compose.yml", "deploy/docker-compose.example.yml"])
def test_django_services_use_explicit_secret_scoped_environment_allowlists(compose_path: str) -> None:
    configuration = yaml.safe_load((PROJECT_ROOT / compose_path).read_text(encoding="utf-8"))
    services = configuration["services"]

    updater_environment = set(services["updater"]["environment"])
    assert FORBIDDEN_NON_UPDATER_ENVIRONMENT_KEYS <= updater_environment

    for service_name, expected_keys in EXPECTED_SERVICE_ENVIRONMENT_KEYS.items():
        service = services[service_name]
        assert "env_file" not in service, service_name
        assert set(service["environment"]) == expected_keys
        assert not FORBIDDEN_NON_UPDATER_ENVIRONMENT_KEYS.intersection(service["environment"])
