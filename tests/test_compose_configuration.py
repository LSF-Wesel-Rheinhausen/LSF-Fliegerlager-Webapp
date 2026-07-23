from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("compose_path", ["docker-compose.yml", "deploy/docker-compose.example.yml"])
def test_background_workers_disable_inherited_http_healthcheck(compose_path: str) -> None:
    configuration = yaml.safe_load((PROJECT_ROOT / compose_path).read_text(encoding="utf-8"))

    for service_name in ("daily-settlement-backup", "push-worker", "email-worker"):
        assert configuration["services"][service_name]["healthcheck"] == {"disable": True}


@pytest.mark.parametrize("compose_path", ["docker-compose.yml", "deploy/docker-compose.example.yml"])
def test_email_worker_uses_read_only_webpush_key_mount(compose_path: str) -> None:
    configuration = yaml.safe_load((PROJECT_ROOT / compose_path).read_text(encoding="utf-8"))
    email_worker = configuration["services"]["email-worker"]

    assert email_worker["environment"]["WEB_PUSH_KEY_DIR"] == "/run/secrets/webpush"
    assert "${PERSISTENCE_DIR:-./data}/secrets/webpush:/run/secrets/webpush:ro" in email_worker["volumes"]
