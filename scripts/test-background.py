#!/usr/bin/env python3
"""Run a local test command detached and save one durable status record."""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_ROOT = PROJECT_ROOT / ".test-local-logs" / "background"
SCHEMA_VERSION = 1
RUN_ID_PATTERN = re.compile(r"\A[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}\Z")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def metadata_path(run_dir: Path) -> Path:
    return run_dir / "status.json"


def read_metadata(run_dir: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(metadata_path(run_dir).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != SCHEMA_VERSION
    ):
        return None
    return value


def write_metadata_atomic(run_dir: Path, value: dict[str, Any]) -> None:
    temporary = run_dir / f".status-{os.getpid()}-{secrets.token_hex(4)}.tmp"
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, metadata_path(run_dir))


@contextmanager
def metadata_lock(run_dir: Path) -> Iterator[None]:
    with (run_dir / ".status.lock").open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def update_metadata(run_dir: Path, update: dict[str, Any]) -> dict[str, Any]:
    with metadata_lock(run_dir):
        current = read_metadata(run_dir)
        if current is None:
            raise RuntimeError("Run-Metadaten fehlen oder sind ungültig.")
        current.update(update)
        write_metadata_atomic(run_dir, current)
        return current


def process_identity(pid: int) -> tuple[str, str] | None:
    """Return boot ID plus process start ticks and state, preventing PID-reuse matches."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        fields = stat[stat.rfind(")") + 1 :].split()
        # The tail starts with field 3 (state); field 22 is starttime.
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        return f"{boot_id}:{fields[19]}", fields[0]
    except (OSError, IndexError, UnicodeDecodeError):
        return None


def git_snapshot(cwd: Path) -> tuple[str | None, bool | None]:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, check=True, capture_output=True, text=True, timeout=5
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"], cwd=cwd, check=True, capture_output=True, text=True, timeout=5
            ).stdout
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    return head, dirty


def create_run_root(raw_path: str | None) -> Path:
    path = Path(raw_path) if raw_path else DEFAULT_RUN_ROOT
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def command_exit_status(exit_code: int) -> int:
    if exit_code == 0:
        return 0
    return exit_code if 0 < exit_code < 256 else 1


def record_startup_failure(run_dir: Path, exit_code: int, error: str) -> None:
    finished_at = utc_now()
    update_metadata(
        run_dir,
        {
            "status": "failed",
            "stage": "startup",
            "finished_at": finished_at,
            "final_result": {
                "status": "failed",
                "stage": "startup",
                "exit_code": exit_code,
                "finished_at": finished_at,
                "error": error,
            },
        },
    )


def start_run(raw_run_root: str | None, raw_cwd: str | None, command: list[str]) -> int:
    if not Path("/proc/self/stat").exists():
        print("Detached Testläufe benötigen Linux /proc zur sicheren PID-Identifikation.", file=sys.stderr)
        return 2
    cwd = Path(raw_cwd) if raw_cwd else PROJECT_ROOT
    if not cwd.is_absolute():
        cwd = Path.cwd() / cwd
    cwd = cwd.resolve()
    if not cwd.is_dir():
        print(f"Arbeitsverzeichnis existiert nicht: {cwd}", file=sys.stderr)
        return 2
    run_root = create_run_root(raw_run_root)
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(6)}"
    run_dir = run_root / run_id
    run_dir.mkdir(mode=0o700)
    git_head, git_dirty = git_snapshot(cwd)
    initial: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "starting",
        "stage": "launch",
        "command": command,
        "cwd": str(cwd),
        "created_at": utc_now(),
        "pid": None,
        "process_start_identity": None,
        "system_boot_id": Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip(),
        "git_head": git_head,
        "git_dirty": git_dirty,
        "log": str(run_dir / "stdout.log"),
        "final_result": None,
    }
    write_metadata_atomic(run_dir, initial)

    read_fd, write_fd = os.pipe()
    try:
        with (run_dir / "stdout.log").open("ab") as log_file:
            worker = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "_worker", str(run_dir), str(read_fd)],
                cwd=PROJECT_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                close_fds=True,
                pass_fds=(read_fd,),
                start_new_session=True,
            )
    except OSError as error:
        os.close(read_fd)
        os.close(write_fd)
        record_startup_failure(run_dir, 127, str(error))
        print(f"Detached Lauf konnte nicht gestartet werden: {error}", file=sys.stderr)
        return 127
    os.close(read_fd)
    identity = process_identity(worker.pid)
    if identity is None:
        worker.terminate()
        worker.wait(timeout=2)
        os.close(write_fd)
        record_startup_failure(run_dir, 2, "Prozessidentität konnte nicht ermittelt werden.")
        print("Prozessidentität des Testläufers konnte nicht gelesen werden.", file=sys.stderr)
        return 2
    update_metadata(
        run_dir,
        {
            "status": "running",
            "stage": "command",
            "pid": worker.pid,
            "process_start_identity": identity[0],
            "started_at": utc_now(),
        },
    )
    try:
        os.write(write_fd, b"1")
    except OSError as error:
        worker.terminate()
        worker.wait(timeout=2)
        record_startup_failure(run_dir, 2, str(error))
        print(f"Testläufer konnte nicht aktiviert werden: {error}", file=sys.stderr)
        return 2
    finally:
        os.close(write_fd)
    print(f"Run: {run_id}")
    print("Status: running")
    print(f"Log: {run_dir / 'stdout.log'}")
    print(f"Status lesen: python scripts/test-background.py status {run_id}")
    return 0


def worker_main(run_dir: Path, ready_fd: int) -> int:
    try:
        ready = os.read(ready_fd, 1)
    finally:
        os.close(ready_fd)
    if ready != b"1":
        return 2
    metadata = read_metadata(run_dir)
    if metadata is None or not isinstance(metadata.get("command"), list):
        return 2
    command = metadata["command"]
    if not command or not all(isinstance(argument, str) for argument in command):
        return 2
    exit_code: int
    error: str | None = None
    try:
        completed = subprocess.run(
            command,
            cwd=metadata["cwd"],
            stdin=subprocess.DEVNULL,
            stdout=None,
            stderr=subprocess.STDOUT,
            check=False,
        )
        exit_code = completed.returncode
    except OSError as exception:
        exit_code = 127
        error = str(exception)
    final_status = "passed" if exit_code == 0 else "failed"
    result: dict[str, Any] = {
        "status": final_status,
        "stage": "command",
        "exit_code": exit_code,
        "finished_at": utc_now(),
    }
    if error is not None:
        result["error"] = error
    update_metadata(
        run_dir,
        {
            "status": final_status,
            "stage": "command",
            "finished_at": result["finished_at"],
            "final_result": result,
        },
    )
    return 0


def valid_final_metadata(metadata: dict[str, Any]) -> bool:
    result = metadata.get("final_result")
    command = metadata.get("command")
    common_valid = (
        not isinstance(result, dict)
        or type(result.get("exit_code")) is not int
        or not isinstance(command, list)
        or not command
        or not all(isinstance(argument, str) for argument in command)
        or not isinstance(metadata.get("cwd"), str)
        or not isinstance(metadata.get("created_at"), str)
        or not metadata["created_at"]
        or not isinstance(metadata.get("finished_at"), str)
        or not metadata["finished_at"]
        or result.get("finished_at") != metadata.get("finished_at")
        or not isinstance(metadata.get("log"), str)
        or (metadata.get("git_dirty") is not None and type(metadata.get("git_dirty")) is not bool)
        or (metadata.get("git_head") is not None and not isinstance(metadata.get("git_head"), str))
        or not isinstance(metadata.get("system_boot_id"), str)
        or not metadata["system_boot_id"]
    )
    if common_valid:
        return False
    if metadata.get("status") == "passed":
        return (
            result.get("status") == "passed"
            and result.get("stage") == "command"
            and metadata.get("stage") == "command"
            and result["exit_code"] == 0
            and type(metadata.get("pid")) is int
            and metadata["pid"] > 0
            and isinstance(metadata.get("process_start_identity"), str)
            and isinstance(metadata.get("started_at"), str)
            and metadata["started_at"]
            and metadata["process_start_identity"].startswith(f"{metadata['system_boot_id']}:")
        )
    if metadata.get("status") == "failed":
        if result.get("status") != "failed" or result["exit_code"] == 0:
            return False
        if result.get("stage") == "startup":
            return metadata.get("stage") == "startup" and metadata.get("pid") is None
        return (
            result.get("stage") == "command"
            and metadata.get("stage") == "command"
            and type(metadata.get("pid")) is int
            and metadata["pid"] > 0
            and isinstance(metadata.get("process_start_identity"), str)
            and isinstance(metadata.get("started_at"), str)
            and metadata["started_at"]
            and metadata["process_start_identity"].startswith(f"{metadata['system_boot_id']}:")
        )
    return False


def render_final_status(run_id: str, run_dir: Path, metadata: dict[str, Any]) -> int:
    if not valid_final_metadata(metadata):
        print(f"Run {run_id}: UNKNOWN (Status-Metadaten unvollständig oder ungültig)")
        return 2
    result = metadata["final_result"]
    exit_code = result["exit_code"]
    print(f"Run {run_id}: {metadata['status'].upper()} (Exit-Code: {exit_code})")
    print(f"Log: {run_dir / 'stdout.log'}")
    return command_exit_status(exit_code)


def status_run(raw_run_root: str | None, run_id: str) -> int:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        print("Ungültige Run-ID.", file=sys.stderr)
        return 2
    run_root = create_run_root(raw_run_root)
    run_dir = run_root / run_id
    metadata = read_metadata(run_dir)
    if metadata is None or metadata.get("run_id") != run_id:
        print(f"Run {run_id}: UNKNOWN (Metadaten fehlen oder sind ungültig)")
        return 2
    if metadata.get("status") in {"passed", "failed"}:
        return render_final_status(run_id, run_dir, metadata)
    if metadata.get("status") == "interrupted":
        print(f"Run {run_id}: INTERRUPTED (kein finales Ergebnis)")
        print(f"Log: {run_dir / 'stdout.log'}")
        return 4
    if metadata.get("status") != "running":
        print(f"Run {run_id}: UNKNOWN (Status-Metadaten unvollständig oder ungültig)")
        return 2
    pid = metadata.get("pid")
    expected_identity = metadata.get("process_start_identity")
    if type(pid) is not int or pid <= 0 or not isinstance(expected_identity, str) or ":" not in expected_identity:
        print(f"Run {run_id}: UNKNOWN (Prozessidentität fehlt)")
        return 2
    current = process_identity(pid)
    if current is not None and current[0] == expected_identity and current[1] not in {"Z", "X", "x"}:
        print(f"Run {run_id}: RUNNING (PID: {pid})")
        print(f"Log: {run_dir / 'stdout.log'}")
        return 3
    # Re-read once to avoid reporting interruption if the worker just finalized.
    latest = read_metadata(run_dir)
    if latest is not None and latest.get("status") in {"passed", "failed"}:
        return render_final_status(run_id, run_dir, latest)
    try:
        update_metadata(
            run_dir,
            {"status": "interrupted", "interruption_observed_at": utc_now(), "final_result": None},
        )
    except RuntimeError:
        print(f"Run {run_id}: UNKNOWN (Status-Metadaten unvollständig oder ungültig)")
        return 2
    print(f"Run {run_id}: INTERRUPTED (Prozess beendet oder PID-Identität geändert; kein finales Ergebnis)")
    print(f"Log: {run_dir / 'stdout.log'}")
    return 4


def parse_options(args: list[str]) -> tuple[str, str | None, str | None, list[str]]:
    if not args or args[0] not in {"start", "status", "_worker"}:
        raise ValueError("Nutzung: test-background.py start [--run-root PATH] [--cwd PATH] [-- ARGV…] | status RUN_ID")
    action = args[0]
    if action == "_worker":
        if len(args) != 3:
            raise ValueError("Ungültiger interner Worker-Aufruf.")
        return action, args[1], args[2], []
    if action == "status":
        import argparse

        parser = argparse.ArgumentParser(prog="test-background.py status")
        parser.add_argument("run_id")
        parser.add_argument("--run-root")
        options = parser.parse_args(args[1:])
        return action, options.run_root, options.run_id, []
    has_delimiter = "--" in args[1:]
    if has_delimiter:
        delimiter = args.index("--", 1)
        option_args = args[1:delimiter]
        command = args[delimiter + 1 :]
    else:
        option_args = args[1:]
        command = []
    import argparse

    parser = argparse.ArgumentParser(prog="test-background.py start")
    parser.add_argument("--run-root")
    parser.add_argument("--cwd")
    options = parser.parse_args(option_args)
    if command and command[0] == "--":
        command = command[1:]
    if command and not all(isinstance(argument, str) for argument in command):
        raise ValueError("Alle Befehlsargumente müssen Text sein.")
    if has_delimiter and not command:
        raise ValueError("Nach `--` muss mindestens ein Programm und ein Argument stehen.")
    if not command:
        command = ["bash", str(PROJECT_ROOT / "scripts" / "test-local.sh")]
    return action, options.run_root, options.cwd, command


def main(args: list[str] | None = None) -> int:
    try:
        action, first, second, command = parse_options(list(sys.argv[1:] if args is None else args))
    except (ValueError, SystemExit) as error:
        if isinstance(error, SystemExit):
            return int(error.code or 0)
        print(str(error), file=sys.stderr)
        return 2
    if action == "start":
        return start_run(first, second, command)
    if action == "status":
        assert second is not None
        return status_run(first, second)
    assert action == "_worker"
    return worker_main(Path(first), int(second))


if __name__ == "__main__":
    raise SystemExit(main())
