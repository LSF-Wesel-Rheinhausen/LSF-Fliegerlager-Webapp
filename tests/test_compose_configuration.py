from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("compose_path", ["docker-compose.yml", "deploy/docker-compose.example.yml"])
def test_background_workers_disable_inherited_http_healthcheck(compose_path: str) -> None:
    configuration = yaml.safe_load((PROJECT_ROOT / compose_path).read_text(encoding="utf-8"))

    for service_name in ("daily-settlement-backup", "push-worker"):
        assert configuration["services"][service_name]["healthcheck"] == {"disable": True}
