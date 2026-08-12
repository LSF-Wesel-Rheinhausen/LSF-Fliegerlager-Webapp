from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW_DIR = Path(__file__).parents[1] / ".github" / "workflows"
SHA = re.compile(r"^[0-9a-f]{40}$")
EXTERNAL_ACTION = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@([0-9a-f]{40})$")


def _workflow_documents() -> list[tuple[Path, dict[str, object]]]:
    return [
        (path, yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader))
        for path in sorted(WORKFLOW_DIR.glob("*.yml"))
    ]


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
    assert {path.name for path, _ in workflows} == {
        "changelog-check.yml",
        "ci.yml",
        "dast.yml",
        "docker.yml",
        "pr-title.yml",
        "security.yml",
    }

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


def test_dast_pr_job_has_no_write_permissions_and_trusted_job_is_separate() -> None:
    workflow = next(workflow for path, workflow in _workflow_documents() if path.name == "dast.yml")
    jobs = dict(workflow["jobs"])
    pr_job = dict(jobs["zap_scan_pr"])
    trusted_job = dict(jobs["zap_scan_trusted"])

    assert dict(pr_job["permissions"]) == {"contents": "read"}
    assert dict(trusted_job["permissions"]) == {"contents": "read", "issues": "write"}
    assert "actions" not in dict(pr_job["permissions"])
    assert "actions" not in dict(trusted_job["permissions"])
    assert "pull_request" in str(pr_job["if"])


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
