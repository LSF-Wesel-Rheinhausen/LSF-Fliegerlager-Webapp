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
        run.return_value = Mock(returncode=0, stdout="", stderr="")
        deployment_agent.compose_up("sha256:old-image")

    command = run.call_args.args[0]
    assert command[-3:] == ["--no-deps", "--force-recreate", "app"]
    assert run.call_args.kwargs["env"]["APP_IMAGE"] == "sha256:old-image"
    assert run.call_args.kwargs["check"] is False


def test_compose_up_reports_stdout_and_stderr(monkeypatch):
    monkeypatch.setattr(deployment_agent, "PROJECT_NAME", "test-project")
    monkeypatch.setattr(deployment_agent, "TARGET_SERVICE", "app")

    result = Mock(returncode=1, stdout="creating app\n", stderr="port already allocated\n")
    with patch("deployment_agent.subprocess.run", return_value=result):
        with pytest.raises(deployment_agent.ComposeUpError) as error:
            deployment_agent.compose_up("sha256:new-image", step="Neuen App-Container starten")

    message = str(error.value)
    assert "Neuen App-Container starten fehlgeschlagen." in message
    assert "Exit-Code: 1" in message
    assert "stdout: creating app" in message
    assert "stderr: port already allocated" in message
    assert "secret" not in message.lower()


def test_wait_until_healthy_rejects_unhealthy_container(monkeypatch):
    container = Mock()
    container.image.id = "sha256:new"
    container.attrs = {"State": {"Health": {"Status": "unhealthy"}}}
    monkeypatch.setattr(deployment_agent, "service_container", lambda _service: container)

    with pytest.raises(RuntimeError, match="unhealthy"):
        deployment_agent.wait_until_healthy("sha256:new")


def test_perform_update_records_compose_and_rollback_diagnostics(monkeypatch):
    states = []
    old_container = Mock()
    old_container.image.id = "sha256:old"
    latest = Mock(id="sha256:new", labels={})
    compose_command = ["docker", "compose", "up", "app"]

    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)
    monkeypatch.setattr(deployment_agent, "service_container", lambda _service: old_container)
    monkeypatch.setattr(deployment_agent, "docker_client", lambda: Mock(images=Mock(pull=Mock(return_value=latest))))
    monkeypatch.setattr(deployment_agent, "create_backup", lambda: "backup.sql.gz")
    monkeypatch.setattr(
        deployment_agent,
        "compose_up",
        Mock(
            side_effect=[
                deployment_agent.ComposeUpError(
                    step="Neuen App-Container starten",
                    image="sha256:new",
                    command=compose_command,
                    returncode=1,
                    stdout="creating app",
                    stderr="port already allocated",
                ),
                deployment_agent.ComposeUpError(
                    step="Rollback: alten App-Container starten",
                    image="sha256:old",
                    command=compose_command,
                    returncode=1,
                    stdout="",
                    stderr="image unavailable",
                ),
            ]
        ),
    )

    deployment_agent.update_lock.acquire()
    deployment_agent.perform_update()

    failed_state = states[-1]
    assert failed_state["phase"] == "failed"
    assert "port already allocated" in failed_state["error"]
    assert "image unavailable" in failed_state["rollback_error"]
    assert "backup.sql.gz" in failed_state["recovery"]
    assert "sha256:old" in failed_state["recovery"]
