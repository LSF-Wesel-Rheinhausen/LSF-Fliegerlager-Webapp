from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPOSITORY_ROOT / ".github" / "workflows"


def workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_ci_separates_quality_python_and_browser_checks() -> None:
    ci = workflow("ci.yml")

    assert ci.startswith("name: CI\n")
    assert "name: Quality\n" in ci
    assert "name: Python tests\n" in ci
    assert "name: E2E (${{ matrix.browser }})\n" in ci
    assert "name: CI / Gate\n" in ci
    assert "python -m ruff check ." in ci
    assert "python -m ruff format --check ." in ci
    assert "python -m mypy src" in ci
    assert "python -m pytest" in ci


def test_ci_uses_version_matched_playwright_container_without_runtime_install() -> None:
    ci = workflow("ci.yml")

    assert (
        "mcr.microsoft.com/playwright:v1.61.1-noble"
        "@sha256:5b8f294aff9041b7191c34a4bab3ac270157a28774d4b0660e9743297b697e48"
    ) in ci
    assert 'EXPECTED_PLAYWRIGHT_VERSION: "1.61.1"' in ci
    assert "fail-fast: false" in ci
    assert "PLAYWRIGHT_PROJECT: ${{ matrix.browser }}" in ci
    assert 'npm run test:e2e -- --project="${PLAYWRIGHT_PROJECT}"' in ci
    assert "actions/upload-artifact@v7" in ci
    assert "npx playwright install" not in ci
    assert "actions/cache@" not in ci


def test_ci_skips_expensive_checks_for_docs_but_always_reports_the_gate() -> None:
    ci = workflow("ci.yml")

    assert "paths-ignore:" not in ci.split("permissions:", maxsplit=1)[0]
    assert "name: Detect relevant changes" in ci
    assert "needs: changes" in ci
    assert "if: needs.changes.outputs.run_ci == 'true'" in ci
    assert "RUN_CI: ${{ needs.changes.outputs.run_ci }}" in ci
    assert 'test "${QUALITY_RESULT}" = "skipped"' in ci


def test_docker_publish_waits_for_successful_current_main_ci() -> None:
    docker = workflow("docker.yml")

    assert 'workflows: ["CI"]' in docker
    assert "github.event.workflow_run.conclusion == 'success'" in docker
    assert "github.event.workflow_run.event == 'push'" in docker
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in docker
    assert "github.event.workflow_run.head_sha" in docker
    assert "git rev-parse origin/main" in docker
    assert docker.count("packages: write") == 1
    assert "scope=app" in docker
    assert "scope=updater" in docker


def test_docker_validates_relevant_pull_requests_without_publishing() -> None:
    docker = workflow("docker.yml")

    assert "pull_request:" in docker
    assert "if: github.event_name == 'pull_request'" in docker
    assert "name: Validate containers" in docker
    assert "name: Publish containers" in docker


def test_zap_is_read_only_report_only_and_waits_for_healthcheck() -> None:
    dast = workflow("dast.yml")

    assert "permissions:\n  contents: read\n" in dast
    assert "uses: actions/checkout@v7" in dast
    assert "allow_issue_writing: false" in dast
    assert "fail_action: false" in dast
    assert "issues: write" not in dast
    assert "actions: write" not in dast
    assert "for attempt in {1..30}" in dast
    assert "http://127.0.0.1:8000/healthz/" in dast
    assert "sleep 2" in dast
    assert "sleep 10" not in dast
    assert "docker logs lsf-webapp" in dast


def test_pull_request_title_check_does_not_run_for_new_commits() -> None:
    title_workflow = workflow("pr-title.yml")

    assert "- opened" in title_workflow
    assert "- edited" in title_workflow
    assert "- reopened" in title_workflow
    assert "- synchronize" not in title_workflow


def test_long_running_workflows_cancel_only_stale_pull_request_runs() -> None:
    expected_group = "group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.run_id }}"
    expected_cancellation = "cancel-in-progress: ${{ github.event_name == 'pull_request' }}"

    for name in ("ci.yml", "dast.yml", "security.yml", "changelog-check.yml"):
        contents = workflow(name)

        assert expected_group in contents
        assert expected_cancellation in contents


def test_workflow_jobs_define_bounded_timeouts() -> None:
    ci = workflow("ci.yml")
    assert ci.count("timeout-minutes: 10") == 1
    assert ci.count("timeout-minutes: 15") == 1
    assert ci.count("timeout-minutes: 20") == 1
    assert ci.count("timeout-minutes: 5") == 2

    docker = workflow("docker.yml")
    assert docker.count("timeout-minutes: 20") == 1
    assert docker.count("timeout-minutes: 45") == 1

    assert "timeout-minutes: 15" in workflow("dast.yml")
    assert "timeout-minutes: 10" in workflow("security.yml")
    assert "timeout-minutes: 5" in workflow("changelog-check.yml")
    assert "timeout-minutes: 5" in workflow("pr-title.yml")
