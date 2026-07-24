import os
import urllib.error
from unittest.mock import Mock, call, patch

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
            "io.lsf-fliegerlager.changelog": (
                '[{"revision":"abc123","title":"Deployment updates","body":"Updater hardening"}]'
            ),
        },
    )

    assert deployment_agent.image_metadata(image) == {
        "id": "sha256:123",
        "image": deployment_agent.TARGET_IMAGE,
        "version": "1.2.3",
        "revision": "abc123",
        "build_date": "2026-06-09T12:00:00Z",
        "change": "feat: deployment updates",
        "changelog": [{"revision": "abc123", "title": "Deployment updates", "body": "Updater hardening", "path": ""}],
    }


def test_image_metadata_ignores_invalid_changelog_labels():
    image = Mock(
        id="sha256:123",
        labels={
            "org.opencontainers.image.version": "1.2.3",
            "org.opencontainers.image.revision": "abc123",
            "org.opencontainers.image.created": "2026-06-09T12:00:00Z",
            "io.lsf-fliegerlager.change": "feat: deployment updates",
            "io.lsf-fliegerlager.changelog": '{"not":"a-list"}',
        },
    )

    assert deployment_agent.image_metadata(image)["changelog"] == []


def test_portainer_request_uses_api_key_and_endpoint_id():
    client = deployment_agent.PortainerClient(
        base_url="https://portainer.example.org",
        api_key="ptr_secret",
        endpoint_id="7",
        stack_id="123",
    )
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status = 200
    response.read.return_value = b'{"Id":123}'

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        result = client.request("GET", "/stacks/123", query={"endpointId": "7"})

    request = urlopen.call_args.args[0]
    assert request.full_url == "https://portainer.example.org/api/stacks/123?endpointId=7"
    assert request.get_header("X-api-key") == "ptr_secret"
    assert urlopen.call_args.kwargs["context"] is None
    assert result == {"Id": 123}


def test_portainer_request_can_disable_ssl_verification():
    client = deployment_agent.PortainerClient(
        base_url="https://portainer.internal",
        api_key="ptr_secret",
        endpoint_id="7",
        stack_id="123",
        verify_ssl="false",
    )
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status = 200
    response.read.return_value = b"{}"

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        client.request("GET", "/stacks/123")

    context = urlopen.call_args.kwargs["context"]
    assert context is not None
    assert context.check_hostname is False
    assert context.verify_mode == deployment_agent.ssl.CERT_NONE


def test_portainer_verify_ssl_rejects_ambiguous_values():
    with pytest.raises(deployment_agent.AgentConfigError, match="PORTAINER_VERIFY_SSL"):
        deployment_agent.PortainerClient(
            base_url="https://portainer.example.org",
            api_key="ptr_secret",
            endpoint_id="7",
            stack_id="123",
            verify_ssl="0",
        )


def test_missing_portainer_env_values_fail_clearly(monkeypatch):
    monkeypatch.setattr(deployment_agent, "PORTAINER_URL", "")

    with pytest.raises(deployment_agent.AgentConfigError, match="PORTAINER_URL"):
        deployment_agent.PortainerClient()


def test_update_stack_image_sets_app_image_in_portainer_payload():
    client = deployment_agent.PortainerClient(
        base_url="https://portainer.example.org",
        api_key="ptr_secret",
        endpoint_id="7",
        stack_id="123",
    )
    stack = {
        "Env": [{"name": "APP_IMAGE", "value": "ghcr.io/example/app:old"}],
        "StackFileContent": "services:\n  app:\n    image: ${APP_IMAGE}\n",
    }

    with patch.object(client, "get_stack", return_value=stack):
        with patch.object(client, "request", return_value={}) as request:
            client.update_stack_image("ghcr.io/example/app:new")

    request.assert_called_once_with(
        "PUT",
        "/stacks/123",
        query={"endpointId": "7"},
        payload={
            "env": [{"name": "APP_IMAGE", "value": "ghcr.io/example/app:new"}],
            "prune": False,
            "pullImage": True,
            "stackFileContent": "services:\n  app:\n    image: ${APP_IMAGE}\n",
        },
        timeout=180,
    )


def test_perform_update_rolls_back_previous_app_image(monkeypatch):
    states = []
    client = Mock()
    client.docker_request.side_effect = [
        [{"ImageID": "sha256:old-config"}],
        {"RepoDigests": ["ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp@sha256:old-manifest"]},
    ]
    client.update_stack_image.side_effect = [
        deployment_agent.PortainerAPIError("Portainer API: update failed"),
        None,
    ]

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", lambda _image: {"id": "sha256:new"})
    monkeypatch.setattr(deployment_agent, "create_backup", lambda: "backup.sql.gz")
    monkeypatch.setattr(deployment_agent, "wait_until_healthy", Mock())
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    deployment_agent.update_lock.acquire()
    deployment_agent.perform_update()

    assert client.update_stack_image.mock_calls == [
        call(deployment_agent.TARGET_IMAGE),
        call("ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp@sha256:old-manifest"),
    ]
    failed_state = states[-1]
    assert failed_state["phase"] == "failed"
    assert "Portainer API: update failed" in failed_state["error"]
    assert (
        "Rollback-Image fuer APP_IMAGE: ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp@sha256:old-manifest"
        in failed_state["recovery"]
    )
    assert "backup.sql.gz" in failed_state["recovery"]


def test_create_backup_uses_database_url_without_leaking_password(monkeypatch, tmp_path):
    monkeypatch.setattr(
        deployment_agent,
        "DATABASE_URL",
        "postgres://fliegerlager:super-secret-password@db:5432/fliegerlager",
    )
    monkeypatch.setattr(deployment_agent, "BACKUP_DIR", tmp_path)
    result = Mock(returncode=1, stdout=b"", stderr=b"password authentication failed for user fliegerlager")

    with patch("deployment_agent.subprocess.run", return_value=result) as run:
        with pytest.raises(RuntimeError) as error:
            deployment_agent.create_backup()

    command = run.call_args.args[0]
    assert "super-secret-password" not in command
    assert run.call_args.kwargs["env"]["PGPASSWORD"] == "super-secret-password"
    assert "super-secret-password" not in str(error.value)


def test_backup_child_path_rejects_path_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_agent, "BACKUP_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="ungültig"):
        deployment_agent.backup_child_path("../outside")


def test_create_backup_archive_contains_database_dump_and_exports(monkeypatch, tmp_path):
    staging = tmp_path / "staging" / "run"
    staging.mkdir(parents=True)
    (staging / "manifest.json").write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(deployment_agent, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(deployment_agent, "database_dump_bytes", lambda: b"-- database dump")

    backup_name = deployment_agent.create_backup_archive("staging/run", "daily-test")

    import tarfile

    with tarfile.open(tmp_path / backup_name, "r:gz") as archive:
        assert sorted(archive.getnames()) == ["database.sql", "exports/manifest.json"]
        dump = archive.extractfile("database.sql")
        assert dump is not None
        assert dump.read() == b"-- database dump"


def test_wait_until_healthy_polls_app_health_url(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status = 204
    monkeypatch.setattr(deployment_agent, "APP_HEALTH_URL", "http://app:8000/healthz/")

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        deployment_agent.wait_until_healthy()

    assert urlopen.call_args.args[0] == "http://app:8000/healthz/"


def test_check_update_detects_update_from_oci_labels(monkeypatch):
    states = []
    client = Mock()
    client.get_stack.return_value = {"Env": [{"name": "APP_IMAGE", "value": "ghcr.io/example/app:latest"}]}
    latest = {
        "id": "sha256:new",
        "image": "ghcr.io/example/app:latest",
        "version": "1.2.4",
        "revision": "newrev",
        "build_date": "2026-06-10T12:00:00Z",
        "change": "fix: updater",
        "changelog": [
            {"revision": "oldrev", "title": "Old", "body": "Already installed"},
            {"revision": "newrev", "title": "New", "body": "Install me"},
        ],
    }

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", lambda _image: latest)
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    result = deployment_agent.check_update(
        {"current": {"version": "1.2.3", "revision": "oldrev", "build_date": "2026-06-09T12:00:00Z"}}
    )

    assert result["latest"] == latest
    assert result["running"]["revision"] == "oldrev"
    assert result["update_available"] is True
    assert result["changelog"] == [{"revision": "newrev", "title": "New", "body": "Install me", "path": ""}]


def test_changelog_between_versions_keeps_entries_after_current_revision():
    latest = {
        "revision": "rev3",
        "changelog": [
            {"revision": "rev1", "title": "One", "body": ""},
            {"revision": "rev2", "title": "Two", "body": ""},
            {"revision": "rev3", "title": "Three", "body": ""},
        ],
    }

    result = deployment_agent.changelog_between_versions(latest, {"revision": "rev1"})

    assert [entry["title"] for entry in result] == ["Two", "Three"]


def test_changelog_between_versions_uses_versions_when_current_revision_has_no_entry():
    latest = {
        "version": "13",
        "revision": "rev13",
        "changelog": [
            {"version": "10", "revision": "rev10", "title": "Ten", "body": ""},
            {"version": "12", "revision": "rev12", "title": "Twelve", "body": ""},
            {"version": "13", "revision": "rev13", "title": "Thirteen", "body": ""},
        ],
    }

    result = deployment_agent.changelog_between_versions(
        latest,
        {"version": "11", "revision": "commit-without-changelog"},
    )

    assert [(entry["version"], entry["title"]) for entry in result] == [
        ("12", "Twelve"),
        ("13", "Thirteen"),
    ]


def test_changelog_between_versions_hides_history_when_current_revision_is_unknown():
    latest = {
        "revision": "rev3",
        "changelog": [
            {"revision": "rev1", "title": "One", "body": ""},
            {"revision": "rev2", "title": "Two", "body": ""},
            {"revision": "rev3", "title": "Three", "body": ""},
        ],
    }

    result = deployment_agent.changelog_between_versions(latest, {"revision": "merge-revision-not-in-manifest"})

    assert result == []


def test_check_update_detects_rebuild_with_same_revision(monkeypatch):
    client = Mock()
    client.get_stack.return_value = {"Env": [{"name": "APP_IMAGE", "value": "ghcr.io/example/app:latest"}]}
    latest = {
        "id": "sha256:new",
        "image": "ghcr.io/example/app:latest",
        "version": "1.2.3",
        "revision": "same",
        "build_date": "2026-06-10T12:00:00Z",
        "change": "fix: updater",
    }

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", lambda _image: latest)
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: values)

    result = deployment_agent.check_update(
        {"current": {"version": "1.2.3", "revision": "same", "build_date": "2026-06-09T12:00:00Z"}}
    )

    assert result["update_available"] is True


def test_check_update_persists_no_update_status(monkeypatch):
    states = []
    client = Mock()
    client.get_stack.return_value = {"Env": [{"name": "APP_IMAGE", "value": "ghcr.io/example/app:latest"}]}
    latest = {
        "id": "sha256:new",
        "image": "ghcr.io/example/app:latest",
        "version": "1.2.3",
        "revision": "same",
        "build_date": "2026-06-10T12:00:00Z",
        "change": "fix: updater",
    }

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", lambda _image: latest)
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    result = deployment_agent.check_update(
        {"current": {"version": "1.2.3", "revision": "same", "build_date": "2026-06-10T12:00:00Z"}}
    )

    assert result["update_available"] is False
    assert states[-1]["update_available"] is False
    assert states[-1]["running"]["revision"] == "same"


def test_deployment_status_respects_persisted_update_available(monkeypatch):
    client = Mock()
    client.get_stack.return_value = {"Env": [{"name": "APP_IMAGE", "value": "ghcr.io/example/app:latest"}]}
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "load_state",
        lambda: {"latest": {"id": "sha256:new"}, "phase": "checked", "update_available": False},
    )

    result = deployment_agent.deployment_status()

    assert result["update_available"] is False


def test_immutable_running_image_reads_repo_digest_via_portainer_docker_proxy():
    client = Mock()
    client.docker_request.side_effect = [
        [{"ImageID": "sha256:old-config"}],
        {
            "RepoDigests": [
                "ghcr.io/other/app@sha256:other",
                "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp@sha256:old-manifest",
            ]
        },
    ]

    result = deployment_agent.immutable_running_image(client)

    assert result == "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp@sha256:old-manifest"
    assert client.docker_request.mock_calls[0] == call(
        "GET",
        "/containers/json",
        query={"filters": '{"label": ["com.docker.compose.service=app"], "status": ["running"]}'},
    )
    assert client.docker_request.mock_calls[1] == call("GET", "/images/sha256%3Aold-config/json")


def test_perform_update_clears_update_available_after_success(monkeypatch):
    states = []
    client = Mock()
    client.docker_request.side_effect = [
        [{"ImageID": "sha256:old-config"}],
        {"RepoDigests": ["ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp@sha256:old-manifest"]},
    ]
    latest = {"id": "sha256:new", "image": deployment_agent.TARGET_IMAGE}

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", lambda _image: latest)
    monkeypatch.setattr(deployment_agent, "create_backup", lambda: "backup.sql.gz")
    monkeypatch.setattr(deployment_agent, "wait_until_healthy", Mock())
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    deployment_agent.update_lock.acquire()
    deployment_agent.perform_update()

    complete_state = states[-1]
    assert complete_state["phase"] == "complete"
    assert complete_state["update_available"] is False


def test_registry_token_request_uses_configured_ghcr_token(monkeypatch):
    token_response = Mock()
    token_response.__enter__ = Mock(return_value=token_response)
    token_response.__exit__ = Mock(return_value=False)
    token_response.read.return_value = b'{"token":"bearer-token"}'
    token_response.status = 200

    monkeypatch.setattr(deployment_agent, "GHCR_TOKEN", "private-token")
    auth_header = 'Bearer realm="https://ghcr.io/token",service="ghcr.io",scope="repository:owner/app:pull"'

    with patch("urllib.request.urlopen", return_value=token_response) as urlopen:
        token = deployment_agent.fetch_registry_token(auth_header)

    request = urlopen.call_args.args[0]
    assert request.get_header("Authorization") == "Basic dW51c2VkOnByaXZhdGUtdG9rZW4="
    assert token == "bearer-token"


def test_registry_request_uses_bearer_token_after_private_registry_challenge(monkeypatch):
    unauthorized = urllib.error.HTTPError(
        url="https://ghcr.io/v2/owner/app/manifests/latest",
        code=401,
        msg="unauthorized",
        hdrs={"WWW-Authenticate": 'Bearer realm="https://ghcr.io/token",service="ghcr.io"'},
        fp=None,
    )
    manifest_response = Mock()
    manifest_response.__enter__ = Mock(return_value=manifest_response)
    manifest_response.__exit__ = Mock(return_value=False)
    manifest_response.read.return_value = b"{}"
    manifest_response.headers = {"Docker-Content-Digest": "sha256:new"}

    monkeypatch.setattr(deployment_agent, "GHCR_TOKEN", "private-token")
    monkeypatch.setattr(deployment_agent, "fetch_registry_token", Mock(return_value="bearer-token"))

    with patch("urllib.request.urlopen", side_effect=[unauthorized, manifest_response]) as urlopen:
        deployment_agent.registry_request("https://ghcr.io/v2/owner/app/manifests/latest", accept="application/json")

    retried_request = urlopen.call_args_list[1].args[0]
    assert retried_request.get_header("Authorization") == "Bearer bearer-token"
