from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml"
SUPPORTED_BROWSERS = ["chromium", "firefox", "webkit"]


def _ci_workflow() -> dict[str, object]:
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _browser_matrix_job() -> dict[str, object]:
    jobs = dict(_ci_workflow()["jobs"])
    return dict(jobs["browser_matrix"])


def _change_scope_script() -> str:
    return dict(dict(_ci_workflow()["jobs"]["change-scope"])["steps"][-1])["run"]


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(["git", *arguments], cwd=repository, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _run_change_scope(repository: Path, base_sha: str, head_sha: str) -> str:
    output = repository / "github-output"
    output.write_text("", encoding="utf-8")
    environment = {
        **os.environ,
        "BASE_SHA": base_sha,
        "HEAD_SHA": head_sha,
        "GITHUB_OUTPUT": str(output),
    }
    subprocess.run(["bash", "-c", _change_scope_script()], cwd=repository, env=environment, check=True)
    return output.read_text(encoding="utf-8").strip()


def test_browser_matrix_runs_all_supported_playwright_projects() -> None:
    job = _browser_matrix_job()
    strategy = dict(job["strategy"])
    matrix = dict(strategy["matrix"])

    assert matrix["browser"] == SUPPORTED_BROWSERS
    assert strategy["fail-fast"] == "false"
    run_commands = [step["run"] for step in job["steps"] if isinstance(step, dict) and "run" in step]
    assert "npx playwright test --project=${{ matrix.browser }}" in run_commands


def test_browser_matrix_uses_digest_pinned_playwright_runtime_without_browser_caches() -> None:
    job = _browser_matrix_job()
    container = dict(job["container"])
    steps = [dict(step) for step in job["steps"]]
    run_commands = [step["run"] for step in steps if "run" in step]
    setup_python = next(step for step in steps if step.get("uses", "").startswith("actions/setup-python@"))
    step_names = [step.get("name") for step in steps]

    assert job["runs-on"] == "ubuntu-24.04"
    assert container["image"] == (
        "mcr.microsoft.com/playwright:v1.64.1-noble@sha256:"
        "2f05f8a734509a7b3f26a912639488ee08f58a7b292d14d62271bcff9038768f"
    )
    assert "python scripts/check_playwright_image.py" in run_commands
    assert "python -m pip install -r requirements-dev.txt" in run_commands
    assert "python -c 'import ssl; print(ssl.OPENSSL_VERSION)'" in run_commands
    assert step_names.index("Verify Python SSL support") < step_names.index("Install Python dependencies")
    assert "npm ci" in run_commands
    assert "cache" not in dict(setup_python.get("with", {}))
    assert not any("playwright install" in command for command in run_commands)
    assert not any("actions/cache@" in step.get("uses", "") for step in steps)


def test_playwright_image_version_guard_accepts_lock_match_and_rejects_mismatch(tmp_path: Path) -> None:
    repository = Path(__file__).parents[1]
    script = repository / "scripts" / "check_playwright_image.py"
    workflow = tmp_path / "ci.yml"
    lockfile = tmp_path / "package-lock.json"
    workflow.write_text(
        "jobs:\n  browser_matrix:\n    container:\n      image: mcr.microsoft.com/playwright:v1.64.1-noble@sha256:"
        "2f05f8a734509a7b3f26a912639488ee08f58a7b292d14d62271bcff9038768f\n",
        encoding="utf-8",
    )
    packages = {
        name: {"version": "1.64.1"}
        for name in (
            "node_modules/@playwright/test",
            "node_modules/playwright",
            "node_modules/playwright-core",
        )
    }
    lockfile.write_text(json.dumps({"packages": packages}), encoding="utf-8")

    match = subprocess.run(
        [sys.executable, str(script), "--workflow", str(workflow), "--lockfile", str(lockfile)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert match.returncode == 0
    assert "versions match" in match.stdout

    packages["node_modules/playwright-core"]["version"] = "1.64.0"
    lockfile.write_text(json.dumps({"packages": packages}), encoding="utf-8")
    mismatch = subprocess.run(
        [sys.executable, str(script), "--workflow", str(workflow), "--lockfile", str(lockfile)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert mismatch.returncode == 1
    assert "package-lock.json has node_modules/playwright-core=1.64.0" in mismatch.stderr


@pytest.mark.parametrize(
    ("workflow_text", "lock_packages", "diagnostic"),
    [
        (
            "# mcr.microsoft.com/playwright:v1.64.1-noble@sha256:"
            "2f05f8a734509a7b3f26a912639488ee08f58a7b292d14d62271bcff9038768f\n"
            "jobs:\n  other:\n    container:\n      image: mcr.microsoft.com/playwright:v1.64.1-noble@sha256:"
            "2f05f8a734509a7b3f26a912639488ee08f58a7b292d14d62271bcff9038768f\n",
            {
                name: {"version": "1.64.1"}
                for name in ("node_modules/@playwright/test", "node_modules/playwright", "node_modules/playwright-core")
            },
            "jobs.browser_matrix",
        ),
        (
            "jobs:\n  browser_matrix:\n    container:\n      image: mcr.microsoft.com/playwright:v1.64.1-noble\n"
            "  other:\n    container:\n      image: mcr.microsoft.com/playwright:v1.64.1-noble@sha256:"
            "2f05f8a734509a7b3f26a912639488ee08f58a7b292d14d62271bcff9038768f\n",
            {
                name: {"version": "1.64.1"}
                for name in ("node_modules/@playwright/test", "node_modules/playwright", "node_modules/playwright-core")
            },
            "official Playwright tag and sha256 digest",
        ),
        (
            "jobs:\n  browser_matrix:\n    container:\n      image: mcr.microsoft.com/playwright:v1.64.1-noble@sha256:"
            "2f05f8a734509a7b3f26a912639488ee08f58a7b292d14d62271bcff9038768f\n",
            {name: {"version": "1.64.1"} for name in ("node_modules/@playwright/test", "node_modules/playwright")},
            "node_modules/playwright-core=missing",
        ),
    ],
)
def test_playwright_image_guard_rejects_decoys_unpinned_image_and_missing_lock_entry(
    tmp_path: Path, workflow_text: str, lock_packages: dict[str, dict[str, str]], diagnostic: str
) -> None:
    repository = Path(__file__).parents[1]
    script = repository / "scripts" / "check_playwright_image.py"
    workflow = tmp_path / "ci.yml"
    lockfile = tmp_path / "package-lock.json"
    workflow.write_text(workflow_text, encoding="utf-8")
    lockfile.write_text(json.dumps({"packages": lock_packages}), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script), "--workflow", str(workflow), "--lockfile", str(lockfile)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert diagnostic in result.stderr


def test_browser_matrix_publishes_browser_specific_reports_and_results() -> None:
    job = _browser_matrix_job()
    artifact_steps = [
        step for step in job["steps"] if isinstance(step, dict) and "upload-artifact@" in step.get("uses", "")
    ]

    assert len(artifact_steps) == 2
    artifact_names = [dict(step["with"])["name"] for step in artifact_steps]
    artifact_paths = [dict(step["with"])["path"] for step in artifact_steps]
    assert all("${{ matrix.browser }}" in name for name in artifact_names)
    assert all("${{ github.run_id }}" in name for name in artifact_names)
    assert "playwright-report" in artifact_paths
    assert "test-results" in artifact_paths
    assert all(dict(step)["if"] == "${{ failure() || cancelled() }}" for step in artifact_steps)
    assert all(dict(step["with"])["retention-days"] == "7" for step in artifact_steps)
    assert 1 <= int(job["timeout-minutes"]) <= 45


def test_ci_runs_for_documentation_changes_without_path_filters() -> None:
    workflow = _ci_workflow()

    assert dict(workflow["on"]) == {
        "push": {"branches": ["main"]},
        "pull_request": {},
    }


def test_ci_has_diagnosable_jobs_and_stable_aggregate_gate() -> None:
    jobs = dict(_ci_workflow()["jobs"])

    assert {
        "quality",
        "python",
        "security-concurrency",
        "browser_matrix",
        "position-report-performance",
        "ci-gate",
    } <= set(jobs)
    gate = dict(jobs["ci-gate"])
    assert gate["name"] == "CI gate"
    assert gate["if"] == "${{ always() }}"
    assert set(gate["needs"]) == {
        "change-scope",
        "quality",
        "python",
        "security-concurrency",
        "browser_matrix",
        "position-report-performance",
    }
    assert "failure|cancelled|*) exit 1" in gate["steps"][0]["run"]


def test_position_report_benchmark_uses_sqlite_and_postgres_matrix_and_uploads_results() -> None:
    job = dict(_ci_workflow()["jobs"]["position-report-performance"])
    assert job["if"] == "${{ needs.change-scope.outputs.docs_only != 'true' }}"
    assert job["needs"] == "change-scope"
    assert dict(dict(job["strategy"])["matrix"])["database"] == ["sqlite", "postgresql"]
    assert dict(dict(job["services"])["postgres"])["image"] == "postgres:16"
    steps = [dict(step) for step in job["steps"]]
    commands = [step["run"] for step in steps if "run" in step]
    assert "pytest tests/test_position_report_performance.py -m position_report_performance -q" in commands
    upload = next(step for step in steps if step.get("name") == "Upload position report benchmark results")
    assert upload["if"] == "${{ always() }}"
    assert upload["uses"] == "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9"


def test_expensive_jobs_skip_only_when_scope_job_classifies_docs_or_graphify() -> None:
    jobs = dict(_ci_workflow()["jobs"])
    for job_name in (
        "quality",
        "python",
        "security-concurrency",
        "browser_matrix",
        "position-report-performance",
    ):
        assert dict(jobs[job_name])["if"] == "${{ needs.change-scope.outputs.docs_only != 'true' }}"
        assert dict(jobs[job_name])["needs"] == "change-scope"

    scope = dict(jobs["change-scope"])
    assert dict(scope["outputs"])["docs_only"] == "${{ steps.classify.outputs.docs_only }}"
    classify = dict(scope["steps"][-1])
    assert classify["id"] == "classify"
    assert "git diff --name-status" in classify["run"]
    assert "graphify-out/" in classify["run"]
    assert "changelog/" in classify["run"]
    assert "docs/" in classify["run"]
    assert "src/*" in classify["run"]
    assert "tests/*" in classify["run"]
    assert "scripts/*" in classify["run"]
    assert "Dockerfile*" in classify["run"]
    assert "requirements*" in classify["run"]
    assert "security/*" in classify["run"]
    assert "*)" in classify["run"]


def test_change_scope_classifies_deleted_and_renamed_technical_paths_as_full_ci() -> None:
    classify_run = dict(dict(_ci_workflow()["jobs"]["change-scope"])["steps"][-1])["run"]

    assert "git diff --name-status" in classify_run
    assert "--no-renames" in classify_run
    assert "--diff-filter=ACDMRTUXB" in classify_run
    assert "read -r -d '' status" in classify_run
    assert "status" in classify_run
    assert "path" in classify_run


def test_deleted_technical_path_and_technical_to_docs_rename_force_full_ci(tmp_path: Path) -> None:
    for scenario in ("deleted", "renamed"):
        repository = tmp_path / scenario
        repository.mkdir()
        _git(repository, "init", "-q")
        _git(repository, "config", "user.email", "test@example.invalid")
        _git(repository, "config", "user.name", "Workflow Test")
        (repository / "src").mkdir()
        (repository / "src" / "app.py").write_text("technical\n", encoding="utf-8")
        _git(repository, "add", "src/app.py")
        _git(repository, "commit", "-qm", "technical")
        base_sha = _git(repository, "rev-parse", "HEAD")
        if scenario == "deleted":
            (repository / "src" / "app.py").unlink()
            _git(repository, "commit", "-am", "delete")
        else:
            (repository / "docs").mkdir()
            _git(repository, "mv", "src/app.py", "docs/app.md")
            _git(repository, "commit", "-qm", "rename")
        head_sha = _git(repository, "rev-parse", "HEAD")

        assert _run_change_scope(repository, base_sha, head_sha) == "docs_only=false"


def test_initial_push_with_empty_or_zero_base_sha_forces_full_ci() -> None:
    classify_run = dict(dict(_ci_workflow()["jobs"]["change-scope"])["steps"][-1])["run"]

    classify_step = dict(dict(_ci_workflow()["jobs"]["change-scope"])["steps"][-1])
    assert dict(classify_step["env"])["BASE_SHA"] == "${{ github.event.pull_request.base.sha || github.event.before }}"
    assert 'base_sha=""' in classify_run
    assert 'base_sha="$(git rev-parse "$HEAD_SHA^"' not in classify_run
    assert "docs_only=false" in classify_run


def test_initial_push_does_not_classify_only_head_parent_as_docs_only(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Workflow Test")
    (tmp_path / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-qm", "baseline")
    (tmp_path / "README.md").write_text("docs\n", encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "docs")

    head_sha = _git(tmp_path, "rev-parse", "HEAD")

    assert _run_change_scope(tmp_path, "0" * 40, head_sha) == "docs_only=false"


def test_valid_base_sha_classifies_the_complete_multi_commit_range() -> None:
    classify_run = dict(dict(_ci_workflow()["jobs"]["change-scope"])["steps"][-1])["run"]

    assert "git diff --name-status" in classify_run
    assert '"$base_sha" "$HEAD_SHA"' in classify_run


def test_multi_commit_range_includes_technical_changes_before_doc_head(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Workflow Test")
    (tmp_path / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-qm", "baseline")
    base_sha = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('technical')\n", encoding="utf-8")
    _git(tmp_path, "add", "src/app.py")
    _git(tmp_path, "commit", "-qm", "technical")
    (tmp_path / "README.md").write_text("docs\n", encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "docs")
    head_sha = _git(tmp_path, "rev-parse", "HEAD")

    assert _run_change_scope(tmp_path, base_sha, head_sha) == "docs_only=false"


def test_ci_gate_accepts_skips_only_after_successful_docs_only_classification() -> None:
    gate = dict(_ci_workflow()["jobs"]["ci-gate"])
    gate_step = dict(gate["steps"][0])
    gate_run = gate_step["run"]

    assert dict(gate_step["env"])["DOCS_ONLY"] == "${{ needs.change-scope.outputs.docs_only }}"
    assert 'CHANGE_SCOPE_RESULT" != "success"' in gate_run
    assert 'allow_skipped="true"' not in gate_run
    assert "allow_skipped=true" in gate_run
    assert "failure|cancelled|*) exit 1" in gate_run


def test_ci_gate_rejects_failure_cancel_and_unexpected_skip_for_technical_changes() -> None:
    gate_run = dict(dict(_ci_workflow()["jobs"]["ci-gate"])["steps"][0])["run"]

    assert 'DOCS_ONLY" != "true"' in gate_run
    assert "success) ;;" in gate_run


@pytest.mark.parametrize(
    ("change_scope", "docs_only", "downstream", "expected_returncode"),
    [
        ("success", "true", "skipped", 0),
        ("success", "false", "skipped", 1),
        ("success", "false", "failure", 1),
        ("success", "false", "cancelled", 1),
        ("success", "false", "unexpected", 1),
        ("failure", "true", "skipped", 1),
    ],
)
def test_ci_gate_result_matrix_has_no_false_green_skips(
    change_scope: str, docs_only: str, downstream: str, expected_returncode: int
) -> None:
    gate_run = dict(dict(_ci_workflow()["jobs"]["ci-gate"])["steps"][0])["run"]
    environment = {
        **os.environ,
        "CHANGE_SCOPE_RESULT": change_scope,
        "DOCS_ONLY": docs_only,
        "QUALITY_RESULT": downstream,
        "PYTHON_RESULT": downstream,
        "SECURITY_RESULT": downstream,
        "BROWSER_RESULT": downstream,
        "POSITION_REPORT_PERFORMANCE_RESULT": downstream,
    }

    result = subprocess.run(["bash", "-c", gate_run], env=environment, check=False)

    assert result.returncode == expected_returncode


def test_isolated_graphify_graph_json_is_docs_only_before_generic_json_guard() -> None:
    classify_run = dict(dict(_ci_workflow()["jobs"]["change-scope"])["steps"][-1])["run"]

    graphify_pattern = "graphify-out/graph.json"
    generic_json_pattern = "*.json"
    assert graphify_pattern in classify_run
    assert classify_run.index(graphify_pattern) < classify_run.index(generic_json_pattern)


def test_graphify_change_mixed_with_technical_path_remains_full_ci() -> None:
    classify_run = dict(dict(_ci_workflow()["jobs"]["change-scope"])["steps"][-1])["run"]

    assert "graphify-out/graph.json" in classify_run
    assert "src/*" in classify_run
    assert "tests/*" in classify_run


def test_graphify_graph_json_is_safe_only_when_isolated(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Workflow Test")
    (tmp_path / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-qm", "baseline")
    base_sha = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", "graphify-out/graph.json")
    _git(tmp_path, "commit", "-qm", "graph")
    graph_head = _git(tmp_path, "rev-parse", "HEAD")

    assert _run_change_scope(tmp_path, base_sha, graph_head) == "docs_only=true"

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("technical\n", encoding="utf-8")
    _git(tmp_path, "add", "src/app.py")
    _git(tmp_path, "commit", "-qm", "technical")
    technical_head = _git(tmp_path, "rev-parse", "HEAD")

    assert _run_change_scope(tmp_path, base_sha, technical_head) == "docs_only=false"


def test_quality_runs_mypy_against_src() -> None:
    quality = dict(_ci_workflow()["jobs"]["quality"])
    run_commands = [step["run"] for step in quality["steps"] if isinstance(step, dict) and "run" in step]

    assert "mypy src" in run_commands


def test_all_ci_jobs_have_bounded_timeouts_and_read_only_permissions() -> None:
    workflow = _ci_workflow()
    jobs = dict(workflow["jobs"])

    for job_name in (
        "change-scope",
        "quality",
        "python",
        "security-concurrency",
        "browser_matrix",
        "position-report-performance",
        "ci-gate",
    ):
        job = dict(jobs[job_name])
        assert 1 <= int(job["timeout-minutes"]) <= 45
        assert dict(job["permissions"]) == {"contents": "read"}
