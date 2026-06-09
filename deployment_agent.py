from __future__ import annotations

import gzip
import hmac
import json
import logging
import os
import subprocess
import threading
import time
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, NotFound

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("deployment-agent")

TOKEN = os.environ["UPDATE_AGENT_TOKEN"]
TARGET_IMAGE = os.getenv("APP_IMAGE", "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp:latest")
PROJECT_NAME = os.getenv("COMPOSE_PROJECT_NAME", "fliegerlager")
TARGET_SERVICE = os.getenv("TARGET_SERVICE", "app")
DATABASE_SERVICE = os.getenv("DATABASE_SERVICE", "db")
COMPOSE_FILE = os.getenv("COMPOSE_FILE", "/deployment/docker-compose.yml")
ENV_FILE = os.getenv("COMPOSE_ENV_FILE", "/deployment/.env")
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/backups"))
HEALTH_TIMEOUT = int(os.getenv("UPDATE_HEALTH_TIMEOUT", "180"))
STATE_FILE = Path(os.getenv("UPDATE_STATE_FILE", "/state/status.json"))

client: Any | None = None
update_lock = threading.Lock()
state_lock = threading.Lock()


def docker_client() -> Any:
    global client
    if client is None:
        client = docker.from_env()
    return client


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def image_metadata(image: Any) -> dict[str, str]:
    labels = image.labels or {}
    return {
        "id": image.id,
        "version": labels.get("org.opencontainers.image.version", "unknown"),
        "revision": labels.get("org.opencontainers.image.revision", "unknown"),
        "build_date": labels.get("org.opencontainers.image.created", "unknown"),
        "change": labels.get("io.lsf-fliegerlager.change", "Unbekannter Change"),
    }


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"phase": "idle", "message": "Noch kein Update ausgeführt."}


def save_state(**values: Any) -> dict[str, Any]:
    with state_lock:
        current = load_state()
        current.update(values, updated_at=utc_now())
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, ensure_ascii=True, indent=2), encoding="utf-8")
        temporary.replace(STATE_FILE)
        return current


def service_container(service: str) -> Any:
    containers = docker_client().containers.list(
        all=True,
        filters={
            "label": [
                f"com.docker.compose.project={PROJECT_NAME}",
                f"com.docker.compose.service={service}",
            ]
        },
    )
    if len(containers) != 1:
        raise RuntimeError(f"Erwartete genau einen Container für Service {service}, gefunden: {len(containers)}")
    return containers[0]


def deployment_status() -> dict[str, Any]:
    running = service_container(TARGET_SERVICE)
    running.reload()
    result = load_state()
    result["running"] = image_metadata(running.image)
    result["container_status"] = running.status
    result["health"] = running.attrs.get("State", {}).get("Health", {}).get("Status", "unknown")
    latest_id = result.get("latest", {}).get("id")
    result["update_available"] = bool(latest_id and latest_id != running.image.id)
    return result


def check_update() -> dict[str, Any]:
    if update_lock.locked():
        raise RuntimeError("Ein Update läuft bereits.")
    running = service_container(TARGET_SERVICE)
    latest = docker_client().images.pull(TARGET_IMAGE)
    latest_data = image_metadata(latest)
    state = save_state(
        phase="checked",
        message="Image-Prüfung abgeschlossen.",
        latest=latest_data,
        checked_at=utc_now(),
    )
    state["running"] = image_metadata(running.image)
    state["update_available"] = latest.id != running.image.id
    return state


def create_backup() -> str:
    database = service_container(DATABASE_SERVICE)
    result = database.exec_run(
        [
            "sh",
            "-c",
            'pg_dump --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB"',
        ]
    )
    if result.exit_code != 0:
        raise RuntimeError("Datenbank-Backup fehlgeschlagen.")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"fliegerlager-before-update-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.sql.gz"
    backup_path = BACKUP_DIR / filename
    with gzip.open(backup_path, "wb") as backup:
        backup.write(result.output)
    if backup_path.stat().st_size == 0:
        raise RuntimeError("Datenbank-Backup ist leer.")
    return filename


def compose_up(image: str) -> None:
    environment = os.environ.copy()
    environment["APP_IMAGE"] = image
    command = [
        "docker",
        "compose",
        "--project-name",
        PROJECT_NAME,
        "--file",
        COMPOSE_FILE,
        "--env-file",
        ENV_FILE,
        "up",
        "--detach",
        "--no-deps",
        "--force-recreate",
        TARGET_SERVICE,
    ]
    subprocess.run(command, env=environment, check=True, capture_output=True, text=True, timeout=180)


def wait_until_healthy(expected_image_id: str) -> None:
    deadline = time.monotonic() + HEALTH_TIMEOUT
    while time.monotonic() < deadline:
        try:
            container = service_container(TARGET_SERVICE)
            container.reload()
        except (NotFound, RuntimeError) as error:
            logger.info("Warte auf neuen App-Container: %s", error)
            time.sleep(3)
            continue
        health = container.attrs.get("State", {}).get("Health", {}).get("Status")
        if container.image.id == expected_image_id and health == "healthy":
            return
        if health == "unhealthy":
            raise RuntimeError("Der neue App-Container ist unhealthy.")
        time.sleep(3)
    raise RuntimeError("Der neue App-Container wurde nicht rechtzeitig healthy.")


def perform_update() -> None:
    old_image_id = ""
    backup_name = ""
    try:
        save_state(phase="preparing", message="Update wird vorbereitet.", error="")
        old_container = service_container(TARGET_SERVICE)
        old_image_id = old_container.image.id
        latest = docker_client().images.pull(TARGET_IMAGE)
        if latest.id == old_image_id:
            save_state(phase="complete", message="Die Anwendung ist bereits aktuell.", latest=image_metadata(latest))
            return

        backup_name = create_backup()
        save_state(phase="installing", message="Neues Image wird gestartet.", backup=backup_name)
        compose_up(TARGET_IMAGE)
        wait_until_healthy(latest.id)
        save_state(
            phase="complete",
            message="Update erfolgreich installiert.",
            installed=image_metadata(latest),
            backup=backup_name,
            completed_at=utc_now(),
        )
    except (DockerException, OSError, RuntimeError, subprocess.SubprocessError) as error:
        logger.exception("Update fehlgeschlagen")
        rollback_error = ""
        if old_image_id:
            try:
                save_state(phase="rollback", message="Update fehlgeschlagen; vorheriges Image wird wiederhergestellt.")
                compose_up(old_image_id)
                wait_until_healthy(old_image_id)
            except (DockerException, OSError, RuntimeError, subprocess.SubprocessError) as rollback_exception:
                logger.exception("Rollback fehlgeschlagen")
                rollback_error = f" Rollback fehlgeschlagen: {rollback_exception}"
        save_state(
            phase="failed",
            message="Update fehlgeschlagen; bitte Logs prüfen.",
            error=f"{error}{rollback_error}",
            backup=backup_name,
        )
    finally:
        update_lock.release()


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "LSFDeploymentAgent/1"

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
                self.respond(HTTPStatus.OK, check_update())
            elif self.command == "POST" and self.path == "/install":
                if not update_lock.acquire(blocking=False):
                    self.respond(HTTPStatus.CONFLICT, {"error": "update_in_progress"})
                    return
                thread = threading.Thread(target=perform_update, name="deployment-update", daemon=True)
                thread.start()
                self.respond(HTTPStatus.ACCEPTED, {"status": "accepted"})
            else:
                self.respond(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except (DockerException, OSError, RuntimeError) as error:
            logger.exception("Agent-Anfrage fehlgeschlagen")
            self.respond(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(error)})

    def do_GET(self) -> None:
        self.dispatch()

    def do_POST(self) -> None:
        self.dispatch()


if __name__ == "__main__":
    docker_client().ping()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", 8080), RequestHandler)
    logger.info("Deployment-Agent gestartet für %s/%s", PROJECT_NAME, TARGET_SERVICE)
    server.serve_forever()
