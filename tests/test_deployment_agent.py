import hashlib
import io
import json
import os
import socket
import threading
import time
import urllib.error
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

os.environ.setdefault("UPDATE_AGENT_TOKEN", "test-agent-token")

import deployment_agent  # noqa: E402

TEST_TARGET_IMAGE = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp:latest"
TEST_CANDIDATE_ID = "checked-candidate-token"
TEST_CANDIDATE_CONTRACT = deployment_agent.CANDIDATE_CONTRACT_VERSION
VALID_STACK_FILE = """services:
  app:
    image: ${APP_IMAGE}
  updater:
    image: ${UPDATER_IMAGE}
    environment:
      UPDATE_AGENT_TOKEN: ${UPDATE_AGENT_TOKEN}
"""


def image_digest(character: str = "a") -> str:
    """Return a syntactically valid digest for updater unit tests."""
    return f"sha256:{character * 64}"


def target_digest_reference(digest: str) -> str:
    """Return the configured target repository bound to a digest."""
    registry, repository, _reference = deployment_agent.parse_image_reference(TEST_TARGET_IMAGE)
    return f"{registry}/{repository}@{digest}"


def active_stack(app_image: str) -> dict:
    """Return a Portainer stack using the updater-safe Compose contract."""
    return {
        "Env": [{"name": "APP_IMAGE", "value": app_image}],
        "StackFileContent": VALID_STACK_FILE,
    }


@pytest.fixture(autouse=True)
def default_runtime_digest(monkeypatch, request):
    """Keep unrelated check tests on a deterministic running-image boundary."""
    if not request.node.name.startswith(("test_immutable_running_image", "test_perform_update")) and (
        request.node.name != "test_update_intent_is_persisted_before_target_stack_put"
    ):
        monkeypatch.setattr(
            deployment_agent,
            "immutable_running_image",
            lambda _client, _target_image: target_digest_reference(image_digest("c")),
        )


def checked_candidate_state(
    *,
    digest: str | None = None,
    phase: str = "checked",
    update_available: bool = True,
    candidate_contract: int | None = TEST_CANDIDATE_CONTRACT,
    candidate_base_digest: str | None = None,
) -> dict:
    """Return a complete installable candidate state for state-machine tests."""
    approved_digest = digest or image_digest("a")
    state = {
        "phase": phase,
        "update_available": update_available,
        "candidate_id": TEST_CANDIDATE_ID,
        "candidate_digest": approved_digest,
        "candidate_base_digest": candidate_base_digest or image_digest("c"),
        "approved_digest": approved_digest,
        "approved_image": target_digest_reference(approved_digest),
        "latest": {"id": approved_digest, "version": "43", "revision": "new-revision"},
        "changelog": [],
    }
    if candidate_contract is not None:
        state["candidate_contract"] = candidate_contract
    return state


def interrupted_update_state(
    *,
    phase: str = "installing",
    target_digest: str | None = None,
    rollback_digest: str | None = None,
) -> dict:
    """Return a complete persisted recovery record for restart tests."""
    target = target_digest or image_digest("a")
    rollback = rollback_digest or image_digest("b")
    return {
        "phase": phase,
        "message": "Update interrupted",
        "recovery_contract": 1,
        "operation_id": "recovery-operation-token",
        "candidate_identity": "c" * 64,
        "operation_started_at": "2026-08-22T12:00:00+00:00",
        "target_put_started_at": "2026-08-22T12:01:00+00:00",
        "target_image": target_digest_reference(target),
        "target_digest": target,
        "rollback_image": target_digest_reference(rollback),
        "latest": {"id": target, "version": "43", "revision": "new-revision"},
        "changelog": [],
        "candidate_id": "",
        "candidate_digest": "",
        "update_available": False,
    }


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        (
            "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp:" + ("1" * 40),
            "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp:latest",
        ),
        (
            "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp:stable",
            "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp:latest",
        ),
        (
            "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp@" + image_digest("a"),
            "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp:latest",
        ),
        (
            "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp:latest",
            "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp:latest",
        ),
        (
            "registry.example:5443/team/platform/fliegerlager:release-2026",
            "registry.example:5443/team/platform/fliegerlager:latest",
        ),
    ],
)
def test_latest_image_reference_preserves_registry_and_repository(image, expected):
    assert deployment_agent.latest_image_reference(image) == expected


@pytest.mark.parametrize(
    ("image", "message"),
    [
        ("fliegerlager:latest", "Registry und Repository"),
        ("ghcr.io/lsf/app@sha256:not-a-digest", "validen OCI-Digest"),
        ("ghcr.io/lsf/app@" + image_digest("a") + "@other", "mehrdeutig"),
        ("ghcr.io/lsf//app:stable", "Repository"),
        ("ghcr.io/lsf/app:stable:other", "mehrdeutig"),
        (" ghcr.io/lsf/app:stable", "Leerzeichen"),
    ],
)
def test_latest_image_reference_rejects_invalid_or_ambiguous_references(image, message):
    with pytest.raises(RuntimeError, match=message):
        deployment_agent.latest_image_reference(image)


@pytest.mark.parametrize(
    ("target_image", "discovery_image"),
    [
        (
            "ghcr.io/lsf/app:" + ("1" * 40),
            "ghcr.io/lsf/app:latest",
        ),
        ("ghcr.io/lsf/app:stable", "ghcr.io/lsf/app:latest"),
        ("ghcr.io/lsf/app@" + image_digest("a"), "ghcr.io/lsf/app:latest"),
        ("ghcr.io/lsf/app:latest", "ghcr.io/lsf/app:latest"),
        (
            "registry.example:5443/team/platform/app:stable",
            "registry.example:5443/team/platform/app:latest",
        ),
    ],
)
def test_check_update_fetches_latest_channel_for_every_supported_target(monkeypatch, target_image, discovery_image):
    digest = image_digest("b")
    client = Mock()
    client.get_stack.return_value = active_stack(target_image)
    fetch = Mock(
        return_value={
            "id": digest,
            "image": discovery_image,
            "version": "2",
            "revision": "new",
            "build_date": "2026-08-22T12:00:00Z",
            "change": "new release",
        }
    )

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", fetch)
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: values)

    result = deployment_agent.check_update({"current": {"revision": "old"}})

    fetch.assert_called_once_with(discovery_image)
    assert result["approved_image"] == discovery_image.removesuffix(":latest") + "@" + digest
    assert result["approved_digest"] == digest


@pytest.mark.parametrize(
    ("stack", "message"),
    [
        ({"Env": []}, "genau einen APP_IMAGE"),
        (
            {
                "Env": [
                    {"name": "APP_IMAGE", "value": "ghcr.io/lsf/app:old"},
                    {"name": "APP_IMAGE", "value": "ghcr.io/lsf/app:new"},
                ]
            },
            "genau einen APP_IMAGE",
        ),
        ({"Env": [{"name": "APP_IMAGE", "value": ""}]}, "Registry und Repository"),
        ({"Env": [{"name": "APP_IMAGE", "value": "app:latest"}]}, "Registry und Repository"),
    ],
)
def test_check_update_rejects_missing_duplicate_or_invalid_stack_app_image(monkeypatch, stack, message):
    client = Mock()
    client.get_stack.return_value = stack
    fetch = Mock()
    save_state = Mock()

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", fetch)
    monkeypatch.setattr(deployment_agent, "save_state", save_state)

    with pytest.raises(RuntimeError, match=message):
        deployment_agent.check_update({"current": {"revision": "old"}})

    fetch.assert_not_called()
    save_state.assert_not_called()
    client.update_stack_image.assert_not_called()


def test_check_update_portainer_failure_does_not_touch_registry_or_state(monkeypatch):
    client = Mock()
    client.get_stack.side_effect = deployment_agent.PortainerAPIError("Portainer API ist nicht erreichbar.")
    fetch = Mock()
    save_state = Mock()

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", fetch)
    monkeypatch.setattr(deployment_agent, "save_state", save_state)

    with pytest.raises(deployment_agent.PortainerAPIError, match="nicht erreichbar"):
        deployment_agent.check_update({"current": {"revision": "old"}})

    fetch.assert_not_called()
    save_state.assert_not_called()


@pytest.mark.parametrize(
    "stack_file",
    [
        """services:
  updater:
    environment:
      APP_IMAGE: ${APP_IMAGE}
""",
        """services:
  updater:
    environment:
      - UPDATE_AGENT_TOKEN=${UPDATE_AGENT_TOKEN}
      - APP_IMAGE=${APP_IMAGE}
""",
        """services:
  updater:
    environment: []
  updater:
    environment:
      APP_IMAGE: ${APP_IMAGE}
""",
    ],
    ids=["mapping-environment", "list-environment", "duplicate-updater-service"],
)
def test_updater_stack_contract_rejects_app_image_environment_variants(stack_file):
    with pytest.raises(deployment_agent.AgentRequestError) as error:
        deployment_agent.validate_updater_stack_contract(stack_file)

    assert error.value.status == HTTPStatus.CONFLICT
    assert error.value.public_code == "updater_stack_upgrade_required"


def test_updater_stack_contract_accepts_current_compose_shape():
    deployment_agent.validate_updater_stack_contract(VALID_STACK_FILE)


@pytest.mark.parametrize(
    "stack_file",
    [
        """x-updater-env: &updater-env
  APP_IMAGE: ${APP_IMAGE}
services:
  updater:
    environment:
      <<: *updater-env
""",
        """x-limits: &limits
  memory: 256M
services:
  updater:
    deploy:
      resources: *limits
""",
        """services:
  updater:
    <<: {environment: {APP_IMAGE: ${APP_IMAGE}}}
""",
        """services:
  updater: {environment: {APP_IMAGE: ${APP_IMAGE}}}
""",
        """services:
  updater:
    <<: [*base, *registry]
""",
        """services:
  updater:
    <<: *base
    <<: *registry
""",
        """x-env: &updater-env
  SAFE: value
services:
  updater:
    environment: *updater-env
""",
        """services:
  updater: *missing
""",
        """x-a: &a
  value: *b
x-b: &b
  value: *a
services:
  updater:
    <<: *a
""",
        """services:
  updater: &updater
    environment:
      SAFE: value
""",
    ],
    ids=[
        "top-level-anchor-merge",
        "nested-alias",
        "inline-merge-mapping",
        "inline-updater-mapping",
        "inline-merge-list",
        "multiple-merges",
        "environment-alias",
        "malformed-alias",
        "cyclic-alias",
        "updater-anchor",
    ],
)
def test_updater_stack_contract_rejects_indirect_yaml_configuration(stack_file):
    with pytest.raises(deployment_agent.AgentRequestError) as error:
        deployment_agent.validate_updater_stack_contract(stack_file)

    assert error.value.status == HTTPStatus.CONFLICT
    assert error.value.public_code == "updater_stack_indirect_configuration"


@pytest.mark.parametrize(
    "stack_file",
    [
        """x-harmless: &harmless
  environment:
    APP_IMAGE: ignored-outside-updater
services:
  app:
    <<: *harmless
  updater:
    environment:
      SAFE: value
""",
        """services:
  app:
    labels:
      note: &label harmless
  updater:
    labels:
      note: "quoted <<: *not-an-alias"
    environment:
      SAFE: value # <<: *comment-only
""",
        """services:
  updater:
    environment:
      - SAFE=value
      - OTHER=also-safe
""",
    ],
    ids=["anchor-outside-updater", "quoted-and-commented-control-text", "direct-list-environment"],
)
def test_updater_stack_contract_accepts_safe_direct_subset(stack_file):
    deployment_agent.validate_updater_stack_contract(stack_file)


@pytest.mark.parametrize(
    "stack_file",
    [
        """services:
  updater:
    env_file: updater.env
""",
        """services:
  updater:
    extends: common-updater
""",
        """services:
  updater:
    environment: {}
  updater:
    environment: {}
""",
    ],
    ids=["env-file", "extends", "duplicate-updater"],
)
def test_updater_stack_contract_keeps_existing_indirect_guards(stack_file):
    with pytest.raises(deployment_agent.AgentRequestError) as error:
        deployment_agent.validate_updater_stack_contract(stack_file)

    assert error.value.public_code == "updater_stack_upgrade_required"


def test_check_rejects_updater_alias_without_candidate_state_or_redeploy(monkeypatch):
    stack = active_stack(TEST_TARGET_IMAGE)
    stack["StackFileContent"] = """x-env: &env
  APP_IMAGE: ${APP_IMAGE}
services:
  updater:
    environment:
      <<: *env
"""
    client = Mock()
    client.get_stack.return_value = stack
    save_state = Mock()
    fetch = Mock()
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "save_state", save_state)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", fetch)

    with pytest.raises(deployment_agent.AgentRequestError) as error:
        deployment_agent.check_update({"current": {"version": "42", "revision": "old"}})

    assert error.value.public_code == "updater_stack_indirect_configuration"
    fetch.assert_not_called()
    save_state.assert_not_called()
    client.update_stack_image.assert_not_called()


def test_check_blocks_legacy_stack_before_registry_or_state_mutation(monkeypatch):
    legacy_stack = {
        "Env": [{"name": "APP_IMAGE", "value": TEST_TARGET_IMAGE}],
        "StackFileContent": """services:
  updater:
    environment:
      APP_IMAGE: ${APP_IMAGE}
""",
    }
    client = Mock()
    client.get_stack.return_value = legacy_stack
    fetch = Mock()
    save_state = Mock()
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", fetch)
    monkeypatch.setattr(deployment_agent, "save_state", save_state)

    with pytest.raises(deployment_agent.AgentRequestError) as error:
        deployment_agent.check_update({"current": {"version": "42", "revision": "old"}})

    assert error.value.public_code == "updater_stack_upgrade_required"
    fetch.assert_not_called()
    save_state.assert_not_called()
    client.update_stack_image.assert_not_called()


@pytest.mark.parametrize(
    ("stack_file", "expected_code"),
    [
        (
            "services:\n  updater:\n    environment:\n      - APP_IMAGE=${APP_IMAGE}\n",
            "updater_stack_upgrade_required",
        ),
        (
            "x-env: &env\n  SAFE: value\nservices:\n  updater:\n    environment:\n      <<: *env\n",
            "updater_stack_indirect_configuration",
        ),
    ],
    ids=["direct-app-image", "alias-merge"],
)
def test_install_blocks_stack_that_became_unsafe_after_check(monkeypatch, tmp_path, stack_file, expected_code):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    deployment_agent.save_state(**checked_candidate_state())
    before = deployment_agent.load_state()
    client = Mock()
    client.get_stack.return_value = {
        "Env": [{"name": "APP_IMAGE", "value": TEST_TARGET_IMAGE}],
        "StackFileContent": stack_file,
    }
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "POST"
    handler.path = "/install"
    handler.authorized = lambda: True
    handler.respond = Mock()
    monkeypatch.setattr(
        deployment_agent,
        "read_json_body",
        lambda _handler: {"candidate_id": TEST_CANDIDATE_ID},
    )
    thread = Mock()
    monkeypatch.setattr(deployment_agent.threading, "Thread", thread)

    handler.dispatch()

    handler.respond.assert_called_once_with(
        HTTPStatus.CONFLICT,
        {"error": expected_code},
    )
    assert deployment_agent.load_state() == before
    client.update_stack_image.assert_not_called()
    thread.assert_not_called()


def manifest_bytes(payload: dict) -> bytes:
    """Serialize a registry fixture exactly as the mocked registry returns it."""
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def content_digest(raw: bytes) -> str:
    """Return the OCI digest for the exact bytes served by the registry fixture."""
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def platform_descriptor(
    digest_character: str,
    *,
    os_name: str = "linux",
    architecture: str = "amd64",
    variant: str | None = None,
    media_type: str = "application/vnd.oci.image.manifest.v1+json",
) -> dict:
    """Return a valid platform-specific image-manifest descriptor fixture."""
    platform = {"os": os_name, "architecture": architecture}
    if variant is not None:
        platform["variant"] = variant
    return {
        "mediaType": media_type,
        "digest": image_digest(digest_character),
        "platform": platform,
    }


def test_choose_manifest_descriptor_selects_only_linux_amd64_from_mixed_index():
    expected = platform_descriptor("3")
    index = {
        "manifests": [
            platform_descriptor("1", architecture="arm64", variant="v8"),
            platform_descriptor("2", os_name="windows"),
            expected,
        ]
    }

    assert deployment_agent.choose_manifest_descriptor(index) == expected


@pytest.mark.parametrize(
    "descriptors",
    [
        [platform_descriptor("1", architecture="arm64", variant="v8")],
        [platform_descriptor("1", os_name="windows")],
        [platform_descriptor("1", os_name="unknown")],
        [platform_descriptor("1", architecture="unknown")],
    ],
    ids=["arm-only", "windows-amd64", "unknown-os", "unknown-architecture"],
)
def test_choose_manifest_descriptor_rejects_index_without_linux_amd64(descriptors):
    with pytest.raises(deployment_agent.RegistryMetadataError, match="linux/amd64"):
        deployment_agent.choose_manifest_descriptor({"manifests": descriptors})


@pytest.mark.parametrize(
    "platform",
    [
        None,
        {},
        {"architecture": "amd64"},
        {"os": "linux"},
        {"os": "linux", "architecture": 42},
        {"os": "linux", "architecture": "amd64", "variant": None},
        {"os": "linux", "architecture": "amd64", "variant": 1},
    ],
    ids=[
        "missing",
        "empty",
        "missing-os",
        "missing-architecture",
        "invalid-architecture",
        "null-variant",
        "invalid-variant",
    ],
)
def test_choose_manifest_descriptor_rejects_missing_or_invalid_platform(platform):
    descriptor = platform_descriptor("1")
    if platform is None:
        descriptor.pop("platform")
    else:
        descriptor["platform"] = platform

    with pytest.raises(deployment_agent.RegistryMetadataError, match="Platform"):
        deployment_agent.choose_manifest_descriptor({"manifests": [descriptor]})


@pytest.mark.parametrize("variant", [None, "v1"], ids=["implicit-baseline", "explicit-v1"])
def test_choose_manifest_descriptor_accepts_amd64_baseline_variant(variant):
    descriptor = platform_descriptor("1", variant=variant)

    assert deployment_agent.choose_manifest_descriptor({"manifests": [descriptor]}) == descriptor


@pytest.mark.parametrize("variant", ["v2", "future"], ids=["higher-cpu-level", "unknown"])
def test_choose_manifest_descriptor_rejects_unsupported_amd64_variant(variant):
    with pytest.raises(deployment_agent.RegistryMetadataError, match="amd64-Variante"):
        deployment_agent.choose_manifest_descriptor({"manifests": [platform_descriptor("1", variant=variant)]})


@pytest.mark.parametrize("same_digest", [False, True], ids=["conflicting", "identical"])
def test_choose_manifest_descriptor_rejects_ambiguous_linux_amd64_descriptors(same_digest):
    descriptors = [platform_descriptor("1"), platform_descriptor("1" if same_digest else "2")]

    with pytest.raises(deployment_agent.RegistryMetadataError, match="mehrere linux/amd64"):
        deployment_agent.choose_manifest_descriptor({"manifests": descriptors})


@pytest.mark.parametrize(
    ("descriptor", "message"),
    [
        (None, "Descriptor"),
        ({}, "Media-Type"),
        ({**platform_descriptor("1"), "mediaType": "application/vnd.oci.image.index.v1+json"}, "Media-Type"),
        ({**platform_descriptor("1"), "digest": "sha256:not-valid"}, "Digest"),
    ],
    ids=["not-a-mapping", "missing-fields", "unsupported-media-type", "invalid-digest"],
)
def test_choose_manifest_descriptor_rejects_malformed_descriptor(descriptor, message):
    with pytest.raises(deployment_agent.RegistryMetadataError, match=message):
        deployment_agent.choose_manifest_descriptor({"manifests": [descriptor]})


@pytest.mark.parametrize(
    "media_type",
    [
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ],
    ids=["oci-index-child", "docker-manifest-list-child"],
)
def test_choose_manifest_descriptor_accepts_supported_image_manifest_media_types(media_type):
    descriptor = platform_descriptor("1", media_type=media_type)

    assert deployment_agent.choose_manifest_descriptor({"manifests": [descriptor]}) == descriptor


def test_image_metadata_reads_oci_and_change_labels():
    image = {
        "id": "sha256:123",
        "image": TEST_TARGET_IMAGE,
        "labels": {
            "org.opencontainers.image.version": "1.2.3",
            "org.opencontainers.image.revision": "abc123",
            "org.opencontainers.image.created": "2026-06-09T12:00:00Z",
            "io.lsf-fliegerlager.change": "feat: deployment updates",
            "io.lsf-fliegerlager.changelog": (
                '[{"revision":"abc123","title":"Deployment updates","body":"Updater hardening"}]'
            ),
        },
    }

    assert deployment_agent.image_metadata(image) == {
        "id": "sha256:123",
        "image": TEST_TARGET_IMAGE,
        "version": "1.2.3",
        "revision": "abc123",
        "build_date": "2026-06-09T12:00:00Z",
        "change": "feat: deployment updates",
        "changelog": [{"revision": "abc123", "title": "Deployment updates", "body": "Updater hardening", "path": ""}],
    }


def test_image_metadata_ignores_invalid_changelog_labels():
    image = {
        "id": "sha256:123",
        "image": TEST_TARGET_IMAGE,
        "labels": {
            "org.opencontainers.image.version": "1.2.3",
            "org.opencontainers.image.revision": "abc123",
            "org.opencontainers.image.created": "2026-06-09T12:00:00Z",
            "io.lsf-fliegerlager.change": "feat: deployment updates",
            "io.lsf-fliegerlager.changelog": '{"not":"a-list"}',
        },
    }

    assert deployment_agent.image_metadata(image)["changelog"] == []


def test_fetch_image_metadata_keeps_index_digest_for_installation(monkeypatch):
    index = {
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "platform": {"os": "linux", "architecture": "amd64"},
            }
        ],
    }
    config_digest = image_digest("3")
    child = {
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {"digest": config_digest},
    }
    child_raw = manifest_bytes(child)
    child_digest = content_digest(child_raw)
    index["manifests"][0]["digest"] = child_digest
    index_raw = manifest_bytes(index)
    index_digest = content_digest(index_raw)
    responses = iter(
        [
            (index_raw, {}),
            (child_raw, {}),
            (manifest_bytes({"config": {"Labels": {}}}), {}),
        ]
    )
    monkeypatch.setattr(deployment_agent, "registry_request", lambda *_args, **_kwargs: next(responses))

    metadata = deployment_agent.fetch_image_metadata(TEST_TARGET_IMAGE)

    assert metadata["id"] == index_digest


def test_fetch_image_metadata_rejects_child_bytes_not_matching_index_digest(monkeypatch):
    config_digest = image_digest("3")
    child = {
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {"digest": config_digest},
    }
    child_raw = manifest_bytes(child)
    index_digest = image_digest("9")
    index = {
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {
                "digest": index_digest,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "platform": {"os": "linux", "architecture": "amd64"},
            }
        ],
    }
    responses = iter(
        [
            (manifest_bytes(index), {}),
            (child_raw, {"Docker-Content-Digest": content_digest(child_raw)}),
            (manifest_bytes({"config": {"Labels": {}}}), {}),
        ]
    )
    monkeypatch.setattr(deployment_agent, "registry_request", lambda *_args, **_kwargs: next(responses))

    with pytest.raises(deployment_agent.RegistryMetadataError):
        deployment_agent.fetch_image_metadata(TEST_TARGET_IMAGE)


def test_fetch_image_metadata_uses_digest_of_exact_manifest_bytes_without_header(monkeypatch):
    raw_manifest = (
        b'{"mediaType":"application/vnd.oci.image.manifest.v1+json", '
        b'"config":{"digest":"' + image_digest("1").encode() + b'"}}'
    )
    responses = iter(
        [
            (raw_manifest, {}),
            (manifest_bytes({"config": {"Labels": {}}}), {}),
        ]
    )
    monkeypatch.setattr(deployment_agent, "registry_request", lambda *_args, **_kwargs: next(responses))

    metadata = deployment_agent.fetch_image_metadata(TEST_TARGET_IMAGE)

    assert metadata["id"] == content_digest(raw_manifest)


def test_fetch_image_metadata_accepts_digest_image_when_bytes_match_reference(monkeypatch):
    raw_manifest = (
        b'{"mediaType":"application/vnd.oci.image.manifest.v1+json","config":{"digest":"'
        + image_digest("2").encode()
        + b'"}}'
    )
    image = target_digest_reference(content_digest(raw_manifest))
    responses = iter(
        [
            (raw_manifest, {}),
            (manifest_bytes({"config": {"Labels": {}}}), {}),
        ]
    )
    monkeypatch.setattr(deployment_agent, "registry_request", lambda *_args, **_kwargs: next(responses))

    assert deployment_agent.fetch_image_metadata(image)["id"] == content_digest(raw_manifest)


def test_fetch_image_metadata_rejects_digest_image_when_bytes_do_not_match_reference(monkeypatch):
    image = target_digest_reference(image_digest("9"))
    raw_manifest = manifest_bytes(
        {"mediaType": "application/vnd.oci.image.manifest.v1+json", "config": {"digest": image_digest("2")}}
    )
    monkeypatch.setattr(
        deployment_agent,
        "registry_request",
        lambda *_args, **_kwargs: (raw_manifest, {}),
    )

    with pytest.raises(deployment_agent.RegistryMetadataError):
        deployment_agent.fetch_image_metadata(image)


def test_fetch_image_metadata_accepts_case_insensitive_matching_digest_header(monkeypatch):
    manifest = {"mediaType": "application/vnd.oci.image.manifest.v1+json", "config": {"digest": image_digest("1")}}
    raw_manifest = manifest_bytes(manifest)
    responses = iter(
        [
            (raw_manifest, {"dOcKeR-cOnTeNt-DiGeSt": content_digest(raw_manifest)}),
            (manifest_bytes({"config": {"Labels": {}}}), {}),
        ]
    )
    monkeypatch.setattr(deployment_agent, "registry_request", lambda *_args, **_kwargs: next(responses))

    assert deployment_agent.fetch_image_metadata(TEST_TARGET_IMAGE)["id"] == content_digest(raw_manifest)


@pytest.mark.parametrize("header_value", ["sha256:not-a-digest", "sha512:" + "a" * 64])
def test_fetch_image_metadata_rejects_malformed_digest_header(monkeypatch, header_value):
    manifest = {"mediaType": "application/vnd.oci.image.manifest.v1+json", "config": {"digest": image_digest("1")}}
    raw_manifest = manifest_bytes(manifest)
    monkeypatch.setattr(
        deployment_agent,
        "registry_request",
        lambda *_args, **_kwargs: (raw_manifest, {"Docker-Content-Digest": header_value}),
    )

    with pytest.raises(deployment_agent.RegistryMetadataError):
        deployment_agent.fetch_image_metadata(TEST_TARGET_IMAGE)


def test_fetch_image_metadata_rejects_digest_header_mismatch(monkeypatch):
    manifest = {"mediaType": "application/vnd.oci.image.manifest.v1+json", "config": {"digest": image_digest("1")}}
    raw_manifest = manifest_bytes(manifest)
    monkeypatch.setattr(
        deployment_agent,
        "registry_request",
        lambda *_args, **_kwargs: (raw_manifest, {"Docker-Content-Digest": image_digest("9")}),
    )

    with pytest.raises(deployment_agent.RegistryMetadataError):
        deployment_agent.fetch_image_metadata(TEST_TARGET_IMAGE)


def test_perform_update_does_not_rollback_when_backup_lock_is_busy(monkeypatch):
    digest = image_digest("4")
    approved_image = target_digest_reference(digest)
    client = Mock()
    client.docker_request.side_effect = [
        [{"ImageID": "sha256:old-config"}],
        {"RepoDigests": [target_digest_reference(image_digest("5"))]},
    ]
    states = []
    checked_state = {
        "candidate_id": TEST_CANDIDATE_ID,
        "latest": {"id": digest, "image": TEST_TARGET_IMAGE},
        "approved_image": approved_image,
        "approved_digest": digest,
        "changelog": [],
    }
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "create_backup", Mock(side_effect=deployment_agent.BackupInProgressError()))
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    deployment_agent.update_lock.acquire()
    try:
        deployment_agent.perform_update(checked_state)
    finally:
        if deployment_agent.update_lock.locked():
            deployment_agent.update_lock.release()

    client.update_stack_image.assert_not_called()
    assert states[-1]["phase"] == "failed"
    assert states[-1]["candidate_id"] == ""
    assert states[-1]["update_available"] is False


def test_incomplete_headers_timeout_and_release_server_slot(monkeypatch):
    monkeypatch.setattr(deployment_agent, "AGENT_READ_TIMEOUT_SECONDS", 0.05)
    server = deployment_agent.BoundedThreadingHTTPServer(
        ("127.0.0.1", 0), deployment_agent.RequestHandler, max_concurrent_requests=1
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        partial = socket.create_connection(server.server_address)
        partial.sendall(b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n")
        time.sleep(0.15)

        with socket.create_connection(server.server_address, timeout=1) as healthy:
            healthy.sendall(
                b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n"
                + f"Authorization: Bearer {deployment_agent.TOKEN}\r\n".encode()
                + b"Connection: close\r\n\r\n"
            )
            response = healthy.recv(4096)

        assert b"200 OK" in response
    finally:
        partial.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1)


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
        "StackFileContent": VALID_STACK_FILE,
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
            "stackFileContent": VALID_STACK_FILE,
        },
        timeout=180,
    )


def test_update_intent_is_persisted_before_target_stack_put(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    deployment_agent.save_state(**checked_candidate_state())
    operation = deployment_agent.consume_install_candidate(TEST_CANDIDATE_ID)
    client = Mock()
    rollback_image = target_digest_reference(image_digest("b"))
    client.docker_request.side_effect = [
        [{"ImageID": "sha256:old-config"}],
        {"RepoDigests": [rollback_image]},
    ]
    client.update_stack_image.side_effect = SystemExit("simulated crash after persisted intent")
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "create_backup", lambda: "backup.sql.gz")

    deployment_agent.update_lock.acquire()
    with pytest.raises(SystemExit, match="simulated crash"):
        deployment_agent.perform_update(operation)

    state = deployment_agent.load_state()
    assert state["phase"] == "installing"
    assert state["recovery_contract"] == 1
    assert state["target_image"] == target_digest_reference(image_digest("a"))
    assert state["target_digest"] == image_digest("a")
    assert state["rollback_image"] == rollback_image
    assert state["operation_id"]
    assert state["candidate_identity"] == hashlib.sha256(TEST_CANDIDATE_ID.encode()).hexdigest()
    assert state["operation_started_at"]
    assert state["target_put_started_at"]
    assert state["candidate_id"] == ""
    assert state["update_available"] is False


def test_startup_reconciliation_completes_when_target_is_running_and_healthy(monkeypatch, tmp_path):
    state_file = tmp_path / "status.json"
    monkeypatch.setattr(deployment_agent, "STATE_FILE", state_file)
    interrupted = interrupted_update_state()
    deployment_agent.save_state(**interrupted)
    client = Mock()
    running = Mock(return_value=interrupted["target_image"])
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "immutable_running_image", running)
    monkeypatch.setattr(deployment_agent, "application_is_healthy", lambda: True)

    result = deployment_agent.reconcile_interrupted_update()

    assert result["phase"] == "complete"
    assert result["installed"]["id"] == interrupted["target_digest"]
    assert result["candidate_id"] == ""
    assert result["update_available"] is False
    client.update_stack_image.assert_not_called()

    second_result = deployment_agent.reconcile_interrupted_update()
    assert second_result["phase"] == "complete"
    assert running.call_count == 1


@pytest.mark.parametrize("phase", ["installing", "rollback"])
def test_startup_reconciliation_records_already_running_rollback(monkeypatch, tmp_path, phase):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    interrupted = interrupted_update_state(phase=phase)
    if phase == "rollback":
        interrupted["rollback_put_started_at"] = "2026-08-22T12:02:00+00:00"
    deployment_agent.save_state(**interrupted)
    client = Mock()
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "immutable_running_image",
        lambda _client, _target: interrupted["rollback_image"],
    )
    monkeypatch.setattr(deployment_agent, "application_is_healthy", lambda: True)

    result = deployment_agent.reconcile_interrupted_update()

    assert result["phase"] == "failed"
    assert result["recovery_outcome"] == "rolled_back"
    assert result["rollback_error"] == ""
    client.update_stack_image.assert_not_called()


def test_startup_reconciliation_rolls_back_other_or_unhealthy_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    interrupted = interrupted_update_state()
    deployment_agent.save_state(**interrupted)
    client = Mock()
    running = Mock(
        side_effect=[
            target_digest_reference(image_digest("c")),
            interrupted["rollback_image"],
        ]
    )
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "immutable_running_image", running)
    monkeypatch.setattr(deployment_agent, "application_is_healthy", lambda: False)
    monkeypatch.setattr(deployment_agent, "wait_until_healthy", Mock())

    def assert_persisted_before_put(image):
        persisted = deployment_agent.load_state()
        assert persisted["phase"] == "rollback"
        assert persisted["rollback_put_started_at"]
        assert persisted["rollback_image"] == interrupted["rollback_image"]
        assert persisted["operation_id"] == interrupted["operation_id"]
        assert image == interrupted["rollback_image"]

    client.update_stack_image.side_effect = assert_persisted_before_put

    result = deployment_agent.reconcile_interrupted_update()

    client.update_stack_image.assert_called_once_with(interrupted["rollback_image"])
    assert result["phase"] == "failed"
    assert result["recovery_outcome"] == "rolled_back"
    assert result["rollback_put_started_at"]


def test_startup_reconciliation_attempts_persisted_rollback_when_runtime_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    interrupted = interrupted_update_state()
    deployment_agent.save_state(**interrupted)
    client = Mock()
    running = Mock(
        side_effect=[
            RuntimeError("no running app container"),
            interrupted["rollback_image"],
        ]
    )
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "immutable_running_image", running)
    monkeypatch.setattr(deployment_agent, "application_is_healthy", lambda: False)
    monkeypatch.setattr(deployment_agent, "wait_until_healthy", Mock())

    result = deployment_agent.reconcile_interrupted_update()

    client.update_stack_image.assert_called_once_with(interrupted["rollback_image"])
    assert result["phase"] == "failed"
    assert result["recovery_outcome"] == "rolled_back"


@pytest.mark.parametrize("phase", ["installing", "rollback", "recovery_required"])
def test_unresolved_recovery_blocks_new_mutations(monkeypatch, tmp_path, phase):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    deployment_agent.save_state(phase=phase)
    client = Mock()
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)

    with pytest.raises(deployment_agent.AgentRequestError) as error:
        deployment_agent.check_update({"current": {}})

    assert error.value.public_code == "update_recovery_required"
    client.get_stack.assert_not_called()


def test_agent_reconciles_before_server_accepts_requests(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    monkeypatch.setattr(deployment_agent, "BACKUP_DIR", tmp_path / "backups")
    client = Mock()
    client.get_stack.side_effect = lambda: events.append("portainer") or {}
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "reconcile_interrupted_update",
        lambda: events.append("reconcile") or {"phase": "idle"},
    )
    server = Mock()

    def server_factory(*_args, **_kwargs):
        events.append("server")
        return server

    monkeypatch.setattr(deployment_agent, "BoundedThreadingHTTPServer", server_factory)

    deployment_agent.run_agent()

    assert events == ["portainer", "reconcile", "server"]
    server.serve_forever.assert_called_once_with()


def test_first_upgrade_runbook_requires_compose_restart_and_health_before_update():
    documentation = Path("deploy/README.md").read_text(encoding="utf-8")

    assert "First Upgrade" in documentation
    first_upgrade = documentation.split("First Upgrade", 1)[1]
    assert "docker-compose.example.yml" in first_upgrade
    assert "updater" in first_upgrade
    assert "health" in first_upgrade.casefold()
    assert first_upgrade.index("docker-compose.example.yml") < first_upgrade.index("/check")
    assert first_upgrade.index("health") < first_upgrade.index("/check")


def test_startup_reconciliation_marks_invalid_or_unrecoverable_state_as_required(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    invalid = interrupted_update_state()
    invalid.pop("rollback_image")
    deployment_agent.save_state(**invalid)
    client = Mock()
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)

    result = deployment_agent.reconcile_interrupted_update()

    assert result["phase"] == "recovery_required"
    assert result["candidate_id"] == ""
    assert result["update_available"] is False
    assert "Recovery" in result["error"]
    client.update_stack_image.assert_not_called()


def test_startup_reconciliation_persists_failed_rollback_diagnostic(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    interrupted = interrupted_update_state()
    deployment_agent.save_state(**interrupted)
    client = Mock()
    client.update_stack_image.side_effect = deployment_agent.PortainerAPIError("Portainer API: unavailable")
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "immutable_running_image",
        lambda _client, _target: target_digest_reference(image_digest("c")),
    )
    monkeypatch.setattr(deployment_agent, "application_is_healthy", lambda: False)

    result = deployment_agent.reconcile_interrupted_update()

    assert result["phase"] == "recovery_required"
    assert result["recovery_outcome"] == "rollback_failed"
    assert "Portainer API: unavailable" in result["rollback_error"]
    assert result["candidate_id"] == ""
    assert result["update_available"] is False


def test_perform_update_rolls_back_when_portainer_update_call_fails(monkeypatch):
    states = []
    digest = image_digest("a")
    approved_image = target_digest_reference(digest)
    client = Mock()
    client.docker_request.side_effect = [
        [{"ImageID": "sha256:old-config"}],
        {"RepoDigests": [target_digest_reference(image_digest("e"))]},
        [{"ImageID": "sha256:restored-config"}],
        {"RepoDigests": [target_digest_reference(image_digest("e"))]},
    ]
    client.update_stack_image.side_effect = [
        deployment_agent.PortainerAPIError("Portainer API: update failed"),
        None,
    ]

    checked_state = {
        "candidate_id": TEST_CANDIDATE_ID,
        "latest": {"id": digest, "image": TEST_TARGET_IMAGE},
        "approved_image": approved_image,
        "approved_digest": digest,
        "changelog": [],
    }
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "create_backup", lambda: "backup.sql.gz")
    monkeypatch.setattr(deployment_agent, "wait_until_healthy", Mock())
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    deployment_agent.update_lock.acquire()
    deployment_agent.perform_update(checked_state)

    assert client.update_stack_image.mock_calls == [
        call(approved_image),
        call(target_digest_reference(image_digest("e"))),
    ]
    failed_state = states[-1]
    assert failed_state["phase"] == "failed"
    assert failed_state["candidate_id"] == ""
    assert failed_state["update_available"] is False
    assert "Portainer API: update failed" in failed_state["error"]
    assert f"Rollback-Image fuer APP_IMAGE: {target_digest_reference(image_digest('e'))}" in failed_state["recovery"]
    assert "backup.sql.gz" in failed_state["recovery"]


def test_perform_update_requires_recovery_when_rollback_put_fails(monkeypatch):
    states = []
    digest = image_digest("a")
    approved_image = target_digest_reference(digest)
    old_image = target_digest_reference(image_digest("b"))
    client = Mock()
    client.docker_request.side_effect = [
        [{"ImageID": "sha256:old-config"}],
        {"RepoDigests": [old_image]},
    ]
    client.update_stack_image.side_effect = [
        deployment_agent.PortainerAPIError("target PUT uncertain"),
        deployment_agent.PortainerAPIError("rollback PUT failed"),
    ]
    checked_state = {
        "candidate_id": TEST_CANDIDATE_ID,
        "latest": {"id": digest, "image": TEST_TARGET_IMAGE},
        "approved_image": approved_image,
        "approved_digest": digest,
        "changelog": [],
    }
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "create_backup", lambda: "backup.sql.gz")
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    deployment_agent.update_lock.acquire()
    deployment_agent.perform_update(checked_state)

    assert states[-1]["phase"] == "recovery_required"
    assert states[-1]["recovery_outcome"] == "rollback_failed"
    assert "rollback PUT failed" in states[-1]["rollback_error"]


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


@pytest.mark.parametrize("invalid_category", ["safe", None, ("safe", ".sql.gz")])
def test_open_exclusive_backup_accepts_only_internal_categories(monkeypatch, tmp_path, invalid_category):
    monkeypatch.setattr(deployment_agent, "BACKUP_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="Backup-Kategorie"):
        deployment_agent.open_exclusive_backup(invalid_category)

    assert list(tmp_path.iterdir()) == []


def test_open_exclusive_backup_creates_only_a_direct_backup_child(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_agent, "BACKUP_DIR", tmp_path)

    backup_path, raw_backup = deployment_agent.open_exclusive_backup(
        deployment_agent.BackupArtifactCategory.BEFORE_UPDATE
    )
    raw_backup.close()

    assert backup_path.parent == tmp_path
    assert backup_path.resolve().parent == tmp_path.resolve()
    assert backup_path.name.startswith("fliegerlager-before-update-")
    assert backup_path.name.endswith(".sql.gz")


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


def test_archive_prefix_is_validated_but_never_used_in_backup_filename(monkeypatch, tmp_path):
    staging = tmp_path / "staging" / "run"
    staging.mkdir(parents=True)
    monkeypatch.setattr(deployment_agent, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(deployment_agent, "database_dump_bytes", lambda: b"-- database dump")

    first = deployment_agent.create_backup_archive("staging/run", "operator-secret")
    second = deployment_agent.create_backup_archive("staging/run", "another-prefix")

    assert first.startswith("backup-archive-")
    assert second.startswith("backup-archive-")
    assert first.endswith(".tar.gz")
    assert second.endswith(".tar.gz")
    assert "operator-secret" not in first
    assert "another-prefix" not in second


def test_safe_archive_prefix_rejects_path_values():
    for value in ("../outside", "/absolute", "nested/name", r"nested\name", ""):
        with pytest.raises(RuntimeError, match="Backup-Archivname ist ungültig"):
            deployment_agent.safe_archive_prefix(value)


def test_wait_until_healthy_polls_app_health_url(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status = 204
    monkeypatch.setattr(deployment_agent, "APP_HEALTH_URL", "http://app:8000/healthz/")

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        deployment_agent.wait_until_healthy()

    assert urlopen.call_args.args[0] == "http://app:8000/healthz/"


@pytest.mark.parametrize(
    (
        "current_version",
        "latest_version",
        "current_revision",
        "latest_revision",
        "current_digest",
        "latest_digest",
        "expected",
    ),
    [
        ("42", "41", "old", "new", image_digest("a"), image_digest("b"), False),
        ("42", "43", "old", "new", image_digest("a"), image_digest("b"), True),
        ("42", "42", "old", "new", image_digest("a"), image_digest("a"), True),
        ("42", "42", "same", "same", image_digest("a"), image_digest("b"), True),
        ("42", "42", "same", "same", image_digest("a"), image_digest("a"), False),
    ],
)
def test_has_update_enforces_numeric_release_order_and_equal_version_identity(
    current_version,
    latest_version,
    current_revision,
    latest_revision,
    current_digest,
    latest_digest,
    expected,
):
    latest = {"version": latest_version, "revision": latest_revision, "id": latest_digest}
    current = {"version": current_version, "revision": current_revision}

    assert deployment_agent.has_update(latest, current, target_digest_reference(current_digest)) is expected


@pytest.mark.parametrize(
    ("current_version", "latest_version"),
    [
        ("", "43"),
        ("42", ""),
        ("development", "43"),
        ("42", "latest"),
        ("1.2.3", "1.2.4"),
        (" 42", "43"),
    ],
)
def test_has_update_fails_closed_for_missing_or_non_release_versions(current_version, latest_version):
    latest = {"version": latest_version, "revision": "new", "id": image_digest("b")}
    current = {"version": current_version, "revision": "old"}

    assert deployment_agent.has_update(latest, current, target_digest_reference(image_digest("a"))) is False


def test_downgrade_check_persists_no_installable_candidate(monkeypatch):
    states = []
    client = Mock()
    client.get_stack.return_value = active_stack(target_digest_reference(image_digest("a")))
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "fetch_image_metadata",
        lambda _image: {
            "id": image_digest("b"),
            "image": TEST_TARGET_IMAGE,
            "version": "41",
            "revision": "older-revision",
        },
    )
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    result = deployment_agent.check_update({"current": {"version": "42", "revision": "current-revision"}})

    assert result["update_available"] is False
    assert result["candidate_id"] == ""
    assert result["candidate_digest"] == ""
    assert states[-1]["update_available"] is False


def test_check_update_detects_update_from_oci_labels(monkeypatch):
    states = []
    client = Mock()
    client.get_stack.return_value = active_stack("ghcr.io/example/app:latest")
    latest = {
        "id": image_digest("a"),
        "image": "ghcr.io/example/app:latest",
        "version": "43",
        "revision": "newrev",
        "build_date": "2026-06-10T12:00:00Z",
        "change": "fix: updater",
        "changelog": [
            {"version": "42", "revision": "oldrev", "title": "Old", "body": "Already installed"},
            {"version": "43", "revision": "newrev", "title": "New", "body": "Install me"},
        ],
    }

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", lambda _image: latest)
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    result = deployment_agent.check_update(
        {"current": {"version": "42", "revision": "oldrev", "build_date": "2026-06-09T12:00:00Z"}}
    )

    assert result["latest"] == latest
    assert result["running"]["revision"] == "oldrev"
    assert result["update_available"] is True
    assert result["changelog"] == [
        {"version": "43", "revision": "newrev", "title": "New", "body": "Install me", "path": ""}
    ]


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


def test_check_update_detects_changed_digest_with_same_version_and_revision(monkeypatch):
    client = Mock()
    client.get_stack.return_value = active_stack("ghcr.io/example/app@" + image_digest("b"))
    latest = {
        "id": image_digest("a"),
        "image": "ghcr.io/example/app:latest",
        "version": "42",
        "revision": "same",
        "build_date": "2026-06-10T12:00:00Z",
        "change": "fix: updater",
    }

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", lambda _image: latest)
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: values)

    result = deployment_agent.check_update(
        {"current": {"version": "42", "revision": "same", "build_date": "2026-06-09T12:00:00Z"}}
    )

    assert result["update_available"] is True


def test_check_update_persists_no_update_status(monkeypatch):
    states = []
    client = Mock()
    client.get_stack.return_value = active_stack("ghcr.io/example/app@" + image_digest("a"))
    latest = {
        "id": image_digest("a"),
        "image": "ghcr.io/example/app:latest",
        "version": "42",
        "revision": "same",
        "build_date": "2026-06-10T12:00:00Z",
        "change": "fix: updater",
    }

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", lambda _image: latest)
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    result = deployment_agent.check_update(
        {"current": {"version": "42", "revision": "same", "build_date": "2026-06-10T12:00:00Z"}}
    )

    assert result["update_available"] is False
    assert states[-1]["update_available"] is False
    assert states[-1]["candidate_id"] == ""
    assert states[-1]["candidate_digest"] == ""
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
                target_digest_reference(image_digest("e")),
            ]
        },
    ]

    result = deployment_agent.immutable_running_image(client, TEST_TARGET_IMAGE)

    assert result == target_digest_reference(image_digest("e"))
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
    old_image = target_digest_reference(image_digest("e"))
    client = Mock()
    client.docker_request.side_effect = [
        [{"ImageID": "sha256:old-config"}],
        {"RepoDigests": [old_image]},
        [{"ImageID": "sha256:new-config"}],
        {"RepoDigests": [approved_image]},
    ]
    latest = {"id": digest, "image": TEST_TARGET_IMAGE}

    checked_state = {
        "candidate_id": TEST_CANDIDATE_ID,
        "latest": latest,
        "approved_image": approved_image,
        "approved_digest": digest,
        "changelog": [],
    }
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "create_backup", lambda: "backup.sql.gz")
    monkeypatch.setattr(deployment_agent, "wait_until_healthy", Mock())
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    deployment_agent.update_lock.acquire()
    deployment_agent.perform_update(checked_state)

    complete_state = states[-1]
    assert complete_state["phase"] == "complete"
    assert complete_state["update_available"] is False
    assert complete_state["candidate_id"] == ""
    assert complete_state["candidate_digest"] == ""


def test_registry_token_request_uses_configured_ghcr_token(monkeypatch):
    token_response = Mock()
    token_response.__enter__ = Mock(return_value=token_response)
    token_response.__exit__ = Mock(return_value=False)
    token_response.read.return_value = b'{"token":"bearer-token"}'
    token_response.status = 200

    monkeypatch.setattr(deployment_agent, "GHCR_TOKEN", "private-token")
    auth_header = 'Bearer realm="https://ghcr.io/token",service="ghcr.io",scope="repository:owner/app:pull"'

    with patch.object(deployment_agent, "registry_urlopen", return_value=token_response) as urlopen:
        token = deployment_agent.fetch_registry_token(auth_header)

    request = urlopen.call_args.args[0]
    assert request.get_header("Authorization") == "Basic dW51c2VkOnByaXZhdGUtdG9rZW4="
    assert token == "bearer-token"


@pytest.mark.parametrize(
    "url",
    [
        "http://ghcr.io/v2/owner/app/manifests/latest",
        "https://localhost/v2/owner/app/manifests/latest",
        "https://127.0.0.1/v2/owner/app/manifests/latest",
        "https://[::1]/v2/owner/app/manifests/latest",
        "https://[fe80::1]/v2/owner/app/manifests/latest",
        "https://[fc00::1]/v2/owner/app/manifests/latest",
        "https://[ff02::1]/v2/owner/app/manifests/latest",
        "https://[2001:db8::1]/v2/owner/app/manifests/latest",
        "https://0.0.0.0/v2/owner/app/manifests/latest",
        "https://169.254.169.254/v2/owner/app/manifests/latest",
        "https://10.0.0.1/v2/owner/app/manifests/latest",
        "https://172.16.0.1/v2/owner/app/manifests/latest",
        "https://192.168.0.1/v2/owner/app/manifests/latest",
        "https://224.0.0.1/v2/owner/app/manifests/latest",
        "https://192.0.2.1/v2/owner/app/manifests/latest",
        "https://ghcr.io.evil.example/v2/owner/app/manifests/latest",
        "https://127.0.0.1.nip.io/v2/owner/app/manifests/latest",
        "https://user@ghcr.io/v2/owner/app/manifests/latest",
        "https://ghcr.io./v2/owner/app/manifests/latest",
    ],
)
def test_registry_request_rejects_untrusted_or_unsafe_hosts_before_network(monkeypatch, url):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b"{}"
    response.headers = {}
    monkeypatch.setattr(deployment_agent, "REGISTRY_ALLOWED_HOSTS", "ghcr.io", raising=False)

    with patch.object(deployment_agent, "registry_urlopen", return_value=response) as urlopen:
        with pytest.raises(deployment_agent.RegistryMetadataError, match="Registry"):
            deployment_agent.registry_request(url, accept="application/json")

    urlopen.assert_not_called()


@pytest.mark.parametrize(
    ("url", "expected_authorization"),
    [
        ("https://GHCR.IO/v2/owner/app/manifests/latest", "Basic dW51c2VkOnByaXZhdGUtdG9rZW4="),
        ("https://registry.example:5443/v2/owner/app/manifests/latest", None),
    ],
)
def test_registry_request_allows_exact_hosts_and_scopes_ghcr_credentials(
    monkeypatch,
    url,
    expected_authorization,
):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b"{}"
    response.headers = {}
    monkeypatch.setattr(deployment_agent, "REGISTRY_ALLOWED_HOSTS", "ghcr.io,registry.example:5443", raising=False)
    monkeypatch.setattr(deployment_agent, "GHCR_TOKEN", "private-token")

    with patch.object(deployment_agent, "registry_urlopen", return_value=response) as urlopen:
        deployment_agent.registry_request(url, accept="application/json")

    request = urlopen.call_args.args[0]
    assert request.get_header("Authorization") == expected_authorization


@pytest.mark.parametrize(
    "allowlist",
    [
        "",
        "*.example.org",
        "https://ghcr.io",
        "user@ghcr.io",
        "ghcr.io/path",
        "ghcr.io.",
        "ghcr.io:0",
        "ghcr.io:65536",
        "ghcr.io:not-a-port",
        "localhost",
        "127.0.0.1",
        "[::1]",
    ],
)
def test_registry_request_rejects_invalid_allowlist_configuration_before_network(monkeypatch, allowlist):
    monkeypatch.setattr(deployment_agent, "REGISTRY_ALLOWED_HOSTS", allowlist, raising=False)

    with patch.object(deployment_agent, "registry_urlopen") as urlopen:
        with pytest.raises(deployment_agent.AgentConfigError, match="REGISTRY_ALLOWED_HOSTS"):
            deployment_agent.registry_request(
                "https://ghcr.io/v2/owner/app/manifests/latest",
                accept="application/json",
            )

    urlopen.assert_not_called()


@pytest.mark.parametrize("authority", ["224.0.0.1", "239.255.255.250", "[ff02::1]", "[ff0e::1]"])
def test_registry_request_rejects_multicast_allowlist_before_network(monkeypatch, authority):
    monkeypatch.setattr(deployment_agent, "REGISTRY_ALLOWED_HOSTS", authority, raising=False)

    with patch.object(deployment_agent, "registry_urlopen") as urlopen:
        with pytest.raises(deployment_agent.AgentConfigError, match="REGISTRY_ALLOWED_HOSTS"):
            deployment_agent.registry_request(
                "https://ghcr.io/v2/owner/app/manifests/latest",
                accept="application/json",
            )

    urlopen.assert_not_called()


@pytest.mark.parametrize("authority", ["224.0.0.1", "239.255.255.250", "[ff02::1]", "[ff0e::1]"])
def test_image_discovery_rejects_multicast_registry_before_network(monkeypatch, authority):
    monkeypatch.setattr(deployment_agent, "REGISTRY_ALLOWED_HOSTS", authority, raising=False)

    with patch.object(deployment_agent, "registry_urlopen") as urlopen:
        with pytest.raises(deployment_agent.RegistryMetadataError, match="Registry-Host"):
            deployment_agent.fetch_image_metadata(f"{authority}/owner/app:latest")

    urlopen.assert_not_called()


@pytest.mark.parametrize(
    "authority",
    ["8.8.8.8:5443", "[2606:4700:4700::1111]:5443"],
    ids=["public-ipv4", "public-ipv6"],
)
def test_registry_request_keeps_explicitly_allowlisted_global_ip_literals(monkeypatch, authority):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b"{}"
    response.headers = {}
    monkeypatch.setattr(deployment_agent, "REGISTRY_ALLOWED_HOSTS", authority, raising=False)

    with patch.object(deployment_agent, "registry_urlopen", return_value=response) as urlopen:
        deployment_agent.registry_request(
            f"https://{authority}/v2/owner/app/manifests/latest",
            accept="application/json",
        )

    urlopen.assert_called_once()


def test_registry_token_rejects_cross_host_realm_without_credentials_or_network(monkeypatch):
    monkeypatch.setattr(deployment_agent, "REGISTRY_ALLOWED_HOSTS", "ghcr.io", raising=False)
    monkeypatch.setattr(deployment_agent, "GHCR_TOKEN", "private-token")
    auth_header = 'Bearer realm="https://evil.example/token",service="ghcr.io"'

    with patch.object(deployment_agent, "registry_urlopen") as urlopen:
        with pytest.raises(deployment_agent.RegistryMetadataError, match="Registry"):
            deployment_agent.fetch_registry_token(auth_header, registry_host="ghcr.io")

    urlopen.assert_not_called()


def test_registry_request_rejects_redirect_without_following_target(monkeypatch):
    redirect = urllib.error.HTTPError(
        url="https://ghcr.io/v2/owner/app/manifests/latest",
        code=HTTPStatus.FOUND,
        msg="redirect",
        hdrs={"Location": "https://169.254.169.254/latest"},
        fp=None,
    )
    opener = Mock()
    opener.open.side_effect = redirect
    monkeypatch.setattr(deployment_agent, "REGISTRY_ALLOWED_HOSTS", "ghcr.io", raising=False)

    with (
        patch("urllib.request.build_opener", return_value=opener) as build_opener,
        patch("urllib.request.urlopen", side_effect=redirect),
    ):
        with pytest.raises(deployment_agent.RegistryMetadataError, match="Redirect"):
            deployment_agent.registry_request(
                "https://ghcr.io/v2/owner/app/manifests/latest",
                accept="application/json",
            )

    build_opener.assert_called_once()
    opener.open.assert_called_once()


def test_check_rejects_untrusted_registry_without_network_or_state_mutation(monkeypatch):
    client = Mock()
    client.get_stack.return_value = active_stack("https://169.254.169.254/metadata/app:latest")
    save_state = Mock()
    network = Mock()
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "REGISTRY_ALLOWED_HOSTS", "ghcr.io", raising=False)
    monkeypatch.setattr(deployment_agent, "save_state", save_state)
    monkeypatch.setattr(deployment_agent, "registry_urlopen", network)

    with pytest.raises(deployment_agent.RegistryMetadataError, match="Registry"):
        deployment_agent.check_update({"current": {"version": "42", "revision": "old"}})

    network.assert_not_called()
    save_state.assert_not_called()
    client.update_stack_image.assert_not_called()


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

    with patch.object(
        deployment_agent,
        "registry_urlopen",
        side_effect=[unauthorized, manifest_response],
    ) as urlopen:
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


def test_health_route_stays_available_while_portainer_is_unreachable(monkeypatch):
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "GET"
    handler.path = "/healthz"
    handler.authorized = lambda: True
    handler.respond = Mock()
    portainer = Mock(side_effect=deployment_agent.PortainerAPIError("Portainer API ist nicht erreichbar."))
    monkeypatch.setattr(deployment_agent, "PortainerClient", portainer)

    handler.dispatch()

    handler.respond.assert_called_once_with(HTTPStatus.OK, {"status": "ok"})
    portainer.assert_not_called()


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


def test_request_handler_maps_invalid_registry_metadata_to_stable_public_error(monkeypatch):
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "POST"
    handler.path = "/check"
    handler.authorized = lambda: True
    handler.respond = Mock()
    monkeypatch.setattr(deployment_agent, "read_json_body", lambda _handler: {})
    monkeypatch.setattr(
        deployment_agent,
        "check_update",
        Mock(side_effect=deployment_agent.RegistryMetadataError("internal digest detail")),
    )

    handler.dispatch()

    handler.respond.assert_called_once_with(
        HTTPStatus.BAD_GATEWAY,
        {"error": "invalid_registry_metadata"},
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

    assert list(tmp_path.glob("backup-archive-*.tar.gz")) == []


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
    repository = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp"
    pinned_image = repository + ":" + ("1" * 40)
    discovery_image = repository + ":latest"
    client = Mock()
    client.get_stack.return_value = active_stack(pinned_image)
    latest = {
        "id": digest,
        "image": discovery_image,
        "version": "43",
        "revision": "newrev",
        "build_date": "2026-08-12T12:00:00Z",
        "change": "fix: updater",
    }
    fetch = Mock(return_value=latest)
    runtime_digest = image_digest("d")

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", fetch)
    monkeypatch.setattr(
        deployment_agent, "immutable_running_image", Mock(return_value=target_digest_reference(runtime_digest))
    )
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)
    monkeypatch.setattr(deployment_agent.secrets, "token_urlsafe", lambda _size: "checked-candidate-token")

    result = deployment_agent.check_update({"current": {"version": "42", "revision": "oldrev"}})

    expected_image = repository + "@" + digest
    fetch.assert_called_once_with(discovery_image)
    assert result["update_available"] is True
    assert result["approved_image"] == expected_image
    assert result["approved_digest"] == digest
    assert result["candidate_id"] == "checked-candidate-token"
    assert result["candidate_digest"] == digest
    assert result["candidate_base_digest"] == runtime_digest
    assert result["candidate_contract"] == TEST_CANDIDATE_CONTRACT
    assert states[-1]["approved_image"] == expected_image
    assert states[-1]["candidate_id"] == "checked-candidate-token"


def test_check_update_binds_candidate_to_running_repo_digest(monkeypatch):
    states = []
    base_digest = image_digest("a")
    candidate_digest = image_digest("b")
    client = Mock()
    client.get_stack.return_value = active_stack(TEST_TARGET_IMAGE)
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "immutable_running_image",
        Mock(return_value=target_digest_reference(base_digest)),
    )
    monkeypatch.setattr(
        deployment_agent,
        "fetch_image_metadata",
        lambda _image: {"id": candidate_digest, "image": TEST_TARGET_IMAGE, "version": "43", "revision": "new"},
    )
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: states.append(values) or values)

    result = deployment_agent.check_update({"current": {"version": "42", "revision": "old"}})

    assert result["candidate_base_digest"] == base_digest
    assert states[-1]["candidate_base_digest"] == base_digest


@pytest.mark.parametrize("runtime_image", [target_digest_reference(image_digest("c")), TEST_TARGET_IMAGE])
def test_install_rejects_changed_or_invalid_runtime_base_before_candidate_consumption(
    monkeypatch, tmp_path, runtime_image
):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    deployment_agent.save_state(**checked_candidate_state(candidate_base_digest=image_digest("a")))
    client = Mock()
    client.get_stack.return_value = active_stack(TEST_TARGET_IMAGE)
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "immutable_running_image",
        Mock(return_value=runtime_image),
    )
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "POST"
    handler.path = "/install"
    handler.authorized = lambda: True
    handler.respond = Mock()
    monkeypatch.setattr(
        deployment_agent,
        "read_json_body",
        lambda _handler: {"candidate_id": TEST_CANDIDATE_ID},
    )
    thread = Mock()
    monkeypatch.setattr(deployment_agent.threading, "Thread", thread)

    handler.dispatch()

    handler.respond.assert_called_once_with(
        HTTPStatus.CONFLICT,
        {"error": "stale_runtime_base"},
    )
    thread.assert_not_called()
    assert client.update_stack_image.call_count == 0
    state = deployment_agent.load_state()
    assert state["update_available"] is False
    assert state["candidate_id"] == ""
    assert state["candidate_base_digest"] == ""


def test_install_rejects_legacy_candidate_without_runtime_base(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    state = checked_candidate_state()
    state.pop("candidate_base_digest")
    deployment_agent.save_state(**state)
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "POST"
    handler.path = "/install"
    handler.authorized = lambda: True
    handler.respond = Mock()
    monkeypatch.setattr(deployment_agent, "read_json_body", lambda _handler: {"candidate_id": TEST_CANDIDATE_ID})
    monkeypatch.setattr(deployment_agent.threading, "Thread", Mock())

    handler.dispatch()

    handler.respond.assert_called_once_with(HTTPStatus.CONFLICT, {"error": "candidate_mismatch"})


def test_install_accepts_candidate_when_runtime_base_is_unchanged_and_is_target(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    target_digest = image_digest("a")
    deployment_agent.save_state(**checked_candidate_state(candidate_base_digest=target_digest))
    client = Mock()
    client.get_stack.return_value = active_stack(TEST_TARGET_IMAGE)
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "immutable_running_image",
        Mock(return_value=target_digest_reference(target_digest)),
    )
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "POST"
    handler.path = "/install"
    handler.authorized = lambda: True
    handler.respond = Mock()
    monkeypatch.setattr(deployment_agent, "read_json_body", lambda _handler: {"candidate_id": TEST_CANDIDATE_ID})

    class NoopThread:
        def __init__(self, *, target, args, name, daemon):
            self.target = target
            self.args = args
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(deployment_agent, "perform_update", lambda _state: deployment_agent.update_lock.release())
    monkeypatch.setattr(deployment_agent.threading, "Thread", NoopThread)

    handler.dispatch()

    handler.respond.assert_called_once_with(HTTPStatus.ACCEPTED, {"status": "accepted"})
    assert client.update_stack_image.call_count == 0


def test_immutable_running_image_rejects_ambiguous_matching_repo_digests():
    client = Mock()
    client.docker_request.side_effect = [
        [{"ImageID": "sha256:config"}],
        {
            "RepoDigests": [
                target_digest_reference(image_digest("a")),
                target_digest_reference(image_digest("b")),
            ]
        },
    ]

    with pytest.raises(RuntimeError, match="genau einen"):
        deployment_agent.immutable_running_image(client, TEST_TARGET_IMAGE)


def test_check_holds_exclusive_lock_through_atomic_state_save(monkeypatch):
    save_started = threading.Event()
    release_save = threading.Event()
    result = {}
    client = Mock()
    client.get_stack.return_value = active_stack(TEST_TARGET_IMAGE)

    def blocking_save(**values):
        save_started.set()
        assert release_save.wait(timeout=2)
        return values

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "fetch_image_metadata",
        lambda _image: {
            "id": image_digest("a"),
            "image": TEST_TARGET_IMAGE,
            "version": "43",
            "revision": "new-revision",
        },
    )
    monkeypatch.setattr(deployment_agent, "save_state", blocking_save)

    check_thread = threading.Thread(
        target=lambda: result.setdefault("state", deployment_agent.check_update({"current": {"revision": "old"}}))
    )
    check_thread.start()
    try:
        assert save_started.wait(timeout=1)

        with pytest.raises(deployment_agent.AgentRequestError) as conflict:
            deployment_agent.check_update({"current": {"revision": "old"}})

        assert conflict.value.status == HTTPStatus.CONFLICT
        assert conflict.value.public_code == "update_in_progress"
    finally:
        release_save.set()
        check_thread.join(timeout=2)

    assert not check_thread.is_alive()
    assert result["state"]["phase"] == "checked"


def test_install_conflicts_while_check_owns_update_lock(monkeypatch):
    registry_started = threading.Event()
    release_registry = threading.Event()
    client = Mock()
    client.get_stack.return_value = active_stack(TEST_TARGET_IMAGE)

    def blocking_fetch(_image):
        registry_started.set()
        assert release_registry.wait(timeout=2)
        return {"id": image_digest("a"), "image": TEST_TARGET_IMAGE}

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", blocking_fetch)
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: values)
    check_thread = threading.Thread(target=lambda: deployment_agent.check_update({"current": {}}))
    check_thread.start()
    try:
        assert registry_started.wait(timeout=1)
        handler = object.__new__(deployment_agent.RequestHandler)
        handler.command = "POST"
        handler.path = "/install"
        handler.authorized = lambda: True
        handler.respond = Mock()
        monkeypatch.setattr(deployment_agent, "read_json_body", lambda _handler: {"candidate_id": "stale"})

        handler.dispatch()

        handler.respond.assert_called_once_with(HTTPStatus.CONFLICT, {"error": "update_in_progress"})
    finally:
        release_registry.set()
        check_thread.join(timeout=2)

    assert not check_thread.is_alive()


@pytest.mark.parametrize("failure_boundary", ["registry", "state"])
def test_check_releases_update_lock_after_registry_or_state_failure(monkeypatch, failure_boundary):
    client = Mock()
    client.get_stack.return_value = active_stack(TEST_TARGET_IMAGE)
    metadata = {"id": image_digest("a"), "image": TEST_TARGET_IMAGE}
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "fetch_image_metadata",
        Mock(side_effect=RuntimeError("registry failed"))
        if failure_boundary == "registry"
        else Mock(return_value=metadata),
    )
    monkeypatch.setattr(
        deployment_agent,
        "save_state",
        Mock(side_effect=OSError("state failed")) if failure_boundary == "state" else Mock(),
    )

    with pytest.raises((OSError, RuntimeError), match="failed"):
        deployment_agent.check_update({"current": {}})

    assert deployment_agent.update_lock.acquire(blocking=False)
    deployment_agent.update_lock.release()


def test_install_owns_lock_until_background_update_finishes(monkeypatch):
    install_started = threading.Event()
    release_install = threading.Event()
    install_finished = threading.Event()
    checked_state = checked_candidate_state()

    def blocking_install(candidate_state):
        assert candidate_state["approved_digest"] == checked_state["approved_digest"]
        assert candidate_state["candidate_identity"] == hashlib.sha256(TEST_CANDIDATE_ID.encode()).hexdigest()
        assert candidate_state["operation_id"]
        install_started.set()
        assert release_install.wait(timeout=2)
        deployment_agent.update_lock.release()
        install_finished.set()

    monkeypatch.setattr(deployment_agent, "load_state", lambda: checked_state)
    monkeypatch.setattr(deployment_agent, "save_state", lambda **values: values)
    monkeypatch.setattr(deployment_agent, "perform_update", blocking_install)
    client = Mock()
    client.get_stack.return_value = active_stack(TEST_TARGET_IMAGE)
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "POST"
    handler.path = "/install"
    handler.authorized = lambda: True
    handler.respond = Mock()
    monkeypatch.setattr(
        deployment_agent,
        "read_json_body",
        lambda _handler: {"candidate_id": "checked-candidate-token"},
    )

    handler.dispatch()
    try:
        assert install_started.wait(timeout=1)
        with pytest.raises(deployment_agent.AgentRequestError) as conflict:
            deployment_agent.check_update({"current": {}})
        assert conflict.value.public_code == "update_in_progress"
    finally:
        release_install.set()
        assert install_finished.wait(timeout=2)

    handler.respond.assert_called_once_with(HTTPStatus.ACCEPTED, {"status": "accepted"})
    assert deployment_agent.update_lock.acquire(blocking=False)
    deployment_agent.update_lock.release()


def test_old_candidate_is_rejected_after_a_new_check_without_starting_install(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    client = Mock()
    client.get_stack.return_value = active_stack(TEST_TARGET_IMAGE)
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "fetch_image_metadata",
        lambda _image: {
            "id": image_digest("a"),
            "image": TEST_TARGET_IMAGE,
            "version": "43",
            "revision": "new-revision",
        },
    )
    monkeypatch.setattr(
        deployment_agent.secrets,
        "token_urlsafe",
        Mock(side_effect=["old-candidate-token", "new-candidate-token"]),
    )
    current = {"current": {"version": "42", "revision": "old-revision"}}
    old_candidate = deployment_agent.check_update(current)["candidate_id"]
    assert deployment_agent.check_update(current)["candidate_id"] == "new-candidate-token"
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "POST"
    handler.path = "/install"
    handler.authorized = lambda: True
    handler.respond = Mock()
    monkeypatch.setattr(deployment_agent, "read_json_body", lambda _handler: {"candidate_id": old_candidate})
    thread = Mock()
    monkeypatch.setattr(deployment_agent.threading, "Thread", thread)

    handler.dispatch()
    if deployment_agent.update_lock.locked():
        deployment_agent.update_lock.release()

    handler.respond.assert_called_once_with(HTTPStatus.CONFLICT, {"error": "candidate_mismatch"})
    thread.assert_not_called()
    assert deployment_agent.load_state()["candidate_id"] == "new-candidate-token"
    assert deployment_agent.update_lock.acquire(blocking=False)
    deployment_agent.update_lock.release()


@pytest.mark.parametrize(
    "state",
    [
        checked_candidate_state(phase="idle"),
        checked_candidate_state(update_available=False),
        checked_candidate_state(candidate_contract=1),
        checked_candidate_state(candidate_contract=None),
        checked_candidate_state(candidate_contract=0),
        {**checked_candidate_state(), "candidate_digest": image_digest("b")},
        {**checked_candidate_state(), "approved_image": TEST_TARGET_IMAGE},
    ],
    ids=[
        "wrong-phase",
        "no-update",
        "old-contract",
        "legacy-state",
        "wrong-contract",
        "digest-mismatch",
        "mutable-image",
    ],
)
def test_install_rejects_noninstallable_or_stale_candidate_state_without_thread(monkeypatch, state):
    monkeypatch.setattr(deployment_agent, "load_state", lambda: state)
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "POST"
    handler.path = "/install"
    handler.authorized = lambda: True
    handler.respond = Mock()
    monkeypatch.setattr(
        deployment_agent,
        "read_json_body",
        lambda _handler: {"candidate_id": TEST_CANDIDATE_ID},
    )
    thread = Mock()
    monkeypatch.setattr(deployment_agent.threading, "Thread", thread)

    handler.dispatch()
    if deployment_agent.update_lock.locked():
        deployment_agent.update_lock.release()

    handler.respond.assert_called_once_with(HTTPStatus.CONFLICT, {"error": "candidate_mismatch"})
    thread.assert_not_called()
    assert deployment_agent.update_lock.acquire(blocking=False)
    deployment_agent.update_lock.release()


def test_install_consumes_candidate_atomically_before_thread_start(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    deployment_agent.save_state(**checked_candidate_state())
    observed = {}

    def background_update(checked_state):
        observed["checked_state"] = checked_state
        deployment_agent.update_lock.release()

    class InspectingThread:
        def __init__(self, *, target, args, name, daemon):
            self.target = target
            self.args = args
            assert name == "deployment-update"
            assert daemon is True

        def start(self):
            consumed = deployment_agent.load_state()
            assert consumed["phase"] == "installing"
            assert consumed["candidate_id"] == ""
            assert consumed["candidate_digest"] == ""
            assert consumed["candidate_base_digest"] == ""
            assert consumed["update_available"] is False
            self.target(*self.args)

    monkeypatch.setattr(deployment_agent, "perform_update", background_update)
    monkeypatch.setattr(deployment_agent.threading, "Thread", InspectingThread)
    client = Mock()
    client.get_stack.return_value = active_stack(TEST_TARGET_IMAGE)
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "POST"
    handler.path = "/install"
    handler.authorized = lambda: True
    handler.respond = Mock()
    monkeypatch.setattr(
        deployment_agent,
        "read_json_body",
        lambda _handler: {"candidate_id": TEST_CANDIDATE_ID},
    )

    handler.dispatch()

    handler.respond.assert_called_once_with(HTTPStatus.ACCEPTED, {"status": "accepted"})
    assert observed["checked_state"]["approved_digest"] == image_digest("a")


def test_consumed_candidate_replay_is_rejected_before_background_work(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_agent, "STATE_FILE", tmp_path / "status.json")
    deployment_agent.save_state(**checked_candidate_state())
    checked_state = deployment_agent.consume_install_candidate(TEST_CANDIDATE_ID)

    with pytest.raises(deployment_agent.AgentRequestError) as conflict:
        deployment_agent.consume_install_candidate(TEST_CANDIDATE_ID)

    assert checked_state["approved_digest"] == image_digest("a")
    assert conflict.value.status == HTTPStatus.CONFLICT
    assert conflict.value.public_code == "candidate_mismatch"


@pytest.mark.parametrize("phase", ["complete", "failed"])
def test_candidate_replay_after_terminal_state_is_rejected_without_thread(monkeypatch, phase):
    stale_candidate = checked_candidate_state(phase=phase)
    stale_candidate["update_available"] = False
    monkeypatch.setattr(deployment_agent, "load_state", lambda: stale_candidate)
    handler = object.__new__(deployment_agent.RequestHandler)
    handler.command = "POST"
    handler.path = "/install"
    handler.authorized = lambda: True
    handler.respond = Mock()
    monkeypatch.setattr(
        deployment_agent,
        "read_json_body",
        lambda _handler: {"candidate_id": TEST_CANDIDATE_ID},
    )
    thread = Mock()
    monkeypatch.setattr(deployment_agent.threading, "Thread", thread)

    handler.dispatch()
    if deployment_agent.update_lock.locked():
        deployment_agent.update_lock.release()

    handler.respond.assert_called_once_with(HTTPStatus.CONFLICT, {"error": "candidate_mismatch"})
    thread.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        deployment_agent.RegistryMetadataError("invalid metadata"),
        RuntimeError("registry unavailable"),
    ],
)
def test_check_update_registry_errors_do_not_mutate_state_or_redeploy(monkeypatch, error):
    client = Mock()
    client.get_stack.return_value = active_stack("ghcr.io/lsf/app@" + image_digest("b"))
    save_state = Mock()

    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(deployment_agent, "fetch_image_metadata", Mock(side_effect=error))
    monkeypatch.setattr(deployment_agent, "save_state", save_state)

    with pytest.raises(type(error), match=str(error)):
        deployment_agent.check_update({"current": {"revision": "oldrev"}})

    save_state.assert_not_called()
    client.update_stack_image.assert_not_called()


def test_check_update_rejects_metadata_without_a_valid_digest(monkeypatch):
    client = Mock()
    client.get_stack.return_value = active_stack(TEST_TARGET_IMAGE)
    monkeypatch.setattr(deployment_agent, "PortainerClient", lambda: client)
    monkeypatch.setattr(
        deployment_agent,
        "fetch_image_metadata",
        lambda _image: {"id": "not-a-digest", "image": TEST_TARGET_IMAGE},
    )

    with pytest.raises(RuntimeError, match="Digest"):
        deployment_agent.check_update({"current": {"revision": "oldrev"}})


def test_perform_update_uses_checked_digest_when_the_tag_changes(monkeypatch):
    digest = "sha256:" + ("b" * 64)
    old_digest = "sha256:" + ("c" * 64)
    approved_image = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp@" + digest
    old_image = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp@" + old_digest
    state = {
        "candidate_id": TEST_CANDIDATE_ID,
        "latest": {"id": digest, "image": TEST_TARGET_IMAGE},
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
        deployment_agent.perform_update(state)
    finally:
        if deployment_agent.update_lock.locked():
            deployment_agent.update_lock.release()

    client.update_stack_image.assert_called_once_with(approved_image)
    assert ":latest" not in client.update_stack_image.call_args.args[0]
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
        "candidate_id": TEST_CANDIDATE_ID,
        "latest": {"id": approved_digest, "image": TEST_TARGET_IMAGE},
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
        [{"ImageID": "sha256:restored-config"}],
        {"RepoDigests": [old_image]},
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
        deployment_agent.perform_update(state)
    finally:
        if deployment_agent.update_lock.locked():
            deployment_agent.update_lock.release()

    assert client.update_stack_image.mock_calls == [call(approved_image), call(old_image)]
    assert states[-1]["phase"] == "failed"
    assert states[-1]["candidate_id"] == ""
    assert states[-1]["update_available"] is False
    assert "freigegebene Image-Digest" in states[-1]["error"]
