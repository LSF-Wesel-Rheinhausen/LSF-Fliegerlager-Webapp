import os
from unittest.mock import Mock, patch

import pytest

os.environ.setdefault("UPDATE_AGENT_TOKEN", "test-agent-token")

import deployment_agent  # noqa: E402


def test_image_metadata_reads_oci_and_change_labels():
    image = Mock(
        id="sha256:123",
        labels={
            "org.opencontainers.image.version": "1.2.3",
            "org.opencontainers.image.revision": "abc123",
            "org.opencontainers.image.created": "2026-06-09T12:00:00Z",
            "io.lsf-fliegerlager.change": "feat: deployment updates",
        },
    )

    assert deployment_agent.image_metadata(image) == {
        "id": "sha256:123",
        "version": "1.2.3",
        "revision": "abc123",
        "build_date": "2026-06-09T12:00:00Z",
        "change": "feat: deployment updates",
    }


def test_compose_up_limits_reconciliation_to_app_service(monkeypatch):
    monkeypatch.setattr(deployment_agent, "PROJECT_NAME", "test-project")
    monkeypatch.setattr(deployment_agent, "TARGET_SERVICE", "app")

    with patch("deployment_agent.subprocess.run") as run:
        deployment_agent.compose_up("sha256:old-image")

    command = run.call_args.args[0]
    assert command[-3:] == ["--no-deps", "--force-recreate", "app"]
    assert run.call_args.kwargs["env"]["APP_IMAGE"] == "sha256:old-image"
    assert run.call_args.kwargs["check"] is True


def test_wait_until_healthy_rejects_unhealthy_container(monkeypatch):
    container = Mock()
    container.image.id = "sha256:new"
    container.attrs = {"State": {"Health": {"Status": "unhealthy"}}}
    monkeypatch.setattr(deployment_agent, "service_container", lambda _service: container)

    with pytest.raises(RuntimeError, match="unhealthy"):
        deployment_agent.wait_until_healthy("sha256:new")
