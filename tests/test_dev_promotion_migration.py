"""Regression coverage for the opt-in legacy dev pointer migration."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
APP = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp"
UPDATER = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp-updater"
OLD_APP = "sha256:81278d20e8dff6632a41ffd47513a0281e18daa4dbbbc0d068e0c0fd9ef1ce86"
OLD_UPDATER = "sha256:6d44ebe288f85954c36e3df08c7049302ff3a0c1181b2ce91188ebcd9e95de1a"
NEW_APP = "sha256:" + "3" * 64
NEW_UPDATER = "sha256:" + "4" * 64
REVISION = "a" * 40


@pytest.mark.parametrize(
    "failure",
    [
        "",
        "legacy-input-mismatch",
        "current-pointer-changed",
        "run-failed",
        "run-wrong-workflow",
        "run-wrong-event",
        "run-wrong-repository",
        "run-wrong-pr",
        "run-attempt-two",
        "pr-moved",
        "app-run-id-mismatch",
        "updater-run-id-mismatch",
        "app-missing-architecture",
        "app-platform-label-mismatch",
        "updater-revision-mismatch",
        "second-write",
    ],
)
def test_legacy_dev_migration_checks_sources_and_recovers_pair(tmp_path: Path, failure: str) -> None:
    state = {
        "tags": {f"{APP}:dev": OLD_APP, f"{UPDATER}:dev": OLD_UPDATER},
        "source_tags": {f"{APP}:dev-659-{REVISION}": NEW_APP, f"{UPDATER}:dev-659-{REVISION}": NEW_UPDATER},
        "source_runs": {NEW_APP: "123", NEW_UPDATER: "123"},
        "writes": [],
        "dev_inspects": {},
        "promotion_writes": 0,
        "failed_once": False,
    }
    if failure == "app-run-id-mismatch":
        state["source_runs"][NEW_APP] = "122"
    if failure == "updater-run-id-mismatch":
        state["source_runs"][NEW_UPDATER] = "122"
    state_path = tmp_path / "registry.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, sys
from pathlib import Path
path = Path(os.environ["FAKE_REGISTRY"])
state = json.loads(path.read_text(encoding="utf-8"))
args = sys.argv[1:]
app = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp"
updater = "ghcr.io/lsf-wesel-rheinhausen/lsf-fliegerlager-webapp-updater"
new_app, new_updater = "sha256:" + "3" * 64, "sha256:" + "4" * 64
failure = os.environ["FAILURE"]
def save(): path.write_text(json.dumps(state), encoding="utf-8")
if args[:3] == ["buildx", "imagetools", "inspect"]:
    ref = args[3]
    if ref.endswith(":dev"):
        count = state["dev_inspects"].get(ref, 0) + 1
        state["dev_inspects"][ref] = count
        digest = state["tags"].get(ref)
        if failure == "current-pointer-changed" and ref.startswith(app) and count >= 2:
            digest = "sha256:" + "9" * 64
        save()
    elif "@" in ref:
        digest = ref.split("@", 1)[1]
    else:
        digest = state["source_tags"].get(ref)
    if digest is None:
        print("404 Not Found", file=sys.stderr); sys.exit(1)
    if "--raw" in args:
        if digest in {new_app, new_updater}:
            if failure == "app-missing-architecture" and digest == new_app:
                manifests = [{"platform":{"os":"linux","architecture":"amd64"},"digest":"sha256:"+"1"*64}]
            else:
                manifests = [
                    {"platform":{"os":"linux","architecture":"amd64"},"digest":"sha256:"+"1"*64},
                    {"platform":{"os":"linux","architecture":"arm64"},"digest":"sha256:"+"2"*64},
                ]
            print(json.dumps({"annotations":{"io.lsf-fliegerlager.test-workflow-run-id":state["source_runs"].get(digest)},"manifests":manifests}))
        else:
            print(json.dumps({"annotations":{},"manifests":[]}))
    elif "--format" in args:
        print(digest)
elif args[:2] == ["pull", "--platform"]:
    sys.exit(0)
elif args[:2] == ["image", "inspect"]:
    if "{{.Os}}/{{.Architecture}}" in args:
        architecture = "amd64" if args[2].endswith("1" * 64) else "arm64"
        if failure == "app-platform-label-mismatch" and args[2].startswith(app + "@"):
            architecture = "arm64"
        print("linux/" + architecture)
    elif failure == "updater-revision-mismatch" and args[2].startswith(updater + "@"):
        print("b" * 40)
    else:
        print(os.environ["REVISION"])
elif args[:3] == ["buildx", "imagetools", "create"]:
    tag = args[args.index("--tag") + 1]
    digest = args[-1].split("@", 1)[1]
    state["promotion_writes"] += 1
    state["writes"].append([tag, digest])
    state["tags"][tag] = digest
    save()
    if (
        failure == "second-write"
        and state["promotion_writes"] == 2
        and digest == new_updater
        and not state["failed_once"]
    ):
        state["failed_once"] = True; save(); sys.exit(1)
else:
    sys.exit(2)
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    gh = tmp_path / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, sys
failure = os.environ["FAILURE"]
path = sys.argv[-1]
run = {
    "workflow_id": 281374633,
    "path": ".github/workflows/ci.yml",
    "status": "completed",
    "conclusion": "success",
    "event": "pull_request",
    "run_attempt": 1,
    "head_repository": {"full_name": "LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp"},
    "head_sha": os.environ["REVISION"],
    "pull_requests": [{"number": 659}],
}
if failure == "run-failed": run["conclusion"] = "failure"
if failure == "run-wrong-workflow": run["workflow_id"] = 9
if failure == "run-wrong-event": run["event"] = "push"
if failure == "run-wrong-repository": run["head_repository"]["full_name"] = "fork/repo"
if failure == "run-wrong-pr": run["pull_requests"] = []
if failure == "run-attempt-two": run["run_attempt"] = 2
if "/actions/runs/" in path:
    print(json.dumps(run))
else:
    sha = "b" * 40 if failure == "pr-moved" else os.environ["REVISION"]
    print(json.dumps({"state":"open","head":{"repo":{"full_name":"LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp"},"sha":sha}}))
""",
        encoding="utf-8",
    )
    gh.chmod(0o755)

    expected_app = "sha256:" + "0" * 64 if failure == "legacy-input-mismatch" else OLD_APP
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/migrate-legacy-dev-pointers.sh")],
        capture_output=True,
        text=True,
        timeout=10,
        env={
            **os.environ,
            "GITHUB_REPOSITORY": "LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp",
            "GITHUB_REF": "refs/heads/main",
            "GH_TOKEN": "test-token",
            "PR_NUMBER": "659",
            "TEST_RUN_ID": "123",
            "EXPECTED_LEGACY_APP_DIGEST": expected_app,
            "EXPECTED_LEGACY_UPDATER_DIGEST": OLD_UPDATER,
            "REVISION": REVISION,
            "FAKE_REGISTRY": str(state_path),
            "FAILURE": failure,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
        },
    )
    final = json.loads(state_path.read_text(encoding="utf-8"))
    if failure == "":
        assert result.returncode == 0, result.stderr
        assert final["tags"][f"{APP}:dev"] == NEW_APP
        assert final["tags"][f"{UPDATER}:dev"] == NEW_UPDATER
        assert len(final["writes"]) == 2
    else:
        assert result.returncode == 1, result.stderr
        assert final["tags"][f"{APP}:dev"] == OLD_APP
        assert final["tags"][f"{UPDATER}:dev"] == OLD_UPDATER
        if failure == "second-write":
            assert len(final["writes"]) == 4
        else:
            assert final["writes"] == []
