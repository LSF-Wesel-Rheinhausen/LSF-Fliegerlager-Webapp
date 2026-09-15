from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import ssl
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, NoReturn

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("deployment-agent")


class AgentConfigError(RuntimeError):
    """Raised when required updater environment variables are missing or invalid."""


class PortainerAPIError(RuntimeError):
    """Raised when Portainer rejects a stack operation."""


class PortainerTransientError(PortainerAPIError):
    """Raised when Portainer cannot be reached and a bounded retry is safe."""


class RegistryMetadataError(RuntimeError):
    """Raised when registry metadata cannot be trusted for an immutable update."""


class BackupArtifactCategory(Enum):
    """Internal backup categories with fixed filesystem naming components."""

    BEFORE_UPDATE = ("fliegerlager-before-update", ".sql.gz")
    ARCHIVE = ("backup-archive", ".tar.gz")

    @property
    def filename_prefix(self) -> str:
        """Return the server-controlled filename prefix for this category."""
        return self.value[0]

    @property
    def suffix(self) -> str:
        """Return the server-controlled filename suffix for this category."""
        return self.value[1]


class AgentRequestError(RuntimeError):
    """Raised for a client request that cannot be safely processed."""

    def __init__(self, status: HTTPStatus, public_code: str) -> None:
        super().__init__(public_code)
        self.status = status
        self.public_code = public_code


class BackupInProgressError(AgentRequestError):
    """Raised when another backup already owns the shared backup lock."""

    def __init__(self) -> None:
        super().__init__(HTTPStatus.CONFLICT, "backup_in_progress")


def positive_int_setting(name: str, default: str) -> int:
    """Read a positive integer setting used to bound agent resources."""
    raw_value = os.getenv(name, default)
    try:
        value = int(raw_value)
    except ValueError as error:
        raise AgentConfigError(f"{name} muss eine positive Ganzzahl sein.") from error
    if value <= 0:
        raise AgentConfigError(f"{name} muss eine positive Ganzzahl sein.")
    return value


def positive_float_setting(name: str, default: str) -> float:
    """Read a positive timeout setting used to bound agent resources."""
    raw_value = os.getenv(name, default)
    try:
        value = float(raw_value)
    except ValueError as error:
        raise AgentConfigError(f"{name} muss eine positive Zahl sein.") from error
    if not math.isfinite(value) or value <= 0:
        raise AgentConfigError(f"{name} muss eine positive Zahl sein.")
    return value


TOKEN = os.environ["UPDATE_AGENT_TOKEN"]
TARGET_SERVICE = os.getenv("TARGET_SERVICE", "app")
PORTAINER_URL = os.getenv("PORTAINER_URL", "").rstrip("/")
PORTAINER_API_KEY = os.getenv("PORTAINER_API_KEY", "")
PORTAINER_ENDPOINT_ID = os.getenv("PORTAINER_ENDPOINT_ID", "")
PORTAINER_STACK_ID = os.getenv("PORTAINER_STACK_ID", "")
PORTAINER_VERIFY_SSL = os.getenv("PORTAINER_VERIFY_SSL", "true")
APP_HEALTH_URL = os.getenv("APP_HEALTH_URL", "http://app:8000/healthz/")
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/backups"))
DATABASE_URL = os.getenv("DATABASE_URL", "")
GHCR_TOKEN = os.getenv("GHCR_TOKEN", "")
REGISTRY_ALLOWED_HOSTS = os.getenv("UPDATE_REGISTRY_ALLOWED_HOSTS", "ghcr.io")
HEALTH_TIMEOUT = int(os.getenv("UPDATE_HEALTH_TIMEOUT", "180"))
STATE_FILE = Path(os.getenv("UPDATE_STATE_FILE", "/state/status.json"))
UPDATE_ENVIRONMENT = os.getenv("UPDATE_ENVIRONMENT", "prod").strip().lower()
MAX_AGENT_BODY_BYTES = positive_int_setting("MAX_AGENT_BODY_BYTES", "1048576")
AGENT_READ_TIMEOUT_SECONDS = positive_float_setting("AGENT_READ_TIMEOUT_SECONDS", "10")
MAX_AGENT_CONCURRENT_REQUESTS = positive_int_setting("MAX_AGENT_CONCURRENT_REQUESTS", "8")
PORTAINER_STARTUP_TIMEOUT_SECONDS = positive_float_setting("PORTAINER_STARTUP_TIMEOUT_SECONDS", "30")
PORTAINER_STARTUP_INITIAL_BACKOFF_SECONDS = positive_float_setting("PORTAINER_STARTUP_INITIAL_BACKOFF_SECONDS", "1")
PORTAINER_STARTUP_MAX_BACKOFF_SECONDS = positive_float_setting("PORTAINER_STARTUP_MAX_BACKOFF_SECONDS", "5")
PORTAINER_REQUEST_TIMEOUT_SECONDS = positive_float_setting("PORTAINER_REQUEST_TIMEOUT_SECONDS", "10")
RECOVERY_CONVERGENCE_TIMEOUT_SECONDS = positive_float_setting("RECOVERY_CONVERGENCE_TIMEOUT_SECONDS", "30")
RECOVERY_CONVERGENCE_INITIAL_BACKOFF_SECONDS = positive_float_setting(
    "RECOVERY_CONVERGENCE_INITIAL_BACKOFF_SECONDS", "1"
)
RECOVERY_CONVERGENCE_MAX_BACKOFF_SECONDS = positive_float_setting("RECOVERY_CONVERGENCE_MAX_BACKOFF_SECONDS", "5")
MAX_REGISTRY_RESPONSE_BYTES = positive_int_setting("MAX_REGISTRY_RESPONSE_BYTES", "16777216")
MAX_REGISTRY_REDIRECTS = 3
BACKUP_STAGING_PATTERN = re.compile(r"^staging/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
BACKUP_ARCHIVE_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
CONTENT_LENGTH_PATTERN = re.compile(r"^[0-9]+$")
IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_TAG_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
REGISTRY_HOST_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
CANDIDATE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
CANDIDATE_CONTRACT_VERSION = 2
RECOVERY_CONTRACT_VERSION = 1

update_lock = threading.Lock()
backup_lock = threading.Lock()
state_lock = threading.Lock()

PERSISTED_STATE_FIELDS = frozenset(
    {
        "phase",
        "message",
        "error",
        "rollback_error",
        "recovery",
        "backup",
        "approved_image",
        "approved_digest",
        "selected_catalog_id",
        "candidate_environment",
        "compatibility",
        "risk_requires_acknowledgement",
        "target_metadata",
        "candidate_id",
        "candidate_digest",
        "candidate_base_digest",
        "candidate_contract",
        "candidate_invalidated_reason",
        "candidate_consumed_at",
        "update_available",
        "checked_at",
        "running",
        "operation_started_at",
        "operation_id",
        "candidate_identity",
        "recovery_contract",
        "target_image",
        "target_digest",
        "rollback_image",
        "target_put_started_at",
        "rollback_put_started_at",
        "recovery_outcome",
        "completed_at",
        "updated_at",
    }
)
COMMON_STATE_FIELDS = frozenset(
    {
        "phase",
        "message",
        "error",
        "rollback_error",
        "recovery",
        "backup",
        "running",
        "update_available",
        "recovery_outcome",
        "completed_at",
        "updated_at",
    }
)
CANDIDATE_STATE_FIELDS = frozenset(
    {
        "approved_image",
        "approved_digest",
        "selected_catalog_id",
        "candidate_environment",
        "compatibility",
        "risk_requires_acknowledgement",
        "target_metadata",
        "candidate_id",
        "candidate_digest",
        "candidate_base_digest",
        "candidate_contract",
        "candidate_invalidated_reason",
        "checked_at",
    }
)
RECOVERY_STATE_FIELDS = frozenset(
    {
        "candidate_consumed_at",
        "operation_started_at",
        "operation_id",
        "candidate_identity",
        "recovery_contract",
        "target_image",
        "target_digest",
        "rollback_image",
        "target_put_started_at",
        "rollback_put_started_at",
    }
)

OCI_LABELS = {
    "version": "org.opencontainers.image.version",
    "revision": "org.opencontainers.image.revision",
    "build_date": "org.opencontainers.image.created",
    "change": "io.lsf-fliegerlager.change",
    "changelog": "io.lsf-fliegerlager.changelog",
    "migrations": "io.lsf-fliegerlager.migrations",
}
MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)
IMAGE_MANIFEST_MEDIA_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}

ENVIRONMENT_CHANNELS = {
    "prod": ("prod",),
    "staging": ("prod", "staging"),
    "dev": ("prod", "staging", "dev"),
}


def environment_channels(environment: str = UPDATE_ENVIRONMENT) -> tuple[str, ...]:
    """Return the release channels visible to one configured environment."""
    try:
        return ENVIRONMENT_CHANNELS[environment]
    except KeyError as error:
        raise AgentConfigError("UPDATE_ENVIRONMENT muss prod, staging oder dev sein.") from error


def require_env(name: str, value: str) -> str:
    """Return a required environment value or raise a clear configuration error."""
    if value.strip():
        return value
    raise AgentConfigError(f"Pflichtvariable {name} ist nicht gesetzt.")


def parse_bool_env(name: str, value: str) -> bool:
    """Parse a strict true/false environment value."""
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise AgentConfigError(f"{name} muss 'true' oder 'false' sein.")


def utc_now() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()


def load_state() -> dict[str, Any]:
    """Load the persisted updater state for the Django status page."""
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"phase": "idle", "message": "Noch kein Update ausgefuehrt."}


def _bounded_metadata(value: Any, allowed: tuple[str, ...]) -> dict[str, str]:
    """Return only short, scalar OCI metadata fields suitable for status.json."""
    if not isinstance(value, dict):
        return {}
    return {
        key: limit_output(str(value[key]), 512 if key == "image" else 256)
        for key in allowed
        if value.get(key) is not None
    }


def _bounded_compatibility(value: Any) -> dict[str, Any]:
    """Return the small, presentation-safe migration risk summary."""
    if not isinstance(value, dict):
        return {}
    risk = value.get("risk")
    if risk not in {"identical", "forward", "downgrade", "divergent", "unknown"}:
        risk = "unknown"
    affected = value.get("affected_migrations")
    migrations = (
        [limit_output(item, 256) for item in affected[:20] if isinstance(item, str)]
        if isinstance(affected, list)
        else []
    )
    return {
        "risk": risk,
        "requires_acknowledgement": value.get("requires_acknowledgement") is True,
        "affected_migrations": migrations,
    }


def save_state(**values: Any) -> dict[str, Any]:
    """Persist updater state atomically and return the merged state."""
    with state_lock:
        current = load_state()
        next_phase = values.get("phase")
        if next_phase == "checked":
            for key in (
                "operation_started_at",
                "operation_id",
                "candidate_identity",
                "recovery_contract",
                "target_image",
                "target_digest",
                "rollback_image",
                "target_put_started_at",
                "rollback_put_started_at",
                "recovery_outcome",
                "completed_at",
            ):
                current.pop(key, None)
        elif next_phase == "installing" and current.get("phase") != "installing":
            for key in ("rollback_put_started_at", "recovery_outcome", "completed_at"):
                current.pop(key, None)
        current.update(values, updated_at=utc_now())
        phase = str(current.get("phase", "idle"))
        phase_fields = COMMON_STATE_FIELDS
        if phase == "checked":
            phase_fields |= CANDIDATE_STATE_FIELDS
        elif phase in {"installing", "rollback", "complete", "failed", "recovery_required"}:
            phase_fields |= RECOVERY_STATE_FIELDS
        persisted = {key: value for key, value in current.items() if key in phase_fields}
        for key in ("message", "error", "rollback_error", "candidate_invalidated_reason"):
            if isinstance(persisted.get(key), str):
                persisted[key] = limit_output(persisted[key], 2000)
        if isinstance(persisted.get("recovery"), str):
            persisted["recovery"] = limit_output(persisted["recovery"], 4000)
        persisted["target_metadata"] = _bounded_metadata(
            persisted.get("target_metadata"),
            ("version", "revision", "build_date", "change"),
        )
        persisted["running"] = _bounded_metadata(
            persisted.get("running"),
            ("image", "version", "revision", "build_date", "change"),
        )
        persisted["compatibility"] = _bounded_compatibility(persisted.get("compatibility"))
        for key in PERSISTED_STATE_FIELDS - {
            "message",
            "error",
            "rollback_error",
            "candidate_invalidated_reason",
            "recovery",
            "target_metadata",
            "running",
            "compatibility",
        }:
            if isinstance(persisted.get(key), str):
                persisted[key] = limit_output(persisted[key], 512)
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(persisted, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
        temporary.replace(STATE_FILE)
        return persisted


def limit_output(output: str, limit: int = 1200) -> str:
    """Shorten process output for UI-safe diagnostics."""
    stripped = output.strip()
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[:limit]}... [gekuerzt]"


def redact_secret(value: str) -> str:
    """Mask a secret while preserving enough context for diagnostics."""
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}...{value[-3:]}"


class PortainerClient:
    """Small Portainer API client scoped to one endpoint and stack."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        endpoint_id: str | None = None,
        stack_id: str | None = None,
        verify_ssl: str | bool | None = None,
    ) -> None:
        self.base_url = require_env("PORTAINER_URL", base_url if base_url is not None else PORTAINER_URL).rstrip("/")
        self.api_key = require_env("PORTAINER_API_KEY", api_key if api_key is not None else PORTAINER_API_KEY)
        self.endpoint_id = require_env(
            "PORTAINER_ENDPOINT_ID",
            endpoint_id if endpoint_id is not None else PORTAINER_ENDPOINT_ID,
        )
        self.stack_id = require_env("PORTAINER_STACK_ID", stack_id if stack_id is not None else PORTAINER_STACK_ID)
        if isinstance(verify_ssl, bool):
            self.verify_ssl = verify_ssl
        else:
            self.verify_ssl = parse_bool_env(
                "PORTAINER_VERIFY_SSL",
                verify_ssl if verify_ssl is not None else PORTAINER_VERIFY_SSL,
            )

    def ssl_context(self) -> ssl.SSLContext | None:
        """Return the Portainer TLS context, or None for default certificate verification."""
        if self.verify_ssl:
            return None
        return ssl._create_unverified_context()

    def raw_request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> Any:
        """Send a request to Portainer and return the decoded JSON payload."""
        url = f"{self.base_url}/api{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "X-API-Key": self.api_key,
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=self.ssl_context()) as response:
                if response.status == HTTPStatus.NO_CONTENT:
                    return {}
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise PortainerAPIError(self._format_http_error(error)) from error
        except (OSError, TimeoutError) as error:
            raise PortainerTransientError("Portainer API ist nicht erreichbar.") from error
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise PortainerAPIError("Portainer API lieferte ungueltiges JSON.") from error

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Send a JSON request to Portainer using the configured API key."""
        parsed = self.raw_request(method, path, query=query, payload=payload, timeout=timeout)
        if not isinstance(parsed, dict):
            raise PortainerAPIError("Portainer API lieferte eine unerwartete Antwort.")
        return parsed

    def docker_request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        timeout: float = PORTAINER_REQUEST_TIMEOUT_SECONDS,
    ) -> Any:
        """Call the Docker API through Portainer's endpoint proxy."""
        return self.raw_request(method, f"/endpoints/{self.endpoint_id}/docker{path}", query=query, timeout=timeout)

    def get_stack(self) -> dict[str, Any]:
        """Return the configured Portainer stack."""
        return self.request("GET", f"/stacks/{self.stack_id}", timeout=PORTAINER_REQUEST_TIMEOUT_SECONDS)

    def get_stack_file_content(self, stack: dict[str, Any]) -> str:
        """Return the Compose content Portainer requires for stack updates."""
        embedded = stack.get("StackFileContent") or stack.get("stackFileContent")
        if isinstance(embedded, str) and embedded.strip():
            return embedded
        result = self.request(
            "GET",
            f"/stacks/{self.stack_id}/file",
            query={"endpointId": self.endpoint_id},
            timeout=PORTAINER_REQUEST_TIMEOUT_SECONDS,
        )
        content = result.get("StackFileContent") or result.get("stackFileContent")
        if not isinstance(content, str) or not content.strip():
            raise PortainerAPIError("Portainer Stack-Datei konnte nicht gelesen werden.")
        return content

    def update_stack_image(self, image: str) -> dict[str, Any]:
        """Update APP_IMAGE in the stack variables and redeploy the stack."""
        stack = self.get_stack()
        stack_file_content = self.get_stack_file_content(stack)
        validate_updater_stack_contract(stack_file_content)
        env = update_env_pairs(extract_stack_env(stack), "APP_IMAGE", image)
        return self.request(
            "PUT",
            f"/stacks/{self.stack_id}",
            query={"endpointId": self.endpoint_id},
            payload={
                "env": env,
                "prune": False,
                "pullImage": True,
                "stackFileContent": stack_file_content,
            },
            timeout=180,
        )

    def _format_http_error(self, error: urllib.error.HTTPError) -> str:
        try:
            body = json.loads(error.read().decode("utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            body = {}
        detail = body.get("message") or body.get("details") or body.get("err") or f"HTTP {error.code}"
        return f"Portainer API: {detail}"


def extract_stack_env(stack: dict[str, Any]) -> list[dict[str, str]]:
    """Read Portainer stack environment variables from known response shapes."""
    env = stack.get("Env") or stack.get("env") or []
    if not isinstance(env, list):
        raise PortainerAPIError("Portainer Stack-ENV hat ein unerwartetes Format.")
    normalized: list[dict[str, str]] = []
    for item in env:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if isinstance(name, str):
            normalized.append({"name": name, "value": str(value or "")})
    return normalized


def update_env_pairs(env: list[dict[str, str]], name: str, value: str) -> list[dict[str, str]]:
    """Return Portainer env pairs with one variable inserted or replaced."""
    updated = False
    result: list[dict[str, str]] = []
    for item in env:
        if item.get("name") == name:
            result.append({"name": name, "value": value})
            updated = True
        else:
            result.append({"name": str(item.get("name", "")), "value": str(item.get("value", ""))})
    if not updated:
        result.append({"name": name, "value": value})
    return result


def stack_app_image(stack: dict[str, Any]) -> str:
    """Return the single validated APP_IMAGE value from the Portainer stack variables."""
    values = [item["value"] for item in extract_stack_env(stack) if item["name"] == "APP_IMAGE"]
    if len(values) != 1:
        raise RuntimeError("Portainer Stack muss genau einen APP_IMAGE-Wert enthalten.")
    latest_image_reference(values[0])
    return values[0]


def _yaml_content(line: str) -> tuple[int, str]:
    """Return indentation and significant YAML text for the supported Compose subset."""
    expanded = line.expandtabs(8)
    content = expanded.lstrip()
    return len(expanded) - len(content), content


def _yaml_unquoted_content(content: str) -> str:
    """Remove YAML comments and quoted scalar contents for lexical safety checks."""
    unquoted: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(content):
        character = content[index]
        if quote == "'":
            if character == "'" and index + 1 < len(content) and content[index + 1] == "'":
                unquoted.extend((" ", " "))
                index += 2
                continue
            if character == "'":
                quote = None
            unquoted.append(" ")
        elif quote == '"':
            if character == "\\" and index + 1 < len(content):
                unquoted.extend((" ", " "))
                index += 2
                continue
            if character == '"':
                quote = None
            unquoted.append(" ")
        elif character == "#":
            break
        elif character in {"'", '"'}:
            quote = character
            unquoted.append(" ")
        else:
            unquoted.append(character)
        index += 1
    return "".join(unquoted)


def _yaml_has_indirect_configuration(content: str) -> bool:
    """Return whether a line uses YAML merge, anchor, or alias syntax."""
    unquoted = _yaml_unquoted_content(content)
    return bool(
        re.search(r"(?:^|[\s\[\]{},:?])<<\s*:", unquoted)
        or re.search(r"(?:^|[\s\[\]{},:?])[&*](?:[^\s\[\]{},]+)?", unquoted)
    )


def validate_updater_stack_contract(stack_file_content: str) -> None:
    """Reject Compose definitions that can inject APP_IMAGE into the updater service.

    This deliberately supports only the ordinary block mapping/list forms emitted by
    this repository. Indirect or ambiguous updater configuration fails closed because
    safely resolving arbitrary YAML would require a full YAML implementation.
    """
    if not isinstance(stack_file_content, str) or not stack_file_content.strip():
        raise AgentRequestError(HTTPStatus.CONFLICT, "updater_stack_upgrade_required")

    lines = [_yaml_content(line) for line in stack_file_content.splitlines()]
    services_index = next(
        (index for index, (_indent, content) in enumerate(lines) if content == "services:"),
        None,
    )
    if services_index is None:
        raise AgentRequestError(HTTPStatus.CONFLICT, "updater_stack_upgrade_required")
    services_indent = lines[services_index][0]
    service_lines: list[tuple[int, int, str]] = []
    for index in range(services_index + 1, len(lines)):
        indent, content = lines[index]
        if not content or content.startswith("#"):
            continue
        if indent <= services_indent:
            break
        service_lines.append((index, indent, content))
    if not service_lines:
        raise AgentRequestError(HTTPStatus.CONFLICT, "updater_stack_upgrade_required")
    service_indent = min(indent for _index, indent, _content in service_lines)
    updater_entries = []
    for entry in service_lines:
        if entry[1] != service_indent:
            continue
        key, separator, _value = entry[2].partition(":")
        if separator and key.strip() == "updater":
            updater_entries.append(entry)
    if len(updater_entries) != 1:
        raise AgentRequestError(HTTPStatus.CONFLICT, "updater_stack_upgrade_required")
    updater_index, updater_indent, updater_content = updater_entries[0]

    updater_lines: list[tuple[int, int, str]] = []
    for index in range(updater_index + 1, len(lines)):
        indent, content = lines[index]
        if not content or content.startswith("#"):
            continue
        if indent <= updater_indent:
            break
        updater_lines.append((index, indent, content))
    if (
        not re.fullmatch(r"updater:\s*(?:#.*)?", updater_content)
        or _yaml_has_indirect_configuration(updater_content)
        or any(_yaml_has_indirect_configuration(content) for _index, _indent, content in updater_lines)
    ):
        raise AgentRequestError(HTTPStatus.CONFLICT, "updater_stack_indirect_configuration")
    if not updater_lines:
        return
    updater_child_indent = min(indent for _index, indent, _content in updater_lines)
    environment_entries: list[tuple[int, int, str]] = []
    for index, indent, content in updater_lines:
        if indent != updater_child_indent:
            continue
        key, separator, value = content.partition(":")
        if separator and key.strip() in {"env_file", "extends"}:
            raise AgentRequestError(HTTPStatus.CONFLICT, "updater_stack_upgrade_required")
        if key.strip() == "environment" and separator:
            if value.strip() not in {"", "{}", "[]"}:
                raise AgentRequestError(HTTPStatus.CONFLICT, "updater_stack_upgrade_required")
            environment_entries.append((index, indent, value.strip()))
    if len(environment_entries) > 1:
        raise AgentRequestError(HTTPStatus.CONFLICT, "updater_stack_upgrade_required")
    if not environment_entries or environment_entries[0][2] in {"{}", "[]"}:
        return
    environment_index, environment_indent, _environment_value = environment_entries[0]

    for indent, content in lines[environment_index + 1 :]:
        if not content or content.startswith("#"):
            continue
        if indent <= environment_indent:
            break
        item = content.removeprefix("- ").strip()
        name = item.split("=", 1)[0].split(":", 1)[0].strip().strip("'\"")
        if name == "APP_IMAGE":
            raise AgentRequestError(HTTPStatus.CONFLICT, "updater_stack_upgrade_required")


def validate_active_stack_contract(client: PortainerClient, stack: dict[str, Any]) -> None:
    """Validate the active Portainer Compose definition before update mutation."""
    embedded = stack.get("StackFileContent") or stack.get("stackFileContent")
    stack_file_content = (
        embedded if isinstance(embedded, str) and embedded.strip() else client.get_stack_file_content(stack)
    )
    validate_updater_stack_contract(stack_file_content)


def immutable_running_image(client: PortainerClient, target_image: str) -> str:
    """Return the currently running app image as an immutable repo digest."""
    filters = json.dumps({"label": [f"com.docker.compose.service={TARGET_SERVICE}"], "status": ["running"]})
    containers = client.docker_request("GET", "/containers/json", query={"filters": filters})
    if not isinstance(containers, list) or len(containers) != 1:
        raise RuntimeError(f"Erwartete genau einen laufenden Container fuer Service {TARGET_SERVICE}.")
    image_id = containers[0].get("ImageID") if isinstance(containers[0], dict) else None
    if not isinstance(image_id, str) or not image_id:
        raise RuntimeError("Laufender App-Container enthaelt keine Image-ID.")
    image = client.docker_request("GET", f"/images/{urllib.parse.quote(image_id, safe='')}/json")
    repo_digests = image.get("RepoDigests") if isinstance(image, dict) else None
    if not isinstance(repo_digests, list):
        raise RuntimeError("Laufendes App-Image enthaelt keine RepoDigests fuer Rollback.")
    target_registry, target_repository, _reference = parse_image_reference(target_image)
    target_prefix = f"{target_registry}/{target_repository}@"
    matching_digests = [
        digest for digest in repo_digests if isinstance(digest, str) and digest.startswith(target_prefix)
    ]
    if len(matching_digests) != 1 or not IMAGE_DIGEST_PATTERN.fullmatch(matching_digests[0].split("@", 1)[-1]):
        raise RuntimeError("Laufendes App-Image enthaelt nicht genau einen validen RepoDigest.")
    return matching_digests[0]


def parse_image_reference(image: str) -> tuple[str, str, str]:
    """Split an OCI image reference into registry, repository and tag or digest."""
    without_scheme = image.removeprefix("https://").removeprefix("http://")
    if "/" not in without_scheme:
        raise RuntimeError("APP_IMAGE muss Registry und Repository enthalten.")
    registry, remainder = without_scheme.split("/", 1)
    if "@" in remainder:
        repository, reference = remainder.split("@", 1)
        return registry, repository, reference
    name_part, separator, tag = remainder.rpartition(":")
    if separator and "/" not in tag:
        return registry, name_part, tag
    return registry, remainder, "latest"


def latest_image_reference(image: str) -> str:
    """Derive the mutable latest release channel from one explicit OCI repository reference."""
    if any(character.isspace() for character in image):
        raise RuntimeError("APP_IMAGE darf keine Leerzeichen enthalten.")
    normalized = image.removeprefix("https://").removeprefix("http://")
    if normalized.count("@") > 1:
        raise RuntimeError("APP_IMAGE ist durch mehrere Digest-Trennzeichen mehrdeutig.")

    registry, repository, reference = parse_image_reference(image)
    repository_parts = repository.split("/")
    if not registry or any(part in {"", ".", ".."} for part in repository_parts):
        raise RuntimeError("APP_IMAGE muss einen gültigen Repository-Namen enthalten.")
    if ":" in repository:
        raise RuntimeError("APP_IMAGE enthält eine mehrdeutige Tag-Referenz.")
    if any(character in registry + repository for character in "?#"):
        raise RuntimeError("APP_IMAGE enthält eine ungültige Registry- oder Repository-Referenz.")
    if "@" in normalized:
        if not IMAGE_DIGEST_PATTERN.fullmatch(reference):
            raise RuntimeError("APP_IMAGE enthält keinen validen OCI-Digest.")
    elif not IMAGE_TAG_PATTERN.fullmatch(reference):
        raise RuntimeError("APP_IMAGE enthält keinen validen OCI-Tag.")
    return f"{registry}/{repository}:latest"


def environment_image_reference(image: str, environment: str = UPDATE_ENVIRONMENT) -> str:
    """Derive the mutable release pointer for one configured environment."""
    registry, repository, _reference = parse_image_reference(image)
    tag = {"prod": "prod", "staging": "latest", "dev": "dev"}.get(environment)
    if tag is None:
        environment_channels(environment)
        raise AssertionError("unreachable")
    return f"{registry}/{repository}:{tag}"


def immutable_image_reference(image: str, digest: Any) -> str:
    """Return a validated registry/repository reference bound to one manifest digest."""
    if not isinstance(digest, str) or not IMAGE_DIGEST_PATTERN.fullmatch(digest):
        raise RuntimeError("OCI-Metadaten enthalten keinen validen Image-Digest.")
    registry, repository, _reference = parse_image_reference(image)
    return f"{registry}/{repository}@{digest}"


def validate_immutable_image_reference(image: Any) -> tuple[str, str]:
    """Validate an approved image reference and return it with its digest."""
    if not isinstance(image, str):
        raise RuntimeError("Kein freigegebenes unveraenderliches Update-Image vorhanden.")
    registry, repository, reference = parse_image_reference(image)
    if not IMAGE_DIGEST_PATTERN.fullmatch(reference):
        raise RuntimeError("Das freigegebene Update-Image ist nicht unveraenderlich.")
    return f"{registry}/{repository}@{reference}", reference


def canonical_registry_authority(value: str, *, configuration: bool = False) -> str:
    """Return one strict lowercase registry Host[:Port] authority."""

    def invalid(message: str) -> NoReturn:
        if configuration:
            raise AgentConfigError(f"UPDATE_REGISTRY_ALLOWED_HOSTS {message}")
        raise RegistryMetadataError(f"Registry-Host {message}")

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character.isspace() for character in value)
    ):
        invalid("ist leer oder enthält Leerzeichen.")
    if any(character in value for character in "/?#") or "://" in value:
        invalid("muss als exakter Host[:Port] ohne Schema oder Pfad angegeben werden.")
    try:
        parsed = urllib.parse.urlsplit(f"//{value}")
        port = parsed.port
    except ValueError:
        invalid("enthält einen ungültigen Port oder eine ungültige IPv6-Adresse.")
    if port == 0:
        invalid("enthält keinen gültigen TCP-Port.")
    if parsed.username is not None or parsed.password is not None or parsed.path or parsed.query or parsed.fragment:
        invalid("darf keine Userinfo, Pfade, Querys oder Fragmente enthalten.")
    hostname = parsed.hostname
    if not hostname or hostname.endswith(".") or "*" in hostname:
        invalid("ist ungültig; Wildcards und abschließende Punkte sind nicht erlaubt.")
    normalized_host = hostname.lower()
    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        try:
            normalized_host.encode("ascii")
        except UnicodeEncodeError:
            invalid("muss ein ASCII-Hostname sein.")
        labels = normalized_host.split(".")
        if len(labels) < 2 or any(not REGISTRY_HOST_LABEL_PATTERN.fullmatch(label) for label in labels):
            invalid("ist kein gültiger vollqualifizierter Hostname.")
    else:
        if (
            address.is_multicast
            or address.is_loopback
            or address.is_link_local
            or address.is_private
            or address.is_reserved
            or address.is_unspecified
            or not address.is_global
        ):
            invalid("darf kein privates, reserviertes oder anderweitig spezielles IP-Literal sein.")
        normalized_host = address.compressed
    authority = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    if port is not None:
        authority = f"{authority}:{port}"
    return authority


def allowed_registry_authorities() -> frozenset[str]:
    """Parse the explicit registry allowlist without DNS or wildcard matching."""
    entries = REGISTRY_ALLOWED_HOSTS.split(",")
    if not entries or any(not entry.strip() for entry in entries):
        raise AgentConfigError("UPDATE_REGISTRY_ALLOWED_HOSTS darf keine leeren Einträge enthalten.")
    return frozenset(canonical_registry_authority(entry.strip(), configuration=True) for entry in entries)


def validate_registry_url(url: str, *, expected_authority: str | None = None) -> str:
    """Validate an HTTPS registry URL against the exact configured host allowlist."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError as error:
        raise RegistryMetadataError("Registry-URL ist ungültig.") from error
    if parsed.scheme != "https" or not parsed.netloc or parsed.username is not None or parsed.password is not None:
        raise RegistryMetadataError("Registry-URL muss HTTPS ohne Userinfo verwenden.")
    authority = canonical_registry_authority(parsed.netloc)
    if authority not in allowed_registry_authorities():
        raise RegistryMetadataError("Registry-Host ist nicht explizit erlaubt.")
    if expected_authority is not None and authority != expected_authority:
        raise RegistryMetadataError("Registry-URL wechselt auf einen anderen Host.")
    return authority


def registry_basic_auth_header(registry_authority: str) -> str | None:
    """Return the configured GHCR Basic credential only for exact ghcr.io requests."""
    if not GHCR_TOKEN or registry_authority != "ghcr.io":
        return None
    encoded = base64.b64encode(f"unused:{GHCR_TOKEN}".encode()).decode("ascii")
    return f"Basic {encoded}"


def validate_registry_redirect_target(newurl: str) -> str:
    """Validate one public HTTPS redirect target without resolving or logging it."""
    if any(ord(character) < 32 or ord(character) == 127 for character in newurl):
        raise RegistryMetadataError("Registry-Redirect-Ziel ist ungueltig.")
    try:
        parsed = urllib.parse.urlsplit(newurl)
    except ValueError as error:
        raise RegistryMetadataError("Registry-Redirect-Ziel ist ungueltig.") from error
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        raise RegistryMetadataError("Registry-Redirect-Ziel ist unsicher.")
    try:
        return canonical_registry_authority(parsed.netloc)
    except RegistryMetadataError as error:
        raise RegistryMetadataError("Registry-Redirect-Ziel ist unsicher.") from error


class RegistryRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects except bounded, safe redirects for digest-addressed blobs."""

    def __init__(self, *, allow_blob_redirect: bool = False) -> None:
        super().__init__()
        self.allow_blob_redirect = allow_blob_redirect
        self.redirect_count = 0

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if not self.allow_blob_redirect:
            raise RegistryMetadataError("Registry-Redirects sind nicht erlaubt.")
        source_url = urllib.parse.urlsplit(req.full_url)
        if req.get_method() != "GET" or (
            self.redirect_count == 0 and not IMAGE_DIGEST_PATTERN.fullmatch(source_url.path.rsplit("/", 1)[-1])
        ):
            raise RegistryMetadataError("Registry-Redirects sind nur fuer Digest-Blobs erlaubt.")
        if self.redirect_count >= MAX_REGISTRY_REDIRECTS:
            raise RegistryMetadataError("Registry-Redirect-Limit ueberschritten.")
        target_authority = validate_registry_redirect_target(newurl)
        source_authority = canonical_registry_authority(source_url.netloc)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            raise RegistryMetadataError("Registry-Redirect-Ziel ist ungueltig.")
        if target_authority != source_authority:
            redirected.remove_header("Authorization")
            redirected.remove_header("Proxy-Authorization")
        self.redirect_count += 1
        return redirected


class RejectRegistryRedirectHandler(RegistryRedirectHandler):
    """Reject every registry redirect for manifests and token endpoints."""

    def __init__(self) -> None:
        super().__init__(allow_blob_redirect=False)


def registry_urlopen(
    request: urllib.request.Request,
    *,
    timeout: int,
    allow_blob_redirect: bool = False,
) -> Any:
    """Open one registry URL with redirects disabled except for safe blob downloads."""
    handler = RegistryRedirectHandler(allow_blob_redirect=allow_blob_redirect)
    opener = urllib.request.build_opener(handler)
    return opener.open(request, timeout=timeout)


def read_registry_body(response: Any) -> bytes:
    """Read a registry response within the configured response-size bound."""
    content_length = response.headers.get("Content-Length")
    if isinstance(content_length, (str, bytes)):
        try:
            if int(content_length) > MAX_REGISTRY_RESPONSE_BYTES:
                raise RegistryMetadataError("Registry-Antwort ist zu gross.")
        except ValueError as error:
            raise RegistryMetadataError("Registry-Antwort hat eine ungueltige Groesse.") from error
    raw = response.read(MAX_REGISTRY_RESPONSE_BYTES + 1)
    if len(raw) > MAX_REGISTRY_RESPONSE_BYTES:
        raise RegistryMetadataError("Registry-Antwort ist zu gross.")
    return raw


def registry_request(
    url: str,
    *,
    accept: str,
    token: str | None = None,
    timeout: int = 30,
    allow_blob_redirect: bool = False,
    expected_blob_digest: str | None = None,
) -> tuple[bytes, dict[str, str]]:
    """Fetch a registry resource and resolve public GHCR bearer auth challenges."""
    registry_authority = validate_registry_url(url)
    if allow_blob_redirect:
        parsed_path = urllib.parse.urlsplit(url).path
        if expected_blob_digest is None or not IMAGE_DIGEST_PATTERN.fullmatch(expected_blob_digest):
            raise RegistryMetadataError("Registry-Blob-Digest ist ungueltig.")
        if parsed_path.rsplit("/", 1)[-1] != expected_blob_digest:
            raise RegistryMetadataError("Registry-Blob-URL ist ungueltig.")
    headers = {"Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        authorization = registry_basic_auth_header(registry_authority)
        if authorization:
            headers["Authorization"] = authorization
    request = urllib.request.Request(url, headers=headers)
    try:
        with registry_urlopen(request, timeout=timeout, allow_blob_redirect=allow_blob_redirect) as response:
            return read_registry_body(response), dict(response.headers)
    except urllib.error.HTTPError as error:
        if HTTPStatus.MULTIPLE_CHOICES <= error.code < HTTPStatus.BAD_REQUEST:
            raise RegistryMetadataError("Registry-Redirects sind nicht erlaubt.") from error
        if error.code != HTTPStatus.UNAUTHORIZED or token:
            raise RuntimeError("Registry-Abfrage fehlgeschlagen.") from error
        bearer_token = fetch_registry_token(
            error.headers.get("WWW-Authenticate", ""),
            registry_host=registry_authority,
        )
        return registry_request(
            url,
            accept=accept,
            token=bearer_token,
            timeout=timeout,
            allow_blob_redirect=allow_blob_redirect,
            expected_blob_digest=expected_blob_digest,
        )
    except (OSError, TimeoutError) as error:
        raise RuntimeError("Registry ist nicht erreichbar.") from error


def registry_header(headers: dict[str, str], name: str) -> str | None:
    """Return a registry response header without depending on header casing."""
    wanted = name.casefold()
    for key, value in headers.items():
        if key.casefold() == wanted:
            return value
    return None


def manifest_digest(raw_manifest: bytes, headers: dict[str, str]) -> str:
    """Validate the optional registry digest against the exact manifest bytes."""
    calculated = "sha256:" + hashlib.sha256(raw_manifest).hexdigest()
    advertised = registry_header(headers, "Docker-Content-Digest")
    if advertised is None:
        return calculated
    if not IMAGE_DIGEST_PATTERN.fullmatch(advertised) or advertised != calculated:
        raise RegistryMetadataError("Registry-Manifest-Digest ist ungueltig.")
    return advertised


def fetch_registry_token(auth_header: str, *, registry_host: str = "ghcr.io") -> str:
    """Fetch a bearer token from a registry WWW-Authenticate challenge."""
    canonical_host = canonical_registry_authority(registry_host)
    if canonical_host not in allowed_registry_authorities():
        raise RegistryMetadataError("Registry-Host ist nicht explizit erlaubt.")
    if not auth_header.startswith("Bearer "):
        raise RuntimeError("Registry verlangt eine unbekannte Authentifizierung.")
    values = urllib.parse.parse_qs(auth_header.removeprefix("Bearer ").replace(",", "&").replace('"', ""))
    realm = values.get("realm", [""])[0]
    if not realm:
        raise RuntimeError("Registry-Authentifizierung enthaelt keinen Token-Endpunkt.")
    validate_registry_url(realm, expected_authority=canonical_host)
    query = {key: value[0] for key, value in values.items() if key in {"service", "scope"} and value}
    url = f"{realm}?{urllib.parse.urlencode(query)}" if query else realm
    headers = {"Accept": "application/json"}
    authorization = registry_basic_auth_header(canonical_host)
    if authorization:
        headers["Authorization"] = authorization
    request = urllib.request.Request(url, headers=headers)
    try:
        with registry_urlopen(request, timeout=30) as response:
            payload = json.loads(read_registry_body(response))
    except urllib.error.HTTPError as error:
        if HTTPStatus.MULTIPLE_CHOICES <= error.code < HTTPStatus.BAD_REQUEST:
            raise RegistryMetadataError("Registry-Redirects sind nicht erlaubt.") from error
        raise RuntimeError("Registry-Token konnte nicht geladen werden.") from error
    except (OSError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("Registry-Token konnte nicht geladen werden.") from error
    token = payload.get("token") or payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Registry-Token-Antwort ist ungueltig.")
    return token


def choose_manifest_descriptor(index: dict[str, Any]) -> dict[str, Any]:
    """Return the single validated baseline linux/amd64 image descriptor."""
    manifests = index.get("manifests")
    if not isinstance(manifests, list) or not manifests:
        raise RegistryMetadataError("OCI-Index enthaelt keine Manifest-Deskriptoren.")

    matches: list[dict[str, Any]] = []
    for descriptor in manifests:
        if not isinstance(descriptor, dict):
            raise RegistryMetadataError("OCI-Index enthaelt einen ungueltigen Descriptor.")
        if descriptor.get("mediaType") not in IMAGE_MANIFEST_MEDIA_TYPES:
            raise RegistryMetadataError("OCI-Index enthaelt einen ungueltigen Manifest-Media-Type.")
        digest = descriptor.get("digest")
        if not isinstance(digest, str) or not IMAGE_DIGEST_PATTERN.fullmatch(digest):
            raise RegistryMetadataError("OCI-Index enthaelt einen ungueltigen Manifest-Digest.")

        platform = descriptor.get("platform")
        if not isinstance(platform, dict):
            raise RegistryMetadataError("OCI-Index enthaelt keine valide Platform-Angabe.")
        os_name = platform.get("os")
        architecture = platform.get("architecture")
        variant = platform.get("variant")
        variant_present = "variant" in platform
        if (
            not isinstance(os_name, str)
            or not os_name
            or not isinstance(architecture, str)
            or not architecture
            or (variant_present and (not isinstance(variant, str) or not variant))
        ):
            raise RegistryMetadataError("OCI-Index enthaelt keine valide Platform-Angabe.")
        if os_name == "linux" and architecture == "amd64":
            if variant not in {None, "v1"}:
                raise RegistryMetadataError("OCI-Index enthaelt eine nicht unterstuetzte amd64-Variante.")
            matches.append(descriptor)

    if not matches:
        raise RegistryMetadataError("OCI-Index enthaelt kein eindeutiges linux/amd64-Manifest.")
    if len(matches) != 1:
        raise RegistryMetadataError("OCI-Index enthaelt mehrere linux/amd64-Manifeste.")
    return matches[0]


def fetch_image_metadata(image: str) -> dict[str, Any]:
    """Read OCI labels and digest metadata for an image from its registry."""
    registry, repository, reference = parse_image_reference(image)
    manifest_url = f"https://{registry}/v2/{repository}/manifests/{reference}"
    raw_manifest, headers = registry_request(manifest_url, accept=MANIFEST_ACCEPT)
    installation_digest = manifest_digest(raw_manifest, headers)
    if reference.startswith("sha256:") and installation_digest != reference:
        raise RegistryMetadataError("Angefordertes Image stimmt nicht mit dem Manifest ueberein.")
    manifest = json.loads(raw_manifest)
    media_type = manifest.get("mediaType") or registry_header(headers, "Content-Type") or ""
    if "image.index" in media_type or "manifest.list" in media_type:
        descriptor = choose_manifest_descriptor(manifest)
        child_digest = descriptor.get("digest")
        if not isinstance(child_digest, str) or not IMAGE_DIGEST_PATTERN.fullmatch(child_digest):
            raise RegistryMetadataError("OCI-Index enthaelt keinen validen Child-Digest.")
        raw_manifest, child_headers = registry_request(
            f"https://{registry}/v2/{repository}/manifests/{child_digest}",
            accept=MANIFEST_ACCEPT,
        )
        if manifest_digest(raw_manifest, child_headers) != child_digest:
            raise RegistryMetadataError("OCI-Index und Child-Manifest stimmen nicht ueberein.")
        manifest = json.loads(raw_manifest)
    config = manifest.get("config", {})
    config_digest = config.get("digest") if isinstance(config, dict) else None
    if not isinstance(config_digest, str) or not config_digest:
        raise RuntimeError("OCI-Manifest enthaelt keinen Config-Digest.")
    raw_config, _headers = registry_request(
        f"https://{registry}/v2/{repository}/blobs/{config_digest}",
        accept="application/vnd.oci.image.config.v1+json, application/vnd.docker.container.image.v1+json",
        allow_blob_redirect=True,
        expected_blob_digest=config_digest,
    )
    if "sha256:" + hashlib.sha256(raw_config).hexdigest() != config_digest:
        raise RegistryMetadataError("Registry-Config-Digest stimmt nicht mit den Bytes ueberein.")
    config_payload = json.loads(raw_config)
    labels = config_payload.get("config", {}).get("Labels", {})
    if not isinstance(labels, dict):
        labels = {}
    return image_metadata(
        {
            "id": installation_digest,
            "image": image,
            "labels": labels,
        }
    )


def _next_tags_page(headers: dict[str, str], *, registry: str, repository: str) -> str | None:
    """Return a validated same-repository next-page URL from an OCI Link header."""
    link = registry_header(headers, "Link")
    if not link:
        return None
    matches = re.findall(r'<([^>]+)>\s*;\s*rel="?next"?', link)
    if len(matches) != 1:
        raise RegistryMetadataError("Registry-Tag-Pagination ist ungueltig.")
    candidate = matches[0]
    validate_registry_url(candidate, expected_authority=registry)
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.path != f"/v2/{repository}/tags/list" or parsed.fragment:
        raise RegistryMetadataError("Registry-Tag-Pagination verlaesst das Repository.")
    query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
    if set(query) - {"n", "last"} or any(len(values) != 1 for values in query.values()):
        raise RegistryMetadataError("Registry-Tag-Pagination ist ungueltig.")
    if query.get("n") != ["100"]:
        raise RegistryMetadataError("Registry-Tag-Pagination hat eine ungueltige Seitengroesse.")
    last = query.get("last", [""])[0]
    if last and not IMAGE_TAG_PATTERN.fullmatch(last):
        raise RegistryMetadataError("Registry-Tag-Pagination enthaelt einen ungueltigen Cursor.")
    return candidate


def list_registry_tags(image: str) -> list[str]:
    """List validated tags for the configured image repository within response bounds."""
    registry, repository, _reference = parse_image_reference(image)
    next_url: str | None = f"https://{registry}/v2/{repository}/tags/list?n=100"
    seen_urls: set[str] = set()
    validated: list[str] = []
    while next_url is not None:
        if next_url in seen_urls or len(seen_urls) >= 100:
            raise RegistryMetadataError("Registry-Tag-Pagination konvergiert nicht.")
        seen_urls.add(next_url)
        raw, headers = registry_request(next_url, accept="application/json")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RegistryMetadataError("Registry-Tagliste ist ungueltig.") from error
        tags = payload.get("tags") if isinstance(payload, dict) else None
        if tags is None:
            tags = []
        if not isinstance(tags, list) or len(tags) > 100:
            raise RegistryMetadataError("Registry-Tagliste ist zu gross oder ungueltig.")
        for tag in tags:
            if not isinstance(tag, str) or not IMAGE_TAG_PATTERN.fullmatch(tag):
                raise RegistryMetadataError("Registry-Tagliste enthaelt einen ungueltigen Tag.")
            if tag not in validated:
                validated.append(tag)
        next_url = _next_tags_page(headers, registry=registry, repository=repository)
    return validated


def channel_for_tag(tag: str) -> str | None:
    """Return the trusted release channel encoded by one repository tag."""
    if tag == "prod" or re.fullmatch(r"prod-[0-9a-f]{40}", tag):
        return "prod"
    if tag == "latest" or re.fullmatch(r"staging-[0-9a-f]{40}", tag):
        return "staging"
    if tag == "dev" or re.fullmatch(r"dev-[1-9][0-9]*-[0-9a-f]{40}", tag):
        return "dev"
    return None


def build_version_catalog(image: str, *, environment: str = UPDATE_ENVIRONMENT) -> list[dict[str, Any]]:
    """Return at most twenty digest-verified image versions per allowed channel."""
    allowed = environment_channels(environment)
    registry, repository, _reference = parse_image_reference(image)
    by_digest: dict[str, dict[str, Any]] = {}
    for tag in list_registry_tags(image):
        channel = channel_for_tag(tag)
        if channel not in allowed:
            continue
        metadata = fetch_image_metadata(f"{registry}/{repository}:{tag}")
        digest = metadata.get("id")
        if not isinstance(digest, str) or not IMAGE_DIGEST_PATTERN.fullmatch(digest):
            raise RegistryMetadataError("Katalog-Image enthaelt keinen validen Digest.")
        entry = by_digest.setdefault(
            digest,
            {
                **metadata,
                "catalog_id": digest,
                "image": f"{registry}/{repository}@{digest}",
                "channels": [],
            },
        )
        if channel not in entry["channels"]:
            entry["channels"].append(channel)
    channel_order = {channel: index for index, channel in enumerate(ENVIRONMENT_CHANNELS["dev"])}
    versions = sorted(
        by_digest.values(),
        key=lambda entry: (str(entry.get("build_date", "")), str(entry.get("version", ""))),
        reverse=True,
    )
    keep: set[str] = set()
    for channel in allowed:
        matching = [entry for entry in versions if channel in entry["channels"]][:20]
        keep.update(str(entry["catalog_id"]) for entry in matching)
    result = [entry for entry in versions if entry["catalog_id"] in keep]
    for entry in result:
        entry["channels"].sort(key=channel_order.__getitem__)
    return result


def _atomic_json_write(path: Path, payload: Any) -> None:
    """Write one JSON cache file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _catalog_cache_path() -> Path:
    return STATE_FILE.with_name("version-catalog.json")


def _metadata_cache_path(digest: str) -> Path:
    return STATE_FILE.with_name("version-metadata") / f"{digest.removeprefix('sha256:')}.json"


def _version_summary(entry: dict[str, Any]) -> dict[str, Any]:
    """Return presentation metadata without large changelog or migration bodies."""
    return {
        key: entry[key]
        for key in ("catalog_id", "image", "id", "version", "revision", "build_date", "change", "channels")
        if key in entry
    }


def _valid_cached_catalog(versions: Any, *, registry: str, repository: str) -> bool:
    """Return whether cached summaries still satisfy the environment and digest contract."""
    if not isinstance(versions, list) or len(versions) > 60:
        return False
    allowed_channels = set(environment_channels(UPDATE_ENVIRONMENT))
    seen: set[str] = set()
    for entry in versions:
        if not isinstance(entry, dict):
            return False
        digest = entry.get("id")
        catalog_id = entry.get("catalog_id")
        image = entry.get("image")
        channels = entry.get("channels")
        if (
            not isinstance(digest, str)
            or not IMAGE_DIGEST_PATTERN.fullmatch(digest)
            or catalog_id != digest
            or digest in seen
            or not isinstance(image, str)
            or not isinstance(channels, list)
            or not channels
            or len(channels) > 3
            or any(not isinstance(channel, str) or channel not in allowed_channels for channel in channels)
        ):
            return False
        try:
            cached_registry, cached_repository, cached_digest = parse_image_reference(image)
        except RuntimeError:
            return False
        if (cached_registry, cached_repository, cached_digest) != (registry, repository, digest):
            return False
        seen.add(digest)
    return True


def _cache_metadata(entry: dict[str, Any]) -> None:
    digest = entry.get("id")
    if not isinstance(digest, str) or not IMAGE_DIGEST_PATTERN.fullmatch(digest):
        raise RegistryMetadataError("Versionsmetadaten enthalten keinen validen Digest.")
    _atomic_json_write(_metadata_cache_path(digest), entry)
    cache_directory = _metadata_cache_path(digest).parent
    cached = sorted(cache_directory.glob("*.json"), key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)
    for stale in cached[60:]:
        stale.unlink(missing_ok=True)


def cached_version_catalog(image: str, *, force: bool = False) -> list[dict[str, Any]]:
    """Load the small five-minute catalog cache or refresh it from the registry."""
    registry, repository, _reference = parse_image_reference(image)
    repository_name = f"{registry}/{repository}"
    cache_path = _catalog_cache_path()
    if not force:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            age = time.time() - float(cached["fetched_at"])
            versions = cached["versions"]
            if (
                cached.get("repository") == repository_name
                and cached.get("environment") == UPDATE_ENVIRONMENT
                and 0 <= age < 300
                and _valid_cached_catalog(versions, registry=registry, repository=repository)
            ):
                return versions
        except FileNotFoundError:
            logger.debug("Versionskatalog-Cache fehlt; Registry wird abgefragt.")
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            logger.warning(
                "Versionskatalog-Cache ist unbrauchbar (%s); Registry wird abgefragt.",
                type(error).__name__,
            )
    full_versions = build_version_catalog(image)
    for entry in full_versions:
        _cache_metadata(entry)
    summaries = [_version_summary(entry) for entry in full_versions]
    _atomic_json_write(
        cache_path,
        {
            "fetched_at": time.time(),
            "repository": repository_name,
            "environment": UPDATE_ENVIRONMENT,
            "versions": summaries,
        },
    )
    return summaries


def version_metadata(entry: dict[str, Any]) -> dict[str, Any]:
    """Load digest-bound detail metadata from cache, refetching only that digest on miss."""
    digest = entry.get("id")
    image = entry.get("image")
    if not isinstance(digest, str) or not IMAGE_DIGEST_PATTERN.fullmatch(digest) or not isinstance(image, str):
        raise RegistryMetadataError("Katalogeintrag ist ungueltig.")
    try:
        cached = json.loads(_metadata_cache_path(digest).read_text(encoding="utf-8"))
        if isinstance(cached, dict) and cached.get("id") == digest and cached.get("image") == image:
            return cached
    except FileNotFoundError:
        logger.debug("Versionsdetail-Cache fehlt; Registry wird abgefragt.")
    except (OSError, json.JSONDecodeError) as error:
        logger.warning(
            "Versionsdetail-Cache ist unbrauchbar (%s); Registry wird abgefragt.",
            type(error).__name__,
        )
    metadata = fetch_image_metadata(image)
    if metadata.get("id") != digest:
        raise RegistryMetadataError("Katalog und Versionsmetadaten widersprechen sich.")
    metadata.update(catalog_id=digest, channels=list(entry.get("channels", [])), image=image)
    _cache_metadata(metadata)
    return metadata


def selected_catalog_entry(versions: list[dict[str, Any]], selected: Any = "") -> dict[str, Any]:
    """Resolve only a digest that belongs to the current environment-limited catalog."""
    if selected:
        if not isinstance(selected, str) or not IMAGE_DIGEST_PATTERN.fullmatch(selected):
            raise AgentRequestError(HTTPStatus.BAD_REQUEST, "invalid_catalog_selection")
        match = next((entry for entry in versions if entry.get("catalog_id") == selected), None)
        if match is None:
            raise AgentRequestError(HTTPStatus.CONFLICT, "catalog_selection_not_allowed")
        return match
    own_channel = UPDATE_ENVIRONMENT
    match = next((entry for entry in versions if own_channel in entry.get("channels", [])), None)
    if match is None:
        raise AgentRequestError(HTTPStatus.CONFLICT, "no_environment_release")
    return match


def deployment_versions(selected: Any = "") -> dict[str, Any]:
    """Return the allowed catalog and selected digest-bound details for the admin UI."""
    client = PortainerClient()
    stack = client.get_stack()
    running_image = stack_app_image(stack)
    versions = cached_version_catalog(running_image)
    selected_summary = selected_catalog_entry(versions, selected)
    selected_details = version_metadata(selected_summary)
    running_digest_image = immutable_running_image(client, running_image)
    _running_repository, running_digest = validate_immutable_image_reference(running_digest_image)
    running_metadata = version_metadata({"id": running_digest, "image": running_digest_image, "channels": []})
    compatibility = migration_compatibility(running_metadata.get("migrations"), selected_details.get("migrations"))
    selected_details = {**selected_details, "compatibility": compatibility}
    return {
        "environment": UPDATE_ENVIRONMENT,
        "allowed_channels": list(environment_channels()),
        "versions": versions,
        "selected": selected_details,
    }


def normalized_changelog_entries(raw_changelog: Any) -> list[dict[str, str]]:
    """Return UI-safe changelog entries from an OCI label value."""
    if isinstance(raw_changelog, str):
        try:
            raw_changelog = json.loads(raw_changelog)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw_changelog, list):
        return []

    entries = []
    for item in raw_changelog:
        if not isinstance(item, dict):
            continue
        revision = str(item.get("revision", "")).strip()
        version = str(item.get("version", "")).strip()
        title = str(item.get("title", "")).strip()
        body = str(item.get("body", "")).strip()
        path = str(item.get("path", "")).strip()
        if not revision or not title:
            continue
        entry = {"revision": revision, "title": title, "body": body, "path": path}
        if version:
            entry["version"] = version
        entries.append(entry)
    return entries


def normalized_migration_manifest(raw_manifest: Any) -> dict[str, Any]:
    """Return a bounded migration manifest from a digest-verified image label."""
    if isinstance(raw_manifest, str):
        try:
            raw_manifest = json.loads(raw_manifest)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw_manifest, dict):
        return {}
    raw_files = raw_manifest.get("files")
    if not isinstance(raw_files, list) or len(raw_files) > 256:
        return {}
    files: list[dict[str, str]] = []
    for item in raw_files:
        if not isinstance(item, dict):
            return {}
        path = item.get("path")
        digest = item.get("sha256")
        if (
            not isinstance(path, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]*/migrations/[0-9]{4}_[a-z0-9_]+\.py", path)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            return {}
        files.append({"path": path, "sha256": digest})
    if len({item["path"] for item in files}) != len(files):
        return {}
    raw_migrations = raw_manifest.get("migrations")
    if not isinstance(raw_migrations, list) or len(raw_migrations) != len(files):
        return {}
    file_digests = {f"{Path(item['path']).parts[0]}.{Path(item['path']).stem}": item["sha256"] for item in files}
    migrations: list[dict[str, Any]] = []
    for item in raw_migrations:
        if not isinstance(item, dict):
            return {}
        identifier = item.get("identifier")
        dependencies = item.get("dependencies")
        reversible = item.get("reversible")
        digest = item.get("sha256")
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]*\.[0-9]{4}_[a-z0-9_]+", identifier)
            or identifier not in file_digests
            or digest != file_digests[identifier]
            or not isinstance(dependencies, list)
            or len(dependencies) > 64
            or not all(
                isinstance(dependency, str)
                and re.fullmatch(r"[a-z][a-z0-9_]*\.(?:[0-9]{4}_[a-z0-9_]+|__first__)", dependency)
                for dependency in dependencies
            )
            or not isinstance(reversible, bool)
        ):
            return {}
        migrations.append(
            {
                "identifier": identifier,
                "dependencies": sorted(set(dependencies)),
                "reversible": reversible,
                "sha256": digest,
            }
        )
    if len({item["identifier"] for item in migrations}) != len(migrations):
        return {}
    return {
        "files": sorted(files, key=lambda item: item["path"]),
        "migrations": sorted(migrations, key=lambda item: item["identifier"]),
    }


def _migration_graph_extends(base: dict[str, dict[str, Any]], extended: dict[str, dict[str, Any]]) -> bool:
    """Return whether every added node descends from a leaf of the base graph."""
    if not base.keys() <= extended.keys():
        return False
    if not base:
        return True
    depended_on = {
        dependency for migration in base.values() for dependency in migration["dependencies"] if dependency in base
    }
    reachable = set(base) - depended_on
    remaining = set(extended) - set(base)
    while remaining:
        connected = {
            identifier
            for identifier in remaining
            if any(dependency in reachable for dependency in extended[identifier]["dependencies"])
        }
        if not connected:
            return False
        reachable.update(connected)
        remaining -= connected
    return True


def migration_compatibility(current: Any, target: Any) -> dict[str, Any]:
    """Classify migration ancestry conservatively without promising compatibility."""
    current_manifest = normalized_migration_manifest(current)
    target_manifest = normalized_migration_manifest(target)
    if not current_manifest or not target_manifest:
        return {"risk": "unknown", "requires_acknowledgement": True, "affected_migrations": []}
    current_migrations = {item["identifier"]: item for item in current_manifest["migrations"]}
    target_migrations = {item["identifier"]: item for item in target_manifest["migrations"]}
    changed = sorted(
        identifier
        for identifier in current_migrations.keys() & target_migrations.keys()
        if current_migrations[identifier] != target_migrations[identifier]
    )
    if changed:
        risk = "divergent"
        affected = changed
    elif current_migrations == target_migrations:
        risk = "identical"
        affected = []
    elif _migration_graph_extends(current_migrations, target_migrations):
        risk = "forward"
        affected = sorted(target_migrations.keys() - current_migrations.keys())
    elif _migration_graph_extends(target_migrations, current_migrations):
        risk = "downgrade"
        affected = sorted(current_migrations.keys() - target_migrations.keys())
    else:
        risk = "divergent"
        affected = sorted(current_migrations.keys() ^ target_migrations.keys())
    return {
        "risk": risk,
        "requires_acknowledgement": risk not in {"identical", "forward"},
        "affected_migrations": affected[:20],
    }


def ensure_risk_acknowledged(state: dict[str, Any], acknowledged: Any) -> None:
    """Reject installation of a risky one-time candidate without explicit consent."""
    if state.get("risk_requires_acknowledgement") is True and acknowledged is not True:
        raise AgentRequestError(HTTPStatus.CONFLICT, "risk_acknowledgement_required")


def image_metadata(image: Any) -> dict[str, Any]:
    """Normalize OCI image metadata from Docker-like objects or dict payloads."""
    if isinstance(image, dict):
        labels = image.get("labels") or {}
        image_id = str(image.get("id", "unknown"))
        image_ref = str(image.get("image", "unknown"))
    else:
        labels = image.labels or {}
        image_id = str(image.id)
        image_ref = "unknown"
    return {
        "id": image_id,
        "image": image_ref,
        "version": str(labels.get(OCI_LABELS["version"], "unknown")),
        "revision": str(labels.get(OCI_LABELS["revision"], "unknown")),
        "build_date": str(labels.get(OCI_LABELS["build_date"], "unknown")),
        "change": str(labels.get(OCI_LABELS["change"], "Unbekannter Change")),
        "changelog": normalized_changelog_entries(labels.get(OCI_LABELS["changelog"], "[]")),
        "migrations": normalized_migration_manifest(labels.get(OCI_LABELS["migrations"], "{}")),
    }


def current_metadata_from_payload(payload: dict[str, Any] | None) -> dict[str, str]:
    """Normalize current build metadata supplied by Django."""
    current = payload.get("current") if payload else None
    if not isinstance(current, dict):
        return {}
    return {key: str(value) for key, value in current.items() if value is not None}


def has_update(latest: dict[str, Any], current: dict[str, str], current_image: str) -> bool:
    """Authorize only monotonic numeric releases or changed equal-release identities."""
    current_version = current.get("version", "")
    latest_version = str(latest.get("version", ""))
    if not re.fullmatch(r"[0-9]+", current_version) or not re.fullmatch(r"[0-9]+", latest_version):
        return False

    current_build = int(current_version)
    latest_build = int(latest_version)
    if latest_build != current_build:
        return latest_build > current_build

    current_revision = current.get("revision", "")
    latest_revision = str(latest.get("revision", ""))
    if (
        current_revision
        and latest_revision
        and current_revision != "unknown"
        and latest_revision != "unknown"
        and current_revision != latest_revision
    ):
        return True

    _registry, _repository, current_reference = parse_image_reference(current_image)
    latest_digest = latest.get("id")
    return (
        isinstance(latest_digest, str)
        and IMAGE_DIGEST_PATTERN.fullmatch(latest_digest) is not None
        and IMAGE_DIGEST_PATTERN.fullmatch(current_reference) is not None
        and latest_digest != current_reference
    )


def changelog_between_versions(latest: dict[str, Any], current: dict[str, str]) -> list[dict[str, str]]:
    """Return changelog entries after the current build up to the latest build."""
    entries = normalized_changelog_entries(latest.get("changelog", []))
    if not entries:
        return []

    current_version_text = current.get("version", "")
    latest_version_text = str(latest.get("version", ""))
    if current_version_text.isdecimal() and latest_version_text.isdecimal():
        current_version = int(current_version_text)
        latest_version = int(latest_version_text)
        return [
            entry
            for entry in entries
            if entry.get("version", "").isdecimal() and current_version < int(entry["version"]) <= latest_version
        ]

    current_revision = current.get("revision") or current.get("version") or ""
    latest_revision = str(latest.get("revision") or latest.get("version") or "")
    start_index = -1
    end_index = len(entries) - 1

    for index, entry in enumerate(entries):
        if current_revision and entry["revision"] == current_revision:
            start_index = index
        if latest_revision and entry["revision"] == latest_revision:
            end_index = index

    if current_revision and start_index == -1:
        return []
    if start_index >= end_index:
        return []
    return entries[start_index + 1 : end_index + 1]


def deployment_status() -> dict[str, Any]:
    """Return persisted update state and the configured Portainer stack image."""
    stack = PortainerClient().get_stack()
    running_image = stack_app_image(stack)
    result = load_state()
    result["running"] = {"image": running_image}
    result["environment"] = UPDATE_ENVIRONMENT
    result.setdefault("update_available", False)
    return result


def check_update(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bind one environment-allowed registry image to the running stack digest."""
    if not update_lock.acquire(blocking=False):
        raise AgentRequestError(HTTPStatus.CONFLICT, "update_in_progress")
    try:
        ensure_update_mutations_allowed()
        client = PortainerClient()
        stack = client.get_stack()
        running_image = stack_app_image(stack)
        validate_active_stack_contract(client, stack)
        running_digest_image = immutable_running_image(client, running_image)
        _running_repository, running_digest = validate_immutable_image_reference(running_digest_image)
        requested_catalog_id = payload.get("catalog_id", "") if isinstance(payload, dict) else ""
        if requested_catalog_id:
            versions = cached_version_catalog(running_image, force=True)
            selected = selected_catalog_entry(versions, requested_catalog_id)
            latest = version_metadata(selected)
            discovery_image = str(latest["image"])
        else:
            discovery_image = environment_image_reference(running_image)
            latest = fetch_image_metadata(discovery_image)
        approved_image = immutable_image_reference(str(latest.get("image") or discovery_image), latest.get("id"))
        approved_digest = str(latest["id"])
        current = current_metadata_from_payload(payload)
        update_available = approved_digest != running_digest
        if latest.get("migrations"):
            running_metadata = fetch_image_metadata(running_digest_image)
            compatibility = migration_compatibility(running_metadata.get("migrations"), latest.get("migrations"))
        else:
            compatibility = migration_compatibility({}, {})
        candidate_id = secrets.token_urlsafe(32) if update_available else ""
        target_metadata = {key: latest[key] for key in ("version", "revision", "build_date", "change") if key in latest}
        return save_state(
            phase="checked",
            message="Image-Pruefung abgeschlossen.",
            error="",
            rollback_error="",
            recovery="",
            target_metadata=target_metadata,
            approved_image=approved_image,
            approved_digest=approved_digest,
            selected_catalog_id=requested_catalog_id or approved_digest,
            candidate_environment=UPDATE_ENVIRONMENT,
            compatibility=compatibility,
            risk_requires_acknowledgement=compatibility["requires_acknowledgement"],
            candidate_id=candidate_id,
            candidate_digest=approved_digest if update_available else "",
            candidate_base_digest=running_digest,
            candidate_contract=CANDIDATE_CONTRACT_VERSION,
            running={"image": running_image, **current},
            update_available=update_available,
            checked_at=utc_now(),
        )
    finally:
        update_lock.release()


def checked_install_candidate(candidate_id: Any) -> tuple[str, dict[str, Any]]:
    """Return checked state only when the opaque install candidate matches exactly."""
    state = load_state()
    expected_candidate_id = state.get("candidate_id")
    if (
        state.get("phase") != "checked"
        or state.get("update_available") is not True
        or state.get("candidate_contract") != CANDIDATE_CONTRACT_VERSION
        or not isinstance(candidate_id, str)
        or not CANDIDATE_ID_PATTERN.fullmatch(candidate_id)
        or not isinstance(expected_candidate_id, str)
        or not CANDIDATE_ID_PATTERN.fullmatch(expected_candidate_id)
        or not hmac.compare_digest(candidate_id, expected_candidate_id)
    ):
        raise AgentRequestError(HTTPStatus.CONFLICT, "candidate_mismatch")

    try:
        _approved_image, approved_digest = validate_immutable_image_reference(state.get("approved_image"))
    except RuntimeError as error:
        raise AgentRequestError(HTTPStatus.CONFLICT, "candidate_mismatch") from error
    if state.get("approved_digest") != approved_digest or state.get("candidate_digest") != approved_digest:
        raise AgentRequestError(HTTPStatus.CONFLICT, "candidate_mismatch")
    if state.get("candidate_environment", UPDATE_ENVIRONMENT) != UPDATE_ENVIRONMENT:
        raise AgentRequestError(HTTPStatus.CONFLICT, "candidate_mismatch")
    candidate_base_digest = state.get("candidate_base_digest")
    if not isinstance(candidate_base_digest, str) or not IMAGE_DIGEST_PATTERN.fullmatch(candidate_base_digest):
        raise AgentRequestError(HTTPStatus.CONFLICT, "candidate_mismatch")
    latest = state.get("latest")
    if latest is not None and (not isinstance(latest, dict) or latest.get("id") != approved_digest):
        raise AgentRequestError(HTTPStatus.CONFLICT, "candidate_mismatch")
    return candidate_id, state


def invalidate_install_candidate(public_code: str) -> None:
    """Invalidate a checked candidate while retaining an actionable status reason."""
    save_state(
        phase="checked",
        message="Der laufende Image-Zustand hat sich geändert. Bitte erneut prüfen.",
        error="stale_runtime_base",
        candidate_id="",
        candidate_digest="",
        candidate_base_digest="",
        update_available=False,
        candidate_invalidated_reason=public_code,
    )


def validate_candidate_runtime_base(client: PortainerClient, stack: dict[str, Any], state: dict[str, Any]) -> None:
    """Reject a candidate when the immutable running image changed after checking."""
    expected_digest = state.get("candidate_base_digest")
    if not isinstance(expected_digest, str) or not IMAGE_DIGEST_PATTERN.fullmatch(expected_digest):
        raise RuntimeError("Der geprüfte Runtime-Basisdigest fehlt oder ist ungültig.")
    running_image = stack_app_image(stack)
    runtime_image = immutable_running_image(client, running_image)
    _runtime_repository, runtime_digest = validate_immutable_image_reference(runtime_image)
    if runtime_digest != expected_digest:
        raise RuntimeError("Der laufende Runtime-Basisdigest hat sich seit der Prüfung geändert.")


def consume_install_candidate(candidate_id: Any) -> dict[str, Any]:
    """Atomically invalidate one checked candidate before background installation starts."""
    confirmed_candidate_id, checked_state = checked_install_candidate(candidate_id)
    operation_started_at = utc_now()
    operation_id = secrets.token_urlsafe(24)
    candidate_identity = hashlib.sha256(confirmed_candidate_id.encode("utf-8")).hexdigest()
    save_state(
        phase="installing",
        message="Update wird vorbereitet.",
        error="",
        rollback_error="",
        recovery="",
        candidate_id="",
        candidate_digest="",
        candidate_base_digest="",
        update_available=False,
        candidate_consumed_at=operation_started_at,
        operation_started_at=operation_started_at,
        operation_id=operation_id,
        candidate_identity=candidate_identity,
    )
    return {
        **checked_state,
        "operation_started_at": operation_started_at,
        "operation_id": operation_id,
        "candidate_identity": candidate_identity,
    }


def ensure_update_mutations_allowed() -> None:
    """Block new checks and installs while persisted recovery needs resolution."""
    if load_state().get("phase") in {"installing", "rollback", "recovery_required"}:
        raise AgentRequestError(HTTPStatus.CONFLICT, "update_recovery_required")


def parse_database_url(database_url: str) -> dict[str, str]:
    """Parse DATABASE_URL into pg_dump connection arguments without leaking passwords."""
    value = require_env("DATABASE_URL", database_url)
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise AgentConfigError("DATABASE_URL muss eine PostgreSQL-URL sein.")
    if not parsed.hostname or not parsed.username or not parsed.path.strip("/"):
        raise AgentConfigError("DATABASE_URL ist unvollstaendig.")
    return {
        "host": parsed.hostname,
        "port": str(parsed.port or 5432),
        "user": urllib.parse.unquote(parsed.username),
        "password": urllib.parse.unquote(parsed.password or ""),
        "database": urllib.parse.unquote(parsed.path.lstrip("/")),
    }


def database_dump_bytes() -> bytes:
    """Return a PostgreSQL dump without writing credentials to process arguments."""
    connection = parse_database_url(DATABASE_URL)
    command = [
        "pg_dump",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--host",
        connection["host"],
        "--port",
        connection["port"],
        "--username",
        connection["user"],
        connection["database"],
    ]
    environment = os.environ.copy()
    environment["PGPASSWORD"] = connection["password"]
    try:
        result = subprocess.run(command, env=environment, check=False, capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("Datenbank-Backup konnte nicht gestartet werden.") from error
    if result.returncode != 0:
        stderr = limit_output(result.stderr.decode("utf-8", errors="replace"))
        raise RuntimeError(f"Datenbank-Backup fehlgeschlagen: {stderr}")
    if not result.stdout:
        raise RuntimeError("Datenbank-Backup ist leer.")
    return result.stdout


def backup_timestamp() -> str:
    """Return the timestamp used in operator-visible backup names."""
    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}"


def open_exclusive_backup(category: BackupArtifactCategory) -> tuple[Path, Any]:
    """Create a private backup file without replacing an existing artifact."""
    if not isinstance(category, BackupArtifactCategory):
        raise RuntimeError("Backup-Kategorie ist ungültig.")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_root = BACKUP_DIR.resolve()
    filename_prefix = f"{category.filename_prefix}-{backup_timestamp()}-{secrets.token_hex(8)}"
    # mkstemp creates the file directly in backup_root with O_EXCL and retries
    # generated-name collisions internally; the resolved directory is its boundary.
    descriptor, raw_path = tempfile.mkstemp(prefix=filename_prefix, suffix=category.suffix, dir=backup_root)
    backup_path = Path(raw_path)
    if backup_path.parent != backup_root:
        os.close(descriptor)
        raise RuntimeError("Backup-Datei muss ein direktes Kind des Backup-Verzeichnisses sein.")
    return backup_path, os.fdopen(descriptor, "wb")


def create_backup() -> str:
    """Create a gzipped PostgreSQL backup using DATABASE_URL connection details."""
    if not backup_lock.acquire(blocking=False):
        raise BackupInProgressError()
    backup_path: Path | None = None
    try:
        dump = database_dump_bytes()
        backup_path, raw_backup = open_exclusive_backup(BackupArtifactCategory.BEFORE_UPDATE)
        try:
            with raw_backup:
                with gzip.GzipFile(fileobj=raw_backup, mode="wb") as backup:
                    backup.write(dump)
            if backup_path.stat().st_size == 0:
                raise RuntimeError("Datenbank-Backup ist leer.")
        except BaseException:
            backup_path.unlink(missing_ok=True)
            raise
        return backup_path.name
    finally:
        backup_lock.release()


def backup_child_path(relative_path: str) -> Path:
    """Resolve a backup child path and reject traversal outside BACKUP_DIR."""
    if not BACKUP_STAGING_PATTERN.fullmatch(relative_path):
        raise RuntimeError("Backup-Pfad ist ungültig.")
    backup_root = BACKUP_DIR.resolve()
    staging_name = relative_path.removeprefix("staging/")
    candidate = backup_root / "staging" / staging_name
    if backup_root != candidate and backup_root not in candidate.parents:
        raise RuntimeError("Backup-Pfad verlässt das Backup-Verzeichnis.")
    return candidate


def safe_archive_prefix(value: str) -> str:
    """Normalize a user supplied archive prefix to a filename-safe value."""
    if not BACKUP_ARCHIVE_PREFIX_PATTERN.fullmatch(value):
        raise RuntimeError("Backup-Archivname ist ungültig.")
    return value


def safe_staging_file(path: Path, staging_path: Path) -> Path:
    """Resolve a staged export file and reject anything outside the staging directory."""
    resolved_path = path.resolve()
    resolved_staging = staging_path.resolve()
    if resolved_staging not in resolved_path.parents:
        raise RuntimeError("Backup-Staging-Datei verlässt das Staging-Verzeichnis.")
    return resolved_path


def _create_backup_archive(staging_dir: str, archive_prefix: str) -> str:
    """Create a tar.gz archive containing pg_dump output and prepared export files."""
    staging_path = backup_child_path(staging_dir)
    if not staging_path.is_dir():
        raise RuntimeError("Backup-Staging-Verzeichnis wurde nicht gefunden.")

    dump = database_dump_bytes()
    safe_archive_prefix(archive_prefix)
    archive_path, raw_archive = open_exclusive_backup(BackupArtifactCategory.ARCHIVE)
    try:
        with raw_archive:
            with tarfile.open(fileobj=raw_archive, mode="w:gz") as archive:
                dump_info = tarfile.TarInfo("database.sql")
                dump_info.size = len(dump)
                dump_info.mtime = int(time.time())
                archive.addfile(dump_info, io.BytesIO(dump))
                for path in sorted(staging_path.rglob("*")):
                    export_path = safe_staging_file(path, staging_path)
                    if export_path.is_file():
                        archive.add(export_path, arcname=f"exports/{export_path.relative_to(staging_path).as_posix()}")
        return archive_path.name
    except BaseException:
        archive_path.unlink(missing_ok=True)
        raise


def create_backup_archive(staging_dir: str, archive_prefix: str) -> str:
    """Create one serialized tar.gz archive with pg_dump output and export files."""
    if not backup_lock.acquire(blocking=False):
        raise BackupInProgressError()
    try:
        return _create_backup_archive(staging_dir, archive_prefix)
    finally:
        backup_lock.release()


def redeploy_stack(image: str) -> None:
    """Set APP_IMAGE in Portainer and trigger a stack redeploy."""
    PortainerClient().update_stack_image(image)


def wait_until_healthy() -> None:
    """Poll the configured application health endpoint until it returns 2xx."""
    deadline = time.monotonic() + HEALTH_TIMEOUT
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(APP_HEALTH_URL, timeout=5) as response:
                if 200 <= response.status < 300:
                    return
        except (OSError, TimeoutError) as error:
            logger.info("Warte auf App-Healthcheck: %s", error)
        time.sleep(3)
    raise RuntimeError("Die Anwendung wurde nicht rechtzeitig healthy.")


def application_is_healthy() -> bool:
    """Return whether the application health endpoint currently reports success."""
    try:
        with urllib.request.urlopen(APP_HEALTH_URL, timeout=5) as response:
            return 200 <= response.status < 300
    except (OSError, TimeoutError):
        return False


def wait_for_portainer_startup(
    client: PortainerClient,
    *,
    timeout_seconds: float = PORTAINER_STARTUP_TIMEOUT_SECONDS,
    initial_backoff_seconds: float = PORTAINER_STARTUP_INITIAL_BACKOFF_SECONDS,
    max_backoff_seconds: float = PORTAINER_STARTUP_MAX_BACKOFF_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Wait a bounded time for transient Portainer startup errors before serving requests."""
    deadline = clock() + timeout_seconds
    backoff_seconds = initial_backoff_seconds
    while True:
        try:
            client.get_stack()
            return
        except PortainerTransientError:
            remaining_seconds = deadline - clock()
            if remaining_seconds <= 0:
                raise
            sleep(min(backoff_seconds, remaining_seconds))
            backoff_seconds = min(backoff_seconds * 2, max_backoff_seconds)


def wait_for_recovery_runtime(
    client: PortainerClient,
    target_image: str,
    rollback_image: str,
    *,
    timeout_seconds: float | None = None,
    initial_backoff_seconds: float | None = None,
    max_backoff_seconds: float | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
    inspect_runtime: Callable[[PortainerClient, str], str] | None = None,
    check_health: Callable[[], bool] | None = None,
) -> tuple[str, bool]:
    """Wait a bounded time for an interrupted deployment runtime to converge."""
    timeout = timeout_seconds if timeout_seconds is not None else RECOVERY_CONVERGENCE_TIMEOUT_SECONDS
    initial_backoff = (
        initial_backoff_seconds if initial_backoff_seconds is not None else RECOVERY_CONVERGENCE_INITIAL_BACKOFF_SECONDS
    )
    max_backoff = max_backoff_seconds if max_backoff_seconds is not None else RECOVERY_CONVERGENCE_MAX_BACKOFF_SECONDS
    monotonic_clock = clock or time.monotonic
    sleeper = sleep or time.sleep
    runtime_inspector = inspect_runtime or immutable_running_image
    health_checker = check_health or application_is_healthy
    deadline = monotonic_clock() + timeout
    backoff = initial_backoff
    while True:
        try:
            running_image = runtime_inspector(client, target_image)
        except (PortainerAPIError, OSError, RuntimeError) as inspection_error:
            logger.info("Warte auf konvergierenden App-Runtime-Digest: %s", inspection_error)
            running_image = ""
        if running_image in {target_image, rollback_image}:
            if health_checker():
                return running_image, True
        elif running_image:
            return running_image, False
        remaining_seconds = deadline - monotonic_clock()
        if remaining_seconds <= 0:
            return running_image, False
        sleeper(min(backoff, remaining_seconds))
        backoff = min(backoff * 2, max_backoff)


def _recovery_images(state: dict[str, Any]) -> tuple[str, str, str]:
    """Validate and return target image, target digest and rollback image."""
    if state.get("recovery_contract") != RECOVERY_CONTRACT_VERSION:
        raise RuntimeError("Recovery-Vertrag fehlt oder ist nicht kompatibel.")
    target_image, target_digest = validate_immutable_image_reference(state.get("target_image"))
    rollback_image, _rollback_digest = validate_immutable_image_reference(state.get("rollback_image"))
    if state.get("target_digest") != target_digest:
        raise RuntimeError("Recovery-Zieldigest ist widerspruechlich.")
    target_registry, target_repository, _target_reference = parse_image_reference(target_image)
    rollback_registry, rollback_repository, _rollback_reference = parse_image_reference(rollback_image)
    if (target_registry, target_repository) != (rollback_registry, rollback_repository):
        raise RuntimeError("Recovery-Images gehoeren nicht zum selben Repository.")
    for field in ("operation_id", "candidate_identity", "operation_started_at"):
        if not isinstance(state.get(field), str) or not state[field]:
            raise RuntimeError("Recovery-Identitaet ist unvollstaendig.")
    return target_image, target_digest, rollback_image


def _recovery_required(*, error: str, outcome: str = "invalid_state") -> dict[str, Any]:
    """Persist a terminal fail-closed recovery state."""
    return save_state(
        phase="recovery_required",
        message="Update-Recovery erfordert einen kontrollierten Eingriff.",
        error=error,
        recovery_outcome=outcome,
        candidate_id="",
        candidate_digest="",
        update_available=False,
    )


def reconcile_interrupted_update() -> dict[str, Any]:
    """Resolve one persisted interrupted update exactly once during agent startup."""
    state = load_state()
    if state.get("phase") not in {"installing", "rollback"}:
        return state
    try:
        target_image, target_digest, rollback_image = _recovery_images(state)
    except RuntimeError as error:
        logger.error("Update-Recoverydaten sind ungueltig: %s", error)
        return _recovery_required(error=f"Recovery nicht automatisch moeglich: {error}")

    client = PortainerClient()
    operation_id = state["operation_id"]
    try:
        running_image, healthy = wait_for_recovery_runtime(client, target_image, rollback_image)
        if running_image == target_image and healthy:
            raw_latest = state.get("latest")
            latest: dict[str, Any] = raw_latest if isinstance(raw_latest, dict) else {}
            logger.info("Update-Recovery abgeschlossen; Ziel laeuft, Operation %s", operation_id)
            return save_state(
                phase="complete",
                message="Update nach Neustart erfolgreich verifiziert.",
                error="",
                rollback_error="",
                recovery_outcome="target_verified",
                installed={**latest, "id": target_digest, "image": target_image},
                running={"image": running_image},
                candidate_id="",
                candidate_digest="",
                update_available=False,
                completed_at=utc_now(),
            )
        if target_image == rollback_image:
            logger.warning("Recovery-Ziel ist unbestaetigt und identisch mit Rollback, Operation %s", operation_id)
            return _recovery_required(
                error="Ziel- und Rollback-Image sind identisch, das Ziel ist aber nicht healthy verifiziert.",
                outcome="target_unverified",
            )
        if running_image == rollback_image and healthy:
            logger.info("Update-Recovery bestaetigt vorhandenen Rollback, Operation %s", operation_id)
            return save_state(
                phase="failed",
                message="Unterbrochenes Update wurde auf das vorherige Image zurueckgesetzt.",
                rollback_error="",
                recovery_outcome="rolled_back",
                running={"image": running_image},
                candidate_id="",
                candidate_digest="",
                update_available=False,
                completed_at=utc_now(),
            )

        # A rollback PUT is an externally visible mutation. Once its start was
        # persisted, its outcome is uncertain and must never be retried after
        # restart; fail closed until an operator resolves the runtime.
        if state.get("rollback_put_started_at"):
            logger.error("Rollback ist bereits gestartet; kein weiterer Rollback-PUT, Operation %s", operation_id)
            return _recovery_required(
                error="Rollback wurde bereits gestartet, sein Ergebnis ist aber nicht verifiziert.",
                outcome="rollback_failed",
            )

        save_state(
            phase="rollback",
            message="Unterbrochenes Update wird kontrolliert zurueckgesetzt.",
            recovery_contract=RECOVERY_CONTRACT_VERSION,
            operation_id=state["operation_id"],
            candidate_identity=state["candidate_identity"],
            operation_started_at=state["operation_started_at"],
            target_image=target_image,
            target_digest=target_digest,
            rollback_image=rollback_image,
            rollback_put_started_at=utc_now(),
            candidate_id="",
            candidate_digest="",
            update_available=False,
        )
        logger.warning("Update-Recovery startet Rollback, Operation %s", operation_id)
        client.update_stack_image(rollback_image)
        wait_until_healthy()
        verified_image = immutable_running_image(client, target_image)
        if verified_image != rollback_image:
            raise RuntimeError("Rollback-Digest konnte nach Neustart nicht verifiziert werden.")
        return save_state(
            phase="failed",
            message="Unterbrochenes Update wurde kontrolliert zurueckgesetzt.",
            error=state.get("error", "Update wurde durch einen Neustart unterbrochen."),
            rollback_error="",
            recovery_outcome="rolled_back",
            running={"image": verified_image},
            candidate_id="",
            candidate_digest="",
            update_available=False,
            completed_at=utc_now(),
        )
    except (AgentConfigError, PortainerAPIError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        logger.exception("Automatische Update-Recovery fehlgeschlagen, Operation %s", operation_id)
        _recovery_required(
            error="Automatische Recovery fehlgeschlagen; Portainer und App-Health pruefen.",
            outcome="rollback_failed",
        )
        return save_state(rollback_error=update_error("Rollback-Recovery", error))


def update_error(step: str, error: BaseException) -> str:
    """Format an update error for the Django status page."""
    return f"{step} fehlgeschlagen: {error}"


def recovery_hint(backup_name: str, old_image: str) -> str:
    """Return operator guidance that does not include secrets."""
    lines = [
        "Portainer Stack-Logs fuer app, updater und db pruefen.",
        f"Portainer Stack-ID: {PORTAINER_STACK_ID or 'unbekannt'}",
    ]
    if old_image:
        lines.append(f"Rollback-Image fuer APP_IMAGE: {old_image}")
    if backup_name:
        lines.append(f"Backup vorhanden: {backup_name}")
    return "\n".join(lines)


def perform_update(checked_state: dict[str, Any]) -> None:
    """Install the checked immutable image through Portainer and rollback on failure."""
    old_image = ""
    stack_mutated = False
    backup_name = ""
    step = "Update vorbereiten"
    try:
        approved_image, approved_digest = validate_immutable_image_reference(checked_state.get("approved_image"))
        if checked_state.get("approved_digest") != approved_digest:
            raise RuntimeError("Der freigegebene Image-Digest passt nicht zum Update-Status.")
        latest = checked_state.get("latest")
        if latest is not None and (not isinstance(latest, dict) or latest.get("id") != approved_digest):
            raise RuntimeError("Der freigegebene Image-Digest passt nicht zu den geprüften Metadaten.")
        if not isinstance(latest, dict):
            latest = {}
        client = PortainerClient()
        step = "Rollback-Image ermitteln"
        old_image = immutable_running_image(client, approved_image)
        checked_changelog = normalized_changelog_entries(checked_state.get("changelog", []))
        operation_started_at = str(checked_state.get("operation_started_at") or utc_now())
        operation_id = str(checked_state.get("operation_id") or secrets.token_urlsafe(24))
        candidate_identity = str(
            checked_state.get("candidate_identity")
            or hashlib.sha256(str(checked_state.get("candidate_id", approved_digest)).encode("utf-8")).hexdigest()
        )
        step = "Datenbank-Backup erstellen"
        backup_name = create_backup()
        save_state(
            phase="installing",
            message="Neues Image wird ueber Portainer gestartet.",
            error="",
            rollback_error="",
            recovery="",
            backup=backup_name,
            recovery_contract=RECOVERY_CONTRACT_VERSION,
            operation_id=operation_id,
            candidate_identity=candidate_identity,
            operation_started_at=operation_started_at,
            target_image=approved_image,
            target_digest=approved_digest,
            rollback_image=old_image,
            target_put_started_at=utc_now(),
            candidate_id="",
            candidate_digest="",
            update_available=False,
        )
        step = "Portainer Stack aktualisieren"
        stack_mutated = True
        client.update_stack_image(approved_image)
        step = "Healthcheck abwarten"
        wait_until_healthy()
        step = "Installiertes Image verifizieren"
        running_image = immutable_running_image(client, approved_image)
        if running_image != approved_image:
            raise RuntimeError("Nach dem Healthcheck wurde nicht der freigegebene Image-Digest gestartet.")
        installed = {**latest, "id": approved_digest, "image": approved_image}
        save_state(
            phase="complete",
            message="Update erfolgreich installiert.",
            error="",
            rollback_error="",
            recovery="",
            installed=installed,
            running={"image": running_image},
            update_available=False,
            changelog=checked_changelog,
            backup=backup_name,
            candidate_id="",
            candidate_digest="",
            completed_at=utc_now(),
        )
    except (AgentConfigError, PortainerAPIError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        logger.exception("Update fehlgeschlagen")
        rollback_error = ""
        if old_image and stack_mutated:
            try:
                save_state(
                    phase="rollback",
                    message="Update fehlgeschlagen; vorheriges Image wird wiederhergestellt.",
                    recovery_contract=RECOVERY_CONTRACT_VERSION,
                    operation_id=operation_id,
                    candidate_identity=candidate_identity,
                    operation_started_at=operation_started_at,
                    target_image=approved_image,
                    target_digest=approved_digest,
                    rollback_image=old_image,
                    rollback_put_started_at=utc_now(),
                    candidate_id="",
                    candidate_digest="",
                    update_available=False,
                )
                client.update_stack_image(old_image)
                wait_until_healthy()
                restored_image = immutable_running_image(client, approved_image)
                if restored_image != old_image:
                    raise RuntimeError("Rollback-Digest konnte nicht verifiziert werden.")
            except (AgentConfigError, PortainerAPIError, OSError, RuntimeError, subprocess.SubprocessError) as rollback:
                logger.exception("Rollback fehlgeschlagen")
                rollback_error = update_error("Rollback", rollback)
        save_state(
            phase="recovery_required" if rollback_error else "failed",
            message=(
                "Update und automatischer Rollback fehlgeschlagen; kontrollierte Recovery erforderlich."
                if rollback_error
                else "Update fehlgeschlagen; bitte Logs pruefen."
            ),
            error=update_error(step, error),
            rollback_error=rollback_error,
            recovery_outcome="rollback_failed" if rollback_error else "rolled_back" if stack_mutated else "not_started",
            recovery=recovery_hint(backup_name, old_image),
            backup=backup_name,
            candidate_id="",
            candidate_digest="",
            update_available=False,
        )
    finally:
        update_lock.release()


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    """Read a bounded JSON request body from a handler."""
    raw_length = handler.headers.get("Content-Length")
    if raw_length is None:
        raise AgentRequestError(HTTPStatus.LENGTH_REQUIRED, "content_length_required")
    normalized_length = raw_length.strip()
    if not CONTENT_LENGTH_PATTERN.fullmatch(normalized_length):
        raise AgentRequestError(HTTPStatus.BAD_REQUEST, "invalid_content_length")
    normalized_length = normalized_length.lstrip("0") or "0"
    maximum_length = str(MAX_AGENT_BODY_BYTES)
    if len(normalized_length) > len(maximum_length) or (
        len(normalized_length) == len(maximum_length) and normalized_length > maximum_length
    ):
        raise AgentRequestError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large")
    length = int(normalized_length)
    handler.connection.settimeout(AGENT_READ_TIMEOUT_SECONDS)
    if length == 0:
        return {}
    try:
        raw = handler.rfile.read(length)
    except TimeoutError as error:
        raise AgentRequestError(HTTPStatus.REQUEST_TIMEOUT, "request_timeout") from error
    except OSError as error:
        raise AgentRequestError(HTTPStatus.BAD_REQUEST, "incomplete_body") from error
    if len(raw) != length:
        raise AgentRequestError(HTTPStatus.BAD_REQUEST, "incomplete_body")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise AgentRequestError(HTTPStatus.BAD_REQUEST, "invalid_json") from error
    if not isinstance(payload, dict):
        raise AgentRequestError(HTTPStatus.BAD_REQUEST, "invalid_json_body")
    return payload


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP handler for the internal deployment agent API."""

    server_version = "LSFDeploymentAgent/2"

    def log_message(self, message: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), message % args)

    def authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "").encode("utf-8", "replace")
        expected = f"Bearer {TOKEN}".encode("utf-8", "replace")
        return hmac.compare_digest(supplied, expected)

    def respond(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def dispatch(self) -> None:
        if not self.authorized():
            self.respond(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            parsed_path = urllib.parse.urlsplit(self.path)
            if self.command == "GET" and parsed_path.path == "/healthz":
                self.respond(HTTPStatus.OK, {"status": "ok"})
            elif self.command == "GET" and parsed_path.path == "/status":
                self.respond(HTTPStatus.OK, deployment_status())
            elif self.command == "GET" and parsed_path.path == "/versions":
                values = urllib.parse.parse_qs(parsed_path.query, strict_parsing=True) if parsed_path.query else {}
                if set(values) - {"selected"} or any(len(items) != 1 for items in values.values()):
                    raise AgentRequestError(HTTPStatus.BAD_REQUEST, "invalid_catalog_selection")
                self.respond(HTTPStatus.OK, deployment_versions(values.get("selected", [""])[0]))
            elif self.command == "POST" and parsed_path.path == "/check":
                self.respond(HTTPStatus.OK, check_update(read_json_body(self)))
            elif self.command == "POST" and parsed_path.path == "/install":
                if not update_lock.acquire(blocking=False):
                    self.respond(HTTPStatus.CONFLICT, {"error": "update_in_progress"})
                    return
                lock_handed_to_thread = False
                try:
                    ensure_update_mutations_allowed()
                    request_payload = read_json_body(self)
                    request_candidate_id = request_payload.get("candidate_id")
                    _candidate_id, candidate_state = checked_install_candidate(request_candidate_id)
                    ensure_risk_acknowledged(candidate_state, request_payload.get("risk_acknowledged", False))
                    client = PortainerClient()
                    stack = client.get_stack()
                    validate_active_stack_contract(client, stack)
                    try:
                        validate_candidate_runtime_base(client, stack, load_state())
                    except (AgentConfigError, OSError, PortainerAPIError, RuntimeError):
                        invalidate_install_candidate("stale_runtime_base")
                        raise AgentRequestError(HTTPStatus.CONFLICT, "stale_runtime_base") from None
                    checked_state = consume_install_candidate(request_candidate_id)
                    thread = threading.Thread(
                        target=perform_update,
                        args=(checked_state,),
                        name="deployment-update",
                        daemon=True,
                    )
                    try:
                        thread.start()
                    except (OSError, RuntimeError) as error:
                        save_state(
                            phase="failed",
                            message="Update konnte nicht gestartet werden.",
                            error=update_error("Installations-Thread starten", error),
                            candidate_id="",
                            candidate_digest="",
                            update_available=False,
                        )
                        raise
                    lock_handed_to_thread = True
                finally:
                    if not lock_handed_to_thread:
                        update_lock.release()
                self.respond(HTTPStatus.ACCEPTED, {"status": "accepted"})
            elif self.command == "POST" and parsed_path.path == "/backup" and not parsed_path.query:
                payload = read_json_body(self)
                backup_name = create_backup_archive(
                    str(payload.get("staging_dir", "")),
                    str(payload.get("archive_prefix", "")),
                )
                self.respond(HTTPStatus.OK, {"backup": backup_name})
            else:
                self.respond(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except AgentRequestError as error:
            self.respond(error.status, {"error": error.public_code})
        except RegistryMetadataError:
            logger.exception("Ungültige Registry-Metadaten beim Update-Check.")
            self.respond(HTTPStatus.BAD_GATEWAY, {"error": "invalid_registry_metadata"})
        except (AgentConfigError, PortainerAPIError, OSError, RuntimeError):
            logger.exception("Agent-Anfrage fehlgeschlagen")
            self.respond(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "service_unavailable"})

    def do_GET(self) -> None:
        self.dispatch()

    def do_POST(self) -> None:
        self.dispatch()


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server with a fixed number of request worker slots."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[RequestHandler],
        *,
        max_concurrent_requests: int,
    ):
        super().__init__(server_address, handler_class)
        if max_concurrent_requests <= 0:
            raise ValueError("max_concurrent_requests must be positive")
        self._request_slots = threading.BoundedSemaphore(max_concurrent_requests)

    def process_request(self, request: Any, client_address: Any) -> None:
        """Start a request worker or reject it without creating another thread."""
        if not self._request_slots.acquire(blocking=False):
            self._reject_busy(request)
            return
        try:
            request.settimeout(AGENT_READ_TIMEOUT_SECONDS)
            thread = threading.Thread(
                target=self.process_request_thread,
                args=(request, client_address),
                daemon=self.daemon_threads,
            )
            thread.start()
        except BaseException:
            self._request_slots.release()
            self.shutdown_request(request)
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        """Run the standard request lifecycle and release its worker slot."""
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()

    def _reject_busy(self, request: Any) -> None:
        """Reject excess work with a bounded, generic response."""
        body = b'{"error":"server_busy"}'
        response = (
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Type: application/json\r\n"
            b"Connection: close\r\n" + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        )
        try:
            request.sendall(response)
        except OSError:
            logger.info("Anfrage wegen ausgelastetem Deployment-Agent abgewiesen.")
        finally:
            self.shutdown_request(request)


def run_agent() -> None:
    """Reconcile persisted update work before accepting mutating agent requests."""
    environment_channels()
    wait_for_portainer_startup(PortainerClient())
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    save_state()
    reconcile_interrupted_update()
    server = BoundedThreadingHTTPServer(
        ("0.0.0.0", 8080),
        RequestHandler,
        max_concurrent_requests=MAX_AGENT_CONCURRENT_REQUESTS,
    )
    logger.info("Deployment-Agent gestartet fuer Portainer Stack %s", PORTAINER_STACK_ID)
    server.serve_forever()


if __name__ == "__main__":
    run_agent()
