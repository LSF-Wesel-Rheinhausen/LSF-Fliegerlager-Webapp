from __future__ import annotations

import os
import subprocess
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

    assert {"quality", "python", "security-concurrency", "browser_matrix", "ci-gate"} <= set(jobs)
    gate = dict(jobs["ci-gate"])
    assert gate["name"] == "CI gate"
    assert gate["if"] == "${{ always() }}"
    assert set(gate["needs"]) == {"change-scope", "quality", "python", "security-concurrency", "browser_matrix"}
    assert "failure|cancelled|*) exit 1" in gate["steps"][0]["run"]


def test_expensive_jobs_skip_only_when_scope_job_classifies_docs_or_graphify() -> None:
    jobs = dict(_ci_workflow()["jobs"])
    for job_name in ("quality", "python", "security-concurrency", "browser_matrix"):
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

    for job_name in ("change-scope", "quality", "python", "security-concurrency", "browser_matrix", "ci-gate"):
        job = dict(jobs[job_name])
        assert 1 <= int(job["timeout-minutes"]) <= 45
        assert dict(job["permissions"]) == {"contents": "read"}
