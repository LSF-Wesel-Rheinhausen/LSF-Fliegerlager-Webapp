from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml"
SUPPORTED_BROWSERS = ["chromium", "firefox", "webkit"]


def _ci_workflow() -> dict[str, object]:
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _browser_matrix_job() -> dict[str, object]:
    jobs = dict(_ci_workflow()["jobs"])
    return dict(jobs["browser_matrix"])


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


def test_browser_ui_tests_gate_aggregates_the_browser_matrix() -> None:
    jobs = dict(_ci_workflow()["jobs"])
    gate = dict(jobs["browser-gate"])

    assert gate["name"] == "Browser UI tests"
    assert gate["needs"] == "browser_matrix"
    assert gate["if"] == "${{ always() }}"
    gate_step = dict(gate["steps"][0])
    assert dict(gate_step["env"])["MATRIX_RESULT"] == "${{ needs.browser_matrix.result }}"
    assert gate_step["run"] == 'test "$MATRIX_RESULT" = success'
