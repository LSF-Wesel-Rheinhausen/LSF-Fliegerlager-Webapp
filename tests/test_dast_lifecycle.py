from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "dast-lifecycle.sh"


def _run_lifecycle(
    tmp_path: Path, command: str, docker_script: str, curl_script: str = "exit 0"
) -> subprocess.CompletedProcess[str]:
    assert SCRIPT.exists(), "DAST lifecycle helper must be checked in"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "docker").write_text(docker_script, encoding="utf-8")
    (bin_dir / "curl").write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{curl_script}\n", encoding="utf-8")
    (bin_dir / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    for executable in ("docker", "curl", "sleep"):
        (bin_dir / executable).chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DAST_STATE_FILE": str(tmp_path / "state"),
        "DAST_HEALTH_TIMEOUT_SECONDS": "2",
        "DAST_HEALTH_POLL_SECONDS": "0",
    }
    return subprocess.run(["bash", str(SCRIPT), command], env=environment, text=True, capture_output=True, check=False)


def test_lifecycle_polls_health_and_cleans_container(tmp_path: Path) -> None:
    docker = """
case "$1" in
  run) echo container-id ;;
  inspect) exit 0 ;;
  rm) echo removed >> "$DAST_LOG" ;;
esac
"""
    log = tmp_path / "docker.log"
    os.environ["DAST_LOG"] = str(log)
    try:
        started = _run_lifecycle(tmp_path, "start", docker)
        assert started.returncode == 0
        healthy = _run_lifecycle(
            tmp_path,
            "wait",
            docker,
            """
count_file="$DAST_STATE_FILE.count"
count=$(cat "$count_file" 2>/dev/null || echo 0)
count=$((count + 1))
echo "$count" > "$count_file"
test "$count" -ge 2
""",
        )
        assert healthy.returncode == 0
        cleaned = _run_lifecycle(tmp_path, "cleanup", docker)
        assert cleaned.returncode == 0
        assert "removed" in log.read_text(encoding="utf-8")
    finally:
        os.environ.pop("DAST_LOG", None)


def test_lifecycle_health_timeout_is_nonzero(tmp_path: Path) -> None:
    (tmp_path / "state").write_text("lsf-webapp\n", encoding="utf-8")
    result = _run_lifecycle(tmp_path, "wait", "exit 0", "exit 1")

    assert result.returncode != 0
    assert "timed out" in result.stderr


def test_lifecycle_start_failure_is_nonzero(tmp_path: Path) -> None:
    result = _run_lifecycle(tmp_path, "start", 'if [ "$1" = run ]; then exit 42; fi')

    assert result.returncode != 0


def test_lifecycle_cleanup_failure_is_nonzero(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.write_text("lsf-webapp\n", encoding="utf-8")
    result = _run_lifecycle(tmp_path, "cleanup", 'if [ "$1" = inspect ]; then exit 0; fi; exit 42')

    assert result.returncode != 0
