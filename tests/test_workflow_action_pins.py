from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW_DIR = Path(__file__).parents[1] / ".github" / "workflows"
SHA = re.compile(r"^[0-9a-f]{40}$")
EXTERNAL_ACTION = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@([0-9a-f]{40})$")


def _workflow_paths(workflow_dir: Path = WORKFLOW_DIR) -> list[Path]:
    return sorted(path for path in workflow_dir.rglob("*") if path.is_file() and path.suffix in {".yml", ".yaml"})


def _workflow_documents(workflow_dir: Path = WORKFLOW_DIR) -> list[tuple[Path, dict[str, object]]]:
    return [
        (path, yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader))
        for path in _workflow_paths(workflow_dir)
    ]


def _docker_workflow() -> dict[str, object]:
    return next(workflow for path, workflow in _workflow_documents() if path.name == "docker.yml")


def _uses_values(value: object) -> list[str]:
    if isinstance(value, dict):
        values: list[str] = []
        for key, nested in value.items():
            if key == "uses" and isinstance(nested, str):
                values.append(nested)
            values.extend(_uses_values(nested))
        return values
    if isinstance(value, list):
        return [item for nested in value for item in _uses_values(nested)]
    return []


def _assert_external_action_is_pinned(reference: str) -> None:
    if reference.startswith("./"):
        return
    match = EXTERNAL_ACTION.fullmatch(reference)
    assert match, f"invalid external action reference: {reference!r}"
    assert SHA.fullmatch(match.group(1)), f"action is not pinned to a full SHA: {reference!r}"


def test_all_external_workflow_actions_are_pinned_to_lowercase_full_shas() -> None:
    workflows = _workflow_documents()
    assert workflows

    for _path, workflow in workflows:
        for reference in _uses_values(workflow):
            _assert_external_action_is_pinned(reference)


@pytest.mark.parametrize(
    "reference",
    [
        "actions/checkout@v4",
        "actions/checkout@main",
        "actions/checkout@${{ github.ref }}",
        "actions/checkout@0123456789abcdef",
        "https://github.com/actions/checkout@v4",
        "actions/checkout owner@0123456789abcdef0123456789abcdef01234567",
        "actions//checkout@0123456789abcdef0123456789abcdef01234567",
        "actions/checkout/extra@0123456789abcdef0123456789abcdef01234567",
        "actions/checkout?@0123456789abcdef0123456789abcdef01234567",
        "actions/checkout@0123456789abcdef0123456789abcdef0123456!",
    ],
)
def test_action_pin_validator_rejects_tags_branches_expressions_short_shas_and_urls(reference: str) -> None:
    with pytest.raises(AssertionError):
        _assert_external_action_is_pinned(reference)


def test_docker_permissions_are_job_scoped_and_publish_waits_for_tests() -> None:
    workflow = dict(_workflow_documents()[3][1])
    assert "packages" not in dict(workflow.get("permissions", {}))

    jobs = dict(workflow["jobs"])
    test_job = dict(jobs["docker-test"])
    publish_job = dict(jobs["docker-publish"])
    assert dict(test_job["permissions"]) == {"contents": "read"}
    assert dict(publish_job["permissions"]) == {"contents": "read", "packages": "write"}
    assert publish_job["needs"] == "docker-test"
    assert "workflow_run.conclusion == 'success'" in publish_job["if"]


def test_dast_pr_job_has_no_write_permissions_and_trusted_job_is_separate() -> None:
    workflow = next(workflow for path, workflow in _workflow_documents() if path.name == "dast.yml")
    jobs = dict(workflow["jobs"])
    pr_job = dict(jobs["zap_scan_pr"])
    trusted_job = dict(jobs["zap_scan_trusted"])

    assert dict(pr_job["permissions"]) == {"contents": "read"}
    assert dict(trusted_job["permissions"]) == {"contents": "read", "issues": "write"}
    assert dict(pr_job["steps"][-1]["with"])["allow_issue_writing"] == "false"
    assert dict(trusted_job["steps"][-1]["with"])["allow_issue_writing"] == "true"
    assert "actions" not in dict(pr_job["permissions"])
    assert "actions" not in dict(trusted_job["permissions"])
    assert "pull_request" in str(pr_job["if"])


def test_workflow_discovery_includes_nested_yml_and_yaml_files(tmp_path: Path) -> None:
    nested_workflow_dir = tmp_path / "nested"
    nested_workflow_dir.mkdir()
    (tmp_path / "root.yml").write_text("name: root\n", encoding="utf-8")
    (nested_workflow_dir / "new-workflow.yaml").write_text("name: yaml\n", encoding="utf-8")

    assert _workflow_paths(tmp_path) == sorted([tmp_path / "root.yml", nested_workflow_dir / "new-workflow.yaml"])


def test_pull_request_target_semantic_action_has_no_checkout_or_run_step() -> None:
    workflow = next(workflow for path, workflow in _workflow_documents() if path.name == "pr-title.yml")
    job = dict(dict(workflow["jobs"])["main"])
    assert dict(workflow["permissions"]) == {"pull-requests": "read"}
    steps = list(job["steps"])
    assert _uses_values(job) == ["amannn/action-semantic-pull-request@48f256284bd46cdaab1048c3721360e808335d50"]
    assert len(steps) == 1
    for step in steps:
        assert "run" not in step
        assert "checkout" not in step.get("uses", "")
        assert step["uses"] == _uses_values(job)[0]


def test_docker_builds_pull_requests_and_main_without_publishing() -> None:
    workflow = _docker_workflow()
    events = dict(workflow["on"])
    jobs = dict(workflow["jobs"])
    docker_test = dict(jobs["docker-test"])
    publish = dict(jobs["docker-publish"])

    assert "pull_request" in events
    assert "push" not in events
    assert "workflow_run" in events
    assert "pull_request" in docker_test["if"]
    assert "workflow_run" in docker_test["if"]
    assert "workflow_run.conclusion == 'success'" in docker_test["if"]
    assert "push: true" not in "\n".join(str(step) for step in docker_test["steps"])
    assert "workflow_run" in publish["if"]
    assert "pull_request" not in publish["if"]
    assert publish["needs"] == "docker-test"
    test_builds = [step for step in docker_test["steps"] if "build-push-action@" in str(step)]
    assert len(test_builds) == 2
    assert all(dict(step["with"])["load"] == "true" for step in test_builds)
    assert "Test application image" in [dict(step)["name"] for step in docker_test["steps"]]
    assert "Test updater image" in [dict(step)["name"] for step in docker_test["steps"]]


def test_docker_publish_is_bound_to_successful_trusted_main_sha_and_checks_race() -> None:
    workflow = _docker_workflow()
    publish = dict(dict(workflow["jobs"])["docker-publish"])
    steps = list(publish["steps"])
    checkout = dict(steps[0])
    checkout_with = dict(checkout["with"])
    verify = next(step for step in steps if dict(step).get("name") == "Verify main has not moved")
    publish_text = "\n".join(str(step) for step in steps if "build-push-action@" in str(step))

    assert checkout_with["ref"] == "${{ github.event.workflow_run.head_sha }}"
    assert "workflow_run.conclusion == 'success'" in publish["if"]
    assert "workflow_run.event == 'push'" in publish["if"]
    assert "workflow_run.head_branch == 'main'" in publish["if"]
    assert "workflow_run.head_repository.full_name == github.repository" in publish["if"]
    assert "needs.docker-test.result == 'success'" in publish["if"]
    assert "git ls-remote" in verify["run"]
    assert "refs/heads/main" in verify["run"]
    assert sum("git ls-remote" in dict(step).get("run", "") for step in steps) == 3
    assert "workflow_run.head_sha" in publish_text
    assert "github.sha" not in publish_text


def test_docker_test_and_publish_share_the_exact_sha_for_pr_and_workflow_run() -> None:
    jobs = dict(_docker_workflow()["jobs"])
    docker_test = dict(jobs["docker-test"])
    checkout = dict(docker_test["steps"][0])
    application_build = next(
        step for step in docker_test["steps"] if "Build application image" in dict(step).get("name", "")
    )
    build_args = dict(application_build["with"])["build-args"]
    expected_sha = "${{ github.event_name == 'workflow_run' && github.event.workflow_run.head_sha || github.sha }}"

    assert dict(checkout["with"])["ref"] == expected_sha
    assert f"APP_REVISION={expected_sha}" in build_args


def test_docker_publish_permissions_and_cache_scopes_are_isolated_and_bounded() -> None:
    jobs = dict(_docker_workflow()["jobs"])
    docker_test = dict(jobs["docker-test"])
    publish = dict(jobs["docker-publish"])

    assert dict(docker_test["permissions"]) == {"contents": "read"}
    assert dict(publish["permissions"]) == {"contents": "read", "packages": "write"}
    assert "secrets" not in str(docker_test)
    assert "scope=app" in str(docker_test)
    assert "scope=updater" in str(docker_test)
    assert "scope=app" in str(publish)
    assert "scope=updater" in str(publish)
    assert 1 <= int(docker_test["timeout-minutes"]) <= 60
    assert 1 <= int(publish["timeout-minutes"]) <= 60
