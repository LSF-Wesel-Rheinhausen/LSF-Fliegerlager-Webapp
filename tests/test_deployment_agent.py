import io
import os
import threading
import urllib.error
from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import Mock, call, patch

import pytest

os.environ.setdefault("UPDATE_AGENT_TOKEN", "test-agent-token")

import deployment_agent  # noqa: E402


def image_digest(character: str = "a") -> str:
    """Return a syntactically valid digest for updater unit tests."""
    return f"sha256:{character * 64}"


def target_digest_reference(digest: str) -> str:
    """Return the configured target repository bound to a digest."""
    registry, repository, _reference = deployment_agent.parse_image_reference(deployment_agent.TARGET_IMAGE)
    return f"{registry}/{repository}@{digest}"


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
    digest = image_digest("a")
    approved_image = target_digest_reference(digest)
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
    monkeypatch.setattr(
        deployment_agent,
        "load_state",
        lambda: {
            "latest": {"id": digest, "image": deployment_agent.TARGET_IMAGE},
            "approved_image": approved_image,
            "approved_digest": digest,
            "changelog": [],
        },
    )
    monkeypatch.setattr(deployment_agent, "create_backup", lambda: "backup.sql.gz")
    monkeypatch.setattr(deployment_agent, "wait_until_healthy", Mock())
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    deployment_agent.update_lock.acquire()
    deployment_agent.perform_update()

    assert client.update_stack_image.mock_calls == [
        call(approved_image),
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
        "id": image_digest("a"),
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
        "id": image_digest("a"),
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
        "id": image_digest("a"),
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
    digest = image_digest("a")
    approved_image = target_digest_reference(digest)
    old_image = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp@sha256:old-manifest"
    client = Mock()
    client.docker_request.side_effect = [
        [{"ImageID": "sha256:old-config"}],
        {"RepoDigests": [old_image]},
        [{"ImageID": "sha256:new-config"}],
        {"RepoDigests": [approved_image]},
    ]
    latest = {"id": digest, "image": deployment_agent.TARGET_IMAGE}

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "load_state",
        lambda: {
            "latest": latest,
            "approved_image": approved_image,
            "approved_digest": digest,
            "changelog": [],
        },
    )
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


def test_read_json_body_requires_content_length():
    handler = Mock()
    handler.headers = {}

    with pytest.raises(RuntimeError) as error:
        deployment_agent.read_json_body(handler)

    assert error.value.status == HTTPStatus.LENGTH_REQUIRED
    assert error.value.public_code == "content_length_required"


@pytest.mark.parametrize(
    ("content_length", "expected_status", "expected_code"),
    [
        ("invalid", HTTPStatus.BAD_REQUEST, "invalid_content_length"),
        ("-1", HTTPStatus.BAD_REQUEST, "invalid_content_length"),
        ("9" * 5000, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large"),
        ("1048577", HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large"),
    ],
)
def test_read_json_body_rejects_invalid_or_oversized_content_length(content_length, expected_status, expected_code):
    handler = Mock()
    handler.headers = {"Content-Length": content_length}

    with pytest.raises(RuntimeError) as error:
        deployment_agent.read_json_body(handler)

    assert error.value.status == expected_status
    assert error.value.public_code == expected_code


def test_read_json_body_accepts_payload_at_documented_limit():
    value_length = 1_048_576 - len('{"value":""}')
    raw = ('{"value":"' + ("a" * value_length) + '"}').encode("utf-8")
    handler = Mock()
    handler.headers = {"Content-Length": str(len(raw))}
    handler.rfile = io.BytesIO(raw)

    assert deployment_agent.read_json_body(handler) == {"value": "a" * value_length}


def test_read_json_body_rejects_incomplete_read():
    handler = Mock()
    handler.headers = {"Content-Length": "10"}
    handler.rfile = io.BytesIO(b"{}")

    with pytest.raises(RuntimeError) as error:
        deployment_agent.read_json_body(handler)

    assert error.value.status == HTTPStatus.BAD_REQUEST
    assert error.value.public_code == "incomplete_body"


def test_read_json_body_maps_socket_timeout_to_request_timeout():
    handler = Mock()
    handler.headers = {"Content-Length": "2"}
    handler.rfile.read.side_effect = TimeoutError

    with pytest.raises(RuntimeError) as error:
        deployment_agent.read_json_body(handler)

    assert error.value.status == HTTPStatus.REQUEST_TIMEOUT
    assert error.value.public_code == "request_timeout"


def test_check_route_returns_length_required_for_missing_request_body_length(monkeypatch):
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "POST"
    handler.path = "/check"
    handler.headers = {}
    handler.authorized = lambda: True
    handler.respond = Mock()
    monkeypatch.setattr(deployment_agent, "check_update", Mock())

    handler.dispatch()

    handler.respond.assert_called_once_with(
        HTTPStatus.LENGTH_REQUIRED,
        {"error": "content_length_required"},
    )


def test_request_handler_does_not_return_internal_exception_text(monkeypatch):
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "POST"
    handler.path = "/check"
    handler.authorized = lambda: True
    handler.respond = Mock()
    monkeypatch.setattr(
        deployment_agent,
        "read_json_body",
        Mock(side_effect=RuntimeError("database-password-must-not-leak")),
    )

    handler.dispatch()

    handler.respond.assert_called_once_with(
        HTTPStatus.SERVICE_UNAVAILABLE,
        {"error": "service_unavailable"},
    )


def test_bounded_http_server_rejects_requests_after_capacity_is_reached():
    server = object.__new__(deployment_agent.BoundedThreadingHTTPServer)
    server.daemon_threads = True
    server._request_slots = threading.BoundedSemaphore(1)
    server.shutdown_request = Mock()
    started = threading.Event()
    release = threading.Event()

    def hold_request(_request, _client_address):
        started.set()
        release.wait(timeout=2)

    server.process_request_thread = hold_request
    first_request = Mock()
    second_request = Mock()
    try:
        server.process_request(first_request, ("local", 1))
        assert started.wait(timeout=1)

        server.process_request(second_request, ("local", 2))
        response = second_request.sendall.call_args.args[0]

        assert b"503 Service Unavailable" in response
        assert b'"server_busy"' in response
    finally:
        release.set()


def test_backup_archives_keep_both_outputs_when_time_and_prefix_match(monkeypatch, tmp_path):
    staging = tmp_path / "staging" / "run"
    staging.mkdir(parents=True)
    (staging / "manifest.json").write_text('{"run": true}', encoding="utf-8")
    monkeypatch.setattr(deployment_agent, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(deployment_agent, "database_dump_bytes", lambda: b"-- database dump")
    frozen_now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

    class FrozenDatetime:
        @classmethod
        def now(cls, _timezone):
            return frozen_now

    monkeypatch.setattr(deployment_agent, "datetime", FrozenDatetime)

    first = deployment_agent.create_backup_archive("staging/run", "daily-test")
    second = deployment_agent.create_backup_archive("staging/run", "daily-test")

    assert first != second
    assert (tmp_path / first).is_file()
    assert (tmp_path / second).is_file()


def test_backup_archive_uses_shared_lock_and_rejects_parallel_backup(monkeypatch, tmp_path):
    staging = tmp_path / "staging" / "run"
    staging.mkdir(parents=True)
    monkeypatch.setattr(deployment_agent, "BACKUP_DIR", tmp_path)
    assert deployment_agent.backup_lock.acquire(blocking=False)
    try:
        with pytest.raises(RuntimeError) as error:
            deployment_agent.create_backup_archive("staging/run", "daily-test")
    finally:
        deployment_agent.backup_lock.release()

    assert isinstance(error.value, deployment_agent.BackupInProgressError)


def test_backup_archive_removes_partial_file_after_archive_failure(monkeypatch, tmp_path):
    staging = tmp_path / "staging" / "run"
    staging.mkdir(parents=True)
    monkeypatch.setattr(deployment_agent, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(deployment_agent, "database_dump_bytes", lambda: b"-- database dump")

    def fail_after_writing_partial_file(*args, **kwargs):
        if args and isinstance(args[0], (str, bytes, os.PathLike)):
            partial_path = args[0]
            with open(partial_path, "wb") as partial:
                partial.write(b"partial")
        else:
            kwargs["fileobj"].write(b"partial")
        raise RuntimeError("archive failure")

    monkeypatch.setattr(deployment_agent.tarfile, "open", fail_after_writing_partial_file)

    with pytest.raises(RuntimeError, match="archive failure"):
        deployment_agent.create_backup_archive("staging/run", "daily-test")

    assert list(tmp_path.glob("daily-test-*.tar.gz")) == []


def test_database_backup_uses_the_same_shared_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_agent, "BACKUP_DIR", tmp_path)
    database_dump = Mock(return_value=b"-- database dump")
    monkeypatch.setattr(deployment_agent, "database_dump_bytes", database_dump)
    assert deployment_agent.backup_lock.acquire(blocking=False)
    try:
        with pytest.raises(deployment_agent.BackupInProgressError):
            deployment_agent.create_backup()
    finally:
        deployment_agent.backup_lock.release()

    database_dump.assert_not_called()


def test_backup_route_returns_conflict_when_backup_is_running(monkeypatch):
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "POST"
    handler.path = "/backup"
    handler.authorized = lambda: True
    handler.respond = Mock()
    monkeypatch.setattr(deployment_agent, "read_json_body", lambda _handler: {})
    monkeypatch.setattr(
        deployment_agent,
        "create_backup_archive",
        Mock(side_effect=deployment_agent.BackupInProgressError()),
    )

    handler.dispatch()

    handler.respond.assert_called_once_with(
        HTTPStatus.CONFLICT,
        {"error": "backup_in_progress"},
    )


def test_check_update_persists_validated_immutable_digest(monkeypatch):
    states = []
    digest = "sha256:" + ("a" * 64)
    client = Mock()
    client.get_stack.return_value = {"Env": [{"name": "APP_IMAGE", "value": deployment_agent.TARGET_IMAGE}]}
    latest = {
        "id": digest,
        "image": deployment_agent.TARGET_IMAGE,
        "version": "1.2.4",
        "revision": "newrev",
        "build_date": "2026-08-12T12:00:00Z",
        "change": "fix: updater",
    }

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", lambda _image: latest)
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    result = deployment_agent.check_update({"current": {"revision": "oldrev"}})

    expected_image = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp@" + digest
    assert result["approved_image"] == expected_image
    assert result["approved_digest"] == digest
    assert states[-1]["approved_image"] == expected_image


def test_check_update_rejects_metadata_without_a_valid_digest(monkeypatch):
    client = Mock()
    client.get_stack.return_value = {"Env": [{"name": "APP_IMAGE", "value": deployment_agent.TARGET_IMAGE}]}
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "fetch_image_metadata",
        lambda _image: {"id": "not-a-digest", "image": deployment_agent.TARGET_IMAGE},
    )

    with pytest.raises(RuntimeError, match="Digest"):
        deployment_agent.check_update({"current": {"revision": "oldrev"}})


def test_perform_update_uses_checked_digest_when_the_tag_changes(monkeypatch):
    digest = "sha256:" + ("b" * 64)
    old_digest = "sha256:" + ("c" * 64)
    approved_image = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp@" + digest
    old_image = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp@" + old_digest
    state = {
        "latest": {"id": digest, "image": deployment_agent.TARGET_IMAGE},
        "approved_image": approved_image,
        "approved_digest": digest,
        "changelog": [],
    }
    client = Mock()
    client.docker_request.side_effect = [
        [{"ImageID": "sha256:old-config"}],
        {"RepoDigests": [old_image]},
        [{"ImageID": "sha256:new-config"}],
        {"RepoDigests": [approved_image]},
    ]
    states = []
    fetch = Mock(side_effect=AssertionError("the moving tag must not be refetched during install"))

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "load_state", lambda: state)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", fetch)
    monkeypatch.setattr(deployment_agent, "create_backup", lambda: "backup.sql.gz")
    monkeypatch.setattr(deployment_agent, "wait_until_healthy", Mock())
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    deployment_agent.update_lock.acquire()
    try:
        deployment_agent.perform_update()
    finally:
        if deployment_agent.update_lock.locked():
            deployment_agent.update_lock.release()

    client.update_stack_image.assert_called_once_with(approved_image)
    fetch.assert_not_called()
    assert states[-1]["phase"] == "complete"
    assert states[-1]["running"]["image"] == approved_image


def test_perform_update_rolls_back_when_running_digest_does_not_match(monkeypatch):
    approved_digest = "sha256:" + ("d" * 64)
    old_digest = "sha256:" + ("e" * 64)
    wrong_digest = "sha256:" + ("f" * 64)
    repository = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp"
    approved_image = f"{repository}@{approved_digest}"
    old_image = f"{repository}@{old_digest}"
    wrong_image = f"{repository}@{wrong_digest}"
    state = {
        "latest": {"id": approved_digest, "image": deployment_agent.TARGET_IMAGE},
        "approved_image": approved_image,
        "approved_digest": approved_digest,
        "changelog": [],
    }
    client = Mock()
    client.docker_request.side_effect = [
        [{"ImageID": "sha256:old-config"}],
        {"RepoDigests": [old_image]},
        [{"ImageID": "sha256:wrong-config"}],
        {"RepoDigests": [wrong_image]},
    ]
    client.update_stack_image.side_effect = [None, None]
    states = []

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "load_state", lambda: state)
    monkeypatch.setattr(deployment_agent, "create_backup", lambda: "backup.sql.gz")
    monkeypatch.setattr(deployment_agent, "wait_until_healthy", Mock())
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    deployment_agent.update_lock.acquire()
    try:
        deployment_agent.perform_update()
    finally:
        if deployment_agent.update_lock.locked():
            deployment_agent.update_lock.release()

    assert client.update_stack_image.mock_calls == [call(approved_image), call(old_image)]
    assert states[-1]["phase"] == "failed"
    assert "freigegebene Image-Digest" in states[-1]["error"]
