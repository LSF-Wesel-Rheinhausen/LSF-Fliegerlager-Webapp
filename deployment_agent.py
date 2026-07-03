from __future__ import annotations

import base64
import gzip
import hmac
import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("deployment-agent")

TOKEN = os.environ["UPDATE_AGENT_TOKEN"]
TARGET_IMAGE = os.getenv("APP_IMAGE", "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp:latest")
TARGET_SERVICE = os.getenv("TARGET_SERVICE", "app")
PORTAINER_URL = os.getenv("PORTAINER_URL", "").rstrip("/")
PORTAINER_API_KEY = os.getenv("PORTAINER_API_KEY", "")
PORTAINER_ENDPOINT_ID = os.getenv("PORTAINER_ENDPOINT_ID", "")
PORTAINER_STACK_ID = os.getenv("PORTAINER_STACK_ID", "")
APP_HEALTH_URL = os.getenv("APP_HEALTH_URL", "http://app:8000/healthz/")
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/backups"))
DATABASE_URL = os.getenv("DATABASE_URL", "")
GHCR_TOKEN = os.getenv("GHCR_TOKEN", "")
HEALTH_TIMEOUT = int(os.getenv("UPDATE_HEALTH_TIMEOUT", "180"))
STATE_FILE = Path(os.getenv("UPDATE_STATE_FILE", "/state/status.json"))

update_lock = threading.Lock()
state_lock = threading.Lock()

OCI_LABELS = {
    "version": "org.opencontainers.image.version",
    "revision": "org.opencontainers.image.revision",
    "build_date": "org.opencontainers.image.created",
    "change": "io.lsf-fliegerlager.change",
}
MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


class AgentConfigError(RuntimeError):
    """Raised when required updater environment variables are missing or invalid."""


class PortainerAPIError(RuntimeError):
    """Raised when Portainer rejects a stack operation."""


def require_env(name: str, value: str) -> str:
    """Return a required environment value or raise a clear configuration error."""
    if value.strip():
        return value
    raise AgentConfigError(f"Pflichtvariable {name} ist nicht gesetzt.")


def utc_now() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()


def load_state() -> dict[str, Any]:
    """Load the persisted updater state for the Django status page."""
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"phase": "idle", "message": "Noch kein Update ausgefuehrt."}


def save_state(**values: Any) -> dict[str, Any]:
    """Persist updater state atomically and return the merged state."""
    with state_lock:
        current = load_state()
        current.update(values, updated_at=utc_now())
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, ensure_ascii=True, indent=2), encoding="utf-8")
        temporary.replace(STATE_FILE)
        return current


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
    ) -> None:
        self.base_url = require_env("PORTAINER_URL", base_url if base_url is not None else PORTAINER_URL).rstrip("/")
        self.api_key = require_env("PORTAINER_API_KEY", api_key if api_key is not None else PORTAINER_API_KEY)
        self.endpoint_id = require_env(
            "PORTAINER_ENDPOINT_ID",
            endpoint_id if endpoint_id is not None else PORTAINER_ENDPOINT_ID,
        )
        self.stack_id = require_env("PORTAINER_STACK_ID", stack_id if stack_id is not None else PORTAINER_STACK_ID)

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
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status == HTTPStatus.NO_CONTENT:
                    return {}
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise PortainerAPIError(self._format_http_error(error)) from error
        except (OSError, TimeoutError) as error:
            raise PortainerAPIError("Portainer API ist nicht erreichbar.") from error
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

    def docker_request(self, method: str, path: str, *, query: dict[str, str] | None = None) -> Any:
        """Call the Docker API through Portainer's endpoint proxy."""
        return self.raw_request(method, f"/endpoints/{self.endpoint_id}/docker{path}", query=query)

    def get_stack(self) -> dict[str, Any]:
        """Return the configured Portainer stack."""
        return self.request("GET", f"/stacks/{self.stack_id}")

    def get_stack_file_content(self, stack: dict[str, Any]) -> str:
        """Return the Compose content Portainer requires for stack updates."""
        embedded = stack.get("StackFileContent") or stack.get("stackFileContent")
        if isinstance(embedded, str) and embedded.strip():
            return embedded
        result = self.request(
            "GET",
            f"/stacks/{self.stack_id}/file",
            query={"endpointId": self.endpoint_id},
        )
        content = result.get("StackFileContent") or result.get("stackFileContent")
        if not isinstance(content, str) or not content.strip():
            raise PortainerAPIError("Portainer Stack-Datei konnte nicht gelesen werden.")
        return content

    def update_stack_image(self, image: str) -> dict[str, Any]:
        """Update APP_IMAGE in the stack variables and redeploy the stack."""
        stack = self.get_stack()
        stack_file_content = self.get_stack_file_content(stack)
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
    """Return APP_IMAGE from the Portainer stack variables."""
    for item in extract_stack_env(stack):
        if item["name"] == "APP_IMAGE":
            return item["value"]
    return TARGET_IMAGE


def immutable_running_image(client: PortainerClient) -> str:
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
    target_registry, target_repository, _reference = parse_image_reference(TARGET_IMAGE)
    target_prefix = f"{target_registry}/{target_repository}@"
    for digest in repo_digests:
        if isinstance(digest, str) and digest.startswith(target_prefix):
            return digest
    for digest in repo_digests:
        if isinstance(digest, str) and "@sha256:" in digest:
            return digest
    raise RuntimeError("Kein unveraenderlicher Image-Digest fuer Rollback gefunden.")


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


def registry_basic_auth_header() -> str | None:
    """Return a GHCR Basic auth header when a token is configured."""
    if not GHCR_TOKEN:
        return None
    encoded = base64.b64encode(f"unused:{GHCR_TOKEN}".encode()).decode("ascii")
    return f"Basic {encoded}"


def registry_request(
    url: str,
    *,
    accept: str,
    token: str | None = None,
    timeout: int = 30,
) -> tuple[bytes, dict[str, str]]:
    """Fetch a registry resource and resolve public GHCR bearer auth challenges."""
    headers = {"Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        authorization = registry_basic_auth_header()
        if authorization:
            headers["Authorization"] = authorization
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        if error.code != HTTPStatus.UNAUTHORIZED or token:
            raise RuntimeError("Registry-Abfrage fehlgeschlagen.") from error
        bearer_token = fetch_registry_token(error.headers.get("WWW-Authenticate", ""))
        return registry_request(url, accept=accept, token=bearer_token, timeout=timeout)
    except (OSError, TimeoutError) as error:
        raise RuntimeError("Registry ist nicht erreichbar.") from error


def fetch_registry_token(auth_header: str) -> str:
    """Fetch a bearer token from a registry WWW-Authenticate challenge."""
    if not auth_header.startswith("Bearer "):
        raise RuntimeError("Registry verlangt eine unbekannte Authentifizierung.")
    values = urllib.parse.parse_qs(auth_header.removeprefix("Bearer ").replace(",", "&").replace('"', ""))
    realm = values.get("realm", [""])[0]
    if not realm:
        raise RuntimeError("Registry-Authentifizierung enthaelt keinen Token-Endpunkt.")
    query = {key: value[0] for key, value in values.items() if key in {"service", "scope"} and value}
    url = f"{realm}?{urllib.parse.urlencode(query)}" if query else realm
    headers = {"Accept": "application/json"}
    authorization = registry_basic_auth_header()
    if authorization:
        headers["Authorization"] = authorization
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (OSError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("Registry-Token konnte nicht geladen werden.") from error
    token = payload.get("token") or payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Registry-Token-Antwort ist ungueltig.")
    return token


def choose_manifest_descriptor(index: dict[str, Any]) -> dict[str, Any]:
    """Pick a linux/amd64 manifest from an OCI index, falling back to the first item."""
    manifests = index.get("manifests")
    if not isinstance(manifests, list) or not manifests:
        raise RuntimeError("OCI-Index enthaelt keine Manifest-Eintraege.")
    for manifest in manifests:
        platform = manifest.get("platform", {}) if isinstance(manifest, dict) else {}
        if platform.get("os") == "linux" and platform.get("architecture") == "amd64":
            return manifest
    first = manifests[0]
    if not isinstance(first, dict):
        raise RuntimeError("OCI-Index enthaelt ein ungueltiges Manifest.")
    return first


def fetch_image_metadata(image: str) -> dict[str, str]:
    """Read OCI labels and digest metadata for an image from its registry."""
    registry, repository, reference = parse_image_reference(image)
    manifest_url = f"https://{registry}/v2/{repository}/manifests/{reference}"
    raw_manifest, headers = registry_request(manifest_url, accept=MANIFEST_ACCEPT)
    manifest = json.loads(raw_manifest)
    media_type = manifest.get("mediaType") or headers.get("Content-Type", "")
    digest = headers.get("Docker-Content-Digest", reference if reference.startswith("sha256:") else "unknown")
    if "image.index" in media_type or "manifest.list" in media_type:
        descriptor = choose_manifest_descriptor(manifest)
        digest = str(descriptor.get("digest", digest))
        raw_manifest, headers = registry_request(
            f"https://{registry}/v2/{repository}/manifests/{digest}",
            accept=MANIFEST_ACCEPT,
        )
        manifest = json.loads(raw_manifest)
        digest = headers.get("Docker-Content-Digest", digest)
    config = manifest.get("config", {})
    config_digest = config.get("digest") if isinstance(config, dict) else None
    if not isinstance(config_digest, str) or not config_digest:
        raise RuntimeError("OCI-Manifest enthaelt keinen Config-Digest.")
    raw_config, _headers = registry_request(
        f"https://{registry}/v2/{repository}/blobs/{config_digest}",
        accept="application/vnd.oci.image.config.v1+json, application/vnd.docker.container.image.v1+json",
    )
    config_payload = json.loads(raw_config)
    labels = config_payload.get("config", {}).get("Labels", {})
    if not isinstance(labels, dict):
        labels = {}
    return image_metadata(
        {
            "id": digest,
            "image": image,
            "labels": labels,
        }
    )


def image_metadata(image: Any) -> dict[str, str]:
    """Normalize OCI image metadata from Docker-like objects or dict payloads."""
    if isinstance(image, dict):
        labels = image.get("labels") or {}
        image_id = str(image.get("id", "unknown"))
        image_ref = str(image.get("image", TARGET_IMAGE))
    else:
        labels = image.labels or {}
        image_id = str(image.id)
        image_ref = TARGET_IMAGE
    return {
        "id": image_id,
        "image": image_ref,
        "version": str(labels.get(OCI_LABELS["version"], "unknown")),
        "revision": str(labels.get(OCI_LABELS["revision"], "unknown")),
        "build_date": str(labels.get(OCI_LABELS["build_date"], "unknown")),
        "change": str(labels.get(OCI_LABELS["change"], "Unbekannter Change")),
    }


def current_metadata_from_payload(payload: dict[str, Any] | None) -> dict[str, str]:
    """Normalize current build metadata supplied by Django."""
    current = payload.get("current") if payload else None
    if not isinstance(current, dict):
        return {}
    return {key: str(value) for key, value in current.items() if value is not None}


def has_update(latest: dict[str, str], current: dict[str, str], current_image: str) -> bool:
    """Compare latest OCI labels with the currently running Django build metadata."""
    compared = False
    for key in ("revision", "version", "build_date"):
        current_value = current.get(key)
        latest_value = latest.get(key)
        if current_value and latest_value and current_value != "unknown" and latest_value != "unknown":
            compared = True
            if current_value != latest_value:
                return True
    if compared:
        return False
    return latest.get("image") != current_image


def deployment_status() -> dict[str, Any]:
    """Return persisted update state and the configured Portainer stack image."""
    stack = PortainerClient().get_stack()
    running_image = stack_app_image(stack)
    result = load_state()
    result["running"] = {"image": running_image}
    if "update_available" not in result:
        latest_id = result.get("latest", {}).get("id")
        installed_id = result.get("installed", {}).get("id")
        result["update_available"] = bool(latest_id and latest_id != installed_id)
    return result


def check_update(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Check GHCR metadata and compare it with current Django build metadata."""
    if update_lock.locked():
        raise RuntimeError("Ein Update laeuft bereits.")
    stack = PortainerClient().get_stack()
    running_image = stack_app_image(stack)
    latest = fetch_image_metadata(TARGET_IMAGE)
    current = current_metadata_from_payload(payload)
    update_available = has_update(latest, current, running_image)
    state = save_state(
        phase="checked",
        message="Image-Pruefung abgeschlossen.",
        error="",
        rollback_error="",
        recovery="",
        latest=latest,
        running={"image": running_image, **current},
        update_available=update_available,
        checked_at=utc_now(),
    )
    return state


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


def create_backup() -> str:
    """Create a gzipped PostgreSQL backup using DATABASE_URL connection details."""
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
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"fliegerlager-before-update-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.sql.gz"
    backup_path = BACKUP_DIR / filename
    with gzip.open(backup_path, "wb") as backup:
        backup.write(result.stdout)
    if backup_path.stat().st_size == 0:
        raise RuntimeError("Datenbank-Backup ist leer.")
    return filename


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


def perform_update() -> None:
    """Install the configured APP_IMAGE through Portainer and rollback on failure."""
    old_image = ""
    backup_name = ""
    step = "Update vorbereiten"
    try:
        save_state(phase="preparing", message="Update wird vorbereitet.", error="", rollback_error="", recovery="")
        client = PortainerClient()
        step = "Rollback-Image ermitteln"
        old_image = immutable_running_image(client)
        step = "Neuestes Image pruefen"
        latest = fetch_image_metadata(TARGET_IMAGE)
        step = "Datenbank-Backup erstellen"
        backup_name = create_backup()
        save_state(
            phase="installing",
            message="Neues Image wird ueber Portainer gestartet.",
            error="",
            rollback_error="",
            recovery="",
            backup=backup_name,
        )
        step = "Portainer Stack aktualisieren"
        client.update_stack_image(TARGET_IMAGE)
        step = "Healthcheck abwarten"
        wait_until_healthy()
        save_state(
            phase="complete",
            message="Update erfolgreich installiert.",
            error="",
            rollback_error="",
            recovery="",
            installed=latest,
            running={"image": TARGET_IMAGE},
            update_available=False,
            backup=backup_name,
            completed_at=utc_now(),
        )
    except (AgentConfigError, PortainerAPIError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        logger.exception("Update fehlgeschlagen")
        rollback_error = ""
        if old_image:
            try:
                save_state(phase="rollback", message="Update fehlgeschlagen; vorheriges Image wird wiederhergestellt.")
                redeploy_stack(old_image)
                wait_until_healthy()
            except (AgentConfigError, PortainerAPIError, OSError, RuntimeError, subprocess.SubprocessError) as rollback:
                logger.exception("Rollback fehlgeschlagen")
                rollback_error = update_error("Rollback", rollback)
        save_state(
            phase="failed",
            message="Update fehlgeschlagen; bitte Logs pruefen.",
            error=update_error(step, error),
            rollback_error=rollback_error,
            recovery=recovery_hint(backup_name, old_image),
            backup=backup_name,
        )
    finally:
        update_lock.release()


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    """Read an optional JSON request body from a handler."""
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("Ungueltiger JSON-Body.") from error
    if not isinstance(payload, dict):
        raise RuntimeError("JSON-Body muss ein Objekt sein.")
    return payload


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP handler for the internal deployment agent API."""

    server_version = "LSFDeploymentAgent/2"

    def log_message(self, message: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), message % args)

    def authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {TOKEN}"
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
            if self.command == "GET" and self.path == "/healthz":
                self.respond(HTTPStatus.OK, {"status": "ok"})
            elif self.command == "GET" and self.path == "/status":
                self.respond(HTTPStatus.OK, deployment_status())
            elif self.command == "POST" and self.path == "/check":
                self.respond(HTTPStatus.OK, check_update(read_json_body(self)))
            elif self.command == "POST" and self.path == "/install":
                if not update_lock.acquire(blocking=False):
                    self.respond(HTTPStatus.CONFLICT, {"error": "update_in_progress"})
                    return
                thread = threading.Thread(target=perform_update, name="deployment-update", daemon=True)
                thread.start()
                self.respond(HTTPStatus.ACCEPTED, {"status": "accepted"})
            else:
                self.respond(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except (AgentConfigError, PortainerAPIError, OSError, RuntimeError) as error:
            logger.exception("Agent-Anfrage fehlgeschlagen")
            self.respond(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(error)})

    def do_GET(self) -> None:
        self.dispatch()

    def do_POST(self) -> None:
        self.dispatch()


if __name__ == "__main__":
    PortainerClient().get_stack()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", 8080), RequestHandler)
    logger.info("Deployment-Agent gestartet fuer Portainer Stack %s", PORTAINER_STACK_ID)
    server.serve_forever()
