import json
import os
import re
import signal
import subprocess
import sys
import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "scripts" / "test-background.py"
RUN_ID_RE = re.compile(r"Run: ([0-9]{8}T[0-9]{6}Z-[a-f0-9]{12})")
RUNNER_SPEC = spec_from_file_location("background_test_runner", RUNNER)
RUNNER_MODULE = module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(RUNNER_MODULE)


def start_run(tmp_path, *command):
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "start",
            "--run-root",
            str(tmp_path),
            "--cwd",
            str(PROJECT_ROOT),
            "--",
            *command,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    match = RUN_ID_RE.search(result.stdout)
    assert match, result.stdout
    return match.group(1), result


def read_metadata(root, run_id):
    return json.loads((root / run_id / "status.json").read_text(encoding="utf-8"))


def read_status(root, run_id):
    return subprocess.run(
        [sys.executable, str(RUNNER), "status", run_id, "--run-root", str(root)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


@pytest.mark.parametrize(("exit_code", "status"), [(0, "passed"), (17, "failed")])
def test_detached_command_persists_log_and_exact_final_result(tmp_path, exit_code, status):
    run_id, started = start_run(
        tmp_path,
        sys.executable,
        "-c",
        "import sys,time; print('detached-output', flush=True); time.sleep(.1); sys.exit(int(sys.argv[1]))",
        str(exit_code),
    )
    assert started.stdout.find("Status: running") >= 0
    time.sleep(0.5)

    result = read_status(tmp_path, run_id)

    assert result.returncode == exit_code
    assert f"{status.upper()} (Exit-Code: {exit_code})" in result.stdout
    metadata = read_metadata(tmp_path, run_id)
    assert metadata["status"] == status
    assert metadata["final_result"]["exit_code"] == exit_code
    assert "detached-output" in (tmp_path / run_id / "stdout.log").read_text(encoding="utf-8")
    assert metadata["command"][-1] == str(exit_code)
    assert metadata["pid"] > 0
    assert metadata["process_start_identity"]
    assert metadata["created_at"] and metadata["started_at"] and metadata["finished_at"]
    assert "git_head" in metadata and "git_dirty" in metadata


def test_runner_passes_argv_without_shell_interpolation(tmp_path):
    literal = "value; touch /tmp/runner-should-not-evaluate"
    run_id, _started = start_run(
        tmp_path,
        sys.executable,
        "-c",
        "import sys; print(sys.argv[1])",
        literal,
    )
    time.sleep(0.3)

    result = read_status(tmp_path, run_id)

    assert result.returncode == 0
    assert literal in (tmp_path / run_id / "stdout.log").read_text(encoding="utf-8")
    metadata = read_metadata(tmp_path, run_id)
    assert metadata["command"][-1] == literal


def test_running_status_then_completion_requires_no_session_handle(tmp_path):
    run_id, _started = start_run(tmp_path, sys.executable, "-c", "import time; time.sleep(.6)")

    running = read_status(tmp_path, run_id)
    assert running.returncode == 3
    assert "RUNNING" in running.stdout

    time.sleep(0.8)
    completed = read_status(tmp_path, run_id)
    assert completed.returncode == 0
    assert "PASSED" in completed.stdout


def write_status_fixture(run_root: Path, run_id: str, metadata: dict) -> None:
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "status.json").write_text(json.dumps(metadata), encoding="utf-8")


def test_missing_and_invalid_status_never_report_pass(tmp_path):
    run_id = "20261125T120000Z-012345abcdef"
    missing = read_status(tmp_path, run_id)
    assert missing.returncode == 2
    assert "UNKNOWN" in missing.stdout

    write_status_fixture(
        tmp_path,
        run_id,
        {"schema_version": 1, "run_id": run_id, "status": "passed", "final_result": None},
    )
    invalid = read_status(tmp_path, run_id)
    assert invalid.returncode == 2
    assert "UNKNOWN" in invalid.stdout


def test_schema_version_boolean_is_not_accepted_as_version_one(tmp_path):
    run_id = "20261125T120002Z-012345abcdef"
    write_status_fixture(
        tmp_path,
        run_id,
        {
            "schema_version": True,
            "run_id": run_id,
            "status": "passed",
            "final_result": {"status": "passed", "exit_code": 0},
        },
    )

    result = read_status(tmp_path, run_id)

    assert result.returncode == 2
    assert "UNKNOWN" in result.stdout


def test_empty_explicit_command_errors_while_bare_start_keeps_default():
    action, _run_root, _cwd, command = RUNNER_MODULE.parse_options(["start"])
    assert action == "start"
    assert command == ["bash", str(PROJECT_ROOT / "scripts" / "test-local.sh")]

    result = subprocess.run(
        [sys.executable, str(RUNNER), "start", "--run-root", "/tmp", "--"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 2
    assert "muss mindestens ein Programm" in result.stderr


def test_launcher_failure_is_persisted_as_failed_exit_127(monkeypatch, tmp_path, capsys):
    def fail_to_spawn(*_args, **_kwargs):
        raise OSError("synthetic spawn failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(RUNNER_MODULE.subprocess, "Popen", fail_to_spawn)
        assert RUNNER_MODULE.start_run(str(tmp_path), str(PROJECT_ROOT), ["never-launched"]) == 127

    run_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    metadata = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["stage"] == "startup"
    assert metadata["final_result"]["exit_code"] == 127
    result = read_status(tmp_path, metadata["run_id"])
    assert result.returncode == 127
    assert "FAILED (Exit-Code: 127)" in result.stdout
    assert "synthetic spawn failure" in capsys.readouterr().err


def test_pid_reuse_or_stale_identity_is_interrupted(tmp_path):
    run_id = "20261125T120001Z-fedcba987654"
    write_status_fixture(
        tmp_path,
        run_id,
        {
            "schema_version": 1,
            "run_id": run_id,
            "status": "running",
            "pid": os.getpid(),
            "process_start_identity": "old-boot:12345",
            "system_boot_id": "old-boot",
            "final_result": None,
        },
    )

    result = read_status(tmp_path, run_id)

    assert result.returncode == 4
    assert "INTERRUPTED" in result.stdout
    assert read_metadata(tmp_path, run_id)["status"] == "interrupted"


def test_gone_worker_without_final_result_is_interrupted(tmp_path):
    run_id, _started = start_run(tmp_path, sys.executable, "-c", "import time; time.sleep(30)")
    metadata = read_metadata(tmp_path, run_id)

    os.killpg(metadata["pid"], signal.SIGKILL)
    result = read_status(tmp_path, run_id)

    assert result.returncode == 4
    assert "INTERRUPTED" in result.stdout
    assert read_metadata(tmp_path, run_id)["status"] == "interrupted"
